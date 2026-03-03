"""Pydantic argument validators matching MATLAB arguments blocks.

Provides reusable ``Annotated`` types for cloud API functions.  Each type
maps to a specific MATLAB argument constraint:

    CloudId     -> (1,1) string   (non-empty resource identifier)
    NonEmptyStr -> (1,1) string   (non-empty general string)
    PageNumber  -> (1,1) double   (integer >= 1)
    PageSize    -> (1,1) double   (integer >= 1)
    Scope       -> {mustBeMember} (Literal enum)
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

from pathlib import Path
from typing import Annotated, Literal

from pydantic import AfterValidator, ConfigDict, Field

# -- (1,1) string: non-empty scalar string -----------------------------------
CloudId = Annotated[str, Field(min_length=1)]
NonEmptyStr = Annotated[str, Field(min_length=1)]

# -- (1,1) double: pagination integers ---------------------------------------
PageNumber = Annotated[int, Field(ge=1)]
PageSize = Annotated[int, Field(ge=1)]

# -- {mustBeMember(scope, ["public", "private", "all"])} ---------------------
Scope = Literal["public", "private", "all"]


# -- {mustBeFile}: file must exist on disk ------------------------------------
def _check_file_exists(v: str) -> str:
    if not Path(v).is_file():
        raise ValueError(f"File not found: {v}")
    return v


FilePath = Annotated[str, AfterValidator(_check_file_exists)]

# -- Shared validate_call config ---------------------------------------------
VALIDATE_CONFIG = ConfigDict(arbitrary_types_allowed=True)
