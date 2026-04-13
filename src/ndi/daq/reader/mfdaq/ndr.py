"""
ndi.daq.reader.mfdaq.ndr - NDR (Neuroscience Data Reader) wrapper.

Delegates all read operations to the appropriate NDR-python reader
based on the ``ndr_reader_string`` property (e.g. ``'neuropixelsGLX'``,
``'intan_rhd'``, ``'axon_abf'``).

MATLAB equivalent: src/ndi/+ndi/+daq/+reader/+mfdaq/ndr.m
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from ...mfdaq import ChannelInfo, ndi_daq_reader_mfdaq

logger = logging.getLogger(__name__)


class ndi_daq_reader_mfdaq_ndr(ndi_daq_reader_mfdaq):
    """
    Reader that delegates to NDR-python readers.

    Wraps ``ndr.reader(ndr_reader_string)`` to provide NDI-compatible
    channel reading for any format supported by the NDR library.

    The ``ndr_reader_string`` identifies the format (e.g.
    ``'neuropixelsGLX'``, ``'intan_rhd'``, ``'axon_abf'``).  Valid
    strings are listed by ``ndr.known_readers()``.
    """

    NDI_DAQREADER_CLASS = "ndi.daq.reader.mfdaq.ndr"

    def __init__(
        self,
        ndr_reader_string: str = "",
        identifier: str | None = None,
        session: Any | None = None,
        document: Any | None = None,
    ):
        super().__init__(identifier=identifier, session=session, document=document)
        self._ndi_daqreader_class = self.NDI_DAQREADER_CLASS
        self.ndr_reader_string = ndr_reader_string

        # When constructed from a document, read the reader string from it
        if document is not None:
            props = getattr(document, "document_properties", {})
            if isinstance(props, dict):
                self.ndr_reader_string = (
                    props.get("daqreader_ndr", {}).get("ndr_reader_string", "")
                )

    def _get_ndr_reader(self):
        """Get the NDR reader for this format."""
        import ndr

        return ndr.reader(self.ndr_reader_string)

    def getchannelsepoch(self, epochfiles: list[str]) -> list[ChannelInfo]:
        """List channels available for an epoch.

        Delegates to the NDR reader and converts the returned dicts
        to :class:`ChannelInfo` objects.
        """
        r = self._get_ndr_reader()
        ndr_channels = r.getchannelsepoch(epochfiles, 1)
        return [
            ChannelInfo(
                name=ch["name"],
                type=ch["type"],
                time_channel=ch.get("time_channel"),
            )
            for ch in ndr_channels
        ]

    def readchannels_epochsamples(self, channeltype, channel, epochfiles, s0, s1):
        """Read channel data as samples.

        Delegates to the NDR reader with ``epoch_select=1``.
        """
        r = self._get_ndr_reader()
        # NDR expects a single channeltype string
        if isinstance(channeltype, list):
            channeltype = channeltype[0]
        if isinstance(channel, int):
            channel = [channel]
        return r.readchannels_epochsamples(channeltype, channel, epochfiles, 1, s0, s1)

    def samplerate(self, epochfiles, channeltype, channel):
        """Get sample rate for specified channels.

        Delegates to the NDR reader with ``epoch_select=1``.
        """
        r = self._get_ndr_reader()
        if isinstance(channeltype, list):
            channeltype = channeltype[0]
        sr = r.samplerate(epochfiles, 1, channeltype, channel)
        return np.atleast_1d(sr)

    def epochclock(self, epochfiles):
        """Return the clock types for an epoch.

        Converts NDR ``ClockType`` objects to NDI ``ndi_time_clocktype``.
        """
        r = self._get_ndr_reader()
        from ...time import ndi_time_clocktype

        ndr_clocks = r.epochclock(epochfiles, 1)
        return [ndi_time_clocktype(ec.type) for ec in ndr_clocks]

    def t0_t1(self, epochfiles):
        """Return the start and end times for an epoch.

        Returns list of ``(t0, t1)`` tuples.
        """
        r = self._get_ndr_reader()
        result = r.t0_t1(epochfiles, 1)
        return [(row[0], row[1]) for row in result]

    def underlying_datatype(self, epochfiles, channeltype, channel):
        """Get the underlying data type for channels.

        Delegates to the NDR reader.
        """
        r = self._get_ndr_reader()
        if isinstance(channeltype, list):
            channeltype = channeltype[0]
        return r.ndr_reader_base.underlying_datatype(epochfiles, 1, channeltype, channel)

    def readevents_epochsamples_native(self, channeltype, channel, epochfiles, t0, t1):
        """Read native event data.

        Delegates to the NDR reader.
        """
        r = self._get_ndr_reader()
        if isinstance(channeltype, list):
            channeltype = channeltype[0]
        if isinstance(channel, int):
            channel = [channel]
        return r.readevents_epochsamples_native(channeltype, channel, epochfiles, 1, t0, t1)

    def epochsamples2times(self, channeltype, channel, epochfiles, samples):
        """Convert sample indices to time.

        For readers with time gaps, interpolates from the time channel.
        Otherwise delegates to the base class formula.
        """
        r = self._get_ndr_reader()
        if r.MightHaveTimeGaps:
            t_all = self.readchannels_epochsamples("time", [1], epochfiles, 1, int(1e12))
            t_all = t_all.flatten()
            s_all = np.arange(len(t_all))
            return np.interp(np.asarray(samples, dtype=float), s_all, t_all)
        return super().epochsamples2times(channeltype, channel, epochfiles, samples)

    def epochtimes2samples(self, channeltype, channel, epochfiles, times):
        """Convert time to sample indices.

        For readers with time gaps, interpolates from the time channel.
        Otherwise delegates to the base class formula.
        """
        r = self._get_ndr_reader()
        if r.MightHaveTimeGaps:
            t_all = self.readchannels_epochsamples("time", [1], epochfiles, 1, int(1e12))
            t_all = t_all.flatten()
            s_all = np.arange(len(t_all))
            return np.round(np.interp(np.asarray(times, dtype=float), t_all, s_all)).astype(int)
        return super().epochtimes2samples(channeltype, channel, epochfiles, times)

    def __repr__(self):
        rs = self.ndr_reader_string or "?"
        return f"ndi_daq_reader_mfdaq_ndr(reader='{rs}', id={self.id[:8]}...)"
