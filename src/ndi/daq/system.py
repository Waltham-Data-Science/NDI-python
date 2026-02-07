"""
ndi.daq.system - DAQ system class combining navigator, reader, and metadata.

This module provides the DAQSystem class that combines file navigation,
data reading, and metadata reading for a complete data acquisition system.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from ..ido import Ido
from ..time import NO_TIME, ClockType
from .reader_base import DAQReader

logger = logging.getLogger(__name__)


class DAQSystem(Ido):
    """
    Complete data acquisition system.

    DAQSystem combines:
    - FileNavigator: Finds and organizes data files
    - DAQReader: Reads data from files
    - MetadataReader(s): Read stimulus/experiment metadata

    This provides a unified interface for accessing experimental data
    organized by epochs.

    Attributes:
        name: Name of the DAQ system
        filenavigator: Navigator for finding epoch files
        daqreader: Reader for data acquisition data
        daqmetadatareaders: List of metadata readers

    Example:
        >>> from ndi.daq import DAQSystem
        >>> from ndi.file import FileNavigator
        >>> from ndi.daq.reader import IntanReader
        >>>
        >>> nav = FileNavigator(session, '*.rhd')
        >>> reader = IntanReader()
        >>> sys = DAQSystem('my_daq', nav, reader)
        >>>
        >>> # Get epoch table
        >>> et = sys.epochtable()
    """

    def __init__(
        self,
        name: str = "",
        filenavigator: Any | None = None,
        daqreader: DAQReader | None = None,
        daqmetadatareaders: list[Any] | None = None,
        identifier: str | None = None,
        session: Any | None = None,
        document: Any | None = None,
    ):
        """
        Create a new DAQSystem.

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
        if daqreader is not None and not isinstance(daqreader, DAQReader):
            raise TypeError("daqreader must be a DAQReader instance")

    def _load_from_document(self, session: Any, document: Any) -> None:
        """Load DAQSystem from a document."""
        doc_props = getattr(document, "document_properties", document)

        # Get IDs from document
        daqreader_id = document.dependency_value("daqreader_id")
        filenavigator_id = document.dependency_value("filenavigator_id")

        # Load reader and navigator from database
        from ..query import Query

        reader_docs = session.database_search(Query("base.id") == daqreader_id)
        if len(reader_docs) != 1:
            raise ValueError(f"Could not find daqreader with id {daqreader_id}")

        nav_docs = session.database_search(Query("base.id") == filenavigator_id)
        if len(nav_docs) != 1:
            raise ValueError(f"Could not find filenavigator with id {filenavigator_id}")

        # Load metadata readers
        metadata_ids = (
            document.dependency_value_n("daqmetadatareader_id", error_if_not_found=False) or []
        )
        metadata_readers = []
        for mid in metadata_ids:
            m_docs = session.database_search(Query("base.id") == mid)
            if len(m_docs) == 1:
                # Create reader from document
                from .metadatareader import MetadataReader

                metadata_readers.append(MetadataReader(session=session, document=m_docs[0]))

        self._name = doc_props.base.name if hasattr(doc_props, "base") else ""
        self.identifier = doc_props.base.id if hasattr(doc_props, "base") else self.identifier
        self._session = session
        self._daqmetadatareaders = metadata_readers

        # Reconstruct reader from its document
        reader_doc = reader_docs[0]
        reader_class_name = reader_doc._get_nested_property("daqreader.ndi_daqreader_class", "")
        _READER_CLASSES = {
            "IntanReader": "ndi.daq.reader.mfdaq.intan.IntanReader",
            "BlackrockReader": "ndi.daq.reader.mfdaq.blackrock.BlackrockReader",
            "CEDSpike2Reader": "ndi.daq.reader.mfdaq.cedspike2.CEDSpike2Reader",
            "SpikeGadgetsReader": "ndi.daq.reader.mfdaq.spikegadgets.SpikeGadgetsReader",
        }
        reader_path = _READER_CLASSES.get(reader_class_name)
        if reader_path:
            try:
                module_path, cls_name = reader_path.rsplit(".", 1)
                import importlib

                mod = importlib.import_module(module_path)
                ReaderCls = getattr(mod, cls_name)
                self._daqreader = ReaderCls(session=session, document=reader_doc)
            except Exception as exc:
                logger.warning("Could not reconstruct DAQ reader %s: %s", reader_class_name, exc)
                self._daqreader = None
        else:
            logger.debug("Unknown DAQ reader class: %s", reader_class_name)
            self._daqreader = None

        # Reconstruct file navigator from its document
        from ..file.navigator import FileNavigator

        try:
            self._filenavigator = FileNavigator(session=session, document=nav_docs[0])
        except Exception as exc:
            logger.warning("Could not reconstruct file navigator: %s", exc)
            self._filenavigator = None

    @property
    def name(self) -> str:
        """Get the DAQ system name."""
        return self._name

    @property
    def filenavigator(self) -> Any:
        """Get the file navigator."""
        return self._filenavigator

    @property
    def daqreader(self) -> DAQReader | None:
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

    def set_daqmetadatareaders(
        self,
        readers: list[Any],
    ) -> DAQSystem:
        """
        Set the metadata readers.

        Args:
            readers: List of MetadataReader objects

        Returns:
            Self for chaining

        Raises:
            TypeError: If any reader is not a MetadataReader
        """
        from .metadatareader import MetadataReader

        for i, r in enumerate(readers):
            if not isinstance(r, MetadataReader):
                raise TypeError(f"Element {i} is not a MetadataReader instance")
        self._daqmetadatareaders = readers
        return self

    def set_session(self, session: Any) -> DAQSystem:
        """
        Set the session for this DAQ system.

        Args:
            session: The session object

        Returns:
            Self for chaining
        """
        if self._filenavigator is not None:
            self._filenavigator = self._filenavigator.set_session(session)
        self._session = session
        return self

    def epochclock(
        self,
        epoch_number: int,
    ) -> list[ClockType]:
        """
        Return clock types for an epoch.

        Args:
            epoch_number: The epoch number (1-indexed)

        Returns:
            List of ClockType objects

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
            Epoch identifier string
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
            - epochprobemap: Probe mapping for the epoch
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
                    "epoch_session_id": self.session.id if self.session else None,
                    "epochprobemap": epochprobemap,
                    "epoch_clock": epoch_clock,
                    "t0_t1": t0_t1,
                    "underlying_epochs": entry.get("underlying_epochs"),
                }
            )

        return et

    def getprobes(self) -> list[dict[str, Any]]:
        """
        Return all probes associated with this DAQ system.

        Returns:
            List of probe dicts with:
            - name: Probe name
            - reference: Probe reference
            - type: Probe type
            - subject_id: Subject identifier
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
            epoch: Epoch number
            filenavepochprobemap: Optional probe map from navigator

        Returns:
            Epoch probe map object
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
            epoch: Epoch number
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
            session_id = self.session.id
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
            return False, f"Epoch {epoch_number} out of range (1..{len(et)})"

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
            from ..query import Query

            # Delete ingested epoch data documents
            if self._daqreader is not None:
                q = (
                    Query("").isa("daqreader_epochdata_ingested")
                    & Query("").depends_on("daqreader_id", self._daqreader.id)
                    & (Query("epochid.epochid") == epoch_id)
                )
                docs = self.session.database_search(q)
                for doc in docs:
                    self.session.database_remove(doc)

            # Delete ingested metadata documents
            for mreader in self._daqmetadatareaders:
                q = (
                    Query("").isa("daqmetadatareader_epochdata_ingested")
                    & Query("").depends_on("daqmetadatareader_id", mreader.id)
                    & (Query("epochid.epochid") == epoch_id)
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

        return True, f"Epoch {epoch_number} deleted"

    def verifyepochprobemap(
        self,
        epochprobemap: Any,
        epoch: int,
    ) -> tuple[bool, str]:
        """
        Verify that an epochprobemap is valid for an epoch.

        Args:
            epochprobemap: The probe map to verify
            epoch: Epoch number

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
            - [0]: FileNavigator document
            - [1]: DAQReader document
            - [2]: DAQSystem document
            - [3+]: MetadataReader documents
        """
        from ..document import Document

        docs = []

        # Navigator document
        if self._filenavigator is not None:
            docs.append(self._filenavigator.newdocument())

        # Reader document
        if self._daqreader is not None:
            docs.append(self._daqreader.newdocument())

        # System document
        sys_doc = Document(
            "daq/daqsystem",
            **{
                "daqsystem.ndi_daqsystem_class": self.__class__.__name__,
                "base.id": self.id,
                "base.name": self._name,
            },
        )

        if self.session is not None:
            sys_doc.set_session_id(self.session.id)

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
            Query object
        """
        from ..query import Query

        q = Query("base.id") == self.id
        if self._name:
            q = q & (Query("base.name") == self._name)
        if self.session is not None:
            q = q & (Query("base.session_id") == self.session.id)

        return q

    def __eq__(self, other: Any) -> bool:
        """Test equality by name and class."""
        if not isinstance(other, DAQSystem):
            return False
        return self._name == other._name and self.__class__.__name__ == other.__class__.__name__

    def __hash__(self) -> int:
        """Hash by ID."""
        return hash(self.id)
