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
    "abundanceBand",
    "labelAgreement",
    "selectLabelings",
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


def abundanceBand(totals, lo: float = 0.0, hi: float = 100.0):
    """Which entries fall in a percentile band OF THE READS.

    NOT a percentile of the list, and the difference is the whole point.
    Rank least to most abundant and accumulate the totals; an entry's
    position is where its own reads sit in that cumulative sweep. So
    ``lo=90`` keeps the handful of genes that between them carry the top
    10% OF ALL READS. Ranking by list position instead would keep 10% of
    the genes, which in a real section is a completely different and much
    larger set: expression is heavy-tailed, and a few hundred genes out
    of thirty thousand carry most of the signal.

    An entry occupies an INTERVAL of that sweep -- the mass before it to
    the mass after -- and sits at the interval's midpoint. Using either
    endpoint would let one dominant gene straddle a cut and be kept or
    dropped on the strength of its own bulk.

    TIES SHARE ONE MIDPOINT, computed over the whole tied group.
    Otherwise ties break on sort order, which is arbitrary, and two genes
    with identical totals land on opposite sides of the same threshold.
    It matters most at the bottom, where thousands of genes tie near zero.

    A consequence that looks like a bug the first time: an entry whose
    own reads are a large share of the total cannot be removed by a small
    top cut. One gene carrying 30% of all reads has the interval
    [70, 100] and the midpoint 85, so ``hi=99`` keeps it -- correctly,
    since dropping it would remove 30% of the reads, not 1%. *info*
    reports that gene's share and the cut that would drop it, so a panel
    can say so rather than appear inert.

    Args:
        totals: reads per entry, array-like.
        lo, hi: band edges in percent.

    Returns:
        ``(keep, info)``. *keep* is a boolean array over *totals*.
    """
    import numpy as np

    tot = np.asarray(totals, dtype=np.float64).ravel()
    n = len(tot)
    grand = float(tot.sum())
    if n == 0 or grand <= 0:
        return np.ones(n, bool), {"available": False, "nTotal": n}

    loudest = int(np.argmax(tot))
    top_share = float(tot[loudest] / grand * 100.0)
    info = {
        "available": True,
        "nTotal": n,
        "lo": float(lo),
        "hi": float(hi),
        "topRow": loudest,
        "topShare": top_share,
        # Where the loudest entry sits, so a panel can name the cut that
        # would actually drop it. Its interval is [100 - share, 100].
        "topMid": 100.0 - top_share / 2.0,
    }
    if lo <= 0.0 and hi >= 100.0:
        return (
            np.ones(n, bool),
            {**info, "nKept": n, "pctReads": 100.0, "droppedTop": []},
        )

    order = np.argsort(tot, kind="stable")
    srt = tot[order]
    cum = np.cumsum(srt)
    before = cum - srt
    start = np.flatnonzero(np.r_[True, srt[1:] != srt[:-1]])
    stop = np.r_[start[1:], n] - 1
    group_mid = (before[start] + cum[stop]) / 2.0 / grand * 100.0
    mid = np.repeat(group_mid, np.r_[start[1:], n] - start)

    in_band = (mid >= lo) & (mid <= hi)
    keep = np.zeros(n, bool)
    keep[order[in_band]] = True

    # Which loud entries the top cut removed. At hi=99 that is a handful
    # of names, and naming them is the useful feedback -- "you just
    # dropped MBP" rather than "1,204 genes hidden".
    dropped = []
    if hi < 100.0:
        for i in order[::-1][:40]:
            if not keep[i]:
                dropped.append(int(i))
            if len(dropped) == 8:
                break
    return keep, {
        **info,
        "nKept": int(keep.sum()),
        "pctReads": float(tot[keep].sum() / grand * 100.0) if keep.any() else 0.0,
        "droppedTop": dropped,
    }


# Distinct colours rather than one map applied to everything: the layers
# blend additively, so two genes in the same colormap make one picture
# that neither of them is.
_GENE_COLORMAPS = ("magenta", "green", "cyan", "yellow", "red", "blue")


# The useful band settings are not obvious from a bare slider and are
# nearly the same on every section, so they are offered as presets.
_BAND_PRESETS = (
    ("all", 0.0, 100.0),
    ("drop top 1%", 0.0, 99.0),
    ("drop top 5%", 0.0, 95.0),
    ("middle 5-95%", 5.0, 95.0),
    ("top 10% only", 90.0, 100.0),
)


def addGenePanel(viewer, session, pyr_doc) -> Any:
    """A filterable list of gene symbols, one checkbox each.

    Ticking a symbol ADDS ITS OWN LAYER rather than replacing the base
    image, which is what makes two genes comparable: they land as
    separate additive layers in different colours and the base stays put
    underneath. Unticking removes that layer again, and removing the
    layer in napari's own list unticks the box, so the two never disagree.

    Variants are already combined by :func:`geneIndex`; every row a
    symbol names is summed into its layer, and its counts are the sum
    over those rows too.

    TWO FILTERS, applied together. The text box answers "where is this
    gene"; the abundance band answers "which genes carry the signal".
    They compose, because narrowing to the loud genes and then searching
    within them is the normal way to use both.
    """
    import numpy as np
    from qtpy.QtCore import Qt, QTimer
    from qtpy.QtWidgets import (
        QDoubleSpinBox,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )

    from ....fun.doc_gene_export import readGeneList, readGeneTotals
    from .multiscale import layerSpec

    ids, names = readGeneList(session, pyr_doc)
    index = geneIndex(ids, names)
    n_variants = sum(1 for e in index.values() if len(e["rows"]) > 1)

    # Counts per SYMBOL, summed over its variant rows -- the same rows the
    # layer sums, so the number in the list is the number the picture is
    # drawn from.
    totals, _records = readGeneTotals(session, pyr_doc)
    if totals is not None and len(totals) != len(ids):
        # Indexing a short totals array by gene row would either raise or,
        # worse, put one gene's reads on another. Neither is worth risking
        # for a column.
        print(
            f"[genepyramid] gene_totals.tsv has {len(totals)} rows but the "
            f"gene list has {len(ids)}; counts and the abundance band are "
            f"omitted rather than guessed."
        )
        totals = None
    if totals is None:
        symbol_totals = None
    else:
        symbol_totals = np.array([int(totals[e["rows"]].sum()) for e in index.values()], np.int64)

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
    for i, (symbol, entry) in enumerate(index.items()):
        rows, accs = entry["rows"], entry["accessions"]
        text = symbol
        if symbol_totals is not None:
            text += f"  \u2014  {int(symbol_totals[i]):,}"
        if len(rows) > 1:
            text += f"  ({len(rows)} variants)"
        item = QListWidgetItem(text)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Unchecked)
        item.setData(Qt.UserRole, symbol)
        # Accessions are searchable too: a symbol is what people usually
        # type, but not everything here has one.
        item.setData(Qt.UserRole + 1, " ".join([symbol] + accs).lower())
        tip = [
            symbol,
            f"{len(rows)} pyramid column(s): {', '.join(accs) or '(no accession)'}",
        ]
        if totals is not None:
            # By ROW, not zipped against the accessions: duplicates are
            # dropped from that list, so position there is not position
            # here and pairing them would attach the wrong number.
            tip.append("counts per column: " + ", ".join(f"{int(totals[r]):,}" for r in rows))
        item.setToolTip("\n".join(tip))
        listw.addItem(item)
        items[symbol] = item
    listw.setUpdatesEnabled(True)

    state = {"busy": False, "colour": 0, "keep": None}

    # ---- the abundance band ------------------------------------------
    band_readout = QLabel()
    band_readout.setWordWrap(True)
    if symbol_totals is None:
        band_readout.setText(
            "This pyramid has no gene_totals.tsv, so abundance is unknown "
            "and the band cannot be applied. Counts are omitted above for "
            "the same reason."
        )
        outer.addWidget(band_readout)
        slider = lo_box = hi_box = None
    else:
        outer.addWidget(QLabel("Abundance band (percentile of total reads)"))
        slider = lo_box = hi_box = None
        try:
            # napari depends on superqt, so the two-handle widget is
            # normally there. Still optional: the spin boxes below are
            # fully functional, and a missing optional import should not
            # cost the control.
            from superqt import QLabeledDoubleRangeSlider

            slider = QLabeledDoubleRangeSlider(Qt.Horizontal)
            slider.setRange(0.0, 100.0)
            slider.setValue((0.0, 100.0))
            slider.setDecimals(1)
            outer.addWidget(slider)
        except Exception as e:  # pragma: no cover - depends on the install
            print(f"[genepyramid] no superqt range slider ({e}); using spin boxes")
            form = QFormLayout()
            lo_box = QDoubleSpinBox(minimum=0.0, maximum=100.0, decimals=1, singleStep=0.5)
            hi_box = QDoubleSpinBox(minimum=0.0, maximum=100.0, decimals=1, singleStep=0.5)
            hi_box.setValue(100.0)
            form.addRow("low %", lo_box)
            form.addRow("high %", hi_box)
            outer.addLayout(form)

        presets = QHBoxLayout()
        for label, a, b in _BAND_PRESETS:
            btn = QPushButton(label)
            btn.setFlat(True)
            btn.clicked.connect(lambda _=False, a=a, b=b: _setBand(a, b))
            presets.addWidget(btn)
        outer.addLayout(presets)
        outer.addWidget(band_readout)

    outer.addWidget(listw, stretch=1)

    status = QLabel("")
    status.setWordWrap(True)
    clear = QPushButton("Remove all gene layers")
    row = QHBoxLayout()
    row.addStretch()
    row.addWidget(clear)
    outer.addLayout(row)
    outer.addWidget(status)

    # ---- filtering ----------------------------------------------------

    def _band():
        if slider is not None:
            v = slider.value()
            return float(v[0]), float(v[1])
        if lo_box is not None:
            lo, hi = lo_box.value(), hi_box.value()
            # Keep the handles ordered rather than rejecting the edit: a
            # user dragging the low box past the high one means to move
            # the band, and a silent no-op reads as a broken widget.
            return (hi, lo) if lo > hi else (lo, hi)
        return 0.0, 100.0

    def _setBand(lo, hi):
        if slider is not None:
            slider.blockSignals(True)
            slider.setValue((lo, hi))
            slider.blockSignals(False)
        elif lo_box is not None:
            for w, v in ((lo_box, lo), (hi_box, hi)):
                w.blockSignals(True)
                w.setValue(v)
                w.blockSignals(False)
        _applyBand()

    def _applyBand():
        if symbol_totals is None:
            state["keep"] = None
            _refilter()
            return
        lo, hi = _band()
        keep, info = abundanceBand(symbol_totals, lo, hi)
        state["keep"] = keep
        band_readout.setText(_bandText(info, list(index)))
        _refilter()

    def _refilter():
        needle = search.text().strip().lower()
        keep = state["keep"]
        listw.setUpdatesEnabled(False)
        try:
            for i, item in enumerate(items.values()):
                ok = True if keep is None else bool(keep[i])
                if ok and needle:
                    ok = needle in item.data(Qt.UserRole + 1)
                item.setHidden(not ok)
        finally:
            listw.setUpdatesEnabled(True)

    # A slider emits continuously while dragged and the band is arithmetic
    # over thirty thousand entries plus a pass over the list, so it is
    # applied once the handle settles rather than on every tick.
    debounce = QTimer(box)
    debounce.setSingleShot(True)
    debounce.setInterval(180)
    debounce.timeout.connect(_applyBand)
    if slider is not None:
        slider.valueChanged.connect(lambda *_: debounce.start())
    elif lo_box is not None:
        lo_box.valueChanged.connect(lambda *_: debounce.start())
        hi_box.valueChanged.connect(lambda *_: debounce.start())

    search.textChanged.connect(lambda *_: _refilter())

    # ---- layers -------------------------------------------------------

    def _shown() -> int:
        return sum(1 for it in items.values() if it.checkState() == Qt.Checked)

    def _report(extra: str = ""):
        n = _shown()
        status.setText(f"{n} gene layer(s) shown" + (f" -- {extra}" if extra else ""))

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

    _applyBand()
    _report()
    viewer.window.add_dock_widget(box, name="Genes", area="right")
    return box


def _bandText(info, symbols) -> str:
    """What the band actually selected, in words.

    A percentile band is not self-explanatory: 5-95% sounds like it keeps
    most genes and in fact keeps a small minority, since the bottom 5% of
    READS is spread over many thousands of barely detected ones. Showing
    both numbers, and naming what the top cut removed, is what makes the
    control readable.
    """
    if not info.get("available"):
        return "no abundance information for this pyramid."
    parts = [
        f"{info['nKept']:,} of {info['nTotal']:,} genes  ·  "
        f"{info['pctReads']:.1f}% of all reads"
    ]
    dropped = info.get("droppedTop") or []
    if dropped:
        parts.append("dropped from the top: " + ", ".join(symbols[i] for i in dropped))
    # The confusing case: a top cut that removes nothing because one gene
    # is too large to fit inside it. Say why, and say what cut would work,
    # rather than letting the control look broken.
    elif info["hi"] < 100.0 and info.get("topShare"):
        parts.append(
            f"nothing dropped at the top: {symbols[info['topRow']]} alone is "
            f"{info['topShare']:.1f}% of all reads, so no gene fits in the top "
            f"{100 - info['hi']:.1f}%. Set the high edge below "
            f"{info['topMid']:.1f} to drop it."
        )
    if info["nKept"] == 0:
        parts.append("empty band -- nothing listed.")
    return "\n".join(parts)


# ------------------------------------------------------------- display


def addDisplayPanel(viewer, session, pyr_doc, image_layer, density: bool = True) -> Any:
    """Radio buttons for density against raw counts.

    Two exclusive states, so radio buttons rather than a checkbox: the
    label then says what each choice IS, instead of naming one and
    leaving the other implied. Why it matters is hover text on the two
    buttons rather than a paragraph in the panel: it is read once.

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

    # Why the choice exists, as hover text rather than a paragraph: it is
    # read once and then never again, and a standing explanation of a
    # two-button control is mostly in the way.
    why = (
        "Binning sums, so raw counts make a coarse level binSize^2 brighter\n"
        "than a fine one and the picture jumps at each level change.\n"
        "Density divides that out, so one contrast range serves every level."
    )
    for w in (r_density, r_counts):
        w.setToolTip(why)

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


# Two labelings this close say the same thing about the section. The
# number is reported every time rather than applied silently, so a pair
# that only nearly agrees is visible as a pair that nearly agrees.
REDUNDANT_AT = 0.99


def labelAgreement(a, b) -> float:
    """How completely knowing *a* tells you *b*, as a fraction of cells.

    Exact equality of partitions was too strict for the case it was
    written for. A subclass call transferred cell by cell onto a
    clustering agrees with it almost everywhere and disagrees on a
    handful of boundary cells, which is not a second opinion -- it is the
    same opinion with noise -- but it is not the same partition either,
    so an equality test showed both and the reader was back where they
    started.

    For each group of *a*, the majority *b* value is the one *a* would
    predict; this returns the fraction of cells that value is right for.
    1.0 means *a* determines *b* exactly, which is what a per-cluster
    renaming gives.

    The measure is DIRECTIONAL. A fine clustering determines a coarse
    call without the reverse holding, so callers test both ways.
    """
    a = list(a)
    b = list(b)
    if len(a) != len(b):
        raise ValueError(
            f"labelings of {len(a)} and {len(b)} cells cannot be compared; "
            f"they are not labelings of the same cells"
        )
    if not a:
        return 1.0
    groups: dict[Any, dict] = {}
    for va, vb in zip(a, b):
        counts = groups.setdefault(va, {})
        counts[vb] = counts.get(vb, 0) + 1
    return sum(max(c.values()) for c in groups.values()) / len(a)


def selectLabelings(found, wanted=None):
    """Which labelings to draw, and which are the same one twice.

    Pure, so the decision is testable without a display -- it is the part
    that can be wrong.

    *found* is a list of ``(labels, info)`` as
    :func:`~ndi.fun.doc_gene.readCellTypeLabels` returns them.

    With *wanted* -- a list of label names -- the caller has chosen, and
    nothing is collapsed or reordered away from that choice. Names that
    are not there come back in *missing* rather than being ignored: a
    typo that silently showed everything would look like the flag not
    working.

    Without it, supervised calls are considered first and any later
    labeling that agrees with a kept one above :data:`REDUNDANT_AT` is
    set aside, so the labeling carrying biological names is the one that
    stays.

    Returns:
        ``(kept, redundant, missing)``. *redundant* holds
        ``(name, kept_name, forward, reverse)``, the two agreements
        measured in both directions so the note can quote a number.
    """
    found = sorted(found, key=lambda t: (bool(t[1]["isUnsupervised"]), t[1]["labelName"] or ""))

    if wanted is not None:
        want = [str(w).strip() for w in wanted if str(w).strip()]
        by_name = {(t[1]["labelName"] or ""): t for t in found}
        kept = [by_name[w] for w in want if w in by_name]
        return kept, [], [w for w in want if w not in by_name]

    kept, redundant = [], []
    for labels, info in found:
        name = info["labelName"] or "(unnamed)"
        dup = None
        for kept_labels, kept_info in kept:
            forward = labelAgreement(labels, kept_labels)
            reverse = labelAgreement(kept_labels, labels)
            if max(forward, reverse) >= REDUNDANT_AT:
                dup = (name, kept_info["labelName"] or "(unnamed)", forward, reverse)
                break
        if dup is None:
            kept.append((labels, info))
        else:
            redundant.append(dup)
    return kept, redundant, []


def addCellTypePanel(
    viewer, session, cells_doc, points_layer, shapes_layer=None, labelings=None
) -> Any:
    """One checkbox per class, per labeling, over the cell layers.

    A cellbin routinely carries several labelings -- a transferred atlas
    call and one or more clusterings -- so each becomes its own group
    rather than being merged. They are not interchangeable: a clustering
    carries no biological identity.

    A labeling that says the same thing as one already shown is named
    and then set aside rather than drawn twice; see
    :func:`selectLabelings`. Pass *labelings* -- a list of label names --
    to choose outright instead, in which case nothing is collapsed.

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

    found = []
    for d in docs:
        try:
            labels, info = readCellTypeLabels(session, d)
        except Exception as e:
            print(f"[genepyramid] skipping a cellTypeLabels document: {e}")
            continue
        found.append((labels, info))
    if not found:
        return None

    kept, redundant, missing = selectLabelings(found, labelings)

    box = QWidget()
    outer = QVBoxLayout(box)

    def _note(msg):
        print(f"[genepyramid] {msg}")
        w = QLabel(msg)
        w.setWordWrap(True)
        outer.addWidget(w)

    for name, other, forward, reverse in redundant:
        _note(
            f"{name} and {other} agree about {100 * max(forward, reverse):.1f}% "
            f"of cells -- one grouping under two sets of names -- so only "
            f"{other} is shown. Use --labels to choose for yourself."
        )
    if missing:
        have = ", ".join((i["labelName"] or "(unnamed)") for _lb, i in found)
        _note(f"no labeling named {', '.join(missing)}; this cells document has: {have}")
    if not kept:
        _note("no labelings to show.")

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
    labelings=None,
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
