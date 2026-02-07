"""
Port of MATLAB ndi.unittest.probe.* tests.

MATLAB source files:
  +probe/ProbeMapTest.m   -> TestProbeMap
  +probe/ProbeTest.m      -> TestProbe

Tests for:
- ndi.probe.init_probe_type_map() / get_probe_type_map()
- ndi.probe.Probe instantiation and basic interface
"""

import pytest

from ndi.probe import Probe, init_probe_type_map, get_probe_type_map


# ===========================================================================
# TestProbeMap
# Port of: ndi.unittest.probe.ProbeMapTest
# ===========================================================================

class TestProbeMap:
    """Port of ndi.unittest.probe.ProbeMapTest.

    Verifies that the probe type -> class mapping is loaded correctly
    from probetype2object.json.
    """

    def test_init_probe_type_map(self):
        """init_probe_type_map() returns a non-empty dict.

        MATLAB equivalent: ProbeMapTest.testInitProbeTypeMap
        """
        probe_map = init_probe_type_map()
        assert isinstance(probe_map, dict)
        assert len(probe_map) > 0, 'Probe type map should be non-empty'

    def test_get_probe_type_map(self):
        """get_probe_type_map() returns the cached version, same result.

        MATLAB equivalent: ProbeMapTest.testGetProbeTypeMap
        """
        map_init = init_probe_type_map()
        map_cached = get_probe_type_map()

        assert isinstance(map_cached, dict)
        assert map_cached == map_init, \
            'Cached map should equal freshly loaded map'

    def test_map_contains_expected_types(self):
        """Map should contain some known probe types from probetype2object.json.

        MATLAB equivalent: ProbeMapTest.testMapContents
        """
        probe_map = get_probe_type_map()

        # These types are defined in ndi_common/probe/probetype2object.json
        expected_types = ['n-trode', 'patch', 'sharp', 'stimulator']

        for ptype in expected_types:
            assert ptype in probe_map, \
                f"Expected probe type '{ptype}' to be in probe type map"

    def test_map_values_are_strings(self):
        """All values in the probe type map should be class name strings.

        MATLAB equivalent: ProbeMapTest (implicit)
        """
        probe_map = get_probe_type_map()
        for key, value in probe_map.items():
            assert isinstance(key, str), f'Key should be string, got {type(key)}'
            assert isinstance(value, str), f'Value should be string, got {type(value)}'
            assert len(value) > 0, f'Class name for type "{key}" should be non-empty'

    def test_map_ntrode_class(self):
        """n-trode type maps to ndi.probe.timeseries.mfdaq.

        MATLAB equivalent: ProbeMapTest (spot check)
        """
        probe_map = get_probe_type_map()
        assert probe_map['n-trode'] == 'ndi.probe.timeseries.mfdaq'


# ===========================================================================
# TestProbe
# Port of: ndi.unittest.probe.ProbeTest
# ===========================================================================

class TestProbe:
    """Port of ndi.unittest.probe.ProbeTest.

    Tests Probe instantiation and basic interface without a session
    (since getprobes/samplerate/read_epochsamples require a full
    DAQ system setup that is not available in unit tests).
    """

    def test_probe_instantiation(self):
        """Probe can be created without a session.

        MATLAB equivalent: ProbeTest.testProbeCreate
        """
        probe = Probe(
            name='electrode1',
            reference=1,
            type='n-trode',
        )
        assert probe is not None
        assert probe._name == 'electrode1'
        assert probe._reference == 1
        assert probe._type == 'n-trode'

    def test_probe_with_session(self, tmp_path):
        """Probe can be created with a DirSession.

        MATLAB equivalent: ProbeTest.testGetprobes (setup phase)
        """
        from ndi.session.dir import DirSession

        session_dir = tmp_path / 'probe_sess'
        session_dir.mkdir()
        session = DirSession('probe_test', session_dir)

        probe = Probe(
            session=session,
            name='electrode1',
            reference=1,
            type='n-trode',
            subject_id='subject_001',
        )
        assert probe._session is session
        assert probe._name == 'electrode1'

    def test_probe_issyncgraphroot(self):
        """Probes return False from issyncgraphroot().

        MATLAB equivalent: ProbeTest (implicit property)
        """
        probe = Probe(name='test', reference=0, type='n-trode')
        assert probe.issyncgraphroot() is False

    def test_probe_epochsetname(self):
        """epochsetname() returns formatted string.

        MATLAB equivalent: ProbeTest (implicit property)
        """
        probe = Probe(name='electrode1', reference=1, type='n-trode')
        name = probe.epochsetname()
        assert 'electrode1' in name
        assert '1' in name

    def test_probe_buildepochtable_no_session(self):
        """buildepochtable() returns empty list when no session.

        MATLAB equivalent: ProbeTest (edge case)
        """
        probe = Probe(name='test', reference=0, type='n-trode')
        et = probe.buildepochtable()
        assert et == []

    def test_probe_repr(self):
        """Probe has a useful repr string.

        MATLAB equivalent: ProbeTest (implicit)
        """
        probe = Probe(name='electrode1', reference=1, type='n-trode')
        r = repr(probe)
        assert 'Probe' in r
        assert 'electrode1' in r

    def test_probe_epochprobemapmatch(self):
        """epochprobemapmatch() correctly matches dict-style probe maps.

        MATLAB equivalent: ProbeTest (functional)
        """
        probe = Probe(name='electrode1', reference=1, type='n-trode')

        matching_map = {
            'name': 'electrode1',
            'reference': 1,
            'type': 'n-trode',
        }
        non_matching_map = {
            'name': 'electrode2',
            'reference': 1,
            'type': 'n-trode',
        }

        assert probe.epochprobemapmatch(matching_map) is True
        assert probe.epochprobemapmatch(non_matching_map) is False
