"""Command line for viewing a spatial gene expression pyramid.

Reachable three ways, all the same function:

    napariViewGEF <session> ...          the installed console script
    python -m ndi napari <session> ...   the ndi subcommand
    /usr/local/bin/napariViewGEF ...     the shell wrapper, which scrubs
                                         MATLAB's environment first

--report and --list do their work WITHOUT a display. That is deliberate:
it gives the entry point a path that CI can exercise, so the argument
handling, the pyramid lookup and the gene resolution are tested rather
than merely written. Only the actual viewing needs napari.
"""

from __future__ import annotations

import argparse
import sys

__all__ = ["main", "build_parser"]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="napariViewGEF",
        description="View an NDI spatial gene expression pyramid in napari.",
    )
    p.add_argument("session", help="path to the NDI session directory")
    p.add_argument(
        "--pyramid",
        default="",
        metavar="DOCID",
        help="which pyramid document to open. Optional when the session "
        "holds exactly one; when it holds several they are listed and "
        "nothing is opened, because guessing which section to show is "
        "worse than asking.",
    )
    p.add_argument(
        "--genes",
        default="",
        metavar="A,B,C",
        help="comma list of gene symbols or accessions; default is every gene",
    )
    p.add_argument(
        "--no-density",
        action="store_true",
        help="show raw summed counts rather than counts per base pixel. "
        "Off by default because binning sums, so without the divisor the "
        "brightness jumps every time the viewer switches level.",
    )
    p.add_argument(
        "--cells",
        nargs="?",
        const="auto",
        default="",
        metavar="DIR_OR_DOCID",
        help="overlay segmented cell centroids. With no value, finds the "
        "spatialGeneExpressionCells document belonging to this pyramid. "
        "Otherwise a document id, or a directory holding cells.tsv as "
        "extract_cells.py writes it.",
    )
    p.add_argument("--list", action="store_true", help="list the pyramids and exit")
    p.add_argument(
        "--report",
        action="store_true",
        help="print the level ladder and exit; needs no display",
    )
    return p


def _open_session(path):
    from ndi.session.dir import ndi_session_dir

    return ndi_session_dir(path)


def _pyramids(session):
    from ndi.query import ndi_query

    return session.database_search(ndi_query("").isa("spatialGeneExpressionPyramid"))


def _describe(doc) -> str:
    p = doc.document_properties["spatialGeneExpressionPyramid"]
    label = p.get("label") or "(no label)"
    return f"  {doc.id}  {label}  {p['extent_x']} x {p['extent_y']} bins"


def _resolve_cells(session, pyr_doc, spec: str):
    """Cell centroids in SOURCE coordinates, from a document or a directory.

    Both routes go through the same parser, because the Cells document's
    file list is exactly ``cells.tsv`` and ``contours.bin`` -- the same
    names extract_cells.py writes -- and reading a directory by different
    rules than a document is how the two quietly diverge.

    Returns ``(cells, info)`` or ``(None, None)`` when nothing was asked
    for.
    """
    import os

    from ndi.fun.doc_gene import _parse_cells_tsv, readCells
    from ndi.query import ndi_query

    if not spec:
        return None, None

    if spec != "auto" and os.path.isdir(spec):
        path = os.path.join(spec, "cells.tsv")
        if not os.path.isfile(path):
            raise SystemExit(
                f"{spec} has no cells.tsv. --cells wants an extract_cells.py "
                f"OUTPUT directory, a document id, or no value at all to "
                f"find the pyramid's own cells document."
            )
        with open(path, encoding="utf-8") as fh:
            cols, info = _parse_cells_tsv(fh.read(), spec)
        info["source"] = spec
        return cols, info

    docs = session.database_search(
        ndi_query("").isa("spatialGeneExpressionCells")
        & ndi_query("").depends_on("spatialGeneExpressionPyramid_id", pyr_doc.id)
    )
    if spec != "auto":
        docs = [d for d in docs if d.id == spec]
        if not docs:
            raise SystemExit(f"no spatialGeneExpressionCells {spec} belonging to this pyramid")
    if not docs:
        raise SystemExit(
            "this pyramid has no spatialGeneExpressionCells document. Pass a "
            "directory of extracted cells, or a document id."
        )
    if len(docs) > 1:
        raise SystemExit(
            f"this pyramid has {len(docs)} cells documents; name one:\n"
            + "\n".join(f"  {d.id}" for d in docs)
        )
    cols, info = readCells(session, docs[0])
    info["source"] = docs[0].id
    return cols, info


def _resolve_genes(session, pyr_doc, spec: str):
    """Gene symbols or accessions to ZERO-BASED rows.

    A symbol can name several rows -- real annotations repeat them, and
    the opossum list repeats 5,531 of them -- so every match is kept
    rather than the first. Dropping the duplicates would silently show
    part of a gene's signal.
    """
    from ndi.fun.doc_gene_export import readGeneList

    wanted = [s.strip() for s in spec.split(",") if s.strip()]
    if not wanted:
        return None

    ids, names = readGeneList(session, pyr_doc)
    rows, missing = [], []
    for w in wanted:
        hit = [i for i, (a, n) in enumerate(zip(ids, names)) if w in (a, n)]
        if hit:
            rows.extend(hit)
        else:
            missing.append(w)
    if missing:
        raise SystemExit(
            f"not in this pyramid's gene list: {', '.join(missing)}\n"
            f"(the list has {len(ids)} genes; --report shows the pyramid)"
        )
    return sorted(set(rows))


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    session = _open_session(args.session)
    docs = _pyramids(session)

    if not docs:
        print(f"no spatialGeneExpressionPyramid in {args.session}", file=sys.stderr)
        return 1

    if args.list:
        print(f"{len(docs)} pyramid(s) in {args.session}:")
        for d in docs:
            print(_describe(d))
        return 0

    if args.pyramid:
        pyr = next((d for d in docs if d.id == args.pyramid), None)
        if pyr is None:
            print(f"no pyramid {args.pyramid} in this session; --list shows them", file=sys.stderr)
            return 1
    elif len(docs) == 1:
        pyr = docs[0]
    else:
        print(f"this session holds {len(docs)} pyramids; name one with --pyramid:", file=sys.stderr)
        for d in docs:
            print(_describe(d), file=sys.stderr)
        return 1

    gene_rows = _resolve_genes(session, pyr, args.genes)
    cells, cells_info = _resolve_cells(session, pyr, args.cells)
    density = not args.no_density

    if args.report:
        from ndi.fun.doc_gene import levelTable

        levels, frame = levelTable(session, pyr)
        p = pyr.document_properties["spatialGeneExpressionPyramid"]
        print(f"pyramid {pyr.id}  {p.get('label') or '(no label)'}")
        print(f"  origin  ({frame['originX']:g}, {frame['originY']:g}) source units")
        print(f"  extent  {frame['extentX']} x {frame['extentY']} bins")
        print(
            f"  pixel   {frame['basePixelSizeX']:g} x {frame['basePixelSizeY']:g} "
            f"{frame['pixelSizeUnits']}"
        )
        if gene_rows is not None:
            print(f"  genes   {len(gene_rows)} of the list selected")
        if cells is not None:
            n = len(cells["cell_index"])
            print(f"  cells   {n} centroids from {cells_info.get('source')}")
            if cells_info.get("segmentationMethod"):
                print(f"          segmented by {cells_info['segmentationMethod']}")
            if cells_info.get("contoursPresent"):
                print("          contours present but not read; centroids only")
        print(f"  {'bin':>5} {'height':>8} {'width':>8} {'tiles':>12}")
        for lv in levels:
            print(
                f"  {lv['binSize']:>5} {lv['levelHeight']:>8} {lv['levelWidth']:>8} "
                f"{lv['nTilesStored']:>5} of {lv['nTilesGrid']:<4}"
            )
        return 0

    from .viewer import openPyramid

    overlay = None
    if cells is not None:
        overlay = {"x": cells["x"], "y": cells["y"]}
    openPyramid(session, pyr, gene_rows=gene_rows, density=density, cells=overlay)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
