"""
ndi.file.navigator - File navigator for organizing epoch files.

This module provides the ndi_file_navigator class that finds and organizes
data files into epochs based on file patterns.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from ...ido import ndi_ido
from ...time import NO_TIME, ndi_time_clocktype


def _to_matlab_cell_str(items: list[str]) -> str:
    """Convert a list of strings to MATLAB cell-array syntax.

    Example: ``['#.rhd', '#.epochprobemap.ndi']`` becomes
    ``"{ '#.rhd', '#.epochprobemap.ndi' }"``.

    Returns an empty string when *items* is empty or falsy, matching
    the NDI document schema default.
    """
    if not items:
        return ""
    quoted = ", ".join(f"'{s}'" for s in items)
    return f"{{ {quoted} }}"


def _parse_fileparameters(fp_str: str) -> list[str] | None:
    """Parse a fileparameters string, preserving element order.

    MATLAB stores file parameters as cell-array syntax, e.g.
    ``"{ '#.rhd', '#.epochprobemap.ndi' }"``.  ``eval()`` would turn
    this into a Python ``set`` and lose the ordering, which matters
    for epoch-ID filename generation.  This helper extracts the
    quoted elements in document order.

    Returns:
        Ordered list of pattern strings, or *None* when the string is
        empty or cannot be parsed (callers should fall back to an
        empty filematch list).
    """
    if not fp_str:
        return None
    # Fast path: MATLAB cell-array literal  { 'a', 'b', ... }
    stripped = fp_str.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        inner = stripped[1:-1]
        items = re.findall(r"'([^']*)'", inner)
        if items:
            return items
    # Fallback: try Python eval (handles repr() output from Python-created docs)
    try:
        result = eval(fp_str)  # noqa: S307
        if isinstance(result, (list, tuple)):
            return list(result)
        if isinstance(result, (set, frozenset)):
            return sorted(result)
        if isinstance(result, str):
            return [result]
    except Exception:
        pass
    return None


@lru_cache(maxsize=10)
def find_file_groups(
    base_path: str,
    patterns: tuple[str, ...],
) -> list[list[str]]:
    """
    Find groups of files matching patterns.

    Args:
        base_path: Root directory to search
        patterns: Tuple of file patterns (glob or regex)

    Returns:
        List of file groups, each group is a list of file paths
    """
    base = Path(base_path)
    if not base.is_dir():
        return []

    # Find all files recursively
    all_files: dict[str, list[str]] = {}  # directory -> files

    for root, dirs, files in os.walk(base_path):
        # Skip hidden directories
        dirs[:] = [d for d in dirs if not d.startswith(".")]

        for f in files:
            if f.startswith("."):
                continue
            fullpath = os.path.join(root, f)
            if root not in all_files:
                all_files[root] = []
            all_files[root].append(fullpath)

    # Group files by pattern matching
    groups = []

    for _directory, files in all_files.items():
        # Track which pattern matched each file so we can preserve
        # pattern order (MATLAB returns epochfiles ordered by pattern).
        matched_files: list[tuple[int, str]] = []
        for f in files:
            filename = os.path.basename(f)
            for pat_idx, pattern in enumerate(patterns):
                # Convert MATLAB '#' wildcard to glob '*'
                glob_pattern = pattern.replace("#", "*")
                # Try glob pattern first
                if fnmatch.fnmatch(filename, glob_pattern):
                    matched_files.append((pat_idx, f))
                    break
                # Try regex pattern
                try:
                    if re.search(pattern, filename):
                        matched_files.append((pat_idx, f))
                        break
                except re.error:
                    pass

        if matched_files:
            # Sort by pattern index first, then by filename for stability
            matched_files.sort(key=lambda x: (x[0], x[1]))
            groups.append([f for _, f in matched_files])

    return groups


class ndi_file_navigator(ndi_ido):
    """
    Navigator for finding and organizing epoch files.

    ndi_file_navigator finds data files on disk and organizes them into epochs
    based on file patterns. It provides the file foundation for ndi_daq_system.

    Attributes:
        session: The NDI session
        fileparameters: Parameters for finding epoch files
    Class Attributes:
        NDI_FILENAVIGATOR_CLASS: MATLAB-compatible class name string.
        epochprobemap_fileparameters: Parameters for finding probe map files
        epochprobemap_class: Class to use for epoch probe maps

    Example:
        >>> nav = ndi_file_navigator(session, ['*.rhd', '*.dat'])
        >>> epochs = nav.selectfilegroups()
        >>> files = nav.getepochfiles(1)  # Get files for epoch 1
    """

    NDI_FILENAVIGATOR_CLASS = "ndi.file.navigator"

    def __init__(
        self,
        session: Any | None = None,
        fileparameters: str | list[str] | dict[str, Any] | None = None,
        epochprobemap_class: str = "ndi.epoch.ndi_epoch_epochprobemap",
        epochprobemap_fileparameters: str | list[str] | dict[str, Any] | None = None,
        identifier: str | None = None,
        document: Any | None = None,
    ):
        """
        Create a new ndi_file_navigator.

        Args:
            session: NDI session object
            fileparameters: File patterns to match:
                - String: Single pattern (e.g., '*.rhd')
                - List: Multiple patterns (e.g., ['*.rhd', '*.dat'])
                - Dict: With 'filematch' key
            epochprobemap_class: Class name for epoch probe maps
            epochprobemap_fileparameters: Patterns for finding probe map files
            identifier: Optional unique identifier
            document: Optional document to load from
        """
        super().__init__(identifier)
        self._session = session
        self._epochprobemap_class = epochprobemap_class
        self._raw_fileparameters_str = ""
        self._cached_epoch_filenames: dict[int, list[str]] = {}

        # Load from document if provided
        if session is not None and document is not None:
            self._load_from_document(document)
            return

        # Process file parameters
        self._fileparameters = self._normalize_fileparameters(fileparameters)
        self._epochprobemap_fileparameters = self._normalize_fileparameters(
            epochprobemap_fileparameters
        )

    def _load_from_document(self, document: Any) -> None:
        """Load navigator from a document."""
        doc_props = getattr(document, "document_properties", document)

        def _prop(obj: Any, key: str, default: Any = None) -> Any:
            """Get a property from a dict or object."""
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)

        base = _prop(doc_props, "base")
        if base is not None:
            base_id = _prop(base, "id")
            if base_id is not None:
                self.identifier = base_id
            self._name = _prop(base, "name", "") or "unknown"

        filenavigator = _prop(doc_props, "filenavigator")
        if filenavigator:
            fp = _prop(filenavigator, "fileparameters", "")
            self._raw_fileparameters_str = fp
            self._fileparameters = self._normalize_fileparameters(_parse_fileparameters(fp))
            self._epochprobemap_class = _prop(
                filenavigator, "epochprobemap_class", "ndi.epoch.ndi_epoch_epochprobemap"
            )
            epfp = _prop(filenavigator, "epochprobemap_fileparameters", "")
            self._epochprobemap_fileparameters = self._normalize_fileparameters(
                _parse_fileparameters(epfp)
            )
        else:
            self._fileparameters = {"filematch": []}
            self._epochprobemap_fileparameters = {"filematch": []}

    @staticmethod
    def _parse_fileparameters(raw: str) -> Any:
        """Parse a fileparameters string, handling MATLAB cell array syntax.

        MATLAB stores cell arrays as ``"{ '#.rhd', '#.dat' }"`` which
        ``eval()`` turns into a Python ``set`` (losing order).  We detect
        this pattern and parse it as an ordered list instead.
        """
        stripped = raw.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            # MATLAB cell array — extract quoted strings in order
            items = re.findall(r"'([^']*)'", stripped)
            if items:
                return items
        # Fall back to eval for Python-native formats (list, dict)
        try:
            return eval(stripped)  # noqa: S307
        except Exception:
            return stripped

    @staticmethod
    def _normalize_fileparameters(
        params: str | list[str] | dict[str, Any] | None,
    ) -> dict[str, list[str]]:
        """Normalize file parameters to dict format."""
        if params is None:
            return {"filematch": []}
        if isinstance(params, str):
            return {"filematch": [params]}
        if isinstance(params, (set, frozenset)):
            return {"filematch": sorted(params)}
        if isinstance(params, (list, tuple)):
            return {"filematch": list(params)}
        if isinstance(params, dict):
            fm = params.get("filematch", [])
            if isinstance(fm, str):
                fm = [fm]
            return {"filematch": list(fm)}
        # list, set, tuple, or any iterable (MATLAB cell arrays eval to
        # Python sets when they use { 'a', 'b' } syntax)
        try:
            return {"filematch": list(params)}
        except TypeError:
            return {"filematch": []}

    @property
    def session(self) -> Any:
        """Get the session."""
        return self._session

    def _get_session_id(self) -> str | None:
        """Return the session id, handling both method and property access."""
        if self._session is None:
            return None
        sid = self._session.id
        return sid() if callable(sid) else sid

    @property
    def fileparameters(self) -> dict[str, list[str]]:
        """Get the file parameters."""
        return self._fileparameters

    @property
    def epochprobemap_class(self) -> str:
        """Get the epoch probe map class name."""
        return self._epochprobemap_class

    @epochprobemap_class.setter
    def epochprobemap_class(self, value: str) -> None:
        """Set the epoch probe map class name."""
        self._epochprobemap_class = value

    @property
    def epochprobemap_fileparameters(self) -> dict[str, list[str]]:
        """Get the epoch probe map file parameters."""
        return self._epochprobemap_fileparameters

    def path(self) -> str:
        """
        Get the path for this navigator.

        Returns:
            ndi_session path

        Raises:
            ValueError: If no valid session
        """
        if self._session is None or not hasattr(self._session, "getpath"):
            raise ValueError("No valid session associated with this navigator")
        return self._session.getpath()

    def setsession(self, session: Any) -> ndi_file_navigator:
        """
        Set the session for this navigator.

        MATLAB equivalent: ndi.file.navigator/setsession

        Args:
            session: The session object

        Returns:
            Self for chaining
        """
        self._session = session
        return self

    def setfileparameters(
        self,
        parameters: str | list[str] | dict[str, Any],
    ) -> ndi_file_navigator:
        """
        Set the file parameters.

        Args:
            parameters: File patterns to match

        Returns:
            Self for chaining
        """
        self._fileparameters = self._normalize_fileparameters(parameters)
        return self

    def setepochprobemapfileparameters(
        self,
        parameters: str | list[str] | dict[str, Any],
    ) -> ndi_file_navigator:
        """
        Set the epoch probe map file parameters.

        Args:
            parameters: File patterns to match

        Returns:
            Self for chaining
        """
        self._epochprobemap_fileparameters = self._normalize_fileparameters(parameters)
        return self

    def selectfilegroups(self) -> tuple[list[list[str]], list[Any | None]]:
        """
        Select groups of files that comprise epochs.

        Returns:
            Tuple of (epochfiles, epochprobemaps):
            - epochfiles: List of file groups
            - epochprobemaps: List of probe maps (None if not loaded)
        """
        # Get files from disk
        disk_epochs = self.selectfilegroups_disk()

        # Check for ingested epochs
        ingested_epochs = self.find_ingested_documents()

        if not ingested_epochs:
            return disk_epochs, [None] * len(disk_epochs)

        # Reconcile disk and ingested epochs
        # Get epoch IDs for disk epochs
        disk_ids = []
        for i, files in enumerate(disk_epochs):
            eid = self.epochid(i + 1, files)
            disk_ids.append(eid)

        # Get epoch IDs for ingested epochs
        ingested_ids = [e["epoch_id"] for e in ingested_epochs]

        # Combine unique epoch IDs
        all_ids = list(dict.fromkeys(ingested_ids + disk_ids))

        epochfiles = []
        epochprobemaps = []

        for eid in all_ids:
            if eid in ingested_ids:
                idx = ingested_ids.index(eid)
                epochfiles.append(ingested_epochs[idx]["files"])
                epochprobemaps.append(ingested_epochs[idx].get("epochprobemap"))
            else:
                idx = disk_ids.index(eid)
                epochfiles.append(disk_epochs[idx])
                epochprobemaps.append(None)

        return epochfiles, epochprobemaps

    def selectfilegroups_disk(self) -> list[list[str]]:
        """
        Select file groups from disk.

        Returns:
            List of file groups
        """
        try:
            base_path = self.path()
        except ValueError:
            return []

        patterns = tuple(self._fileparameters.get("filematch", []))
        if not patterns:
            return []

        groups = find_file_groups(base_path, patterns)

        # Filter out hidden files
        filtered = []
        for group in groups:
            visible = [f for f in group if not os.path.basename(f).startswith(".")]
            if visible:
                filtered.append(visible)

        return filtered

    def find_ingested_documents(self) -> list[dict[str, Any]]:
        """Find ingested epoch documents from database.

        MATLAB equivalent: ndi.file.navigator/find_ingested_documents
        """
        if self._session is None:
            return []

        try:
            from ...query import ndi_query

            q = (
                ndi_query("").isa("epochfiles_ingested")
                & ndi_query("").depends_on("filenavigator_id", self.id)
                & (ndi_query("base.session_id") == self._session.id)
            )
            docs = self._session.database_search(q)

            epochs = []
            for doc in docs:
                props = doc.document_properties
                epochs.append(
                    {
                        "epoch_id": props.epochfiles_ingested.epoch_id,
                        "files": props.epochfiles_ingested.files,
                        "epochprobemap": getattr(props.epochfiles_ingested, "epochprobemap", None),
                    }
                )
            return epochs
        except Exception:
            return []

    def epochtable(self) -> list[dict[str, Any]]:
        """
        Build the epoch table.

        Returns:
            List of epoch entries with fields:
            - epoch_number
            - epoch_id
            - epoch_session_id
            - epochprobemap
            - epoch_clock
            - t0_t1
            - underlying_epochs
        """
        all_epochs, epochprobemaps = self.selectfilegroups()

        table = []
        for i, files in enumerate(all_epochs):
            epoch_number = i + 1
            epoch_id = self.epochid(epoch_number, files)

            underlying = {
                "underlying": files,
                "epoch_id": epoch_id,
                "epoch_session_id": self._get_session_id(),
                "epochprobemap": [],
                "epoch_clock": [NO_TIME],
                "t0_t1": [(float("nan"), float("nan"))],
            }

            entry = {
                "epoch_number": epoch_number,
                "epoch_id": epoch_id,
                "epoch_session_id": self._get_session_id(),
                "epochprobemap": epochprobemaps[i] or self.getepochprobemap(epoch_number, files),
                "epoch_clock": [NO_TIME],
                "t0_t1": [(float("nan"), float("nan"))],
                "underlying_epochs": underlying,
            }
            table.append(entry)

        return table

    def epochnodes(self) -> list[dict[str, Any]]:
        """Return epoch node structs for this file navigator.

        Same as ``epochtable`` (minus ``epoch_number``) with
        ``objectname`` and ``objectclass`` appended, matching MATLAB's
        ``epochnodes`` output.  Values are serialized for cross-language
        comparison.
        """
        from ...daq.system import _serialize_epochnode

        et = self.epochtable()
        nodes = []
        for entry in et:
            node = {k: v for k, v in entry.items() if k != "epoch_number"}
            node["objectname"] = self._name if hasattr(self, "_name") else "unknown"
            node["objectclass"] = self.NDI_FILENAVIGATOR_CLASS
            _serialize_epochnode(node)
            nodes.append(node)
        return nodes

    def epochid(
        self,
        epoch_number: int,
        epochfiles: list[str] | None = None,
    ) -> str:
        """
        Get the epoch ID for an epoch.

        Args:
            epoch_number: ndi_epoch_epoch number (1-indexed)
            epochfiles: Optional file list (fetched if not provided)

        Returns:
            ndi_epoch_epoch identifier string
        """
        if epochfiles is None:
            epochfiles = self.getepochfiles_number(epoch_number)

        # Check if ingested
        if self.isingested(epochfiles):
            return self.ingestedfiles_epochid(epochfiles)

        # Try to read from epoch ID file
        eidfname = self.epochidfilename(epoch_number, epochfiles)
        if eidfname and Path(eidfname).is_file():
            with open(eidfname) as f:
                return f.read().strip()

        # Generate new ID
        from ...ido import ndi_ido

        new_id = f"epoch_{ndi_ido().id}"

        # Save to file if possible
        if eidfname:
            Path(eidfname).parent.mkdir(parents=True, exist_ok=True)
            with open(eidfname, "w") as f:
                f.write(new_id)

        return new_id

    def epochidfilename(
        self,
        epoch_number: int,
        epochfiles: list[str] | None = None,
    ) -> str | None:
        """
        Get the filename for storing epoch ID.

        Args:
            epoch_number: ndi_epoch_epoch number
            epochfiles: Optional file list

        Returns:
            Path for epoch ID file, or None
        """
        if epochfiles is None:
            epochfiles = self.getepochfiles_number(epoch_number)

        if not epochfiles:
            return None

        if self.isingested(epochfiles):
            return None

        fmstr = self.filematch_hashstring()
        parent = os.path.dirname(epochfiles[0])
        stem = self._epoch_stem(epochfiles)
        return os.path.join(parent, f".{stem}.{fmstr}.epochid.ndi")

    @staticmethod
    def _epoch_stem(epochfiles: list[str]) -> str:
        """Return the common filename stem for a group of epoch files.

        MATLAB uses the common prefix of basenames (stripping trailing
        dot) so that ``['foo.rhd', 'foo.epochprobemap.ndi']`` yields
        ``'foo'``.
        """
        basenames = [os.path.basename(f) for f in epochfiles]
        stem = os.path.commonprefix(basenames).rstrip(".")
        return stem if stem else basenames[0]

    def epochprobemapfilename(
        self,
        epoch_number: int,
    ) -> str | None:
        """
        Get the filename for epoch probe map.

        Args:
            epoch_number: ndi_epoch_epoch number

        Returns:
            Path for epoch probe map file, or None
        """
        # Check for custom parameters
        if self._epochprobemap_fileparameters.get("filematch"):
            epochfiles = self.getepochfiles_number(epoch_number)
            if self.isingested(epochfiles):
                return None

            for f in epochfiles:
                filename = os.path.basename(f)
                for pattern in self._epochprobemap_fileparameters["filematch"]:
                    if fnmatch.fnmatch(filename, pattern):
                        return f
                    try:
                        if re.search(pattern, filename):
                            return f
                    except re.error:
                        pass

        return self.defaultepochprobemapfilename(epoch_number)

    def defaultepochprobemapfilename(
        self,
        epoch_number: int,
    ) -> str | None:
        """
        Get the default epoch probe map filename.

        Args:
            epoch_number: ndi_epoch_epoch number

        Returns:
            Path for epoch probe map file, or None
        """
        epochfiles = self.getepochfiles_number(epoch_number)
        if not epochfiles or self.isingested(epochfiles):
            return None

        fmstr = self.filematch_hashstring()
        parent = os.path.dirname(epochfiles[0])
        stem = self._epoch_stem(epochfiles)
        return os.path.join(parent, f".{stem}.{fmstr}.epochprobemap.ndi")

    def getepochprobemap(
        self,
        epoch_number: int,
        epochfiles: list[str] | None = None,
    ) -> Any | None:
        """
        Get the epoch probe map for an epoch.

        Args:
            epoch_number: ndi_epoch_epoch number
            epochfiles: Optional file list

        Returns:
            ndi_epoch_epoch probe map object or None
        """
        if epochfiles is None:
            epochfiles = self.getepochfiles_number(epoch_number)

        # If ingested, get from document
        if self.isingested(epochfiles):
            doc = self.getepochingesteddoc(epochfiles)
            if doc:
                props = doc.document_properties
                return getattr(props.epochfiles_ingested, "epochprobemap", None)

        # Try to find a probe map file within the epoch files
        epm_patterns = self._epochprobemap_fileparameters.get("filematch", [])
        for f in epochfiles:
            fname = os.path.basename(f)
            for pat in epm_patterns:
                glob_pat = pat.replace("#", "*")
                if fnmatch.fnmatch(fname, glob_pat):
                    return self._load_epochprobemap_file(f)
                try:
                    if re.search(pat, fname):
                        return self._load_epochprobemap_file(f)
                except re.error:
                    pass

        # Fall back to generated probe map file
        filename = self.epochprobemapfilename(epoch_number)
        if filename and Path(filename).is_file():
            return self._load_epochprobemap_file(filename)

        return None

    @staticmethod
    def _load_epochprobemap_file(filepath: str) -> Any | None:
        """Load an epoch probe map from a TSV file.

        The file format is tab-separated with a header row:
        ``name  reference  type  devicestring  subjectstring``
        """
        from ...epoch.epochprobemap import EpochProbeMap

        try:
            with open(filepath, encoding="utf-8") as f:
                lines = f.read().strip().splitlines()
            if len(lines) < 2:
                return None
            # Skip header, parse data lines
            maps = []
            for line in lines[1:]:
                parts = line.split("\t")
                if len(parts) >= 3:
                    maps.append(
                        EpochProbeMap(
                            name=parts[0].strip(),
                            reference=int(parts[1].strip()),
                            type=parts[2].strip(),
                            devicestring=parts[3].strip() if len(parts) > 3 else "",
                            subjectstring=parts[4].strip() if len(parts) > 4 else "",
                        )
                    )
            if len(maps) == 1:
                return maps[0]
            return maps if maps else None
        except Exception:
            return None

    def getepochingesteddoc(
        self,
        epochfiles: list[str],
    ) -> Any | None:
        """Get the ingested document for epochfiles.

        MATLAB equivalent: ndi.file.navigator/getepochingesteddoc
        """
        if not self.isingested(epochfiles) or self._session is None:
            return None

        epochid = self.ingestedfiles_epochid(epochfiles)

        from ...query import ndi_query

        q = (
            ndi_query("").isa("epochfiles_ingested")
            & ndi_query("").depends_on("filenavigator_id", self.id)
            & (ndi_query("base.session_id") == self._session.id)
            & (ndi_query("epochfiles_ingested.epoch_id") == epochid)
        )
        docs = self._session.database_search(q)

        if len(docs) == 1:
            return docs[0]
        return None

    def getepochfiles(
        self,
        epoch_number_or_id: int | str | list[int] | list[str],
    ) -> tuple[list[str] | list[list[str]], str | list[str]]:
        """
        Get files for one or more epochs.

        MATLAB equivalent: ndi.file.navigator/getepochfiles

        Args:
            epoch_number_or_id: ndi_epoch_epoch number(s) or ID(s)

        Returns:
            Tuple of (fullpathfilenames, epochid):
            - fullpathfilenames: List of file paths (or list of lists)
            - epochid: ndi_epoch_epoch ID string (or list of strings)
        """
        et = self.epochtable()

        # Normalize input
        multiple = False
        if isinstance(epoch_number_or_id, (list, tuple)):
            multiple = True
            items = epoch_number_or_id
        else:
            items = [epoch_number_or_id]

        # Determine if using IDs or numbers
        use_ids = isinstance(items[0], str)

        file_results = []
        id_results = []
        for item in items:
            if use_ids:
                # Find by epoch ID
                match = None
                for entry in et:
                    if entry["epoch_id"] == item:
                        match = entry
                        break
                if match is None:
                    raise ValueError(f"No such epoch ID: {item}")
            else:
                # Find by epoch number
                if item < 1 or item > len(et):
                    raise ValueError(f"ndi_epoch_epoch number out of range: {item}")
                match = et[item - 1]

            underlying = match.get("underlying_epochs", {})
            files = underlying.get("underlying", [])
            file_results.append(files)
            id_results.append(match["epoch_id"])

        if multiple:
            return file_results, id_results
        return file_results[0], id_results[0]

    def getepochfiles_number(
        self,
        epoch_number: int,
    ) -> list[str]:
        """
        Get files for an epoch by number.

        Args:
            epoch_number: ndi_epoch_epoch number (1-indexed)

        Returns:
            List of file paths
        """
        if epoch_number in self._cached_epoch_filenames:
            return self._cached_epoch_filenames[epoch_number]

        all_epochs, _ = self.selectfilegroups()
        if epoch_number < 1 or epoch_number > len(all_epochs):
            raise ValueError(f"ndi_epoch_epoch number out of range: {epoch_number}")

        files = all_epochs[epoch_number - 1]
        self._cached_epoch_filenames[epoch_number] = files
        return files

    def filematch_hashstring(self) -> str:
        """
        Get a hash string based on file match patterns.

        MATLAB hashes the raw ``fileparameters`` string stored in the
        document (e.g. ``"{ '#.rhd', '#.epochprobemap.ndi' }"``).
        When a navigator is loaded from a document we preserve that
        raw string so the hash matches across languages.

        Returns:
            MD5 hash of the file-parameter representation
        """
        # Prefer the raw document string so epoch-ID filenames match MATLAB
        if self._raw_fileparameters_str:
            return hashlib.md5(self._raw_fileparameters_str.encode()).hexdigest()
        patterns = self._fileparameters.get("filematch", [])
        if not patterns:
            return ""
        concat = "".join(patterns)
        return hashlib.md5(concat.encode()).hexdigest()

    def ingest(self) -> list[Any]:
        """
        Create documents for ingested epochs.

        Returns:
            List of created documents
        """
        from ...document import ndi_document

        docs = []
        et = self.epochtable()

        for entry in et:
            files = entry["underlying_epochs"].get("underlying", [])

            if self.isingested(files):
                continue

            # Check if already have ingested doc
            if self.getepochingesteddoc(files) is not None:
                continue

            # Create ingested document
            epochfiles_struct = {
                "epoch_id": entry["epoch_id"],
                "files": [f"epochid://{entry['epoch_id']}"] + files,
            }
            if entry.get("epochprobemap"):
                epochfiles_struct["epochprobemap"] = entry["epochprobemap"]

            doc = ndi_document(
                "ingestion/epochfiles_ingested",
                epochfiles_ingested=epochfiles_struct,
            )
            doc.set_dependency_value("filenavigator_id", self.id)
            if self._session:
                doc.set_session_id(self._session.id)
            docs.append(doc)

        return docs

    def newdocument(self) -> Any:
        """
        Create a document for this ndi_file_navigator.

        Returns:
            ndi_document object
        """
        from ...document import ndi_document

        fp = self._fileparameters.get("filematch", [])
        fp_str = _to_matlab_cell_str(fp)

        epfp = self._epochprobemap_fileparameters.get("filematch", [])
        epfp_str = _to_matlab_cell_str(epfp)

        filenavigator_struct = {
            "ndi_filenavigator_class": self.NDI_FILENAVIGATOR_CLASS,
            "fileparameters": fp_str,
            "epochprobemap_class": self._epochprobemap_class,
            "epochprobemap_fileparameters": epfp_str,
        }

        doc = ndi_document(
            "daq/filenavigator",
            filenavigator=filenavigator_struct,
            **{"base.id": self.id},
        )

        if self._session:
            doc.set_session_id(self._session.id)

        return doc

    def searchquery(self) -> Any:
        """
        Create a search query for this ndi_file_navigator.

        Returns:
            ndi_query object
        """
        from ...query import ndi_query

        q = ndi_query("base.id") == self.id
        if self._session:
            q = q & (ndi_query("base.session_id") == self._session.id)
        return q

    @staticmethod
    def isingested(epochfiles: list[str]) -> bool:
        """
        Check if epochfiles indicate an ingested epoch.

        Args:
            epochfiles: List of file paths

        Returns:
            True if the first file starts with 'epochid://'
        """
        if not epochfiles:
            return False
        return epochfiles[0].startswith("epochid://")

    @staticmethod
    def ingestedfiles_epochid(epochfiles: list[str]) -> str:
        """
        Get the epoch ID from ingested epochfiles.

        Args:
            epochfiles: List of file paths

        Returns:
            ndi_epoch_epoch ID string

        Raises:
            AssertionError: If epochfiles are not ingested
        """
        assert ndi_file_navigator.isingested(
            epochfiles
        ), "This function is only applicable to ingested epochfiles"
        return epochfiles[0][len("epochid://") :]

    def __eq__(self, other: Any) -> bool:
        """Test equality."""
        if not isinstance(other, ndi_file_navigator):
            return False
        return (
            self._session == other._session
            and self._fileparameters == other._fileparameters
            and self._epochprobemap_class == other._epochprobemap_class
            and self._epochprobemap_fileparameters == other._epochprobemap_fileparameters
        )

    def __hash__(self) -> int:
        """Hash by ID."""
        return hash(self.id)
