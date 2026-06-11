"""
Tests for VHSB binary I/O and element_timeseries persistence (audit C8).

The previous code wrote only ``datapoints.tobytes()`` (no header, time axis
dropped) to the wrong filename. These tests pin the VHSB round-trip and the
full addepoch -> readtimeseries flow that now preserves the time axis.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from ndi.element_timeseries import ndi_element_timeseries
from ndi.session.dir import ndi_session_dir
from ndi.time.clocktype import ndi_time_clocktype
from ndi.util.vhsb import HEADER_SIZE, vhsb_read, vhsb_write


class TestVHSBRoundTrip:
    def test_scalar_roundtrip(self, tmp_path):
        x = np.arange(0.0, 1.0, 0.001)
        y = np.sin(2 * np.pi * 5 * x)
        f = tmp_path / "a.vhsb"
        vhsb_write(f, x, y)
        # Byte layout: 1836-byte header + 16 bytes/sample (X float64 + Y float64).
        assert f.stat().st_size == HEADER_SIZE + len(x) * 16
        y2, x2 = vhsb_read(f)
        assert np.allclose(x, x2)
        assert np.allclose(y, y2)

    def test_windowed_read(self, tmp_path):
        x = np.arange(0.0, 1.0, 0.001)
        y = x * 2
        f = tmp_path / "b.vhsb"
        vhsb_write(f, x, y)
        y2, x2 = vhsb_read(f, 0.1, 0.2)
        assert x2[0] >= 0.099 and x2[-1] <= 0.201
        assert np.allclose(y2, x2 * 2)

    def test_multichannel(self, tmp_path):
        x = np.arange(0.0, 0.5, 0.001)
        y = np.column_stack([x, x * 2, x * 3])
        f = tmp_path / "c.vhsb"
        vhsb_write(f, x, y)
        y2, x2 = vhsb_read(f)
        assert y2.shape == (len(x), 3)
        assert np.allclose(y, y2)

    def test_nonconstant_interval(self, tmp_path):
        x = np.array([0.0, 0.1, 0.5, 0.9, 2.0])
        y = np.array([10.0, 20.0, 30.0, 40.0, 50.0])
        f = tmp_path / "d.vhsb"
        vhsb_write(f, x, y)
        y2, x2 = vhsb_read(f, 0.1, 0.9)
        assert np.allclose(x2, [0.1, 0.5, 0.9])
        assert np.allclose(y2, [20.0, 30.0, 40.0])


class TestElementTimeseriesPersistence:
    @pytest.fixture
    def session(self, tmp_path):
        p = tmp_path / "sess"
        p.mkdir()
        return ndi_session_dir("T", p)

    def test_addepoch_readtimeseries_roundtrip(self, session):
        e = ndi_element_timeseries(
            session=session, name="unit1", reference=1, type="spikes", direct=False
        )
        x = np.arange(0.0, 1.0, 0.001)
        y = np.sin(2 * np.pi * 7 * x)
        e, doc = e.addepoch(
            "ep1", [ndi_time_clocktype.DEV_LOCAL_TIME], [(0.0, 1.0)], timepoints=x, datapoints=y
        )
        data, times, ref = e.readtimeseries(1)
        assert np.allclose(data.reshape(-1), y)  # data preserved
        assert np.allclose(times, x)  # TIME AXIS preserved (C8)
        assert ref is not None  # real timeref returned, not None (C8)
        assert ref.epoch == "ep1"

    def test_stored_file_is_named_epoch_binary_data(self, session):
        e = ndi_element_timeseries(
            session=session, name="unit2", reference=1, type="spikes", direct=False
        )
        x = np.arange(0.0, 0.1, 0.001)
        e, doc = e.addepoch(
            "ep1", [ndi_time_clocktype.DEV_LOCAL_TIME], [(0.0, 0.1)], timepoints=x, datapoints=x
        )
        # The binary must be attached under the schema-declared name.
        exists, path = session.database_existbinarydoc(doc, "epoch_binary_data.vhsb")
        assert exists
        assert Path(path).stat().st_size > HEADER_SIZE

    def test_read_by_epoch_id_string(self, session):
        e = ndi_element_timeseries(
            session=session, name="unit3", reference=1, type="spikes", direct=False
        )
        x = np.arange(0.0, 0.2, 0.001)
        y = np.cos(x)
        e, doc = e.addepoch(
            "epA", [ndi_time_clocktype.DEV_LOCAL_TIME], [(0.0, 0.2)], timepoints=x, datapoints=y
        )
        data, times, ref = e.readtimeseries("epA")
        assert np.allclose(data.reshape(-1), y)

    def test_windowed_readtimeseries(self, session):
        e = ndi_element_timeseries(
            session=session, name="unit4", reference=1, type="spikes", direct=False
        )
        x = np.arange(0.0, 1.0, 0.001)
        y = x.copy()
        e, doc = e.addepoch(
            "ep1", [ndi_time_clocktype.DEV_LOCAL_TIME], [(0.0, 1.0)], timepoints=x, datapoints=y
        )
        data, times, ref = e.readtimeseries(1, 0.25, 0.30)
        assert times[0] >= 0.24 and times[-1] <= 0.31
