"""PR12 — NDI Kilosort import pipeline (MATLAB -> Python port).

Faithful port of +ndi/+fun/+probe/+import/+kilosort/{session,probe,getInfo,labels,
waveformdata,meanwaveform,removeold}.m plus +ndi/+fun/+probe/{extracellularInfo,
plotProbeGeometry}.m.

No real Kilosort data is available, so these tests build SYNTHETIC tiny Kilosort
output with hand-computed expected results and exercise:
  * .npy / .tsv parsing (labels, waveformdata)
  * cluster grouping + the quality_labels/quality_values curation filter
  * the amplitude-weighted mean-waveform math (meanwaveform)
  * getInfo's on-disk summary
  * the global->local 0-based sample mapping and epoch splitting in probe()
  * extracellularInfo's database-side view
  * removeold idempotency
  * plotProbeGeometry's deferred-matplotlib contract

The full probe() import runs against a REAL ndi_session_dir (the same infra
test_addmultiple.py uses) with a lightweight FakeProbe that supplies a
deterministic epochtable / samplerate / times2samples / samples2times. Tests
that need that infra skip cleanly if it is unavailable.

NAMING DIVERGENCE under test: the MATLAB package +ndi/+fun/+probe/+import/+kilosort
is reachable in Python as ndi.fun.probe.import_.kilosort (`import` is reserved).
"""

from __future__ import annotations

import numpy as np
import pytest

from ndi.fun.probe.import_ import kilosort
from ndi.time.clocktype import ndi_time_clocktype as CT

# ---------------------------------------------------------------------------
# Synthetic Kilosort fixture
# ---------------------------------------------------------------------------

# Sample rate and epoch layout (hand-chosen so the math is checkable):
#   sample_rate = 10 Hz
#   epoch 0: 100 samples (global 0..99)   -> bounds0 = [0, 100, 200]
#   epoch 1: 100 samples (global 100..199)
SR = 10.0
EPOCH0_COUNT = 100
EPOCH1_COUNT = 100

# Cluster layout: 3 curated clusters.
#   cluster 0 -> "good",  spikes at global samples [5, 105]
#   cluster 1 -> "mua",   spikes at global samples [50]
#   cluster 2 -> "noise", spikes at global samples [10, 110, 195]
# spike_clusters / spike_times are 0-based, in spike order.
_SPIKE_TIMES = np.array([5, 10, 50, 105, 110, 195], dtype=np.int64)
_SPIKE_CLUSTERS = np.array([0, 2, 1, 0, 2, 2], dtype=np.int64)
# template id (0-based) of each spike; templates 0 and 1.
_SPIKE_TEMPLATES = np.array([0, 1, 0, 0, 1, 1], dtype=np.int64)
_AMPLITUDES = np.array([10.0, 1.0, 5.0, 30.0, 2.0, 3.0], dtype=np.float64)

# 2 templates x 4 samples x 2 channels.
_TEMPLATES = np.zeros((2, 4, 2), dtype=np.float64)
# template 0: clear trough (min) at sample 1 on channel 0
_TEMPLATES[0, :, 0] = [0.0, -4.0, -1.0, 0.0]
_TEMPLATES[0, :, 1] = [0.0, -1.0, 0.0, 0.0]
# template 1: trough at sample 2 on channel 1
_TEMPLATES[1, :, 0] = [0.0, 0.0, -1.0, 0.0]
_TEMPLATES[1, :, 1] = [0.0, -1.0, -2.0, 0.0]


def _write_fixture(kdir, *, group_file="cluster_group.tsv"):
    """Write the synthetic Kilosort/Phy output into directory *kdir*."""
    kdir.mkdir(parents=True, exist_ok=True)
    np.save(kdir / "spike_times.npy", _SPIKE_TIMES)
    np.save(kdir / "spike_clusters.npy", _SPIKE_CLUSTERS)
    np.save(kdir / "spike_templates.npy", _SPIKE_TEMPLATES)
    np.save(kdir / "amplitudes.npy", _AMPLITUDES)
    np.save(kdir / "templates.npy", _TEMPLATES)
    # curation labels
    lines = ["cluster_id\tgroup", "0\tgood", "1\tmua", "2\tnoise"]
    (kdir / group_file).write_text("\n".join(lines) + "\n")


def _kilosort_dir(session_path, probe):
    """The on-disk kilosort dir for *probe* under *session_path*, matching the
    importer's layout: spaces in elementstring() -> underscores (only spaces)."""
    elestr = probe.elementstring().replace(" ", "_")
    return session_path / "kilosort" / elestr / "kilosort_output"


@pytest.fixture
def kdir(tmp_path):
    d = tmp_path / "kilosort" / "probe_1" / "kilosort_output"
    _write_fixture(d)
    return d


# ---------------------------------------------------------------------------
# labels()  (cluster_group.tsv / cluster_KSLabel.tsv / cluster_info.tsv)
# ---------------------------------------------------------------------------


class TestLabels:
    def test_reads_cluster_group(self, kdir):
        ids, labs = kilosort.labels(kdir)
        assert ids == [0, 1, 2]
        assert labs == ["good", "mua", "noise"]

    def test_prefers_cluster_group_over_kslabel(self, tmp_path):
        d = tmp_path / "ks"
        d.mkdir()
        # KSLabel says noise, group (preferred) says good
        (d / "cluster_KSLabel.tsv").write_text("cluster_id\tKSLabel\n0\tnoise\n")
        (d / "cluster_group.tsv").write_text("cluster_id\tgroup\n0\tgood\n")
        ids, labs = kilosort.labels(d)
        assert ids == [0] and labs == ["good"]

    def test_falls_back_to_kslabel(self, tmp_path):
        d = tmp_path / "ks"
        d.mkdir()
        (d / "cluster_KSLabel.tsv").write_text("cluster_id\tKSLabel\n7\tmua\n")
        ids, labs = kilosort.labels(d)
        assert ids == [7] and labs == ["mua"]

    def test_id_column_alias(self, tmp_path):
        d = tmp_path / "ks"
        d.mkdir()
        # some Phy versions name the id column 'id'
        (d / "cluster_group.tsv").write_text("id\tgroup\n3\tgood\n")
        ids, labs = kilosort.labels(d)
        assert ids == [3] and labs == ["good"]

    def test_missing_raises(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        with pytest.raises(FileNotFoundError):
            kilosort.labels(d)


# ---------------------------------------------------------------------------
# waveformdata()
# ---------------------------------------------------------------------------


class TestWaveformData:
    def test_loads_arrays(self, kdir):
        templates, spike_templates, amplitudes, winv = kilosort.waveformdata(kdir)
        assert templates.shape == (2, 4, 2)
        np.testing.assert_array_equal(spike_templates, _SPIKE_TEMPLATES)
        np.testing.assert_allclose(amplitudes, _AMPLITUDES)
        assert winv is None  # no whitening_mat_inv.npy in the fixture

    def test_winv_loaded_when_present(self, kdir):
        np.save(kdir / "whitening_mat_inv.npy", np.eye(2))
        _, _, _, winv = kilosort.waveformdata(kdir)
        assert winv is not None and winv.shape == (2, 2)

    def test_missing_required_raises(self, tmp_path):
        d = tmp_path / "ks"
        d.mkdir()
        np.save(d / "templates.npy", _TEMPLATES)  # missing spike_templates/amplitudes
        with pytest.raises(FileNotFoundError):
            kilosort.waveformdata(d)


# ---------------------------------------------------------------------------
# meanwaveform()  (amplitude-weighted average; 0-based template indexing)
# ---------------------------------------------------------------------------


class TestMeanWaveform:
    def test_single_template_cluster(self):
        """Cluster 1 has one spike on template 0 (amp 5). Hand-computed result."""
        mwf = kilosort.meanwaveform(
            1, _SPIKE_CLUSTERS, _SPIKE_TEMPLATES, _AMPLITUDES, _TEMPLATES, None
        )
        # weighted avg over template 0 only -> template 0 itself; scaled by mean(amp)=5
        expected = _TEMPLATES[0] * 5.0
        np.testing.assert_allclose(mwf, expected)

    def test_multi_template_cluster_amplitude_weighted(self):
        """Cluster 2 spans templates 0 (amp 1) and 1 (amp 2,3) -> weighted average."""
        mwf = kilosort.meanwaveform(
            2, _SPIKE_CLUSTERS, _SPIKE_TEMPLATES, _AMPLITUDES, _TEMPLATES, None
        )
        # cluster 2 spikes: template ids [1,1,1]? No: spikes idx where cluster==2 are
        # positions 1,4,5 -> templates [1,1,1], amps [1,2,3].
        # All on template 1: weighted avg = template 1; mean(amp) = 2.
        expected = _TEMPLATES[1] * 2.0
        np.testing.assert_allclose(mwf, expected)

    def test_true_mix_of_templates(self):
        """Cluster 0 spikes (idx 0,3): templates [0,0], amps [10,30] — template 0."""
        mwf = kilosort.meanwaveform(
            0, _SPIKE_CLUSTERS, _SPIKE_TEMPLATES, _AMPLITUDES, _TEMPLATES, None
        )
        expected = _TEMPLATES[0] * 20.0  # mean([10,30]) = 20
        np.testing.assert_allclose(mwf, expected)

    def test_synthetic_cross_template_weighting(self):
        """Hand-built two-template cluster to verify the weighting formula directly."""
        sc = np.array([9, 9])
        st = np.array([0, 1])
        amp = np.array([1.0, 3.0])
        mwf = kilosort.meanwaveform(9, sc, st, amp, _TEMPLATES, None)
        # weighted avg = (1*T0 + 3*T1)/4, scaled by mean(amp)=2
        expected = (1.0 * _TEMPLATES[0] + 3.0 * _TEMPLATES[1]) / 4.0 * 2.0
        np.testing.assert_allclose(mwf, expected)

    def test_empty_cluster_returns_zeros(self):
        mwf = kilosort.meanwaveform(
            999, _SPIKE_CLUSTERS, _SPIKE_TEMPLATES, _AMPLITUDES, _TEMPLATES, None
        )
        np.testing.assert_array_equal(mwf, np.zeros((4, 2)))

    def test_unwhitening_applies_matrix(self):
        winv = np.array([[2.0, 0.0], [0.0, 1.0]])
        mwf = kilosort.meanwaveform(
            1, _SPIKE_CLUSTERS, _SPIKE_TEMPLATES, _AMPLITUDES, _TEMPLATES, winv
        )
        expected = (_TEMPLATES[0] * 5.0) @ winv
        np.testing.assert_allclose(mwf, expected)


# ---------------------------------------------------------------------------
# getInfo()  (on-disk summary; needs a probe-with-elementstring + session.path)
# ---------------------------------------------------------------------------


class _PathSession:
    """Minimal session exposing only .path (getInfo reads nothing else)."""

    def __init__(self, path):
        self.path = path


class _NamedProbe:
    """Minimal probe exposing only elementstring() (getInfo needs no more)."""

    def __init__(self, name="probe", reference=1):
        self._name = name
        self._reference = reference

    def elementstring(self):
        return f"{self._name} | {self._reference}"


class TestGetInfo:
    def test_summary_counts_and_filter(self, tmp_path):
        # getInfo builds [path]/kilosort/[elementstring_underscored]/kilosort_output
        sess_path = tmp_path
        prb = _NamedProbe("probe", 1)
        _write_fixture(_kilosort_dir(sess_path, prb))
        sess = _PathSession(sess_path)

        info, summary = kilosort.getInfo(sess, prb)
        assert info["num_clusters"] == 3
        assert info["cluster_ids"] == [0, 1, 2]
        assert info["cluster_labels"] == ["good", "mua", "noise"]
        # spike counts per cluster: cluster0=2, cluster1=1, cluster2=3
        assert info["num_spikes"] == [2, 1, 3]
        assert info["num_spikes_total"] == 6
        # default quality_labels=(good, mua) -> clusters 0 and 1 would import
        assert info["would_import"] == [True, True, False]
        assert info["num_would_import"] == 2
        # template dims from templates.npy (2 templates, 4 samples, 2 channels)
        assert info["num_templates"] == 2
        assert info["samples_per_template"] == 4
        assert info["num_channels"] == 2
        assert "Would import (good, mua): 2 of 3" in summary

    def test_unique_tags_sorted(self, tmp_path):
        prb = _NamedProbe("probe", 1)
        _write_fixture(_kilosort_dir(tmp_path, prb))
        info, _ = kilosort.getInfo(_PathSession(tmp_path), prb)
        assert info["unique_tags"] == ["good", "mua", "noise"]
        assert info["tag_counts"] == [1, 1, 1]

    def test_templates_absent_reports_none(self, tmp_path):
        prb = _NamedProbe("probe", 1)
        d = _kilosort_dir(tmp_path, prb)
        _write_fixture(d)
        (d / "templates.npy").unlink()
        info, summary = kilosort.getInfo(_PathSession(tmp_path), prb)
        assert info["num_templates"] is None
        assert "templates.npy not present" in summary

    def test_missing_dir_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            kilosort.getInfo(_PathSession(tmp_path), _NamedProbe("nope", 9))


# ---------------------------------------------------------------------------
# Cluster grouping + curation logic (deterministic, no DB)
# ---------------------------------------------------------------------------


class TestClusterGroupingAndCuration:
    def test_grouping_by_cluster_id(self):
        for cid, expected in [(0, [5, 105]), (1, [50]), (2, [10, 110, 195])]:
            idx = np.flatnonzero(_SPIKE_CLUSTERS == cid)
            np.testing.assert_array_equal(_SPIKE_TIMES[idx], expected)

    def test_curation_default_filter(self):
        ids, labs = [0, 1, 2], ["good", "mua", "noise"]
        want = [s.lower() for s in ("good", "mua")]
        kept = [cid for cid, lab in zip(ids, labs) if lab.lower() in want]
        assert kept == [0, 1]

    def test_curation_case_insensitive(self):
        labs = ["GOOD", "Mua", "NOISE"]
        want = [s.lower() for s in ("good", "mua")]
        kept = [lab for lab in labs if lab.lower() in want]
        assert kept == ["GOOD", "Mua"]

    def test_quality_values_parallel_mapping(self):
        labels_opt, values_opt = ("good", "mua"), (1, 4)
        want = [s.lower() for s in labels_opt]
        # cluster labelled 'mua' -> quality value 4
        assert values_opt[want.index("mua")] == 4
        assert values_opt[want.index("good")] == 1

    def test_global_to_local_0based_split(self):
        """The 0-based local-sample mapping that probe() performs per epoch."""
        bounds0 = np.array([0, EPOCH0_COUNT, EPOCH0_COUNT + EPOCH1_COUNT])
        # cluster 0 global spikes [5, 105]
        g0 = np.array([5, 105])
        # epoch 0
        in0 = np.flatnonzero((g0 >= bounds0[0]) & (g0 < bounds0[1]))
        local0 = g0[in0] - bounds0[0]
        np.testing.assert_array_equal(local0, [5])
        np.testing.assert_allclose(local0 / SR, [0.5])
        # epoch 1
        in1 = np.flatnonzero((g0 >= bounds0[1]) & (g0 < bounds0[2]))
        local1 = g0[in1] - bounds0[1]
        np.testing.assert_array_equal(local1, [5])  # 105 - 100
        np.testing.assert_allclose(local1 / SR, [0.5])


# ---------------------------------------------------------------------------
# Full probe() import against a REAL ndi_session_dir + a FakeProbe
# ---------------------------------------------------------------------------


def _real_session(tmp_path):
    """Return a real ndi_session_dir, or skip if the infra is unavailable."""
    try:
        from ndi.session.dir import ndi_session_dir
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"ndi_session_dir unavailable: {exc}")
    p = tmp_path / "sess"
    p.mkdir(exist_ok=True)
    try:
        return ndi_session_dir("T", p)
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"could not create ndi_session_dir: {exc}")


class _FakeProbe:
    """A probe-like element with a deterministic 2-epoch table at SR Hz.

    Supplies exactly the surface probe() / getInfo() touch: id, name, reference,
    elementstring, epochtable, samplerate, times2samples (0-based, like
    ndi.probe.timeseries), samples2times (0-based), and subject_id.
    """

    def __init__(self, session, name="probe", reference=1):
        # register a real element doc so addMultiple's underlying_element_id is real
        from ndi.element import ndi_element

        self._elem = ndi_element(
            session=session,
            name=name,
            reference=reference,
            type="n-trode",
            direct=False,
            subject_id="subj1",
        )
        session.database_add(self._elem.newdocument())
        self._name = name
        self._reference = reference

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
                "t0_t1": [[0.0, (EPOCH0_COUNT - 1) / SR]],
            },
            {
                "epoch_id": "ep1",
                "epoch_clock": [CT.DEV_LOCAL_TIME],
                "t0_t1": [[0.0, (EPOCH1_COUNT - 1) / SR]],
            },
        ]
        return et, "hash"

    def samplerate(self, epoch):
        return SR

    def times2samples(self, epoch, times):
        # 0-based, matching ndi.probe.timeseries
        return np.round(np.asarray(times) * SR).astype(int)

    def samples2times(self, epoch, samples):
        return np.asarray(samples, dtype=float) / SR


class TestProbeImportIntegration:
    def test_dry_run_makes_no_changes(self, tmp_path, capsys):
        sess = _real_session(tmp_path)
        prb = _FakeProbe(sess)
        d = _kilosort_dir(tmp_path / "sess", prb)
        _write_fixture(d)

        from ndi.query import ndi_query

        kilosort.probe(sess, prb, dryRun=True, verbose=False)
        out = capsys.readouterr().out
        assert "Would import" in out
        # no kilosort_clusters / neuron documents created
        assert sess.database_search(ndi_query("").isa("kilosort_clusters")) == []
        assert sess.database_search(ndi_query("").isa("neuron_extracellular")) == []

    def test_import_creates_neurons_and_docs(self, tmp_path):
        sess = _real_session(tmp_path)
        prb = _FakeProbe(sess)
        d = _kilosort_dir(tmp_path / "sess", prb)
        _write_fixture(d)

        from ndi.query import ndi_query

        kilosort.probe(sess, prb, verbose=False)

        kc = sess.database_search(ndi_query("").isa("kilosort_clusters"))
        assert len(kc) == 1
        ne = sess.database_search(ndi_query("").isa("neuron_extracellular"))
        # default filter keeps clusters 0 (good) and 1 (mua) -> 2 neurons
        assert len(ne) == 2
        cluster_indices = sorted(
            doc.document_properties["neuron_extracellular"]["cluster_index"] for doc in ne
        )
        assert cluster_indices == [0, 1]

    def test_imported_neuron_quality_and_waveform(self, tmp_path):
        sess = _real_session(tmp_path)
        prb = _FakeProbe(sess)
        d = _kilosort_dir(tmp_path / "sess", prb)
        _write_fixture(d)

        from ndi.query import ndi_query

        kilosort.probe(sess, prb, verbose=False)
        ne = sess.database_search(ndi_query("").isa("neuron_extracellular"))
        by_cluster = {
            doc.document_properties["neuron_extracellular"]["cluster_index"]: doc for doc in ne
        }
        good = by_cluster[0].document_properties["neuron_extracellular"]
        assert good["quality_label"] == "good"
        assert good["quality_number"] == 1
        mua = by_cluster[1].document_properties["neuron_extracellular"]
        assert mua["quality_label"] == "mua"
        assert mua["quality_number"] == 4
        # waveform dims: 4 samples x 2 channels
        assert good["number_of_samples_per_channel"] == 4
        assert good["number_of_channels"] == 2

    def test_spike_times_mapped_to_local_epoch_time(self, tmp_path):
        sess = _real_session(tmp_path)
        prb = _FakeProbe(sess)
        d = _kilosort_dir(tmp_path / "sess", prb)
        _write_fixture(d)

        from ndi.query import ndi_query

        kilosort.probe(sess, prb, verbose=False)
        # find the neuron element for cluster 0 (good) and read its two epochs
        elems = sess.database_search(
            ndi_query("").isa("element") & ndi_query("").depends_on("underlying_element_id", prb.id)
        )
        # the good-cluster neuron is named probe_1_0
        good_elem = next(
            e for e in elems if e.document_properties["element"]["name"] == "probe_1_0"
        )
        from ndi.neuron import ndi_neuron

        neuron = ndi_neuron(session=sess, document=good_elem)
        # cluster 0 spikes at global [5, 105] -> local 0.5s in BOTH epochs
        data0, t0, _ = neuron.readtimeseries("ep0")
        np.testing.assert_allclose(t0, [0.5])
        data1, t1, _ = neuron.readtimeseries("ep1")
        np.testing.assert_allclose(t1, [0.5])

    def test_idempotent_unchanged_curation(self, tmp_path, capsys):
        sess = _real_session(tmp_path)
        prb = _FakeProbe(sess)
        d = _kilosort_dir(tmp_path / "sess", prb)
        _write_fixture(d)

        from ndi.query import ndi_query

        kilosort.probe(sess, prb, verbose=False)
        capsys.readouterr()
        # second run with identical curation -> nothing to do
        kilosort.probe(sess, prb, verbose=True)
        out = capsys.readouterr().out
        assert "unchanged" in out
        # still exactly one kilosort_clusters doc and 2 neurons
        assert len(sess.database_search(ndi_query("").isa("kilosort_clusters"))) == 1
        assert len(sess.database_search(ndi_query("").isa("neuron_extracellular"))) == 2

    def test_reimport_on_changed_curation(self, tmp_path):
        sess = _real_session(tmp_path)
        prb = _FakeProbe(sess)
        d = _kilosort_dir(tmp_path / "sess", prb)
        _write_fixture(d)

        from ndi.query import ndi_query

        kilosort.probe(sess, prb, verbose=False)
        # change curation: relabel cluster 2 noise -> good (now 3 importable)
        lines = ["cluster_id\tgroup", "0\tgood", "1\tmua", "2\tgood"]
        (d / "cluster_group.tsv").write_text("\n".join(lines) + "\n")
        # also need spike_clusters.npy MD5 to change so re-import triggers; the
        # importer keys on spike_clusters.npy. Touch one spike's cluster (re-save).
        np.save(d / "spike_clusters.npy", _SPIKE_CLUSTERS.copy())  # same content
        # MD5 unchanged -> use force to re-import with the new labels
        kilosort.probe(sess, prb, force=True, verbose=False)

        kc = sess.database_search(ndi_query("").isa("kilosort_clusters"))
        assert len(kc) == 1  # old removed, new added
        ne = sess.database_search(ndi_query("").isa("neuron_extracellular"))
        assert len(ne) == 3  # clusters 0, 1, 2 now all importable

    def test_sample_out_of_range_raises(self, tmp_path):
        sess = _real_session(tmp_path)
        prb = _FakeProbe(sess)
        d = _kilosort_dir(tmp_path / "sess", prb)
        _write_fixture(d)
        # put a spike past the end of the 200-sample concatenation
        bad = _SPIKE_TIMES.copy()
        bad[-1] = 10_000
        np.save(d / "spike_times.npy", bad)
        with pytest.raises(ValueError, match="sampleOutOfRange"):
            kilosort.probe(sess, prb, verbose=False)


# ---------------------------------------------------------------------------
# session() — iterate probes, skip missing with a warning
# ---------------------------------------------------------------------------


class TestSession:
    def test_skips_probe_without_output(self, tmp_path, monkeypatch):
        sess = _real_session(tmp_path)
        prb = _FakeProbe(sess)  # no kilosort dir written for it
        monkeypatch.setattr(sess, "getprobes", lambda **kw: [prb])
        with pytest.warns(UserWarning, match="no kilosort output found"):
            kilosort.session(sess, verbose=False)

    def test_imports_present_probe(self, tmp_path, monkeypatch):
        sess = _real_session(tmp_path)
        prb = _FakeProbe(sess)
        d = _kilosort_dir(tmp_path / "sess", prb)
        _write_fixture(d)
        monkeypatch.setattr(sess, "getprobes", lambda **kw: [prb])

        from ndi.query import ndi_query

        kilosort.session(sess, verbose=False)
        assert len(sess.database_search(ndi_query("").isa("neuron_extracellular"))) == 2


# ---------------------------------------------------------------------------
# extracellularInfo() — database-side view of imported neurons
# ---------------------------------------------------------------------------


class TestExtracellularInfo:
    def test_summarizes_imported_neurons(self, tmp_path):
        from ndi.fun.probe import extracellularInfo

        sess = _real_session(tmp_path)
        prb = _FakeProbe(sess)
        d = _kilosort_dir(tmp_path / "sess", prb)
        _write_fixture(d)
        kilosort.probe(sess, prb, verbose=False)

        info, summary = extracellularInfo(sess, prb)
        assert len(info) == 2
        # sorted by cluster_index
        assert [e["cluster_index"] for e in info] == [0, 1]
        assert info[0]["quality_label"] == "good"
        assert info[1]["quality_label"] == "mua"
        assert "Kilosort" in (info[0]["pipeline"] or "")
        assert "Neurons:          2" in summary

    def test_quality_label_filter(self, tmp_path):
        from ndi.fun.probe import extracellularInfo

        sess = _real_session(tmp_path)
        prb = _FakeProbe(sess)
        d = _kilosort_dir(tmp_path / "sess", prb)
        _write_fixture(d)
        kilosort.probe(sess, prb, verbose=False)

        info, _ = extracellularInfo(sess, prb, quality_labels=["good"])
        assert len(info) == 1 and info[0]["quality_label"] == "good"

    def test_empty_when_no_neurons(self, tmp_path):
        from ndi.fun.probe import extracellularInfo

        sess = _real_session(tmp_path)
        prb = _FakeProbe(sess)
        info, summary = extracellularInfo(sess, prb)
        assert info == []
        assert "no neuron_extracellular documents" in summary


# ---------------------------------------------------------------------------
# removeold() — remove a previous import
# ---------------------------------------------------------------------------


class TestRemoveOld:
    def test_removes_clusters_neurons_and_epochs(self, tmp_path):
        sess = _real_session(tmp_path)
        prb = _FakeProbe(sess)
        d = _kilosort_dir(tmp_path / "sess", prb)
        _write_fixture(d)
        kilosort.probe(sess, prb, verbose=False)

        from ndi.query import ndi_query

        kc = sess.database_search(ndi_query("").isa("kilosort_clusters"))[0]
        kilosort.removeold(sess, kc)

        assert sess.database_search(ndi_query("").isa("kilosort_clusters")) == []
        assert sess.database_search(ndi_query("").isa("neuron_extracellular")) == []
        # neuron elements gone too
        elems = sess.database_search(
            ndi_query("").isa("element") & ndi_query("").depends_on("underlying_element_id", prb.id)
        )
        assert elems == []


# ---------------------------------------------------------------------------
# plotProbeGeometry() — deferred matplotlib contract
# ---------------------------------------------------------------------------


class TestPlotProbeGeometry:
    def test_module_imports_without_matplotlib(self):
        # importing the module must not require matplotlib. (The package
        # re-exports the function under the same name, so reach the submodule
        # explicitly via importlib rather than attribute access.)
        import importlib

        mod = importlib.import_module("ndi.fun.probe.plotProbeGeometry")
        assert callable(mod.plotProbeGeometry)

    def test_plots_when_matplotlib_present(self):
        mpl = pytest.importorskip("matplotlib")
        mpl.use("Agg")
        import matplotlib.pyplot as plt

        from ndi.fun.probe import plotProbeGeometry

        pg = {
            "site_locations_leftright": [0.0, 0.0, 20.0, 20.0],
            "site_locations_depth": [0.0, 20.0, 0.0, 20.0],
            "shank_id": [1, 1, 1, 1],
            "unit": "um",
            "probe_model": "test",
        }
        fig, ax = plt.subplots()
        h = plotProbeGeometry(pg, axes=ax)
        assert "sites" in h and h["ax"] is ax
        plt.close(fig)

    def test_raises_cleanly_if_matplotlib_absent(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("matplotlib"):
                raise ImportError("no matplotlib")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        from ndi.fun.probe import plotProbeGeometry

        with pytest.raises(ImportError, match="requires matplotlib"):
            plotProbeGeometry({"site_locations_leftright": [], "site_locations_depth": []})
