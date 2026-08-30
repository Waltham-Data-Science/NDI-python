"""
ndi.daq.reader.image.ndr - image-series reader that forwards to NDR-python.

The imaging peer of :class:`ndi.daq.reader.mfdaq.ndr.ndi_daq_reader_mfdaq_ndr`:
that one bridges NDR for multichannel time series, this one for frames.

``ndr_reader_string`` names the NDR reader to forward to -- e.g.
``'tiffstack'``, ``'prairieview'`` -- and an ``ndr.reader`` is instantiated per
call, as MATLAB does.

MATLAB equivalent: src/ndi/+ndi/+daq/+reader/+image/ndr.m
"""

from __future__ import annotations

from typing import Any

from ....time.clocktype import ndi_time_clocktype
from . import ndi_daq_reader_image

__all__ = ["ndi_daq_reader_image_ndr"]

#: Used when no reader string is given, matching MATLAB's zero-argument form.
DEFAULT_READER_STRING = "tiffstack"


class ndi_daq_reader_image_ndr(ndi_daq_reader_image):
    """Bridge from NDI's image reader API to an NDR-python image reader."""

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

        # Reconstructed from the database: the reader string lives in the
        # shared 'daqreader_ndr' document type, as it does for the mfdaq
        # bridge, so both are rebuilt from the same document shape.
        if document is not None:
            props = getattr(document, "document_properties", {})
            if isinstance(props, dict):
                stored = props.get("daqreader_ndr", {}).get("ndr_reader_string", "")
                if stored:
                    self.ndr_reader_string = stored

    def _get_ndr_reader(self):
        """Instantiate the NDR reader named by ``ndr_reader_string``."""
        import ndr

        return ndr.reader(self.ndr_reader_string)

    # --- live frame API, forwarded to the NDR reader ----------------------
    #
    # NDR's own API takes a 1-based epoch_select, fixed at 1 throughout: one
    # NDI epoch is one NDR epoch. That mirrors the mfdaq bridge.

    def numframes(self, epochfiles: list[str]) -> int:
        return self._get_ndr_reader().numframes(epochfiles, 1)

    def framesize(self, epochfiles: list[str]) -> list[int]:
        return self._get_ndr_reader().framesize(epochfiles, 1)

    def dimensionorder(self, epochfiles: list[str]) -> str:
        return self._get_ndr_reader().dimensionorder(epochfiles, 1)

    def datatype(self, epochfiles: list[str]) -> str:
        return self._get_ndr_reader().datatype(epochfiles, 1)

    def frametimes(self, epochfiles: list[str], frameind: list[int] | None = None) -> Any:
        r = self._get_ndr_reader()
        if frameind is None:
            frameind = list(range(self.numframes(epochfiles)))
        # NDI-python frame indices are 0-based; NDR's are 1-based.
        return r.frametimes(epochfiles, [i + 1 for i in frameind], 1)

    def readframes(
        self,
        epochfiles: list[str],
        frameind: list[int] | None = None,
        select_c: list[int] | None = None,
        select_z: list[int] | None = None,
    ) -> Any:
        r = self._get_ndr_reader()
        if frameind is None:
            frameind = list(range(self.numframes(epochfiles)))
        return r.readframes(
            epochfiles,
            [i + 1 for i in frameind],
            1,
            select_c=None if select_c is None else [c + 1 for c in select_c],
            select_z=None if select_z is None else [z + 1 for z in select_z],
        )

    def getchannelsepoch(self, epochfiles: list[str]) -> list[dict[str, Any]]:
        return self._get_ndr_reader().getchannelsepoch(epochfiles, 1)

    def epochclock(self, epochfiles: list[str]) -> list[ndi_time_clocktype]:
        """Clock types for the epoch, adapted from NDR's own clocktype.

        A movie with real per-frame timestamps reports ``dev_local_time``; a
        clockless stack (z-stack, slide scan) reports ``no_time``.
        """
        ec_ndr = self._get_ndr_reader().epochclock(epochfiles, 1)
        return [ndi_time_clocktype(ec.type) for ec in ec_ndr]

    def t0_t1(self, epochfiles: list[str]) -> list[tuple[float, float]]:
        return self._get_ndr_reader().t0_t1(epochfiles, 1)

    def metadata(self, epochfiles: list[str]) -> dict[str, Any]:
        return self._get_ndr_reader().metadata(epochfiles, 1)

    # --- documentservice --------------------------------------------------

    def newdocument(self) -> Any:
        """Create the ``daqreader_ndr`` document describing this reader.

        Deliberately the same document type the mfdaq bridge uses: it already
        carries the reader string plus the concrete NDI class name, which is
        all that is needed to rebuild either one.
        """
        from ....document import ndi_document

        return ndi_document(
            "daq/daqreader_ndr",
            **{
                "daqreader.ndi_daqreader_class": self.NDI_DAQREADER_CLASS,
                "daqreader_ndr.ndr_reader_string": self.ndr_reader_string,
                "daqreader_ndr.ndi_daqreader_ndr_class": self.NDI_DAQREADER_CLASS,
                "base.id": self.id,
            },
        )
