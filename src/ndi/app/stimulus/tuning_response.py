"""
ndi.app.stimulus.tuning_response - Stimulus-response analysis.

Computes scalar responses of neural elements to stimulus presentations
and generates tuning curves.

MATLAB equivalent: src/ndi/+ndi/+app/+stimulus/tuning_response.m
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from .. import ndi_app

if TYPE_CHECKING:
    from ...document import ndi_document
    from ...session.session_base import ndi_session


# ---------------------------------------------------------------------------
# Grounded numerical helpers (ports of vlt.neuro.stimulus / vlt.math)
# ---------------------------------------------------------------------------


def _fouriercoeffs_tf2(response: np.ndarray, tf: float, sample_rate: float) -> complex | float:
    """Fourier coefficient of a signal at a particular frequency.

    Faithful port of ``vlt.math.fouriercoeffs_tf2`` (vhlab-toolbox-matlab,
    ``+vlt/+math/fouriercoeffs_tf2.m``), the routine called by
    ``vlt.neuro.stimulus.stimulus_response_scalar`` for F1/F2.

    Convention (cited from fouriercoeffs_tf2.m lines 15-22)::

        if tf == 0:  f = mean(response)
        else:        expvec = exp(-(1:N) * 2*pi*i*tf/SAMPLERATE)
                     f      = (2/N) * expvec * response

    The exponent index runs 1..N (MATLAB 1-based), so it is reproduced
    here with ``np.arange(1, N + 1)`` rather than ``0..N-1``.

    Args:
        response: 1-D signal samples within the stimulus window.
        tf: Frequency to analyze, in the same units as ``sample_rate`` (Hz).
        sample_rate: Sampling rate (Hz).

    Returns:
        The mean (``tf == 0``) or the complex Fourier amplitude (``tf != 0``).
    """
    r = np.asarray(response, dtype=float).ravel()
    n = r.size
    if tf == 0:
        return float(np.mean(r)) if n > 0 else float("nan")
    if n == 0:
        return 0.0 + 0.0j
    k = np.arange(1, n + 1)
    expvec = np.exp(-k * 2.0 * np.pi * 1j * tf / sample_rate)
    return (2.0 / n) * complex(np.dot(expvec, r))


def _stimids2reps(stimids: np.ndarray, numstims: int) -> tuple[np.ndarray, bool]:
    """Label each stimulus with its repetition number for a regular sequence.

    Faithful port of ``vlt.neuro.stimulus.stimids2reps`` (stimids2reps.m).

    Args:
        stimids: 1-D array of presentation order (1-based stimulus ids).
        numstims: Number of distinct stimuli.

    Returns:
        Tuple ``(reps, isregular)``. ``reps`` is the 1-based repetition
        label (same length as ``stimids``); ``isregular`` is True if the
        order is a regular cycle of ``1..numstims`` (last cycle may be
        incomplete).
    """
    s = np.asarray(stimids).ravel()
    n = s.size
    if numstims <= 0 or n == 0:
        return np.ones(n, dtype=int), False

    reps = np.ceil(np.arange(1, n + 1) / numstims).astype(int)
    r_max = int(reps.max())

    isregular = True
    for r in range(1, r_max):  # all but the last full repetition
        block = np.sort(s[reps == r])
        if not np.array_equal(block, np.arange(1, numstims + 1)):
            isregular = False
            return reps, isregular

    laststims = s[reps == r_max]
    in_range = np.all((laststims <= numstims) & (laststims >= 1))
    no_repeats = laststims.size == np.unique(laststims).size
    if not (in_range and no_repeats):
        isregular = False

    return reps, isregular


def _findcontrolstimulus(stimid: np.ndarray, controlstimid: Any) -> np.ndarray:
    """Find the control-stimulus presentation index for each stimulus.

    Faithful port of ``vlt.neuro.stimulus.findcontrolstimulus``
    (findcontrolstimulus.m). Indices returned are 1-based, matching the
    MATLAB convention that the rest of the response math relies on.

    Args:
        stimid: 1-D array of 1-based presentation order.
        controlstimid: Scalar or array of control stimulus id(s), or empty.

    Returns:
        1-D float array (1-based presentation indices, ``nan`` where there
        is no control), or an empty array if no control id is supplied.
    """
    cs = np.atleast_1d(np.asarray(controlstimid)).ravel()
    cs = cs[~_isnan_array(cs)] if cs.size else cs
    s = np.asarray(stimid).ravel()
    if cs.size == 0 or s.size == 0:
        return np.array([], dtype=float)

    numstims = int(np.max(s))
    reps, isregular = _stimids2reps(s, numstims)
    isregular = isregular and (cs.size == 1)

    controlstimnumber: list[float] = []

    if isregular:
        cid = cs[0]
        r_max = int(np.max(reps))
        for r in range(1, r_max):
            # 1-based index within this repetition where stim == control id
            block_idx = np.where(s[reps == r] == cid)[0]
            offset = (r - 1) * numstims + (block_idx[0] + 1)
            controlstimnumber.extend([offset] * numstims)
        # last repetition may be incomplete but still regular
        last_block = np.where(s[reps == r_max] == cid)[0]
        if last_block.size:
            offset = (r_max - 1) * numstims + (last_block[0] + 1)
            controlstimnumber.extend([offset] * numstims)
        else:
            prev_block = np.where(s[reps == r_max - 1] == cid)[0]
            offset = (r_max - 2) * numstims + (prev_block[0] + 1)
            controlstimnumber.extend([offset] * numstims)
        out = np.asarray(controlstimnumber[: s.size], dtype=float)
    else:
        cs_mask = np.isin(s, cs)
        cs_inds = np.where(cs_mask)[0] + 1  # 1-based
        out = np.empty(s.size, dtype=float)
        if cs_inds.size == 0:
            out[:] = np.nan
        else:
            positions = np.arange(1, s.size + 1)
            for i, pos in enumerate(positions):
                dists = np.abs(cs_inds - pos)
                out[i] = float(cs_inds[int(np.argmin(dists))])

    return out


def _isnan_array(a: np.ndarray) -> np.ndarray:
    """NaN mask that tolerates non-float dtypes."""
    try:
        return np.isnan(a.astype(float))
    except (TypeError, ValueError):
        return np.zeros(a.shape, dtype=bool)


def _findclosest(values: np.ndarray, target: float) -> int:
    """Index (0-based) of the entry in ``values`` closest to ``target``."""
    v = np.asarray(values, dtype=float)
    return int(np.argmin(np.abs(v - target)))


def _nanstderr(values: Any) -> float:
    """Standard error of the mean ignoring NaNs (mirrors vlt.data.nanstderr)."""
    v = np.asarray(values)
    mag = np.abs(v) if np.iscomplexobj(v) else np.real(v).astype(float)
    valid = mag[~np.isnan(mag)]
    if valid.size < 2:
        return 0.0
    return float(np.nanstd(valid, ddof=1) / np.sqrt(valid.size))


def _stimulus_response_scalar(
    timeseries: np.ndarray,
    timestamps: np.ndarray,
    stim_onsetoffsetid: np.ndarray,
    control_stimid: Any = None,
    freq_response: Any = 0,
    prestimulus_time: Any = None,
    prestimulus_normalization: Any = None,
    isspike: bool = False,
    spiketrain_dt: float = 0.001,
) -> dict[str, np.ndarray]:
    """Compute scalar (F0/F1/...) responses for a set of stimulus windows.

    Faithful port of ``vlt.neuro.stimulus.stimulus_response_scalar``
    (stimulus_response_scalar.m). For each row ``[onset offset stimid]``
    in ``stim_onsetoffsetid`` it integrates the response over the
    on/off window:

    * ``freq_response == 0`` -> F0, the window mean (non-spike) or
      spike-count/duration (spike) -- mirrors lines 135-142.
    * ``freq_response != 0`` -> the Fourier amplitude at that frequency,
      via :func:`_fouriercoeffs_tf2` (lines 155-161).

    The control response is computed identically over the control
    stimulus' window. ``prestimulus_normalization`` (subtract / fractional
    / divide) is applied as in lines 204-218.

    Args:
        timeseries: 1-D response values.
        timestamps: 1-D timestamps for ``timeseries`` (seconds).
        stim_onsetoffsetid: ``(M, 3)`` array of ``[onset, offset, stimid]``.
        control_stimid: control stimulus id(s), or None.
        freq_response: scalar frequency, or per-stimulus vector indexed by
            stimid (``freq_response[stimid-1]``), or 0 for the mean.
        prestimulus_time: baseline window length, or None.
        prestimulus_normalization: 0/'none', 1/'subtract', 2/'fractional',
            3/'divide', or None.
        isspike: whether the signal is a spike train.
        spiketrain_dt: spike train reconstruction resolution (unused here;
            preserved for parameter parity).

    Returns:
        Dict with ``stimid``, ``response``, ``control_response``,
        ``controlstimnumber`` (all length M).
    """
    ts = np.asarray(timeseries, dtype=float).ravel()
    t = np.asarray(timestamps, dtype=float).ravel()
    soi = np.atleast_2d(np.asarray(stim_onsetoffsetid, dtype=float))
    stimid = soi[:, 2]
    m = soi.shape[0]

    freq_vec = np.atleast_1d(np.asarray(freq_response, dtype=float))

    sample_rate = 0.0
    if t.size > 1:
        sample_rate = 1.0 / float(np.median(np.diff(t)))

    controlstimnumber = _findcontrolstimulus(stimid, control_stimid)

    norm = prestimulus_normalization
    if isinstance(norm, str):
        norm = norm.lower()

    response = np.full(m, np.nan, dtype=complex)
    control_response = np.full(m, np.nan, dtype=complex)

    for i in range(m):
        onset_i, offset_i = soi[i, 0], soi[i, 1]
        stim_samples = np.where((t >= onset_i) & (t <= offset_i))[0]

        control_stim_here = None
        control_stim_samples = np.array([], dtype=int)
        if controlstimnumber.size and not np.isnan(controlstimnumber[i]):
            control_stim_here = int(controlstimnumber[i]) - 1  # to 0-based row
            c_on = soi[control_stim_here, 0]
            c_off = soi[control_stim_here, 1]
            control_stim_samples = np.where((t >= c_on) & (t <= c_off))[0]

        if not isspike:
            oob1 = (t.size == 0) or (t[-1] < offset_i) or (t[0] > onset_i)
            oob2 = False
            if control_stim_here is not None:
                c_on = soi[control_stim_here, 0]
                c_off = soi[control_stim_here, 1]
                oob2 = (t[-1] < c_off) or (t[0] > c_on)
        else:
            oob1 = False
            oob2 = False

        if oob1 or oob2:
            response[i] = np.nan
            control_response[i] = np.nan
            continue

        prestim_samples = np.array([], dtype=int)
        control_prestim_samples = np.array([], dtype=int)
        if prestimulus_time:
            prestim_samples = np.where((t >= onset_i - prestimulus_time) & (t < onset_i))[0]
            if control_stim_here is not None:
                c_on = soi[control_stim_here, 0]
                control_prestim_samples = np.where((t >= c_on - prestimulus_time) & (t < c_on))[0]

        # Pick the frequency for this stimulus.
        freq_here = freq_vec[0]
        if freq_vec.size > 1:
            sid = int(stimid[i])
            freq_here = freq_vec[sid - 1] if 1 <= sid <= freq_vec.size else freq_vec[0]

        prestim_here: Any = None
        control_prestim_here: Any = None

        if freq_here == 0:
            if not isspike:
                resp_here = np.nanmean(ts[stim_samples]) if stim_samples.size else np.nan
                control_resp_here = (
                    np.nanmean(ts[control_stim_samples]) if control_stim_samples.size else np.nan
                )
            else:
                dur = offset_i - onset_i
                resp_here = np.sum(ts[stim_samples]) / dur if dur != 0 else np.nan
                control_resp_here = np.sum(ts[control_stim_samples]) / dur if dur != 0 else np.nan
            if prestimulus_time:
                if not isspike:
                    prestim_here = (
                        np.nanmean(ts[prestim_samples]) if prestim_samples.size else np.nan
                    )
                    control_prestim_here = (
                        np.nanmean(ts[control_prestim_samples])
                        if control_prestim_samples.size
                        else np.nan
                    )
                else:
                    dur = offset_i - onset_i
                    prestim_here = np.sum(ts[prestim_samples]) / dur if dur != 0 else np.nan
                    control_prestim_here = (
                        np.sum(ts[control_prestim_samples]) / dur if dur != 0 else np.nan
                    )
        else:
            if not isspike:
                resp_here = (
                    _fouriercoeffs_tf2(ts[stim_samples], freq_here, sample_rate)
                    if stim_samples.size
                    else 0.0
                )
                control_resp_here = (
                    _fouriercoeffs_tf2(ts[control_stim_samples], freq_here, sample_rate)
                    if control_stim_samples.size
                    else 0.0
                )
            else:
                # Spike-train Fourier amplitude at freq_here over the window.
                if stim_samples.size:
                    times = t[stim_samples] - onset_i
                    resp_here = np.sum(np.exp(-1j * 2.0 * np.pi * freq_here * times))
                else:
                    resp_here = 0.0
                if control_stim_samples.size and control_stim_here is not None:
                    c_on = soi[control_stim_here, 0]
                    times = t[control_stim_samples] - c_on
                    control_resp_here = np.sum(np.exp(-1j * 2.0 * np.pi * freq_here * times))
                else:
                    control_resp_here = 0.0
            if prestimulus_time:
                prestim_here = (
                    _fouriercoeffs_tf2(ts[prestim_samples], freq_here, sample_rate)
                    if prestim_samples.size
                    else 0.0
                )
                control_prestim_here = (
                    _fouriercoeffs_tf2(ts[control_prestim_samples], freq_here, sample_rate)
                    if control_prestim_samples.size
                    else 0.0
                )

        if norm is not None and prestim_here is not None:
            if norm in (0, "none"):
                pass
            elif norm in (1, "subtract"):
                resp_here = resp_here - prestim_here
                control_resp_here = control_resp_here - control_prestim_here
            elif norm in (2, "fractional"):
                resp_here = (resp_here - prestim_here) / prestim_here
                control_resp_here = (
                    control_resp_here - control_prestim_here
                ) / control_prestim_here
            elif norm in (3, "divide"):
                resp_here = resp_here / prestim_here
                control_resp_here = control_resp_here / control_prestim_here

        response[i] = resp_here
        if controlstimnumber.size:
            control_response[i] = control_resp_here
        else:
            control_response[i] = np.nan

    return {
        "stimid": stimid,
        "response": response,
        "control_response": control_response,
        "controlstimnumber": controlstimnumber,
    }


class ndi_app_stimulus_tuning__response(ndi_app):
    """
    ndi_app for computing stimulus-response relationships.

    Computes scalar response measures (mean firing rate, F1 component, etc.)
    of neural elements to each stimulus in a set, then organizes these
    into tuning curves.

    Example:
        >>> tr = ndi_app_stimulus_tuning__response(session)
        >>> docs = tr.stimulus_responses(stim_element, timeseries_obj)
        >>> tuning = tr.tuning_curve(response_doc)
    """

    def __init__(self, session: ndi_session | None = None):
        super().__init__(session=session, name="ndi_app_tuning_response")

    def stimulus_responses(
        self,
        ndi_element_stim: Any,
        ndi_timeseries_obj: Any,
        reset: bool = False,
        do_mean_only: bool = False,
    ) -> list[ndi_document]:
        """
        Compute responses to a stimulus set.

        MATLAB equivalent: ndi.app.stimulus.tuning_response/stimulus_responses

        Iterates the stimulus_presentation documents for ``ndi_element_stim``
        that overlap ``ndi_timeseries_obj`` and calls
        :meth:`compute_stimulus_response_scalar` for each, honoring
        ``reset`` (clear existing response docs first) and ``do_mean_only``
        (F0 only). Mirrors tuning_response.m:26-138.

        Args:
            ndi_element_stim: Stimulus element with presentations
            ndi_timeseries_obj: Response timeseries (e.g., neuron)
            reset: Clear existing results first
            do_mean_only: Only compute mean (not frequency components)

        Returns:
            List of stimulus_response_scalar documents
        """
        if self._session is None:
            return []

        from ...query import ndi_query

        E = self._session

        sq_nditimeseries = ndi_query("").depends_on("element_id", ndi_timeseries_obj.id)
        sq_stimelement = ndi_query("").depends_on("stimulus_element_id", ndi_element_stim.id)
        sq_stimelement2 = ndi_query("").depends_on("stimulator_id", ndi_element_stim.id)
        sq_e = E.searchquery()
        sq_stim = ndi_query("").isa("stimulus_presentation")
        sq_resp = ndi_query("").isa("stimulus_response_scalar")
        doc_stim = E.database_search(sq_stim & sq_e & sq_stimelement)
        doc_resp = E.database_search(sq_resp & sq_e & sq_stimelement2 & sq_nditimeseries)

        if reset:
            doc_p = []
            for d in doc_resp:
                pid = d.dependency_value(
                    "stimulus_response_scalar_parameters_id", error_if_not_found=False
                )
                if pid:
                    doc_p.extend(E.database_search(ndi_query("base.id", "exact_string", pid, "")))
            for d in doc_resp:
                E.database_rm(d)
            for d in doc_p:
                E.database_rm(d)

        freq_response = 0 if do_mean_only else None

        rdocs: list[ndi_document] = []
        for stim_d in doc_stim:
            ctrl_search = ndi_query("").depends_on(
                "stimulus_presentation_id", stim_d.id
            ) & ndi_query("").isa("control_stimulus_ids")
            control_stim_docs = E.database_search(ctrl_search)
            for control_d in control_stim_docs:
                result = self.compute_stimulus_response_scalar(
                    ndi_element_stim,
                    ndi_timeseries_obj,
                    stim_d,
                    control_d,
                    freq_response=freq_response,
                )
                if result:
                    rdocs.extend(result)
        return rdocs

    def compute_stimulus_response_scalar(
        self,
        ndi_stim_obj: Any,
        ndi_timeseries_obj: Any,
        stim_doc: ndi_document,
        control_doc: ndi_document | None = None,
        *,
        temporalfreqfunc: str = "ndi.fun.stimulustemporalfrequency",
        freq_response: Any = None,
        prestimulus_time: Any = None,
        prestimulus_normalization: Any = None,
        isspike: bool = False,
        spiketrain_dt: float = 0.001,
    ) -> list[ndi_document]:
        """
        Compute scalar response(s) for a single stimulus presentation.

        MATLAB equivalent:
        ndi.app.stimulus.tuning_response/compute_stimulus_response_scalar
        (tuning_response.m:140-332).

        Reads the response timeseries inside each stimulus on/off window,
        computes the F0 (mean) and, when a stimulus temporal frequency is
        present, the F1/F2 Fourier responses, subtracts the control
        response, and assembles one ``stimulus_response_scalar`` document
        per frequency command (mean, F1, F2). The F0/F1 math is performed
        by :func:`_stimulus_response_scalar` (a faithful port of
        ``vlt.neuro.stimulus.stimulus_response_scalar``).

        Args:
            ndi_stim_obj: Stimulus element
            ndi_timeseries_obj: Response timeseries element
            stim_doc: Stimulus presentation document
            control_doc: Control stimulus document, or None
            temporalfreqfunc: Name of the temporal-frequency routine
            freq_response: Frequency response to measure; None requests the
                default [0, 1, 2] sweep when a fundamental frequency exists.
            prestimulus_time: Baseline window length, or None
            prestimulus_normalization: Normalization mode, or None
            isspike: Whether the response signal is a spike train
            spiketrain_dt: Spike-train reconstruction resolution

        Returns:
            List of stimulus_response_scalar documents (added to the
            database when a session is present).

        Raises:
            NotImplementedError: only for documents whose stimulus on/off timing
                lives solely in the binary ``presentation_time.bin`` portion
                (the reader is not yet ported). The deprecated inline
                ``presentation_time`` form is fully supported.
        """
        if self._session is None:
            return []

        from ...document import ndi_document
        from ...fun.stimulus import stimulustemporalfrequency
        from ...time.clocktype import ndi_time_clocktype
        from ...time.timereference import ndi_time_timereference
        from ..markgarbage import ndi_app_markgarbage
        from .decoder import ndi_app_stimulus_decoder

        E = self._session
        decoder = ndi_app_stimulus_decoder(E)
        gapp = ndi_app_markgarbage(E)

        stim_pres = stim_doc.document_properties.get("stimulus_presentation", {})
        stimuli = stim_pres.get("stimuli", [])
        presentation_order = list(stim_pres.get("presentation_order", []))

        # Decide the set of frequency commands.
        if freq_response is None:
            gotone = False
            for stim in stimuli:
                tf, _ = stimulustemporalfrequency(stim.get("parameters", {}))
                if tf is not None:
                    gotone = True
                    break
            freq_response_commands = [0, 1, 2] if gotone else [0]
        else:
            freq_response_commands = list(np.atleast_1d(freq_response))

        # Per-stimulus fundamental frequency multiplier.
        freq_mult = np.zeros(len(stimuli), dtype=float)
        for j, stim in enumerate(stimuli):
            tf, _ = stimulustemporalfrequency(stim.get("parameters", {}))
            freq_mult[j] = tf if tf is not None else 0.0

        # ---- stimulus on/off timing ----------------------------------------
        # Both forms are supported: the deprecated inline 'presentation_time'
        # field and the current binary 'presentation_time.bin' (read via
        # database_openbinarydoc + read_presentation_time_structure, fetched on
        # demand for cloud datasets). Only error if neither yields timing.
        presentation_time = decoder.load_presentation_time(stim_doc)
        if not presentation_time:
            raise ValueError(
                "compute_stimulus_response_scalar requires per-stimulus on/off "
                "timing, but this stimulus_presentation document has neither an "
                "inline 'presentation_time' nor a readable 'presentation_time.bin' "
                "(for a cloud dataset, ensure NDI_CLOUD credentials / a cloud "
                "client are available). Without it the F0/F1 integration windows "
                "cannot be established."
            )

        onsets = np.asarray([p["onset"] for p in presentation_time], dtype=float)
        offsets = np.asarray([p["offset"] for p in presentation_time], dtype=float)
        clocktype = presentation_time[0].get("clocktype", "dev_local_time")
        epochid = stim_doc.document_properties.get("epochid", {}).get("epochid", "")

        # Convert each stimulus onset/offset into the response timeseries clock.
        stim_timeref = ndi_time_timereference(
            ndi_stim_obj, ndi_time_clocktype(clocktype), epochid, 0
        )
        dev_clock = ndi_time_clocktype("dev_local_time")
        ts_onsets = np.empty_like(onsets)
        ts_offsets = np.empty_like(offsets)
        ts_epoch = None
        for i in range(onsets.size):
            on_out, tr_out, _ = E.syncgraph.time_convert(
                stim_timeref, float(onsets[i]), ndi_timeseries_obj, dev_clock
            )
            off_out, _, _ = E.syncgraph.time_convert(
                stim_timeref, float(offsets[i]), ndi_timeseries_obj, dev_clock
            )
            ts_onsets[i] = on_out if on_out is not None else np.nan
            ts_offsets[i] = off_out if off_out is not None else np.nan
            if tr_out is not None and ts_epoch is None:
                ts_epoch = tr_out.epoch

        ts_stim_onsetoffsetid = np.column_stack(
            [ts_onsets, ts_offsets, np.asarray(presentation_order, dtype=float)]
        )

        # Read the response timeseries over the valid interval.
        _, _, timeref = ndi_timeseries_obj.readtimeseries(ts_epoch, 0, 1)
        gapp.loadvalidinterval(ndi_timeseries_obj)
        interval = gapp.identifyvalidintervals(ndi_timeseries_obj, timeref, 0, float("inf"))
        t0, t1 = (interval[0][0], interval[0][1]) if len(interval) else (0, float("inf"))
        data, t_raw, _ = ndi_timeseries_obj.readtimeseries(ts_epoch, t0, t1)
        data = np.asarray(data, dtype=float).ravel()
        t_raw = np.asarray(t_raw, dtype=float).ravel()

        controlstimids = []
        if control_doc is not None:
            controlstimids = list(
                control_doc.document_properties.get("control_stimulus_ids", {}).get(
                    "control_stimulus_ids", []
                )
            )

        response_docs: list[ndi_document] = []
        for fr in freq_response_commands:
            response_type = "mean" if fr == 0 else f"F{int(fr)}"

            # Parameter document (create or reuse).
            param_doc = self._find_or_make_param_doc(
                temporalfreqfunc,
                fr,
                prestimulus_time,
                prestimulus_normalization,
                isspike,
                spiketrain_dt,
            )

            # Remove any stale matching response docs.
            self._remove_existing_response_docs(
                ndi_timeseries_obj, stim_doc, control_doc, param_doc
            )

            resp = _stimulus_response_scalar(
                data,
                t_raw,
                ts_stim_onsetoffsetid,
                control_stimid=controlstimids,
                freq_response=fr * freq_mult,
                prestimulus_time=prestimulus_time,
                prestimulus_normalization=prestimulus_normalization,
                isspike=isspike,
                spiketrain_dt=spiketrain_dt,
            )

            r = np.asarray(resp["response"], dtype=complex)
            cr = np.asarray(resp["control_response"], dtype=complex)

            responses_struct = {
                "stimid": [int(x) for x in ts_stim_onsetoffsetid[:, 2]],
                "response_real": np.real(r).tolist(),
                "response_imaginary": np.imag(r).tolist(),
                "control_response_real": np.real(cr).tolist(),
                "control_response_imaginary": np.imag(cr).tolist(),
            }

            doc = ndi_document("stimulus/stimulus_response_scalar")
            props = doc.document_properties
            props["stimulus_response_scalar"]["response_type"] = response_type
            props["stimulus_response_scalar"]["responses"] = responses_struct
            props["stimulus_response"]["stimulator_epochid"] = epochid
            props["stimulus_response"]["element_epochid"] = ts_epoch
            if self._session is not None:
                doc.set_session_id(self._session.id())
            doc = doc.set_dependency_value("stimulus_response_scalar_parameters_id", param_doc.id)
            doc = doc.set_dependency_value(
                "element_id", ndi_timeseries_obj.id, error_if_not_found=False
            )
            doc = doc.set_dependency_value(
                "stimulus_presentation_id", stim_doc.id, error_if_not_found=False
            )
            if control_doc is not None:
                doc = doc.set_dependency_value(
                    "stimulus_control_id", control_doc.id, error_if_not_found=False
                )
            doc = doc.set_dependency_value(
                "stimulator_id", ndi_stim_obj.id, error_if_not_found=False
            )
            E.database_add(doc)
            response_docs.append(doc)

        return response_docs

    def tuning_curve(
        self,
        stim_response_doc: ndi_document,
        independent_label: Any = "label1",
        independent_parameter: Any = None,
        constraint: Any = None,
        do_add: bool = True,
    ) -> ndi_document | None:
        """
        Create a tuning curve from stimulus responses.

        MATLAB equivalent: ndi.app.stimulus.tuning_response/tuning_curve
        (tuning_response.m:334-504).

        Aggregates the per-presentation responses in a
        ``stimulus_response_scalar`` document into a
        ``stimulus_tuningcurve`` document: for each unique value of the
        varied parameter(s) it stores the individual responses and their
        mean / stddev / stderr (complex magnitude when the mean is
        complex), together with the matching control statistics.

        Args:
            stim_response_doc: stimulus_response_scalar document
            independent_label: Label(s) for the independent variable
            independent_parameter: Parameter name(s) to vary; required
            constraint: Optional list of fieldsearch-style constraints
            do_add: If True, add the result to the database

        Returns:
            stimulus_tuningcurve document, or None (empty tuning curve)

        Raises:
            ValueError: If ``independent_parameter`` is empty or its
                dimension does not match ``independent_label``.
            RuntimeError: If the stimulus presentation document cannot be
                loaded.
        """
        from ...document import ndi_document
        from ...query import ndi_query

        if self._session is None:
            raise RuntimeError("tuning_curve requires a session")

        E = self._session

        ind_param = independent_parameter
        if ind_param is None:
            ind_param = []
        if isinstance(ind_param, str):
            ind_param = [ind_param]
        ind_label = independent_label
        if isinstance(ind_label, str):
            ind_label = [ind_label]

        # Step 1: error checking
        if len(ind_param) < 1:
            raise ValueError("No criteria for tuning curve: independent_parameter is empty.")
        if len(ind_param) != len(ind_label):
            raise ValueError(
                "Mismatch between dimensions of independent_parameter and " "independent_label."
            )

        # Step 2: build the inclusion constraints (each param must be present)
        constraints = list(constraint) if constraint else []
        for p in ind_param:
            constraints.append({"field": p, "operation": "hasfield", "param1": "", "param2": ""})

        # Step 3: load the stimulus presentation document
        sp_id = stim_response_doc.dependency_value(
            "stimulus_presentation_id", error_if_not_found=False
        )
        stim_pres_docs = E.database_search(ndi_query("base.id", "exact_string", sp_id, ""))
        if not stim_pres_docs:
            raise RuntimeError("Could not load stimulus presentation document.")
        stim_pres_doc = stim_pres_docs[0]
        stimuli = stim_pres_doc.document_properties.get("stimulus_presentation", {}).get(
            "stimuli", []
        )

        responses = stim_response_doc.document_properties.get("stimulus_response_scalar", {}).get(
            "responses", {}
        )
        resp_real = np.asarray(responses.get("response_real", []), dtype=float)
        resp_imag = np.asarray(responses.get("response_imaginary", []), dtype=float)
        ctl_real = np.asarray(responses.get("control_response_real", []), dtype=float)
        ctl_imag = np.asarray(responses.get("control_response_imaginary", []), dtype=float)
        resp_stimid = np.asarray(responses.get("stimid", []))

        # Step 5: determine which stimuli are included + their values
        isincluded: list[bool] = []
        independent_variable_value: list[list[float]] = []
        for stim in stimuli:
            p = stim.get("parameters", {})
            inc = _fieldsearch(p, constraints)
            isincluded.append(inc)
            if inc:
                independent_variable_value.append([float(p[name]) for name in ind_param])

        if not isincluded:
            import warnings

            warnings.warn("empty tuning curve.", UserWarning, stacklevel=2)
            return None

        ivv = np.asarray(independent_variable_value, dtype=float)
        unique_values = _unique_rows(ivv) if ivv.size else np.zeros((0, len(ind_param)))
        num_points = unique_values.shape[0]

        ind_r: list[list[float]] = [[] for _ in range(num_points)]
        ind_i: list[list[float]] = [[] for _ in range(num_points)]
        ctl_r: list[list[float]] = [[] for _ in range(num_points)]
        ctl_i: list[list[float]] = [[] for _ in range(num_points)]
        stim_pres_number: list[list[int]] = [[] for _ in range(num_points)]
        stimid_out = [float("nan")] * num_points
        response_mean = [0.0] * num_points
        response_stddev = [0.0] * num_points
        response_stderr = [0.0] * num_points
        control_response_mean = [0.0] * num_points
        control_response_stddev = [0.0] * num_points
        control_response_stderr = [0.0] * num_points

        nth = 0
        for n in range(len(stimuli)):
            if not isincluded[n]:
                continue
            value_here = ivv[nth]
            nth += 1
            row = _findrow(unique_values, value_here)
            if row is None:
                raise RuntimeError("unexpected.. cannot find stimulus values. Should not happen.")
            # MATLAB stimulus number n is 1-based; presentation stimids match it.
            stim_number = n + 1
            stim_indexes = np.where(resp_stimid == stim_number)[0]
            stimid_out[row] = float(stim_number)

            ind_r[row] = resp_real[stim_indexes].tolist()
            ind_i[row] = resp_imag[stim_indexes].tolist()
            ctl_r[row] = ctl_real[stim_indexes].tolist()
            ctl_i[row] = ctl_imag[stim_indexes].tolist()
            stim_pres_number[row] = [int(x) for x in stim_indexes]

            all_resp = np.asarray(ind_r[row]) + 1j * np.asarray(ind_i[row])
            response_mean[row] = _mean_mag(all_resp)
            response_stddev[row] = _nanstd_complex(all_resp)
            response_stderr[row] = _nanstderr(all_resp)

            all_ctl = np.asarray(ctl_r[row]) + 1j * np.asarray(ctl_i[row])
            control_response_mean[row] = _mean_mag(all_ctl)
            control_response_stddev[row] = _nanstd_complex(all_ctl)
            control_response_stderr[row] = _nanstderr(all_ctl)

        tc = {
            "independent_variable_label": [",".join(str(x) for x in ind_label)],
            "independent_variable_value": unique_values.tolist(),
            "stimid": stimid_out,
            "response_mean": response_mean,
            "response_stddev": response_stddev,
            "response_stderr": response_stderr,
            "individual_responses_real": ind_r,
            "individual_responses_imaginary": ind_i,
            "stimulus_presentation_number": stim_pres_number,
            "control_stimid": [float("nan")] * num_points,
            "control_response_mean": control_response_mean,
            "control_response_stddev": control_response_stddev,
            "control_response_stderr": control_response_stderr,
            "control_individual_responses_real": ctl_r,
            "control_individual_responses_imaginary": ctl_i,
            "response_units": "Spikes/s",
        }

        tuning_doc = ndi_document("stimulus/stimulus_tuningcurve")
        tuning_doc.document_properties["stimulus_tuningcurve"] = tc
        if self._session is not None:
            tuning_doc.set_session_id(self._session.id())
        tuning_doc = tuning_doc.set_dependency_value(
            "stimulus_response_scalar_id", stim_response_doc.id, error_if_not_found=False
        )
        element_id = stim_response_doc.dependency_value("element_id", error_if_not_found=False)
        if element_id is not None:
            tuning_doc = tuning_doc.set_dependency_value(
                "element_id", element_id, error_if_not_found=False
            )
        if do_add:
            E.database_add(tuning_doc)
        return tuning_doc

    def label_control_stimuli(
        self,
        stimulus_element_obj: Any,
        reset: bool = False,
        **kwargs: Any,
    ) -> list[ndi_document]:
        """
        Label control stimuli in a stimulus set.

        MATLAB equivalent: ndi.app.stimulus.tuning_response/label_control_stimuli
        (tuning_response.m:506-544).

        Finds all ``stimulus_presentation`` documents for
        ``stimulus_element_obj``, computes their control stimuli via
        :meth:`control_stimulus`, and stores a ``control_stimulus_ids``
        document for each.

        Args:
            stimulus_element_obj: Stimulus element
            reset: Clear existing labels first
            **kwargs: Forwarded to :meth:`control_stimulus`

        Returns:
            List of control_stimulus_ids documents
        """
        if self._session is None:
            return []

        from ...query import ndi_query

        E = self._session

        sq_stimulus_element = ndi_query("").depends_on(
            "stimulus_element_id", stimulus_element_obj.id
        )
        sq_stim = ndi_query("").isa("stimulus_presentation")
        stim_docs = E.database_search(sq_stim & sq_stimulus_element)

        if reset:
            for stim_d in stim_docs:
                sq_csi = ndi_query("").isa("control_stimulus_ids")
                sq_csi_stim = ndi_query("").depends_on("stimulus_presentation_id", stim_d.id)
                old = E.database_search(sq_csi & sq_csi_stim)
                for d in old:
                    E.database_rm(d)

        cs_docs: list[ndi_document] = []
        for stim_d in stim_docs:
            _, cs_doc = self.control_stimulus(stim_d, **kwargs)
            if cs_doc is not None:
                cs_docs.append(cs_doc)
        return cs_docs

    def control_stimulus(
        self,
        stim_doc: ndi_document,
        *,
        control_stim_method: str = "pseudorandom",
        controlid: str = "isblank",
        controlid_value: Any = 1,
    ) -> tuple[list[float], ndi_document | None]:
        """
        Determine control stimulus IDs for a stimulus presentation.

        MATLAB equivalent: ndi.app.stimulus.tuning_response/control_stimulus
        (tuning_response.m:546-660).

        For each stimulus in the presentation, finds the id of the control
        ("blank") stimulus to subtract. ``pseudorandom`` matches the control
        within the same repetition (closest if a repetition is incomplete);
        ``hasfield`` finds stimuli that carry the ``controlid`` field. A
        ``control_stimulus_ids`` document is created and (when a session is
        present) added to the database.

        Args:
            stim_doc: Stimulus presentation document
            control_stim_method: ``'pseudorandom'`` or ``'hasfield'``
            controlid: Parameter name marking a control stimulus
            controlid_value: Parameter value marking a control stimulus

        Returns:
            Tuple ``(cs_ids, cs_doc)`` where ``cs_ids`` is a list of 1-based
            control-stimulus presentation indices (``nan`` where none) and
            ``cs_doc`` is the control_stimulus_ids document (or None).

        Raises:
            ValueError: If ``control_stim_method`` is unknown or more than
                one control stimulus type is found.
            NotImplementedError: BLOCKER -- the irregular-sequence branch
                needs per-stimulus onset times from
                ``ndi.app.stimulus.decoder.load_presentation_time``, which is
                an unported stub returning ``None``.
        """
        from ...document import ndi_document

        method = control_stim_method.lower()
        if method not in ("pseudorandom", "hasfield"):
            raise ValueError(f"Unknown control stimulus method {control_stim_method}.")

        stim_pres = stim_doc.document_properties.get("stimulus_presentation", {})
        stimuli = stim_pres.get("stimuli", [])
        stimids = np.asarray(stim_pres.get("presentation_order", []))

        # Identify which stimulus indexes are the "control" stimulus.
        controlstimid: list[int] = []
        for n, stim in enumerate(stimuli):
            params = stim.get("parameters", {})
            if method == "pseudorandom":
                cons = [
                    {
                        "field": controlid,
                        "operation": "exact_number",
                        "param1": controlid_value,
                        "param2": "",
                    }
                ]
            else:  # hasfield
                cons = [
                    {
                        "field": controlid,
                        "operation": "hasfield",
                        "param1": "",
                        "param2": "",
                    }
                ]
            if _fieldsearch(params, cons):
                controlstimid.append(n + 1)  # 1-based

        if len(controlstimid) > 1:
            raise ValueError("Do not know what to do with more than one control stimulus type.")

        reps, isregular = _stimids2reps(stimids, len(stimuli))

        control_stim_indexes = np.array([], dtype=int)
        if controlstimid:
            control_stim_indexes = np.where(stimids == controlstimid[0])[0] + 1  # 1-based

        if control_stim_indexes.size == 0:
            cs_ids = np.full(stimids.shape, np.nan, dtype=float)
        else:
            if isregular:
                csi = control_stim_indexes.tolist()
                if np.unique(reps).size > len(csi):
                    csi.append(csi[-1])  # incomplete rep reuses previous control
                cs_ids = np.asarray([csi[r - 1] for r in reps], dtype=float)
            else:
                # Irregular sequence needs presentation onsets (timing). BLOCKER.
                from .decoder import ndi_app_stimulus_decoder

                presentation_time = None
                if self._session is not None:
                    presentation_time = ndi_app_stimulus_decoder(
                        self._session
                    ).load_presentation_time(stim_doc)
                if not presentation_time:
                    raise NotImplementedError(
                        "control_stimulus with an irregular presentation order "
                        "needs per-stimulus onset times from "
                        "ndi.app.stimulus.decoder.load_presentation_time(), which "
                        "is an unported stub returning None. The regular "
                        "(pseudorandom) path is fully supported; this irregular "
                        "branch is a BLOCKER."
                    )
                onsets = np.asarray([p["onset"] for p in presentation_time], dtype=float)
                control_onsets = onsets[control_stim_indexes - 1]
                cs_ids = np.empty(stimids.size, dtype=float)
                for n in range(stimids.size):
                    i = _findclosest(control_onsets, onsets[n])
                    cs_ids[n] = float(control_stim_indexes[i])

        control_stim_id_method = {
            "method": control_stim_method,
            "controlid": controlid,
            "controlid_value": controlid_value,
        }
        cs_doc = ndi_document("stimulus/control_stimulus_ids")
        cs_doc.document_properties["control_stimulus_ids"] = {
            "control_stimulus_ids": cs_ids.tolist(),
            "control_stimulus_id_method": control_stim_id_method,
        }
        if self._session is not None:
            cs_doc.set_session_id(self._session.id())
        cs_doc = cs_doc.set_dependency_value(
            "stimulus_presentation_id", stim_doc.id, error_if_not_found=False
        )
        if self._session is not None:
            self._session.database_add(cs_doc)

        return cs_ids.tolist(), cs_doc

    def find_tuningcurve_document(
        self,
        ndi_element_obj: Any,
        epochid: str,
        response_type: str = "mean",
    ) -> tuple[list[ndi_document], list[ndi_document]]:
        """
        Find existing tuning curve documents.

        MATLAB equivalent: ndi.app.stimulus.tuning_response/find_tuningcurve_document

        Args:
            ndi_element_obj: Neural element
            epochid: Epoch ID
            response_type: Response type (mean, f1, etc.)

        Returns:
            Tuple of (tc_docs, srs_docs) where tc_docs are tuning curve
            documents and srs_docs are stimulus response scalar documents.
        """
        if self._session is None:
            return [], []

        from ...query import ndi_query

        q = ndi_query("").isa("stimulus_tuningcurve") & ndi_query("").depends_on(
            "element_id", ndi_element_obj.id
        )
        tc_docs = self._session.database_search(q)

        q_srs = ndi_query("").isa("stimulus_response_scalar") & ndi_query("").depends_on(
            "element_id", ndi_element_obj.id
        )
        srs_docs = self._session.database_search(q_srs)

        return tc_docs, srs_docs

    def make_1d_tuning(
        self,
        stim_response_doc: ndi_document,
        param_to_vary: str,
        param_to_vary_label: str,
        param_to_fix: str,
    ) -> list[ndi_document]:
        """
        Create 1D tuning curves from a multi-dimensional parameter space.

        MATLAB equivalent: ndi.app.stimulus.tuning_response/make_1d_tuning
        (tuning_response.m:730-777).

        "Deals" the responses of a 2-parameter stimulus set into one tuning
        curve per fixed value of ``param_to_fix``, in each of which
        ``param_to_vary`` varies. Blank stimuli are excluded.

        Args:
            stim_response_doc: stimulus_response_scalar document
            param_to_vary: Parameter name to vary
            param_to_vary_label: Label for the varying parameter
            param_to_fix: Parameter name to hold fixed

        Returns:
            List of stimulus_tuningcurve documents

        Raises:
            RuntimeError: If the stimulus presentation document cannot be
                found.
        """
        if self._session is None:
            raise RuntimeError("make_1d_tuning requires a session")

        from ...query import ndi_query

        S = self._session
        sp_id = stim_response_doc.dependency_value(
            "stimulus_presentation_id", error_if_not_found=False
        )
        stim_pres_docs = S.database_search(ndi_query("base.id", "exact_string", sp_id, ""))
        if not stim_pres_docs:
            raise RuntimeError(
                "Could not find stimulus presentation doc for stimulus response doc."
            )
        stimuli = (
            stim_pres_docs[0]
            .document_properties.get("stimulus_presentation", {})
            .get("stimuli", [])
        )

        included: list[int] = []
        param_to_fix_values: list[float] = []
        for n, stim in enumerate(stimuli):
            params = stim.get("parameters", {})
            if "isblank" not in params:
                included.append(n)
            elif not params["isblank"]:
                included.append(n)
            if n in included and param_to_fix in params and param_to_vary in params:
                param_to_fix_values.append(params[param_to_fix])

        unique_fix = sorted(set(param_to_fix_values))

        tuning_docs: list[ndi_document] = []
        for v in unique_fix:
            constraint = [
                {
                    "field": param_to_fix,
                    "operation": "exact_number",
                    "param1": v,
                    "param2": "",
                }
            ]
            doc = self.tuning_curve(
                stim_response_doc,
                independent_parameter=[param_to_vary],
                independent_label=[param_to_vary_label],
                constraint=constraint,
            )
            if doc is not None:
                tuning_docs.append(doc)
        return tuning_docs

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_or_make_param_doc(
        self,
        temporalfreqfunc: str,
        freq_response: Any,
        prestimulus_time: Any,
        prestimulus_normalization: Any,
        isspike: bool,
        spiketrain_dt: float,
    ) -> ndi_document:
        """Find a matching stimulus_response_scalar_parameters_basic doc or make one."""
        from ...document import ndi_document
        from ...query import ndi_query

        E = self._session
        q = (
            E.searchquery()
            & ndi_query("").isa("stimulus_response_scalar_parameters_basic")
            & ndi_query(
                "stimulus_response_scalar_parameters_basic.temporalfreqfunc",
                "exact_string",
                temporalfreqfunc,
                "",
            )
            & ndi_query(
                "stimulus_response_scalar_parameters_basic.freq_response",
                "exact_number",
                freq_response,
                "",
            )
        )
        found = E.database_search(q)
        if found:
            return found[0]

        doc = ndi_document("stimulus/stimulus_response_scalar_parameters_basic")
        basic = doc.document_properties["stimulus_response_scalar_parameters_basic"]
        basic["temporalfreqfunc"] = temporalfreqfunc
        basic["freq_response"] = freq_response
        basic["prestimulus_time"] = "" if prestimulus_time is None else prestimulus_time
        basic["prestimulus_normalization"] = (
            "" if prestimulus_normalization is None else prestimulus_normalization
        )
        basic["isspike"] = int(isspike)
        basic["spiketrain_dt"] = spiketrain_dt
        if self._session is not None:
            doc.set_session_id(self._session.id())
        E.database_add(doc)
        return doc

    def _remove_existing_response_docs(
        self,
        ndi_timeseries_obj: Any,
        stim_doc: ndi_document,
        control_doc: ndi_document | None,
        param_doc: ndi_document,
    ) -> None:
        """Remove stale stimulus_response_scalar docs that match the new one."""
        from ...query import ndi_query

        E = self._session
        q = (
            E.searchquery()
            & ndi_query("").isa("stimulus_response_scalar")
            & ndi_query("").depends_on("element_id", ndi_timeseries_obj.id)
            & ndi_query("").depends_on("stimulus_presentation_id", stim_doc.id)
            & ndi_query("").depends_on("stimulus_response_scalar_parameters_id", param_doc.id)
        )
        if control_doc is not None:
            q = q & ndi_query("").depends_on("stimulus_control_id", control_doc.id)
        for d in E.database_search(q):
            E.database_rm(d)

    def __repr__(self) -> str:
        return f"ndi_app_stimulus_tuning__response(session={self._session is not None})"


# ---------------------------------------------------------------------------
# Module-level aggregation helpers (ports of vlt.data utilities used by
# tuning_curve)
# ---------------------------------------------------------------------------


def _fieldsearch(params: dict, constraints: list[dict]) -> bool:
    """Minimal port of ``vlt.data.fieldsearch`` for the operations used here.

    Supports the operations that tuning_response.m relies on: ``hasfield``
    and ``exact_number``. Every constraint must be satisfied (logical AND).

    Args:
        params: Stimulus parameter dict.
        constraints: List of ``{field, operation, param1, param2}`` dicts.

    Returns:
        True if all constraints are satisfied.
    """
    for c in constraints:
        field = c.get("field", "")
        op = c.get("operation", "")
        if op == "hasfield":
            if field not in params:
                return False
        elif op == "exact_number":
            if field not in params:
                return False
            try:
                if float(params[field]) != float(c.get("param1")):
                    return False
            except (TypeError, ValueError):
                return False
        else:
            raise ValueError(f"Unsupported fieldsearch operation '{op}'.")
    return True


def _unique_rows(values: np.ndarray) -> np.ndarray:
    """Sorted unique rows of a 2-D array (mirrors MATLAB ``unique(.,'rows')``)."""
    v = np.atleast_2d(values)
    if v.size == 0:
        return v
    return np.unique(v, axis=0)


def _findrow(matrix: np.ndarray, row: np.ndarray) -> int | None:
    """Index of ``row`` within the rows of ``matrix`` (mirrors vlt.data.findrowvec)."""
    m = np.atleast_2d(matrix)
    target = np.asarray(row, dtype=float).ravel()
    for i in range(m.shape[0]):
        if np.array_equal(m[i], target):
            return i
    return None


def _mean_mag(values: np.ndarray) -> float:
    """nanmean that returns magnitude if the mean is complex (tuning_response.m:470-473)."""
    v = np.asarray(values)
    if v.size == 0:
        return float("nan")
    mean = np.nanmean(v)
    if np.iscomplexobj(v) and abs(np.imag(mean)) > 0:
        return float(np.abs(mean))
    return float(np.real(mean))


def _nanstd_complex(values: np.ndarray) -> float:
    """nanstd over complex magnitudes (mirrors MATLAB nanstd on complex data)."""
    v = np.asarray(values)
    if v.size < 2:
        return 0.0
    mag = np.abs(v) if np.iscomplexobj(v) else np.real(v).astype(float)
    valid = mag[~np.isnan(mag)]
    if valid.size < 2:
        return 0.0
    return float(np.nanstd(valid, ddof=1))
