"""
ndi.daq.reader.image - abstract reader for image-series (frame) data.

The imaging counterpart of :mod:`ndi.daq.reader.mfdaq`. It extends
``ndi_daq_reader`` DIRECTLY, as a sibling of mfdaq and not a subclass:
images are frames on a pixel grid, not (sample x channel) columns, and do
not fit the mfdaq 1-D sampled API. This module declares the frame API
surface (numframes, readframes, framesize, dimensionorder, datatype,
frametimes) and provides a generic ingest / read-ingested implementation.

Concrete readers (e.g. :class:`ndi.daq.reader.image.ndr`, the thin bridge
to NDR-python) implement the live frame methods. Format reading lives in
NDR-python; NDI never hand-rolls per-format image readers.

Clock model:
    - The base epochclock is ``no_time`` (inherited from ndi_daq_reader):
      a clockless slide scan / z-stack is one ordered epoch with no real
      time axis, and frames are addressed by index.
    - A movie overrides epochclock to a real clock (``dev_local_time``)
      and returns per-frame times from ``frametimes``, in that clock's
      units.

MATLAB equivalent: src/ndi/+ndi/+daq/+reader/image.m
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from ...reader_base import ndi_daq_reader

__all__ = ["ndi_daq_reader_image", "emptymetadata"]

#: Dimension order used when a reader does not say otherwise.
DEFAULT_DIMENSION_ORDER = "YXCZT"


def emptymetadata() -> dict[str, Any]:
    """The standardized image-metadata dict with every field at "unknown".

    MATLAB equivalent: ``ndi.daq.reader.image.emptymetadata``

    Mirrors ``ndr.reader.base.emptyimagemetadata`` on the NDR side so the
    NDI and NDR structures share field names. ALL TIME FIELDS ARE IN
    SECONDS.
    """
    return {
        "israster": False,
        "frame_period": math.nan,
        "line_period": math.nan,
        "dwell_time": math.nan,
        "lines_per_frame": math.nan,
        "pixels_per_line": math.nan,
        "bidirectional": False,
    }


#: metadata fields that carry a float and may be "unknown" (NaN)
_NUMERIC_METADATA_FIELDS = (
    "frame_period",
    "line_period",
    "dwell_time",
    "lines_per_frame",
    "pixels_per_line",
)


def _metadata_to_json(m: dict[str, Any]) -> dict[str, Any]:
    """Replace NaN with None so the document serializes to valid JSON.

    ``json.dumps`` writes a bare ``NaN`` token, which is not valid JSON and
    which MATLAB's ``jsondecode`` cannot read. MATLAB's ``jsonencode``
    writes ``null`` for NaN, so None is also the symmetric choice.
    """
    out = dict(m)
    for k in _NUMERIC_METADATA_FIELDS:
        v = out.get(k)
        if isinstance(v, float) and math.isnan(v):
            out[k] = None
    return out


def _metadata_from_json(m: dict[str, Any]) -> dict[str, Any]:
    """Restore None back to NaN, so a round trip returns what went in."""
    out = dict(m)
    for k in _NUMERIC_METADATA_FIELDS:
        if out.get(k) is None:
            out[k] = math.nan
    return out


class ndi_daq_reader_image(ndi_daq_reader):
    """Abstract reader for image-series (frame) data.

    Concrete subclasses must override :meth:`numframes`, :meth:`framesize`,
    :meth:`datatype`, :meth:`frametimes` and :meth:`readframes`. The
    ingested path is provided here and is not normally overridden.
    """

    NDI_DAQREADER_CLASS = "ndi.daq.reader.image"

    # ------------------------------------------------------------------
    # live frame API (abstract; concrete readers must override)
    # ------------------------------------------------------------------

    def numframes(self, epochfiles: list[str]) -> int:
        """Number of frames (timepoints) in an image epoch.

        A frame is one timepoint; the channels of a timepoint count once
        (they are the C axis of :meth:`readframes`, not separate frames).
        """
        raise NotImplementedError(
            "numframes must be overridden by a concrete ndi.daq.reader.image subclass."
        )

    def framesize(self, epochfiles: list[str]) -> list[int]:
        """``[Y X C Z T]`` extent of an image epoch, without reading pixels."""
        raise NotImplementedError(
            "framesize must be overridden by a concrete ndi.daq.reader.image subclass."
        )

    def dimensionorder(self, epochfiles: list[str]) -> str:
        """Axis order of the arrays returned by :meth:`readframes`."""
        return DEFAULT_DIMENSION_ORDER

    def datatype(self, epochfiles: list[str]) -> str:
        """Underlying numeric class of the image data, e.g. ``'uint16'``."""
        raise NotImplementedError(
            "datatype must be overridden by a concrete ndi.daq.reader.image subclass."
        )

    def frametimes(self, epochfiles: list[str], frameind: Any = None) -> np.ndarray:
        """Time of each requested frame, in :meth:`epochclock` units."""
        raise NotImplementedError(
            "frametimes must be overridden by a concrete ndi.daq.reader.image subclass."
        )

    def readframes(
        self,
        epochfiles: list[str],
        frameind: Any = None,
        select_c: Any = None,
        select_z: Any = None,
    ) -> np.ndarray:
        """Read image frames from an epoch.

        Returns an array in :meth:`dimensionorder` (default ``'YXCZT'``)
        with the requested timepoints collapsed to the trailing dimension:
        ``[Y, X, len(select_c), len(select_z), len(frameind)]``.
        """
        raise NotImplementedError(
            "readframes must be overridden by a concrete ndi.daq.reader.image subclass."
        )

    def getchannelsepoch(self, epochfiles: list[str]) -> list[dict[str, Any]]:
        """List channels available for an image epoch.

        Default: a single ``image`` channel named ``image1``.
        """
        return [{"name": "image1", "type": "image", "time_channel": None}]

    def metadata(self, epochfiles: list[str]) -> dict[str, Any]:
        """Standardized image-acquisition metadata for an epoch.

        The raster-scan timing and geometry that let a caller reconstruct
        when each line/pixel was sampled, separately from the pixel data.
        ALL TIME FIELDS ARE IN SECONDS. See :func:`emptymetadata` for the
        field list. Not every image epoch is a raster scan and not every
        raster scan preserves this timing, so callers should check
        ``israster`` and for NaN fields.
        """
        return emptymetadata()

    # ------------------------------------------------------------------
    # ingestion
    # ------------------------------------------------------------------

    def ingest_epochfiles(self, epochfiles: list[str], epoch_id: str) -> Any:
        """Create a document holding the ingested image data for an epoch.

        MATLAB equivalent: ``ndi.daq.reader.image/ingest_epochfiles``

        Builds a ``daqreader_image_epochdata_ingested`` document that
        stores the frames as a flat raw binary (``frames.bin``) plus a
        small queryable header (dimension order/size, data type, number of
        frames, frame times, clock type, acquisition metadata). The
        document is NOT added to any database.
        """
        import tempfile

        from ....document import ndi_document
        from ....time import ndi_time_clocktype

        sz = list(self.framesize(epochfiles))
        dorder = self.dimensionorder(epochfiles)
        dtype = self.datatype(epochfiles)
        n = int(self.numframes(epochfiles))
        ft = np.asarray(self.frametimes(epochfiles, range(1, n + 1)), dtype=float).ravel()

        ec = self.epochclock(epochfiles)
        ec_strings = [c.value if isinstance(c, ndi_time_clocktype) else str(c) for c in ec]

        t0t1 = self.t0_t1(epochfiles)
        sanitized_t0t1 = []
        for pair in t0t1:
            if isinstance(pair, (list, tuple)):
                sanitized_t0t1.append(
                    [None if (isinstance(v, float) and math.isnan(v)) else v for v in pair]
                )
            else:
                sanitized_t0t1.append(
                    None if (isinstance(pair, float) and math.isnan(pair)) else pair
                )

        # Always store one time per frame as a 1xN row (NaN for clockless
        # epochs). frametimes is a matrix in the schema, so an empty list
        # fails validation where a NaN row does not.
        if ft.size == 0:
            ft = np.full(max(n, 1), np.nan)

        header = {
            "dimension_order": dorder,
            "dimension_size": [int(v) for v in sz],
            "data_type": dtype,
            "num_frames": n,
            # NaN is not valid JSON; MATLAB's jsondecode cannot read it.
            "frametimes": [None if math.isnan(v) else float(v) for v in ft],
            "clocktype": ec_strings[0] if ec_strings else "no_time",
            "metadata": _metadata_to_json(self.metadata(epochfiles)),
        }

        doc = ndi_document(
            "ingestion/daqreader_image_epochdata_ingested",
            daqreader_image_epochdata_ingested=header,
            daqreader_epochdata_ingested={
                "epochtable": {"epochclock": ec_strings, "t0_t1": sanitized_t0t1}
            },
            epochid={"epochid": epoch_id},
        )
        doc.set_dependency_value("daqreader_id", self.id)

        # Write the frames to a flat raw binary. MATLAB's fwrite consumes
        # the array in column-major order, so the bytes must be written
        # Fortran-ordered for a MATLAB-written and a Python-written
        # frames.bin to be interchangeable.
        frames = np.asarray(self.readframes(epochfiles, range(1, n + 1)), dtype=dtype)
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as fh:
            fh.write(frames.tobytes(order="F"))
            framesfile = fh.name
        doc = doc.add_file("frames.bin", framesfile)

        return doc

    # ------------------------------------------------------------------
    # read-from-ingested-document API
    # ------------------------------------------------------------------

    def ingested_header(self, epochfiles: list[str], session: Any) -> dict[str, Any]:
        """Return the image header dict from an ingested epoch document."""
        d = self.getingesteddocument(epochfiles, session)
        return d.document_properties["daqreader_image_epochdata_ingested"]

    def numframes_ingested(self, epochfiles: list[str], session: Any) -> int:
        """Number of frames for an ingested image epoch."""
        return int(self.ingested_header(epochfiles, session)["num_frames"])

    def framesize_ingested(self, epochfiles: list[str], session: Any) -> list[int]:
        """``[Y X C Z T]`` extent for an ingested image epoch."""
        return [int(v) for v in self.ingested_header(epochfiles, session)["dimension_size"]]

    def dimensionorder_ingested(self, epochfiles: list[str], session: Any) -> str:
        """Dimension order for an ingested image epoch."""
        return self.ingested_header(epochfiles, session)["dimension_order"]

    def datatype_ingested(self, epochfiles: list[str], session: Any) -> str:
        """Numeric class for an ingested image epoch."""
        return self.ingested_header(epochfiles, session)["data_type"]

    def frametimes_ingested(
        self, epochfiles: list[str], frameind: Any = None, session: Any = None
    ) -> np.ndarray:
        """Per-frame times for an ingested image epoch.

        ``frameind`` is 1-based, matching the live :meth:`frametimes`.
        """
        header = self.ingested_header(epochfiles, session)
        raw = header.get("frametimes") or []
        allt = np.array([np.nan if v is None else float(v) for v in np.ravel(raw)], dtype=float)
        if allt.size == 0:
            allt = np.full(int(header["num_frames"]), np.nan)
        if frameind is None:
            return allt
        idx = np.asarray(list(frameind), dtype=int) - 1
        return allt[idx]

    def readframes_ingested(
        self,
        epochfiles: list[str],
        frameind: Any = None,
        session: Any = None,
        select_c: Any = None,
        select_z: Any = None,
    ) -> np.ndarray:
        """Read frames back from the ``frames.bin`` of an ingested document.

        ``frameind``, ``select_c`` and ``select_z`` are 1-based, matching
        the live :meth:`readframes`.
        """
        d = self.getingesteddocument(epochfiles, session)
        header = d.document_properties["daqreader_image_epochdata_ingested"]
        sz = [int(v) for v in header["dimension_size"]]
        Y, X, C = sz[0], sz[1], sz[2]
        n = int(header["num_frames"])
        dtype = header["data_type"]

        fh = session.database_openbinarydoc(d, "frames.bin")
        try:
            raw = np.frombuffer(fh.read(), dtype=dtype, count=Y * X * C * n)
        finally:
            session.database_closebinarydoc(fh)

        # Written column-major by both languages; read it back the same way.
        allframes = raw.reshape((Y, X, C, 1, n), order="F")

        if frameind is None:
            frameind = range(1, n + 1)
        frames = allframes[:, :, :, :, np.asarray(list(frameind), dtype=int) - 1]
        if select_c is not None and len(list(select_c)) > 0:
            frames = frames[:, :, np.asarray(list(select_c), dtype=int) - 1, :, :]
        if select_z is not None and len(list(select_z)) > 0:
            frames = frames[:, :, :, np.asarray(list(select_z), dtype=int) - 1, :]
        return frames

    def getchannelsepoch_ingested(
        self, epochfiles: list[str], session: Any
    ) -> list[dict[str, Any]]:
        """List channels for an ingested image epoch."""
        return self.getchannelsepoch(epochfiles)

    def metadata_ingested(self, epochfiles: list[str], session: Any) -> dict[str, Any]:
        """Image-acquisition metadata recorded in an ingested epoch document.

        Documents ingested before the metadata field existed do not carry
        it; in that case the default "unknown" dict is returned.
        """
        header = self.ingested_header(epochfiles, session)
        m = header.get("metadata")
        return _metadata_from_json(m) if isinstance(m, dict) and m else emptymetadata()
