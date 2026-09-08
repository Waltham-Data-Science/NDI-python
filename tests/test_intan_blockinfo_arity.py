"""The Intan reader survives NDR growing a return value.

``pyproject.toml`` pins ``ndr[formats] @ git+...NDR-python.git@main``, so
CI installs NDR from its tip on every run and an arity change upstream
reaches this repo the moment it merges -- with no version bump to notice
and no local reproduction, because a developer's installed NDR is
whatever they last resolved.

That happened. VH-Lab/NDR-python#26, "Read a multi-file Intan recording as
one continuous stream", widened ``Intan_RHD2000_blockinfo`` from four
returns to five::

    -> tuple[dict[str, Any], int, int, int]
    -> tuple[dict[str, Any], int, int, int, list[int]]

The fifth is ``file_blocks``, the per-file block counts -- length 1 in
single-file mode, length N in multi-file -- which is what lets the data
reader map a global sample range onto the file holding it. ``t0_t1`` wants
none of it: ``num_data_blocks`` is now summed across every file, which is
already what the total-sample computation needs.

``NDI-python`` unpacked exactly four, so ``t0_t1`` raised
``ValueError: too many values to unpack (expected 4)`` and every
``getprobes()`` on an Intan session went with it. It turned ``main`` red,
not just one branch.

These pin both shapes so the reader keeps working whichever NDR is
installed, and so the next widening upstream is a passing test rather than
a red ``main``.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import ndi.daq.reader.mfdaq.intan as intan_module

SAMPLES_PER_BLOCK = 128
NUM_DATA_BLOCKS = 8
SAMPLE_RATE = 1000.0

#: (total_samples - 1) / rate, with total_samples = 128 * 8.
EXPECTED_T1 = (SAMPLES_PER_BLOCK * NUM_DATA_BLOCKS - 1) / SAMPLE_RATE


def _blockinfo_returning(*values):
    def stub(filename, header):
        return values

    return stub


@pytest.fixture
def reader():
    obj = intan_module.ndi_daq_reader_mfdaq_intan()
    with (
        patch.object(
            obj,
            "_get_header",
            lambda epochfiles: {"frequency_parameters": {"amplifier_sample_rate": SAMPLE_RATE}},
        ),
        patch.object(obj, "_rhd_file", lambda epochfiles: "epoch.rhd"),
    ):
        yield obj


class TestT0T1AcceptsEitherArity:
    def test_the_four_value_shape_still_works(self, reader):
        """NDR before #26, and any pinned older install."""
        stub = _blockinfo_returning(
            {"samples_per_block": SAMPLES_PER_BLOCK}, 100, 1000, NUM_DATA_BLOCKS
        )
        with patch.object(intan_module, "Intan_RHD2000_blockinfo", stub):
            assert reader.t0_t1(["epoch.rhd"]) == [(0.0, EXPECTED_T1)]

    def test_the_five_value_shape_works(self, reader):
        """NDR at main: the fifth value is file_blocks."""
        stub = _blockinfo_returning(
            {"samples_per_block": SAMPLES_PER_BLOCK},
            100,
            1000,
            NUM_DATA_BLOCKS,
            [NUM_DATA_BLOCKS],
        )
        with patch.object(intan_module, "Intan_RHD2000_blockinfo", stub):
            assert reader.t0_t1(["epoch.rhd"]) == [(0.0, EXPECTED_T1)]

    def test_a_multi_file_recording_reads_as_one_stream(self, reader):
        """What NDR#26 is for: num_data_blocks is the sum across files, so
        t0_t1 spans the whole recording rather than its first file."""
        per_file = [3, 5]
        stub = _blockinfo_returning(
            {"samples_per_block": SAMPLES_PER_BLOCK},
            100,
            1000,
            sum(per_file),
            per_file,
        )
        with patch.object(intan_module, "Intan_RHD2000_blockinfo", stub):
            assert reader.t0_t1(["epoch.rhd"]) == [(0.0, EXPECTED_T1)]

    def test_a_further_widening_would_not_break_it(self, reader):
        """The point of slicing rather than positional unpacking: this repo
        tracks NDR's main branch, so the next added return value must widen
        the total rather than break the call."""
        stub = _blockinfo_returning(
            {"samples_per_block": SAMPLES_PER_BLOCK},
            100,
            1000,
            NUM_DATA_BLOCKS,
            [NUM_DATA_BLOCKS],
            "something NDR adds next",
        )
        with patch.object(intan_module, "Intan_RHD2000_blockinfo", stub):
            assert reader.t0_t1(["epoch.rhd"]) == [(0.0, EXPECTED_T1)]
