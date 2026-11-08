"""
ndi.fun.doc_lightsheet.makeSourceFile

MATLAB equivalent: +ndi/+fun/+doc/+lightsheet/makeSourceFile.m

Describe (fileReference), or attach (generic_file), the source OME-Zarr a
lightsheet pyramid was built from.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import pydantic

from ...document import ndi_document
from .. import file as ndi_file

__all__ = ["makeSourceFile"]


def _datenum(when: datetime | None) -> float:
    """A datetime as a MATLAB datenum in local time; 0 when unknown."""
    if when is None:
        return 0
    local = when.astimezone() if when.tzinfo is not None else when
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return local.toordinal() + 366 + (local - midnight).total_seconds() / 86400


@pydantic.validate_call(config={"arbitrary_types_allowed": True})
def makeSourceFile(
    session: Any,
    filename: str | os.PathLike,
    *,
    checksum: bool = True,
    attachFile: bool = False,
    formatOntology: str = "",
    documentID: str = "",
) -> ndi_document:
    """Make the document a lightsheetZarrPyramid's ``source_file_id`` names.

    MATLAB equivalent: ``ndi.fun.doc.lightsheet.makeSourceFile(session,
    filename, 'checksum', ..., 'attachFile', ..., 'formatOntology', ...,
    'documentID', ...)``

    DESCRIBING IS NOT ATTACHING, and the default is to describe: an OME-Zarr
    store is a directory tree of many GB, so the document records its name,
    size, checksum and dates rather than a copy.

    * ``attachFile=False`` -> a ``fileReference`` document, holding no file.
    * ``attachFile=True``  -> a ``generic_file`` document holding
      ``generic_file.ext``. Only valid for a plain file.

    Args:
        session: the ndi session the document belongs to.
        filename: a file or a directory (an OME-Zarr store).
        checksum: compute the MD5 fingerprint -- of ``.zattrs`` for a
            directory, of the file itself otherwise. False leaves the
            checksum (and checksumAlgorithm) empty.
        attachFile: ingest a copy of the file (generic_file).
        formatOntology: an ontology term for the format; left empty rather
            than guessed.
        documentID: a document this file is about, for the class's own
            ``document_id`` dependency.

    Returns:
        The document, NOT yet added to the database; the caller adds it.

    Raises:
        FileNotFoundError: no file or directory at *filename* (MATLAB:
            ``NDI:lightsheet:makeSourceFile:noSuchPath``).
        ValueError: ``attachFile=True`` for a directory (MATLAB:
            ``NDI:lightsheet:makeSourceFile:cannotAttachDirectory``).
    """
    filename = os.fspath(filename)
    isDir = os.path.isdir(filename)
    isFile = not isDir and os.path.isfile(filename)
    if not isDir and not isFile:
        raise FileNotFoundError(f"No file or directory at {filename}.")
    if attachFile and isDir:
        raise ValueError(
            "attachFile is only valid for a plain file. An OME-Zarr store is a "
            "directory tree and is described, not ingested."
        )

    leafname = os.path.basename(os.path.normpath(filename))

    md5 = ""
    algorithm = ""
    if checksum:
        if isDir:
            zattrs = os.path.join(filename, ".zattrs")
            if os.path.isfile(zattrs):
                md5 = ndi_file.MD5(zattrs)
        else:
            md5 = ndi_file.MD5(filename)
        if md5:
            algorithm = "MD5"

    created = 0
    updated = 0
    try:
        created = _datenum(ndi_file.dateCreated(filename))
        updated = _datenum(ndi_file.dateUpdated(filename))
    except Exception:  # noqa: BLE001 - dates are best effort, as in MATLAB
        pass

    # session.newdocument rather than MATLAB's ``ndi.document(...) +
    # session.newdocument()``: Python's ``+`` keeps the left operand's base,
    # so the session id would be lost.
    if attachFile:
        s = {
            "filename": leafname,
            "formatOntology": formatOntology,
            "dateCreated": created,
            "dateUpdated": updated,
            "checksum": md5,
        }
        doc = session.newdocument("generic_file", generic_file=s)
        doc = doc.add_file("generic_file.ext", filename, delete_original=False)
    else:
        fileSize = os.path.getsize(filename) if isFile else 0
        s = {
            "filename": leafname,
            "originalPath": filename,
            "formatOntology": formatOntology,
            "dateCreated": created,
            "dateUpdated": updated,
            "fileSize": fileSize,
            "checksum": md5,
            "checksumAlgorithm": algorithm,
        }
        doc = session.newdocument("fileReference", fileReference=s)

    if documentID:
        doc = doc.set_dependency_value("document_id", documentID)
    return doc
