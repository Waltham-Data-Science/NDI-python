"""
ndi.cloud.sync.index - Sync index for tracking local/remote state.

Persists to ``<dataset_path>/.ndi/sync/index.json``.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


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

        The same ``.ndi/sync/index.json`` file is shared with MATLAB, which
        writes camelCase keys (``localDocumentIdsLastSync`` etc.). Earlier
        Python builds wrote snake_case keys to the same file. Both dialects
        are read here so a dataset touched by either client is understood;
        :meth:`write` always emits the camelCase form MATLAB expects.
        """
        index_file = Path(dataset_path) / ".ndi" / "sync" / "index.json"
        if not index_file.exists():
            return cls()
        try:
            data = json.loads(index_file.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            # A truncated/corrupt index (e.g. a crash mid-write, or a reader that
            # caught the old zero-byte window) must not propagate as an unhandled
            # traceback out of every sync entry point. Treat it as empty; the next
            # write rewrites it atomically.
            logger.warning("Corrupt sync index at %s (%s); treating as empty", index_file, exc)
            return cls()

        def _pick(camel: str, snake: str) -> Any:
            if camel in data:
                return data[camel]
            return data.get(snake, [])

        return cls(
            local_doc_ids_last_sync=_pick("localDocumentIdsLastSync", "local_doc_ids_last_sync"),
            remote_doc_ids_last_sync=_pick("remoteDocumentIdsLastSync", "remote_doc_ids_last_sync"),
            last_sync_timestamp=(
                data.get("lastSyncTimestamp") or data.get("last_sync_timestamp") or ""
            ),
        )

    def write(self, dataset_path: Path) -> None:
        """Write the sync index to ``<dataset_path>/.ndi/sync/index.json``.

        Writes the MATLAB-compatible camelCase keys so a dataset synced by
        alternating Python and MATLAB clients sees a consistent index;
        mismatched dialects previously caused a full re-transfer (audit C2).

        Writes atomically: a sibling temp file is written + fsync'd and then
        os.replace()'d onto index.json. os.replace is atomic on POSIX and
        Windows, so a concurrent reader (or a second writer) never sees a
        zero-byte or half-written index. The previous ``open(..., "w")``
        truncated the file to zero bytes BEFORE taking the flock, so the lock
        could not actually protect against that window — and importing fcntl at
        module scope broke Windows despite the "OS Independent" classifier.
        """
        index_dir = Path(dataset_path) / ".ndi" / "sync"
        index_dir.mkdir(parents=True, exist_ok=True)
        index_file = index_dir / "index.json"
        content = json.dumps(
            {
                "localDocumentIdsLastSync": self.local_doc_ids_last_sync,
                "remoteDocumentIdsLastSync": self.remote_doc_ids_last_sync,
                "lastSyncTimestamp": self.last_sync_timestamp,
            },
            indent=2,
        )
        fd, tmp_name = tempfile.mkstemp(dir=index_dir, prefix=".index.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, index_file)
        except BaseException:
            # Never leave a stray temp file behind on failure.
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
