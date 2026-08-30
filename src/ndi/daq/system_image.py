"""
ndi.daq.system.image - image-series DAQ system.

Addresses acquisition systems that produce image-series data: frames on a
pixel grid (2-photon / widefield movies, z-stacks, histology or slide scans).
It is the imaging peer of :class:`ndi.daq.system_mfdaq.ndi_daq_system_mfdaq`.

Unlike mfdaq, an image DAQ system reads FRAMES rather than
(sample x channel) columns. The frame API is delegated to the reader, which
must be an :class:`ndi.daq.reader.image.ndi_daq_reader_image`.

Clock model: a clockless slide scan or z-stack is one epoch with clock
``no_time`` and frames addressed by index; a movie is one epoch with a real
clock (``dev_local_time``) whose per-frame times come from
:meth:`frametimes`.

MATLAB equivalent: src/ndi/+ndi/+daq/+system/image.m
"""

from __future__ import annotations

from typing import Any

from .reader.image import ndi_daq_reader_image
from .system import ndi_daq_system

__all__ = ["ndi_daq_system_image"]


class ndi_daq_system_image(ndi_daq_system):
    """DAQ system for image-series acquisition."""

    NDI_DAQSYSTEM_CLASS = "ndi.daq.system.image"

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._ndi_daqsystem_class = self.NDI_DAQSYSTEM_CLASS

        reader = getattr(self, "daqreader", None)
        if reader is not None and not isinstance(reader, ndi_daq_reader_image):
            raise TypeError(
                "The daqreader for an ndi_daq_system_image must be a type of "
                f"ndi.daq.reader.image; got {type(reader).__name__}."
            )

    def _epochfiles(self, epoch: Any) -> list[str]:
        """Files making up an epoch, via the file navigator."""
        return self.filenavigator.getepochfiles(epoch)

    # --- frame API, delegated to the reader -------------------------------
    #
    # MATLAB additionally routes every one of these through an
    # ``*_ingested`` variant when the epoch has been ingested. Ingested image
    # epochs are not part of this port -- NDI-python has no
    # daqreader_image_epochdata_ingested document type yet -- so these read
    # the live files only. See issue #71.

    def numframes(self, epoch: Any) -> int:
        """Number of frames (timepoints) in an image epoch."""
        return self.daqreader.numframes(self._epochfiles(epoch))

    def framesize(self, epoch: Any) -> list[int]:
        """``[Y X C Z T]`` extent of an image epoch, without reading pixels."""
        return self.daqreader.framesize(self._epochfiles(epoch))

    def dimensionorder(self, epoch: Any) -> str:
        """Dimension order of the frames returned for an epoch."""
        return self.daqreader.dimensionorder(self._epochfiles(epoch))

    def datatype(self, epoch: Any) -> str:
        """Underlying numeric type of the image data for an epoch."""
        return self.daqreader.datatype(self._epochfiles(epoch))

    def frametimes(self, epoch: Any, frameind: list[int] | None = None) -> Any:
        """Per-frame times for an epoch, in epoch-clock units."""
        return self.daqreader.frametimes(self._epochfiles(epoch), frameind)

    def readframes(
        self,
        epoch: Any,
        frameind: list[int] | None = None,
        select_c: list[int] | None = None,
        select_z: list[int] | None = None,
    ) -> Any:
        """Read image frames for an epoch, in ``YXCZT`` order."""
        return self.daqreader.readframes(
            self._epochfiles(epoch), frameind, select_c=select_c, select_z=select_z
        )

    def metadata(self, epoch: Any) -> dict[str, Any]:
        """Standardized image-acquisition metadata for an epoch, times in seconds."""
        return self.daqreader.metadata(self._epochfiles(epoch))

    # --- epochset overrides -----------------------------------------------

    def epochclock(self, epoch: Any) -> Any:
        """Clock types for an epoch: ``no_time`` for a stack, a real clock for a movie."""
        return self.daqreader.epochclock(self._epochfiles(epoch))

    def t0_t1(self, epoch: Any) -> Any:
        """``[t0 t1]`` begin/end times for an epoch."""
        return self.daqreader.t0_t1(self._epochfiles(epoch))

    def getchannelsepoch(self, epoch: Any) -> list[dict[str, Any]]:
        """Image channels available for one epoch."""
        return self.daqreader.getchannelsepoch(self._epochfiles(epoch))

    def getchannels(self) -> list[dict[str, Any]]:
        """Image channels available across every epoch, de-duplicated."""
        channels: list[dict[str, Any]] = []
        seen: set[tuple] = set()
        for n in range(self.numepochs()):
            for ch in self.getchannelsepoch(n):
                key = (ch.get("name"), ch.get("type"), ch.get("time_channel"))
                if key not in seen:
                    seen.add(key)
                    channels.append(ch)
        return channels
