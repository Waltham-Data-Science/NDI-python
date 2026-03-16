"""
ndi.app.spikeextractor - Spike extraction from timeseries data.

Provides the ndi_app_spikeextractor app for detecting and extracting spike
waveforms from continuous electrophysiology recordings.

MATLAB equivalent: src/ndi/+ndi/+app/spikeextractor.m
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from . import ndi_app
from .appdoc import ndi_app_appdoc

if TYPE_CHECKING:
    from ..document import ndi_document
    from ..session.session_base import ndi_session


class ndi_app_spikeextractor(ndi_app, ndi_app_appdoc):
    """
    ndi_app for extracting spike waveforms from timeseries data.

    Detects threshold crossings in filtered neural data and extracts
    spike waveforms around each detected event.

    Doc types:
        - extraction_parameters: Filter and detection settings
        - extraction_parameters_modification: Overrides per epoch
        - spikewaves: Extracted waveform binary data

    Example:
        >>> extractor = ndi_app_spikeextractor(session)
        >>> extractor.extract(timeseries_obj, epoch=1)
    """

    def __init__(self, session: ndi_session | None = None):
        ndi_app.__init__(self, session=session, name="ndi_app_spikeextractor")
        ndi_app_appdoc.__init__(
            self,
            doc_types=["extraction_parameters", "extraction_parameters_modification", "spikewaves"],
            doc_document_types=[
                "apps/spikeextractor/spike_extraction_parameters",
                "apps/spikeextractor/spike_extraction_parameters_modification",
                "apps/spikeextractor/spikewaves",
            ],
        )

    def makefilterstruct(
        self,
        extraction_doc: ndi_document,
        sample_rate: float,
    ) -> dict[str, Any]:
        """
        Create a filter structure from extraction parameters.

        MATLAB equivalent: ndi.app.spikeextractor/makefilterstruct

        Args:
            extraction_doc: Extraction parameters document
            sample_rate: Sampling rate in Hz

        Returns:
            Dict with filter coefficients and parameters
        """
        raise NotImplementedError("makefilterstruct requires scipy.signal for filter design.")

    def filter(
        self,
        data_in: np.ndarray,
        filterstruct: dict[str, Any],
    ) -> np.ndarray:
        """
        Apply filter to data.

        MATLAB equivalent: ndi.app.spikeextractor/filter

        Args:
            data_in: Input data array
            filterstruct: Filter structure from makefilterstruct

        Returns:
            Filtered data array
        """
        raise NotImplementedError("filter requires scipy.signal for signal filtering.")

    def extract(
        self,
        ndi_timeseries_obj: Any,
        epoch: Any = None,
        extraction_name: str = "default",
        redo: bool = False,
        t0_t1: Any | None = None,
    ) -> None:
        """
        Extract spikes from a timeseries element.

        MATLAB equivalent: ndi.app.spikeextractor/extract

        Args:
            ndi_timeseries_obj: Timeseries element or probe
            epoch: ndi_epoch_epoch number/id or None for all epochs
            extraction_name: Name of extraction parameters to use
            redo: If True, re-extract even if results exist
            t0_t1: Optional time bounds [t0, t1]
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

    def struct2doc(self, appdoc_type: str, appdoc_struct: dict, **kwargs) -> ndi_document:
        from ..document import ndi_document

        return ndi_document(
            self.doc_document_types[self.doc_types.index(appdoc_type)],
            **{appdoc_type: appdoc_struct},
        )

    def find_appdoc(self, appdoc_type: str, **kwargs) -> list[ndi_document]:
        if self._session is None:
            return []
        from ..query import ndi_query

        q = ndi_query("").isa(appdoc_type)
        return self._session.database_search(q)

    def isvalid_appdoc_struct(self, appdoc_type: str, appdoc_struct: dict) -> tuple[bool, str]:
        """
        Validate an appdoc struct.

        MATLAB equivalent: ndi.app.spikeextractor/isvalid_appdoc_struct

        Returns:
            Tuple of (is_valid, error_message)
        """
        if appdoc_type == "extraction_parameters":
            if "filter" not in appdoc_struct or "threshold" not in appdoc_struct:
                return False, "extraction_parameters requires 'filter' and 'threshold' fields"
            return True, ""
        return True, ""

    def loaddata_appdoc(self, appdoc_type: str, *args, **kwargs) -> Any:
        """
        Load data from an app document.

        MATLAB equivalent: ndi.app.spikeextractor/loaddata_appdoc
        """
        return None

    def __repr__(self) -> str:
        return f"ndi_app_spikeextractor(session={self._session is not None})"
