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
    "parseGeneLayers",
    "abundanceBand",
    "countsOrder",
    "labelAgreement",
    "selectLabelings",
    "addGenePanel",
    "addDisplayPanel",
    "addCellTypePanel",
    "addAllPanels",
    "addCloudPanel",
    "cloudSignInDialog",
    "buildCloudSignInDialog",
    "cloudProfileChoices",
    "cloudSessionLooksLikely",
    "saveCloudProfile",
    "geneLayers",
    "geneName",
    "contrastWindow",
    "pulseGamma",
    "applyGeneAppearance",
    "applySolo",
    "addGeneAppearancePanel",
    "addGeneTourPanel",
    "blurLevels",
    "basePixelUm",
]


# --------------------------------------------------------------- genes


def parseGeneLayers(spec: str):
    """``"HPCAL1:green,RORB:blue,SST"`` to ``[(symbol, colormap|None), ...]``.

    One layer per gene, each in its own colour, which is a different
    request from ``--genes``: that one FILTERS the base layer to a
    subset, leaving one picture. This adds a layer per gene on top of
    the base, which is what makes two genes comparable.

    THE COLOUR IS OPTIONAL and None means "take the next one from the
    cycle", so a caller can name the colours that matter and leave the
    rest. Colormap names may contain spaces -- napari ships ``bop
    orange``, ``bop blue`` and ``bop purple`` -- so only the ends of each
    field are trimmed, never the middle.

    A gene named twice is kept once, at its first position: ticking the
    same box twice adds nothing the second time, and the layer names
    would collide.

    Args:
        spec: comma-separated ``SYMBOL`` or ``SYMBOL:COLORMAP`` entries.
            Empty gives an empty list rather than None -- "no layers
            asked for" is a fact, not a missing answer.

    Returns:
        A list of ``(symbol, colormap or None)``, in the order given,
        which is the order the layers are added and so the order the
        colour cycle advances.
    """
    out, seen = [], set()
    for entry in str(spec or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        symbol, sep, colour = entry.partition(":")
        symbol = symbol.strip()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        colour = colour.strip() if sep else ""
        out.append((symbol, colour or None))
    return out


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
#
# IN RAINBOW ORDER, long wavelength to short: red, yellow, green, cyan,
# blue, then magenta. Genes are assigned in the order they are ticked, so
# the order of this tuple is the order a reader sees them arrive -- and a
# spectral run is one they can hold in their head and read back off the
# picture. Magenta is not spectral at all; it closes the circle, which is
# where the eye expects it after blue.
_GENE_COLORMAPS = ("red", "yellow", "green", "cyan", "blue", "magenta")


# --------------------------------------------------- gene layer appearance

# The one thing that separates a gene layer from the base image and the
# cell overlays. Named rather than spelled out at each use: three panels
# now depend on it, and a prefix that drifts in one of them would leave a
# control quietly governing nothing.
_GENE_PREFIX = "gene: "

# napari rejects a gamma of exactly zero, and the value is a divisor in
# its shader. Small enough to look like zero, large enough to be legal.
_GAMMA_FLOOR = 0.01


def geneLayers(viewer):
    """The gene layers, in the order they were added.

    EXCLUDES the base image, whose name is the pyramid's own label, and
    the cell overlays. That is the whole point of these controls: the
    base layer is the anatomy read underneath, and dimming or gamma-
    pulsing it would take the reference frame away from the thing being
    pointed at.
    """
    out = []
    for layer in getattr(viewer, "layers", ()) or ():
        if str(getattr(layer, "name", "")).startswith(_GENE_PREFIX):
            out.append(layer)
    return out


def geneName(layer) -> str:
    """A gene layer's symbol, without the prefix the layer list needs."""
    name = str(getattr(layer, "name", ""))
    return name[len(_GENE_PREFIX) :] if name.startswith(_GENE_PREFIX) else name


def contrastWindow(reference, contrast: float):
    """Narrow a layer's contrast window by *contrast*, about its floor.

    ``reference`` is ``(lo, hi)`` as the layer was auto-set when it
    arrived, and the result is ``(lo, lo + (hi - lo) / contrast)``.

    THE REFERENCE IS THE POINT. Applying a factor to whatever the limits
    are NOW compounds -- three nudges up and one back down does not
    return you to where you started, and the knob stops meaning a
    setting and starts meaning a history. Every change is computed from
    the window the layer was born with, so the number on the control is
    the whole state.

    Above 1 narrows the window, which is what "more contrast" means for
    a sparse signal: the dim end of the range is where all the counts
    are, so the picture brightens and separates. Below 1 widens it.

    The floor is held rather than the centre because these layers start
    at zero and blend additively: raising the floor would punch holes in
    the background where a gene is merely absent.
    """
    lo, hi = float(reference[0]), float(reference[1])
    contrast = max(1e-6, float(contrast))
    span = (hi - lo) / contrast
    # A window with no width is not a picture. One count of separation is
    # the smallest thing the data can express, so that is the smallest
    # window worth handing to napari.
    return (lo, lo + span if span > 0 else lo + 1.0)


def pulseGamma(base: float, seconds: float, period: float = 1.0) -> float:
    """Gamma partway through one pulse: base -> ~0 -> base, once a period.

    A TRIANGLE, not a sine. The eye reads a linear ramp as a steady
    sweep and a sinusoid as a lingering pause at each end; what this is
    for is saying "this one, now", and the sweep says it more clearly.

    Args:
        base: the gamma to return to, and to depart from.
        seconds: elapsed time. Any value works, including past the end of
            a period -- the pulse repeats.
        period: seconds per pulse.

    Returns:
        A gamma in ``[_GAMMA_FLOOR, base]``, at the floor rather than at
        zero because napari will not take zero.
    """
    if period <= 0:
        return float(base)
    phase = (float(seconds) % period) / period
    # 1 at the start of the period, 0 at its middle, 1 at its end.
    away = abs(2.0 * phase - 1.0)
    return max(_GAMMA_FLOOR, float(base) * away)


def applyGeneAppearance(layers, contrast: float, gamma: float, references: dict) -> int:
    """Put one contrast and one gamma on every gene layer.

    *references* maps layer name to the ``(lo, hi)`` the layer was
    auto-set to when it arrived, and is FILLED IN HERE for any layer not
    yet in it. A layer's own current limits are the right reference only
    the first time; after that they are this function's own output.

    Returns:
        How many layers were changed. A layer that refuses either
        setting is skipped rather than allowed to stop the rest -- one
        odd layer must not cost the control.
    """
    done = 0
    for layer in layers:
        name = str(getattr(layer, "name", ""))
        try:
            if name not in references:
                lo, hi = layer.contrast_limits
                references[name] = (float(lo), float(hi))
            layer.contrast_limits = list(contrastWindow(references[name], contrast))
            layer.gamma = max(_GAMMA_FLOOR, float(gamma))
        except Exception:  # noqa: BLE001 - see docstring
            continue
        done += 1
    return done


def countsOrder(totals, ascending: bool = False):
    """Positions ordered by count, ties left alone.

    STABLE, and that is the whole content of this function. The list
    arrives alphabetical, so a stable sort leaves genes with equal counts
    in alphabetical order instead of an arbitrary one -- and at the
    bottom of a real section thousands of them tie, which is precisely
    where an arbitrary order is most annoying to read.

    Sorting ASCENDING is a separate sort rather than the descending one
    reversed: reversing would reverse the ties too, so the alphabetical
    order inside each tied group would come back backwards in one
    direction and forwards in the other.

    Args:
        totals: counts per entry, array-like.
        ascending: quietest first rather than loudest first.

    Returns:
        An int array of positions into *totals*.
    """
    import numpy as np

    t = np.asarray(totals)
    return np.argsort(t if ascending else -t, kind="stable")


def addGenePanel(viewer, session, pyr_doc, initial=None) -> Any:
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
    within them is the normal way to use both. Sorting is separate from
    both and survives them: alphabetical to find a gene you can name, by
    counts to see which ones there are -- which is what the band leaves
    you wanting, since a few hundred loud genes in alphabetical order
    still hide their own ranking.
    """
    import numpy as np
    from qtpy.QtCore import Qt, QTimer
    from qtpy.QtWidgets import (
        QDoubleSpinBox,
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
    base_head = f"{len(index):,} genes"
    if n_variants:
        base_head += f"  ({n_variants:,} with variants, summed)"
    header = QLabel(base_head)

    def _headText(info=None) -> str:
        # The band's own count lives here rather than in a line of its
        # own: it is the same fact the header already states, narrowed.
        if not info or not info.get("available") or info["nKept"] == info["nTotal"]:
            return base_head
        return (
            f"{info['nKept']:,} of {info['nTotal']:,} genes  ·  "
            f"{info['pctReads']:.1f}% of reads"
        )

    outer.addWidget(header)

    search = QLineEdit()
    search.setPlaceholderText("filter by symbol or accession")
    outer.addWidget(search)

    # Column headers, not a menu: two buttons that read like a table's
    # header row and behave like one -- click to sort by that column,
    # click again to reverse it. Four orders, which is what looking at a
    # ranked list actually needs; a menu would have listed all four and
    # made the reader pick the wording rather than the direction.
    sort_row = QHBoxLayout()
    name_btn = QPushButton("Gene")
    count_btn = QPushButton("Counts")
    for b in (name_btn, count_btn):
        b.setFlat(True)
        sort_row.addWidget(b)
    count_btn.setEnabled(symbol_totals is not None)
    sort_row.addStretch()
    outer.addLayout(sort_row)

    listw = QListWidget()
    # THE LIST IS WHAT THE PANEL IS FOR. Left to its own size hint it came
    # up four rows tall, wedged between the band above and the blur below,
    # and finding a gene among 26,444 meant scrolling a porthole. A dock
    # panel is only as tall as it is asked to be, so it is asked.
    listw.setMinimumHeight(260)
    items: dict[str, Any] = {}
    symbols = list(index)
    entries = list(index.values())
    state = {"busy": False, "colour": 0, "keep": None, "sigma": 0.0, "raw": {}}

    def _makeItem(i: int):
        symbol = symbols[i]
        rows, accs = entries[i]["rows"], entries[i]["accessions"]
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
        # The symbol's ORIGINAL position, carried on the item so that the
        # abundance mask -- computed once, in that order -- is still
        # readable after the list has been re-sorted into another one.
        item.setData(Qt.UserRole + 2, i)
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
        return item

    def _populate(order):
        """Fill the list in ORDER, a sequence of original positions.

        Rebuilt rather than reordered in place. Moving thirty thousand
        items one at a time is quadratic, and sorting them through a
        Python comparison is no cheaper than making them again -- while
        this is the same single batched pass the panel already pays once.

        THE TICKS COME BACK FROM THE LAYERS, not from remembered state:
        the drawn layers are what a tick means, so reading them is what
        stops the boxes and the picture from disagreeing after a sort.
        """
        was, state["busy"] = state["busy"], True
        listw.setUpdatesEnabled(False)
        try:
            listw.clear()
            items.clear()
            for i in order:
                item = _makeItem(int(i))
                symbol = symbols[int(i)]
                if f"gene: {symbol}" in viewer.layers:
                    item.setCheckState(Qt.Checked)
                listw.addItem(item)
                items[symbol] = item
        finally:
            listw.setUpdatesEnabled(True)
            state["busy"] = was
        _refilter()

    # (column, ascending). Names start A-Z; counts, when asked for, start
    # loudest-first, because that is the question a counts column is
    # being clicked to answer.
    sort_state = {"by": "name", "asc": True}

    def _sortBy(column: str):
        if sort_state["by"] == column:
            sort_state["asc"] = not sort_state["asc"]
        else:
            sort_state["by"] = column
            sort_state["asc"] = column == "name"
        _resort()

    def _resort():
        by, asc = sort_state["by"], sort_state["asc"]
        if by == "counts" and symbol_totals is not None:
            order = countsOrder(symbol_totals, ascending=asc)
        else:
            # geneIndex already sorted by name, and symbols are unique, so
            # Z-A is that order backwards -- no tie to preserve.
            order = range(len(symbols)) if asc else range(len(symbols) - 1, -1, -1)
        arrow = " \u25b2" if asc else " \u25bc"
        name_btn.setText("Gene" + (arrow if by == "name" else ""))
        count_btn.setText("Counts" + (arrow if by == "counts" else ""))
        _populate(order)

    name_btn.clicked.connect(lambda *_: _sortBy("name"))
    count_btn.clicked.connect(lambda *_: _sortBy("counts"))

    # ---- the abundance band ------------------------------------------
    # THE SLIDER GETS ITS OWN LINE. Sharing one with the label left it a
    # stub in a narrow dock -- and this slider carries its own value
    # labels at each end, so what was left after "Abundance band" was the
    # numbers and no track between them: unreachable rather than merely
    # cramped. Same lesson as the rotation slider.
    #
    # What the band is and what it just did stay hover text rather than a
    # paragraph: the explanation is read once and the panel is read every
    # time, and the list underneath is what the space is for.
    if symbol_totals is None:
        note = QLabel("no gene_totals.tsv: no counts, no band")
        note.setToolTip(
            "This pyramid was written without gene_totals.tsv, so per-gene "
            "abundance is unknown. The counts column and the abundance "
            "band are both omitted rather than invented."
        )
        outer.addWidget(note)
        slider = lo_box = hi_box = None
    else:
        outer.addWidget(QLabel("Abundance band"))
        band_row = QHBoxLayout()
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
            band_row.addWidget(slider, stretch=1)
        except Exception as e:  # pragma: no cover - depends on the install
            print(f"[genepyramid] no superqt range slider ({e}); using spin boxes")
            lo_box = QDoubleSpinBox(minimum=0.0, maximum=100.0, decimals=1, singleStep=0.5)
            hi_box = QDoubleSpinBox(minimum=0.0, maximum=100.0, decimals=1, singleStep=0.5)
            hi_box.setValue(100.0)
            band_row.addWidget(lo_box)
            band_row.addWidget(hi_box)
        outer.addLayout(band_row)

    outer.addWidget(listw, stretch=1)

    # ---- blur ---------------------------------------------------------
    # Gene expression is a handful of counts in scattered single pixels.
    # Drawn honestly it is dust; blurred it reads as a pattern. On the
    # GENE layers only -- the base layer is already dense and the cell
    # layers are not what anyone is squinting at.
    blur_row = QHBoxLayout()
    blur_row.addWidget(QLabel("blur"))
    blur = QDoubleSpinBox()
    blur.setRange(0.0, 200.0)
    blur.setDecimals(1)
    blur.setSingleStep(1.0)
    blur.setSuffix(" um")
    blur.setToolTip(
        "Spreads each gene's counts over its neighbourhood, so a sparse\n"
        "gene reads as a pattern instead of dust. The width is a DISTANCE,\n"
        "so it stays the same as you zoom between levels. 0 is off.\n"
        "Spreading lowers the peak a long way -- the contrast limits are\n"
        "reset each time so the layer stays visible."
    )
    blur_row.addWidget(blur, 1)
    outer.addLayout(blur_row)

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

    def _applyBand():
        if symbol_totals is None:
            state["keep"] = None
            _refilter()
            return
        lo, hi = _band()
        keep, info = abundanceBand(symbol_totals, lo, hi)
        state["keep"] = keep
        for w in (slider, lo_box, hi_box):
            if w is not None:
                w.setToolTip(_bandText(info, symbols))
        header.setText(_headText(info))
        _refilter()

    def _refilter():
        needle = search.text().strip().lower()
        keep = state["keep"]
        listw.setUpdatesEnabled(False)
        try:
            for item in items.values():
                i = item.data(Qt.UserRole + 2)
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

    def _binSizes():
        # Cached: levelTable reads the level documents, and the blur knob
        # would otherwise re-read them on every tick of the spin box.
        if state.get("bins") is None:
            from ....fun.doc_gene import levelTable

            levels, _f = levelTable(session, pyr_doc)
            state["bins"] = [lv["binSize"] for lv in levels]
        return state["bins"]

    def _blurred(data):
        """The ladder as it should be drawn at the current width."""
        if not state["sigma"]:
            return data
        return blurLevels(data, _binSizes(), state["sigma"] / basePixelUm(pyr_doc))

    def _add(symbol: str, colour: str | None = None):
        name = f"gene: {symbol}"
        if name in viewer.layers:
            return
        rows = index[symbol]["rows"]
        spec = layerSpec(session, pyr_doc, rows, True, name)
        # The UNBLURRED ladder is kept, because the knob is absolute: each
        # change re-blurs from the original rather than blurring what was
        # already blurred, which would compound and could not be undone.
        state["raw"][name] = spec["data"]
        spec["data"] = _blurred(spec["data"])
        # A NAMED COLOUR DOES NOT ADVANCE THE CYCLE. The cycle exists so
        # that genes ticked by hand come out different from each other;
        # a caller that named its own colours has already solved that,
        # and letting those consume cycle positions would make the first
        # hand-ticked gene's colour depend on how many were preset.
        if colour:
            cmap = colour
        else:
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
        state["raw"].pop(name, None)
        _report()

    def _reblur(_value=None):
        state["sigma"] = float(blur.value())
        for name, raw in list(state["raw"].items()):
            if name not in viewer.layers:
                state["raw"].pop(name, None)
                continue
            layer = viewer.layers[name]
            try:
                layer.data = _blurred(raw)
                # Spreading a sparse signal lowers its peak a long way, so
                # limits set for the unblurred layer would show black.
                layer.reset_contrast_limits()
            except Exception as e:  # noqa: BLE001 - a knob never costs a layer
                status.setText(f"blur failed: {e}")
                return
        _report()

    # DEBOUNCED, and generously. A spin box emits on every keystroke, so
    # typing "50" asks for a blur at 5 um first -- and re-blurring is a
    # whole-ladder map_overlap that takes long enough to see, so the
    # picture visibly redraws at the wrong width before the second digit
    # lands. 1.5s is past the gap between two digits and short enough not
    # to feel stuck.
    #
    # The band slider above uses the same trick at 180ms; the difference
    # is that dragging a slider WANTS to be followed, while a number
    # being typed is not a request until it is finished.
    blurWait = QTimer(box)
    blurWait.setSingleShot(True)
    blurWait.setInterval(1500)
    blurWait.timeout.connect(_reblur)
    blur.valueChanged.connect(lambda *_: blurWait.start())
    # Enter, or clicking away, means the number IS finished -- no reason
    # to sit out the rest of the wait.
    blur.editingFinished.connect(lambda *_: (blurWait.stop(), _reblur()))
    box._ndi_blur_wait = blurWait

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

    _resort()
    _applyBand()

    # ---- genes asked for at launch ------------------------------------
    # Ticked through the panel's OWN checkbox, not by calling _add
    # directly: the box and the layer would otherwise disagree, and
    # unticking a gene that was never ticked does nothing at all. This
    # way a preset gene behaves exactly like one the reader ticked.
    missing = []
    for symbol, colour in parseGeneLayers("") if initial is None else list(initial):
        item = items.get(symbol)
        if item is None:
            missing.append(symbol)
            continue
        was, state["busy"] = state["busy"], True
        try:
            item.setCheckState(Qt.Checked)
        finally:
            state["busy"] = was
        _add(symbol, colour)
    _report()
    if missing:
        # Named but not in this pyramid's gene list. Said out loud rather
        # than passed over: a demo that quietly opens four of six layers
        # looks like the viewer working.
        #
        # AFTER _report, not before: _report rewrites this same label, so
        # the warning set first is the warning nobody sees.
        status.setText(f"not in this pyramid: {', '.join(missing)}")
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

    # Kept, but HIDDEN until something goes wrong. It used to sit under the
    # buttons restating which one was just clicked, which the buttons
    # already show. Deleting it outright would make a failed switch silent,
    # and a control that can fail without saying so is worse than a
    # redundant line -- so it appears only when there is something to say.
    status = QLabel("")
    status.setWordWrap(True)
    status.hide()

    def _switch(want_density: bool):
        try:
            image_layer.data = levelArrays(
                session, pyr_doc, _currentRows(image_layer), want_density
            )
            image_layer.reset_contrast_limits()
        except Exception as e:
            status.setText(f"failed: {e}")
            status.show()
            return
        status.hide()

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

    Without it, everything found is kept and the redundancy is REPORTED
    rather than acted on. Dropping one automatically was wrong twice
    over: below the threshold it did nothing and the reader still saw
    two, and above it the labeling vanished with no way to bring it
    back. Naming the pair and letting the reader switch one off is the
    same information with the decision left where it belongs.

    Supervised calls are ordered first, so a redundant pair is measured
    against the labeling that carries biological names rather than
    against a cluster index.

    Returns:
        ``(kept, redundant, missing)``. *redundant* holds
        ``(name, other_name, forward, reverse)``, the two agreements
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
        for kept_labels, kept_info in kept:
            forward = labelAgreement(labels, kept_labels)
            reverse = labelAgreement(kept_labels, labels)
            if max(forward, reverse) >= REDUNDANT_AT:
                redundant.append((name, kept_info["labelName"] or "(unnamed)", forward, reverse))
                break
        kept.append((labels, info))
    return kept, redundant, []


def addCellTypePanel(
    viewer, session, cells_doc, points_layer, shapes_layer=None, labelings=None
) -> Any:
    """One checkbox per class, per labeling, over the cell layers.

    A cellbin routinely carries several labelings -- a transferred atlas
    call and one or more clusterings -- so each becomes its own group
    rather than being merged. They are not interchangeable: a clustering
    carries no biological identity.

    ONE ROW EACH, with the classes behind a toggle. A cellbin carries a
    couple of labelings with dozens of classes between them, and listing
    every class of every one fills the dock before anyone has asked to
    see them.

    The row's own checkbox switches the whole labeling off, which drops
    its contribution to the filter rather than hiding the cells it
    named: an unwanted second opinion should stop having an opinion.
    Everything starts on, and a labeling that says the same thing as
    another is NAMED rather than removed, so the reader is told which
    one to untick instead of finding one of them gone.

    Hiding works by ALPHA, not by removing points. The row order of the
    points layer is the row order of cells.tsv and of every labels.tsv
    beside it, and deleting rows would break that correspondence for the
    next labeling the user toggles.
    """
    from qtpy.QtWidgets import (
        QCheckBox,
        QHBoxLayout,
        QLabel,
        QPushButton,
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

    # Named, not acted on: it says WHICH of the two to switch off.
    agrees = {}
    for name, other, forward, reverse in redundant:
        agrees[name] = (other, max(forward, reverse))
        _note(
            f"{name} agrees with {other} on {100 * max(forward, reverse):.1f}% "
            f"of cells -- untick one of them."
        )
    if missing:
        have = ", ".join((i["labelName"] or "(unnamed)") for _lb, i in found)
        _note(f"no labeling named {', '.join(missing)}; this cells document has: {have}")
    if not kept:
        _note("no labelings to show.")

    n_points = len(points_layer.data)
    # visible[i] is False when ANY ticked-off class of a labeling that is
    # still switched ON covers cell i, so two labelings filter jointly
    # rather than the last one clicked winning.
    hidden_by = {}
    switched_off = set()

    def _refresh():
        hide = np.zeros(n_points, dtype=bool)
        for (label_name, _category), mask in hidden_by.items():
            if mask is None or label_name in switched_off:
                continue
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
        name = info["labelName"] or "(unnamed)"
        kind = "clustering" if info["isUnsupervised"] else "cell type call"

        # ONE ROW PER LABELING, and the classes are behind it. A cellbin
        # carries a couple of labelings with dozens of classes between
        # them, and listing every class of every one of them fills the
        # dock with checkboxes nobody asked to see yet.
        head = QHBoxLayout()
        master = QCheckBox(f"{name}  ({len(info['categories'])} {kind})")
        master.setChecked(True)
        tip = [f"{name} -- {kind}, {len(info['categories'])} classes"]
        if info["nUnlabeled"]:
            tip.append(f"{info['nUnlabeled']:,} cells are unlabelled by this")
        if name in agrees:
            other, share = agrees[name]
            tip.append(f"agrees with {other} on {100 * share:.1f}% of cells")
        master.setToolTip("\n".join(tip))
        expand = QPushButton("classes \u25b8")
        expand.setFlat(True)
        head.addWidget(master, stretch=1)
        head.addWidget(expand)
        outer.addLayout(head)

        arr = np.asarray(labels, dtype=object)
        inner = QWidget()
        col = QVBoxLayout(inner)
        for category in info["categories"]:
            mask = arr == category
            cb = QCheckBox(f"{category}  ({int(mask.sum()):,})")
            cb.setChecked(True)
            key = (name, category)

            def _toggled(on, key=key, mask=mask):
                hidden_by[key] = None if on else mask[:n_points]
                _refresh()

            cb.toggled.connect(_toggled)
            col.addWidget(cb)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setMaximumHeight(180)
        scroll.setVisible(False)
        outer.addWidget(scroll)

        def _onExpand(*_, scroll=scroll, expand=expand):
            shown = not scroll.isVisible()
            scroll.setVisible(shown)
            expand.setText("classes \u25be" if shown else "classes \u25b8")

        def _onMaster(on, name=name, scroll=scroll, expand=expand):
            # Switching a labeling OFF drops its whole contribution to the
            # filter rather than hiding its cells: an unwanted second
            # opinion should stop having an opinion, not start hiding
            # everything it named.
            if on:
                switched_off.discard(name)
            else:
                switched_off.add(name)
                scroll.setVisible(False)
                expand.setText("classes \u25b8")
            expand.setEnabled(on)
            _refresh()

        expand.clicked.connect(_onExpand)
        master.toggled.connect(_onMaster)

    outer.addStretch()

    viewer.window.add_dock_widget(box, name="Cell types", area="right")
    return box


# ----------------------------------------------------------------- all


def rotationAffine(angle_deg, center):
    """A 3x3 homogeneous affine rotating ``(row, col)`` about ``center``.

    Pure, and separate from the panel, because the thing most likely to be
    wrong here is the SIGN and the PIVOT, and neither needs a display to
    check.

    napari layer coordinates are ``(row, col)`` with row increasing
    DOWNWARD -- the pyramid records ``origin_corner: upper-left`` and the
    viewer honours it. The two sign flips that come from that cancel, so
    the matrix is the ordinary one and a positive angle turns the section
    ANTICLOCKWISE on screen. Checked rather than reasoned about: a point
    to the right of the pivot lands above it at +90 degrees.

    Args:
        angle_deg: rotation in degrees, positive anticlockwise on screen.
        center: ``(row, col)`` pivot in WORLD coordinates -- the same space
            ``viewer.camera.center`` reports, which is what makes "rotate
            about what I am looking at" expressible.

    Returns:
        ``numpy.ndarray`` of shape (3, 3), suitable for ``layer.affine``.
    """
    import numpy as np

    t = np.deg2rad(float(angle_deg))
    c, s = np.cos(t), np.sin(t)
    r = np.array([[c, -s], [s, c]], float)
    # A = T(center) . R . T(-center), so the offset is center - R @ center:
    # the pivot is the one point the rotation leaves alone.
    cy, cx = float(center[0]), float(center[1])
    offset = np.array([cy, cx]) - r @ np.array([cy, cx])
    a = np.eye(3)
    a[:2, :2] = r
    a[:2, 2] = offset
    return a


def rotationCenter(viewer):
    """The current view centre as ``(row, col)`` in world coordinates.

    ``viewer.camera.center`` is reported as ``(z, y, x)`` even for 2D data,
    where z is 0, so the last two entries are the ones that mean anything
    here. Taking the LAST two rather than indexing 1 and 2 keeps this
    right if a 2-tuple is ever handed back instead.
    """
    c = tuple(float(v) for v in viewer.camera.center)
    if len(c) < 2:
        raise ValueError(f"camera centre has no row/column to read: {c!r}")
    return (c[-2], c[-1])


def applyRotation(layers, angle_deg, center):
    """Put ONE shared affine on every layer, so they turn together.

    napari applies ``affine`` after each layer's own scale and translate,
    so the same matrix means the same world-space rotation on all of them
    even though the image ladder, the centroids and the outlines arrive in
    different units. That is the whole reason this is one matrix rather
    than a rotation per layer: the section, the cells and their outlines
    are one picture, and a control that could slide them apart would be a
    control that can produce a wrong picture.

    ``None`` entries are skipped -- outlines and centroids are optional and
    a session without them is the normal case, not an error.

    Returns:
        The affine that was applied.
    """
    a = rotationAffine(angle_deg, center)
    for layer in layers:
        if layer is None:
            continue
        layer.affine = a
    return a


def addRotationPanel(viewer, layers) -> Any:
    """A slider and a box for turning the whole picture.

    Sections are not mounted square, and a reader lining one up against an
    atlas plate or a companion section wants an arbitrary angle rather than
    the 90-degree steps napari offers on the canvas.

    THE PIVOT IS TAKEN WHEN THE INTERACTION STARTS, not on every tick.
    Rotating the layers does not move the camera, so re-reading the view
    centre mid-drag would usually give the same answer -- but "usually" is
    the problem: pan during a drag and the picture would jump as the pivot
    moved under it. Captured once per interaction, a drag is a drag.

    The angle is ABSOLUTE, not accumulated: every change rebuilds the
    affine from zero, so the picture cannot drift out of square through
    repeated small adjustments the way an incremental compose would.
    """
    from qtpy.QtCore import Qt
    from qtpy.QtWidgets import (
        QDoubleSpinBox,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QSlider,
        QVBoxLayout,
        QWidget,
    )

    box = QWidget()
    outer = QVBoxLayout(box)

    slider = QSlider(Qt.Horizontal)
    slider.setMinimum(-180)
    slider.setMaximum(180)
    slider.setValue(0)
    spin = QDoubleSpinBox()
    spin.setRange(-180.0, 180.0)
    spin.setDecimals(1)
    # The step is what the box's own - and + buttons move by, and five
    # degrees is a visible turn -- half a degree took ten clicks to show
    # anything. Anyone wanting finer than five types the number, which the
    # one decimal place still accepts.
    spin.setSingleStep(5.0)
    spin.setSuffix(" deg")
    reset = QPushButton("Reset")

    why = (
        "Turns the image, the centroids and the outlines together, about\n"
        "the centre of the current view. Positive is anticlockwise.\n"
        "The pivot is taken when you start moving the control, so panning\n"
        "between adjustments re-centres it."
    )
    for w in (slider, spin):
        w.setToolTip(why)

    # Hidden until it has something to report, for the same reason as the
    # display panel's: the spin box already shows the angle.
    status = QLabel("")
    status.setWordWrap(True)
    status.hide()

    # One-element lists rather than nonlocal: these are read and written
    # from several nested callbacks and a mutable holder keeps them in one
    # place instead of scattering `nonlocal` declarations.
    pivot = [None]
    guard = [False]
    # The affine currently in force, or None while the picture is square.
    # Kept rather than recomputed, because a layer added later has to get
    # THE SAME matrix -- rebuilding it from the angle would use whatever
    # the view centre is by then, and two layers rotated by equal angles
    # about different pivots do not line up.
    current = [None]

    def _layers():
        """Every layer the rotation governs, as of right now.

        NOT the list this panel was built with. That list is the layers
        that existed at launch, and a gene ticked afterwards is not in it
        -- it arrived square while the section around it was turned, which
        is a picture that is wrong rather than merely unrotated. The
        viewer's own list is the answer to "what is on screen", so it is
        what gets asked, with the passed-in layers kept as a seed for
        anything not registered with the viewer.
        """
        seen, out = set(), []
        for group in (layers or (), getattr(viewer, "layers", ()) or ()):
            for layer in group:
                if layer is None or id(layer) in seen:
                    continue
                seen.add(id(layer))
                out.append(layer)
        return out

    def _pivot():
        if pivot[0] is None:
            pivot[0] = rotationCenter(viewer)
        return pivot[0]

    def _apply(angle):
        try:
            current[0] = applyRotation(_layers(), angle, _pivot())
        except Exception as e:  # noqa: BLE001 - a control never costs the picture
            status.setText(f"failed: {e}")
            status.show()
            return
        status.hide()

    def _onInserted(event=None):
        """Turn a newly added layer to match the ones already turned.

        Ticking a gene while the section is rotated adds its layer square,
        and the two then disagree about where the tissue is -- the gene
        lands beside the anatomy rather than on it. Since the matrix is
        shared and absolute, catching the layer as it arrives is enough:
        it gets exactly what everything else has.
        """
        a = current[0]
        if a is None:
            return
        layer = getattr(event, "value", None)
        # Fall back to sweeping the viewer: napari's event carries the new
        # layer, but a caller that inserts by other means may not, and a
        # missed layer is the failure this exists to prevent.
        targets = [layer] if layer is not None else _layers()
        for target in targets:
            try:
                target.affine = a
            except Exception:  # noqa: BLE001 - a stray entry never costs the rest
                continue

    # Wrapped: the fakes a headless test builds have no event system, and
    # neither does a viewer whose layer list is a plain container.
    try:
        viewer.layers.events.inserted.connect(_onInserted)
    except Exception:  # noqa: BLE001 - see above
        pass

    def _sync(angle, source):
        # The slider and the box show the same number, so each has to move
        # the other -- and setting a widget's value emits its own signal,
        # which would come straight back here. The guard makes the pair one
        # control rather than two that argue.
        if guard[0]:
            return
        guard[0] = True
        try:
            if source is not slider:
                slider.setValue(int(round(angle)))
            if source is not spin:
                spin.setValue(float(angle))
            _apply(float(angle))
        finally:
            guard[0] = False

    def _release():
        # Interaction over: the next one re-reads the view centre.
        pivot[0] = None

    slider.sliderPressed.connect(lambda: pivot[0] or _pivot())
    slider.sliderReleased.connect(_release)
    slider.valueChanged.connect(lambda v: _sync(v, slider))
    spin.editingFinished.connect(lambda: (_sync(spin.value(), spin), _release()))

    def _reset():
        pivot[0] = None
        _sync(0.0, None)
        pivot[0] = None

    reset.clicked.connect(_reset)

    # TWO ROWS, NOT ONE. Sharing a row with the box and the button left
    # the slider a stub too short to aim with: a dock panel is narrow, and
    # the number and the Reset button take a fixed width out of it whatever
    # is left over. On its own row the slider gets the panel's full width,
    # which is what makes it draggable.
    row = QHBoxLayout()
    row.addWidget(spin)
    row.addWidget(reset)
    row.addStretch()
    outer.addLayout(row)
    outer.addWidget(slider)
    outer.addWidget(status)
    outer.addStretch()

    viewer.window.add_dock_widget(box, name="Rotation", area="right")
    return box


def blurLevels(levels, binSizes, sigmaBasePixels: float, truncate: float = 3.0):
    """Gaussian-blur a multiscale ladder by the same DISTANCE at every level.

    Gene expression is a handful of counts in scattered single pixels.
    Drawn honestly it is dust, and a reader looking for where a gene is
    expressed cannot see a pattern in it. Blurring spreads each pixel over
    its neighbourhood so the pattern reads, at the cost of no longer being
    able to point at one bin.

    THE WIDTH IS IN BASE PIXELS, NOT LEVEL PIXELS, and that is the whole
    difficulty. Each level is binned differently, so a fixed number of
    level-pixels would be a different physical distance on each one -- the
    blur would visibly change width as the viewer switched levels while
    zooming, which is precisely what a multiscale ladder exists to avoid.
    Dividing by the level's bin size makes one setting mean one distance
    everywhere.

    BLURRED PER BLOCK, WITH A HALO. Levels are dask arrays whose blocks
    are tiles, and a plain per-block filter would see each tile's edge as
    the end of the world -- leaving a seam at every tile boundary, in a
    grid, which reads as an artefact of the data rather than of the
    drawing. map_overlap gives each block ``truncate * sigma`` of its
    neighbours to work from, which is exactly the reach of the kernel, so
    the result matches blurring the level whole.

    The kernel is unity: widening spreads each pixel's counts rather than
    adding to them, so width and brightness stay separate knobs. Contrast limits will want resetting afterwards
    all the same -- spreading a sparse signal lowers its peak a long way.

    Args:
        levels: dask arrays, finest first, as ``layerSpec`` returns.
        binSizes: each level's bin size in base pixels, same order.
        sigmaBasePixels: blur width, in BASE pixels. 0 or less returns the
            ladder untouched, which is what "no blur" should cost.
        truncate: kernel cutoff in sigmas; also the halo, so the two
            cannot disagree.

    Returns:
        A new list of dask arrays. The input is not modified.
    """
    import numpy as np
    from scipy.ndimage import gaussian_filter

    if sigmaBasePixels is None or sigmaBasePixels <= 0:
        return list(levels)

    out = []
    for arr, b in zip(levels, binSizes):
        sigma = float(sigmaBasePixels) / float(b)
        if sigma <= 0:
            out.append(arr)
            continue
        # +1 so integer truncation can never make the halo shorter than
        # the kernel's reach, which is the one way a seam gets back in.
        depth = int(np.ceil(truncate * sigma)) + 1
        out.append(
            arr.map_overlap(
                gaussian_filter,
                depth=depth,
                boundary=0,
                sigma=sigma,
                truncate=truncate,
                mode="constant",
                dtype=arr.dtype,
            )
        )
    return out


def basePixelUm(pyr_doc, fallback: float = 0.5) -> float:
    """One base pixel's physical width, so a blur can be set in microns.

    The blur knob is in micrometres because that is the unit a reader
    thinks in -- a spread of ten microns means something about tissue,
    ten base pixels means something about the chip. :func:`blurLevels`
    works in base pixels, and this is the conversion between them.

    Only the X size is used. A pyramid whose pixels are not square would
    want an anisotropic sigma, and neither the ladder nor the knob is
    built for that; Stereo-seq's DNB grid is square, so the case has not
    arisen. If it does, this is where it would be noticed.

    Args:
        pyr_doc: a spatialGeneExpressionPyramid document.
        fallback: used when the document does not say, or says something
            that is not a positive number. 0.5 um is the Stereo-seq DNB
            pitch, which is what every pyramid seen so far records. A
            wrong-but-plausible scale makes the knob mean the wrong
            distance; a zero would make it divide by zero.

    Returns:
        Micrometres per base pixel, always positive.
    """
    try:
        p = pyr_doc.document_properties["spatialGeneExpressionPyramid"]
        um = float(p["base_pixel_size_x"])
    except Exception:  # noqa: BLE001 - a missing field costs the default, not the knob
        return float(fallback)
    return um if um > 0 else float(fallback)


def _importQtWidgets() -> None:
    """Import qtpy.QtWidgets, or raise ImportError.

    A named function rather than an inline import inside addAllPanels so a
    test can stand in for it. What addAllPanels does AROUND the panels --
    the order they are built in, and that one throwing does not stop the
    rest or take the window down -- is not about Qt, and a CI job that
    installs no Qt binding should still hold that behaviour to account.
    Without this seam those tests passed anywhere a binding happened to be
    installed and silently asserted nothing anywhere else.
    """
    import qtpy.QtWidgets  # noqa: F401


def cloudSessionLooksLikely() -> bool:
    """Is there any reason to show a cloud login in this viewer?

    A token in the environment is the signal, and it is the right one for
    the same reason the MATLAB launcher uses it: the viewer inherits its
    parent's environment, so a token there says the process that started
    this one had been talking to the cloud and expects this one to keep
    doing so. A purely local pyramid has none, and a login control on a
    window that needs no login is clutter that also implies the picture
    might be waiting on something.

    A token that has ALREADY expired still counts -- that is precisely
    when the panel is wanted.
    """
    import os

    return bool(os.environ.get("NDI_CLOUD_TOKEN"))


def cloudProfileChoices():
    """Saved profiles, as ``(label, email, uid, stored, note)`` rows.

    The label is what a chooser shows: the nickname when there is one,
    else the email, with the email appended either way so two profiles
    for the same person on different stages can be told apart.

    ``note`` SAYS WHY THERE IS NO PASSWORD, which is the whole reason
    this returns five things rather than four. A profile whose secret
    lives in a store this process is not reading looks exactly like a
    profile with no secret at all -- and that is not a rare corner:
    :func:`ndi.cloud.profile._detect_backend` picks ``keyring`` whenever
    keyring merely imports, while MATLAB writes its secret to the AES
    file, so a machine with both ends up looking in the wrong one. The
    note names the backend, so the reader is told which store came up
    empty instead of being told their password is missing.

    Never raises. A secrets backend that will not open, a profile file
    that will not parse -- none of that is a reason a sign-in dialog
    should fail to appear, since typing the credentials by hand is
    exactly the fallback it exists to offer.
    """
    rows = []
    try:
        from ....cloud import profile

        entries = profile.list_profiles()
    except Exception:  # noqa: BLE001 - see docstring
        return rows
    try:
        backend = str(profile.backend())
    except Exception:  # noqa: BLE001 - a name is a nicety, not a requirement
        backend = "unknown"
    for entry in entries:
        uid = str(getattr(entry, "UID", "") or "")
        email = str(getattr(entry, "Email", "") or "")
        nickname = str(getattr(entry, "Nickname", "") or "")
        stage = str(getattr(entry, "Stage", "") or "")
        label = nickname or email or uid
        if email and label != email:
            label = f"{label} ({email})"
        if stage and stage != "prod":
            label = f"{label} [{stage}]"
        stored, note = False, ""
        try:
            stored = bool(profile.get_password(uid))
            note = "password saved" if stored else f"no password in the {backend} store"
        except Exception as exc:  # noqa: BLE001 - the reason is the useful part
            note = f"password unreadable from the {backend} store ({exc})"
        rows.append((label, email, uid, stored, note))
    return rows


def addCloudPanel(viewer) -> Any:
    """A clock on the cloud token, and a button that renews it.

    A VIEWER OUTLIVES ITS TOKEN. Someone reading a section works for
    hours; the token is good for rather less, and it cannot renew itself
    unless credentials happen to be reachable. What running out looks
    like from here is not a login prompt but MISSING DATA -- tiles
    already cached keep drawing, and the ones that were never fetched
    fail one at a time as the reader pans, which reads as a broken
    pyramid. The remedy used to be quitting, logging in elsewhere, and
    opening the section again, since the token lives in this process's
    environment and nothing outside it can reach in.

    ONE ROW, because that is all it is worth until it matters: a button
    and the time left. The credentials live behind the button, in a
    dialog, rather than as three permanently docked fields for something
    a reader does once a day at most.
    """
    from qtpy.QtCore import QTimer
    from qtpy.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

    from ....cloud import auth

    box = QWidget()
    outer = QVBoxLayout(box)

    signin = QPushButton("Sign in...")
    signin.setToolTip(
        "Sign in to NDI Cloud, so tiles that are not already downloaded\n"
        "keep loading. The token lives in this process, so signing in\n"
        "anywhere else does not reach this window."
    )
    clock = QLabel("")
    clock.setWordWrap(True)
    row = QHBoxLayout()
    row.addWidget(signin)
    row.addWidget(clock, 1)
    outer.addLayout(row)

    result = QLabel("")
    result.setWordWrap(True)
    result.hide()
    outer.addWidget(result)
    outer.addStretch()

    def _tick():
        left = auth.tokenSecondsRemaining()
        line = auth.tokenStatusLine()
        # Warned about BEFORE it bites: a reader who sees "12 min left"
        # can sign in at a convenient moment instead of discovering it
        # through a tile that will not load.
        if left is not None and 0 < left < 900:
            clock.setText(f"{line} -- renew before it runs out.")
        elif left is not None and left <= 0:
            clock.setText(f"{line}. Undownloaded tiles will fail until you sign in.")
        else:
            clock.setText(line)

    def _open():
        ok, note = cloudSignInDialog(box)
        if note:
            result.setText(note)
            result.show()
        elif ok:
            result.hide()
        _tick()

    signin.clicked.connect(_open)

    # Parented to the widget, so it stops when the dock goes. A free timer
    # would keep firing at a deleted label and take the process with it.
    timer = QTimer(box)
    timer.setInterval(30_000)
    timer.timeout.connect(_tick)
    timer.start()
    _tick()

    box._ndi_signin = _open
    viewer.window.add_dock_widget(box, name="NDI Cloud", area="right")
    return box


def cloudSignInDialog(parent=None):
    """Show the sign-in dialog and sign in. Returns ``(signed_in, note)``.

    The building is :func:`buildCloudSignInDialog`; this is the two
    lines around it that block. Split so a test can drive the dialog's
    fields and its Sign in button without an event loop to escape from.
    """
    dialog, outcome = buildCloudSignInDialog(parent)
    runner = getattr(dialog, "exec", None) or getattr(dialog, "exec_", None)
    runner()
    return outcome["ok"], outcome["note"]


def buildCloudSignInDialog(parent=None):
    """The sign-in dialog, built but not shown. ``(dialog, outcome)``.

    Behind a button rather than docked, because it is a thing a reader
    does once a day at most and three permanent fields would say
    otherwise.

    THE SAVED PROFILES ARE OFFERED FIRST. Someone whose profile works
    should not be retyping a password to get past an expired token, and
    someone whose profile does NOT work -- which is how most people
    arrive here -- can see which one is being used, which is half the
    diagnosis. Picking one fills the email in; picking one that has a
    stored password signs in with it directly.

    THE PASSWORD IS NOT KEPT. It goes to the login call and nothing else:
    not to a field that stays filled, not to a file, and to the profile
    only when the checkbox asks -- which exists because credentials
    saved once and wrong are exactly how someone ends up in this dialog.
    """
    from qtpy.QtWidgets import (
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QLabel,
        QLineEdit,
        QVBoxLayout,
    )

    from ....cloud import auth

    dialog = QDialog(parent)
    dialog.setWindowTitle("Sign in to NDI Cloud")
    outer = QVBoxLayout(dialog)

    why = QLabel(
        "The token lives in this process, so signing in elsewhere does not " "reach this window."
    )
    why.setWordWrap(True)
    outer.addWidget(why)

    choices = cloudProfileChoices()
    chooser = QComboBox()
    chooser.addItem("type them below", None)
    for label, email, uid, stored, note in choices:
        chooser.addItem(f"{label} -- {note}" if note else label, (email, uid, stored))

    email = QLineEdit()
    email.setPlaceholderText("you@example.com")
    password = QLineEdit()
    password.setEchoMode(QLineEdit.Password)
    password.setPlaceholderText("password")

    form = QFormLayout()
    if choices:
        form.addRow("profile", chooser)
    form.addRow("email", email)
    form.addRow("password", password)
    outer.addLayout(form)

    save = QCheckBox("also save these to my NDI profile")
    save.setToolTip(
        "Stores the credentials so a future session can renew its own\n"
        "token without asking. Overwrites what is saved now, which is\n"
        "the point if what is saved now is wrong."
    )
    outer.addWidget(save)

    said = QLabel("")
    said.setWordWrap(True)
    said.hide()
    outer.addWidget(said)

    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.button(QDialogButtonBox.Ok).setText("Sign in")
    outer.addWidget(buttons)

    def _chose(index):
        data = chooser.itemData(index)
        if not data:
            said.hide()
            return
        picked_email, _uid, stored = data
        email.setText(picked_email)
        # A profile whose password is saved needs nothing typed.
        password.clear()
        if not stored:
            # A profile without a usable password needs the password and
            # not the email, so the focus goes where the work is -- and
            # the reason is put on screen, because "this profile exists
            # but its password is not readable from here" is a different
            # problem from "you never saved one", and only one of them is
            # solved by typing it again.
            said.setText(choices[index - 1][4])
            said.show()
            password.setFocus()
        else:
            said.hide()

    chooser.currentIndexChanged.connect(_chose)

    outcome = {"ok": False, "note": ""}

    def _accept():
        who, secret = email.text().strip(), password.text()
        if not secret:
            # An empty password with a profile picked means "use the one
            # you have", which is the whole reason to pick a profile.
            data = chooser.itemData(chooser.currentIndex())
            if data and data[2]:
                try:
                    from ....cloud import profile as _profile

                    secret = _profile.get_password(data[1])
                except Exception as e:  # noqa: BLE001 - fall through to the message
                    secret = ""
                    said.setText(f"Could not read the saved password: {e}")
        if not who or not secret:
            said.setText("Both an email and a password are needed.")
            said.show()
            return
        try:
            auth.login(who, secret)
        except Exception as e:  # noqa: BLE001 - a bad password is not a crash
            said.setText(f"Sign-in failed: {e}")
            said.show()
            password.clear()
            return
        note = "Signed in."
        if save.isChecked():
            try:
                saveCloudProfile(who, secret)
                note += " Saved to your NDI profile."
            except Exception as e:  # noqa: BLE001 - the sign-in still worked
                note += f" (Could not save to the profile: {e})"
        outcome.update(ok=True, note=note)
        password.clear()
        dialog.accept()

    buttons.accepted.connect(_accept)
    buttons.rejected.connect(dialog.reject)
    password.returnPressed.connect(_accept)

    dialog._ndi_accept = _accept
    dialog._ndi_fields = {"email": email, "password": password, "save": save, "profile": chooser}
    dialog._ndi_said = said
    return dialog, outcome


def saveCloudProfile(email: str, password: str) -> None:
    """Make these the credentials a future session renews itself with.

    Updates the profile that already carries this email rather than
    adding a second one for it -- someone whose saved password is wrong
    is trying to CORRECT it, and a duplicate entry would leave the wrong
    one in place to be picked instead.
    """
    from ....cloud import profile

    for entry in profile.list_profiles():
        if str(getattr(entry, "Email", "")).lower() == email.lower():
            profile.set_password(entry.UID, password)
            profile.set_default(entry.UID)
            return
    uid = profile.add(email.split("@")[0] or "ndi", email, password)
    profile.set_default(uid)


def applySolo(layers, current) -> int:
    """Show one gene layer and hide the rest.

    *current* is the layer NAME to show, or None to show them all --
    which is what restoring looks like when nothing was hidden to begin
    with.

    The base section and the cell overlays are not in *layers* and so
    are never hidden. That is the point of showing one gene at a time
    rather than one layer at a time: the anatomy has to stay under it,
    or a lone gene floats on black and there is nothing to read it
    against.

    Returns:
        How many layers were changed. One that refuses is skipped rather
        than allowed to stop the rest.
    """
    done = 0
    for layer in layers:
        try:
            layer.visible = True if current is None else str(layer.name) == str(current)
        except Exception:  # noqa: BLE001 - see docstring
            continue
        done += 1
    return done


def addGeneAppearancePanel(viewer) -> Any:
    """One contrast and one gamma across every gene layer at once.

    Gene layers arrive with limits set from their own data, which is
    right for reading one gene and wrong for comparing several: two
    genes an order of magnitude apart are drawn as though they were the
    same brightness, and the picture says less than the data does. These
    two knobs move them together, so what is being compared stays
    comparable.

    THE BASE LAYER IS NOT TOUCHED, and neither are the cell overlays.
    The section underneath is the anatomy the genes are read against;
    dimming it to make a gene stand out would take away the frame that
    makes standing out mean anything.

    Both are ABSOLUTE. Contrast recomputes from the window each layer
    was born with rather than from whatever it is now, so the number on
    the control is the whole state and a nudge back really does return.
    """
    from qtpy.QtCore import Qt
    from qtpy.QtWidgets import (
        QHBoxLayout,
        QLabel,
        QPushButton,
        QSlider,
        QVBoxLayout,
        QWidget,
    )

    box = QWidget()
    outer = QVBoxLayout(box)

    # name -> the (lo, hi) the layer was auto-set to when it arrived.
    references: dict[str, tuple[float, float]] = {}
    state = {"contrast": 1.0, "gamma": 1.0}

    def _row(label, lo, hi, value, tip):
        """A slider on one row, with its name and value beside it.

        NO SPIN BOX. Two docks of two rows each was most of the panel
        stack for two knobs that are dragged rather than typed -- these
        are "a bit more" and "a bit less" controls, not values anyone
        needs to enter exactly. The number is still shown, as a label, so
        a setting worth writing down can be read off.
        """
        caption = QLabel(f"{label} {value:.2f}")
        caption.setMinimumWidth(84)
        caption.setToolTip(tip)
        slider = QSlider(Qt.Horizontal)
        # Sliders are integers, so the value is carried in hundredths and
        # converted at the boundary. Hundredths because gamma runs from
        # 0.1 to 3 and tenths would be eight usable positions.
        slider.setRange(int(lo * 100), int(hi * 100))
        slider.setValue(int(value * 100))
        slider.setToolTip(tip)
        row = QHBoxLayout()
        row.addWidget(caption)
        row.addWidget(slider, 1)
        outer.addLayout(row)
        return caption, slider

    contrast_tip = (
        "Narrows the contrast window of every gene layer about its floor.\n"
        "Above 1 brightens and separates a sparse gene, because the dim\n"
        "end of the range is where all the counts are. The base section\n"
        "and the cell layers are not affected."
    )
    gamma_tip = (
        "Gamma for every gene layer. Below 1 lifts the faint counts;\n"
        "above 1 pushes them down. The base section and the cell layers\n"
        "are not affected."
    )
    contrast_label, contrast_slider = _row("contrast", 0.1, 10.0, 1.0, contrast_tip)
    gamma_label, gamma_slider = _row("gamma", 0.1, 3.0, 1.0, gamma_tip)

    status = QLabel("")
    status.setWordWrap(True)
    status.hide()
    reset = QPushButton("Reset")
    row = QHBoxLayout()
    row.addStretch()
    row.addWidget(reset)
    outer.addLayout(row)
    outer.addWidget(status)
    outer.addStretch()

    guard = [False]

    def _apply():
        layers = geneLayers(viewer)
        if not layers:
            status.setText("No gene layers yet -- tick a gene to see this work.")
            status.show()
            return
        applyGeneAppearance(layers, state["contrast"], state["gamma"], references)
        status.hide()

    def _sync(which, value, source=None):
        # Setting a slider emits its own signal, which would come straight
        # back here; the guard makes one change one change.
        if guard[0]:
            return
        guard[0] = True
        try:
            state[which] = float(value)
            label, slider, caption = (
                (contrast_label, contrast_slider, "contrast")
                if which == "contrast"
                else (gamma_label, gamma_slider, "gamma")
            )
            label.setText(f"{caption} {float(value):.2f}")
            if source is not slider:
                slider.setValue(int(round(float(value) * 100)))
            _apply()
        finally:
            guard[0] = False

    contrast_slider.valueChanged.connect(lambda v: _sync("contrast", v / 100.0, contrast_slider))
    gamma_slider.valueChanged.connect(lambda v: _sync("gamma", v / 100.0, gamma_slider))

    def _reset():
        _sync("contrast", 1.0)
        _sync("gamma", 1.0)

    reset.clicked.connect(_reset)

    def _onInserted(event=None):
        """A gene ticked later gets the settings already in force.

        Otherwise it arrives at its own auto-set brightness while the
        others sit where the knobs put them, and the comparison the
        panel exists for is broken by the act of adding to it.
        """
        layer = getattr(event, "value", None)
        if layer is None or not str(getattr(layer, "name", "")).startswith(_GENE_PREFIX):
            return
        if state["contrast"] == 1.0 and state["gamma"] == 1.0:
            return
        applyGeneAppearance([layer], state["contrast"], state["gamma"], references)

    def _onRemoved(event=None):
        # Its reference window goes with it, so a gene ticked, unticked
        # and ticked again is measured from its new data rather than
        # from what it happened to look like the first time.
        layer = getattr(event, "value", None)
        references.pop(str(getattr(layer, "name", "")), None)

    try:
        viewer.layers.events.inserted.connect(_onInserted)
        viewer.layers.events.removed.connect(_onRemoved)
    except Exception:  # noqa: BLE001 - a headless fake has no event system
        pass

    # Exposed so the tour can pulse around the gamma this panel set,
    # and put it back afterwards rather than back to 1.
    box._ndi_appearance = state
    viewer.window.add_dock_widget(box, name="Gene appearance", area="right")
    return box


def addGeneTourPanel(viewer, appearance=None, interval_ms: int = 50) -> Any:
    """Two ways of walking the gene layers, five seconds each.

    Showing someone six genes means saying which is which, and a legend
    of six colours against a section this dense is a legend nobody can
    read. So the picture says it instead, one gene at a time, with its
    name standing in the corner of the canvas.

    TWO MODES, because they answer different questions.

    PULSE leaves every gene on screen and sweeps one gene's gamma down
    and back, once a second. Everything stays in view, so it answers
    "where is THIS one, among the others" -- the comparison is the
    point, and the sweep is the pointer.

    SOLO hides the others outright. It answers "what does this one look
    like, by itself", which additive blending otherwise makes hard: six
    layers over each other are a colour nobody can decompose by eye.
    The base section is NOT hidden, or a lone gene would float on black
    with nothing to read it against.

    NOTHING BLOCKS. Both are one timer stepping a small state machine,
    not a loop with sleeps in it, so the viewer stays live throughout: a
    tour can be stopped mid-gene, and panning while it runs works.

    WHAT IT TOUCHES IT PUTS BACK. Gammas for the pulse, visibility for
    the solo -- recorded when the tour starts and restored when it ends,
    however it ends. Stopping halfway must not leave a gene stranded at
    a gamma nobody chose, or leave five of six genes hidden.

    ONE AT A TIME. Starting either mode stops the other first, so the
    two can never both be moving the same layers.

    Args:
        appearance: the gene-appearance panel, if there is one. Its
            gamma is the value each pulse departs from and returns to,
            so the two controls agree rather than fighting.
        interval_ms: timer period. 50ms is 20 steps a second, which
            reads as a sweep rather than a blink.
    """
    from qtpy.QtCore import QTimer
    from qtpy.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

    seconds_per_gene = 5.0
    pulse_period = 1.0

    box = QWidget()
    outer = QVBoxLayout(box)

    play = QPushButton("Pulse each gene")
    play.setToolTip(
        "Leaves every gene on screen and sweeps one gene's gamma down and\n"
        "back, once a second for five seconds, naming it on the canvas.\n"
        'Answers "where is this one, among the others". Click again to\n'
        "stop; every gamma is put back."
    )
    solo = QPushButton("Show one gene at a time")
    solo.setToolTip(
        "Hides the other genes and shows one for five seconds, naming it\n"
        'on the canvas. Answers "what does this one look like by\n'
        'itself", which additive blending otherwise makes hard. The\n'
        "section underneath stays visible. Click again to stop; every\n"
        "layer is shown again."
    )
    outer.addWidget(play)
    outer.addWidget(solo)

    status = QLabel("")
    status.setWordWrap(True)
    outer.addWidget(status)
    outer.addStretch()

    # THE CLOCK IS A STEP COUNT, not an accumulated float. Adding 0.05 a
    # hundred times lands near 5.0 but not on it, and "has this gene had
    # its five seconds" is a comparison against exactly that -- so the
    # boundary would fall a frame early or late depending on the
    # interval, which is the kind of bug that only shows up on somebody
    # else's machine. Multiplying an integer is exact.
    tour = {"on": False, "mode": "", "order": [], "i": 0, "n": 0, "base": 1.0, "shown": {}}
    steps_per_gene = max(1, int(round(seconds_per_gene * 1000 / interval_ms)))

    def _baseGamma() -> float:
        if appearance is not None:
            try:
                return float(appearance._ndi_appearance["gamma"])
            except Exception:  # noqa: BLE001 - a panel that is gone is not a crash
                pass
        return 1.0

    def _layer(name):
        try:
            return viewer.layers[name]
        except Exception:  # noqa: BLE001 - removed mid-tour is normal, not an error
            return None

    def _overlay(text, visible=True):
        """The gene's name, bottom right, in something readable.

        On the canvas rather than in the panel because that is where the
        eye already is, and because a demo is usually being watched on
        somebody else's screen where the docks are small.
        """
        try:
            overlay = viewer.text_overlay
            overlay.text = str(text)
            overlay.visible = bool(visible)
            overlay.font_size = 24
            overlay.position = "bottom_right"
            overlay.color = "white"
        except Exception:  # noqa: BLE001 - an older napari names these differently
            pass

    def _restore(name):
        layer = _layer(name)
        if layer is None:
            return
        try:
            layer.gamma = max(_GAMMA_FLOOR, tour["base"])
        except Exception:  # noqa: BLE001 - a control never costs the picture
            pass

    def _stop(message=""):
        # Every gene, not only the one in hand: an earlier one whose
        # restore was missed because its layer was briefly gone would
        # otherwise stay where the sweep left it.
        if tour["mode"] == "pulse":
            for name in tour["order"]:
                _restore(name)
        elif tour["mode"] == "solo":
            # Back to what each layer's visibility WAS, not to all-on: a
            # gene the reader had already hidden by hand should stay
            # hidden, and a tour is not a request to change that.
            for name, was in tour["shown"].items():
                layer = _layer(name)
                if layer is None:
                    continue
                try:
                    layer.visible = bool(was)
                except Exception:  # noqa: BLE001 - a control never costs the picture
                    pass
        tour.update(on=False, mode="", order=[], i=0, n=0, shown={})
        timer.stop()
        _overlay("", visible=False)
        play.setText("Pulse each gene")
        solo.setText("Show one gene at a time")
        status.setText(message)

    def _step():
        if not tour["on"]:
            return
        tour["n"] += 1
        if tour["n"] >= steps_per_gene:
            _restore(tour["order"][tour["i"]])
            tour["i"] += 1
            tour["n"] = 0
            if tour["i"] >= len(tour["order"]):
                _stop("Tour finished.")
                return
            _announce()
        name = tour["order"][tour["i"]]
        layer = _layer(name)
        if layer is None:
            # Unticked while the tour was on it. Move along rather than
            # spending five seconds on something that is not there.
            tour["n"] = steps_per_gene - 1
            return
        if tour["mode"] != "pulse":
            # Solo changes nothing between gene boundaries -- the switch
            # happens once, in _announce. The clock still has to run.
            return
        try:
            elapsed = tour["n"] * interval_ms / 1000.0
            layer.gamma = pulseGamma(tour["base"], elapsed, pulse_period)
        except Exception:  # noqa: BLE001 - see _restore
            pass

    def _announce():
        name = tour["order"][tour["i"]]
        if tour["mode"] == "solo":
            applySolo(geneLayers(viewer), name)
        _overlay(geneName(_layer(name)) if _layer(name) is not None else geneName(name))
        status.setText(f"{tour['i'] + 1} of {len(tour['order'])}")

    timer = QTimer(box)
    timer.setInterval(interval_ms)
    timer.timeout.connect(_step)

    def _toggle(mode="pulse"):
        # Clicking the running mode's button stops it; clicking the other
        # one switches, which means stopping first so the layers it was
        # moving are put back before the next mode records them.
        was = tour["mode"]
        if tour["on"]:
            _stop("Stopped.")
            if was == mode:
                return
        layers = geneLayers(viewer)
        order = [str(layer.name) for layer in layers]
        if not order:
            status.setText("No gene layers to tour -- tick some genes first.")
            return
        shown = {}
        if mode == "solo":
            for layer in layers:
                shown[str(layer.name)] = bool(getattr(layer, "visible", True))
        tour.update(on=True, mode=mode, order=order, i=0, n=0, base=_baseGamma(), shown=shown)
        (play if mode == "pulse" else solo).setText("Stop")
        _announce()
        timer.start()

    play.clicked.connect(lambda *_: _toggle("pulse"))
    solo.clicked.connect(lambda *_: _toggle("solo"))

    row = QHBoxLayout()
    row.addStretch()
    outer.addLayout(row)

    box._ndi_tour = tour
    box._ndi_step = _step
    box._ndi_toggle = _toggle
    viewer.window.add_dock_widget(box, name="Gene tour", area="right")
    return box


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
    gene_layers=None,
):
    """Every panel the session supports, skipping what it has no data for.

    Added in the order they should read down the right-hand side: the
    display mode, the cell types, then the genes. napari stacks docks in
    the order they arrive, so this order is the layout.

    A PANEL MUST NOT COST THE PICTURE. By the time this runs the viewer is
    on screen and the image layer is drawn; a panel that throws would
    unwind out of openPyramid before napari.run(), so the window appears
    and the process exits -- a viewer that "opens briefly and closes",
    with the reason lost unless someone was watching stderr.

    That is not hypothetical. Each panel reads files out of the database
    to build itself: genes.tsv and gene_totals.tsv for the genes, one
    labels.tsv per labeling for the cell types. Those reads can fail for
    reasons that have nothing to do with the image -- a document whose
    binary is not local, a cloud-backed session, a file an older ingest
    never wrote -- and none of them is a reason to refuse to draw the
    section. So each panel is built independently and a failure costs
    that panel, named, with its traceback.
    """
    import sys
    import traceback

    try:
        _importQtWidgets()
    except ImportError as e:
        print(
            f"[genepyramid] control panels unavailable ({e}). The image is "
            f"unaffected; --genes and --no-density still work at launch.",
            file=sys.stderr,
        )
        return {}

    def _build(name, fn):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - a panel is never worth the window
            print(
                f"[genepyramid] the {name} panel could not be built "
                f"({type(e).__name__}: {e}). The image is unaffected.",
                file=sys.stderr,
            )
            traceback.print_exc()
            return None

    made = {}
    made["display"] = _build(
        "display", lambda: addDisplayPanel(viewer, session, pyr_doc, image_layer, density)
    )
    # Rotation sits with the other whole-picture controls, above the ones
    # that choose WHAT is drawn: it changes how the section is presented,
    # not which genes or cells are in it.
    made["rotation"] = _build(
        "rotation",
        lambda: addRotationPanel(viewer, [image_layer, shapes_layer, points_layer]),
    )
    if cells_doc is not None and points_layer is not None:
        made["cellTypes"] = _build(
            "cell types",
            lambda: addCellTypePanel(
                viewer, session, cells_doc, points_layer, shapes_layer, labelings
            ),
        )
    # Only when there is a token to run out, and up here with the other
    # whole-session controls rather than among the gene ones: it is about
    # the connection, not about the picture.
    if cloudSessionLooksLikely():
        made["cloud"] = _build("cloud", lambda: addCloudPanel(viewer))
    made["appearance"] = _build("gene appearance", lambda: addGeneAppearancePanel(viewer))
    made["tour"] = _build(
        "gene tour", lambda: addGeneTourPanel(viewer, appearance=made.get("appearance"))
    )
    # THE GENE LIST IS LAST, so it sits at the bottom of the stack. It is
    # the tallest panel by a long way -- 26,444 rows -- and napari gives
    # the leftover height to whatever is furthest down, so anything below
    # it would be squeezed while the list took the room. The two controls
    # above it act on what is ticked in it, which is also the order they
    # are used in.
    made["genes"] = _build(
        "genes", lambda: addGenePanel(viewer, session, pyr_doc, initial=gene_layers)
    )
    return made
