"""
ndi.app.stimulus.tuning_response - Stimulus-response analysis.

Computes scalar responses of neural elements to stimulus presentations
and generates tuning curves.

MATLAB equivalent: src/ndi/+ndi/+app/+stimulus/tuning_response.m
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .. import App

if TYPE_CHECKING:
    from ...document import Document
    from ...session.session_base import Session


class TuningResponse(App):
    """
    App for computing stimulus-response relationships.

    Computes scalar response measures (mean firing rate, F1 component, etc.)
    of neural elements to each stimulus in a set, then organizes these
    into tuning curves.

    Example:
        >>> tr = TuningResponse(session)
        >>> docs = tr.stimulus_responses(stim_element, timeseries_obj)
        >>> tuning = tr.tuning_curve(response_doc)
    """

    def __init__(self, session: Session | None = None):
        super().__init__(session=session, name="ndi_app_tuning_response")

    def stimulus_responses(
        self,
        stimulus_element: Any,
        timeseries_obj: Any,
        reset: bool = False,
        do_mean_only: bool = False,
    ) -> list[Document]:
        """
        Compute responses to a stimulus set.

        Args:
            stimulus_element: Stimulus element with presentations
            timeseries_obj: Response timeseries (e.g., neuron)
            reset: Clear existing results first
            do_mean_only: Only compute mean (not frequency components)

        Returns:
            List of stimulus_response_scalar documents
        """
        raise NotImplementedError(
            "Full stimulus response computation requires signal processing. "
            "This class provides the framework structure."
        )

    def tuning_curve(
        self,
        response_doc: Document,
        independent_label: str = "angle",
        independent_parameter: str = "angle",
    ) -> Document | None:
        """
        Create a tuning curve from stimulus responses.

        Args:
            response_doc: stimulus_response_scalar document
            independent_label: Label for independent variable
            independent_parameter: Parameter name to vary

        Returns:
            stimulus_tuningcurve document, or None
        """
        raise NotImplementedError("Tuning curve generation requires response data analysis.")

    def label_control_stimuli(
        self,
        stimulus_element: Any,
        reset: bool = False,
    ) -> list[Document]:
        """
        Label control stimuli in a stimulus set.

        Args:
            stimulus_element: Stimulus element
            reset: Clear existing labels first

        Returns:
            List of control_stimulus_ids documents
        """
        return []

    def find_tuningcurve_document(
        self,
        element_obj: Any,
        epochid: str,
        response_type: str = "mean",
    ) -> list[Document]:
        """
        Find existing tuning curve documents.

        Args:
            element_obj: Neural element
            epochid: Epoch ID
            response_type: Response type (mean, f1, etc.)

        Returns:
            List of matching tuning curve documents
        """
        if self._session is None:
            return []

        from ...query import Query

        q = Query("").isa("stimulus_tuningcurve") & Query("").depends_on(
            "element_id", element_obj.id
        )
        return self._session.database_search(q)

    def __repr__(self) -> str:
        return f"TuningResponse(session={self._session is not None})"
