"""Pydantic argument validators matching MATLAB arguments blocks.

Provides reusable ``Annotated`` types for cloud API functions.  Each type
maps to a specific MATLAB argument constraint:

    CloudId     -> (1,1) string   (non-empty resource identifier)
    NonEmptyStr -> (1,1) string   (non-empty general string)
    PageNumber  -> (1,1) double   (integer >= 1)
    PageSize    -> (1,1) double   (integer >= 1)
    Scope       -> {iMustBeValidScope} (keyword, or dataset-id list)
    FilePath    -> {mustBeFile}   (file must exist on disk)

Usage::

    from pydantic import validate_call
    from ._validators import CloudId, PageNumber, VALIDATE_CONFIG

    @_auto_client
    @validate_call(config=VALIDATE_CONFIG)
    def get_dataset(dataset_id: CloudId, *, client: CloudClient | None = None):
        ...
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

from pydantic import AfterValidator, ConfigDict, Field

# -- (1,1) string: non-empty scalar string -----------------------------------
CloudId = Annotated[str, Field(min_length=1)]
NonEmptyStr = Annotated[str, Field(min_length=1)]

# -- (1,1) double: pagination integers ---------------------------------------
PageNumber = Annotated[int, Field(ge=1)]
PageSize = Annotated[int, Field(ge=1)]

# -- {iMustBeValidScope} -----------------------------------------------------
#: The three keyword scopes. A query may instead name specific datasets.
SCOPE_KEYWORDS = ("public", "private", "all")

#: A dataset ObjectId as the cloud writes them.
_DATASET_ID = re.compile(r"^[a-fA-F0-9]{24}$")


def _check_scope(value: str) -> str:
    """A scope keyword, or a comma-separated list of dataset ObjectIds.

    MATLAB widened this from ``mustBeMember`` to ``iMustBeValidScope`` so a
    query can be scoped to particular datasets; the server then returns only
    documents from the datasets the user can see, dropping the rest
    silently. A ``Literal`` of the three keywords rejects that form outright,
    which is why this is a validator rather than an enum.
    """
    if value in SCOPE_KEYWORDS:
        return value
    parts = [part.strip() for part in value.split(",")]
    parts = [part for part in parts if part]
    if not parts:
        raise ValueError(
            "scope must be 'public', 'private', 'all', or a comma-separated "
            "list of 24-character hex dataset IDs"
        )
    for part in parts:
        if not _DATASET_ID.match(part):
            raise ValueError(f"scope entry {part!r} is not a valid 24-character hex dataset ID")
    return value


Scope = Annotated[str, AfterValidator(_check_scope)]


# -- {mustBeFile}: file must exist on disk ------------------------------------
def _check_file_exists(v: str) -> str:
    if not Path(v).is_file():
        raise ValueError(f"File not found: {v}")
    return v


FilePath = Annotated[str, AfterValidator(_check_file_exists)]

# -- Shared validate_call config ---------------------------------------------
VALIDATE_CONFIG = ConfigDict(arbitrary_types_allowed=True)
