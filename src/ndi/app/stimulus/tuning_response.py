"""
ndi.app.stimulus.tuning_response - Stimulus-response analysis.

Computes scalar responses of neural elements to stimulus presentations
and generates tuning curves.

MATLAB equivalent: src/ndi/+ndi/+app/+stimulus/tuning_response.m
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
    ) -> list[ndi_document]:
        """
        Label control stimuli in a stimulus set.

        MATLAB equivalent: ndi.app.stimulus.tuning_response/label_control_stimuli

        Args:
            stimulus_element_obj: Stimulus element
            reset: Clear existing labels first

        Returns:
            List of control_stimulus_ids documents
        """
        return []

    def control_stimulus(
        self,
        stim_doc: ndi_document,
    ) -> tuple[list[int], ndi_document | None]:
        """
        Determine control stimulus IDs for a stimulus presentation.

        MATLAB equivalent: ndi.app.stimulus.tuning_response/control_stimulus

        Args:
            stim_doc: Stimulus presentation document

        Returns:
            Tuple of (cs_ids, cs_doc) where cs_ids is a list of
            control stimulus indices and cs_doc is the control
            stimulus document.
        """
        raise NotImplementedError("Control stimulus identification requires stimulus analysis.")

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
