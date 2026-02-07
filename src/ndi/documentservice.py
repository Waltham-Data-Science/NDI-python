"""
ndi.documentservice - Mixin for database document handling.

This module provides the DocumentService mixin class that defines
the interface for objects that can be stored in and loaded from
the NDI database.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .document import Document
    from .query import Query


class DocumentService(ABC):
    """
    Mixin for database document handling.

    DocumentService defines the interface for objects that can be
    represented as documents in the NDI database. Classes that
    inherit from this mixin can create documents for storage and
    queries for retrieval.

    Subclasses must implement:
        - newdocument(): Create a new document for this object
        - searchquery(): Create a query to find this object

    Example:
        >>> class MyObject(DocumentService):
        ...     def newdocument(self):
        ...         return Document('myobject', **{'myobject.name': self.name})
        ...     def searchquery(self):
        ...         return Query('base.id') == self.id
    """

    @abstractmethod
    def newdocument(self) -> Document:
        """
        Create a new document for this object.

        Returns:
            Document representing this object
        """
        pass

    @abstractmethod
    def searchquery(self) -> Query:
        """
        Create a query to find this object in the database.

        Returns:
            Query that matches this object's document
        """
        pass

    def load_element_doc(self, session: Any) -> Document | None:
        """
        Load this object's document from the database.

        Args:
            session: Session with database access

        Returns:
            Document if found, None otherwise
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
            session: Session with database access

        Returns:
            Document ID if found, None otherwise
        """
        doc = self.load_element_doc(session)
        if doc is not None:
            return doc.id
        return None
