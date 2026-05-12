"""
ndi.util.matlab_regex - Translate MATLAB regex syntax to Python ``re`` syntax.

All user-facing NDI regex (file navigator ``filematch`` patterns,
ndi.file.navigator.rhd_series series/ancillary patterns, etc.) is
written in MATLAB regex syntax. The cross-language bridge yaml
documents MATLAB regex as the contract for those fields. This module
performs a minimum-viable translation from a MATLAB pattern to an
equivalent Python ``re`` pattern.

Translations performed
----------------------
* ``\\<``               -> ``\\b``   (MATLAB start-of-word anchor)
* ``\\>``               -> ``\\b``   (MATLAB end-of-word anchor)
* ``(?<name>...)``     -> ``(?P<name>...)``   (named capturing group)

The boundary translations only fire when the backslash is the regex
escape; a doubled backslash (``\\\\>``) which encodes a literal
backslash followed by ``>`` is left alone, as is a bare ``<`` or ``>``
that is not preceded by a backslash. ``(?<=...)`` lookbehinds are
preserved because they start with ``(?<=`` / ``(?<!`` rather than
``(?<<name>``.

The function is idempotent: a pattern that has already been through
the translator is unchanged when passed through a second time, because
``\\b`` has no MATLAB-only construct and ``(?P<name>...)`` does not
match the MATLAB named-group regex.

MATLAB regex features NOT yet handled (extend this module to add them)
---------------------------------------------------------------------
* POSIX character classes inside a class, e.g. ``[[:alpha:]]``,
  ``[[:digit:]]``, ``[[:space:]]``. Python ``re`` has no direct
  equivalent; would need expansion to explicit class contents.
* ``\\k<name>`` backreference to a named group (MATLAB) vs.
  ``(?P=name)`` in Python.
* ``(?#comment)`` is shared between the two flavors but with subtle
  rules; not normalized here.
* MATLAB's ``\\oNNN`` octal escape (Python uses ``\\NNN``).
* MATLAB's ``(?@command)``, ``(?(condition)yes|no)`` conditional
  patterns, and ``(?>...)`` atomic groups when used with MATLAB-only
  options.
* MATLAB ``(?i)``/``(?-i)`` inline flag scoping differs slightly from
  Python; we do not rewrite inline flags.
* MATLAB ``\\cX`` control-character escape (Python uses ``\\xNN``).
"""

from __future__ import annotations

import re

__all__ = ["matlab_to_python_regex"]


# Match an odd number of backslashes followed by '<' or '>'. The negative
# lookbehind anchors the backslash run to a non-backslash boundary so the
# count is exact: an even-length prefix is each pair of literal backslashes
# and the final \\ is the escape that owns the < or >.
_WORD_BOUNDARY_RE = re.compile(r"(?<!\\)(?P<bs>(?:\\\\)*)\\(?P<ch>[<>])")

# MATLAB named group (?<name>...) -> Python (?P<name>...). Exclude
# (?<=...) and (?<!...) lookbehind by requiring an identifier character
# right after '<'.
_NAMED_GROUP_RE = re.compile(r"\(\?<(?P<name>[A-Za-z_][A-Za-z0-9_]*)>")


def matlab_to_python_regex(pattern: str) -> str:
    """Translate a MATLAB regex pattern to an equivalent Python ``re`` pattern.

    The translation is minimum-viable: it covers MATLAB start/end-of-word
    boundaries (``\\<`` / ``\\>``) and MATLAB named capturing groups
    (``(?<name>...)``). All other constructs pass through unchanged.

    The function is pure and idempotent.

    Args:
        pattern: MATLAB-flavored regex string.

    Returns:
        Python ``re``-compatible regex string.
    """
    if not isinstance(pattern, str):
        raise TypeError(f"matlab_to_python_regex expected str, got {type(pattern).__name__}")

    def _boundary_sub(m: re.Match[str]) -> str:
        return f"{m.group('bs')}\\b"

    result = _WORD_BOUNDARY_RE.sub(_boundary_sub, pattern)
    result = _NAMED_GROUP_RE.sub(r"(?P<\g<name>>", result)
    return result
