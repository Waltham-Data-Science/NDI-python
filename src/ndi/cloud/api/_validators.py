"""Pydantic argument validators matching MATLAB arguments blocks.

Provides reusable ``Annotated`` types for cloud API functions.  Each type
maps to a specific MATLAB argument constraint:

    CloudId     -> (1,1) string   (non-empty resource identifier)
    NonEmptyStr -> (1,1) string   (non-empty general string)
    PageNumber  -> (1,1) double   (integer >= 1)
    PageSize    -> (1,1) double   (integer >= 1)
    Scope       -> visibility keyword ('public'/'private'/'all') OR a
                   comma-separated list of 24-hex dataset ids (MATLAB parity)
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


# -- scope: visibility keyword OR dataset-id(s) ------------------------------
# MATLAB's +cloud/+api/+documents iMustBeValidScope accepts 'public'/'private'/
# 'all' OR a comma-separated list of 24-hex dataset ObjectIds — the cloud
# /ndiquery endpoint is scope-first and treats a dataset id (or list) as a
# single-/multi-dataset query. The original Literal['public','private','all']
# was a too-narrow port that rejected dataset-scoped queries with a
# ValidationError before any HTTP call.
_SCOPE_KEYWORDS = ("public", "private", "all")
_OBJECTID_RE = re.compile(r"^[a-fA-F0-9]{24}$")


def _check_scope(v: str) -> str:
    if v in _SCOPE_KEYWORDS:
        return v
    parts = [p.strip() for p in v.split(",") if p.strip()]
    if parts and all(_OBJECTID_RE.match(p) for p in parts):
        # Return the NORMALIZED list (stripped, empty segments dropped) so a
        # stray space or trailing comma isn't forwarded verbatim to the cloud.
        return ",".join(parts)
    raise ValueError(
        f"scope must be one of {_SCOPE_KEYWORDS} or a comma-separated list of "
        f"24-character hex dataset ids; got {v!r}"
    )


Scope = Annotated[str, AfterValidator(_check_scope)]


# -- {mustBeFile}: file must exist on disk ------------------------------------
def _check_file_exists(v: str) -> str:
    if not Path(v).is_file():
        raise ValueError(f"File not found: {v}")
    return v


FilePath = Annotated[str, AfterValidator(_check_file_exists)]

# -- Shared validate_call config ---------------------------------------------
VALIDATE_CONFIG = ConfigDict(arbitrary_types_allowed=True)
