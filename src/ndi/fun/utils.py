"""
ndi.fun.utils - General utility functions.

MATLAB equivalents: +ndi/+fun/channelname2prefixnumber.m,
    name2variableName.m, pseudorandomint.m, timestamp.m
"""

from __future__ import annotations

import random
import re
from datetime import datetime, timezone
from typing import Tuple


def channelname2prefixnumber(channelname: str) -> Tuple[str, int]:
    """Parse channel name into prefix and number.

    MATLAB equivalent: ndi.fun.channelname2prefixnumber

    Args:
        channelname: Channel string like ``'ai5'`` or ``'dev1'``.

    Returns:
        Tuple of ``(prefix, number)``, e.g. ``('ai', 5)``.

    Raises:
        ValueError: If no digits found or name starts with a digit.
    """
    m = re.search(r'\d', channelname)
    if m is None:
        raise ValueError(f"No digits found in channel name '{channelname}'")
    idx = m.start()
    if idx == 0:
        raise ValueError(f"Channel name '{channelname}' starts with a digit")
    prefix = channelname[:idx].strip()
    number = int(channelname[idx:])
    return prefix, number


def name2variable_name(name: str) -> str:
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
        return ''
    # Replace non-alphanumeric (except underscore) with space
    cleaned = re.sub(r'[^a-zA-Z0-9_]', ' ', name)
    words = cleaned.split()
    if not words:
        return ''
    # CamelCase: first word lowercase, rest capitalised
    parts = [words[0].lower()] + [w.capitalize() for w in words[1:]]
    result = ''.join(parts)
    # Prepend 'x' if starts with digit
    if result and result[0].isdigit():
        result = 'x' + result
    return result


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
    return seconds * 1000 + random.randint(1, 1000)


def timestamp() -> str:
    """Return current UTC timestamp string.

    MATLAB equivalent: ndi.fun.timestamp

    Handles leap-second artefact by clamping second=60 to 59.999.

    Returns:
        ISO-style UTC timestamp string.
    """
    now = datetime.now(timezone.utc)
    ts = now.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]
    # Leap-second guard (Python doesn't really produce :60 but be safe)
    ts = ts.replace(':60.', ':59.999')
    return ts
