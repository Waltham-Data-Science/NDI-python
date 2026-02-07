"""
Port of MATLAB ndi.unittest.element.OneEpochTest tests.

MATLAB source files:
  +element/OneEpochTest.m → TestOneEpoch

Tests the element module including:
  - Element instantiation and basic properties
  - Element epoch table management
  - oneepoch() function for creating single-epoch concatenated elements
  - missingepochs() function for comparing epoch tables
  - downsample_timeseries() for signal processing

The MATLAB tests use WhiteMatter fixtures with real Intan data.
We provide mocked tests that exercise the same APIs.
"""

from unittest.mock import MagicMock

import numpy as np
import pytest

# ===========================================================================
# TestElementInstantiation — Element creation and basic properties
# ===========================================================================


class TestElementInstantiation:
    """Port of ndi.unittest.element basic tests."""

    def test_create_element_no_session(self):
        """Element can be created without a session."""
        from ndi.element import Element

        elem = Element(name="electrode1", reference=1, type="n-trode")
        assert elem is not None
        assert elem.name == "electrode1"
        assert elem.reference == 1

    def test_create_element_with_session(self):
        """Element can be created with a mocked session."""
        from ndi.element import Element

        session = MagicMock()
        session.id.return_value = "session-123"
        elem = Element(
            session=session,
            name="cortex",
            reference=1,
            type="n-trode",
        )
        assert elem.session is session
        assert elem.name == "cortex"

    def test_element_type_attribute(self):
        """Element stores type correctly."""
        from ndi.element import Element

        elem = Element(name="stim", reference=0, type="stimulator")
        assert elem._type == "stimulator"

    def test_element_default_values(self):
        """Element has correct default values."""
        from ndi.element import Element

        elem = Element()
        assert elem.name == ""
        assert elem.reference == 0

    def test_element_subject_id(self):
        """Element stores subject_id."""
        from ndi.element import Element

        elem = Element(
            name="e1",
            reference=1,
            type="n-trode",
            subject_id="subj-001",
        )
        assert elem.subject_id == "subj-001"

    def test_element_underlying_element(self):
        """Element stores underlying_element reference."""
        from ndi.element import Element

        parent = Element(name="parent", reference=1, type="n-trode")
        child = Element(
            name="child",
            reference=1,
            type="timeseries",
            underlying_element=parent,
        )
        assert child.underlying_element is parent

    def test_element_direct_flag(self):
        """Element stores direct flag."""
        from ndi.element import Element

        elem = Element(name="e1", reference=1, direct=False)
        assert elem.direct is False

    def test_element_inherits_ido(self):
        """Element inherits from Ido (has unique identifier)."""
        from ndi.element import Element
        from ndi.ido import Ido

        elem = Element(name="e1", reference=1)
        assert isinstance(elem, Ido)

    def test_element_inherits_epochset(self):
        """Element inherits from EpochSet."""
        from ndi.element import Element
        from ndi.epoch.epochset import EpochSet

        elem = Element(name="e1", reference=1)
        assert isinstance(elem, EpochSet)

    def test_element_inherits_documentservice(self):
        """Element inherits from DocumentService."""
        from ndi.documentservice import DocumentService
        from ndi.element import Element

        elem = Element(name="e1", reference=1)
        assert isinstance(elem, DocumentService)


# ===========================================================================
# TestElementEpochTable — Epoch table operations
# ===========================================================================


class TestElementEpochTable:
    """Port of ndi.unittest.element.OneEpochTest — epoch table tests."""

    def test_epochtable_no_session(self):
        """epochtable returns empty for element with no session."""
        from ndi.element import Element

        elem = Element(name="e1", reference=1)
        et = elem.buildepochtable()
        assert isinstance(et, list)
        assert len(et) == 0

    def test_elementstring(self):
        """elementstring returns formatted string."""
        from ndi.element import Element

        elem = Element(name="cortex", reference=1)
        s = elem.elementstring()
        assert "cortex" in s

    def test_epochsetname(self):
        """epochsetname returns name string."""
        from ndi.element import Element

        elem = Element(name="cortex", reference=1, type="n-trode")
        name = elem.epochsetname()
        assert isinstance(name, str)
        assert len(name) > 0


# ===========================================================================
# TestOneEpoch — Port of OneEpochTest.m
# ===========================================================================


class TestOneEpoch:
    """Port of ndi.unittest.element.OneEpochTest — oneepoch function tests."""

    def test_oneepoch_creates_element(self):
        """oneepoch() creates a new Element."""
        from ndi.element import Element
        from ndi.element.functions import oneepoch

        session = MagicMock()
        session.id.return_value = "session-123"

        # Create input element with mock epoch table
        input_elem = MagicMock()
        input_elem.name = "probe1"
        input_elem.reference = 1
        input_elem._type = "timeseries"
        input_elem.epochtable.return_value = [
            {"epoch_id": "epoch_001", "epoch_clock": "utc"},
        ]

        result = oneepoch(session, input_elem, "probe1_oneepoch", 1)
        assert isinstance(result, Element)
        assert result.name == "probe1_oneepoch"
        assert result.reference == 1

    def test_oneepoch_preserves_type(self):
        """oneepoch() preserves the element type."""
        from ndi.element.functions import oneepoch

        session = MagicMock()
        input_elem = MagicMock()
        input_elem._type = "timeseries"
        input_elem.epochtable.return_value = [
            {"epoch_id": "epoch_001"},
        ]

        result = oneepoch(session, input_elem, "out", 1)
        assert result._type == "timeseries"

    def test_oneepoch_empty_epochs_raises(self):
        """oneepoch() raises ValueError for element with no epochs."""
        from ndi.element.functions import oneepoch

        session = MagicMock()
        input_elem = MagicMock()
        input_elem.epochtable.return_value = []

        with pytest.raises(ValueError, match="no epochs"):
            oneepoch(session, input_elem, "out", 1)

    def test_oneepoch_multiple_epochs(self):
        """oneepoch() works with multiple input epochs."""
        from ndi.element import Element
        from ndi.element.functions import oneepoch

        session = MagicMock()
        input_elem = MagicMock()
        input_elem._type = "timeseries"
        input_elem.epochtable.return_value = [
            {"epoch_id": "epoch_001", "epoch_clock": "utc"},
            {"epoch_id": "epoch_002", "epoch_clock": "utc"},
        ]

        result = oneepoch(session, input_elem, "combined", 1)
        assert isinstance(result, Element)

    def test_oneepoch_with_list_epochs(self):
        """oneepoch() works when epoch table is provided as a list."""
        from ndi.element.functions import oneepoch

        session = MagicMock()
        input_elem = [
            {"epoch_id": "epoch_001"},
            {"epoch_id": "epoch_002"},
        ]

        result = oneepoch(session, input_elem, "out", 1)
        assert result is not None


# ===========================================================================
# TestMissingEpochs — Port of missingepochs function
# ===========================================================================


class TestMissingEpochs:
    """Tests for ndi.element.functions.missingepochs."""

    def test_no_missing_epochs(self):
        """missingepochs returns False when all epochs present."""
        from ndi.element.functions import missingepochs

        elem1 = MagicMock()
        elem1.epochtable.return_value = [
            {"epoch_id": "e1"},
            {"epoch_id": "e2"},
        ]
        elem2 = MagicMock()
        elem2.epochtable.return_value = [
            {"epoch_id": "e1"},
            {"epoch_id": "e2"},
            {"epoch_id": "e3"},
        ]

        missing, ids = missingepochs(elem1, elem2)
        assert missing is False
        assert ids == []

    def test_missing_epochs_detected(self):
        """missingepochs returns True and lists missing epoch IDs."""
        from ndi.element.functions import missingepochs

        elem1 = MagicMock()
        elem1.epochtable.return_value = [
            {"epoch_id": "e1"},
            {"epoch_id": "e2"},
            {"epoch_id": "e3"},
        ]
        elem2 = MagicMock()
        elem2.epochtable.return_value = [
            {"epoch_id": "e1"},
        ]

        missing, ids = missingepochs(elem1, elem2)
        assert missing is True
        assert "e2" in ids
        assert "e3" in ids

    def test_missing_epochs_empty_element2(self):
        """missingepochs detects all missing when element2 is empty."""
        from ndi.element.functions import missingepochs

        elem1 = MagicMock()
        elem1.epochtable.return_value = [
            {"epoch_id": "e1"},
        ]
        elem2 = MagicMock()
        elem2.epochtable.return_value = []

        missing, ids = missingepochs(elem1, elem2)
        assert missing is True
        assert "e1" in ids

    def test_missing_epochs_both_empty(self):
        """missingepochs returns False when both elements have no epochs."""
        from ndi.element.functions import missingepochs

        elem1 = MagicMock()
        elem1.epochtable.return_value = []
        elem2 = MagicMock()
        elem2.epochtable.return_value = []

        missing, ids = missingepochs(elem1, elem2)
        assert missing is False
        assert ids == []


# ===========================================================================
# TestSpikesForProbe — Port of spikesForProbe function
# ===========================================================================


class TestSpikesForProbe:
    """Tests for ndi.element.functions.spikes_for_probe."""

    def test_creates_spike_element(self):
        """spikes_for_probe creates an element of type 'spikes'."""
        from ndi.element import Element
        from ndi.element.functions import spikes_for_probe

        session = MagicMock()
        probe = MagicMock()
        probe.epochtable.return_value = [
            {"epoch_id": "epoch_001"},
        ]

        spikedata = [
            {"epochid": "epoch_001", "spiketimes": [0.1, 0.5]},
        ]

        result = spikes_for_probe(session, probe, "unit1", 1, spikedata)
        assert isinstance(result, Element)
        assert result._type == "spikes"

    def test_invalid_epoch_raises(self):
        """spikes_for_probe raises ValueError for unknown epoch."""
        from ndi.element.functions import spikes_for_probe

        session = MagicMock()
        probe = MagicMock()
        probe.epochtable.return_value = [
            {"epoch_id": "epoch_001"},
        ]

        spikedata = [
            {"epochid": "epoch_999", "spiketimes": [0.1]},
        ]

        with pytest.raises(ValueError, match="not found"):
            spikes_for_probe(session, probe, "unit1", 1, spikedata)


# ===========================================================================
# TestDownsampleTimeseries — Port of downsample function tests
# ===========================================================================


class TestDownsampleTimeseries:
    """Tests for ndi.element.functions.downsample_timeseries."""

    def test_downsample_basic(self):
        """downsample_timeseries reduces sample count."""
        from ndi.element.functions import downsample_timeseries

        # Create 1000 Hz signal, 1 second
        fs = 1000
        t = np.linspace(0, 1, fs, endpoint=False)
        d = np.sin(2 * np.pi * 10 * t)  # 10 Hz sine

        # Downsample to 100 Hz
        t_out, d_out = downsample_timeseries(t, d, 50.0)
        assert len(t_out) < len(t)
        assert len(d_out) == len(t_out)

    def test_downsample_no_change_if_below_nyquist(self):
        """downsample_timeseries returns unchanged if fs <= 2*lp_freq."""
        from ndi.element.functions import downsample_timeseries

        fs = 100
        t = np.linspace(0, 1, fs, endpoint=False)
        d = np.sin(2 * np.pi * 10 * t)

        # lp_freq = 100 Hz, so fs (100) <= 2*100 — no downsampling
        t_out, d_out = downsample_timeseries(t, d, 100.0)
        assert len(t_out) == len(t)
        np.testing.assert_array_equal(t_out, t)

    def test_downsample_short_signal(self):
        """downsample_timeseries handles very short signals."""
        from ndi.element.functions import downsample_timeseries

        t = np.array([0.0])
        d = np.array([1.0])

        t_out, d_out = downsample_timeseries(t, d, 50.0)
        np.testing.assert_array_equal(t_out, t)
        np.testing.assert_array_equal(d_out, d)

    def test_downsample_multichannel(self):
        """downsample_timeseries works with multi-channel data."""
        from ndi.element.functions import downsample_timeseries

        fs = 1000
        t = np.linspace(0, 1, fs, endpoint=False)
        d = np.column_stack(
            [
                np.sin(2 * np.pi * 10 * t),
                np.cos(2 * np.pi * 10 * t),
            ]
        )

        t_out, d_out = downsample_timeseries(t, d, 50.0)
        assert d_out.shape[1] == 2
        assert len(t_out) < len(t)

    def test_downsample_element_function(self):
        """downsample() creates a new Element."""
        from ndi.element import Element
        from ndi.element.functions import downsample

        session = MagicMock()
        input_elem = MagicMock()
        input_elem._type = "timeseries"
        input_elem.epochtable.return_value = [
            {"epoch_id": "epoch_001"},
        ]

        result = downsample(session, input_elem, 50.0, "ds_output", 1)
        assert isinstance(result, Element)

    def test_downsample_invalid_frequency_raises(self):
        """downsample() raises for non-positive frequency."""
        from ndi.element.functions import downsample

        session = MagicMock()
        input_elem = MagicMock()
        input_elem.epochtable.return_value = [
            {"epoch_id": "epoch_001"},
        ]

        with pytest.raises(ValueError, match="positive"):
            downsample(session, input_elem, -10.0, "out", 1)

    def test_downsample_empty_epochs_raises(self):
        """downsample() raises for element with no epochs."""
        from ndi.element.functions import downsample

        session = MagicMock()
        input_elem = MagicMock()
        input_elem.epochtable.return_value = []

        with pytest.raises(ValueError, match="no epochs"):
            downsample(session, input_elem, 50.0, "out", 1)
