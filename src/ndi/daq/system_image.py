"""
ndi.daq.system_image - Image-series DAQ system class.

Addresses data acquisition systems that produce image-series data: frames
on a pixel grid (2-photon / widefield movies, z-stacks, histology or slide
scans). It is the imaging peer of :class:`ndi.daq.system_mfdaq`, and its
reader must be an :class:`ndi.daq.reader.image.ndi_daq_reader_image`.

Unlike mfdaq, an image DAQ system reads FRAMES, not (sample x channel)
columns. The frame API (numframes, framesize, readframes, frametimes,
dimensionorder, datatype, metadata) is delegated to the reader,
transparently using either the live files or the ingested-epoch document.

Clock model: a clockless slide scan / z-stack is one epoch with clock
``no_time`` and frames addressed by index. A movie is one epoch with a
real clock (``dev_local_time``) whose per-frame times come from
``frametimes``.

MATLAB equivalent: src/ndi/+ndi/+daq/+system/image.m
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .reader.image import ndi_daq_reader_image
from .system import ndi_daq_system

__all__ = ["ndi_daq_system_image"]


class ndi_daq_system_image(ndi_daq_system):
    """Image-series DAQ system.

    Example:
        >>> sys = ndi_daq_system_image('prairie1', navigator, reader)
        >>> sz = sys.framesize(1)              # [Y X C Z T]
        >>> frames = sys.readframes(1, [1, 2, 3])
    """

    NDI_DAQSYSTEM_CLASS = "ndi.daq.system.image"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self._daqreader is not None and not isinstance(self._daqreader, ndi_daq_reader_image):
            raise TypeError(
                "The daqreader for an ndi.daq.system.image must be a type of "
                f"ndi.daq.reader.image; got {type(self._daqreader).__name__}."
            )

    def _getepochfiles(self, epoch_number: int) -> list[str]:
        """Get epoch files, unpacking the tuple from getepochfiles."""
        result = self._filenavigator.getepochfiles(epoch_number)
        return result[0] if isinstance(result, tuple) else result

    def _reader_call(self, live: str, ingested: str, epoch_number: int, *args, **kwargs):
        """Call the reader's live or ingested method for an epoch.

        Every frame method has the same shape: resolve the epoch's files,
        then dispatch to the live method or the ``*_ingested`` twin, which
        takes the session as an extra argument.
        """
        epochfiles = self._getepochfiles(epoch_number)
        if self._is_ingested(epochfiles):
            return getattr(self._daqreader, ingested)(
                epochfiles, *args, session=self.session, **kwargs
            )
        return getattr(self._daqreader, live)(epochfiles, *args, **kwargs)

    # ------------------------------------------------------------------
    # ndi.epoch.epochset overrides
    # ------------------------------------------------------------------

    def epochclock(self, epoch_number: int) -> list[Any]:
        """Clock type(s) for an epoch.

        ``no_time`` for a clockless image epoch; the reader's real clock
        for a movie.
        """
        if self._daqreader is None or self._filenavigator is None:
            from ..time import NO_TIME

            return [NO_TIME]
        epochfiles = self._getepochfiles(epoch_number)
        if self._is_ingested(epochfiles):
            return self._daqreader.epochclock_ingested(epochfiles, self.session)
        return self._daqreader.epochclock(epochfiles)

    def t0_t1(self, epoch_number: int) -> list[tuple[float, float]]:
        """``[t0 t1]`` begin/end times for an epoch, one pair per clock."""
        if self._daqreader is None or self._filenavigator is None:
            return [(np.nan, np.nan)]
        epochfiles = self._getepochfiles(epoch_number)
        if self._is_ingested(epochfiles):
            return self._daqreader.t0_t1_ingested(epochfiles, self.session)
        return self._daqreader.t0_t1(epochfiles)

    def getchannelsepoch(self, epoch_number: int) -> list[Any]:
        """List the image channels available for an epoch."""
        if self._daqreader is None or self._filenavigator is None:
            return []
        return self._reader_call("getchannelsepoch", "getchannelsepoch_ingested", epoch_number)

    def getchannels(self) -> list[Any]:
        """List the image channels available across all epochs."""
        all_channels: list[Any] = []
        seen = set()
        for entry in self.epochtable():
            for ch in self.getchannelsepoch(entry["epoch_number"]):
                key = (ch.get("name"), ch.get("type")) if isinstance(ch, dict) else (ch,)
                if key not in seen:
                    seen.add(key)
                    all_channels.append(ch)
        return all_channels

    # ------------------------------------------------------------------
    # frame API (delegated to the reader, ingested-aware)
    # ------------------------------------------------------------------

    def numframes(self, epoch_number: int) -> int:
        """Number of frames in an image epoch."""
        return self._reader_call("numframes", "numframes_ingested", epoch_number)

    def framesize(self, epoch_number: int) -> list[int]:
        """``[Y X C Z T]`` extent of an epoch, without reading pixels."""
        return self._reader_call("framesize", "framesize_ingested", epoch_number)

    def dimensionorder(self, epoch_number: int) -> str:
        """Dimension order of the frames returned for an epoch."""
        return self._reader_call("dimensionorder", "dimensionorder_ingested", epoch_number)

    def datatype(self, epoch_number: int) -> str:
        """Underlying numeric class of the image data for an epoch."""
        return self._reader_call("datatype", "datatype_ingested", epoch_number)

    def metadata(self, epoch_number: int) -> dict[str, Any]:
        """Standardized image-acquisition metadata for an epoch.

        Raster line/frame timing, geometry and scan direction, with all
        time fields in SECONDS.
        """
        return self._reader_call("metadata", "metadata_ingested", epoch_number)

    def frametimes(self, epoch_number: int, frameind: Any = None) -> np.ndarray:
        """Per-frame times for an epoch, in epoch-clock units.

        ``frameind`` is 1-based; omitted means every frame.
        """
        if frameind is None:
            frameind = range(1, self.numframes(epoch_number) + 1)
        return self._reader_call("frametimes", "frametimes_ingested", epoch_number, frameind)

    def readframes(
        self,
        epoch_number: int,
        frameind: Any = None,
        select_c: Any = None,
        select_z: Any = None,
    ) -> np.ndarray:
        """Read image frames for an epoch.

        Returns an array in ``'YXCZT'`` order,
        ``[Y, X, len(select_c), len(select_z), len(frameind)]``.
        ``frameind``, ``select_c`` and ``select_z`` are 1-based; omitted
        means all.
        """
        if frameind is None:
            frameind = range(1, self.numframes(epoch_number) + 1)
        return self._reader_call(
            "readframes",
            "readframes_ingested",
            epoch_number,
            frameind,
            select_c=select_c,
            select_z=select_z,
        )

    def __repr__(self):
        return f"ndi_daq_system_image(name='{self.name}', id={self.id[:8]}...)"
