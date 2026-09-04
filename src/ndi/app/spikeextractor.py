"""
ndi.app.spikeextractor - Spike extraction from timeseries data.

Provides the ndi_app_spikeextractor app for detecting and extracting spike
waveforms from continuous electrophysiology recordings.

MATLAB equivalent: src/ndi/+ndi/+app/spikeextractor.m

Storage (byte-compatible with MATLAB):
    Extracted waveforms are written to ``spikewaves.vsw`` in the real VH-Lab
    custom binary format ``vhlspikewaveformfile`` (big-endian 512-byte header +
    float32 data) via :mod:`ndi.util.vhlspikewaveformfile`, so a
    MATLAB-extracted file reads here and vice versa. Spike times are written to
    ``spiketimes.bin`` as float32 (matching MATLAB ``fwrite(...,'float32')``).
    Both files are attached to a ``spikewaves`` document. See :meth:`extract`.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import numpy as np

from . import ndi_app
from .appdoc import ndi_app_appdoc

if TYPE_CHECKING:
    from ..document import ndi_document
    from ..session.session_base import ndi_session


# ---------------------------------------------------------------------------
# Grounded private helpers (replacements for MISSING / unreliable vlt functions)
# ---------------------------------------------------------------------------
#
# The Python ``vlt`` port ships ``vlt.signal.dotdisc`` and
# ``vlt.signal.refractory``, but ``vlt.signal.dotdisc`` does NOT match the
# MATLAB/C ground truth (vhlab-toolbox-matlab/+vlt/+signal/dotdisc.c): it
# computes ``(data*sign) > thresh`` which, for the negative-going single-dot
# case used by this app (sign=-1, thresh<0), is true across the entire
# baseline and collapses the whole trace into a single bogus event. The C
# reference instead compares ``y[i] < thresh`` directly for sign<0. We
# therefore implement faithful grounded ports here rather than relying on the
# broken vlt function.


def _dotdisc(data: np.ndarray, dots: np.ndarray) -> np.ndarray:
    """Dot discriminator -- detect threshold crossings.

    Faithful port of the MEX C reference
    ``vhlab-toolbox-matlab/+vlt/+signal/dotdisc.c``.

    ``dots`` is an N x 3 array of rows ``[THRESH, SIGN, OFFSET]``. A sample
    ``i`` "matches" when, for every dot ``j``, ``y[i+offset_j] > thresh_j``
    (sign>0) or ``y[i+offset_j] < thresh_j`` (sign<0). A contiguous run of
    matching samples (length ``ptsgood``) emits a single event at
    ``ceil(i_end - ptsgood/2)`` where ``i_end`` is the first non-matching
    sample after the run (C: ``T = ceil(i - ptsgood/2.0)``).

    Returns the (0-based) sample indices of detected events.
    """
    y = np.asarray(data, dtype=float).reshape(-1)
    dots = np.atleast_2d(np.asarray(dots, dtype=float))
    if dots.shape[1] != 3:
        raise ValueError("dots must be an N x 3 matrix [THRESH, SIGN, OFFSET]")

    ylen = y.shape[0]
    offsets = dots[:, 2].astype(int)
    earlydot = int(min(0, offsets.min()))
    latedot = int(max(0, offsets.max()))

    events: list[float] = []
    ptsgood = 0
    for i in range(-earlydot, ylen - latedot):
        m = True
        for j in range(dots.shape[0]):
            thresh = dots[j, 0]
            sign = dots[j, 1]
            off = int(dots[j, 2])
            if sign > 0:
                m = m and (y[i + off] > thresh)
            else:
                m = m and (y[i + off] < thresh)
            if not m:
                break
        if (not m) and ptsgood > 0:
            events.append(math.ceil(i - ptsgood / 2.0))
            ptsgood = 0
        elif m:
            ptsgood += 1
    return np.asarray(events, dtype=float)


def _refractory(in_times: np.ndarray, refractory_period: float) -> np.ndarray:
    """Impose a refractory period on a sequence of event times/samples.

    Faithful port of ``vhlab-toolbox-matlab/+vlt/+signal/refractory.m``.

    Iteratively keeps index 0 plus every sample whose gap to the previous
    surviving sample exceeds the period, until a pass removes nothing. The
    round-based collapse differs from a single last-kept forward pass
    (e.g. [0,0.9,1.8,5,5.4,9] @ 1.0 -> [0,5,9], not [0,1.8,5,9]).
    """
    times = np.asarray(in_times, dtype=float).reshape(-1)
    if times.size == 0:
        return times
    out = np.sort(times)
    if refractory_period == 0:
        return out
    while out.size > 1:
        d = np.diff(out)
        keep = np.concatenate(([0], 1 + np.where(d > refractory_period)[0]))
        if keep.size == out.size:
            break
        out = out[keep]
    return out


class ndi_app_spikeextractor(ndi_app, ndi_app_appdoc):
    """
    ndi_app for extracting spike waveforms from timeseries data.

    Detects threshold crossings in filtered neural data and extracts
    spike waveforms around each detected event.

    Doc types:
        - extraction_parameters: Filter and detection settings
        - extraction_parameters_modification: Overrides per epoch
        - spikewaves: Extracted waveform binary data

    Example:
        >>> extractor = ndi_app_spikeextractor(session)
        >>> extractor.extract(timeseries_obj, epoch=1, extraction_name="default")
    """

    def __init__(self, session: ndi_session | None = None):
        ndi_app.__init__(self, session=session, name="ndi_app_spikeextractor")
        ndi_app_appdoc.__init__(
            self,
            doc_types=[
                "extraction_parameters",
                "extraction_parameters_modification",
                "spikewaves",
            ],
            doc_document_types=[
                "apps/spikeextractor/spike_extraction_parameters",
                "apps/spikeextractor/spike_extraction_parameters_modification",
                "apps/spikeextractor/spikewaves",
            ],
            doc_session=session,
        )

    # ------------------------------------------------------------------
    # Filter design + application
    # ------------------------------------------------------------------

    def makefilterstruct(
        self,
        extraction_doc: ndi_document | dict,
        sample_rate: float,
    ) -> dict[str, Any] | None:
        """
        Create a filter structure from extraction parameters.

        MATLAB equivalent: ndi.app.spikeextractor/makefilterstruct

        Designs a high-pass filter for ``sample_rate`` based on ``filter_type``
        in the extraction parameters. Supported types (MATLAB parity):
        ``'cheby1high'`` (Chebyshev type I high-pass) and ``'none'``.

        Returns a dict ``{'b': b, 'a': a}`` of filter coefficients, or ``None``
        when the filter type is ``'none'`` (MATLAB returns ``[]``).
        """
        from scipy.signal import cheby1

        params = self._extraction_params(extraction_doc)
        filter_type = params["filter_type"]

        if filter_type == "cheby1high":
            wn = params["filter_high"] / (0.5 * sample_rate)
            b, a = cheby1(
                int(params["filter_order"]),
                params["filter_ripple"],
                wn,
                btype="high",
            )
            return {"b": b, "a": a}
        elif filter_type == "none":
            return None
        else:
            raise ValueError(f"Unknown filter type: {filter_type}")

    def filter(
        self,
        data_in: np.ndarray,
        filterstruct: dict[str, Any] | None,
    ) -> np.ndarray:
        """
        Apply a filter to data.

        MATLAB equivalent: ndi.app.spikeextractor/filter

        Applies zero-phase filtering (``filtfilt``) along the sample (time)
        axis using the coefficients in ``filterstruct``. If ``filterstruct`` is
        ``None`` (filter type ``'none'``), the data is returned unchanged.
        """
        if filterstruct is None:
            return data_in

        from scipy.signal import filtfilt

        data = np.asarray(data_in, dtype=float)
        return filtfilt(filterstruct["b"], filterstruct["a"], data, axis=0)

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    def extract(
        self,
        ndi_timeseries_obj: Any,
        epoch: Any = None,
        extraction_name: str = "default",
        redo: bool = False,
        t0_t1: Any | None = None,
    ) -> list[ndi_document]:
        """
        Extract spikes from one or more epochs of a timeseries element.

        MATLAB equivalent: ndi.app.spikeextractor/extract

        Faithfully ports the MATLAB detection + extraction pipeline:

        1. Read the epoch's data (optionally restricted to ``[t0, t1]``).
        2. Build and apply the high-pass filter (:meth:`makefilterstruct` /
           :meth:`filter`).
        3. Per channel, threshold-detect events with :func:`_dotdisc`
           (``standard_deviation`` or ``absolute`` method), drop events too
           close to the data edges, then merge channels and apply the
           refractory period with :func:`_refractory`.
        4. Cut the SxDxN waveform tensor around each event and re-center with
           ``vlt.neuro.spikesorting.centerspikes_neg`` (sign-flipped for
           low-to-high thresholds), exactly as MATLAB does.
        5. Compute each spike's local-epoch time.

        DIVERGENCE FROM MATLAB: MATLAB chunk-reads the epoch using
        ``times2samples`` / ``samples2times`` and writes incrementally. The
        Python port reads the requested window in one ``readtimeseries`` call
        and (when a session is present) persists via the NDI binary-document
        mechanism. The detection/extraction math is unchanged.

        Returns:
            List of ``spikewaves`` documents created (one per epoch). When no
            session is configured, an empty list is returned but extraction is
            still performed (results discarded); use
            :meth:`extract_epoch_inmemory` for in-memory results.
        """
        epochs = self._normalize_epochs(ndi_timeseries_obj, epoch)
        extraction_doc = self._require_extraction_doc(extraction_name)

        if t0_t1 is None:
            t0_t1 = [[-np.inf, np.inf]] * len(epochs)
        elif len(t0_t1) == 2 and not isinstance(t0_t1[0], (list, tuple, np.ndarray)):
            t0_t1 = [list(t0_t1)] * len(epochs)

        created_docs: list[ndi_document] = []

        for n, ep in enumerate(epochs):
            epoch_string = self._epoch2str(ndi_timeseries_obj, ep)

            if not redo and self._session is not None:
                existing = self.find_appdoc(
                    "spikewaves", ndi_timeseries_obj, epoch_string, extraction_name
                )
                if existing:
                    continue

            t0, t1 = t0_t1[n][0], t0_t1[n][1]
            waveforms, spiketimes, waveparameters = self.extract_epoch_inmemory(
                ndi_timeseries_obj, ep, extraction_doc, t0, t1
            )

            if self._session is None:
                continue

            self.clear_appdoc("spikewaves", ndi_timeseries_obj, epoch_string, extraction_name)

            doc = self._store_spikewaves(
                ndi_timeseries_obj,
                epoch_string,
                extraction_name,
                extraction_doc,
                waveforms,
                spiketimes,
                waveparameters,
            )
            if doc is not None:
                created_docs.append(doc)

        return created_docs

    def extract_epoch_inmemory(
        self,
        ndi_timeseries_obj: Any,
        epoch: Any,
        extraction_doc: ndi_document | dict,
        t0: float = -np.inf,
        t1: float = np.inf,
    ) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
        """
        Detect and extract spike waveforms for a single epoch, in memory.

        This is the load-bearing detection/extraction core shared by
        :meth:`extract`. It performs no database I/O.

        Returns:
            Tuple ``(waveforms, spiketimes, waveparameters)`` where:
              - ``waveforms`` has shape ``(S, D, N)`` (samples x channels x
                spikes), matching MATLAB's ``CONCATENATED_SPIKES`` layout.
              - ``spiketimes`` has shape ``(N,)`` of local-epoch spike times.
              - ``waveparameters`` is a dict with ``numchannels``, ``S0``,
                ``S1``, ``samplerate``.
        """
        params = self._extraction_params(extraction_doc)

        result = ndi_timeseries_obj.readtimeseries(epoch, t0, t1)
        data, times = result[0], result[1]
        data = np.asarray(data, dtype=float)
        if data.ndim == 1:
            data = data.reshape(-1, 1)
        times = np.asarray(times, dtype=float).reshape(-1)
        n_data, n_channels = data.shape

        sample_rate = self._resolve_sample_rate(ndi_timeseries_obj, epoch, times)

        center_range_samples = int(math.ceil(params["center_range_time"] * sample_rate))
        refractory_samples = int(round(params["refractory_time"] * sample_rate))
        spike_sample_start = int(math.floor(params["spike_start_time"] * sample_rate))
        spike_sample_end = int(math.ceil(params["spike_end_time"] * sample_rate))
        spike_sample_selection = np.arange(spike_sample_start, spike_sample_end + 1)
        n_spike_samples = spike_sample_selection.size

        threshold_sign = params["threshold_sign"]

        waveparameters = {
            "numchannels": n_channels,
            "S0": spike_sample_start,
            "S1": spike_sample_end,
            "samplerate": sample_rate,
        }

        filterstruct = self.makefilterstruct(extraction_doc, sample_rate)
        if filterstruct is not None:
            data = self.filter(data, filterstruct)

        all_locs: list[float] = []
        method = params["threshold_method"]
        for ch in range(n_channels):
            column = data[:, ch]
            if method == "standard_deviation":
                stddev = np.std(column, ddof=1) if column.size > 1 else 0.0
                thresh = params["threshold_parameter"] * stddev
            elif method == "absolute":
                thresh = params["threshold_parameter"]
            else:
                raise ValueError(f"unknown threshold method: {method}")

            locs_here = _dotdisc(column, [[thresh, threshold_sign, 0]])
            if locs_here.size:
                mask = (locs_here > -spike_sample_start) & (locs_here <= n_data - spike_sample_end)
                locs_here = locs_here[mask]
            all_locs.extend(locs_here.tolist())

        locs = np.sort(np.asarray(all_locs, dtype=float))
        locs = _refractory(locs, refractory_samples)
        locs = locs.astype(int)
        n_spikes = locs.size

        if n_spikes == 0:
            empty = np.zeros((n_spike_samples, n_channels, 0), dtype=np.float32)
            return empty, np.zeros((0,), dtype=float), waveparameters

        sample_idx = locs[:, None] + spike_sample_selection[None, :]
        waveforms_nsd = data[sample_idx, :]
        waveforms_nsd = waveforms_nsd.astype(np.float32)

        from vlt.neuro.spikesorting.centerspikes_neg import centerspikes_neg

        flipped = (-1.0 * threshold_sign) * waveforms_nsd
        centered, sampleshifts = centerspikes_neg(flipped, center_range_samples)
        centered = centered * (-1.0 * threshold_sign)
        sampleshifts = np.asarray(sampleshifts).reshape(-1)

        waveforms_sdn = np.transpose(centered, (1, 2, 0)).astype(np.float32)

        # MATLAB ``round`` rounds half away from zero; Python ``round`` uses
        # banker's rounding, which diverges for odd N (default N=45 -> MATLAB
        # round(22.5)=23 vs Python round=22). Use the half-away-from-zero form.
        center_pos = math.floor(n_spike_samples / 2.0 + 0.5) - 1
        center_pos = int(np.clip(center_pos, 0, n_spike_samples - 1))
        center_time_in_samples = int(spike_sample_selection[center_pos])
        time_sample_idx = (locs - sampleshifts + center_time_in_samples).astype(float)
        spiketimes = self._times_from_index(times, time_sample_idx, sample_rate)

        return waveforms_sdn, spiketimes, waveparameters

    @staticmethod
    def _resolve_sample_rate(ndi_timeseries_obj: Any, epoch: Any, times: np.ndarray) -> float:
        """Return the epoch's sampling rate in Hz.

        Prefer the element's per-epoch ``samplerate(epoch)`` accessor. When
        that is unavailable -- cloud-materialized elements can return ``None``
        because the per-epoch rate metadata is not populated in the
        materialized DID/sqlite store -- fall back to deriving the rate from
        the ``times`` vector: ``fs = (N - 1) / (t_last - t_first)`` for a
        uniformly sampled epoch.
        """
        rate: Any = None
        try:
            rate = ndi_timeseries_obj.samplerate(epoch)
        except Exception:  # noqa: BLE001
            rate = None
        try:
            rate = float(rate) if rate is not None else None
        except (TypeError, ValueError):
            rate = None
        if rate is not None and rate > 0:
            return rate

        t = np.asarray(times, dtype=float).reshape(-1)
        if t.size >= 2:
            span = float(t[-1] - t[0])
            if math.isfinite(span) and span > 0:
                derived = (t.size - 1) / span
                if derived > 0:
                    return float(derived)

        raise ValueError("Could not determine a positive sample rate for the epoch.")

    # ------------------------------------------------------------------
    # Persistence (NDI binary-document mechanism; divergence from MATLAB)
    # ------------------------------------------------------------------

    def _store_spikewaves(
        self,
        ndi_timeseries_obj: Any,
        epoch_string: str,
        extraction_name: str,
        extraction_doc: ndi_document,
        waveforms: np.ndarray,
        spiketimes: np.ndarray,
        waveparameters: dict[str, Any],
    ) -> ndi_document | None:
        """Create + store a ``spikewaves`` document with its two binary files.

        Writes ``spikewaves.vsw`` in the real ``vhlspikewaveformfile`` format
        (:func:`ndi.util.vhlspikewaveformfile.write_vhlspikewaveformfile`) and
        the spike times to ``spiketimes.bin`` as float32 -- the same two
        files, byte-compatible, that MATLAB ``ndi.app.spikeextractor`` attaches.
        """
        import tempfile
        from pathlib import Path

        from ..util.vhlspikewaveformfile import write_vhlspikewaveformfile

        tmpdir = Path(tempfile.mkdtemp(prefix="ndi_spikewaves_"))
        vsw_path = tmpdir / "spikewaves.vsw"
        write_vhlspikewaveformfile(
            str(vsw_path),
            waveforms,
            {
                "numchannels": int(waveparameters["numchannels"]),
                "S0": int(waveparameters["S0"]),
                "S1": int(waveparameters["S1"]),
                "samplingrate": float(waveparameters["samplerate"]),
                "name": str(extraction_name)[:80],
            },
        )

        st_path = tmpdir / "spiketimes.bin"
        st = np.asarray(spiketimes, dtype="<f4")
        with open(st_path, "wb") as fh:
            fh.write(st.tobytes())

        from ..document import ndi_document

        doc = ndi_document(
            "apps/spikeextractor/spikewaves",
            **{
                "spikewaves.extraction_name": extraction_name,
                "epochid.epochid": epoch_string,
                "spikewaves.numchannels": int(waveparameters["numchannels"]),
                "spikewaves.S0": int(waveparameters["S0"]),
                "spikewaves.S1": int(waveparameters["S1"]),
                "spikewaves.samplerate": float(waveparameters["samplerate"]),
            },
        )
        if self._session is not None:
            doc = doc.set_session_id(self._session.id())
        doc = doc.set_dependency_value(
            "extraction_parameters_id", extraction_doc.id, error_if_not_found=False
        )
        doc = doc.set_dependency_value(
            "element_id", ndi_timeseries_obj.id, error_if_not_found=False
        )
        doc = doc.add_file("spikewaves.vsw", str(vsw_path))
        doc = doc.add_file("spiketimes.bin", str(st_path))

        self._session.database_add(doc)
        return doc

    # ------------------------------------------------------------------
    # Parameter defaults / validation
    # ------------------------------------------------------------------

    @staticmethod
    def default_extraction_parameters() -> dict[str, Any]:
        """
        Return default spike extraction parameters.

        Mirrors the defaults in the ``spike_extraction_parameters`` document
        definition (apps/spikeextractor/spike_extraction_parameters.json).
        """
        return {
            "center_range_time": 0.0005,
            "overlap": 0.5,
            "read_time": 30,
            "refractory_time": 0.001,
            "spike_start_time": -0.00045,
            "spike_end_time": 0.001,
            "do_filter": 1,
            "filter_type": "cheby1high",
            "filter_low": 0,
            "filter_high": 300,
            "filter_order": 4,
            "filter_ripple": 0.8,
            "threshold_method": "standard_deviation",
            "threshold_parameter": -4,
            "threshold_sign": -1,
        }

    def isvalid_appdoc_struct(self, appdoc_type: str, appdoc_struct: dict) -> tuple[bool, str]:
        """
        Validate an appdoc struct.

        MATLAB equivalent: ndi.app.spikeextractor/isvalid_appdoc_struct
        """
        if appdoc_type in (
            "extraction_parameters",
            "extraction_parameters_modification",
        ):
            fields_needed = [
                "center_range_time",
                "overlap",
                "read_time",
                "refractory_time",
                "spike_start_time",
                "spike_end_time",
                "do_filter",
                "filter_type",
                "filter_low",
                "filter_high",
                "filter_order",
                "filter_ripple",
                "threshold_method",
                "threshold_parameter",
                "threshold_sign",
            ]
            missing = [f for f in fields_needed if f not in appdoc_struct]
            if missing:
                return False, "missing fields: " + ", ".join(missing)
            return True, ""
        elif appdoc_type == "spikewaves":
            return True, ""
        else:
            raise ValueError(f"Unknown appdoc_type {appdoc_type}.")

    # ------------------------------------------------------------------
    # Document creation / finding / loading
    # ------------------------------------------------------------------

    def struct2doc(self, appdoc_type: str, appdoc_struct: dict, *args, **kwargs) -> ndi_document:
        """
        Create an ndi.document from an input structure.

        MATLAB equivalent: ndi.app.spikeextractor/struct2doc
        """
        from ..document import ndi_document

        if appdoc_type == "extraction_parameters":
            extraction_name = args[0] if args else kwargs.get("extraction_name", "")
            doc = ndi_document(
                "apps/spikeextractor/spike_extraction_parameters",
                **{
                    "spike_extraction_parameters": appdoc_struct,
                    "base.name": extraction_name,
                },
            )
            if self._session is not None:
                doc = doc.set_session_id(self._session.id())
            return doc
        elif appdoc_type == "extraction_parameters_modification":
            ndi_timeseries_obj = args[0]
            epochid = args[1]
            extraction_name = args[2]
            epoch_string = self._epoch2str(ndi_timeseries_obj, epochid)
            extraction_doc = self._require_extraction_doc(extraction_name)
            doc = ndi_document(
                "apps/spikeextractor/spike_extraction_parameters_modification",
                **{
                    "spike_extraction_parameters_modification": appdoc_struct,
                    "epochid.epochid": epoch_string,
                    "base.name": extraction_name,
                },
            )
            if self._session is not None:
                doc = doc.set_session_id(self._session.id())
            doc = doc.set_dependency_value(
                "extraction_parameters_id",
                extraction_doc.id,
                error_if_not_found=False,
            )
            doc = doc.set_dependency_value(
                "element_id", ndi_timeseries_obj.id, error_if_not_found=False
            )
            return doc
        elif appdoc_type == "spikewaves":
            raise ValueError("spikewaves documents are created internally.")
        else:
            raise ValueError(f"Unknown APPDOC_TYPE {appdoc_type}.")

    def find_appdoc(self, appdoc_type: str, *args, **kwargs) -> list[ndi_document]:
        """
        Find app documents in the session database.

        MATLAB equivalent: ndi.app.spikeextractor/find_appdoc
        """
        if self._session is None:
            return []
        from ..query import ndi_query

        appdoc_type_l = appdoc_type.lower()

        if appdoc_type_l == "extraction_parameters":
            if not args:
                raise ValueError("extraction_parameters documents need a name.")
            name = args[0]
            q = (ndi_query("base.name") == name) & ndi_query("").isa("spike_extraction_parameters")
            return self._session.database_search(q)
        elif appdoc_type_l in (
            "extraction_parameters_modification",
            "spikewaves",
            "spiketimes",
        ):
            ndi_timeseries_obj = args[0]
            epoch = args[1]
            extraction_name = args[2]

            extraction_docs = self.find_appdoc("extraction_parameters", extraction_name)
            if not extraction_docs:
                return []
            epoch_string = self._epoch2str(ndi_timeseries_obj, epoch)

            q = (
                self.searchquery()
                & (ndi_query("epochid.epochid") == epoch_string)
                & ndi_query("").depends_on("element_id", ndi_timeseries_obj.id)
                & ndi_query("").depends_on("extraction_parameters_id", extraction_docs[0].id)
            )
            if appdoc_type_l == "spikewaves":
                q = q & ndi_query("").isa("spikewaves")
            elif appdoc_type_l == "spiketimes":
                q = q & ndi_query("").isa("spiketimes")
            elif appdoc_type_l == "extraction_parameters_modification":
                q = q & ndi_query("").isa("spike_extraction_parameters_modification")
            return self._session.database_search(q)
        else:
            raise ValueError(f"Unknown APPDOC_TYPE {appdoc_type}.")

    def loaddata_appdoc(self, appdoc_type: str, *args, **kwargs) -> Any:
        """
        Load data from an app document.

        MATLAB equivalent: ndi.app.spikeextractor/loaddata_appdoc

        For ``'spikewaves'`` returns
        ``(waveforms, waveparameters, spiketimes, spikewaves_doc)`` where
        ``waveforms`` is the SxDxN tensor, ``waveparameters`` carries
        ``numchannels``/``S0``/``S1``/``samplerate``, and ``spiketimes`` are
        the local-epoch times.
        """
        appdoc_type_l = appdoc_type.lower()
        if appdoc_type_l in (
            "extraction_parameters",
            "extraction_parameters_modification",
        ):
            return self.find_appdoc(appdoc_type, *args, **kwargs)
        elif appdoc_type_l == "spikewaves":
            docs = self.find_appdoc("spikewaves", *args, **kwargs)
            if not docs:
                return None, None, None, None
            if len(docs) > 1:
                raise RuntimeError(
                    f"Found {len(docs)} spikewaves documents matching the "
                    "criteria. Do not know how to proceed."
                )
            doc = docs[0]
            waveforms, waveparameters, spiketimes = self._read_spikewaves(doc)
            return waveforms, waveparameters, spiketimes, doc
        else:
            raise ValueError(f"Unknown APPDOC_TYPE {appdoc_type}.")

    def _read_spikewaves(self, doc: ndi_document) -> tuple[np.ndarray, dict[str, Any], np.ndarray]:
        """Read back waveforms + times from a spikewaves doc.

        The ``spikewaves.vsw`` binary is the real vhlspikewaveformfile format
        (MATLAB-byte-compatible); decode it with
        :func:`ndi.util.vhlspikewaveformfile.read_vhlspikewaveformfile` and
        ``spiketimes.bin`` as float32 (matching MATLAB ``fwrite(...,'float32')``).
        """
        from ..util.vhlspikewaveformfile import read_vhlspikewaveformfile

        props = doc.document_properties
        sw = props.get("spikewaves", {})
        numchannels = int(sw.get("numchannels", 1))
        s0 = int(sw.get("S0", 0))
        s1 = int(sw.get("S1", 0))
        samplerate = float(sw.get("samplerate", 0.0))
        waveparameters = {
            "numchannels": numchannels,
            "S0": s0,
            "S1": s1,
            "samplerate": samplerate,
        }

        vsw_fh = self._session.database_openbinarydoc(doc, "spikewaves.vsw")
        try:
            waveforms, _ = read_vhlspikewaveformfile(vsw_fh)
        finally:
            self._session.database_closebinarydoc(vsw_fh)
        waveforms = np.asarray(waveforms, dtype=np.float32)

        stf = self._session.database_openbinarydoc(doc, "spiketimes.bin")
        try:
            raw = stf.read()
        finally:
            self._session.database_closebinarydoc(stf)
        spiketimes = np.frombuffer(raw, dtype="<f4").astype(float)

        return waveforms, waveparameters, spiketimes

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extraction_params(extraction_doc: ndi_document | dict) -> dict[str, Any]:
        """Return the spike_extraction_parameters dict from a doc or dict."""
        if isinstance(extraction_doc, dict):
            if "filter_type" in extraction_doc:
                return extraction_doc
            return extraction_doc.get("spike_extraction_parameters", extraction_doc)
        props = extraction_doc.document_properties
        return props.get("spike_extraction_parameters", {})

    def _require_extraction_doc(self, extraction_name: str) -> ndi_document:
        docs = self.find_appdoc("extraction_parameters", extraction_name)
        if not docs:
            raise ValueError(
                f"No spike_extraction_parameters document named {extraction_name} found."
            )
        if len(docs) > 1:
            raise RuntimeError("More than one extraction_parameters document with same name.")
        return docs[0]

    @staticmethod
    def _epoch2str(ndi_timeseries_obj: Any, epoch: Any) -> str:
        """Return the string epoch id, mirroring MATLAB epoch2str."""
        if isinstance(epoch, str):
            return epoch
        if hasattr(ndi_timeseries_obj, "epoch2str"):
            try:
                return ndi_timeseries_obj.epoch2str(epoch)
            except Exception:
                pass
        if isinstance(epoch, int) and hasattr(ndi_timeseries_obj, "epochid"):
            try:
                return ndi_timeseries_obj.epochid(epoch)
            except Exception:
                pass
        return str(epoch)

    @staticmethod
    def _normalize_epochs(ndi_timeseries_obj: Any, epoch: Any) -> list[Any]:
        """Normalize the ``epoch`` argument to a list of epochs."""
        if epoch is None:
            if hasattr(ndi_timeseries_obj, "epochtable"):
                et = ndi_timeseries_obj.epochtable()
                if isinstance(et, tuple):
                    et = et[0]
                return [e.get("epoch_id", e) if isinstance(e, dict) else e for e in et]
            if hasattr(ndi_timeseries_obj, "numepochs"):
                return list(range(1, ndi_timeseries_obj.numepochs() + 1))
            return [1]
        if isinstance(epoch, (list, tuple)):
            return list(epoch)
        return [epoch]

    @staticmethod
    def _times_from_index(times: np.ndarray, idx: np.ndarray, sample_rate: float) -> np.ndarray:
        """Map (possibly fractional) sample indices to local-epoch times.

        ``idx`` may be fractional (centering shifts). When indices fall inside
        the returned ``times`` vector we linearly interpolate; out-of-range
        indices are extrapolated from the window start using ``sample_rate``.
        """
        idx = np.asarray(idx, dtype=float)
        if times.size == 0:
            return idx / sample_rate
        n = times.size
        clipped = np.clip(idx, 0, n - 1)
        lo = np.floor(clipped).astype(int)
        hi = np.minimum(lo + 1, n - 1)
        frac = clipped - lo
        interp = times[lo] * (1 - frac) + times[hi] * frac
        out_of_range = (idx < 0) | (idx > n - 1)
        if np.any(out_of_range):
            interp = np.where(out_of_range, times[0] + idx / sample_rate, interp)
        return interp

    def __repr__(self) -> str:
        return f"ndi_app_spikeextractor(session={self._session is not None})"
