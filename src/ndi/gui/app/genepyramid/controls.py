"""A small dock panel for the two choices that were launch-only.

Which genes to show and whether to divide by bin area were both fixed at
startup, so changing either meant quitting and relaunching -- and a
relaunch rebuilds nothing cheap: it reopens the session and rebuilds the
ladder. Both are in fact recomputable in place, because a level is summed
over the selected genes into a 2D array, so the shape does not change
when the selection does. Only the layer's data has to be swapped.

Kept OUT of :mod:`viewer` because it needs magicgui, which napari brings
but which a caller composing layers by hand may not have. A missing
magicgui costs the panel, not the picture.
"""

from __future__ import annotations

from typing import Any

__all__ = ["addControls", "resolveGeneRows"]


def resolveGeneRows(session, pyr_doc, text: str):
    """Comma-separated symbols or accessions to ZERO-BASED geneList rows.

    Returns ``(rows, missing)``. *rows* is None for "everything", which is
    what an empty box means and what ``levelArrays`` wants for all genes.

    EVERY match is kept, not the first. Real annotations repeat symbols --
    the opossum list repeats thousands of them -- and taking one row would
    silently show part of a gene's signal while looking complete.
    """
    from ....fun.doc_gene_export import readGeneList

    wanted = [w.strip() for w in text.split(",") if w.strip()]
    if not wanted:
        return None, []

    ids, names = readGeneList(session, pyr_doc)
    rows: list[int] = []
    missing: list[str] = []
    for w in wanted:
        hit = [i for i, (a, n) in enumerate(zip(ids, names)) if w in (a, n)]
        if hit:
            rows.extend(hit)
        else:
            missing.append(w)
    return sorted(set(rows)), missing


def addControls(viewer, session, pyr_doc, image_layer, density: bool = True) -> Any:
    """Dock the gene / density panel. Returns the widget, or None.

    None means magicgui was not importable. That is reported once on
    stderr rather than raised: the viewer is already on screen by this
    point and taking it down over a missing convenience would be worse
    than doing without.
    """
    try:
        from magicgui.widgets import CheckBox, Container, Label, LineEdit, PushButton
    except ImportError as e:  # pragma: no cover - depends on the install
        import sys

        print(
            f"[genepyramid] gene/density panel unavailable ({e}). The image is "
            f"unaffected; relaunch with --genes / --no-density to change them.",
            file=sys.stderr,
        )
        return None

    from .multiscale import levelArrays

    genes = LineEdit(
        label="genes",
        value="",
        tooltip=(
            "Comma-separated symbols or accessions. Empty means every gene. "
            "A symbol naming several rows contributes all of them."
        ),
    )
    dens = CheckBox(
        label="density",
        value=density,
        tooltip=(
            "Counts per base pixel rather than per bin. Binning SUMS, so "
            "with this off a coarse level is binSize^2 brighter than a fine "
            "one and the picture jumps every time the viewer changes level."
        ),
    )
    status = Label(value="all genes")
    apply = PushButton(text="Apply")

    def _apply():
        rows, missing = resolveGeneRows(session, pyr_doc, genes.value)
        if missing:
            # Refuse rather than quietly drawing the genes that did match:
            # a partial picture is indistinguishable from a complete one.
            status.value = (
                "not found: " + ", ".join(missing[:4]) + (" ..." if len(missing) > 4 else "")
            )
            return
        try:
            image_layer.data = levelArrays(session, pyr_doc, rows, dens.value)
        except Exception as e:  # pragma: no cover - depends on the data
            status.value = f"failed: {e}"
            return
        # The contrast range that suited all genes is wrong for three of
        # them, and vice versa, so it is recomputed rather than kept.
        try:
            image_layer.reset_contrast_limits()
        except Exception:
            pass
        n = "all genes" if rows is None else f"{len(rows)} row(s)"
        status.value = f"{n}, {'density' if dens.value else 'raw counts'}"

    apply.changed.connect(lambda *_: _apply())

    panel = Container(widgets=[genes, dens, apply, status], labels=True)
    panel.native.setToolTip("Applies on click; the ladder is rebuilt lazily.")
    viewer.window.add_dock_widget(panel, area="right", name="genes")
    return panel
