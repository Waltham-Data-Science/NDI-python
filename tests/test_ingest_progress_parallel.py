"""Ingestion progress bars and parallel per-epoch work.

MATLAB counterpart: tests/+ndi/+unittest/+ingestion/ingestionProgressParallel.m
(VH-Lab/NDI-matlab#1079)

Covers the pieces ported together for that change:

* ndi_gui_component_ProgressBarWindow's silent (headless) mode and per-bar
  Timeout -- needed so ingest can show progress by default without a display;
* the Parallel.* preferences and ndi.fun.parallelWorkers;
* ndi.daq.fun.ingestEpochDocuments, serially and on worker processes;
* ndi_session.ingest / ndi_daq_system.ingest driving the bars, end to end on
  the example Intan session given a second epoch.

Every window here is forced silent, so no display or PySide6 is needed.
"""

from __future__ import annotations

import math
import shutil
import threading
import warnings

import pytest

import ndi.preferences
from ndi.daq.fun import ingestEpochDocuments
from ndi.fun.utils import parallelWorkers
from ndi.gui.component.ProgressBarWindow import ndi_gui_component_ProgressBarWindow as PBW

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_silent_override():
    """Leave the process-wide silent override as it was found."""
    previous = PBW.silentModeDefault()
    yield
    PBW.silentModeDefault(previous)


def _prefs(monkeypatch, **values):
    """Pin Parallel.* preference values for one test (nothing is written)."""
    real_get = ndi.preferences.get

    def fake_get(path):
        key = path.split(".")[-1]
        if path.startswith("Parallel.") and key in values:
            return values[key]
        return real_get(path)

    monkeypatch.setattr(ndi.preferences, "get", fake_get)


class _FakeDoc:
    def __init__(self, kind, epoch_id):
        self.kind = kind
        self.epoch_id = epoch_id

    def __eq__(self, other):
        return (self.kind, self.epoch_id) == (other.kind, other.epoch_id)


class _FakeReader:
    """A picklable reader; its _session is deliberately unpicklable."""

    def __init__(self, kind="reader"):
        self.kind = kind
        self._session = threading.Lock()  # a live session cannot be pickled either

    def ingest_epochfiles(self, epochfiles, epoch_id):
        return _FakeDoc(self.kind, epoch_id)


class _UnpicklableReader(_FakeReader):
    def __init__(self):
        super().__init__()
        self.handle = threading.Lock()  # not the session: cannot be detached


# ---------------------------------------------------------------------------
# ProgressBarWindow silent mode
# ---------------------------------------------------------------------------


class TestSilentProgressBarWindow:
    def test_silent_window_keeps_bookkeeping(self):
        w = PBW("silent test", Silent=True, AutoDelete=False)
        assert w.Silent
        w.addBar(Label="one", Tag="a", Auto=False)
        assert w.getState("a") == "Open"
        w.updateBar("a", 0.5)
        assert w._bars[0].Progress == 0.5
        w.updateBar("a", 1.0)
        assert w.getState("a") == "Complete"
        w.removeBar("a")
        assert w.getBarNum("a")[0] is None

    def test_auto_bar_is_removed_on_completion(self):
        w = PBW("silent auto", Silent=True, AutoDelete=False)
        w.addBar(Label="auto", Tag="a", Auto=True)
        w.updateBar("a", 1.0)
        assert w.getBarNum("a")[0] is None

    def test_per_bar_timeout(self):
        w = PBW("silent timeout", Silent=True, AutoDelete=False)
        w.setTimeout(0.0)
        w.addBar(Label="inherits", Tag="inherit", Auto=False)
        w.addBar(Label="never", Tag="never", Auto=False, Timeout=math.inf)
        w.updateBar("never", 0.5)
        assert w.getState("inherit") == "Timeout"
        assert w.getState("never") == "Open"

    def test_silent_mode_default_overrides_detection(self):
        PBW.silentModeDefault(True)
        assert PBW.resolveSilentMode() is True
        assert PBW.resolveSilentMode(False) is False  # explicit wins
        PBW.silentModeDefault(False)
        assert PBW.resolveSilentMode() is False
        PBW.silentModeDefault(None)
        assert PBW.silentModeDefault() is None

    def test_is_headless_rules(self, monkeypatch):
        import ndi.gui.component.ProgressBarWindow as mod

        monkeypatch.setattr(mod, "_QT_AVAILABLE", False)
        assert PBW.isHeadless() is True

        monkeypatch.setattr(mod, "_QT_AVAILABLE", True)
        monkeypatch.setattr(mod.sys, "platform", "linux")
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
        assert PBW.isHeadless() is True
        monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
        assert PBW.isHeadless() is False
        monkeypatch.delenv("QT_QPA_PLATFORM")
        monkeypatch.setenv("DISPLAY", ":0")
        assert PBW.isHeadless() is False


# ---------------------------------------------------------------------------
# Parallel preferences and parallelWorkers
# ---------------------------------------------------------------------------


class TestParallelWorkers:
    def test_preferences_are_registered_with_matlab_defaults(self):
        prefs = ndi.preferences.ndi_preferences(filename=None)
        items = {(i.category, i.name): i for i in prefs._items}
        assert items[("Parallel", "OpenPoolIfNone")].default_value is False
        assert items[("Parallel", "UseDefaultNumberOfWorkers")].default_value is True
        assert items[("Parallel", "NumberOfWorkers")].default_value == 2

    def test_default_is_serial(self, monkeypatch):
        _prefs(monkeypatch, OpenPoolIfNone=False, UseDefaultNumberOfWorkers=True)
        assert parallelWorkers() == 0
        # naming a number does not start workers either, as in MATLAB
        assert parallelWorkers(numberOfWorkers=4) == 0

    def test_open_pool_uses_number_of_workers(self, monkeypatch):
        _prefs(
            monkeypatch,
            OpenPoolIfNone=True,
            UseDefaultNumberOfWorkers=False,
            NumberOfWorkers=3,
        )
        assert parallelWorkers() == 3
        assert parallelWorkers(numberOfWorkers=5) == 5

    def test_open_pool_default_size_is_cpu_count(self, monkeypatch):
        _prefs(monkeypatch, OpenPoolIfNone=True, UseDefaultNumberOfWorkers=True)
        assert parallelWorkers() >= 1

    def test_bad_worker_count_warns_and_uses_default(self, monkeypatch):
        _prefs(
            monkeypatch,
            OpenPoolIfNone=True,
            UseDefaultNumberOfWorkers=False,
            NumberOfWorkers=0,
        )
        with pytest.warns(UserWarning, match="not a number of workers"):
            n = parallelWorkers()
        assert n >= 1


# ---------------------------------------------------------------------------
# ingestEpochDocuments
# ---------------------------------------------------------------------------

_EPOCH_FILES = [[f"/data/e{k}.rhd"] for k in range(1, 5)]
_EPOCH_IDS = [f"epoch_{k}" for k in range(1, 5)]


class TestIngestEpochDocuments:
    def test_serial_order_and_progress(self, monkeypatch):
        _prefs(monkeypatch, OpenPoolIfNone=False)
        calls = []
        docs, used_parallel = ingestEpochDocuments(
            _FakeReader(),
            [_FakeReader("meta")],
            _EPOCH_FILES,
            _EPOCH_IDS,
            ProgressFcn=lambda done, total: calls.append((done, total)),
        )
        assert not used_parallel
        assert calls == [(k, 4) for k in range(1, 5)]
        assert [d[0].epoch_id for d in docs] == _EPOCH_IDS
        assert [d[1].kind for d in docs] == ["meta"] * 4

    def test_forced_serial_override(self, monkeypatch):
        _prefs(monkeypatch, OpenPoolIfNone=True, UseDefaultNumberOfWorkers=True)
        _, used_parallel = ingestEpochDocuments(
            _FakeReader(), [], _EPOCH_FILES, _EPOCH_IDS, NumberOfWorkers=0
        )
        assert not used_parallel

    def test_parallel_matches_serial(self, monkeypatch):
        _prefs(monkeypatch, OpenPoolIfNone=False)
        serial, _ = ingestEpochDocuments(
            _FakeReader(), [_FakeReader("meta")], _EPOCH_FILES, _EPOCH_IDS
        )

        _prefs(
            monkeypatch,
            OpenPoolIfNone=True,
            UseDefaultNumberOfWorkers=False,
            NumberOfWorkers=2,
        )
        calls = []
        reader = _FakeReader()
        parallel, used_parallel = ingestEpochDocuments(
            reader,
            [_FakeReader("meta")],
            _EPOCH_FILES,
            _EPOCH_IDS,
            ProgressFcn=lambda done, total: calls.append((done, total)),
        )
        assert used_parallel
        assert parallel == serial
        assert sorted(calls) == [(k, 4) for k in range(1, 5)]
        # the caller's reader keeps its session; only the workers' copies lose it
        assert reader._session is not None

    def test_unpicklable_reader_falls_back_to_serial(self, monkeypatch):
        _prefs(
            monkeypatch,
            OpenPoolIfNone=True,
            UseDefaultNumberOfWorkers=False,
            NumberOfWorkers=2,
        )
        with pytest.warns(UserWarning, match="Ingesting serially"):
            docs, used_parallel = ingestEpochDocuments(
                _UnpicklableReader(), [], _EPOCH_FILES, _EPOCH_IDS
            )
        assert not used_parallel
        assert [d[0].epoch_id for d in docs] == _EPOCH_IDS

    def test_worker_errors_propagate(self, monkeypatch):
        _prefs(monkeypatch, OpenPoolIfNone=False)

        class Boom(_FakeReader):
            def ingest_epochfiles(self, epochfiles, epoch_id):
                raise RuntimeError("bad epoch")

        with pytest.raises(RuntimeError, match="bad epoch"):
            ingestEpochDocuments(Boom(), [], _EPOCH_FILES, _EPOCH_IDS)

    def test_size_mismatch_raises(self):
        with pytest.raises(ValueError, match="same number"):
            ingestEpochDocuments(_FakeReader(), [], _EPOCH_FILES, _EPOCH_IDS[:2])


# ---------------------------------------------------------------------------
# ndi_session.ingest end to end
# ---------------------------------------------------------------------------


def _intan_session(session_dir):
    """The example Intan session (as in the ingestion symmetry test) with a
    second epoch, so there is more than one epoch to distribute.

    The second epoch is a copy in a subdirectory: this port's
    find_file_groups still makes one epoch per DIRECTORY (see the comment
    there), where MATLAB's findfilegroups makes one per '#' match, which is
    why the MATLAB test can keep both copies side by side."""
    from ndi.session.dir import ndi_session_dir
    from tests.symmetry.make_artifacts.session._ingestion_helpers import (
        setup_intan_session,
    )

    session_dir.mkdir()
    info = setup_intan_session(session_dir, reader_class="intan")
    stem = info["rhd_file"][: -len(".rhd")]
    second = session_dir / "t00002"
    second.mkdir()
    shutil.copy2(session_dir / info["rhd_file"], second / info["rhd_file"])
    shutil.copy2(
        session_dir / f"{stem}.epochprobemap.ndi",
        second / f"{stem}.epochprobemap.ndi",
    )

    session = ndi_session_dir("exp1", session_dir)
    session.cache.clear()
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
    return session


def _ingested_epoch_docs(session):
    from ndi.query import ndi_query

    return session.database_search(ndi_query("").isa("daqreader_epochdata_ingested"))


def _ingested_summary(session):
    """What each ingested epoch says, independent of the (random) epoch ids."""
    import json

    return sorted(
        json.dumps(d.document_properties["daqreader_epochdata_ingested"], sort_keys=True)
        for d in _ingested_epoch_docs(session)
    )


def _have_intan():
    try:
        from tests.symmetry.make_artifacts.session._ingestion_helpers import _find_intan_rhd

        return _find_intan_rhd() is not None
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _have_intan(), reason="Intan example data (.rhd) not found")
class TestSessionIngest:
    def test_default_ingest_still_works(self, tmp_path, monkeypatch):
        _prefs(monkeypatch, OpenPoolIfNone=False)
        PBW.silentModeDefault(True)
        session = _intan_session(tmp_path / "exp1")
        ok, msg = session.ingest()
        assert ok, msg
        assert len(_ingested_epoch_docs(session)) == 2

    def test_progress_bars_reach_completion(self, tmp_path, monkeypatch):
        _prefs(monkeypatch, OpenPoolIfNone=False)
        session = _intan_session(tmp_path / "exp1")
        w = PBW("ingest test", Silent=True, AutoDelete=False)
        ok, msg = session.ingest(ProgressBar=w, ProgressBarTag="sessionBar")
        assert ok, msg
        idx, _ = w.getBarNum("sessionBar")
        assert idx is not None
        assert w._bars[idx].Progress == 1.0
        assert w.getState("sessionBar") == "Complete"
        # the DAQ system's auto bar completed and removed itself
        assert len(w._bars) == 1

    def test_show_progress_false_adds_no_bars(self, tmp_path, monkeypatch):
        _prefs(monkeypatch, OpenPoolIfNone=False)
        session = _intan_session(tmp_path / "exp1")
        w = PBW("ingest test", Silent=True, AutoDelete=False)
        ok, msg = session.ingest(ShowProgress=False, ProgressBar=w)
        assert ok, msg
        assert w._bars == []

    def test_parallel_matches_serial(self, tmp_path, monkeypatch):
        PBW.silentModeDefault(True)
        _prefs(monkeypatch, OpenPoolIfNone=False)
        s1 = _intan_session(tmp_path / "serial")
        ok, msg = s1.ingest()
        assert ok, msg

        _prefs(
            monkeypatch,
            OpenPoolIfNone=True,
            UseDefaultNumberOfWorkers=False,
            NumberOfWorkers=2,
        )
        s2 = _intan_session(tmp_path / "parallel")
        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)  # no fallback to serial
            ok, msg = s2.ingest()
        assert ok, msg
        assert len(_ingested_epoch_docs(s2)) == 2
        assert _ingested_summary(s2) == _ingested_summary(s1)
