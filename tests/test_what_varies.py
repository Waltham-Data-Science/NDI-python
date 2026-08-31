"""Unit tests for ndi.fun.stimulus.whatVaries / whatIsConstant.

Mirrors tests/+ndi/+unittest/+fun/+stimulus/whatVariesTest.m. The symmetry
generator deliberately records errors rather than asserting, so this file is
where the ported function's behaviour is actually pinned.
"""

from __future__ import annotations

import math

import pytest

from ndi.fun.stimulus import isequaln, whatIsConstant, whatVaries


def _params(varies, name):
    for v in varies:
        if v["parameter"] == name:
            return v["values"]
    return None


def _const(constant, name):
    for c in constant:
        if c["parameter"] == name:
            return c["value"]
    return None


THREE_ANGLES = [
    {"parameters": {"angle": a, "contrast": 1, "sFrequency": 0.5}} for a in (0, 90, 180)
]


class TestInputShapes:
    def test_stimuli_struct_array(self):
        varies, constant = whatVaries(THREE_ANGLES)
        assert [v["parameter"] for v in varies] == ["angle"]
        assert _params(varies, "angle") == [0, 90, 180]
        assert _const(constant, "contrast") == 1
        assert _const(constant, "sFrequency") == 0.5

    def test_list_of_parameter_dicts(self):
        varies, constant = whatVaries([{"angle": 0, "contrast": 1}, {"angle": 90, "contrast": 1}])
        assert _params(varies, "angle") == [0, 90]
        assert _const(constant, "contrast") == 1

    def test_document_properties_shaped_dict(self):
        varies, _ = whatVaries({"stimulus_presentation": {"stimuli": THREE_ANGLES}})
        assert _params(varies, "angle") == [0, 90, 180]

    def test_pooling_across_presentations(self):
        second = [
            {"parameters": {"angle": a, "contrast": 1, "sFrequency": 0.5}} for a in (270, 315)
        ]
        varies, _ = whatVaries(
            [
                {"stimulus_presentation": {"stimuli": THREE_ANGLES}},
                {"stimulus_presentation": {"stimuli": second}},
            ]
        )
        assert _params(varies, "angle") == [0, 90, 180, 270, 315]

    def test_single_parameter_dict(self):
        varies, constant = whatVaries({"angle": 0, "contrast": 1})
        assert varies == []
        assert {c["parameter"] for c in constant} == {"angle", "contrast"}

    def test_empty_input(self):
        assert whatVaries([]) == ([], [])

    def test_bad_input_raises(self):
        with pytest.raises(TypeError):
            whatVaries(42)

    def test_bad_entry_raises(self):
        with pytest.raises(ValueError):
            whatVaries([42])


class TestSemantics:
    def test_values_sorted_and_unique(self):
        stimuli = [{"parameters": {"angle": a, "contrast": 1}} for a in (180, 0, 90, 0)]
        varies, _ = whatVaries(stimuli)
        assert _params(varies, "angle") == [0, 90, 180]

    def test_field_present_in_some_stimuli_varies(self):
        """A parameter absent from some stimuli is varying, not constant."""
        varies, constant = whatVaries(
            [{"angle": 0, "contrast": 1}, {"angle": 0, "contrast": 1, "phase": 5}]
        )
        assert [v["parameter"] for v in varies] == ["phase"]
        assert _params(varies, "phase") == [5]
        assert {c["parameter"] for c in constant} == {"angle", "contrast"}

    def test_parameter_order_is_first_appearance(self):
        varies, constant = whatVaries([{"z": 1, "a": 0}, {"z": 1, "a": 90}])
        assert [c["parameter"] for c in constant] == ["z"]
        assert [v["parameter"] for v in varies] == ["a"]

    def test_vector_valued_varying_parameter(self):
        varies, _ = whatVaries([{"rect": [0, 0, 100, 100]}, {"rect": [0, 0, 200, 200]}])
        assert _params(varies, "rect") == [[0, 0, 100, 100], [0, 0, 200, 200]]

    def test_non_numeric_values_keep_first_appearance_order(self):
        varies, constant = whatVaries(
            [{"shape": "circle", "size": 5}, {"shape": "square", "size": 5}]
        )
        assert _params(varies, "shape") == ["circle", "square"]
        assert _const(constant, "size") == 5

    def test_all_constant_gives_no_varies(self):
        varies, constant = whatVaries([{"angle": 0}, {"angle": 0}])
        assert varies == []
        assert _const(constant, "angle") == 0


class TestBlankStimuli:
    STIMULI = [
        {"angle": 0, "contrast": 1},
        {"angle": 90, "contrast": 1},
        {"angle": 0, "contrast": 1, "isblank": 1},
    ]

    def test_blank_excluded_by_default(self):
        varies, _ = whatVaries(self.STIMULI)
        assert [v["parameter"] for v in varies] == ["angle"]
        assert _params(varies, "angle") == [0, 90]

    def test_blank_included_when_option_false(self):
        varies, _ = whatVaries(self.STIMULI, excludeBlank=False)
        assert "isblank" in [v["parameter"] for v in varies]

    def test_all_blank_gives_empty(self):
        assert whatVaries([{"angle": 0, "isblank": 1}, {"angle": 90, "isblank": 1}]) == ([], [])


class TestWhatIsConstant:
    def test_matches_second_output(self):
        """The invariant the symmetry battery checks on every case."""
        for stimuli in (THREE_ANGLES, [{"angle": 0}, {"angle": 90}], [{"a": 1}]):
            assert whatIsConstant(stimuli) == whatVaries(stimuli)[1]

    def test_excludeblank_is_forwarded(self):
        stimuli = TestBlankStimuli.STIMULI
        assert (
            whatIsConstant(stimuli, excludeBlank=False)
            == whatVaries(stimuli, excludeBlank=False)[1]
        )


class TestIsequalnSemantics:
    """This port uses isequaln throughout; MATLAB's whatVaries uses eqlen.

    These two cases are the recorded cross-language divergences. Pinning the
    Python behaviour here means a change to it is caught in Python's own
    suite, not only when the symmetry artifacts are compared.
    """

    def test_nan_equals_nan_so_an_all_nan_parameter_is_constant(self):
        nan = float("nan")
        varies, constant = whatVaries([{"angle": nan, "contrast": 1}] * 2)
        assert varies == []
        assert math.isnan(_const(constant, "angle"))

    def test_cell_valued_constant_parameter_succeeds(self):
        varies, constant = whatVaries(
            [{"color": ["r", "g", "b"], "angle": 0}, {"color": ["r", "g", "b"], "angle": 90}]
        )
        assert _const(constant, "color") == ["r", "g", "b"]
        assert _params(varies, "angle") == [0, 90]

    def test_isequaln_treats_bool_and_int_as_distinct(self):
        assert isequaln(True, True)
        assert not isequaln(True, 1)
        assert isequaln(float("nan"), float("nan"))
