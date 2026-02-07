"""
ndi.subject - Subject class for managing experimental subjects.

Subjects represent the experimental entities (animals, humans, etc.)
that are the source of recorded data. Each subject has a unique
local identifier (e.g., 'mouse23@vhlab.org') and a free-form description.
"""

from __future__ import annotations
import re
from typing import Any, Optional, Tuple, TYPE_CHECKING

from .ido import Ido
from .documentservice import DocumentService

if TYPE_CHECKING:
    from .document import Document
    from .query import Query


class Subject(Ido, DocumentService):
    """
    Represents an experimental subject.

    A Subject is identified by a local_identifier that must contain '@'
    (e.g., 'anteater23@nosuchlab.org') and an optional description.

    Can be created from scratch or loaded from a session database document.

    Attributes:
        local_identifier: Unique identifier with '@' separator
        description: Free-form description string

    Example:
        >>> subject = Subject('mouse23@vhlab.org', 'Laboratory mouse, strain C57BL/6')
        >>> doc = subject.newdocument()
    """

    def __init__(
        self,
        local_identifier_or_session: Any = '',
        description_or_document: Any = '',
        identifier: Optional[str] = None,
    ):
        """
        Create a new Subject.

        Forms:
            Subject(local_identifier, description)
            Subject(session, document_or_id)

        Args:
            local_identifier_or_session: Either a local_identifier string
                or a Session object (when loading from document)
            description_or_document: Either a description string
                or a Document/document_id (when loading from session)
            identifier: Optional unique identifier (auto-generated if None)
        """
        Ido.__init__(self, identifier)

        # Determine construction mode
        if hasattr(local_identifier_or_session, 'database_search'):
            # Loading from session + document
            session = local_identifier_or_session
            doc_or_id = description_or_document
            self._load_from_session(session, doc_or_id)
        else:
            # Creating from scratch
            local_identifier = str(local_identifier_or_session) if local_identifier_or_session else ''
            description = str(description_or_document) if description_or_document else ''

            if local_identifier:
                valid, msg = Subject.is_valid_local_identifier(local_identifier)
                if not valid:
                    raise ValueError(msg)

            self._local_identifier = local_identifier
            self._description = description

    def _load_from_session(self, session: Any, doc_or_id: Any) -> None:
        """Load subject from a session database document."""
        from .document import Document

        if isinstance(doc_or_id, str):
            # It's a document ID - look it up
            from .query import Query
            q = Query('base.id') == doc_or_id
            docs = session.database_search(q)
            if not docs:
                raise ValueError(f"No document found with id '{doc_or_id}'")
            doc = docs[0]
        elif isinstance(doc_or_id, Document):
            doc = doc_or_id
        else:
            raise TypeError(f"Expected Document or document ID string, got {type(doc_or_id)}")

        props = doc.document_properties
        subject_props = props.get('subject', {})

        self._local_identifier = subject_props.get('local_identifier', '')
        self._description = subject_props.get('description', '')

        # Use document ID as our identifier
        base_id = props.get('base', {}).get('id', '')
        if base_id:
            self.identifier = base_id

    @property
    def local_identifier(self) -> str:
        """Get the local identifier."""
        return self._local_identifier

    @property
    def description(self) -> str:
        """Get the description."""
        return self._description

    # =========================================================================
    # DocumentService Implementation
    # =========================================================================

    def newdocument(self) -> 'Document':
        """
        Create a new subject document.

        Returns:
            Document of type 'subject' with local_identifier and description
        """
        from .document import Document

        doc = Document(
            'subject',
            **{
                'subject.local_identifier': self._local_identifier,
                'subject.description': self._description,
                'base.id': self.id,
            }
        )
        return doc

    def searchquery(self) -> 'Query':
        """
        Create a query to find this subject in the database.

        Returns:
            Query matching subject by local_identifier
        """
        from .query import Query

        return (
            Query('').isa('subject') &
            (Query('subject.local_identifier') == self._local_identifier)
        )

    # =========================================================================
    # Validation
    # =========================================================================

    @staticmethod
    def is_valid_local_identifier(local_identifier: str) -> Tuple[bool, str]:
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

        if ' ' in local_identifier:
            return False, "local_identifier cannot contain spaces"

        if '@' not in local_identifier:
            return False, "local_identifier must contain '@' character"

        return True, ""

    @staticmethod
    def does_subjectstring_match_session_document(
        session: Any,
        subjectstring: str,
        make_if_missing: bool = False,
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if a subject string matches a subject in the session database.

        Args:
            session: Session to search
            subjectstring: Subject local_identifier to search for
            make_if_missing: If True, create the subject if not found

        Returns:
            Tuple of (found, subject_document_id)
        """
        from .query import Query

        q = (
            Query('').isa('subject') &
            (Query('subject.local_identifier') == subjectstring)
        )
        docs = session.database_search(q)

        if docs:
            return True, docs[0].id

        if make_if_missing:
            subject = Subject(subjectstring, '')
            doc = subject.newdocument()
            session.database_add(doc)
            return True, doc.id

        return False, None

    # =========================================================================
    # Equality and Representation
    # =========================================================================

    def __eq__(self, other: Any) -> bool:
        """Test equality by local_identifier."""
        if not isinstance(other, Subject):
            return False
        return self._local_identifier == other._local_identifier

    def __hash__(self) -> int:
        """Hash by ID."""
        return hash(self.id)

    def __repr__(self) -> str:
        """String representation."""
        return f"Subject('{self._local_identifier}')"
