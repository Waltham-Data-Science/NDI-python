"""Regression tests for ingested-segment read integrity (mfdaq).

readchannels_epochsamples_ingested used to pre-fill its output with NaN, swallow
any per-segment decode failure (logging a warning and advancing the row count),
and shrink a short segment regardless of position — so a missing/corrupt or
short mid-stream segment silently became NaN or shifted every later sample while
the call reported success. These tests pin the loud-failure behaviour.
"""

from __future__ import annotations

from unittest import mock

import numpy as np
import pytest

from ndi.daq.mfdaq import ndi_daq_reader_mfdaq


class _Reader(ndi_daq_reader_mfdaq):
    def getchannelsepoch(self, epochfiles):
        return []

    def readchannels_epochsamples(self, channeltype, channel, epochfiles, s0, s1):
        return np.zeros((s1 - s0 + 1, 1))

    def samplerate(self, epochfiles, channeltype, channel):
        return [30000.0]


def _fake_fobj():
    f = mock.MagicMock()
    f.name = "chunk.nbf"
    return f


def _patch_common(reader, monkeypatch):
    """Stub the metadata helpers so the code reaches the segment loop with one
    analog group, 100-sample segments, unit scale/offset."""
    doc = mock.MagicMock()
    doc.document_properties = {
        "daqreader_mfdaq_epochdata_ingested": {"parameters": {"sample_analog_segment": 100}}
    }
    monkeypatch.setattr(reader, "getingesteddocument", lambda *a, **k: doc)
    monkeypatch.setattr(reader, "samplerate_ingested", lambda *a, **k: ([30000.0], [0.0], [1.0]))
    monkeypatch.setattr(reader, "t0_t1_ingested", lambda *a, **k: [(0.0, 1.0)])
    monkeypatch.setattr(reader, "epochtimes2samples_ingested", lambda *a, **k: np.array([0, 250]))
    monkeypatch.setattr(reader, "getchannelsepoch_ingested", lambda *a, **k: [object()])
    from ndi.file.type.mfdaq_epoch_channel import ndi_file_type_mfdaq__epoch__channel

    monkeypatch.setattr(
        ndi_file_type_mfdaq__epoch__channel,
        "channelgroupdecoding",
        staticmethod(lambda info, ctype, channel: ([1], [0], [0])),
    )


def test_ingested_segment_failure_raises(monkeypatch):
    """A segment that cannot be opened/decoded must raise, not return a NaN-filled
    'successful' array."""
    reader = _Reader()
    _patch_common(reader, monkeypatch)

    session = mock.MagicMock()
    session.database_openbinarydoc = mock.MagicMock(side_effect=OSError("segment gone"))

    with pytest.raises(RuntimeError, match="could not be read/decoded"):
        reader.readchannels_epochsamples_ingested(
            "analog_in", [1], ["epochid://x"], 0, 250, session
        )


def test_short_middle_segment_raises(monkeypatch):
    """A non-final segment shorter than requested must raise rather than splice
    later samples earlier (matching MATLAB mfdaq.m:288-297)."""
    reader = _Reader()
    _patch_common(reader, monkeypatch)

    session = mock.MagicMock()
    session.database_openbinarydoc = mock.MagicMock(side_effect=lambda *a, **k: _fake_fobj())

    # seg 1 full (100), seg 2 short (50) -> must raise before seg 3.
    monkeypatch.setattr(
        "ndicompress.expand_ephys",
        mock.MagicMock(side_effect=[np.zeros((100, 1)), np.zeros((50, 1))]),
    )

    with pytest.raises(RuntimeError, match="short by"):
        reader.readchannels_epochsamples_ingested(
            "analog_in", [1], ["epochid://x"], 0, 250, session
        )


def test_full_segments_succeed(monkeypatch):
    """The happy path still returns a complete, NaN-free array."""
    reader = _Reader()
    _patch_common(reader, monkeypatch)

    session = mock.MagicMock()
    session.database_openbinarydoc = mock.MagicMock(side_effect=lambda *a, **k: _fake_fobj())

    # 3 segments: 100 + 100 + 51 rows = 251 == (250 - 0 + 1).
    monkeypatch.setattr(
        "ndicompress.expand_ephys",
        mock.MagicMock(side_effect=[np.ones((100, 1)), np.ones((100, 1)), np.ones((51, 1))]),
    )

    out = reader.readchannels_epochsamples_ingested(
        "analog_in", [1], ["epochid://x"], 0, 250, session
    )
    assert out.shape == (251, 1)
    assert not np.isnan(out).any()
