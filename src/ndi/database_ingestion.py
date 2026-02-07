"""
ndi.database.ingestion - File ingestion and expulsion for NDI documents.

MATLAB equivalents: +ndi/+database/+implementations/+fun/ingest.m,
    ingest_plan.m, expell.m, expell_plan.m

Two-phase operation:
  1. Plan phase: validate and build operation lists
  2. Execute phase: copy/delete files
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


def ingest_plan(
    document: Any,
    ingestion_directory: str,
) -> tuple[list[str], list[str], list[str]]:
    """Plan file ingestion for a document.

    MATLAB equivalent: ndi.database.implementations.fun.ingest_plan

    Examines the document's file_info locations to determine which
    files should be copied into the ingestion directory and which
    originals should be deleted afterward.

    Args:
        document: An ndi.Document object.
        ingestion_directory: Target directory for ingested files.

    Returns:
        Tuple of (source_files, dest_files, to_delete_files).
    """
    props = document.document_properties if hasattr(document, "document_properties") else document
    if not isinstance(props, dict):
        return [], [], []

    source_files: list[str] = []
    dest_files: list[str] = []
    to_delete: list[str] = []

    files = props.get("files", {})
    if not isinstance(files, dict):
        return [], [], []

    ing_dir = Path(ingestion_directory)

    for fi in files.get("file_info", []):
        if not isinstance(fi, dict):
            continue
        for loc in fi.get("locations", []):
            if not isinstance(loc, dict):
                continue

            should_ingest = loc.get("ingest", False)
            delete_original = loc.get("delete_original", False)
            source = loc.get("location", "")
            uid = loc.get("uid", "")

            if should_ingest and source and uid:
                dest = str(ing_dir / uid)
                source_files.append(source)
                dest_files.append(dest)

            if delete_original and source:
                to_delete.append(source)

    return source_files, dest_files, to_delete


def ingest(
    source_files: list[str],
    dest_files: list[str],
    to_delete: list[str],
) -> tuple[bool, str]:
    """Execute file ingestion: copy sources to destinations, then delete originals.

    MATLAB equivalent: ndi.database.implementations.fun.ingest

    Args:
        source_files: Source file paths.
        dest_files: Destination file paths (matched by index).
        to_delete: Files to delete after successful copy.

    Returns:
        Tuple of (success, error_message).
    """
    # Copy files
    for src, dst in zip(source_files, dest_files):
        try:
            src_path = Path(src)
            dst_path = Path(dst)
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src_path), str(dst_path))
        except Exception as exc:
            return False, f"Copying {src} -> {dst}: {exc}"

    # Delete originals
    for f in to_delete:
        try:
            Path(f).unlink(missing_ok=True)
        except Exception as exc:
            return False, f"Deleting {f}: {exc}"

    return True, ""


def expell_plan(
    document: Any,
    ingestion_directory: str,
) -> list[str]:
    """Plan file expulsion (removal) for a document.

    MATLAB equivalent: ndi.database.implementations.fun.expell_plan

    Returns:
        List of file paths to delete from the ingestion directory.
    """
    props = document.document_properties if hasattr(document, "document_properties") else document
    if not isinstance(props, dict):
        return []

    to_delete: list[str] = []
    files = props.get("files", {})
    if not isinstance(files, dict):
        return []

    ing_dir = Path(ingestion_directory)

    for fi in files.get("file_info", []):
        if not isinstance(fi, dict):
            continue
        for loc in fi.get("locations", []):
            if not isinstance(loc, dict):
                continue
            if loc.get("ingest", False):
                uid = loc.get("uid", "")
                if uid:
                    to_delete.append(str(ing_dir / uid))

    return to_delete


def expell(to_delete: list[str]) -> tuple[bool, str]:
    """Execute file expulsion: delete ingested files.

    MATLAB equivalent: ndi.database.implementations.fun.expell

    Returns:
        Tuple of (success, error_message).
    """
    if not to_delete:
        return True, ""

    for f in to_delete:
        try:
            Path(f).unlink(missing_ok=True)
        except Exception as exc:
            return False, f"Deleting {f}: {exc}"

    return True, ""
