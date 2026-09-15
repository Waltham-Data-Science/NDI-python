"""``readchannels_epochsamples_ingested`` survives windows past epoch edges.

Issue: Waltham-Data-Science/NDI-python#311 (mirrors VH-Lab/NDI-matlab#993).

The ingested reader addresses concrete ``_seg.nbf_N`` files. Segment files
are numbered from 1 by every writer in the wild; the first sample of an
epoch is 0 in the 0-based Python port. A request with ``s0`` below the
epoch's first sample must therefore be clamped rather than passed through:
unclamped, ``s0 // samples_segment`` floors toward negative infinity and
asks the document for ``_seg.nbf_0`` -- a filename no writer has ever
produced. Before the fix that miss was swallowed by a ``try/except`` that
logged a warning and returned partly-NaN data with no exception.

A local reader in the same shape (``ndi.daq.reader.mfdaq.intan`` and
friends) hands the value to an external file library and quietly returns
an empty or short slice, so ``pyraview``'s own excess-read never surfaced
this over local files. These tests drive ``readchannels_epochsamples_ingested``
directly with the windows that used to fail: before ``t0``, after ``t1``,
entirely before ``t0``, ``[-inf, inf]`` (regression), and inverted.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from ndi.daq.mfdaq import ChannelInfo, ndi_daq_reader_mfdaq

SR = 1_000.0  # samples/second
T0 = 0.0
T1 = 1.999  # 2000 samples at 1 kHz, 0-based indices 0..1999
NUM_SAMPLES = 2000
NUM_CHANNELS_IN_GROUP = 2
SEGMENT_SIZE = 500  # exercises the multi-segment path


class _FakeBinaryDoc:
    """Stand-in for the object ``session.database_openbinarydoc`` returns."""

    def __init__(self, name: str) -> None:
        self.name = name

    def close(self) -> None:
        return None


def _make_channel_info() -> list[ChannelInfo]:
    return [
        ChannelInfo(name="ai1", type="analog_in", number=1, sample_rate=SR, group=1),
        ChannelInfo(name="ai2", type="analog_in", number=2, sample_rate=SR, group=1),
    ]


class _ConcreteReader(ndi_daq_reader_mfdaq):
    """Concrete stand-in that answers ``getchannelsepoch``/``samplerate``/``t0_t1``.

    The methods on the ingested code path (``getingesteddocument``,
    ``samplerate_ingested``, ``t0_t1_ingested``, ``epochtimes2samples_ingested``,
    ``getchannelsepoch_ingested``) are stubbed on the instance in each test so
    they need no session state.
    """

    def getchannelsepoch(self, epochfiles):
        return _make_channel_info()

    def readchannels_epochsamples(self, channeltype, channel, epochfiles, s0, s1):
        raise NotImplementedError

    def samplerate(self, epochfiles, channeltype, channel):
        if isinstance(channel, int):
            channel = [channel]
        return np.full(len(channel), SR)

    def t0_t1(self, epochfiles):
        return [(T0, T1)]


@pytest.fixture
def reader():
    r = _ConcreteReader()

    channel_info = _make_channel_info()

    # Build a synthetic "ingested" document. ``samples_segment`` here is
    # small on purpose so the tests exercise the multi-segment path
    # without a million-row array.
    doc = MagicMock()
    doc.document_properties = {
        "daqreader_mfdaq_epochdata_ingested": {
            "parameters": {
                "sample_analog_segment": SEGMENT_SIZE,
                "sample_digital_segment": SEGMENT_SIZE,
            },
            "epochtable": {
                "channels": [
                    {
                        "name": ci.name,
                        "type": ci.type,
                        "number": ci.number,
                        "sample_rate": ci.sample_rate,
                        "group": ci.group,
                    }
                    for ci in channel_info
                ],
                "t0_t1": [(T0, T1)],
            },
        },
    }

    r.getingesteddocument = MagicMock(return_value=doc)
    r.samplerate_ingested = MagicMock(
        return_value=(
            np.array([SR, SR]),
            np.array([0.0, 0.0]),
            np.array([1.0, 1.0]),
        ),
    )
    r.t0_t1_ingested = MagicMock(return_value=[(T0, T1)])
    r.epochtimes2samples_ingested = MagicMock(
        return_value=np.array([0, NUM_SAMPLES - 1]),
    )
    r.getchannelsepoch_ingested = MagicMock(return_value=channel_info)

    return r


def _install_fake_segments(reader, monkeypatch, requested_segments):
    """Route ``session.database_openbinarydoc`` and ``ndicompress.expand_ephys``.

    ``requested_segments`` receives ``(name,)`` tuples in call order so tests
    can assert which segment files the reader tried to open. The fake
    ``expand_ephys`` returns SEGMENT_SIZE rows of a value pinned to the
    segment number, so the tests can spot-check which segment each output
    row came from.
    """

    session = MagicMock()

    def open_binary(_doc, name):
        requested_segments.append(name)
        return _FakeBinaryDoc(name)

    session.database_openbinarydoc = open_binary

    def fake_expand_ephys(_tname_base):
        # ``_tname_base`` is the fake .name we stored; e.g.
        # ``"ai_group1_seg.nbf_3"``.
        seg = int(_tname_base.rsplit("_", 1)[-1])
        # Rows carry the segment number so tests can trace provenance.
        arr = np.full((SEGMENT_SIZE, NUM_CHANNELS_IN_GROUP), float(seg), dtype=float)
        return arr, None

    import ndicompress

    monkeypatch.setattr(ndicompress, "expand_ephys", fake_expand_ephys)

    return session


class TestClampsRequestedWindow:
    """The fix: clamp s0/s1 to what the epoch actually has."""

    def test_read_before_epoch_start_clamps_to_zero(self, reader, monkeypatch):
        """``s0 = -100, s1 = 100`` reads samples 0..100 from segment 1."""
        requested: list[str] = []
        session = _install_fake_segments(reader, monkeypatch, requested)

        data = reader.readchannels_epochsamples_ingested(
            "ai", [1, 2], ["epochid://test"], -100, 100, session
        )

        # Sample 0 through sample 100 inclusive -> 101 rows.
        assert data.shape == (101, 2)
        # Only segment 1 was asked for; ``_seg.nbf_0`` never appears.
        assert requested == ["ai_group1_seg.nbf_1"]
        assert all("_seg.nbf_0" not in name for name in requested)

    def test_read_past_epoch_end_clamps_to_last_sample(self, reader, monkeypatch):
        """``s1`` past the last sample reads through the last real segment."""
        requested: list[str] = []
        session = _install_fake_segments(reader, monkeypatch, requested)

        data = reader.readchannels_epochsamples_ingested(
            "ai", [1, 2], ["epochid://test"], NUM_SAMPLES - 10, NUM_SAMPLES + 100, session
        )

        # Samples 1990..1999 inclusive -> 10 rows.
        assert data.shape == (10, 2)
        # Segment 4 (samples 1500..1999) is the last real one; no segment 5.
        assert requested == ["ai_group1_seg.nbf_4"]

    def test_read_entirely_after_epoch_returns_empty(self, reader, monkeypatch):
        """A window wholly past the epoch returns ``zeros((0, N))``."""
        requested: list[str] = []
        session = _install_fake_segments(reader, monkeypatch, requested)

        data = reader.readchannels_epochsamples_ingested(
            "ai",
            [1, 2],
            ["epochid://test"],
            NUM_SAMPLES + 1,
            NUM_SAMPLES + 100,
            session,
        )

        assert data.shape == (0, 2)
        # No segment was touched -- the reader shortcut out before I/O.
        assert requested == []

    def test_read_entirely_before_epoch_returns_empty(self, reader, monkeypatch):
        """Symmetric case: a window wholly before ``t0`` returns empty."""
        requested: list[str] = []
        session = _install_fake_segments(reader, monkeypatch, requested)

        data = reader.readchannels_epochsamples_ingested(
            "ai", [1, 2], ["epochid://test"], -100, -1, session
        )

        assert data.shape == (0, 2)
        assert requested == []


class TestInfBoundsRegression:
    """Regression guard: the pre-existing +/-Inf clamp survives the new
    finite clamp block."""

    def test_neg_inf_pos_inf_reads_whole_epoch(self, reader, monkeypatch):
        requested: list[str] = []
        session = _install_fake_segments(reader, monkeypatch, requested)

        data = reader.readchannels_epochsamples_ingested(
            "ai", [1, 2], ["epochid://test"], -np.inf, np.inf, session
        )

        # NUM_SAMPLES rows across 4 segments of SEGMENT_SIZE each.
        assert data.shape == (NUM_SAMPLES, 2)
        assert requested == [
            "ai_group1_seg.nbf_1",
            "ai_group1_seg.nbf_2",
            "ai_group1_seg.nbf_3",
            "ai_group1_seg.nbf_4",
        ]


class TestInversionIsAnError:
    """``s0 > s1`` is a coding error, not a request; the check precedes the
    clamp so an inversion is not silently absorbed by clipping one endpoint
    into the other."""

    def test_inverted_bounds_raise(self, reader, monkeypatch):
        session = _install_fake_segments(reader, monkeypatch, [])

        with pytest.raises(ValueError, match="s0 must be less than or equal to s1"):
            reader.readchannels_epochsamples_ingested(
                "ai", [1, 2], ["epochid://test"], 100, 50, session
            )


class TestMissingSegmentIsNotSwallowed:
    """Once s0/s1 are clamped to the epoch's actual range, a per-segment
    ``database_openbinarydoc`` miss is genuine document corruption and must
    surface, not silently NaN-pad."""

    def test_missing_segment_propagates(self, reader, monkeypatch):
        session = MagicMock()
        session.database_openbinarydoc = MagicMock(side_effect=FileNotFoundError("_seg.nbf_2"))

        # Force ``expand_ephys`` never to be reached on the good path either.
        import ndicompress

        monkeypatch.setattr(
            ndicompress,
            "expand_ephys",
            MagicMock(side_effect=AssertionError("should not be reached")),
        )

        with pytest.raises(FileNotFoundError):
            reader.readchannels_epochsamples_ingested(
                "ai", [1, 2], ["epochid://test"], 0, NUM_SAMPLES - 1, session
            )
