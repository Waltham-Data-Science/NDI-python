"""
ndi.doc_comparison - Parameterized document comparison.

MATLAB equivalent: +ndi/+database/+doctools/docComparison.m

Provides a configurable document comparison engine supporting
multiple comparison methods per field.
"""

from __future__ import annotations

import json
import math
from typing import Any


class DocComparison:
    """Parameterized comparison between NDI documents.

    Supports configurable comparison methods per field:
    ``'none'``, ``'abs_difference'``, ``'difference'``,
    ``'abs_percent_difference'``, ``'percent_difference'``,
    ``'character_exact'``, ``'p_value_consistent'``.

    MATLAB equivalent: ndi.database.doctools.docComparison

    Example:
        >>> dc = DocComparison()
        >>> dc.add_comparison_parameter('base.id', 'none')
        >>> dc.add_comparison_parameter('response.mean', 'abs_difference', tolerance=0.01)
        >>> result = dc.compare(doc1, doc2)
        >>> print(result['equal'])
    """

    METHODS = (
        "none",
        "abs_difference",
        "difference",
        "abs_percent_difference",
        "percent_difference",
        "character_exact",
        "p_value_consistent",
    )

    def __init__(self) -> None:
        self._parameters: list[dict[str, Any]] = []

    def add_comparison_parameter(
        self,
        field_path: str,
        method: str = "none",
        *,
        tolerance: float = 0.0,
        scope: str = "",
    ) -> None:
        """Add a comparison parameter for a specific field.

        Args:
            field_path: Dot-separated path (e.g. ``'response.mean'``).
            method: Comparison method name.
            tolerance: Allowed tolerance for numeric comparisons.
            scope: Optional scope filter string.

        Raises:
            ValueError: If method is not recognized.
        """
        method_lower = method.lower().replace(" ", "_")
        if method_lower not in self.METHODS:
            raise ValueError(
                f"Unknown comparison method: '{method}'. "
                f"Valid methods: {', '.join(self.METHODS)}"
            )

        self._parameters.append(
            {
                "field_path": field_path,
                "method": method_lower,
                "tolerance": tolerance,
                "scope": scope,
            }
        )

    def compare(
        self,
        doc1: Any,
        doc2: Any,
    ) -> dict[str, Any]:
        """Compare two documents using configured parameters.

        Args:
            doc1: First document.
            doc2: Second document.

        Returns:
            Dict with ``'equal'`` (bool), ``'results'`` (list of per-field
            results), and ``'summary'`` (string).
        """
        p1 = doc1.document_properties if hasattr(doc1, "document_properties") else doc1
        p2 = doc2.document_properties if hasattr(doc2, "document_properties") else doc2

        results: list[dict[str, Any]] = []
        all_pass = True

        for param in self._parameters:
            field = param["field_path"]
            method = param["method"]
            tol = param["tolerance"]

            v1 = _get_value(p1, field)
            v2 = _get_value(p2, field)

            passed, detail = _perform_check(method, v1, v2, tol)
            if not passed:
                all_pass = False

            results.append(
                {
                    "field": field,
                    "method": method,
                    "value1": v1,
                    "value2": v2,
                    "passed": passed,
                    "detail": detail,
                }
            )

        return {
            "equal": all_pass,
            "results": results,
            "summary": "All checks passed" if all_pass else "Some checks failed",
        }

    def matches_scope(self, scope: str) -> list[dict[str, Any]]:
        """Return comparison parameters matching a scope.

        Args:
            scope: Scope filter string.

        Returns:
            List of matching parameter dicts.
        """
        if not scope:
            return list(self._parameters)
        return [p for p in self._parameters if p.get("scope", "") == scope]

    def to_json(self) -> str:
        """Serialize the comparison configuration to JSON.

        Returns:
            JSON string.
        """
        return json.dumps(
            {
                "parameters": self._parameters,
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, json_str: str) -> DocComparison:
        """Create a DocComparison from a JSON string.

        Args:
            json_str: JSON configuration string.

        Returns:
            New DocComparison instance.
        """
        data = json.loads(json_str)
        dc = cls()
        for p in data.get("parameters", []):
            dc.add_comparison_parameter(
                field_path=p["field_path"],
                method=p["method"],
                tolerance=p.get("tolerance", 0.0),
                scope=p.get("scope", ""),
            )
        return dc

    def __repr__(self) -> str:
        return f"DocComparison(parameters={len(self._parameters)})"


def _get_value(props: Any, field_path: str) -> Any:
    """Navigate a nested dict by dot-separated path."""
    if not isinstance(props, dict):
        return None
    parts = field_path.split(".")
    current = props
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _perform_check(
    method: str,
    v1: Any,
    v2: Any,
    tolerance: float,
) -> tuple[bool, str]:
    """Perform a single comparison check."""
    if method == "none":
        return True, "skipped"

    if method == "character_exact":
        passed = str(v1) == str(v2)
        return passed, f"{v1!r} vs {v2!r}"

    # Numeric methods
    try:
        n1 = float(v1) if v1 is not None else float("nan")
        n2 = float(v2) if v2 is not None else float("nan")
    except (TypeError, ValueError):
        return v1 == v2, f"{v1!r} vs {v2!r}"

    if math.isnan(n1) or math.isnan(n2):
        passed = math.isnan(n1) and math.isnan(n2)
        return passed, f"{n1} vs {n2}"

    if method == "difference":
        diff = n1 - n2
        passed = abs(diff) <= tolerance
        return passed, f"diff={diff:.6g}"

    if method == "abs_difference":
        diff = abs(n1 - n2)
        passed = diff <= tolerance
        return passed, f"abs_diff={diff:.6g}"

    if method == "percent_difference":
        if n2 == 0:
            return n1 == 0, "denominator is zero"
        pct = (n1 - n2) / abs(n2) * 100
        passed = abs(pct) <= tolerance
        return passed, f"pct_diff={pct:.4g}%"

    if method == "abs_percent_difference":
        if n2 == 0:
            return n1 == 0, "denominator is zero"
        pct = abs(n1 - n2) / abs(n2) * 100
        passed = pct <= tolerance
        return passed, f"abs_pct_diff={pct:.4g}%"

    if method == "p_value_consistent":
        # p-value should be above tolerance (e.g. 0.05)
        passed = n1 >= tolerance
        return passed, f"p_value={n1:.4g} >= {tolerance}"

    return True, "unknown method"
