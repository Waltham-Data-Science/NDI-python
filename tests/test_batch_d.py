"""
Tests for Batch D: ndi_gui_Lab-specific + advanced.

Tests ndi_daq_metadatareader_NewStimStims, ndi_daq_metadatareader_NielsenLabStims,
ndi_probe_timeseries_stimulator, downsample, downsample_timeseries.
"""

import os
import tempfile
from types import SimpleNamespace

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
from ndi.daq.metadatareader import ndi_daq_metadatareader, ndi_daq_metadatareader_NewStimStims, ndi_daq_metadatareader_NielsenLabStims
from ndi.daq.metadatareader.newstim_stims import ndi_daq_metadatareader_NewStimStims as NewStimDirect
from ndi.daq.metadatareader.nielsenlab_stims import ndi_daq_metadatareader_NielsenLabStims as NielsenDirect
from ndi.element.functions import downsample, downsample_timeseries
from ndi.probe.timeseries_stimulator import ndi_probe_timeseries_stimulator


class TestImports:
    """Verify all Batch D classes are importable."""

    def test_import_newstim_from_package(self):
        assert ndi_daq_metadatareader_NewStimStims is NewStimDirect

    def test_import_nielsen_from_package(self):
        assert ndi_daq_metadatareader_NielsenLabStims is NielsenDirect

    def test_import_stimulator(self):
        assert ndi_probe_timeseries_stimulator is not None

    def test_import_downsample_functions(self):
        assert downsample is not None
        assert downsample_timeseries is not None

    def test_metadatareader_still_importable_from_daq(self):
        from ndi.daq import ndi_daq_metadatareader as MR

        assert MR is ndi_daq_metadatareader

    def test_readers_importable_from_daq(self):
        from ndi.daq import ndi_daq_metadatareader_NewStimStims as NS
        from ndi.daq import ndi_daq_metadatareader_NielsenLabStims as NL

        assert NS is ndi_daq_metadatareader_NewStimStims
        assert NL is ndi_daq_metadatareader_NielsenLabStims


# ===========================================================================
# ndi_daq_metadatareader_NewStimStims
# ===========================================================================


class TestNewStimStimsReader:
    """Tests for the NewStim metadata reader."""

    def test_init(self):
        reader = ndi_daq_metadatareader_NewStimStims()
        assert isinstance(reader, ndi_daq_metadatareader)
        assert reader.tab_separated_file_parameter == ""

    def test_init_with_tsv_pattern(self):
        reader = ndi_daq_metadatareader_NewStimStims(tsv_pattern=r"stim\.tsv")
        assert reader.tab_separated_file_parameter == r"stim\.tsv"

    def test_stim_file_pattern(self):
        assert "stims" in ndi_daq_metadatareader_NewStimStims.STIM_FILE_PATTERN

    def test_find_stim_file_found(self):
        reader = ndi_daq_metadatareader_NewStimStims()
        result = reader._find_stim_file(["data.rhd", "events.nev", "stims.mat"])
        assert result == "stims.mat"

    def test_find_stim_file_not_found(self):
        reader = ndi_daq_metadatareader_NewStimStims()
        result = reader._find_stim_file(["data.rhd", "events.nev"])
        assert result is None

    def test_find_stim_file_case_insensitive(self):
        reader = ndi_daq_metadatareader_NewStimStims()
        result = reader._find_stim_file(["data.rhd", "Stims.MAT"])
        assert result == "Stims.MAT"

    def test_readmetadata_no_stim_file(self):
        reader = ndi_daq_metadatareader_NewStimStims()
        result = reader.readmetadata(["data.rhd", "events.nev"])
        assert result == []

    def test_readmetadata_falls_back_to_tsv(self):
        """With a TSV pattern set, tries TSV first."""
        reader = ndi_daq_metadatareader_NewStimStims(tsv_pattern=r"nonexistent\.tsv")
        # No matching TSV and no stims.mat → empty
        result = reader.readmetadata(["data.rhd"])
        assert result == []

    def test_read_newstim_mat_nonexistent(self):
        reader = ndi_daq_metadatareader_NewStimStims()
        result = reader._read_newstim_mat("/nonexistent/stims.mat")
        # scipy may or may not be installed
        # If scipy not installed, raises ImportError
        # If installed, returns [] for nonexistent file
        assert isinstance(result, list)

    def test_extract_script_parameters_empty(self):
        result = ndi_daq_metadatareader_NewStimStims._extract_script_parameters(np.array([]))
        assert isinstance(result, list)

    def test_repr(self):
        reader = ndi_daq_metadatareader_NewStimStims()
        assert "ndi_daq_metadatareader_NewStimStims" in repr(reader)


# ===========================================================================
# ndi_daq_metadatareader_NielsenLabStims
# ===========================================================================


class TestNielsenLabStimsReader:
    """Tests for the Nielsen ndi_gui_Lab metadata reader."""

    def test_init(self):
        reader = ndi_daq_metadatareader_NielsenLabStims()
        assert isinstance(reader, ndi_daq_metadatareader)

    def test_analyzer_file_pattern(self):
        assert "analyzer" in ndi_daq_metadatareader_NielsenLabStims.ANALYZER_FILE_PATTERN

    def test_find_analyzer_file_found(self):
        reader = ndi_daq_metadatareader_NielsenLabStims()
        result = reader._find_analyzer_file(["data.rhd", "analyzer.mat"])
        assert result == "analyzer.mat"

    def test_find_analyzer_file_not_found(self):
        reader = ndi_daq_metadatareader_NielsenLabStims()
        result = reader._find_analyzer_file(["data.rhd"])
        assert result is None

    def test_readmetadata_no_analyzer(self):
        reader = ndi_daq_metadatareader_NielsenLabStims()
        result = reader.readmetadata(["data.rhd"])
        assert result == []

    def test_extract_stimulus_parameters_empty(self):
        # Create a minimal structured array with correct dtype
        dt = np.dtype([("M", "O"), ("P", "O"), ("loops", "O")])
        analyzer = np.zeros((), dtype=dt)
        result = ndi_daq_metadatareader_NielsenLabStims.extract_stimulus_parameters(analyzer)
        assert isinstance(result, list)

    def test_extract_display_order_empty(self):
        dt = np.dtype([("loops", "O")])
        analyzer = np.zeros((), dtype=dt)
        result = ndi_daq_metadatareader_NielsenLabStims.extract_display_order(analyzer)
        assert isinstance(result, list)

    def test_repr(self):
        reader = ndi_daq_metadatareader_NielsenLabStims()
        assert "ndi_daq_metadatareader_NielsenLabStims" in repr(reader)


# ===========================================================================
# ndi_daq_metadatareader (regression - ensure package refactoring didn't break)
# ===========================================================================


class TestMetadataReaderRegression:
    """Verify ndi_daq_metadatareader still works after file→package refactoring."""

    def test_base_class_works(self):
        reader = ndi_daq_metadatareader()
        assert reader.tab_separated_file_parameter == ""

    def test_base_readmetadata_empty_pattern(self):
        reader = ndi_daq_metadatareader()
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
            reader = ndi_daq_metadatareader(tsv_pattern=os.path.basename(filepath))
            result = reader.readmetadata([filepath])
            assert len(result) == 2
            assert result[0]["STIMID"] == 1
            assert result[0]["angle"] == 0
            assert result[1]["contrast"] == 1.0
        finally:
            os.unlink(filepath)

    def test_equality(self):
        r1 = ndi_daq_metadatareader(tsv_pattern="test")
        r2 = ndi_daq_metadatareader(tsv_pattern="test")
        assert r1 == r2

    def test_inequality(self):
        r1 = ndi_daq_metadatareader(tsv_pattern="test")
        r2 = ndi_daq_metadatareader(tsv_pattern="other")
        assert r1 != r2

    def test_newdocument_class_name(self):
        """Verify the reader knows its own class for serialization."""
        reader = ndi_daq_metadatareader(tsv_pattern="stim.tsv")
        assert reader.__class__.__name__ == "ndi_daq_metadatareader"
        assert reader.tab_separated_file_parameter == "stim.tsv"


# ===========================================================================
# ndi_probe_timeseries_stimulator
# ===========================================================================


class TestProbeTimeseriesStimulator:
    """Tests for the stimulus delivery probe."""

    def test_init(self):
        stim = ndi_probe_timeseries_stimulator()
        assert stim._type == "stimulator"

    def test_init_with_args(self):
        session = SimpleNamespace(
            id=lambda: "s1",
            database_search=lambda q: [],
        )
        stim = ndi_probe_timeseries_stimulator(
            session=session,
            name="vis_stim",
            reference=2,
        )
        assert stim._name == "vis_stim"
        assert stim._reference == 2

    def test_inherits_probe_timeseries(self):
        from ndi.probe.timeseries import ndi_probe_timeseries

        assert issubclass(ndi_probe_timeseries_stimulator, ndi_probe_timeseries)

    def test_readtimeseriesepoch_no_session(self):
        stim = ndi_probe_timeseries_stimulator()
        data, times, timeref = stim.readtimeseriesepoch(1, 0, 10)
        assert data is None
        assert times is None
        assert timeref is None

    def test_readtimeseriesepoch_with_session(self):
        session = SimpleNamespace(
            id=lambda: "s1",
            database_search=lambda q: [],
        )
        stim = ndi_probe_timeseries_stimulator(session=session, name="test")
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
        stim = ndi_probe_timeseries_stimulator()
        result = stim.parse_marker_data(np.array([]), np.array([]))
        assert len(result["stimid"]) == 0
        assert len(result["stimon"]) == 0
        assert len(result["stimoff"]) == 0
        assert result["stimopenclose"].shape == (0, 2)

    def test_parse_marker_data_onset_offset(self):
        stim = ndi_probe_timeseries_stimulator()
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
        stim = ndi_probe_timeseries_stimulator()
        assert stim._get_epoch_timeref(1) is None

    def test_get_epoch_timeref_with_session(self):
        from ndi.time import ndi_time_clocktype

        session = SimpleNamespace(id=lambda: "s1")
        stim = ndi_probe_timeseries_stimulator(session=session)
        assert stim._get_epoch_timeref(1) == ndi_time_clocktype.DEV_LOCAL_TIME

    def test_repr(self):
        stim = ndi_probe_timeseries_stimulator(name="vis")
        assert "ndi_probe_timeseries_stimulator" in repr(stim)
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
        from ndi.element import ndi_element

        session = SimpleNamespace(id=lambda: "s1")
        element_in = SimpleNamespace(
            epochtable=lambda: [{"epoch_id": "e1"}],
            _type="timeseries",
        )
        result = downsample(session, element_in, 100.0, "ds_out", 1)
        assert isinstance(result, ndi_element)


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
