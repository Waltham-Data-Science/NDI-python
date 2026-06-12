"""Real-export validation for the Kilosort import pipeline (PR12).

The PR12 unit tests (tests/test_pr12_kilosort.py) exercise the importer against
hand-built SYNTHETIC Phy output. This module validates it against a REAL
Kilosort2.5 / Phy export so the parsers are checked against genuine on-disk
formats: uint64 ``spike_times``, uint32 ``spike_clusters``/``spike_templates``,
float32 ``templates``, a ``cluster_group.tsv`` whose column header is
``KSLabel`` (not ``group``), and the whitening-matrix un-whitening of templates.

The sample is ``phy/phy_example_0`` from NeuralEnsemble/ephy_testing_data
(32 channels, ~10 s, 788 spikes, 13 clusters; CC-licensed). It is NOT vendored
into the repo; point ``NDI_KILOSORT_REAL_DIR`` at a directory containing at
least these files and the test runs, otherwise it skips:

    spike_times.npy  spike_clusters.npy  spike_templates.npy  amplitudes.npy
    templates.npy    whitening_mat_inv.npy  cluster_group.tsv

Fetch (no auth needed)::

    base=https://gin.g-node.org/NeuralEnsemble/ephy_testing_data/raw/master/phy/phy_example_0
    mkdir -p ~/.cache/ndi/ks_phy_example_0 && cd ~/.cache/ndi/ks_phy_example_0
    for f in spike_times spike_clusters spike_templates amplitudes templates \
             whitening_mat_inv; do curl -sSLO $base/$f.npy; done
    curl -sSLO $base/cluster_group.tsv
    export NDI_KILOSORT_REAL_DIR=~/.cache/ndi/ks_phy_example_0
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from ndi.fun.probe.import_ import kilosort
from ndi.time.clocktype import ndi_time_clocktype as CT

_REAL_DIR = os.environ.get("NDI_KILOSORT_REAL_DIR", "")
_REQUIRED = [
    "spike_times.npy",
    "spike_clusters.npy",
    "spike_templates.npy",
    "amplitudes.npy",
    "templates.npy",
    "whitening_mat_inv.npy",
    "cluster_group.tsv",
]


def _have_real_data() -> bool:
    if not _REAL_DIR:
        return False
    d = Path(_REAL_DIR)
    return all((d / f).is_file() for f in _REQUIRED)


pytestmark = pytest.mark.skipif(
    not _have_real_data(),
    reason="set NDI_KILOSORT_REAL_DIR to a real Phy/Kilosort export (see module docstring)",
)

SR = 32000.0
N_SAMPLES = 320000  # one epoch covering the ~10 s recording (max spike sample 319953)


class _FakeProbe:
    """A probe-like element with one epoch sized to the real recording."""

    def __init__(self, session, name="ks_probe", reference=1):
        from ndi.element import ndi_element

        self._elem = ndi_element(
            session=session,
            name=name,
            reference=reference,
            type="n-trode",
            direct=False,
            subject_id="subj_ks",
        )
        session.database_add(self._elem.newdocument())
        self._name, self._reference = name, reference

    @property
    def id(self):
        return self._elem.id

    @property
    def name(self):
        return self._name

    @property
    def reference(self):
        return self._reference

    @property
    def subject_id(self):
        return self._elem.subject_id

    def elementstring(self):
        return f"{self._name} | {self._reference}"

    def epochtable(self, force_rebuild=False):
        et = [
            {
                "epoch_id": "ep0",
                "epoch_clock": [CT.DEV_LOCAL_TIME],
                "t0_t1": [[0.0, (N_SAMPLES - 1) / SR]],
            }
        ]
        return et, "hash"

    def samplerate(self, epoch):
        return SR

    def times2samples(self, epoch, times):
        return np.round(np.asarray(times) * SR).astype(int)

    def samples2times(self, epoch, samples):
        return np.asarray(samples, dtype=float) / SR


@pytest.fixture
def kdir():
    return Path(_REAL_DIR)


def test_labels_parses_real_cluster_group(kdir):
    # Real cluster_group.tsv header is 'KSLabel', not 'group'; 13 clusters, 3 good.
    ids, labs = kilosort.labels(kdir)
    assert ids == list(range(13))
    assert sum(1 for x in labs if x == "good") == 3
    assert [i for i, x in zip(ids, labs) if x == "good"] == [9, 10, 11]


def test_waveformdata_real_dtypes(kdir):
    templates, spike_templates, amplitudes, winv = kilosort.waveformdata(kdir)
    assert templates.shape == (13, 82, 32)  # nTemplates x nSamples x nChannels (float32 on disk)
    assert winv is not None and winv.shape == (32, 32)
    assert spike_templates.shape == (788,)
    assert amplitudes.shape == (788,)


def test_meanwaveform_unwhitens_real_template(kdir):
    ids, labs = kilosort.labels(kdir)
    templates, spike_templates, amplitudes, winv = kilosort.waveformdata(kdir)
    sc = np.load(kdir / "spike_clusters.npy").astype(np.float64).ravel()
    mw = kilosort.meanwaveform(9, sc, spike_templates, amplitudes, templates, winv)
    mw = np.asarray(mw)
    assert mw.shape == (82, 32)
    assert np.all(np.isfinite(mw)) and np.any(mw != 0)


def _build_session(tmp_path):
    from ndi.session.dir import ndi_session_dir

    sess = ndi_session_dir("T", tmp_path)
    prb = _FakeProbe(sess)
    elestr = prb.elementstring().replace(" ", "_")
    out = tmp_path / "kilosort" / elestr / "kilosort_output"
    out.mkdir(parents=True, exist_ok=True)
    for f in Path(_REAL_DIR).glob("*"):
        if f.is_file():
            (out / f.name).write_bytes(f.read_bytes())
    return sess, prb


def test_getInfo_real_summary(tmp_path):
    sess, prb = _build_session(tmp_path)
    info, _ = kilosort.getInfo(sess, prb)
    assert info["num_clusters"] == 13
    assert info["num_spikes_total"] == 788
    assert info["num_channels"] == 32
    assert info["samples_per_template"] == 82
    assert info["num_would_import"] == 13  # all good/mua, no noise


def test_probe_import_creates_13_neurons(tmp_path):
    from ndi.query import ndi_query

    sess, prb = _build_session(tmp_path)

    kilosort.probe(sess, prb, dryRun=True, verbose=False)
    assert sess.database_search(ndi_query("").isa("neuron_extracellular")) == []

    kilosort.probe(sess, prb, verbose=False)
    kc = sess.database_search(ndi_query("").isa("kilosort_clusters"))
    ne = sess.database_search(ndi_query("").isa("neuron_extracellular"))
    assert len(kc) == 1
    assert len(ne) == 13
    idxs = sorted(d.document_properties["neuron_extracellular"]["cluster_index"] for d in ne)
    assert idxs == list(range(13))
    for d in ne:
        mw = np.asarray(d.document_properties["neuron_extracellular"]["mean_waveform"])
        assert mw.shape == (82, 32)

    # idempotent re-import (removeold + re-add) keeps exactly 13
    kilosort.probe(sess, prb, force=True, verbose=False)
    assert len(sess.database_search(ndi_query("").isa("neuron_extracellular"))) == 13


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
