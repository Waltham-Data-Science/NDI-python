"""
ndi.file.navigator - File navigator for organizing epoch files.

This module provides the FileNavigator class that finds and organizes
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

from ...ido import Ido
from ...time import ClockType, NO_TIME


@lru_cache(maxsize=10)
def find_file_groups(
    base_path: str,
    patterns: Tuple[str, ...],
) -> List[List[str]]:
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
    all_files: Dict[str, List[str]] = {}  # directory -> files

    for root, dirs, files in os.walk(base_path):
        # Skip hidden directories
        dirs[:] = [d for d in dirs if not d.startswith('.')]

        for f in files:
            if f.startswith('.'):
                continue
            fullpath = os.path.join(root, f)
            if root not in all_files:
                all_files[root] = []
            all_files[root].append(fullpath)

    # Group files by pattern matching
    groups = []

    for directory, files in all_files.items():
        matched_files = []
        for f in files:
            filename = os.path.basename(f)
            for pattern in patterns:
                # Try glob pattern first
                if fnmatch.fnmatch(filename, pattern):
                    matched_files.append(f)
                    break
                # Try regex pattern
                try:
                    if re.search(pattern, filename):
                        matched_files.append(f)
                        break
                except re.error:
                    pass

        if matched_files:
            groups.append(sorted(matched_files))

    return groups


class FileNavigator(Ido):
    """
    Navigator for finding and organizing epoch files.

    FileNavigator finds data files on disk and organizes them into epochs
    based on file patterns. It provides the file foundation for DAQSystem.

    Attributes:
        session: The NDI session
        fileparameters: Parameters for finding epoch files
        epochprobemap_fileparameters: Parameters for finding probe map files
        epochprobemap_class: Class to use for epoch probe maps

    Example:
        >>> nav = FileNavigator(session, ['*.rhd', '*.dat'])
        >>> epochs = nav.selectfilegroups()
        >>> files = nav.getepochfiles(1)  # Get files for epoch 1
    """

    def __init__(
        self,
        session: Optional[Any] = None,
        fileparameters: Optional[Union[str, List[str], Dict[str, Any]]] = None,
        epochprobemap_class: str = 'ndi.epoch.EpochProbeMap',
        epochprobemap_fileparameters: Optional[Union[str, List[str], Dict[str, Any]]] = None,
        identifier: Optional[str] = None,
        document: Optional[Any] = None,
    ):
        """
        Create a new FileNavigator.

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
        self._cached_epoch_filenames: Dict[int, List[str]] = {}

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
        doc_props = getattr(document, 'document_properties', document)

        if hasattr(doc_props, 'base') and hasattr(doc_props.base, 'id'):
            self.identifier = doc_props.base.id

        filenavigator = getattr(doc_props, 'filenavigator', None)
        if filenavigator:
            fp = getattr(filenavigator, 'fileparameters', '')
            self._fileparameters = self._normalize_fileparameters(
                eval(fp) if fp else None
            )
            self._epochprobemap_class = getattr(
                filenavigator, 'epochprobemap_class',
                'ndi.epoch.EpochProbeMap'
            )
            epfp = getattr(filenavigator, 'epochprobemap_fileparameters', '')
            self._epochprobemap_fileparameters = self._normalize_fileparameters(
                eval(epfp) if epfp else None
            )
        else:
            self._fileparameters = {'filematch': []}
            self._epochprobemap_fileparameters = {'filematch': []}

    @staticmethod
    def _normalize_fileparameters(
        params: Optional[Union[str, List[str], Dict[str, Any]]],
    ) -> Dict[str, List[str]]:
        """Normalize file parameters to dict format."""
        if params is None:
            return {'filematch': []}
        if isinstance(params, str):
            return {'filematch': [params]}
        if isinstance(params, list):
            return {'filematch': params}
        if isinstance(params, dict):
            fm = params.get('filematch', [])
            if isinstance(fm, str):
                fm = [fm]
            return {'filematch': fm}
        return {'filematch': []}

    @property
    def session(self) -> Any:
        """Get the session."""
        return self._session

    @property
    def fileparameters(self) -> Dict[str, List[str]]:
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
    def epochprobemap_fileparameters(self) -> Dict[str, List[str]]:
        """Get the epoch probe map file parameters."""
        return self._epochprobemap_fileparameters

    def path(self) -> str:
        """
        Get the path for this navigator.

        Returns:
            Session path

        Raises:
            ValueError: If no valid session
        """
        if self._session is None or not hasattr(self._session, 'getpath'):
            raise ValueError("No valid session associated with this navigator")
        return self._session.getpath()

    def set_session(self, session: Any) -> 'FileNavigator':
        """
        Set the session for this navigator.

        Args:
            session: The session object

        Returns:
            Self for chaining
        """
        self._session = session
        return self

    def setfileparameters(
        self,
        parameters: Union[str, List[str], Dict[str, Any]],
    ) -> 'FileNavigator':
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
        parameters: Union[str, List[str], Dict[str, Any]],
    ) -> 'FileNavigator':
        """
        Set the epoch probe map file parameters.

        Args:
            parameters: File patterns to match

        Returns:
            Self for chaining
        """
        self._epochprobemap_fileparameters = self._normalize_fileparameters(parameters)
        return self

    def selectfilegroups(self) -> Tuple[List[List[str]], List[Optional[Any]]]:
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
        ingested_epochs = self._get_ingested_epochs()

        if not ingested_epochs:
            return disk_epochs, [None] * len(disk_epochs)

        # Reconcile disk and ingested epochs
        # Get epoch IDs for disk epochs
        disk_ids = []
        for i, files in enumerate(disk_epochs):
            eid = self.epochid(i + 1, files)
            disk_ids.append(eid)

        # Get epoch IDs for ingested epochs
        ingested_ids = [e['epoch_id'] for e in ingested_epochs]

        # Combine unique epoch IDs
        all_ids = list(dict.fromkeys(ingested_ids + disk_ids))

        epochfiles = []
        epochprobemaps = []

        for eid in all_ids:
            if eid in ingested_ids:
                idx = ingested_ids.index(eid)
                epochfiles.append(ingested_epochs[idx]['files'])
                epochprobemaps.append(ingested_epochs[idx].get('epochprobemap'))
            else:
                idx = disk_ids.index(eid)
                epochfiles.append(disk_epochs[idx])
                epochprobemaps.append(None)

        return epochfiles, epochprobemaps

    def selectfilegroups_disk(self) -> List[List[str]]:
        """
        Select file groups from disk.

        Returns:
            List of file groups
        """
        try:
            base_path = self.path()
        except ValueError:
            return []

        patterns = tuple(self._fileparameters.get('filematch', []))
        if not patterns:
            return []

        groups = find_file_groups(base_path, patterns)

        # Filter out hidden files
        filtered = []
        for group in groups:
            visible = [f for f in group if not os.path.basename(f).startswith('.')]
            if visible:
                filtered.append(visible)

        return filtered

    def _get_ingested_epochs(self) -> List[Dict[str, Any]]:
        """Get ingested epochs from database."""
        if self._session is None:
            return []

        try:
            from ...query import Query

            q = (
                Query('').isa('epochfiles_ingested') &
                Query('').depends_on('filenavigator_id', self.id) &
                (Query('base.session_id') == self._session.id)
            )
            docs = self._session.database_search(q)

            epochs = []
            for doc in docs:
                props = doc.document_properties
                epochs.append({
                    'epoch_id': props.epochfiles_ingested.epoch_id,
                    'files': props.epochfiles_ingested.files,
                    'epochprobemap': getattr(
                        props.epochfiles_ingested, 'epochprobemap', None
                    ),
                })
            return epochs
        except Exception:
            return []

    def epochtable(self) -> List[Dict[str, Any]]:
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
                'underlying': files,
                'epoch_id': epoch_id,
                'epoch_session_id': self._session.id if self._session else None,
                'epoch_clock': [NO_TIME],
                't0_t1': [(float('nan'), float('nan'))],
            }

            entry = {
                'epoch_number': epoch_number,
                'epoch_id': epoch_id,
                'epoch_session_id': self._session.id if self._session else None,
                'epochprobemap': epochprobemaps[i] or self.getepochprobemap(epoch_number, files),
                'epoch_clock': [NO_TIME],
                't0_t1': [(float('nan'), float('nan'))],
                'underlying_epochs': underlying,
            }
            table.append(entry)

        return table

    def epochid(
        self,
        epoch_number: int,
        epochfiles: Optional[List[str]] = None,
    ) -> str:
        """
        Get the epoch ID for an epoch.

        Args:
            epoch_number: Epoch number (1-indexed)
            epochfiles: Optional file list (fetched if not provided)

        Returns:
            Epoch identifier string
        """
        if epochfiles is None:
            epochfiles = self.getepochfiles_number(epoch_number)

        # Check if ingested
        if self.isingested(epochfiles):
            return self.ingestedfiles_epochid(epochfiles)

        # Try to read from epoch ID file
        eidfname = self.epochidfilename(epoch_number, epochfiles)
        if eidfname and Path(eidfname).is_file():
            with open(eidfname, 'r') as f:
                return f.read().strip()

        # Generate new ID
        from ...ido import Ido
        new_id = f"epoch_{Ido().id}"

        # Save to file if possible
        if eidfname:
            Path(eidfname).parent.mkdir(parents=True, exist_ok=True)
            with open(eidfname, 'w') as f:
                f.write(new_id)

        return new_id

    def epochidfilename(
        self,
        epoch_number: int,
        epochfiles: Optional[List[str]] = None,
    ) -> Optional[str]:
        """
        Get the filename for storing epoch ID.

        Args:
            epoch_number: Epoch number
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
        parent, filename = os.path.split(epochfiles[0])
        return os.path.join(parent, f".{filename}.{fmstr}.epochid.ndi")

    def epochprobemapfilename(
        self,
        epoch_number: int,
    ) -> Optional[str]:
        """
        Get the filename for epoch probe map.

        Args:
            epoch_number: Epoch number

        Returns:
            Path for epoch probe map file, or None
        """
        # Check for custom parameters
        if self._epochprobemap_fileparameters.get('filematch'):
            epochfiles = self.getepochfiles_number(epoch_number)
            if self.isingested(epochfiles):
                return None

            for f in epochfiles:
                filename = os.path.basename(f)
                for pattern in self._epochprobemap_fileparameters['filematch']:
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
    ) -> Optional[str]:
        """
        Get the default epoch probe map filename.

        Args:
            epoch_number: Epoch number

        Returns:
            Path for epoch probe map file, or None
        """
        epochfiles = self.getepochfiles_number(epoch_number)
        if not epochfiles or self.isingested(epochfiles):
            return None

        fmstr = self.filematch_hashstring()
        parent, filename = os.path.split(epochfiles[0])
        return os.path.join(parent, f".{filename}.{fmstr}.epochprobemap.ndi")

    def getepochprobemap(
        self,
        epoch_number: int,
        epochfiles: Optional[List[str]] = None,
    ) -> Optional[Any]:
        """
        Get the epoch probe map for an epoch.

        Args:
            epoch_number: Epoch number
            epochfiles: Optional file list

        Returns:
            Epoch probe map object or None
        """
        if epochfiles is None:
            epochfiles = self.getepochfiles_number(epoch_number)

        # If ingested, get from document
        if self.isingested(epochfiles):
            doc = self._get_epoch_ingested_doc(epochfiles)
            if doc:
                props = doc.document_properties
                return getattr(props.epochfiles_ingested, 'epochprobemap', None)

        # Try to load from file
        filename = self.epochprobemapfilename(epoch_number)
        if filename and Path(filename).is_file():
            # Load probe map from file
            # This would need to be implemented based on the probe map format
            pass

        return None

    def _get_epoch_ingested_doc(
        self,
        epochfiles: List[str],
    ) -> Optional[Any]:
        """Get the ingested document for epochfiles."""
        if not self.isingested(epochfiles) or self._session is None:
            return None

        epochid = self.ingestedfiles_epochid(epochfiles)

        from ...query import Query
        q = (
            Query('').isa('epochfiles_ingested') &
            Query('').depends_on('filenavigator_id', self.id) &
            (Query('base.session_id') == self._session.id) &
            (Query('epochfiles_ingested.epoch_id') == epochid)
        )
        docs = self._session.database_search(q)

        if len(docs) == 1:
            return docs[0]
        return None

    def getepochfiles(
        self,
        epoch_number_or_id: Union[int, str, List[int], List[str]],
    ) -> Union[List[str], List[List[str]]]:
        """
        Get files for one or more epochs.

        Args:
            epoch_number_or_id: Epoch number(s) or ID(s)

        Returns:
            List of file paths, or list of lists if multiple epochs
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

        results = []
        for item in items:
            if use_ids:
                # Find by epoch ID
                match = None
                for entry in et:
                    if entry['epoch_id'] == item:
                        match = entry
                        break
                if match is None:
                    raise ValueError(f"No such epoch ID: {item}")
            else:
                # Find by epoch number
                if item < 1 or item > len(et):
                    raise ValueError(f"Epoch number out of range: {item}")
                match = et[item - 1]

            underlying = match.get('underlying_epochs', {})
            files = underlying.get('underlying', [])
            results.append(files)

        if multiple:
            return results
        return results[0]

    def getepochfiles_number(
        self,
        epoch_number: int,
    ) -> List[str]:
        """
        Get files for an epoch by number.

        Args:
            epoch_number: Epoch number (1-indexed)

        Returns:
            List of file paths
        """
        if epoch_number in self._cached_epoch_filenames:
            return self._cached_epoch_filenames[epoch_number]

        all_epochs, _ = self.selectfilegroups()
        if epoch_number < 1 or epoch_number > len(all_epochs):
            raise ValueError(f"Epoch number out of range: {epoch_number}")

        files = all_epochs[epoch_number - 1]
        self._cached_epoch_filenames[epoch_number] = files
        return files

    def filematch_hashstring(self) -> str:
        """
        Get a hash string based on file match patterns.

        Returns:
            MD5 hash of concatenated patterns
        """
        patterns = self._fileparameters.get('filematch', [])
        if not patterns:
            return ""

        concat = ''.join(patterns)
        return hashlib.md5(concat.encode()).hexdigest()

    def ingest(self) -> List[Any]:
        """
        Create documents for ingested epochs.

        Returns:
            List of created documents
        """
        from ...document import Document

        docs = []
        et = self.epochtable()

        for entry in et:
            files = entry['underlying_epochs'].get('underlying', [])

            if self.isingested(files):
                continue

            # Check if already have ingested doc
            if self._get_epoch_ingested_doc(files) is not None:
                continue

            # Create ingested document
            epochfiles_struct = {
                'epoch_id': entry['epoch_id'],
                'files': [f"epochid://{entry['epoch_id']}"] + files,
            }
            if entry.get('epochprobemap'):
                epochfiles_struct['epochprobemap'] = entry['epochprobemap']

            doc = Document(
                'ingestion/epochfiles_ingested',
                epochfiles_ingested=epochfiles_struct,
            )
            doc.set_dependency_value('filenavigator_id', self.id)
            if self._session:
                doc.set_session_id(self._session.id)
            docs.append(doc)

        return docs

    def newdocument(self) -> Any:
        """
        Create a document for this FileNavigator.

        Returns:
            Document object
        """
        from ...document import Document

        fp = self._fileparameters.get('filematch', [])
        fp_str = repr(fp) if fp else ''

        epfp = self._epochprobemap_fileparameters.get('filematch', [])
        epfp_str = repr(epfp) if epfp else ''

        filenavigator_struct = {
            'ndi_filenavigator_class': self.__class__.__name__,
            'fileparameters': fp_str,
            'epochprobemap_class': self._epochprobemap_class,
            'epochprobemap_fileparameters': epfp_str,
        }

        doc = Document(
            'daq/filenavigator',
            filenavigator=filenavigator_struct,
            **{'base.id': self.id},
        )

        if self._session:
            doc.set_session_id(self._session.id)

        return doc

    def searchquery(self) -> Any:
        """
        Create a search query for this FileNavigator.

        Returns:
            Query object
        """
        from ...query import Query

        q = Query('base.id') == self.id
        if self._session:
            q = q & (Query('base.session_id') == self._session.id)
        return q

    @staticmethod
    def isingested(epochfiles: List[str]) -> bool:
        """
        Check if epochfiles indicate an ingested epoch.

        Args:
            epochfiles: List of file paths

        Returns:
            True if the first file starts with 'epochid://'
        """
        if not epochfiles:
            return False
        return epochfiles[0].startswith('epochid://')

    @staticmethod
    def ingestedfiles_epochid(epochfiles: List[str]) -> str:
        """
        Get the epoch ID from ingested epochfiles.

        Args:
            epochfiles: List of file paths

        Returns:
            Epoch ID string

        Raises:
            AssertionError: If epochfiles are not ingested
        """
        assert FileNavigator.isingested(epochfiles), \
            "This function is only applicable to ingested epochfiles"
        return epochfiles[0][len('epochid://'):]

    def __eq__(self, other: Any) -> bool:
        """Test equality."""
        if not isinstance(other, FileNavigator):
            return False
        return (
            self._session == other._session and
            self._fileparameters == other._fileparameters and
            self._epochprobemap_class == other._epochprobemap_class and
            self._epochprobemap_fileparameters == other._epochprobemap_fileparameters
        )

    def __hash__(self) -> int:
        """Hash by ID."""
        return hash(self.id)
