"""
ndi.daq.reader.image.ndr - read image-series data into NDI using NDR-python.

A thin BRIDGE that lets an ``ndi.daq.system.image`` read image frames
through an NDR-python reader. It is the image-series twin of
:class:`ndi.daq.reader.mfdaq.ndr`.

Architecture -- the object stores a single reader string (e.g.
``'tiffstack'``, ``'prairieview'``, ``'imagestack'``). Every data call
instantiates the corresponding NDR reader and forwards to it, performing
only NDI-side adaptation (for example converting NDR clock types to NDI
clock types). This class does NO file I/O of its own; all format decoding
lives in NDR-python::

    ndi.daq.system.image
          |
    ndi.daq.reader.image.ndr   (this class: NDI <-> NDR adapter)
          |
    ndr.reader('<reader string>')

Frame and dimension model -- a "frame" is a single timepoint.
Multi-channel acquisitions are NOT separate frames: the channels are
returned on the C axis. Frames are addressed by a 1-based index into the
time (T) axis. ``framesize`` reports ``[Y X C Z T]``.

Epoch files -- every data method takes ``epochfiles``, the list of file
paths making up ONE epoch, as assembled by the file navigator of the
owning ``ndi.daq.system.image``. It is passed straight through to the NDR
reader. Because NDI delivers one epoch's files per call, the NDR per-file
epoch index is always 1 here.

MATLAB equivalent: src/ndi/+ndi/+daq/+reader/+image/ndr.m
"""

from __future__ import annotations

from typing import Any

import numpy as np

from . import ndi_daq_reader_image

__all__ = ["ndi_daq_reader_image_ndr"]

#: Reader string used when none is given, matching MATLAB's default.
DEFAULT_READER_STRING = "tiffstack"


class ndi_daq_reader_image_ndr(ndi_daq_reader_image):
    """Bridge that reads image frames through an NDR-python reader.

    Note:
        MATLAB validates the reader string against ``ndr.known_readers()``
        in the constructor. NDR-python exposes no ``known_readers``, so
        validation here is deferred to first use: constructing the bridge
        always succeeds, and an unknown reader string surfaces as an error
        from NDR when a data method is actually called. This also lets a
        session that names an image DAQ system load and report its
        structure on an installation whose NDR does not yet implement that
        format.
    """

    NDI_DAQREADER_CLASS = "ndi.daq.reader.image.ndr"

    def __init__(
        self,
        ndr_reader_string: str = DEFAULT_READER_STRING,
        identifier: str | None = None,
        session: Any | None = None,
        document: Any | None = None,
    ):
        super().__init__(identifier=identifier, session=session, document=document)
        self._ndi_daqreader_class = self.NDI_DAQREADER_CLASS
        self.ndr_reader_string = ndr_reader_string or DEFAULT_READER_STRING

        # When constructed from a document, read the reader string from it.
        if document is not None:
            props = getattr(document, "document_properties", {})
            if isinstance(props, dict):
                stored = props.get("daqreader_ndr", {}).get("ndr_reader_string", "")
                if stored:
                    self.ndr_reader_string = stored

    def _get_ndr_reader(self):
        """Instantiate the NDR reader this bridge forwards to."""
        import ndr

        return ndr.reader(self.ndr_reader_string)

    def _forward(self, method: str, *args, **kwargs):
        """Call ``method`` on the NDR reader, saying so plainly if it is absent.

        NDR-python grew the multichannel API before the frame API. A
        missing frame method is a version mismatch, not a bug in the
        caller, so name it as one rather than letting an AttributeError on
        an internal object reach the user.
        """
        r = self._get_ndr_reader()
        fn = getattr(r, method, None)
        if fn is None:
            raise NotImplementedError(
                f"The NDR reader {self.ndr_reader_string!r} does not implement "
                f"{method!r}. The image frame API (numframes, framesize, "
                f"readframes, frametimes, dimensionorder, datatype, metadata) "
                f"is provided by NDR-python; install a version that supports "
                f"image readers."
            )
        return fn(*args, **kwargs)

    # ------------------------------------------------------------------
    # live frame API (forwarded to the NDR reader)
    # ------------------------------------------------------------------

    def numframes(self, epochfiles: list[str]) -> int:
        """Number of frames (timepoints) in an image epoch."""
        return int(self._forward("numframes", epochfiles, 1))

    def framesize(self, epochfiles: list[str]) -> list[int]:
        """``[Y X C Z T]`` extent of an image epoch, without reading pixels."""
        return [int(v) for v in np.ravel(self._forward("framesize", epochfiles, 1))]

    def dimensionorder(self, epochfiles: list[str]) -> str:
        """Axis order of the arrays returned by :meth:`readframes`."""
        return str(self._forward("dimensionorder", epochfiles, 1))

    def datatype(self, epochfiles: list[str]) -> str:
        """Numeric class of the image data, e.g. ``'uint16'``."""
        return str(self._forward("datatype", epochfiles, 1))

    def frametimes(self, epochfiles: list[str], frameind: Any = None) -> np.ndarray:
        """Time of each requested frame, in :meth:`epochclock` units.

        ``frameind`` is a 1-based index into the time axis.
        """
        if frameind is None:
            t = self._forward("frametimes", epochfiles, 1)
        else:
            t = self._forward("frametimes", epochfiles, 1, list(frameind))
        return np.asarray(t, dtype=float).ravel()

    def readframes(
        self,
        epochfiles: list[str],
        frameind: Any = None,
        select_c: Any = None,
        select_z: Any = None,
    ) -> np.ndarray:
        """Read pixel data for the requested timepoints.

        ``frameind``, ``select_c`` and ``select_z`` are 1-based. Forwarding
        the selections to NDR lets a reader avoid reading unselected
        channels and planes rather than discarding them afterwards.
        """
        return self._forward(
            "readframes",
            epochfiles,
            1,
            None if frameind is None else list(frameind),
            select_c=None if select_c is None else list(select_c),
            select_z=None if select_z is None else list(select_z),
        )

    def getchannelsepoch(self, epochfiles: list[str]) -> list[dict[str, Any]]:
        """List the channels the NDR reader exposes for an epoch."""
        return self._forward("getchannelsepoch", epochfiles, 1)

    def metadata(self, epochfiles: list[str]) -> dict[str, Any]:
        """Standardized image-acquisition metadata for an epoch, via NDR."""
        return self._forward("metadata", epochfiles, 1)

    def epochclock(self, epochfiles: list[str]) -> list[Any]:
        """Clock type(s) for an epoch, adapted from NDR to NDI clock types.

        A movie with real per-frame timestamps returns ``dev_local_time``;
        a clockless stack (z-stack, slide scan) returns ``no_time``.
        """
        from ....time import ndi_time_clocktype

        ndr_clocks = self._forward("epochclock", epochfiles, 1)
        return [ndi_time_clocktype(ec.type) for ec in ndr_clocks]

    def t0_t1(self, epochfiles: list[str]) -> list[tuple[float, float]]:
        """``[t0 t1]`` bounds of an epoch, one pair per :meth:`epochclock`."""
        result = self._forward("t0_t1", epochfiles, 1)
        return [(row[0], row[1]) for row in result]

    # ------------------------------------------------------------------
    # documentservice
    # ------------------------------------------------------------------

    def newdocument(self) -> Any:
        """Create an ``ndi.document`` describing this reader.

        Reuses the generic ``daqreader_ndr`` document type shared with
        :class:`ndi.daq.reader.mfdaq.ndr`, recording the NDR reader string
        and the concrete NDI reader class name.
        """
        from ....document import ndi_document
        from ....session.session_base import empty_id

        return ndi_document(
            "daq/daqreader_ndr",
            **{
                "daqreader.ndi_daqreader_class": self.NDI_DAQREADER_CLASS,
                "daqreader_ndr.ndr_reader_string": self.ndr_reader_string,
                "daqreader_ndr.ndi_daqreader_ndr_class": self.NDI_DAQREADER_CLASS,
                "base.id": self.id,
                "base.session_id": empty_id(),
            },
        )

    def __repr__(self):
        rs = self.ndr_reader_string or "?"
        return f"ndi_daq_reader_image_ndr(reader='{rs}', id={self.id[:8]}...)"
