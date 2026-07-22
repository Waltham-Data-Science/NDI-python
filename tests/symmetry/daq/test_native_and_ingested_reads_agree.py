"""Gate for the sample-index convention fix (commit 12, SPLIT OUT / not landed).

The same epoch read NATIVELY (via the Intan reader) and after INGESTION must
return byte-identical data AND identical time vectors. NDI core emits 0-based
sample indices (epochtimes2samples), the ingested read path consumes them
0-based, but the native Intan reader treats them 1-based (intan.py subtracts 1;
ndr.py forwards NDI's 0-based indices into NDR's 1-based API) — so the two paths
disagree by exactly one sample for identical data.

STATUS: the seam fix that would make this pass is deliberately NOT applied on
this branch. This test is the gate that must go GREEN before that fix lands.

It cannot pass in a plain local checkout: NDI-python's mfdaq/intan reader does
NOT override ``ingest_epochfiles`` to write the sample binaries
(``channel_list.bin`` / ``ai_group*_seg.nbf_*``) — the base implementation writes
only the epoch-metadata document — so a locally-ingested epoch has no readable
ingested data, and the ingested read raises. Whoever lands the seam fix must run
this gate against a MATLAB- or cloud-ingested epoch (which carries those
binaries). Until then it SKIPS rather than failing, and the ``xfail`` marker
records that native vs ingested currently disagree.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

_TESTS_ROOT = Path(__file__).resolve().parents[2]
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))


def _have_intan_data() -> bool:
    try:
        from symmetry.make_artifacts.session._ingestion_helpers import _find_intan_rhd

        return _find_intan_rhd() is not None
    except Exception:
        return False


def _build_intan_session(session_dir: Path):
    from symmetry.make_artifacts.session._ingestion_helpers import setup_intan_session

    from ndi.session import ndi_session_dir
    from ndi.subject import ndi_subject

    session = ndi_session_dir("exp1", session_dir)
    session.cache.clear()
    setup_intan_session(session_dir, reader_class="intan")
    fn_doc = session.newdocument(
        "daq/filenavigator",
        **{
            "base.name": "unknown",
            "filenavigator.ndi_filenavigator_class": "ndi.file.navigator",
            "filenavigator.fileparameters": "{ '#.rhd', '#.epochprobemap.ndi' }",
            "filenavigator.epochprobemap_class": "ndi.epoch.epochprobemap_daqsystem",
            "filenavigator.epochprobemap_fileparameters": "{ '(.*?)epochprobemap.ndi' }",
        },
    )
    session.database_add(fn_doc)
    dr_doc = session.newdocument(
        "daq/daqreader",
        **{
            "base.name": "intan_reader",
            "daqreader.ndi_daqreader_class": "ndi.daq.reader.mfdaq.intan",
        },
    )
    session.database_add(dr_doc)
    daq_doc = session.newdocument(
        "daq/daqsystem",
        **{"base.name": "intan1", "daqsystem.ndi_daqsystem_class": "ndi.daq.system.mfdaq"},
    )
    daq_doc = daq_doc.set_dependency_value("filenavigator_id", fn_doc.id, error_if_not_found=False)
    daq_doc = daq_doc.set_dependency_value("daqreader_id", dr_doc.id, error_if_not_found=False)
    session.database_add(daq_doc)
    subject = ndi_subject("anteater27@nosuchlab.org", "")
    session.database_add(subject.newdocument())
    return session


def _first_epoch_id(daq):
    et = daq.epochtable()
    et = et[0] if isinstance(et, tuple) else et
    return et[0]["epoch_id"]


def _read(daq, epoch_id, channeltype, channel, t0, t1):
    s0, s1 = (int(v) for v in np.ravel(daq.epochtimes2samples(channeltype, channel, epoch_id, [t0, t1])))
    data = np.asarray(daq.readchannels_epochsamples(channeltype, channel, epoch_id, s0, s1))
    times = np.ravel(np.asarray(daq.epochsamples2times(channeltype, channel, epoch_id, np.arange(s0, s1 + 1))))
    return data, times


@pytest.mark.skipif(not _have_intan_data(), reason="Intan example data (.rhd) not found")
@pytest.mark.xfail(
    reason="sample-index seam fix (commit 12) intentionally not applied on this branch",
    strict=False,
)
def test_native_and_ingested_reads_agree():
    channeltype, channel = "analog_in", [1]
    with tempfile.TemporaryDirectory() as td:
        sdir = Path(td) / "exp1"
        sdir.mkdir()
        session = _build_intan_session(sdir)
        session.getprobes()

        daq = session.daqsystem_load()
        eid = _first_epoch_id(daq)
        data_native, t_native = _read(daq, eid, channeltype, channel, 0.0, 0.005)

        ok, msg = session.ingest()
        assert ok, f"ingest failed: {msg}"
        session.cache.clear()
        session.getprobes()
        daq2 = session.daqsystem_load()
        eid2 = _first_epoch_id(daq2)

        try:
            data_ing, t_ing = _read(daq2, eid2, channeltype, channel, 0.0, 0.005)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(
                "ingested read unavailable locally (Python mfdaq ingest writes no "
                f"channel_list.bin/.nbf sample binaries): {type(exc).__name__}: {exc}"
            )

        # The gate: identical data and identical time vectors, no one-sample shift.
        assert data_native.shape == data_ing.shape
        np.testing.assert_array_equal(data_native, data_ing)
        np.testing.assert_allclose(t_native, t_ing, rtol=0, atol=0)
