"""ndi_daq_system_mfdaq.readchannels_epochsamples reads the same samples
whether the epoch is raw or ingested.

Sample positions are 0-based in this port (docs/developer_notes/
ndi_xlang_principles.md): sample 0 is the epoch's first sample, as for
epochtimes2samples and epochsamples2times. A raw reader's
readchannels_epochsamples takes 1-based samples and the ingested reader
0-based ones; the DAQ system used to pass its numbers to both unchanged, so a
raw epoch read one sample later than the same epoch ingested.
"""

from __future__ import annotations

import shutil

import numpy as np
import pytest

from ndi.gui.component.ProgressBarWindow import ndi_gui_component_ProgressBarWindow as PBW
from tests.test_ingest_progress_parallel import _have_intan, _intan_session, _prefs

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


def _epoch_number(daq, epoch_id):
    return next(e["epoch_number"] for e in daq.epochtable() if e["epoch_id"] == epoch_id)


def test_raw_read_starts_at_sample_zero(tmp_path, monkeypatch):
    _prefs(monkeypatch, OpenPoolIfNone=False)
    daq = _daq(_intan_session(tmp_path / "exp1"))
    files = daq.epochtable()[0]["underlying_epochs"]["underlying"]
    first_five = daq.daqreader.readchannels_epochsamples("ai", [1, 2], files, 1, 5)
    np.testing.assert_array_equal(daq.readchannels_epochsamples("ai", [1, 2], 1, 0, 4), first_five)


def test_raw_time_channel_matches_epochsamples2times(tmp_path, monkeypatch):
    # what a probe returns: data read at samples s0..s1, times from
    # epochsamples2times(s0..s1); the two must describe the same samples
    _prefs(monkeypatch, OpenPoolIfNone=False)
    daq = _daq(_intan_session(tmp_path / "exp1"))
    samples = np.arange(10, 20)
    t_read = np.ravel(daq.readchannels_epochsamples("time", [1], 1, 10, 19))
    t_calc = np.ravel(daq.epochsamples2times("time", [1], 1, samples))
    np.testing.assert_allclose(t_read, t_calc, rtol=0, atol=1e-9)


def test_raw_and_ingested_read_the_same_samples(tmp_path, monkeypatch):
    from ndi.session.dir import ndi_session_dir

    _prefs(monkeypatch, OpenPoolIfNone=False)
    raw = _intan_session(tmp_path / "raw")
    _daq(raw).epochtable()  # write the epoch ids, so the copy shares them
    shutil.copytree(tmp_path / "raw", tmp_path / "ingested")
    raw = ndi_session_dir("exp1", tmp_path / "raw")
    ing = ndi_session_dir("exp1", tmp_path / "ingested")
    ok, msg = ing.ingest()
    assert ok, msg
    ing.cache.clear()

    d_raw, d_ing = _daq(raw), _daq(ing)
    for entry in d_raw.epochtable():
        n_raw = entry["epoch_number"]
        n_ing = _epoch_number(d_ing, entry["epoch_id"])
        for channeltype, channels in (("ai", [1, 2]), ("time", [1])):
            for s0, s1 in ((0, 4), (100, 140)):
                np.testing.assert_allclose(
                    d_raw.readchannels_epochsamples(channeltype, channels, n_raw, s0, s1),
                    d_ing.readchannels_epochsamples(channeltype, channels, n_ing, s0, s1),
                    rtol=0,
                    atol=1e-9,
                    err_msg=f"{channeltype} samples {s0}..{s1}",
                )
