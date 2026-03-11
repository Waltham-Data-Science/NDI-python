"""
ndi.util.datestamp2datetime

MATLAB equivalent: +ndi/+util/datestamp2datetime.m

Converts an NDI datestamp string to a Python ``datetime`` object.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pydantic


@pydantic.validate_call
def datestamp2datetime(datestampStr: str) -> datetime:
    """Convert an NDI datestamp string to a :class:`datetime.datetime`.

    MATLAB equivalent: ``ndi.util.datestamp2datetime(datestampStr)``

    The expected input format is ISO 8601 with milliseconds and timezone
    offset, e.g. ``'2023-01-01T12:00:00.000+00:00'``.  The returned
    datetime is always in UTC.

    Parameters
    ----------
    datestampStr : str
        An ISO 8601 datestamp string.

    Returns
    -------
    datetime.datetime
        A timezone-aware datetime in UTC.

    Raises
    ------
    ValidationError
        If *datestampStr* is not a string.
    ValueError
        If the string cannot be parsed.
    """
    dt = datetime.fromisoformat(datestampStr)
    return dt.astimezone(timezone.utc)
