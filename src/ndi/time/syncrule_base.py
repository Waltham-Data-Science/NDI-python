"""
ndi.time.syncrule - Base class for synchronization rules.

This module provides the ndi_time_syncrule abstract base class for managing
synchronization between epochs and devices.
"""

from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Any

from ..ido import ndi_ido
from ..util.classname import ndi_matlab_classname
from .clocktype import ndi_time_clocktype
from .timemapping import ndi_time_timemapping

if TYPE_CHECKING:
    from ..document import ndi_document


class ndi_time_syncrule(ndi_ido, ABC):
    """
    Abstract base class for synchronization rules.

    ndi_time_syncrule objects define how to synchronize time between different
    epochs and devices. Subclasses implement specific synchronization
    strategies.

    Attributes:
        parameters: A dictionary of parameters for the sync rule
    """

    def __init__(
        self,
        parameters: dict[str, Any] | None = None,
        identifier: str | None = None,
    ):
        """
        Create a new ndi_time_syncrule.

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
    def parameters(self) -> dict[str, Any]:
        """Get the sync rule parameters."""
        return self._parameters.copy()

    def set_parameters(self, parameters: dict[str, Any]) -> None:
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

    def is_valid_parameters(self, parameters: dict[str, Any]) -> tuple[bool, str]:
        """
        Determine if a parameter structure is valid for this sync rule.

        Override in subclasses to provide specific validation.

        Args:
            parameters: Dictionary of parameters to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        return True, ""

    def eligible_clocks(self) -> list[ndi_time_clocktype]:
        """
        Return eligible clock types that can be used with this sync rule.

        If empty, no information is conveyed about which clock types
        are valid (i.e., no specific limits).

        Override in subclasses to restrict eligible clocks.

        Returns:
            List of eligible ndi_time_clocktype values
        """
        return []

    def ineligible_clocks(self) -> list[ndi_time_clocktype]:
        """
        Return ineligible clock types that cannot be used with this sync rule.

        If empty, no information is conveyed about which clock types
        are invalid (i.e., no specific limits).

        The base class returns [ndi_time_clocktype.NO_TIME].

        Returns:
            List of ineligible ndi_time_clocktype values
        """
        return [ndi_time_clocktype.NO_TIME]

    def eligible_epochsets(self) -> list[str]:
        """
        Return eligible epochset class names for this sync rule.

        If empty, no information is conveyed about which epochset
        subtypes can be processed.

        Override in subclasses to restrict eligible epochsets.

        Returns:
            List of eligible epochset class names
        """
        return []

    def ineligible_epochsets(self) -> list[str]:
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
        epochnode_a: dict[str, Any],
        epochnode_b: dict[str, Any],
        daqsystem1: Any = None,
    ) -> tuple[float | None, ndi_time_timemapping | None]:
        """
        Apply the sync rule to obtain cost and mapping between two epoch nodes.

        Override in subclasses to implement specific synchronization logic.

        Args:
            epochnode_a: First epoch node (dict with epoch_id, epoch_clock, etc.)
            epochnode_b: Second epoch node
            daqsystem1: The DAQ system object corresponding to epochnode_a

        Returns:
            Tuple of (cost, mapping) where:
            - cost is the synchronization cost (float or None if no sync possible)
            - mapping is the ndi_time_timemapping object (or None if no sync possible)
        """
        return None, None

    def __eq__(self, other: object) -> bool:
        """Check equality of two sync rules."""
        if not isinstance(other, ndi_time_syncrule):
            return NotImplemented
        return self._parameters == other._parameters

    def new_document(self) -> ndi_document:
        """
        Create a new ndi.ndi_document for this sync rule.

        Returns:
            ndi_document representing this sync rule
        """
        from ..document import ndi_document

        doc = ndi_document(
            document_type="daq/syncrule",
            **{
                "syncrule.ndi_syncrule_class": ndi_matlab_classname(self),
                "syncrule.parameters": self._parameters,
                "base.id": self.id,
            },
        )
        return doc

    def search_query(self) -> Any:
        """
        Create a search query for this sync rule object.

        Returns:
            ndi_query object to find this sync rule
        """
        from ..query import ndi_query

        return ndi_query("base.id") == self.id

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to dictionary for serialization.

        Returns:
            Dictionary representation
        """
        return {
            "id": self.id,
            "class": ndi_matlab_classname(self),
            "parameters": self._parameters,
        }

    @classmethod
    def from_document(cls, session: Any, doc: ndi_document) -> ndi_time_syncrule:
        """
        Create a ndi_time_syncrule from a document.

        This factory method creates the appropriate subclass based on
        the document's syncrule.ndi_syncrule_class field.

        Args:
            session: The session object
            doc: The document to load from

        Returns:
            ndi_time_syncrule instance of the appropriate subclass
        """
        # Get class name from document
        props = doc.document_properties
        class_name = props.get("syncrule", {}).get("ndi_syncrule_class", "ndi_time_syncrule")
        parameters = props.get("syncrule", {}).get("parameters", {})
        identifier = props.get("base", {}).get("id")

        # Import subclasses dynamically
        from . import syncrule as syncrule_module

        # Map class names to classes
        class_map = {
            "ndi_time_syncrule": ndi_time_syncrule,
            "ndi_time_syncrule_filematch": syncrule_module.ndi_time_syncrule_filematch,
            "ndi_time_syncrule_filefind": syncrule_module.ndi_time_syncrule_filefind,
            "ndi_time_syncrule_commonTriggersOverlappingEpochs": syncrule_module.ndi_time_syncrule_commonTriggersOverlappingEpochs,
            "ndi_time_syncrule_randomPulses": syncrule_module.ndi_time_syncrule_randomPulses,
        }

        rule_class = class_map.get(class_name, cls)

        # Abstract classes can't be instantiated directly
        if rule_class is ndi_time_syncrule:
            raise ValueError("Cannot instantiate abstract ndi_time_syncrule directly")

        return rule_class(parameters=parameters, identifier=identifier)
