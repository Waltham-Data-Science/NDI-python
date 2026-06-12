"""
ndi.app.spikesorter_gui - interactive spike-sorter (PyQt port).

A faithful PyQt/pyqtgraph reimplementation of the MATLAB interactive spike
sorter ``vlt.neuro.spikesorting.cluster_spikewaves_gui`` -- the editor NDI users
are familiar with. It presents the extracted spike waveforms as per-cluster
overlay plots (with zoomable, pannable axes) alongside a feature scatter, and
lets the user:

  * run an automatic clustering (KlustaKwik or KMeans) with a chosen number of
    clusters,
  * merge two clusters, move a cluster to the front, and lasso-select points in
    the feature view to split spikes into a new cluster,
  * assign each cluster a quality label (Unselected / Not usable / Multi-unit /
    Good / Excellent) and a present-from/present-to epoch range,
  * and finish (DONE) -- returning the per-spike ``clusterids`` and the
    ``clusterinfo`` array, or cancel.

All cluster-edit *logic* lives in the headless
:class:`ndi.app.spikesorter_clustermodel.ClusterModel`; this module is only the
Qt presentation + event wiring, so the curation semantics are unit-tested
without a display. The returned ``clusterids`` / ``clusterinfo`` are written to
the ``spike_clusters`` document in exactly the layout the automatic
:meth:`ndi.app.spikesorter.ndi_app_spikesorter.spike_sort` path produces.

The GUI dependencies (PyQt + pyqtgraph) are OPTIONAL -- install the ``[gui]``
extra (``pip install 'ndi[gui]'``). Importing this module never imports Qt;
:func:`cluster_spikewaves_gui` raises a clear error if the extra is missing.

MATLAB equivalent: vlt.neuro.spikesorting.cluster_spikewaves_gui
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .spikesorter_clustermodel import (
    QUALITY_LABELS,
    ClusterModel,
    points_in_polygon,
)


def gui_available() -> bool:
    """Return True if the optional GUI backend (PyQt + pyqtgraph) is importable."""
    try:
        import pyqtgraph  # noqa: F401
        from pyqtgraph.Qt import QtWidgets  # noqa: F401

        return True
    except Exception:
        return False


def _require_gui() -> Any:
    """Import the Qt backend or raise a clear, actionable ImportError."""
    try:
        import pyqtgraph as pg
        from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

        return pg, QtWidgets, QtCore, QtGui
    except Exception as exc:  # pragma: no cover - exercised only without the dep
        raise ImportError(
            "The interactive spike sorter requires the optional GUI dependencies "
            "(PyQt + pyqtgraph). Install them with:  pip install 'ndi[gui]'  (or "
            "directly:  pip install PyQt6 pyqtgraph). Use the automatic sorting "
            "path (graphical_mode=0) if a display is not available."
        ) from exc


# Module-level strong reference to the QApplication. PyQt will garbage-collect a
# QApplication that has no live Python reference and delete the underlying C++
# object -- after which creating any QWidget aborts the process with "Must
# construct a QApplication before a QWidget". Holding the instance here keeps it
# alive for the lifetime of the process.
_QAPP: Any = None


def _ensure_qapp() -> Any:
    """Return the singleton QApplication, creating one if necessary.

    The instance is cached in a module global so it is never garbage-collected
    out from under live widgets (a long sorting session can trigger a GC that
    would otherwise destroy an unreferenced QApplication and crash).
    """
    global _QAPP
    _pg, QtWidgets, _QtCore, _QtGui = _require_gui()
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    _QAPP = app
    return app


def _pen_for_color(pg: Any, color: tuple[float, float, float], width: int = 1) -> Any:
    r, g, b = (int(round(255 * c)) for c in color)
    return pg.mkPen((r, g, b), width=width)


def _brush_for_color(pg: Any, color: tuple[float, float, float]) -> Any:
    r, g, b = (int(round(255 * c)) for c in color)
    return pg.mkBrush((r, g, b))


def build_window(model: ClusterModel, **kwargs: Any) -> Any:
    """Construct (but do not run) the spike-sorter window for ``model``.

    Importable + constructible under ``QT_QPA_PLATFORM=offscreen`` for testing.
    """
    _ensure_qapp()
    return _window_class()(model, **kwargs)


def cluster_spikewaves_gui(
    waves: np.ndarray,
    waveparameters: dict[str, Any] | None = None,
    *,
    clusterids: np.ndarray | None = None,
    clusterinfo: list[dict[str, Any]] | None = None,
    wavetimes: np.ndarray | None = None,
    epoch_start_samples: list[int] | None = None,
    epoch_names: list[str] | None = None,
    wavesamples: np.ndarray | None = None,
    spikewaves2NpointfeatureSampleList: list[int] | None = None,  # noqa: N803 (MATLAB name)
    spikewaves2pcaRange: list[int] | None = None,  # noqa: N803 (MATLAB name)
    force_quality_assessment: bool = True,
    enable_cluster_editing: bool = True,
    ask_before_done: bool = True,
    figure_name: str = "Cluster spikewaves",
    cluster_right_away: bool = False,
) -> tuple[np.ndarray | None, list[dict[str, Any]] | None]:
    """Open the interactive spike sorter and return the curated clustering.

    Python counterpart of ``vlt.neuro.spikesorting.cluster_spikewaves_gui``.
    Blocks (modal) until the user clicks DONE or Cancel.

    Args:
        waves: ``NumSamples x NumChannels x NumSpikes`` waveform array.
        waveparameters: extraction waveform parameters (unused for display;
            accepted for MATLAB call-signature parity).
        clusterids: optional preliminary per-spike cluster assignment.
        clusterinfo: optional preliminary per-cluster info.
        wavetimes: optional per-spike times.
        epoch_start_samples / epoch_names: epoch partition (1-based spike-index
            starts + epoch ids).
        wavesamples: optional sample-time axis (``waveform_sample_times``).
        spikewaves2NpointfeatureSampleList: 1-based sample offsets for the
            2-point feature (defaults to half-way + 5/6-of-the-way).
        spikewaves2pcaRange: 1-based ``[start, stop]`` PCA sample range.
        force_quality_assessment: if True, DONE is refused until every cluster
            has a non-``Unselected`` quality label.
        enable_cluster_editing: if False, the clustering/merge controls are
            disabled (review-only).
        ask_before_done: if True, confirm before finishing.
        figure_name: window title.
        cluster_right_away: if True, run the default clustering on open.

    Returns:
        ``(clusterids, clusterinfo)`` on DONE (``clusterids`` is a length-NumSpikes
        array, ``NaN`` for unclassified spikes); ``(None, None)`` on Cancel.

    Raises:
        ImportError: if the optional GUI dependencies are not installed.
    """
    _pg, QtWidgets, _QtCore, _QtGui = _require_gui()
    _ensure_qapp()

    model = ClusterModel(
        waves,
        clusterids=clusterids,
        clusterinfo=clusterinfo,
        wavetimes=wavetimes,
        epoch_start_samples=epoch_start_samples,
        epoch_names=epoch_names,
        wavesamples=wavesamples,
        npoint_samplelist=spikewaves2NpointfeatureSampleList,
        pca_range=spikewaves2pcaRange,
    )

    window = _window_class()(
        model,
        force_quality_assessment=force_quality_assessment,
        enable_cluster_editing=enable_cluster_editing,
        ask_before_done=ask_before_done,
        figure_name=figure_name,
    )
    if cluster_right_away:
        window.on_cluster_all()
    window.setModal(True)
    window.show()
    window.exec()

    if window.success:
        return window.result_clusterids, window.result_clusterinfo
    return None, None


def _make_window_base() -> Any:
    """Return the QDialog subclass for the window (built lazily so importing this
    module does not import Qt)."""
    pg, QtWidgets, QtCore, QtGui = _require_gui()

    class _ClusterSpikewavesWindow(QtWidgets.QDialog):
        """The spike-sorter dialog. See :func:`cluster_spikewaves_gui`."""

        def __init__(
            self,
            model: ClusterModel,
            *,
            force_quality_assessment: bool = True,
            enable_cluster_editing: bool = True,
            ask_before_done: bool = True,
            figure_name: str = "Cluster spikewaves",
        ):
            super().__init__()
            self.model = model
            self.force_quality_assessment = force_quality_assessment
            self.enable_cluster_editing = enable_cluster_editing
            self.ask_before_done = ask_before_done
            self.success = False
            self.result_clusterids: np.ndarray | None = None
            self.result_clusterinfo: list[dict[str, Any]] | None = None

            self._feature_kind = "pca3"
            self._marker_size = 6
            self._random_subset = True
            self._random_subset_size = 200
            self._dim_x = 0
            self._dim_y = 1
            self._pending_action: str | None = None  # lasso mode
            self._lasso_points: list[tuple[float, float]] = []
            self._lasso_curve = None
            self._suspend_signals = False

            self.setWindowTitle(figure_name)
            self.resize(1100, 760)
            self._build_ui()
            self.model.compute_features(self._feature_kind)
            self._refresh_cluster_menus()
            self.redraw()

        # -- construction ------------------------------------------------

        def _build_ui(self) -> None:
            outer = QtWidgets.QVBoxLayout(self)
            controls = self._build_controls()
            outer.addLayout(controls)

            splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
            # feature scatter (left)
            self.feature_plot = pg.PlotWidget()
            self.feature_plot.setBackground("w")
            self.feature_plot.setLabel("bottom", "feature dim")
            self.feature_plot.setLabel("left", "feature dim")
            self.feature_scatter = pg.ScatterPlotItem()
            self.feature_plot.addItem(self.feature_scatter)
            self.feature_plot.scene().sigMouseClicked.connect(self._on_scene_clicked)
            self.feature_plot.scene().sigMouseMoved.connect(self._on_scene_moved)
            splitter.addWidget(self.feature_plot)

            # waveform overlays (right), scrollable grid
            self.wave_layout = pg.GraphicsLayoutWidget()
            self.wave_layout.setBackground("w")
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(self.wave_layout)
            splitter.addWidget(scroll)
            splitter.setSizes([520, 580])
            outer.addWidget(splitter, stretch=1)

        def _build_controls(self) -> Any:
            grid = QtWidgets.QGridLayout()
            row = 0

            self.done_btn = QtWidgets.QPushButton("DONE")
            self.done_btn.clicked.connect(self.on_done)
            self.cancel_btn = QtWidgets.QPushButton("Cancel")
            self.cancel_btn.clicked.connect(self.on_cancel)
            self.cluster_all_btn = QtWidgets.QPushButton("Cluster all")
            self.cluster_all_btn.clicked.connect(self.on_cluster_all)
            self.reset_zoom_btn = QtWidgets.QPushButton("Reset zoom")
            self.reset_zoom_btn.clicked.connect(self.on_autorange)
            grid.addWidget(self.done_btn, row, 0)
            grid.addWidget(self.cancel_btn, row, 1)
            grid.addWidget(self.cluster_all_btn, row, 2)
            grid.addWidget(self.reset_zoom_btn, row, 3)
            row += 1

            # feature selection
            grid.addWidget(QtWidgets.QLabel("Feature:"), row, 0)
            self.feature_menu = QtWidgets.QComboBox()
            self.feature_menu.addItems(["2points", "pca3"])
            self.feature_menu.setCurrentText("pca3")
            self.feature_menu.currentTextChanged.connect(self.on_feature_changed)
            grid.addWidget(self.feature_menu, row, 1)
            self.feature_edit = QtWidgets.QLineEdit()
            self.feature_edit.editingFinished.connect(self.on_feature_param_changed)
            grid.addWidget(self.feature_edit, row, 2)
            grid.addWidget(QtWidgets.QLabel("scatter dims X,Y:"), row, 3)
            self.dim_x_spin = QtWidgets.QSpinBox()
            self.dim_y_spin = QtWidgets.QSpinBox()
            self.dim_x_spin.valueChanged.connect(self.on_dim_changed)
            self.dim_y_spin.valueChanged.connect(self.on_dim_changed)
            grid.addWidget(self.dim_x_spin, row, 4)
            grid.addWidget(self.dim_y_spin, row, 5)
            row += 1

            # algorithm
            grid.addWidget(QtWidgets.QLabel("Algorithm:"), row, 0)
            self.algorithm_menu = QtWidgets.QComboBox()
            self.algorithm_menu.addItems(["KlustaKwik", "KMeans"])
            self.algorithm_menu.currentTextChanged.connect(self.on_algorithm_changed)
            grid.addWidget(self.algorithm_menu, row, 1)
            self.cluster_size_label = QtWidgets.QLabel("# clusters [min max]")
            grid.addWidget(self.cluster_size_label, row, 2)
            self.cluster_size_edit = QtWidgets.QLineEdit("[2 4]")
            grid.addWidget(self.cluster_size_edit, row, 3)
            row += 1

            # cluster actions: merge
            grid.addWidget(QtWidgets.QLabel("Cluster actions:"), row, 0)
            self.merge1_menu = QtWidgets.QComboBox()
            self.merge1_menu.currentTextChanged.connect(self.on_merge1_changed)
            grid.addWidget(self.merge1_menu, row, 1)
            grid.addWidget(QtWidgets.QLabel("merge with"), row, 2)
            self.merge2_menu = QtWidgets.QComboBox()
            grid.addWidget(self.merge2_menu, row, 3)
            self.merge_btn = QtWidgets.QPushButton("Merge")
            self.merge_btn.clicked.connect(self.on_merge)
            grid.addWidget(self.merge_btn, row, 4)
            self.other_action_menu = QtWidgets.QComboBox()
            self.other_action_menu.addItems(
                [
                    "Other actions",
                    "Move to front",
                    "Select spikes to add",
                    "Select spikes to exclude (split)",
                    "Cancel selection",
                ]
            )
            self.other_action_menu.activated.connect(self.on_other_action)
            grid.addWidget(self.other_action_menu, row, 5)
            row += 1

            # cluster info: quality
            grid.addWidget(QtWidgets.QLabel("Cluster info: selected is"), row, 0)
            self.quality_menu = QtWidgets.QComboBox()
            self.quality_menu.addItems(QUALITY_LABELS)
            self.quality_menu.currentTextChanged.connect(self.on_quality_changed)
            grid.addWidget(self.quality_menu, row, 1)

            # epochs (only meaningful with >1 epoch)
            self.epoch_start_label = QtWidgets.QLabel("present from")
            grid.addWidget(self.epoch_start_label, row, 2)
            self.epoch_start_menu = QtWidgets.QComboBox()
            self.epoch_start_menu.addItems(self.model.epoch_names)
            self.epoch_start_menu.currentTextChanged.connect(self.on_epoch_changed)
            grid.addWidget(self.epoch_start_menu, row, 3)
            self.epoch_stop_label = QtWidgets.QLabel("to")
            grid.addWidget(self.epoch_stop_label, row, 4)
            self.epoch_stop_menu = QtWidgets.QComboBox()
            self.epoch_stop_menu.addItems(self.model.epoch_names)
            if self.model.epoch_names:
                self.epoch_stop_menu.setCurrentIndex(len(self.model.epoch_names) - 1)
            self.epoch_stop_menu.currentTextChanged.connect(self.on_epoch_changed)
            grid.addWidget(self.epoch_stop_menu, row, 5)
            row += 1

            # display options
            grid.addWidget(QtWidgets.QLabel("MarkerSize:"), row, 0)
            self.marker_size_spin = QtWidgets.QSpinBox()
            self.marker_size_spin.setRange(1, 40)
            self.marker_size_spin.setValue(self._marker_size)
            self.marker_size_spin.valueChanged.connect(self.on_marker_size_changed)
            grid.addWidget(self.marker_size_spin, row, 1)
            self.subset_cb = QtWidgets.QCheckBox("Show subset of spikes")
            self.subset_cb.setChecked(self._random_subset)
            self.subset_cb.stateChanged.connect(self.on_subset_changed)
            grid.addWidget(self.subset_cb, row, 2)
            grid.addWidget(QtWidgets.QLabel("Subset size:"), row, 3)
            self.subset_size_spin = QtWidgets.QSpinBox()
            self.subset_size_spin.setRange(1, 100000)
            self.subset_size_spin.setValue(self._random_subset_size)
            self.subset_size_spin.valueChanged.connect(self.on_subset_changed)
            grid.addWidget(self.subset_size_spin, row, 4)
            self.status_label = QtWidgets.QLabel("")
            grid.addWidget(self.status_label, row, 5)

            self._sync_feature_edit()
            self._update_dim_spin_ranges()
            self._apply_editing_enabled()
            self._apply_epoch_visibility()
            return grid

        # -- enable/disable, visibility ---------------------------------

        def _apply_editing_enabled(self) -> None:
            for w in (
                self.cluster_all_btn,
                self.algorithm_menu,
                self.cluster_size_edit,
                self.merge1_menu,
                self.merge2_menu,
                self.merge_btn,
                self.other_action_menu,
            ):
                w.setEnabled(self.enable_cluster_editing)

        def _apply_epoch_visibility(self) -> None:
            show = len(self.model.epoch_names) > 1
            for w in (
                self.epoch_start_label,
                self.epoch_start_menu,
                self.epoch_stop_label,
                self.epoch_stop_menu,
            ):
                w.setVisible(show)

        def _update_dim_spin_ranges(self) -> None:
            nfeat = 0 if self.model.features is None else self.model.features.shape[1]
            self._suspend_signals = True
            for spin in (self.dim_x_spin, self.dim_y_spin):
                spin.setRange(1, max(1, nfeat))
            self.dim_x_spin.setValue(min(self._dim_x + 1, max(1, nfeat)))
            self.dim_y_spin.setValue(min(self._dim_y + 1, max(1, nfeat)))
            self._suspend_signals = False

        def _sync_feature_edit(self) -> None:
            if self._feature_kind == "2points":
                self.feature_edit.setText(str(self.model.npoint_samplelist))
                self.cluster_size_label.setText("# clusters [min max]")
            else:
                self.feature_edit.setText(str(self.model.pca_range))

        # -- menu population --------------------------------------------

        def _cluster_numbers(self) -> list[str]:
            out: list[str] = []
            for c in self.model.unique_clusters():
                out.append("NaN" if np.isnan(c) else str(int(c)))
            return out

        def _refresh_cluster_menus(self) -> None:
            self._suspend_signals = True
            numbers = self._cluster_numbers()
            cur1 = self.merge1_menu.currentText()
            self.merge1_menu.clear()
            self.merge1_menu.addItems(numbers)
            if cur1 in numbers:
                self.merge1_menu.setCurrentText(cur1)
            self._refresh_merge2()
            self._sync_quality_to_selection()
            self._sync_epoch_to_selection()
            self._suspend_signals = False

        def _refresh_merge2(self) -> None:
            numbers = self._cluster_numbers()
            sel = self.merge1_menu.currentText()
            others = [n for n in numbers if n != sel]
            self.merge2_menu.clear()
            self.merge2_menu.addItems(others if others else [""])

        def _selected_number(self) -> str | None:
            txt = self.merge1_menu.currentText()
            return txt or None

        def _sync_quality_to_selection(self) -> None:
            sel = self._selected_number()
            if sel is None:
                return
            loc = self.model._info_index_for_number(sel)
            if loc is None:
                return
            label = self.model.clusterinfo[loc].get("qualitylabel", "Unselected")
            if label in QUALITY_LABELS:
                self.quality_menu.setCurrentText(label)

        def _sync_epoch_to_selection(self) -> None:
            sel = self._selected_number()
            if sel is None:
                return
            loc = self.model._info_index_for_number(sel)
            if loc is None:
                return
            ci = self.model.clusterinfo[loc]
            start = ci.get("EpochStart", self.model.epoch_names[0])
            stop = ci.get("EpochStop", self.model.epoch_names[-1])
            if start in self.model.epoch_names:
                self.epoch_start_menu.setCurrentText(start)
            if stop in self.model.epoch_names:
                self.epoch_stop_menu.setCurrentText(stop)

        # -- event handlers ---------------------------------------------

        def on_feature_changed(self, kind: str) -> None:
            self._feature_kind = kind
            self.model.compute_features(kind)
            self._sync_feature_edit()
            self._update_dim_spin_ranges()
            self.redraw()
            self.feature_plot.autoRange()  # the projection changed -> re-fit

        def on_feature_param_changed(self) -> None:
            text = self.feature_edit.text().strip()
            try:
                values = [
                    int(v) for v in text.replace("[", "").replace("]", "").replace(",", " ").split()
                ]
            except ValueError:
                self.status_label.setText("bad feature parameter")
                self._sync_feature_edit()
                return
            if self._feature_kind == "2points" and values:
                self.model.npoint_samplelist = values
            elif self._feature_kind == "pca3" and len(values) >= 2:
                self.model.pca_range = [values[0], values[1]]
            self.model._clamp_feature_params()
            self.model.compute_features(self._feature_kind)
            self._update_dim_spin_ranges()
            self.redraw()
            self.feature_plot.autoRange()  # feature params changed -> re-fit

        def on_dim_changed(self, _value: int = 0) -> None:
            if self._suspend_signals:
                return
            self._dim_x = max(0, self.dim_x_spin.value() - 1)
            self._dim_y = max(0, self.dim_y_spin.value() - 1)
            self.redraw()
            self.feature_plot.autoRange()  # different scatter dims -> re-fit

        def on_algorithm_changed(self, name: str) -> None:
            if name == "KlustaKwik":
                self.cluster_size_label.setText("# clusters [min max]")
                self.cluster_size_edit.setText("[2 4]")
            else:
                self.cluster_size_label.setText("# clusters:")
                self.cluster_size_edit.setText("5")

        def on_cluster_all(self) -> None:
            algorithm = self.algorithm_menu.currentText()
            text = self.cluster_size_edit.text().strip()
            try:
                spec = [
                    int(v) for v in text.replace("[", "").replace("]", "").replace(",", " ").split()
                ]
            except ValueError:
                self.status_label.setText("bad # clusters")
                return
            if not spec:
                self.status_label.setText("bad # clusters")
                return
            self.status_label.setText(f"clustering ({algorithm})...")
            if QtWidgets.QApplication.instance() is not None:
                QtWidgets.QApplication.processEvents()
            try:
                self.model.cluster_all(
                    algorithm, spec if len(spec) > 1 else spec[0], feature_kind=self._feature_kind
                )
            except ImportError as exc:
                self.status_label.setText(str(exc).splitlines()[0])
                return
            self.status_label.setText(f"{len(self.model.clusterinfo)} clusters")
            self._refresh_cluster_menus()
            self.redraw()

        def on_merge1_changed(self, _text: str = "") -> None:
            if self._suspend_signals:
                return
            self._refresh_merge2()
            self._sync_quality_to_selection()
            self._sync_epoch_to_selection()

        def on_merge(self) -> None:
            a = self.merge1_menu.currentText()
            b = self.merge2_menu.currentText()
            if not a or not b:
                self.status_label.setText("select two clusters to merge")
                return
            try:
                self.model.merge(a, b)
            except ValueError as exc:
                self.status_label.setText(str(exc))
                return
            self._refresh_cluster_menus()
            self.redraw()

        def on_move_to_front(self) -> None:
            sel = self._selected_number()
            if sel is None:
                return
            self.model.move_to_front(sel)
            self._refresh_cluster_menus()
            self.redraw()

        def on_other_action(self, index: int = 0) -> None:
            choice = self.other_action_menu.currentText()
            self.other_action_menu.setCurrentIndex(0)
            if choice == "Move to front":
                self.on_move_to_front()
            elif choice == "Select spikes to add":
                self._start_lasso("add")
            elif choice.startswith("Select spikes to exclude"):
                self._start_lasso("split")
            elif choice == "Cancel selection":
                self._cancel_lasso()

        def on_quality_changed(self, label: str) -> None:
            if self._suspend_signals:
                return
            sel = self._selected_number()
            if sel is None:
                return
            try:
                self.model.set_quality(sel, label)
            except ValueError as exc:
                self.status_label.setText(str(exc))
                return
            self._redraw_labels_only()

        def on_epoch_changed(self, _text: str = "") -> None:
            if self._suspend_signals:
                return
            sel = self._selected_number()
            if sel is None:
                return
            start = self.epoch_start_menu.currentText()
            stop = self.epoch_stop_menu.currentText()
            if start in self.model.epoch_names and stop in self.model.epoch_names:
                self.model.set_epochs(sel, start, stop)
                self.redraw()

        def on_marker_size_changed(self, value: int) -> None:
            self._marker_size = int(value)
            self._draw_features()

        def on_subset_changed(self, _value: int = 0) -> None:
            self._random_subset = self.subset_cb.isChecked()
            self._random_subset_size = self.subset_size_spin.value()
            self._draw_spikes()

        # -- lasso selection --------------------------------------------

        def _start_lasso(self, action: str) -> None:
            self._pending_action = action
            self._lasso_points = []
            self.status_label.setText(
                f"lasso: click to add vertices in the feature view, "
                f"double-click to apply ({action}); Esc/Cancel selection to abort"
            )

        def _cancel_lasso(self) -> None:
            self._pending_action = None
            self._lasso_points = []
            if self._lasso_curve is not None:
                self.feature_plot.removeItem(self._lasso_curve)
                self._lasso_curve = None
            self.status_label.setText("selection cancelled")

        def keyPressEvent(self, event: Any) -> None:  # noqa: N802 (Qt override)
            # Escape aborts an in-progress lasso (not the whole dialog); otherwise
            # fall through to QDialog's default (reject == Cancel).
            if event.key() == QtCore.Qt.Key.Key_Escape and self._pending_action is not None:
                self._cancel_lasso()
                event.accept()
                return
            super().keyPressEvent(event)

        def _on_scene_clicked(self, event: Any) -> None:
            if self._pending_action is None:
                return
            vb = self.feature_plot.getPlotItem().vb
            point = vb.mapSceneToView(event.scenePos())
            self._lasso_points.append((float(point.x()), float(point.y())))
            self._update_lasso_curve()
            try:
                double = event.double()
            except Exception:
                double = False
            if double and len(self._lasso_points) >= 3:
                self.apply_selection(np.asarray(self._lasso_points), self._pending_action)
                self._cancel_lasso()

        def _on_scene_moved(self, _pos: Any) -> None:
            return

        def _update_lasso_curve(self) -> None:
            if not self._lasso_points:
                return
            pts = np.asarray(self._lasso_points + self._lasso_points[:1])
            if self._lasso_curve is None:
                self._lasso_curve = pg.PlotCurveItem(pen=pg.mkPen((0, 0, 0), width=1))
                self.feature_plot.addItem(self._lasso_curve)
            self._lasso_curve.setData(pts[:, 0], pts[:, 1])

        def apply_selection(self, polygon_xy: np.ndarray, action: str) -> int:
            """Apply a lasso selection (add-to-current or split-out).

            Returns the number of spikes affected. Operates only on the spikes
            currently visible in the feature scatter (the same projection the
            user sees), matching the MATLAB select-spikes commands.
            """
            feats = self.model.features
            if feats is None or feats.shape[1] == 0:
                return 0
            visible = self.model.visible_indices()
            if visible.size == 0:
                return 0
            proj = feats[np.ix_(visible, [self._dim_x, min(self._dim_y, feats.shape[1] - 1)])]
            inside = points_in_polygon(proj, polygon_xy)
            chosen = visible[inside]
            if chosen.size == 0:
                self.status_label.setText("no spikes inside selection")
                return 0
            sel = self._selected_number()
            if action == "add" and sel is not None and sel != "NaN":
                self.model.clusterids[chosen] = float(int(sel))
                self.model.make_clusters_1_to_n()
            elif action == "split" and sel is not None:
                # restrict to spikes that belong to the selected cluster, then split.
                belong = (
                    chosen[self.model.clusterids[chosen] == float(int(sel))]
                    if sel != "NaN"
                    else chosen
                )
                if belong.size == 0:
                    self.status_label.setText("no spikes of the selected cluster inside selection")
                    return 0
                self.model.split_cluster(sel, belong)
            else:
                return 0
            self._refresh_cluster_menus()
            self.redraw()
            self.status_label.setText(f"{chosen.size} spikes selected")
            return int(chosen.size)

        # -- drawing ----------------------------------------------------

        def on_autorange(self) -> None:
            """Reset every view to fit its data (the 'Reset zoom' button)."""
            self.feature_plot.autoRange()
            if getattr(self, "_spike_plots", None):
                # waveform panels share one X axis (link), so ranging the first
                # ranges them all; Y auto-fits per panel.
                self._spike_plots[0].enableAutoRange(axis="x")
                self._spike_plots[0].autoRange()

        def redraw(self) -> None:
            self._draw_features()
            self._draw_spikes()
            self._refresh_merge2()

        def _visible_present(self, number: str) -> np.ndarray:
            inds = self.model._indices_of_number(number)
            inds = self.model.visible_indices(indices=inds)
            return self.model.present_indices(number, inds)

        def _draw_features(self) -> None:
            feats = self.model.features
            self.feature_scatter.clear()
            if feats is None or feats.shape[1] == 0 or self.model.n_spikes == 0:
                return
            dx = min(self._dim_x, feats.shape[1] - 1)
            dy = min(self._dim_y, feats.shape[1] - 1)
            spots = []
            for pos, number in enumerate(self._cluster_numbers(), start=1):
                is_nan = number == "NaN"
                color = self.model.color_for_position(pos, is_nan=is_nan)
                inds = self._visible_present(number)
                if inds.size == 0:
                    continue
                brush = _brush_for_color(pg, color)
                for j in inds:
                    spots.append(
                        {
                            "pos": (feats[j, dx], feats[j, dy]),
                            "brush": brush,
                            "size": self._marker_size,
                            "pen": None,
                        }
                    )
            self.feature_scatter.setData(spots)
            self.feature_plot.setLabel("bottom", f"feature dim {dx + 1}")
            self.feature_plot.setLabel("left", f"feature dim {dy + 1}")

        def _build_spike_panels(self, n: int) -> None:
            """(Re)create the n waveform panels. Called only when the panel count
            changes, so user zoom/pan persists across ordinary content redraws.

            All panels share ONE X axis (setXLink) so horizontal zoom/pan is
            consistent across every cluster (mirroring MATLAB's shared spike
            axis); the mouse is constrained to X and Y auto-fits the visible
            data, so the only zoom gesture acts on the shared time axis and can
            never desynchronise the panels.
            """
            self.wave_layout.clear()
            self._spike_plots = []
            ncols = 2
            for pos in range(1, n + 1):
                r, col = divmod(pos - 1, ncols)
                plt = self.wave_layout.addPlot(row=r, col=col)
                plt.setMenuEnabled(False)
                plt.showAxis("bottom", False)
                plt.showAxis("left", False)
                plt.setMouseEnabled(x=True, y=False)  # zoom only the (shared) time axis
                plt.enableAutoRange(axis="y")
                plt.setAutoVisible(y=True)  # Y re-fits to the visible X window
                vb = plt.getViewBox()
                vb.setDefaultPadding(0.02)
                if self._spike_plots:
                    plt.setXLink(self._spike_plots[0])  # all panels pan/zoom together in X
                self._spike_plots.append(plt)
            self._n_panels = n

        def _draw_spikes(self) -> None:
            numbers = self._cluster_numbers()
            if not numbers:
                self.wave_layout.clear()
                self._spike_plots = []
                self._n_panels = 0
                return
            n = len(numbers)
            if getattr(self, "_n_panels", None) != n or not getattr(self, "_spike_plots", None):
                self._build_spike_panels(n)
            waves = self.model.waves
            s, c, _ = waves.shape
            x = np.arange(s * c)
            xb = np.append(x.astype(float), np.nan)  # one spike + a NaN break
            sep_pen = pg.mkPen((225, 225, 225), width=1)
            rng = np.random.default_rng(0)
            for pos, number in enumerate(numbers, start=1):
                plt = self._spike_plots[pos - 1]
                plt.clear()  # remove data items but KEEP the ViewBox range (zoom persists)
                is_nan = number == "NaN"
                color = self.model.color_for_position(pos, is_nan=is_nan)
                inds = self._visible_present(number)
                label = (
                    self.model.clusterinfo[pos - 1].get("qualitylabel", "Unselected")
                    if pos - 1 < len(self.model.clusterinfo)
                    else ""
                )
                plt.setTitle(f"{number}: N={inds.size}, Q={label}", size="8pt")
                # faint separators between the concatenated channels
                for ch in range(1, c):
                    plt.addLine(x=ch * s, pen=sep_pen)
                if inds.size == 0:
                    continue
                draw_inds = inds
                if self._random_subset and inds.size > self._random_subset_size:
                    draw_inds = inds[rng.permutation(inds.size)[: self._random_subset_size]]
                flat = waves[:, :, draw_inds].reshape(s * c, draw_inds.size, order="F")
                # ONE NaN-separated polyline for the whole panel (connect='finite')
                # so the scene holds ~1 item per panel instead of hundreds -- this
                # keeps zoom/pan smooth even with a couple hundred overlaid spikes.
                m = flat.shape[1]
                xs = np.tile(xb, m)
                ys = np.empty((s * c + 1) * m, dtype=float)
                for k in range(m):
                    ys[k * (s * c + 1) : (k + 1) * (s * c + 1) - 1] = flat[:, k]
                    ys[(k + 1) * (s * c + 1) - 1] = np.nan
                plt.plot(
                    xs,
                    ys,
                    pen=_pen_for_color(pg, color, width=1),
                    connect="finite",
                    antialias=False,
                )
                # bold mean waveform (the cluster template) on top
                mean_flat = np.nanmean(waves[:, :, inds], axis=2).reshape(s * c, order="F")
                plt.plot(x, mean_flat, pen=pg.mkPen((0, 0, 0), width=2))

        def _redraw_labels_only(self) -> None:
            # cheap update of the per-cluster titles (quality changed).
            numbers = self._cluster_numbers()
            for pos, number in enumerate(numbers, start=1):
                if pos - 1 >= len(getattr(self, "_spike_plots", [])):
                    break
                inds = self._visible_present(number)
                label = (
                    self.model.clusterinfo[pos - 1].get("qualitylabel", "Unselected")
                    if pos - 1 < len(self.model.clusterinfo)
                    else ""
                )
                self._spike_plots[pos - 1].setTitle(f"{number}: N={inds.size}, Q={label}")

        # -- finish -----------------------------------------------------

        def on_done(self) -> None:
            if self.force_quality_assessment and not self.model.all_quality_assigned():
                self.status_label.setText(
                    "Assign a quality label to every cluster before finishing."
                )
                self._maybe_message(
                    "Assign quality label",
                    "Please make sure a quality label has been assigned to all clusters.",
                )
                return
            if self.ask_before_done and not self._confirm_done():
                return
            self.model.finalize()
            self.result_clusterids = self.model.clusterids.copy()
            self.result_clusterinfo = [dict(c) for c in self.model.clusterinfo]
            self.success = True
            self.accept()

        def on_cancel(self) -> None:
            self.success = False
            self.reject()

        def _confirm_done(self) -> bool:
            if QtWidgets.QApplication.instance() is None:  # pragma: no cover
                return True
            box = QtWidgets.QMessageBox(self)
            box.setWindowTitle("Confirm Done")
            box.setText("Are you sure you are done?")
            box.setStandardButtons(
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No
            )
            # In headless/offscreen test runs there is no user; default to Yes only
            # when explicitly driven. Here we show modally.
            return box.exec() == QtWidgets.QMessageBox.StandardButton.Yes

        def _maybe_message(self, title: str, text: str) -> None:
            box = QtWidgets.QMessageBox(self)
            box.setWindowTitle(title)
            box.setText(text)
            box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
            box.exec()

    return _ClusterSpikewavesWindow


# The window class is built lazily (it subclasses QDialog, which requires Qt).
_WINDOW_CLASS: Any = None


def _window_class() -> Any:
    """Build (once) and return the QDialog window subclass."""
    global _WINDOW_CLASS
    if _WINDOW_CLASS is None:
        _WINDOW_CLASS = _make_window_base()
    return _WINDOW_CLASS


def __getattr__(name: str) -> Any:  # PEP 562 module-level lazy attribute
    if name == "ClusterSpikewavesWindow":
        return _window_class()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
