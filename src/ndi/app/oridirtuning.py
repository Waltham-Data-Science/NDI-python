"""
ndi.app.oridirtuning - Orientation/direction tuning analysis.

Computes orientation and direction selectivity indices from
stimulus tuning curves.

MATLAB equivalent: src/ndi/+ndi/+app/oridirtuning.m
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from . import App
from .appdoc import AppDoc

if TYPE_CHECKING:
    from ..document import Document
    from ..session.session_base import Session


class OriDirTuning(App, AppDoc):
    """
    App for orientation/direction tuning analysis.

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
        >>> odt = OriDirTuning(session)
        >>> odt.calculate_all_tuning_curves(element_obj)
        >>> odt.calculate_all_oridir_indexes(element_obj)
    """

    def __init__(self, session: Optional['Session'] = None):
        App.__init__(self, session=session, name='ndi_app_oridirtuning')
        AppDoc.__init__(
            self,
            doc_types=['orientation_direction_tuning', 'tuning_curve'],
            doc_document_types=[
                'apps/oridirtuning/orientation_direction_tuning',
                'apps/oridirtuning/tuning_curve',
            ],
        )

    def calculate_all_tuning_curves(
        self,
        element_obj: Any,
        docexistsaction: str = 'Replace',
    ) -> List['Document']:
        """
        Calculate tuning curves for all stimulus responses.

        Args:
            element_obj: Neural element
            docexistsaction: What to do if docs exist

        Returns:
            List of tuning curve documents
        """
        raise NotImplementedError(
            "Full tuning curve calculation requires stimulus response data."
        )

    def calculate_all_oridir_indexes(
        self,
        element_obj: Any,
        docexistsaction: str = 'Replace',
    ) -> List['Document']:
        """
        Calculate orientation/direction indices for all responses.

        Args:
            element_obj: Neural element
            docexistsaction: What to do if docs exist

        Returns:
            List of orientation_direction_tuning documents
        """
        raise NotImplementedError(
            "Full index calculation requires circular statistics (numpy)."
        )

    @staticmethod
    def is_oridir_stimulus_response(response_doc: 'Document') -> bool:
        """
        Check if a response document contains orientation/direction data.

        Args:
            response_doc: stimulus_response_scalar document

        Returns:
            True if the stimulus varies in angle
        """
        props = getattr(response_doc, 'document_properties', response_doc)
        # Check if independent variable is angle-like
        try:
            indep = props.stimulus_tuningcurve.independent_variable_label
            return indep.lower() in ('angle', 'direction', 'orientation')
        except AttributeError:
            return False

    def struct2doc(self, appdoc_type: str, appdoc_struct: Dict, **kwargs) -> 'Document':
        from ..document import Document
        return Document(
            self.doc_document_types[self.doc_types.index(appdoc_type)],
            **{appdoc_type: appdoc_struct},
        )

    def find_appdoc(self, appdoc_type: str, **kwargs) -> List['Document']:
        if self._session is None:
            return []
        from ..query import Query
        return self._session.database_search(Query('').isa(appdoc_type))

    def isvalid_appdoc_struct(self, appdoc_type: str, appdoc_struct: Dict) -> bool:
        return True

    def __repr__(self) -> str:
        return f"OriDirTuning(session={self._session is not None})"
