"""``ndi.validators`` against ``+ndi/+validators/``.

WHY THIS FILE EXISTS. The package had no behavioural tests at all -- the
only thing importing ``ndi.validators`` was the bridge completeness guard,
which checks that the names exist and never calls one. Eleven entries were
recorded ported on the strength of a reading, and a reading is exactly what
:data:`mustBeID`'s fall-through survived.

THE BUG THESE LOCK IN. ``mustBeID`` checked the format with an ASCII
pattern and then, to report WHICH character was at fault, looped with
``str.isalnum()``. ``str.isalnum()`` is Unicode-aware, so for an ID holding
a non-ASCII letter or digit the pattern failed, the loop found nothing to
blame, and the function returned ``None`` -- silently ACCEPTING an ID it had
just rejected. A validator that returns without raising is a validator that
passed.
"""

from __future__ import annotations

import pytest

from ndi.validators import (
    mustBeCellArrayOfClass,
    mustBeCellArrayOfNonEmptyCharacterArrays,
    mustBeEpochInput,
    mustBeID,
    mustBeNumericClass,
    mustBeTextLike,
    mustHaveFields,
    mustHaveRequiredColumns,
    mustMatchRegex,
)

VALID_ID = "a" * 16 + "_" + "b" * 16


class TestMustBeID:
    """MATLAB counterpart: ``+ndi/+validators/mustBeID.m``.

    MATLAB's own error text spells the rule ``(A-Z, a-z, 0-9)``, so ASCII
    is the intended contract on both sides.
    """

    def test_a_well_formed_id_is_accepted(self):
        mustBeID(VALID_ID)
        mustBeID("0123456789abcdef_FEDCBA9876543210")

    @pytest.mark.parametrize(
        "value, fragment",
        [
            ("a" * 32, "exactly 33 characters"),
            ("a" * 34, "exactly 33 characters"),
            ("a" * 16 + "-" + "b" * 16, "must be an underscore"),
        ],
    )
    def test_length_and_underscore_are_enforced(self, value, fragment):
        with pytest.raises(ValueError, match=fragment):
            mustBeID(value)

    def test_a_non_string_is_rejected(self):
        with pytest.raises(TypeError):
            mustBeID(123)

    @pytest.mark.parametrize(
        "char, why",
        [
            ("é", "a Unicode letter: str.isalnum() is True"),
            ("٣", "an Arabic-Indic digit: str.isalnum() is True"),
            ("½", "VULGAR FRACTION ONE HALF: str.isalnum() is True"),
        ],
        ids=["latin-e-acute", "arabic-indic-three", "vulgar-half"],
    )
    def test_a_non_ascii_character_is_rejected_not_silently_accepted(self, char, why):
        """The regression. Each of these is ``str.isalnum()``-true, so the
        old reporting loop found nothing to blame and fell off the end,
        returning None -- which every caller reads as "valid"."""
        value = "a" * 15 + char + "_" + "b" * 16
        assert len(value) == 33, "fixture must otherwise be well formed"
        assert char.isalnum(), f"fixture must be {why}"
        with pytest.raises(ValueError, match="must be alphanumeric"):
            mustBeID(value)

    def test_the_offending_character_and_its_position_are_named(self):
        value = "a" * 5 + "!" + "a" * 10 + "_" + "b" * 16
        with pytest.raises(ValueError, match="position 6"):
            mustBeID(value)


class TestMustBeEpochInput:
    """MATLAB counterpart: ``+ndi/+validators/mustBeEpochInput.m``."""

    @pytest.mark.parametrize("value", ["t00001", 1, 12345])
    def test_text_and_positive_integers_are_accepted(self, value):
        mustBeEpochInput(value)

    def test_a_non_positive_integer_is_rejected(self):
        with pytest.raises(ValueError):
            mustBeEpochInput(0)

    def test_an_empty_string_is_rejected(self):
        with pytest.raises(ValueError):
            mustBeEpochInput("")

    def test_a_list_is_rejected(self):
        """MATLAB's example: ``mustBeEpochInput([1 2 3])`` errors."""
        with pytest.raises(TypeError):
            mustBeEpochInput([1, 2, 3])

    def test_a_bool_is_not_an_epoch_number(self):
        """``True`` is an ``int`` in Python; MATLAB's mustBeInteger path
        takes a double, so a logical must not slip through as epoch 1."""
        with pytest.raises(TypeError):
            mustBeEpochInput(True)


class TestCellArrayValidators:
    """MATLAB counterparts: the three ``mustBeCellArrayOf*`` validators.

    MATLAB names the offending index (``Element %d``); these assert the
    Python messages do too, which is what a leaked mechanical rename of
    ``element`` had broken.
    """

    def test_a_list_of_the_required_class_is_accepted(self):
        mustBeCellArrayOfClass(["a", "b"], str)

    def test_a_wrong_element_is_named_by_index(self):
        with pytest.raises(TypeError, match=r"Element 1 is of class int"):
            mustBeCellArrayOfClass(["a", 2], str)

    def test_a_non_list_is_rejected(self):
        with pytest.raises(TypeError, match="list or tuple"):
            mustBeCellArrayOfClass("not a list", str)

    def test_an_empty_list_is_accepted(self):
        """MATLAB guards the loop with ``if ~isempty(value)``."""
        mustBeCellArrayOfClass([], str)
        mustBeCellArrayOfNonEmptyCharacterArrays([])

    def test_non_empty_character_arrays_are_required(self):
        mustBeCellArrayOfNonEmptyCharacterArrays(["a", "b"])
        with pytest.raises(ValueError, match=r"Element 1 is empty"):
            mustBeCellArrayOfNonEmptyCharacterArrays(["a", ""])
        with pytest.raises(TypeError, match=r"Element 0 is of type"):
            mustBeCellArrayOfNonEmptyCharacterArrays([1])


class TestTextAndNumericClassValidators:
    """MATLAB counterparts: ``mustBeTextLike.m``, ``mustBeNumericClass.m``."""

    @pytest.mark.parametrize("value", ["hello", ["a", "b"], ("a",), []])
    def test_text_like_values_are_accepted(self, value):
        mustBeTextLike(value)

    @pytest.mark.parametrize("value", [1, ["a", 2], None])
    def test_non_text_is_rejected(self, value):
        with pytest.raises(TypeError):
            mustBeTextLike(value)

    @pytest.mark.parametrize(
        "name",
        [
            "uint8",
            "uint16",
            "uint32",
            "uint64",
            "int8",
            "int16",
            "int32",
            "int64",
            "single",
            "double",
            "logical",
        ],
    )
    def test_every_matlab_numeric_class_name_is_accepted(self, name):
        """The exact list ``mustBeNumericClass.m`` enumerates."""
        mustBeNumericClass(name)

    def test_an_unknown_class_name_is_rejected(self):
        with pytest.raises(ValueError, match="valid numeric or logical class"):
            mustBeNumericClass("complex256")


class TestStructAndTableValidators:
    """MATLAB counterparts: ``mustHaveFields.m``, ``mustHaveRequiredColumns.m``,
    ``mustMatchRegex.m``."""

    def test_missing_fields_are_named(self):
        mustHaveFields({"a": 1, "b": 2}, ["a"])
        with pytest.raises(ValueError, match="missing fields: c"):
            mustHaveFields({"a": 1}, ["a", "c"])

    def test_a_non_mapping_is_rejected(self):
        with pytest.raises(TypeError):
            mustHaveFields("not a dict", ["a"])

    def test_missing_columns_are_named(self):
        pd = pytest.importorskip("pandas")
        frame = pd.DataFrame({"a": [1], "b": [2]})
        mustHaveRequiredColumns(frame, ["a", "b"])
        mustHaveRequiredColumns(frame, "a")  # MATLAB accepts a bare char row
        with pytest.raises(ValueError, match="missing required column"):
            mustHaveRequiredColumns(frame, ["a", "z"])

    def test_the_regex_must_match_the_whole_string(self):
        """MATLAB anchors the pattern as ``^(pattern)$``."""
        mustMatchRegex("ABC12345", r"[A-Z]{3}\d{5}")
        with pytest.raises(ValueError):
            mustMatchRegex("xABC12345", r"[A-Z]{3}\d{5}")
        with pytest.raises(ValueError):
            mustMatchRegex("ABC12345x", r"[A-Z]{3}\d{5}")
