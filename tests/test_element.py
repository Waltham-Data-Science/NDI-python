"""
Tests for ndi.epoch, ndi.element, and ndi.probe (Phase 6).

Tests cover:
- EpochProbeMap dataclass
- EpochSet abstract base class
- Epoch immutable data class
- Element base class
- Probe specialized element
"""

import pytest
from unittest.mock import MagicMock, patch
from typing import Dict, List, Any

import numpy as np

from ndi.epoch.epochprobemap import EpochProbeMap, parse_devicestring, build_devicestring
from ndi.epoch.epochset import EpochSet
from ndi.epoch.epoch import Epoch, is_epoch_or_empty
from ndi.element import Element
from ndi.probe import Probe
from ndi.documentservice import DocumentService
from ndi.time import ClockType, DEV_LOCAL_TIME, UTC


# =============================================================================
# EpochProbeMap Tests
# =============================================================================

class TestEpochProbeMap:
    """Tests for EpochProbeMap dataclass."""

    def test_creation(self):
        """Test creating an EpochProbeMap."""
        epm = EpochProbeMap(
            name='electrode1',
            reference=1,
            type='n-trode',
            devicestring='intan1:SpikeInterfaceReader:',
            subjectstring='mouse001',
        )
        assert epm.name == 'electrode1'
        assert epm.reference == 1
        assert epm.type == 'n-trode'

    def test_whitespace_in_name_raises(self):
        """Test that whitespace in name raises error."""
        with pytest.raises(ValueError, match="name cannot contain whitespace"):
            EpochProbeMap(name='electrode 1', reference=1, type='n-trode')

    def test_whitespace_in_type_raises(self):
        """Test that whitespace in type raises error."""
        with pytest.raises(ValueError, match="type cannot contain whitespace"):
            EpochProbeMap(name='electrode1', reference=1, type='n trode')

    def test_negative_reference_raises(self):
        """Test that negative reference raises error."""
        with pytest.raises(ValueError, match="reference must be non-negative"):
            EpochProbeMap(name='electrode1', reference=-1, type='n-trode')

    def test_devicename_property(self):
        """Test devicename property extraction."""
        epm = EpochProbeMap(
            name='e1', reference=1, type='probe',
            devicestring='intan1:SpikeInterfaceReader:details'
        )
        assert epm.devicename == 'intan1'

    def test_deviceclass_property(self):
        """Test deviceclass property extraction."""
        epm = EpochProbeMap(
            name='e1', reference=1, type='probe',
            devicestring='intan1:SpikeInterfaceReader:details'
        )
        assert epm.deviceclass == 'SpikeInterfaceReader'

    def test_matches_all(self):
        """Test matches with all criteria."""
        epm = EpochProbeMap(name='e1', reference=1, type='probe')
        assert epm.matches(name='e1', reference=1, type='probe') is True
        assert epm.matches(name='e2', reference=1, type='probe') is False

    def test_matches_partial(self):
        """Test matches with partial criteria."""
        epm = EpochProbeMap(name='e1', reference=1, type='probe')
        assert epm.matches(name='e1') is True
        assert epm.matches(reference=1) is True
        assert epm.matches(type='probe') is True
        assert epm.matches() is True

    def test_to_dict(self):
        """Test conversion to dictionary."""
        epm = EpochProbeMap(
            name='e1', reference=1, type='probe',
            devicestring='dev:class:', subjectstring='subj'
        )
        d = epm.to_dict()
        assert d['name'] == 'e1'
        assert d['reference'] == 1
        assert d['type'] == 'probe'

    def test_from_dict(self):
        """Test creation from dictionary."""
        d = {'name': 'e1', 'reference': 1, 'type': 'probe'}
        epm = EpochProbeMap.from_dict(d)
        assert epm.name == 'e1'
        assert epm.reference == 1

    def test_str(self):
        """Test string representation."""
        epm = EpochProbeMap(name='e1', reference=1, type='probe')
        assert str(epm) == 'e1|1|probe'

    def test_equality(self):
        """Test equality comparison."""
        epm1 = EpochProbeMap(name='e1', reference=1, type='probe')
        epm2 = EpochProbeMap(name='e1', reference=1, type='probe')
        epm3 = EpochProbeMap(name='e2', reference=1, type='probe')
        assert epm1 == epm2
        assert epm1 != epm3


class TestDeviceStringHelpers:
    """Tests for device string helper functions."""

    def test_parse_devicestring(self):
        """Test parsing device string."""
        result = parse_devicestring('intan1:SpikeInterfaceReader:extra:info')
        assert result['name'] == 'intan1'
        assert result['class'] == 'SpikeInterfaceReader'
        assert result['details'] == 'extra:info'

    def test_build_devicestring(self):
        """Test building device string."""
        assert build_devicestring('dev', 'cls', 'det') == 'dev:cls:det'
        assert build_devicestring('dev', 'cls') == 'dev:cls:'
        assert build_devicestring('dev') == 'dev'


# =============================================================================
# EpochSet Tests
# =============================================================================

class ConcreteEpochSet(EpochSet):
    """Concrete implementation for testing."""

    def __init__(self, epochs=None):
        super().__init__()
        self._epochs = epochs or []

    def buildepochtable(self):
        return self._epochs

    def epochsetname(self):
        return 'test_epochset'

    def issyncgraphroot(self):
        return True


class TestEpochSet:
    """Tests for EpochSet abstract base class."""

    def test_epochtable_caching(self):
        """Test epoch table caching."""
        epochs = [{'epoch_number': 1, 'epoch_id': 'ep1'}]
        es = ConcreteEpochSet(epochs)

        et1, hash1 = es.epochtable()
        et2, hash2 = es.epochtable()

        assert et1 is et2  # Same cached object
        assert hash1 == hash2

    def test_epochtable_force_rebuild(self):
        """Test force rebuild of epoch table."""
        epochs = [{'epoch_number': 1, 'epoch_id': 'ep1'}]
        es = ConcreteEpochSet(epochs)

        et1, _ = es.epochtable()
        es._epochs = [{'epoch_number': 1, 'epoch_id': 'ep2'}]
        et2, _ = es.epochtable(force_rebuild=True)

        assert et2[0]['epoch_id'] == 'ep2'

    def test_numepochs(self):
        """Test numepochs method."""
        epochs = [
            {'epoch_number': 1, 'epoch_id': 'ep1'},
            {'epoch_number': 2, 'epoch_id': 'ep2'},
        ]
        es = ConcreteEpochSet(epochs)
        assert es.numepochs() == 2

    def test_epochclock(self):
        """Test epochclock method."""
        epochs = [
            {'epoch_number': 1, 'epoch_id': 'ep1', 'epoch_clock': [DEV_LOCAL_TIME]},
        ]
        es = ConcreteEpochSet(epochs)
        clocks = es.epochclock(1)
        assert clocks == [DEV_LOCAL_TIME]

    def test_epochclock_out_of_range(self):
        """Test epochclock with invalid epoch number."""
        es = ConcreteEpochSet([{'epoch_number': 1, 'epoch_id': 'ep1'}])
        with pytest.raises(IndexError):
            es.epochclock(5)

    def test_t0_t1(self):
        """Test t0_t1 method."""
        epochs = [
            {'epoch_number': 1, 'epoch_id': 'ep1', 't0_t1': [(0.0, 10.0)]},
        ]
        es = ConcreteEpochSet(epochs)
        t0t1 = es.t0_t1(1)
        assert t0t1 == [(0.0, 10.0)]

    def test_epochid(self):
        """Test epochid method."""
        epochs = [{'epoch_number': 1, 'epoch_id': 'my_epoch_123'}]
        es = ConcreteEpochSet(epochs)
        assert es.epochid(1) == 'my_epoch_123'

    def test_epochnumber(self):
        """Test epochnumber method."""
        epochs = [
            {'epoch_number': 1, 'epoch_id': 'ep1'},
            {'epoch_number': 2, 'epoch_id': 'ep2'},
        ]
        es = ConcreteEpochSet(epochs)
        assert es.epochnumber('ep2') == 2

    def test_epochnumber_not_found(self):
        """Test epochnumber with unknown ID."""
        es = ConcreteEpochSet([{'epoch_number': 1, 'epoch_id': 'ep1'}])
        with pytest.raises(ValueError):
            es.epochnumber('unknown')

    def test_clear_cache(self):
        """Test cache clearing."""
        es = ConcreteEpochSet([{'epoch_number': 1, 'epoch_id': 'ep1'}])
        es.epochtable()  # Populate cache
        assert es._epochtable_cache is not None

        es.clear_cache()
        assert es._epochtable_cache is None


# =============================================================================
# Epoch Tests
# =============================================================================

class TestEpoch:
    """Tests for Epoch immutable data class."""

    def test_creation(self):
        """Test creating an Epoch."""
        epoch = Epoch(
            epoch_number=1,
            epoch_id='ep_abc123',
            epoch_session_id='sess_xyz',
        )
        assert epoch.epoch_number == 1
        assert epoch.epoch_id == 'ep_abc123'

    def test_immutability(self):
        """Test that Epoch is immutable."""
        epoch = Epoch(epoch_number=1, epoch_id='ep1')
        with pytest.raises(AttributeError):
            epoch.epoch_number = 2

    def test_from_dict(self):
        """Test creating Epoch from dictionary."""
        data = {
            'epoch_number': 1,
            'epoch_id': 'ep1',
            'epoch_session_id': 'sess1',
            'epochprobemap': [{'name': 'e1', 'reference': 1, 'type': 'probe'}],
            'epoch_clock': ['dev_local_time'],
            't0_t1': [(0.0, 10.0)],
        }
        epoch = Epoch.from_dict(data)
        assert epoch.epoch_number == 1
        assert len(epoch.epochprobemap) == 1

    def test_to_dict(self):
        """Test converting Epoch to dictionary."""
        epm = EpochProbeMap(name='e1', reference=1, type='probe')
        epoch = Epoch(
            epoch_number=1,
            epoch_id='ep1',
            epochprobemap=(epm,),
            epoch_clock=(DEV_LOCAL_TIME,),
            t0_t1=((0.0, 10.0),),
        )
        d = epoch.to_dict()
        assert d['epoch_number'] == 1
        assert d['epoch_id'] == 'ep1'

    def test_has_clock(self):
        """Test has_clock method."""
        epoch = Epoch(
            epoch_number=1,
            epoch_id='ep1',
            epoch_clock=(DEV_LOCAL_TIME, UTC),
        )
        assert epoch.has_clock(DEV_LOCAL_TIME) is True
        assert epoch.has_clock(ClockType.EXP_GLOBAL_TIME) is False

    def test_time_range(self):
        """Test time_range method."""
        epoch = Epoch(
            epoch_number=1,
            epoch_id='ep1',
            epoch_clock=(DEV_LOCAL_TIME, UTC),
            t0_t1=((0.0, 10.0), (100.0, 110.0)),
        )
        assert epoch.time_range(DEV_LOCAL_TIME) == (0.0, 10.0)
        assert epoch.time_range(UTC) == (100.0, 110.0)

    def test_matches_probe(self):
        """Test matches_probe method."""
        epm = EpochProbeMap(name='e1', reference=1, type='probe')
        epoch = Epoch(
            epoch_number=1,
            epoch_id='ep1',
            epochprobemap=(epm,),
        )
        assert epoch.matches_probe('e1', 1, 'probe') is True
        assert epoch.matches_probe('e2', 1, 'probe') is False


class TestIsEpochOrEmpty:
    """Tests for is_epoch_or_empty validator."""

    def test_none(self):
        """Test with None."""
        assert is_epoch_or_empty(None) is True

    def test_epoch(self):
        """Test with Epoch."""
        epoch = Epoch(epoch_number=1, epoch_id='ep1')
        assert is_epoch_or_empty(epoch) is True

    def test_empty_list(self):
        """Test with empty list."""
        assert is_epoch_or_empty([]) is True

    def test_list_of_epochs(self):
        """Test with list of Epochs."""
        epochs = [Epoch(epoch_number=i, epoch_id=f'ep{i}') for i in range(3)]
        assert is_epoch_or_empty(epochs) is True

    def test_invalid(self):
        """Test with invalid value."""
        assert is_epoch_or_empty("not an epoch") is False


# =============================================================================
# Element Tests
# =============================================================================

class TestElement:
    """Tests for Element base class."""

    def test_creation(self):
        """Test creating an Element."""
        elem = Element(
            name='electrode1',
            reference=1,
            type='n-trode',
        )
        assert elem.name == 'electrode1'
        assert elem.reference == 1
        assert elem.type == 'n-trode'

    def test_whitespace_in_name_raises(self):
        """Test that whitespace in name raises error."""
        with pytest.raises(ValueError, match="name cannot contain whitespace"):
            Element(name='electrode 1', reference=1, type='n-trode')

    def test_negative_reference_raises(self):
        """Test that negative reference raises error."""
        with pytest.raises(ValueError, match="reference must be non-negative"):
            Element(name='electrode1', reference=-1, type='n-trode')

    def test_elementstring(self):
        """Test elementstring method."""
        elem = Element(name='electrode1', reference=1, type='n-trode')
        assert elem.elementstring() == 'electrode1 | 1'

    def test_epochsetname(self):
        """Test epochsetname method."""
        elem = Element(name='electrode1', reference=1, type='n-trode')
        assert 'element' in elem.epochsetname()
        assert 'electrode1' in elem.epochsetname()

    def test_issyncgraphroot_no_underlying(self):
        """Test issyncgraphroot with no underlying element."""
        elem = Element(name='e1', reference=1, type='probe')
        assert elem.issyncgraphroot() is True

    def test_issyncgraphroot_with_underlying(self):
        """Test issyncgraphroot with underlying element."""
        underlying = Element(name='base', reference=0, type='base')
        elem = Element(
            name='derived',
            reference=1,
            type='derived',
            underlying_element=underlying,
        )
        assert elem.issyncgraphroot() is False

    def test_direct_epochtable(self):
        """Test epoch table from direct underlying element."""
        # Create underlying with mock epoch table
        underlying = Element(name='base', reference=0, type='base')
        underlying._epochtable_cache = [
            {'epoch_number': 1, 'epoch_id': 'ep1', 'epoch_clock': [], 't0_t1': []}
        ]
        underlying._epochtable_hash = 'hash1'

        elem = Element(
            name='derived',
            reference=1,
            type='derived',
            underlying_element=underlying,
            direct=True,
        )

        et, _ = elem.epochtable()
        assert len(et) == 1
        assert et[0]['epoch_id'] == 'ep1'

    def test_equality(self):
        """Test element equality."""
        elem1 = Element(name='e1', reference=1, type='probe')
        elem2 = Element(name='e1', reference=1, type='probe')
        elem3 = Element(name='e2', reference=1, type='probe')

        assert elem1 == elem2
        assert elem1 != elem3

    def test_has_unique_id(self):
        """Test that elements have unique IDs."""
        elem1 = Element(name='e1', reference=1, type='probe')
        elem2 = Element(name='e1', reference=1, type='probe')
        assert elem1.id != elem2.id

    def test_newdocument(self):
        """Test newdocument method."""
        elem = Element(name='e1', reference=1, type='probe')
        try:
            doc = elem.newdocument()
            assert doc is not None
            # Check document has correct properties
            assert hasattr(doc, 'document_properties')
        except FileNotFoundError:
            # Schema not available in test environment
            pytest.skip("Element JSON schema not available")

    def test_searchquery(self):
        """Test searchquery method."""
        elem = Element(name='e1', reference=1, type='probe')
        q = elem.searchquery()
        assert q is not None


# =============================================================================
# Probe Tests
# =============================================================================

class TestProbe:
    """Tests for Probe specialized element."""

    def test_creation(self):
        """Test creating a Probe."""
        probe = Probe(
            name='electrode1',
            reference=1,
            type='n-trode',
            subject_id='subj001',
        )
        assert probe.name == 'electrode1'
        assert probe.reference == 1
        assert probe.type == 'n-trode'
        assert probe.subject_id == 'subj001'

    def test_probe_is_never_direct(self):
        """Test that probes are always direct=False."""
        probe = Probe(name='e1', reference=1, type='probe')
        assert probe.direct is False

    def test_epochsetname(self):
        """Test epochsetname method."""
        probe = Probe(name='electrode1', reference=1, type='n-trode')
        assert 'probe' in probe.epochsetname()
        assert 'electrode1' in probe.epochsetname()

    def test_issyncgraphroot(self):
        """Test issyncgraphroot returns False for probes."""
        probe = Probe(name='e1', reference=1, type='probe')
        assert probe.issyncgraphroot() is False

    def test_epochprobemapmatch(self):
        """Test epochprobemapmatch method."""
        probe = Probe(name='e1', reference=1, type='probe')
        epm = EpochProbeMap(name='e1', reference=1, type='probe')

        assert probe.epochprobemapmatch(epm) is True
        assert probe.epochprobemapmatch(
            EpochProbeMap(name='e2', reference=1, type='probe')
        ) is False

    def test_epochprobemapmatch_dict(self):
        """Test epochprobemapmatch with dict."""
        probe = Probe(name='e1', reference=1, type='probe')
        epm_dict = {'name': 'e1', 'reference': 1, 'type': 'probe'}

        assert probe.epochprobemapmatch(epm_dict) is True

    def test_newdocument(self):
        """Test newdocument creates probe document."""
        probe = Probe(name='e1', reference=1, type='probe', subject_id='subj1')
        try:
            doc = probe.newdocument()
            assert doc is not None
        except FileNotFoundError:
            # Schema not available in test environment
            pytest.skip("Probe JSON schema not available")

    def test_repr(self):
        """Test string representation."""
        probe = Probe(name='e1', reference=1, type='probe')
        assert 'Probe' in repr(probe)
        assert 'e1' in repr(probe)


class TestProbeBuildEpochtable:
    """Tests for Probe.buildepochtable with mocked DAQ systems."""

    def test_buildepochtable_no_session(self):
        """Test buildepochtable with no session returns empty."""
        probe = Probe(name='e1', reference=1, type='probe')
        et = probe.buildepochtable()
        assert et == []

    def test_buildepochtable_with_matching_epoch(self):
        """Test buildepochtable finds matching epochs."""
        # Create mock session and DAQ system
        mock_session = MagicMock()

        mock_daqsys = MagicMock()
        mock_daqsys.epochtable.return_value = [
            {
                'epoch_number': 1,
                'epoch_id': 'dev_ep1',
                'epoch_session_id': 'sess1',
                'epochprobemap': [
                    EpochProbeMap(name='e1', reference=1, type='probe', devicestring='dev1::'),
                ],
                'epoch_clock': [DEV_LOCAL_TIME],
                't0_t1': [(0.0, 10.0)],
            }
        ]

        mock_session.getdaqsystems.return_value = [mock_daqsys]

        probe = Probe(session=mock_session, name='e1', reference=1, type='probe')
        et = probe.buildepochtable()

        assert len(et) == 1
        assert et[0]['epoch_id'] == 'dev_ep1'

    def test_buildepochtable_no_matching_epoch(self):
        """Test buildepochtable with no matching epochs."""
        mock_session = MagicMock()

        mock_daqsys = MagicMock()
        mock_daqsys.epochtable.return_value = [
            {
                'epoch_number': 1,
                'epoch_id': 'dev_ep1',
                'epochprobemap': [
                    EpochProbeMap(name='other', reference=99, type='other'),
                ],
                'epoch_clock': [],
                't0_t1': [],
            }
        ]

        mock_session.getdaqsystems.return_value = [mock_daqsys]

        probe = Probe(session=mock_session, name='e1', reference=1, type='probe')
        et = probe.buildepochtable()

        assert len(et) == 0


# =============================================================================
# DocumentService Tests
# =============================================================================

class TestDocumentService:
    """Tests for DocumentService mixin."""

    def test_element_implements_documentservice(self):
        """Test that Element implements DocumentService."""
        elem = Element(name='e1', reference=1, type='probe')
        assert isinstance(elem, DocumentService)
        assert hasattr(elem, 'newdocument')
        assert hasattr(elem, 'searchquery')

    def test_probe_implements_documentservice(self):
        """Test that Probe implements DocumentService."""
        probe = Probe(name='e1', reference=1, type='probe')
        assert isinstance(probe, DocumentService)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
