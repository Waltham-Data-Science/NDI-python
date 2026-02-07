"""
ndi.app.appdoc - Mixin for application document management.

Provides CRUD operations for typed application documents,
abstracting the conversion between Python dicts and ndi.Documents.

MATLAB equivalent: src/ndi/+ndi/+app/appdoc.m
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..document import Document


class DocExistsAction(str, Enum):
    """Action to take when a document already exists."""

    ERROR = "Error"
    NO_ACTION = "NoAction"
    REPLACE = "Replace"
    REPLACE_IF_DIFFERENT = "ReplaceIfDifferent"


class AppDoc:
    """
    Mixin for application document management.

    Provides standardized CRUD operations for app-specific
    document types. Subclasses define their document types
    and implement struct2doc/doc2struct/find_appdoc.

    Attributes:
        doc_types: List of internal names for document types
        doc_document_types: List of NDI document schema types
        doc_session: Session for database access
    """

    def __init__(
        self,
        doc_types: list[str] | None = None,
        doc_document_types: list[str] | None = None,
        doc_session: Any = None,
    ):
        self.doc_types = doc_types or []
        self.doc_document_types = doc_document_types or []
        self.doc_session = doc_session

    def add_appdoc(
        self,
        appdoc_type: str,
        appdoc_struct: Any = None,
        doc_exists_action: DocExistsAction = DocExistsAction.ERROR,
        *args,
        **kwargs,
    ) -> list[Document]:
        """
        Create and store an app document.

        Args:
            appdoc_type: The internal type name
            appdoc_struct: Dict of parameters, or None for defaults
            doc_exists_action: What to do if document exists

        Returns:
            List of created/found Documents
        """
        # Get default struct if none provided
        if appdoc_struct is None:
            appdoc_struct = self.defaultstruct_appdoc(appdoc_type)

        # Check for existing documents
        existing = self.find_appdoc(appdoc_type, *args, **kwargs)

        if existing:
            if doc_exists_action == DocExistsAction.ERROR:
                raise RuntimeError(f"Document of type '{appdoc_type}' already exists")
            elif doc_exists_action == DocExistsAction.NO_ACTION:
                return existing
            elif doc_exists_action == DocExistsAction.REPLACE_IF_DIFFERENT:
                # Check if the existing doc matches
                for doc in existing:
                    existing_struct = self.doc2struct(appdoc_type, doc)
                    if self.isequal_appdoc_struct(appdoc_type, existing_struct, appdoc_struct):
                        return existing
                # Different - fall through to replace
                if self.doc_session is not None:
                    for doc in existing:
                        try:
                            self.doc_session.database_rm(doc)
                        except Exception:
                            pass
            elif doc_exists_action == DocExistsAction.REPLACE:
                if self.doc_session is not None:
                    for doc in existing:
                        try:
                            self.doc_session.database_rm(doc)
                        except Exception:
                            pass

        # Create new document
        doc = self.struct2doc(appdoc_type, appdoc_struct, *args, **kwargs)
        if doc is not None and self.doc_session is not None:
            self.doc_session.database_add(doc)
            return [doc]

        return []

    def struct2doc(
        self,
        appdoc_type: str,
        appdoc_struct: dict,
        *args,
        **kwargs,
    ) -> Document | None:
        """
        Convert a parameter dict to an ndi.Document.

        Base class returns None. Subclasses must override.
        """
        return None

    def doc2struct(
        self,
        appdoc_type: str,
        doc: Document,
    ) -> dict:
        """
        Extract parameter dict from a Document.

        Base class reads the property_list_name from the document.
        """
        props = doc.document_properties
        doc_class = props.get("document_class", {})
        property_list_name = doc_class.get("property_list_name", appdoc_type)
        return props.get(property_list_name, {})

    def defaultstruct_appdoc(self, appdoc_type: str) -> dict:
        """Return default parameters for the given appdoc type."""
        return {}

    def find_appdoc(
        self,
        appdoc_type: str,
        *args,
        **kwargs,
    ) -> list[Document]:
        """
        Find existing app documents in the database.

        Base class returns []. Subclasses must override.
        """
        return []

    def clear_appdoc(
        self,
        appdoc_type: str,
        *args,
        **kwargs,
    ) -> bool:
        """
        Remove app documents from the database.

        Returns True if documents were found and removed.
        """
        docs = self.find_appdoc(appdoc_type, *args, **kwargs)
        if docs and self.doc_session is not None:
            for doc in docs:
                try:
                    self.doc_session.database_rm(doc)
                except Exception:
                    pass
            return True
        return False

    def loaddata_appdoc(
        self,
        appdoc_type: str,
        *args,
        **kwargs,
    ) -> Any:
        """Load data from an app document. Base class returns None."""
        return None

    def isvalid_appdoc_struct(
        self,
        appdoc_type: str,
        appdoc_struct: dict,
    ) -> tuple[bool, str]:
        """Validate an appdoc struct. Base class returns (False, message)."""
        return False, "Base class always returns invalid"

    def isequal_appdoc_struct(
        self,
        appdoc_type: str,
        struct1: dict,
        struct2: dict,
    ) -> bool:
        """Compare two appdoc structs for equality."""
        return struct1 == struct2
