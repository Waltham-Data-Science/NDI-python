"""
ndi.element_timeseries - Time series element class.

This module provides ndi_element_timeseries, an extension of ndi_element that
can read and write time series data (e.g., voltage traces, spike times).

ndi_element_timeseries is the intermediate class between ndi_element and ndi_neuron.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .element import ndi_element
from .time import ndi_time_clocktype


class ndi_element_timeseries(ndi_element):
    """
    ndi_element that can store and retrieve time series data.

    Extends ndi_element with:
    - readtimeseries(): Read recorded data for an epoch
    - addepoch(): Add epoch with actual data (stores in VHSB format)
    - samplerate(): Get the sampling rate for a channel/epoch

    This is the base class for ndi_neuron and other data-producing elements.

    Example:
        >>> ts_elem = ndi_element_timeseries(
        ...     session=session, name='neuron1', reference=1,
        ...     type='neuron', underlying_element=probe,
        ... )
        >>> data, t, timeref = ts_elem.readtimeseries(epoch_ref, 0, 10)
    """

    def __init__(self, **kwargs):
        """
        Create a new ndi_element_timeseries.

        Takes the same arguments as ndi_element.
        """
        super().__init__(**kwargs)

    def readtimeseries(
        self,
        timeref_or_epoch: Any,
        t0: float = 0.0,
        t1: float = -1.0,
    ) -> tuple[np.ndarray, np.ndarray, Any | None]:
        """
        Read time series data from this element.

        Reads data from the underlying data source for a given epoch
        and time range.

        Args:
            timeref_or_epoch: ndi_time_timereference object or epoch number/id
            t0: Start time (seconds)
            t1: End time (seconds). -1 means end of epoch.

        Returns:
            Tuple of (data, times, timeref):
                - data: numpy array of shape (n_samples, n_channels)
                - times: numpy array of timestamps
                - timeref: ndi_time_timereference for the returned data

        Raises:
            ValueError: If no underlying element or data source available
        """
        if self._session is None:
            raise ValueError("ndi_session required to read time series")

        # Resolve epoch
        epoch_number = self._resolve_epoch(timeref_or_epoch)
        if epoch_number is None:
            raise ValueError(f"Could not resolve epoch: {timeref_or_epoch}")

        # Try to read from ingested data first
        data, times = self._read_from_ingested(epoch_number, t0, t1)
        if data is not None:
            return data, times, self._epoch_timeref(epoch_number)

        # Fall back to underlying element
        if self._underlying_element is not None and hasattr(
            self._underlying_element, "readtimeseries"
        ):
            return self._underlying_element.readtimeseries(timeref_or_epoch, t0, t1)

        # No data source available
        return np.array([]), np.array([]), None

    def _epoch_timeref(self, epoch_number: int) -> Any:
        """Build a concrete time reference for an ingested epoch's data.

        MATLAB readtimeseries always returns a real timeref (referent=self,
        the epoch's local clock, the epoch id, time 0); the previous Python
        implementation returned None, losing the time basis of the data
        (audit C8).
        """
        from .time.clocktype import ndi_time_clocktype
        from .time.timereference import ndi_time_timereference

        epoch_id = None
        clock = ndi_time_clocktype.DEV_LOCAL_TIME
        try:
            et, _ = self.epochtable()
            if 0 < epoch_number <= len(et):
                entry = et[epoch_number - 1]
                epoch_id = entry.get("epoch_id")
                clocks = entry.get("epoch_clock")
                if isinstance(clocks, list) and clocks:
                    clock = clocks[0]
                elif clocks is not None:
                    clock = clocks
        except Exception:
            pass

        try:
            return ndi_time_timereference(self, clock, epoch_id, 0)
        except Exception:
            return None

    def _resolve_epoch(self, timeref_or_epoch: Any) -> int | None:
        """Resolve a timeref/epoch to an epoch number."""
        if isinstance(timeref_or_epoch, int):
            return timeref_or_epoch

        if isinstance(timeref_or_epoch, str):
            # It's an epoch_id - find it
            et, _ = self.epochtable()
            for entry in et:
                if entry.get("epoch_id") == timeref_or_epoch:
                    return entry.get("epoch_number")
            return None

        # Try ndi_time_timereference
        if hasattr(timeref_or_epoch, "epoch"):
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
    ) -> tuple[np.ndarray | None, np.ndarray | None]:
        """
        Read data from ingested epoch documents.

        Looks for element_epoch documents that have associated binary data.

        Returns:
            Tuple of (data, times) or (None, None) if not available
        """
        if self._session is None:
            return None, None

        from .query import ndi_query

        # Find epoch document
        q = ndi_query("").isa("element_epoch") & ndi_query("").depends_on("element_id", self.id)
        epoch_docs = self._session.database_search(q)

        if epoch_number < 1 or epoch_number > len(epoch_docs):
            return None, None

        doc = epoch_docs[epoch_number - 1]

        # Read the VHSB binary (X time axis + Y data), windowed to [t0, t1].
        try:
            from .util.vhsb import vhsb_read

            exists, binary_path = self._session.database_existbinarydoc(
                doc, "epoch_binary_data.vhsb"
            )
            if not exists or not binary_path:
                return None, None

            lo = t0 if t0 is not None else -np.inf
            hi = t1 if (t1 is not None and t1 >= 0) else np.inf
            y, x = vhsb_read(str(binary_path), lo, hi)
            if y.size == 0:
                return None, None
            data = y.reshape(len(x), -1) if y.ndim == 1 else y
            return data, x
        except Exception:
            return None, None

    def _get_samplerate_from_doc(self, doc: Any) -> float:
        """Extract sample rate from an epoch document."""
        props = doc.document_properties
        ee = props.get("element_epoch", {})
        return float(ee.get("samplerate", 0))

    def addepoch(
        self,
        epoch_id: str,
        epoch_clock: list[ndi_time_clocktype],
        t0_t1: list[tuple[float, float]],
        timepoints: np.ndarray | None = None,
        datapoints: np.ndarray | None = None,
    ) -> tuple[ndi_element_timeseries, Any]:
        """
        Add a new epoch with optional time series data.

        Extends ndi_element.addepoch() to also store binary data
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
        has_data = timepoints is not None and datapoints is not None and self._session is not None

        # Build the epoch document. When there is binary data, defer the
        # database_add so the VHSB file can be attached first and ingested
        # together with the document (MATLAB element/timeseries.m:109-119).
        elem, doc = super().addepoch(epoch_id, epoch_clock, t0_t1, add_to_database=not has_data)

        if has_data:
            self._store_timeseries_data(doc, timepoints, datapoints)
            self._session.database_add(doc)
            self.resetepochtable()

        return self, doc

    def _store_timeseries_data(
        self,
        doc: Any,
        timepoints: np.ndarray,
        datapoints: np.ndarray,
    ) -> None:
        """Store time series data as a VHSB binary file attached to *doc*.

        Writes the X (time) axis alongside the Y (data) in VHSB format (the
        MATLAB filename ``epoch_binary_data.vhsb``) to a temp file and attaches
        it via ``add_file``; the document's ``database_add`` then ingests the
        file. The previous implementation wrote only ``datapoints.tobytes()``
        with no header — dropping the time axis and producing a file MATLAB
        could not read (audit C8).
        """
        if self._session is None:
            return

        import tempfile
        from pathlib import Path

        from .util.vhsb import vhsb_write

        timepoints = np.asarray(timepoints, dtype=np.float64)
        datapoints = np.asarray(datapoints, dtype=np.float64)

        tmp = Path(tempfile.mkdtemp()) / "epoch_binary_data.vhsb"
        vhsb_write(tmp, timepoints, datapoints)
        doc.add_file("epoch_binary_data.vhsb", str(tmp))

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
            if hasattr(self._underlying_element, "samplerate"):
                return self._underlying_element.samplerate(epoch)

        # Check epoch documents
        if self._session is not None and epoch is not None:
            epoch_number = self._resolve_epoch(epoch) if not isinstance(epoch, int) else epoch
            if epoch_number is not None:
                from .query import ndi_query

                q = ndi_query("").isa("element_epoch") & ndi_query("").depends_on(
                    "element_id", self.id
                )
                epoch_docs = self._session.database_search(q)
                if 0 < epoch_number <= len(epoch_docs):
                    return self._get_samplerate_from_doc(epoch_docs[epoch_number - 1])

        return 0.0

    def __repr__(self) -> str:
        """String representation."""
        return f"ndi_element_timeseries({self._name}|{self._reference}|{self._type})"
