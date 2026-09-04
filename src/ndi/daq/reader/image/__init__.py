"""
ndi.daq.reader.image - abstract reader for image-series acquisition.

An image reader returns FRAMES on a pixel grid (2-photon / widefield movies,
z-stacks, histology or slide scans), not (sample x channel) columns. It is the
imaging peer of :class:`ndi.daq.reader.mfdaq.ndi_daq_reader_mfdaq`.

This class is abstract in the same sense as MATLAB's: it fixes the frame API
and the metadata shape, and leaves the actual format reading to a subclass.
The only concrete subclass here is
:class:`ndi.daq.reader.image.ndr.ndi_daq_reader_image_ndr`, which forwards to
an NDR-python reader.

MATLAB equivalent: src/ndi/+ndi/+daq/+reader/image.m
"""

from __future__ import annotations

from typing import Any

from ...reader_base import ndi_daq_reader

__all__ = ["ndi_daq_reader_image", "emptymetadata"]


def emptymetadata() -> dict[str, Any]:
    """Return the standardized image-metadata struct with everything unset.

    The field list is fixed so that callers can rely on it whatever the
    underlying format is; a reader that is not a raster imager leaves the
    raster fields as ``None``. All time fields are in SECONDS.

    MATLAB equivalent: ndi.daq.reader.image/emptymetadata.
    """
    return {
        "frame_period": None,
        "line_period": None,
        "dwell_time": None,
        "scan_direction": None,
        "pixels_per_line": None,
        "lines_per_frame": None,
        "microns_per_pixel_x": None,
        "microns_per_pixel_y": None,
        "microns_per_pixel_z": None,
        "optical_zoom": None,
        "objective": None,
        "excitation_wavelength": None,
    }


class ndi_daq_reader_image(ndi_daq_reader):
    """Abstract image-series DAQ reader.

    Subclasses implement the live frame methods:
    :meth:`numframes`, :meth:`framesize`, :meth:`dimensionorder`,
    :meth:`datatype`, :meth:`frametimes` and :meth:`readframes`.

    Frame indices are 0-based here, unlike MATLAB's 1-based ``frameind``.
    That follows the rest of NDI-python (see ``ndi_daq_system_mfdaq``, whose
    sample indices are 0-based for the same reason) rather than MATLAB.
    """

    NDI_DAQREADER_CLASS = "ndi.daq.reader.image"

    def numframes(self, epochfiles: list[str]) -> int:
        """Number of frames (timepoints) in an image epoch.

        A frame is one timepoint. Multiple colour channels of one timepoint
        count once -- they are the C axis of :meth:`readframes`, not separate
        frames.
        """
        raise NotImplementedError("numframes must be implemented by a subclass")

    def framesize(self, epochfiles: list[str]) -> list[int]:
        """``[Y X C Z T]`` extent of the epoch, without reading pixels.

        ``framesize()[4]`` equals :meth:`numframes`.
        """
        raise NotImplementedError("framesize must be implemented by a subclass")

    def dimensionorder(self, epochfiles: list[str]) -> str:
        """Dimension order of the array returned by :meth:`readframes`."""
        raise NotImplementedError("dimensionorder must be implemented by a subclass")

    def datatype(self, epochfiles: list[str]) -> str:
        """Underlying numeric type of the image data (e.g. ``'uint16'``)."""
        raise NotImplementedError("datatype must be implemented by a subclass")

    def frametimes(self, epochfiles: list[str], frameind: list[int] | None = None) -> Any:
        """Per-frame times, in the units of the epoch clock."""
        raise NotImplementedError("frametimes must be implemented by a subclass")

    def readframes(
        self,
        epochfiles: list[str],
        frameind: list[int] | None = None,
        select_c: list[int] | None = None,
        select_z: list[int] | None = None,
    ) -> Any:
        """Read image frames, returned in ``YXCZT`` order.

        ``select_c`` and ``select_z`` subset the channel and plane axes;
        ``None`` means all.
        """
        raise NotImplementedError("readframes must be implemented by a subclass")

    def getchannelsepoch(self, epochfiles: list[str]) -> list[dict[str, Any]]:
        """Channels the reader exposes for the epoch.

        Image readers typically present a single logical image channel (e.g.
        ``image1`` of type ``image``) however many colour channels the data
        carry; colour rides on the C axis of :meth:`readframes`.
        """
        raise NotImplementedError("getchannelsepoch must be implemented by a subclass")

    def metadata(self, epochfiles: list[str]) -> dict[str, Any]:
        """Standardized image-acquisition metadata, times in SECONDS.

        The base class reports nothing known; see :func:`emptymetadata` for
        the field list.
        """
        return emptymetadata()
