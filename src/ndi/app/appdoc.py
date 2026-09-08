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
    from ..document import ndi_document


class DocExistsAction(str, Enum):
    """Action to take when a document already exists."""

    ERROR = "Error"
    NO_ACTION = "NoAction"
    REPLACE = "Replace"
    REPLACE_IF_DIFFERENT = "ReplaceIfDifferent"


class ndi_app_appdoc:
    """
    Mixin for application document management.

    Provides standardized CRUD operations for app-specific
    document types. Subclasses define their document types
    and implement struct2doc/doc2struct/find_appdoc.

    Attributes:
        doc_types: List of internal names for document types
        doc_document_types: List of NDI document schema types
        doc_session: ndi_session for database access
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
    ) -> list[ndi_document]:
        """
        Create and store an app document.

        Args:
            appdoc_type: The internal type name
            appdoc_struct: Dict of parameters, or None for defaults
            doc_exists_action: What to do if document exists

        Returns:
            List of created/found Documents
        """
        # Resolve appdoc_struct. MATLAB accepts an empty value (use the
        # defaults), an ndi.document (convert it back to a struct), or a
        # struct; anything else is an error. Only the empty case was handled
        # here, so a caller who passed the document they had just found got
        # it written back into struct2doc as if it were parameters.
        from ..document import ndi_document as _ndi_document

        if appdoc_struct is None:
            appdoc_struct = self.defaultstruct_appdoc(appdoc_type)
        elif isinstance(appdoc_struct, _ndi_document):
            appdoc_struct = self.doc2struct(appdoc_type, appdoc_struct)
        elif not isinstance(appdoc_struct, dict):
            raise TypeError(
                f"Do not know how to process appdoc_struct of type "
                f"{type(appdoc_struct).__name__}."
            )

        # Check for existing documents
        existing = self.find_appdoc(appdoc_type, *args, **kwargs)

        if existing:
            if doc_exists_action == DocExistsAction.ERROR:
                raise RuntimeError(
                    f"{len(existing)} document(s) of application document type "
                    f"'{appdoc_type}' already exist."
                )
            elif doc_exists_action == DocExistsAction.NO_ACTION:
                return existing
            elif doc_exists_action in (
                DocExistsAction.REPLACE,
                DocExistsAction.REPLACE_IF_DIFFERENT,
            ):
                # MATLAB: replace unless we were told to check AND there is
                # exactly one existing document that is equal to what we
                # want. MORE THAN ONE existing document counts as different
                # by itself -- "there are multiple versions, must be
                # different" -- where this returned as soon as ANY of them
                # matched, leaving the others in place.
                are_different = True
                if doc_exists_action == DocExistsAction.REPLACE_IF_DIFFERENT and len(existing) == 1:
                    existing_struct = self.doc2struct(appdoc_type, existing[0])
                    are_different = not self.isequal_appdoc_struct(
                        appdoc_type, appdoc_struct, existing_struct
                    )
                if not are_different:
                    return existing
                # MATLAB clears through clear_appdoc and ERRORS if that
                # fails; removing here under `except Exception: pass` left
                # the old documents in place and added a new one beside them.
                if not self.clear_appdoc(appdoc_type, *args, **kwargs):
                    raise RuntimeError(f"Could not delete existing '{appdoc_type}' document(s).")
            else:
                raise ValueError(f"Unknown doc_exists_action: {doc_exists_action}.")

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
    ) -> ndi_document | None:
        """
        Convert a parameter dict to an ndi.ndi_document.

        Base class returns None. Subclasses must override.
        """
        return None

    def doc2struct(
        self,
        appdoc_type: str,
        doc: ndi_document,
    ) -> dict:
        """
        Extract parameter dict from a ndi_document.

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
    ) -> list[ndi_document]:
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
            # Errors are not swallowed: add_appdoc reads this return value to
            # decide whether it is safe to write a replacement, so reporting
            # success for a removal that failed is how duplicates appear.
            for doc in docs:
                self.doc_session.database_rm(doc)
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

    def appdoc_description(self) -> str:
        """Describe the appdoc types this class offers.

        MATLAB equivalent: ``appdoc_description``, which every subclass
        overrides with a table of its document types. There was no Python
        counterpart, so a caller following MATLAB met an AttributeError; the
        base class lists what it knows and says the rest is for subclasses,
        which is what MATLAB's own base-class text says.
        """
        if not self.doc_types:
            return "The APPDOCs available to this class are the following:\n(none)"
        lines = ["The APPDOCs available to this class are the following:", ""]
        lines.append(f"{'APPDOC_TYPE':<26}| Document type")
        lines.append("-" * 80)
        document_types = list(self.doc_document_types) + [""] * len(self.doc_types)
        for appdoc_type, document_type in zip(self.doc_types, document_types):
            lines.append(f"{appdoc_type!r:<26}| {document_type}")
        return "\n".join(lines)
