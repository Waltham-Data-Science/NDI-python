"""PR5 DAQ/epoch parity tests (§3.4-4 analog-event channels, others added alongside).

§3.4-4: ndi.daq.system.mfdaq must recognize the analog-event/analog-mark channel
types (aep/aen/aimp/aimn) and strip/re-attach the ``_t<threshold>`` suffix, like
MATLAB mfdaq_prefix/mfdaq_type (2157c70f).
"""

from __future__ import annotations

from ndi.daq.mfdaq import standardize_channel_type, strip_threshold_suffix
from ndi.daq.system_mfdaq import ndi_daq_system_mfdaq as MFDAQ


class TestStripThreshold:
    def test_strips_threshold_suffix(self):
        assert strip_threshold_suffix("aep_t2.5") == "aep"
        assert strip_threshold_suffix("aimn_t-3") == "aimn"
        assert strip_threshold_suffix("analog_in") == "analog_in"  # no suffix
        assert strip_threshold_suffix("ai") == "ai"


class TestAnalogEventType:
    def test_standardize_analog_event_types(self):
        assert standardize_channel_type("aep") == "analog_in_event_pos"
        assert standardize_channel_type("aen") == "analog_in_event_neg"
        assert standardize_channel_type("aimp") == "analog_in_mark_pos"
        assert standardize_channel_type("aimn") == "analog_in_mark_neg"
        assert standardize_channel_type("ae") == "analog_in_event_pos"
        assert standardize_channel_type("aim") == "analog_in_mark_pos"

    def test_standardize_strips_threshold(self):
        assert standardize_channel_type("aep_t5") == "analog_in_event_pos"
        assert standardize_channel_type("aimn_t2.5") == "analog_in_mark_neg"

    def test_basic_types_unchanged(self):
        assert standardize_channel_type("ai") == "analog_in"
        assert standardize_channel_type("mk") == "marker"
        assert standardize_channel_type("analog_in") == "analog_in"


class TestMfdaqPrefix:
    def test_analog_event_prefixes(self):
        assert MFDAQ.mfdaq_prefix("analog_in_event_pos") == "aep"
        assert MFDAQ.mfdaq_prefix("analog_in_event_neg") == "aen"
        assert MFDAQ.mfdaq_prefix("analog_in_mark_pos") == "aimp"
        assert MFDAQ.mfdaq_prefix("analog_in_mark_neg") == "aimn"
        assert MFDAQ.mfdaq_prefix("aep") == "aep"

    def test_digital_event_prefixes(self):
        assert MFDAQ.mfdaq_prefix("digital_in_event_pos") == "dep"
        assert MFDAQ.mfdaq_prefix("digital_in_mark_neg") == "dimn"

    def test_threshold_reattached_only_for_analog_events(self):
        # analog-event prefix keeps the threshold suffix
        assert MFDAQ.mfdaq_prefix("aep_t2.5") == "aep_t2.5"
        assert MFDAQ.mfdaq_prefix("analog_in_mark_neg_t-3") == "aimn_t-3"
        # a non-analog-event channel does not carry it through
        assert MFDAQ.mfdaq_prefix("analog_in") == "ai"

    def test_basic_prefixes_unchanged(self):
        assert MFDAQ.mfdaq_prefix("analog_in") == "ai"
        assert MFDAQ.mfdaq_prefix("digital_out") == "do"
        assert MFDAQ.mfdaq_prefix("time") == "t"

    def test_mfdaq_type_strips_threshold(self):
        assert MFDAQ.mfdaq_type("aep_t5") == "analog_in_event_pos"
        assert MFDAQ.mfdaq_type("aimn") == "analog_in_mark_neg"


class TestVHAudreyBPodTransform:
    """§3.4-5: readAudreyBPodJson 7-stimulus transform."""

    def _config(self):
        s = {
            "DelayB4NextStim": 1.5,
            "WashDuration": 3.0,
            "InterStimTime": 2.0,
            "WaterSolenoidNum": 7,
        }
        for k in range(1, 7):
            s[f"Sol{k}"] = 1
            s[f"Sol{k}Valve"] = k
            s[f"Sol{k}_Tastant"] = "water" if k == 1 else f"tastant{k}"
            s[f"Stim{k}OpenDuration"] = 0.1 * k
        return s

    def test_produces_seven_entries(self):
        from ndi.daq.metadatareader.vhaudreybpod_stims import (
            ndi_daq_metadatareader_VHAudreyBPod as BPod,
        )

        params = BPod.read_audrey_bpod_json(self._config())
        assert len(params) == 7
        assert [p["stimid"] for p in params] == [1, 2, 3, 4, 5, 6, 7]

    def test_solenoid_entries(self):
        from ndi.daq.metadatareader.vhaudreybpod_stims import (
            ndi_daq_metadatareader_VHAudreyBPod as BPod,
        )

        params = BPod.read_audrey_bpod_json(self._config())
        p3 = params[2]
        assert p3["solenoidValve"] == 3
        assert p3["tastant"] == "tastant3"
        assert abs(p3["solenoidOpenDuration"] - 0.3) < 1e-9
        assert p3["DelayBeforeNextStim"] == 1.5
        assert p3["InterStimulusTime"] == 2.0
        assert p3["isblank"] == 0
        # entry 1 has tastant 'water' -> isblank=1
        assert params[0]["isblank"] == 1

    def test_water_entry(self):
        from ndi.daq.metadatareader.vhaudreybpod_stims import (
            ndi_daq_metadatareader_VHAudreyBPod as BPod,
        )

        water = BPod.read_audrey_bpod_json(self._config())[6]
        assert water["stimid"] == 7
        assert water["isUsed"] == 1
        assert water["solenoidValve"] == 7
        assert water["tastant"] == "Water"
        assert water["solenoidOpenDuration"] == 3.0
        assert water["isblank"] == 0
