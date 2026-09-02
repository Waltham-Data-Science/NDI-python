"""
ndi.app.stimulus.tuning_response - Stimulus-response analysis.

Computes scalar responses of neural elements to stimulus presentations
and generates tuning curves.

MATLAB equivalent: src/ndi/+ndi/+app/+stimulus/tuning_response.m

WHAT A CONTROL STIMULUS IS, AND WHY IT HAS TO BE FOUND PER TRIAL
A tuning measurement is a comparison: the response to a stimulus against
the response to nothing. The "nothing" is the control (blank) stimulus, and
which blank trial a given stimulus trial should be compared against matters,
because a preparation drifts over a recording. So
:meth:`~ndi_app_stimulus_tuning__response.control_stimulus` does not name
one blank for the whole run -- it names one PER TRIAL, taken from the same
pseudorandom repetition where the presentation order is regular, and from
the nearest blank in time where it is not. Getting this wrong does not
raise; it shifts every tuning curve by whatever the preparation drifted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from ...fun.utils import identifier
from .. import ndi_app

if TYPE_CHECKING:
    from ...document import ndi_document
    from ...session.session_base import ndi_session


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

        Args:
            ndi_element_stim: Stimulus element with presentations
            ndi_timeseries_obj: Response timeseries (e.g., neuron)
            reset: Clear existing results first
            do_mean_only: Only compute mean (not frequency components)

        Returns:
            List of stimulus_response_scalar documents
        """
        raise NotImplementedError(
            "Full stimulus response computation requires signal processing. "
            "This class provides the framework structure."
        )

    def compute_stimulus_response_scalar(
        self,
        ndi_stim_obj: Any,
        ndi_timeseries_obj: Any,
        stim_doc: ndi_document,
        control_doc: ndi_document | None = None,
    ) -> ndi_document | None:
        """
        Compute scalar response for a single stimulus presentation.

        MATLAB equivalent: ndi.app.stimulus.tuning_response/compute_stimulus_response_scalar

        Args:
            ndi_stim_obj: Stimulus element
            ndi_timeseries_obj: Response timeseries element
            stim_doc: Stimulus presentation document
            control_doc: Control stimulus document, or None

        Returns:
            stimulus_response_scalar document, or None
        """
        raise NotImplementedError(
            "Stimulus response scalar computation requires signal processing."
        )

    def tuning_curve(
        self,
        stim_response_doc: ndi_document,
        independent_label: str = "angle",
        independent_parameter: str = "angle",
    ) -> ndi_document | None:
        """
        Create a tuning curve from stimulus responses.

        MATLAB equivalent: ndi.app.stimulus.tuning_response/tuning_curve

        Args:
            stim_response_doc: stimulus_response_scalar document
            independent_label: Label for independent variable
            independent_parameter: Parameter name to vary

        Returns:
            stimulus_tuningcurve document, or None
        """
        raise NotImplementedError("Tuning curve generation requires response data analysis.")

    def label_control_stimuli(
        self,
        stimulus_element_obj: Any,
        reset: bool = False,
        **kwargs: Any,
    ) -> list[ndi_document]:
        """
        Label the control stimuli of every stimulus presentation of an element.

        MATLAB equivalent: ndi.app.stimulus.tuning_response/label_control_stimuli

        Finds every ``stimulus_presentation`` document of
        *stimulus_element_obj*, works out which trial is the control for each
        trial in it, and writes one ``control_stimulus_ids`` document per
        presentation INTO THE DATABASE.

        This operates on ALL of the element's presentations -- MATLAB offers
        no per-epoch filter here, and neither does this. That is why
        :class:`ndi.gui.app.stimulusDecoder` enables its button on the
        element having any decoded epoch rather than on a selection.

        Args:
            stimulus_element_obj: Stimulus element or probe.
            reset: Remove the existing control_stimulus_ids documents of
                these presentations before rebuilding them.
            **kwargs: Passed to :meth:`control_stimulus`
                (``control_stim_method``, ``controlid``,
                ``controlid_value``).

        Returns:
            The control_stimulus_ids documents, one per presentation.
        """
        if self._session is None:
            raise RuntimeError("No session configured")

        from ...query import ndi_query

        session = self._session
        element_id = identifier(stimulus_element_obj)

        stim_docs = session.database_search(
            ndi_query("").isa("stimulus_presentation")
            & ndi_query("").depends_on("stimulus_element_id", element_id)
        )

        if reset:
            for doc in stim_docs:
                old = session.database_search(
                    ndi_query("").isa("control_stimulus_ids")
                    & ndi_query("").depends_on("stimulus_presentation_id", identifier(doc))
                )
                if old:
                    session.database_rm(old)

        cs_docs: list[ndi_document] = []
        for doc in stim_docs:
            _cs_ids, cs_doc = self.control_stimulus(doc, **kwargs)
            if cs_doc is not None:
                cs_docs.append(cs_doc)
        return cs_docs

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
            epochid: ndi_epoch_epoch ID
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
        param_to_fix: list[str],
    ) -> list[ndi_document]:
        """
        Create 1D tuning curves from a multi-dimensional parameter space.

        MATLAB equivalent: ndi.app.stimulus.tuning_response/make_1d_tuning

        Args:
            stim_response_doc: stimulus_response_scalar document
            param_to_vary: Parameter name to vary
            param_to_vary_label: Label for the varying parameter
            param_to_fix: List of parameter names to hold fixed

        Returns:
            List of stimulus_tuningcurve documents
        """
        raise NotImplementedError(
            "1D tuning curve extraction requires multi-dimensional response analysis."
        )

    def __repr__(self) -> str:
        return f"ndi_app_stimulus_tuning__response(session={self._session is not None})"


# ----------------------------------------------------------------------
# module helpers: choosing the control trial
# ----------------------------------------------------------------------


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
