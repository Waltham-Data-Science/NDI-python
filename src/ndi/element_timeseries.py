"""
ndi.element_timeseries - Time series element class.

This module provides ElementTimeseries, an extension of Element that
can read and write time series data (e.g., voltage traces, spike times).

ElementTimeseries is the intermediate class between Element and Neuron.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

from .element import Element
from .time import ClockType


class ElementTimeseries(Element):
    """
    Element that can store and retrieve time series data.

    Extends Element with:
    - readtimeseries(): Read recorded data for an epoch
    - addepoch(): Add epoch with actual data (stores in VHSB format)
    - samplerate(): Get the sampling rate for a channel/epoch

    This is the base class for Neuron and other data-producing elements.

    Example:
        >>> ts_elem = ElementTimeseries(
        ...     session=session, name='neuron1', reference=1,
        ...     type='neuron', underlying_element=probe,
        ... )
        >>> data, t, timeref = ts_elem.readtimeseries(epoch_ref, 0, 10)
    """

    def __init__(self, **kwargs):
        """
        Create a new ElementTimeseries.

        Takes the same arguments as Element.
        """
        super().__init__(**kwargs)

    def readtimeseries(
        self,
        timeref_or_epoch: Any,
        t0: float = 0.0,
        t1: float = -1.0,
    ) -> Tuple[np.ndarray, np.ndarray, Optional[Any]]:
        """
        Read time series data from this element.

        Reads data from the underlying data source for a given epoch
        and time range.

        Args:
            timeref_or_epoch: TimeReference object or epoch number/id
            t0: Start time (seconds)
            t1: End time (seconds). -1 means end of epoch.

        Returns:
            Tuple of (data, times, timeref):
                - data: numpy array of shape (n_samples, n_channels)
                - times: numpy array of timestamps
                - timeref: TimeReference for the returned data

        Raises:
            ValueError: If no underlying element or data source available
        """
        if self._session is None:
            raise ValueError("Session required to read time series")

        # Resolve epoch
        epoch_number = self._resolve_epoch(timeref_or_epoch)
        if epoch_number is None:
            raise ValueError(f"Could not resolve epoch: {timeref_or_epoch}")

        # Try to read from ingested data first
        data, times = self._read_from_ingested(epoch_number, t0, t1)
        if data is not None:
            return data, times, None

        # Fall back to underlying element
        if self._underlying_element is not None and hasattr(self._underlying_element, 'readtimeseries'):
            return self._underlying_element.readtimeseries(timeref_or_epoch, t0, t1)

        # No data source available
        return np.array([]), np.array([]), None

    def _resolve_epoch(self, timeref_or_epoch: Any) -> Optional[int]:
        """Resolve a timeref/epoch to an epoch number."""
        if isinstance(timeref_or_epoch, int):
            return timeref_or_epoch

        if isinstance(timeref_or_epoch, str):
            # It's an epoch_id - find it
            et, _ = self.epochtable()
            for entry in et:
                if entry.get('epoch_id') == timeref_or_epoch:
                    return entry.get('epoch_number')
            return None

        # Try TimeReference
        if hasattr(timeref_or_epoch, 'epoch'):
            epoch = timeref_or_epoch.epoch
            if isinstance(epoch, int):
                return epoch
            return self._resolve_epoch(epoch)

        return None

    def _read_from_ingested(
        self,
        epoch_number: int,
        t0: float,
        t1: float,
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """
        Read data from ingested epoch documents.

        Looks for element_epoch documents that have associated binary data.

        Returns:
            Tuple of (data, times) or (None, None) if not available
        """
        if self._session is None:
            return None, None

        from .query import Query

        # Find epoch document
        q = (
            Query('').isa('element_epoch') &
            Query('').depends_on('element_id', self.id)
        )
        epoch_docs = self._session.database_search(q)

        if epoch_number < 1 or epoch_number > len(epoch_docs):
            return None, None

        doc = epoch_docs[epoch_number - 1]

        # Check for binary data
        try:
            exists, binary_path = self._session.database_existbinarydoc(doc, 'timeseries.vhsb')
            if not exists:
                return None, None

            # Read VHSB file
            fid = self._session.database_openbinarydoc(doc, 'timeseries.vhsb')
            if fid is None:
                return None, None

            try:
                raw_data = fid.read()
                if not raw_data:
                    return None, None
                # Parse VHSB format
                data = np.frombuffer(raw_data, dtype=np.float64)
                # Reconstruct time array
                sr = self._get_samplerate_from_doc(doc)
                if sr > 0 and len(data) > 0:
                    times = np.arange(len(data)) / sr
                    return data.reshape(-1, 1), times
                return data.reshape(-1, 1), np.arange(len(data), dtype=np.float64)
            finally:
                self._session.database_closebinarydoc(fid)

        except Exception:
            return None, None

    def _get_samplerate_from_doc(self, doc: Any) -> float:
        """Extract sample rate from an epoch document."""
        props = doc.document_properties
        ee = props.get('element_epoch', {})
        return float(ee.get('samplerate', 0))

    def addepoch(
        self,
        epoch_id: str,
        epoch_clock: List[ClockType],
        t0_t1: List[Tuple[float, float]],
        timepoints: Optional[np.ndarray] = None,
        datapoints: Optional[np.ndarray] = None,
    ) -> Tuple['ElementTimeseries', Any]:
        """
        Add a new epoch with optional time series data.

        Extends Element.addepoch() to also store binary data
        if timepoints and datapoints are provided.

        Args:
            epoch_id: Unique identifier for the epoch
            epoch_clock: List of clock types
            t0_t1: List of (t0, t1) time ranges
            timepoints: Optional array of time values
            datapoints: Optional array of data values

        Returns:
            Tuple of (self, epoch_document)
        """
        # Create the epoch document via parent
        elem, doc = super().addepoch(epoch_id, epoch_clock, t0_t1)

        # Store binary data if provided
        if timepoints is not None and datapoints is not None and self._session is not None:
            self._store_timeseries_data(doc, timepoints, datapoints)

        return self, doc

    def _store_timeseries_data(
        self,
        doc: Any,
        timepoints: np.ndarray,
        datapoints: np.ndarray,
    ) -> None:
        """Store time series data as binary file attached to document."""
        if self._session is None:
            return

        timepoints = np.asarray(timepoints, dtype=np.float64)
        datapoints = np.asarray(datapoints, dtype=np.float64)

        try:
            fid = self._session.database_openbinarydoc(doc, 'timeseries.vhsb')
            if fid is not None:
                # Write data in simple format: timepoints then datapoints
                fid.write(datapoints.tobytes())
                self._session.database_closebinarydoc(fid)
        except Exception:
            pass  # Binary storage is best-effort

    def samplerate(self, epoch: Any = None) -> float:
        """
        Get the sample rate for this element.

        Args:
            epoch: Optional epoch number or id

        Returns:
            Sample rate in Hz, or 0 if unknown
        """
        # Check underlying element
        if self._underlying_element is not None:
            if hasattr(self._underlying_element, 'samplerate'):
                return self._underlying_element.samplerate(epoch)

        # Check epoch documents
        if self._session is not None and epoch is not None:
            epoch_number = self._resolve_epoch(epoch) if not isinstance(epoch, int) else epoch
            if epoch_number is not None:
                from .query import Query
                q = (
                    Query('').isa('element_epoch') &
                    Query('').depends_on('element_id', self.id)
                )
                epoch_docs = self._session.database_search(q)
                if 0 < epoch_number <= len(epoch_docs):
                    return self._get_samplerate_from_doc(epoch_docs[epoch_number - 1])

        return 0.0

    def __repr__(self) -> str:
        """String representation."""
        return f"ElementTimeseries({self._name}|{self._reference}|{self._type})"
