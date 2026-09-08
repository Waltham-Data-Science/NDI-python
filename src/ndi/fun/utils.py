"""
ndi.fun.utils - General utility functions.

MATLAB equivalents: +ndi/+fun/channelname2prefixnumber.m,
    name2variableName.m, pseudorandomint.m, timestamp.m
"""

from __future__ import annotations

import random
import re
from datetime import datetime, timezone


def channelname2prefixnumber(channelname: str) -> tuple[str, int]:
    """Parse channel name into prefix and number.

    MATLAB equivalent: ndi.fun.channelname2prefixnumber

    Args:
        channelname: Channel string like ``'ai5'`` or ``'dev1'``.

    Returns:
        Tuple of ``(prefix, number)``, e.g. ``('ai', 5)``.

    Raises:
        ValueError: If no digits found or name starts with a digit.
    """
    m = re.search(r"\d", channelname)
    if m is None:
        raise ValueError(f"No digits found in channel name '{channelname}'")
    idx = m.start()
    if idx == 0:
        raise ValueError(f"Channel name '{channelname}' starts with a digit")
    prefix = channelname[:idx].strip()
    number = int(channelname[idx:])
    return prefix, number


def name2variableName(name: str) -> str:
    """Convert arbitrary string to a camelCase variable name.

    MATLAB equivalent: ndi.fun.name2variableName

    Replaces non-alphanumeric chars (except underscore) with spaces,
    splits into words, capitalises each, concatenates.  Prepends ``'x'``
    if the result starts with a digit.

    Args:
        name: Arbitrary string.

    Returns:
        camelCase variable name.
    """
    if not name:
        return ""
    # Replace non-alphanumeric (except underscore) with space
    cleaned = re.sub(r"[^a-zA-Z0-9_]", " ", name)
    words = cleaned.split()
    if not words:
        return ""
    # CamelCase: first word lowercase, rest capitalised
    parts = [words[0].lower()] + [w.capitalize() for w in words[1:]]
    result = "".join(parts)
    # Prepend 'x' if starts with digit
    if result and result[0].isdigit():
        result = "x" + result
    return result


# Backward-compatible alias
name2variable_name = name2variableName


def pseudorandomint() -> int:
    """Generate a pseudo-random integer from date/time + random component.

    MATLAB equivalent: ndi.fun.pseudorandomint

    Returns seconds since 2022-06-01 * 1000 + random(1..1000),
    guaranteeing ~1000 unique values per second.

    Returns:
        Positive integer.
    """
    epoch = datetime(2022, 6, 1, tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    seconds = int((now - epoch).total_seconds())
    # MATLAB is `t_offset*1000 + randi(1000) - 1`, and its own comment spells
    # that out: "random number between 1 and 1000, -1". The -1 was dropped
    # here, shifting every value by one against the MATLAB.
    return seconds * 1000 + random.randint(1, 1000) - 1


def timestamp() -> str:
    """Return current UTC timestamp string.

    MATLAB equivalent: ``ndi.fun.timestamp``, which is
    ``char(datetime('now','TimeZone','UTCLeapSeconds'))`` -- a format that
    ends in a ``Z``.

    THE ZONE DESIGNATOR IS NOT DECORATION. Without it this function emitted
    ``2026-09-08T02:25:18.707``, which :func:`ndi.util.datestamp2datetime`
    refuses, so two functions in this same package did not compose. It also
    disagreed with :func:`ndi.common.timestamp`, which does emit the ``Z``
    and is what ``ndi_document`` stamps documents with -- and every datestamp
    in ``ndi_common/`` carries one.

    Handles the leap-second artefact the MATLAB does: a rounded ``60.000``
    seconds field fails document validation, so it becomes ``59.999``.

    Returns:
        A UTC timestamp string ending in ``Z``.
    """
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
    # MATLAB rewrites the six characters before the trailing Z, so replace
    # the seconds field itself rather than a substring of it: replacing
    # ":60." with ":59.999" would leave the old fraction appended.
    if ts.endswith(":60.000"):
        ts = ts[: -len(":60.000")] + ":59.999"
    return ts + "Z"


def identifier(obj) -> str | None:
    """The id of an NDI object, whether ``id`` is a method or a property.

    Python only; MATLAB has one spelling, ``obj.id()``, and every port of a
    MATLAB call site reaches for it. This side is not uniform: a session's
    ``id`` IS a method, while a document's, an element's and a probe's are
    properties inherited from :class:`ndi.ido.ndi_ido`. So ``probe.id()``
    raises ``TypeError: 'str' object is not callable`` on a real probe while
    passing every test whose double defines ``id`` as a method -- a failure
    that appears only against real objects.

    Reading it either way costs nothing and removes a whole class of that
    mistake from the ported call sites. Returns None when OBJ has no id at
    all, which is what a caller building a query wants to notice.
    """
    value = getattr(obj, "id", None)
    return value() if callable(value) else value
