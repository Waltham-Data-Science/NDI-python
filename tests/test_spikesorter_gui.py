"""
Offscreen tests for ndi.app.spikesorter_gui (the interactive spike-sorter GUI).

These build the real PyQt/pyqtgraph window under QT_QPA_PLATFORM=offscreen and
drive its event handlers directly (no pixel clicking), asserting that each
control routes to the headless ClusterModel correctly and that drawing does not
raise. They skip cleanly when the optional GUI dependencies (PyQt + pyqtgraph)
are absent. The curation *math* is covered separately and headlessly in
tests/test_spikesorter_clustermodel.py.

MATLAB equivalent: vlt.neuro.spikesorting.cluster_spikewaves_gui (interactive).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("pyqtgraph")
pytest.importorskip("pyqtgraph.Qt")

from ndi.app.spikesorter_clustermodel import ClusterModel  # noqa: E402
from ndi.app.spikesorter_gui import build_window, gui_available  # noqa: E402

pytestmark = pytest.mark.skipif(
    not gui_available(), reason="GUI deps (PyQt/pyqtgraph) not installed"
)

S0, S1 = -10, 10
NCHAN = 2


def _archetype(label: int) -> np.ndarray:
    s = np.arange(S0, S1 + 1)
    bump = np.exp(-(s**2) / 8.0)
    return {
        1: np.stack([-8.0 * bump, -1.0 * bump], axis=1),
        2: np.stack([-1.0 * bump, -8.0 * bump], axis=1),
        3: np.stack([-8.0 * bump, 8.0 * bump], axis=1),
    }[label]


def _model(labels=None, two_epochs=True, assigned=True):
    labels = labels or [1, 2, 3] * 8
    rng = np.random.default_rng(0)
    n = len(labels)
    w = np.zeros((S1 - S0 + 1, NCHAN, n))
    for i, lab in enumerate(labels):
        w[:, :, i] = _archetype(lab) + 0.1 * rng.standard_normal((S1 - S0 + 1, NCHAN))
    kwargs = {}
    if two_epochs:
        kwargs = {"epoch_start_samples": [1, n // 2 + 1], "epoch_names": ["ep0", "ep1"]}
    m = ClusterModel(w, clusterids=(np.array(labels, dtype=float) if assigned else None), **kwargs)
    if assigned:
        m.init_cluster_info(rebuild=True)
        m.make_clusters_1_to_n()
    return m, labels


@pytest.fixture
def win(qtbot):
    m, _labels = _model()
    w = build_window(m, ask_before_done=False)
    qtbot.addWidget(w)
    return w


# ---------------------------------------------------------------------------
# construction + drawing
# ---------------------------------------------------------------------------


def test_window_builds_and_populates_menus(win):
    numbers = [win.merge1_menu.itemText(i) for i in range(win.merge1_menu.count())]
    assert numbers == ["1", "2", "3"]
    assert len(win._spike_plots) == 3  # one waveform overlay per cluster
    assert win.feature_scatter.data is not None  # scatter drawn


def test_epoch_controls_visible_with_two_epochs(win):
    assert win.epoch_start_menu.isVisibleTo(win)
    assert [win.epoch_start_menu.itemText(i) for i in range(win.epoch_start_menu.count())] == [
        "ep0",
        "ep1",
    ]


def test_epoch_controls_hidden_with_single_epoch(qtbot):
    m, _ = _model(two_epochs=False)
    w = build_window(m, ask_before_done=False)
    qtbot.addWidget(w)
    assert not w.epoch_start_menu.isVisibleTo(w)


# ---------------------------------------------------------------------------
# control wiring -> model
# ---------------------------------------------------------------------------


def test_quality_menu_sets_label(win):
    win.merge1_menu.setCurrentText("2")
    win.on_quality_changed("Excellent")
    loc = win.model._info_index_for_number(2)
    assert win.model.clusterinfo[loc]["qualitylabel"] == "Excellent"
    # the cluster's waveform title reflects the new quality.
    assert "Q=Excellent" in win._spike_plots[1].titleLabel.text


def test_merge_button_merges(win):
    win.merge1_menu.setCurrentText("1")
    win.merge2_menu.setCurrentText("2")
    win.on_merge()
    assert sorted(set(win.model.clusterids)) == [1.0, 2.0]
    numbers = [win.merge1_menu.itemText(i) for i in range(win.merge1_menu.count())]
    assert numbers == ["1", "2"]


def test_move_to_front(win):
    win.merge1_menu.setCurrentText("3")
    win.model.set_quality(3, "Good")
    win.on_move_to_front()
    assert win.model.clusterinfo[0]["qualitylabel"] == "Good"


def test_cluster_all_kmeans(qtbot):
    pytest.importorskip("sklearn")
    m, labels = _model(assigned=False)  # start unclustered
    w = build_window(m, ask_before_done=False)
    qtbot.addWidget(w)
    w.algorithm_menu.setCurrentText("KMeans")
    w.cluster_size_edit.setText("3")
    w.on_cluster_all()
    assert sorted(set(w.model.clusterids)) == [1.0, 2.0, 3.0]
    assert len(w._spike_plots) == 3


def test_feature_switch_recomputes(win):
    win.on_feature_changed("2points")
    assert win.model.features.shape[1] == len(win.model.npoint_samplelist) * NCHAN
    win.on_feature_changed("pca3")
    assert win.model.features.shape[1] == 3


def test_lasso_split_and_add(win):
    # Select roughly half of cluster 1 (a left half-plane through the median of
    # its feature x) so the split is genuine (parent survives) -> +1 cluster.
    win.merge1_menu.setCurrentText("1")
    feats = win.model.features
    vis = win.model.visible_indices()
    c1 = vis[win.model.clusterids[vis] == 1.0]
    med = float(np.median(feats[c1, win._dim_x]))
    big = 1e3
    poly = np.array([[-big, -big], [med, -big], [med, big], [-big, big]])
    before = len(win.model.clusterinfo)
    n = win.apply_selection(poly, "split")
    assert n > 0
    assert len(win.model.clusterinfo) == before + 1


def test_lasso_add_moves_into_selected_cluster(win):
    win.merge1_menu.setCurrentText("2")
    poly = np.array([[-1e3, -1e3], [1e3, -1e3], [1e3, 1e3], [-1e3, 1e3]])
    win.apply_selection(poly, "add")
    # everything visible was added to cluster 2 -> after 1..N renumber, a single
    # cluster remains.
    assert sorted(set(win.model.clusterids)) == [1.0]


def test_marker_size_and_subset_redraw(win):
    win.marker_size_spin.setValue(12)  # triggers on_marker_size_changed
    assert win._marker_size == 12
    win.subset_cb.setChecked(False)  # triggers on_subset_changed
    assert win._random_subset is False
    win.redraw()  # must not raise


# ---------------------------------------------------------------------------
# finish / cancel
# ---------------------------------------------------------------------------


def test_done_success_returns_result(win):
    for n in (1, 2, 3):
        win.model.set_quality(n, "Good")
    win.on_done()
    assert win.success is True
    assert win.result_clusterids is not None
    assert win.result_clusterinfo is not None
    assert len(win.result_clusterids) == win.model.n_spikes


def test_done_blocked_until_quality_assigned(win, monkeypatch):
    # avoid the modal warning dialog in a headless run.
    monkeypatch.setattr(win, "_maybe_message", lambda *a, **k: None)
    win.on_done()  # clusters still Unselected
    assert win.success is False


def test_cancel_returns_no_result(win):
    win.on_cancel()
    assert win.success is False


def test_scene_click_lasso_path(win):
    # drive the REAL mouse handler (_on_scene_clicked) with synthetic click
    # events: build a polygon around cluster 1's points, double-click to apply a
    # split. Exercises the scenePos/mapping/double-click path end to end.
    from pyqtgraph.Qt import QtCore

    win.merge1_menu.setCurrentText("1")
    win._start_lasso("split")
    feats = win.model.features
    c1 = np.flatnonzero(win.model.clusterids == 1.0)
    cx = float(np.median(feats[c1, win._dim_x]))
    cy = float(np.median(feats[c1, win._dim_y]))
    vb = win.feature_plot.getPlotItem().vb
    before = len(win.model.clusterinfo)

    def click(x, y, double=False):
        sp = vb.mapViewToScene(QtCore.QPointF(x, y))

        class _Evt:
            def scenePos(self):
                return sp

            def double(self):
                return double

        win._on_scene_clicked(_Evt())

    # left half-plane through cluster 1's median x -> selects ~half of cluster 1
    # (scale-independent), a genuine split rather than swallowing the cluster.
    big = 1e6
    pts = [(cx - big, cy - big), (cx, cy - big), (cx, cy + big), (cx - big, cy + big)]
    for i, (x, y) in enumerate(pts):
        click(x, y, double=(i == len(pts) - 1))
    # the lasso resolved (pending action cleared); a split added a cluster.
    assert win._pending_action is None
    assert len(win.model.clusterinfo) == before + 1


def test_merge_all_the_way_down_to_one(win):
    # repeatedly merge the two lowest clusters until one remains -- must not
    # crash and must stay contiguous (this path hung/crashed before the
    # QApplication-reference fix surfaced it).
    guard = 0
    while len([c for c in win.model.unique_clusters() if not np.isnan(c)]) > 1 and guard < 40:
        nums = [n for n in win._cluster_numbers() if n != "NaN"]
        win.merge1_menu.setCurrentText(nums[0])
        win.merge2_menu.setCurrentText(nums[1])
        win.on_merge()
        guard += 1
    assert sorted(set(win.model.clusterids)) == [1.0]
    # merging with a single cluster left is a no-op, not a crash.
    win.on_merge()
    assert sorted(set(win.model.clusterids)) == [1.0]


def test_single_spike_window_builds_and_draws(qtbot):
    m, _ = _model()
    one = ClusterModel(
        m.waves[:, :, :1],
        clusterids=np.array([1.0]),
        epoch_names=["e1"],
        epoch_start_samples=[1],
    )
    w = build_window(one, ask_before_done=False)
    qtbot.addWidget(w)
    w.on_feature_changed("pca3")
    w.redraw()  # must not raise
    assert len(w._spike_plots) == 1


def test_waveform_panels_persist_and_share_zoom(win):
    panels = list(win._spike_plots)
    assert len(panels) == 3
    # every panel shares panel[0]'s X axis -> horizontal zoom stays consistent.
    vb0 = panels[0].getViewBox()
    for p in panels[1:]:
        assert p.getViewBox().linkedView(0) is vb0
    # mouse is constrained to X (Y auto-fits), so zoom can't desync the panels.
    assert panels[0].getViewBox().state["mouseEnabled"] == [True, False]
    # set a custom X zoom, then a content redraw with the SAME cluster count.
    panels[0].setXRange(50, 150, padding=0)
    x_before = list(panels[0].getViewBox().viewRange()[0])
    win.on_subset_changed()  # redraws spikes; must NOT recreate the panels
    assert win._spike_plots[0] is panels[0]  # same objects -> zoom preserved
    x_after = win._spike_plots[0].getViewBox().viewRange()[0]
    assert abs(x_after[0] - x_before[0]) < 1e-6 and abs(x_after[1] - x_before[1]) < 1e-6
    # changing the cluster COUNT rebuilds the grid (zoom reset is acceptable then).
    win.merge1_menu.setCurrentText("1")
    win.merge2_menu.setCurrentText("2")
    win.on_merge()
    assert len(win._spike_plots) == 2


def test_reset_zoom_button(win):
    win._spike_plots[0].setXRange(10, 20, padding=0)
    win.on_autorange()  # the Reset zoom button
    # after auto-range the X window spans (roughly) the full concatenated trace
    # (fixture is 2 channels x 21 samples = 42 wide), not the 10-wide zoom.
    lo, hi = win._spike_plots[0].getViewBox().viewRange()[0]
    assert hi - lo > 35


def test_qapplication_reference_survives_gc(tmp_path):
    """Regression: _ensure_qapp must keep a live reference to the QApplication.

    PyQt garbage-collects a QApplication with no live Python reference and deletes
    the C++ object, after which constructing any QWidget aborts the process
    ("Must construct a QApplication before a QWidget"). pytest-qt holds the app
    itself, which masks the bug -- so this runs a standalone subprocess (no
    pytest-qt) that drops the _ensure_qapp() return, forces GC, and then builds
    widgets. Exit 0 proves the module keeps the app alive; a regression SIGABRTs.
    """
    import subprocess
    import sys

    script = (
        "import gc\n"
        "from ndi.app.spikesorter_clustermodel import ClusterModel\n"
        "from ndi.app.spikesorter_gui import _ensure_qapp, build_window\n"
        "import numpy as np\n"
        "_ensure_qapp()\n"  # return intentionally discarded
        "del_ = None\n"
        "gc.collect(); gc.collect()\n"  # would destroy an unreferenced QApplication
        "w = build_window(ClusterModel(np.zeros((5,1,4)), clusterids=np.array([1.,1.,2.,2.])))\n"
        "gc.collect(); gc.collect()\n"
        "w2 = build_window(ClusterModel(np.zeros((5,1,3)), clusterids=np.array([1.,2.,3.])))\n"
        "print('OK')\n"
    )
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    proc = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, env=env, timeout=120
    )
    assert proc.returncode == 0, (
        f"QApplication GC regression: subprocess exited {proc.returncode}\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr[-800:]!r}"
    )
    assert "OK" in proc.stdout


def test_escape_cancels_lasso_not_dialog(win):
    from pyqtgraph.Qt import QtCore, QtGui

    win._start_lasso("split")
    assert win._pending_action == "split"
    esc = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Escape, QtCore.Qt.KeyboardModifier.NoModifier
    )
    win.keyPressEvent(esc)
    # the lasso is cancelled, but the dialog is NOT rejected.
    assert win._pending_action is None
    assert win.success is False
    assert win.result_clusterids is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
