"""ndi.fun.doc.lightsheet.fromOMEZarr -- lightsheet documents from an OME-Zarr store.

MATLAB counterpart: ``+ndi/+fun/+doc/+lightsheet/fromOMEZarr.m``.

Probes the store with :func:`ndr.format.omezarr.listPyramids`, picks each
multiscales entry's reduction (``reductionMap`` by name or type, else 'max'
for a max pyramid and 'mean' otherwise), converts the store's NGFF
translations (voxel CENTRES) to the documents' voxel CORNERS, makes the
source-file document unless ``sourceFileID`` is given, and hands the rest to
:func:`makePyramid`. A cloud target (an ``ndi.cloud`` SessionWriter) always
materializes chunks and is committed at the end (``info['cloud']``).
"""

from __future__ import annotations

import os
import warnings
from collections.abc import Callable
from typing import Any

from ndi.fun.doc_lightsheet._progress import resolveProgressCallback
from ndi.fun.doc_lightsheet.makePyramid import makePyramid

__all__ = ["fromOMEZarr"]


def _isCloudTarget(session: Any) -> bool:
    return hasattr(session, "streamMembers") and hasattr(session, "commit")


def _centresToCorners(pyramids: list[dict]) -> list[dict]:
    """The store's pyramids with each spatial translation moved half a voxel back."""
    out = []
    for entry in pyramids:
        axes = entry.get("axes") or []
        spatial = []
        for a in axes:
            t = str(a.get("type", "") or "")
            spatial.append(
                t == "space" or (not t and str(a.get("name", "")).lower() in ("x", "y", "z"))
            )
        levels = []
        for L in entry.get("levels") or []:
            L = dict(L)
            scale = [float(v) for v in (L.get("scale") or [])]
            tr = [float(v) for v in (L.get("translation") or [])] or [0.0] * len(scale)
            if len(scale) == len(spatial) and len(tr) == len(spatial):
                L["translation"] = [t - s / 2 if sp else t for t, s, sp in zip(tr, scale, spatial)]
            levels.append(L)
        e = dict(entry)
        e["levels"] = levels
        out.append(e)
    return out


def _pickReduction(entry: dict, reductionMap: dict | None) -> str:
    r = ""
    name = str(entry.get("name", "") or "")
    typ = str(entry.get("type", "") or "")
    if reductionMap:
        if name and name in reductionMap:
            r = str(reductionMap[name])
        elif typ and typ in reductionMap:
            r = str(reductionMap[typ])
    if not r:
        t, n = typ.strip().lower(), name.strip().lower()
        if t == "max" or "max" in n:
            r = "max"
        else:
            r = "mean"
            if t and t not in ("mean", "box", "average"):
                warnings.warn(
                    f"Pyramid {name} has type '{typ}'; falling back to 'mean'. Pass "
                    "reductionMap to override.",
                    stacklevel=3,
                )
    return r


def fromOMEZarr(
    session: Any,
    zarrPath: str,
    *,
    subjectID: str = "",
    elementID: str = "",
    pyramidNames: list[str] | None = None,
    reductionMap: dict[str, str] | None = None,
    pipelineVersion: str = "",
    sourceFileID: str = "",
    label: str = "",
    tileBudgetBytes: float = 32 * 2**20,
    chunks: Any = None,
    materializeChunks: bool = False,
    codec: str = "raw",
    clevel: int = 5,
    progressFcn: Callable | str | None = "default",
    numWorkers: int = -1,
    prefetchBytes: float = 512 * 2**20,
    asyncPrefetch: bool = True,
    debugLog: str = "",
    profileLog: str = "",
    resume: dict | None = None,
) -> tuple[Any, list[Any], dict]:
    """Build a lightsheetZarrPyramid (and its levels) from the OME-Zarr store at zarrPath.

    Returns ``(pyramidDoc, levelDocs, info)``; ``info`` has ``zarrPath``,
    ``pyramids`` (as the store describes them, centres and all),
    ``reductions``, ``sourceFileID``, ``sharedLevel0`` and, for a cloud
    target, ``cloud`` (what its commit returned).
    """
    from ndr.format.omezarr.isOMEZarr import isOMEZarr
    from ndr.format.omezarr.listPyramids import listPyramids

    from ndi.fun.doc_lightsheet.makeSourceFile import makeSourceFile

    if not str(subjectID).strip():
        raise ValueError("A lightsheetZarrPyramid depends_on a subject; pass 'subjectID'.")
    toCloud = _isCloudTarget(session)
    if not os.path.isdir(zarrPath):
        raise FileNotFoundError(f"OME-Zarr store not found at {zarrPath}.")
    if not isOMEZarr(zarrPath):
        raise ValueError(
            f"{zarrPath} does not look like an OME-Zarr store (.zattrs missing multiscales)."
        )
    pyramids = listPyramids(zarrPath)
    if not pyramids:
        raise ValueError(f"{zarrPath} reports zero multiscales entries.")
    if pyramidNames:
        wanted = [str(n) for n in pyramidNames]
        kept = [p for p in pyramids if p["name"] in wanted]
        if not kept:
            raise ValueError(
                f"None of the requested pyramid names ({', '.join(wanted)}) matched. "
                f"Available: {', '.join(p['name'] for p in pyramids)}."
            )
        pyramids = kept
    storePyramids = pyramids
    pyramids = _centresToCorners(pyramids)
    perEntryReduction = [_pickReduction(p, reductionMap) for p in pyramids]

    if toCloud:
        session.requireSubject(subjectID)
        if elementID:
            session.requireDocument(elementID)
        if sourceFileID:
            session.requireDocument(sourceFileID)
        materializeChunks = True
    if not sourceFileID:
        srcDoc = makeSourceFile(session, zarrPath)
        session.database_add(srcDoc)
        sourceFileID = srcDoc.id
    barLabel = "Building lightsheet pyramid"
    if label:
        barLabel = f"Building pyramid: {label}"
    elif os.path.basename(os.path.normpath(zarrPath)):
        barLabel = (
            f"Building pyramid: {os.path.splitext(os.path.basename(os.path.normpath(zarrPath)))[0]}"
        )
    progress = resolveProgressCallback(progressFcn, barLabel, "ingest")

    pyramidDoc, levelDocs, sharedLevel0 = makePyramid(
        session,
        pyramids,
        perEntryReduction,
        subjectID=subjectID,
        elementID=elementID,
        sourceFileID=sourceFileID,
        pipelineVersion=pipelineVersion,
        label=label,
        tileBudgetBytes=tileBudgetBytes,
        chunks=chunks,
        materializeChunks=materializeChunks,
        sourceZarrPath=str(zarrPath),
        codec=codec,
        clevel=clevel,
        progressFcn=progress,
        numWorkers=numWorkers,
        prefetchBytes=prefetchBytes,
        asyncPrefetch=asyncPrefetch,
        debugLog=debugLog,
        profileLog=profileLog,
        resume=resume,
    )
    info: dict[str, Any] = {
        "zarrPath": str(zarrPath),
        "pyramids": storePyramids,
        "reductions": sorted(set(perEntryReduction)),
        "sourceFileID": sourceFileID,
        "sharedLevel0": sharedLevel0,
    }
    if toCloud:
        info["cloud"] = session.commit()
    return pyramidDoc, levelDocs, info
