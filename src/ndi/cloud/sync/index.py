"""
ndi.cloud.sync.index - Sync index for tracking local/remote state.

Persists to ``<dataset_path>/.ndi/sync/index.json``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List


@dataclass
class SyncIndex:
    """Tracks which document IDs were synced in the last operation."""

    local_doc_ids_last_sync: List[str] = field(default_factory=list)
    remote_doc_ids_last_sync: List[str] = field(default_factory=list)
    last_sync_timestamp: str = ''

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @classmethod
    def read(cls, dataset_path: Path) -> 'SyncIndex':
        """Read the sync index from ``<dataset_path>/.ndi/sync/index.json``."""
        index_file = Path(dataset_path) / '.ndi' / 'sync' / 'index.json'
        if not index_file.exists():
            return cls()
        data = json.loads(index_file.read_text())
        return cls(
            local_doc_ids_last_sync=data.get('local_doc_ids_last_sync', []),
            remote_doc_ids_last_sync=data.get('remote_doc_ids_last_sync', []),
            last_sync_timestamp=data.get('last_sync_timestamp', ''),
        )

    def write(self, dataset_path: Path) -> None:
        """Write the sync index to ``<dataset_path>/.ndi/sync/index.json``."""
        index_dir = Path(dataset_path) / '.ndi' / 'sync'
        index_dir.mkdir(parents=True, exist_ok=True)
        index_file = index_dir / 'index.json'
        index_file.write_text(json.dumps({
            'local_doc_ids_last_sync': self.local_doc_ids_last_sync,
            'remote_doc_ids_last_sync': self.remote_doc_ids_last_sync,
            'last_sync_timestamp': self.last_sync_timestamp,
        }, indent=2))

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(
        self,
        local_ids: List[str],
        remote_ids: List[str],
    ) -> None:
        """Update both ID lists and set the timestamp to now."""
        self.local_doc_ids_last_sync = list(local_ids)
        self.remote_doc_ids_last_sync = list(remote_ids)
        self.last_sync_timestamp = datetime.now(timezone.utc).isoformat()
