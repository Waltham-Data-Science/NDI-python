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
from typing import Any


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
        >>> table.addtableentry('abc123', '/data/experiment1')
        >>> table.getsessionpath('abc123')
        '/data/experiment1'
    """

    _REQUIRED_FIELDS = ("session_id", "path")

    def __init__(self, table_path: Path | None = None):
        """
        Create a SessionTable instance.

        Args:
            table_path: Override the default table file location.
                        If None, uses ``localtablefilename()``.
        """
        self._table_path = Path(table_path) if table_path is not None else self.localtablefilename()

    @staticmethod
    def localtablefilename() -> Path:
        """Return the default session table file path.

        MATLAB equivalent: ``ndi.session.sessiontable.localtablefilename``
        """
        return Path.home() / ".ndi" / "preferences" / "local_sessiontable.txt"

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def getsessiontable(self) -> list[dict[str, str]]:
        """
        Read and return the session table.

        MATLAB equivalent: ``ndi.session.sessiontable/getsessiontable``

        Returns:
            List of dicts with keys ``session_id`` and ``path``.
            Returns an empty list if the file does not exist or is empty.
        """
        if not self._table_path.is_file():
            return []

        try:
            entries: list[dict[str, str]] = []
            with open(self._table_path, newline="") as f:
                reader = csv.DictReader(f, delimiter="\t")
                if reader.fieldnames is None:
                    return []
                for row in reader:
                    sid = row.get("session_id", "")
                    path = row.get("path", "")
                    if not isinstance(sid, str):
                        sid = str(sid)
                    if not isinstance(path, str):
                        path = str(path)
                    entries.append({"session_id": sid, "path": path})
            return entries
        except Exception:
            return []

    def getsessionpath(self, session_id: str) -> str | None:
        """
        Look up the filesystem path for *session_id*.

        MATLAB equivalent: ``ndi.session.sessiontable/getsessionpath``

        Args:
            session_id: The session identifier to search for.

        Returns:
            Path string if found, None otherwise.
        """
        for entry in self.getsessiontable():
            if entry["session_id"] == session_id:
                return entry["path"]
        return None

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def addtableentry(self, session_id: str, path: str) -> None:
        """
        Add or replace an entry in the session table.

        MATLAB equivalent: ``ndi.session.sessiontable/addtableentry``

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
        self.removetableentry(session_id)
        entries = self.getsessiontable()
        entries.append({"session_id": session_id, "path": path})
        self._writesessiontable(entries)

    def removetableentry(self, session_id: str) -> None:
        """
        Remove the entry with the given *session_id*.

        MATLAB equivalent: ``ndi.session.sessiontable/removetableentry``

        Does nothing if the ID is not present.
        """
        entries = self.getsessiontable()
        filtered = [e for e in entries if e["session_id"] != session_id]
        if len(filtered) != len(entries):
            self._writesessiontable(filtered)

    def clearsessiontable(self, make_backup: bool = False) -> None:
        """
        Remove all entries from the session table.

        MATLAB equivalent: ``ndi.session.sessiontable/clearsessiontable``

        Args:
            make_backup: If True, create a backup before clearing.
        """
        if make_backup:
            self.backupsessiontable()
        self._writesessiontable([])

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def checktable(self) -> tuple[bool, list[dict[str, Any]]]:
        """
        Validate the session table and check path accessibility.

        MATLAB equivalent: ``ndi.session.sessiontable/checktable``

        Returns:
            Tuple of (valid, results):
            - valid: True if the table has the correct format
            - results: List of dicts with ``exists`` key for each entry
        """
        entries = self.getsessiontable()
        valid, _ = self.isvalidtable(entries)
        if not valid:
            return False, []

        results = []
        for entry in entries:
            results.append(
                {
                    "session_id": entry["session_id"],
                    "path": entry["path"],
                    "exists": Path(entry["path"]).is_dir(),
                }
            )
        return True, results

    def isvalidtable(
        self,
        entries: list[dict[str, str]] | None = None,
    ) -> tuple[bool, str]:
        """
        Check whether the session table has the correct fields.

        MATLAB equivalent: ``ndi.session.sessiontable/isvalidtable``

        Args:
            entries: Table entries to validate. If None, reads from file.

        Returns:
            Tuple of (valid, message). Message is empty if valid.
        """
        if entries is None:
            entries = self.getsessiontable()

        for i, entry in enumerate(entries):
            if "path" not in entry:
                return False, f"Entry {i}: 'path' is a required field."
            if "session_id" not in entry:
                return False, f"Entry {i}: 'session_id' is a required field."
            if not isinstance(entry["path"], str):
                return False, f"Entry {i}: 'path' must be a string."
            if not isinstance(entry["session_id"], str):
                return False, f"Entry {i}: 'session_id' must be a string."
        return True, ""

    # ------------------------------------------------------------------
    # Backup
    # ------------------------------------------------------------------

    def backupsessiontable(self) -> Path | None:
        """
        Create a numbered backup of the table file.

        MATLAB equivalent: ``ndi.session.sessiontable/backupsessiontable``

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

    def backupfilelist(self) -> list[Path]:
        """Return a list of existing backup files.

        MATLAB equivalent: ``ndi.session.sessiontable/backupfilelist``
        """
        if not self._table_path.parent.is_dir():
            return []

        stem = self._table_path.stem
        ext = self._table_path.suffix
        pattern = f"{stem}_bkup*{ext}"
        return sorted(self._table_path.parent.glob(pattern))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _writesessiontable(self, entries: list[dict[str, str]]) -> None:
        """Write entries to the table file (atomic-ish via parent mkdir).

        MATLAB equivalent: ``ndi.session.sessiontable/writesessiontable`` (protected)
        """
        valid, msg = self.isvalidtable(entries)
        if not valid:
            raise ValueError(f"Invalid session table: {msg}")

        self._table_path.parent.mkdir(parents=True, exist_ok=True)

        with open(self._table_path, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["session_id", "path"],
                delimiter="\t",
            )
            writer.writeheader()
            writer.writerows(entries)

    def __repr__(self) -> str:
        return f"SessionTable(path={self._table_path})"
