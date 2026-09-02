"""ndi.gui.app.spike_sorter_importer - import spike-sorter output into a session.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+app/spikeSorterImporter.m``

A session GUI app over ``ndi.fun.probe.import_.kilosort``. Three panes for a
chosen n-trode probe:

* LEFT, "Session neurons" -- the ``neuron_extracellular`` documents already in
  the database for this probe (via ``ndi.fun.probe.extracellularInfo``), as
  ``name | quality | pipeline``. Multi-select; Reload re-reads, Delete removes.
* MIDDLE, "import" -- the curation tags found on the right, and the button
  that imports the sort keeping the selected tags.
* RIGHT, "Pipeline Neurons" -- the clusters on disk for this probe and
  pipeline (via ``kilosort.getInfo``), as ``cluster | tag | #spikes``, with
  the raw-binary status underneath.

THIS IS THE APP THAT MAKES NEURONS EXIST. Nothing else in the Python port
creates the ``'spikes'`` elements that ``ndi.fun.ensemble`` (and so
``ndi.gui.app.ensembleMaker``) reads: ``ndi.app.spikesorter`` still raises
NotImplementedError from ``clusters2neurons``. A sort curated in Phy comes
into NDI through here.

THE MODEL IS PYTHON, NOT THE WIDGETS -- the same split
``ndi.gui.app.ensemble_maker`` documents, and for the same reasons: every
decision this app makes is checkable with no display, and ``build=False``
constructs the model alone. What is different here is that the actions are
DESTRUCTIVE (an import writes documents; Delete removes them), so each one
asks first through :meth:`confirm`, and a caller without a display supplies
its answer rather than being asked.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, ClassVar

from .session_app import SessionApp

__all__ = [
    "spikeSorterImporter",
    "session_neuron_items",
    "pipeline_items",
    "tag_defaults",
    "quality_values_for",
    "binary_status_text",
    "import_confirm_message",
    "delete_confirm_message",
    "pipeline_key",
    "PIPELINES",
    "DEFAULT_PIPELINE",
    "WINDOW_TAG",
    "DEFAULT_POSITION",
    "NTRODE_TYPE",
    "NO_PROBES_ITEM",
    "NO_PROBE_SELECTED",
    "NO_TAGS_SELECTED",
    "NOTHING_TO_DELETE",
    "INVALID_WINDOW",
    "LOADING_PROBES",
    "LOADING_NEURONS",
]

#: The pipelines the right-hand selector offers. One today, as in MATLAB; the
#: list is the extension point, since every other pipeline reference in this
#: module goes through the selected value.
PIPELINES = ("Kilosort 2.5",)
DEFAULT_PIPELINE = PIPELINES[0]

#: Object name on the window, and its default geometry.
WINDOW_TAG = "ndi.gui.app.spikeSorterImporter"
DEFAULT_POSITION = (100, 100, 600, 600)

#: The probe type a spike sort is imported for.
NTRODE_TYPE = "n-trode"

#: The dropdown's entry when the session has no n-trode probes.
NO_PROBES_ITEM = "(no n-trode probes)"

#: The tags imported by default, when the sort carries them.
DEFAULT_TAGS = ("good", "mua")

#: What the user is told when an action cannot proceed.
NO_PROBE_SELECTED = "Select an n-trode probe first."
NO_TAGS_SELECTED = "Select at least one tag to import."
NOTHING_TO_DELETE = "Select one or more neurons to delete."
INVALID_WINDOW = "The waveform window end must be greater than the window start."

#: Shown over the reads behind the panes.
LOADING_PROBES = "Loading probes..."
LOADING_NEURONS = "Loading neurons..."

#: The status line's colours, as MATLAB sets FontColor on the same label.
_STATUS_GREEN = "#008000"
_STATUS_RED = "#b30000"

#: How the status line reports a located recording, as
#: :func:`binary_status_text` writes it.
_FOUND_PREFIX = "Raw binary: found"


def _found(text: str) -> bool:
    return text.startswith(_FOUND_PREFIX)


# ----------------------------------------------------------------------
# what the three panes show
# ----------------------------------------------------------------------
def session_neuron_items(entries: Sequence[dict[str, Any]]) -> list[str]:
    """The left pane's rows: ``name | quality | pipeline``, one per neuron."""
    return [
        f"{str(entry.get('element_name', '')):<18} | "
        f"{str(entry.get('quality_label', '')):<8} | {entry.get('pipeline', '')}"
        for entry in entries
    ]


def pipeline_items(info: dict[str, Any] | None) -> list[str]:
    """The right pane's rows: ``cluster | tag | #spikes``, one per cluster."""
    if not info:
        return []
    return [
        f"{int(cid):5d} | {str(label):<8} | {int(count):7d}"
        for cid, label, count in zip(
            info.get("cluster_ids", []),
            info.get("cluster_labels", []),
            info.get("num_spikes", []),
        )
    ]


def tag_defaults(tags: Sequence[str]) -> list[str]:
    """Which of TAGS start selected: the importer's defaults that are present.

    Matching is case-insensitive but the ORIGINAL spelling is returned, since
    that is what the list shows and what the import is asked for.
    """
    return [tag for tag in tags if str(tag).lower() in DEFAULT_TAGS]


def quality_values_for(tags: Sequence[str]) -> list[int]:
    """A ``quality_number`` per tag, on the importer's convention.

    ``good``/``single`` are 1 and everything else 4 -- including a custom tag,
    which is the honest default: the app cannot know where in a quality scale
    a lab's own label belongs, and 4 (multi-unit) claims the less.
    """
    return [1 if str(tag).lower() in ("good", "single") else 4 for tag in tags]


def pipeline_key(pipeline: str) -> str:
    """The substring matching a stored pipeline string to the selected one.

    ``"Kilosort 2.5"`` -> ``"Kilosort2.5"``, which appears inside the recorded
    provenance ``"Kilosort2.5 to phy to ndi.fun.probe.import.kilosort"``.
    """
    return re.sub(r"\s", "", str(pipeline))


def binary_status_text(info: dict[str, Any] | None) -> tuple[str, str]:
    """The raw-binary status line and its tooltip, as ``(text, tooltip)``.

    Empty when there is nothing to report. This is the pane that tells someone
    whether wide mean waveforms are actually going to be recalculated, which
    is otherwise only discoverable by importing and looking at the result.
    """
    if not info or "binary_found" not in info:
        return "", ""

    if info["binary_found"]:
        from pathlib import Path

        name = Path(str(info.get("binary_file", ""))).name
        channels = info.get("binary_num_channels")
        suffix = ""
        if isinstance(channels, (int, float)) and channels == channels:  # not NaN
            suffix = f", {int(channels)} ch"
        return f"Raw binary: found ({name}{suffix})", str(info.get("binary_file", ""))

    dat_path = str(info.get("binary_dat_path", "") or "")
    if dat_path:
        return (
            f"Raw binary NOT FOUND; params.py dat_path: {dat_path}. Wide waveforms "
            "will fall back to templates - edit dat_path if the recording was moved.",
            f"params.py dat_path points to: {dat_path}",
        )
    return (
        "Raw binary NOT FOUND (no .metadata / no params.py dat_path). Wide waveforms "
        "will fall back to templates.",
        "",
    )


def import_confirm_message(
    pipeline: str,
    probe_label: str,
    tags: Sequence[str],
    *,
    recalculate: bool = False,
    window_ms: tuple[float, float] = (-5.0, 5.0),
    overwrite: bool = False,
) -> str:
    """What the user confirms before an import writes anything.

    Names the pipeline, the probe and the tags, and spells out the two options
    that change what happens rather than how fast: recalculation (which reads
    the raw recording) and overwrite (which REMOVES neurons already imported).
    """
    message = (
        f'Import the {pipeline} sort for probe "{probe_label}", keeping clusters '
        f"tagged [{', '.join(str(tag) for tag in tags)}]?"
    )
    if recalculate:
        message += (
            f"\n\nMean waveforms will be recalculated from the raw binary over "
            f"[{window_ms[0]:g}, {window_ms[1]:g}] ms."
        )
    if overwrite:
        message += (
            "\n\nOverwrite is on: any neurons already imported for this sort will be "
            "removed and re-imported from disk."
        )
    return message


def delete_confirm_message(entries: Sequence[dict[str, Any]]) -> str:
    """What the user confirms before neurons are deleted.

    Names every neuron, because the deletion cascades to their epochs and
    documents and cannot be undone.
    """
    names = ", ".join(str(entry.get("element_name", "")) for entry in entries)
    return f"Delete {len(entries)} neuron(s) from the database? This cannot be undone.\n\n{names}"


# ----------------------------------------------------------------------
# the app
# ----------------------------------------------------------------------
class spikeSorterImporter(SessionApp):  # noqa: N801 - MATLAB's class name, kept exactly
    """The NDI Spike Sorter Importer window.

    ``spikeSorterImporter(session)`` opens it, which is all
    :class:`SessionApp` asks. MATLAB declares no ``Category``, so it sits at
    the Apps menu's top level.
    """

    Name: ClassVar[str] = "spikeSorterImporter"

    def __init__(
        self,
        session: Any,
        *,
        position: tuple[float, float, float, float] = DEFAULT_POSITION,
        build: bool = True,
    ):
        self.session = session
        self.position = tuple(position)

        # --- the model the widgets mirror -----------------------------
        #: The session's n-trode probes, and which one is selected (0-based).
        self.probes: list[Any] = []
        self.probe_items: list[str] = [NO_PROBES_ITEM]
        self.probe_index: int | None = None
        #: The left pane: extracellularInfo entries and their rows.
        self.session_entries: list[dict[str, Any]] = []
        self.session_items: list[str] = []
        self.session_selection: list[int] = []
        #: The right pane: the getInfo result, its rows, and any read error.
        self.pipeline_info: dict[str, Any] | None = None
        self.pipeline_items: list[str] = []
        self.pipeline_error: str = ""
        #: The middle pane: the tags on offer and those chosen.
        self.tags: list[str] = []
        self.selected_tags: list[str] = []
        #: The options.
        self.pipeline: str = DEFAULT_PIPELINE
        self.filter_by_pipeline: bool = False
        self.overwrite: bool = False
        self.recalculate: bool = True
        self.waveform_t0_ms: float = -5.0
        self.waveform_t1_ms: float = 5.0
        #: The raw-binary status, and the last thing the user was told.
        self.binary_status: tuple[str, str] = ("", "")
        self.last_alert: tuple[str, str] | None = None
        #: Answers a caller without a display supplies to :meth:`confirm`.
        #: None means "ask"; True/False answer every confirmation.
        self.auto_confirm: bool | None = None

        # --- the widgets ----------------------------------------------
        self.figure: Any = None
        self.probe_dropdown: Any = None
        self.session_list: Any = None
        self.pipeline_list: Any = None
        self.tag_list: Any = None
        self.overwrite_checkbox: Any = None
        self.recalc_checkbox: Any = None
        self.waveform_t0_field: Any = None
        self.waveform_t1_field: Any = None
        self.pipeline_selector: Any = None
        self.filter_checkbox: Any = None
        self.binary_status_label: Any = None
        self.wait_dialog: Any = None
        self._held: list[Any] = []

        if build:
            self.build()
        self.with_wait(LOADING_NEURONS, self.reload_probes)

    # ------------------------------------------------------------------
    # model
    # ------------------------------------------------------------------
    def reload_probes(self) -> list[str]:
        """Re-read the session's n-trode probes; returns the dropdown's items."""
        try:
            probes = self.session.getprobes(type=NTRODE_TYPE)
        except Exception:  # noqa: BLE001 - a session that cannot list probes has none
            probes = []
        self.probes = list(probes) if probes else []

        if not self.probes:
            self.probe_items = [NO_PROBES_ITEM]
            self.probe_index = None
            self.clear_session_list()
            self.clear_pipeline_list()
            self._sync_probes()
            return self.probe_items

        self.probe_items = [f"{probe.name} | ref {probe.reference}" for probe in self.probes]
        self.probe_index = 0
        self._sync_probes()
        self.on_probe_changed()
        return self.probe_items

    def selected_probe(self) -> Any:
        """The probe the dropdown is on, or None."""
        if self.probe_index is None:
            return None
        if 0 <= self.probe_index < len(self.probes):
            return self.probes[self.probe_index]
        return None

    def set_probe(self, index: int) -> Any:
        """Select the probe at INDEX and reload both panes."""
        if 0 <= int(index) < len(self.probes):
            self.probe_index = int(index)
            self._sync_probes()
            self.on_probe_changed()
        return self.selected_probe()

    def on_probe_changed(self) -> None:
        """Both panes follow the probe."""
        self.with_wait(LOADING_NEURONS, self.reload_probe_data)

    def reload_probe_data(self) -> None:
        """Refresh the pipeline pane first, so a filter has its tags."""
        self.reload_pipeline()
        self.reload_session_neurons()

    def reload_session_neurons(self) -> list[str]:
        """Re-read the imported neurons for the selected probe (the left pane)."""
        probe = self.selected_probe()
        if probe is None:
            self.clear_session_list()
            return self.session_items

        from ...fun.probe import extracellularInfo

        try:
            entries, _ = extracellularInfo(self.session, probe)
        except Exception:  # noqa: BLE001 - an unreadable database shows no neurons
            entries = []

        if self.filter_by_pipeline and entries:
            key = pipeline_key(self.pipeline)
            entries = [e for e in entries if key in str(e.get("pipeline", ""))]

        self.session_entries = list(entries)
        self.session_items = session_neuron_items(self.session_entries)
        # the selection is dropped rather than kept: the rows it pointed at
        # have been rebuilt, and a stale index would delete the wrong neuron
        self.session_selection = []
        self._sync_session_list()
        return self.session_items

    def reload_pipeline(self) -> list[str]:
        """Re-read the sort on disk for the selected probe (the right pane)."""
        probe = self.selected_probe()
        if probe is None:
            self.clear_pipeline_list()
            return self.pipeline_items

        from ...fun.probe.import_ import kilosort

        try:
            info, _ = kilosort.getInfo(self.session, probe)
        except Exception as exc:  # noqa: BLE001 - no sort on disk is the common case
            self.pipeline_info = None
            self.pipeline_error = str(exc)
            self.pipeline_items = [f"(no Kilosort output: {exc})"]
            self.tags = []
            self.selected_tags = []
            self.binary_status = binary_status_text(None)
            self._sync_pipeline_list()
            return self.pipeline_items

        self.pipeline_info = info
        self.pipeline_error = ""
        self.pipeline_items = pipeline_items(info)
        self.binary_status = binary_status_text(info)
        self.tags = [str(tag) for tag in info.get("unique_tags", [])]
        self.selected_tags = tag_defaults(self.tags)
        self._sync_pipeline_list()
        return self.pipeline_items

    def clear_session_list(self) -> None:
        self.session_entries = []
        self.session_items = []
        self.session_selection = []
        self._sync_session_list()

    def clear_pipeline_list(self) -> None:
        self.pipeline_info = None
        self.pipeline_error = ""
        self.pipeline_items = []
        self.tags = []
        self.selected_tags = []
        self.binary_status = binary_status_text(None)
        self._sync_pipeline_list()

    # -- setters, for a caller without a display -----------------------
    def set_tags(self, tags: Sequence[str]) -> list[str]:
        """Choose which tags to import, keeping only ones on offer."""
        self.selected_tags = [tag for tag in tags if tag in self.tags]
        self._sync_tag_list()
        return self.selected_tags

    def set_session_selection(self, rows: Sequence[int]) -> list[int]:
        """Select left-pane rows (0-based), dropping any that do not exist."""
        self.session_selection = [
            int(row) for row in rows if 0 <= int(row) < len(self.session_entries)
        ]
        self._sync_session_selection()
        return self.session_selection

    def set_overwrite(self, value: bool) -> bool:
        self.overwrite = bool(value)
        if self.overwrite_checkbox is not None:
            self.overwrite_checkbox.setChecked(self.overwrite)
        return self.overwrite

    def set_recalculate(self, value: bool) -> bool:
        """Tick or untick recalculation, enabling the window fields with it."""
        self.recalculate = bool(value)
        if self.recalc_checkbox is not None:
            self.recalc_checkbox.setChecked(self.recalculate)
        self.on_recalc_toggled()
        return self.recalculate

    def set_filter_by_pipeline(self, value: bool) -> bool:
        self.filter_by_pipeline = bool(value)
        if self.filter_checkbox is not None:
            self.filter_checkbox.setChecked(self.filter_by_pipeline)
        self.with_wait(LOADING_NEURONS, self.reload_session_neurons)
        return self.filter_by_pipeline

    def set_window_ms(self, t0: float, t1: float) -> tuple[float, float]:
        self.waveform_t0_ms = float(t0)
        self.waveform_t1_ms = float(t1)
        if self.waveform_t0_field is not None:
            self.waveform_t0_field.setValue(self.waveform_t0_ms)
        if self.waveform_t1_field is not None:
            self.waveform_t1_field.setValue(self.waveform_t1_ms)
        return self.waveform_t0_ms, self.waveform_t1_ms

    def on_recalc_toggled(self) -> None:
        """The window fields are usable only when recalculation is on."""
        for field in (self.waveform_t0_field, self.waveform_t1_field):
            if field is not None:
                field.setEnabled(self.recalculate)

    # ------------------------------------------------------------------
    # importing
    # ------------------------------------------------------------------
    def on_import(self) -> int:
        """Import the selected tags of the selected probe's sort.

        Returns the number of neurons imported; 0 when the import did not run
        (nothing selected, the window is invalid, the user declined, or the
        importer failed -- each of which says why through :meth:`alert`).
        """
        probe = self.selected_probe()
        if probe is None:
            self.alert(NO_PROBE_SELECTED, "No probe")
            return 0
        tags = list(self.selected_tags)
        if not tags:
            self.alert(NO_TAGS_SELECTED, "No tags selected")
            return 0
        if self.recalculate and not (self.waveform_t1_ms > self.waveform_t0_ms):
            self.alert(INVALID_WINDOW, "Invalid window")
            return 0

        message = import_confirm_message(
            self.pipeline,
            str(probe.elementstring()),
            tags,
            recalculate=self.recalculate,
            window_ms=(self.waveform_t0_ms, self.waveform_t1_ms),
            overwrite=self.overwrite,
        )
        if not self.confirm(message, "Confirm import", accept="Import"):
            return 0

        # clear a provenance marker left behind by an earlier delete, so the
        # importer's checksum guard does not refuse to re-import a sort whose
        # neurons are already gone
        self.cleanup_orphan_clusters(probe)

        from ...fun.probe.import_ import kilosort

        try:
            imported = self.with_wait(
                "Importing...",
                lambda: kilosort.probe(
                    self.session,
                    probe,
                    quality_labels=tags,
                    quality_values=quality_values_for(tags),
                    kilosort_version=self.kilosort_version(),
                    force=self.overwrite,
                    RecalculateMeanWaveforms=self.recalculate,
                    RecalculateMeanWaveformT0=self.waveform_t0_ms / 1000.0,
                    RecalculateMeanWaveformT1=self.waveform_t1_ms / 1000.0,
                    progressbar=True,
                    verbose=False,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - the reason is what the user needs
            self.alert(str(exc), "Import failed")
            return 0

        self.alert("Import complete.", "Done", success=True)
        self.reload_session_neurons()
        return int(imported or 0)

    def kilosort_version(self) -> str:
        """The version implied by the selected pipeline, e.g. ``'2.5'``.

        Recorded in the provenance of everything the import writes, and it is
        what ``filter_by_pipeline`` later matches against.
        """
        match = re.search(r"([\d.]+)\s*$", str(self.pipeline))
        return match.group(1) if match else "2.5"

    # ------------------------------------------------------------------
    # deleting
    # ------------------------------------------------------------------
    def on_delete(self) -> int:
        """Delete the selected neurons. Returns how many were removed."""
        if not self.session_selection:
            self.alert(NOTHING_TO_DELETE, "Nothing selected")
            return 0
        entries = [self.session_entries[row] for row in self.session_selection]

        if not self.confirm(delete_confirm_message(entries), "Confirm delete", accept="Delete"):
            return 0

        # element_id was captured when the list was loaded; removing the
        # element documents cascades to their dependents (the
        # neuron_extracellular and epoch documents), so one call does the batch
        ids = [entry.get("element_id") for entry in entries if entry.get("element_id")]
        if ids:
            self.with_wait(
                f"Deleting {len(entries)} neuron(s)...",
                lambda: self.session.database_rm(ids),
            )

        # a sort with no neurons left keeps a kilosort_clusters document that
        # would make the importer report "nothing to do" forever
        self.cleanup_orphan_clusters(self.selected_probe())
        self.reload_session_neurons()
        return len(ids)

    def cleanup_orphan_clusters(self, probe: Any) -> int:
        """Remove this probe's ``kilosort_clusters`` documents with no neurons left.

        Returns how many were removed. The importer treats an existing cluster
        document with a matching checksum as "already imported"; once its
        neurons are deleted that claim is false, and clearing it is what lets
        the same sort be imported again.
        """
        if probe is None:
            return 0
        from ...query import ndi_query

        try:
            clusters = self.session.database_search(
                ndi_query("").isa("kilosort_clusters")
                & ndi_query("").depends_on("element_id", probe.id)
            )
        except Exception:  # noqa: BLE001 - nothing to clean if nothing can be read
            return 0

        removed = 0
        for doc in clusters:
            remaining = self.session.database_search(
                ndi_query("").isa("neuron_extracellular")
                & ndi_query("").depends_on("spike_clusters_id", doc.id)
            )
            if not remaining:
                self.session.database_rm(doc)
                removed += 1
        return removed

    # ------------------------------------------------------------------
    # the shared "please wait" indicator (nestable, as MATLAB's is)
    # ------------------------------------------------------------------
    def with_wait(self, message: str, fn: Any) -> Any:
        """Run FN under an indeterminate "please wait" dialog, returning its result."""
        if self.wait_dialog is not None or self.figure is None:
            return fn()
        self.wait_dialog = self._progress(message)
        try:
            return fn()
        finally:
            self.clear_wait()

    def clear_wait(self) -> None:
        if self.wait_dialog is not None:
            try:
                self.wait_dialog.close()
            except Exception:  # noqa: BLE001 - already gone
                pass
        self.wait_dialog = None

    # ------------------------------------------------------------------
    # Qt
    # ------------------------------------------------------------------
    def build(self) -> Any:
        """Build the window and return it."""
        from .._qt_helpers import get_or_create_app, require_qt

        require_qt()
        get_or_create_app()
        from PySide6 import QtCore, QtGui, QtWidgets

        fixed_font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)
        x, y, w, h = self.position

        self.figure = QtWidgets.QWidget()
        self.figure.setWindowTitle("NDI Spike Sorter Importer")
        self.figure.setObjectName(WINDOW_TAG)
        self.figure.setGeometry(int(x), int(y), int(w), int(h))

        root = QtWidgets.QVBoxLayout(self.figure)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)

        title = QtWidgets.QLabel("NDI Spike Sorter Importer")
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        root.addWidget(title)

        subtitle = QtWidgets.QLabel(
            f"Session: {self.session.reference}     Path: {self._session_path()}"
        )
        subtitle.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        root.addWidget(subtitle)

        probe_row = QtWidgets.QHBoxLayout()
        probe_row.addStretch(1)
        probe_row.addWidget(QtWidgets.QLabel("n-trode probes:"))
        self.probe_dropdown = QtWidgets.QComboBox()
        self.probe_dropdown.setMinimumWidth(200)
        self.probe_dropdown.currentIndexChanged.connect(self._on_probe_index_changed)
        probe_row.addWidget(self.probe_dropdown)
        reload_button = QtWidgets.QPushButton("reload")
        reload_button.clicked.connect(lambda: self.with_wait(LOADING_PROBES, self.reload_probes))
        probe_row.addWidget(reload_button)
        probe_row.addStretch(1)
        root.addLayout(probe_row)

        content = QtWidgets.QHBoxLayout()
        content.setSpacing(8)
        content.addLayout(self._build_left(QtWidgets, fixed_font), 1)
        content.addLayout(self._build_middle(QtWidgets, fixed_font), 0)
        content.addLayout(self._build_right(QtWidgets, fixed_font), 1)
        root.addLayout(content, 1)

        self._sync_probes()
        self._sync_session_list()
        self._sync_pipeline_list()
        self.on_recalc_toggled()
        self.figure.show()
        return self.figure

    def _build_left(self, QtWidgets: Any, fixed_font: Any) -> Any:  # noqa: N803
        column = QtWidgets.QVBoxLayout()
        header = QtWidgets.QLabel("Session neurons")
        header.setStyleSheet("font-weight: bold;")
        column.addWidget(header)

        self.session_list = QtWidgets.QListWidget()
        self.session_list.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.session_list.setFont(fixed_font)
        self.session_list.itemSelectionChanged.connect(self._on_session_selection_changed)
        column.addWidget(self.session_list, 1)

        buttons = QtWidgets.QHBoxLayout()
        reload_button = QtWidgets.QPushButton("Reload")
        reload_button.clicked.connect(
            lambda: self.with_wait(LOADING_NEURONS, self.reload_session_neurons)
        )
        buttons.addWidget(reload_button)
        delete_button = QtWidgets.QPushButton("Delete")
        delete_button.clicked.connect(self.on_delete)
        buttons.addWidget(delete_button)
        column.addLayout(buttons)

        self.filter_checkbox = QtWidgets.QCheckBox("Filter by pipeline")
        self.filter_checkbox.toggled.connect(self.set_filter_by_pipeline)
        column.addWidget(self.filter_checkbox)
        return column

    def _build_middle(self, QtWidgets: Any, fixed_font: Any) -> Any:  # noqa: N803
        column = QtWidgets.QVBoxLayout()
        column.addStretch(1)
        column.addWidget(QtWidgets.QLabel("Tags to import"))

        self.tag_list = QtWidgets.QListWidget()
        self.tag_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tag_list.setFont(fixed_font)
        self.tag_list.setFixedHeight(100)
        self.tag_list.itemSelectionChanged.connect(self._on_tag_selection_changed)
        column.addWidget(self.tag_list)

        import_button = QtWidgets.QPushButton("<- import <-")
        import_button.clicked.connect(self.on_import)
        column.addWidget(import_button)

        self.overwrite_checkbox = QtWidgets.QCheckBox("Overwrite existing")
        self.overwrite_checkbox.setToolTip(
            "Re-import from disk, replacing any neurons already imported for this sort"
        )
        self.overwrite_checkbox.toggled.connect(self.set_overwrite)
        column.addWidget(self.overwrite_checkbox)

        self.recalc_checkbox = QtWidgets.QCheckBox("Recalc mean waveforms")
        self.recalc_checkbox.setChecked(True)
        self.recalc_checkbox.setToolTip(
            "Recompute mean spike waveforms over a wider window by reading the raw "
            "binary recording, instead of the narrow (~2 ms) Kilosort templates. For "
            "sorts done outside NDI, the binary is found via 'dat_path' in the folder's "
            "params.py; edit that if the recording was moved (otherwise this falls back "
            "to the narrow template waveforms)."
        )
        self.recalc_checkbox.toggled.connect(self.set_recalculate)
        column.addWidget(self.recalc_checkbox)

        window_row = QtWidgets.QHBoxLayout()
        window_row.addWidget(QtWidgets.QLabel("Window (ms):"))
        self.waveform_t0_field = QtWidgets.QDoubleSpinBox()
        self.waveform_t0_field.setRange(-1000.0, 1000.0)
        self.waveform_t0_field.setValue(self.waveform_t0_ms)
        self.waveform_t0_field.setToolTip("Window start relative to each spike, in milliseconds")
        self.waveform_t0_field.valueChanged.connect(self._on_t0_changed)
        window_row.addWidget(self.waveform_t0_field)
        window_row.addWidget(QtWidgets.QLabel("to"))
        self.waveform_t1_field = QtWidgets.QDoubleSpinBox()
        self.waveform_t1_field.setRange(-1000.0, 1000.0)
        self.waveform_t1_field.setValue(self.waveform_t1_ms)
        self.waveform_t1_field.setToolTip("Window end relative to each spike, in milliseconds")
        self.waveform_t1_field.valueChanged.connect(self._on_t1_changed)
        window_row.addWidget(self.waveform_t1_field)
        column.addLayout(window_row)

        column.addStretch(1)
        return column

    def _build_right(self, QtWidgets: Any, fixed_font: Any) -> Any:  # noqa: N803
        column = QtWidgets.QVBoxLayout()

        selector_row = QtWidgets.QHBoxLayout()
        selector_row.addWidget(QtWidgets.QLabel("Pipeline:"))
        self.pipeline_selector = QtWidgets.QComboBox()
        self.pipeline_selector.addItems(list(PIPELINES))
        self.pipeline_selector.currentTextChanged.connect(self._on_pipeline_changed)
        selector_row.addWidget(self.pipeline_selector, 1)
        column.addLayout(selector_row)

        header = QtWidgets.QLabel("Pipeline Neurons")
        header.setStyleSheet("font-weight: bold;")
        column.addWidget(header)

        columns = QtWidgets.QLabel(f"{'clust':>5} | {'tag':<8} | {'#spikes':>7}")
        columns.setFont(fixed_font)
        columns.setStyleSheet("font-weight: bold;")
        column.addWidget(columns)

        self.pipeline_list = QtWidgets.QListWidget()
        self.pipeline_list.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.pipeline_list.setFont(fixed_font)
        column.addWidget(self.pipeline_list, 1)

        self.binary_status_label = QtWidgets.QLabel("")
        self.binary_status_label.setWordWrap(True)
        self.binary_status_label.setStyleSheet("font-size: 11px;")
        column.addWidget(self.binary_status_label)
        return column

    def show(self) -> None:
        if self.figure is not None:
            self.figure.show()

    def close(self) -> None:
        self.clear_wait()
        if self.figure is not None:
            self.figure.close()

    # -- widget mirrors: each a no-op until the window exists -----------
    def _sync_probes(self) -> None:
        if self.probe_dropdown is None:
            return
        blocked = self.probe_dropdown.blockSignals(True)
        try:
            self.probe_dropdown.clear()
            self.probe_dropdown.addItems(self.probe_items)
            if self.probe_index is not None:
                self.probe_dropdown.setCurrentIndex(self.probe_index)
            self.probe_dropdown.setEnabled(bool(self.probes))
        finally:
            self.probe_dropdown.blockSignals(blocked)

    def _sync_session_list(self) -> None:
        if self.session_list is None:
            return
        blocked = self.session_list.blockSignals(True)
        try:
            self.session_list.clear()
            self.session_list.addItems(self.session_items)
            self._sync_session_selection()
        finally:
            self.session_list.blockSignals(blocked)

    def _sync_session_selection(self) -> None:
        if self.session_list is None:
            return
        blocked = self.session_list.blockSignals(True)
        try:
            self.session_list.clearSelection()
            for row in self.session_selection:
                item = self.session_list.item(row)
                if item is not None:
                    item.setSelected(True)
        finally:
            self.session_list.blockSignals(blocked)

    def _sync_pipeline_list(self) -> None:
        if self.pipeline_list is not None:
            blocked = self.pipeline_list.blockSignals(True)
            try:
                self.pipeline_list.clear()
                self.pipeline_list.addItems(self.pipeline_items)
            finally:
                self.pipeline_list.blockSignals(blocked)
        self._sync_tag_list()
        if self.binary_status_label is not None:
            text, tooltip = self.binary_status
            self.binary_status_label.setText(text)
            self.binary_status_label.setToolTip(tooltip)
            # green when the recording was found, red when it was not: the
            # difference decides whether wide waveforms happen at all
            colour = "" if not text else _STATUS_GREEN if _found(text) else _STATUS_RED
            self.binary_status_label.setStyleSheet(
                f"font-size: 11px; color: {colour};" if colour else "font-size: 11px;"
            )

    def _sync_tag_list(self) -> None:
        if self.tag_list is None:
            return
        blocked = self.tag_list.blockSignals(True)
        try:
            self.tag_list.clear()
            self.tag_list.addItems(self.tags)
            for row, tag in enumerate(self.tags):
                if tag in self.selected_tags:
                    item = self.tag_list.item(row)
                    if item is not None:
                        item.setSelected(True)
        finally:
            self.tag_list.blockSignals(blocked)

    # -- widget events -------------------------------------------------
    def _on_probe_index_changed(self, index: int) -> None:
        if self.probes and 0 <= index < len(self.probes):
            self.probe_index = index
            self.on_probe_changed()

    def _on_session_selection_changed(self) -> None:
        self.session_selection = sorted(
            self.session_list.row(item) for item in self.session_list.selectedItems()
        )

    def _on_tag_selection_changed(self) -> None:
        self.selected_tags = [item.text() for item in self.tag_list.selectedItems()]

    def _on_pipeline_changed(self, text: str) -> None:
        self.pipeline = text
        self.with_wait(LOADING_NEURONS, self.reload_pipeline)

    def _on_t0_changed(self, value: float) -> None:
        self.waveform_t0_ms = float(value)

    def _on_t1_changed(self, value: float) -> None:
        self.waveform_t1_ms = float(value)

    # -- dialogs -------------------------------------------------------
    def _session_path(self) -> str:
        from .ensemble_maker import session_path

        return session_path(self.session)

    def _progress(self, message: str) -> Any:
        if self.figure is None:
            return None
        from PySide6 import QtCore, QtWidgets

        dialog = QtWidgets.QProgressDialog(message, "", 0, 0, self.figure)
        dialog.setWindowTitle("Please wait")
        dialog.setCancelButton(None)
        dialog.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.show()
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.processEvents()
        return dialog

    def alert(self, message: str, title: str, *, success: bool = False) -> Any:
        """Tell the user something, and record it in ``last_alert``."""
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
        self._held.append(box)
        box.finished.connect(lambda _=0, b=box: self._held.remove(b) if b in self._held else None)
        return box

    def confirm(self, message: str, title: str, *, accept: str) -> bool:
        """Confirm a destructive action, defaulting to Cancel.

        ``auto_confirm`` answers instead when it is set, which is how a script
        or a test drives an import without a dialog. With no window and no
        ``auto_confirm`` the answer is NO: a destructive action that nobody
        can be asked about does not proceed.
        """
        self.last_alert = (title, message)
        if self.auto_confirm is not None:
            return bool(self.auto_confirm)
        if self.figure is None:
            return False
        from PySide6 import QtWidgets

        box = QtWidgets.QMessageBox(self.figure)
        box.setWindowTitle(title)
        box.setText(message)
        box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        go = box.addButton(accept, QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton("Cancel", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        return box.clickedButton() is go

    def __repr__(self) -> str:
        return (
            f"spikeSorterImporter(probes={len(self.probes)}, "
            f"imported={len(self.session_entries)})"
        )
