"""ndi.job.lightsheet_to_cloud - build a lightsheet pyramid straight into a cloud session.

MATLAB counterpart: ``+ndi/+job/LightsheetToCloud.m`` (kind
``'lightsheetToCloud'``).

``ndi_job_LightsheetToCloud.create(choices)`` takes the Lightsheet Manager's
Add choices (MATLAB ``ndi.gui.app.LightsheetManager.addChoices``) with
destination ``'cloud'``; ``run()`` builds the pyramid with
:func:`ndi.fun.doc_lightsheet.fromSPIM` or :func:`fromOMEZarr` through an
:class:`ndi.cloud.session_writer.SessionWriter`, which streams the chunks as
they are made.

RESUMING. Every document the writer uploads is also saved in the job's
folder (``documents/``), with its series member uids. If the run stops --
paused, a lost connection, a slice server that stayed down, Ctrl+C, a crash
-- the next ``run()`` adopts the pyramid and the levels already in the cloud
and builds only their missing chunks. The writer's cache (the level a
coarser level is reduced from) is in the job's folder too. The job record and
the folder are shared with NDI-matlab, so a build MATLAB started can be
resumed here, and the other way round.

PROFILE. Every super-block's timings go to ``profile.csv`` in the job's
folder (appended across runs; see ``BuildProfile``).

WORKERS. ``spec['numWorkers']`` threads compress (-1: one per core); a
SmartSPIM build reads slices on ``spec['readWorkers']`` more (optional,
default 8). Edit them in job.json while the job is paused.

RESTART starts over with a new pyramid; the one the earlier run left in the
cloud stays there, labelled "(uploading)".
"""

from __future__ import annotations

import json
import os
import shutil
from typing import Any

from ndi.job.job import ndi_job_Job

__all__ = ["ndi_job_LightsheetToCloud", "addPlan", "addMessage"]


def _field(s: dict, name: str, dflt: Any) -> Any:
    return s[name] if isinstance(s, dict) and name in s else dflt


def _bullets(items: list[str]) -> str:
    return "\n".join(f"  - {t}" for t in items)


def _isWhole(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and float(v) == round(v)


def addPlan(choices: dict) -> dict:
    """What Add would do, or everything still missing (pure; nothing is read or written).

    MATLAB: ``ndi.gui.app.LightsheetManager.addPlan``. ``errors`` lists every
    problem at once; ``warnings`` what will happen anyway; ``ingest`` is
    'fromSPIM' or 'fromOMEZarr'; ``where`` says where the image goes.
    """
    F = lambda name, dflt: _field(choices, name, dflt)  # noqa: E731
    E: list[str] = []
    W: list[str] = []
    plan: dict[str, Any] = {"errors": E, "warnings": W, "ingest": "", "where": "",
                            "choices": choices}  # fmt: skip
    toCloud = F("destination", "local") == "cloud"
    if toCloud:
        if not F("datasetId", ""):
            E.append("Choose the NDI Cloud dataset.")
        if not F("sessionId", ""):
            E.append(
                "Choose the session in that dataset. An image goes into a session, not into "
                "the dataset itself."
            )
        plan["where"] = (
            f"session {F('sessionReference', '')} of the NDI Cloud dataset "
            f"{F('datasetName', '')}"
        )
    else:
        plan["where"] = "this session"
    if not F("subjectID", ""):
        E.append("Choose the subject the image is of, or add a new subject to the session.")
    kind = str(F("sourceKind", "") or "")
    if kind == "smartspim":
        plan["ingest"] = "fromSPIM"
    elif kind == "omezarr":
        plan["ingest"] = "fromOMEZarr"
    elif not str(F("sourcePath", "") or "").strip():
        E.append("Choose the image folder: a SmartSPIM acquisition or an OME-Zarr store.")
    else:
        E.append("The image folder is not a SmartSPIM acquisition or an OME-Zarr store.")

    vox = F("voxelSizeUm", None) or []
    if vox and (
        len(vox) != 3
        or any(not isinstance(v, (int, float)) or not (float(v) > 0) or v != v or v == float("inf")
               for v in vox)
    ):  # fmt: skip
        E.append(
            "Voxel size must be three positive numbers (z y x, in micrometers), or empty to "
            "read it from the acquisition."
        )
    if vox and plan["ingest"] == "fromOMEZarr":
        W.append("Voxel size is ignored for an OME-Zarr store: the store records its own.")

    cl = F("clevel", 5)
    if not _isWhole(cl) or cl < 1 or cl > 9:
        E.append("Compression must be a whole number from 1 to 9.")
    elif cl == 9:
        W.append(
            "Compression 9 is Zstd's slowest setting: many times slower than 8, with much more "
            "memory per worker, for files only a percent or two smaller."
        )
    red = F("reductions", ["mean", "max"])
    red = [red] if isinstance(red, str) else list(red)
    if plan["ingest"] == "fromSPIM":
        if not red or not all(r in ("mean", "max") for r in red):
            E.append("Reductions must be mean, max, or both.")
    elif plan["ingest"] == "fromOMEZarr" and set(red) != {"mean", "max"}:
        W.append(
            "Reductions are ignored for an OME-Zarr store: it brings the ladders it was made "
            "with."
        )
    nw = F("numWorkers", -1)
    if not _isWhole(nw) or (nw < 1 and nw != -1):
        E.append("Workers must be a whole number, 1 or more.")
    if toCloud:
        W.append(
            "Every image chunk is built on this computer and uploaded as it is made. A large "
            "volume takes hours; the disk holds only the chunks in flight plus one coarser "
            "level at a time."
        )
    else:
        W.append(
            "Every image chunk is built and stored in this session. A large volume takes "
            "hours, and needs as much free disk as the chunks."
        )
    return plan


def addMessage(plan: dict) -> str:
    """The confirmation before the wait, or what is missing. MATLAB: LightsheetManager.addMessage."""
    if plan["errors"]:
        return "Not ready yet:\n\n" + _bullets(plan["errors"])
    c = plan["choices"]
    label = c.get("label") or os.path.basename(os.path.normpath(str(c["sourcePath"])))
    msg = (
        f'Add the image\n  {c["sourcePath"]}\nas "{label}", of subject '
        f'{c.get("subjectName", "")}, to {plan["where"]}?'
    )
    how = f"Compression {int(_field(c, 'clevel', 5))}"
    if plan["ingest"] == "fromSPIM":
        red = _field(c, "reductions", ["mean", "max"])
        red = [red] if isinstance(red, str) else list(red)
        how = f"{how}, {' and '.join(red)} ladder(s)"
    nw = _field(c, "numWorkers", -1)
    if nw > 1:
        how = f"{how}, {int(nw)} parallel workers"
    elif nw == 1:
        how = f"{how}, one worker"
    msg = f"{msg}\n{how}."
    if plan["warnings"]:
        msg = f"{msg}\n\n{_bullets(plan['warnings'])}"
    return msg


class ndi_job_LightsheetToCloud(ndi_job_Job):
    """A lightsheet build streamed to a session of an NDI Cloud dataset, resumable."""

    Kind = "lightsheetToCloud"

    def __init__(self) -> None:
        super().__init__()
        # Test hook: extra keyword options for fromSPIM / fromOMEZarr (small
        # chunks and reads, so a test can pause part-way). Not saved.
        self.ExtraIngestArgs: dict[str, Any] = {}

    @classmethod
    def create(cls, choices: dict) -> ndi_job_LightsheetToCloud:
        """A new job for CHOICES (destination 'cloud'), saved and queued."""
        if _field(choices, "destination", "") != "cloud":
            raise ValueError("This job adds to an NDI Cloud session; choose destination 'cloud'.")
        plan = addPlan(choices)
        if plan["errors"]:
            raise ValueError(addMessage(plan))
        label = choices.get("label") or os.path.basename(
            os.path.normpath(str(choices["sourcePath"]))
        )
        job = cls()
        job.initialize(f"{label} to {plan['where']}", choices)
        return job

    def work(self) -> None:
        from ndi.cloud.session_writer import SessionWriter
        from ndi.fun.doc_lightsheet.fromOMEZarr import fromOMEZarr
        from ndi.fun.doc_lightsheet.fromSPIM import fromSPIM

        c = self.spec
        folder = str(self.folder())
        writer = SessionWriter(
            c["datasetId"],
            c["sessionId"],
            cacheDir=os.path.join(folder, "cache"),
            keepLocalCopies=True,
            onUpload=self._recordUpload,
            api=self.Api,
        )
        try:
            args: dict[str, Any] = {
                "subjectID": c["subjectID"],
                "clevel": int(c.get("clevel", 5)),
                "numWorkers": int(c.get("numWorkers", -1)),
                "progressFcn": lambda f, t: self.beat(f, t),
                "profileLog": os.path.join(folder, "profile.csv"),
            }
            if c.get("label"):
                args["label"] = c["label"]
            if c.get("readWorkers") and c.get("sourceKind") == "smartspim":
                args["readWorkers"] = int(c["readWorkers"])
            args.update(self.ExtraIngestArgs)
            resume, sourceFileID = self._resumeFromSaved()
            if sourceFileID:
                args["sourceFileID"] = sourceFileID
            if resume is not None:
                self.beat(self.progress, "Resuming: asking the cloud what it already has...")
                args["resume"] = resume
            kind = str(c.get("sourceKind", ""))
            if kind == "smartspim":
                red = c.get("reductions", ["mean", "max"])
                args["reductions"] = [red] if isinstance(red, str) else list(red)
                if c.get("voxelSizeUm"):
                    args["voxelSizeUm"] = [float(v) for v in c["voxelSizeUm"]]
                _, _, info = fromSPIM(writer, c["sourcePath"], **args)
            elif kind == "omezarr":
                _, _, info = fromOMEZarr(
                    writer, c["sourcePath"], materializeChunks=True, codec="blosc-zstd", **args
                )
            else:
                raise ValueError(f"Unknown source kind '{kind}'.")
        finally:
            delete = getattr(writer, "delete", None)
            if callable(delete):
                delete()
        self.setCheckpoint("report", info["cloud"])
        shutil.rmtree(os.path.join(folder, "cache"), ignore_errors=True)

    def onRestart(self) -> None:
        for sub in ("documents", "cache"):
            shutil.rmtree(self.folder() / sub, ignore_errors=True)

    def _recordUpload(self, doc: Any) -> None:
        """Keep each uploaded document (with its series member uids) for a later run."""
        d = self.folder() / "documents"
        d.mkdir(parents=True, exist_ok=True)
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        (d / f"{props['base']['id']}.json").write_text(json.dumps(props))

    def _resumeFromSaved(self) -> tuple[dict | None, str]:
        """What an earlier run of this job (in either language) put in the cloud."""
        from ndi.document import ndi_document

        d = self.folder() / "documents"
        pyramid = None
        levels: list[Any] = []
        sourceFileID = ""
        for f in sorted(d.glob("*.json")) if d.is_dir() else []:
            props = json.loads(f.read_text())
            doc = ndi_document(props)
            cls = str(props.get("document_class", {}).get("class_name", ""))
            if cls == "lightsheetZarrPyramid":
                pyramid = doc
            elif cls == "lightsheetZarrLevel":
                levels.append(doc)
            elif cls == "fileReference":
                sourceFileID = doc.id
        if pyramid is None:
            return None, sourceFileID
        return {"pyramidDoc": pyramid, "levelDocs": levels}, sourceFileID


# The kinds NDI ships are registered already (MATLAB: ndi.job.Job.registry).
ndi_job_Job.register(ndi_job_LightsheetToCloud.Kind, ndi_job_LightsheetToCloud)
