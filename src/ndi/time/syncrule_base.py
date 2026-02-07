"""
ndi.time.syncrule - Base class for synchronization rules.

This module provides the SyncRule abstract base class for managing
synchronization between epochs and devices.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from ..ido import Ido
from .clocktype import ClockType
from .timemapping import TimeMapping

if TYPE_CHECKING:
    from ..document import Document


class SyncRule(Ido, ABC):
    """
    Abstract base class for synchronization rules.

    SyncRule objects define how to synchronize time between different
    epochs and devices. Subclasses implement specific synchronization
    strategies.

    Attributes:
        parameters: A dictionary of parameters for the sync rule
    """

    def __init__(
        self,
        parameters: Optional[Dict[str, Any]] = None,
        identifier: Optional[str] = None,
    ):
        """
        Create a new SyncRule.

        Args:
            parameters: Parameters for the sync rule (must be valid)
            identifier: Optional identifier (generated if not provided)

        Raises:
            ValueError: If parameters are invalid
        """
        super().__init__(identifier)

        if parameters is None:
            parameters = {}

        self._parameters = {}
        self.set_parameters(parameters)

    @property
    def parameters(self) -> Dict[str, Any]:
        """Get the sync rule parameters."""
        return self._parameters.copy()

    def set_parameters(self, parameters: Dict[str, Any]) -> None:
        """
        Set the parameters for this sync rule, checking for validity.

        Args:
            parameters: Dictionary of parameters

        Raises:
            ValueError: If parameters are invalid
        """
        is_valid, msg = self.is_valid_parameters(parameters)
        if not is_valid:
            raise ValueError(f"Could not set parameters: {msg}")
        self._parameters = parameters.copy()

    def is_valid_parameters(self, parameters: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Determine if a parameter structure is valid for this sync rule.

        Override in subclasses to provide specific validation.

        Args:
            parameters: Dictionary of parameters to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        return True, ""

    def eligible_clocks(self) -> List[ClockType]:
        """
        Return eligible clock types that can be used with this sync rule.

        If empty, no information is conveyed about which clock types
        are valid (i.e., no specific limits).

        Override in subclasses to restrict eligible clocks.

        Returns:
            List of eligible ClockType values
        """
        return []

    def ineligible_clocks(self) -> List[ClockType]:
        """
        Return ineligible clock types that cannot be used with this sync rule.

        If empty, no information is conveyed about which clock types
        are invalid (i.e., no specific limits).

        The base class returns [ClockType.NO_TIME].

        Returns:
            List of ineligible ClockType values
        """
        return [ClockType.NO_TIME]

    def eligible_epochsets(self) -> List[str]:
        """
        Return eligible epochset class names for this sync rule.

        If empty, no information is conveyed about which epochset
        subtypes can be processed.

        Override in subclasses to restrict eligible epochsets.

        Returns:
            List of eligible epochset class names
        """
        return []

    def ineligible_epochsets(self) -> List[str]:
        """
        Return ineligible epochset class names for this sync rule.

        If empty, no information is conveyed about which epochset
        subtypes cannot be processed.

        Override in subclasses to specify ineligible epochsets.

        Returns:
            List of ineligible epochset class names
        """
        return []

    def apply(
        self,
        epochnode_a: Dict[str, Any],
        epochnode_b: Dict[str, Any],
    ) -> Tuple[Optional[float], Optional[TimeMapping]]:
        """
        Apply the sync rule to obtain cost and mapping between two epoch nodes.

        Override in subclasses to implement specific synchronization logic.

        Args:
            epochnode_a: First epoch node (dict with epoch_id, epoch_clock, etc.)
            epochnode_b: Second epoch node

        Returns:
            Tuple of (cost, mapping) where:
            - cost is the synchronization cost (float or None if no sync possible)
            - mapping is the TimeMapping object (or None if no sync possible)
        """
        return None, None

    def __eq__(self, other: object) -> bool:
        """Check equality of two sync rules."""
        if not isinstance(other, SyncRule):
            return NotImplemented
        return self._parameters == other._parameters

    def new_document(self) -> 'Document':
        """
        Create a new ndi.Document for this sync rule.

        Returns:
            Document representing this sync rule
        """
        from ..document import Document

        doc = Document(
            document_type='daq/syncrule',
            **{
                'syncrule.ndi_syncrule_class': type(self).__name__,
                'syncrule.parameters': self._parameters,
                'base.id': self.id,
            }
        )
        return doc

    def search_query(self) -> Any:
        """
        Create a search query for this sync rule object.

        Returns:
            Query object to find this sync rule
        """
        from ..query import Query
        return Query('base.id') == self.id

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.

        Returns:
            Dictionary representation
        """
        return {
            'id': self.id,
            'class': type(self).__name__,
            'parameters': self._parameters,
        }

    @classmethod
    def from_document(cls, session: Any, doc: 'Document') -> 'SyncRule':
        """
        Create a SyncRule from a document.

        This factory method creates the appropriate subclass based on
        the document's syncrule.ndi_syncrule_class field.

        Args:
            session: The session object
            doc: The document to load from

        Returns:
            SyncRule instance of the appropriate subclass
        """
        # Get class name from document
        props = doc.document_properties
        class_name = props.get('syncrule', {}).get('ndi_syncrule_class', 'SyncRule')
        parameters = props.get('syncrule', {}).get('parameters', {})
        identifier = props.get('base', {}).get('id')

        # Import subclasses dynamically
        from . import syncrule as syncrule_module

        # Map class names to classes
        class_map = {
            'SyncRule': SyncRule,
            'FileMatch': syncrule_module.FileMatch,
            'FileFind': syncrule_module.FileFind,
        }

        rule_class = class_map.get(class_name, cls)

        # Abstract classes can't be instantiated directly
        if rule_class is SyncRule:
            raise ValueError(f"Cannot instantiate abstract SyncRule directly")

        return rule_class(parameters=parameters, identifier=identifier)
