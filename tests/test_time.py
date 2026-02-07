"""
Tests for ndi.time module (Phase 4).
"""

import pytest
import numpy as np

from ndi.time import (
    ClockType,
    TimeMapping,
    TimeReference,
    SyncRule,
    SyncGraph,
    EpochNode,
    UTC,
    DEV_LOCAL_TIME,
    NO_TIME,
)
from ndi.time.syncrule import FileMatch, FileFind


class TestClockType:
    """Tests for ClockType enum."""

    def test_all_clock_types_exist(self):
        """Test that all 9 clock types are defined."""
        expected = [
            'utc', 'approx_utc', 'exp_global_time', 'approx_exp_global_time',
            'dev_global_time', 'approx_dev_global_time', 'dev_local_time',
            'no_time', 'inherited'
        ]
        actual = [ct.value for ct in ClockType]
        assert sorted(actual) == sorted(expected)

    def test_from_string(self):
        """Test creating ClockType from string."""
        assert ClockType.from_string('utc') == ClockType.UTC
        assert ClockType.from_string('UTC') == ClockType.UTC
        assert ClockType.from_string('dev_local_time') == ClockType.DEV_LOCAL_TIME

    def test_from_string_invalid(self):
        """Test that invalid string raises ValueError."""
        with pytest.raises(ValueError):
            ClockType.from_string('invalid_clock')

    def test_str(self):
        """Test string conversion."""
        assert str(ClockType.UTC) == 'utc'
        assert str(ClockType.DEV_LOCAL_TIME) == 'dev_local_time'

    def test_needs_epoch(self):
        """Test needs_epoch method."""
        assert ClockType.DEV_LOCAL_TIME.needs_epoch()
        assert not ClockType.UTC.needs_epoch()
        assert not ClockType.EXP_GLOBAL_TIME.needs_epoch()

    def test_is_global(self):
        """Test is_global method."""
        assert ClockType.UTC.is_global()
        assert ClockType.APPROX_UTC.is_global()
        assert ClockType.EXP_GLOBAL_TIME.is_global()
        assert not ClockType.DEV_LOCAL_TIME.is_global()
        assert not ClockType.NO_TIME.is_global()

    def test_assert_global(self):
        """Test assert_global static method."""
        # Should not raise
        ClockType.assert_global(ClockType.UTC)
        ClockType.assert_global(ClockType.EXP_GLOBAL_TIME)

        # Should raise
        with pytest.raises(AssertionError):
            ClockType.assert_global(ClockType.DEV_LOCAL_TIME)
        with pytest.raises(AssertionError):
            ClockType.assert_global(ClockType.NO_TIME)

    def test_epochgraph_edge_utc_to_utc(self):
        """Test epochgraph_edge for utc->utc transition."""
        cost, mapping = ClockType.UTC.epochgraph_edge(ClockType.UTC)
        assert cost == 100.0
        assert mapping is not None
        assert mapping.map(5.0) == 5.0  # Identity mapping

    def test_epochgraph_edge_utc_to_approx_utc(self):
        """Test epochgraph_edge for utc->approx_utc transition."""
        cost, mapping = ClockType.UTC.epochgraph_edge(ClockType.APPROX_UTC)
        assert cost == 100.0
        assert mapping is not None

    def test_epochgraph_edge_no_time(self):
        """Test epochgraph_edge with no_time."""
        cost, mapping = ClockType.NO_TIME.epochgraph_edge(ClockType.UTC)
        assert cost == float('inf')
        assert mapping is None

        cost, mapping = ClockType.UTC.epochgraph_edge(ClockType.NO_TIME)
        assert cost == float('inf')
        assert mapping is None

    def test_epochgraph_edge_no_transition(self):
        """Test epochgraph_edge for invalid transition."""
        cost, mapping = ClockType.DEV_LOCAL_TIME.epochgraph_edge(ClockType.UTC)
        assert cost == float('inf')
        assert mapping is None


class TestTimeMapping:
    """Tests for TimeMapping class."""

    def test_default_mapping(self):
        """Test default identity mapping."""
        tm = TimeMapping()
        assert tm.scale == 1.0
        assert tm.shift == 0.0
        assert tm.map(5.0) == 5.0

    def test_linear_mapping(self):
        """Test linear mapping t_out = 2*t_in + 10."""
        tm = TimeMapping([2.0, 10.0])
        assert tm.scale == 2.0
        assert tm.shift == 10.0
        assert tm.map(5.0) == 20.0
        assert tm.map(0.0) == 10.0

    def test_identity_classmethod(self):
        """Test identity classmethod."""
        tm = TimeMapping.identity()
        assert tm.scale == 1.0
        assert tm.shift == 0.0
        assert tm.map(100.0) == 100.0

    def test_linear_classmethod(self):
        """Test linear classmethod."""
        tm = TimeMapping.linear(scale=3.0, shift=-5.0)
        assert tm.map(0.0) == -5.0
        assert tm.map(2.0) == 1.0

    def test_callable(self):
        """Test calling mapping directly."""
        tm = TimeMapping([2.0, 1.0])
        assert tm(5.0) == 11.0

    def test_array_input(self):
        """Test with numpy array input."""
        tm = TimeMapping([2.0, 1.0])
        t_in = np.array([1.0, 2.0, 3.0])
        t_out = tm.map(t_in)
        np.testing.assert_array_equal(t_out, np.array([3.0, 5.0, 7.0]))

    def test_inverse(self):
        """Test inverse mapping."""
        tm = TimeMapping([2.0, 10.0])
        inv = tm.inverse()
        assert inv.map(20.0) == pytest.approx(5.0)
        assert inv.map(10.0) == pytest.approx(0.0)

    def test_inverse_zero_scale(self):
        """Test inverse with zero scale raises error."""
        tm = TimeMapping([0.0, 10.0])
        with pytest.raises(ValueError):
            tm.inverse()

    def test_compose(self):
        """Test composing two mappings."""
        tm1 = TimeMapping([2.0, 1.0])  # t1 = 2*t0 + 1
        tm2 = TimeMapping([3.0, 4.0])  # t2 = 3*t1 + 4
        composed = tm1.compose(tm2)

        # t2 = 3*(2*t0 + 1) + 4 = 6*t0 + 7
        assert composed.scale == pytest.approx(6.0)
        assert composed.shift == pytest.approx(7.0)
        assert composed.map(1.0) == pytest.approx(13.0)

    def test_equality(self):
        """Test equality comparison."""
        tm1 = TimeMapping([2.0, 1.0])
        tm2 = TimeMapping([2.0, 1.0])
        tm3 = TimeMapping([3.0, 1.0])

        assert tm1 == tm2
        assert tm1 != tm3

    def test_to_dict_from_dict(self):
        """Test serialization."""
        tm = TimeMapping([2.5, -3.0])
        d = tm.to_dict()
        tm2 = TimeMapping.from_dict(d)
        assert tm == tm2


class TestTimeReference:
    """Tests for TimeReference class."""

    @pytest.fixture
    def mock_referent(self):
        """Create a mock referent object."""
        class MockSession:
            def id(self):
                return 'session_123'

        class MockReferent:
            def __init__(self):
                self.session = MockSession()
                self.name = 'test_daq'

            def epochsetname(self):
                return 'test_daq'

        return MockReferent()

    def test_create_utc_reference(self, mock_referent):
        """Test creating a UTC time reference."""
        tr = TimeReference(
            referent=mock_referent,
            clocktype=ClockType.UTC,
            time=1234567890.0
        )
        assert tr.clocktype == ClockType.UTC
        assert tr.time == 1234567890.0
        assert tr.epoch is None
        assert tr.session_id == 'session_123'

    def test_create_local_reference_requires_epoch(self, mock_referent):
        """Test that DEV_LOCAL_TIME requires epoch."""
        with pytest.raises(ValueError):
            TimeReference(
                referent=mock_referent,
                clocktype=ClockType.DEV_LOCAL_TIME,
                time=0.5
            )

    def test_create_local_reference_with_epoch(self, mock_referent):
        """Test creating a local time reference with epoch."""
        tr = TimeReference(
            referent=mock_referent,
            clocktype=ClockType.DEV_LOCAL_TIME,
            epoch='epoch_001',
            time=0.5
        )
        assert tr.clocktype == ClockType.DEV_LOCAL_TIME
        assert tr.epoch == 'epoch_001'
        assert tr.time == 0.5

    def test_clocktype_from_string(self, mock_referent):
        """Test creating with string clocktype."""
        tr = TimeReference(
            referent=mock_referent,
            clocktype='utc',
            time=100.0
        )
        assert tr.clocktype == ClockType.UTC

    def test_to_struct(self, mock_referent):
        """Test converting to struct."""
        tr = TimeReference(
            referent=mock_referent,
            clocktype=ClockType.UTC,
            epoch='epoch_001',
            time=100.0
        )
        struct = tr.to_struct()
        assert struct.referent_epochsetname == 'test_daq'
        assert struct.clocktypestring == 'utc'
        assert struct.epoch == 'epoch_001'
        assert struct.time == 100.0

    def test_to_dict(self, mock_referent):
        """Test converting to dict."""
        tr = TimeReference(
            referent=mock_referent,
            clocktype=ClockType.UTC,
            time=100.0
        )
        d = tr.to_dict()
        assert d['clocktypestring'] == 'utc'
        assert d['time'] == 100.0


class TestFileMatch:
    """Tests for FileMatch sync rule."""

    def test_default_parameters(self):
        """Test default parameters."""
        rule = FileMatch()
        assert rule.parameters['number_fullpath_matches'] == 2

    def test_custom_parameters(self):
        """Test custom parameters."""
        rule = FileMatch({'number_fullpath_matches': 3})
        assert rule.parameters['number_fullpath_matches'] == 3

    def test_invalid_parameters(self):
        """Test invalid parameters raise error."""
        with pytest.raises(ValueError):
            FileMatch({'number_fullpath_matches': 'not_a_number'})

    def test_apply_matching_files(self):
        """Test apply with matching files."""
        rule = FileMatch({'number_fullpath_matches': 2})

        node_a = {
            'objectclass': 'ndi.daq.system',
            'underlying_epochs': {
                'underlying': ['/data/file1.dat', '/data/file2.dat', '/data/file3.dat']
            }
        }
        node_b = {
            'objectclass': 'ndi.daq.system',
            'underlying_epochs': {
                'underlying': ['/data/file1.dat', '/data/file2.dat', '/data/file4.dat']
            }
        }

        cost, mapping = rule.apply(node_a, node_b)
        assert cost == 1.0
        assert mapping is not None
        assert mapping.map(5.0) == 5.0  # Identity mapping

    def test_apply_not_enough_matches(self):
        """Test apply with not enough matching files."""
        rule = FileMatch({'number_fullpath_matches': 2})

        node_a = {
            'objectclass': 'ndi.daq.system',
            'underlying_epochs': {
                'underlying': ['/data/file1.dat', '/data/file2.dat']
            }
        }
        node_b = {
            'objectclass': 'ndi.daq.system',
            'underlying_epochs': {
                'underlying': ['/data/file1.dat', '/data/file3.dat']
            }
        }

        cost, mapping = rule.apply(node_a, node_b)
        assert cost is None
        assert mapping is None

    def test_apply_non_daq_system(self):
        """Test apply with non-DAQ system returns None."""
        rule = FileMatch()

        node_a = {
            'objectclass': 'some.other.class',
            'underlying_epochs': {'underlying': ['/data/file1.dat']}
        }
        node_b = {
            'objectclass': 'ndi.daq.system',
            'underlying_epochs': {'underlying': ['/data/file1.dat']}
        }

        cost, mapping = rule.apply(node_a, node_b)
        assert cost is None
        assert mapping is None


class TestFileFind:
    """Tests for FileFind sync rule."""

    def test_default_parameters(self):
        """Test default parameters."""
        rule = FileFind()
        assert rule.parameters['file_patterns'] == []
        assert rule.parameters['match_type'] == 'exact'

    def test_apply_exact_match(self):
        """Test apply with exact file match."""
        rule = FileFind({
            'file_patterns': ['sync.txt'],
            'match_type': 'exact'
        })

        node_a = {
            'objectclass': 'ndi.daq.system',
            'underlying_epochs': {
                'underlying': ['/data/sync.txt', '/data/other.dat']
            }
        }
        node_b = {
            'objectclass': 'ndi.daq.system',
            'underlying_epochs': {
                'underlying': ['/data/sync.txt', '/data/more.dat']
            }
        }

        cost, mapping = rule.apply(node_a, node_b)
        assert cost == 1.0
        assert mapping is not None

    def test_apply_contains_match(self):
        """Test apply with contains match."""
        rule = FileFind({
            'file_patterns': ['sync'],
            'match_type': 'contains'
        })

        node_a = {
            'objectclass': 'ndi.daq.system',
            'underlying_epochs': {
                'underlying': ['/data/my_sync_file.txt']
            }
        }
        node_b = {
            'objectclass': 'ndi.daq.system',
            'underlying_epochs': {
                'underlying': ['/data/sync_data.dat']
            }
        }

        cost, mapping = rule.apply(node_a, node_b)
        assert cost == 1.0

    def test_apply_no_match(self):
        """Test apply when patterns don't match."""
        rule = FileFind({
            'file_patterns': ['missing.txt'],
            'match_type': 'exact'
        })

        node_a = {
            'objectclass': 'ndi.daq.system',
            'underlying_epochs': {'underlying': ['/data/file.txt']}
        }
        node_b = {
            'objectclass': 'ndi.daq.system',
            'underlying_epochs': {'underlying': ['/data/other.txt']}
        }

        cost, mapping = rule.apply(node_a, node_b)
        assert cost is None


class TestEpochNode:
    """Tests for EpochNode dataclass."""

    def test_create_epoch_node(self):
        """Test creating an epoch node."""
        node = EpochNode(
            epoch_id='epoch_001',
            epoch_session_id='session_123',
            epochprobemap=None,
            epoch_clock=ClockType.UTC,
            t0_t1=(0.0, 100.0),
            objectname='daq1',
            objectclass='ndi.daq.system'
        )
        assert node.epoch_id == 'epoch_001'
        assert node.epoch_clock == ClockType.UTC
        assert node.t0_t1 == (0.0, 100.0)

    def test_to_dict(self):
        """Test converting to dict."""
        node = EpochNode(
            epoch_id='epoch_001',
            epoch_session_id='session_123',
            epochprobemap=None,
            epoch_clock=ClockType.UTC,
            t0_t1=(0.0, 100.0),
            objectname='daq1',
            objectclass='ndi.daq.system'
        )
        d = node.to_dict()
        assert d['epoch_id'] == 'epoch_001'
        assert d['epoch_clock'] == 'utc'
        assert d['t0_t1'] == [0.0, 100.0]

    def test_from_dict(self):
        """Test creating from dict."""
        d = {
            'epoch_id': 'epoch_001',
            'epoch_session_id': 'session_123',
            'epochprobemap': None,
            'epoch_clock': 'utc',
            't0_t1': [0.0, 100.0],
            'objectname': 'daq1',
            'objectclass': 'ndi.daq.system'
        }
        node = EpochNode.from_dict(d)
        assert node.epoch_id == 'epoch_001'
        assert node.epoch_clock == ClockType.UTC
        assert node.t0_t1 == (0.0, 100.0)


class TestSyncGraph:
    """Tests for SyncGraph class."""

    def test_create_empty_syncgraph(self):
        """Test creating an empty sync graph."""
        sg = SyncGraph()
        assert sg.rules == []
        assert sg.session is None

    def test_add_rule(self):
        """Test adding a sync rule."""
        sg = SyncGraph()
        rule = FileMatch()
        sg.add_rule(rule)

        assert len(sg.rules) == 1
        assert sg.rules[0] == rule

    def test_add_duplicate_rule(self):
        """Test that duplicate rules aren't added."""
        sg = SyncGraph()
        rule = FileMatch({'number_fullpath_matches': 2})
        sg.add_rule(rule)
        sg.add_rule(rule)  # Same rule

        assert len(sg.rules) == 1

    def test_remove_rule(self):
        """Test removing a sync rule."""
        sg = SyncGraph()
        rule1 = FileMatch({'number_fullpath_matches': 2})
        rule2 = FileMatch({'number_fullpath_matches': 3})
        sg.add_rule(rule1)
        sg.add_rule(rule2)

        sg.remove_rule(0)
        assert len(sg.rules) == 1
        assert sg.rules[0].parameters['number_fullpath_matches'] == 3

    def test_has_unique_id(self):
        """Test that sync graph has unique ID."""
        sg1 = SyncGraph()
        sg2 = SyncGraph()
        assert sg1.id != sg2.id
