"""Dock panels: choose density or counts, filter cell types, pick genes.

Built with qtpy directly rather than magicgui, to match the widgets the
FICTURE viewer in the bscholl project already uses -- a filterable list
with a checkbox per entry, and radio buttons for the two display modes.
Those are the shapes people here already know, and a different idiom for
the same job is a cost with no return.

PANEL ORDER, top to bottom on the right: the display mode, then the cell
types, then the genes. The first two are short and are read once; the
gene list is long and is scrolled, so putting it last keeps the others
on screen.

Everything Qt is imported inside the functions. This module is imported
by :mod:`viewer`, which a headless caller may import to compose layers by
hand, and a top-level ``qtpy`` import would drag Qt into that.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "geneIndex",
    "labelPartition",
    "addGenePanel",
    "addDisplayPanel",
    "addCellTypePanel",
    "addAllPanels",
]


# --------------------------------------------------------------- genes


def geneIndex(ids, names) -> dict:
    """Collapse a gene list to ONE ENTRY PER SYMBOL.

    Real annotations name the same gene on several rows -- this opossum
    list repeats 324 symbols in its first 2,000 -- because a symbol can
    carry several accessions: transcript variants, a duplicated model, a
    scaffold copy. The rows are separate columns of the pyramid, so a
    picker that offered one item per ROW listed the same gene many times
    over and left the user to guess which was the gene.

    Every row a symbol names is kept, and callers sum them: taking the
    first would show part of the gene's signal and look like the whole.

    Args:
        ids: accessions, one per gene row, in zero-based row order.
        names: symbols, same length. A blank falls back to the accession.

    Returns:
        A dict, sorted case-insensitively by symbol, mapping symbol to
        ``{"rows": [...], "accessions": [...]}``.
    """
    by: dict[str, dict] = {}
    for row, (acc, nm) in enumerate(zip(ids, names)):
        acc = str(acc or "").strip()
        symbol = str(nm or "").strip() or acc or f"row {row}"
        entry = by.setdefault(symbol, {"rows": [], "accessions": []})
        entry["rows"].append(row)
        if acc and acc not in entry["accessions"]:
            entry["accessions"].append(acc)
    return dict(sorted(by.items(), key=lambda kv: kv[0].lower()))


# Distinct colours rather than one map applied to everything: the layers
# blend additively, so two genes in the same colormap make one picture
# that neither of them is.
_GENE_COLORMAPS = ("magenta", "green", "cyan", "yellow", "red", "blue")


def addGenePanel(viewer, session, pyr_doc) -> Any:
    """A filterable list of gene symbols, one checkbox each.

    Ticking a symbol ADDS ITS OWN LAYER rather than replacing the base
    image, which is what makes two genes comparable: they land as
    separate additive layers in different colours and the base stays put
    underneath. Unticking removes that layer again, and removing the
    layer in napari's own list unticks the box, so the two never disagree.

    Variants are already combined by :func:`geneIndex`; every row a
    symbol names is summed into its layer.
    """
    from qtpy.QtCore import Qt
    from qtpy.QtWidgets import (
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )

    from ....fun.doc_gene_export import readGeneList
    from .multiscale import layerSpec

    ids, names = readGeneList(session, pyr_doc)
    index = geneIndex(ids, names)
    n_variants = sum(1 for e in index.values() if len(e["rows"]) > 1)

    box = QWidget()
    outer = QVBoxLayout(box)
    head = f"{len(index):,} genes"
    if n_variants:
        head += f"  ({n_variants:,} with variants, summed)"
    outer.addWidget(QLabel(head))

    search = QLineEdit()
    search.setPlaceholderText("filter by symbol or accession")
    outer.addWidget(search)

    listw = QListWidget()
    items: dict[str, Any] = {}
    # Thirty thousand items go in as one batch: each add would otherwise
    # relayout the list.
    listw.setUpdatesEnabled(False)
    for symbol, entry in index.items():
        rows, accs = entry["rows"], entry["accessions"]
        text = symbol if len(rows) == 1 else f"{symbol}  ({len(rows)} variants)"
        item = QListWidgetItem(text)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Unchecked)
        item.setData(Qt.UserRole, symbol)
        # Accessions are searchable too: a symbol is what people usually
        # type, but not everything here has one.
        item.setData(Qt.UserRole + 1, " ".join([symbol] + accs).lower())
        item.setToolTip(
            f"{symbol}\n{len(rows)} pyramid column(s): {', '.join(accs) or '(no accession)'}"
        )
        listw.addItem(item)
        items[symbol] = item
    listw.setUpdatesEnabled(True)
    outer.addWidget(listw, stretch=1)

    status = QLabel("")
    status.setWordWrap(True)

    clear = QPushButton("Remove all gene layers")
    row = QHBoxLayout()
    row.addStretch()
    row.addWidget(clear)
    outer.addLayout(row)
    outer.addWidget(status)

    state = {"busy": False, "colour": 0}

    def _shown() -> int:
        return sum(1 for it in items.values() if it.checkState() == Qt.Checked)

    def _report(extra: str = ""):
        n = _shown()
        status.setText(f"{n} gene layer(s) shown" + (f" -- {extra}" if extra else ""))

    def _filter(text: str):
        needle = text.strip().lower()
        listw.setUpdatesEnabled(False)
        try:
            for it in items.values():
                it.setHidden(bool(needle) and needle not in it.data(Qt.UserRole + 1))
        finally:
            listw.setUpdatesEnabled(True)

    search.textChanged.connect(_filter)

    def _add(symbol: str):
        name = f"gene: {symbol}"
        if name in viewer.layers:
            return
        rows = index[symbol]["rows"]
        spec = layerSpec(session, pyr_doc, rows, True, name)
        cmap = _GENE_COLORMAPS[state["colour"] % len(_GENE_COLORMAPS)]
        state["colour"] += 1
        try:
            layer = viewer.add_image(**spec, colormap=cmap, blending="additive")
        except Exception:
            # An unknown colormap must not cost the layer.
            layer = viewer.add_image(**spec, blending="additive")
        try:
            layer.reset_contrast_limits()
        except Exception:
            pass
        extra = f"{symbol}: {len(rows)} variants summed" if len(rows) > 1 else ""
        _report(extra)

    def _remove(symbol: str):
        name = f"gene: {symbol}"
        if name in viewer.layers:
            del viewer.layers[name]
        _report()

    def _on_item_changed(item):
        if state["busy"]:
            return
        state["busy"] = True
        try:
            symbol = item.data(Qt.UserRole)
            if item.checkState() == Qt.Checked:
                _add(symbol)
            else:
                _remove(symbol)
        except Exception as e:
            status.setText(f"failed: {e}")
        finally:
            state["busy"] = False

    listw.itemChanged.connect(_on_item_changed)

    def _on_clear():
        state["busy"] = True
        try:
            for symbol, it in items.items():
                if it.checkState() == Qt.Checked:
                    it.setCheckState(Qt.Unchecked)
                    _remove(symbol)
        finally:
            state["busy"] = False
        _report()

    clear.clicked.connect(_on_clear)

    def _on_layer_removed(event):
        """A layer closed in napari's own list unticks its box."""
        name = getattr(getattr(event, "value", None), "name", "")
        if not str(name).startswith("gene: "):
            return
        item = items.get(str(name)[len("gene: ") :])
        if item is None or item.checkState() != Qt.Checked:
            return
        was, state["busy"] = state["busy"], True
        try:
            item.setCheckState(Qt.Unchecked)
        finally:
            state["busy"] = was
        _report()

    try:
        viewer.layers.events.removed.connect(_on_layer_removed)
    except Exception:  # pragma: no cover - depends on the napari build
        pass

    _report()
    viewer.window.add_dock_widget(box, name="Genes", area="right")
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


def labelPartition(labels) -> frozenset:
    """The GROUPING a labeling induces, with the class names discarded.

    Two labelings that partition the cells identically and differ only in
    what the groups are called carry the same information, and showing
    both invites the reader to treat one as corroborating the other. That
    happens for a real reason: a subclass call transferred onto clusters
    is a RENAMING of those clusters, one name per cluster, so it agrees
    with the clustering by construction.

    Comparing names would miss this; comparing memberships catches it.
    """
    groups: dict[Any, list] = {}
    for i, v in enumerate(labels):
        groups.setdefault(v, []).append(i)
    return frozenset(frozenset(g) for g in groups.values())


def addCellTypePanel(viewer, session, cells_doc, points_layer, shapes_layer=None) -> Any:
    """One checkbox per class, per labeling, over the cell layers.

    A cellbin routinely carries several labelings -- a transferred atlas
    call and one or more clusterings -- so each becomes its own group
    rather than being merged. They are not interchangeable: a clustering
    carries no biological identity.

    A labeling that groups the cells EXACTLY as an earlier one does is
    named and then skipped, not drawn twice; see :func:`labelPartition`.
    Supervised calls are considered first, so when a clustering and the
    subclass call transferred onto it agree, it is the one carrying
    biological names that stays.

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

    # Supervised first, so a redundant pair keeps the named call.
    labelings.sort(key=lambda t: (bool(t[1]["isUnsupervised"]), t[1]["labelName"] or ""))

    kept, redundant, seen = [], [], {}
    for labels, info in labelings:
        key = labelPartition(labels)
        first = seen.get(key)
        if first is None:
            seen[key] = info["labelName"] or "(unnamed)"
            kept.append((labels, info))
        else:
            redundant.append((info["labelName"] or "(unnamed)", first))

    box = QWidget()
    outer = QVBoxLayout(box)

    for name, first in redundant:
        msg = (
            f"{name} groups the cells exactly as {first} does, differing only "
            f"in what the groups are called, so it is not shown separately."
        )
        print(f"[genepyramid] {msg}")
        note = QLabel(msg)
        note.setWordWrap(True)
        outer.addWidget(note)

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

    for labels, info in kept:
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

    Added in the order they should read down the right-hand side: the
    display mode, the cell types, then the genes. napari stacks docks in
    the order they arrive, so this order is the layout.

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
    made["display"] = addDisplayPanel(viewer, session, pyr_doc, image_layer, density)
    if cells_doc is not None and points_layer is not None:
        made["cellTypes"] = addCellTypePanel(viewer, session, cells_doc, points_layer, shapes_layer)
    made["genes"] = addGenePanel(viewer, session, pyr_doc)
    return made
