"""
ndi.element - Base class for data elements.

This module provides the Element class that represents logical
data sources in neuroscience experiments (e.g., electrodes,
stimulators, behavioral sensors).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

from ..documentservice import DocumentService
from ..epoch.epochprobemap import EpochProbeMap
from ..epoch.epochset import EpochSet
from ..ido import Ido
from ..time import ClockType


class Element(Ido, EpochSet, DocumentService):
    """
    Base class for data elements.

    Element represents a logical data source or sink in an experiment.
    Elements can be electrodes, stimulators, behavioral sensors, or
    any other entity that produces or consumes time series data.

    Elements manage epochs through the EpochSet interface and can
    be stored in the database through DocumentService.

    Attributes:
        session: Associated session object
        name: Element name (no whitespace)
        reference: Reference number (non-negative)
        type: Element type identifier (no whitespace)
        underlying_element: Element this depends on (for derived elements)
        direct: If True, epochs come directly from underlying_element
        subject_id: Associated subject document ID
        dependencies: Additional named dependencies

    Example:
        >>> elem = Element(
        ...     session=my_session,
        ...     name='electrode1',
        ...     reference=1,
        ...     type='n-trode',
        ... )
        >>> et, hash_val = elem.epochtable()
    """

    def __init__(
        self,
        session: Any | None = None,
        name: str = "",
        reference: int = 0,
        type: str = "",
        underlying_element: Element | None = None,
        direct: bool = True,
        subject_id: str = "",
        dependencies: dict[str, str] | None = None,
        identifier: str | None = None,
        document: Any | None = None,
    ):
        """
        Create a new Element.

        Can be created from scratch or loaded from a document.

        Args:
            session: Session object with database access
            name: Element name (no whitespace allowed)
            reference: Reference number (non-negative integer)
            type: Element type identifier (no whitespace)
            underlying_element: Element this depends on
            direct: If True, use underlying_element epochs directly
            subject_id: Subject document ID
            dependencies: Dict of named dependencies
            identifier: Optional unique identifier
            document: Optional document to load from
        """
        # Initialize base classes
        Ido.__init__(self, identifier)
        EpochSet.__init__(self)

        # Load from document if provided
        if document is not None and session is not None:
            self._load_from_document(session, document)
            return

        # Validate inputs
        if " " in name or "\t" in name:
            raise ValueError(f"name cannot contain whitespace: '{name}'")
        if " " in type or "\t" in type:
            raise ValueError(f"type cannot contain whitespace: '{type}'")
        if reference < 0:
            raise ValueError(f"reference must be non-negative: {reference}")

        # If underlying_element provided, inherit subject_id
        if underlying_element is not None and subject_id == "":
            subject_id = underlying_element.subject_id

        self._session = session
        self._name = name
        self._reference = reference
        self._type = type
        self._underlying_element = underlying_element
        self._direct = direct
        self._subject_id = subject_id
        self._dependencies = dependencies or {}

    def _load_from_document(self, session: Any, document: Any) -> None:
        """Load element from a document."""
        props = getattr(document, "document_properties", document)

        # Get basic properties
        if hasattr(props, "element"):
            self._name = getattr(props.element, "name", "")
            self._reference = getattr(props.element, "reference", 0)
            self._type = getattr(props.element, "type", "")
            self._direct = getattr(props.element, "direct", True)
        else:
            self._name = ""
            self._reference = 0
            self._type = ""
            self._direct = True

        # Get ID from base
        if hasattr(props, "base") and hasattr(props.base, "id"):
            self.identifier = props.base.id

        self._session = session
        self._subject_id = document.dependency_value("subject_id", error_if_not_found=False) or ""
        self._underlying_element = None
        self._dependencies = {}

        # Load underlying element if dependency exists
        underlying_id = document.dependency_value("underlying_element_id", error_if_not_found=False)
        if underlying_id:
            from ..query import Query

            q = Query("base.id") == underlying_id
            docs = session.database_search(q)
            if len(docs) == 1:
                self._underlying_element = Element(session=session, document=docs[0])

    @property
    def session(self) -> Any:
        """Get the session."""
        return self._session

    @property
    def name(self) -> str:
        """Get the element name."""
        return self._name

    @property
    def reference(self) -> int:
        """Get the reference number."""
        return self._reference

    @property
    def type(self) -> str:
        """Get the element type."""
        return self._type

    @property
    def underlying_element(self) -> Element | None:
        """Get the underlying element."""
        return self._underlying_element

    @property
    def direct(self) -> bool:
        """Get the direct flag."""
        return self._direct

    @property
    def subject_id(self) -> str:
        """Get the subject ID."""
        return self._subject_id

    @property
    def dependencies(self) -> dict[str, str]:
        """Get additional dependencies."""
        return self._dependencies

    def elementstring(self) -> str:
        """
        Format element as human-readable string.

        Returns:
            String in format "name | reference"
        """
        return f"{self._name} | {self._reference}"

    # =========================================================================
    # EpochSet Implementation
    # =========================================================================

    def buildepochtable(self) -> list[dict[str, Any]]:
        """
        Build the epoch table for this element.

        If direct=True, uses underlying_element's epochs directly.
        If direct=False, loads registered epochs from the database.

        Returns:
            List of epoch table entries
        """
        if self._direct and self._underlying_element is not None:
            # Use underlying element's epochs directly
            return self._build_direct_epochtable()
        else:
            # Load registered epochs from database
            return self._build_registered_epochtable()

    def _build_direct_epochtable(self) -> list[dict[str, Any]]:
        """Build epoch table from underlying element."""
        if self._underlying_element is None:
            return []

        underlying_et, _ = self._underlying_element.epochtable()
        et = []

        for i, entry in enumerate(underlying_et):
            et.append(
                {
                    "epoch_number": i + 1,
                    "epoch_id": entry.get("epoch_id", ""),
                    "epoch_session_id": entry.get("epoch_session_id", ""),
                    "epochprobemap": entry.get("epochprobemap", []),
                    "epoch_clock": entry.get("epoch_clock", []),
                    "t0_t1": entry.get("t0_t1", []),
                    "underlying_epochs": {
                        "underlying": self._underlying_element,
                        "epoch_id": entry.get("epoch_id", ""),
                        "epoch_session_id": entry.get("epoch_session_id", ""),
                        "epochprobemap": entry.get("epochprobemap", []),
                        "epoch_clock": entry.get("epoch_clock", []),
                        "t0_t1": entry.get("t0_t1", []),
                    },
                }
            )

        return et

    def _build_registered_epochtable(self) -> list[dict[str, Any]]:
        """Build epoch table from registered epochs in database."""
        if self._session is None:
            return []

        from ..query import Query

        # Query for registered epochs
        q = Query("").isa("element_epoch") & Query("").depends_on("element_id", self.id)
        epoch_docs = self._session.database_search(q)

        et = []
        for i, doc in enumerate(epoch_docs):
            props = doc.document_properties

            # Parse epoch_clock
            clock_raw = getattr(props.element_epoch, "epoch_clock", [])
            epoch_clock = []
            for c in clock_raw:
                if isinstance(c, str):
                    epoch_clock.append(ClockType(c))
                elif isinstance(c, ClockType):
                    epoch_clock.append(c)

            # Parse t0_t1
            t0t1_raw = getattr(props.element_epoch, "t0_t1", [])
            t0_t1 = []
            for t in t0t1_raw:
                if isinstance(t, (list, tuple)) and len(t) >= 2:
                    t0_t1.append((float(t[0]), float(t[1])))

            et.append(
                {
                    "epoch_number": i + 1,
                    "epoch_id": getattr(props.epochid, "epochid", ""),
                    "epoch_session_id": self._session.id() if self._session else "",
                    "epochprobemap": [],  # Registered epochs don't have probepmaps
                    "epoch_clock": epoch_clock,
                    "t0_t1": t0_t1,
                    "underlying_epochs": {},
                }
            )

        return et

    def epochsetname(self) -> str:
        """Return the name of this epoch set."""
        return f"element: {self._name} | {self._reference}"

    def issyncgraphroot(self) -> bool:
        """
        Check if this element is a sync graph root.

        Elements are typically roots (return True) unless they
        have underlying elements to traverse.

        Returns:
            True to stop traversal, False to continue
        """
        return self._underlying_element is None

    # =========================================================================
    # Epoch Management
    # =========================================================================

    def addepoch(
        self,
        epoch_id: str,
        epoch_clock: list[ClockType],
        t0_t1: list[tuple[float, float]],
    ) -> tuple[Element, Any]:
        """
        Add a new epoch to this element.

        Creates and stores an epoch document in the database.

        Args:
            epoch_id: Unique identifier for the epoch
            epoch_clock: List of clock types
            t0_t1: List of (t0, t1) time ranges

        Returns:
            Tuple of (self, epoch_document)

        Raises:
            ValueError: If direct=True (can't add epochs to direct elements)
        """
        if self._direct:
            raise ValueError("Cannot add epochs to direct elements")

        if self._session is None:
            raise ValueError("Session required to add epochs")

        from ..document import Document

        # Create epoch document
        doc = Document(
            "element_epoch",
            **{
                "element_epoch.epoch_clock": [str(c) for c in epoch_clock],
                "element_epoch.t0_t1": list(t0_t1),
                "epochid.epochid": epoch_id,
            },
        )
        doc.set_dependency_value("element_id", self.id)
        doc.set_session_id(self._session.id())

        # Add to database
        self._session.database_add(doc)

        # Clear cache
        self.clear_cache()

        return self, doc

    def loadaddedepochs(self) -> tuple[list[dict[str, Any]], list[Any]]:
        """
        Load registered epochs from the database.

        Returns:
            Tuple of (epoch_table, epoch_documents)
        """
        if self._session is None:
            return [], []

        from ..query import Query

        q = Query("").isa("element_epoch") & Query("").depends_on("element_id", self.id)
        epoch_docs = self._session.database_search(q)

        et = self._build_registered_epochtable()

        return et, epoch_docs

    # =========================================================================
    # DocumentService Implementation
    # =========================================================================

    def newdocument(self) -> Any:
        """
        Create a new document for this element.

        Returns:
            Document representing this element
        """
        from ..document import Document

        doc = Document(
            "element",
            **{
                "element.name": self._name,
                "element.reference": self._reference,
                "element.type": self._type,
                "element.direct": self._direct,
                "base.id": self.id,
            },
        )

        # Set session ID
        if self._session is not None:
            doc.set_session_id(self._session.id())

        # Set dependencies
        if self._subject_id:
            doc.set_dependency_value("subject_id", self._subject_id)

        if self._underlying_element is not None:
            doc.set_dependency_value("underlying_element_id", self._underlying_element.id)

        for name, value in self._dependencies.items():
            doc.set_dependency_value(name, value)

        return doc

    def searchquery(self) -> Any:
        """
        Create a query to find this element.

        Returns:
            Query matching this element's document
        """
        from ..query import Query

        q = Query("base.id") == self.id
        return q

    # =========================================================================
    # Cache Management
    # =========================================================================

    def getcache(self) -> tuple[Any | None, str]:
        """
        Get the session cache for this element.

        Returns:
            Tuple of (cache_object, cache_key)
        """
        if self._session is None:
            return None, ""

        cache = getattr(self._session, "cache", None)
        key = f"element_{self.id}"

        return cache, key

    # =========================================================================
    # Equality and Hashing
    # =========================================================================

    def __eq__(self, other: Any) -> bool:
        """Test equality by name, reference, and type."""
        if not isinstance(other, Element):
            return False
        return (
            self._name == other._name
            and self._reference == other._reference
            and self._type == other._type
        )

    def __hash__(self) -> int:
        """Hash by ID."""
        return hash(self.id)

    def __repr__(self) -> str:
        """String representation."""
        return f"Element({self._name}|{self._reference}|{self._type})"
