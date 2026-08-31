"""Tests for ndi.data.evaluate_fitcurve.

Mirrors MATLAB ndi.data.evaluate_fitcurve, but evaluates the stored equation
through a restricted AST walker rather than eval(). The escape tests below are
the point of that difference and should be treated as load-bearing.
"""

from __future__ import annotations

import numpy as np
import pytest

from ndi.data import FitEquationError, evaluate_fitcurve


def _doc(equation="y=a+b*x.^c", params=(0, 1, 2), names="a b c", ind="x", dep="y"):
    return {
        "fitcurve": {
            "fit_equation": equation,
            "fit_parameters": list(params),
            "fit_parameter_names": names,
            "fit_independent_variable_names": ind,
            "fit_dependent_variable_names": dep,
        }
    }


class _Doc:
    def __init__(self, props):
        self.document_properties = props


class TestEvaluation:
    def test_schema_default_equation(self):
        """y=a+b*x.^c with a=0,b=1,c=2 is x squared."""
        x = np.array([0.0, 1.0, 2.0, 3.0])
        assert evaluate_fitcurve(_doc(), x) == pytest.approx(x**2)

    def test_accepts_a_document_object_not_just_a_mapping(self):
        """Real callers pass a document with .document_properties."""
        x = np.array([2.0])
        assert evaluate_fitcurve(_Doc(_doc()), x) == pytest.approx([4.0])

    def test_scalar_input(self):
        assert evaluate_fitcurve(_doc(), 3.0) == pytest.approx(9.0)

    def test_matlab_elementwise_operators_are_translated(self):
        x = np.array([1.0, 2.0, 4.0])
        d = _doc(equation="y=a.*x./b.^c", params=(8, 2, 1), names="a b c")
        assert evaluate_fitcurve(d, x) == pytest.approx(8 * x / 2)

    def test_matlab_caret_is_exponentiation_not_xor(self):
        """MATLAB ^ means power; in Python it would be bitwise xor."""
        d = _doc(equation="y=x^b", params=(3,), names="b")
        assert evaluate_fitcurve(d, 2.0) == pytest.approx(8.0)

    def test_allowed_functions_resolve_to_numpy(self):
        x = np.array([0.0, 1.0])
        d = _doc(equation="y=exp(x)+sqrt(b)", params=(9,), names="b")
        assert evaluate_fitcurve(d, x) == pytest.approx(np.exp(x) + 3.0)

    def test_parameters_may_arrive_as_a_string(self):
        d = _doc(params="0 1 2")
        d["fitcurve"]["fit_parameters"] = "0 1 2"
        assert evaluate_fitcurve(d, 3.0) == pytest.approx(9.0)


class TestMatlabParityErrors:
    """MATLAB errors on these three; so do we."""

    def test_multiple_independent_variables(self):
        with pytest.raises(ValueError, match="independent"):
            evaluate_fitcurve(_doc(ind="x z"), 1.0)

    def test_multiple_dependent_variables(self):
        with pytest.raises(ValueError, match="dependent"):
            evaluate_fitcurve(_doc(dep="y w"), 1.0)

    def test_parameter_name_and_value_counts_must_agree(self):
        with pytest.raises(ValueError, match="same number of entries"):
            evaluate_fitcurve(_doc(params=(0, 1), names="a b c"), 1.0)


class TestEquationShape:
    def test_equation_must_be_an_assignment(self):
        with pytest.raises(FitEquationError, match="single assignment"):
            evaluate_fitcurve(_doc(equation="a+b*x"), 1.0)

    def test_equation_must_assign_to_the_declared_dependent_variable(self):
        with pytest.raises(FitEquationError, match="declares the dependent variable"):
            evaluate_fitcurve(_doc(equation="z=a+b*x"), 1.0)

    def test_unparseable_equation_is_reported_with_both_forms(self):
        with pytest.raises(FitEquationError, match="Could not parse"):
            evaluate_fitcurve(_doc(equation="y=a+*"), 1.0)

    def test_unknown_name_is_named(self):
        with pytest.raises(FitEquationError, match="Unknown name 'q'"):
            evaluate_fitcurve(_doc(equation="y=q*x"), 1.0)


class TestSandboxRefusesEscapes:
    """The reason this is not eval().

    A fitcurve document is data and can arrive from a shared or cloud dataset.
    Each of these is something MATLAB's eval would happily execute.
    """

    @pytest.mark.parametrize(
        "equation",
        [
            "y=__import__('os').system('echo pwned')",
            "y=open('/etc/passwd').read()",
            "y=eval('1+1')",
            "y=exec('import os')",
            "y=(1).__class__.__mro__[1].__subclasses__()",
            "y=x.__class__",
            "y=globals()",
            "y=[i for i in range(10)]",
            "y=(lambda: 1)()",
            "y=np.exp(x)",
        ],
    )
    def test_hostile_equation_is_refused(self, equation):
        with pytest.raises(FitEquationError):
            evaluate_fitcurve(_doc(equation=equation, params=(1,), names="b"), 1.0)

    def test_nothing_is_executed_before_the_refusal(self, tmp_path):
        """The walker must reject before evaluating, not part-way through."""
        target = tmp_path / "written.txt"
        eq = f"y=open('{target}','w').write('x')"
        with pytest.raises(FitEquationError):
            evaluate_fitcurve(_doc(equation=eq, params=(1,), names="b"), 1.0)
        assert not target.exists()

    def test_unlisted_function_is_refused_by_name(self):
        with pytest.raises(FitEquationError, match="not an allowed fit-equation function"):
            evaluate_fitcurve(_doc(equation="y=erf(x)", params=(1,), names="b"), 1.0)

    def test_keyword_arguments_are_refused(self):
        with pytest.raises(FitEquationError, match="Keyword arguments"):
            evaluate_fitcurve(_doc(equation="y=exp(x, dtype=1)", params=(1,), names="b"), 1.0)
