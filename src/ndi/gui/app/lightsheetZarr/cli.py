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
        help="Path to the ndi.session.dir on disk (or its cloud-cache " "local mirror).",
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
        choices=("mean", "max"),
        default=None,
        help="Open the sibling pyramid with this reduction instead of "
        "the one --pyramid names. Requires that --pyramid also identify "
        "the sibling (same subject_id + source_file_id).",
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
        help="Enumerate lightsheetZarrPyramid documents in the session " "and exit (no napari).",
    )
    p.add_argument(
        "--report",
        action="store_true",
        help="Print the pyramid's level table (level, reduction, shape, "
        "chunks, voxel size) and exit (no napari).",
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


def _describe(doc: Any) -> str:
    """One line per pyramid, matching what --list prints."""
    props = doc.document_properties["lightsheetZarrPyramid"]
    label = props.get("label") or props.get("pyramid_name") or "(unnamed)"
    reduction = props.get("reduction", "?")
    n_levels = props.get("n_levels", 0)
    shape = props.get("shape_level0", [])
    return (
        f"{doc.id():.16}  reduction={reduction:<4}  n_levels={n_levels}  "
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
        if doc.id() == pyramid_id or doc.id().startswith(pyramid_id):
            return doc
    raise SystemExit(f"No lightsheetZarrPyramid with id starting {pyramid_id!r}.")


def _resolve_reduction(session: Any, pyramid_doc: Any, reduction: str) -> Any:
    """Swap to the sibling pyramid with a different reduction."""
    props = pyramid_doc.document_properties["lightsheetZarrPyramid"]
    if props.get("reduction") == reduction:
        return pyramid_doc
    subject_id = pyramid_doc.dependency_value("subject_id")
    source_file_id = pyramid_doc.dependency_value("source_file_id")
    for other in _pyramids(session):
        p = other.document_properties["lightsheetZarrPyramid"]
        if (
            p.get("reduction") == reduction
            and other.dependency_value("subject_id") == subject_id
            and other.dependency_value("source_file_id") == source_file_id
        ):
            return other
    raise SystemExit(
        f"No sibling lightsheetZarrPyramid with reduction={reduction!r} "
        f"for subject={subject_id!s} / source_file={source_file_id!s}."
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
            print(_describe(doc))
        return 0

    pyramid_doc = _pick_pyramid(session, args.pyramid)
    if args.reduction is not None:
        pyramid_doc = _resolve_reduction(session, pyramid_doc, args.reduction)

    if args.report:
        # levelTable does the depends_on query and reports metadata only.
        from ndi.gui.app.lightsheetZarr import multiscale  # deferred

        for row in multiscale.levelTable(session, pyramid_doc):
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
        show=True,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
