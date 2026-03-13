"""
ndi.app.spikesorter - Spike sorting and clustering.

Provides the SpikeSorter app for clustering extracted spike waveforms
into putative single-neuron units.

MATLAB equivalent: src/ndi/+ndi/+app/spikesorter.m
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

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

    def check_sorting_parameters(
        self,
        sorting_parameters_struct: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Validate and fill defaults for sorting parameters.

        MATLAB equivalent: ndi.app.spikesorter/check_sorting_parameters

        Args:
            sorting_parameters_struct: Input sorting parameters

        Returns:
            Validated sorting parameters with defaults filled in
        """
        defaults = self.default_sorting_parameters()
        for key, value in defaults.items():
            if key not in sorting_parameters_struct:
                sorting_parameters_struct[key] = value
        return sorting_parameters_struct

    def loadwaveforms(
        self,
        ndi_timeseries_obj: Any,
        extraction_name: str = "default",
    ) -> tuple[np.ndarray, dict[str, Any], np.ndarray, list[dict], Any, list]:
        """
        Load extracted spike waveforms.

        MATLAB equivalent: ndi.app.spikesorter/loadwaveforms

        Args:
            ndi_timeseries_obj: Source timeseries element
            extraction_name: Name of extraction parameters

        Returns:
            Tuple of (waveforms, waveformparams, spiketimes,
            epochinfo, extraction_params_doc, waveform_docs)
        """
        raise NotImplementedError("loadwaveforms requires spike extraction results in database.")

    def spike_sort(
        self,
        ndi_timeseries_obj: Any,
        extraction_name: str = "default",
        sorting_parameters_name: str = "default",
        redo: bool = False,
    ) -> list[Document]:
        """
        Perform spike sorting on extracted spikes.

        MATLAB equivalent: ndi.app.spikesorter/spike_sort

        Args:
            ndi_timeseries_obj: Source timeseries element
            extraction_name: Name of extraction parameters
            sorting_parameters_name: Name of sorting parameters
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
        ndi_timeseries_obj: Any,
        sorting_parameters_name: str = "default",
        extraction_parameters_name: str = "default",
        redo: bool = False,
    ) -> None:
        """
        Create Neuron elements from cluster assignments.

        MATLAB equivalent: ndi.app.spikesorter/clusters2neurons

        Args:
            ndi_timeseries_obj: Source timeseries element
            sorting_parameters_name: Name of sorting parameters
            extraction_parameters_name: Name of extraction parameters
            redo: Re-create even if neurons exist
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

    def isvalid_appdoc_struct(self, appdoc_type: str, appdoc_struct: dict) -> tuple[bool, str]:
        """
        Validate an appdoc struct.

        MATLAB equivalent: ndi.app.spikesorter/isvalid_appdoc_struct

        Returns:
            Tuple of (is_valid, error_message)
        """
        if appdoc_type == "sorting_parameters":
            if "num_pca_features" not in appdoc_struct:
                return False, "sorting_parameters requires 'num_pca_features'"
            return True, ""
        return True, ""

    def loaddata_appdoc(self, appdoc_type: str, *args, **kwargs) -> Any:
        """
        Load data from an app document.

        MATLAB equivalent: ndi.app.spikesorter/loaddata_appdoc
        """
        return None

    def __repr__(self) -> str:
        return f"SpikeSorter(session={self._session is not None})"
