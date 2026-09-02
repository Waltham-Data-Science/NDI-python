"""
ndi.element_timeseries - Time series element class.

This module provides ndi_element_timeseries, an extension of ndi_element that
can read and write time series data (e.g., voltage traces, spike times).

ndi_element_timeseries is the intermediate class between ndi_element and ndi_neuron.

Epoch data is stored in **VHSB**, the VH-Lab series binary format, in a
document file named ``epoch_binary_data.vhsb`` -- byte-for-byte the same
contract as MATLAB's ``ndi.element.timeseries``:

    MATLAB   vlt.file.custom_file_formats.vhsb_write(fname, timepoints, datapoints, 'use_filelock', 0)
             epochdoc.add_file('epoch_binary_data.vhsb', fname)
    Python   vlt.file.custom_file_formats.vhsb_write(fname, timepoints, datapoints, use_filelock=0)
             doc.add_file(BINARY_FILE_NAME, fname)

VHSB stores a timestamp per sample whenever the sampling interval is not
constant, which is what makes it usable for a **marked point process** -- an
ensemble epoch, where the spike times are irregular and *are* the data. An
implementation that stores only the data and reconstructs times from a sample
rate is correct for a regularly sampled trace and silently wrong for spikes.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from .element import ndi_element
from .time import ndi_time_clocktype

#: The document file name both languages use for an epoch's binary data. It is
#: also the only name ``element_epoch.json`` declares in its ``file_list``, in
#: both repositories, so nothing else can be attached under this document.
BINARY_FILE_NAME = "epoch_binary_data.vhsb"


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

        # Resolve to an epoch ID. MATLAB queries the epoch document by
        # epochid.epochid; resolving to a position and indexing a search
        # result would depend on the database returning documents in a
        # defined order, which it does not promise.
        #
        # An epoch we cannot resolve, or one with no stored binary, is not an
        # error here: it falls through to the underlying element, which may
        # well have that epoch. MATLAB errors instead ("Could not find
        # epochdoc for epoch X") because it reaches this code only for a
        # non-direct element. That asymmetry is pre-existing and is left
        # alone; changing it would turn the documented empty return of
        # readtimeseries on an element with no data into a raise.
        epoch_id = self._resolve_epoch_id(timeref_or_epoch)
        data, times = (
            (None, None) if epoch_id is None else self._read_from_ingested(epoch_id, t0, t1)
        )
        if data is not None:
            return data, times, None

        # Fall back to underlying element
        if self._underlying_element is not None and hasattr(
            self._underlying_element, "readtimeseries"
        ):
            return self._underlying_element.readtimeseries(timeref_or_epoch, t0, t1)

        # No data source available
        return np.array([]), np.array([]), None

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

    def _resolve_epoch_id(self, timeref_or_epoch: Any) -> str | None:
        """Resolve a timeref / epoch number / epoch id to an epoch ID string."""
        if isinstance(timeref_or_epoch, str):
            return timeref_or_epoch

        if isinstance(timeref_or_epoch, int):
            et, _ = self.epochtable()
            for entry in et:
                if entry.get("epoch_number") == timeref_or_epoch:
                    return entry.get("epoch_id")
            return None

        if hasattr(timeref_or_epoch, "epoch"):
            return self._resolve_epoch_id(timeref_or_epoch.epoch)

        return None

    def _epoch_document(self, epoch_id: str) -> Any | None:
        """The element_epoch document for EPOCH_ID, or None.

        Mirrors the MATLAB query in ndi.element.timeseries/readtimeseries:
        isa element_epoch, depends_on element_id, and an exact epochid match.
        """
        from .query import ndi_query

        q = (
            ndi_query("").isa("element_epoch")
            & ndi_query("").depends_on("element_id", self.id)
            & ndi_query("epochid.epochid", "exact_string", epoch_id, "")
        )
        docs = self._session.database_search(q)
        if not docs:
            return None
        return docs[0]

    def _read_from_ingested(
        self,
        epoch_id: str,
        t0: float,
        t1: float,
    ) -> tuple[np.ndarray | None, np.ndarray | None]:
        """
        Read one epoch's data back out of its VHSB binary.

        Returns:
            Tuple of (data, times), or (None, None) when this epoch has no
            stored binary -- which is not an error: the caller then falls back
            to the underlying element.

        ``vhsb_read`` returns ``(y, x)`` -- data first, times second -- which
        is the order MATLAB's ``[data, t] = vhsb_read(...)`` uses, and the
        order ``readtimeseries`` returns them in. Getting it backwards
        produces two arrays of the right length and entirely wrong content,
        so it is spelled out rather than left to the reader.
        """
        if self._session is None:
            return None, None

        from vlt.file.custom_file_formats import vhsb_read

        doc = self._epoch_document(epoch_id)
        if doc is None:
            return None, None

        exists, _ = self._session.database_existbinarydoc(doc, BINARY_FILE_NAME)
        if not exists:
            return None, None

        fid = self._session.database_openbinarydoc(doc, BINARY_FILE_NAME)
        try:
            # The handle carries fullpathfilename, which is what
            # vlt.file.filename_value reads -- the same way MATLAB hands its
            # ndi.database.binarydoc straight to vhsb_read.
            data, times = vhsb_read(fid, t0, t1)
        finally:
            self._session.database_closebinarydoc(fid)

        data = np.asarray(data)
        if data.ndim == 1:
            data = data.reshape(-1, 1)
        return data, np.asarray(times).ravel()

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
        *,
        add_to_database: bool = True,
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
            add_to_database: When False, the document is built and the binary
                attached, but the document is NOT added -- the caller adds it,
                typically because a second document depends on this one's id
                and both must land together. Mirrors the base class's
                argument of the same name, which in turn is MATLAB's
                ``nargout<2`` deferral made explicit.

        Returns:
            Tuple of (self, epoch_document)

        The binary is attached BEFORE the document reaches the database,
        because ``add_file`` records the file on the document and a document
        already in the database is not revisited. MATLAB gets the same
        ordering from its ``nargout<2`` deferral in
        ``ndi.element.timeseries/addepoch``; ``add_to_database`` is the
        explicit form of that, since Python has no ``nargout``.
        """
        has_data = timepoints is not None and datapoints is not None

        if not has_data or self._session is None:
            return super().addepoch(epoch_id, epoch_clock, t0_t1, add_to_database=add_to_database)

        _, doc = super().addepoch(epoch_id, epoch_clock, t0_t1, add_to_database=False)
        doc = self._attach_timeseries_data(doc, timepoints, datapoints)
        if add_to_database:
            self._session.database_add(doc)
            self.resetepochtable()
        return self, doc

    def _attach_timeseries_data(
        self,
        doc: Any,
        timepoints: np.ndarray,
        datapoints: np.ndarray,
    ) -> Any:
        """Write the epoch's samples to a VHSB file and attach it to DOC.

        Errors are NOT swallowed. The previous implementation wrapped this in
        a bare ``except Exception: pass`` under the banner "binary storage is
        best-effort", which meant a caller that stored an epoch and got no
        exception still had nothing on disk. Storage either happens or says
        why.
        """
        from vlt.file.custom_file_formats import vhsb_write

        timepoints = np.asarray(timepoints, dtype=np.float64).reshape(-1, 1)
        datapoints = np.asarray(datapoints, dtype=np.float64)
        if datapoints.ndim == 1:
            datapoints = datapoints.reshape(-1, 1)
        if len(timepoints) != len(datapoints):
            raise ValueError(
                f"timepoints and datapoints must have the same number of samples; "
                f"got {len(timepoints)} and {len(datapoints)}."
            )

        # MATLAB writes to <TempFolder>/<epochdoc.id()>.vhsb and then attaches
        # it under the document name; the temp name is not part of the
        # contract but matching it keeps the two behaving alike.
        tmpdir = tempfile.mkdtemp(prefix="ndi-vhsb-")
        fname = os.path.join(tmpdir, f"{doc.id}.vhsb")
        vhsb_write(fname, timepoints, datapoints, use_filelock=0)
        return doc.add_file(BINARY_FILE_NAME, fname)

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

    # ------------------------------------------------------------------
    # batched creation
    # ------------------------------------------------------------------
    @staticmethod
    def add_multiple(
        session: Any,
        underlying_element: Any,
        specs: Sequence[Mapping[str, Any]],
        *,
        element_class: str = "ndi.neuron",
        chunksize: int = 100,
        progressbar: bool = False,
        verbose: bool = False,
        build_objects: bool = False,
    ) -> list[Any]:
        """Create many timeseries elements with epochs, in batched writes.

        MATLAB equivalent: ``ndi.element.timeseries.addMultiple``.

        Each entry of SPECS describes one element to create on the shared
        UNDERLYING_ELEMENT (which supplies the subject and the
        ``underlying_element_id`` dependency), with keys:

        ``name``, ``reference``
            The element's name and reference number.
        ``type``
            The element type; ``'spikes'`` when absent. This is what
            ``ndi.fun.ensemble.load`` looks for, so a spiking neuron written
            here is one an ensemble will later find.
        ``epochs``
            A sequence of mappings with ``epoch_id``, ``epoch_clock``,
            ``t0_t1``, ``timepoints`` and ``datapoints``.
        ``extra_documents``
            Optional documents committed in the same batch, each stamped with
            the new element's ``element_id`` -- a ``neuron_extracellular``
            document per neuron, in the importer's case.

        WHY THIS EXISTS AT ALL: constructing each element and calling
        ``addepoch`` per epoch costs a database search and a separate write
        for every epoch of every element. Here the documents are built in
        memory and committed a chunk at a time -- elements first, then
        everything that depends on them, which is the order that keeps a
        dependency from naming a document the database has not seen yet.

        ``build_objects`` returns the constructed element objects, which
        MATLAB does only when an output is requested; the importer does not
        ask for them, since building each one costs a load it has no use for.
        """
        results: list[Any] = []
        specs = list(specs)
        if not specs:
            return results

        cls = _element_class_for(element_class)
        subject_id = getattr(underlying_element, "subject_id", "")

        bar = _progress_bar("Creating neurons") if progressbar else None
        done = 0
        for start in range(0, len(specs), max(int(chunksize), 1)):
            chunk = specs[start : start + max(int(chunksize), 1)]
            element_docs = []
            dependent_docs = []

            for spec in chunk:
                element = ndi_element_timeseries(
                    session=session,
                    name=str(spec["name"]),
                    reference=spec["reference"],
                    type=str(spec.get("type") or "spikes"),
                    underlying_element=underlying_element,
                    direct=False,
                    subject_id=subject_id,
                )
                doc = element.newdocument()
                # The element is BUILT as a timeseries but RECORDED as
                # element_class, exactly as MATLAB's addMultiple writes
                # element.ndi_element_class from its option: the object only
                # has to hold the epochs while they are written, while the
                # stored class is what the element loads back as.
                doc.document_properties["element"]["ndi_element_class"] = element_class
                element_docs.append(doc)

                for epoch in spec.get("epochs") or []:
                    _, epoch_doc = element.addepoch(
                        epoch["epoch_id"],
                        [epoch["epoch_clock"]],
                        [tuple(epoch["t0_t1"])],
                        epoch.get("timepoints"),
                        epoch.get("datapoints"),
                        add_to_database=False,
                    )
                    dependent_docs.append(epoch_doc)

                for extra in spec.get("extra_documents") or []:
                    dependent_docs.append(extra.set_dependency_value("element_id", element.id))

                if build_objects:
                    results.append(cls(session=session, document=doc))
                if verbose:
                    print(f"  Built {spec['name']}.")

            session.database_add(element_docs)
            if dependent_docs:
                session.database_add(dependent_docs)

            done += len(chunk)
            if bar is not None:
                bar(done / len(specs))

        if bar is not None:
            bar(1.0)
        return results

    #: MATLAB's spelling, as elsewhere in this port.
    addMultiple = add_multiple  # noqa: N815

    def __repr__(self) -> str:
        """String representation."""
        return f"ndi_element_timeseries({self._name}|{self._reference}|{self._type})"


def _element_class_for(element_class: str) -> type:
    """The Python class recording itself as ELEMENT_CLASS.

    The class registry answers for the classes it knows; ``ndi.neuron`` is
    not among them (it registers no ndi_element_class of its own -- the same
    pre-existing gap ndi.element.ensemble documents), so it is named here
    rather than left to fall through to the base timeseries.
    """
    from .class_registry import get_class

    found = get_class(element_class)
    if found is not None:
        return found
    if element_class in ("ndi.neuron", "ndi_neuron"):
        from .neuron import ndi_neuron

        return ndi_neuron
    return ndi_element_timeseries


def _progress_bar(label: str) -> Any:
    """A callable taking a 0..1 fraction, or None when no bar can be shown.

    The progress bar is optional in both languages: MATLAB wraps its
    ProgressBarWindow construction in try/catch, because a batch import must
    not fail for want of a display.
    """
    try:
        from .gui.component.ProgressBarWindow import ProgressBarWindow

        window = ProgressBarWindow("NDI import")
        tag = label
        window.addBar(Label=label, Tag=tag, Auto=True)

        def update(fraction: float) -> None:
            try:
                window.updateBar(tag, max(0.0, min(1.0, float(fraction))))
            except Exception:  # noqa: BLE001 - a bar that stops updating is not an error
                pass

        return update
    except Exception:  # noqa: BLE001 - no display, no bar, no failure
        return None
