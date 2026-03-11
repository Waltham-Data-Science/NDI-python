"""
ndi.util.rehydrateJSONNanNull

MATLAB equivalent: +ndi/+util/rehydrateJSONNanNull.m

Replaces NDI sentinel strings for NaN, Infinity, and -Infinity in JSON
text with Python-compatible representations.
"""

from __future__ import annotations


def rehydrateJSONNanNull(
    jsonText: str,
    *,
    nan_string: str = '"__NDI__NaN__"',
    inf_string: str = '"__NDI__Infinity__"',
    ninf_string: str = '"__NDI__-Infinity__"',
) -> str:
    """Replace NaN/Inf sentinel strings in JSON text.

    MATLAB equivalent:
    ``rehydratedJsonText = ndi.util.rehydrateJSONNanNull(jsonText)``

    By default performs the following replacements:

    * ``"__NDI__NaN__"``        → ``NaN``
    * ``"__NDI__Infinity__"``   → ``Infinity``
    * ``"__NDI__-Infinity__"``  → ``-Infinity``

    Parameters
    ----------
    jsonText : str
        The JSON string to process.
    nan_string : str, optional
        Sentinel for NaN.
    inf_string : str, optional
        Sentinel for Infinity.
    ninf_string : str, optional
        Sentinel for -Infinity.

    Returns
    -------
    str
        The JSON string with sentinels replaced.

    Raises
    ------
    TypeError
        If *jsonText* is not a string.
    """
    if not isinstance(jsonText, str):
        raise TypeError("Input must be a string.")

    result = jsonText
    result = result.replace(nan_string, "NaN")
    result = result.replace(inf_string, "Infinity")
    result = result.replace(ninf_string, "-Infinity")
    return result
