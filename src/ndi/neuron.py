"""
ndi.neuron - ndi_neuron element class.

A ndi_neuron is an ndi_element_timeseries with type='neuron'. It represents
a single neuron identified through spike sorting or other means.

Neurons are typically derived from probe-type elements and produce
time series data (spike times, waveforms, etc.).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .element_timeseries import ndi_element_timeseries

if TYPE_CHECKING:
    from .document import ndi_document
    from .query import ndi_query


class ndi_neuron(ndi_element_timeseries):
    """
    Represents a single neuron.

    Neurons are ndi_element_timeseries objects with type='neuron'. They
    are typically derived from electrode/probe data through spike
    sorting.

    The neuron document depends on:
    - underlying_element_id: The probe/electrode element
    - subject_id: The experimental subject

    Example:
        >>> neuron = ndi_neuron(
        ...     session=session,
        ...     name='neuron1',
        ...     reference=1,
        ...     underlying_element=probe_element,
        ... )
        >>> data, times, ref = neuron.readtimeseries(epoch_id, 0, 10)
    """

    def __init__(
        self,
        session: Any | None = None,
        name: str = "",
        reference: int = 0,
        underlying_element: Any | None = None,
        direct: bool = True,
        subject_id: str = "",
        dependencies: dict[str, str] | None = None,
        identifier: str | None = None,
        document: Any | None = None,
    ):
        """
        Create a new ndi_neuron.

        Args:
            session: ndi_session with database access
            name: ndi_neuron name
            reference: Reference number
            underlying_element: ndi_probe/electrode this neuron was sorted from
            direct: If True, use underlying element epochs
            subject_id: ndi_subject document ID
            dependencies: Additional named dependencies
            identifier: Optional unique identifier
            document: Optional document to load from
        """
        super().__init__(
            session=session,
            name=name,
            reference=reference,
            type="neuron",
            underlying_element=underlying_element,
            direct=direct,
            subject_id=subject_id,
            dependencies=dependencies,
            identifier=identifier,
            document=document,
        )

    def newdocument(self) -> ndi_document:
        """
        Create a new document for this neuron.

        Returns:
            ndi_document representing this neuron element
        """
        # Use parent's newdocument - type is already 'neuron'
        return super().newdocument()

    def searchquery(self) -> ndi_query:
        """
        Create a query to find this neuron.

        Returns:
            ndi_query matching this neuron by ID and type
        """
        from .query import ndi_query

        return ndi_query("base.id") == self.id

    def epochsetname(self) -> str:
        """Return the name of this epoch set."""
        return f"neuron: {self._name} | {self._reference}"

    def issyncgraphroot(self) -> bool:
        """Neurons are never sync graph roots."""
        return False

    def __repr__(self) -> str:
        """String representation."""
        return f"ndi_neuron({self._name}|{self._reference})"
