"""
ndi.app.spikesorter - Spike sorting and clustering.

Provides the SpikeSorter app for clustering extracted spike waveforms
into putative single-neuron units.

MATLAB equivalent: src/ndi/+ndi/+app/spikesorter.m
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import App
from .appdoc import AppDoc

if TYPE_CHECKING:
    from ..document import Document
    from ..session.session_base import Session


class SpikeSorter(App, AppDoc):
    """
    App for clustering spikes into neuron units.

    Takes extracted spike waveforms (from SpikeExtractor) and
    clusters them using PCA and K-means or similar algorithms.

    Doc types:
        - sorting_parameters: Clustering algorithm settings
        - spike_clusters: Cluster assignments and statistics

    Example:
        >>> sorter = SpikeSorter(session)
        >>> sorter.spike_sort(timeseries_obj, 'default', 'default')
    """

    def __init__(self, session: Session | None = None):
        App.__init__(self, session=session, name="ndi_app_spikesorter")
        AppDoc.__init__(
            self,
            doc_types=["sorting_parameters", "spike_clusters"],
            doc_document_types=[
                "apps/spikesorter/sorting_parameters",
                "apps/spikesorter/spike_clusters",
            ],
        )

    @staticmethod
    def default_sorting_parameters() -> dict[str, Any]:
        """Return default sorting parameters."""
        return {
            "graphical_mode": False,
            "num_pca_features": 4,
            "interpolation": 2,
            "min_clusters": 1,
            "max_clusters": 5,
            "num_start": 5,
        }

    def spike_sort(
        self,
        timeseries_obj: Any,
        extraction_name: str = "default",
        sorting_name: str = "default",
        redo: bool = False,
    ) -> list[Document]:
        """
        Perform spike sorting on extracted spikes.

        Args:
            timeseries_obj: Source timeseries element
            extraction_name: Name of extraction parameters
            sorting_name: Name of sorting parameters
            redo: Re-sort even if results exist

        Returns:
            List of spike_clusters documents
        """
        raise NotImplementedError(
            "Full spike sorting requires sklearn.cluster. "
            "This class provides the framework structure."
        )

    def clusters2neurons(
        self,
        timeseries_obj: Any,
        sorting_name: str = "default",
        extraction_name: str = "default",
        redo: bool = False,
    ) -> list[Any]:
        """
        Create Neuron elements from cluster assignments.

        Args:
            timeseries_obj: Source timeseries element
            sorting_name: Name of sorting parameters
            extraction_name: Name of extraction parameters
            redo: Re-create even if neurons exist

        Returns:
            List of Neuron objects
        """
        raise NotImplementedError(
            "Full neuron creation from clusters requires additional infrastructure."
        )

    def struct2doc(self, appdoc_type: str, appdoc_struct: dict, **kwargs) -> Document:
        from ..document import Document

        return Document(
            self.doc_document_types[self.doc_types.index(appdoc_type)],
            **{appdoc_type: appdoc_struct},
        )

    def find_appdoc(self, appdoc_type: str, **kwargs) -> list[Document]:
        if self._session is None:
            return []
        from ..query import Query

        return self._session.database_search(Query("").isa(appdoc_type))

    def isvalid_appdoc_struct(self, appdoc_type: str, appdoc_struct: dict) -> bool:
        if appdoc_type == "sorting_parameters":
            return "num_pca_features" in appdoc_struct
        return True

    def __repr__(self) -> str:
        return f"SpikeSorter(session={self._session is not None})"
