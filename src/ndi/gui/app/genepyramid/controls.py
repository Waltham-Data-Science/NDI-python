"""Dock panels: pick a gene, choose density or counts, filter cell types.

Built with qtpy directly rather than magicgui, to match the widgets the
FICTURE viewer in the bscholl project already uses -- a type-ahead
combobox over the gene list, radio buttons for the two display modes, and
one checkbox per cell class. Those are the shapes people here already
know, and a different idiom for the same job is a cost with no return.

Everything Qt is imported inside the functions. This module is imported
by :mod:`viewer`, which a headless caller may import to compose layers by
hand, and a top-level ``qtpy`` import would drag Qt into that.
"""

from __future__ import annotations

from typing import Any

__all__ = ["addGenePanel", "addDisplayPanel", "addCellTypePanel", "addAllPanels"]


# --------------------------------------------------------------- genes


def addGenePanel(viewer, session, pyr_doc) -> Any:
    """Type-ahead combobox over the gene list, and an Add button.

    ADDS A LAYER PER GENE rather than replacing the base image, which is
    what makes two genes comparable: they land as separate additive
    layers and the base stays put underneath. Adding the same gene twice
    replaces its own layer instead of stacking duplicates.

    A symbol can name SEVERAL rows -- real annotations repeat them, and
    this opossum list repeats 324 of the first 2,000 -- so every matching
    row is summed into the layer. Taking the first would silently show
    part of a gene's signal.
    """
    from qtpy.QtCore import Qt
    from qtpy.QtWidgets import (
        QComboBox,
        QCompleter,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )

    from ....fun.doc_gene_export import readGeneList
    from .multiscale import layerSpec

    ids, names = readGeneList(session, pyr_doc)

    # Symbol first because that is what people type; the accession is kept
    # alongside so an unnamed or duplicated symbol is still selectable.
    display, lookup = [], {}
    for row, (acc, nm) in enumerate(zip(ids, names)):
        text = f"{nm} ({acc})" if nm and nm != acc else str(acc)
        display.append(text)
        lookup.setdefault(text, []).append(row)
        for key in (nm, acc):
            if key:
                lookup.setdefault(str(key), []).append(row)

    box = QWidget()
    outer = QVBoxLayout(box)
    outer.addWidget(QLabel(f"Add gene  ({len(ids):,} in this pyramid)"))

    combo = QComboBox()
    combo.setEditable(True)
    combo.addItems(display)
    completer = QCompleter(display, combo)
    completer.setCaseSensitivity(Qt.CaseInsensitive)
    completer.setFilterMode(Qt.MatchContains)
    combo.setCompleter(completer)

    add = QPushButton("Add")
    status = QLabel("")
    status.setWordWrap(True)

    def _on_add():
        text = combo.currentText().strip()
        if not text:
            return
        rows = lookup.get(text)
        if not rows:
            status.setText(f"'{text}' is not in this gene list")
            return
        name = f"gene: {text}"
        if name in viewer.layers:
            del viewer.layers[name]
        spec = layerSpec(session, pyr_doc, sorted(set(rows)), True, name)
        layer = viewer.add_image(**spec, colormap="viridis", blending="additive")
        try:
            layer.reset_contrast_limits()
        except Exception:
            pass
        extra = f" ({len(rows)} rows summed)" if len(rows) > 1 else ""
        status.setText(f"added {name}{extra}")

    add.clicked.connect(_on_add)

    row = QHBoxLayout()
    row.addWidget(combo, stretch=1)
    row.addWidget(add)
    outer.addLayout(row)
    outer.addWidget(status)
    outer.addStretch()

    viewer.window.add_dock_widget(box, name="Add gene", area="right")
    return box


# ------------------------------------------------------------- display


def addDisplayPanel(viewer, session, pyr_doc, image_layer, density: bool = True) -> Any:
    """Radio buttons for density against raw counts.

    Two exclusive states, so radio buttons rather than a checkbox: the
    label then says what each choice IS, instead of naming one and
    leaving the other implied.

    Switching only swaps the layer's data. A level is summed over the
    selected genes into a 2D array, so the shape does not change and the
    camera, the zoom and the level the viewer is on all survive.
    """
    from qtpy.QtWidgets import QButtonGroup, QLabel, QRadioButton, QVBoxLayout, QWidget

    from .multiscale import levelArrays

    box = QWidget()
    outer = QVBoxLayout(box)
    outer.addWidget(QLabel("Base layer values"))

    r_density = QRadioButton("density (counts per base pixel)")
    r_counts = QRadioButton("raw counts (summed per bin)")
    r_density.setChecked(density)
    r_counts.setChecked(not density)

    group = QButtonGroup(box)
    group.addButton(r_density)
    group.addButton(r_counts)

    note = QLabel(
        "Binning sums, so raw counts make a coarse level binSize^2 brighter "
        "than a fine one and the picture jumps at each level change."
    )
    note.setWordWrap(True)

    status = QLabel("")
    status.setWordWrap(True)

    def _switch(want_density: bool):
        try:
            image_layer.data = levelArrays(
                session, pyr_doc, _currentRows(image_layer), want_density
            )
            image_layer.reset_contrast_limits()
        except Exception as e:
            status.setText(f"failed: {e}")
            return
        status.setText("density" if want_density else "raw counts")

    r_density.toggled.connect(lambda on: _switch(True) if on else None)
    r_counts.toggled.connect(lambda on: _switch(False) if on else None)

    outer.addWidget(r_density)
    outer.addWidget(r_counts)
    outer.addWidget(note)
    outer.addWidget(status)
    outer.addStretch()

    viewer.window.add_dock_widget(box, name="Display", area="right")
    return box


def _currentRows(image_layer):
    """The gene rows the base layer was built from, if it recorded them.

    The base layer is whatever openPyramid drew; nothing here changes its
    gene selection, so None (all genes) is the honest default rather than
    a guess that would quietly widen the picture.
    """
    return getattr(image_layer, "_ndi_gene_rows", None)


# ---------------------------------------------------------- cell types


def addCellTypePanel(viewer, session, cells_doc, points_layer, shapes_layer=None) -> Any:
    """One checkbox per class, per labeling, over the cell layers.

    A cellbin routinely carries several labelings -- a transferred atlas
    call and one or more clusterings -- so each becomes its own group
    rather than being merged. They are not interchangeable: a clustering
    carries no biological identity.

    Hiding works by ALPHA, not by removing points. The row order of the
    points layer is the row order of cells.tsv and of every labels.tsv
    beside it, and deleting rows would break that correspondence for the
    next labeling the user toggles.
    """
    from qtpy.QtWidgets import (
        QCheckBox,
        QLabel,
        QScrollArea,
        QVBoxLayout,
        QWidget,
    )

    from ....fun.doc_gene import findCellTypeLabels, readCellTypeLabels

    docs = findCellTypeLabels(session, cells_doc)
    if not docs:
        return None

    import numpy as np

    labelings = []
    for d in docs:
        try:
            labels, info = readCellTypeLabels(session, d)
        except Exception as e:
            print(f"[genepyramid] skipping a cellTypeLabels document: {e}")
            continue
        labelings.append((labels, info))
    if not labelings:
        return None

    box = QWidget()
    outer = QVBoxLayout(box)

    n_points = len(points_layer.data)
    # visible[i] is False when ANY ticked-off class covers cell i, so two
    # labelings filter jointly rather than the last one clicked winning.
    hidden_by = {}

    def _refresh():
        hide = np.zeros(n_points, dtype=bool)
        for mask in hidden_by.values():
            if mask is not None:
                hide |= mask
        for layer in (points_layer, shapes_layer):
            if layer is None:
                continue
            try:
                colors = np.asarray(layer.face_color).copy()
                if colors.shape[0] == len(hide):
                    colors[:, 3] = np.where(hide, 0.0, 1.0)
                    layer.face_color = colors
                edge = np.asarray(layer.edge_color).copy()
                if edge.shape[0] == len(hide):
                    edge[:, 3] = np.where(hide, 0.0, 1.0)
                    layer.edge_color = edge
                layer.refresh()
            except Exception:
                pass

    for labels, info in labelings:
        kind = "clustering" if info["isUnsupervised"] else "cell type call"
        title = QLabel(f"{info['labelName'] or '(unnamed)'} -- {kind}")
        outer.addWidget(title)
        if info["nUnlabeled"]:
            note = QLabel(f"  {info['nUnlabeled']:,} cells unlabelled by this")
            note.setWordWrap(True)
            outer.addWidget(note)

        arr = np.asarray(labels, dtype=object)
        inner = QWidget()
        col = QVBoxLayout(inner)
        for category in info["categories"]:
            mask = arr == category
            cb = QCheckBox(f"{category}  ({int(mask.sum()):,})")
            cb.setChecked(True)
            key = (info["labelName"], category)

            def _toggled(on, key=key, mask=mask):
                hidden_by[key] = None if on else mask[:n_points]
                _refresh()

            cb.toggled.connect(_toggled)
            col.addWidget(cb)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        outer.addWidget(scroll)

    viewer.window.add_dock_widget(box, name="Cell types", area="right")
    return box


# ----------------------------------------------------------------- all


def addAllPanels(
    viewer,
    session,
    pyr_doc,
    image_layer,
    density,
    cells_doc=None,
    points_layer=None,
    shapes_layer=None,
):
    """Every panel the session supports, skipping what it has no data for.

    A missing Qt costs the panels rather than the picture: the viewer is
    already on screen by the time this runs, and taking it down over a
    convenience would be worse than doing without.
    """
    try:
        import qtpy.QtWidgets  # noqa: F401
    except ImportError as e:  # pragma: no cover - depends on the install
        import sys

        print(
            f"[genepyramid] control panels unavailable ({e}). The image is "
            f"unaffected; --genes and --no-density still work at launch.",
            file=sys.stderr,
        )
        return {}

    made = {}
    made["genes"] = addGenePanel(viewer, session, pyr_doc)
    made["display"] = addDisplayPanel(viewer, session, pyr_doc, image_layer, density)
    if cells_doc is not None and points_layer is not None:
        made["cellTypes"] = addCellTypePanel(viewer, session, cells_doc, points_layer, shapes_layer)
    return made
