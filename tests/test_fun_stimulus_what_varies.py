"""Tests for ndi.fun.stimulus.whatVaries / whatIsConstant / whatVaries_parameterList.

Mirrors tests/+ndi/+unittest/+fun/+stimulus/whatVariesTest.m from NDI-matlab
(origin/main, whatVaries.m at fa5542b32), one Python test per MATLAB test method,
plus Python-specific cases (numpy values, NaN, ndi_document input).

Fully offline: the stimuli are plain dicts, no session or database needed.
"""

from __future__ import annotations

import math

import numpy as np
import pytest


def three_angle_stimuli() -> list[dict]:
    """A stimulus_presentation.stimuli-shaped list: angle varies, the rest constant.

    Mirrors whatVariesTest.threeAngleStimuli.
    """
    return [
        {"parameters": {"angle": 0, "contrast": 1, "sFrequency": 0.5}},
        {"parameters": {"angle": 90, "contrast": 1, "sFrequency": 0.5}},
        {"parameters": {"angle": 180, "contrast": 1, "sFrequency": 0.5}},
    ]


class _FakeDoc:
    """Minimal stand-in for ndi.document: only document_properties and id()."""

    def __init__(self, props: dict, doc_id: str = "fake_id"):
        self.document_properties = props
        self._id = doc_id

    def id(self) -> str:
        return self._id


# ===========================================================================
# whatVaries — input shapes (mirrors the MATLAB test class)
# ===========================================================================


class TestWhatVariesInputShapes:
    def test_stimuli_list(self):
        """MATLAB testStimuliStructArray."""
        from ndi.fun.stimulus import whatVaries

        varies, constant = whatVaries(three_angle_stimuli())

        assert len(varies) == 1
        assert varies[0]["parameter"] == "angle"
        assert varies[0]["values"] == [0, 90, 180]

        assert [c["parameter"] for c in constant] == ["contrast", "sFrequency"]
        assert [c["value"] for c in constant] == [1, 0.5]

    def test_values_sorted_and_unique(self):
        """MATLAB testValuesSortedAndUnique."""
        from ndi.fun.stimulus import whatVaries

        s = [
            {"parameters": {"angle": 180, "contrast": 1}},
            {"parameters": {"angle": 0, "contrast": 1}},
            {"parameters": {"angle": 90, "contrast": 1}},
            {"parameters": {"angle": 0, "contrast": 1}},
        ]
        varies, _ = whatVaries(s)
        assert varies[0]["parameter"] == "angle"
        assert varies[0]["values"] == [0, 90, 180]

    def test_list_of_parameter_dicts(self):
        """MATLAB testCellOfParameterStructs / testStructArrayOfParameterStructs.

        Both MATLAB shapes (cell array and struct array) collapse to one Python
        shape: a list of parameter dicts.
        """
        from ndi.fun.stimulus import whatVaries

        p = [{"angle": 0, "contrast": 1}, {"angle": 90, "contrast": 1}]
        varies, constant = whatVaries(p)
        assert varies[0]["parameter"] == "angle"
        assert varies[0]["values"] == [0, 90]
        assert constant[0]["parameter"] == "contrast"
        assert constant[0]["value"] == 1

    def test_document_properties_shaped_dict(self):
        """MATLAB testDocumentPropertiesShapedStruct."""
        from ndi.fun.stimulus import whatVaries

        dp = {"stimulus_presentation": {"stimuli": three_angle_stimuli()}}
        varies, constant = whatVaries(dp)
        assert varies[0]["parameter"] == "angle"
        assert varies[0]["values"] == [0, 90, 180]
        assert [c["parameter"] for c in constant] == ["contrast", "sFrequency"]

    def test_pooling_across_presentations(self):
        """MATLAB testPoolingAcrossPresentations."""
        from ndi.fun.stimulus import whatVaries

        dp = [
            {"stimulus_presentation": {"stimuli": three_angle_stimuli()}},
            {
                "stimulus_presentation": {
                    "stimuli": [{"parameters": {"angle": 270, "contrast": 1, "sFrequency": 0.5}}]
                }
            },
        ]
        varies, constant = whatVaries(dp)
        assert varies[0]["parameter"] == "angle"
        assert varies[0]["values"] == [0, 90, 180, 270]
        assert [c["parameter"] for c in constant] == ["contrast", "sFrequency"]

    def test_single_parameter_dict(self):
        """MATLAB testAllConstantSingleStimulus."""
        from ndi.fun.stimulus import whatVaries

        varies, constant = whatVaries({"angle": 0, "contrast": 1})
        assert varies == []
        assert [c["parameter"] for c in constant] == ["angle", "contrast"]
        assert [c["value"] for c in constant] == [0, 1]

    def test_ndi_document_input(self):
        """Python-side equivalent of the ndi.document branch."""
        from ndi.fun.stimulus import whatVaries

        doc = _FakeDoc({"stimulus_presentation": {"stimuli": three_angle_stimuli()}})
        varies, constant = whatVaries(doc)
        assert varies[0]["parameter"] == "angle"
        assert varies[0]["values"] == [0, 90, 180]
        assert [c["parameter"] for c in constant] == ["contrast", "sFrequency"]

    def test_list_of_ndi_documents_pooled(self):
        """A list mixing documents and parameter dicts pools everything, in order."""
        from ndi.fun.stimulus import whatVaries

        doc = _FakeDoc({"stimulus_presentation": {"stimuli": three_angle_stimuli()}})
        varies, constant = whatVaries([doc, {"angle": 270, "contrast": 1, "sFrequency": 0.5}])
        assert varies[0]["parameter"] == "angle"
        assert varies[0]["values"] == [0, 90, 180, 270]
        assert [c["parameter"] for c in constant] == ["contrast", "sFrequency"]

    def test_real_ndi_document_object(self):
        """The real ndi.document class is accepted, not just a duck-typed stand-in."""
        from ndi.document import ndi_document
        from ndi.fun.stimulus import whatVaries

        doc = ndi_document({"stimulus_presentation": {"stimuli": three_angle_stimuli()}})
        varies, _ = whatVaries(doc)
        assert varies[0]["parameter"] == "angle"
        assert varies[0]["values"] == [0, 90, 180]


# ===========================================================================
# whatVaries — semantics
# ===========================================================================


class TestWhatVariesSemantics:
    def test_field_present_in_some_stimuli(self):
        """MATLAB testFieldPresentInSomeStimuli."""
        from ndi.fun.stimulus import whatVaries

        p = [{"angle": 0, "contrast": 1}, {"angle": 0, "contrast": 1, "phase": 5}]
        varies, constant = whatVaries(p)
        assert varies[0]["parameter"] == "phase"
        assert varies[0]["values"] == [5]
        assert [c["parameter"] for c in constant] == ["angle", "contrast"]

    def test_cell_valued_constant_parameter(self):
        """MATLAB testCellValuedConstantParameter (commit 1103b9481 regression)."""
        from ndi.fun.stimulus import whatVaries

        p = [{"color": ["r", "g", "b"], "angle": 0}, {"color": ["r", "g", "b"], "angle": 90}]
        varies, constant = whatVaries(p)
        assert varies[0]["parameter"] == "angle"
        assert varies[0]["values"] == [0, 90]
        assert constant[0]["parameter"] == "color"
        assert constant[0]["value"] == ["r", "g", "b"]

    def test_vector_valued_varying_parameter(self):
        """MATLAB testVectorValuedVaryingParameter."""
        from ndi.fun.stimulus import whatVaries

        p = [{"rect": [0, 0, 100, 100]}, {"rect": [0, 0, 200, 200]}]
        varies, _ = whatVaries(p)
        assert varies[0]["parameter"] == "rect"
        assert varies[0]["values"] == [[0, 0, 100, 100], [0, 0, 200, 200]]

    def test_cell_valued_varying_parameter(self):
        """A cell-valued parameter that actually VARIES.

        Relocated here from the cross-language ``fun`` symmetry battery, which
        joins 1:1 with MATLAB's case list and has no row for it.  Kept because it
        reaches a second code path that the constant case does not: the constant
        case is settled inside ``_varying_fields``, while this one also runs
        ``_unique_values``' first-appearance branch on two list values.  On the
        MATLAB side both paths bottom out in ``vlt.data.eqlen``'s bare ``==``,
        which is undefined for two cell arrays -- so a MATLAB build that survived
        the comparison would still have a second place to throw.
        """
        from ndi.fun.stimulus import whatVaries

        p = [{"color": ["r", "g"], "angle": 0}, {"color": ["b", "y"], "angle": 0}]
        varies, constant = whatVaries(p)
        assert varies[0]["parameter"] == "color"
        assert varies[0]["values"] == [["r", "g"], ["b", "y"]]
        assert constant[0]["parameter"] == "angle"
        assert constant[0]["value"] == 0

    def test_one_element_vector_values_are_not_scalars(self):
        """A one-element list is a VECTOR here, not a scalar.

        Relocated here from the ``fun`` symmetry battery for the same reason, and
        this one is a genuine documented divergence rather than extra coverage:
        MATLAB's ``isscalar`` is true for a 1x1 array, so ``[2]`` and ``[10]``
        take ``local_uniqueValues``' sorted-numeric path there and come back as
        bare sorted numbers.  Python has no 1x1 scalar, so the values stay
        wrapped and keep first-appearance order.  Asserting that here rather than
        in the symmetry battery keeps the cross-language case list joinable
        1:1 while still pinning the behaviour.  See the whatVaries decision_log
        in src/ndi/fun/ndi_matlab_python_bridge.yaml.
        """
        from ndi.fun.stimulus import whatVaries

        p = [{"gain": [10]}, {"gain": [2]}]
        varies, _ = whatVaries(p)
        assert varies[0]["parameter"] == "gain"
        # first appearance, still wrapped -- NOT [2, 10] and NOT [2], [10]
        assert varies[0]["values"] == [[10], [2]]

    def test_non_numeric_values_returned_in_first_appearance_order(self):
        """MATLAB testNonNumericValuesReturnedAsCell."""
        from ndi.fun.stimulus import whatVaries

        p = [{"shape": "circle", "size": 5}, {"shape": "square", "size": 5}]
        varies, constant = whatVaries(p)
        assert varies[0]["parameter"] == "shape"
        assert varies[0]["values"] == ["circle", "square"]
        assert constant[0]["parameter"] == "size"
        assert constant[0]["value"] == 5

    def test_parameter_order_is_first_appearance(self):
        """Parameters are reported in order of first appearance across stimuli."""
        from ndi.fun.stimulus import whatVaries

        p = [{"b": 1, "a": 0}, {"b": 1, "a": 0, "c": 7}]
        varies, constant = whatVaries(p)
        assert [c["parameter"] for c in constant] == ["b", "a"]
        assert [v["parameter"] for v in varies] == ["c"]

    def test_empty_input(self):
        """MATLAB testEmptyInput."""
        from ndi.fun.stimulus import whatVaries

        varies, constant = whatVaries([])
        assert varies == []
        assert constant == []

    def test_numpy_scalar_values_treated_as_scalars(self):
        """numpy scalars take the sorted-numeric path, like MATLAB doubles."""
        from ndi.fun.stimulus import whatVaries

        p = [{"angle": np.float64(180)}, {"angle": np.float64(0)}]
        varies, _ = whatVaries(p)
        assert varies[0]["values"] == [0.0, 180.0]

    def test_numpy_array_valued_constant(self):
        """A numpy-array-valued parameter compares elementwise without crashing."""
        from ndi.fun.stimulus import whatVaries

        p = [
            {"rect": np.array([0, 0, 100, 100]), "angle": 0},
            {"rect": np.array([0, 0, 100, 100]), "angle": 90},
        ]
        varies, constant = whatVaries(p)
        assert varies[0]["parameter"] == "angle"
        assert constant[0]["parameter"] == "rect"
        assert np.array_equal(constant[0]["value"], np.array([0, 0, 100, 100]))

    def test_numpy_arrays_of_different_length_vary(self):
        """Different-length arrays are unequal (vlt.data.eqlen size check)."""
        from ndi.fun.stimulus import whatVaries

        p = [{"rect": np.array([0, 0])}, {"rect": np.array([0, 0, 1])}]
        varies, constant = whatVaries(p)
        assert varies[0]["parameter"] == "rect"
        assert constant == []

    def test_nan_valued_parameter_is_constant(self):
        """NaN == NaN for the constancy test (isequaln semantics)."""
        from ndi.fun.stimulus import whatVaries

        p = [{"angle": float("nan"), "contrast": 1}, {"angle": float("nan"), "contrast": 1}]
        varies, constant = whatVaries(p)
        assert varies == []
        assert [c["parameter"] for c in constant] == ["angle", "contrast"]
        assert math.isnan(constant[0]["value"])

    def test_nan_values_collapse_to_one_and_sort_last(self):
        """MATLAB local_uniqueValues collapses repeated NaNs and puts NaN last."""
        from ndi.fun.stimulus import whatVaries

        p = [
            {"angle": float("nan")},
            {"angle": 90},
            {"angle": float("nan")},
            {"angle": 0},
        ]
        varies, _ = whatVaries(p)
        vals = varies[0]["values"]
        assert len(vals) == 3
        assert vals[0] == 0
        assert vals[1] == 90
        assert math.isnan(vals[2])


# ===========================================================================
# whatVaries — blank stimulus exclusion (commit 1456b8e4b)
# ===========================================================================


class TestBlankStimulusExclusion:
    BLANK_SET = [
        {"angle": 0, "contrast": 1},
        {"angle": 90, "contrast": 1},
        {"angle": 0, "contrast": 1, "isblank": 1},
    ]

    def test_blank_excluded_by_default(self):
        """MATLAB testBlankStimuliExcludedByDefault."""
        from ndi.fun.stimulus import whatVaries

        varies, constant = whatVaries(self.BLANK_SET)
        assert varies[0]["parameter"] == "angle"
        assert varies[0]["values"] == [0, 90]
        assert [c["parameter"] for c in constant] == ["contrast"]
        assert "isblank" not in [v["parameter"] for v in varies]

    def test_blank_included_when_option_false(self):
        """MATLAB testBlankStimuliIncludedWhenOptionFalse."""
        from ndi.fun.stimulus import whatVaries

        varies, _ = whatVaries(self.BLANK_SET, exclude_blank=False)
        assert "isblank" in [v["parameter"] for v in varies]

    def test_all_blank_gives_empty(self):
        """MATLAB testAllBlankStimuliGivesEmpty."""
        from ndi.fun.stimulus import whatVaries

        p = [{"angle": 0, "isblank": 1}, {"angle": 90, "isblank": 1}]
        varies, constant = whatVaries(p)
        assert varies == []
        assert constant == []

    def test_isblank_false_is_not_blank(self):
        """isblank == 0 marks a normal stimulus, which stays in the comparison."""
        from ndi.fun.stimulus import whatVaries

        p = [{"angle": 0, "isblank": 0}, {"angle": 90, "isblank": 0}]
        varies, constant = whatVaries(p)
        assert varies[0]["parameter"] == "angle"
        assert [c["parameter"] for c in constant] == ["isblank"]

    def test_isblank_empty_is_not_blank(self):
        """MATLAB local_isBlank requires a non-empty value: ~isempty(v) && all(...)."""
        from ndi.fun.stimulus import whatVaries

        p = [{"angle": 0, "isblank": []}, {"angle": 90, "isblank": []}]
        varies, _ = whatVaries(p)
        assert varies[0]["parameter"] == "angle"

    def test_isblank_vector_requires_all_true(self):
        """MATLAB all(logical(v(:))): a vector is blank only if every entry is true."""
        from ndi.fun.stimulus import whatVaries

        p = [
            {"a": 1, "isblank": [1, 0]},  # not blank: not every entry is true
            {"a": 2, "isblank": [1, 1]},  # blank: dropped
            {"a": 1, "isblank": [0, 0]},  # not blank
        ]
        varies, constant = whatVaries(p)
        # the two survivors agree on 'a' and on 'isblank'? no: isblank differs
        assert [v["parameter"] for v in varies] == ["isblank"]
        assert [c["parameter"] for c in constant] == ["a"]
        assert constant[0]["value"] == 1


# ===========================================================================
# whatIsConstant
# ===========================================================================


class TestWhatIsConstant:
    def test_matches_second_output(self):
        """MATLAB testWhatIsConstantMatchesSecondOutput."""
        from ndi.fun.stimulus import whatIsConstant, whatVaries

        s = three_angle_stimuli()
        _, constant = whatVaries(s)
        assert whatIsConstant(s) == constant

    def test_passes_exclude_blank_through(self):
        """The blank stimulus contrast of 0 must not make 'contrast' vary by default."""
        from ndi.fun.stimulus import whatIsConstant

        p = [
            {"angle": 0, "contrast": 1},
            {"angle": 90, "contrast": 1},
            {"angle": 0, "contrast": 0, "isblank": 1},
        ]
        assert [c["parameter"] for c in whatIsConstant(p)] == ["contrast"]
        assert whatIsConstant(p, exclude_blank=False) == []


# ===========================================================================
# whatVaries_parameterList
# ===========================================================================


class TestWhatVariesParameterList:
    def test_normalizes_stimuli_list(self):
        from ndi.fun.stimulus import whatVaries_parameterList

        params = whatVaries_parameterList(three_angle_stimuli())
        assert len(params) == 3
        assert params[0] == {"angle": 0, "contrast": 1, "sFrequency": 0.5}

    def test_normalizes_document(self):
        from ndi.fun.stimulus import whatVaries_parameterList

        doc = _FakeDoc({"stimulus_presentation": {"stimuli": three_angle_stimuli()}})
        params = whatVaries_parameterList(doc)
        assert [p["angle"] for p in params] == [0, 90, 180]

    def test_empty_inputs(self):
        from ndi.fun.stimulus import whatVaries_parameterList

        assert whatVaries_parameterList([]) == []
        assert whatVaries_parameterList({"stimulus_presentation": {"stimuli": []}}) == []

    def test_bad_input_raises(self):
        """MATLAB testBadInputErrors: whatVaries_parameterList:badInput."""
        from ndi.fun.stimulus import whatVaries

        with pytest.raises(TypeError, match="badInput"):
            whatVaries(42)

    def test_bad_list_entry_raises(self):
        """MATLAB testBadInputErrors: whatVaries_parameterList:badCellEntry."""
        from ndi.fun.stimulus import whatVaries

        with pytest.raises(TypeError, match="badCellEntry"):
            whatVaries([42])

    def test_stimulus_without_parameters_raises(self):
        """A stimulus with no 'parameters' would make everything look varying."""
        from ndi.fun.stimulus import whatVaries_parameterList

        dp = {"stimulus_presentation": {"stimuli": [{"parameters": {"angle": 0}}, {"angle": 90}]}}
        with pytest.raises(ValueError, match="badStimulus"):
            whatVaries_parameterList(dp)

    def test_presentation_without_stimuli_is_empty(self):
        """A presentation with no stimuli is 'nothing to compare', not an error."""
        from ndi.fun.stimulus import whatVaries_parameterList

        assert whatVaries_parameterList({"stimulus_presentation": {}}) == []

    def test_document_without_stimulus_presentation_raises(self):
        """MATLAB local_docParameters: whatVaries_parameterList:notPresentation."""
        from ndi.fun.stimulus import whatVaries_parameterList

        doc = _FakeDoc({"base": {"id": "abc"}}, doc_id="abc")
        with pytest.raises(ValueError, match="notPresentation"):
            whatVaries_parameterList(doc)


# ===========================================================================
# snake_case aliases and module surface
# ===========================================================================


class TestAliases:
    def test_snake_case_aliases_exist(self):
        from ndi.fun import stimulus

        assert stimulus.what_varies is stimulus.whatVaries
        assert stimulus.what_is_constant is stimulus.whatIsConstant
        assert stimulus.what_varies_parameter_list is stimulus.whatVaries_parameterList
