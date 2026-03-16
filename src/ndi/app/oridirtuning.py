"""
ndi.app.oridirtuning - Orientation/direction tuning analysis.

Computes orientation and direction selectivity indices from
stimulus tuning curves.

MATLAB equivalent: src/ndi/+ndi/+app/oridirtuning.m
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import ndi_app
from .appdoc import ndi_app_appdoc

if TYPE_CHECKING:
    from ..document import ndi_document
    from ..session.session_base import ndi_session


class ndi_app_oridirtuning(ndi_app, ndi_app_appdoc):
    """
    ndi_app for orientation/direction tuning analysis.

    Computes orientation and direction selectivity measures from
    stimulus tuning curves, including:
    - Circular variance
    - Direction selectivity index
    - Orientation selectivity index
    - Von Mises fit parameters

    Doc types:
        - orientation_direction_tuning: Computed tuning properties
        - tuning_curve: Stimulus tuning curves

    Example:
        >>> odt = ndi_app_oridirtuning(session)
        >>> odt.calculate_all_tuning_curves(element_obj)
        >>> odt.calculate_all_oridir_indexes(element_obj)
    """

    def __init__(self, session: ndi_session | None = None):
        ndi_app.__init__(self, session=session, name="ndi_app_oridirtuning")
        ndi_app_appdoc.__init__(
            self,
            doc_types=["orientation_direction_tuning", "tuning_curve"],
            doc_document_types=[
                "apps/oridirtuning/orientation_direction_tuning",
                "apps/oridirtuning/tuning_curve",
            ],
        )

    def calculate_all_tuning_curves(
        self,
        ndi_element_obj: Any,
        docexistsaction: str = "Replace",
    ) -> list[ndi_document]:
        """
        Calculate tuning curves for all stimulus responses.

        MATLAB equivalent: ndi.app.oridirtuning/calculate_all_tuning_curves

        Args:
            ndi_element_obj: Neural element
            docexistsaction: What to do if docs exist

        Returns:
            List of tuning curve documents
        """
        raise NotImplementedError("Full tuning curve calculation requires stimulus response data.")

    def calculate_tuning_curve(
        self,
        ndi_element_obj: Any,
        ndi_response_doc: ndi_document,
        do_add: bool = True,
    ) -> ndi_document | None:
        """
        Calculate a single tuning curve from a response document.

        MATLAB equivalent: ndi.app.oridirtuning/calculate_tuning_curve

        Args:
            ndi_element_obj: Neural element
            ndi_response_doc: Stimulus response document
            do_add: If True, add to database

        Returns:
            Tuning curve document, or None
        """
        raise NotImplementedError(
            "Single tuning curve calculation requires response data analysis."
        )

    def calculate_all_oridir_indexes(
        self,
        ndi_element_obj: Any,
        docexistsaction: str = "Replace",
    ) -> list[ndi_document]:
        """
        Calculate orientation/direction indices for all responses.

        MATLAB equivalent: ndi.app.oridirtuning/calculate_all_oridir_indexes

        Args:
            ndi_element_obj: Neural element
            docexistsaction: What to do if docs exist

        Returns:
            List of orientation_direction_tuning documents
        """
        raise NotImplementedError("Full index calculation requires circular statistics (numpy).")

    def calculate_oridir_indexes(
        self,
        tuning_doc: ndi_document,
        do_add: bool = True,
        do_plot: bool = False,
    ) -> ndi_document | None:
        """
        Calculate orientation/direction indices from a tuning curve.

        MATLAB equivalent: ndi.app.oridirtuning/calculate_oridir_indexes

        Args:
            tuning_doc: Tuning curve document
            do_add: If True, add to database
            do_plot: If True, plot results (not applicable in Python)

        Returns:
            Orientation/direction tuning document, or None
        """
        raise NotImplementedError("Index calculation requires circular statistics.")

    @staticmethod
    def is_oridir_stimulus_response(response_doc: ndi_document) -> bool:
        """
        Check if a response document contains orientation/direction data.

        MATLAB equivalent: ndi.app.oridirtuning/is_oridir_stimulus_response

        Args:
            response_doc: stimulus_response_scalar document

        Returns:
            True if the stimulus varies in angle
        """
        props = getattr(response_doc, "document_properties", response_doc)
        try:
            indep = props.stimulus_tuningcurve.independent_variable_label
            return indep.lower() in ("angle", "direction", "orientation")
        except AttributeError:
            return False

    def plot_oridir_response(self, oriprops_doc: ndi_document) -> None:
        """
        Plot orientation/direction response.

        MATLAB equivalent: ndi.app.oridirtuning/plot_oridir_response

        Args:
            oriprops_doc: Orientation/direction tuning document

        Python-specific Notes:
            Not applicable in Python without GUI. Use matplotlib
            directly for plotting.
        """
        raise NotImplementedError("Plotting requires matplotlib. Use matplotlib directly.")

    def struct2doc(self, appdoc_type: str, appdoc_struct: dict, **kwargs) -> ndi_document:
        from ..document import ndi_document

        return ndi_document(
            self.doc_document_types[self.doc_types.index(appdoc_type)],
            **{appdoc_type: appdoc_struct},
        )

    def find_appdoc(self, appdoc_type: str, **kwargs) -> list[ndi_document]:
        if self._session is None:
            return []
        from ..query import ndi_query

        return self._session.database_search(ndi_query("").isa(appdoc_type))

    def isvalid_appdoc_struct(self, appdoc_type: str, appdoc_struct: dict) -> tuple[bool, str]:
        """
        Validate an appdoc struct.

        MATLAB equivalent: ndi.app.oridirtuning/isvalid_appdoc_struct

        Returns:
            Tuple of (is_valid, error_message)
        """
        return True, ""

    def __repr__(self) -> str:
        return f"ndi_app_oridirtuning(session={self._session is not None})"
