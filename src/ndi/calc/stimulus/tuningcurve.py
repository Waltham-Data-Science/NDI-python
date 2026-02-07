"""
ndi.calc.stimulus.tuningcurve - Tuning curve calculator.

Computes tuning curves from stimulus_response_scalar documents
using the Calculator pipeline.

MATLAB equivalent: src/ndi/+ndi/+calc/+stimulus/tuningcurve.m
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

import numpy as np

from ...calculator import Calculator
from ...app.appdoc import DocExistsAction

if TYPE_CHECKING:
    from ...document import Document
    from ...session.session_base import Session


class TuningCurveCalc(Calculator):
    """
    Calculator for stimulus tuning curves.

    Takes stimulus_response_scalar documents as input and produces
    tuningcurve_calc documents containing organized tuning curve data.

    Example:
        >>> calc = TuningCurveCalc(session)
        >>> docs = calc.run(DocExistsAction.REPLACE)
    """

    def __init__(self, session: Optional['Session'] = None):
        super().__init__(
            session=session,
            document_type='tuningcurve_calc',
            path_to_doc_type='apps/calculators/tuningcurve_calc',
        )

    def calculate(self, parameters: dict) -> List['Document']:
        """
        Calculate tuning curves from stimulus responses.

        Args:
            parameters: Dict with 'input_parameters', 'depends_on', containing:
                - independent_label: Label for x-axis
                - independent_parameter: Stimulus parameter to vary
                - selection: Criteria for selecting stimuli
                - best_algorithm: How to select 'best' stimulus

        Returns:
            List of tuningcurve_calc documents
        """
        from ...document import Document

        input_params = parameters.get('input_parameters', {})

        tuningcurve_data = {
            'input_parameters': input_params,
            'independent_variable': [],
            'response_mean': [],
            'response_stderr': [],
        }

        doc = Document(
            'apps/calculators/tuningcurve_calc',
            **{'tuningcurve_calc': tuningcurve_data},
        )

        if self._session is not None:
            doc = doc.set_session_id(self._session.id())

        depends_on = parameters.get('depends_on', [])
        if depends_on:
            dep = depends_on[0]
            doc = doc.set_dependency_value(
                dep.get('name', 'document_id'),
                dep.get('value', ''),
            )

        return [doc]

    def default_search_for_input_parameters(self) -> dict:
        """Return default search parameters for tuning curves."""
        from ...query import Query

        return {
            'input_parameters': {
                'independent_label': 'angle',
                'independent_parameter': 'angle',
                'selection': {},
                'best_algorithm': 'empirical',
            },
            'depends_on': [],
            'query': [
                {
                    'name': 'document_id',
                    'query': Query('').isa('stimulus_response_scalar'),
                },
            ],
        }

    # =========================================================================
    # TuningCurve Analysis Methods
    # =========================================================================

    def default_parameters_query(
        self,
        parameters_specification: dict,
    ) -> List[dict]:
        """Return default queries for finding input parameters.

        MATLAB equivalent: tuningcurve.default_parameters_query

        First checks for fixed dependencies via the base class. If none,
        searches for stimulus_response_scalar documents with response_type
        containing 'mean' or 'F1'.

        Args:
            parameters_specification: Current parameter spec.

        Returns:
            List of query spec dicts ``[{name, query}]``.
        """
        from ...query import Query

        q_default = super().default_parameters_query(parameters_specification)
        if q_default:
            return q_default

        q1 = Query('').isa('stimulus_response_scalar')
        q2 = Query.from_search(
            'stimulus_response_scalar.response_type',
            'contains_string', 'mean', '',
        )
        q3 = Query.from_search(
            'stimulus_response_scalar.response_type',
            'contains_string', 'F1', '',
        )
        q_total = q1 & (q2 | q3)

        return [{'name': 'stimulus_response_scalar_id', 'query': q_total}]

    def best_value(
        self,
        algorithm: str,
        stim_response_doc: 'Document',
        prop: str,
    ) -> Tuple[int, float, Any]:
        """Find the stimulus with the "best" response.

        MATLAB equivalent: tuningcurve.best_value

        Args:
            algorithm: Algorithm name (e.g. ``'empirical_maximum'``).
            stim_response_doc: A stimulus_response_scalar Document.
            prop: Stimulus property name to examine.

        Returns:
            Tuple ``(n, v, property_value)`` where *n* is the 0-based
            stimulus index, *v* is the best response value, and
            *property_value* is the value of *prop* for stimulus *n*.

        Raises:
            ValueError: If algorithm is unknown.
        """
        algo = algorithm.lower()
        if algo == 'empirical_maximum':
            return self.best_value_empirical(stim_response_doc, prop)
        raise ValueError(f"Unknown best_value algorithm: '{algorithm}'")

    def best_value_empirical(
        self,
        stim_response_doc: 'Document',
        prop: str,
    ) -> Tuple[int, float, Any]:
        """Find the stimulus with the largest empirical mean response.

        MATLAB equivalent: tuningcurve.best_value_empirical

        For each stimulus that has the given property, computes the mean
        response (real + imaginary, minus control), and returns the one
        with the highest value.

        Args:
            stim_response_doc: A stimulus_response_scalar Document.
            prop: Stimulus property name.

        Returns:
            Tuple ``(n, v, property_value)`` where *n* is the 0-based
            stimulus index, *v* is the best mean response, and
            *property_value* is the value of *prop* for that stimulus.

        Raises:
            RuntimeError: If stimulus presentation document cannot be found.
        """
        from ...query import Query

        stim_pres_doc = self._get_stim_presentation_doc(stim_response_doc)

        stim_pres = stim_pres_doc.document_properties.get(
            'stimulus_presentation', {}
        )
        stimuli = stim_pres.get('stimuli', [])
        presentation_order = stim_pres.get('presentation_order', [])

        # Find stimuli that have the requested property
        include = []
        for i, stim in enumerate(stimuli):
            params = stim.get('parameters', {})
            if prop in params:
                include.append(i)

        n = -1
        v = float('-inf')
        property_value: Any = ''

        responses = stim_response_doc.document_properties.get(
            'stimulus_response_scalar', {}
        ).get('responses', {})
        response_real = responses.get('response_real', [])
        response_imag = responses.get('response_imaginary', [])
        control_real = responses.get('control_response_real', [])
        control_imag = responses.get('control_response_imaginary', [])

        for idx in include:
            # Find all presentations of this stimulus
            indexes = [
                j for j, po in enumerate(presentation_order)
                if po == idx or po == idx + 1  # handle 0-based or 1-based
            ]
            # Use strict equality with actual presentation_order values
            indexes = [
                j for j, po in enumerate(presentation_order)
                if po == idx
            ]

            r_values = []
            for j in indexes:
                if j < len(response_real):
                    r = response_real[j]
                    if j < len(response_imag):
                        r = complex(r, response_imag[j])
                    # Subtract control if available
                    if j < len(control_real) and not _is_nan(control_real[j]):
                        c = control_real[j]
                        if j < len(control_imag):
                            c = complex(c, control_imag[j])
                        r = r - c
                    r_values.append(r)

            if r_values:
                mn = np.nanmean(r_values)
                if np.iscomplex(mn):
                    mn = abs(mn)
                else:
                    mn = float(np.real(mn))

                if mn > v:
                    v = mn
                    n = idx
                    property_value = stimuli[idx].get('parameters', {}).get(
                        prop, ''
                    )

        return (n, v, property_value)

    def property_value_array(
        self,
        stim_response_doc: 'Document',
        prop: str,
    ) -> List[Any]:
        """Find all unique values of a stimulus property.

        MATLAB equivalent: tuningcurve.property_value_array

        Args:
            stim_response_doc: A stimulus_response_scalar Document.
            prop: Stimulus property name.

        Returns:
            List of unique property values.

        Raises:
            RuntimeError: If stimulus presentation document cannot be found.
        """
        stim_pres_doc = self._get_stim_presentation_doc(stim_response_doc)

        stim_pres = stim_pres_doc.document_properties.get(
            'stimulus_presentation', {}
        )
        stimuli = stim_pres.get('stimuli', [])

        pva: List[Any] = []
        for stim in stimuli:
            params = stim.get('parameters', {})
            if prop in params:
                val = params[prop]
                if not _value_in_list(val, pva):
                    pva.append(val)

        return pva

    def generate_mock_docs(
        self,
        scope: str = 'standard',
        number_of_tests: int = 4,
        *,
        generate_expected_docs: bool = False,
        specific_test_inds: Optional[List[int]] = None,
    ) -> Tuple[List[Any], List[Any], List[Any]]:
        """Generate synthetic test data for tuning curve calculation.

        MATLAB equivalent: tuningcurve.generate_mock_docs

        Creates mock stimulus presentation and response documents for
        several test scenarios (contrast tuning, orientation tuning, etc.)
        and runs the calculator on them.

        Args:
            scope: ``'standard'`` or ``'lowSNR'``.
            number_of_tests: Number of test cases (up to 4 predefined).
            generate_expected_docs: If True, save outputs as expected.
            specific_test_inds: Subset of test indices to run.

        Returns:
            Tuple ``(docs, doc_output, doc_expected_output)`` where each
            is a list aligned with test indices.
        """
        docs: List[Any] = [None] * number_of_tests
        doc_output: List[Any] = [None] * number_of_tests
        doc_expected_output: List[Any] = [None] * number_of_tests

        test_inds = (
            specific_test_inds
            if specific_test_inds
            else list(range(number_of_tests))
        )

        for i in test_inds:
            if i >= number_of_tests:
                continue

            # Defaults
            param_struct = {
                'spatial_frequency': 0.5,
                'angle': 0,
                'contrast': 1,
            }
            independent_variables = ['contrast']
            selection = [
                {'property': 'contrast', 'operation': 'hasfield', 'value': 'varies'},
            ]

            if i == 0:
                # Contrast tuning (Naka-Rushton)
                X = np.array([0, 0.2, 0.4, 0.6, 0.8, 1.0])
                Rmax, C50, n_exp, Baseline = 10, 0.5, 2, 1
                R = Rmax * (X ** n_exp) / (X ** n_exp + C50 ** n_exp) + Baseline
                selection = [
                    {'property': 'contrast', 'operation': 'hasfield', 'value': 'varies'},
                ]

            elif i == 1:
                # Orientation + contrast 2D
                angles = np.arange(0, 360, 45)
                contrasts = np.array([0, 0.25, 0.50, 0.75, 1.0])
                A, C = np.meshgrid(angles, contrasts, indexing='ij')
                X = np.column_stack([A.ravel(), C.ravel()])
                Preferred, Width, Baseline, Amplitude = 90, 30, 2, 20
                C50, n_exp = 0.3, 2
                da = np.minimum(
                    np.abs(A.ravel() - Preferred),
                    np.minimum(
                        np.abs(A.ravel() - Preferred - 360),
                        np.abs(A.ravel() - Preferred + 360),
                    ),
                )
                R_angle = np.exp(-(da ** 2) / (2 * Width ** 2))
                R_contrast = (C.ravel() ** n_exp) / (
                    C.ravel() ** n_exp + C50 ** n_exp
                )
                R = Baseline + Amplitude * R_angle * R_contrast
                independent_variables = ['angle', 'contrast']
                selection = [
                    {'property': 'angle', 'operation': 'hasfield', 'value': 'varies'},
                    {'property': 'contrast', 'operation': 'hasfield', 'value': 'varies'},
                    {'property': 'angle', 'operation': 'exact_number', 'value': 'best'},
                ]

            elif i == 2:
                # 2D: contrast x spatial_frequency
                c_vals = np.array([0, 0.5, 1.0])
                sf_vals = np.array([0.1, 1.0, 10.0])
                CC, SF = np.meshgrid(c_vals, sf_vals, indexing='ij')
                X = np.column_stack([CC.ravel(), SF.ravel()])
                Rmax, C50, n_exp = 10, 0.5, 2
                Rc = (CC.ravel() ** n_exp) / (CC.ravel() ** n_exp + C50 ** n_exp)
                PrefSF, SigmaSF = 1, 0.5
                Rsf = np.exp(
                    -(np.log10(SF.ravel()) - np.log10(PrefSF)) ** 2
                    / (2 * SigmaSF ** 2)
                )
                R = 20 * Rc * Rsf + 1
                independent_variables = ['contrast', 'spatial_frequency']
                selection = [
                    {'property': 'contrast', 'operation': 'hasfield', 'value': 'varies'},
                    {'property': 'spatial_frequency', 'operation': 'hasfield', 'value': 'varies'},
                ]

            elif i == 3:
                # Orientation tuning shifted
                X = np.arange(0, 360, 30)
                Preferred, Width, Baseline, Amplitude = 180, 45, 5, 15
                da = np.minimum(
                    np.abs(X - Preferred),
                    np.minimum(
                        np.abs(X - Preferred - 360),
                        np.abs(X - Preferred + 360),
                    ),
                )
                R = Amplitude * np.exp(-(da ** 2) / (2 * Width ** 2)) + Baseline
                independent_variables = ['angle']
                selection = [
                    {'property': 'angle', 'operation': 'hasfield', 'value': 'varies'},
                ]

            else:
                # Default fallback
                X = np.array([0, 1])
                R = np.array([0, 10])

            noise = 0.2 if scope.lower() == 'lowsnr' else 0
            reps = 5

            docs[i] = {
                'param_struct': param_struct,
                'independent_variables': independent_variables,
                'X': X,
                'R': R,
                'noise': noise,
                'reps': reps,
                'selection': selection,
            }
            doc_output[i] = None
            doc_expected_output[i] = None

        return docs, doc_output, doc_expected_output

    # =========================================================================
    # Internal helpers
    # =========================================================================

    def _get_stim_presentation_doc(
        self, stim_response_doc: 'Document',
    ) -> 'Document':
        """Retrieve the stimulus_presentation doc linked to a response doc."""
        from ...query import Query

        if self._session is None:
            raise RuntimeError('Session is required for stimulus lookup')

        dep_id = stim_response_doc.dependency_value(
            'stimulus_presentation_id'
        )
        results = self._session.database_search(
            Query('base.id') == dep_id
        )
        if len(results) != 1:
            doc_id = stim_response_doc.document_properties.get(
                'base', {}
            ).get('id', '<unknown>')
            raise RuntimeError(
                f'Could not find stimulus presentation doc for '
                f'document {doc_id}'
            )
        return results[0]

    def __repr__(self) -> str:
        return f"TuningCurveCalc(session={self._session is not None})"


def _is_nan(value: Any) -> bool:
    """Check if a value is NaN (handles non-float types)."""
    try:
        return math.isnan(float(value))
    except (TypeError, ValueError):
        return False


def _value_in_list(val: Any, lst: List[Any]) -> bool:
    """Check if val is already in lst (deep equality)."""
    for existing in lst:
        if type(val) == type(existing):
            if isinstance(val, (int, float, str, bool)):
                if val == existing:
                    return True
            elif isinstance(val, (list, dict)):
                if val == existing:
                    return True
            elif val == existing:
                return True
        elif val == existing:
            return True
    return False
