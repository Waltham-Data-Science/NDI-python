"""Tests for ndi.gui.app.pyraview.

MATLAB counterparts: ndi.gui.app.pyraview and its +pyraview helper package.

Three layers, and the middle one carries the weight:

  * the transforms and the filter, which decide what is drawn;
  * the viewer's rules -- which level, whether to reload, where the
    scrollbars sit -- all plain functions, tested with no display;
  * the round trip through the real Pyraview library: build a pyramid from a
    synthetic signal and read it back at several zooms. Those skip where the
    library is not installed, since it is a compiled dependency.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from ndi.element import ndi_element
from ndi.gui.app.pyraview import pyraview as pyraview_pkg
from ndi.gui.app.pyraview.filter_data import filter_data
from ndi.gui.app.pyraview.get_data import dataset_from_document, get_data, level_file_names
from ndi.gui.app.pyraview.load_spiking_neurons import waveform_channels
from ndi.gui.app.pyraview.make_pyraview_doc import epoch_bounds, make_pyraview_doc
from ndi.gui.app.pyraview.mappings import mappings
from ndi.gui.app.pyraview.transform_plot_data import transform_plot_data
from ndi.gui.app.pyraview.transform_spike_data import transform_spike_data
from ndi.gui.app.pyraview.viewer import (
    BANDS,
    DEFAULT_SPACING,
    EMPTY_EPOCH_ITEM,
    NO_PROBES_ITEM,
    WINDOW_TAG,
    ZOOM_MAX_DURATION,
    ZOOM_MIN_DURATION,
    ZOOM_STEPS,
    clamp_view,
    duration_for_zoom,
    needs_reload,
    pan_slider_state,
    sort_spiking_info,
    spacing_or_default,
    zoom_for_duration,
)
from ndi.gui.app.session_app import SessionApp
from ndi.session.dir import ndi_session_dir
from ndi.subject import ndi_subject

SAMPLE_RATE = 30000.0
EPOCH_DURATION = 20.0
CHANNELS = 4


# ----------------------------------------------------------------------
# fakes
# ----------------------------------------------------------------------
class FakeProbe:
    """A probe with a synthetic trace, enough for the pyramid and the viewer."""

    def __init__(self, session, identifier, duration=EPOCH_DURATION, clock="dev_local_time"):
        self.session = session
        self.id = identifier
        self.duration = duration
        self.clock = clock
        self.reads = []

    def elementstring(self):
        return "ntrodeA | 1"

    def epochtable(self):
        return (
            [
                {
                    "epoch_id": "e1",
                    "epoch_clock": [{"type": self.clock}],
                    "t0_t1": [[0.0, self.duration]],
                }
            ],
            "hash",
        )

    def samplerate(self, epochid):
        return SAMPLE_RATE

    def readtimeseries(self, epochid, t0, t1):
        self.reads.append((t0, t1))
        t0 = max(t0, 0.0)
        t1 = min(t1, self.duration)
        if t1 <= t0:
            return np.zeros((0, CHANNELS))
        t = np.arange(t0, t1, 1 / SAMPLE_RATE)
        return np.sin(2 * np.pi * 10 * t)[:, None] * np.array([1.0, 2.0, 3.0, 4.0])


@pytest.fixture
def session(tmp_path):
    directory = tmp_path / "sess"
    directory.mkdir(parents=True, exist_ok=True)
    s = ndi_session_dir("pyraview_test", str(directory))
    subject_doc = ndi_subject("mouse@vhlab.org", "test mouse").newdocument()
    subject_doc.set_session_id(s.id())
    s.database_add(subject_doc)
    s._subject_doc = subject_doc
    return s


@pytest.fixture
def probe(session):
    element = ndi_element(
        session=session,
        name="ntrodeA",
        reference=1,
        type="n-trode",
        direct=False,
        subject_id=session._subject_doc.id,
    )
    session.database_add(element.newdocument())
    return FakeProbe(session, element.id)


def _library_or_skip():
    return pytest.importorskip("pyraview", reason="the Pyraview library is not installed")


# ----------------------------------------------------------------------
# the transforms
# ----------------------------------------------------------------------
class TestMappings:
    def test_raw_leaves_the_order_alone(self):
        assert mappings([1, 2, 3], "raw") == [1, 2, 3]

    def test_plexon_is_the_fixed_permutation(self):
        mapped = mappings(list(range(1, 33)), "PlexonSV")
        assert mapped[:8] == [25, 26, 27, 28, 29, 30, 31, 32]
        assert mapped[8:24] == list(range(16, 0, -1))
        assert sorted(mapped) == list(range(1, 33))

    def test_plexon_refuses_a_different_channel_set(self):
        """A wrong electrode order is invisible in the trace it draws."""
        with pytest.raises(ValueError, match="exactly channels 1:32"):
            mappings([1, 2, 3], "PlexonSV")

    def test_an_unknown_mapping_says_so(self):
        with pytest.raises(ValueError, match="mapping_name"):
            mappings([1], "nosuchmapping")


class TestFilterData:
    def test_all_and_none_are_all_pass(self):
        data = np.random.randn(100, 2)
        for band in ("all", "none"):
            filtered, spec = filter_data(data, SAMPLE_RATE, band)
            assert np.array_equal(filtered, data)
            assert spec["type"] == "none"
            assert spec["algorithm"] == "none"
            assert spec["label"] == band

    def test_a_band_records_its_design(self):
        filtered, spec = filter_data(np.random.randn(500, 2), SAMPLE_RATE, "high")
        assert filtered.shape == (500, 2)
        assert spec["type"] == "high"
        assert spec["algorithm"] == "chebyshev_1"
        assert spec["parameters"]["filterFrequency"] == 300
        assert spec["parameters"]["sampleFrequency"] == SAMPLE_RATE

    def test_a_high_pass_removes_a_slow_drift(self):
        t = np.arange(0, 1, 1 / SAMPLE_RATE)
        drift = np.linspace(0, 100, t.size)[:, None]
        filtered, _ = filter_data(drift, SAMPLE_RATE, "high")
        # The tail is where the filter has settled; the ramp should be gone.
        assert abs(filtered[-1000:].mean()) < abs(drift[-1000:].mean()) / 10

    def test_a_cutoff_above_nyquist_is_clamped_not_fatal(self):
        with pytest.warns(UserWarning, match="Nyquist"):
            filtered, _ = filter_data(np.random.randn(100, 1), 400.0, "low")
        assert filtered.shape == (100, 1)

    def test_an_unknown_band_says_so(self):
        with pytest.raises(ValueError, match="type must be one of"):
            filter_data(np.zeros((2, 1)), SAMPLE_RATE, "bandpass")


class TestTransformPlotData:
    def test_raw_channels_are_separated_by_nan(self):
        data = np.array([[1.0, 10.0], [2.0, 20.0]])
        x, y = transform_plot_data(data, np.array([0.0, 1.0]), 0, 100)
        assert np.isnan(x[2]) and np.isnan(y[2])
        assert list(y[:2]) == [1.0, 2.0]
        assert list(y[3:5]) == [110.0, 120.0]

    def test_a_decimated_sample_is_a_min_max_bar(self):
        data = np.zeros((1, 1, 2))
        data[0, 0] = [-5.0, 5.0]
        x, y = transform_plot_data(data, np.array([2.0]), 1, 100)
        assert list(x[:2]) == [2.0, 2.0]
        assert list(y[:2]) == [-5.0, 5.0]
        assert np.isnan(x[2])

    def test_a_mapping_reorders_the_channels(self):
        data = np.array([[1.0, 10.0]])
        _, plain = transform_plot_data(data, np.array([0.0]), 0, 100)
        _, swapped = transform_plot_data(data, np.array([0.0]), 0, 100, [2, 1])
        assert plain[0] == 1.0 and swapped[0] == 10.0

    def test_a_mapping_that_does_not_fit_is_warned_and_dropped(self):
        data = np.array([[1.0, 10.0]])
        with pytest.warns(UserWarning, match="mapping"):
            _, y = transform_plot_data(data, np.array([0.0]), 0, 100, [1, 2, 3])
        assert y[0] == 1.0

    def test_no_data_draws_nothing(self):
        x, y = transform_plot_data(np.zeros((0, 2)), np.array([]), 0, 100)
        assert x.size == 0 and y.size == 0


class TestTransformSpikeData:
    def _info(self, times, **extra):
        record = {"spike_times": times, "best_channel": 2}
        record.update(extra)
        return [record]

    def test_a_spike_is_a_tick_on_its_best_channel(self):
        x, y = transform_spike_data(self._info([1.0]), [0], 0.0, 2.0, 100)
        assert list(x[:2]) == [1.0, 1.0]
        assert list(y[:2]) == [140.0, 160.0]  # (2-1)*100 + 0.4/0.6 of spacing

    def test_only_spikes_in_the_window_are_drawn(self):
        x, _ = transform_spike_data(self._info([0.5, 5.0]), [0], 0.0, 1.0, 100)
        assert x.size == 3  # one tick, not two

    def test_a_box_spans_the_units_channels(self):
        x, y = transform_spike_data(
            self._info([1.0], low_channel=1, high_channel=3), [0], 0.0, 2.0, 100, show_box=True
        )
        assert x.size == 3 + 6
        assert min(y[3:-1]) == 0.0 and max(y[3:-1]) == 200.0

    def test_center_of_mass_stands_in_for_a_missing_best_channel(self):
        info = [{"spike_times": [1.0], "center_of_mass": 2.4}]
        _, y = transform_spike_data(info, [0], 0.0, 2.0, 100)
        assert y[0] == 140.0

    def test_nothing_selected_draws_nothing(self):
        x, _ = transform_spike_data(self._info([1.0]), [], 0.0, 2.0, 100)
        assert x.size == 0

    def test_an_out_of_range_selection_is_skipped(self):
        x, _ = transform_spike_data(self._info([1.0]), [0, 7], 0.0, 2.0, 100)
        assert x.size == 3


class TestWaveformChannels:
    def test_the_best_channel_is_the_most_energetic(self):
        waveform = np.zeros((3, 4))
        waveform[0] = [1, 10, 2.5, 0.25]
        waveform[2] = [-1, -10, -2.5, -0.25]
        best, low, high = waveform_channels(waveform)
        assert best == 2

    def test_the_span_is_the_channels_above_a_tenth_of_the_peak(self):
        waveform = np.zeros((3, 4))
        waveform[0] = [1, 10, 2.5, 0.25]
        waveform[2] = [-1, -10, -2.5, -0.25]
        _, low, high = waveform_channels(waveform)
        assert (low, high) == (1, 3)  # the 0.25 channel falls below the threshold

    def test_an_empty_waveform_is_channel_one(self):
        assert waveform_channels(np.zeros((0, 0))) == (1, 1, 1)


# ----------------------------------------------------------------------
# the viewer's rules
# ----------------------------------------------------------------------
class TestZoom:
    def test_the_ends_are_the_documented_durations(self):
        assert duration_for_zoom(0.0) == pytest.approx(ZOOM_MAX_DURATION)
        assert duration_for_zoom(1.0) == pytest.approx(ZOOM_MIN_DURATION)

    @pytest.mark.parametrize("duration", [0.01, 1.0, 60.0, 3600.0])
    def test_a_duration_round_trips_through_the_slider(self, duration):
        """Within one notch -- the slider has ZOOM_STEPS of them, not infinite.

        A month down to a millisecond in 200 notches makes each one about an
        11% step, so a round trip lands within half a notch of where it
        started. MATLAB quantises identically; asking for more than this
        would be asking the slider to hold positions it does not have.
        """
        notch = (ZOOM_MAX_DURATION / ZOOM_MIN_DURATION) ** (1 / ZOOM_STEPS)
        got = duration_for_zoom(zoom_for_duration(duration))
        assert 1 / notch < got / duration < notch

    def test_it_is_logarithmic_not_linear(self):
        """Linear would put milliseconds-to-seconds in the last hair of travel."""
        middle = duration_for_zoom(0.5)
        assert middle < (ZOOM_MAX_DURATION + ZOOM_MIN_DURATION) / 2 / 100

    def test_a_duration_off_the_scale_parks_at_an_end(self):
        assert zoom_for_duration(ZOOM_MAX_DURATION * 100) == 0.0
        assert zoom_for_duration(ZOOM_MIN_DURATION / 100) == 1.0

    def test_the_notching_matches_matlabs(self):
        assert duration_for_zoom(0.5) == duration_for_zoom(round(0.5 * ZOOM_STEPS) / ZOOM_STEPS)


class TestPanSlider:
    def test_a_view_narrower_than_the_epoch_can_pan(self):
        state = pan_slider_state(0, 100, 10, 20)
        assert state["enabled"]
        assert state["maximum"] == 80_000  # 80 s of pannable range, in ms
        assert state["value"] == 10_000
        assert state["step"] == 2_000  # a tenth of the view

    def test_a_view_covering_the_epoch_is_parked(self):
        state = pan_slider_state(0, 10, 0, 10)
        assert not state["enabled"]
        assert state["maximum"] == 0

    def test_the_value_is_clamped_into_range(self):
        assert pan_slider_state(0, 100, 999, 20)["value"] == 80_000


class TestClampView:
    def test_a_view_past_the_end_is_pulled_back(self):
        assert clamp_view(0, 100, 95, 20) == 80

    def test_a_view_before_the_start_is_pulled_forward(self):
        assert clamp_view(0, 100, -5, 20) == 0

    def test_a_view_wider_than_the_epoch_sits_at_the_start(self):
        assert clamp_view(0, 10, 5, 50) == 0


class TestNeedsReload:
    def test_a_view_inside_the_buffer_does_not(self):
        assert not needs_reload(1.0, 1.0, 0.0, 5.0, 800, 800, 1.0)

    def test_leaving_the_buffer_does(self):
        assert needs_reload(4.5, 1.0, 0.0, 5.0, 800, 800, 1.0)
        assert needs_reload(-0.5, 1.0, 0.0, 5.0, 800, 800, 1.0)

    def test_a_resize_of_more_than_a_tenth_does(self):
        assert needs_reload(1.0, 1.0, 0.0, 5.0, 900, 800, 1.0)
        assert not needs_reload(1.0, 1.0, 0.0, 5.0, 850, 800, 1.0)

    def test_zooming_in_past_eighty_percent_does(self):
        assert needs_reload(1.0, 0.7, 0.0, 5.0, 800, 800, 1.0)
        assert not needs_reload(1.0, 0.9, 0.0, 5.0, 800, 800, 1.0)


class TestSortSpikingInfo:
    def _units(self):
        return [
            {"name": "beta", "best_channel": 1, "quality": 3},
            {"name": "alpha", "best_channel": 9, "quality": 2},
        ]

    def test_by_channel_is_descending(self):
        """Descending puts the smallest channel last, the way the traces stack."""
        ordered = sort_spiking_info(self._units(), by_channel=True)
        assert [u["best_channel"] for u in ordered] == [9, 1]

    def test_by_name_is_case_insensitive(self):
        ordered = sort_spiking_info(self._units(), by_channel=False)
        assert [u["name"] for u in ordered] == ["alpha", "beta"]

    def test_labels_are_renumbered_to_the_new_order(self):
        ordered = sort_spiking_info(self._units(), by_channel=False)
        assert ordered[0]["label"].startswith("1 alpha Q2")
        assert ordered[1]["label"].startswith("2 beta Q3")

    def test_colours_cycle_in_order(self):
        ordered = sort_spiking_info(self._units(), by_channel=False)
        assert ordered[0]["color"] == "k"
        assert ordered[1]["color"] == "m"

    def test_no_units_sorts_to_nothing(self):
        assert sort_spiking_info([], by_channel=True) == []


class TestSpacing:
    def test_a_number_is_taken(self):
        assert spacing_or_default("250") == 250.0

    @pytest.mark.parametrize("text", ["", "abc", None, "nan"])
    def test_anything_else_falls_back(self, text):
        assert spacing_or_default(text) == DEFAULT_SPACING


class TestLevelFiles:
    def test_they_are_the_names_the_document_stores(self):
        assert level_file_names(3) == ["level1.bin", "level2.bin", "level3.bin"]

    def test_none_is_no_files(self):
        assert level_file_names(0) == []


# ----------------------------------------------------------------------
# the viewer
# ----------------------------------------------------------------------
class TestViewerModel:
    def test_it_is_a_session_app_named_as_matlab_names_it(self):
        assert issubclass(pyraview_pkg, SessionApp)
        assert pyraview_pkg.Name == "pyraview"
        assert pyraview_pkg.Category == ""

    def test_discovery_finds_it(self):
        found = {app["Name"]: app["Class"] for app in SessionApp.list()}
        assert found["pyraview"] == "ndi.gui.app.pyraview.viewer.pyraview"

    def test_a_session_with_no_probes_says_so(self, session):
        app = pyraview_pkg(session, build=False)
        assert app.probes == []
        assert app.probe_items() == [NO_PROBES_ITEM]
        assert app.epoch_items() == [EMPTY_EPOCH_ITEM]

    def test_the_bands_are_matlabs(self, session):
        assert BANDS == ("high", "low", "all")

    def test_epochs_come_from_the_selected_probe(self, session, probe):
        app = pyraview_pkg(session, build=False)
        app.probes = [probe]
        assert app.epoch_items() == ["e1"]

    def test_no_document_means_nothing_to_view(self, session, probe):
        app = pyraview_pkg(session, build=False)
        app.probes = [probe]
        app.epoch = "e1"
        assert app.check_and_load(create=False) is None
        assert app.update_view() is False


class TestEpochBounds:
    def test_it_reads_the_dev_local_time_clock(self, session, probe):
        assert epoch_bounds(probe, "e1") == (0.0, EPOCH_DURATION)

    def test_an_unknown_epoch_says_so(self, session, probe):
        with pytest.raises(ValueError, match="not found"):
            epoch_bounds(probe, "nosuchepoch")

    def test_another_clock_is_refused(self, session):
        """Every time in the document would otherwise be in an unstated frame."""
        other = FakeProbe(session, "id", clock="utc")
        with pytest.raises(ValueError, match="dev_local_time"):
            epoch_bounds(other, "e1")


# ----------------------------------------------------------------------
# the round trip, through the real library
# ----------------------------------------------------------------------
class TestPyramidRoundTrip:
    def _document(self, probe):
        return make_pyraview_doc(probe, "e1", "high", chunk_duration=10)

    def test_a_pyramid_is_built_and_recorded(self, session, probe):
        _library_or_skip()
        doc = self._document(probe)
        properties = doc.document_properties["pyraview"]
        assert properties["nativeRate"] == SAMPLE_RATE
        assert properties["channels"] == CHANNELS
        assert properties["decimationLevels"][0] == 100
        assert len(properties["decimationSamplingRates"]) == len(properties["decimationLevels"])

    def test_the_document_carries_a_level_file_per_level(self, session, probe):
        _library_or_skip()
        doc = self._document(probe)
        names = [f["name"] for f in doc.document_properties["files"]["file_info"]]
        assert names[:3] == ["level1.bin", "level2.bin", "level3.bin"]

    def test_the_dataset_is_built_from_the_documents_properties(self, session, probe):
        _library_or_skip()
        doc = self._document(probe)
        dataset = dataset_from_document(doc)
        assert dataset.native_rate == SAMPLE_RATE
        assert dataset.channels == CHANNELS
        assert dataset.files[0] == "level1.bin"

    def test_zoomed_in_reads_raw_and_zoomed_out_reads_the_pyramid(self, session, probe):
        _library_or_skip()
        doc = self._document(probe)

        t_vec, data, level = get_data(probe, doc, 0.0, 0.05, 1000)
        assert level == 0
        assert data.ndim == 2 and data.shape[1] == CHANNELS

        t_vec, data, level = get_data(probe, doc, 0.0, EPOCH_DURATION, 1000)
        assert level >= 1
        assert data.ndim == 3 and data.shape[1:] == (CHANNELS, 2)
        assert len(t_vec) == data.shape[0]

    def test_the_viewer_finds_the_document_it_already_built(self, session, probe):
        _library_or_skip()
        self._document(probe)
        app = pyraview_pkg(session, build=False)
        app.probes = [probe]
        app.probe_index = 0
        app.epoch = "e1"
        probe.reads.clear()
        doc = app.check_and_load()
        assert doc is not None
        assert probe.reads == []  # found, not rebuilt

    def test_panning_inside_the_buffer_does_not_read_again(self, session, probe):
        """The whole point of reading a window either side of the view."""
        _library_or_skip()
        self._document(probe)
        app = pyraview_pkg(session, build=False)
        app.probes = [probe]
        app.epoch = "e1"
        app.check_and_load()

        app.view_t0, app.view_duration = 8.0, 2.0
        assert app.update_view() is True
        assert app.data_t0 <= 8.0 and app.data_t1 >= 10.0

        app.view_t0 = 8.4
        assert app.update_view() is False

        app.view_t0 = 13.0
        assert app.update_view() is True

    def test_the_traces_become_one_polyline(self, session, probe):
        _library_or_skip()
        self._document(probe)
        app = pyraview_pkg(session, build=False)
        app.probes = [probe]
        app.epoch = "e1"
        app.check_and_load()
        app.update_view()
        x, y = app.plot_lines()
        assert x.size == y.size > 0
        assert np.isnan(x).any()  # the breaks between channels


# ----------------------------------------------------------------------
# Qt
# ----------------------------------------------------------------------
def _qt_or_skip():
    pytest.importorskip("PySide6")
    pytest.importorskip("matplotlib")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from ndi.gui._qt_helpers import get_or_create_app

        return get_or_create_app()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no usable Qt platform plugin: {exc}")


class TestWindow:
    def test_it_is_titled_and_tagged(self, session):
        _qt_or_skip()
        app = pyraview_pkg(session, build=True)
        assert app.figure.objectName() == WINDOW_TAG
        assert app.figure.windowTitle() == "pyraview: pyraview_test"
        app.close()

    def test_the_controls_offer_matlabs_choices(self, session):
        _qt_or_skip()
        app = pyraview_pkg(session, build=True)
        bands = [app.band_dropdown.itemText(i) for i in range(app.band_dropdown.count())]
        assert bands == list(BANDS)
        mappings_offered = [
            app.mapping_dropdown.itemText(i) for i in range(app.mapping_dropdown.count())
        ]
        assert mappings_offered == ["raw", "PlexonSV"]
        app.close()

    def test_the_zoom_slider_spans_the_notches(self, session):
        _qt_or_skip()
        app = pyraview_pkg(session, build=True)
        assert app.zoom_slider.minimum() == 0
        assert app.zoom_slider.maximum() == ZOOM_STEPS
        app.close()

    def test_the_spiking_list_is_hidden_until_asked_for(self, session):
        _qt_or_skip()
        app = pyraview_pkg(session, build=True)
        assert not app.spiking_list.isVisible()
        app.close()

    def test_a_bad_spacing_entry_is_replaced_in_the_box(self, session):
        _qt_or_skip()
        app = pyraview_pkg(session, build=True)
        app.spacing_edit.setText("not a number")
        app._on_spacing_changed()
        assert app.channel_y_spacing == DEFAULT_SPACING
        assert app.spacing_edit.text() == str(int(DEFAULT_SPACING))
        app.close()

    def test_the_scrollbars_follow_the_view(self, session):
        _qt_or_skip()
        app = pyraview_pkg(session, build=True)
        app.epoch_t0, app.epoch_t1 = 0.0, 100.0
        app.view_t0, app.view_duration = 10.0, 20.0
        app.sync_scrollbars()
        assert app.pan_slider.isEnabled()
        assert app.pan_slider.value() == 10_000
        assert app.zoom_slider.value() == round(zoom_for_duration(20.0) * ZOOM_STEPS)
        app.close()


if __name__ == "__main__":
    pytest.main([__file__])
