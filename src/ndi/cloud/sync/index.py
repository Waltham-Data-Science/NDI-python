"""
ndi.cloud.sync.index - Sync index for tracking local/remote state.

Persists to ``<dataset_path>/.ndi/sync/index.json``.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

#: The keys MATLAB's ``createSyncIndexStruct`` puts in the JSON. This file
#: lives inside the dataset at ``.ndi/sync/index.json``, so it is an
#: interchange format between the two languages, not a private Python file.
_MATLAB_KEYS = (
    "localDocumentIdsLastSync",
    "remoteDocumentIdsLastSync",
    "lastSyncTimestamp",
)

#: What Python wrote before it used MATLAB's names. Still READ, so an index
#: already on disk from an older NDI-python keeps working.
_LEGACY_KEYS = (
    "local_doc_ids_last_sync",
    "remote_doc_ids_last_sync",
    "last_sync_timestamp",
)


def index_filepath(dataset_path: Path, mode: str = "read", verbose: bool = False) -> Path:
    """Return ``<dataset_path>/.ndi/sync/index.json``.

    MATLAB equivalent: ``ndi.cloud.sync.internal.index.getIndexFilepath``.
    As there, ``mode='write'`` creates the sync directory and ``mode='read'``
    does not -- reading must not leave a directory behind in a dataset that
    has never been synced.
    """
    if mode not in ("read", "write"):
        raise ValueError(f"mode must be 'read' or 'write', not {mode!r}")
    sync_dir = Path(dataset_path) / ".ndi" / "sync"
    if mode == "write" and not sync_dir.is_dir():
        if verbose:
            print(f"Creating sync directory: {sync_dir}")
        sync_dir.mkdir(parents=True, exist_ok=True)
    return sync_dir / "index.json"


def _pick(data: dict, matlab_key: str, legacy_key: str, default):
    """MATLAB's key wins; the legacy Python spelling is the fallback."""
    if matlab_key in data:
        return data[matlab_key]
    return data.get(legacy_key, default)


@dataclass
class SyncIndex:
    """Tracks which document IDs were synced in the last operation."""

    local_doc_ids_last_sync: list[str] = field(default_factory=list)
    remote_doc_ids_last_sync: list[str] = field(default_factory=list)
    last_sync_timestamp: str = ""

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @classmethod
    def read(cls, dataset_path: Path) -> SyncIndex:
        """Read the sync index from ``<dataset_path>/.ndi/sync/index.json``.

        No lock is taken and none is needed: :meth:`write` swaps the file in
        atomically, so a reader racing a writer sees either the whole old
        index or the whole new one.

        Accepts MATLAB's key names and the legacy Python ones. Reading an
        index this cannot understand yields an empty index, which every
        caller treats as "never synced" -- so a spelling it does not know is
        not a cosmetic problem, it silently rewrites what the next sync does.
        """
        index_file = index_filepath(dataset_path, "read")
        if not index_file.exists():
            return cls()
        data = json.loads(index_file.read_text(encoding="utf-8"))
        local_m, remote_m, stamp_m = _MATLAB_KEYS
        local_l, remote_l, stamp_l = _LEGACY_KEYS
        return cls(
            local_doc_ids_last_sync=_pick(data, local_m, local_l, []),
            remote_doc_ids_last_sync=_pick(data, remote_m, remote_l, []),
            last_sync_timestamp=_pick(data, stamp_m, stamp_l, ""),
        )

    def write(self, dataset_path: Path) -> None:
        """Write the sync index to ``<dataset_path>/.ndi/sync/index.json``.

        The write is atomic. The JSON goes to a temporary file in the same
        directory and is then moved into place with :func:`os.replace`, which
        replaces the target in a single step on POSIX and on Windows. A
        concurrent reader therefore never observes a partial file, and a
        crash mid-write leaves the previous index intact.

        This replaces an earlier ``flock`` scheme that could not work:
        ``open(path, "w")`` truncates before the lock is taken, so the old
        contents were already gone by the time the lock was held. Dropping it
        also removes the module-level ``fcntl`` import, which made this module
        -- and everything that imports the sync package -- unimportable on
        Windows.

        The keys written are MATLAB's, so the same dataset can be synced
        from either language.
        """
        index_file = index_filepath(dataset_path, "write")
        index_dir = index_file.parent
        local_m, remote_m, stamp_m = _MATLAB_KEYS
        content = json.dumps(
            {
                local_m: self.local_doc_ids_last_sync,
                remote_m: self.remote_doc_ids_last_sync,
                stamp_m: self.last_sync_timestamp,
            },
            indent=2,
        )

        # The temporary file must live in the destination directory:
        # os.replace is only atomic within a single filesystem.
        fd, tmp_name = tempfile.mkstemp(dir=index_dir, prefix="index.json.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, index_file)
        except BaseException:
            # Do not leave a stray temp file in the dataset on failure.
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(
        self,
        local_ids: list[str],
        remote_ids: list[str],
    ) -> None:
        """Update both ID lists and set the timestamp to now.

        The timestamp is MATLAB's format, ``yyyy-MM-dd'T'HH:mm:ssZZZZ`` --
        local time with an explicit numeric offset and second resolution,
        as ``createSyncIndexStruct`` writes it. Local time is MATLAB's
        choice; the offset is written out, so the value is still unambiguous.
        """
        self.local_doc_ids_last_sync = list(local_ids)
        self.remote_doc_ids_last_sync = list(remote_ids)
        self.last_sync_timestamp = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
