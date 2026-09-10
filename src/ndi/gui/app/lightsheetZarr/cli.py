"""napariViewLightsheet - open a lightsheetZarrPyramid in napari.

Installed by ``pyproject.toml`` `[project.scripts]` as
``napariViewLightsheet``; the MATLAB ``ndi.gui.app.LightsheetZarrManager``
shell-execs it through ``/usr/local/bin/napariViewLightsheet``, a small
wrapper that scrubs MATLAB's library paths before starting Python. The
argument set here MUST stay in sync with
``ndi.fun.doc.lightsheet.viewCommand`` in NDI-matlab.

Purely orchestration. No napari, dask, or zarr imports at module load,
so ``--help`` and ``--list``/``--report`` stay cheap on a headless box.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import Any


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="napariViewLightsheet",
        description=(
            "Open a lightsheetZarrPyramid document from an NDI session in "
            "napari. Chunk bytes are pulled through the NDI cloud cache."
        ),
    )
    p.add_argument(
        "session",
        help="Path to the ndi.session.dir on disk (or its cloud-cache local mirror).",
    )
    p.add_argument(
        "--pyramid",
        default=None,
        help="Document id of the lightsheetZarrPyramid to open. When "
        "the session holds exactly one, this may be omitted; when it "
        "holds more, --list shows the ids.",
    )
    p.add_argument(
        "--reduction",
        default=None,
        help="Filter the pyramid's level ladder to levels with "
        "reduction_function in {'none', <reduction>}. Required when the "
        "ladder holds more than one non-'none' reduction. "
        "'none' is the shared raw level 0 that both mean and max "
        "pyramids typically point at.",
    )
    p.add_argument(
        "--channel",
        type=int,
        default=None,
        help="1-based channel index to display. Omit to add every "
        "channel as its own napari layer.",
    )
    p.add_argument(
        "--level",
        type=int,
        default=None,
        help="0-based level to display at startup. Omit to let napari's "
        "multiscale renderer pick from the window size.",
    )
    p.add_argument(
        "--no-controls",
        dest="controls",
        action="store_false",
        default=True,
        help="Do not dock the reduction / channel / level panels.",
    )
    p.add_argument(
        "--name",
        default=None,
        help="Layer name. Omit to use the pyramid document's label.",
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="Enumerate lightsheetZarrPyramid documents in the session and exit (no napari).",
    )
    p.add_argument(
        "--report",
        action="store_true",
        help="Print the pyramid's level table (level, reduction_function, "
        "shape, chunks, voxel size) and exit (no napari).",
    )
    return p


def _open_session(session_path: str) -> Any:
    """Open the ndi.session.dir at ``session_path``.

    Kept in this module rather than in ``multiscale`` so ``--list`` and
    ``--report`` do not import napari or dask via that module.
    """
    from ndi.session.dir import ndi_session_dir  # deferred

    return ndi_session_dir(session_path)


def _pyramids(session: Any) -> list[Any]:
    """Every ``lightsheetZarrPyramid`` document in the session."""
    from ndi.query import ndi_query  # deferred

    return list(session.database_search(ndi_query("").isa("lightsheetZarrPyramid")))


def _reductions_for(session: Any, pyramid_doc: Any) -> list[str]:
    """Set of non-'none' reduction_function values in the pyramid's ladder."""
    from ndi.gui.app.lightsheetZarr.multiscale import levelDocs  # deferred

    docs = levelDocs(session, pyramid_doc)
    seen = {
        d.document_properties["lightsheetZarrLevel"].get("reduction_function", "none") for d in docs
    }
    return sorted(seen - {"none"})


def _describe(session: Any, doc: Any) -> str:
    """One line per pyramid, matching what --list prints.

    The parent no longer carries reduction / n_levels; both come from a
    child query. One query per pyramid on --list is fine at the scales
    this runs at (a session typically holds a handful of pyramids).
    """
    from ndi.gui.app.lightsheetZarr.multiscale import levelDocs  # deferred

    props = doc.document_properties["lightsheetZarrPyramid"]
    label = props.get("label") or props.get("pyramid_name") or "(unnamed)"
    shape = props.get("shape_level0", [])
    docs = levelDocs(session, doc)
    n_levels = len(docs)
    reductions = sorted(
        {
            d.document_properties["lightsheetZarrLevel"].get("reduction_function", "none")
            for d in docs
        }
        - {"none"}
    ) or ["(none)"]
    return (
        f"{doc.id}  n_levels={n_levels}  "
        f"reductions={','.join(reductions):<12}  "
        f"shape0={list(shape)}  label={label}"
    )


def _pick_pyramid(session: Any, pyramid_id: str | None) -> Any:
    """Resolve --pyramid (or refuse when a session holds more than one)."""
    all_pyramids = _pyramids(session)
    if not all_pyramids:
        raise SystemExit(
            "No lightsheetZarrPyramid documents in this session. "
            "Add one with ndi.fun.doc.lightsheet.fromOMEZarr in MATLAB, "
            "or the equivalent Python builder when it lands."
        )
    if pyramid_id is None:
        if len(all_pyramids) == 1:
            return all_pyramids[0]
        raise SystemExit(
            f"Session holds {len(all_pyramids)} lightsheetZarrPyramid "
            "documents; pass --pyramid <id> or use --list to see them."
        )
    for doc in all_pyramids:
        if doc.id == pyramid_id or doc.id.startswith(pyramid_id):
            return doc
    raise SystemExit(f"No lightsheetZarrPyramid with id starting {pyramid_id!r}.")


def _pick_reduction(session: Any, pyramid_doc: Any, requested: str | None) -> str | None:
    """Choose which reduction the viewer should show.

    None-return means "do not filter" -- the ladder holds only 'none'
    levels (e.g. a raw-only pyramid). Otherwise returns the reduction
    string to use as the filter. Refuses ambiguity: a ladder with
    multiple non-'none' reductions and no ``--reduction`` on the CLI
    is not something the viewer can guess.
    """
    available = _reductions_for(session, pyramid_doc)
    if requested is not None:
        if requested not in available:
            raise SystemExit(
                f"Reduction {requested!r} not available on this pyramid. "
                f"Available: {available or ['(none)']}."
            )
        return requested
    if not available:
        return None
    if len(available) == 1:
        return available[0]
    raise SystemExit(
        f"Pyramid ladder holds multiple reductions ({available}); "
        "pass --reduction <name> to pick one."
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        session = _open_session(args.session)
    except ImportError as exc:  # pragma: no cover
        print(f"ndi package not importable: {exc}", file=sys.stderr)
        return 2

    if args.list:
        for doc in _pyramids(session):
            print(_describe(session, doc))
        return 0

    pyramid_doc = _pick_pyramid(session, args.pyramid)
    reduction = _pick_reduction(session, pyramid_doc, args.reduction)

    if args.report:
        # levelTable does the depends_on query and reports metadata only.
        from ndi.gui.app.lightsheetZarr import multiscale  # deferred

        for row in multiscale.levelTable(session, pyramid_doc, reduction=reduction):
            print(row)
        return 0

    # napari path
    from ndi.gui.app.lightsheetZarr.viewer import openPyramid

    openPyramid(
        session,
        pyramid_doc,
        channel=args.channel,
        level=args.level,
        controls=args.controls,
        name=args.name,
        reduction=reduction,
        show=True,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
