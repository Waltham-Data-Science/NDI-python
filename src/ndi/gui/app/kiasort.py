"""ndi.gui.app.kiasort - run and curate KIASORT spike sorting within NDI.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+app/kiasort.m``

A window over the KIASORT pipeline for a session: the n-trode probes on the
left with their pipeline status ("exported / run / curated"), the main
KIASORT config below, and two buttons that act on the selected probe --
Run (sort + import) and Curate (open KIASORT's curation UI). Grouped under
"Spike Sorters" in the navigator's per-session Apps menu, beside
:mod:`ndi.gui.app.vh_ndi_spike_sorter`.

RUN AND CURATE ARE MATLAB-ONLY, AS THE BACKEND ALREADY SAYS
The KIASORT toolbox is MATLAB, so
:func:`ndi.fun.probe.import_.kiasort.run` and
:func:`ndi.fun.probe.import_.kiasort.curate` are ported as
``NotImplementedError`` with the sentence that names the way forward: sort
and curate in MATLAB, then import the result with
:func:`ndi.fun.probe.import_.kiasort.probe` -- which IS ported and works
end-to-end. Following that same pattern, this window opens on both sides:
buttons stay enabled by pipeline state so the state machine reads the same,
and when Run or Curate is pressed on Python the alert is exactly what the
backend says. A stack trace would leave the user hunting an installation
bug for something that is not an installation problem.

THE MODEL IS PYTHON, NOT THE WIDGETS -- the same split
:mod:`ndi.gui.app.spike_sorter_importer` and
:mod:`ndi.gui.app.vh_ndi_spike_sorter` document. The probe-label text, the
config dict this app hands the backend, and whether either button may be
pressed are plain functions here and testable with no display. What is Qt
is the window that shows them.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from .session_app import SessionApp

__all__ = [
    "kiasort",
    "Kiasort",
    "DEFAULT_POSITION",
    "WINDOW_TAG",
    "DEFAULT_KIASORT_DIR",
    "DEFAULT_BINARY_NAME",
    "DEFAULT_SUBDIR",
    "CHECK_OPTIONS",
    "NUM_OPTIONS",
    "NOT_EXPORTED_SUFFIX",
    "RUN_FAILED_TITLE",
    "RUN_COMPLETE_TITLE",
    "CURATION_FAILED_TITLE",
    "probe_label",
    "config_overrides_from",
    "can_run",
    "can_curate",
]

#: Where the window opens, ``(x, y, width, height)``, as MATLAB positions it.
DEFAULT_POSITION: tuple[float, float, float, float] = (100, 100, 560, 545)

#: The window's object name, MATLAB's figure Tag.
WINDOW_TAG = "ndi.gui.app.kiasort"

#: The kiasort filesystem defaults, matching MATLAB's kiasort.m properties.
#: Kept here so a test can construct the app with the same layout MATLAB
#: reads, and so an alternate export layout stays a single-callsite change.
DEFAULT_KIASORT_DIR = "kiasort"
DEFAULT_BINARY_NAME = "kiasort.bin"
DEFAULT_SUBDIR = "kiasort_output"

#: The label MATLAB shows for a probe that has not been exported yet.
NOT_EXPORTED_SUFFIX = "(not exported)"

#: Dialog titles, matching MATLAB's uialert titles verbatim.
RUN_FAILED_TITLE = "KIASORT run failed"
RUN_COMPLETE_TITLE = "Run complete"
CURATION_FAILED_TITLE = "Curation failed"

#: The boolean KIASORT options: (field, label, default, tooltip). The
#: FIELD names are MATLAB's cfg field names -- they reach
#: :func:`ndi.fun.probe.import_.kiasort.run` as ``cfg_overrides`` keys -- so
#: they keep MATLAB's spelling verbatim, camelCase included.
CHECK_OPTIONS: tuple[tuple[str, str, bool, str], ...] = (
    (
        "useGPU",
        "Use GPU",
        True,
        "Use GPU acceleration if a compatible GPU is available.",
    ),
    (
        "parallelProcessing",
        "Parallel processing",
        False,
        "Use a parallel pool (Parallel Computing Toolbox) to sort across CPU workers.",
    ),
    (
        "denoising",
        "Whitening",
        True,
        "Spatially whiten the data (decorrelate channels) to remove shared / "
        "common-mode noise before spike detection. Recommended.",
    ),
    (
        "extremeNoise",
        "Denoising",
        False,
        "Extra removal of extreme, correlated noise using the noise percentile / "
        "correlation thresholds. Off by default; enable for unusually noisy data.",
    ),
    (
        "sort_only",
        "Sort only",
        False,
        "Skip the sample-clustering stage and re-sort the full recording using "
        "previously sorted samples. Leave OFF for a fresh sort (needs prior samples).",
    ),
    (
        "extractWaveform",
        "Save waveforms",
        False,
        "Also save every spike's waveform to disk (waveforms.h5). NOT required for "
        "curation - KIASORT curation reconstructs individual spike waveforms (and "
        "their variability) from the raw binary - nor for NDI import. Enable only to "
        "precompute a per-spike waveform file for other analysis.",
    ),
    (
        "parallelSort",
        "Parallel sort",
        False,
        "EXPERIMENTAL. Run the final sorting stage (sortData) with per-channel "
        "parallelism across CPU workers. Serial (unchecked) is the validated default "
        "and results should match it (validate with kiaSort_compare_sortings). "
        "Needs the Parallel Computing Toolbox; falls back to serial if unavailable.",
    ),
)

#: The numeric KIASORT parameters: (field, label, default, minimum, integer, tooltip).
NUM_OPTIONS: tuple[tuple[str, str, float, float, bool, str], ...] = (
    (
        "sortingChunkDuration",
        "Sort chunk (s)",
        120.0,
        1.0,
        False,
        'Duration (s) of each stage-3 sorting chunk (the "Chunk k/N" loop). Larger '
        "= fewer passes but much more RAM: peak is SEVERAL times the raw block "
        "(num_channels x duration x fs x 8 bytes) because filtered copies, "
        "waveforms, and whitening temporaries coexist. Raise it in small steps and "
        "watch memory. Default 120.",
    ),
    (
        "batch_ch_size",
        "Chan. batch",
        64.0,
        1.0,
        True,
        "Channels loaded/processed per batch. RAM scales with this AND every "
        "per-block op (whitening/denoising temporaries) scales with it too, so "
        "raising it is expensive - maxing it to all channels can need 100+ GB and "
        "crash. Keep it modest (64-128); the redundant-read savings are small on an "
        "SSD (mostly cache hits). Default 64.",
    ),
)


# ----------------------------------------------------------------------
# model helpers
# ----------------------------------------------------------------------
def probe_label(probe: Any, status: Any) -> str:
    """The listbox label for one probe: ``"<element> (<status words>)"``.

    Uses :meth:`ndi.fun.probe.import_.kiasort.status.Status.words` so the
    order of the words is fixed once, in the backend, and never comes back
    as "run, exported" instead of "exported, run".
    """
    element = str(probe.elementstring())
    words = list(status.words()) if status is not None else []
    if not words:
        return f"{element} {NOT_EXPORTED_SUFFIX}"
    return f"{element} ({', '.join(words)})"


def config_overrides_from(
    checks: Mapping[str, Any],
    nums: Mapping[str, Any],
) -> dict[str, Any]:
    """The ``cfg_overrides`` dict passed to the backend, built from GUI state.

    Checkbox values become plain ``bool`` (a Qt ``CheckState`` is not one).
    Numeric fields pass through unchanged: MATLAB's numeric edit-field
    already rounds integer fields on entry, and the equivalent Qt spin box
    does the same, so no re-coercion here.
    """
    cfg: dict[str, Any] = {key: bool(value) for key, value in checks.items()}
    cfg.update(dict(nums))
    return cfg


def can_run(status: Any) -> bool:
    """The Run button's enable state: an exported probe."""
    return status is not None and bool(getattr(status, "exported", False))


def can_curate(status: Any) -> bool:
    """The Curate button's enable state: a probe that has been run."""
    return status is not None and bool(getattr(status, "run", False))


# ----------------------------------------------------------------------
# app
# ----------------------------------------------------------------------
class kiasort(SessionApp):  # noqa: N801 (MATLAB class name)
    """Run and curate KIASORT for the n-trode probes of a session.

    ``kiasort(session)`` opens the window, which is the whole contract
    :class:`~ndi.gui.app.SessionApp` asks of an app. Passing ``build=False``
    constructs the model alone -- probes are loaded and their statuses read
    -- and is what the tests use, so every model decision is checkable with
    no display.

    MATLAB equivalent: ``ndi.gui.app.kiasort``.
    """

    #: The Apps-menu label. Verbatim from MATLAB: it is user-visible text.
    Name: ClassVar[str] = "Kiasort"

    #: Groups this app beside the other sorters, as MATLAB groups it.
    Category: ClassVar[str] = "Spike Sorters"

    def __init__(
        self,
        session: Any,
        *,
        position: tuple[float, float, float, float] = DEFAULT_POSITION,
        kiasort_dir: str = DEFAULT_KIASORT_DIR,
        binary_file_name: str = DEFAULT_BINARY_NAME,
        subdir: str = DEFAULT_SUBDIR,
        build: bool = True,
    ):
        self.session = session
        self.position = tuple(position)
        self.kiasort_dir = kiasort_dir
        self.binary_file_name = binary_file_name
        self.subdir = subdir

        self.probes: list[Any] = []
        self._statuses: list[Any] = []

        self.figure: Any = None
        self.probe_list: Any = None
        self.run_button: Any = None
        self.curate_button: Any = None
        self.status_label: Any = None
        self._check_widgets: dict[str, Any] = {}
        self._num_widgets: dict[str, Any] = {}
        self._held: list[Any] = []

        self.load_probes()
        self.refresh_statuses()

        if build:
            self.build()

    # ------------------------------------------------------------------
    # model
    # ------------------------------------------------------------------
    def load_probes(self) -> list[Any]:
        """Read the session's n-trode probes; empty list on any failure.

        MATLAB's ``getprobes('type','n-trode')`` wrapped in try/catch so
        that a session that cannot list its probes still opens the window,
        rather than the app dying before it exists.
        """
        try:
            probes = self.session.getprobes(type="n-trode")
        except Exception:  # noqa: BLE001 - MATLAB catches it too
            probes = []
        self.probes = list(probes) if probes else []
        return self.probes

    def probe_status(self, probe: Any) -> Any:
        """One probe's KIASORT-pipeline status.

        Thin delegate to :func:`ndi.fun.probe.import_.kiasort.status`, so
        the app itself owns no answer about what "exported" means. Returns
        ``None`` when the status call cannot run (a broken export layout,
        say), which every consumer treats as "nothing known yet".
        """
        from ...fun.probe.import_ import kiasort as kiasort_backend

        try:
            return kiasort_backend.status(
                self.session,
                probe,
                kiasort_dir=self.kiasort_dir,
                binaryFileName=self.binary_file_name,
                subdir=self.subdir,
            )
        except Exception:  # noqa: BLE001 - reported by the listbox and buttons
            return None

    def refresh_statuses(self) -> list[Any]:
        """Re-read every probe's status; also called after Run finishes."""
        self._statuses = [self.probe_status(p) for p in self.probes]
        return self._statuses

    def probe_labels(self) -> list[str]:
        """The listbox rows, one per probe."""
        return [probe_label(probe, status) for probe, status in zip(self.probes, self._statuses)]

    def selected_index(self) -> int | None:
        """The listbox selection, as an index into ``probes``, or None."""
        if self.probe_list is None:
            return None
        row = self.probe_list.currentRow()
        if row is None or row < 0 or row >= len(self.probes):
            return None
        return int(row)

    def selected_probe(self) -> Any | None:
        """The probe under the selection, or None."""
        idx = self.selected_index()
        return None if idx is None else self.probes[idx]

    def selected_status(self) -> Any | None:
        """The cached status of the selected probe, or None."""
        idx = self.selected_index()
        return None if idx is None else self._statuses[idx]

    def config_overrides(self) -> dict[str, Any]:
        """The ``cfg_overrides`` dict as the KIASORT backend expects it."""
        checks = {key: widget.isChecked() for key, widget in self._check_widgets.items()}
        nums = {key: widget.value() for key, widget in self._num_widgets.items()}
        return config_overrides_from(checks, nums)

    # ------------------------------------------------------------------
    # the window
    # ------------------------------------------------------------------
    def build(self) -> Any:  # noqa: PLR0915 - matches MATLAB's build layout
        from .._qt_helpers import get_or_create_app, require_qt

        require_qt()
        get_or_create_app()
        from PySide6 import QtCore, QtWidgets

        from ..cloud_colors import cloud_colors, rgb_to_hex

        c = cloud_colors()
        x, y, w, h = self.position
        navy = rgb_to_hex(c.dark_blue)
        white = rgb_to_hex(c.white)
        light_blue = rgb_to_hex(c.light_blue)

        self.figure = QtWidgets.QWidget()
        self.figure.setWindowTitle(f"KIASORT: {self.session.reference}")
        self.figure.setObjectName(WINDOW_TAG)
        self.figure.setGeometry(int(x), int(y), int(w), int(h))
        self.figure.setStyleSheet(f"background-color: {navy};")

        root = QtWidgets.QVBoxLayout(self.figure)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        title = QtWidgets.QLabel("Run and Curate KIASORT")
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color: {white}; font-size: 16px; font-weight: bold;")
        title.setFixedHeight(30)
        root.addWidget(title)

        header = QtWidgets.QLabel("n-trode Probes (status):")
        header.setStyleSheet(f"color: {white}; font-weight: bold;")
        header.setFixedHeight(18)
        root.addWidget(header)

        self.probe_list = QtWidgets.QListWidget()
        self.probe_list.setStyleSheet(f"background-color: {white}; color: {navy};")
        self.probe_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.probe_list.currentRowChanged.connect(lambda _row: self.update_button_state())
        root.addWidget(self.probe_list, 1)

        cfg_header = QtWidgets.QLabel("KIASORT options:")
        cfg_header.setStyleSheet(f"color: {white}; font-weight: bold;")
        cfg_header.setFixedHeight(18)
        root.addWidget(cfg_header)

        cfg_grid = QtWidgets.QGridLayout()
        cfg_grid.setContentsMargins(0, 0, 0, 0)
        cfg_grid.setHorizontalSpacing(8)
        cfg_grid.setVerticalSpacing(4)
        for i, (field, label, default, tooltip) in enumerate(CHECK_OPTIONS):
            check = QtWidgets.QCheckBox(label)
            check.setChecked(default)
            check.setToolTip(tooltip)
            check.setStyleSheet(f"color: {white};")
            self._check_widgets[field] = check
            cfg_grid.addWidget(check, i // 3, i % 3)
        cfg_container = QtWidgets.QWidget()
        cfg_container.setLayout(cfg_grid)
        cfg_container.setFixedHeight(100)
        root.addWidget(cfg_container)

        num_row = QtWidgets.QHBoxLayout()
        num_row.setContentsMargins(0, 0, 0, 0)
        num_row.setSpacing(6)
        for field, label, default, minimum, integer, tooltip in NUM_OPTIONS:
            lbl = QtWidgets.QLabel(f"{label}:")
            lbl.setStyleSheet(f"color: {white};")
            lbl.setAlignment(
                QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
            )
            num_row.addWidget(lbl)
            spin: Any
            if integer:
                spin = QtWidgets.QSpinBox()
                spin.setRange(int(minimum), 2**31 - 1)
                spin.setValue(int(default))
            else:
                spin = QtWidgets.QDoubleSpinBox()
                spin.setDecimals(3)
                spin.setRange(float(minimum), 1e12)
                spin.setValue(float(default))
            spin.setToolTip(tooltip)
            spin.setStyleSheet(f"background-color: {white}; color: {navy};")
            self._num_widgets[field] = spin
            num_row.addWidget(spin)
        num_row.addStretch(1)
        num_container = QtWidgets.QWidget()
        num_container.setLayout(num_row)
        num_container.setFixedHeight(34)
        root.addWidget(num_container)

        bottom = QtWidgets.QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(8)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setStyleSheet(f"color: {white};")
        self.status_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignVCenter)
        bottom.addWidget(self.status_label, 1)

        self.run_button = QtWidgets.QPushButton("Run")
        self.run_button.setFixedSize(110, 44)
        self.run_button.setStyleSheet(
            f"background-color: {light_blue}; color: {navy}; font-weight: bold;"
        )
        self.run_button.setToolTip("Run KIASORT on the exported probe and import the results")
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self.run_selected)
        bottom.addWidget(self.run_button)

        self.curate_button = QtWidgets.QPushButton("Curate")
        self.curate_button.setFixedSize(110, 44)
        self.curate_button.setStyleSheet(
            f"background-color: {light_blue}; color: {navy}; font-weight: bold;"
        )
        self.curate_button.setToolTip("Open KIASORT curation for the selected probe's results")
        self.curate_button.setEnabled(False)
        self.curate_button.clicked.connect(self.curate_selected)
        bottom.addWidget(self.curate_button)

        bottom_container = QtWidgets.QWidget()
        bottom_container.setLayout(bottom)
        bottom_container.setFixedHeight(44)
        root.addWidget(bottom_container)

        self.refresh_probe_list()
        self.figure.show()
        return self.figure

    def refresh_probe_list(self) -> list[str]:
        """Re-render the listbox rows and update the button state.

        Preserves the current selection when the row it names still exists,
        as MATLAB's ``refreshProbeList`` does. Returns the labels rendered,
        for the tests.
        """
        if self.probe_list is None:
            return []
        previous = self.selected_index()
        labels = self.probe_labels()
        self.probe_list.clear()
        for label in labels:
            self.probe_list.addItem(label)
        if labels and previous is not None and 0 <= previous < len(labels):
            self.probe_list.setCurrentRow(previous)
        self.update_button_state()
        return labels

    def update_button_state(self) -> tuple[bool, bool]:
        """Enable Run and Curate to match the selected probe's status.

        Returns the (run, curate) enabled pair, for the tests.
        """
        status = self.selected_status()
        run_ok = can_run(status)
        curate_ok = can_curate(status)
        if self.run_button is not None:
            self.run_button.setEnabled(run_ok)
        if self.curate_button is not None:
            self.curate_button.setEnabled(curate_ok)
        return run_ok, curate_ok

    def show(self) -> None:
        if self.figure is not None:
            self.figure.show()

    def close(self) -> None:
        if self.figure is not None:
            self.figure.close()

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------
    def run_selected(self) -> Any:
        """Run KIASORT on the selected probe and import the results.

        On Python, :func:`ndi.fun.probe.import_.kiasort.run` raises
        ``NotImplementedError`` with the sentence that names the way
        forward -- "sort in MATLAB, then import here". This method catches
        that and shows it in a dialog, so the state matches MATLAB's
        state-machine (buttons enabled by pipeline state) while the user
        sees why nothing happened.
        """
        probe = self.selected_probe()
        if probe is None:
            return None

        from ...fun.probe.import_ import kiasort as kiasort_backend

        cfg = self.config_overrides()
        self._set_busy(True, "Running KIASORT (this can take a while)...")
        error: str | None = None
        imported = False
        try:
            kiasort_backend.run(self.session, probe, cfg_overrides=cfg, verbose=0)
            self._set_status_text("Importing results...")
            kiasort_backend.probe(self.session, probe, verbose=0)
            imported = True
        except Exception as exc:  # noqa: BLE001 - shown in a dialog, not raised
            error = str(exc)
        finally:
            self._set_busy(False, "")
            self.refresh_statuses()
            self.refresh_probe_list()

        if error is not None:
            return self.alert(error, RUN_FAILED_TITLE)
        if imported:
            element = str(getattr(probe, "elementstring", lambda: "")()) or "probe"
            return self.alert(
                f"KIASORT finished and results were imported for {element}.",
                RUN_COMPLETE_TITLE,
                success=True,
            )
        return None

    def curate_selected(self) -> Any:
        """Open KIASORT's curation UI for the selected probe.

        Same shape as :meth:`run_selected`: the backend raises
        ``NotImplementedError`` on Python (KIASORT's curation is a MATLAB
        app) and this shows the message; a lab that grows a Python
        equivalent needs no change here.
        """
        probe = self.selected_probe()
        if probe is None:
            return None

        from ...fun.probe.import_ import kiasort as kiasort_backend

        try:
            return kiasort_backend.curate(self.session, probe)
        except Exception as exc:  # noqa: BLE001 - shown in a dialog, not raised
            return self.alert(str(exc), CURATION_FAILED_TITLE)

    # ------------------------------------------------------------------
    # helpers used by the actions
    # ------------------------------------------------------------------
    def _set_busy(self, busy: bool, message: str) -> None:
        self._set_status_text(message)
        enabled = not busy
        if self.probe_list is not None:
            self.probe_list.setEnabled(enabled)
        if self.run_button is not None:
            self.run_button.setEnabled(enabled)
        if self.curate_button is not None:
            self.curate_button.setEnabled(enabled)
        if not busy:
            self.update_button_state()

    def _set_status_text(self, message: str) -> None:
        if self.status_label is not None:
            self.status_label.setText(message)

    # ------------------------------------------------------------------
    # dialogs
    # ------------------------------------------------------------------
    def alert(self, message: str, title: str, *, success: bool = False) -> Any:
        """Show a message. Non-blocking, matching the navigator's alert.

        Held in ``self._held`` while it is open so Qt does not garbage
        collect the modeless box out from under itself, and dropped on close.
        """
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

    def __repr__(self) -> str:
        return f"kiasort(probes={len(self.probes)})"


#: PascalCase spelling, for code that would rather not write a class name
#: that starts lowercase. The MATLAB spelling is the class itself.
Kiasort = kiasort
