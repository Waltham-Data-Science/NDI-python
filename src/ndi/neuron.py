"""
ndi.neuron - Neuron element class.

A Neuron is an ElementTimeseries with type='neuron'. It represents
a single neuron identified through spike sorting or other means.

Neurons are typically derived from probe-type elements and produce
time series data (spike times, waveforms, etc.).
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

import numpy as np

from .element_timeseries import ElementTimeseries

if TYPE_CHECKING:
    from .document import Document
    from .query import Query


class Neuron(ElementTimeseries):
    """
    Represents a single neuron.

    Neurons are ElementTimeseries objects with type='neuron'. They
    are typically derived from electrode/probe data through spike
    sorting.

    The neuron document depends on:
    - underlying_element_id: The probe/electrode element
    - subject_id: The experimental subject

    Example:
        >>> neuron = Neuron(
        ...     session=session,
        ...     name='neuron1',
        ...     reference=1,
        ...     underlying_element=probe_element,
        ... )
        >>> data, times, ref = neuron.readtimeseries(epoch_id, 0, 10)
    """

    def __init__(
        self,
        session: Optional[Any] = None,
        name: str = '',
        reference: int = 0,
        underlying_element: Optional[Any] = None,
        direct: bool = True,
        subject_id: str = '',
        dependencies: Optional[Dict[str, str]] = None,
        identifier: Optional[str] = None,
        document: Optional[Any] = None,
    ):
        """
        Create a new Neuron.

        Args:
            session: Session with database access
            name: Neuron name
            reference: Reference number
            underlying_element: Probe/electrode this neuron was sorted from
            direct: If True, use underlying element epochs
            subject_id: Subject document ID
            dependencies: Additional named dependencies
            identifier: Optional unique identifier
            document: Optional document to load from
        """
        super().__init__(
            session=session,
            name=name,
            reference=reference,
            type='neuron',
            underlying_element=underlying_element,
            direct=direct,
            subject_id=subject_id,
            dependencies=dependencies,
            identifier=identifier,
            document=document,
        )

    def newdocument(self) -> 'Document':
        """
        Create a new document for this neuron.

        Returns:
            Document representing this neuron element
        """
        # Use parent's newdocument - type is already 'neuron'
        return super().newdocument()

    def searchquery(self) -> 'Query':
        """
        Create a query to find this neuron.

        Returns:
            Query matching this neuron by ID and type
        """
        from .query import Query

        return (
            Query('base.id') == self.id
        )

    def epochsetname(self) -> str:
        """Return the name of this epoch set."""
        return f"neuron: {self._name} | {self._reference}"

    def issyncgraphroot(self) -> bool:
        """Neurons are never sync graph roots."""
        return False

    def __repr__(self) -> str:
        """String representation."""
        return f"Neuron({self._name}|{self._reference})"
