"""ndi.gui.app.katz_exporter - export a spiking-neuron ensemble to a blech_clust HDF5 file.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+app/katzExporter.m``

A session GUI app (see :class:`~ndi.gui.app.session_app.SessionApp`) over
:func:`ndi.fun.export.blech_clust`. It exports one epoch of one ensemble --
its neurons' spike times, plus the tastant stimulus identities and delivery
times recorded by a stimulator -- to the HMM-ready HDF5 file the Katz lab's
blech_clust reads (https://github.com/vh-lab/blech_clust).

An export has three coordinates, and the window is those three dropdowns: an
ENSEMBLE (whose underlying probe is what is exported), an EPOCH of it, and a
STIMULATOR. The ensembles come from :mod:`ndi.gui.app.ensemble_maker`, or from
anywhere else that wrote ``ndi.element.ensemble`` elements.

THE QUALITY FILTER IS A PREVIEW, NOT A PROMISE
Neurons can be restricted by their ``neuron_extracellular`` spike-sorting
quality: a minimum ``quality_number``, a set of ``quality_labels``, or both.
The list shows every neuron with its quality and marks the excluded ones with
``x``, so the effect of a filter is visible BEFORE an export rather than
inferred from a file size afterwards. The rule the preview applies is
:func:`passes_filter`, which is ``ndi.fun.ensemble.read``'s rule -- including
the part that surprises: an unrated neuron (no quality document) fails any
active filter unless "Keep unrated neurons" is on, which overrides for
unrated neurons only. The export itself re-applies the same rule inside
``blech_clust``; the preview does not filter anything for it.

THE MODEL IS PYTHON, NOT THE WIDGETS
As in :mod:`ndi.gui.app.ensemble_maker`: MATLAB keeps this app's state in the
widgets (a dropdown's ``ItemsData``, a listbox's ``Value``), while here it
lives on the object and the widgets mirror it. So every decision -- which
neurons pass, whether Export is live, what the file will be called -- is
checkable with no display attached, and ``build=False`` constructs the model
alone.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from typing import Any, ClassVar

from .session_app import SessionApp

__all__ = [
    "katzExporter",
    "session_path",
    "ensemble_items",
    "epoch_ids",
    "passes_filter",
    "neuron_row",
    "summary_message",
    "suggest_file_name",
    "WINDOW_TAG",
    "DEFAULT_POSITION",
    "TITLE_TEXT",
    "DEFAULT_MIN_QUALITY",
    "DEFAULT_PRE_STIM",
    "DEFAULT_POST_STIM",
    "ENSEMBLE_TYPE",
    "STIMULATOR_TYPE",
    "NO_ENSEMBLES_ITEM",
    "NO_STIMULATORS_ITEM",
    "NO_EPOCHS_ITEM",
    "NO_NEURONS_ITEM",
    "UNRATED_LABEL",
    "LOADING_MESSAGE",
    "READING_MESSAGE",
]

#: Object name on the window, matching MATLAB's figure Tag.
WINDOW_TAG = "ndi.gui.app.katzExporter"

#: MATLAB's Position: (x, y, width, height).
DEFAULT_POSITION = (100, 100, 680, 620)

#: The heading.
TITLE_TEXT = "Export Ensemble to blech_clust HDF5 (Katz Lab)"

#: Where the minimum-quality spinner starts. Only read while its checkbox is on.
DEFAULT_MIN_QUALITY = 2

#: Milliseconds retained either side of a stimulus delivery. blech_clust's own
#: defaults, and the same numbers ndi.fun.export.blech_clust defaults to.
DEFAULT_PRE_STIM = 2000
DEFAULT_POST_STIM = 5000

#: The element type an ensemble has, and the probe type a stimulator has.
ENSEMBLE_TYPE = "ensemble"
STIMULATOR_TYPE = "stimulator"

#: Placeholders. A dropdown showing one of these has nothing selectable in it,
#: which is what tells the app there is no real choice behind it.
NO_ENSEMBLES_ITEM = "(no ensembles found)"
NO_STIMULATORS_ITEM = "(no stimulators found)"
NO_EPOCHS_ITEM = "(no epochs)"
NO_NEURONS_ITEM = "(no neurons)"

#: Shown for a neuron with no neuron_extracellular document.
UNRATED_LABEL = "(unrated)"

#: What the wait dialog says over each of the two slow reads.
LOADING_MESSAGE = "Loading ensembles..."
READING_MESSAGE = "Reading ensemble neurons..."


# ----------------------------------------------------------------------
# What the window says -- no Qt in this section
# ----------------------------------------------------------------------
def session_path(session: Any) -> str:
    """The session's path, for the subtitle. "" when it will not say."""
    for attribute in ("getpath", "path"):
        try:
            value = getattr(session, attribute, None)
            if callable(value):
                value = value()
            if value:
                return str(value)
        except Exception:  # noqa: BLE001 - a session that cannot say has no path
            continue
    return ""


def ensemble_items(elements: Sequence[Any]) -> list[str]:
    """One dropdown label per element, in order."""
    labels: list[str] = []
    for element in elements:
        try:
            labels.append(str(element.elementstring()))
        except Exception:  # noqa: BLE001 - an element that cannot name itself
            labels.append(type(element).__name__)
    return labels


def epoch_ids(ensemble: Any) -> list[str]:
    """The epoch ids of ENSEMBLE, or [] when it has none or cannot say."""
    try:
        table = ensemble.epochtable()
    except Exception:  # noqa: BLE001 - an unreadable ensemble offers no epochs
        return []
    if isinstance(table, tuple):
        table = table[0]
    if not table:
        return []
    return [str(entry.get("epoch_id", "")) for entry in table if entry.get("epoch_id")]


def passes_filter(
    quality_number: float,
    quality_label: str,
    min_quality: float | None,
    labels: Sequence[str] | None,
    keep_unrated: bool,
) -> bool:
    """Whether one neuron survives the quality filter.

    ``ndi.fun.ensemble.read``'s rule, which the export re-applies: quality is
    a HARD filter, and an unrated neuron -- one with no
    ``neuron_extracellular`` document, so a NaN quality_number -- fails any
    active filter unless KEEP_UNRATED says otherwise.

    That last clause is the part worth stating twice: KEEP_UNRATED overrides
    for unrated neurons ONLY. It does not rescue a rated neuron whose quality
    is below the minimum, and it does nothing at all when no filter is active
    (with none, everything passes anyway).
    """
    unrated = quality_number is None or (
        isinstance(quality_number, float) and math.isnan(quality_number)
    )
    label_set = [str(label) for label in labels] if labels else []

    passes = True
    if min_quality is not None and (unrated or float(quality_number) < float(min_quality)):
        passes = False
    if label_set and str(quality_label) not in label_set:
        passes = False
    if unrated and (min_quality is not None or label_set):
        passes = bool(keep_unrated)
    return passes


def neuron_row(name: str, quality_number: Any, quality_label: str, passes: bool) -> str:
    """One preview row: the exclusion mark, the name, the quality, the label.

    MATLAB's ``'%s%-18s | q=%s | %s'``, mark included, so the two windows read
    identically -- and so the columns line up under a fixed-width font.
    """
    unrated = quality_number is None or (
        isinstance(quality_number, float) and math.isnan(quality_number)
    )
    quality_text = "  -" if unrated else f"{float(quality_number):3g}"
    mark = "  " if passes else "x "
    label = str(quality_label) if quality_label else UNRATED_LABEL
    return f"{mark}{str(name):<18} | q={quality_text} | {label}"


def summary_message(n_pass: int, n_total: int) -> str:
    """The line under the preview list. "" when there are no neurons at all."""
    if not n_total:
        return ""
    return f"{n_pass} of {n_total} neurons pass the quality filter (x = excluded)"


def suggest_file_name(reference: str, ensemble_name: str, epoch: str) -> str:
    """The default HDF5 name: session, ensemble and epoch, whitespace squashed."""
    parts = [re.sub(r"\s", "_", str(part or "")) for part in (reference, ensemble_name, epoch)]
    return "_".join(parts) + "_blech.h5"


class katzExporter(SessionApp):  # noqa: N801 - MATLAB's class name, kept exactly
    """Export an ensemble's neurons and a stimulator's tastants to blech_clust."""

    Name: ClassVar[str] = "Katz Lab Exporter"
    Category: ClassVar[str] = "Exporters"

    def __init__(self, session: Any, *, build: bool = True):
        self.session = session
        self.figure: Any = None
        self.wait_dialog: Any = None
        #: (title, message) of the last thing the app said, window or not.
        self.last_alert: tuple[str, str] | None = None

        # widgets
        self.ensemble_dropdown: Any = None
        self.epoch_dropdown: Any = None
        self.stimulator_dropdown: Any = None
        self.min_quality_checkbox: Any = None
        self.min_quality_spinner: Any = None
        self.quality_label_list: Any = None
        self.keep_unrated_checkbox: Any = None
        self.pre_stim_spinner: Any = None
        self.post_stim_spinner: Any = None
        self.neuron_list: Any = None
        self.summary_label: Any = None
        self.export_button: Any = None

        # model
        #: The session's ensemble elements, in dropdown order.
        self.ensembles: list[Any] = []
        #: The session's stimulator probes, in dropdown order.
        self.stimulators: list[Any] = []
        #: One dict per neuron of the selected ensemble/epoch: name,
        #: quality_number, quality_label, passes.
        self.neuron_info: list[dict[str, Any]] = []
        #: Index into :attr:`ensembles`, and into :attr:`stimulators`.
        self.ensemble_index = 0
        self.stimulator_index = 0
        #: The chosen epoch id, "" for none.
        self.epoch = ""
        #: The quality filter.
        self.min_quality_enabled = False
        self.min_quality: float = DEFAULT_MIN_QUALITY
        self.quality_labels: list[str] = []
        self.keep_unrated = False
        #: The window kept either side of a delivery, in milliseconds.
        self.pre_stim: float = DEFAULT_PRE_STIM
        self.post_stim: float = DEFAULT_POST_STIM
        #: Set when the neurons could not be read, so the list can say so.
        self.read_error = ""

        if build:
            self.build()
        self.with_wait(LOADING_MESSAGE, self.reload_all)

    # ------------------------------------------------------------------
    # reading the session -- no Qt in this section
    # ------------------------------------------------------------------
    def reload_all(self) -> None:
        """Re-read the ensembles and stimulators, then everything downstream."""
        self.load_ensembles()
        self.load_stimulators()
        self.on_ensemble_changed()

    def load_ensembles(self) -> list[Any]:
        """The session's ensemble elements."""
        try:
            elements = self.session.getelements(**{"element.type": ENSEMBLE_TYPE})
        except Exception:  # noqa: BLE001 - a session that cannot say has none
            elements = []
        self.ensembles = list(elements) if elements else []
        self.ensemble_index = 0
        self._sync_ensemble_dropdown()
        return self.ensembles

    def load_stimulators(self) -> list[Any]:
        """The session's stimulator probes."""
        try:
            probes = self.session.getprobes(type=STIMULATOR_TYPE)
        except Exception:  # noqa: BLE001 - as above
            probes = []
        self.stimulators = list(probes) if probes else []
        self.stimulator_index = 0
        self._sync_stimulator_dropdown()
        return self.stimulators

    def selected_ensemble(self) -> Any:
        """The chosen ensemble, or None."""
        if 0 <= self.ensemble_index < len(self.ensembles):
            return self.ensembles[self.ensemble_index]
        return None

    def selected_stimulator(self) -> Any:
        """The chosen stimulator, or None."""
        if 0 <= self.stimulator_index < len(self.stimulators):
            return self.stimulators[self.stimulator_index]
        return None

    def epoch_choices(self) -> list[str]:
        """The epochs the selected ensemble offers."""
        ensemble = self.selected_ensemble()
        return epoch_ids(ensemble) if ensemble is not None else []

    def on_ensemble_changed(self) -> None:
        """Re-offer the epochs, then re-read the neurons."""
        choices = self.epoch_choices()
        self.epoch = choices[0] if choices else ""
        self._sync_epoch_dropdown(choices)
        self.on_epoch_changed()

    def on_epoch_changed(self) -> None:
        """Re-read the neurons of the current ensemble/epoch."""
        self.with_wait(READING_MESSAGE, self.refresh_neurons)

    def refresh_neurons(self) -> list[dict[str, Any]]:
        """Read the selected ensemble/epoch's neurons and their quality.

        Populates :attr:`neuron_info`, from which the preview list, the
        quality-label choices and the summary are all derived. A read that
        fails leaves it empty and records the message in :attr:`read_error`,
        which the list shows rather than an empty box: "could not read" and
        "no neurons" are different answers.
        """
        self.neuron_info = []
        self.read_error = ""
        ensemble = self.selected_ensemble()
        if ensemble is None or not self.epoch:
            self._sync_after_refresh()
            return self.neuron_info

        try:
            from ...fun.ensemble import neuron_quality

            ids = ensemble.neuron_ids(self.epoch)
            names = ensemble.neuron_names(self.epoch)
            quality_numbers, quality_labels = neuron_quality(self.session, ids)
        except Exception as exc:  # noqa: BLE001 - reported in the list, not raised
            self.read_error = str(exc)
            self._sync_after_refresh()
            return self.neuron_info

        for index, _ in enumerate(ids):
            self.neuron_info.append(
                {
                    "name": names[index] if index < len(names) else "",
                    "quality_number": quality_numbers[index],
                    "quality_label": quality_labels[index],
                    "passes": True,
                }
            )

        # Keep only those label choices that are still present, as MATLAB's
        # intersect does: a label that no longer exists cannot stay selected.
        present = self.quality_labels_present()
        self.quality_labels = [label for label in self.quality_labels if label in present]
        self._sync_after_refresh()
        return self.neuron_info

    def quality_labels_present(self) -> list[str]:
        """The quality labels the current neurons actually carry, sorted."""
        return sorted(
            {str(info["quality_label"]) for info in self.neuron_info if info["quality_label"]}
        )

    def apply_filter(self) -> int:
        """Mark each cached neuron pass/fail; return how many passed."""
        minimum = self.min_quality if self.min_quality_enabled else None
        passed = 0
        for info in self.neuron_info:
            info["passes"] = passes_filter(
                info["quality_number"],
                info["quality_label"],
                minimum,
                self.quality_labels,
                self.keep_unrated,
            )
            if info["passes"]:
                passed += 1
        return passed

    def neuron_rows(self) -> list[str]:
        """The preview list's rows, filter applied."""
        self.apply_filter()
        if self.read_error:
            return [f"(could not read neurons: {self.read_error})"]
        if not self.neuron_info:
            return [NO_NEURONS_ITEM]
        return [
            neuron_row(info["name"], info["quality_number"], info["quality_label"], info["passes"])
            for info in self.neuron_info
        ]

    def summary_text(self) -> str:
        """The line under the list."""
        if self.read_error:
            return ""
        return summary_message(self.apply_filter(), len(self.neuron_info))

    def can_export(self) -> bool:
        """Export needs all three coordinates and at least one surviving neuron."""
        return bool(
            self.selected_ensemble() is not None
            and self.epoch
            and self.selected_stimulator() is not None
            and self.apply_filter() > 0
        )

    def default_file_name(self) -> str:
        """The name the save dialog opens with."""
        ensemble = self.selected_ensemble()
        reference = ""
        try:
            reference = str(self.session.reference or "")
        except Exception:  # noqa: BLE001
            reference = ""
        name = ""
        if ensemble is not None:
            name = str(getattr(ensemble, "name", "") or "")
        return suggest_file_name(reference, name, self.epoch)

    def export(self, outputfile: str) -> None:
        """Write the blech_clust HDF5 file. Raises what the export raised.

        Separate from the button handler so the export itself can be tested
        without a file dialog -- and so a caller can drive it from a script.
        """
        from ...fun.export import blech_clust

        ensemble = self.selected_ensemble()
        stimulator = self.selected_stimulator()
        probe = ensemble.underlying_element if ensemble is not None else None
        if ensemble is None or stimulator is None or not self.epoch:
            raise ValueError("Select an ensemble, an epoch and a stimulator first.")
        if probe is None:
            raise ValueError(
                "The selected ensemble has no underlying probe, so it cannot be exported."
            )

        blech_clust(
            stimulator,
            probe,
            self.epoch,
            outputfile,
            ensemble=ensemble,
            min_quality=self.min_quality if self.min_quality_enabled else None,
            quality_label=list(self.quality_labels),
            keep_unrated=self.keep_unrated,
            pre_stim=self.pre_stim,
            post_stim=self.post_stim,
            verbose=False,
        )

    # ------------------------------------------------------------------
    # Qt
    # ------------------------------------------------------------------
    def build(self) -> Any:
        """Build the window and return it."""
        from .._qt_helpers import get_or_create_app, require_qt

        require_qt()
        get_or_create_app()
        from PySide6 import QtCore, QtWidgets

        from ..cloud_colors import cloud_colors, rgb_to_hex

        colors = cloud_colors()
        navy = rgb_to_hex(colors.dark_blue)
        white = rgb_to_hex(colors.white)
        accent = rgb_to_hex(colors.light_blue)
        field = f"background-color: {white}; color: {navy};"
        label_style = f"color: {white};"
        bold_label = f"color: {white}; font-weight: bold;"

        x, y, width, height = DEFAULT_POSITION
        self.figure = QtWidgets.QWidget()
        self.figure.setObjectName(WINDOW_TAG)
        self.figure.setWindowTitle(self.window_title())
        self.figure.setGeometry(x, y, width, height)
        self.figure.setStyleSheet(f"background-color: {navy};")

        root = QtWidgets.QVBoxLayout(self.figure)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        self.title_label = QtWidgets.QLabel(TITLE_TEXT)
        self.title_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet(f"color: {white}; font-size: 16px; font-weight: bold;")
        root.addWidget(self.title_label)

        self.subtitle_label = QtWidgets.QLabel(self.subtitle())
        self.subtitle_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.subtitle_label.setStyleSheet(label_style)
        root.addWidget(self.subtitle_label)

        # Ensemble + Reload
        ensemble_row = QtWidgets.QHBoxLayout()
        ensemble_row.setSpacing(8)
        ensemble_caption = QtWidgets.QLabel("Ensemble:")
        ensemble_caption.setStyleSheet(bold_label)
        ensemble_row.addWidget(ensemble_caption)
        self.ensemble_dropdown = QtWidgets.QComboBox()
        self.ensemble_dropdown.setStyleSheet(field)
        self.ensemble_dropdown.currentIndexChanged.connect(self._on_ensemble_index_changed)
        ensemble_row.addWidget(self.ensemble_dropdown, 1)
        reload_button = QtWidgets.QPushButton("Reload")
        reload_button.setStyleSheet(field)
        reload_button.clicked.connect(lambda: self.with_wait(LOADING_MESSAGE, self.reload_all))
        ensemble_row.addWidget(reload_button)
        root.addLayout(ensemble_row)

        # Epoch + Stimulator
        selector_row = QtWidgets.QHBoxLayout()
        selector_row.setSpacing(8)
        epoch_caption = QtWidgets.QLabel("Epoch:")
        epoch_caption.setStyleSheet(bold_label)
        selector_row.addWidget(epoch_caption)
        self.epoch_dropdown = QtWidgets.QComboBox()
        self.epoch_dropdown.setStyleSheet(field)
        self.epoch_dropdown.currentTextChanged.connect(self._on_epoch_text_changed)
        selector_row.addWidget(self.epoch_dropdown, 1)
        stimulator_caption = QtWidgets.QLabel("Stimulator:")
        stimulator_caption.setStyleSheet(bold_label)
        selector_row.addWidget(stimulator_caption)
        self.stimulator_dropdown = QtWidgets.QComboBox()
        self.stimulator_dropdown.setStyleSheet(field)
        self.stimulator_dropdown.currentIndexChanged.connect(self._on_stimulator_index_changed)
        selector_row.addWidget(self.stimulator_dropdown, 1)
        root.addLayout(selector_row)

        # Quality filter
        quality_box = QtWidgets.QGroupBox("Filter by quality")
        quality_box.setStyleSheet(f"QGroupBox {{ color: {white}; font-weight: bold; }}")
        quality_grid = QtWidgets.QGridLayout(quality_box)
        quality_grid.setContentsMargins(10, 10, 10, 10)
        quality_grid.setHorizontalSpacing(12)
        quality_grid.setVerticalSpacing(6)

        self.min_quality_checkbox = QtWidgets.QCheckBox("Minimum quality_number")
        self.min_quality_checkbox.setStyleSheet(label_style)
        self.min_quality_checkbox.toggled.connect(self._on_min_quality_toggled)
        quality_grid.addWidget(self.min_quality_checkbox, 0, 0)

        self.min_quality_spinner = QtWidgets.QSpinBox()
        self.min_quality_spinner.setRange(0, 100)
        self.min_quality_spinner.setValue(int(self.min_quality))
        self.min_quality_spinner.setEnabled(False)
        self.min_quality_spinner.setStyleSheet(field)
        self.min_quality_spinner.valueChanged.connect(self._on_min_quality_value_changed)
        quality_grid.addWidget(self.min_quality_spinner, 0, 1)

        self.keep_unrated_checkbox = QtWidgets.QCheckBox("Keep unrated neurons")
        self.keep_unrated_checkbox.setStyleSheet(label_style)
        self.keep_unrated_checkbox.setToolTip(
            "Keep neurons with no neuron_extracellular quality document"
        )
        self.keep_unrated_checkbox.toggled.connect(self._on_keep_unrated_toggled)
        quality_grid.addWidget(self.keep_unrated_checkbox, 0, 2)

        labels_caption = QtWidgets.QLabel("quality_label is any of (none = ignore):")
        labels_caption.setStyleSheet(label_style)
        quality_grid.addWidget(labels_caption, 1, 0)
        self.quality_label_list = QtWidgets.QListWidget()
        self.quality_label_list.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.quality_label_list.setStyleSheet(field)
        self.quality_label_list.setFixedHeight(70)
        self.quality_label_list.itemSelectionChanged.connect(self._on_quality_labels_changed)
        quality_grid.addWidget(self.quality_label_list, 1, 1, 1, 2)

        window_row = QtWidgets.QHBoxLayout()
        pre_caption = QtWidgets.QLabel("preStim (ms):")
        pre_caption.setStyleSheet(label_style)
        window_row.addWidget(pre_caption)
        self.pre_stim_spinner = QtWidgets.QSpinBox()
        self.pre_stim_spinner.setRange(0, 1_000_000)
        self.pre_stim_spinner.setSingleStep(100)
        self.pre_stim_spinner.setValue(int(self.pre_stim))
        self.pre_stim_spinner.setStyleSheet(field)
        self.pre_stim_spinner.valueChanged.connect(self._on_pre_stim_changed)
        window_row.addWidget(self.pre_stim_spinner)
        post_caption = QtWidgets.QLabel("postStim:")
        post_caption.setStyleSheet(label_style)
        window_row.addWidget(post_caption)
        self.post_stim_spinner = QtWidgets.QSpinBox()
        self.post_stim_spinner.setRange(1, 1_000_000)
        self.post_stim_spinner.setSingleStep(100)
        self.post_stim_spinner.setValue(int(self.post_stim))
        self.post_stim_spinner.setStyleSheet(field)
        self.post_stim_spinner.valueChanged.connect(self._on_post_stim_changed)
        window_row.addWidget(self.post_stim_spinner)
        window_row.addStretch(1)
        quality_grid.addLayout(window_row, 2, 0, 1, 3)
        root.addWidget(quality_box)

        # Preview
        self.neuron_list = QtWidgets.QListWidget()
        self.neuron_list.setStyleSheet(field)
        fixed = QtGui_fixed_font()
        if fixed is not None:
            self.neuron_list.setFont(fixed)
        root.addWidget(self.neuron_list, 1)

        self.summary_label = QtWidgets.QLabel("")
        self.summary_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.summary_label.setStyleSheet(label_style)
        root.addWidget(self.summary_label)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addStretch(1)
        self.export_button = QtWidgets.QPushButton("Export to HDF5...")
        self.export_button.setStyleSheet(
            f"background-color: {accent}; color: {navy}; font-weight: bold;"
        )
        self.export_button.setFixedWidth(200)
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.do_export)
        button_row.addWidget(self.export_button)
        button_row.addStretch(1)
        root.addLayout(button_row)

        self.figure.show()
        return self.figure

    def window_title(self) -> str:
        """MATLAB's window name: the app, then which session it is exporting."""
        try:
            reference = str(self.session.reference or "")
        except Exception:  # noqa: BLE001
            reference = ""
        return f"Katz Lab Exporter: {reference}"

    def subtitle(self) -> str:
        """The second line: which session, and where it lives."""
        try:
            reference = str(self.session.reference or "")
        except Exception:  # noqa: BLE001
            reference = ""
        return f"Session: {reference}    Path: {session_path(self.session)}"

    # ------------------------------------------------------------------
    # widget mirroring
    # ------------------------------------------------------------------
    def _sync_ensemble_dropdown(self) -> None:
        if self.ensemble_dropdown is None:
            return
        self.ensemble_dropdown.blockSignals(True)
        self.ensemble_dropdown.clear()
        items = ensemble_items(self.ensembles)
        self.ensemble_dropdown.addItems(items or [NO_ENSEMBLES_ITEM])
        if items:
            self.ensemble_dropdown.setCurrentIndex(self.ensemble_index)
        self.ensemble_dropdown.blockSignals(False)

    def _sync_stimulator_dropdown(self) -> None:
        if self.stimulator_dropdown is None:
            return
        self.stimulator_dropdown.blockSignals(True)
        self.stimulator_dropdown.clear()
        items = ensemble_items(self.stimulators)
        self.stimulator_dropdown.addItems(items or [NO_STIMULATORS_ITEM])
        if items:
            self.stimulator_dropdown.setCurrentIndex(self.stimulator_index)
        self.stimulator_dropdown.blockSignals(False)

    def _sync_epoch_dropdown(self, choices: Sequence[str]) -> None:
        if self.epoch_dropdown is None:
            return
        self.epoch_dropdown.blockSignals(True)
        self.epoch_dropdown.clear()
        self.epoch_dropdown.addItems(list(choices) or [NO_EPOCHS_ITEM])
        if choices:
            self.epoch_dropdown.setCurrentIndex(0)
        self.epoch_dropdown.blockSignals(False)

    def _sync_after_refresh(self) -> None:
        """Redraw everything downstream of the neuron cache."""
        rows = self.neuron_rows()
        summary = self.summary_text()
        present = self.quality_labels_present()

        if self.quality_label_list is not None:
            self.quality_label_list.blockSignals(True)
            self.quality_label_list.clear()
            self.quality_label_list.addItems(present)
            for row in range(self.quality_label_list.count()):
                item = self.quality_label_list.item(row)
                item.setSelected(item.text() in self.quality_labels)
            self.quality_label_list.blockSignals(False)

        if self.neuron_list is not None:
            self.neuron_list.clear()
            self.neuron_list.addItems(rows)
        if self.summary_label is not None:
            self.summary_label.setText(summary)
        self.update_button_state()

    def update_button_state(self) -> None:
        """Export is live only with all three coordinates and a surviving neuron."""
        if self.min_quality_spinner is not None:
            self.min_quality_spinner.setEnabled(self.min_quality_enabled)
        if self.export_button is not None:
            self.export_button.setEnabled(self.can_export())

    # ------------------------------------------------------------------
    # handlers
    # ------------------------------------------------------------------
    def _on_ensemble_index_changed(self, index: int) -> None:
        if 0 <= index < len(self.ensembles):
            self.ensemble_index = index
            self.on_ensemble_changed()

    def _on_stimulator_index_changed(self, index: int) -> None:
        if 0 <= index < len(self.stimulators):
            self.stimulator_index = index
        self.update_button_state()

    def _on_epoch_text_changed(self, text: str) -> None:
        if text and text != NO_EPOCHS_ITEM:
            self.epoch = text
            self.on_epoch_changed()

    def _on_min_quality_toggled(self, checked: bool) -> None:
        self.min_quality_enabled = bool(checked)
        self.on_filter_changed()

    def _on_min_quality_value_changed(self, value: int) -> None:
        self.min_quality = float(value)
        self.on_filter_changed()

    def _on_keep_unrated_toggled(self, checked: bool) -> None:
        self.keep_unrated = bool(checked)
        self.on_filter_changed()

    def _on_quality_labels_changed(self) -> None:
        if self.quality_label_list is None:
            return
        self.quality_labels = [item.text() for item in self.quality_label_list.selectedItems()]
        self.on_filter_changed()

    def _on_pre_stim_changed(self, value: int) -> None:
        self.pre_stim = float(value)

    def _on_post_stim_changed(self, value: int) -> None:
        self.post_stim = float(value)

    def on_filter_changed(self) -> None:
        """Redraw the preview for the filter as it now stands.

        The neurons are NOT re-read: the filter is applied to the cache, which
        is what makes moving a spinner feel instant on a session whose quality
        documents took a moment to load.
        """
        if self.neuron_list is not None:
            self.neuron_list.clear()
            self.neuron_list.addItems(self.neuron_rows())
        if self.summary_label is not None:
            self.summary_label.setText(self.summary_text())
        self.update_button_state()

    def do_export(self) -> str | None:
        """Ask where to save, then export. Returns the file written, or None."""
        if not self.can_export():
            self.alert(
                "Select an ensemble, an epoch and a stimulator first.", "Incomplete selection"
            )
            return None

        outputfile = self.ask_for_file(self.default_file_name())
        if not outputfile:
            return None  # cancelled

        if self.export_button is not None:
            self.export_button.setEnabled(False)
        dialog = self._progress(f"Exporting to {outputfile}...")
        try:
            self.export(outputfile)
        except Exception as exc:  # noqa: BLE001 - reported, not raised at the user
            self.alert(str(exc), "Export failed")
            return None
        finally:
            _close(dialog)
            self.update_button_state()

        self.alert(f"Wrote blech_clust HDF5 file:\n{outputfile}", "Export complete", success=True)
        return outputfile

    def ask_for_file(self, default_name: str) -> str:
        """Where to write. "" when the user cancels.

        Its own method so a test can answer it without a file dialog, which is
        the only part of the export path a display is genuinely needed for.
        """
        if self.figure is None:
            return ""
        from PySide6 import QtWidgets

        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self.figure,
            "Save blech_clust HDF5 file as",
            default_name,
            "HDF5 file (*.h5);;All files (*)",
        )
        return filename or ""

    # ------------------------------------------------------------------
    # dialogs
    # ------------------------------------------------------------------
    def with_wait(self, message: str, fn: Any) -> Any:
        """Run FN under an indeterminate "please wait" dialog.

        Nestable, as MATLAB's is: an inner call while one is already up runs
        FN without a second dialog, which is what lets ``reload_all`` be
        reached both directly and from the Reload button.
        """
        if self.wait_dialog is not None or self.figure is None:
            return fn()
        self.wait_dialog = self._progress(message)
        try:
            return fn()
        finally:
            self.clear_wait()

    def clear_wait(self) -> None:
        """Take down the wait dialog, if one is up."""
        _close(self.wait_dialog)
        self.wait_dialog = None

    def _progress(self, message: str) -> Any:
        """An indeterminate progress dialog, or None with no window to own it."""
        if self.figure is None:
            return None
        from PySide6 import QtCore, QtWidgets

        dialog = QtWidgets.QProgressDialog(message, "", 0, 0, self.figure)
        dialog.setWindowTitle("Please wait")
        dialog.setCancelButton(None)  # neither language offers a cancel here
        dialog.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.show()
        _process_events()
        return dialog

    def alert(self, message: str, title: str, *, success: bool = False) -> Any:
        """Tell the user something.

        Recorded in :attr:`last_alert` whether or not there is a window, so
        what the app says is checkable with no display -- and so a build that
        never ran cannot swallow an error in silence.
        """
        self.last_alert = (title, message)
        if self.figure is None:
            return None
        from PySide6 import QtWidgets

        box = QtWidgets.QMessageBox(self.figure)
        box.setWindowTitle(title)
        box.setText(message)
        box.setIcon(
            QtWidgets.QMessageBox.Icon.Information
            if success
            else QtWidgets.QMessageBox.Icon.Warning
        )
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
            f"katzExporter({len(self.ensembles)} ensembles, "
            f"{len(self.neuron_info)} neurons, epoch {self.epoch!r})"
        )


def QtGui_fixed_font() -> Any:  # noqa: N802 - names the Qt class it reaches for
    """The platform's fixed-width font, or None where Qt is not importable.

    MATLAB reads ``get(groot,'FixedWidthFontName')`` for the same reason: the
    preview's columns only line up under one.
    """
    try:
        from PySide6 import QtGui

        return QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)
    except Exception:  # noqa: BLE001 - no Qt, no font
        return None


def _close(dialog: Any) -> None:
    """Close a dialog that may not exist."""
    if dialog is not None:
        try:
            dialog.close()
        except Exception:  # noqa: BLE001 - already gone
            pass


def _process_events() -> None:
    """Let Qt paint, so a wait dialog appears before the work starts."""
    try:
        from PySide6 import QtWidgets

        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.processEvents()
    except Exception:  # noqa: BLE001 - no Qt, nothing to paint
        pass
