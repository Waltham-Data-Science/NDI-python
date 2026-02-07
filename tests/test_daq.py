"""
Tests for ndi.daq module (Phase 5).

Tests cover:
- DAQReader abstract base class
- MFDAQReader multi-function DAQ reader
- DAQSystem complete system
- MetadataReader metadata reading
- FileNavigator file navigation
"""

import os
import tempfile
from pathlib import Path
from typing import List
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from ndi.daq.reader_base import DAQReader
from ndi.daq.mfdaq import (
    MFDAQReader, ChannelInfo, ChannelType,
    standardize_channel_type, standardize_channel_types,
)
from ndi.daq.system import DAQSystem
from ndi.daq.metadatareader import MetadataReader
from ndi.file.navigator import FileNavigator, find_file_groups
from ndi.time import ClockType, NO_TIME, DEV_LOCAL_TIME


# =============================================================================
# DAQReader Tests
# =============================================================================

class TestDAQReader:
    """Tests for DAQReader base class."""

    def test_daqreader_creation(self):
        """Test creating a DAQReader."""
        class SimpleReader(DAQReader):
            pass

        reader = SimpleReader()
        assert reader.id is not None
        assert len(reader.id) > 0

    def test_daqreader_with_identifier(self):
        """Test creating DAQReader with custom identifier."""
        class SimpleReader(DAQReader):
            pass

        reader = SimpleReader(identifier='test_reader_123')
        assert reader.id == 'test_reader_123'

    def test_daqreader_epochclock(self):
        """Test default epochclock returns NO_TIME."""
        class SimpleReader(DAQReader):
            pass

        reader = SimpleReader()
        clocks = reader.epochclock(['/path/to/file.dat'])
        assert len(clocks) == 1
        assert clocks[0] == NO_TIME

    def test_daqreader_t0_t1(self):
        """Test default t0_t1 returns NaN."""
        class SimpleReader(DAQReader):
            pass

        reader = SimpleReader()
        t0t1 = reader.t0_t1(['/path/to/file.dat'])
        assert len(t0t1) == 1
        assert np.isnan(t0t1[0][0])
        assert np.isnan(t0t1[0][1])

    def test_daqreader_verifyepochprobemap(self):
        """Test verifyepochprobemap accepts anything by default."""
        class SimpleReader(DAQReader):
            pass

        reader = SimpleReader()
        valid, msg = reader.verifyepochprobemap({}, ['/path/to/file.dat'])
        assert valid is True
        assert msg == ""

    def test_daqreader_equality(self):
        """Test DAQReader equality by ID."""
        class SimpleReader(DAQReader):
            pass

        reader1 = SimpleReader(identifier='abc')
        reader2 = SimpleReader(identifier='abc')
        reader3 = SimpleReader(identifier='xyz')

        assert reader1 == reader2
        assert reader1 != reader3


# =============================================================================
# ChannelType Tests
# =============================================================================

class TestChannelType:
    """Tests for ChannelType enum."""

    def test_channel_type_values(self):
        """Test channel type values."""
        assert ChannelType.ANALOG_IN.value == 'analog_in'
        assert ChannelType.DIGITAL_IN.value == 'digital_in'
        assert ChannelType.TIME.value == 'time'

    def test_from_abbreviation(self):
        """Test creating ChannelType from abbreviation."""
        assert ChannelType.from_abbreviation('ai') == ChannelType.ANALOG_IN
        assert ChannelType.from_abbreviation('di') == ChannelType.DIGITAL_IN
        assert ChannelType.from_abbreviation('t') == ChannelType.TIME
        assert ChannelType.from_abbreviation('ax') == ChannelType.AUXILIARY_IN

    def test_abbreviation_property(self):
        """Test abbreviation property."""
        assert ChannelType.ANALOG_IN.abbreviation == 'ai'
        assert ChannelType.DIGITAL_OUT.abbreviation == 'do'
        assert ChannelType.EVENT.abbreviation == 'e'


class TestStandardizeChannelType:
    """Tests for channel type standardization."""

    def test_standardize_abbreviation(self):
        """Test standardizing abbreviations."""
        assert standardize_channel_type('ai') == 'analog_in'
        assert standardize_channel_type('di') == 'digital_in'
        assert standardize_channel_type('t') == 'time'

    def test_standardize_full_name(self):
        """Test standardizing full names (passthrough)."""
        assert standardize_channel_type('analog_in') == 'analog_in'
        assert standardize_channel_type('time') == 'time'

    def test_standardize_channel_type_enum(self):
        """Test standardizing ChannelType enum."""
        assert standardize_channel_type(ChannelType.ANALOG_IN) == 'analog_in'

    def test_standardize_list(self):
        """Test standardizing a list of types."""
        types = ['ai', 'di', 'time']
        result = standardize_channel_types(types)
        assert result == ['analog_in', 'digital_in', 'time']


# =============================================================================
# MFDAQReader Tests
# =============================================================================

class ConcreteMFDAQReader(MFDAQReader):
    """Concrete implementation for testing."""

    def __init__(self, channels=None, **kwargs):
        super().__init__(**kwargs)
        self._channels = channels or []
        self._sample_rate = 30000.0
        self._num_samples = 10000

    def getchannelsepoch(self, epochfiles):
        return self._channels

    def readchannels_epochsamples(self, channeltype, channel, epochfiles, s0, s1):
        if isinstance(channel, int):
            channel = [channel]
        num_samples = s1 - s0 + 1
        return np.random.randn(num_samples, len(channel))

    def samplerate(self, epochfiles, channeltype, channel):
        if isinstance(channel, int):
            channel = [channel]
        return np.full(len(channel), self._sample_rate)

    def t0_t1(self, epochfiles):
        t1 = (self._num_samples - 1) / self._sample_rate
        return [(0.0, t1)]


class TestMFDAQReader:
    """Tests for MFDAQReader class."""

    def test_mfdaq_creation(self):
        """Test creating MFDAQReader."""
        channels = [
            ChannelInfo(name='ai1', type='analog_in', number=1, sample_rate=30000),
            ChannelInfo(name='ai2', type='analog_in', number=2, sample_rate=30000),
        ]
        reader = ConcreteMFDAQReader(channels=channels)
        assert reader.id is not None

    def test_mfdaq_epochclock(self):
        """Test MFDAQReader returns DEV_LOCAL_TIME."""
        reader = ConcreteMFDAQReader()
        clocks = reader.epochclock(['test.dat'])
        assert len(clocks) == 1
        assert clocks[0] == DEV_LOCAL_TIME

    def test_mfdaq_getchannelsepoch(self):
        """Test getting channels."""
        channels = [
            ChannelInfo(name='ai1', type='analog_in', number=1, sample_rate=30000),
            ChannelInfo(name='di1', type='digital_in', number=1, sample_rate=30000),
        ]
        reader = ConcreteMFDAQReader(channels=channels)
        result = reader.getchannelsepoch(['test.dat'])
        assert len(result) == 2
        assert result[0].name == 'ai1'

    def test_mfdaq_readchannels(self):
        """Test reading channel data."""
        reader = ConcreteMFDAQReader()
        data = reader.readchannels_epochsamples('ai', [1, 2], ['test.dat'], 1, 100)
        assert data.shape == (100, 2)

    def test_mfdaq_samplerate(self):
        """Test getting sample rate."""
        reader = ConcreteMFDAQReader()
        sr = reader.samplerate(['test.dat'], 'ai', [1, 2])
        assert len(sr) == 2
        assert all(sr == 30000.0)

    def test_mfdaq_epochsamples2times(self):
        """Test converting samples to times."""
        reader = ConcreteMFDAQReader()
        samples = np.array([1, 1001, 2001])
        times = reader.epochsamples2times('ai', 1, ['test.dat'], samples)
        # t = t0 + (s-1)/sr = 0 + (s-1)/30000
        expected = (samples - 1) / 30000.0
        np.testing.assert_array_almost_equal(times, expected)

    def test_mfdaq_epochtimes2samples(self):
        """Test converting times to samples."""
        reader = ConcreteMFDAQReader()
        times = np.array([0.0, 0.1, 0.2])
        samples = reader.epochtimes2samples('ai', 1, ['test.dat'], times)
        # s = 1 + round((t-t0)*sr) = 1 + round(t*30000)
        expected = 1 + np.round(times * 30000).astype(int)
        np.testing.assert_array_equal(samples, expected)

    def test_mfdaq_channel_types(self):
        """Test channel_types static method."""
        types, abbrevs = MFDAQReader.channel_types()
        assert 'analog_in' in types
        assert 'ai' in abbrevs
        assert len(types) == len(abbrevs)

    def test_mfdaq_underlying_datatype(self):
        """Test underlying_datatype."""
        reader = ConcreteMFDAQReader()
        dtype, poly, size = reader.underlying_datatype(['test.dat'], 'analog_in', [1, 2])
        assert dtype == 'float64'
        assert size == 64
        assert poly.shape == (2, 2)


# =============================================================================
# DAQSystem Tests
# =============================================================================

class TestDAQSystem:
    """Tests for DAQSystem class."""

    def test_daqsystem_creation(self):
        """Test creating a DAQSystem."""
        sys = DAQSystem(name='test_daq')
        assert sys.name == 'test_daq'
        assert sys.id is not None

    def test_daqsystem_with_components(self):
        """Test creating DAQSystem with components."""
        reader = ConcreteMFDAQReader()
        sys = DAQSystem(name='test_daq', daqreader=reader)
        assert sys.daqreader is reader

    def test_daqsystem_invalid_reader(self):
        """Test DAQSystem rejects invalid reader."""
        with pytest.raises(TypeError):
            DAQSystem(name='test', daqreader="not a reader")

    def test_daqsystem_epochclock(self):
        """Test DAQSystem epochclock returns NO_TIME by default."""
        sys = DAQSystem()
        clocks = sys.epochclock(1)
        assert len(clocks) == 1
        assert clocks[0] == NO_TIME

    def test_daqsystem_set_metadatareaders(self):
        """Test setting metadata readers."""
        sys = DAQSystem()
        readers = [MetadataReader(), MetadataReader()]
        sys.set_daqmetadatareaders(readers)
        assert len(sys.daqmetadatareaders) == 2

    def test_daqsystem_set_invalid_metadatareaders(self):
        """Test setting invalid metadata readers."""
        sys = DAQSystem()
        with pytest.raises(TypeError):
            sys.set_daqmetadatareaders(["not a reader"])

    def test_daqsystem_equality(self):
        """Test DAQSystem equality."""
        sys1 = DAQSystem(name='test')
        sys2 = DAQSystem(name='test')
        sys3 = DAQSystem(name='other')

        assert sys1 == sys2
        assert sys1 != sys3


# =============================================================================
# MetadataReader Tests
# =============================================================================

class TestMetadataReader:
    """Tests for MetadataReader class."""

    def test_metadatareader_creation(self):
        """Test creating a MetadataReader."""
        reader = MetadataReader()
        assert reader.id is not None

    def test_metadatareader_with_pattern(self):
        """Test creating MetadataReader with pattern."""
        reader = MetadataReader(tsv_pattern=r'stim.*\.txt')
        assert reader.tab_separated_file_parameter == r'stim.*\.txt'

    def test_metadatareader_readmetadata_no_pattern(self):
        """Test readmetadata with no pattern returns empty."""
        reader = MetadataReader()
        result = reader.readmetadata(['file1.dat', 'file2.dat'])
        assert result == []

    def test_metadatareader_readmetadatafromfile(self):
        """Test reading metadata from a TSV file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.tsv', delete=False) as f:
            f.write("stimid\tparam1\tparam2\n")
            f.write("1\t10\t20.5\n")
            f.write("2\t30\t40.5\n")
            filepath = f.name

        try:
            reader = MetadataReader()
            params = reader.readmetadatafromfile(filepath)
            assert len(params) == 2
            assert params[0]['stimid'] == 1
            assert params[0]['param1'] == 10
            assert params[0]['param2'] == 20.5
            assert params[1]['stimid'] == 2
        finally:
            os.unlink(filepath)

    def test_metadatareader_readmetadata_with_pattern(self):
        """Test readmetadata with matching pattern."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create stimulus file
            stim_file = Path(tmpdir) / 'stim_params.txt'
            stim_file.write_text("stimid\tvalue\n1\t100\n2\t200\n")

            data_file = Path(tmpdir) / 'data.bin'
            data_file.write_bytes(b'\x00' * 100)

            reader = MetadataReader(tsv_pattern=r'stim.*\.txt')
            params = reader.readmetadata([str(data_file), str(stim_file)])
            assert len(params) == 2
            assert params[0]['stimid'] == 1

    def test_metadatareader_equality(self):
        """Test MetadataReader equality."""
        r1 = MetadataReader(tsv_pattern='.*\\.txt')
        r2 = MetadataReader(tsv_pattern='.*\\.txt')
        r3 = MetadataReader(tsv_pattern='.*\\.csv')

        assert r1 == r2
        assert r1 != r3


# =============================================================================
# FileNavigator Tests
# =============================================================================

class MockSession:
    """Mock session for testing."""

    def __init__(self, path):
        self._path = path
        self._id = 'test_session_123'

    def getpath(self):
        return self._path

    @property
    def id(self):
        return self._id

    def database_search(self, query):
        return []


class TestFileNavigator:
    """Tests for FileNavigator class."""

    def test_filenavigator_creation(self):
        """Test creating a FileNavigator."""
        nav = FileNavigator()
        assert nav.id is not None

    def test_filenavigator_with_session(self):
        """Test FileNavigator with session."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session = MockSession(tmpdir)
            nav = FileNavigator(session=session)
            assert nav.session is session

    def test_filenavigator_with_fileparameters(self):
        """Test FileNavigator with file parameters."""
        nav = FileNavigator(fileparameters='*.dat')
        assert nav.fileparameters == {'filematch': ['*.dat']}

    def test_filenavigator_with_list_parameters(self):
        """Test FileNavigator with list file parameters."""
        nav = FileNavigator(fileparameters=['*.dat', '*.bin'])
        assert nav.fileparameters == {'filematch': ['*.dat', '*.bin']}

    def test_filenavigator_setfileparameters(self):
        """Test setting file parameters."""
        nav = FileNavigator()
        nav.setfileparameters(['*.rhd', '*.dat'])
        assert nav.fileparameters == {'filematch': ['*.rhd', '*.dat']}

    def test_filenavigator_filematch_hashstring(self):
        """Test filematch hash string generation."""
        nav = FileNavigator(fileparameters=['*.dat', '*.bin'])
        hash1 = nav.filematch_hashstring()
        assert len(hash1) == 32  # MD5 hex digest

        nav2 = FileNavigator(fileparameters=['*.dat', '*.bin'])
        hash2 = nav2.filematch_hashstring()
        assert hash1 == hash2  # Same patterns = same hash

        nav3 = FileNavigator(fileparameters=['*.rhd'])
        hash3 = nav3.filematch_hashstring()
        assert hash1 != hash3  # Different patterns = different hash

    def test_filenavigator_isingested(self):
        """Test isingested static method."""
        assert FileNavigator.isingested(['epochid://abc123', 'file.dat']) is True
        assert FileNavigator.isingested(['file.dat']) is False
        assert FileNavigator.isingested([]) is False

    def test_filenavigator_ingestedfiles_epochid(self):
        """Test extracting epoch ID from ingested files."""
        epochid = FileNavigator.ingestedfiles_epochid(['epochid://abc123', 'file.dat'])
        assert epochid == 'abc123'

    def test_filenavigator_selectfilegroups_disk(self):
        """Test selecting file groups from disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            (Path(tmpdir) / 'epoch1' / 'data.rhd').parent.mkdir(parents=True)
            (Path(tmpdir) / 'epoch1' / 'data.rhd').touch()
            (Path(tmpdir) / 'epoch2' / 'data.rhd').parent.mkdir(parents=True)
            (Path(tmpdir) / 'epoch2' / 'data.rhd').touch()

            session = MockSession(tmpdir)
            nav = FileNavigator(session=session, fileparameters='*.rhd')
            groups = nav.selectfilegroups_disk()

            assert len(groups) == 2

    def test_filenavigator_epochid_generation(self):
        """Test epoch ID generation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test file
            (Path(tmpdir) / 'data.dat').touch()

            session = MockSession(tmpdir)
            nav = FileNavigator(session=session, fileparameters='*.dat')

            # First call should generate new ID
            epochfiles = [str(Path(tmpdir) / 'data.dat')]
            epoch_id = nav.epochid(1, epochfiles)
            assert epoch_id.startswith('epoch_')

    def test_filenavigator_equality(self):
        """Test FileNavigator equality."""
        nav1 = FileNavigator(fileparameters='*.dat')
        nav2 = FileNavigator(fileparameters='*.dat')
        nav3 = FileNavigator(fileparameters='*.bin')

        assert nav1 == nav2
        assert nav1 != nav3


class TestFindFileGroups:
    """Tests for find_file_groups function."""

    def test_find_file_groups_glob(self):
        """Test finding file groups with glob pattern."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            (Path(tmpdir) / 'dir1').mkdir()
            (Path(tmpdir) / 'dir1' / 'data.dat').touch()
            (Path(tmpdir) / 'dir2').mkdir()
            (Path(tmpdir) / 'dir2' / 'data.dat').touch()
            (Path(tmpdir) / 'dir2' / 'other.txt').touch()

            groups = find_file_groups(tmpdir, ('*.dat',))
            assert len(groups) == 2

    def test_find_file_groups_multiple_patterns(self):
        """Test finding file groups with multiple patterns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / 'data.dat').touch()
            (Path(tmpdir) / 'data.bin').touch()

            groups = find_file_groups(tmpdir, ('*.dat', '*.bin'))
            assert len(groups) == 1
            assert len(groups[0]) == 2

    def test_find_file_groups_empty(self):
        """Test finding file groups with no matches."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / 'data.txt').touch()

            groups = find_file_groups(tmpdir, ('*.dat',))
            assert len(groups) == 0


# =============================================================================
# ChannelInfo Tests
# =============================================================================

class TestChannelInfo:
    """Tests for ChannelInfo dataclass."""

    def test_channelinfo_creation(self):
        """Test creating ChannelInfo."""
        ch = ChannelInfo(name='ai1', type='analog_in')
        assert ch.name == 'ai1'
        assert ch.type == 'analog_in'
        assert ch.time_channel is None

    def test_channelinfo_with_all_fields(self):
        """Test ChannelInfo with all fields."""
        ch = ChannelInfo(
            name='ai1',
            type='analog_in',
            time_channel=1,
            number=1,
            sample_rate=30000.0,
            offset=0.0,
            scale=1.0,
            group=1,
        )
        assert ch.number == 1
        assert ch.sample_rate == 30000.0


# =============================================================================
# Integration Tests
# =============================================================================

class TestDAQIntegration:
    """Integration tests for DAQ components."""

    def test_daqsystem_with_reader_and_navigator(self):
        """Test complete DAQ system setup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test file
            (Path(tmpdir) / 'data.dat').touch()

            session = MockSession(tmpdir)
            reader = ConcreteMFDAQReader()
            nav = FileNavigator(session=session, fileparameters='*.dat')

            sys = DAQSystem(
                name='test_system',
                filenavigator=nav,
                daqreader=reader,
            )

            assert sys.name == 'test_system'
            assert sys.filenavigator is nav
            assert sys.daqreader is reader

    def test_full_workflow(self):
        """Test full workflow from file to data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test file structure
            epoch_dir = Path(tmpdir) / 'epoch1'
            epoch_dir.mkdir()
            (epoch_dir / 'recording.dat').touch()

            session = MockSession(tmpdir)

            channels = [
                ChannelInfo(name='ai1', type='analog_in', number=1, sample_rate=30000),
                ChannelInfo(name='ai2', type='analog_in', number=2, sample_rate=30000),
            ]
            reader = ConcreteMFDAQReader(channels=channels)
            nav = FileNavigator(session=session, fileparameters='*.dat')

            # Get epoch files
            groups = nav.selectfilegroups_disk()
            assert len(groups) == 1

            # Get channel info
            epoch_channels = reader.getchannelsepoch(groups[0])
            assert len(epoch_channels) == 2

            # Read some data
            data = reader.readchannels_epochsamples('ai', [1, 2], groups[0], 1, 100)
            assert data.shape == (100, 2)


# =============================================================================
# Ingested Data Tests
# =============================================================================

class TestIngestedDataMethods:
    """Tests for ingested data methods in MFDAQReader."""

    def test_samplerate_ingested_no_session(self):
        """Test samplerate_ingested with mock session."""
        reader = ConcreteMFDAQReader()

        # Create mock session and document
        mock_doc = MagicMock()
        mock_doc.document_properties.daqreader_epochdata_ingested.epochtable = {
            'channels': [
                {'name': 'ai1', 'type': 'analog_in', 'number': 1, 'sample_rate': 30000},
                {'name': 'ai2', 'type': 'analog_in', 'number': 2, 'sample_rate': 30000},
            ]
        }

        mock_session = MagicMock()

        # Mock getingesteddocument
        reader.getingesteddocument = MagicMock(return_value=mock_doc)

        sr = reader.samplerate_ingested(
            ['epochid://test123'],
            ['ai', 'ai'],
            [1, 2],
            mock_session
        )
        assert len(sr) == 2
        assert sr[0] == 30000
        assert sr[1] == 30000

    def test_getchannelsepoch_ingested(self):
        """Test getchannelsepoch_ingested."""
        reader = ConcreteMFDAQReader()

        # Create mock document
        mock_doc = MagicMock()
        mock_doc.document_properties.daqreader_epochdata_ingested.epochtable = {
            'channels': [
                {'name': 'ai1', 'type': 'analog_in', 'number': 1, 'sample_rate': 30000},
                {'name': 'di1', 'type': 'digital_in', 'number': 1, 'sample_rate': 30000},
            ]
        }

        mock_session = MagicMock()
        reader.getingesteddocument = MagicMock(return_value=mock_doc)

        channels = reader.getchannelsepoch_ingested(['epochid://test'], mock_session)
        assert len(channels) == 2
        assert channels[0].name == 'ai1'
        assert channels[0].type == 'analog_in'
        assert channels[1].name == 'di1'

    def test_epochsamples2times_ingested(self):
        """Test epochsamples2times_ingested."""
        reader = ConcreteMFDAQReader()

        # Create mock document
        mock_doc = MagicMock()
        mock_doc.document_properties.daqreader_epochdata_ingested.epochtable = {
            'channels': [
                {'name': 'ai1', 'type': 'analog_in', 'number': 1, 'sample_rate': 30000},
            ],
            't0_t1': [(0.0, 1.0)],
        }

        mock_session = MagicMock()
        reader.getingesteddocument = MagicMock(return_value=mock_doc)

        samples = np.array([1, 3001, 6001])
        times = reader.epochsamples2times_ingested(
            'ai', 1, ['epochid://test'], samples, mock_session
        )
        # t = t0 + (s-1)/sr = 0 + (s-1)/30000
        expected = (samples - 1) / 30000.0
        np.testing.assert_array_almost_equal(times, expected)

    def test_epochtimes2samples_ingested(self):
        """Test epochtimes2samples_ingested."""
        reader = ConcreteMFDAQReader()

        # Create mock document
        mock_doc = MagicMock()
        mock_doc.document_properties.daqreader_epochdata_ingested.epochtable = {
            'channels': [
                {'name': 'ai1', 'type': 'analog_in', 'number': 1, 'sample_rate': 30000},
            ],
            't0_t1': [(0.0, 1.0)],
        }

        mock_session = MagicMock()
        reader.getingesteddocument = MagicMock(return_value=mock_doc)

        times = np.array([0.0, 0.1, 0.2])
        samples = reader.epochtimes2samples_ingested(
            'ai', 1, ['epochid://test'], times, mock_session
        )
        # s = 1 + round((t-t0)*sr) = 1 + round(t*30000)
        expected = 1 + np.round(times * 30000).astype(int)
        np.testing.assert_array_equal(samples, expected)


# =============================================================================
# DAQSystem deleteepoch Tests
# =============================================================================

class TestDAQSystemDeleteEpoch:
    """Tests for DAQSystem.deleteepoch method."""

    def test_deleteepoch_no_navigator(self):
        """Test deleteepoch with no file navigator."""
        sys = DAQSystem(name='test')
        success, msg = sys.deleteepoch(1)
        assert success is False
        assert "No file navigator" in msg

    def test_deleteepoch_out_of_range(self):
        """Test deleteepoch with epoch out of range."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session = MockSession(tmpdir)
            nav = FileNavigator(session=session, fileparameters='*.dat')
            sys = DAQSystem(name='test', filenavigator=nav)

            success, msg = sys.deleteepoch(10)
            assert success is False
            assert "out of range" in msg

    def test_deleteepoch_with_epochs(self):
        """Test deleteepoch with existing epochs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test file
            (Path(tmpdir) / 'data.dat').touch()

            session = MockSession(tmpdir)
            nav = FileNavigator(session=session, fileparameters='*.dat')

            # Add deleteepoch method to navigator
            nav.deleteepoch = MagicMock()

            sys = DAQSystem(name='test', filenavigator=nav)

            success, msg = sys.deleteepoch(1)
            assert success is True
            assert "deleted" in msg
            nav.deleteepoch.assert_called_once_with(1)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
