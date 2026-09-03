"""
ndi.cloud.sync.index - Sync index for tracking local/remote state.

Persists to ``<dataset_path>/.ndi/sync/index.json``.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


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
        """
        index_file = Path(dataset_path) / ".ndi" / "sync" / "index.json"
        if not index_file.exists():
            return cls()
        data = json.loads(index_file.read_text(encoding="utf-8"))
        return cls(
            local_doc_ids_last_sync=data.get("local_doc_ids_last_sync", []),
            remote_doc_ids_last_sync=data.get("remote_doc_ids_last_sync", []),
            last_sync_timestamp=data.get("last_sync_timestamp", ""),
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
        """
        index_dir = Path(dataset_path) / ".ndi" / "sync"
        index_dir.mkdir(parents=True, exist_ok=True)
        index_file = index_dir / "index.json"
        content = json.dumps(
            {
                "local_doc_ids_last_sync": self.local_doc_ids_last_sync,
                "remote_doc_ids_last_sync": self.remote_doc_ids_last_sync,
                "last_sync_timestamp": self.last_sync_timestamp,
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
        """Update both ID lists and set the timestamp to now."""
        self.local_doc_ids_last_sync = list(local_ids)
        self.remote_doc_ids_last_sync = list(remote_ids)
        self.last_sync_timestamp = datetime.now(timezone.utc).isoformat()
