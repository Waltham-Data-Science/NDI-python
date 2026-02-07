"""
ndi.session.sessiontable - Persistent registry of NDI sessions.

Manages a local tab-delimited file mapping session IDs to filesystem paths,
providing quick access to recently opened or registered NDI sessions.

MATLAB equivalent: src/ndi/+ndi/+session/sessiontable.m
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class SessionTable:
    """
    Persistent local registry of NDI sessions.

    Stores (session_id, path) pairs in a tab-delimited text file so
    that sessions can be quickly located by ID without providing full
    paths each time.

    The table file lives at ``~/.ndi/preferences/local_sessiontable.txt``
    by default.

    Example:
        >>> table = SessionTable()
        >>> table.add_entry('abc123', '/data/experiment1')
        >>> table.get_session_path('abc123')
        '/data/experiment1'
    """

    _REQUIRED_FIELDS = ('session_id', 'path')

    def __init__(self, table_path: Optional[Path] = None):
        """
        Create a SessionTable instance.

        Args:
            table_path: Override the default table file location.
                        If None, uses ``local_table_filename()``.
        """
        self._table_path = (
            Path(table_path) if table_path is not None
            else self.local_table_filename()
        )

    @staticmethod
    def local_table_filename() -> Path:
        """Return the default session table file path."""
        return Path.home() / '.ndi' / 'preferences' / 'local_sessiontable.txt'

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_session_table(self) -> List[Dict[str, str]]:
        """
        Read and return the session table.

        Returns:
            List of dicts with keys ``session_id`` and ``path``.
            Returns an empty list if the file does not exist or is empty.
        """
        if not self._table_path.is_file():
            return []

        try:
            entries: List[Dict[str, str]] = []
            with open(self._table_path, 'r', newline='') as f:
                reader = csv.DictReader(f, delimiter='\t')
                if reader.fieldnames is None:
                    return []
                for row in reader:
                    sid = row.get('session_id', '')
                    path = row.get('path', '')
                    if not isinstance(sid, str):
                        sid = str(sid)
                    if not isinstance(path, str):
                        path = str(path)
                    entries.append({'session_id': sid, 'path': path})
            return entries
        except Exception:
            return []

    def get_session_path(self, session_id: str) -> Optional[str]:
        """
        Look up the filesystem path for *session_id*.

        Args:
            session_id: The session identifier to search for.

        Returns:
            Path string if found, None otherwise.
        """
        for entry in self.get_session_table():
            if entry['session_id'] == session_id:
                return entry['path']
        return None

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def add_entry(self, session_id: str, path: str) -> None:
        """
        Add or replace an entry in the session table.

        If *session_id* already exists it is replaced with the new *path*.

        Args:
            session_id: Session identifier (must be a non-empty string).
            path: Filesystem path to the session directory.

        Raises:
            ValueError: If session_id or path is empty.
        """
        if not session_id:
            raise ValueError("session_id must be a non-empty string")
        if not path:
            raise ValueError("path must be a non-empty string")

        # Remove existing entry for this ID (if any), then append
        self.remove_entry(session_id)
        entries = self.get_session_table()
        entries.append({'session_id': session_id, 'path': path})
        self._write_table(entries)

    def remove_entry(self, session_id: str) -> None:
        """
        Remove the entry with the given *session_id*.

        Does nothing if the ID is not present.
        """
        entries = self.get_session_table()
        filtered = [e for e in entries if e['session_id'] != session_id]
        if len(filtered) != len(entries):
            self._write_table(filtered)

    def clear(self, make_backup: bool = False) -> None:
        """
        Remove all entries from the session table.

        Args:
            make_backup: If True, create a backup before clearing.
        """
        if make_backup:
            self.backup()
        self._write_table([])

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def check_table(self) -> Tuple[bool, List[Dict[str, Any]]]:
        """
        Validate the session table and check path accessibility.

        Returns:
            Tuple of (valid, results):
            - valid: True if the table has the correct format
            - results: List of dicts with ``exists`` key for each entry
        """
        entries = self.get_session_table()
        valid, _ = self.is_valid_table(entries)
        if not valid:
            return False, []

        results = []
        for entry in entries:
            results.append({
                'session_id': entry['session_id'],
                'path': entry['path'],
                'exists': Path(entry['path']).is_dir(),
            })
        return True, results

    def is_valid_table(
        self, entries: Optional[List[Dict[str, str]]] = None,
    ) -> Tuple[bool, str]:
        """
        Check whether the session table has the correct fields.

        Args:
            entries: Table entries to validate. If None, reads from file.

        Returns:
            Tuple of (valid, message). Message is empty if valid.
        """
        if entries is None:
            entries = self.get_session_table()

        for i, entry in enumerate(entries):
            if 'path' not in entry:
                return False, f"Entry {i}: 'path' is a required field."
            if 'session_id' not in entry:
                return False, f"Entry {i}: 'session_id' is a required field."
            if not isinstance(entry['path'], str):
                return False, f"Entry {i}: 'path' must be a string."
            if not isinstance(entry['session_id'], str):
                return False, f"Entry {i}: 'session_id' must be a string."
        return True, ''

    # ------------------------------------------------------------------
    # Backup
    # ------------------------------------------------------------------

    def backup(self) -> Optional[Path]:
        """
        Create a numbered backup of the table file.

        Returns:
            Path to the backup file, or None if no file to back up.
        """
        if not self._table_path.is_file():
            return None

        parent = self._table_path.parent
        stem = self._table_path.stem
        ext = self._table_path.suffix

        # Find next backup number
        n = 1
        while True:
            backup_path = parent / f"{stem}_bkup{n:03d}{ext}"
            if not backup_path.exists():
                break
            n += 1

        shutil.copy2(self._table_path, backup_path)
        return backup_path

    def backup_file_list(self) -> List[Path]:
        """Return a list of existing backup files."""
        if not self._table_path.parent.is_dir():
            return []

        stem = self._table_path.stem
        ext = self._table_path.suffix
        pattern = f"{stem}_bkup*{ext}"
        return sorted(self._table_path.parent.glob(pattern))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _write_table(self, entries: List[Dict[str, str]]) -> None:
        """Write entries to the table file (atomic-ish via parent mkdir)."""
        valid, msg = self.is_valid_table(entries)
        if not valid:
            raise ValueError(f"Invalid session table: {msg}")

        self._table_path.parent.mkdir(parents=True, exist_ok=True)

        with open(self._table_path, 'w', newline='') as f:
            writer = csv.DictWriter(
                f,
                fieldnames=['session_id', 'path'],
                delimiter='\t',
            )
            writer.writeheader()
            writer.writerows(entries)

    def __repr__(self) -> str:
        return f"SessionTable(path={self._table_path})"
