"""
ndi.daq.reader_base - Abstract base class for DAQ readers.

This module provides the DAQReader abstract base class that defines
the interface for reading data from data acquisition systems.
"""

from __future__ import annotations

from abc import ABC
from typing import Any

import numpy as np

from ..ido import Ido
from ..time import NO_TIME, ClockType


class DAQReader(Ido, ABC):
    """
    Abstract base class for DAQ readers.

    DAQReader defines the interface for objects that read samples from
    data acquisition systems. Concrete implementations handle specific
    file formats (e.g., Intan, Blackrock, CED Spike2).

    This class inherits from Ido to provide unique identification.

    Attributes:
        identifier: Unique identifier for this reader instance

    Example:
        >>> class MyReader(DAQReader):
        ...     def epochclock(self, epochfiles):
        ...         return [ClockType.DEV_LOCAL_TIME]
        ...     # ... implement other abstract methods
    """

    def __init__(
        self,
        identifier: str | None = None,
        session: Any | None = None,
        document: Any | None = None,
    ):
        """
        Create a new DAQReader.

        Args:
            identifier: Optional identifier (generated if not provided)
            session: Optional session object
            document: Optional document to load from
        """
        super().__init__(identifier)
        self._session = session

        # Load from document if provided
        if document is not None:
            doc_props = getattr(document, "document_properties", document)
            if hasattr(doc_props, "base") and hasattr(doc_props.base, "id"):
                self.identifier = doc_props.base.id

    def epochclock(
        self,
        epochfiles: list[str],
    ) -> list[ClockType]:
        """
        Return the clock types for an epoch.

        Args:
            epochfiles: List of file paths for the epoch

        Returns:
            List of ClockType objects available for this epoch.
            The base class returns [NO_TIME].

        See also: ClockType
        """
        return [NO_TIME]

    def t0_t1(
        self,
        epochfiles: list[str],
    ) -> list[tuple[float, float]]:
        """
        Return the start and end times for an epoch.

        Args:
            epochfiles: List of file paths for the epoch

        Returns:
            List of (t0, t1) tuples for each clock type.
            The base class returns [(NaN, NaN)].

        See also: epochclock
        """
        return [(np.nan, np.nan)]

    # =========================================================================
    # Ingested data methods - for reading from database-stored epochs
    # =========================================================================

    def getingesteddocument(
        self,
        epochfiles: list[str],
        session: Any,
    ) -> Any:
        """
        Get the document containing ingested data for an epoch.

        Args:
            epochfiles: List of file paths (starting with epochid://)
            session: Session object with database access

        Returns:
            Document containing the ingested epoch data

        Raises:
            AssertionError: If not exactly one document found
        """
        from ..file.navigator import FileNavigator
        from ..query import Query

        epochid = FileNavigator.ingestedfiles_epochid(epochfiles)

        q = (
            Query("").isa("daqreader_epochdata_ingested")
            & Query("").depends_on("daqreader_id", self.id)
            & (Query("epochid.epochid") == epochid)
        )
        docs = session.database_search(q)

        assert len(docs) == 1, f"Found {len(docs)} documents for {epochid}, needed exactly 1."

        return docs[0]

    def ingested2epochs_t0t1_epochclock(
        self,
        session: Any,
    ) -> dict[str, dict[str, Any]]:
        """
        Create maps of all ingested epochs to t0t1 and epochclock.

        Args:
            session: Session object with database access

        Returns:
            Dict with 't0t1' and 'epochclock' keys, each mapping
            epoch_id to the respective values
        """
        from ..query import Query

        q = Query("").isa("daqreader_epochdata_ingested") & Query("").depends_on(
            "daqreader_id", self.id
        )
        d_ingested = session.database_search(q)

        t0t1_map = {}
        epochclock_map = {}

        for doc in d_ingested:
            props = doc.document_properties
            epochid = props.epochid.epochid
            et = props.daqreader_epochdata_ingested.epochtable

            # Extract epoch clock
            ec_list = []
            for ec_str in et.get("epochclock", []):
                ec_list.append(ClockType(ec_str) if isinstance(ec_str, str) else ec_str)
            epochclock_map[epochid] = ec_list

            # Extract t0_t1
            t0t1_raw = et.get("t0_t1", [])
            if not isinstance(t0t1_raw, list):
                # Handle single entry case
                t0t1_list = [tuple(t0t1_raw)]
            else:
                t0t1_list = [tuple(t) if isinstance(t, (list, tuple)) else t for t in t0t1_raw]
            t0t1_map[epochid] = t0t1_list

        return {
            "t0t1": t0t1_map,
            "epochclock": epochclock_map,
        }

    def epochclock_ingested(
        self,
        epochfiles: list[str],
        session: Any,
    ) -> list[ClockType]:
        """
        Return the clock types for an ingested epoch.

        Args:
            epochfiles: List of file paths (starting with epochid://)
            session: Session object with database access

        Returns:
            List of ClockType objects available for this epoch

        See also: epochclock, ClockType
        """
        doc = self.getingesteddocument(epochfiles, session)
        et = doc.document_properties.daqreader_epochdata_ingested.epochtable

        ec_list = []
        for ec_str in et.get("epochclock", []):
            if isinstance(ec_str, str):
                ec_list.append(ClockType(ec_str))
            else:
                ec_list.append(ec_str)

        return ec_list

    def t0_t1_ingested(
        self,
        epochfiles: list[str],
        session: Any,
    ) -> list[tuple[float, float]]:
        """
        Return the start and end times for an ingested epoch.

        Args:
            epochfiles: List of file paths (starting with epochid://)
            session: Session object with database access

        Returns:
            List of (t0, t1) tuples for each clock type

        See also: t0_t1, epochclock_ingested
        """
        doc = self.getingesteddocument(epochfiles, session)
        et = doc.document_properties.daqreader_epochdata_ingested.epochtable

        t0t1_raw = et.get("t0_t1", [])
        if not isinstance(t0t1_raw, list):
            return [tuple(t0t1_raw)]

        t0t1_list = []
        for t in t0t1_raw:
            if isinstance(t, (list, tuple)):
                t0t1_list.append(tuple(t))
            else:
                t0t1_list.append((t, t))

        return t0t1_list

    def verifyepochprobemap(
        self,
        epochprobemap: Any,
        epochfiles: list[str],
    ) -> tuple[bool, str]:
        """
        Verify that an epochprobemap is compatible with this reader.

        Args:
            epochprobemap: The epoch probe map to verify
            epochfiles: List of file paths for the epoch

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Base class accepts any epochprobemap
        return True, ""

    def ingest_epochfiles(
        self,
        epochfiles: list[str],
        epoch_id: str,
    ) -> Any:
        """
        Create a document describing the data for an ingested epoch.

        Args:
            epochfiles: List of file paths for the epoch
            epoch_id: Unique identifier for this epoch

        Returns:
            Document object describing the ingested data

        Note:
            The returned document is not added to any database.
        """
        from ..document import Document

        # Get epoch clock and t0_t1
        ec = self.epochclock(epochfiles)
        ec_strings = [c.value if isinstance(c, ClockType) else str(c) for c in ec]
        t0t1 = self.t0_t1(epochfiles)

        epochtable = {
            "epochclock": ec_strings,
            "t0_t1": t0t1,
        }

        doc = Document(
            "ingestion/daqreader_epochdata_ingested",
            daqreader_epochdata_ingested={"epochtable": epochtable},
            epochid={"epochid": epoch_id},
        )
        doc.set_dependency_value("daqreader_id", self.id)

        return doc

    def newdocument(self) -> Any:
        """
        Create a new document for this DAQReader.

        Returns:
            Document representing this reader
        """
        from ..document import Document

        doc = Document(
            "daq/daqreader",
            **{
                "daqreader.ndi_daqreader_class": self.__class__.__name__,
                "base.id": self.id,
            },
        )
        return doc

    def searchquery(self) -> Any:
        """
        Create a search query for this DAQReader.

        Returns:
            Query object for finding this reader
        """
        from ..query import Query

        return Query("base.id") == self.id

    def __eq__(self, other: Any) -> bool:
        """Test equality by class and ID."""
        if not isinstance(other, DAQReader):
            return False
        return self.__class__.__name__ == other.__class__.__name__ and self.id == other.id

    def __hash__(self) -> int:
        """Hash by ID."""
        return hash(self.id)
