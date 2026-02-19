"""
ndi.fun.name_utils - Name conversion utilities.

MATLAB equivalent: +ndi/+fun/name2variableName.m

Provides utilities for converting human-readable names into
programming-safe variable names (PascalCase with underscores).
"""

from __future__ import annotations

import re


def name_to_variable_name(name: str) -> str:
    """Convert a human-readable name to a PascalCase variable name.

    MATLAB equivalent: ndi.fun.name2variableName

    Algorithm (matching MATLAB):
      1. Replace ``:`` and ``-`` with ``_``
      2. Replace other non-alphanumeric chars (except ``_``) with spaces
      3. Split into words, capitalize the first letter of each
      4. Join without spaces
      5. Prepend ``var_`` if result doesn't start with a letter
      6. Remove any remaining invalid characters

    Examples::

        >>> name_to_variable_name("treatment: food restriction onset time")
        'Treatment_FoodRestrictionOnsetTime'
        >>> name_to_variable_name("Optogenetic Tetanus Stimulation Target Location")
        'OptogeneticTetanusStimulationTargetLocation'
        >>> name_to_variable_name("elevated plus maze: test duration")
        'ElevatedPlusMaze_TestDuration'

    Args:
        name: Human-readable name string.

    Returns:
        PascalCase variable-safe string.
    """
    if not name or name.isspace():
        return ""

    # Step 1: Replace ':' and '-' with '_'
    s = name.replace(":", "_").replace("-", "_")

    # Step 2: Replace non-alphanumeric (except '_') with spaces
    s = re.sub(r"[^a-zA-Z0-9_]", " ", s)

    # Step 3-4: Split, capitalize first letter of each word, join
    words = s.split()
    capitalized = []
    for w in words:
        if w:
            capitalized.append(w[0].upper() + w[1:])
    result = "".join(capitalized)

    # Step 5: Ensure starts with a letter
    if result and not result[0].isalpha():
        result = "var_" + result

    # Step 6: Final cleanup — keep only letters, digits, underscores
    result = re.sub(r"[^a-zA-Z0-9_]", "", result)

    return result
