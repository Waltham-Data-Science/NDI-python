"""ndi.gui.app.pyraview.viewer - the NDI signal viewer.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+app/pyraview.m``

Continuous data for one probe, epoch and filter band, with pan and zoom
scrollbars and an optional spiking panel that overlays spike ticks on the
traces and draws unit waveforms beside them.

WHY THERE IS A PYRAMID AT ALL
An epoch can be hours of data at 30 kHz and a screen is a couple of thousand
pixels wide. Drawing raw samples for a whole epoch means reading and throwing
away millions of points per repaint. So the data is stored decimated at
several resolutions (see :mod:`ndi.gui.app.pyraview.make_pyraview_doc`) and
each view reads the coarsest level that still fills the pixels available --
which is the one decision this app makes constantly, and the one it delegates
entirely to the Pyraview library so both ports make it identically.

THE CACHE RULE IS THE OTHER HALF OF FEELING FAST
Each read fetches a window either side of what is shown, so panning inside it
is a redraw rather than a read. :func:`needs_reload` is the rule for when
that is no longer good enough: the view left the buffer, the window changed
size by more than a tenth, or the user zoomed in past 80% of the duration the
buffer was read for. Anything else pans by moving the x limits.

THE MODEL IS PYTHON, NOT THE WIDGETS
As elsewhere in this package, MATLAB keeps state in the controls and finds
them with ``findobj(fig, 'Tag', ...)``; here the state lives on the object and
the widgets mirror it. Every rule above -- which level, whether to reload,
where the scrollbars sit, how units are ordered -- is a plain function tested
with no display attached.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from ..session_app import SessionApp

__all__ = [
    "pyraview",
    "duration_for_zoom",
    "zoom_for_duration",
    "pan_slider_state",
    "clamp_view",
    "needs_reload",
    "sort_spiking_info",
    "spacing_or_default",
    "WINDOW_TAG",
    "DEFAULT_POSITION",
    "ZOOM_MAX_DURATION",
    "ZOOM_MIN_DURATION",
    "ZOOM_STEPS",
    "DEFAULT_SPACING",
    "DEFAULT_SPLIT",
    "COLOR_CYCLE",
    "BANDS",
    "NO_PROBES_ITEM",
    "EMPTY_EPOCH_ITEM",
]

#: Object name on the window, matching MATLAB's figure Tag.
WINDOW_TAG = "ndi.gui.app.pyraview"

#: (x, y, width, height). MATLAB lets the figure default and lays out in
#: pixels; a signal viewer wants room, so the window opens at a usable size.
DEFAULT_POSITION = (100, 100, 1100, 700)

#: The zoom slider maps its 0..1 position onto a duration LOGARITHMICALLY, in
#: ZOOM_STEPS notches from a month down to a millisecond. Linear would make
#: the whole useful range of a spike recording -- milliseconds to seconds --
#: occupy the last hair of slider travel.
ZOOM_MAX_DURATION = 2592000.0
ZOOM_MIN_DURATION = 0.001
ZOOM_STEPS = 200

#: Volts (or whatever the probe records) between one channel and the next.
DEFAULT_SPACING = 100.0

#: Fraction of the window height given to the traces when the spiking panel
#: is open; the rest draws waveforms.
DEFAULT_SPLIT = 0.8

#: Unit colours, cycled in list order. MATLAB's colour cycle exactly.
COLOR_CYCLE = ("k", "m", "b", "g", (1.0, 0.5, 0.0), "r")

#: The filter bands offered, in menu order.
BANDS = ("high", "low", "all")

#: Shown when the session has no multifunction-DAQ probes to view.
NO_PROBES_ITEM = "No probes found"

#: MATLAB's placeholder epoch entry: a single space, which carries no epoch.
EMPTY_EPOCH_ITEM = " "


# ----------------------------------------------------------------------
# The rules -- no Qt in this section
# ----------------------------------------------------------------------
def duration_for_zoom(value: float) -> float:
    """The view duration a zoom slider position means.

    VALUE runs 0 (widest) to 1 (narrowest) and is quantised to
    :data:`ZOOM_STEPS` notches first, as MATLAB quantises it, so dragging the
    slider steps through the same durations in both ports.
    """
    notch = round(value * ZOOM_STEPS)
    exponent = (ZOOM_STEPS - notch) / ZOOM_STEPS
    return ZOOM_MIN_DURATION * (ZOOM_MAX_DURATION / ZOOM_MIN_DURATION) ** exponent


def zoom_for_duration(duration: float) -> float:
    """The slider position that shows DURATION -- the inverse of the above.

    Quantised the same way and clamped to 0..1, so a duration outside the
    slider's range parks it at an end rather than off it.
    """
    if duration <= 0:
        return 1.0
    exponent = math.log(duration / ZOOM_MIN_DURATION) / math.log(
        ZOOM_MAX_DURATION / ZOOM_MIN_DURATION
    )
    notch = round(ZOOM_STEPS * (1 - exponent))
    return max(0.0, min(1.0, notch / ZOOM_STEPS))


def pan_slider_state(
    epoch_t0: float, epoch_t1: float, view_t0: float, view_duration: float
) -> dict[str, Any]:
    """How the pan scrollbar should be configured for the current view.

    Returns ``maximum`` (the pannable range in milliseconds), ``value`` (the
    view start in the same units), ``step`` (a tenth of the view duration,
    also in milliseconds) and ``enabled``.

    Milliseconds, not seconds or fractions, because the scrollbar is an
    integer control in both toolkits: one unit per millisecond gives fine
    control on a short view without overflowing a long one. A view covering
    the whole epoch has nothing to pan, and the slider is parked rather than
    left live at zero width.
    """
    max_start = max(epoch_t1 - view_duration, epoch_t0)
    range_ms = round((max_start - epoch_t0) * 1000)

    if range_ms < 1:
        return {"maximum": 0, "value": 0, "step": 1, "enabled": False}

    value_ms = round((view_t0 - epoch_t0) * 1000)
    value_ms = max(0, min(range_ms, value_ms))
    step_ms = max(1, round(0.1 * view_duration * 1000))
    return {"maximum": range_ms, "value": value_ms, "step": step_ms, "enabled": True}


def clamp_view(epoch_t0: float, epoch_t1: float, view_t0: float, view_duration: float) -> float:
    """VIEW_T0 pulled back inside the epoch, as MATLAB clamps it.

    A view wider than the epoch sits at its start rather than being centred:
    the epoch's beginning is the useful edge to see.
    """
    start = view_t0
    if start + view_duration > epoch_t1:
        start = epoch_t1 - view_duration
    if start < epoch_t0:
        start = epoch_t0
    return start


def needs_reload(
    view_t0: float,
    view_duration: float,
    data_t0: float,
    data_t1: float,
    pixel_span: float,
    loaded_pixel_span: float,
    loaded_view_duration: float,
) -> bool:
    """Whether the buffer still serves the view, or a fresh read is needed.

    Three ways it stops serving, and each is a different kind of staleness:
    the view has moved off the buffer's edge; the window has been resized by
    more than a tenth, so the level chosen for the old width is wrong; or the
    user has zoomed in past 80% of the duration the buffer was read for, where
    the decimated level being drawn is coarser than the screen can now show.
    """
    if view_t0 < data_t0 or view_t0 + view_duration > data_t1:
        return True
    if loaded_pixel_span > 0 and abs(pixel_span - loaded_pixel_span) / loaded_pixel_span > 0.1:
        return True
    return view_duration < loaded_view_duration * 0.8


def sort_spiking_info(
    records: Sequence[Mapping[str, Any]], by_channel: bool
) -> list[dict[str, Any]]:
    """Order the units, then renumber and recolour them to match.

    BY_CHANNEL sorts by best channel DESCENDING, which is what puts the
    smallest channel last -- the order the traces are drawn in, so the list
    reads down the screen the way the channels do. Otherwise units sort by
    name, case-insensitively.

    Labels carry the position, so they are rebuilt after the sort rather than
    kept: a list numbered in a different order than it is displayed is worse
    than one not numbered at all.
    """
    ordered = [dict(record) for record in records]
    if not ordered:
        return ordered

    if by_channel:
        ordered.sort(key=lambda r: r.get("best_channel", 1), reverse=True)
    else:
        ordered.sort(key=lambda r: str(r.get("name") or r.get("label") or "").lower())

    for position, record in enumerate(ordered, start=1):
        quality = record.get("quality") or 0
        name = record.get("name") or ""
        record["label"] = f"{position} {name} Q{int(quality)}"
        record["color"] = COLOR_CYCLE[(position - 1) % len(COLOR_CYCLE)]
    return ordered


def spacing_or_default(text: str) -> float:
    """The spacing a user typed, or :data:`DEFAULT_SPACING` if it is not a number.

    MATLAB writes the default back into the box when the entry will not parse,
    and so does the caller here: a field showing something that is not being
    used is a lie about the plot.
    """
    try:
        value = float(str(text).strip())
    except (TypeError, ValueError):
        return DEFAULT_SPACING
    if math.isnan(value):
        return DEFAULT_SPACING
    return value


class pyraview(SessionApp):  # noqa: N801 - MATLAB's class name, kept exactly
    """The NDI signal viewer."""

    Name: ClassVar[str] = "pyraview"

    def __init__(self, session: Any, *, build: bool = True):
        self.session = session
        self.figure: Any = None
        self.canvas: Any = None
        self.axes: Any = None
        self.waveform_axes: Any = None
        self.last_alert: tuple[str, str] | None = None

        # widgets
        self.probe_dropdown: Any = None
        self.epoch_dropdown: Any = None
        self.band_dropdown: Any = None
        self.mapping_dropdown: Any = None
        self.spacing_edit: Any = None
        self.pan_slider: Any = None
        self.zoom_slider: Any = None
        self.spiking_checkbox: Any = None
        self.spiking_list: Any = None

        # model
        #: The session's multifunction-DAQ timeseries probes.
        self.probes: list[Any] = []
        self.probe_index = 0
        self.epoch = ""
        self.band = BANDS[0]
        self.mapping_name = "raw"

        #: The pyraview document for the current probe/epoch/band.
        self.current_doc: Any = None
        self.epoch_t0 = 0.0
        self.epoch_t1 = 0.0

        #: What is in the buffer, and what it was read for.
        self.current_data: Any = None
        self.current_time: Any = None
        self.current_level: int | None = None
        self.data_t0 = -math.inf
        self.data_t1 = -math.inf
        self.loaded_pixel_span = 0.0
        self.loaded_view_duration = math.inf

        #: What is on screen.
        self.view_t0 = 0.0
        self.view_duration = 1.0
        self.channel_y_spacing = DEFAULT_SPACING
        self.first_plot = True
        self.pixel_span = 1000.0

        #: The spiking panel.
        self.spiking_info: list[dict[str, Any]] = []
        self.spiking_epochid = ""
        self.selected_units: list[int] = []
        self.sort_by_channel = False
        self.show_boxes = False

        self.load_probes()
        if build:
            self.build()

    # ------------------------------------------------------------------
    # reading the session -- no Qt in this section
    # ------------------------------------------------------------------
    def load_probes(self) -> list[Any]:
        """The session's multifunction-DAQ timeseries probes.

        Everything an ``ndi.probe.timeseries.mfdaq`` is -- n-trode, patch,
        sharp, ecg, eeg, and the rest. Stimulator and image probes are
        siblings of it under ``ndi.probe.timeseries`` and are excluded, as
        MATLAB's isa() test excludes them: neither has a continuous trace to
        draw.
        """
        from ....probe.timeseries_mfdaq import ndi_probe_timeseries_mfdaq

        try:
            found = self.session.getprobes()
        except Exception:  # noqa: BLE001 - a session that cannot list has none
            found = []
        self.probes = [p for p in (found or []) if isinstance(p, ndi_probe_timeseries_mfdaq)]
        self.probe_index = 0
        return self.probes

    def probe_items(self) -> list[str]:
        """The probe dropdown's entries."""
        labels = [str(probe.elementstring()) for probe in self.probes]
        return labels or [NO_PROBES_ITEM]

    def selected_probe(self) -> Any:
        """The probe being viewed, or None."""
        if 0 <= self.probe_index < len(self.probes):
            return self.probes[self.probe_index]
        return None

    def epoch_items(self) -> list[str]:
        """The epochs the selected probe offers."""
        probe = self.selected_probe()
        if probe is None:
            return [EMPTY_EPOCH_ITEM]
        try:
            table = probe.epochtable()
        except Exception:  # noqa: BLE001 - a probe that cannot say has none
            return [EMPTY_EPOCH_ITEM]
        if isinstance(table, tuple):
            table = table[0]
        ids = [str(entry.get("epoch_id", "")) for entry in (table or []) if entry.get("epoch_id")]
        return ids or [EMPTY_EPOCH_ITEM]

    def find_document(self, probe: Any, epoch: str, band: str) -> Any:
        """The pyraview document for this probe, epoch and band, or None.

        Four conditions, as MATLAB queries: the class, the element it depends
        on, the epoch, and the band. The band is part of the identity -- the
        same epoch filtered differently is a different pyramid, not the same
        one seen another way.
        """
        from ....fun.utils import identifier
        from ....query import ndi_query

        query = (
            ndi_query("").isa("pyraview")
            & ndi_query("").depends_on("element_id", identifier(probe))
            & ndi_query("epochid.epochid", "exact_string", str(epoch), "")
            & ndi_query("filter.label", "exact_string", str(band), "")
        )
        try:
            docs = self.session.database_search(query)
        except Exception:  # noqa: BLE001 - an unreadable database has no document
            return None
        return docs[0] if docs else None

    def check_and_load(self, create: bool = True) -> Any:
        """Find the current view's document, building the pyramid if there is none.

        Returns the document, or None when there is nothing to view. Building
        is the expensive path -- it reads the whole epoch and writes every
        pyramid level -- so it happens once per probe/epoch/band and is what
        the wait indicator covers.
        """
        probe = self.selected_probe()
        if probe is None or not self.epoch or self.epoch == EMPTY_EPOCH_ITEM:
            self.current_doc = None
            return None

        doc = self.find_document(probe, self.epoch, self.band)
        if doc is None and create:
            from .make_pyraview_doc import make_pyraview_doc

            try:
                doc = make_pyraview_doc(probe, self.epoch, self.band)
            except Exception as exc:  # noqa: BLE001 - reported, not raised at the user
                self.alert(str(exc), "Could not build the pyramid")
                self.current_doc = None
                return None

        self.current_doc = doc
        if doc is not None:
            self.epoch_t0, self.epoch_t1 = self._document_bounds(doc)
            self.reset_view()
        return doc

    @staticmethod
    def _document_bounds(doc: Any) -> tuple[float, float]:
        """The epoch's ``(t0, t1)`` as the document records them."""
        try:
            bounds = doc.document_properties["epochclocktimes"]["t0_t1"]
            return float(bounds[0]), float(bounds[1])
        except Exception:  # noqa: BLE001 - MATLAB's fallback, and for the same reason:
            return 0.0, 100.0  # a window on nothing is worse than one on a guess

    def reset_view(self) -> None:
        """Show the whole epoch, and drop the buffer."""
        self.view_t0 = self.epoch_t0
        self.view_duration = max(self.epoch_t1 - self.epoch_t0, ZOOM_MIN_DURATION)
        self.data_t0 = -math.inf
        self.data_t1 = -math.inf
        self.loaded_pixel_span = 0.0
        self.loaded_view_duration = math.inf
        self.first_plot = True

    # ------------------------------------------------------------------
    # the view
    # ------------------------------------------------------------------
    def update_view(self) -> bool:
        """Bring the buffer up to date if it needs to be, then draw.

        Returns whether a read happened, which is what a test asks about: the
        point of the cache is that panning inside the buffer does NOT read.
        """
        if self.current_doc is None:
            return False

        if not needs_reload(
            self.view_t0,
            self.view_duration,
            self.data_t0,
            self.data_t1,
            self.pixel_span,
            self.loaded_pixel_span,
            self.loaded_view_duration,
        ):
            self.set_x_limits()
            return False

        from .get_data import get_data

        probe = self.selected_probe()
        if probe is None:
            return False

        t_vec, data, level = get_data(
            probe,
            self.current_doc,
            self.view_t0,
            self.view_t0 + self.view_duration,
            self.pixel_span,
        )
        if t_vec is None or len(t_vec) == 0:
            self.current_data = None
            self.current_time = None
            self.clear_axes()
            return True

        self.data_t0 = float(t_vec[0])
        self.data_t1 = float(t_vec[-1])
        self.current_time = t_vec
        self.current_data = data
        self.current_level = level
        self.loaded_pixel_span = self.pixel_span
        self.loaded_view_duration = self.view_duration
        self.plot_data()
        return True

    def plot_lines(self) -> tuple[Any, Any]:
        """The polyline the traces draw as, mapping applied.

        Split out from :meth:`plot_data` so what will be drawn is checkable
        without an axes to draw it on.
        """
        import numpy as np

        from .mappings import mappings
        from .transform_plot_data import transform_plot_data

        if self.current_data is None or len(self.current_data) == 0:
            return np.array([]), np.array([])

        channels = self.current_data.shape[1] if self.current_data.ndim > 1 else 1
        try:
            mapping = mappings(list(range(1, channels + 1)), self.mapping_name)
        except ValueError as exc:
            # A mapping that does not fit this probe is reported and dropped,
            # as MATLAB warns and carries on: the wrong order is worse than none.
            self.alert(str(exc), "Mapping error")
            mapping = None

        return transform_plot_data(
            self.current_data,
            self.current_time,
            self.current_level or 0,
            self.channel_y_spacing,
            mapping,
        )

    def spike_lines(self) -> tuple[Any, Any]:
        """The tick overlay for the selected units, over the current view."""
        from .transform_spike_data import transform_spike_data

        return transform_spike_data(
            self.spiking_info,
            self.selected_units,
            self.view_t0,
            self.view_t0 + self.view_duration,
            self.channel_y_spacing,
            self.show_boxes,
        )

    def ensure_spike_times_loaded(self) -> None:
        """Read the spike trains of the selected units, once each.

        The trains are what ``load_spiking_neurons`` deliberately does not
        read; this is where that debt is paid, for the selected units only.
        """
        for index in self.selected_units:
            if index >= len(self.spiking_info):
                continue
            record = self.spiking_info[index]
            if record.get("times_loaded"):
                continue
            record["spike_times"] = self._read_spike_times(record)
            record["times_loaded"] = True

    def _read_spike_times(self, record: Mapping[str, Any]) -> list[float]:
        """One unit's spike times, building its element if need be."""
        import numpy as np

        element = record.get("element_obj")
        if element is None:
            try:
                from ....element import ndi_element

                element = ndi_element(session=self.session, document=record["element_doc"])
            except Exception:  # noqa: BLE001 - a unit that will not rebuild has no ticks
                return []
        try:
            result = element.readtimeseries(self.spiking_epochid or self.epoch, -math.inf, math.inf)
        except Exception:  # noqa: BLE001 - as above
            return []
        # readtimeseries answers (data, time, ...) for a spike train; the
        # times are what a tick needs.
        if isinstance(result, tuple) and len(result) > 1:
            times = result[1]
        else:
            times = result
        return list(np.asarray(times, dtype=float).ravel())

    def set_spacing(self, text: str) -> float:
        """Take a typed channel spacing, and redraw at it."""
        self.channel_y_spacing = spacing_or_default(text)
        self.plot_data()
        return self.channel_y_spacing

    def set_zoom(self, value: float) -> None:
        """Zoom to slider position VALUE, keeping the view's centre put."""
        centre = self.view_t0 + self.view_duration / 2
        self.view_duration = duration_for_zoom(value)
        self.view_t0 = clamp_view(
            self.epoch_t0, self.epoch_t1, centre - self.view_duration / 2, self.view_duration
        )
        self.update_view()

    def set_pan(self, value_ms: float) -> None:
        """Pan so the view starts VALUE_MS milliseconds into the epoch."""
        self.view_t0 = clamp_view(
            self.epoch_t0, self.epoch_t1, self.epoch_t0 + value_ms / 1000.0, self.view_duration
        )
        self.update_view()

    def reset_x(self) -> None:
        """Show the whole epoch again."""
        self.view_t0 = self.epoch_t0
        self.view_duration = max(self.epoch_t1 - self.epoch_t0, ZOOM_MIN_DURATION)
        self.update_view()
        self.sync_scrollbars()

    # ------------------------------------------------------------------
    # Qt
    # ------------------------------------------------------------------
    def build(self) -> Any:
        """Build the window and return it.

        The traces live on an embedded matplotlib canvas rather than in a
        separate figure, because this app IS its plot: MATLAB puts the axes
        and the controls on one figure, and splitting them would make panning
        a conversation between two windows.
        """
        from ..._qt_helpers import get_or_create_app, require_qt

        require_qt()
        get_or_create_app()
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.figure import Figure
        from PySide6 import QtCore, QtWidgets

        from ...cloud_colors import cloud_colors, rgb_to_hex

        colors = cloud_colors()
        navy = rgb_to_hex(colors.dark_blue)
        white = rgb_to_hex(colors.white)
        field = f"background-color: {white}; color: {navy};"
        caption = f"color: {white}; font-weight: bold;"

        self.figure = QtWidgets.QWidget()
        self.figure.setObjectName(WINDOW_TAG)
        self.figure.setWindowTitle(self.window_title())
        x, y, width, height = DEFAULT_POSITION
        self.figure.setGeometry(x, y, width, height)
        self.figure.setStyleSheet(f"background-color: {navy};")

        root = QtWidgets.QVBoxLayout(self.figure)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)

        # ---- controls
        controls = QtWidgets.QHBoxLayout()
        controls.setSpacing(8)

        def labelled(text: str, widget: Any) -> None:
            label = QtWidgets.QLabel(text)
            label.setStyleSheet(caption)
            controls.addWidget(label)
            widget.setStyleSheet(field)
            controls.addWidget(widget)

        self.probe_dropdown = QtWidgets.QComboBox()
        self.probe_dropdown.addItems(self.probe_items())
        self.probe_dropdown.currentIndexChanged.connect(self._on_probe_changed)
        labelled("Probe:", self.probe_dropdown)

        self.epoch_dropdown = QtWidgets.QComboBox()
        self.epoch_dropdown.currentTextChanged.connect(self._on_epoch_changed)
        labelled("epoch_id:", self.epoch_dropdown)

        self.band_dropdown = QtWidgets.QComboBox()
        self.band_dropdown.addItems(BANDS)
        self.band_dropdown.currentTextChanged.connect(self._on_band_changed)
        labelled("Band:", self.band_dropdown)

        self.mapping_dropdown = QtWidgets.QComboBox()
        from .mappings import MAPPING_NAMES

        self.mapping_dropdown.addItems(MAPPING_NAMES)
        self.mapping_dropdown.currentTextChanged.connect(self._on_mapping_changed)
        labelled("Mapping:", self.mapping_dropdown)

        self.spacing_edit = QtWidgets.QLineEdit(str(int(DEFAULT_SPACING)))
        self.spacing_edit.setFixedWidth(70)
        self.spacing_edit.editingFinished.connect(self._on_spacing_changed)
        labelled("Spacing:", self.spacing_edit)

        reset_button = QtWidgets.QPushButton("Reset X")
        reset_button.setStyleSheet(field)
        reset_button.clicked.connect(self.reset_x)
        controls.addWidget(reset_button)

        self.spiking_checkbox = QtWidgets.QCheckBox("Spiking units")
        self.spiking_checkbox.setStyleSheet(f"color: {white};")
        self.spiking_checkbox.toggled.connect(self._on_spiking_toggled)
        controls.addWidget(self.spiking_checkbox)

        controls.addStretch(1)
        root.addLayout(controls)

        # ---- traces, with the unit list beside them
        body = QtWidgets.QHBoxLayout()
        canvas_figure = Figure(figsize=(8, 5))
        self.canvas = FigureCanvasQTAgg(canvas_figure)
        self.axes = canvas_figure.add_subplot(1, 1, 1)
        body.addWidget(self.canvas, 1)

        self.spiking_list = QtWidgets.QListWidget()
        self.spiking_list.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.spiking_list.setStyleSheet(field)
        self.spiking_list.setFixedWidth(220)
        self.spiking_list.setVisible(False)
        self.spiking_list.itemSelectionChanged.connect(self._on_units_selected)
        body.addWidget(self.spiking_list)
        root.addLayout(body, 1)

        # ---- pan and zoom
        self.pan_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.pan_slider.valueChanged.connect(self._on_pan)
        pan_row = QtWidgets.QHBoxLayout()
        pan_caption = QtWidgets.QLabel("Pan:")
        pan_caption.setStyleSheet(caption)
        pan_row.addWidget(pan_caption)
        pan_row.addWidget(self.pan_slider, 1)
        root.addLayout(pan_row)

        # The zoom slider is integer like every Qt slider, so it carries the
        # notch number and duration_for_zoom turns it back into a duration.
        self.zoom_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(0, ZOOM_STEPS)
        self.zoom_slider.valueChanged.connect(self._on_zoom)
        zoom_row = QtWidgets.QHBoxLayout()
        zoom_caption = QtWidgets.QLabel("Zoom:")
        zoom_caption.setStyleSheet(caption)
        zoom_row.addWidget(zoom_caption)
        zoom_row.addWidget(self.zoom_slider, 1)
        root.addLayout(zoom_row)

        self.figure.show()
        self._sync_epoch_dropdown()
        return self.figure

    def window_title(self) -> str:
        """MATLAB's window name: the app, then which session it is viewing."""
        try:
            reference = str(self.session.reference or "")
        except Exception:  # noqa: BLE001
            reference = ""
        return f"pyraview: {reference}"

    def plot_data(self) -> None:
        """Draw the buffer at the current spacing and mapping."""
        if self.axes is None:
            return
        x, y = self.plot_lines()
        self.axes.clear()
        if len(x):
            self.axes.plot(x, y, color=(0.0, 0.4470, 0.7410), linewidth=0.5)
        self.draw_spike_overlay()
        self.set_x_limits()
        if self.first_plot:
            self.axes.relim()
            self.axes.autoscale(axis="y")
            self.first_plot = False
        self._draw()

    def draw_spike_overlay(self) -> None:
        """Draw the tick layer over the traces, if the panel is open."""
        if self.axes is None or not self.selected_units:
            return
        x, y = self.spike_lines()
        if len(x):
            # Drawn after the traces so the ticks sit on top -- MATLAB
            # reorders the axes children for the same reason.
            self.axes.plot(x, y, color="k", linewidth=0.8)

    def set_x_limits(self) -> None:
        """Point the axes at the current view."""
        if self.axes is not None:
            self.axes.set_xlim(self.view_t0, self.view_t0 + self.view_duration)
            self._draw()

    def clear_axes(self) -> None:
        """Empty the plot -- there is nothing to show."""
        if self.axes is not None:
            self.axes.clear()
            self._draw()

    def _draw(self) -> None:
        if self.canvas is not None:
            self.canvas.draw_idle()

    def sync_scrollbars(self) -> None:
        """Put both sliders where the current view says they belong."""
        if self.pan_slider is not None:
            state = pan_slider_state(self.epoch_t0, self.epoch_t1, self.view_t0, self.view_duration)
            self.pan_slider.blockSignals(True)
            self.pan_slider.setMaximum(int(state["maximum"]))
            self.pan_slider.setValue(int(state["value"]))
            self.pan_slider.setSingleStep(int(state["step"]))
            self.pan_slider.setPageStep(int(state["step"]))
            self.pan_slider.setEnabled(bool(state["enabled"]))
            self.pan_slider.blockSignals(False)

        if self.zoom_slider is not None:
            self.zoom_slider.blockSignals(True)
            self.zoom_slider.setValue(
                int(round(zoom_for_duration(self.view_duration) * ZOOM_STEPS))
            )
            self.zoom_slider.blockSignals(False)

    # ------------------------------------------------------------------
    # handlers
    # ------------------------------------------------------------------
    def _sync_epoch_dropdown(self) -> None:
        if self.epoch_dropdown is None:
            return
        items = self.epoch_items()
        self.epoch_dropdown.blockSignals(True)
        self.epoch_dropdown.clear()
        self.epoch_dropdown.addItems(items)
        self.epoch_dropdown.blockSignals(False)
        self.epoch = items[0] if items and items[0] != EMPTY_EPOCH_ITEM else ""

    def _on_probe_changed(self, index: int) -> None:
        if 0 <= index < len(self.probes):
            self.probe_index = index
            self._sync_epoch_dropdown()
            self._load_and_draw()

    def _on_epoch_changed(self, text: str) -> None:
        if text and text != EMPTY_EPOCH_ITEM:
            self.epoch = text
            self._load_and_draw()

    def _on_band_changed(self, text: str) -> None:
        if text in BANDS:
            self.band = text
            self._load_and_draw()

    def _on_mapping_changed(self, text: str) -> None:
        self.mapping_name = text
        self.plot_data()

    def _on_spacing_changed(self) -> None:
        value = self.set_spacing(self.spacing_edit.text())
        # Write the default back when the entry would not parse, so the box
        # never shows a number that is not the one being used.
        self.spacing_edit.setText(str(int(value)) if value.is_integer() else str(value))

    def _on_pan(self, value: int) -> None:
        self.set_pan(float(value))

    def _on_zoom(self, value: int) -> None:
        self.set_zoom(value / ZOOM_STEPS)

    def _on_spiking_toggled(self, checked: bool) -> None:
        if self.spiking_list is not None:
            self.spiking_list.setVisible(checked)
        if not checked:
            self.selected_units = []
            self.plot_data()
            return

        probe = self.selected_probe()
        if probe is None or not self.epoch:
            return
        from .load_spiking_neurons import load_spiking_neurons

        self.spiking_epochid = self.epoch
        self.spiking_info = sort_spiking_info(
            load_spiking_neurons(self.session, probe, self.epoch), self.sort_by_channel
        )
        self._sync_spiking_list()

    def _sync_spiking_list(self) -> None:
        if self.spiking_list is None:
            return
        self.spiking_list.blockSignals(True)
        self.spiking_list.clear()
        self.spiking_list.addItems([str(r.get("label", "")) for r in self.spiking_info])
        self.spiking_list.blockSignals(False)

    def _on_units_selected(self) -> None:
        self.selected_units = [index.row() for index in self.spiking_list.selectedIndexes()]
        self.ensure_spike_times_loaded()
        self.plot_data()

    def _load_and_draw(self) -> None:
        """Find or build the document for the new selection, then show it."""
        self.check_and_load()
        self.update_view()
        self.sync_scrollbars()

    def alert(self, message: str, title: str) -> Any:
        """Tell the user something, and record it whether or not there is a window."""
        self.last_alert = (title, message)
        if self.figure is None:
            return None
        from PySide6 import QtWidgets

        box = QtWidgets.QMessageBox(self.figure)
        box.setWindowTitle(title)
        box.setText(message)
        box.show()
        return box

    def show(self) -> None:
        """Put the window on screen."""
        if self.figure is not None:
            self.figure.show()

    def close(self) -> None:
        """Close the window."""
        if self.figure is not None:
            self.figure.close()

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"pyraview({len(self.probes)} probes, epoch {self.epoch!r}, "
            f"band {self.band!r}, view {self.view_duration:g}s)"
        )
