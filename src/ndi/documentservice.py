"""
ndi.documentservice - Mixin for database document handling.

This module provides the ndi_documentservice mixin class that defines
the interface for objects that can be stored in and loaded from
the NDI database.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .document import ndi_document
    from .query import ndi_query


class ndi_documentservice(ABC):
    """
    Mixin for database document handling.

    ndi_documentservice defines the interface for objects that can be
    represented as documents in the NDI database. Classes that
    inherit from this mixin can create documents for storage and
    queries for retrieval.

    Subclasses must implement:
        - newdocument(): Create a new document for this object
        - searchquery(): Create a query to find this object

    Example:
        >>> class MyObject(ndi_documentservice):
        ...     def newdocument(self):
        ...         return ndi_document('myobject', **{'myobject.name': self.name})
        ...     def searchquery(self):
        ...         return ndi_query('base.id') == self.id
    """

    @abstractmethod
    def newdocument(self) -> ndi_document:
        """
        Create a new document for this object.

        Returns:
            ndi_document representing this object
        """
        pass

    @abstractmethod
    def searchquery(self) -> ndi_query:
        """
        Create a query to find this object in the database.

        Returns:
            ndi_query that matches this object's document
        """
        pass

    def load_element_doc(self, session: Any) -> ndi_document | None:
        """
        Load this object's document from the database.

        Args:
            session: ndi_session with database access

        Returns:
            ndi_document if found, None otherwise
        """
        q = self.searchquery()
        docs = session.database_search(q)
        if len(docs) == 1:
            return docs[0]
        return None

    def document_id(self, session: Any) -> str | None:
        """
        Get the document ID for this object.

        Args:
            session: ndi_session with database access

        Returns:
            ndi_document ID if found, None otherwise
        """
        doc = self.load_element_doc(session)
        if doc is not None:
            return doc.id
        return None
