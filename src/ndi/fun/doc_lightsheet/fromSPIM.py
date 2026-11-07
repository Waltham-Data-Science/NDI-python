"""ndi.fun.doc.lightsheet.fromSPIM -- lightsheet documents from SmartSPIM slices.

MATLAB counterpart: ``+ndi/+fun/+doc/+lightsheet/fromSPIM.m``.

Builds a lightsheetZarrPyramid straight from a SmartSPIM acquisition's
stitched ``All_Channels`` slices (no spim2zarr step): level 0 is read from
the slices (axes t,c,z,y,x), and each reduction ladder ('mean', 'max') is
built by block-reducing the level before it, halving every spatial axis
whose voxel is within 1.5x of the finest until the largest spatial axis is
at most ``minLevelSize`` (or ``maxLevels`` levels). Every level's
translation is 0 (the corner of voxel 0).

To a cloud target (an ``ndi.cloud`` SessionWriter) level 1 of each ladder
is reduced straight from the slices, since level 0 does not stay on disk,
and makePyramid folds it into level 0's reads; the target is committed at
the end (``info['cloud']``).
"""

from __future__ import annotations

import math
import os
import warnings
from collections.abc import Callable
from typing import Any

from ndi.fun.doc_lightsheet._progress import resolveProgressCallback
from ndi.fun.doc_lightsheet.makePyramid import makePyramid

__all__ = ["fromSPIM"]

_AXES = [
    {"name": "t", "type": "time", "unit": ""},
    {"name": "c", "type": "channel", "unit": ""},
    {"name": "z", "type": "space", "unit": "micrometer"},
    {"name": "y", "type": "space", "unit": "micrometer"},
    {"name": "x", "type": "space", "unit": "micrometer"},
]


def _planLadder(shape0, scale0, minLevelSize, maxLevels) -> list[dict]:
    steps: list[dict] = []
    shape = [int(s) for s in shape0]
    scale = [float(s) for s in scale0]
    while len(steps) + 1 < maxLevels and max(shape[2:5]) > minLevelSize:
        live = [a for a in range(2, 5) if shape[a] > 1]
        if not live:
            break
        finest = min(scale[a] for a in live)
        f = [1] * 5
        for a in range(2, 5):
            if shape[a] > 1 and scale[a] <= 1.5 * finest:
                f[a] = 2
        if all(v == 1 for v in f):
            break
        shape = [math.ceil(s / k) for s, k in zip(shape, f)]
        scale = [s * k for s, k in zip(scale, f)]
        steps.append({"shape": list(shape), "scale": list(scale), "factor": list(f)})
    return steps


def _levelEntry(path: str, shape, scale, dtype: str) -> dict:
    return {
        "path": path,
        "shape": [int(s) for s in shape],
        "chunks": [],
        "dtype": dtype,
        "scale": [float(s) for s in scale],
        "translation": [0.0] * 5,
    }


def _pickChannels(spim: dict, wanted) -> tuple[list[dict], list[str]]:
    chans = list(spim["channels"])
    if not wanted:
        return chans, [c["name"] for c in chans]
    if isinstance(wanted, str):
        wanted = [wanted]
    have = [c["name"] for c in chans]
    picked = []
    for w in wanted:
        if w not in have:
            raise ValueError(f"No channel {w} in All_Channels. Available: {', '.join(have)}.")
        picked.append(chans[have.index(w)])
    return picked, [c["name"] for c in picked]


def fromSPIM(
    session: Any,
    rootDir: str,
    *,
    subjectID: str = "",
    elementID: str = "",
    label: str = "",
    channels: list[str] | None = None,
    reductions: list[str] = ("mean", "max"),
    voxelSizeUm: list[float] | None = None,
    minLevelSize: float = 512,
    maxLevels: int = 10,
    pipelineVersion: str = "",
    sourceFileID: str = "",
    tileBudgetBytes: float = 32 * 2**20,
    chunks: Any = None,
    codec: str = "blosc-zstd",
    clevel: int = 5,
    progressFcn: Callable | str | None = "default",
    numWorkers: int = -1,
    prefetchBytes: float = 512 * 2**20,
    asyncPrefetch: bool = True,
    debugLog: str = "",
    profileLog: str = "",
    readWorkers: int = 8,
    splitReadsWithoutPool: bool = False,
    foldLevel1: bool = True,
    resume: dict | None = None,
) -> tuple[Any, list[Any], dict]:
    """Build a lightsheetZarrPyramid from the SmartSPIM acquisition at rootDir.

    Returns ``(pyramidDoc, levelDocs, info)``; ``info`` has ``rootDir``,
    ``channelNames``, ``levels`` (path, reduction, shape, voxelSize, factor
    for every level), ``sourceFileID``, ``sharedLevel0`` and, for a cloud
    target, ``cloud``.
    """
    from ndr.format.smartspim.hasAllChannels import hasAllChannels
    from ndr.format.smartspim.readAllChannelsInfo import readAllChannelsInfo

    from ndi.fun.doc_lightsheet.makeSourceFile import makeSourceFile

    if not str(subjectID).strip():
        raise ValueError("A lightsheetZarrPyramid depends_on a subject; pass 'subjectID'.")
    toCloud = hasattr(session, "streamMembers") and hasattr(session, "commit")
    if not os.path.isdir(rootDir):
        raise FileNotFoundError(f"SmartSPIM folder not found at {rootDir}.")
    if not hasAllChannels(rootDir):
        raise ValueError(
            f"{rootDir} has no usable All_Channels folder (SmartSPIM AutoStitch output, "
            "with slices for every channel). Run AutoStitch, or convert the per-tile data "
            "with spim2zarr and use fromOMEZarr."
        )
    reductions = [str(r) for r in ([reductions] if isinstance(reductions, str) else reductions)]
    if not reductions or not all(r in ("mean", "max") for r in reductions):
        raise ValueError('reductions must be a non-empty subset of {"mean", "max"}.')

    spim = readAllChannelsInfo(rootDir)
    chans, channelNames = _pickChannels(spim, channels)
    nSlices = [int(c["numSlices"]) for c in chans]
    nz = min(nSlices)
    if any(n != nz for n in nSlices):
        warnings.warn(
            f"Channels have different slice counts ({nSlices}); using the first {nz} "
            "slices of each.",
            stacklevel=2,
        )
    slicePaths = [list(c["slicePaths"][:nz]) for c in chans]

    voxel = list(voxelSizeUm) if voxelSizeUm else list(spim.get("voxelSizeUm") or [])
    if len(voxel) != 3 or any((not math.isfinite(v)) or v <= 0 for v in voxel):
        raise ValueError(
            "No [z y x] voxel size: the acquisition metadata.json does not give one. "
            "Pass 'voxelSizeUm', [z y x]."
        )
    dtype = str(spim["dtype"])
    shape0 = [1, len(chans), nz, int(spim["height"]), int(spim["width"])]
    scale0 = [1.0, 1.0] + [float(v) for v in voxel]
    steps = _planLadder(shape0, scale0, minLevelSize, maxLevels)

    level0 = _levelEntry("0", shape0, scale0, dtype)
    levelSources: dict[str, dict] = {
        "0": {"kind": "smartspim", "slicePaths": slicePaths, "dtype": dtype}
    }
    levelInfo = [
        {"path": "0", "reduction": "none", "shape": shape0, "voxelSize": scale0,
         "factor": [1] * 5}
    ]  # fmt: skip
    pyramids = []
    for red in reductions:
        levels = [level0]
        prev = "0"
        for k, st in enumerate(steps, start=1):
            path = f"{red}/{k}"
            levels.append(_levelEntry(path, st["shape"], st["scale"], dtype))
            if toCloud and k == 1:
                levelSources[path] = {
                    "kind": "reduceSmartspim", "slicePaths": slicePaths, "sourceDtype": dtype,
                    "fromShape": shape0, "factor": st["factor"], "reduction": red,
                }  # fmt: skip
            else:
                levelSources[path] = {
                    "kind": "reduce", "fromPath": prev, "factor": st["factor"], "reduction": red,
                }  # fmt: skip
            levelInfo.append(
                {"path": path, "reduction": red, "shape": st["shape"],
                 "voxelSize": st["scale"], "factor": st["factor"]}
            )  # fmt: skip
            prev = path
        pyramids.append({"name": red, "type": red, "axes": _AXES, "levels": levels})

    if toCloud:
        session.requireSubject(subjectID)
        if elementID:
            session.requireDocument(elementID)
        if sourceFileID:
            session.requireDocument(sourceFileID)
    if not sourceFileID:
        srcDoc = makeSourceFile(session, rootDir)
        session.database_add(srcDoc)
        sourceFileID = srcDoc.id
    if not label:
        label = os.path.basename(os.path.normpath(rootDir))
    progress = resolveProgressCallback(progressFcn, f"Building pyramid: {label}", "spim")

    pyramidDoc, levelDocs, sharedLevel0 = makePyramid(
        session,
        pyramids,
        reductions,
        subjectID=subjectID,
        elementID=elementID,
        sourceFileID=sourceFileID,
        pipelineVersion=pipelineVersion,
        label=label,
        channelNames=",".join(channelNames),
        tileBudgetBytes=tileBudgetBytes,
        chunks=chunks,
        materializeChunks=True,
        levelSources=levelSources,
        codec=codec,
        clevel=clevel,
        progressFcn=progress,
        numWorkers=numWorkers,
        prefetchBytes=prefetchBytes,
        asyncPrefetch=asyncPrefetch,
        debugLog=debugLog,
        profileLog=profileLog,
        readWorkers=readWorkers,
        splitReadsWithoutPool=splitReadsWithoutPool,
        foldLevel1=foldLevel1,
        resume=resume,
    )
    info: dict[str, Any] = {
        "rootDir": str(rootDir),
        "channelNames": channelNames,
        "levels": levelInfo,
        "sourceFileID": sourceFileID,
        "sharedLevel0": sharedLevel0,
    }
    if toCloud:
        info["cloud"] = session.commit()
    return pyramidDoc, levelDocs, info
