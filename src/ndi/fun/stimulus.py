"""
ndi.fun.stimulus - Stimulus analysis utility functions.

MATLAB equivalents: +ndi/+fun/+stimulus/f0_f1_responses.m,
    findMixtureName.m, tuning_curve_to_response_type.m,
    +ndi/+fun/stimulustemporalfrequency.m
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def tuning_curve_to_response_type(
    session: Any,
    doc: Any,
) -> tuple[str, Any | None]:
    """Resolve response type from a tuning curve document.

    MATLAB equivalent: ndi.fun.stimulus.tuning_curve_to_response_type

    Recursively follows dependencies to find the response type
    (``'mean'``, ``'F1'``, etc.).

    Args:
        session: NDI session instance.
        doc: A tuning curve document.

    Returns:
        Tuple of ``(response_type, stimulus_response_scalar_doc)``.
    """
    from ndi.query import Query

    props = doc.document_properties if hasattr(doc, "document_properties") else doc
    if not isinstance(props, dict):
        return "", None

    depends = props.get("depends_on", [])

    # Look for stimulus_response_scalar dependency
    for dep in depends:
        if not isinstance(dep, dict):
            continue
        dep_name = dep.get("name", "")
        dep_value = dep.get("value", "")
        if "stimulus_response_scalar" in dep_name and dep_value:
            results = session.database_search(Query("base.id") == dep_value)
            if results:
                scalar_doc = results[0]
                sp = (
                    scalar_doc.document_properties
                    if hasattr(scalar_doc, "document_properties")
                    else scalar_doc
                )
                if isinstance(sp, dict):
                    rt = sp.get("stimulus_response_scalar", {}).get("response_type", "")
                    if rt:
                        return rt, scalar_doc

    # Look for stimulus_tuningcurve dependency (recurse)
    for dep in depends:
        if not isinstance(dep, dict):
            continue
        dep_name = dep.get("name", "")
        dep_value = dep.get("value", "")
        if "stimulus_tuningcurve" in dep_name and dep_value:
            results = session.database_search(Query("base.id") == dep_value)
            if results:
                return tuning_curve_to_response_type(session, results[0])

    return "", None


def f0_f1_responses(
    session: Any,
    doc: Any,
    response_index: int | None = None,
) -> dict[str, Any]:
    """Extract F0 and F1 responses for a tuning curve.

    MATLAB equivalent: ndi.fun.stimulus.f0_f1_responses

    Args:
        session: NDI session instance.
        doc: A tuning curve document.
        response_index: Stimulus index (0-based). If None, uses max response.

    Returns:
        Dict with ``'f0'``, ``'f1'``, ``'response_type'`` keys.
    """
    response_type, scalar_doc = tuning_curve_to_response_type(session, doc)

    props = doc.document_properties if hasattr(doc, "document_properties") else doc
    if not isinstance(props, dict):
        return {"f0": None, "f1": None, "response_type": response_type}

    tc_data = props.get("stimulus_tuningcurve", {})
    responses = tc_data.get("responses", [])

    if not responses:
        return {"f0": None, "f1": None, "response_type": response_type}

    if response_index is not None and 0 <= response_index < len(responses):
        val = responses[response_index]
    else:
        # Use max
        val = max(responses) if responses else None

    return {
        "f0": val if response_type == "mean" else None,
        "f1": val if response_type == "F1" else None,
        "response_type": response_type,
    }


def find_mixture_name(
    dictionary_path: str,
    mixture: list[dict[str, Any]],
) -> list[str]:
    """Match mixture against a JSON mixture dictionary.

    MATLAB equivalent: ndi.fun.stimulus.findMixtureName

    Args:
        dictionary_path: Path to the mixture dictionary JSON file.
        mixture: List of dicts with ``ontologyName``, ``name``,
            ``value``, ``ontologyUnit``, ``unitName`` keys.

    Returns:
        List of matching entry names from the dictionary.
    """
    p = Path(dictionary_path)
    if not p.exists():
        return []

    with open(p) as f:
        dictionary = json.load(f)

    if not isinstance(dictionary, dict):
        return []

    matches: list[str] = []
    compare_fields = ["ontologyName", "name", "value", "ontologyUnit", "unitName"]

    for entry_name, entry_components in dictionary.items():
        if not isinstance(entry_components, list):
            continue
        if len(entry_components) != len(mixture):
            continue

        # Sort both by name for order-independent comparison
        sorted_entry = sorted(entry_components, key=lambda x: x.get("name", ""))
        sorted_mix = sorted(mixture, key=lambda x: x.get("name", ""))

        all_match = True
        for ec, mc in zip(sorted_entry, sorted_mix):
            for field in compare_fields:
                if str(ec.get(field, "")) != str(mc.get(field, "")):
                    all_match = False
                    break
            if not all_match:
                break

        if all_match:
            matches.append(entry_name)

    return matches


def stimulus_temporal_frequency(
    stimulus_parameters: dict[str, Any],
    config_path: str | None = None,
) -> tuple[float | None, str]:
    """Extract temporal frequency from stimulus parameters.

    MATLAB equivalent: ndi.fun.stimulustemporalfrequency

    Uses a JSON config that maps parameter names to temporal frequency
    with optional multiplier, adder, and period-inversion.

    Args:
        stimulus_parameters: Dict of stimulus parameter values.
        config_path: Path to config JSON. Uses default if not provided.

    Returns:
        Tuple of ``(tf_value, param_name)`` or ``(None, '')`` if no match.
    """
    if config_path is None:
        try:
            from ndi.common import PathConstants

            config_path = str(
                PathConstants.COMMON_FOLDER / "stimulus" / "temporal_frequency_rules.json"
            )
        except Exception:
            return None, ""

    p = Path(config_path)
    if not p.exists():
        return None, ""

    with open(p) as f:
        rules = json.load(f)

    if not isinstance(rules, list):
        rules = rules.get("rules", []) if isinstance(rules, dict) else []

    for rule in rules:
        param_name = rule.get("parameterName", "")
        if param_name not in stimulus_parameters:
            continue

        val = stimulus_parameters[param_name]
        if not isinstance(val, (int, float)):
            continue

        multiplier = rule.get("multiplier", 1.0)
        adder = rule.get("adder", 0.0)
        is_period = rule.get("isPeriod", False)

        tf = val * multiplier + adder

        if is_period:
            if tf == 0:
                continue
            tf = 1.0 / tf

        # Optional secondary parameter multiplication
        secondary = rule.get("multiplyByParameter", "")
        if secondary and secondary in stimulus_parameters:
            sec_val = stimulus_parameters[secondary]
            if isinstance(sec_val, (int, float)):
                tf *= sec_val

        return tf, param_name

    return None, ""


def stimulus_tuningcurve_log(
    session: Any,
    doc: Any,
) -> str:
    """Retrieve the log string from a dependent tuningcurve_calc document.

    MATLAB equivalent: ndi.fun.calc.stimulus_tuningcurve_log

    Given a document with a ``stimulus_tuningcurve_id`` dependency,
    looks up the corresponding ``tuningcurve_calc`` document and
    returns its ``log`` field.

    Args:
        session: NDI session instance.
        doc: An NDI document with ``stimulus_tuningcurve_id`` dependency.

    Returns:
        The log string, or ``''`` if not found.
    """
    from ndi.query import Query

    props = doc.document_properties if hasattr(doc, "document_properties") else doc
    if not isinstance(props, dict):
        return ""

    # Find the stimulus_tuningcurve_id dependency value
    stim_tune_doc_id = ""
    for dep in props.get("depends_on", []):
        if isinstance(dep, dict) and dep.get("name", "") == "stimulus_tuningcurve_id":
            stim_tune_doc_id = dep.get("value", "")
            break

    if not stim_tune_doc_id:
        return ""

    q = (Query("base.id") == stim_tune_doc_id) & Query("").isa("tuningcurve_calc")
    results = session.database_search(q)

    if results:
        rp = (
            results[0].document_properties
            if hasattr(results[0], "document_properties")
            else results[0]
        )
        if isinstance(rp, dict):
            return rp.get("tuningcurve_calc", {}).get("log", "")

    return ""
