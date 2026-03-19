"""
ndi.subject - ndi_subject class for managing experimental subjects.

Subjects represent the experimental entities (animals, humans, etc.)
that are the source of recorded data. Each subject has a unique
local identifier (e.g., 'mouse23@vhlab.org') and a free-form description.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .documentservice import ndi_documentservice
from .ido import ndi_ido

if TYPE_CHECKING:
    from .document import ndi_document
    from .query import ndi_query


class ndi_subject(ndi_ido, ndi_documentservice):
    """
    Represents an experimental subject.

    A ndi_subject is identified by a local_identifier that must contain '@'
    (e.g., 'anteater23@nosuchlab.org') and an optional description.

    Can be created from scratch or loaded from a session database document.

    Attributes:
        local_identifier: Unique identifier with '@' separator
        description: Free-form description string

    Example:
        >>> subject = ndi_subject('mouse23@vhlab.org', 'Laboratory mouse, strain C57BL/6')
        >>> doc = subject.newdocument()
    """

    def __init__(
        self,
        local_identifier_or_session: Any = "",
        description_or_document: Any = "",
        identifier: str | None = None,
    ):
        """
        Create a new ndi_subject.

        Forms:
            ndi_subject(local_identifier, description)
            ndi_subject(session, document_or_id)

        Args:
            local_identifier_or_session: Either a local_identifier string
                or a ndi_session object (when loading from document)
            description_or_document: Either a description string
                or a ndi_document/document_id (when loading from session)
            identifier: Optional unique identifier (auto-generated if None)
        """
        ndi_ido.__init__(self, identifier)

        # Determine construction mode
        if hasattr(local_identifier_or_session, "database_search"):
            # Loading from session + document
            session = local_identifier_or_session
            doc_or_id = description_or_document
            self._load_from_session(session, doc_or_id)
        else:
            # Creating from scratch
            local_identifier = (
                str(local_identifier_or_session) if local_identifier_or_session else ""
            )
            description = str(description_or_document) if description_or_document else ""

            if local_identifier:
                valid, msg = ndi_subject.is_valid_local_identifier(local_identifier)
                if not valid:
                    raise ValueError(msg)

            self._local_identifier = local_identifier
            self._description = description

    def _load_from_session(self, session: Any, doc_or_id: Any) -> None:
        """Load subject from a session database document."""
        from .document import ndi_document

        if isinstance(doc_or_id, str):
            # It's a document ID - look it up
            from .query import ndi_query

            q = ndi_query("base.id") == doc_or_id
            docs = session.database_search(q)
            if not docs:
                raise ValueError(f"No document found with id '{doc_or_id}'")
            doc = docs[0]
        elif isinstance(doc_or_id, ndi_document):
            doc = doc_or_id
        else:
            raise TypeError(f"Expected ndi_document or document ID string, got {type(doc_or_id)}")

        props = doc.document_properties
        subject_props = props.get("subject", {})

        self._local_identifier = subject_props.get("local_identifier", "")
        self._description = subject_props.get("description", "")

        # Use document ID as our identifier
        base_id = props.get("base", {}).get("id", "")
        if base_id:
            self._id = base_id

    @property
    def local_identifier(self) -> str:
        """Get the local identifier."""
        return self._local_identifier

    @property
    def description(self) -> str:
        """Get the description."""
        return self._description

    # =========================================================================
    # ndi_documentservice Implementation
    # =========================================================================

    def newdocument(self) -> ndi_document:
        """
        Create a new subject document.

        Returns:
            ndi_document of type 'subject' with local_identifier and description
        """
        from .document import ndi_document

        doc = ndi_document(
            "subject",
            **{
                "subject.local_identifier": self._local_identifier,
                "subject.description": self._description,
                "base.id": self.id,
            },
        )
        return doc

    def searchquery(self) -> ndi_query:
        """
        Create a query to find this subject in the database.

        Returns:
            ndi_query matching subject by local_identifier
        """
        from .query import ndi_query

        return ndi_query("").isa("subject") & (
            ndi_query("subject.local_identifier") == self._local_identifier
        )

    # =========================================================================
    # Validation
    # =========================================================================

    @staticmethod
    def is_valid_local_identifier(local_identifier: str) -> tuple[bool, str]:
        """
        Validate a local identifier string.

        Must contain '@' and have no spaces.

        Args:
            local_identifier: The identifier to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not isinstance(local_identifier, str):
            return False, "local_identifier must be a string"

        if not local_identifier:
            return False, "local_identifier cannot be empty"

        if " " in local_identifier:
            return False, "local_identifier cannot contain spaces"

        if "@" not in local_identifier:
            return False, "local_identifier must contain '@' character"

        return True, ""

    @staticmethod
    def does_subjectstring_match_session_document(
        session: Any,
        subjectstring: str,
        make_if_missing: bool = False,
    ) -> tuple[bool, str | None]:
        """
        Check if a subject string matches a subject in the session database.

        Args:
            session: ndi_session to search
            subjectstring: ndi_subject local_identifier to search for
            make_if_missing: If True, create the subject if not found

        Returns:
            Tuple of (found, subject_document_id)
        """
        from .query import ndi_query

        q = ndi_query("").isa("subject") & (ndi_query("subject.local_identifier") == subjectstring)
        docs = session.database_search(q)

        if docs:
            return True, docs[0].id

        if make_if_missing:
            subject = ndi_subject(subjectstring, "")
            doc = subject.newdocument()
            session.database_add(doc)
            return True, doc.id

        return False, None

    # =========================================================================
    # Equality and Representation
    # =========================================================================

    def __eq__(self, other: Any) -> bool:
        """Test equality by local_identifier."""
        if not isinstance(other, ndi_subject):
            return False
        return self._local_identifier == other._local_identifier

    def __hash__(self) -> int:
        """Hash by ID."""
        return hash(self.id)

    def __repr__(self) -> str:
        """String representation."""
        return f"ndi_subject('{self._local_identifier}')"
