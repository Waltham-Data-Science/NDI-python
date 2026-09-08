"""
ndi.fun.stimulus - Stimulus analysis utility functions.

MATLAB equivalents: +ndi/+fun/+stimulus/f0_f1_responses.m,
    findMixtureName.m, tuning_curve_to_response_type.m,
    +ndi/+fun/stimulustemporalfrequency.m
"""

from __future__ import annotations

import json
import math
import warnings
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
    from ndi.query import ndi_query

    # MATLAB checks these two dependencies BY NAME, in this order, and acts
    # differently on each: the scalar finishes the lookup, the tuning curve
    # recurses. Matching the name as a SUBSTRING, as this did, also matched
    # numbered variants such as stimulus_response_scalar_id_2 and took
    # whichever came first in the list rather than the one named.
    for dependency_name, action in (
        ("stimulus_response_scalar_id", "finish"),
        ("stimulus_tuningcurve_id", "recursive"),
    ):
        value = _dependency_value(doc, dependency_name)
        if not value:
            continue

        found = session.database_search(ndi_query("base.id", "exact_string", value))
        # MATLAB errors here rather than moving on; a database that cannot
        # resolve a dependency it declares is not a document without one.
        if len(found) != 1:
            raise ValueError(f"Could not find dependent doc {value}.")

        if action == "recursive":
            return tuning_curve_to_response_type(session, found[0])

        response_type = (
            _properties(found[0]).get("stimulus_response_scalar", {}).get("response_type")
        )
        if not response_type:
            raise ValueError("Could not find field 'response_type' in document.")
        return response_type, found[0]

    return "", None


def f0_f1_responses(
    session: Any,
    doc: Any,
    response_index: int | None = None,
) -> tuple[float, float, Any | None, Any | None]:
    """Get the F0 and F1 responses for a tuning curve document.

    MATLAB equivalent: ndi.fun.stimulus.f0_f1_responses

    The point of this function is that F0 and F1 live in SEPARATE tuning
    curve documents. Given either one, it finds the other -- same element,
    same stimulator and element epochs, opposite response type, matching
    independent variable -- and reads both at the same stimulus index.

    The previous implementation never looked the partner up. It read one
    value out of the document it was handed and returned ``None`` for the
    other, so one of ``f0``/``f1`` was always absent and the pair could
    never be compared, which is the entire purpose.

    Args:
        session: NDI session instance.
        doc: A ``stimulus_tuningcurve`` document, or one with a
            ``stimulus_tuningcurve_id`` dependency.
        response_index: Stimulus index (0-based here; MATLAB's is 1-based).
            If None, the index of the larger of the two peak responses is
            used, as MATLAB does.

    Returns:
        Tuple of ``(f0, f1, f0_tuningcurve_doc, f1_tuningcurve_doc)``.
        The two values are ``nan`` and the two documents ``None`` when no
        partner curve exists, matching MATLAB's initial values.

    Raises:
        ValueError: If *doc* is neither a tuning curve nor carries a
            ``stimulus_tuningcurve_id``, if the response type is neither
            mean nor F1, or if no partner curve is found.
    """
    import numpy as np

    from ndi.app.stimulus.tuning_response import ndi_app_stimulus_tuning__response
    from ndi.query import ndi_query

    response_type, scalar_doc = tuning_curve_to_response_type(session, doc)

    # Pass 1: find the tuning curve associated with the document we were given.
    if _doc_isa(doc, "stimulus_tuningcurve"):
        tc_doc = doc
    else:
        dependency = _dependency_value(doc, "stimulus_tuningcurve_id")
        if not dependency:
            raise ValueError(
                "doc is not a stimulus_tuningcurve and has no "
                "'stimulus_tuningcurve_id' dependency."
            )
        found = session.database_search(ndi_query("base.id", "exact_string", dependency))
        if len(found) != 1:
            raise ValueError(f"Could not find dependent doc {dependency}.")
        tc_doc = found[0]

    normalized = str(response_type).lower()
    if normalized == "mean":
        f0_curve_doc, f1_curve_doc = tc_doc, None
        target_response_type = "F1"
    elif normalized == "f1":
        f0_curve_doc, f1_curve_doc = None, tc_doc
        target_response_type = "mean"
    else:
        raise ValueError(f"Unknown response type (expected mean or F1): {response_type}")

    partner = _find_partner_tuning_curve(session, tc_doc, scalar_doc, target_response_type)
    if partner is None:
        return float("nan"), float("nan"), None, None

    if f0_curve_doc is None:
        f0_curve_doc = partner
    else:
        f1_curve_doc = partner

    to_struct = ndi_app_stimulus_tuning__response.tuningcurvedoc2vhlabrespstruct
    resp_f0 = to_struct(f0_curve_doc)
    resp_f1 = to_struct(f1_curve_doc)

    # Row 1 (MATLAB's row 2) of `curve` is the mean response.
    curve_f0 = np.asarray(resp_f0["curve"])[1]
    curve_f1 = np.asarray(resp_f1["curve"])[1]

    if response_index is None:
        peak_f0, at_f0 = float(np.nanmax(curve_f0)), int(np.nanargmax(curve_f0))
        peak_f1, at_f1 = float(np.nanmax(curve_f1)), int(np.nanargmax(curve_f1))
        response_index = at_f0 if peak_f0 > peak_f1 else at_f1

    return (
        float(curve_f0[response_index]),
        float(curve_f1[response_index]),
        f0_curve_doc,
        f1_curve_doc,
    )


def _find_partner_tuning_curve(
    session: Any,
    tc_doc: Any,
    scalar_doc: Any,
    target_response_type: str,
) -> Any | None:
    """The tuning curve of the opposite response type, or None.

    MATLAB's search: stimulus_response_scalar documents on the same element,
    the same stimulator and element epochs, and the target response type;
    then the stimulus_tuningcurve documents depending on any of those; then
    the one whose independent_variable_label matches.
    """
    from ndi.query import ndi_query

    scalar_properties = _properties(scalar_doc)
    stimulus_response = scalar_properties.get("stimulus_response", {})
    if not isinstance(stimulus_response, dict):
        return None

    element_id = _dependency_value(tc_doc, "element_id")

    candidates = session.database_search(
        ndi_query("", "depends_on", "element_id", element_id)
        & ndi_query("", "isa", "stimulus_response_scalar")
        & ndi_query(
            "stimulus_response.stimulator_epochid",
            "exact_string",
            stimulus_response.get("stimulator_epochid", ""),
        )
        & ndi_query(
            "stimulus_response.element_epochid",
            "exact_string",
            stimulus_response.get("element_epochid", ""),
        )
        & ndi_query(
            "stimulus_response_scalar.response_type",
            "exact_string",
            target_response_type,
        )
    )
    if not candidates:
        return None

    depends_query = None
    for candidate in candidates:
        one = ndi_query("", "depends_on", "stimulus_response_scalar_id", _doc_id(candidate))
        depends_query = one if depends_query is None else (depends_query | one)

    tc_candidates = session.database_search(
        depends_query & ndi_query("", "isa", "stimulus_tuningcurve")
    )

    wanted = _properties(tc_doc).get("stimulus_tuningcurve", {}).get("independent_variable_label")
    matches = [
        c
        for c in tc_candidates
        if _properties(c).get("stimulus_tuningcurve", {}).get("independent_variable_label")
        == wanted
    ]

    if not matches:
        raise ValueError(f"No corresponding {target_response_type} found.")
    if len(matches) > 1:
        warnings.warn(
            f"Too many {target_response_type} found ({len(matches)}).",
            stacklevel=2,
        )
    return matches[0]


def _properties(doc: Any) -> dict[str, Any]:
    props = getattr(doc, "document_properties", doc)
    return props if isinstance(props, dict) else {}


def _doc_id(doc: Any) -> str:
    doc_id = getattr(doc, "id", None)
    if callable(doc_id):
        doc_id = doc_id()
    if doc_id:
        return str(doc_id)
    return str(_properties(doc).get("base", {}).get("id", ""))


def _doc_isa(doc: Any, document_class: str) -> bool:
    checker = getattr(doc, "doc_isa", None)
    if callable(checker):
        return bool(checker(document_class))
    return document_class in _properties(doc)


def _dependency_value(doc: Any, name: str) -> str:
    getter = getattr(doc, "dependency_value", None)
    if callable(getter):
        try:
            return getter(name, error_if_not_found=False) or ""
        except TypeError:
            pass
    for dep in _properties(doc).get("depends_on", []) or []:
        if isinstance(dep, dict) and dep.get("name") == name:
            return str(dep.get("value", ""))
    return ""


#: The five fields findMixtureName compares, in MATLAB's order.
MIXTURE_COMPARE_FIELDS = ("ontologyName", "name", "value", "ontologyUnit", "unitName")


def _as_component_list(value: Any) -> list[dict[str, Any]]:
    """Normalise a mixture or dictionary entry to a list of components.

    MATLAB accepts a scalar struct, a struct array or a table, and wraps a
    scalar for uniform iteration. jsondecode turns a lone JSON object into a
    scalar struct, so a one-component dictionary entry arrives here as a
    plain dict -- which the previous implementation skipped outright with
    ``if not isinstance(entry_components, list): continue``, so no
    single-component entry could ever match.
    """
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    return []


def _as_number(value: Any) -> float | None:
    """The value as a float, or None if it is not a number or numeric text."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _values_match(a: Any, b: Any) -> bool:
    """MATLAB compares the four text fields with strcmp and value with eq().

    Comparing every field as a STRING, as this used to, made 1 and 1.0
    different -- the difference between a JSON integer and a JSON float for
    the same quantity.

    Numeric TEXT is also accepted on either side, which is deliberately more
    permissive than MATLAB: eq('0.9', 0.9) there compares char codes and
    returns a 1x3 logical, which the following && rejects outright, so
    MATLAB errors on that input rather than defining an answer. A mixture
    read out of a table or a CSV carries its values as text, and refusing it
    would be a worse answer than accepting it.
    """
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    number_a, number_b = _as_number(a), _as_number(b)
    if number_a is not None and number_b is not None:
        return number_a == number_b
    return a == b


def _components_match(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """True when two mixture components agree on all five compared fields."""
    return all(_values_match(a.get(f), b.get(f)) for f in MIXTURE_COMPARE_FIELDS)


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

    mixture_components = _as_component_list(mixture)

    matches: list[str] = []
    for entry_name, entry_components in dictionary.items():
        components = _as_component_list(entry_components)
        if not components:
            continue
        # MATLAB: all(entryMatch) where entryMatch(j) = any(mixtureMatch).
        # Every component of the dictionary entry must find SOME element of
        # the mixture that matches it on all five fields.
        if all(
            any(_components_match(component, element) for element in mixture_components)
            for component in components
        ):
            matches.append(entry_name)

    return matches


def stimulustemporalfrequency(
    stimulus_parameters: dict[str, Any],
    config_path: str | None = None,
) -> tuple[float | None, str]:
    """Extract temporal frequency from stimulus parameters.

    MATLAB equivalent: ndi.fun.stimulustemporalfrequency

    A stimulus can encode its temporal frequency in several ways -- directly
    in Hz, scaled, or as a period to be inverted -- so which parameter to
    read and what to do with it is data, not code: the rules live in
    ``ndi_common/stimulus/ndi_stimulusparameters2temporalfrequency.json``,
    shared verbatim with NDI-matlab. Rules are tried in file order and the
    first match wins, as MATLAB does.

    THIS READ THE WRONG FILE AND THE WRONG KEYS. It looked for
    ``temporal_frequency_rules.json``, which does not exist in ndi_common,
    and then for rule keys (``parameterName``, ``multiplier``, ``adder``,
    ``multiplyByParameter``) that are not the ones the shipped file uses
    (``parameter_name``, ``temporalFrequencyMultiplier``,
    ``temporalFrequencyAdder``, ``parameterMultiplier``). Either alone made
    it return ``(None, "")`` for every stimulus ever passed to it -- so no
    stimulus had a fundamental frequency, and
    ``ndi.app.stimulus.tuning_response`` computed only F0, silently skipping
    the F1 and F2 responses that are the whole reason a response is stored
    as a complex number.

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
                / "ndi_stimulusparameters2temporalfrequency.json"
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
        param_name = rule.get("parameter_name", "")
        if param_name not in stimulus_parameters:
            continue

        val = stimulus_parameters[param_name]
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            continue

        multiplier = rule.get("temporalFrequencyMultiplier", 1.0)
        adder = rule.get("temporalFrequencyAdder", 0.0)
        is_period = rule.get("isPeriod", False)

        tf = adder + multiplier * val

        if is_period:
            if tf == 0:
                continue
            tf = 1.0 / tf

        # A period given in frames needs the refresh rate to become seconds,
        # which is what parameterMultiplier names. MATLAB errors when the
        # named parameter is absent; here the rule is skipped and the next
        # one tried, so a stimulus set with one malformed entry still
        # reports the frequencies of the rest.
        secondary = rule.get("parameterMultiplier", "")
        if secondary:
            sec_val = stimulus_parameters.get(secondary)
            if isinstance(sec_val, bool) or not isinstance(sec_val, (int, float)):
                continue
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


# Backward-compatible aliases
find_mixture_name = findMixtureName
stimulus_temporal_frequency = stimulustemporalfrequency


def isequaln(a: Any, b: Any) -> bool:
    """Value equality treating NaN as equal to NaN.

    MATLAB's ``isequaln``. Used throughout this port, including where
    MATLAB's ``whatVaries`` uses ``vlt.data.eqlen`` instead -- see the note
    in :func:`whatVaries` about the resulting known divergences.
    """
    if isinstance(a, bool) or isinstance(b, bool):
        # bool before number: in Python bool is a subclass of int, and
        # True == 1 must not make a logical equal to a double here.
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, float) and isinstance(b, float):
        if math.isnan(a) and math.isnan(b):
            return True
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        try:
            if math.isnan(a) and math.isnan(b):
                return True
        except TypeError:
            pass
        return a == b
    if isinstance(a, str) or isinstance(b, str):
        return isinstance(a, str) and isinstance(b, str) and a == b
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(isequaln(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(isequaln(a[k], b[k]) for k in a)
    try:
        return bool(a == b)
    except Exception:
        return False


def _is_document(obj: Any) -> bool:
    """Is this an ndi_document? Duck-typed to avoid a circular import."""
    return hasattr(obj, "document_properties") and not isinstance(obj, dict)


def _stimuli_parameters(stimuli: Any) -> list[dict]:
    """The ``parameters`` of a ``stimulus_presentation.stimuli`` list."""
    if isinstance(stimuli, dict):
        stimuli = [stimuli]
    return [s["parameters"] for s in stimuli]


def _doc_parameters(doc: Any) -> list[dict]:
    """The parameter structs held in one stimulus_presentation document."""
    dp = doc.document_properties
    if "stimulus_presentation" not in dp:
        raise ValueError(
            f"ndi_document (id {getattr(doc, 'id', '?')}) does not have a "
            "stimulus_presentation field."
        )
    return _stimuli_parameters(dp["stimulus_presentation"]["stimuli"])


def whatVaries_parameterList(stimuli: Any) -> list[dict]:  # noqa: N802 (MATLAB mirror)
    """Flatten *stimuli*, in any accepted form, to a list of parameter dicts.

    Accepted forms mirror MATLAB's, with one unavoidable adaptation.

    MATLAB distinguishes a **cell array** of parameter structs from a
    **struct array** of stimuli, and treats them differently: a cell entry is
    itself the parameter struct, while a struct-array element has its
    ``.parameters`` read. Python has one list type for both, so the shape
    cannot be recovered from the container. This port uses the contents
    instead: **if every dict in the list carries a ``parameters`` key it is
    read as a stimuli list, otherwise each dict is taken as a parameter
    struct.** That reproduces MATLAB's behaviour on every shape the symmetry
    battery exercises, and the battery records the MATLAB-side shape in a
    field that is deliberately *not* compared across languages.

    MATLAB equivalent: ``ndi.fun.stimulus.whatVaries_parameterList``.
    """
    if _is_document(stimuli):
        return _doc_parameters(stimuli)

    if isinstance(stimuli, (list, tuple)):
        if not stimuli:
            return []
        dicts = [e for e in stimuli if isinstance(e, dict)]
        stimuli_shaped = len(dicts) == len(stimuli) and all("parameters" in d for d in dicts)
        params: list[dict] = []
        for entry in stimuli:
            if _is_document(entry):
                params.extend(_doc_parameters(entry))
            elif isinstance(entry, dict):
                if stimuli_shaped:
                    params.append(entry["parameters"])
                elif "stimulus_presentation" in entry:
                    params.extend(_stimuli_parameters(entry["stimulus_presentation"]["stimuli"]))
                else:
                    params.append(entry)
            else:
                raise ValueError(
                    "Each entry must be an ndi_document or a parameter dict; "
                    f"got {type(entry).__name__}."
                )
        return params

    if isinstance(stimuli, dict):
        if "stimulus_presentation" in stimuli:
            return _stimuli_parameters(stimuli["stimulus_presentation"]["stimuli"])
        if "parameters" in stimuli:
            return [stimuli["parameters"]]
        return [stimuli]

    raise TypeError(
        "stimuli must be an ndi_document, a list, or a dict. " f"Got a {type(stimuli).__name__}."
    )


def _is_blank(p: dict) -> bool:
    """A stimulus is blank when its parameters have a true ``isblank``."""
    if "isblank" not in p:
        return False
    v = p["isblank"]
    if isinstance(v, (list, tuple)):
        return len(v) > 0 and all(bool(x) for x in v)
    return bool(v)


def _is_numeric_scalar(v: Any) -> bool:
    return isinstance(v, (int, float, bool)) and not isinstance(v, str)


def _unique_values(vals: list[Any]) -> Any:
    """The distinct values in *vals*.

    A sorted list when every value is a numeric or logical scalar (matching
    MATLAB's sorted row vector), otherwise the distinct values in order of
    first appearance.
    """
    if vals and all(_is_numeric_scalar(v) for v in vals):
        nans = [v for v in vals if isinstance(v, float) and math.isnan(v)]
        finite = [v for v in vals if not (isinstance(v, float) and math.isnan(v))]
        seen: list[Any] = []
        for v in finite:
            if not any(isequaln(v, s) for s in seen):
                seen.append(v)
        seen.sort()
        # MATLAB's unique() keeps NaNs distinct; whatVaries collapses them.
        if nans:
            seen.append(float("nan"))
        return seen

    out: list[Any] = []
    for v in vals:
        if not any(isequaln(u, v) for u in out):
            out.append(v)
    return out


def _varying_fields(params: list[dict]) -> set[str]:
    """Parameter names that vary across *params*.

    Each struct is compared to the first: a field varies if it is present in
    only one of the two, or present in both with unequal values.

    **Equality here is** :func:`isequaln`. MATLAB uses ``vlt.data.eqlen``,
    which bottoms out in a bare ``==``, and that difference is the source of
    the two known cross-language divergences the symmetry battery records:
    ``eqlen(NaN, NaN)`` is false so MATLAB reports an all-NaN parameter as
    varying, and ``==`` is undefined for two cell arrays so MATLAB errors on
    a cell-valued constant parameter. Both are believed to be MATLAB bugs;
    the upstream fix is to use ``isequaln`` in ``local_varyingFields`` there
    too.
    """
    names: set[str] = set()
    if not params:
        return names
    ref = params[0]
    ref_fields = set(ref)
    for other in params[1:]:
        these = set(other)
        names |= these ^ ref_fields  # present in only one of the two
        for f in these & ref_fields:
            if not isequaln(ref[f], other[f]):
                names.add(f)
    return names


def whatVaries(
    stimuli: Any, excludeBlank: bool = True  # noqa: N803 (MATLAB mirror)
) -> tuple[list[dict], list[dict]]:
    """Which stimulus parameters vary across a set of stimuli, and which are constant.

    Returns ``(varies, constant)``.

    A parameter is CONSTANT when it is present in every considered stimulus
    and takes the same value in each; every other parameter -- including one
    present in some stimuli but not all -- is VARYING. Parameters are
    reported in the order first encountered.

    ``varies`` is a list of ``{'parameter': name, 'values': distinct}``;
    ``constant`` is a list of ``{'parameter': name, 'value': v}``.

    By default blank (control) stimuli are excluded: a stimulus is blank when
    its parameters have an ``isblank`` field that is true. Pass
    ``excludeBlank=False`` to include them.

    MATLAB equivalent: ``ndi.fun.stimulus.whatVaries``.
    """
    params = whatVaries_parameterList(stimuli)

    if excludeBlank:
        params = [p for p in params if not _is_blank(p)]

    varies: list[dict] = []
    constant: list[dict] = []
    if not params:
        return varies, constant

    # union of parameter names, in order of first appearance
    fields: list[str] = []
    for p in params:
        for f in p:
            if f not in fields:
                fields.append(f)

    varying_names = _varying_fields(params)

    for field in fields:
        if field in varying_names:
            vals = [p[field] for p in params if field in p]
            varies.append({"parameter": field, "values": _unique_values(vals)})
        else:
            constant.append({"parameter": field, "value": params[0][field]})

    return varies, constant


def whatIsConstant(
    stimuli: Any, excludeBlank: bool = True  # noqa: N803 (MATLAB mirror)
) -> list[dict]:
    """Which stimulus parameters are held constant across a set of stimuli.

    A convenience wrapper returning the second output of :func:`whatVaries`.

    MATLAB equivalent: ``ndi.fun.stimulus.whatIsConstant``.
    """
    _, constant = whatVaries(stimuli, excludeBlank=excludeBlank)
    return constant
