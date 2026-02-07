"""
Tests for Batch A: Core infrastructure gap-fill.

Tests DAQSystemString, EpochProbeMapDAQSystem, epoch functions,
MFDAQEpochChannel, DAQSystemMFDAQ, EpochDirNavigator,
ProbeTimeseries, ProbeTimeseriesMFDAQ, and element utility functions.
"""

import numpy as np
import pytest

# ============================================================================
# DAQSystemString Tests
# ============================================================================


class TestDAQSystemString:
    """Tests for ndi.daq.daqsystemstring."""

    def test_import(self):
        from ndi.daq.daqsystemstring import DAQSystemString

        assert DAQSystemString is not None

    def test_parse_simple(self):
        from ndi.daq.daqsystemstring import DAQSystemString

        dss = DAQSystemString.parse("mydevice:ai1-5")
        assert dss.devicename == "mydevice"
        assert len(dss.channels) == 1
        assert dss.channels[0][0] == "ai"
        assert dss.channels[0][1] == [1, 2, 3, 4, 5]

    def test_parse_multiple_groups(self):
        from ndi.daq.daqsystemstring import DAQSystemString

        dss = DAQSystemString.parse("intan1:ai1-3;di1,2")
        assert dss.devicename == "intan1"
        assert len(dss.channels) == 2
        assert dss.channels[0] == ("ai", [1, 2, 3])
        assert dss.channels[1] == ("di", [1, 2])

    def test_parse_comma_separated(self):
        from ndi.daq.daqsystemstring import DAQSystemString

        dss = DAQSystemString.parse("dev:ai1,3,7")
        assert dss.channel_list("ai") == [1, 3, 7]

    def test_parse_mixed_ranges_and_singles(self):
        from ndi.daq.daqsystemstring import DAQSystemString

        dss = DAQSystemString.parse("dev:ai1-3,7,10-12")
        assert dss.channel_list("ai") == [1, 2, 3, 7, 10, 11, 12]

    def test_parse_device_only(self):
        from ndi.daq.daqsystemstring import DAQSystemString

        dss = DAQSystemString.parse("mydevice")
        assert dss.devicename == "mydevice"
        assert dss.channels == []

    def test_parse_empty(self):
        from ndi.daq.daqsystemstring import DAQSystemString

        dss = DAQSystemString.parse("")
        assert dss.devicename == ""
        assert dss.channels == []

    def test_parse_device_colon_no_channels(self):
        from ndi.daq.daqsystemstring import DAQSystemString

        dss = DAQSystemString.parse("dev:")
        assert dss.devicename == "dev"
        assert dss.channels == []

    def test_devicestring_roundtrip(self):
        from ndi.daq.daqsystemstring import DAQSystemString

        original = "intan1:ai1-5;di1-3"
        dss = DAQSystemString.parse(original)
        result = dss.devicestring()
        dss2 = DAQSystemString.parse(result)
        assert dss2.devicename == dss.devicename
        assert dss2.channels == dss.channels

    def test_channel_types(self):
        from ndi.daq.daqsystemstring import DAQSystemString

        dss = DAQSystemString.parse("dev:ai1-3;di1;ao2")
        assert set(dss.channel_types()) == {"ai", "di", "ao"}

    def test_channel_list_filtered(self):
        from ndi.daq.daqsystemstring import DAQSystemString

        dss = DAQSystemString.parse("dev:ai1-3;di5,6")
        assert dss.channel_list("ai") == [1, 2, 3]
        assert dss.channel_list("di") == [5, 6]
        assert dss.channel_list("ao") == []

    def test_channel_list_all(self):
        from ndi.daq.daqsystemstring import DAQSystemString

        dss = DAQSystemString.parse("dev:ai1,2;di5")
        assert dss.channel_list() == [1, 2, 5]

    def test_str_repr(self):
        from ndi.daq.daqsystemstring import DAQSystemString

        dss = DAQSystemString.parse("dev:ai1")
        assert "dev" in str(dss)
        assert "DAQSystemString" in repr(dss)

    def test_equality(self):
        from ndi.daq.daqsystemstring import DAQSystemString

        dss1 = DAQSystemString.parse("dev:ai1-3")
        dss2 = DAQSystemString.parse("dev:ai1-3")
        dss3 = DAQSystemString.parse("dev:ai1-4")
        assert dss1 == dss2
        assert dss1 != dss3

    def test_invalid_range(self):
        from ndi.daq.daqsystemstring import DAQSystemString

        with pytest.raises(ValueError):
            DAQSystemString.parse("dev:aiabc-def")


# ============================================================================
# EpochProbeMapDAQSystem Tests
# ============================================================================


class TestEpochProbeMapDAQSystem:
    """Tests for ndi.epoch.epochprobemap_daqsystem."""

    def test_import(self):
        from ndi.epoch.epochprobemap_daqsystem import EpochProbeMapDAQSystem

        assert EpochProbeMapDAQSystem is not None

    def test_construction(self):
        from ndi.epoch.epochprobemap_daqsystem import EpochProbeMapDAQSystem

        epm = EpochProbeMapDAQSystem(
            name="probe1",
            reference=1,
            type="n-trode",
            devicestring="intan1:ai1-4",
            subjectstring="mouse001",
        )
        assert epm.name == "probe1"
        assert epm.reference == 1
        assert epm.type == "n-trode"
        assert epm.devicestring == "intan1:ai1-4"

    def test_daqsystemstring_property(self):
        from ndi.epoch.epochprobemap_daqsystem import EpochProbeMapDAQSystem

        epm = EpochProbeMapDAQSystem(
            name="probe1",
            reference=1,
            type="n-trode",
            devicestring="intan1:ai1-4",
        )
        dss = epm.daqsystemstring
        assert dss.devicename == "intan1"
        assert dss.channel_list("ai") == [1, 2, 3, 4]

    def test_serialization(self):
        from ndi.epoch.epochprobemap_daqsystem import EpochProbeMapDAQSystem

        epm = EpochProbeMapDAQSystem(
            name="probe1",
            reference=1,
            type="n-trode",
            devicestring="intan1:ai1-4",
            subjectstring="mouse001",
        )
        s = epm.serialize()
        assert "\t" in s
        parts = s.split("\t")
        assert len(parts) == 5
        assert parts[0] == "probe1"

    def test_decode_roundtrip(self):
        from ndi.epoch.epochprobemap_daqsystem import EpochProbeMapDAQSystem

        epm = EpochProbeMapDAQSystem(
            name="probe1",
            reference=1,
            type="n-trode",
            devicestring="intan1:ai1-4",
            subjectstring="mouse001",
        )
        s = epm.serialize()
        decoded = EpochProbeMapDAQSystem.decode(s)
        assert decoded.name == epm.name
        assert decoded.reference == epm.reference
        assert decoded.type == epm.type
        assert decoded.devicestring == epm.devicestring
        assert decoded.subjectstring == epm.subjectstring

    def test_file_io(self, tmp_path):
        from ndi.epoch.epochprobemap_daqsystem import EpochProbeMapDAQSystem

        epm = EpochProbeMapDAQSystem(
            name="probe1",
            reference=1,
            type="n-trode",
            devicestring="intan1:ai1-4",
            subjectstring="mouse001",
        )
        filepath = str(tmp_path / "test_epm.txt")
        epm.save_to_file(filepath)
        loaded = EpochProbeMapDAQSystem.load_from_file(filepath)
        assert len(loaded) == 1
        assert loaded[0].name == "probe1"

    def test_decode_invalid(self):
        from ndi.epoch.epochprobemap_daqsystem import EpochProbeMapDAQSystem

        with pytest.raises(ValueError):
            EpochProbeMapDAQSystem.decode("only\ttwo\tfields")

    def test_inherits_epochprobemap(self):
        from ndi.epoch.epochprobemap import EpochProbeMap
        from ndi.epoch.epochprobemap_daqsystem import EpochProbeMapDAQSystem

        epm = EpochProbeMapDAQSystem(
            name="probe1",
            reference=1,
            type="n-trode",
            devicestring="intan1:ai1-4",
        )
        assert isinstance(epm, EpochProbeMap)
        assert epm.matches(name="probe1")
        assert not epm.matches(name="probe2")

    def test_serialization_struct(self):
        from ndi.epoch.epochprobemap_daqsystem import EpochProbeMapDAQSystem

        epm = EpochProbeMapDAQSystem(
            name="p1",
            reference=2,
            type="t",
            devicestring="d:ai1",
            subjectstring="s",
        )
        d = epm.serialization_struct()
        assert d["name"] == "p1"
        assert d["reference"] == 2


# ============================================================================
# Epoch Functions Tests
# ============================================================================


class TestEpochFunctions:
    """Tests for ndi.epoch.functions."""

    def test_import(self):
        from ndi.epoch.functions import epochrange

        assert epochrange is not None

    def _make_mock_epochset(self, n_epochs=3):
        """Create a mock object with epochtable()."""
        from ndi.time import NO_TIME

        class MockEpochSet:
            def epochtable(self):
                table = []
                for i in range(n_epochs):
                    table.append(
                        {
                            "epoch_number": i + 1,
                            "epoch_id": f"epoch_{i+1:03d}",
                            "epoch_clock": [NO_TIME],
                            "t0_t1": [(0.0, 10.0 * (i + 1))],
                        }
                    )
                return table

        return MockEpochSet()

    def test_epochrange_by_number(self):
        from ndi.epoch.functions import epochrange
        from ndi.time import NO_TIME

        es = self._make_mock_epochset(5)
        ids, et, t0t1 = epochrange(es, NO_TIME, 2, 4)
        assert len(ids) == 3
        assert ids == ["epoch_002", "epoch_003", "epoch_004"]

    def test_epochrange_by_id(self):
        from ndi.epoch.functions import epochrange
        from ndi.time import NO_TIME

        es = self._make_mock_epochset(5)
        ids, et, t0t1 = epochrange(es, NO_TIME, "epoch_001", "epoch_003")
        assert len(ids) == 3

    def test_epochrange_single(self):
        from ndi.epoch.functions import epochrange
        from ndi.time import NO_TIME

        es = self._make_mock_epochset(3)
        ids, et, t0t1 = epochrange(es, NO_TIME, 2, 2)
        assert len(ids) == 1
        assert ids[0] == "epoch_002"

    def test_epochrange_invalid_range(self):
        from ndi.epoch.functions import epochrange
        from ndi.time import NO_TIME

        es = self._make_mock_epochset(3)
        with pytest.raises(ValueError):
            epochrange(es, NO_TIME, 3, 1)

    def test_epochrange_out_of_bounds(self):
        from ndi.epoch.functions import epochrange
        from ndi.time import NO_TIME

        es = self._make_mock_epochset(3)
        with pytest.raises(ValueError):
            epochrange(es, NO_TIME, 1, 5)

    def test_epochrange_empty(self):
        from ndi.epoch.functions import epochrange
        from ndi.time import NO_TIME

        class EmptyEpochSet:
            def epochtable(self):
                return []

        ids, et, t0t1 = epochrange(EmptyEpochSet(), NO_TIME, 0, 0)
        assert ids == []


# ============================================================================
# MFDAQEpochChannel Tests
# ============================================================================


class TestMFDAQEpochChannel:
    """Tests for ndi.file.type.mfdaq_epoch_channel."""

    def test_import(self):
        from ndi.file.type.mfdaq_epoch_channel import ChannelInfo, MFDAQEpochChannel

        assert MFDAQEpochChannel is not None
        assert ChannelInfo is not None

    def test_channel_info_creation(self):
        from ndi.file.type.mfdaq_epoch_channel import ChannelInfo

        ch = ChannelInfo(name="ai1", type="analog_in", sample_rate=30000.0, number=1)
        assert ch.name == "ai1"
        assert ch.sample_rate == 30000.0
        assert ch.scale == 1.0

    def test_channel_info_dict_roundtrip(self):
        from ndi.file.type.mfdaq_epoch_channel import ChannelInfo

        ch = ChannelInfo(name="ai1", type="analog_in", sample_rate=30000.0, number=1)
        d = ch.to_dict()
        ch2 = ChannelInfo.from_dict(d)
        assert ch2.name == ch.name
        assert ch2.sample_rate == ch.sample_rate

    def test_mfdaq_epoch_channel_creation(self):
        from ndi.file.type.mfdaq_epoch_channel import ChannelInfo, MFDAQEpochChannel

        channels = [
            ChannelInfo(name="ai1", type="analog_in", number=1, sample_rate=30000.0),
            ChannelInfo(name="ai2", type="analog_in", number=2, sample_rate=30000.0),
            ChannelInfo(name="di1", type="digital_in", number=1, sample_rate=30000.0),
        ]
        mec = MFDAQEpochChannel(channels)
        assert len(mec) == 3

    def test_channels_of_type(self):
        from ndi.file.type.mfdaq_epoch_channel import ChannelInfo, MFDAQEpochChannel

        channels = [
            ChannelInfo(name="ai1", type="analog_in", number=1),
            ChannelInfo(name="ai2", type="analog_in", number=2),
            ChannelInfo(name="di1", type="digital_in", number=1),
        ]
        mec = MFDAQEpochChannel(channels)
        ai_channels = mec.channels_of_type("analog_in")
        assert len(ai_channels) == 2
        di_channels = mec.channels_of_type("digital_in")
        assert len(di_channels) == 1

    def test_channel_numbers(self):
        from ndi.file.type.mfdaq_epoch_channel import ChannelInfo, MFDAQEpochChannel

        channels = [
            ChannelInfo(name="ai1", type="analog_in", number=1),
            ChannelInfo(name="ai3", type="analog_in", number=3),
        ]
        mec = MFDAQEpochChannel(channels)
        assert mec.channel_numbers("analog_in") == [1, 3]
        assert mec.channel_numbers() == [1, 3]

    def test_file_io(self, tmp_path):
        from ndi.file.type.mfdaq_epoch_channel import ChannelInfo, MFDAQEpochChannel

        channels = [
            ChannelInfo(name="ai1", type="analog_in", number=1, sample_rate=30000.0),
        ]
        mec = MFDAQEpochChannel(channels)
        filepath = str(tmp_path / "channels.json")
        mec.write_to_file(filepath)

        mec2 = MFDAQEpochChannel()
        mec2.read_from_file(filepath)
        assert len(mec2) == 1
        assert mec2.channel_information[0].name == "ai1"
        assert mec2.channel_information[0].sample_rate == 30000.0

    def test_channel_group_decoding(self):
        from ndi.file.type.mfdaq_epoch_channel import ChannelInfo, MFDAQEpochChannel

        channels = [
            ChannelInfo(name="ai1", type="analog_in", number=1, group=1),
            ChannelInfo(name="ai2", type="analog_in", number=2, group=1),
            ChannelInfo(name="ai3", type="analog_in", number=3, group=2),
        ]
        groups = MFDAQEpochChannel.channel_group_decoding(channels, "analog_in", [1, 3])
        assert groups == [1, 2]

    def test_repr(self):
        from ndi.file.type.mfdaq_epoch_channel import MFDAQEpochChannel

        mec = MFDAQEpochChannel()
        assert "MFDAQEpochChannel" in repr(mec)


# ============================================================================
# DAQSystemMFDAQ Tests
# ============================================================================


class TestDAQSystemMFDAQ:
    """Tests for ndi.daq.system_mfdaq."""

    def test_import(self):
        from ndi.daq.system_mfdaq import DAQSystemMFDAQ

        assert DAQSystemMFDAQ is not None

    def test_construction(self):
        from ndi.daq.system_mfdaq import DAQSystemMFDAQ

        sys = DAQSystemMFDAQ(name="intan1")
        assert sys.name == "intan1"

    def test_inherits_daqsystem(self):
        from ndi.daq.system import DAQSystem
        from ndi.daq.system_mfdaq import DAQSystemMFDAQ

        sys = DAQSystemMFDAQ(name="intan1")
        assert isinstance(sys, DAQSystem)

    def test_epochclock_returns_dev_local_time(self):
        from ndi.daq.system_mfdaq import DAQSystemMFDAQ
        from ndi.time import DEV_LOCAL_TIME

        sys = DAQSystemMFDAQ(name="test")
        clocks = sys.epochclock(1)
        assert len(clocks) == 1
        assert clocks[0] == DEV_LOCAL_TIME

    def test_static_channel_types(self):
        from ndi.daq.system_mfdaq import DAQSystemMFDAQ

        types = DAQSystemMFDAQ.mfdaq_channeltypes()
        assert "analog_in" in types
        assert "digital_in" in types
        assert "event" in types

    def test_mfdaq_prefix(self):
        from ndi.daq.system_mfdaq import DAQSystemMFDAQ

        assert DAQSystemMFDAQ.mfdaq_prefix("analog_in") == "ai"
        assert DAQSystemMFDAQ.mfdaq_prefix("digital_in") == "di"
        assert DAQSystemMFDAQ.mfdaq_prefix("event") == "e"

    def test_mfdaq_type(self):
        from ndi.daq.system_mfdaq import DAQSystemMFDAQ

        assert DAQSystemMFDAQ.mfdaq_type("ai") == "analog_in"
        assert DAQSystemMFDAQ.mfdaq_type("di") == "digital_in"

    def test_no_reader_getchannels(self):
        from ndi.daq.system_mfdaq import DAQSystemMFDAQ

        sys = DAQSystemMFDAQ(name="test")
        assert sys.getchannelsepoch(1) == []

    def test_no_reader_raises_on_read(self):
        from ndi.daq.system_mfdaq import DAQSystemMFDAQ

        sys = DAQSystemMFDAQ(name="test")
        with pytest.raises(RuntimeError):
            sys.readchannels_epochsamples("ai", [1], 1, 0, 100)


# ============================================================================
# EpochDirNavigator Tests
# ============================================================================


class TestEpochDirNavigator:
    """Tests for ndi.file.navigator.epochdir."""

    def test_import(self):
        from ndi.file.navigator.epochdir import EpochDirNavigator

        assert EpochDirNavigator is not None

    def test_inherits_filenavigator(self):
        from ndi.file import FileNavigator
        from ndi.file.navigator.epochdir import EpochDirNavigator

        nav = EpochDirNavigator()
        assert isinstance(nav, FileNavigator)

    def test_selectfilegroups_disk(self, tmp_path):
        from ndi.file.navigator.epochdir import EpochDirNavigator

        # Create test directory structure
        (tmp_path / "trial_001").mkdir()
        (tmp_path / "trial_001" / "data.rhd").write_text("test1")
        (tmp_path / "trial_002").mkdir()
        (tmp_path / "trial_002" / "data.rhd").write_text("test2")
        (tmp_path / "trial_003").mkdir()
        # trial_003 has no matching files

        class MockSession:
            def getpath(self):
                return str(tmp_path)

        nav = EpochDirNavigator(
            session=MockSession(),
            fileparameters="*.rhd",
        )
        groups = nav.selectfilegroups_disk()
        assert len(groups) == 2

    def test_selectfilegroups_disk_empty(self, tmp_path):
        from ndi.file.navigator.epochdir import EpochDirNavigator

        class MockSession:
            def getpath(self):
                return str(tmp_path)

        nav = EpochDirNavigator(session=MockSession(), fileparameters="*.rhd")
        groups = nav.selectfilegroups_disk()
        assert groups == []

    def test_selectfilegroups_disk_hidden_dirs(self, tmp_path):
        from ndi.file.navigator.epochdir import EpochDirNavigator

        (tmp_path / ".hidden").mkdir()
        (tmp_path / ".hidden" / "data.rhd").write_text("test")
        (tmp_path / "visible").mkdir()
        (tmp_path / "visible" / "data.rhd").write_text("test")

        class MockSession:
            def getpath(self):
                return str(tmp_path)

        nav = EpochDirNavigator(session=MockSession(), fileparameters="*.rhd")
        groups = nav.selectfilegroups_disk()
        assert len(groups) == 1  # Only visible dir

    def test_repr(self):
        from ndi.file.navigator.epochdir import EpochDirNavigator

        nav = EpochDirNavigator(fileparameters=["*.rhd", "*.dat"])
        assert "EpochDirNavigator" in repr(nav)


# ============================================================================
# ProbeTimeseries Tests
# ============================================================================


class TestProbeTimeseries:
    """Tests for ndi.probe.timeseries."""

    def test_import(self):
        from ndi.probe.timeseries import ProbeTimeseries

        assert ProbeTimeseries is not None

    def test_inherits_probe(self):
        from ndi.probe import Probe
        from ndi.probe.timeseries import ProbeTimeseries

        pt = ProbeTimeseries(name="test", reference=1, type="n-trode")
        assert isinstance(pt, Probe)

    def test_samplerate_default(self):
        from ndi.probe.timeseries import ProbeTimeseries

        pt = ProbeTimeseries(name="test", reference=1, type="n-trode")
        assert pt.samplerate(1) == -1.0

    def test_readtimeseries_needs_epoch_or_timeref(self):
        from ndi.probe.timeseries import ProbeTimeseries

        pt = ProbeTimeseries(name="test", reference=1, type="n-trode")
        with pytest.raises(ValueError):
            pt.readtimeseries()

    def test_readtimeseriesepoch_returns_none(self):
        from ndi.probe.timeseries import ProbeTimeseries

        pt = ProbeTimeseries(name="test", reference=1, type="n-trode")
        data, t, tr = pt.readtimeseriesepoch(1, 0, 10)
        assert data is None

    def test_times2samples(self):
        from ndi.probe.timeseries import ProbeTimeseries

        class MockTimeseries(ProbeTimeseries):
            def samplerate(self, epoch):
                return 1000.0

        pt = MockTimeseries(name="test", reference=1, type="n-trode")
        samples = pt.times2samples(1, np.array([0.0, 0.001, 0.01]))
        assert samples[0] == 1
        assert samples[1] == 2
        assert samples[2] == 11

    def test_samples2times(self):
        from ndi.probe.timeseries import ProbeTimeseries

        class MockTimeseries(ProbeTimeseries):
            def samplerate(self, epoch):
                return 1000.0

        pt = MockTimeseries(name="test", reference=1, type="n-trode")
        times = pt.samples2times(1, np.array([1, 2, 11]))
        np.testing.assert_allclose(times, [0.0, 0.001, 0.01])

    def test_repr(self):
        from ndi.probe.timeseries import ProbeTimeseries

        pt = ProbeTimeseries(name="test", reference=1, type="n-trode")
        assert "ProbeTimeseries" in repr(pt)


# ============================================================================
# ProbeTimeseriesMFDAQ Tests
# ============================================================================


class TestProbeTimeseriesMFDAQ:
    """Tests for ndi.probe.timeseries_mfdaq."""

    def test_import(self):
        from ndi.probe.timeseries_mfdaq import ProbeTimeseriesMFDAQ

        assert ProbeTimeseriesMFDAQ is not None

    def test_inherits_probe_timeseries(self):
        from ndi.probe.timeseries import ProbeTimeseries
        from ndi.probe.timeseries_mfdaq import ProbeTimeseriesMFDAQ

        pt = ProbeTimeseriesMFDAQ(name="test", reference=1, type="n-trode")
        assert isinstance(pt, ProbeTimeseries)

    def test_samplerate_no_session(self):
        from ndi.probe.timeseries_mfdaq import ProbeTimeseriesMFDAQ

        pt = ProbeTimeseriesMFDAQ(name="test", reference=1, type="n-trode")
        assert pt.samplerate(1) == -1.0

    def test_getchanneldevinfo_no_session(self):
        from ndi.probe.timeseries_mfdaq import ProbeTimeseriesMFDAQ

        pt = ProbeTimeseriesMFDAQ(name="test", reference=1, type="n-trode")
        assert pt.getchanneldevinfo(1) is None

    def test_read_epochsamples_no_device(self):
        from ndi.probe.timeseries_mfdaq import ProbeTimeseriesMFDAQ

        pt = ProbeTimeseriesMFDAQ(name="test", reference=1, type="n-trode")
        data, t, tr = pt.read_epochsamples(1, 0, 100)
        assert data is None

    def test_repr(self):
        from ndi.probe.timeseries_mfdaq import ProbeTimeseriesMFDAQ

        pt = ProbeTimeseriesMFDAQ(name="test", reference=1, type="n-trode")
        assert "ProbeTimeseriesMFDAQ" in repr(pt)


# ============================================================================
# Element Functions Tests
# ============================================================================


class TestElementFunctions:
    """Tests for ndi.element.functions."""

    def test_import(self):
        from ndi.element.functions import missingepochs, oneepoch, spikes_for_probe

        assert missingepochs is not None
        assert oneepoch is not None
        assert spikes_for_probe is not None

    def test_missingepochs_none_missing(self):
        from ndi.element.functions import missingepochs

        class MockElement:
            def epochtable(self):
                return [
                    {"epoch_id": "e1"},
                    {"epoch_id": "e2"},
                ]

        e1 = MockElement()
        e2 = MockElement()
        missing, ids = missingepochs(e1, e2)
        assert not missing
        assert ids == []

    def test_missingepochs_some_missing(self):
        from ndi.element.functions import missingepochs

        class Element1:
            def epochtable(self):
                return [
                    {"epoch_id": "e1"},
                    {"epoch_id": "e2"},
                    {"epoch_id": "e3"},
                ]

        class Element2:
            def epochtable(self):
                return [
                    {"epoch_id": "e1"},
                ]

        missing, ids = missingepochs(Element1(), Element2())
        assert missing
        assert set(ids) == {"e2", "e3"}

    def test_missingepochs_all_missing(self):
        from ndi.element.functions import missingepochs

        class Element1:
            def epochtable(self):
                return [{"epoch_id": "e1"}]

        class Element2:
            def epochtable(self):
                return []

        missing, ids = missingepochs(Element1(), Element2())
        assert missing
        assert ids == ["e1"]

    def test_missingepochs_with_dicts(self):
        from ndi.element.functions import missingepochs

        e1 = [{"epoch_id": "a"}, {"epoch_id": "b"}]
        e2 = [{"epoch_id": "a"}]
        missing, ids = missingepochs(e1, e2)
        assert missing
        assert ids == ["b"]

    def test_spikes_for_probe_validates_epochs(self, tmp_path):
        from ndi.element.functions import spikes_for_probe
        from ndi.session import DirSession

        session_path = tmp_path / "test_session"
        session_path.mkdir()
        session = DirSession("test_ref", str(session_path))

        class MockProbe:
            def epochtable(self):
                return [{"epoch_id": "e1"}]

        spikedata = [
            {"epochid": "nonexistent", "spiketimes": [0.1, 0.5]},
        ]

        with pytest.raises(ValueError, match="not found"):
            spikes_for_probe(session, MockProbe(), "unit1", 1, spikedata)


# ============================================================================
# Integration / Package Import Tests
# ============================================================================


class TestBatchAImports:
    """Test that all Batch A classes are importable from expected locations."""

    def test_daqsystemstring_from_daq(self):
        from ndi.daq import DAQSystemString

        assert DAQSystemString is not None

    def test_daqsystemmfdaq_from_daq(self):
        from ndi.daq import DAQSystemMFDAQ

        assert DAQSystemMFDAQ is not None

    def test_epochprobemap_daqsystem_from_epoch(self):
        from ndi.epoch import EpochProbeMapDAQSystem

        assert EpochProbeMapDAQSystem is not None

    def test_epochrange_from_epoch(self):
        from ndi.epoch import epochrange

        assert epochrange is not None

    def test_epochdir_from_file(self):
        from ndi.file import EpochDirNavigator

        assert EpochDirNavigator is not None

    def test_mfdaq_epoch_channel_from_file_type(self):
        from ndi.file.type import MFDAQEpochChannel

        assert MFDAQEpochChannel is not None

    def test_probe_timeseries(self):
        from ndi.probe.timeseries import ProbeTimeseries

        assert ProbeTimeseries is not None

    def test_probe_timeseries_mfdaq(self):
        from ndi.probe.timeseries_mfdaq import ProbeTimeseriesMFDAQ

        assert ProbeTimeseriesMFDAQ is not None

    def test_element_functions(self):
        from ndi.element.functions import missingepochs, oneepoch, spikes_for_probe

        assert callable(missingepochs)
        assert callable(oneepoch)
        assert callable(spikes_for_probe)
