"""A query's ``scope`` may name datasets, not just the three keywords.

MATLAB counterpart: ``+ndi/+cloud/+api/+documents/ndiquery.m`` and
``ndiqueryAll.m``, whose ``arguments`` blocks moved from
``mustBeMember(scope, ["public", "private", "all"])`` to a local
``iMustBeValidScope`` validator.

The widening is a capability, not a formality: a caller can now restrict a
query to particular datasets by passing their ObjectIds, and the server
returns only documents from the ones the caller may see, dropping the rest
without an error. Python's ``Scope`` was a ``Literal`` of the three
keywords, so ``validate_call`` rejected the new form before the request was
ever built -- the dataset-scoped query was unreachable from Python.

These check both halves: that the new form is accepted, and that the
validation MATLAB performs still happens. A widening that accepted anything
would pass the first half and lose the second.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError, validate_call

from ndi.cloud.api._validators import VALIDATE_CONFIG, Scope

DATASET_ID = "65a1b2c3d4e5f60718293a4b"
OTHER_ID = "65a1b2c3d4e5f60718293a4c"


@validate_call(config=VALIDATE_CONFIG)
def _takes_a_scope(scope: Scope) -> str:
    return scope


class TestTheKeywordsStillWork:
    @pytest.mark.parametrize("keyword", ["public", "private", "all"])
    def test_each_keyword_is_accepted(self, keyword):
        assert _takes_a_scope(keyword) == keyword


class TestDatasetIdsAreAccepted:
    def test_a_single_dataset_id(self):
        assert _takes_a_scope(DATASET_ID) == DATASET_ID

    def test_a_comma_separated_list(self):
        value = f"{DATASET_ID},{OTHER_ID}"
        assert _takes_a_scope(value) == value

    def test_surrounding_whitespace_is_tolerated(self):
        """MATLAB ``strtrim``s each element before checking it."""
        value = f"{DATASET_ID}, {OTHER_ID}"
        assert _takes_a_scope(value) == value

    def test_uppercase_hex_is_accepted(self):
        """The MATLAB regexp is ``[a-fA-F0-9]{24}``, not lowercase-only."""
        value = DATASET_ID.upper()
        assert _takes_a_scope(value) == value


class TestTheValidationIsRealAndStillRejects:
    """Widening a rule is only safe if it does not become "anything goes"."""

    @pytest.mark.parametrize(
        "value",
        [
            "publik",  # a near-miss keyword, which is how this gets typed
            "",  # no scope at all
            ",",  # a list of nothing
            "65a1b2c3d4e5f60718293a4",  # 23 characters
            "65a1b2c3d4e5f60718293a4bb",  # 25 characters
            "65a1b2c3d4e5f60718293a4g",  # 'g' is not hex
            f"{DATASET_ID},public",  # a keyword cannot join a list
        ],
    )
    def test_it_is_rejected(self, value):
        with pytest.raises(ValidationError):
            _takes_a_scope(value)
