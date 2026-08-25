"""Unit tests for the canonical value grammar (FUN_CASES_SCHEMA.md section 3).

The renderer is the whole comparison.  Every cross-language assertion in the
``fun`` symmetry pair reduces to two rendered strings being equal, so a renderer
that quietly disagreed with MATLAB's ``ndi.symmetry.fun.cases.render`` would not
make the suite red -- it would make it green over a real difference, or red over
none.  These tests pin the grammar against the values that actually decide it:
the non-finite tokens, the boolean-before-number ordering, key sorting, quoting,
the one-element collapse ``renderSequence`` exists to defeat, and the ``%.12g``
edges.

Every expectation here is what the MATLAB source in ``cases.m`` produces for the
equivalent MATLAB value.  Where MATLAB cannot express the Python value at all
(``None``, a ``dict`` key that is not a valid MATLAB field name) the test says so
rather than pretending there is a contract.
"""

import math

import numpy as np

from tests.symmetry._fun_cases import num_token, render, render_sequence


class TestNumbers:
    def test_integers_and_simple_decimals(self):
        assert render(0) == "0"
        assert render(180) == "180"
        assert render(0.5) == "0.5"
        assert render(-3.25) == "-3.25"

    def test_integer_valued_float_renders_without_a_decimal_point(self):
        """MATLAB has only doubles, so its ``1`` and Python's ``1.0`` must render
        the same or every constant-valued case would mismatch."""
        assert render(1.0) == render(1) == "1"

    def test_negative_zero_keeps_its_sign(self):
        """Pinned for this side only. No case in the battery produces a negative
        zero, and MATLAB's ``sprintf('%.12g', -0)`` was not measured, so this is
        Python's behaviour recorded -- not a cross-language claim."""
        assert num_token(-0.0) == "-0"

    def test_twelve_significant_digits(self):
        # %.12g, exactly as sprintf('%.12g') -- 12 significant digits, then stop.
        assert num_token(1 / 3) == "0.333333333333"
        assert num_token(123456789012345.0) == "1.23456789012e+14"

    def test_float_representation_noise_is_rounded_away(self):
        """The classic 0.1+0.2 case: %.12g is what makes the two languages agree
        about a value neither of them stores exactly."""
        assert 0.1 + 0.2 != 0.3
        assert num_token(0.1 + 0.2) == "0.3" == num_token(0.3)

    def test_exponent_form_matches_c_printf(self):
        # MATLAB's sprintf and Python's % both use C printf, so the exponent is
        # signed and at least two digits on both sides.
        assert num_token(1e-5) == "1e-05"
        assert num_token(1e21) == "1e+21"

    def test_non_finite_tokens_use_matlab_spelling(self):
        """Python's %g gives 'nan'/'inf'; the schema fixes MATLAB's spelling."""
        assert render(float("nan")) == "NaN"
        assert render(float("inf")) == "Inf"
        assert render(float("-inf")) == "-Inf"
        assert render(-math.inf) == "-Inf"

    def test_numpy_scalars_render_as_their_python_equivalents(self):
        assert render(np.float64(0.5)) == "0.5"
        assert render(np.int64(180)) == "180"
        assert render(np.float64("nan")) == "NaN"


class TestBooleans:
    def test_booleans_are_checked_before_numbers(self):
        """``bool`` is a subclass of ``int`` in Python. ``True`` must render
        ``true``, not ``1`` -- MATLAB's ``islogical`` branch runs before its
        ``isnumeric`` one for the same reason."""
        assert render(True) == "true"
        assert render(False) == "false"
        assert render(True) != render(1)
        assert render(np.bool_(True)) == "true"

    def test_booleans_inside_containers_too(self):
        assert render([True, False]) == "[true, false]"
        assert render({"flag": True}) == "{flag: true}"


class TestText:
    def test_text_is_single_quoted(self):
        assert render("circle") == "'circle'"

    def test_empty_text_is_two_quotes(self):
        assert render("") == "''"

    def test_quotes_inside_text_are_not_escaped(self):
        """The grammar says 'single-quoted, no escaping'. That makes the output
        ambiguous for text containing a quote -- but it makes the two languages
        ambiguous the SAME way, which is all a comparison needs. Escaping on one
        side only would be the real hazard."""
        assert render("it's") == "'it's'"
        assert render("a'b'c") == "'a'b'c'"
        assert render('say "hi"') == "'say \"hi\"'"

    def test_text_is_one_element_not_a_sequence_of_characters(self):
        assert render_sequence("circle") == "['circle']"


class TestSequences:
    def test_numbers_and_text(self):
        assert render([0, 90, 180]) == "[0, 90, 180]"
        assert render(["r", "g", "b"]) == "['r', 'g', 'b']"

    def test_empty_sequence(self):
        assert render([]) == "[]"
        assert render(()) == "[]"
        assert render_sequence([]) == "[]"

    def test_tuples_lists_and_arrays_are_indistinguishable(self):
        """The grammar deliberately does not distinguish container types: MATLAB
        cell, struct array and numeric vector all render '[...]', because Python
        has one list type for all three."""
        assert render([1, 2]) == render((1, 2)) == render(np.array([1, 2])) == "[1, 2]"

    def test_nested_sequences(self):
        assert render([[0, 0, 100, 100], [0, 0, 200, 200]]) == (
            "[[0, 0, 100, 100], [0, 0, 200, 200]]"
        )

    def test_render_sequence_always_brackets_a_single_value(self):
        """The one-element collapse is exactly what ``renderSequence`` exists to
        defeat: MATLAB gives back a bare scalar where Python gives a one-element
        list, and ``render`` would spell those ``5`` and ``[5]``."""
        assert render(5) == "5"
        assert render_sequence(5) == "[5]"
        assert render_sequence([5]) == "[5]"
        assert render_sequence(np.array([5])) == "[5]"
        assert render_sequence("circle") == "['circle']"
        assert render_sequence({"a": 1}) == "[{a: 1}]"

    def test_zero_dimensional_array_is_a_scalar(self):
        assert render(np.array(5)) == "5"
        assert render_sequence(np.array(5)) == "[5]"


class TestMappings:
    def test_keys_are_sorted_not_insertion_ordered(self):
        """Field-insertion order must not be able to make the two languages
        disagree -- MATLAB struct field order follows assignment order and
        Python dict order follows literal order, and neither is a behaviour."""
        assert render({"contrast": 1, "angle": 0}) == "{angle: 0, contrast: 1}"
        assert render({"angle": 0, "contrast": 1}) == render({"contrast": 1, "angle": 0})

    def test_sorting_is_applied_at_every_level(self):
        value = {"z": {"b": 2, "a": 1}, "y": [{"d": 4, "c": 3}]}
        assert render(value) == "{y: [{c: 3, d: 4}], z: {a: 1, b: 2}}"

    def test_sorting_is_by_codepoint_like_matlab_sort(self):
        # MATLAB sort() on a cellstr orders by character code, so uppercase
        # sorts before lowercase; Python's sorted() on str does the same.
        assert render({"b": 1, "A": 2, "a": 3}) == "{A: 2, a: 3, b: 1}"

    def test_empty_mapping(self):
        assert render({}) == "{}"

    def test_mapping_values_of_every_kind(self):
        assert render({"parameter": "contrast", "value": 1}) == (
            "{parameter: 'contrast', value: 1}"
        )
        assert render({"angle": float("nan"), "contrast": 1}) == "{angle: NaN, contrast: 1}"


class TestFallback:
    def test_unknown_types_render_as_their_class_name(self):
        class Widget:
            pass

        assert render(Widget()) == "<Widget>"

    def test_none_has_no_matlab_counterpart(self):
        """MATLAB has no ``None``. It renders as a class token rather than as
        ``[]`` or ``''`` so that a ``None`` leaking into a compared value shows
        up as a mismatch instead of silently reading as an empty value."""
        assert render(None) == "<NoneType>"
        assert render(None) != render([])
        assert render(None) != render("")
