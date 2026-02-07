"""
ndi.app.spikeextractor - Spike extraction from timeseries data.

Provides the SpikeExtractor app for detecting and extracting spike
waveforms from continuous electrophysiology recordings.

MATLAB equivalent: src/ndi/+ndi/+app/spikeextractor.m
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import App
from .appdoc import AppDoc

if TYPE_CHECKING:
    from ..document import Document
    from ..session.session_base import Session


class SpikeExtractor(App, AppDoc):
    """
    App for extracting spike waveforms from timeseries data.

    Detects threshold crossings in filtered neural data and extracts
    spike waveforms around each detected event.

    Doc types:
        - extraction_parameters: Filter and detection settings
        - extraction_parameters_modification: Overrides per epoch
        - spikewaves: Extracted waveform binary data

    Example:
        >>> extractor = SpikeExtractor(session)
        >>> extractor.extract(timeseries_obj, epoch=1)
    """

    def __init__(self, session: Session | None = None):
        App.__init__(self, session=session, name="ndi_app_spikeextractor")
        AppDoc.__init__(
            self,
            doc_types=["extraction_parameters", "extraction_parameters_modification", "spikewaves"],
            doc_document_types=[
                "apps/spikeextractor/spike_extraction_parameters",
                "apps/spikeextractor/spike_extraction_parameters_modification",
                "apps/spikeextractor/spikewaves",
            ],
        )

    def extract(
        self,
        timeseries_obj: Any,
        epoch: Any = None,
        extraction_name: str = "default",
        redo: bool = False,
        t0_t1: Any | None = None,
    ) -> list[Document]:
        """
        Extract spikes from a timeseries element.

        Args:
            timeseries_obj: Timeseries element or probe
            epoch: Epoch number/id or None for all epochs
            extraction_name: Name of extraction parameters to use
            redo: If True, re-extract even if results exist
            t0_t1: Optional time bounds [t0, t1]

        Returns:
            List of spikewaves documents created
        """
        raise NotImplementedError(
            "Full spike extraction requires scipy.signal. "
            "This class provides the framework structure."
        )

    @staticmethod
    def default_extraction_parameters() -> dict[str, Any]:
        """
        Return default spike extraction parameters.

        Returns:
            Dict with filter, threshold, and timing parameters
        """
        return {
            "filter": {
                "type": "cheby1",
                "order": 4,
                "low": 300,
                "high": 6000,
                "passband_ripple": 0.8,
            },
            "threshold": {
                "method": "std",
                "parameter": -4.0,
            },
            "timing": {
                "pre_samples": 10,
                "post_samples": 22,
                "refractory_samples": 10,
            },
        }

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

        q = Query("").isa(appdoc_type)
        return self._session.database_search(q)

    def isvalid_appdoc_struct(self, appdoc_type: str, appdoc_struct: dict) -> bool:
        if appdoc_type == "extraction_parameters":
            return "filter" in appdoc_struct and "threshold" in appdoc_struct
        return True

    def __repr__(self) -> str:
        return f"SpikeExtractor(session={self._session is not None})"
