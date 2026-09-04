"""ndi.gui.app.ensemble_maker - build spiking-neuron ensembles for n-trode probes.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+app/ensembleMaker.m``

A session GUI app (see :class:`~ndi.gui.app.session_app.SessionApp`) over
:func:`ndi.fun.ensemble.all_element`. It lists the session's n-trode probes,
marks the ones that already have an ensemble with a leading ``*``, builds (or
rebuilds) ensembles for the probes you select, and raster-plots one epoch of
one ensemble.

Ensembles produced here are what ``ndi.fun.export.blech_clust`` -- and
:mod:`ndi.gui.app.katz_exporter`, the app over it -- read when exporting.

WHAT THIS APP CONSUMES, AND WHAT DOES NOT YET PRODUCE IT
An ensemble is built from the SPIKING-NEURON elements recorded on a probe:
``ndi.fun.ensemble.load`` collects the elements of type ``'spikes'`` that
have the probe as their underlying element. A probe with none yields an
ensemble of zero neurons -- built, marked, and empty when plotted -- which is
what MATLAB does too, and is the reason the "no neurons to plot" message
exists in both.

Those neuron elements come from spike sorting, and Python cannot yet produce
them: ``ndi.app.spikesorter.clusters2neurons`` and ``loadwaveforms``, and
several ``ndi.app.spikeextractor`` methods, raise NotImplementedError, while
MATLAB's two sorter apps (kiasort, vhNDISpikeSorter) are blocked on their own
external toolboxes. So this app is fully useful today on a session whose
neurons arrived from somewhere else -- sorted in MATLAB, pulled from the
cloud, or written by a lab's own code -- and will build empty ensembles on
one sorted entirely within Python, until that pipeline lands. Nothing here
needs revisiting when it does; the app reads whatever ``'spikes'`` elements
the session holds.

THE MODEL IS PYTHON, NOT THE WIDGETS
MATLAB keeps this app's state IN the widgets: the listbox's ``ItemsData`` is
the probe index, the dropdown's ``Value`` is the epoch. Here the state lives
on the object (``probes``, ``ensemble_map``, ``items``, ``selection``,
``epoch``) and the widgets mirror it. Two things follow, and both are why it
is done this way: every decision the app makes -- which probes are selected,
whether Make is enabled, which epochs are offered -- is checkable with no
display attached, and a build failure costs the window rather than the class.
``build=False`` constructs the model alone.

SELECTION INDICES ARE 0-BASED
MATLAB's listbox carries ``1:n`` in ``ItemsData``; ``selection`` here holds
Qt row numbers, which are 0-based. They index a Python list and are never
shown to anyone, so they are internal data access in the sense of
``ndi_xlang_principles`` -- the 1-based rule covers epochs, channels and
trials, not widget rows.

WHY THE ENSEMBLE LOOKUP IS NOT ``ndi_document2ndi_object``
MATLAB walks each ``ensemble`` map document back to its element with
``ndi.database.fun.ndi_document2ndi_object``. The Python function of that
name maps the stored class to a constructor that builds a BRAND NEW element
from its name, reference and type -- fresh id, no underlying element -- so
the walk back to the probe would find nothing (the same trap
``ndi.fun.ensemble_db._element_from_document`` documents). :func:`ensemble_map`
therefore constructs ``ndi.element.ensemble`` from the document directly,
which is the load form that restores the id and the underlying element, and
is what MATLAB's helper achieves there.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from .session_app import SessionApp

__all__ = [
    "ensembleMaker",
    "ensemble_map",
    "probe_items",
    "epoch_choices",
    "session_path",
    "number_of_neurons",
    "built_message",
    "failures_message",
    "empty_ensemble_message",
    "raster_title",
    "if_exists_for",
    "MARKER",
    "UNMARKED",
    "WINDOW_TAG",
    "DEFAULT_POSITION",
    "NTRODE_TYPE",
    "NO_PROBES_ITEM",
    "EPOCH_PLACEHOLDER",
    "NO_EPOCHS_ITEM",
    "NO_SELECTION",
    "CANNOT_PLOT",
    "NO_EPOCH",
    "LOADING_MESSAGE",
    "READING_MESSAGE",
]

#: Drawn before a probe that already has an ensemble with at least one epoch.
MARKER = "* "

#: Drawn before a probe that does not, so every label starts in one column.
UNMARKED = "  "

#: Object name on the window, matching MATLAB's figure Tag.
WINDOW_TAG = "ndi.gui.app.ensembleMaker"

#: Default geometry ``(x, y, width, height)``, as MATLAB has it.
DEFAULT_POSITION = (100, 100, 560, 500)

#: The probe type this app builds ensembles for -- the same type
#: ``ndi.fun.ensemble.allNTrodes`` sweeps. Spelled out here rather than
#: imported from ``ndi.fun.ensemble_db`` so that importing this module costs
#: nothing but the standard library: discovery imports EVERY module in
#: ``ndi.gui.app`` to find the apps in it, whether or not one is launched.
NTRODE_TYPE = "n-trode"

#: The single list entry shown when the session has no n-trode probes.
NO_PROBES_ITEM = "(no n-trode probes)"

#: The dropdown's entry when the selection is not one ensemble-bearing probe.
EPOCH_PLACEHOLDER = "(select one probe with an ensemble)"

#: The dropdown's entry when the selected probe's ensemble has no epochs.
NO_EPOCHS_ITEM = "(no epochs)"

#: Said when Make Ensemble is pressed with nothing selected.
NO_SELECTION = "Select one or more n-trode probes."

#: Said when Plot Ensemble is pressed without a single plottable probe.
CANNOT_PLOT = "Select a single n-trode probe that has an ensemble (marked with *)."

#: Said when Plot Ensemble is pressed with no epoch chosen.
NO_EPOCH = "Choose an epoch to plot."

#: Shown over the database reads that fill the probe list.
LOADING_MESSAGE = "Loading n-trode probes..."

#: Shown over the read behind Plot Ensemble.
READING_MESSAGE = "Reading ensemble..."


# ----------------------------------------------------------------------
# What the window shows: pure functions, so it is checkable without one
# ----------------------------------------------------------------------
def probe_items(probes: Sequence[Any], have_ensemble: Sequence[str] = ()) -> list[str]:
    """One list label per probe, ``*``-marked when it already has an ensemble.

    ``have_ensemble`` holds element ids -- the keys of :func:`ensemble_map`.
    Unmarked labels are padded to the same width, so the probe names line up
    whether or not their neighbours are marked.
    """
    marked = set(have_ensemble or ())
    return [
        f"{MARKER if _identifier(probe) in marked else UNMARKED}{probe.elementstring()}"
        for probe in probes
    ]


def ensemble_map(session: Any) -> dict[str, Any]:
    """Map a probe's element id to its ensemble, for probes that have one.

    Ensembles are found through their ``ensemble`` MAP documents, which exist
    only once an epoch has actually been built, and then walked back to the
    underlying probe. Asking ``getelements`` instead would also report an
    ensemble element that was created and never filled, and the ``*`` in the
    list would then promise data that is not there.

    Every failure along the way -- an unsearchable database, a document whose
    element will not load, an ensemble with no underlying element -- costs
    that one entry and nothing else, as MATLAB's try/catch does: a probe that
    silently loses its marker is a lesser fault than a window that will not
    open.
    """
    from ...query import ndi_query

    try:
        map_docs = session.database_search(ndi_query("", "isa", "ensemble", ""))
    except Exception:  # noqa: BLE001 - an unsearchable database means "none known"
        map_docs = []

    found: dict[str, Any] = {}
    for element_id in _unique_stable(_dependency_ids(map_docs, "element_id")):
        ensemble = _load_ensemble(session, element_id)
        if ensemble is None:
            continue
        underlying = getattr(ensemble, "underlying_element", None)
        if underlying is None:
            continue
        found[_identifier(underlying)] = ensemble
    return found


def epoch_choices(ensemble: Any) -> tuple[list[str], bool]:
    """The epoch dropdown's entries and whether it is usable.

    ``(ids, True)`` when ENSEMBLE has epochs; otherwise a single placeholder
    entry and False, which is also what disables the Plot button. The two
    placeholders differ because the two situations do: "you have not selected
    one probe with an ensemble" is the user's next move, "(no epochs)" is not.
    """
    if ensemble is None:
        return [EPOCH_PLACEHOLDER], False
    try:
        table = ensemble.epochtable()
        # ndi.epoch.epochset.epochtable returns (table, hashvalue); MATLAB's
        # returns the table alone.
        entries = table[0] if isinstance(table, tuple) else table
        ids = [str(_epoch_id(entry)) for entry in entries if _epoch_id(entry)]
    except Exception:  # noqa: BLE001 - an unreadable epoch table means "none"
        ids = []
    if not ids:
        return [NO_EPOCHS_ITEM], False
    return ids, True


def session_path(session: Any) -> str:
    """SESSION's directory for the header line, ``""`` when it has none.

    Best-effort, as MATLAB's is: a session need not be on disk (an
    ``ndi.session`` that is not an ``ndi.session.dir`` has no path at all),
    and a header line is not worth an exception.
    """
    getpath = getattr(session, "getpath", None)
    if callable(getpath):
        try:
            return str(getpath())
        except Exception:  # noqa: BLE001 - fall through to the property
            pass
    try:
        return str(getattr(session, "path", "") or "")
    except Exception:  # noqa: BLE001 - a session that will not say
        return ""


def number_of_neurons(E: Mapping[str, Any]) -> int:
    """Rows in an ensemble structure's activity matrix, dense or sparse."""
    activity = E.get("activity")
    if activity is None:
        return 0
    shape = getattr(activity, "shape", None)
    return int(shape[0]) if shape is not None else len(activity)


def if_exists_for(rebuild: bool) -> str:
    """``all_element``'s ``if_exists`` for the Rebuild checkbox's state.

    Unticked is ``'skip'``, so pressing Make Ensemble on a probe that already
    has one is safe and only fills in the epochs that are missing. Ticked is
    ``'replace'``, which deletes and rebuilds -- the reason the checkbox says
    so and defaults to off.
    """
    return "replace" if rebuild else "skip"


def built_message(count: int) -> str:
    """Reported when every selected probe's ensemble was built."""
    return f"Built ensembles for {count} probe(s)."


def failures_message(errors: Sequence[str]) -> str:
    """Reported when some did not: one line per probe, MATLAB's strjoin."""
    return "\n".join(errors)


def empty_ensemble_message(label: str, epoch: str) -> str:
    """Reported when the epoch asked for holds no neurons to plot."""
    return f"The ensemble for {label}, epoch {epoch} has no neurons to plot."


def raster_title(label: str, epoch: str, count: int) -> str:
    """The title over a plotted raster."""
    return f"{label}  -  epoch {epoch}  ({count} neuron(s))"


# ----------------------------------------------------------------------
# The app
# ----------------------------------------------------------------------
class ensembleMaker(SessionApp):  # noqa: N801 - MATLAB's class name, kept exactly
    """The Ensemble Maker window.

    ``ensembleMaker(session)`` opens it, which is the whole contract
    :class:`SessionApp` asks for: the navigator's Apps menu finds this class
    by its ``Name`` and launches it with the session.
    """

    Name: ClassVar[str] = "Ensemble Maker"
    Category: ClassVar[str] = "Ensembles"

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
        #: The session's n-trode probes, in list order.
        self.probes: list[Any] = []
        #: Probe element id -> its ndi.element.ensemble, for those that have one.
        self.ensemble_map: dict[str, Any] = {}
        #: The element ids of the probes marked with a "*".
        self.have_ensemble: list[str] = []
        #: The list labels, one per probe (or the empty-list placeholder).
        self.items: list[str] = [NO_PROBES_ITEM]
        #: Selected rows, 0-based, always within range of ``probes``.
        self.selection: list[int] = []
        #: The epoch dropdown's entries, and the epoch currently chosen.
        self.epoch_items: list[str] = [EPOCH_PLACEHOLDER]
        self.epoch: str = ""
        #: "Rebuild existing (replace)".
        self.rebuild: bool = False
        #: Whether each control is usable, mirrored onto the widgets.
        self.make_enabled: bool = False
        self.plot_enabled: bool = False
        self.epoch_enabled: bool = False
        #: ``(title, message)`` of the last thing the user was told, so what
        #: the app SAYS is checkable without a display.
        self.last_alert: tuple[str, str] | None = None

        # --- the widgets ----------------------------------------------
        self.figure: Any = None
        self.probe_list: Any = None
        self.epoch_dropdown: Any = None
        self.plot_button: Any = None
        self.rebuild_checkbox: Any = None
        self.make_button: Any = None
        self.wait_dialog: Any = None
        #: Raster figures, and message boxes, kept from being collected while
        #: they are on screen -- the same reason SessionApp.launch returns the
        #: app rather than discarding it.
        self.rasters: list[Any] = []
        self._held: list[Any] = []

        if build:
            self.build()
        # The first reads (probes, then every ensemble map document) can take
        # a moment on a large session, so they happen under the wait dialog.
        self.with_wait(LOADING_MESSAGE, self.reload_probes)

    # ------------------------------------------------------------------
    # model
    # ------------------------------------------------------------------
    def reload_probes(self) -> list[str]:
        """Re-read the probes and their ensembles; returns the list labels.

        The selection is preserved across the reload, dropping any row that no
        longer exists. Keeping the ROW rather than the probe matches MATLAB,
        and the reload is what refreshes the ``*`` markers after a build.
        """
        previous = list(self.selection)
        try:
            probes = self.session.getprobes(type=NTRODE_TYPE)
        except Exception:  # noqa: BLE001 - a session that cannot list probes has none to show
            probes = []
        self.probes = list(probes) if probes else []
        self.ensemble_map = self.build_ensemble_map()
        self.have_ensemble = list(self.ensemble_map)

        self.items = probe_items(self.probes, self.have_ensemble) or [NO_PROBES_ITEM]
        self.selection = [row for row in previous if 0 <= row < len(self.probes)]

        self._sync_probe_list()
        self.on_selection_changed()
        return self.items

    def build_ensemble_map(self) -> dict[str, Any]:
        """This session's probe id -> ensemble map. See :func:`ensemble_map`."""
        return ensemble_map(self.session)

    def session_path(self) -> str:
        """This session's directory, for the header line."""
        return session_path(self.session)

    def selected_probes(self) -> list[Any]:
        """The probe objects currently selected."""
        return [self.probes[row] for row in self.selection if 0 <= row < len(self.probes)]

    def single_plottable_probe(self) -> tuple[Any, Any]:
        """``(probe, ensemble)`` when exactly one selected probe has an ensemble.

        ``(None, None)`` otherwise -- no selection, several probes, or one
        probe that has no ensemble yet. Plotting is a single-probe action, so
        the question is asked once here and answered the same way by the Plot
        button and by the epoch dropdown.
        """
        selected = self.selected_probes()
        if len(selected) != 1:
            return None, None
        probe = selected[0]
        ensemble = self.ensemble_map.get(_identifier(probe))
        return (probe, ensemble) if ensemble is not None else (None, None)

    def on_selection_changed(self) -> None:
        """Re-derive everything that depends on which probes are selected."""
        self.update_button_state()
        self.update_epoch_choices()

    def update_button_state(self) -> None:
        """Make Ensemble is usable exactly when something is selected."""
        self.make_enabled = bool(self.selected_probes())
        if self.make_button is not None:
            self.make_button.setEnabled(self.make_enabled)

    def update_epoch_choices(self) -> None:
        """Refill the epoch dropdown for the current selection.

        The previously chosen epoch is kept when it is still on offer, so
        re-selecting the same probe does not silently move the plot to a
        different epoch.
        """
        previous = self.epoch
        _, ensemble = self.single_plottable_probe()
        self.epoch_items, self.epoch_enabled = epoch_choices(ensemble)
        self.plot_enabled = self.epoch_enabled
        if self.epoch_enabled:
            self.epoch = previous if previous in self.epoch_items else self.epoch_items[0]
        else:
            self.epoch = ""
        self._sync_epoch_dropdown()

    def set_selection(self, rows: Sequence[int]) -> list[int]:
        """Select ROWS (0-based), dropping any that no longer exist.

        The way a caller without a display -- a test, or a script driving the
        app -- says what the user would have clicked.
        """
        self.selection = [int(row) for row in rows if 0 <= int(row) < len(self.probes)]
        self._sync_probe_list_selection()
        self.on_selection_changed()
        return self.selection

    def set_epoch(self, epoch: str) -> str:
        """Choose EPOCH in the dropdown, if it is on offer."""
        if epoch in self.epoch_items and self.epoch_enabled:
            self.epoch = epoch
            self._sync_epoch_dropdown()
        return self.epoch

    def set_rebuild(self, rebuild: bool) -> bool:
        """Tick or untick "Rebuild existing (replace)"."""
        self.rebuild = bool(rebuild)
        if self.rebuild_checkbox is not None:
            self.rebuild_checkbox.setChecked(self.rebuild)
        return self.rebuild

    # ------------------------------------------------------------------
    # ensemble building
    # ------------------------------------------------------------------
    def make_ensembles(self) -> list[str]:
        """Build (or rebuild) the selected probes' ensembles.

        Returns one ``"<probe>: <reason>"`` line per probe that failed, empty
        when all succeeded. A failing probe does NOT stop the ones after it --
        with several selected, the alternative is that one bad probe silently
        costs the rest of a long build.
        """
        selected = self.selected_probes()
        if not selected:
            self.alert(NO_SELECTION, "Nothing selected")
            return []

        from ...fun import ensemble as ndi_ensemble

        if_exists = if_exists_for(self.rebuild)
        count = len(selected)
        if self.make_button is not None:
            self.make_button.setEnabled(False)
        dialog = self._progress(f"Building ensembles for {count} probe(s)...", maximum=count)

        errors: list[str] = []
        try:
            for index, probe in enumerate(selected, start=1):
                label = str(probe.elementstring())
                self._advance(
                    dialog,
                    f"Building ensemble for {label} ({index} of {count})...",
                    value=index - 1,
                )
                try:
                    ndi_ensemble.all_element(
                        self.session, probe, if_exists=if_exists, verbose=False
                    )
                except Exception as exc:  # noqa: BLE001 - reported per probe, below
                    errors.append(f"{label}: {exc}")
            self._advance(dialog, value=count)

            self.reload_probes()  # refresh the "*" markers

            if errors:
                self.alert(failures_message(errors), "Some ensembles failed")
            else:
                self.alert(built_message(count), "Done", success=True)
        finally:
            # MATLAB's onCleanup: the dialog goes when this returns, however
            # it returns, and the button comes back with it.
            self.finish_make(dialog)
        return errors

    def finish_make(self, dialog: Any = None) -> None:
        """Close the build's progress dialog and re-enable Make Ensemble."""
        _close(dialog)
        self.update_button_state()

    # ------------------------------------------------------------------
    # plotting
    # ------------------------------------------------------------------
    def plot_ensemble(self) -> Any:
        """Plot the chosen epoch of the selected probe's ensemble."""
        probe, ensemble = self.single_plottable_probe()
        if ensemble is None:
            self.alert(CANNOT_PLOT, "Cannot plot")
            return None
        epoch = self.epoch
        if not epoch:
            self.alert(NO_EPOCH, "No epoch")
            return None
        return self.with_wait(READING_MESSAGE, lambda: self.do_plot(probe, ensemble, epoch))

    def do_plot(self, probe: Any, ensemble: Any, epoch: str) -> Any:
        """Read one epoch of ENSEMBLE and draw its raster. Returns the figure."""
        from ...fun import ensemble as ndi_ensemble

        try:
            E = ndi_ensemble.read(self.session, ensemble, epoch)
        except Exception as exc:  # noqa: BLE001 - the reason is what the user needs
            self.alert(str(exc), "Could not read ensemble")
            return None

        label = str(probe.elementstring())
        count = number_of_neurons(E)
        if count == 0:
            self.alert(empty_ensemble_message(label, epoch), "Empty ensemble")
            return None
        return self.draw_raster(E, label, epoch, count)

    def draw_raster(self, E: Mapping[str, Any], label: str, epoch: str, count: int) -> Any:
        """Draw E's raster in a new matplotlib figure, and return it.

        MATLAB has to create the figure, create the axes and make them CURRENT
        before calling ``ndi.fun.ensemble.plot``, which draws into whatever is
        current. The Python function takes the axes as an argument, so the
        figure is built and handed over instead -- same picture, no global
        state in the middle of it.
        """
        import matplotlib.pyplot as plt

        from ...fun import ensemble as ndi_ensemble
        from ..cloud_colors import cloud_colors

        colors = cloud_colors()
        figure, axes = plt.subplots()
        figure.set_facecolor("w")
        try:
            figure.canvas.manager.set_window_title(f"Ensemble raster: {label}  epoch {epoch}")
        except Exception:  # noqa: BLE001 - a backend with no window to title
            pass
        ndi_ensemble.plot(E, ax=axes, color=colors.dark_blue)
        axes.set_title(raster_title(label, epoch, count))
        self.rasters.append(figure)
        try:
            figure.show()
        except Exception:  # noqa: BLE001 - a non-interactive backend cannot show one
            pass
        return figure

    # ------------------------------------------------------------------
    # the shared "please wait" indicator (nestable, as MATLAB's is)
    # ------------------------------------------------------------------
    def with_wait(self, message: str, fn: Any) -> Any:
        """Run FN under an indeterminate "please wait" dialog.

        Nestable: an inner call while one is already up runs FN without a
        second dialog, so ``reload_probes`` can be reached both directly and
        from inside a build. Returns whatever FN returns -- MATLAB's version
        discards it, and keeping it is what lets ``plot_ensemble`` hand back
        its figure.
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

        c = cloud_colors()
        navy = rgb_to_hex(c.dark_blue)
        white = rgb_to_hex(c.white)
        accent = rgb_to_hex(c.light_blue)
        x, y, w, h = self.position

        self.figure = QtWidgets.QWidget()
        self.figure.setWindowTitle(f"Ensemble Maker: {self.session.reference}")
        self.figure.setObjectName(WINDOW_TAG)
        self.figure.setGeometry(int(x), int(y), int(w), int(h))
        self.figure.setStyleSheet(f"background-color: {navy}; color: {white};")

        root = QtWidgets.QVBoxLayout(self.figure)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        title = QtWidgets.QLabel("Make Neuron Ensembles")
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color: {white}; font-size: 16px; font-weight: bold;")
        root.addWidget(title)

        subtitle = QtWidgets.QLabel(
            f"Session: {self.session.reference}    Path: {self.session_path()}"
        )
        subtitle.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(f"color: {white};")
        root.addWidget(subtitle)

        header = QtWidgets.QLabel("n-trode probes (* = has ensemble):")
        header.setStyleSheet(f"color: {white}; font-weight: bold;")
        root.addWidget(header)

        self.probe_list = QtWidgets.QListWidget()
        self.probe_list.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.probe_list.setStyleSheet(f"background-color: {white}; color: {navy};")
        self.probe_list.setFont(_fixed_width_font())
        self.probe_list.itemSelectionChanged.connect(self._on_selection_changed)
        root.addWidget(self.probe_list, 1)

        plot_row = QtWidgets.QHBoxLayout()
        plot_row.setSpacing(8)
        epoch_label = QtWidgets.QLabel("Epoch:")
        epoch_label.setStyleSheet(f"color: {white}; font-weight: bold;")
        plot_row.addWidget(epoch_label)
        self.epoch_dropdown = QtWidgets.QComboBox()
        self.epoch_dropdown.setStyleSheet(f"background-color: {white}; color: {navy};")
        self.epoch_dropdown.currentTextChanged.connect(self._on_epoch_changed)
        plot_row.addWidget(self.epoch_dropdown, 1)
        self.plot_button = QtWidgets.QPushButton("Plot Ensemble")
        self.plot_button.setStyleSheet(
            f"background-color: {accent}; color: {navy}; font-weight: bold;"
        )
        self.plot_button.clicked.connect(self.plot_ensemble)
        plot_row.addWidget(self.plot_button)
        root.addLayout(plot_row)

        bottom_row = QtWidgets.QHBoxLayout()
        bottom_row.setSpacing(12)
        self.rebuild_checkbox = QtWidgets.QCheckBox("Rebuild existing (replace)")
        self.rebuild_checkbox.setStyleSheet(f"color: {white};")
        self.rebuild_checkbox.setToolTip(
            "Delete and rebuild the selected probes' ensembles, even for "
            "epochs that already have one"
        )
        self.rebuild_checkbox.toggled.connect(self._on_rebuild_toggled)
        bottom_row.addWidget(self.rebuild_checkbox)
        bottom_row.addStretch(1)
        reload_button = QtWidgets.QPushButton("Reload")
        reload_button.setStyleSheet(f"background-color: {white}; color: {navy};")
        reload_button.clicked.connect(lambda: self.with_wait(LOADING_MESSAGE, self.reload_probes))
        bottom_row.addWidget(reload_button)
        self.make_button = QtWidgets.QPushButton("Make Ensemble")
        self.make_button.setStyleSheet(
            f"background-color: {accent}; color: {navy}; font-weight: bold;"
        )
        self.make_button.clicked.connect(self.make_ensembles)
        bottom_row.addWidget(self.make_button)
        root.addLayout(bottom_row)

        self._sync_probe_list()
        self._sync_epoch_dropdown()
        self.make_button.setEnabled(self.make_enabled)
        self.figure.show()
        return self.figure

    def show(self) -> None:
        """Bring the window up, if there is one."""
        if self.figure is not None:
            self.figure.show()

    def close(self) -> None:
        """Close the window and every raster it opened."""
        import contextlib

        self.clear_wait()
        for figure in self.rasters:
            with contextlib.suppress(Exception):
                figure.clf()
        self.rasters.clear()
        if self.figure is not None:
            self.figure.close()

    # -- widget mirrors: each a no-op until the window exists -----------
    def _sync_probe_list(self) -> None:
        if self.probe_list is None:
            return
        blocked = self.probe_list.blockSignals(True)
        try:
            self.probe_list.clear()
            self.probe_list.addItems(self.items)
            self._sync_probe_list_selection()
        finally:
            self.probe_list.blockSignals(blocked)

    def _sync_probe_list_selection(self) -> None:
        if self.probe_list is None:
            return
        blocked = self.probe_list.blockSignals(True)
        try:
            self.probe_list.clearSelection()
            for row in self.selection:
                item = self.probe_list.item(row)
                if item is not None:
                    item.setSelected(True)
        finally:
            self.probe_list.blockSignals(blocked)

    def _sync_epoch_dropdown(self) -> None:
        if self.epoch_dropdown is None:
            return
        blocked = self.epoch_dropdown.blockSignals(True)
        try:
            self.epoch_dropdown.clear()
            self.epoch_dropdown.addItems(self.epoch_items)
            if self.epoch:
                self.epoch_dropdown.setCurrentText(self.epoch)
            self.epoch_dropdown.setEnabled(self.epoch_enabled)
        finally:
            self.epoch_dropdown.blockSignals(blocked)
        if self.plot_button is not None:
            self.plot_button.setEnabled(self.plot_enabled)

    # -- widget events -------------------------------------------------
    def _on_selection_changed(self) -> None:
        self.selection = sorted(
            self.probe_list.row(item) for item in self.probe_list.selectedItems()
        )
        self.on_selection_changed()

    def _on_epoch_changed(self, text: str) -> None:
        if self.epoch_enabled and text in self.epoch_items:
            self.epoch = text

    def _on_rebuild_toggled(self, checked: bool) -> None:
        self.rebuild = bool(checked)

    # -- dialogs -------------------------------------------------------
    def _progress(self, message: str, *, maximum: int = 0) -> Any:
        """A progress dialog, or None when there is no window to own it.

        ``maximum`` 0 means indeterminate, which is Qt's convention and
        MATLAB's ``'Indeterminate','on'``.
        """
        if self.figure is None:
            return None
        from PySide6 import QtCore, QtWidgets

        dialog = QtWidgets.QProgressDialog(message, "", 0, int(maximum), self.figure)
        dialog.setWindowTitle("Please wait")
        dialog.setCancelButton(None)  # neither language offers a cancel here
        dialog.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setValue(0)
        dialog.show()
        _process_events()
        return dialog

    @staticmethod
    def _advance(dialog: Any, message: str | None = None, *, value: int | None = None) -> None:
        """Update a progress dialog that may not exist."""
        if dialog is None:
            return
        if message is not None:
            dialog.setLabelText(message)
        if value is not None:
            dialog.setValue(int(value))
        _process_events()

    def alert(self, message: str, title: str, *, success: bool = False) -> Any:
        """Tell the user something. Non-blocking, as the navigator's alert is.

        Recorded in ``last_alert`` whether or not there is a window, so what
        the app says is checkable with no display -- and so a build that never
        ran cannot swallow an error message in silence.
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
        self._held.append(box)
        box.finished.connect(lambda _=0, b=box: self._held.remove(b) if b in self._held else None)
        return box

    def __repr__(self) -> str:
        return (
            f"ensembleMaker(probes={len(self.probes)}, " f"with_ensembles={len(self.ensemble_map)})"
        )


# ----------------------------------------------------------------------
# module helpers
# ----------------------------------------------------------------------
def _identifier(obj: Any) -> str:
    """OBJ's ndi id.

    ``id`` is a PROPERTY on elements and probes but a METHOD on sessions, so
    both shapes are accepted rather than a caller having to know which kind of
    object it is holding.
    """
    ident = getattr(obj, "id", None)
    if callable(ident):
        try:
            ident = ident()
        except Exception:  # noqa: BLE001 - an object that will not identify itself
            return ""
    return str(ident) if ident is not None else ""


def _epoch_id(entry: Any) -> str:
    """The epoch id of an epoch table entry, mapping or object."""
    if isinstance(entry, Mapping):
        return str(entry.get("epoch_id", "") or "")
    return str(getattr(entry, "epoch_id", "") or "")


def _dependency_ids(docs: Sequence[Any], name: str) -> list[str]:
    """The value of dependency NAME on each of DOCS that has one."""
    values = []
    for doc in docs:
        try:
            value = doc.dependency_value(name, error_if_not_found=False)
        except Exception:  # noqa: BLE001 - a document that cannot answer has no dependency
            value = None
        if value:
            values.append(str(value))
    return values


def _load_ensemble(session: Any, element_id: str) -> Any:
    """The ndi.element.ensemble with document id ELEMENT_ID, or None.

    The load form of the constructor, which restores the stored id and the
    underlying element -- see the module docstring on why
    ``ndi_document2ndi_object`` is not what is wanted here.
    """
    from ...element.ensemble import ndi_element_ensemble
    from ...query import ndi_query

    try:
        docs = session.database_search(ndi_query("base.id") == element_id)
        if not docs:
            return None
        return ndi_element_ensemble(session, docs[0])
    except Exception:  # noqa: BLE001 - one unloadable ensemble costs its own marker
        return None


def _unique_stable(values: Sequence[str]) -> list[str]:
    """VALUES with duplicates dropped and first-seen order kept.

    One ensemble has one map document PER EPOCH, so the ids collected from
    them repeat; MATLAB's ``unique`` sorts, and keeping discovery order here
    costs nothing since the result is a map.
    """
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _close(dialog: Any) -> None:
    """Close a dialog that may be None or already gone."""
    if dialog is None:
        return
    try:
        dialog.close()
    except Exception:  # noqa: BLE001 - already deleted
        pass


def _fixed_width_font() -> Any:
    """The system fixed-width font, as MATLAB's FixedWidthFontName listbox uses."""
    from PySide6 import QtGui

    return QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)


def _process_events() -> None:
    """Let a just-shown dialog paint itself before the work starts."""
    from PySide6 import QtWidgets

    app = QtWidgets.QApplication.instance()
    if app is not None:
        app.processEvents()
