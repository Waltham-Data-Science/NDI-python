"""ndi.app.stimulus.tuning_response - scalar stimulus responses and tuning curves.

MATLAB counterpart: ``src/ndi/+ndi/+app/+stimulus/tuning_response.m``

The middle of the stimulus pipeline. ``ndi.app.stimulus.decoder`` writes what
was shown and when; this app measures how an element answered each stimulus
and stores the answers as ``stimulus_response_scalar`` documents; then
``ndi.calc.stimulus.tuningcurve`` fits them. Before this, the middle step
raised NotImplementedError and the two ends had nothing to say to each other.

WHAT A "SCALAR RESPONSE" IS
For each stimulus presentation, one number: either the mean of the signal
over the stimulus window (F0), or the Fourier component of the signal at the
stimulus's own fundamental frequency (F1) or twice it (F2), which is complex.
Each is paired with the response to that presentation's CONTROL stimulus (a
blank screen, usually), so the caller can subtract a baseline that was
measured close in time rather than once at the start.

Complex numbers reach the database as two real fields, ``response_real`` and
``response_imaginary``, because that is what the ``stimulus_response_scalar``
schema holds in both languages. F0 fills the imaginary field with zeros.

THE MATH LIVES IN vlt, EXCEPT ONE LOOP
NDI-matlab calls ``vlt.neuro.stimulus.stimulus_response_scalar``, and the
Python toolbox has that function -- but as of vhlab-toolbox-python 9228e90 it
cannot run: it reaches its helpers as ``module.function`` where the package
``__init__`` has already bound the bare function to that name
(``AttributeError`` on the first call), and its output arrays are
preallocated ``float``, so the F1/F2 path raises as soon as a complex
response is stored. Both are reported in VH-Lab/vhlab-toolbox-python#24.

So :func:`scalar_responses` below is the loop, and only the loop. Everything
under it -- ``findcontrolstimulus``, ``fouriercoeffs_tf2``,
``fouriercoeffs_tf_spikes`` -- is called from the toolbox, where it works and
where it belongs. When the toolbox function runs, this one should be deleted
in favour of it; it is written to the same signature so that is a one-line
change. Nothing else here reimplements vlt: ``fieldsearch``,
``stimids2reps``, ``findclosest``, ``findrowvec`` and ``nanstderr`` are all
imported.

INDEXES: WHERE 1-BASED SURVIVES AND WHERE IT DOES NOT
Stimulus ids and presentation numbers are user-facing scientific counts and
stay 1-based in the documents, as in MATLAB -- a document written by one
language is read by the other. Everything internal (indexing into a NumPy
array of samples, into the presentation order) is 0-based, per
``docs/developer_notes/ndi_xlang_principles.md``. The conversions are made
explicitly at each boundary rather than absorbed, so they can be checked.

AN UPSTREAM BUG, MIRRORED DELIBERATELY
MATLAB hands ``control_stimulus_ids`` -- a per-presentation vector of control
PRESENTATION numbers -- to a vlt argument named ``control_stimid``, which
that function documents as the id of the control STIMULUS. The two are
different quantities, so the stimulus subtracted as the "blank" is whichever
one's id happens to equal the blank's position in repetition 1: correct by
coincidence for an unshuffled order, a different grating each epoch for a
pseudorandom one. The effect is close to a constant baseline offset -- tuning
shape and preferred direction are unchanged, which is why it went unnoticed
-- but the offset can be as large as the whole response when the substitute
lands on the preferred direction.

It is mirrored here rather than corrected: parity with NDI-matlab is the
contract, and a divergence would make the two ports store different controls
for the same data. Reported as VH-Lab/NDI-matlab#912, with the one-line fix;
this port should follow whatever lands there.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any

import numpy as np

from ...fun.utils import identifier
from .. import ndi_app

if TYPE_CHECKING:
    from ...document import ndi_document
    from ...session.session_base import ndi_session

__all__ = [
    "ndi_app_stimulus_tuning__response",
    "scalar_responses",
    "MEAN_RESPONSE_NAMES",
    "MODULATED_RESPONSE_NAMES",
]

#: ``response_type`` values that count as the mean response, for
#: :meth:`ndi_app_stimulus_tuning__response.modulated_or_mean`.
MEAN_RESPONSE_NAMES = ("F0", "mean")

#: ``response_type`` values that count as the modulated response.
MODULATED_RESPONSE_NAMES = ("F1", "modulated")

#: The temporal-frequency routine named in the parameter document.
DEFAULT_TEMPORALFREQFUNC = "ndi.fun.stimulustemporalfrequency"


# ----------------------------------------------------------------------
# The scalar-response loop (stand-in for vlt.neuro.stimulus.stimulus_response_scalar)
# ----------------------------------------------------------------------
def scalar_responses(
    timeseries: Any,
    timestamps: Any,
    stim_onsetoffsetid: Any,
    *,
    freq_response: Any = 0,
    control_stimid: Any = (),
    prestimulus_time: float | None = None,
    prestimulus_normalization: Any = None,
    isspike: bool = False,
    spiketrain_dt: float = 0.001,
) -> dict[str, Any]:
    """One scalar response per stimulus presentation, with its control.

    A port of ``vlt.neuro.stimulus.stimulus_response_scalar``, kept here only
    until the toolbox's own version runs (see the module docstring and
    VH-Lab/vhlab-toolbox-python#24). Same arguments, same returned fields.

    Args:
        timeseries: the response signal; for a spike process, ones at spike
            times.
        timestamps: the time of each sample of TIMESERIES, in seconds.
        stim_onsetoffsetid: one row per presentation,
            ``[onset, offset, stimid]``, in TIMESTAMPS' units.
        freq_response: 0 for the mean, a frequency for the Fourier component
            at that frequency, or one frequency per STIMULUS (indexed by
            stimid, 1-based) to use a different frequency for each.
        control_stimid: the control stimulus id(s), as MATLAB passes them.
        prestimulus_time: seconds of baseline before each stimulus, or None.
        prestimulus_normalization: None/0 none, 1 subtract, 2 fractional
            change, 3 divide. The names ``'none'``, ``'subtract'``,
            ``'fractional'`` and ``'divide'`` are accepted too.
        isspike: True when TIMESERIES is a spike process, which changes F0
            from a mean to a rate and F1 from an FFT to a spike-time sum.
        spiketrain_dt: recorded in the parameters; the spike Fourier
            routine works from spike times directly and does not need it.

    Returns:
        ``{"stimid", "response", "control_response", "controlstimnumber",
        "parameters"}``. ``response`` and ``control_response`` are complex
        arrays -- the reason this function exists rather than the toolbox's.
    """
    from vlt.math.fouriercoeffs_tf2 import fouriercoeffs_tf2
    from vlt.math.fouriercoeffs_tf_spikes import fouriercoeffs_tf_spikes
    from vlt.neuro.stimulus.findcontrolstimulus import findcontrolstimulus

    timeseries = np.asarray(timeseries, dtype=float).ravel()
    timestamps = np.asarray(timestamps, dtype=float).ravel()
    onsetoffsetid = np.atleast_2d(np.asarray(stim_onsetoffsetid, dtype=float))

    stimid = onsetoffsetid[:, 2].astype(int)
    n = stimid.size

    # Complex from the start. MATLAB grows the array and it becomes complex
    # when the first Fourier response lands in it; NumPy has to be told, and
    # the toolbox's float array is exactly the bug this stands in for.
    response = np.full(n, np.nan, dtype=complex)
    control_response = np.full(n, np.nan, dtype=complex)

    sample_rate = 0.0
    if timestamps.size > 1:
        sample_rate = 1.0 / float(np.median(np.diff(timestamps)))

    controlstimnumber = np.asarray(findcontrolstimulus(stimid, np.asarray(control_stimid).ravel()))

    if isinstance(prestimulus_normalization, str):
        prestimulus_normalization = prestimulus_normalization.lower()
    freq_vector = np.atleast_1d(np.asarray(freq_response, dtype=float))

    for i in range(n):
        onset, offset = onsetoffsetid[i, 0], onsetoffsetid[i, 1]
        duration = offset - onset
        stimulus_samples = np.where((timestamps >= onset) & (timestamps <= offset))[0]

        control_index = _control_index_for(controlstimnumber, i, onsetoffsetid.shape[0])
        control_samples: np.ndarray = np.empty(0, dtype=int)
        if control_index is not None:
            control_samples = np.where(
                (timestamps >= onsetoffsetid[control_index, 0])
                & (timestamps <= onsetoffsetid[control_index, 1])
            )[0]

        if not isspike and _out_of_bounds(timestamps, onsetoffsetid, i, control_index):
            # A window the recording does not cover. NaN, not zero: nothing
            # was measured here, which is not the same as measuring nothing.
            response[i] = np.nan
            control_response[i] = np.nan
            continue

        prestimulus_samples: np.ndarray = np.empty(0, dtype=int)
        control_prestimulus_samples: np.ndarray = np.empty(0, dtype=int)
        if prestimulus_time:
            prestimulus_samples = np.where(
                (timestamps >= onset - prestimulus_time) & (timestamps < onset)
            )[0]
            if control_index is not None:
                control_onset = onsetoffsetid[control_index, 0]
                control_prestimulus_samples = np.where(
                    (timestamps >= control_onset - prestimulus_time) & (timestamps < control_onset)
                )[0]

        freq_here = _frequency_for(freq_vector, stimid, i)

        if freq_here == 0:
            if not isspike:
                response_here = _nanmean(timeseries[stimulus_samples])
                control_here = _nanmean(timeseries[control_samples])
            else:
                # A rate: spikes in the window over the window's length.
                # MATLAB divides the CONTROL count by this stimulus's
                # duration as well, and that is mirrored rather than
                # "fixed" -- the two ports must agree on stored numbers.
                response_here = _rate(timeseries[stimulus_samples], duration)
                control_here = _rate(timeseries[control_samples], duration)
            if prestimulus_time:
                if not isspike:
                    prestimulus_here = _nanmean(timeseries[prestimulus_samples])
                    control_prestimulus_here = _nanmean(timeseries[control_prestimulus_samples])
                else:
                    prestimulus_here = _rate(timeseries[prestimulus_samples], duration)
                    control_prestimulus_here = _rate(
                        timeseries[control_prestimulus_samples], duration
                    )
            else:
                prestimulus_here = control_prestimulus_here = 0.0
        else:
            if not isspike:
                response_here = (
                    fouriercoeffs_tf2(timeseries[stimulus_samples], freq_here, sample_rate)
                    if stimulus_samples.size
                    else 0.0
                )
                control_here = (
                    fouriercoeffs_tf2(timeseries[control_samples], freq_here, sample_rate)
                    if control_samples.size
                    else 0.0
                )
            else:
                response_here = (
                    fouriercoeffs_tf_spikes(
                        timestamps[stimulus_samples] - onset, freq_here, duration
                    )
                    if stimulus_samples.size
                    else 0.0
                )
                control_here = 0.0
                if control_samples.size and control_index is not None:
                    control_onset = onsetoffsetid[control_index, 0]
                    control_here = fouriercoeffs_tf_spikes(
                        timestamps[control_samples] - control_onset,
                        freq_here,
                        onsetoffsetid[control_index, 1] - control_onset,
                    )
            prestimulus_here = control_prestimulus_here = 0.0
            if prestimulus_time:
                if not isspike:
                    prestimulus_here = (
                        fouriercoeffs_tf2(timeseries[prestimulus_samples], freq_here, sample_rate)
                        if prestimulus_samples.size
                        else 0.0
                    )
                    control_prestimulus_here = (
                        fouriercoeffs_tf2(
                            timeseries[control_prestimulus_samples], freq_here, sample_rate
                        )
                        if control_prestimulus_samples.size
                        else 0.0
                    )
                else:
                    if prestimulus_samples.size:
                        prestimulus_here = fouriercoeffs_tf_spikes(
                            timestamps[prestimulus_samples] - onset - prestimulus_time,
                            freq_here,
                            prestimulus_time,
                        )
                    if control_prestimulus_samples.size and control_index is not None:
                        control_prestimulus_here = fouriercoeffs_tf_spikes(
                            timestamps[control_prestimulus_samples]
                            - onsetoffsetid[control_index, 0]
                            - prestimulus_time,
                            freq_here,
                            prestimulus_time,
                        )

        response_here, control_here = _normalize(
            response_here,
            control_here,
            prestimulus_here,
            control_prestimulus_here,
            prestimulus_normalization,
        )

        response[i] = response_here
        control_response[i] = control_here if controlstimnumber.size else np.nan

    return {
        "stimid": stimid,
        "response": response,
        "control_response": control_response,
        "controlstimnumber": controlstimnumber,
        "parameters": {
            "freq_response": freq_response,
            "control_stimid": control_stimid,
            "prestimulus_time": prestimulus_time,
            "prestimulus_normalization": prestimulus_normalization,
            "isspike": isspike,
            "spiketrain_dt": spiketrain_dt,
        },
    }


def _control_index_for(controlstimnumber: np.ndarray, i: int, n_rows: int) -> int | None:
    """The presentation index of stimulus I's control, or None.

    ``findcontrolstimulus`` returns 0-based indexes (MATLAB's are 1-based;
    the toolbox converts, and this is the internal side of the boundary). It
    can also return fewer entries than there are presentations, or an index
    past the end when a repetition is incomplete -- both mean "no control
    here" rather than an error.
    """
    if i >= controlstimnumber.size:
        return None
    value = controlstimnumber[i]
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    index = int(value)
    return index if 0 <= index < n_rows else None


def _out_of_bounds(
    timestamps: np.ndarray, onsetoffsetid: np.ndarray, i: int, control_index: int | None
) -> bool:
    """True when the recording does not cover this stimulus or its control.

    Only meaningful for a sampled signal. For a spike process the absence of
    a spike is a measurement, not a gap, so MATLAB skips this test there and
    so does the caller.
    """
    if timestamps.size == 0:
        return True
    out = timestamps[-1] < onsetoffsetid[i, 1] or timestamps[0] > onsetoffsetid[i, 0]
    if control_index is not None:
        out = out or (
            timestamps[-1] < onsetoffsetid[control_index, 1]
            or timestamps[0] > onsetoffsetid[control_index, 0]
        )
    return bool(out)


def _frequency_for(freq_vector: np.ndarray, stimid: np.ndarray, i: int) -> float:
    """The frequency to measure for presentation I.

    A single value applies to every stimulus; a vector is indexed by the
    stimulus id, which is 1-based in the documents. MATLAB falls back to the
    first entry and warns of a "likely stimulus glitch" when the id is out of
    range; the same fallback, said in a way that names the id.
    """
    if freq_vector.size <= 1:
        return float(freq_vector[0]) if freq_vector.size else 0.0
    index = int(stimid[i]) - 1
    if 0 <= index < freq_vector.size:
        return float(freq_vector[index])
    warnings.warn(
        f"likely stimulus glitch: stimulus id {stimid[i]} has no frequency entry; "
        f"using the first of {freq_vector.size}.",
        stacklevel=3,
    )
    return float(freq_vector[0])


def _nanmean(values: np.ndarray) -> float:
    """MATLAB's nanmean, including NaN for an empty window."""
    if values.size == 0 or np.all(np.isnan(values)):
        return float("nan")
    return float(np.nanmean(values))


def _rate(values: np.ndarray, duration: float) -> float:
    """Spikes per second over DURATION. NaN when the window has no length."""
    if duration <= 0:
        return float("nan")
    return float(np.sum(values)) / float(duration)


def _normalize(
    response: Any, control: Any, prestimulus: Any, control_prestimulus: Any, mode: Any
) -> tuple[Any, Any]:
    """Apply the prestimulus normalization MODE. MATLAB's switch."""
    if mode in (None, 0, "none", ""):
        return response, control
    if mode in (1, "subtract"):
        return response - prestimulus, control - control_prestimulus
    if mode in (2, "fractional"):
        return (
            _divide(response - prestimulus, prestimulus),
            _divide(control - control_prestimulus, control_prestimulus),
        )
    if mode in (3, "divide"):
        return _divide(response, prestimulus), _divide(control, control_prestimulus)
    return response, control


def _divide(numerator: Any, denominator: Any) -> Any:
    """Division that yields NaN rather than raising on a zero baseline."""
    if denominator == 0:
        return float("nan")
    return numerator / denominator


class ndi_app_stimulus_tuning__response(ndi_app):
    """Compute stimulus responses and tuning curves for an element.

    MATLAB counterpart: ``ndi.app.stimulus.tuning_response``.

    Example:
        >>> app = ndi_app_stimulus_tuning__response(session)
        >>> app.label_control_stimuli(stimulator)         # once per stimulator
        >>> docs = app.stimulus_responses(stimulator, neuron)
        >>> curve = app.tuning_curve(docs[0], independent_parameter=["angle"])
    """

    def __init__(self, session: ndi_session | None = None):
        super().__init__(session=session, name="ndi_app_tuning_response")

    # ------------------------------------------------------------------
    # responses
    # ------------------------------------------------------------------
    def stimulus_responses(
        self,
        ndi_element_stim: Any,
        ndi_timeseries_obj: Any,
        reset: bool = False,
        do_mean_only: bool = False,
    ) -> list[ndi_document]:
        """Write stimulus responses for every epoch NDI_ELEMENT_STIM shares.

        MATLAB equivalent: ``tuning_response/stimulus_responses``.

        For each ``stimulus_presentation`` document of the stimulator, this
        finds the epoch of NDI_TIMESERIES_OBJ that the presentation overlaps,
        and computes the responses there. A presentation whose epoch cannot
        be reached from the response element -- a different recording, a
        session with no sync rule between the two -- is SKIPPED rather than
        raising: a stimulator and an electrode that never ran together simply
        have no responses to compute, which is not an error.

        Args:
            ndi_element_stim: the stimulator element.
            ndi_timeseries_obj: the element that responded.
            reset: remove the existing responses (and their parameter
                documents) for this pair first, rebuilding from scratch.
            do_mean_only: compute F0 only, skipping F1 and F2.

        Returns:
            The ``stimulus_response_scalar`` documents written.
        """
        if self._session is None:
            return []

        from ...query import ndi_query
        from ...time.clocktype import ndi_time_clocktype
        from ...time.timereference import ndi_time_timereference
        from .decoder import ndi_app_stimulus_decoder

        session = self._session
        decoder = ndi_app_stimulus_decoder(session)

        in_session = session.searchquery()
        doc_stim = session.database_search(
            ndi_query("").isa("stimulus_presentation")
            & in_session
            & ndi_query("").depends_on("stimulus_element_id", identifier(ndi_element_stim))
        )
        if reset:
            self._remove_responses(ndi_element_stim, ndi_timeseries_obj)

        device_clock = ndi_time_clocktype("dev_local_time")
        response_docs: list[ndi_document] = []

        for stim_doc in doc_stim:
            presentation_time = decoder.load_presentation_time(stim_doc)
            if not presentation_time:
                continue
            # One stimulus epoch overlaps one response epoch, so the first
            # stimulus stands in for them all -- MATLAB's assumption, and the
            # reason this costs one time conversion per document.
            first = presentation_time[0]
            stim_timeref = ndi_time_timereference(
                ndi_element_stim,
                ndi_time_clocktype(first.get("clocktype", "dev_local_time")),
                self._epochid(stim_doc),
                first["onset"],
            )
            try:
                t_out, _, _ = session.syncgraph.time_convert(
                    stim_timeref, 0, ndi_timeseries_obj, device_clock
                )
            except Exception:  # noqa: BLE001 - unreachable epoch, not an error
                t_out = None
            if t_out is None:
                continue

            control_docs = session.database_search(
                ndi_query("").depends_on("stimulus_presentation_id", stim_doc.id)
                & ndi_query("").isa("control_stimulus_ids")
            )
            for control_doc in control_docs:
                response_docs.extend(
                    self.compute_stimulus_response_scalar(
                        ndi_element_stim,
                        ndi_timeseries_obj,
                        stim_doc,
                        control_doc,
                        freq_response=0 if do_mean_only else None,
                    )
                )
        return response_docs

    def compute_stimulus_response_scalar(
        self,
        ndi_stim_obj: Any,
        ndi_timeseries_obj: Any,
        stim_doc: ndi_document,
        control_doc: ndi_document | None = None,
        *,
        temporalfreqfunc: str = DEFAULT_TEMPORALFREQFUNC,
        freq_response: Any = None,
        prestimulus_time: float | None = None,
        prestimulus_normalization: Any = None,
        isspike: bool | None = None,
        spiketrain_dt: float = 0.001,
    ) -> list[ndi_document]:
        """Compute the responses to one stimulus presentation.

        MATLAB equivalent:
        ``tuning_response/compute_stimulus_response_scalar``.

        One document per frequency: ``mean`` always, plus ``F1`` and ``F2``
        when any stimulus in the set declares a fundamental frequency. Each
        carries the response and the control response to every presentation,
        so a caller can average them however it likes.

        Args:
            ndi_stim_obj: the stimulator element.
            ndi_timeseries_obj: the element that responded.
            stim_doc: the ``stimulus_presentation`` document.
            control_doc: the ``control_stimulus_ids`` document, or None.
            temporalfreqfunc: the routine that reads a stimulus's frequency,
                recorded in the parameter document so a later reader knows
                how the frequencies were obtained.
            freq_response: the frequencies to measure. None asks for the
                ``[0, 1, 2]`` sweep when a fundamental frequency exists, and
                ``[0]`` when none does.
            prestimulus_time: seconds of baseline before each stimulus.
            prestimulus_normalization: how to apply that baseline.
            isspike: True for a spike process. None reads the element's
                ``type``, as MATLAB does, so spiking elements are handled
                correctly without the caller saying so.
            spiketrain_dt: spike-train reconstruction resolution.

        Returns:
            The ``stimulus_response_scalar`` documents, already added.

        Raises:
            ValueError: when the presentation document carries no per-stimulus
                timing, inline or binary. That is a limitation of the
                document, not an unported path: without onsets there are no
                windows to measure over.
        """
        if self._session is None:
            return []

        from ...fun.stimulus import stimulustemporalfrequency
        from ...time.clocktype import ndi_time_clocktype
        from ...time.timereference import ndi_time_timereference
        from ..markgarbage import ndi_app_markgarbage
        from .decoder import ndi_app_stimulus_decoder

        session = self._session
        if isspike is None:
            isspike = str(getattr(ndi_timeseries_obj, "type", "")).lower() == "spikes"

        presentation = stim_doc.document_properties.get("stimulus_presentation", {}) or {}
        stimuli = presentation.get("stimuli", []) or []
        presentation_order = list(presentation.get("presentation_order", []) or [])

        # The fundamental frequency of each stimulus, 0 where it has none.
        freq_mult = np.zeros(len(stimuli), dtype=float)
        for j, stimulus in enumerate(stimuli):
            frequency, _ = stimulustemporalfrequency(stimulus.get("parameters", {}) or {})
            freq_mult[j] = frequency if frequency is not None else 0.0

        if freq_response is None:
            freq_commands = [0, 1, 2] if np.any(freq_mult != 0) else [0]
        else:
            freq_commands = [float(f) for f in np.atleast_1d(freq_response)]

        decoder = ndi_app_stimulus_decoder(session)
        presentation_time = decoder.load_presentation_time(stim_doc)
        if not presentation_time:
            raise ValueError(
                "compute_stimulus_response_scalar needs the onset and offset of each "
                "stimulus, and this stimulus_presentation document has neither an "
                "inline 'presentation_time' nor a readable 'presentation_time.bin'. "
                "Without them there is no window to measure a response over."
            )

        epochid = self._epochid(stim_doc)
        clocktype = presentation_time[0].get("clocktype", "dev_local_time")
        stim_timeref = ndi_time_timereference(
            ndi_stim_obj, ndi_time_clocktype(clocktype), epochid, 0
        )
        device_clock = ndi_time_clocktype("dev_local_time")

        onsets = np.asarray([p["onset"] for p in presentation_time], dtype=float)
        offsets = np.asarray([p["offset"] for p in presentation_time], dtype=float)
        ts_onsets = np.full(onsets.shape, np.nan)
        ts_offsets = np.full(offsets.shape, np.nan)
        element_epoch = None
        for i in range(onsets.size):
            on_out, timeref_out, _ = session.syncgraph.time_convert(
                stim_timeref, float(onsets[i]), ndi_timeseries_obj, device_clock
            )
            off_out, _, _ = session.syncgraph.time_convert(
                stim_timeref, float(offsets[i]), ndi_timeseries_obj, device_clock
            )
            if on_out is not None:
                ts_onsets[i] = float(on_out)
            if off_out is not None:
                ts_offsets[i] = float(off_out)
            if element_epoch is None and timeref_out is not None:
                element_epoch = timeref_out.epoch

        onsetoffsetid = np.column_stack(
            [ts_onsets, ts_offsets, np.asarray(presentation_order, dtype=float)]
        )

        # Read the element over its valid interval. The first read is the one
        # that yields the time reference the valid intervals are expressed in,
        # which is why it happens before the interval is known -- MATLAB reads
        # a single sample for the same reason.
        _, _, element_timeref = ndi_timeseries_obj.readtimeseries(element_epoch, 0, 1)
        interval = ndi_app_markgarbage(session).identifyvalidintervals(
            ndi_timeseries_obj, element_timeref, 0, float("inf")
        )
        t0, t1 = interval[0] if interval else (0.0, float("inf"))
        data, t_raw, _ = ndi_timeseries_obj.readtimeseries(element_epoch, t0, t1)
        data = np.asarray(data, dtype=float).ravel()
        t_raw = np.asarray(t_raw, dtype=float).ravel()

        control_stimulus_ids: list[Any] = []
        if control_doc is not None:
            control_stimulus_ids = list(
                (control_doc.document_properties.get("control_stimulus_ids", {}) or {}).get(
                    "control_stimulus_ids", []
                )
                or []
            )

        response_docs: list[ndi_document] = []
        for freq in freq_commands:
            response_type = "mean" if freq == 0 else f"F{int(freq)}"
            param_doc = self._parameter_document(
                temporalfreqfunc,
                freq,
                prestimulus_time,
                prestimulus_normalization,
                isspike,
                spiketrain_dt,
            )
            # An existing response for exactly these parameters is replaced,
            # not added beside: two documents claiming the same measurement
            # would make every later reader pick one arbitrarily.
            self._remove_matching_responses(ndi_timeseries_obj, stim_doc, control_doc, param_doc)

            computed = scalar_responses(
                data,
                t_raw,
                onsetoffsetid,
                freq_response=freq * freq_mult if freq else 0,
                control_stimid=control_stimulus_ids,
                prestimulus_time=prestimulus_time,
                prestimulus_normalization=prestimulus_normalization,
                isspike=isspike,
                spiketrain_dt=spiketrain_dt,
            )
            response = np.asarray(computed["response"], dtype=complex)
            control = np.asarray(computed["control_response"], dtype=complex)

            doc = self._new_document("stimulus_response_scalar")
            doc.document_properties["stimulus_response_scalar"] = {
                "response_type": response_type,
                "responses": {
                    "stimid": [int(s) for s in onsetoffsetid[:, 2]],
                    "response_real": np.real(response).tolist(),
                    "response_imaginary": np.imag(response).tolist(),
                    "control_response_real": np.real(control).tolist(),
                    "control_response_imaginary": np.imag(control).tolist(),
                },
            }
            doc.document_properties["stimulus_response"] = {
                "stimulator_epochid": epochid,
                "element_epochid": element_epoch,
            }
            doc = doc.set_dependency_value(
                "stimulus_response_scalar_parameters_id", param_doc.id, error_if_not_found=False
            )
            doc = doc.set_dependency_value(
                "element_id", identifier(ndi_timeseries_obj), error_if_not_found=False
            )
            doc = doc.set_dependency_value(
                "stimulus_presentation_id", stim_doc.id, error_if_not_found=False
            )
            if control_doc is not None:
                doc = doc.set_dependency_value(
                    "stimulus_control_id", control_doc.id, error_if_not_found=False
                )
            doc = doc.set_dependency_value(
                "stimulator_id", identifier(ndi_stim_obj), error_if_not_found=False
            )
            session.database_add(doc)
            response_docs.append(doc)

        return response_docs

    # ------------------------------------------------------------------
    # tuning curves
    # ------------------------------------------------------------------
    def tuning_curve(
        self,
        stim_response_doc: ndi_document,
        independent_label: Any = "label1",
        independent_parameter: Any = None,
        constraint: Any = None,
        do_add: bool = True,
        response_units: str = "Spikes/s",
    ) -> ndi_document | None:
        """Average the per-presentation responses into a tuning curve.

        MATLAB equivalent: ``tuning_response/tuning_curve``.

        One point per unique value of the independent parameter(s), holding
        the individual responses that went into it as well as their mean,
        standard deviation and standard error, with the matching control
        statistics. Keeping the individuals is what lets a later fit weight
        or resample them.

        A mean that comes out complex is reported as its MAGNITUDE, as in
        MATLAB: the phase of an F1 response depends on when the stimulus
        happened to start, so it is not comparable across stimuli, while the
        magnitude is the response strength a tuning curve is about.

        Args:
            stim_response_doc: the ``stimulus_response_scalar`` document.
            independent_label: the axis label(s), one per parameter.
            independent_parameter: the stimulus parameter(s) that vary,
                e.g. ``["angle"]`` or ``["angle", "sFrequency"]``. Required.
            constraint: further ``vlt.data.fieldsearch`` constraints a
                stimulus must satisfy to be included.
            do_add: add the document to the database.
            response_units: recorded in the document, for a later reader.

        Returns:
            The ``stimulus_tuningcurve`` document, or None when no stimulus
            in the set carries the parameters asked for.

        Raises:
            ValueError: when no independent parameter is given, or the labels
                do not match the parameters one for one.
            RuntimeError: when the presentation document cannot be loaded.
        """
        from vlt.data.fieldsearch import fieldsearch
        from vlt.data.findrowvec import findrowvec

        from ...query import ndi_query

        if self._session is None:
            raise RuntimeError("tuning_curve requires a session.")

        parameters = _as_list(independent_parameter)
        labels = _as_list(independent_label)
        if not parameters:
            raise ValueError(
                "No criteria for tuning curve: independent_parameter is empty. "
                "Name the stimulus parameter that varies, e.g. ['angle']."
            )
        if len(parameters) != len(labels):
            raise ValueError(
                "Mismatch between dimensions of independent_parameter and independent_label: "
                f"{len(parameters)} parameter(s) against {len(labels)} label(s)."
            )

        constraints = [dict(c) for c in _as_list(constraint)]
        constraints.extend(
            {"field": name, "operation": "hasfield", "param1": "", "param2": ""}
            for name in parameters
        )

        presentation_id = stim_response_doc.dependency_value(
            "stimulus_presentation_id", error_if_not_found=False
        )
        presentation_docs = self._session.database_search(
            ndi_query("base.id", "exact_string", presentation_id or "", "")
        )
        if not presentation_docs:
            raise RuntimeError(
                "Could not load the stimulus presentation document this response refers to "
                f"(id {presentation_id!r})."
            )
        stimuli = (
            presentation_docs[0].document_properties.get("stimulus_presentation", {}) or {}
        ).get("stimuli", []) or []

        responses = (
            stim_response_doc.document_properties.get("stimulus_response_scalar", {}) or {}
        ).get("responses", {}) or {}
        response_real = np.asarray(responses.get("response_real", []), dtype=float)
        response_imaginary = np.asarray(responses.get("response_imaginary", []), dtype=float)
        control_real = np.asarray(responses.get("control_response_real", []), dtype=float)
        control_imaginary = np.asarray(responses.get("control_response_imaginary", []), dtype=float)
        response_stimid = np.asarray(responses.get("stimid", []))

        included: list[bool] = []
        values: list[list[float]] = []
        for stimulus in stimuli:
            stimulus_parameters = stimulus.get("parameters", {}) or {}
            is_in = bool(fieldsearch(stimulus_parameters, constraints))
            included.append(is_in)
            if is_in:
                values.append([float(stimulus_parameters[name]) for name in parameters])

        if not any(included):
            warnings.warn("empty tuning curve.", stacklevel=2)
            return None

        value_array = np.asarray(values, dtype=float)
        unique_values = _unique_rows(value_array)
        num_points = unique_values.shape[0]

        curve = _empty_curve(num_points, labels, unique_values, response_units)

        nth = 0
        for n, is_in in enumerate(included):
            if not is_in:
                continue
            found = findrowvec(unique_values, value_array[nth])
            nth += 1
            if found is None or len(np.atleast_1d(found)) == 0:
                raise RuntimeError("unexpected: cannot find stimulus values. Should not happen.")
            row = int(np.atleast_1d(found)[0])

            # Stimulus numbers in a document are 1-based, as in MATLAB; N is
            # the 0-based position in the list.
            stimulus_number = n + 1
            where = np.where(response_stimid == stimulus_number)[0]
            curve["stimid"][row] = float(stimulus_number)
            curve["individual_responses_real"][row] = response_real[where].tolist()
            curve["individual_responses_imaginary"][row] = response_imaginary[where].tolist()
            curve["control_individual_responses_real"][row] = control_real[where].tolist()
            curve["control_individual_responses_imaginary"][row] = control_imaginary[where].tolist()
            # Presentation numbers are user-facing too, so 1-based.
            curve["stimulus_presentation_number"][row] = [int(i) + 1 for i in where]

            all_responses = response_real[where] + 1j * response_imaginary[where]
            curve["response_mean"][row] = _mean_magnitude(all_responses)
            curve["response_stddev"][row] = _nanstd(all_responses)
            curve["response_stderr"][row] = _nanstderr(all_responses)

            all_controls = control_real[where] + 1j * control_imaginary[where]
            curve["control_response_mean"][row] = _mean_magnitude(all_controls)
            curve["control_response_stddev"][row] = _nanstd(all_controls)
            curve["control_response_stderr"][row] = _nanstderr(all_controls)

        tuning_doc = self._new_document("stimulus_tuningcurve")
        tuning_doc.document_properties["stimulus_tuningcurve"] = curve
        tuning_doc = tuning_doc.set_dependency_value(
            "stimulus_response_scalar_id", stim_response_doc.id, error_if_not_found=False
        )
        element_id = stim_response_doc.dependency_value("element_id", error_if_not_found=False)
        if element_id:
            tuning_doc = tuning_doc.set_dependency_value(
                "element_id", element_id, error_if_not_found=False
            )
        if do_add:
            self._session.database_add(tuning_doc)
        return tuning_doc

    def make_1d_tuning(
        self,
        stim_response_doc: ndi_document,
        param_to_vary: str,
        param_to_vary_label: str,
        param_to_fix: str,
    ) -> list[ndi_document]:
        """Deal a two-parameter response set into one curve per fixed value.

        MATLAB equivalent: ``tuning_response/make_1d_tuning``.

        A set that varied orientation at several spatial frequencies becomes
        one orientation curve per spatial frequency. Blank stimuli are left
        out: they carry neither parameter and belong to every curve as the
        control, not to one of them as a point.

        Returns:
            One ``stimulus_tuningcurve`` document per value of PARAM_TO_FIX.

        Raises:
            RuntimeError: when the presentation document cannot be found.
        """
        from ...query import ndi_query

        if self._session is None:
            raise RuntimeError("make_1d_tuning requires a session.")

        presentation_id = stim_response_doc.dependency_value(
            "stimulus_presentation_id", error_if_not_found=False
        )
        presentation_docs = self._session.database_search(
            ndi_query("base.id", "exact_string", presentation_id or "", "")
        )
        if not presentation_docs:
            raise RuntimeError("Could not find the stimulus presentation doc for this response.")
        stimuli = (
            presentation_docs[0].document_properties.get("stimulus_presentation", {}) or {}
        ).get("stimuli", []) or []

        fixed_values: list[float] = []
        for stimulus in stimuli:
            stimulus_parameters = stimulus.get("parameters", {}) or {}
            if stimulus_parameters.get("isblank"):
                continue
            if param_to_fix in stimulus_parameters and param_to_vary in stimulus_parameters:
                fixed_values.append(stimulus_parameters[param_to_fix])

        tuning_docs: list[ndi_document] = []
        for value in sorted(set(fixed_values)):
            doc = self.tuning_curve(
                stim_response_doc,
                independent_parameter=[param_to_vary],
                independent_label=[param_to_vary_label],
                constraint=[
                    {
                        "field": param_to_fix,
                        "operation": "exact_number",
                        "param1": value,
                        "param2": "",
                    }
                ],
            )
            if doc is not None:
                tuning_docs.append(doc)
        return tuning_docs

    def find_tuningcurve_document(
        self,
        ndi_element_obj: Any,
        epochid: str,
        response_type: str = "mean",
    ) -> tuple[list[ndi_document], list[ndi_document]]:
        """The tuning curves of an element for one epoch and response type.

        MATLAB equivalent: ``tuning_response/find_tuningcurve_document``.

        Both filters matter and both are applied: an element usually has a
        mean curve AND an F1 curve for every epoch it was recorded in, so a
        search that returned all of them would leave the caller to pick, and
        the wrong pick is a plausible-looking wrong answer rather than an
        error.

        Returns:
            ``(tuning_curve_docs, stimulus_response_scalar_docs)``, aligned:
            entry i of the second is the response the curve at i came from.
        """
        if self._session is None:
            return [], []

        from ...query import ndi_query

        session = self._session
        curves = session.database_search(
            session.searchquery()
            & ndi_query("").isa("stimulus_tuningcurve")
            & ndi_query("").depends_on("element_id", identifier(ndi_element_obj))
        )

        tuning_docs: list[ndi_document] = []
        response_docs: list[ndi_document] = []
        for curve in curves:
            response_id = curve.dependency_value(
                "stimulus_response_scalar_id", error_if_not_found=False
            )
            if not response_id:
                continue
            for response in session.database_search(
                ndi_query("base.id", "exact_string", response_id, "")
            ):
                properties = response.document_properties
                scalar = properties.get("stimulus_response_scalar", {}) or {}
                stimulus_response = properties.get("stimulus_response", {}) or {}
                if str(scalar.get("response_type", "")).lower() != str(response_type).lower():
                    continue
                if (
                    str(stimulus_response.get("element_epochid", "")).lower()
                    != str(epochid).lower()
                ):
                    continue
                tuning_docs.append(curve)
                response_docs.append(response)
        return tuning_docs, response_docs

    # ------------------------------------------------------------------
    # control stimuli
    # ------------------------------------------------------------------
    def label_control_stimuli(
        self,
        stimulus_element_obj: Any,
        reset: bool = False,
        **kwargs: Any,
    ) -> list[ndi_document]:
        """Label the control stimulus of every presentation of a stimulator.

        MATLAB equivalent: ``tuning_response/label_control_stimuli``.

        Responses cannot be computed until this has run: a response is stored
        with the control it is to be compared against, and that pairing is
        what this writes.

        Args:
            stimulus_element_obj: the stimulator element.
            reset: remove the existing labels first.
            **kwargs: passed to :meth:`control_stimulus`.

        Returns:
            The ``control_stimulus_ids`` documents written.

        Raises:
            RuntimeError: when the app has no session to write to. An empty
                list would say "this element has no presentations", which is
                a different thing from "there is nowhere to look".
        """
        if self._session is None:
            raise RuntimeError("No session configured")

        from ...query import ndi_query

        session = self._session
        stim_docs = session.database_search(
            ndi_query("").isa("stimulus_presentation")
            & ndi_query("").depends_on("stimulus_element_id", identifier(stimulus_element_obj))
        )

        if reset:
            for stim_doc in stim_docs:
                old = session.database_search(
                    ndi_query("").isa("control_stimulus_ids")
                    & ndi_query("").depends_on("stimulus_presentation_id", stim_doc.id)
                )
                if old:
                    session.database_rm(old)

        control_docs: list[ndi_document] = []
        for stim_doc in stim_docs:
            _, control_doc = self.control_stimulus(stim_doc, **kwargs)
            if control_doc is not None:
                control_docs.append(control_doc)
        return control_docs

    def control_stimulus(
        self,
        stim_doc: ndi_document,
        control_stim_method: str = "pseudorandom",
        controlid: str = "isblank",
        controlid_value: Any = 1,
    ) -> tuple[list[float], ndi_document | None]:
        """
        Name the control trial for each trial of one stimulus presentation.

        MATLAB equivalent: ndi.app.stimulus.tuning_response/control_stimulus

        Returns ``(cs_ids, cs_doc)``. ``cs_ids`` has one entry per trial in
        the presentation: the 1-BASED trial index of the control trial that
        trial should be compared against, or NaN when the presentation has
        no control stimulus at all. ``cs_doc`` is the
        ``control_stimulus_ids`` document holding them, which is added to
        the database.

        HOW THE CONTROL TRIAL IS CHOSEN
        First the control STIMULUS is identified among the distinct stimuli,
        by ``control_stim_method``:

        * ``pseudorandom`` -- the stimulus whose parameters have
          ``controlid`` equal to ``controlid_value`` (by default
          ``isblank == 1``);
        * ``hasfield`` -- the stimulus whose parameters merely HAVE a
          ``controlid`` field, whatever its value.

        Then each trial is matched to one presentation of it. When the
        presentation order is regular -- every stimulus shown once per
        repetition -- the control trial of the same repetition is used, so
        the comparison is local in time. When it is not, the control trial
        CLOSEST IN TIME is used instead, which is the best available
        approximation of the same thing.

        Args:
            stim_doc: A stimulus_presentation document.
            control_stim_method: ``'pseudorandom'`` or ``'hasfield'``.
            controlid: The parameter that marks a control stimulus.
            controlid_value: The value of that parameter that marks it, for
                ``pseudorandom``.

        Raises:
            ValueError: for an unknown method, or when more than one
                stimulus looks like the control -- MATLAB errors there too,
                because which of them a trial belongs to is genuinely
                undecidable rather than merely awkward.
        """
        if self._session is None:
            raise RuntimeError("No session configured")

        method = str(control_stim_method).lower()
        if method not in ("pseudorandom", "hasfield"):
            raise ValueError(f"Unknown control_stim_method {control_stim_method}.")

        from ...document import ndi_document
        from .decoder import ndi_app_stimulus_decoder

        presentation = _presentation_properties(stim_doc)
        stimuli = presentation.get("stimuli", []) or []
        stimids = np.asarray(presentation.get("presentation_order", []), dtype=float).ravel()

        control_stim_ids = _control_stimulus_indexes(stimuli, method, controlid, controlid_value)
        if len(control_stim_ids) > 1:
            raise ValueError("Do not know what to do with more than one control stimulus type.")

        if control_stim_ids:
            presentation_time = ndi_app_stimulus_decoder(self._session).load_presentation_time(
                stim_doc
            )
            cs_ids = _match_trials_to_controls(
                stimids, len(stimuli), control_stim_ids[0], presentation_time
            )
        else:
            # No control stimulus in this set. NaN per trial, not an error:
            # a run with no blank is a legitimate experiment, it simply
            # cannot be baselined.
            cs_ids = [float("nan")] * int(stimids.size)

        method_struct = {
            "method": method,
            "controlid": controlid,
            "controlid_value": controlid_value,
        }
        cs_doc = ndi_document(
            "control_stimulus_ids",
            **{
                "control_stimulus_ids": {
                    "control_stimulus_ids": list(cs_ids),
                    "control_stimulus_id_method": method_struct,
                }
            },
        )
        cs_doc = cs_doc + self.newdocument()
        cs_doc = cs_doc.set_dependency_value("stimulus_presentation_id", identifier(stim_doc))
        self._session.database_add(cs_doc)
        return list(cs_ids), cs_doc

    # ------------------------------------------------------------------
    # statics
    # ------------------------------------------------------------------
    @staticmethod
    def tuningcurvedoc2vhlabrespstruct(tuning_doc: ndi_document) -> dict[str, Any]:
        """A tuning curve as the VH lab response structure.

        MATLAB equivalent: ``tuning_response.tuningcurvedoc2vhlabrespstruct``.

        The shape the VH lab analysis libraries take: a 4-row ``curve`` of
        [value; mean; stddev; stderr] with the control already subtracted,
        the individual responses beside it, and the control responses as
        ``spont``/``blankresp``.

        Returns:
            A dict with ``curve``, ``ind``, ``spont``, ``spontind``,
            ``blankresp`` and ``blankind``.
        """
        from vlt.stats.stderr import stderr

        curve_properties = tuning_doc.document_properties.get("stimulus_tuningcurve", {}) or {}
        individual_real = _rows(curve_properties.get("individual_responses_real", []))
        individual_imaginary = _rows(curve_properties.get("individual_responses_imaginary", []))
        control_real = _rows(curve_properties.get("control_individual_responses_real", []))
        control_imaginary = _rows(
            curve_properties.get("control_individual_responses_imaginary", [])
        )

        individual: list[np.ndarray] = []
        control_individual: list[np.ndarray] = []
        response_individual: list[np.ndarray] = []
        response_mean: list[float] = []
        response_stddev: list[float] = []
        response_stderr: list[float] = []

        for i in range(len(individual_real)):
            values = np.asarray(individual_real[i], dtype=float) + 1j * np.asarray(
                individual_imaginary[i], dtype=float
            )
            controls = np.asarray(control_real[i], dtype=float) + 1j * np.asarray(
                control_imaginary[i], dtype=float
            )
            individual.append(_real_or_magnitude(values))
            control_individual.append(_real_or_magnitude(controls))
            difference = values - controls
            response_mean.append(_mean_magnitude(difference))
            response_stddev.append(_nanstd(difference))
            response_stderr.append(_nanstderr(difference))
            response_individual.append(_real_or_magnitude(difference))

        blank = control_individual[0] if control_individual else np.asarray([])
        blank_flat = np.asarray(blank, dtype=float).ravel()
        blank_response = (
            [float(np.mean(blank_flat)), float(np.std(blank_flat)), float(stderr(blank_flat))]
            if blank_flat.size
            else [float("nan")] * 3
        )

        values = np.asarray(curve_properties.get("independent_variable_value", []), dtype=float)
        if values.ndim > 1 and values.shape[1] > 1:
            # Multi-variate: no single axis to plot against, so the points are
            # numbered instead -- 1-based, being an axis a person reads.
            axis = np.arange(1, len(response_mean) + 1, dtype=float)
        else:
            axis = values.ravel().astype(float)

        return {
            "curve": np.vstack(
                [
                    axis,
                    np.asarray(response_mean, dtype=float),
                    np.asarray(response_stddev, dtype=float),
                    np.asarray(response_stderr, dtype=float),
                ]
            ),
            "ind": response_individual,
            "blankind": blank,
            "spontind": blank,
            "blankresp": blank_response,
            "spont": blank_response,
        }

    @staticmethod
    def tuningdoc_fixcellarrays_static(tc_doc: ndi_document) -> ndi_document:
        """Ensure the per-point response fields are lists of lists.

        MATLAB equivalent: ``tuning_response.tuningdoc_fixcellarrays_static``,
        and MOSTLY UNNECESSARY HERE. MATLAB needs it because a cell array
        whose entries are all the same length comes back from JSON as a
        matrix, and a cell array of scalars as a vector, so the field's type
        depends on the data in it. Python's lists survive the round trip.

        What remains is the one case that is genuinely ambiguous in the
        stored JSON: a curve with one repetition per point, whose rows may
        have been written as bare numbers. Those are wrapped, so a caller can
        always index ``[point][repetition]``.
        """
        properties = tc_doc.document_properties.get("stimulus_tuningcurve", {}) or {}
        for field in (
            "individual_responses_real",
            "individual_responses_imaginary",
            "control_individual_responses_real",
            "control_individual_responses_imaginary",
            "stimulus_presentation_number",
        ):
            if field in properties:
                properties[field] = _rows(properties[field])
        return tc_doc

    @staticmethod
    def modulated_or_mean(
        stimulus_response_scalar_docs: list[ndi_document],
        *,
        modulated_response_names: tuple[str, ...] = MODULATED_RESPONSE_NAMES,
        mean_response_names: tuple[str, ...] = MEAN_RESPONSE_NAMES,
    ) -> tuple[int, float, float, float, int | None, int | None]:
        """Is this element's response stronger in modulation or in mean?

        MATLAB equivalent: ``tuning_response.modulated_or_mean``.

        The simple/complex distinction, decided empirically rather than by
        fitting: for the stimulus that drove the element hardest, compare the
        F1 response against the F0 response, both with their control
        subtracted.

        Returns:
            ``(b, ratio, meanresponse, modulatedresponse, mean_index,
            modulated_index)``. B is 1 when the modulated response is
            greater, 0 when the mean is, and -1 when there is no basis to
            compare -- the documents given do not include both kinds.

        Raises:
            TypeError: when the argument is not a list of documents.
            ValueError: when a document is not a stimulus response, or when
                two of them claim the same kind of response.
        """
        if not isinstance(stimulus_response_scalar_docs, (list, tuple)):
            raise TypeError("stimulus_response_scalar_docs should be a list of documents.")

        response_types: list[str] = []
        for doc in stimulus_response_scalar_docs:
            scalar = (getattr(doc, "document_properties", {}) or {}).get("stimulus_response_scalar")
            if not scalar:
                raise ValueError(
                    "stimulus_response_scalar_docs must be documents of type "
                    "'stimulus_response_scalar'."
                )
            response_types.append(str(scalar.get("response_type", "")))

        lowered_mean = {name.lower() for name in mean_response_names}
        lowered_modulated = {name.lower() for name in modulated_response_names}
        mean_indexes = [i for i, t in enumerate(response_types) if t.lower() in lowered_mean]
        modulated_indexes = [
            i for i, t in enumerate(response_types) if t.lower() in lowered_modulated
        ]

        if not mean_indexes or not modulated_indexes:
            return -1, float("nan"), float("nan"), float("nan"), None, None
        if len(mean_indexes) > 1:
            raise ValueError("More than one mean response; do not know which to use.")
        if len(modulated_indexes) > 1:
            raise ValueError("More than one modulated response; do not know which to use.")

        mean_index, modulated_index = mean_indexes[0], modulated_indexes[0]
        mean_responses = _responses_by_stimulus(stimulus_response_scalar_docs[mean_index])
        modulated_responses = _responses_by_stimulus(stimulus_response_scalar_docs[modulated_index])
        if not mean_responses:
            return -1, float("nan"), float("nan"), float("nan"), mean_index, modulated_index

        stimulus_ids = sorted(mean_responses)
        mean_values = np.asarray([mean_responses[s] for s in stimulus_ids], dtype=float)
        modulated_values = np.asarray(
            [modulated_responses.get(s, float("nan")) for s in stimulus_ids], dtype=float
        )

        biggest_modulated = int(np.nanargmax(modulated_values))
        biggest_mean = int(np.nanargmax(mean_values))
        is_modulated = int(modulated_values[biggest_modulated] > mean_values[biggest_mean])

        if is_modulated:
            modulated_response = float(modulated_values[biggest_modulated])
            mean_response = float(mean_values[biggest_modulated])
        else:
            modulated_response = float(modulated_values[biggest_mean])
            mean_response = float(mean_values[biggest_mean])

        ratio = modulated_response / mean_response if mean_response else float("nan")
        return (
            is_modulated,
            ratio,
            mean_response,
            modulated_response,
            mean_index,
            modulated_index,
        )

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    def _new_document(self, document_type: str) -> ndi_document:
        """A new document of DOCUMENT_TYPE, stamped with this session."""
        from ...document import ndi_document

        doc = ndi_document(document_type)
        if self._session is not None:
            doc = doc.set_session_id(self._session.id())
        return doc

    @staticmethod
    def _epochid(doc: ndi_document) -> str:
        return str((doc.document_properties.get("epochid", {}) or {}).get("epochid", ""))

    def _parameter_document(
        self,
        temporalfreqfunc: str,
        freq_response: Any,
        prestimulus_time: Any,
        prestimulus_normalization: Any,
        isspike: bool,
        spiketrain_dt: float,
    ) -> ndi_document:
        """The parameter document for these settings, reused or created.

        Reused rather than written per response: the parameters are what make
        two responses comparable, so responses computed the same way must
        point at the SAME document, not at equal copies of one.
        """
        from ...query import ndi_query

        session = self._session
        assert session is not None
        parameters = {
            "temporalfreqfunc": temporalfreqfunc,
            "freq_response": freq_response,
            "prestimulus_time": prestimulus_time,
            "prestimulus_normalization": prestimulus_normalization,
            "isspike": int(bool(isspike)),
            "spiketrain_dt": spiketrain_dt,
        }

        query = session.searchquery() & ndi_query("").isa(
            "stimulus_response_scalar_parameters_basic"
        )
        for field, value in parameters.items():
            if value is None:
                continue
            operation = "exact_string" if isinstance(value, str) else "exact_number"
            query = query & ndi_query(
                f"stimulus_response_scalar_parameters_basic.{field}", operation, value, ""
            )
        existing = session.database_search(query)
        if existing:
            return existing[0]

        doc = self._new_document("stimulus_response_scalar_parameters_basic")
        doc.document_properties["stimulus_response_scalar_parameters_basic"] = parameters
        session.database_add(doc)
        return doc

    def _remove_responses(self, ndi_element_stim: Any, ndi_timeseries_obj: Any) -> None:
        """Remove this pair's responses and their parameter documents."""
        from ...query import ndi_query

        session = self._session
        assert session is not None
        docs = session.database_search(
            ndi_query("").isa("stimulus_response_scalar")
            & session.searchquery()
            & ndi_query("").depends_on("stimulator_id", identifier(ndi_element_stim))
            & ndi_query("").depends_on("element_id", identifier(ndi_timeseries_obj))
        )
        if not docs:
            return
        parameter_docs: list[ndi_document] = []
        for doc in docs:
            parameter_id = doc.dependency_value(
                "stimulus_response_scalar_parameters_id", error_if_not_found=False
            )
            if parameter_id:
                parameter_docs.extend(
                    session.database_search(ndi_query("base.id", "exact_string", parameter_id, ""))
                )
        session.database_rm(docs)
        if parameter_docs:
            session.database_rm(parameter_docs)

    def _remove_matching_responses(
        self,
        ndi_timeseries_obj: Any,
        stim_doc: ndi_document,
        control_doc: ndi_document | None,
        param_doc: ndi_document,
    ) -> None:
        """Remove the response for exactly this element/stimulus/parameters."""
        from ...query import ndi_query

        session = self._session
        assert session is not None
        query = (
            session.searchquery()
            & ndi_query("").isa("stimulus_response_scalar")
            & ndi_query("").depends_on("element_id", identifier(ndi_timeseries_obj))
            & ndi_query("").depends_on("stimulus_presentation_id", stim_doc.id)
            & ndi_query("").depends_on("stimulus_response_scalar_parameters_id", param_doc.id)
        )
        if control_doc is not None:
            query = query & ndi_query("").depends_on("stimulus_control_id", control_doc.id)
        docs = session.database_search(query)
        if docs:
            session.database_rm(docs)

    def __repr__(self) -> str:
        return f"ndi_app_stimulus_tuning__response(session={self._session is not None})"


# ----------------------------------------------------------------------
# small shared helpers
# ----------------------------------------------------------------------
def _as_list(value: Any) -> list[Any]:
    """VALUE as a list. A bare string or dict is one item, not a sequence."""
    if value is None:
        return []
    if isinstance(value, (str, dict)):
        return [value]
    if isinstance(value, (list, tuple, np.ndarray)):
        return list(value)
    return [value]


def _rows(value: Any) -> list[list[Any]]:
    """VALUE as a list of rows, wrapping a row of bare scalars."""
    if value is None:
        return []
    rows = []
    for entry in value:
        if isinstance(entry, (list, tuple, np.ndarray)):
            rows.append(list(entry))
        else:
            rows.append([entry])
    return rows


def _empty_curve(
    num_points: int, labels: list[Any], unique_values: np.ndarray, response_units: str
) -> dict[str, Any]:
    """A tuning curve with every field sized and nothing filled in yet.

    The fields, and their order, are MATLAB's ``vlt.data.emptystruct`` call:
    the schema is shared between the two ports, so a curve written here is
    read there. Per-point fields start as NaN rather than 0 -- a point the
    loop never reaches has no response, and 0 is a response.
    """
    labels_joined = ",".join(str(label) for label in labels)
    return {
        "independent_variable_label": [labels_joined],
        "independent_variable_value": unique_values.tolist(),
        "stimid": [float("nan")] * num_points,
        "response_mean": [float("nan")] * num_points,
        "response_stddev": [float("nan")] * num_points,
        "response_stderr": [float("nan")] * num_points,
        "individual_responses_real": [[] for _ in range(num_points)],
        "individual_responses_imaginary": [[] for _ in range(num_points)],
        "stimulus_presentation_number": [[] for _ in range(num_points)],
        "control_stimid": [float("nan")] * num_points,
        "control_response_mean": [float("nan")] * num_points,
        "control_response_stddev": [float("nan")] * num_points,
        "control_response_stderr": [float("nan")] * num_points,
        "control_individual_responses_real": [[] for _ in range(num_points)],
        "control_individual_responses_imaginary": [[] for _ in range(num_points)],
        "response_units": response_units,
    }


def _unique_rows(values: np.ndarray) -> np.ndarray:
    """The unique rows of VALUES, sorted -- MATLAB's unique(...,'rows')."""
    if values.size == 0:
        return values.reshape(0, values.shape[1] if values.ndim > 1 else 1)
    return np.unique(np.atleast_2d(values), axis=0)


def _mean_magnitude(values: np.ndarray) -> float:
    """The mean, as a magnitude when it is complex. See tuning_curve."""
    if values.size == 0 or np.all(np.isnan(values)):
        return float("nan")
    mean = np.nanmean(values)
    return float(np.abs(mean)) if np.iscomplexobj(values) and mean.imag != 0 else float(mean.real)


def _nanstderr(values: np.ndarray) -> float:
    """``vlt.data.nanstderr``, without the warning for a single repetition.

    One repetition per point is a real experimental design, and its standard
    error is legitimately NaN. NumPy says so with a "Degrees of freedom <= 0"
    RuntimeWarning per point, which for a 16-point curve is 16 lines of
    scrollback telling the user something the NaN already tells them.
    """
    from vlt.data.nanstderr import nanstderr

    values = np.asarray(values)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        if values.size == 0:
            return float("nan")
        return float(nanstderr(values))


def _nanstd(values: np.ndarray) -> float:
    """MATLAB's nanstd: the sample standard deviation, NaNs dropped."""
    finite = values[~np.isnan(values)]
    if finite.size < 2:
        return float("nan") if finite.size == 0 else 0.0
    return float(np.std(finite, ddof=1))


def _real_or_magnitude(values: np.ndarray) -> np.ndarray:
    """VALUES as reals, taking magnitudes if any of them is complex."""
    values = np.asarray(values)
    if np.iscomplexobj(values) and np.any(values.imag != 0):
        return np.abs(values)
    return values.real.astype(float)


def _responses_by_stimulus(doc: ndi_document) -> dict[int, float]:
    """Mean control-subtracted response per stimulus id, for modulated_or_mean."""
    responses = (doc.document_properties.get("stimulus_response_scalar", {}) or {}).get(
        "responses", {}
    ) or {}
    stimid = np.asarray(responses.get("stimid", []))
    if stimid.size == 0:
        return {}
    real = np.asarray(responses.get("response_real", []), dtype=float)
    imaginary = np.asarray(responses.get("response_imaginary", []), dtype=float)
    control_real = np.asarray(responses.get("control_response_real", []), dtype=float)
    control_imaginary = np.asarray(responses.get("control_response_imaginary", []), dtype=float)
    values = (real + 1j * imaginary) - (control_real + 1j * control_imaginary)

    out: dict[int, float] = {}
    for stimulus in np.unique(stimid):
        where = np.where(stimid == stimulus)[0]
        mean = np.nanmean(values[where]) if where.size else complex("nan")
        # MATLAB keeps the real part when the imaginary part is negligible,
        # and the magnitude otherwise; 1e-6 is its threshold.
        out[int(stimulus)] = float(np.abs(mean)) if abs(mean.imag) > 1e-6 else float(mean.real)
    return out


def _presentation_properties(stim_doc: Any) -> dict[str, Any]:
    """The ``stimulus_presentation`` block of a document, or an empty one."""
    props = getattr(stim_doc, "document_properties", None) or {}
    return props.get("stimulus_presentation", {}) or {}


def _stimulus_parameters(stimulus: Any) -> dict[str, Any]:
    """One stimulus's parameter dict, however the document nests it."""
    if isinstance(stimulus, dict):
        parameters = stimulus.get("parameters", stimulus)
        return parameters if isinstance(parameters, dict) else {}
    parameters = getattr(stimulus, "parameters", None)
    return parameters if isinstance(parameters, dict) else {}


def _control_stimulus_indexes(
    stimuli: Any,
    method: str,
    controlid: str,
    controlid_value: Any,
) -> list[int]:
    """The 1-based indexes of the stimuli that count as controls.

    ``vlt.data.fieldsearch`` does the matching, as MATLAB's does, so
    ``exact_number`` and ``hasfield`` mean the same thing on both sides.
    """
    from vlt.data import fieldsearch

    if method == "pseudorandom":
        search = {
            "field": controlid,
            "operation": "exact_number",
            "param1": controlid_value,
            "param2": [],
        }
    else:  # hasfield
        search = {"field": controlid, "operation": "hasfield", "param1": [], "param2": []}

    found: list[int] = []
    for index, stimulus in enumerate(stimuli):
        try:
            matched = bool(fieldsearch(_stimulus_parameters(stimulus), search))
        except Exception:  # noqa: BLE001 - a stimulus that cannot be searched is not a control
            matched = False
        if matched:
            found.append(index + 1)  # 1-based, as the presentation order is
    return found


def _match_trials_to_controls(
    stimids: np.ndarray,
    num_stimuli: int,
    control_stim_id: int,
    presentation_time: list[dict[str, Any]],
) -> list[float]:
    """One control TRIAL index per trial, both 1-based.

    Regular presentation order -- every stimulus once per repetition -- lets
    each trial take the control of its own repetition, which is the local
    comparison a drifting preparation needs. Irregular order falls back to
    the control trial closest in time.
    """
    from vlt.data import findclosest
    from vlt.neuro.stimulus import stimids2reps

    trial_count = int(stimids.size)
    control_trials = [i + 1 for i in range(trial_count) if stimids[i] == control_stim_id]
    if not control_trials:
        return [float("nan")] * trial_count

    reps, is_regular = _stimids2reps(stimids2reps, stimids, num_stimuli)

    if is_regular and reps is not None and len(reps) == trial_count:
        trials = list(control_trials)
        if len({int(r) for r in reps}) > len(trials):
            # A final, incomplete repetition has no control of its own; the
            # previous one stands in, as MATLAB lets it.
            trials.append(trials[-1])
        out: list[float] = []
        for rep in reps:
            index = int(rep) - 1
            out.append(float(trials[index]) if 0 <= index < len(trials) else float("nan"))
        return out

    onsets = [float(entry.get("onset", float("nan"))) for entry in presentation_time]
    if len(onsets) < trial_count:
        # Without a time for every trial there is no "closest in time" to
        # find; report unknown rather than guess a neighbour.
        return [float("nan")] * trial_count

    control_onsets = [onsets[t - 1] for t in control_trials]
    out = []
    for trial in range(trial_count):
        nearest = int(findclosest(control_onsets, onsets[trial])[0])
        out.append(float(control_trials[nearest]))
    return out


def _stimids2reps(stimids2reps: Any, stimids: np.ndarray, num_stimuli: int):
    """Call vlt's stimids2reps, tolerating either return shape.

    It answers "which repetition is each trial in, and is the order
    regular?". A version that returns only the repetitions is read as
    irregular, which costs the local comparison but never mismatches a
    control.
    """
    try:
        result = stimids2reps(stimids, num_stimuli)
    except Exception:  # noqa: BLE001 - an order it cannot read is not regular
        return None, False
    if isinstance(result, tuple):
        reps = result[0]
        is_regular = bool(result[1]) if len(result) > 1 else False
    else:
        reps, is_regular = result, False
    if reps is None:
        return None, False
    return np.asarray(reps).ravel(), is_regular
