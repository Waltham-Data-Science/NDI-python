"""
ndi.fun.stimulus - Stimulus analysis utility functions.

MATLAB equivalents: +ndi/+fun/+stimulus/f0_f1_responses.m,
    findMixtureName.m, tuning_curve_to_response_type.m,
    whatVaries.m, whatIsConstant.m, whatVaries_parameterList.m,
    +ndi/+fun/stimulustemporalfrequency.m
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np


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
    from ndi.query import ndi_query

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
            results = session.database_search(ndi_query("base.id") == dep_value)
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
            results = session.database_search(ndi_query("base.id") == dep_value)
            if results:
                return tuning_curve_to_response_type(session, results[0])

    return "", None


def f0_f1_responses(
    session: Any,
    doc: Any,
    response_index: int | None = None,
) -> tuple[Any, Any, Any | None, Any | None]:
    """Extract F0 and F1 responses for a tuning curve.

    MATLAB equivalent: ndi.fun.stimulus.f0_f1_responses

    Args:
        session: NDI session instance.
        doc: A tuning curve document.
        response_index: Stimulus index (0-based). If None, uses max response.

    Returns:
        Tuple of ``(f0, f1, f0_tuningcurve_doc, f1_tuningcurve_doc)``
        where *f0* and *f1* are the response values (or None), and
        *f0_tuningcurve_doc* and *f1_tuningcurve_doc* are the
        corresponding tuning curve documents (or None).
    """
    response_type, scalar_doc = tuning_curve_to_response_type(session, doc)

    props = doc.document_properties if hasattr(doc, "document_properties") else doc
    if not isinstance(props, dict):
        return None, None, None, None

    tc_data = props.get("stimulus_tuningcurve", {})
    responses = tc_data.get("responses", [])

    if not responses:
        return None, None, None, None

    if response_index is not None and 0 <= response_index < len(responses):
        val = responses[response_index]
    else:
        # Use max
        val = max(responses) if responses else None

    f0 = val if response_type == "mean" else None
    f1 = val if response_type == "F1" else None
    f0_doc = doc if response_type == "mean" else None
    f1_doc = doc if response_type == "F1" else None

    return f0, f1, f0_doc, f1_doc


def findMixtureName(
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


def stimulustemporalfrequency(
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
            from ndi.common import ndi_common_PathConstants

            config_path = str(
                ndi_common_PathConstants.COMMON_FOLDER
                / "stimulus"
                / "temporal_frequency_rules.json"
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
    from ndi.query import ndi_query

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

    q = (ndi_query("base.id") == stim_tune_doc_id) & ndi_query("").isa("tuningcurve_calc")
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


# ===========================================================================
# What varies / what is constant across a set of stimuli
#
# MATLAB: +ndi/+fun/+stimulus/{whatVaries,whatIsConstant,
#         whatVaries_parameterList}.m  (origin/main @ fa5542b32)
# ===========================================================================


def _is_document(obj: Any) -> bool:
    """True for an ndi.document (duck-typed on ``document_properties``)."""
    return hasattr(obj, "document_properties")


def _document_id(doc: Any) -> str:
    """Best-effort document id, for error messages only."""
    try:
        did = doc.id
        return str(did() if callable(did) else did)
    except Exception:
        return "<unknown>"


def _stimuli_parameters(stimuli: Any) -> list[dict[str, Any]]:
    """The ``parameters`` of a ``stimulus_presentation.stimuli`` list.

    MATLAB equivalent: whatVaries_parameterList/local_stimuliParameters.
    """
    if stimuli is None:
        return []
    if isinstance(stimuli, Mapping):
        stimuli = [stimuli]

    params: list[dict[str, Any]] = []
    for index, stimulus in enumerate(stimuli):
        # a stimulus without parameters would silently contribute an empty
        # parameter set, which makes every other parameter look like it varies.
        # MATLAB raises here too ("Reference to non-existent field
        # 'parameters'"), so this is a wrong answer avoided, not a new rule.
        is_stimulus = isinstance(stimulus, Mapping) and isinstance(
            stimulus.get("parameters"), Mapping
        )
        if not is_stimulus:
            raise ValueError(
                "ndi:fun:stimulus:whatVaries_parameterList:badStimulus: "
                f"stimulus_presentation.stimuli[{index}] has no 'parameters' "
                f"dict (got a {type(stimulus).__name__})."
            )
        params.append(dict(stimulus["parameters"]))
    return params


def _presentation_parameters(props: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The parameter dicts held in one ``document_properties``-shaped mapping."""
    presentation = props.get("stimulus_presentation")
    if not isinstance(presentation, Mapping):
        return []
    return _stimuli_parameters(presentation.get("stimuli", []))


def _doc_parameters(doc: Any) -> list[dict[str, Any]]:
    """The parameter dicts held in a single ``stimulus_presentation`` document.

    MATLAB equivalent: whatVaries_parameterList/local_docParameters.
    """
    props = doc.document_properties
    if not isinstance(props, Mapping) or "stimulus_presentation" not in props:
        raise ValueError(
            "ndi:fun:stimulus:whatVaries_parameterList:notPresentation: "
            f"ndi.document (id {_document_id(doc)}) does not have a "
            "stimulus_presentation field."
        )
    return _presentation_parameters(props)


def _mapping_parameters(entry: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Normalize one mapping to a list of parameter dicts.

    A mapping shaped like ``document_properties`` (it has a
    ``stimulus_presentation`` mapping) is expanded to all of its stimuli; a
    mapping shaped like one ``stimulus_presentation.stimuli`` entry (it has a
    ``parameters`` mapping) yields that one parameter dict; anything else is
    taken to be a parameter dict itself.
    """
    if isinstance(entry.get("stimulus_presentation"), Mapping):
        return _presentation_parameters(entry)
    if isinstance(entry.get("parameters"), Mapping):
        return [dict(entry["parameters"])]
    return [dict(entry)]


def whatVaries_parameterList(stimuli: Any) -> list[dict[str, Any]]:
    """Normalize assorted stimulus inputs to a flat list of parameter dicts.

    MATLAB equivalent: ndi.fun.stimulus.whatVaries_parameterList

    Lets the rest of :mod:`ndi.fun.stimulus` treat every accepted input shape
    uniformly. *stimuli* may be:

    * an ``ndi.document`` of type ``stimulus_presentation`` (parameters are
      read from
      ``document_properties['stimulus_presentation']['stimuli'][i]['parameters']``);
    * a list mixing such documents, ``document_properties``-shaped dicts,
      ``stimulus_presentation.stimuli``-shaped dicts (having a ``parameters``
      key), and/or bare parameter dicts -- all pooled, in order;
    * a single dict in any of those three shapes.

    Args:
        stimuli: The stimuli, in any of the shapes above.

    Returns:
        A list of parameter dicts (possibly empty).

    Raises:
        TypeError: If *stimuli*, or one entry of a list, is not one of the
            accepted shapes.
        ValueError: If a document has no ``stimulus_presentation``, or a
            ``stimulus_presentation.stimuli`` entry has no ``parameters``.
    """
    if _is_document(stimuli):
        return _doc_parameters(stimuli)

    if isinstance(stimuli, Mapping):
        return _mapping_parameters(stimuli)

    if isinstance(stimuli, Sequence) and not isinstance(stimuli, (str, bytes)):
        params: list[dict[str, Any]] = []
        for entry in stimuli:
            if _is_document(entry):
                params.extend(_doc_parameters(entry))
            elif isinstance(entry, Mapping):
                params.extend(_mapping_parameters(entry))
            else:
                raise TypeError(
                    "ndi:fun:stimulus:whatVaries_parameterList:badCellEntry: "
                    "each list entry must be an ndi.document or a parameter "
                    f"dict. Got a {type(entry).__name__}."
                )
        return params

    raise TypeError(
        "ndi:fun:stimulus:whatVaries_parameterList:badInput: stimuli must be "
        "an ndi.document, a list, or a dict. Got a "
        f"{type(stimuli).__name__}."
    )


def _is_blank(parameters: Mapping[str, Any]) -> bool:
    """True when a stimulus is blank (a control stimulus).

    MATLAB equivalent: whatVaries/local_isBlank -- an ``isblank`` field that is
    present, non-empty, and true throughout (``~isempty(v) && all(logical(v))``).
    """
    if "isblank" not in parameters:
        return False
    value = parameters["isblank"]
    if value is None:
        return False
    if isinstance(value, np.ndarray):
        return bool(value.size) and bool(np.all(value.astype(bool)))
    if isinstance(value, (list, tuple)):
        return len(value) > 0 and all(bool(v) for v in value)
    return bool(value)


def _values_equal(a: Any, b: Any) -> bool:
    """Compare two parameter values for equality.

    Mirrors ``vlt.data.eqlen`` (equal size *and* equal contents) but with
    ``isequaln`` NaN semantics -- NaN equals NaN -- and in place of eqlen's bare
    ``x == y``, which is undefined for MATLAB cell values. See the whatVaries
    entry in ndi_matlab_python_bridge.yaml for the divergence rationale.
    """
    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        arr_a, arr_b = np.asarray(a), np.asarray(b)
        if arr_a.shape != arr_b.shape:
            return False
        if arr_a.dtype.kind in "fc" and arr_b.dtype.kind in "fc":
            return bool(np.array_equal(arr_a, arr_b, equal_nan=True))
        try:
            return bool(np.array_equal(arr_a, arr_b))
        except (TypeError, ValueError):
            return arr_a.tolist() == arr_b.tolist()

    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True

    a_seq = isinstance(a, (list, tuple))
    b_seq = isinstance(b, (list, tuple))
    if a_seq or b_seq:
        if not (a_seq and b_seq) or len(a) != len(b):
            return False
        return all(_values_equal(x, y) for x, y in zip(a, b))

    a_map = isinstance(a, Mapping)
    b_map = isinstance(b, Mapping)
    if a_map or b_map:
        if not (a_map and b_map) or set(a) != set(b):
            return False
        return all(_values_equal(a[k], b[k]) for k in a)

    try:
        return bool(a == b)
    except Exception:
        return False


def _is_scalar_number(value: Any) -> bool:
    """True for a numeric or logical scalar (MATLAB ``isnumeric``/``islogical``
    plus ``isscalar``).

    Python lists, tuples and numpy arrays with ndim > 0 are treated as vectors
    even when they hold one element -- unlike MATLAB, where a 1x1 array *is* a
    scalar. Complex values are excluded because Python cannot order them.
    """
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, np.generic):
        return value.dtype.kind in "biuf"
    if isinstance(value, np.ndarray):
        return value.ndim == 0 and value.dtype.kind in "biuf"
    return False


def _to_python_number(value: Any) -> Any:
    """numpy scalar / 0-d array -> the equivalent Python number."""
    if isinstance(value, (np.generic, np.ndarray)):
        return value.item()
    return value


def _is_nan(value: Any) -> bool:
    return isinstance(value, float) and math.isnan(value)


def _unique_values(values: Sequence[Any]) -> list[Any]:
    """The distinct values in *values*.

    MATLAB equivalent: whatVaries/local_uniqueValues. When every value is a
    numeric or logical scalar the result is sorted ascending with any NaNs
    collapsed to a single trailing NaN; otherwise it is the distinct values in
    order of first appearance.
    """
    if values and all(_is_scalar_number(v) for v in values):
        numbers = [_to_python_number(v) for v in values]
        has_nan = any(_is_nan(v) for v in numbers)
        unique: list[Any] = []
        for value in numbers:
            if _is_nan(value):
                continue
            if not any(value == seen for seen in unique):
                unique.append(value)
        unique.sort()
        if has_nan:
            unique.append(float("nan"))
        return unique

    unique = []
    for value in values:
        if not any(_values_equal(seen, value) for seen in unique):
            unique.append(value)
    return unique


def _varying_fields(params: Sequence[Mapping[str, Any]]) -> set[str]:
    """The parameter names that vary across *params*.

    MATLAB equivalent: whatVaries/local_varyingFields (itself a local
    reimplementation of ``vlt.data.structwhatvaries``): every parameter dict is
    compared to the first, and a name varies if it is present in only one of the
    two, or present in both with unequal values.
    """
    names: set[str] = set()
    if not params:
        return names
    ref = params[0]
    ref_fields = set(ref)
    for other in params[1:]:
        these = set(other)
        names |= these ^ ref_fields
        for name in these & ref_fields:
            if not _values_equal(ref[name], other[name]):
                names.add(name)
    return names


def whatVaries(
    stimuli: Any,
    *,
    exclude_blank: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Which stimulus parameters vary across a set of stimuli, and which are constant.

    MATLAB equivalent: ndi.fun.stimulus.whatVaries

    A parameter is CONSTANT when it is present in every considered stimulus and
    takes the same value in each; every other parameter -- including one present
    in some stimuli but not all -- is VARYING. Parameters are reported in the
    order in which they are first encountered.

    By default, blank (control) stimuli are excluded from the comparison: a
    stimulus is blank when its parameters have an ``isblank`` entry that is
    present, non-empty, and true. Pass ``exclude_blank=False`` to include them.

    Args:
        stimuli: The stimuli, in any shape accepted by
            :func:`whatVaries_parameterList`.
        exclude_blank: Drop blank (control) stimuli before comparing.
            Defaults to True.

    Returns:
        Tuple of ``(varies, constant)``.

        *varies* is a list of dicts with keys ``parameter`` (the name) and
        ``values`` (the distinct values it takes: sorted ascending when every
        value is a numeric or logical scalar, otherwise in order of first
        appearance).

        *constant* is a list of dicts with keys ``parameter`` and ``value``
        (the single value it takes in every stimulus).

    Example:
        >>> s = [
        ...     {"parameters": {"angle": 0, "contrast": 1}},
        ...     {"parameters": {"angle": 90, "contrast": 1}},
        ... ]
        >>> varies, constant = whatVaries(s)
        >>> varies
        [{'parameter': 'angle', 'values': [0, 90]}]
        >>> constant
        [{'parameter': 'contrast', 'value': 1}]
    """
    params = whatVaries_parameterList(stimuli)

    if exclude_blank:
        params = [p for p in params if not _is_blank(p)]

    varies: list[dict[str, Any]] = []
    constant: list[dict[str, Any]] = []

    if not params:
        return varies, constant

    # the union of parameter names, in order of first appearance
    fields: list[str] = []
    for p in params:
        for name in p:
            if name not in fields:
                fields.append(name)

    varying_names = _varying_fields(params)

    for name in fields:
        if name in varying_names:
            values = [p[name] for p in params if name in p]
            varies.append({"parameter": name, "values": _unique_values(values)})
        else:
            constant.append({"parameter": name, "value": params[0][name]})

    return varies, constant


def whatIsConstant(
    stimuli: Any,
    *,
    exclude_blank: bool = True,
) -> list[dict[str, Any]]:
    """Which stimulus parameters are held constant across a set of stimuli.

    MATLAB equivalent: ndi.fun.stimulus.whatIsConstant

    Convenience wrapper: returns the second element of :func:`whatVaries`.

    Args:
        stimuli: The stimuli, in any shape accepted by
            :func:`whatVaries_parameterList`.
        exclude_blank: Drop blank (control) stimuli before comparing.
            Defaults to True.

    Returns:
        A list of dicts with keys ``parameter`` and ``value``.
    """
    return whatVaries(stimuli, exclude_blank=exclude_blank)[1]


# Backward-compatible aliases
find_mixture_name = findMixtureName
stimulus_temporal_frequency = stimulustemporalfrequency

# snake_case aliases for the MATLAB-mirror names above
what_varies = whatVaries
what_is_constant = whatIsConstant
what_varies_parameter_list = whatVaries_parameterList
