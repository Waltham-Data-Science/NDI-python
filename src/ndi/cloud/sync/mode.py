"""
ndi.cloud.sync.mode - Sync modes and options.

MATLAB equivalent: sync mode constants used across +ndi/+cloud/+sync/*.m
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SyncMode(Enum):
    """Synchronisation direction / strategy."""

    DOWNLOAD_NEW = "download_new"
    MIRROR_FROM_REMOTE = "mirror_from_remote"
    UPLOAD_NEW = "upload_new"
    MIRROR_TO_REMOTE = "mirror_to_remote"
    TWO_WAY_SYNC = "two_way_sync"


@dataclass
class SyncOptions:
    """Options controlling sync behaviour.

    Attributes:
        sync_files: Whether to sync associated binary files.
        verbose: Print progress information.
        dry_run: Report what would be done without making changes.
        file_upload_strategy: ``'batch'`` (zip) or ``'serial'``.
        file_batch_size_limit: Maximum size in bytes of each zip batch when
            ``file_upload_strategy`` is ``'batch'``. ``None`` (default) uses
            the preference ``Cloud.Upload.Max_File_Batch_Size`` (250 MB unless
            changed; see :mod:`ndi.preferences`), read when the upload runs.
    """

    sync_files: bool = False
    verbose: bool = True
    dry_run: bool = False
    file_upload_strategy: str = "batch"
    file_batch_size_limit: float | None = None
