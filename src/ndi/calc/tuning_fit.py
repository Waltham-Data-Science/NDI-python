"""
ndi.calc.tuning_fit - Abstract base class for tuning curve fitting calculators.

Extends Calculator with a mock document generation framework that
subclasses (e.g., OriDirTuning) use for self-testing.

MATLAB equivalent: src/ndi/+ndi/+calc/tuning_fit.m
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Any

import numpy as np

from ..calculator import Calculator

if TYPE_CHECKING:
    from ..session.session_base import Session


class TuningFit(Calculator):
    """
    Abstract base for stimulus tuning curve fitting calculators.

    Provides:
    - ``generate_mock_parameters()`` — abstract, implemented by subclasses
    - ``generate_mock_docs()`` — creates synthetic stimulus-response data
      for self-testing at two noise levels (highSNR / lowSNR)

    Subclasses must implement both ``calculate()`` (from Calculator)
    and ``generate_mock_parameters()``.

    Example:
        >>> class MyFit(TuningFit):
        ...     def calculate(self, parameters): ...
        ...     def generate_mock_parameters(self, scope, index): ...
        >>> fit = MyFit(session, 'my_fit', 'apps/calculators/my_fit')
    """

    # Scope presets (reps, noise)
    SCOPE_PRESETS: dict[str, dict[str, Any]] = {
        "highSNR": {"reps": 5, "noise": 0.001},
        "lowSNR": {"reps": 10, "noise": 1.0},
    }

    def __init__(
        self,
        session: Session | None = None,
        document_type: str = "",
        path_to_doc_type: str = "",
    ):
        super().__init__(
            session=session,
            document_type=document_type,
            path_to_doc_type=path_to_doc_type,
        )

    # ------------------------------------------------------------------
    # Abstract method – subclasses MUST implement
    # ------------------------------------------------------------------

    @abstractmethod
    def generate_mock_parameters(
        self,
        scope: str,
        index: int,
    ) -> tuple[dict[str, Any], list[str], np.ndarray, np.ndarray]:
        """
        Generate mock stimulus parameters for testing.

        Args:
            scope: ``'highSNR'`` or ``'lowSNR'``
            index: 1-based test index

        Returns:
            Tuple of:
            - param_struct: Parameter dict for stimulus_response documents
            - independent_variable: List of variable name strings
            - x: Independent variable values, shape (M,) or (M, N)
            - r: Response values, shape (M,)
        """

    # ------------------------------------------------------------------
    # Mock document generation
    # ------------------------------------------------------------------

    def generate_mock_docs(
        self,
        scope: str,
        number_of_tests: int,
        *,
        generate_expected_docs: bool = False,
        specific_test_inds: list[int] | None = None,
    ) -> tuple[list[Any], list[Any], list[Any]]:
        """
        Generate mock input documents and expected outputs for self-testing.

        Creates synthetic stimulus-response data at the requested noise
        level, feeds it through the calculator, and returns the inputs,
        actual outputs, and expected (noiseless) outputs.

        Args:
            scope: ``'highSNR'`` or ``'lowSNR'``
            number_of_tests: Number of test cases to generate.
            generate_expected_docs: If True, store expected output
                documents for later comparison.
            specific_test_inds: Subset of 1-based test indices to run.
                If None/empty, all tests are run.

        Returns:
            Tuple of (docs, doc_output, doc_expected_output):
            - docs[i]: Helper documents created for test *i*
            - doc_output[i]: Actual calculator output for test *i*
            - doc_expected_output[i]: Expected (reference) output

        Raises:
            ValueError: If *scope* is not a recognised preset.
        """
        if scope not in self.SCOPE_PRESETS:
            raise ValueError(f"scope must be one of {list(self.SCOPE_PRESETS)}, got '{scope}'")

        preset = self.SCOPE_PRESETS[scope]
        reps = preset["reps"]
        noise = preset["noise"]

        if specific_test_inds is None or len(specific_test_inds) == 0:
            specific_test_inds = list(range(1, number_of_tests + 1))

        docs: list[Any] = [None] * number_of_tests
        doc_output: list[Any] = [None] * number_of_tests
        doc_expected_output: list[Any] = [None] * number_of_tests

        for i in range(1, number_of_tests + 1):
            if i not in specific_test_inds:
                continue

            idx = i - 1  # 0-based storage index

            param_struct, independent_variable, x, r = self.generate_mock_parameters(scope, i)

            # Build synthetic stimulus-response data
            x = np.asarray(x, dtype=float)
            r = np.asarray(r, dtype=float)
            n_stim = len(x)

            stim_responses = []
            for s in range(n_stim):
                for _rep in range(reps):
                    noisy_r = r[s] + noise * np.random.randn()
                    entry = {
                        "stimid": s + 1,
                        "response": noisy_r,
                        "parameters": {
                            **param_struct,
                        },
                    }
                    # Add independent variable values
                    if x.ndim == 1:
                        entry["parameters"][independent_variable[0]] = float(x[s])
                    else:
                        for dim, var_name in enumerate(independent_variable):
                            entry["parameters"][var_name] = float(x[s, dim])
                    stim_responses.append(entry)

            docs[idx] = {
                "stim_responses": stim_responses,
                "param_struct": param_struct,
                "independent_variable": independent_variable,
                "x": x,
                "r": r,
                "reps": reps,
                "noise": noise,
            }

            # Build expected output (noiseless)
            doc_expected_output[idx] = {
                "independent_variable": x.tolist(),
                "response_mean": r.tolist(),
                "response_stderr": [0.0] * n_stim,
            }

            # Run the calculator if a session is available
            if self._session is not None:
                calc_params = self.default_search_for_input_parameters()
                calc_params["input_parameters"] = {
                    "independent_variable": independent_variable,
                    **param_struct,
                }
                try:
                    doc_output[idx] = self.calculate(calc_params)
                except Exception:
                    doc_output[idx] = None

        return docs, doc_output, doc_expected_output

    def __repr__(self) -> str:
        doc_type = self.doc_document_types[0] if self.doc_document_types else "none"
        return f"TuningFit(type={doc_type!r}, " f"session={self._session is not None})"
