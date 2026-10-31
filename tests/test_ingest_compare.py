"""ndi.test.ingest.compare / mfdaq_compare, and the plan/segment/attach split.

MATLAB counterparts: tests/+ndi/+unittest/+ingestion/ingestCompareTest.m
(VH-Lab/NDI-matlab#1091) and ingestionProgressParallel.m's
testPlanAndSegmentsMatchIngestEpochfiles (VH-Lab/NDI-matlab#1090).

The compare tests build the example Intan session, copy it, ingest the copy,
and compare the two: every check should pass in 'full' and 'spot' modes. Then
an epoch is added to the raw session only, which the comparison must report as
missing from the ingested copy.
"""

from __future__ import annotations

import shutil

import numpy as np
import pytest

from ndi.daq.mfdaq import ndi_daq_reader_mfdaq
from ndi.gui.component.ProgressBarWindow import ndi_gui_component_ProgressBarWindow as PBW
from ndi.test.ingest import compare, mfdaq_compare
from tests.test_ingest_progress_parallel import _have_intan, _intan_session, _prefs

ndicompress = pytest.importorskip("ndicompress")

pytestmark = pytest.mark.skipif(not _have_intan(), reason="Intan example data (.rhd) not found")


@pytest.fixture(autouse=True)
def _silent():
    previous = PBW.silentModeDefault()
    PBW.silentModeDefault(True)
    yield
    PBW.silentModeDefault(previous)


def _daq(session):
    d = session.daqsystem_load(name="intan1")
    return d[0] if isinstance(d, list) else d


def _raw_and_ingested(tmp_path, monkeypatch, **prefs):
    """The test session and an ingested copy of it."""
    from ndi.session.dir import ndi_session_dir

    _prefs(monkeypatch, **{"OpenPoolIfNone": False, **prefs})
    raw = _intan_session(tmp_path / "raw")
    # build the epoch table first, so the epoch ids are written to disk and
    # the copy shares them
    _daq(raw).epochtable()
    shutil.copytree(tmp_path / "raw", tmp_path / "ingested")
    raw = ndi_session_dir("exp1", tmp_path / "raw")
    ing = ndi_session_dir("exp1", tmp_path / "ingested")
    ok, msg = ing.ingest()
    assert ok, msg
    return raw, ing


def _failures(report):
    return "\n".join(
        f"{r['daqsystem']} {r['epoch_id']} {r['check']}: {r['message']}"
        for r in report
        if not r["ok"]
    )


class TestIngestCompare:
    def test_ingested_copy_matches_raw(self, tmp_path, monkeypatch):
        raw, ing = _raw_and_ingested(tmp_path, monkeypatch)
        b, report = compare(raw, ing, ShowProgress=False, Verbose=False)
        assert b, _failures(report)

        checks = [r["check"] for r in report]
        assert "channel_list" in checks
        analog = [r for r in report if r["check"] == "analog_in"]
        assert analog, "analog_in should be compared"
        reader = _daq(raw).daqreader
        files = {
            e["epoch_id"]: e["underlying_epochs"]["underlying"] for e in _daq(raw).epochtable()
        }
        for r in analog:
            # 'full' covers every sample of the epoch
            s = np.ravel(
                reader.epochtimes2samples("analog_in", [1], files[r["epoch_id"]], r["t0_t1"])
            )
            assert r["samples"] == int(s[-1]) - int(s[0]) + 1
            assert r["maxAbsDiff"] == 0

    def test_spot_mode_and_paths(self, tmp_path, monkeypatch):
        # sessions may also be given as folder paths; 'spot' mode passes too
        raw, ing = _raw_and_ingested(tmp_path, monkeypatch)
        b, report = compare(
            raw.path, ing.path, Mode="spot", SpotSeconds=1, ShowProgress=False, Verbose=False
        )
        assert b, _failures(report)
        assert any(r["check"] == "analog_in" for r in report)

    def test_mfdaq_compare_outputs(self, tmp_path, monkeypatch):
        raw, ing = _raw_and_ingested(tmp_path, monkeypatch)
        b, errmsg, report = mfdaq_compare(_daq(raw), _daq(ing), Verbose=False)
        assert b, errmsg
        assert errmsg == []
        assert report

    def test_a_changed_sample_is_reported(self, tmp_path, monkeypatch):
        raw, ing = _raw_and_ingested(tmp_path, monkeypatch)
        real = ndi_daq_reader_mfdaq.readchannels_epochsamples_ingested

        def corrupted(self, channeltype, channel, *args, **kwargs):
            data = np.array(real(self, channeltype, channel, *args, **kwargs), dtype=float)
            if channeltype == "analog_in" and data.size:
                data[0, 0] += 1
            return data

        monkeypatch.setattr(ndi_daq_reader_mfdaq, "readchannels_epochsamples_ingested", corrupted)
        b, errmsg, report = mfdaq_compare(_daq(raw), _daq(ing), Verbose=False)
        assert not b
        bad = [r for r in report if not r["ok"]]
        assert {r["check"] for r in bad} == {"analog_in"}
        assert "Data differ" in bad[0]["message"]

    def test_missing_epoch_is_reported(self, tmp_path, monkeypatch):
        raw, ing = _raw_and_ingested(tmp_path, monkeypatch)
        # an epoch that only the raw session has (one epoch per directory in
        # this port; see _intan_session). Only the data files are copied: the
        # hidden .epochid.ndi file would give the new epoch the old one's id.
        shutil.copytree(
            tmp_path / "raw" / "t00002",
            tmp_path / "raw" / "t00003",
            ignore=shutil.ignore_patterns(".*"),
        )
        raw.cache.clear()
        b, report = compare(raw, ing, ShowProgress=False, Verbose=False)
        assert not b, "An epoch missing from the ingested copy should fail the comparison."
        missing = [r for r in report if r["check"] == "epoch" and not r["ok"]]
        assert len(missing) == 1
        assert "missing" in missing[0]["message"]

    def test_parallel_ingest_by_segment_matches_raw(self, tmp_path, monkeypatch):
        # small segments on two workers: the segments of both epochs are
        # written out of order across the pool and attached afterwards
        monkeypatch.setattr(ndi_daq_reader_mfdaq, "SAMPLE_ANALOG_SEGMENT", 7001)
        monkeypatch.setattr(ndi_daq_reader_mfdaq, "SAMPLE_DIGITAL_SEGMENT", 13003)
        raw, ing = _raw_and_ingested(
            tmp_path,
            monkeypatch,
            OpenPoolIfNone=True,
            UseDefaultNumberOfWorkers=False,
            NumberOfWorkers=2,
        )
        b, report = compare(raw, ing, ChunkSeconds=0.5, ShowProgress=False, Verbose=False)
        assert b, _failures(report)

    def test_daq_system_names_filter(self, tmp_path, monkeypatch):
        raw, ing = _raw_and_ingested(tmp_path, monkeypatch)
        b, report = compare(
            raw, ing, DaqSystemNames=["nosuchdaq"], ShowProgress=False, Verbose=False
        )
        assert b
        assert report == []


def _ai_data(filename):
    """The analog data in one segment file (.nbf.tgz)."""
    data, _ = ndicompress.expand_ephys(filename)
    return np.asarray(data)


class TestPlanAndSegments:
    def test_plan_and_segments_match_ingest_epochfiles(self, tmp_path, monkeypatch):
        """Planning, then ingesting the segments in any order, then attaching
        them gives the same document as ingest_epochfiles (the parallel
        scheduler relies on this)."""
        monkeypatch.setattr(ndi_daq_reader_mfdaq, "SAMPLE_ANALOG_SEGMENT", 20000)
        session = _intan_session(tmp_path / "exp1")
        reader = _daq(session).daqreader
        files = _daq(session).epochtable()[0]["underlying_epochs"]["underlying"]

        whole = reader.ingest_epochfiles(files, "epoch_x")

        d, plan = reader.ingest_epochfiles_plan(files, "epoch_x")
        assert len(plan) > 1
        assert abs(sum(p["weight"] for p in plan) - 1) < 1e-12
        segment_files = [None] * len(plan)
        for k in reversed(range(len(plan))):
            segment_files[k] = reader.ingest_segment(files, plan[k])
        split = ndi_daq_reader_mfdaq.ingest_attach_segments(d, plan, segment_files)

        def names(doc):
            return [f["name"] for f in doc.document_properties["files"]["file_info"]]

        def location(doc, name):
            info = next(
                f for f in doc.document_properties["files"]["file_info"] if f["name"] == name
            )
            return info["locations"][0]["location"]

        assert names(split) == names(whole)
        for name in names(whole):
            if name.startswith("ai_"):
                np.testing.assert_array_equal(
                    _ai_data(location(split, name)), _ai_data(location(whole, name))
                )
