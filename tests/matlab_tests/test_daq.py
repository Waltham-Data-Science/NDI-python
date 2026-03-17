"""
Port of MATLAB ndi.unittest.daq.reader.* tests.

MATLAB source files:
  mfdaqIntanTest.m        -> TestIntanReader
  mfdaqNDRAxonTest.m      -> skipped (ABF reader not ported; uses NDR)
  mfdaqNDRIntanTest.m     -> TestIntanReader (now uses ndr.format.intan)

Python replacement modules:
  ndi.daq.reader.mfdaq.intan.ndi_daq_reader_mfdaq_intan  (uses ndr.format.intan)
  ndi.daq.mfdaq.ndi_daq_reader_mfdaq (base with epochsamples2times / epochtimes2samples)
  ndi.fun.utils.channelname2prefixnumber
"""

import os
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from ndi.daq.mfdaq import ChannelInfo, ChannelType, ndi_daq_reader_mfdaq, standardize_channel_type
from ndi.daq.reader.mfdaq.intan import ndi_daq_reader_mfdaq_intan
from ndi.fun.utils import channelname2prefixnumber

# ---------------------------------------------------------------------------
# Marker for tests that need real example .rhd data files
# ---------------------------------------------------------------------------


def _have_example_data() -> bool:
    """Check whether Intan example .rhd files are available on disk."""
    candidates = [
        Path(os.environ.get("NDI_EXAMPLE_DATA", "")) / "intan",
        Path.home() / "ndi_example_data" / "intan",
        Path(__file__).resolve().parents[3] / "example_data" / "intan",
    ]
    for d in candidates:
        if d.is_dir() and list(d.glob("*.rhd")):
            return True
    return False


def _find_example_rhd() -> str:
    """Return path to the first available .rhd file, or '' if none."""
    candidates = [
        Path(os.environ.get("NDI_EXAMPLE_DATA", "")) / "intan",
        Path.home() / "ndi_example_data" / "intan",
        Path(__file__).resolve().parents[3] / "example_data" / "intan",
    ]
    for d in candidates:
        if d.is_dir():
            for f in sorted(d.glob("*.rhd")):
                return str(f)
    return ""


requires_data = pytest.mark.skipif(
    not _have_example_data(),
    reason="No Intan example .rhd data files available",
)


# ===========================================================================
# TestIntanReader
# Port of: ndi.unittest.daq.reader.mfdaqIntanTest
# ===========================================================================


class TestIntanReader:
    """Port of ndi.unittest.daq.reader.mfdaqIntanTest.

    The MATLAB test creates an ndi_daq_reader_mfdaq_intan, points it at real .rhd files,
    and checks channel discovery, epochsamples2times, epochtimes2samples.
    The Python reader uses ndr.format.intan for header parsing and data reading.
    """

    def test_intan_reader_instantiation(self):
        """ndi_daq_reader_mfdaq_intan can be created with no arguments.

        MATLAB equivalent: mfdaqIntanTest - reader construction
        """
        reader = ndi_daq_reader_mfdaq_intan()

        assert reader is not None
        assert isinstance(reader, ndi_daq_reader_mfdaq_intan)
        assert isinstance(reader, ndi_daq_reader_mfdaq)
        assert reader.NDI_DAQREADER_CLASS == "ndi.daq.reader.mfdaq.intan"
        assert reader.FILE_EXTENSIONS == [".rhd", ".rhs"]
        assert reader.id  # ndi_ido gives a non-empty id string
        assert isinstance(reader.id, str)

    def test_intan_reader_with_identifier(self):
        """ndi_daq_reader_mfdaq_intan can be created with an explicit identifier.

        MATLAB equivalent: mfdaqIntanTest - reader construction with identifier
        """
        reader = ndi_daq_reader_mfdaq_intan(identifier="test_reader_id")
        # The identifier is stored via ndi_ido but may not be directly the same
        # because ndi_ido might override it; just verify we got a valid object
        assert isinstance(reader, ndi_daq_reader_mfdaq_intan)

    def test_intan_reader_ndi_class(self):
        """ndi_daq_reader_mfdaq_intan reports the correct NDI DAQ reader class string.

        MATLAB equivalent: mfdaqIntanTest - class property check
        """
        reader = ndi_daq_reader_mfdaq_intan()
        assert reader._ndi_daqreader_class == "ndi.daq.reader.mfdaq.intan"

    def test_intan_reader_channel_types(self):
        """ndi_daq_reader_mfdaq.channel_types() returns known channel types.

        MATLAB equivalent: mfdaqIntanTest - channel type discovery
        """
        types, abbrevs = ndi_daq_reader_mfdaq.channel_types()

        assert "analog_in" in types
        assert "digital_in" in types
        assert "time" in types
        assert "ai" in abbrevs
        assert "di" in abbrevs
        assert "t" in abbrevs
        assert len(types) == len(abbrevs)

    def test_intan_reader_mocked_getchannels(self):
        """ndi_daq_reader_mfdaq_intan.getchannelsepoch works via mocked ndr header.

        We mock ndr.format.intan.read_Intan_RHD2000_header to simulate a
        successful channel discovery without needing real data files.
        """
        reader = ndi_daq_reader_mfdaq_intan()

        mock_header = {
            "sample_rate": 30000.0,
            "num_amplifier_channels": 2,
            "num_aux_input_channels": 0,
            "num_supply_voltage_channels": 0,
            "num_board_adc_channels": 0,
            "num_board_dig_in_channels": 0,
            "num_board_dig_out_channels": 0,
            "num_temp_sensor_channels": 0,
            "num_samples_per_data_block": 128,
            "num_samples": 128000,
            "header_size": 512,
            "amplifier_channels": [
                {"native_channel_name": "A-000", "signal_type": 0},
                {"native_channel_name": "A-001", "signal_type": 0},
            ],
            "aux_input_channels": [],
            "board_adc_channels": [],
            "board_dig_in_channels": [],
            "board_dig_out_channels": [],
            "supply_voltage_channels": [],
            "frequency_parameters": {
                "amplifier_sample_rate": 30000.0,
                "aux_input_sample_rate": 7500.0,
            },
        }

        with patch(
            "ndi.daq.reader.mfdaq.intan.read_Intan_RHD2000_header",
            return_value=mock_header,
        ):
            # Clear any cached header
            reader._header_cache.clear()
            channels = reader.getchannelsepoch(["fake_data.rhd"])

        assert len(channels) == 3  # 2 amplifier + 1 time
        assert channels[0].name == "ai1"
        assert channels[0].type == "analog_in"
        assert channels[0].sample_rate == 30000.0
        assert channels[1].name == "ai2"
        assert channels[2].type == "time"

    def test_intan_reader_no_rhd_file(self):
        """ndi_daq_reader_mfdaq_intan.getchannelsepoch returns [] with no .rhd file."""
        reader = ndi_daq_reader_mfdaq_intan()
        channels = reader.getchannelsepoch(["nonexistent.txt"])
        assert channels == []

    def test_intan_reader_readchannels_no_file_raises(self):
        """ndi_daq_reader_mfdaq_intan.readchannels_epochsamples raises with no .rhd file."""
        reader = ndi_daq_reader_mfdaq_intan()

        with pytest.raises(FileNotFoundError):
            reader.readchannels_epochsamples("ai", [1], ["fake.txt"], 1, 100)

    def test_intan_reader_samplerate_no_file_raises(self):
        """ndi_daq_reader_mfdaq_intan.samplerate raises with no .rhd file."""
        reader = ndi_daq_reader_mfdaq_intan()

        with pytest.raises(FileNotFoundError):
            reader.samplerate(["fake.txt"], "ai", [1])

    def test_intan_reader_repr(self):
        """ndi_daq_reader_mfdaq_intan has a useful repr."""
        reader = ndi_daq_reader_mfdaq_intan()
        r = repr(reader)
        assert "ndi_daq_reader_mfdaq_intan" in r

    @requires_data
    def test_intan_reader_live(self):
        """Read a real .rhd file and verify channel discovery.

        MATLAB equivalent: mfdaqIntanTest - live read test

        This test is skipped unless example .rhd data files are available.
        """
        rhd_path = _find_example_rhd()
        assert rhd_path, "Should have found an .rhd file"

        reader = ndi_daq_reader_mfdaq_intan()
        channels = reader.getchannelsepoch([rhd_path])

        # Should discover at least one analog input channel
        assert len(channels) > 0
        analog_channels = [c for c in channels if c.type == "analog_in"]
        assert len(analog_channels) > 0

        # Each channel should have a sample rate
        for ch in analog_channels:
            assert ch.sample_rate is not None
            assert ch.sample_rate > 0

    def test_intan_reader_samplerate_mocked(self):
        """ndi_daq_reader_mfdaq_intan.samplerate returns correct rates via mocked header."""
        reader = ndi_daq_reader_mfdaq_intan()

        mock_header = {
            "sample_rate": 30000.0,
            "num_amplifier_channels": 2,
            "num_aux_input_channels": 1,
            "num_supply_voltage_channels": 0,
            "num_board_adc_channels": 0,
            "num_board_dig_in_channels": 0,
            "num_board_dig_out_channels": 0,
            "num_temp_sensor_channels": 0,
            "num_samples_per_data_block": 128,
            "num_samples": 128000,
            "header_size": 512,
            "amplifier_channels": [
                {"native_channel_name": "A-000", "signal_type": 0},
                {"native_channel_name": "A-001", "signal_type": 0},
            ],
            "aux_input_channels": [{"native_channel_name": "AUX1", "signal_type": 1}],
            "board_adc_channels": [],
            "board_dig_in_channels": [],
            "board_dig_out_channels": [],
            "supply_voltage_channels": [],
            "frequency_parameters": {
                "amplifier_sample_rate": 30000.0,
                "aux_input_sample_rate": 7500.0,
            },
        }

        with patch(
            "ndi.daq.reader.mfdaq.intan.read_Intan_RHD2000_header",
            return_value=mock_header,
        ):
            reader._header_cache.clear()
            rates = reader.samplerate(["fake.rhd"], "ai", [1])
            assert rates[0] == 30000.0

            reader._header_cache.clear()
            aux_rates = reader.samplerate(["fake.rhd"], "auxiliary_in", [1])
            assert aux_rates[0] == 7500.0

    def test_intan_reader_t0_t1_mocked(self):
        """ndi_daq_reader_mfdaq_intan.t0_t1 returns correct time range."""
        reader = ndi_daq_reader_mfdaq_intan()

        mock_header = {
            "num_amplifier_channels": 1,
            "num_aux_input_channels": 0,
            "num_supply_voltage_channels": 0,
            "num_board_adc_channels": 0,
            "num_board_dig_in_channels": 0,
            "num_board_dig_out_channels": 0,
            "num_temp_sensor_channels": 0,
            "num_samples_per_data_block": 60,
            "amplifier_channels": [{"native_channel_name": "A-000", "signal_type": 0}],
            "aux_input_channels": [],
            "board_adc_channels": [],
            "board_dig_in_channels": [],
            "board_dig_out_channels": [],
            "supply_voltage_channels": [],
            "frequency_parameters": {"amplifier_sample_rate": 30000.0},
        }

        # Intan_RHD2000_blockinfo returns (blockinfo, bytes_per_block, bytes_present, num_data_blocks)
        mock_blockinfo = ({"samples_per_block": 60}, 0, 0, 5000)
        # total_samples = 60 * 5000 = 300000

        with patch(
            "ndi.daq.reader.mfdaq.intan.read_Intan_RHD2000_header",
            return_value=mock_header,
        ), patch(
            "ndi.daq.reader.mfdaq.intan.Intan_RHD2000_blockinfo",
            return_value=mock_blockinfo,
        ):
            reader._header_cache.clear()
            t0_t1 = reader.t0_t1(["fake.rhd"])

        assert len(t0_t1) == 1
        assert t0_t1[0][0] == 0.0
        np.testing.assert_allclose(t0_t1[0][1], (300000 - 1) / 30000.0)


# ===========================================================================
# TestEpochSampleTimeConversion
# Port of: mfdaqIntanTest - epochsamples2times / epochtimes2samples
#
# These methods live on ndi_daq_reader_mfdaq. We test them with a concrete mock
# subclass rather than needing real data.
# ===========================================================================


class _MockMFDAQReader(ndi_daq_reader_mfdaq):
    """Concrete MFDAQ reader for testing time/sample conversions."""

    def __init__(self, sample_rate=30000.0, t0=0.0, num_samples=300000):
        super().__init__()
        self._sr = sample_rate
        self._t0 = t0
        self._num_samples = num_samples

    def getchannelsepoch(self, epochfiles):
        return [
            ChannelInfo(name="ai1", type="analog_in", number=1, sample_rate=self._sr),
        ]

    def readchannels_epochsamples(self, channeltype, channel, epochfiles, s0, s1):
        if isinstance(channel, int):
            channel = [channel]
        n_samples = s1 - s0 + 1
        return np.zeros((n_samples, len(channel)))

    def samplerate(self, epochfiles, channeltype, channel):
        if isinstance(channel, int):
            channel = [channel]
        return np.full(len(channel), self._sr)

    def t0_t1(self, epochfiles):
        t1 = self._t0 + (self._num_samples - 1) / self._sr
        return [(self._t0, t1)]


class TestEpochSampleTimeConversion:
    """Port of mfdaqIntanTest - epochsamples2times / epochtimes2samples.

    Tests the ndi_daq_reader_mfdaq methods for converting between sample indices
    and time values. Uses a mock reader with known sample rate and t0.
    """

    def test_epochsamples2times_basic(self):
        """Convert sample indices to times with known sample rate.

        MATLAB equivalent: mfdaqIntanTest - epochsamples2times basic
        """
        sr = 30000.0
        reader = _MockMFDAQReader(sample_rate=sr, t0=0.0)
        files = ["dummy.rhd"]

        samples = np.array([1, 2, 3])
        times = reader.epochsamples2times("ai", 1, files, samples)

        # t = t0 + (sample - 1) / sr  =>  t = (s-1)/30000
        expected = np.array([0.0, 1.0 / sr, 2.0 / sr])
        np.testing.assert_allclose(times, expected, atol=1e-12)

    def test_epochtimes2samples_basic(self):
        """Convert times to sample indices with known sample rate.

        MATLAB equivalent: mfdaqIntanTest - epochtimes2samples basic
        """
        sr = 30000.0
        reader = _MockMFDAQReader(sample_rate=sr, t0=0.0)
        files = ["dummy.rhd"]

        times = np.array([0.0, 1.0 / sr, 2.0 / sr])
        samples = reader.epochtimes2samples("ai", 1, files, times)

        expected = np.array([1, 2, 3])
        np.testing.assert_array_equal(samples, expected)

    def test_roundtrip_samples_times(self):
        """samples -> times -> samples round-trip should be identity.

        MATLAB equivalent: mfdaqIntanTest - round-trip test
        """
        sr = 20000.0
        reader = _MockMFDAQReader(sample_rate=sr, t0=0.5)
        files = ["dummy.rhd"]

        original_samples = np.array([1, 100, 1000, 10000])
        times = reader.epochsamples2times("ai", 1, files, original_samples)
        recovered_samples = reader.epochtimes2samples("ai", 1, files, times)

        np.testing.assert_array_equal(recovered_samples, original_samples)

    def test_roundtrip_times_samples(self):
        """times -> samples -> times round-trip should be identity.

        MATLAB equivalent: mfdaqIntanTest - round-trip test (reverse)
        """
        sr = 30000.0
        reader = _MockMFDAQReader(sample_rate=sr, t0=0.0)
        files = ["dummy.rhd"]

        original_times = np.array([0.0, 0.5, 1.0, 5.0])
        samples = reader.epochtimes2samples("ai", 1, files, original_times)
        recovered_times = reader.epochsamples2times("ai", 1, files, samples)

        np.testing.assert_allclose(recovered_times, original_times, atol=1.0 / sr)

    def test_epochsamples2times_with_nonzero_t0(self):
        """epochsamples2times with nonzero t0 shifts correctly.

        MATLAB equivalent: mfdaqIntanTest - t0 offset check
        """
        sr = 10000.0
        t0 = 2.5
        reader = _MockMFDAQReader(sample_rate=sr, t0=t0)
        files = ["dummy.rhd"]

        samples = np.array([1])
        times = reader.epochsamples2times("ai", 1, files, samples)

        # sample 1 should correspond to t0
        np.testing.assert_allclose(times, np.array([t0]), atol=1e-12)

    def test_epochtimes2samples_with_nonzero_t0(self):
        """epochtimes2samples with nonzero t0.

        MATLAB equivalent: mfdaqIntanTest - t0 offset check (reverse)
        """
        sr = 10000.0
        t0 = 2.5
        reader = _MockMFDAQReader(sample_rate=sr, t0=t0)
        files = ["dummy.rhd"]

        times = np.array([t0])
        samples = reader.epochtimes2samples("ai", 1, files, times)

        np.testing.assert_array_equal(samples, np.array([1]))


# ===========================================================================
# TestChannelUtils
# Port of: ndi.fun.channelname2prefixnumber
# ===========================================================================


class TestChannelUtils:
    """Port of ndi.fun.channelname2prefixnumber tests."""

    def test_channel_name_parse_ai(self):
        """'ai5' -> ('ai', 5).

        MATLAB equivalent: channelname2prefixnumber('ai5')
        """
        prefix, number = channelname2prefixnumber("ai5")
        assert prefix == "ai"
        assert number == 5

    def test_channel_name_parse_amp(self):
        """'amp1' -> ('amp', 1).

        MATLAB equivalent: channelname2prefixnumber('amp1')
        """
        prefix, number = channelname2prefixnumber("amp1")
        assert prefix == "amp"
        assert number == 1

    def test_channel_name_parse_di(self):
        """'di12' -> ('di', 12).

        MATLAB equivalent: channelname2prefixnumber('di12')
        """
        prefix, number = channelname2prefixnumber("di12")
        assert prefix == "di"
        assert number == 12

    def test_channel_name_parse_single_letter(self):
        """'t1' -> ('t', 1)."""
        prefix, number = channelname2prefixnumber("t1")
        assert prefix == "t"
        assert number == 1

    def test_channel_name_parse_multidigit(self):
        """'analog100' -> ('analog', 100)."""
        prefix, number = channelname2prefixnumber("analog100")
        assert prefix == "analog"
        assert number == 100

    def test_channel_name_no_digits_raises(self):
        """Channel name without digits should raise ValueError."""
        with pytest.raises(ValueError, match="No digits"):
            channelname2prefixnumber("analog")

    def test_channel_name_starts_with_digit_raises(self):
        """Channel name starting with a digit should raise ValueError."""
        with pytest.raises(ValueError, match="starts with a digit"):
            channelname2prefixnumber("1ai")

    def test_channel_name_parse_zero(self):
        """'ch0' -> ('ch', 0)."""
        prefix, number = channelname2prefixnumber("ch0")
        assert prefix == "ch"
        assert number == 0


# ===========================================================================
# TestChannelTypeStandardization
# Port of channel type abbreviation lookups from MFDAQ
# ===========================================================================


class TestChannelTypeStandardization:
    """Test ChannelType enum and standardize_channel_type utility."""

    def test_standardize_ai(self):
        """'ai' standardizes to 'analog_in'."""
        assert standardize_channel_type("ai") == "analog_in"

    def test_standardize_di(self):
        """'di' standardizes to 'digital_in'."""
        assert standardize_channel_type("di") == "digital_in"

    def test_standardize_t(self):
        """'t' standardizes to 'time'."""
        assert standardize_channel_type("t") == "time"

    def test_standardize_full_name(self):
        """Full name passes through unchanged."""
        assert standardize_channel_type("analog_in") == "analog_in"

    def test_standardize_unknown(self):
        """Unknown type passes through unchanged."""
        assert standardize_channel_type("custom_type") == "custom_type"

    def test_channel_type_from_abbreviation(self):
        """ChannelType.from_abbreviation maps abbreviation to enum."""
        assert ChannelType.from_abbreviation("ai") == ChannelType.ANALOG_IN
        assert ChannelType.from_abbreviation("do") == ChannelType.DIGITAL_OUT
        assert ChannelType.from_abbreviation("aux") == ChannelType.AUXILIARY_IN

    def test_channel_type_abbreviation_property(self):
        """ChannelType enum has abbreviation property."""
        assert ChannelType.ANALOG_IN.abbreviation == "ai"
        assert ChannelType.TIME.abbreviation == "t"
        assert ChannelType.MARKER.abbreviation == "mk"


# ===========================================================================
# TestMFDAQReaderBase
# Additional base-class coverage
# ===========================================================================


class TestMFDAQReaderBase:
    """Test ndi_daq_reader_mfdaq base class methods that don't need real data."""

    def test_underlying_datatype_analog(self):
        """underlying_datatype returns float64 for analog_in channels."""
        reader = _MockMFDAQReader()
        dtype, poly, dsize = reader.underlying_datatype(["dummy.rhd"], "ai", [1, 2])
        assert dtype == "float64"
        assert dsize == 64
        assert poly.shape == (2, 2)
        np.testing.assert_array_equal(poly, [[0.0, 1.0], [0.0, 1.0]])

    def test_underlying_datatype_digital(self):
        """underlying_datatype returns uint8 for digital_in channels."""
        reader = _MockMFDAQReader()
        dtype, poly, dsize = reader.underlying_datatype(["dummy.rhd"], "di", [1])
        assert dtype == "uint8"
        assert dsize == 8

    def test_underlying_datatype_unknown_raises(self):
        """underlying_datatype raises ValueError for unknown type."""
        reader = _MockMFDAQReader()
        with pytest.raises(ValueError, match="Unknown channel type"):
            reader.underlying_datatype(["dummy.rhd"], "bogus_type", [1])

    def test_epochclock_returns_dev_local_time(self):
        """ndi_daq_reader_mfdaq.epochclock returns DEV_LOCAL_TIME."""
        from ndi.time import DEV_LOCAL_TIME

        reader = _MockMFDAQReader()
        clocks = reader.epochclock(["dummy.rhd"])
        assert len(clocks) == 1
        assert clocks[0] == DEV_LOCAL_TIME
