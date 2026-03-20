"""
ndi.daq.system - DAQ system class combining navigator, reader, and metadata.

This module provides the ndi_daq_system class that combines file navigation,
data reading, and metadata reading for a complete data acquisition system.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from ..ido import ndi_ido
from ..time import NO_TIME, ndi_time_clocktype
from .reader_base import ndi_daq_reader

logger = logging.getLogger(__name__)


def _serialize_clocktype(ct: Any) -> dict[str, str]:
    """Convert a ClockType enum (or dict) to a MATLAB-compatible dict."""
    if isinstance(ct, dict):
        return ct
    # ClockType enum — value is the type string
    return {"type": str(ct.value) if hasattr(ct, "value") else str(ct)}


def _serialize_t0_t1(t0_t1: Any) -> list:
    """Convert t0_t1 to MATLAB-compatible format: [t0, t1] with null for NaN."""
    import math

    if isinstance(t0_t1, (list, tuple)) and len(t0_t1) == 1:
        # Single-element list of tuples: [(t0, t1)] -> [t0, t1]
        t0_t1 = t0_t1[0]
    if isinstance(t0_t1, (list, tuple)) and len(t0_t1) == 2:
        t0, t1 = t0_t1
        t0 = None if (isinstance(t0, float) and math.isnan(t0)) else t0
        t1 = None if (isinstance(t1, float) and math.isnan(t1)) else t1
        return [t0, t1]
    return t0_t1


def _serialize_single_epochprobemap(epm: Any) -> dict[str, Any]:
    """Convert a single epochprobemap object to a JSON-compatible dict."""
    if isinstance(epm, dict):
        return epm
    if hasattr(epm, "to_dict"):
        return epm.to_dict()
    if hasattr(epm, "__dict__"):
        return {k: v for k, v in epm.__dict__.items() if not k.startswith("_")}
    return epm


def _serialize_epochnode(node: dict[str, Any]) -> None:
    """Normalize epoch node dict in-place to MATLAB-compatible JSON format."""
    # epoch_clock: list of ClockType -> single dict (MATLAB unwraps single)
    ec = node.get("epoch_clock")
    if isinstance(ec, list):
        node["epoch_clock"] = (
            _serialize_clocktype(ec[0]) if len(ec) == 1 else [_serialize_clocktype(c) for c in ec]
        )
    elif ec is not None:
        node["epoch_clock"] = _serialize_clocktype(ec)

    # t0_t1
    t = node.get("t0_t1")
    if t is not None:
        node["t0_t1"] = _serialize_t0_t1(t)

    # underlying_epochs: recursively normalize
    ue = node.get("underlying_epochs")
    if isinstance(ue, dict):
        ue_ec = ue.get("epoch_clock")
        if isinstance(ue_ec, list):
            ue["epoch_clock"] = [_serialize_clocktype(c) for c in ue_ec]
        ue_t = ue.get("t0_t1")
        if isinstance(ue_t, list):
            ue["t0_t1"] = [_serialize_t0_t1(t) for t in ue_t]

    # epochprobemap: serialize to JSON-compatible format
    epm = node.get("epochprobemap")
    if isinstance(epm, list):
        node["epochprobemap"] = [_serialize_single_epochprobemap(item) for item in epm]
    elif epm is not None and not isinstance(epm, (dict, str)):
        node["epochprobemap"] = _serialize_single_epochprobemap(epm)


class ndi_daq_system(ndi_ido):
    """
    Complete data acquisition system.

    ndi_daq_system combines:
    - ndi_file_navigator: Finds and organizes data files
    - ndi_daq_reader: Reads data from files
    - ndi_daq_metadatareader(s): Read stimulus/experiment metadata

    This provides a unified interface for accessing experimental data
    organized by epochs.

    Attributes:
        name: Name of the DAQ system
        filenavigator: Navigator for finding epoch files
        daqreader: Reader for data acquisition data
        daqmetadatareaders: List of metadata readers

    Example:
        >>> from ndi.daq import ndi_daq_system
        >>> from ndi.file import ndi_file_navigator
        >>> from ndi.daq.reader import ndi_daq_reader_mfdaq_intan
        >>>
        >>> nav = ndi_file_navigator(session, '*.rhd')
        >>> reader = ndi_daq_reader_mfdaq_intan()
        >>> sys = ndi_daq_system('my_daq', nav, reader)
        >>>
        >>> # Get epoch table
        >>> et = sys.epochtable()
    """

    NDI_DAQSYSTEM_CLASS = "ndi.daq.system"

    def __init__(
        self,
        name: str = "",
        filenavigator: Any | None = None,
        daqreader: ndi_daq_reader | None = None,
        daqmetadatareaders: list[Any] | None = None,
        identifier: str | None = None,
        session: Any | None = None,
        document: Any | None = None,
    ):
        """
        Create a new ndi_daq_system.

        Args:
            name: Name for this DAQ system
            filenavigator: Navigator for finding files
            daqreader: Reader for DAQ data
            daqmetadatareaders: List of metadata readers
            identifier: Optional unique identifier
            session: Optional session object
            document: Optional document to load from
        """
        super().__init__(identifier)

        # Handle loading from document
        if session is not None and document is not None:
            self._load_from_document(session, document)
            return

        # Normal initialization
        self._name = name
        self._filenavigator = filenavigator
        self._daqreader = daqreader
        self._daqmetadatareaders = daqmetadatareaders or []
        self._session = session

        # Validate reader
        if daqreader is not None and not isinstance(daqreader, ndi_daq_reader):
            raise TypeError("daqreader must be a ndi_daq_reader instance")

    def _load_from_document(self, session: Any, document: Any) -> None:
        """Load ndi_daq_system from a document."""
        doc_props = getattr(document, "document_properties", document)

        # Extract basic properties using dict access
        base = doc_props.get("base", {}) if isinstance(doc_props, dict) else {}
        self._name = base.get("name", "")
        if "id" in base:
            self._id = base["id"]
        self._session = session

        # Get dependency IDs from document
        daqreader_id = document.dependency_value("daqreader_id", error_if_not_found=False)
        filenavigator_id = document.dependency_value("filenavigator_id", error_if_not_found=False)

        # Load reader and navigator from database
        from ..query import ndi_query

        reader_docs = []
        if daqreader_id:
            reader_docs = session.database_search(ndi_query("base.id") == daqreader_id)

        nav_docs = []
        if filenavigator_id:
            nav_docs = session.database_search(ndi_query("base.id") == filenavigator_id)

        # Load metadata readers
        metadata_ids = (
            document.dependency_value_n("daqmetadatareader_id", error_if_not_found=False) or []
        )
        metadata_readers = []
        for mid in metadata_ids:
            m_docs = session.database_search(ndi_query("base.id") == mid)
            if len(m_docs) == 1:
                from .metadatareader import ndi_daq_metadatareader

                try:
                    metadata_readers.append(
                        ndi_daq_metadatareader(session=session, document=m_docs[0])
                    )
                except Exception:
                    pass
        self._daqmetadatareaders = metadata_readers

        # Reconstruct reader from its document
        self._daqreader = None
        if len(reader_docs) == 1:
            reader_doc = reader_docs[0]
            reader_class_name = ""
            reader_props = reader_doc.document_properties
            if isinstance(reader_props, dict):
                reader_class_name = reader_props.get("daqreader", {}).get("ndi_daqreader_class", "")
            else:
                reader_class_name = reader_doc._get_nested_property(
                    "daqreader.ndi_daqreader_class", ""
                )

            from ..class_registry import get_class

            ReaderCls = get_class(reader_class_name)
            if ReaderCls is None:
                raise ValueError(
                    f"Unknown DAQ reader class: {reader_class_name!r}. "
                    f"Register it in ndi.class_registry."
                )
            try:
                self._daqreader = ReaderCls(session=session, document=reader_doc)
            except Exception as exc:
                raise RuntimeError(
                    f"Could not reconstruct DAQ reader {reader_class_name!r}: {exc}"
                ) from exc

        # Reconstruct file navigator from its document
        self._filenavigator = None
        if len(nav_docs) == 1:
            nav_doc = nav_docs[0]
            nav_class_name = ""
            nav_props = nav_doc.document_properties
            if isinstance(nav_props, dict):
                nav_class_name = nav_props.get("filenavigator", {}).get(
                    "ndi_filenavigator_class", ""
                )

            from ..class_registry import get_class as get_nav_class

            NavCls = get_nav_class(nav_class_name)
            if NavCls is None:
                raise ValueError(
                    f"Unknown file navigator class: {nav_class_name!r}. "
                    f"Register it in ndi.class_registry."
                )
            try:
                self._filenavigator = NavCls(session=session, document=nav_doc)
            except Exception as exc:
                raise RuntimeError(
                    f"Could not reconstruct file navigator {nav_class_name!r}: {exc}"
                ) from exc

    @property
    def name(self) -> str:
        """Get the DAQ system name."""
        return self._name

    @property
    def filenavigator(self) -> Any:
        """Get the file navigator."""
        return self._filenavigator

    @property
    def daqreader(self) -> ndi_daq_reader | None:
        """Get the DAQ reader."""
        return self._daqreader

    @property
    def daqmetadatareaders(self) -> list[Any]:
        """Get the metadata readers."""
        return self._daqmetadatareaders

    @property
    def session(self) -> Any:
        """Get the session from the file navigator."""
        if self._filenavigator is not None:
            return self._filenavigator.session
        return self._session

    def _get_session_id(self) -> str | None:
        """Return the session id, handling both method and property access."""
        s = self.session
        if s is None:
            return None
        sid = s.id
        return sid() if callable(sid) else sid

    def set_daqmetadatareaders(
        self,
        readers: list[Any],
    ) -> ndi_daq_system:
        """
        Set the metadata readers.

        Args:
            readers: List of ndi_daq_metadatareader objects

        Returns:
            Self for chaining

        Raises:
            TypeError: If any reader is not a ndi_daq_metadatareader
        """
        from .metadatareader import ndi_daq_metadatareader

        for i, r in enumerate(readers):
            if not isinstance(r, ndi_daq_metadatareader):
                raise TypeError(f"ndi_element {i} is not a ndi_daq_metadatareader instance")
        self._daqmetadatareaders = readers
        return self

    def set_session(self, session: Any) -> ndi_daq_system:
        """
        Set the session for this DAQ system.

        Args:
            session: The session object

        Returns:
            Self for chaining
        """
        if self._filenavigator is not None:
            self._filenavigator = self._filenavigator.setsession(session)
        self._session = session
        return self

    def epochclock(
        self,
        epoch_number: int,
    ) -> list[ndi_time_clocktype]:
        """
        Return clock types for an epoch.

        Args:
            epoch_number: The epoch number (1-indexed)

        Returns:
            List of ndi_time_clocktype objects

        Note:
            The base class returns [NO_TIME].
        """
        return [NO_TIME]

    def t0_t1(
        self,
        epoch_number: int,
    ) -> list[tuple[float, float]]:
        """
        Return start/end times for an epoch.

        Args:
            epoch_number: The epoch number (1-indexed)

        Returns:
            List of (t0, t1) tuples for each clock type
        """
        return [(np.nan, np.nan)]

    def epochid(
        self,
        epoch_number: int,
    ) -> str:
        """
        Get the epoch ID for an epoch number.

        Args:
            epoch_number: The epoch number (1-indexed)

        Returns:
            ndi_epoch_epoch identifier string
        """
        if self._filenavigator is not None:
            return self._filenavigator.epochid(epoch_number)
        return f"epoch_{epoch_number}"

    def epochtable(self) -> list[dict[str, Any]]:
        """
        Build the epoch table for this DAQ system.

        Returns:
            List of epoch entries with fields:
            - epoch_number: The epoch number
            - epoch_id: Unique epoch identifier
            - epochprobemap: ndi_probe mapping for the epoch
            - epoch_clock: List of clock types
            - t0_t1: List of (t0, t1) tuples
            - underlying_epochs: Underlying file information
        """
        if self._filenavigator is None:
            return []

        # Get base epoch table from navigator
        nav_et = self._filenavigator.epochtable()

        # Get ingested t0_t1 and epochclock maps
        t0t1_map = {}
        clock_map = {}
        if self._daqreader is not None:
            maps = self._daqreader.ingested2epochs_t0t1_epochclock(self.session)
            t0t1_map = maps.get("t0t1", {})
            clock_map = maps.get("epochclock", {})

        et = []
        for i, entry in enumerate(nav_et):
            epoch_number = entry.get("epoch_number", i + 1)
            epoch_id = entry.get("epoch_id", self.epochid(epoch_number))

            # Get epoch probe map
            nav_epochprobemap = entry.get("epochprobemap")
            epochprobemap = self.getepochprobemap(epoch_number, nav_epochprobemap)

            # Get clock info
            if epoch_id in clock_map:
                epoch_clock = clock_map[epoch_id]
            else:
                epoch_clock = self.epochclock(epoch_number)

            # Get t0_t1 info
            if epoch_id in t0t1_map:
                t0_t1 = t0t1_map[epoch_id]
            else:
                t0_t1 = self.t0_t1(epoch_number)

            et.append(
                {
                    "epoch_number": epoch_number,
                    "epoch_id": epoch_id,
                    "epoch_session_id": self._get_session_id(),
                    "epochprobemap": epochprobemap,
                    "epoch_clock": epoch_clock,
                    "t0_t1": t0_t1,
                    "underlying_epochs": entry.get("underlying_epochs"),
                }
            )

        return et

    def epochnodes(self) -> list[dict[str, Any]]:
        """Return epoch node structs for this DAQ system.

        Each node mirrors the MATLAB ``epochnodes`` output: the same fields
        as ``epochtable`` (minus ``epoch_number``) plus ``objectname`` and
        ``objectclass``.  Values are JSON-serializable and match MATLAB's
        format for cross-language comparison.
        """
        et = self.epochtable()
        nodes = []
        for entry in et:
            node = {k: v for k, v in entry.items() if k != "epoch_number"}
            node["objectname"] = self._name
            node["objectclass"] = self.NDI_DAQSYSTEM_CLASS
            _serialize_epochnode(node)
            nodes.append(node)
        return nodes

    def getprobes(self) -> list[dict[str, Any]]:
        """
        Return all probes associated with this DAQ system.

        Returns:
            List of probe dicts with:
            - name: ndi_probe name
            - reference: ndi_probe reference
            - type: ndi_probe type
            - subject_id: ndi_subject identifier
        """
        et = self.epochtable()
        probes = []
        seen = set()

        for entry in et:
            epc = entry.get("epochprobemap")
            if epc is None:
                continue

            # Handle both list and object epochprobemap
            items = epc if isinstance(epc, list) else [epc]
            for item in items:
                if hasattr(item, "devicestring"):
                    # Check if this probe belongs to us
                    device_name = self._parse_devicename(item.devicestring)
                    if device_name.lower() == self._name.lower():
                        key = (item.name, item.reference, item.type)
                        if key not in seen:
                            seen.add(key)
                            probes.append(
                                {
                                    "name": item.name,
                                    "reference": item.reference,
                                    "type": item.type,
                                    "subject_id": getattr(item, "subjectstring", ""),
                                }
                            )

        return probes

    def _parse_devicename(self, devicestring: str) -> str:
        """Parse device name from a device string."""
        # Format: devicename:type:details
        parts = devicestring.split(":")
        return parts[0] if parts else ""

    def getepochprobemap(
        self,
        epoch: int,
        filenavepochprobemap: Any | None = None,
    ) -> Any:
        """
        Get the epoch probe map for an epoch.

        Args:
            epoch: ndi_epoch_epoch number
            filenavepochprobemap: Optional probe map from navigator

        Returns:
            ndi_epoch_epoch probe map object
        """
        # Check if reader has getepochprobemap method
        if self._daqreader is not None and hasattr(self._daqreader, "getepochprobemap"):
            if self._filenavigator is not None:
                ecfname = self._filenavigator.epochprobemapfilename(epoch)
                epochfiles = self._filenavigator.getepochfiles(epoch)
                return self._daqreader.getepochprobemap(ecfname, epochfiles)

        # Fall back to navigator or provided map
        if filenavepochprobemap is not None:
            return filenavepochprobemap
        if self._filenavigator is not None:
            return self._filenavigator.getepochprobemap(epoch)
        return None

    def getmetadata(
        self,
        epoch: int,
        channel: int = 1,
    ) -> list[dict[str, Any]]:
        """
        Get metadata for an epoch.

        Args:
            epoch: ndi_epoch_epoch number
            channel: Metadata reader channel (1-indexed)

        Returns:
            List of metadata entries
        """
        n_readers = len(self._daqmetadatareaders)
        if channel < 1 or channel > max(n_readers, 1):
            raise ValueError(f"Metadata channel out of range: 1..{max(n_readers, 1)}")

        if n_readers == 0:
            return []

        if self._filenavigator is None:
            return []

        epochfiles = self._filenavigator.getepochfiles(epoch)
        reader = self._daqmetadatareaders[channel - 1]

        return reader.readmetadata(epochfiles)

    def ingest(self) -> tuple[bool, list[Any]]:
        """
        Ingest data from this DAQ system into the database.

        Returns:
            Tuple of (success, documents):
            - success: True if successful
            - documents: List of created documents
        """
        et = self.epochtable()
        docs = []
        filenavigator_ingested = False

        for entry in et:
            underlying = entry.get("underlying_epochs", {})
            epochfiles = underlying.get("underlying", [])

            # Check if already ingested
            if self._is_ingested(epochfiles):
                continue

            # Ingest file navigator first
            if not filenavigator_ingested and self._filenavigator is not None:
                nav_docs = self._filenavigator.ingest()
                docs.extend(nav_docs)
                filenavigator_ingested = True

            # Ingest DAQ reader data
            if self._daqreader is not None:
                reader_docs = self._daqreader.ingest_epochfiles(epochfiles, entry["epoch_id"])
                if not isinstance(reader_docs, list):
                    reader_docs = [reader_docs]
                docs.extend(reader_docs)

            # Ingest metadata
            for mreader in self._daqmetadatareaders:
                m_docs = mreader.ingest_epochfiles(epochfiles, entry["epoch_id"])
                if not isinstance(m_docs, list):
                    m_docs = [m_docs]
                docs.extend(m_docs)

        # Set session IDs and add to database
        if self.session is not None:
            session_id = self.session.id()
            for doc in docs:
                doc.set_session_id(session_id)
            self.session.database_add(docs)

        return True, docs

    def _is_ingested(self, epochfiles: list[str]) -> bool:
        """Check if epochfiles indicate an ingested epoch."""
        if not epochfiles:
            return False
        return epochfiles[0].startswith("epochid://")

    def deleteepoch(
        self,
        epoch_number: int,
        delete_from_disk: bool = False,
    ) -> tuple[bool, str]:
        """
        Delete an epoch from this DAQ system.

        This removes the epoch from the file navigator's epoch table.
        Optionally deletes the underlying data files from disk.

        Args:
            epoch_number: The epoch number to delete (1-indexed)
            delete_from_disk: If True, also delete the data files

        Returns:
            Tuple of (success, message)

        Raises:
            ValueError: If epoch_number is out of range
        """
        if self._filenavigator is None:
            return False, "No file navigator configured"

        et = self.epochtable()
        if epoch_number < 1 or epoch_number > len(et):
            return False, f"ndi_epoch_epoch {epoch_number} out of range (1..{len(et)})"

        entry = et[epoch_number - 1]
        epoch_id = entry.get("epoch_id", "")

        # Get epoch files before deletion
        underlying = entry.get("underlying_epochs", {})
        epochfiles = underlying.get("underlying", [])

        # Remove from navigator
        if hasattr(self._filenavigator, "deleteepoch"):
            self._filenavigator.deleteepoch(epoch_number)

        # Delete from database if session exists
        if self.session is not None:
            from ..query import ndi_query

            # Delete ingested epoch data documents
            if self._daqreader is not None:
                q = (
                    ndi_query("").isa("daqreader_epochdata_ingested")
                    & ndi_query("").depends_on("daqreader_id", self._daqreader.id)
                    & (ndi_query("epochid.epochid") == epoch_id)
                )
                docs = self.session.database_search(q)
                for doc in docs:
                    self.session.database_remove(doc)

            # Delete ingested metadata documents
            for mreader in self._daqmetadatareaders:
                q = (
                    ndi_query("").isa("daqmetadatareader_epochdata_ingested")
                    & ndi_query("").depends_on("daqmetadatareader_id", mreader.id)
                    & (ndi_query("epochid.epochid") == epoch_id)
                )
                docs = self.session.database_search(q)
                for doc in docs:
                    self.session.database_remove(doc)

        # Delete files from disk if requested
        if delete_from_disk and epochfiles:
            import os

            for filepath in epochfiles:
                if not filepath.startswith("epochid://") and os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except OSError:
                        pass  # Best effort deletion

        return True, f"ndi_epoch_epoch {epoch_number} deleted"

    def verifyepochprobemap(
        self,
        epochprobemap: Any,
        epoch: int,
    ) -> tuple[bool, str]:
        """
        Verify that an epochprobemap is valid for an epoch.

        Args:
            epochprobemap: The probe map to verify
            epoch: ndi_epoch_epoch number

        Returns:
            Tuple of (is_valid, error_message)
        """
        if self._filenavigator is None or self._daqreader is None:
            return True, ""

        epochfiles = self._filenavigator.getepochfiles(epoch)
        return self._daqreader.verifyepochprobemap(epochprobemap, epochfiles)

    def newdocument(self) -> list[Any]:
        """
        Create documents for this DAQ system.

        Returns:
            List of documents:
            - [0]: ndi_file_navigator document
            - [1]: ndi_daq_reader document
            - [2]: ndi_daq_system document
            - [3+]: ndi_daq_metadatareader documents
        """
        from ..document import ndi_document

        docs = []

        # Navigator document
        if self._filenavigator is not None:
            docs.append(self._filenavigator.newdocument())

        # Reader document
        if self._daqreader is not None:
            docs.append(self._daqreader.newdocument())

        # System document
        sys_doc = ndi_document(
            "daq/daqsystem",
            **{
                "daqsystem.ndi_daqsystem_class": self.NDI_DAQSYSTEM_CLASS,
                "base.id": self.id,
                "base.name": self._name,
            },
        )

        if self.session is not None:
            sys_doc.set_session_id(self.session.id())

        if self._filenavigator is not None:
            sys_doc.set_dependency_value("filenavigator_id", self._filenavigator.id)
        if self._daqreader is not None:
            sys_doc.set_dependency_value("daqreader_id", self._daqreader.id)

        # Metadata reader documents
        for mreader in self._daqmetadatareaders:
            m_doc = mreader.newdocument()
            docs.append(m_doc)
            sys_doc.add_dependency_value_n("daqmetadatareader_id", m_doc.id)

        docs.append(sys_doc)
        return docs

    def searchquery(self) -> Any:
        """
        Create a search query for this DAQ system.

        Returns:
            ndi_query object
        """
        from ..query import ndi_query

        q = ndi_query("base.id") == self.id
        if self._name:
            q = q & (ndi_query("base.name") == self._name)
        if self.session is not None:
            q = q & (ndi_query("base.session_id") == self.session.id())

        return q

    def __eq__(self, other: Any) -> bool:
        """Test equality by name and class."""
        if not isinstance(other, ndi_daq_system):
            return False
        return self._name == other._name and self.__class__.__name__ == other.__class__.__name__

    def __hash__(self) -> int:
        """Hash by ID."""
        return hash(self.id)
