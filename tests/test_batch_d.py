"""
Tests for Batch D: Lab-specific + advanced.

Tests NewStimStimsReader, NielsenLabStimsReader,
ProbeTimeseriesStimulator, downsample, downsample_timeseries.
"""

import os
import tempfile
from types import SimpleNamespace

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
from ndi.daq.metadatareader import MetadataReader, NewStimStimsReader, NielsenLabStimsReader
from ndi.daq.metadatareader.newstim_stims import NewStimStimsReader as NewStimDirect
from ndi.daq.metadatareader.nielsenlab_stims import NielsenLabStimsReader as NielsenDirect
from ndi.element.functions import downsample, downsample_timeseries
from ndi.probe.timeseries_stimulator import ProbeTimeseriesStimulator


class TestImports:
    """Verify all Batch D classes are importable."""

    def test_import_newstim_from_package(self):
        assert NewStimStimsReader is NewStimDirect

    def test_import_nielsen_from_package(self):
        assert NielsenLabStimsReader is NielsenDirect

    def test_import_stimulator(self):
        assert ProbeTimeseriesStimulator is not None

    def test_import_downsample_functions(self):
        assert downsample is not None
        assert downsample_timeseries is not None

    def test_metadatareader_still_importable_from_daq(self):
        from ndi.daq import MetadataReader as MR

        assert MR is MetadataReader

    def test_readers_importable_from_daq(self):
        from ndi.daq import NewStimStimsReader as NS
        from ndi.daq import NielsenLabStimsReader as NL

        assert NS is NewStimStimsReader
        assert NL is NielsenLabStimsReader


# ===========================================================================
# NewStimStimsReader
# ===========================================================================


class TestNewStimStimsReader:
    """Tests for the NewStim metadata reader."""

    def test_init(self):
        reader = NewStimStimsReader()
        assert isinstance(reader, MetadataReader)
        assert reader.tab_separated_file_parameter == ""

    def test_init_with_tsv_pattern(self):
        reader = NewStimStimsReader(tsv_pattern=r"stim\.tsv")
        assert reader.tab_separated_file_parameter == r"stim\.tsv"

    def test_stim_file_pattern(self):
        assert "stims" in NewStimStimsReader.STIM_FILE_PATTERN

    def test_find_stim_file_found(self):
        reader = NewStimStimsReader()
        result = reader._find_stim_file(["data.rhd", "events.nev", "stims.mat"])
        assert result == "stims.mat"

    def test_find_stim_file_not_found(self):
        reader = NewStimStimsReader()
        result = reader._find_stim_file(["data.rhd", "events.nev"])
        assert result is None

    def test_find_stim_file_case_insensitive(self):
        reader = NewStimStimsReader()
        result = reader._find_stim_file(["data.rhd", "Stims.MAT"])
        assert result == "Stims.MAT"

    def test_readmetadata_no_stim_file(self):
        reader = NewStimStimsReader()
        result = reader.readmetadata(["data.rhd", "events.nev"])
        assert result == []

    def test_readmetadata_falls_back_to_tsv(self):
        """With a TSV pattern set, tries TSV first."""
        reader = NewStimStimsReader(tsv_pattern=r"nonexistent\.tsv")
        # No matching TSV and no stims.mat → empty
        result = reader.readmetadata(["data.rhd"])
        assert result == []

    def test_read_newstim_mat_nonexistent(self):
        reader = NewStimStimsReader()
        result = reader._read_newstim_mat("/nonexistent/stims.mat")
        # scipy may or may not be installed
        # If scipy not installed, raises ImportError
        # If installed, returns [] for nonexistent file
        assert isinstance(result, list)

    def test_extract_script_parameters_empty(self):
        result = NewStimStimsReader._extract_script_parameters(np.array([]))
        assert isinstance(result, list)

    def test_repr(self):
        reader = NewStimStimsReader()
        assert "NewStimStimsReader" in repr(reader)


# ===========================================================================
# NielsenLabStimsReader
# ===========================================================================


class TestNielsenLabStimsReader:
    """Tests for the Nielsen Lab metadata reader."""

    def test_init(self):
        reader = NielsenLabStimsReader()
        assert isinstance(reader, MetadataReader)

    def test_analyzer_file_pattern(self):
        assert "analyzer" in NielsenLabStimsReader.ANALYZER_FILE_PATTERN

    def test_find_analyzer_file_found(self):
        reader = NielsenLabStimsReader()
        result = reader._find_analyzer_file(["data.rhd", "analyzer.mat"])
        assert result == "analyzer.mat"

    def test_find_analyzer_file_not_found(self):
        reader = NielsenLabStimsReader()
        result = reader._find_analyzer_file(["data.rhd"])
        assert result is None

    def test_readmetadata_no_analyzer(self):
        reader = NielsenLabStimsReader()
        result = reader.readmetadata(["data.rhd"])
        assert result == []

    def test_extract_stimulus_parameters_empty(self):
        # Create a minimal structured array with correct dtype
        dt = np.dtype([("M", "O"), ("P", "O"), ("loops", "O")])
        analyzer = np.zeros((), dtype=dt)
        result = NielsenLabStimsReader.extract_stimulus_parameters(analyzer)
        assert isinstance(result, list)

    def test_extract_display_order_empty(self):
        dt = np.dtype([("loops", "O")])
        analyzer = np.zeros((), dtype=dt)
        result = NielsenLabStimsReader.extract_display_order(analyzer)
        assert isinstance(result, list)

    def test_repr(self):
        reader = NielsenLabStimsReader()
        assert "NielsenLabStimsReader" in repr(reader)


# ===========================================================================
# MetadataReader (regression - ensure package refactoring didn't break)
# ===========================================================================


class TestMetadataReaderRegression:
    """Verify MetadataReader still works after file→package refactoring."""

    def test_base_class_works(self):
        reader = MetadataReader()
        assert reader.tab_separated_file_parameter == ""

    def test_base_readmetadata_empty_pattern(self):
        reader = MetadataReader()
        result = reader.readmetadata(["file.txt"])
        assert result == []

    def test_base_readmetadata_from_tsv(self):
        """Write a TSV file and read it."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            f.write("STIMID\tangle\tcontrast\n")
            f.write("1\t0\t0.5\n")
            f.write("2\t90\t1.0\n")
            filepath = f.name

        try:
            reader = MetadataReader(tsv_pattern=os.path.basename(filepath))
            result = reader.readmetadata([filepath])
            assert len(result) == 2
            assert result[0]["STIMID"] == 1
            assert result[0]["angle"] == 0
            assert result[1]["contrast"] == 1.0
        finally:
            os.unlink(filepath)

    def test_equality(self):
        r1 = MetadataReader(tsv_pattern="test")
        r2 = MetadataReader(tsv_pattern="test")
        assert r1 == r2

    def test_inequality(self):
        r1 = MetadataReader(tsv_pattern="test")
        r2 = MetadataReader(tsv_pattern="other")
        assert r1 != r2

    def test_newdocument_class_name(self):
        """Verify the reader knows its own class for serialization."""
        reader = MetadataReader(tsv_pattern="stim.tsv")
        assert reader.__class__.__name__ == "MetadataReader"
        assert reader.tab_separated_file_parameter == "stim.tsv"


# ===========================================================================
# ProbeTimeseriesStimulator
# ===========================================================================


class TestProbeTimeseriesStimulator:
    """Tests for the stimulus delivery probe."""

    def test_init(self):
        stim = ProbeTimeseriesStimulator()
        assert stim._type == "stimulator"

    def test_init_with_args(self):
        session = SimpleNamespace(
            id=lambda: "s1",
            database_search=lambda q: [],
        )
        stim = ProbeTimeseriesStimulator(
            session=session,
            name="vis_stim",
            reference=2,
        )
        assert stim._name == "vis_stim"
        assert stim._reference == 2

    def test_inherits_probe_timeseries(self):
        from ndi.probe.timeseries import ProbeTimeseries

        assert issubclass(ProbeTimeseriesStimulator, ProbeTimeseries)

    def test_readtimeseriesepoch_no_session(self):
        stim = ProbeTimeseriesStimulator()
        data, times, timeref = stim.readtimeseriesepoch(1, 0, 10)
        assert data is None
        assert times is None
        assert timeref is None

    def test_readtimeseriesepoch_with_session(self):
        session = SimpleNamespace(
            id=lambda: "s1",
            database_search=lambda q: [],
        )
        stim = ProbeTimeseriesStimulator(session=session, name="test")
        data, times, timeref = stim.readtimeseriesepoch(1, 0, 10)
        assert isinstance(data, dict)
        assert "stimid" in data
        assert "parameters" in data
        assert "analog" in data
        assert isinstance(times, dict)
        assert "stimon" in times
        assert "stimoff" in times
        assert "stimopenclose" in times
        assert "stimevents" in times

    def test_parse_marker_data_empty(self):
        stim = ProbeTimeseriesStimulator()
        result = stim.parse_marker_data(np.array([]), np.array([]))
        assert len(result["stimid"]) == 0
        assert len(result["stimon"]) == 0
        assert len(result["stimoff"]) == 0
        assert result["stimopenclose"].shape == (0, 2)

    def test_parse_marker_data_onset_offset(self):
        stim = ProbeTimeseriesStimulator()
        # 3 marker channels: on/off, stim_id, setup/clear
        timestamps = np.array(
            [
                [1.0, 1.0, 0.5],  # stim on, id=1, setup
                [2.0, 2.0, 3.0],  # stim off (val=-1), (ignored), clear
            ]
        )
        values = np.array(
            [
                [1.0, 1.0, 1.0],  # on, id=1, setup
                [-1.0, 0.0, -1.0],  # off, no id, clear
            ]
        )
        result = stim.parse_marker_data(timestamps, values)
        assert len(result["stimon"]) == 1
        assert result["stimon"][0] == 1.0
        assert len(result["stimoff"]) == 1
        assert result["stimoff"][0] == 2.0
        assert len(result["stimid"]) == 1
        assert result["stimid"][0] == 1
        assert result["stimopenclose"].shape == (1, 2)
        assert result["stimopenclose"][0, 0] == 0.5
        assert result["stimopenclose"][0, 1] == 3.0

    def test_get_epoch_timeref_no_session(self):
        stim = ProbeTimeseriesStimulator()
        assert stim._get_epoch_timeref(1) is None

    def test_get_epoch_timeref_with_session(self):
        from ndi.time import ClockType

        session = SimpleNamespace(id=lambda: "s1")
        stim = ProbeTimeseriesStimulator(session=session)
        assert stim._get_epoch_timeref(1) == ClockType.DEV_LOCAL_TIME

    def test_repr(self):
        stim = ProbeTimeseriesStimulator(name="vis")
        assert "ProbeTimeseriesStimulator" in repr(stim)
        assert "vis" in repr(stim)


# ===========================================================================
# downsample
# ===========================================================================


class TestDownsample:
    """Tests for the element downsample function."""

    def test_downsample_no_epochs_raises(self):
        session = SimpleNamespace(id=lambda: "s1")
        element_in = SimpleNamespace(epochtable=lambda: [])
        with pytest.raises(ValueError, match="no epochs"):
            downsample(session, element_in, 100.0, "ds_out", 1)

    def test_downsample_negative_freq_raises(self):
        session = SimpleNamespace(id=lambda: "s1")
        element_in = SimpleNamespace(
            epochtable=lambda: [{"epoch_id": "e1"}],
            _type="timeseries",
        )
        with pytest.raises(ValueError, match="positive"):
            downsample(session, element_in, -10.0, "ds_out", 1)

    def test_downsample_returns_element(self):
        from ndi.element import Element

        session = SimpleNamespace(id=lambda: "s1")
        element_in = SimpleNamespace(
            epochtable=lambda: [{"epoch_id": "e1"}],
            _type="timeseries",
        )
        result = downsample(session, element_in, 100.0, "ds_out", 1)
        assert isinstance(result, Element)


# ===========================================================================
# downsample_timeseries
# ===========================================================================


class TestDownsampleTimeseries:
    """Tests for the low-level timeseries downsampling."""

    def test_short_signal_passthrough(self):
        """Signal with <2 samples is returned unchanged."""
        t = np.array([0.0])
        d = np.array([1.0])
        t_out, d_out = downsample_timeseries(t, d, 100.0)
        np.testing.assert_array_equal(t_out, t)
        np.testing.assert_array_equal(d_out, d)

    def test_no_downsample_if_fs_below_nyquist(self):
        """If fs <= 2*lp_freq, return unchanged."""
        fs = 100.0  # Hz
        N = 1000
        t = np.arange(N) / fs
        d = np.random.randn(N)
        # lp_freq = 60 → 2*60=120 > fs=100, so no downsampling
        t_out, d_out = downsample_timeseries(t, d, 60.0)
        np.testing.assert_array_equal(t_out, t)
        np.testing.assert_array_equal(d_out, d)

    def test_downsample_reduces_length(self):
        """Downsampling a high-rate signal should reduce sample count."""
        pytest.importorskip("scipy")
        fs = 10000.0  # 10 kHz
        N = 10000
        t = np.arange(N) / fs
        d = np.random.randn(N)
        # lp_freq = 500 → Nyquist = 1000 Hz → decimate by 10
        t_out, d_out = downsample_timeseries(t, d, 500.0)
        assert len(t_out) < len(t)
        assert len(d_out) < len(d)
        # Should be approximately N/10
        assert abs(len(t_out) - 1000) < 10

    def test_downsample_multichannel(self):
        """Multi-channel data maintains channel count."""
        pytest.importorskip("scipy")
        fs = 5000.0
        N = 5000
        C = 4
        t = np.arange(N) / fs
        d = np.random.randn(N, C)
        t_out, d_out = downsample_timeseries(t, d, 200.0)
        assert d_out.ndim == 2
        assert d_out.shape[1] == C
        assert len(t_out) == d_out.shape[0]

    def test_downsample_1d_stays_1d(self):
        """1D input stays 1D after downsampling."""
        pytest.importorskip("scipy")
        fs = 5000.0
        N = 5000
        t = np.arange(N) / fs
        d = np.random.randn(N)
        t_out, d_out = downsample_timeseries(t, d, 200.0)
        assert d_out.ndim == 1

    def test_downsample_preserves_low_freq(self):
        """Low-frequency signal should be preserved after downsampling."""
        pytest.importorskip("scipy")
        fs = 10000.0
        N = 10000
        t = np.arange(N) / fs
        # 10 Hz sine - well below 500 Hz cutoff
        d = np.sin(2 * np.pi * 10 * t)
        t_out, d_out = downsample_timeseries(t, d, 500.0)
        # Check that the 10 Hz oscillation is preserved
        # The downsampled signal should still look like a sine wave
        assert d_out.max() > 0.8
        assert d_out.min() < -0.8
