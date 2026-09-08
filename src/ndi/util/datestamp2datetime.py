"""
ndi.util.datestamp2datetime

MATLAB equivalent: +ndi/+util/datestamp2datetime.m

Converts an NDI datestamp string to a Python ``datetime`` object.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pydantic

#: Why a datestamp with no offset is refused rather than assumed to be UTC.
#:
#: ``datetime.astimezone`` on a NAIVE datetime does not assume UTC -- it
#: assumes the LOCAL SYSTEM timezone and converts from there. So
#: ``'2023-01-01T12:00:00.000'`` silently became 17:00Z on a machine in New
#: York and 03:00Z on one in Tokyo: the same input, a different instant, with
#: nothing to indicate anything had been guessed. MATLAB does not have the
#: option, because its InputFormat ends in ``XXX`` and simply fails to parse
#: a string with no offset. Failing is the honest answer here too.
_NAIVE = (
    "datestamp {datestampStr!r} carries no UTC offset. Give one explicitly "
    "(a trailing 'Z', or '+00:00'): a naive datestamp would otherwise be read "
    "as local system time, which makes the result depend on the machine."
)


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

    A trailing ``Z`` is accepted, and is how ``ndi.common.timestamp`` and
    the documents under ``ndi_common/`` actually spell UTC.

    The offset is REQUIRED, as it is in the MATLAB ``InputFormat``
    (``...SSSXXX``): see :data:`_NAIVE`.

    Raises
    ------
    ValidationError
        If *datestampStr* is not a string.
    ValueError
        If the string cannot be parsed, or carries no UTC offset.
    """
    # datetime.fromisoformat did not accept a trailing 'Z' until Python
    # 3.11, and this project supports 3.10. Passing the repo's OWN datestamp
    # format ('2018-12-05T18:36:47.241Z', what ndi.common.timestamp writes)
    # straight to fromisoformat therefore raised ValueError on 3.10 while
    # working everywhere else. MATLAB's XXX accepts 'Z' on every platform.
    text = datestampStr.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"

    dt = datetime.fromisoformat(text)

    if dt.tzinfo is None:
        raise ValueError(_NAIVE.format(datestampStr=datestampStr))

    return dt.astimezone(timezone.utc)
