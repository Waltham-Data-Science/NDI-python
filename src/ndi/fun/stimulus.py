"""
ndi.fun.stimulus - Stimulus analysis utility functions.

MATLAB equivalents: +ndi/+fun/+stimulus/f0_f1_responses.m,
    findMixtureName.m, tuning_curve_to_response_type.m,
    +ndi/+fun/stimulustemporalfrequency.m
"""

from __future__ import annotations

import json
import math
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
