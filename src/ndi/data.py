"""Evaluation of fitcurve documents.

Python port of MATLAB ``ndi.data``.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable
from typing import Any

import numpy as np

__all__ = ["evaluate_fitcurve", "FitEquationError"]


class FitEquationError(ValueError):
    """A fit equation could not be translated, parsed, or safely evaluated."""


# Functions a fit equation may call, mapped from their MATLAB names to numpy.
# Adding to this list is the supported way to widen what equations may do;
# anything absent is rejected by name rather than silently resolved.
_ALLOWED_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "abs": np.abs,
    "acos": np.arccos,
    "acosh": np.arccosh,
    "asin": np.arcsin,
    "asinh": np.arcsinh,
    "atan": np.arctan,
    "atan2": np.arctan2,
    "atanh": np.arctanh,
    "ceil": np.ceil,
    "cos": np.cos,
    "cosh": np.cosh,
    "exp": np.exp,
    "fix": np.trunc,
    "floor": np.floor,
    "log": np.log,
    "log10": np.log10,
    "log2": np.log2,
    "max": np.maximum,
    "min": np.minimum,
    "mod": np.mod,
    "power": np.power,
    "rem": np.fmod,
    "round": np.round,
    "sign": np.sign,
    "sin": np.sin,
    "sinh": np.sinh,
    "sqrt": np.sqrt,
    "tan": np.tan,
    "tanh": np.tanh,
}

_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.FloorDiv)
_ALLOWED_UNARYOPS = (ast.UAdd, ast.USub)


def _matlab_to_python_expression(equation: str) -> str:
    """Rewrite MATLAB operator spellings into their Python equivalents.

    MATLAB's element-wise operators have no Python spelling, and numpy's
    operators are element-wise already, so ``.*`` ``./`` ``.^`` collapse onto
    ``*`` ``/`` ``**``. MATLAB's ``^`` is also exponentiation, not xor.

    Order matters: the dotted forms are rewritten before the bare ``^``, so a
    ``.^`` is never seen as ``.`` followed by ``^``.
    """
    out = equation
    out = out.replace(".^", "**")
    out = out.replace(".*", "*")
    out = out.replace("./", "/")
    out = re.sub(r"\^", "**", out)
    # MATLAB's inequality; Python's != means the same thing.
    out = out.replace("~=", "!=")
    return out


def _evaluate_node(node: ast.AST, names: dict[str, Any]) -> Any:
    """Evaluate one whitelisted expression node.

    Every node type is checked against an allow-list. Anything not explicitly
    permitted -- attribute access, subscripting, comprehensions, lambdas,
    walrus, f-strings, starred args, keyword args -- raises rather than being
    evaluated. This is what makes a fit equation read out of a document safe
    to evaluate: the document cannot reach anything the list does not name.
    """
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float, complex)):
            raise FitEquationError(f"Only numeric constants are allowed, got {node.value!r}.")
        return node.value

    if isinstance(node, ast.Name):
        if node.id not in names:
            raise FitEquationError(
                f"Unknown name {node.id!r} in fit equation. Known names: "
                f"{', '.join(sorted(names))}."
            )
        return names[node.id]

    if isinstance(node, ast.BinOp):
        if not isinstance(node.op, _ALLOWED_BINOPS):
            raise FitEquationError(f"Operator {type(node.op).__name__} is not allowed.")
        left = _evaluate_node(node.left, names)
        right = _evaluate_node(node.right, names)
        return _apply_binop(node.op, left, right)

    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, _ALLOWED_UNARYOPS):
            raise FitEquationError(f"Operator {type(node.op).__name__} is not allowed.")
        operand = _evaluate_node(node.operand, names)
        return +operand if isinstance(node.op, ast.UAdd) else -operand

    if isinstance(node, ast.Call):
        return _evaluate_call(node, names)

    raise FitEquationError(
        f"{type(node).__name__} is not allowed in a fit equation. Fit equations are "
        "restricted to numeric constants, the declared parameter and variable names, "
        "arithmetic, and a fixed list of mathematical functions."
    )


def _apply_binop(op: ast.operator, left: Any, right: Any) -> Any:
    if isinstance(op, ast.Add):
        return left + right
    if isinstance(op, ast.Sub):
        return left - right
    if isinstance(op, ast.Mult):
        return left * right
    if isinstance(op, ast.Div):
        return left / right
    if isinstance(op, ast.Pow):
        return left**right
    if isinstance(op, ast.Mod):
        return left % right
    return left // right


def _evaluate_call(node: ast.Call, names: dict[str, Any]) -> Any:
    if not isinstance(node.func, ast.Name):
        raise FitEquationError(
            "Only direct calls to allowed functions are permitted; "
            "attribute calls such as np.exp(x) are not."
        )
    if node.keywords:
        raise FitEquationError(f"Keyword arguments are not allowed (in {node.func.id}).")
    if any(isinstance(a, ast.Starred) for a in node.args):
        raise FitEquationError(f"Starred arguments are not allowed (in {node.func.id}).")
    fn = _ALLOWED_FUNCTIONS.get(node.func.id)
    if fn is None:
        raise FitEquationError(
            f"Function {node.func.id!r} is not an allowed fit-equation function. "
            f"Allowed: {', '.join(sorted(_ALLOWED_FUNCTIONS))}."
        )
    return fn(*[_evaluate_node(a, names) for a in node.args])


def _split_names(text: str) -> list[str]:
    """Split a whitespace-separated name list, matching MATLAB's strsplit+strtrim."""
    return [t for t in (s.strip() for s in str(text).split()) if t]


def _parse_parameter_values(raw: Any) -> np.ndarray:
    """Coerce fit_parameters to a 1-D float array.

    MATLAB does ``if ischar(...) fit_parameter_values = str2mat(...)``, which
    is almost certainly a slip: str2mat builds a char matrix, it does not
    parse numbers. A char fit_parameters would therefore not survive the
    numel comparison that follows. Here a string is parsed as the numbers it
    obviously means, which is the only reading under which that branch does
    anything useful.
    """
    if isinstance(raw, str):
        parts = [p for p in re.split(r"[\s,;\[\]]+", raw.strip()) if p]
        try:
            return np.asarray([float(p) for p in parts], dtype=float)
        except ValueError as exc:
            raise FitEquationError(f"Could not read fit_parameters from {raw!r}.") from exc
    return np.atleast_1d(np.asarray(raw, dtype=float))


def evaluate_fitcurve(fitcurve_doc: Any, *args: Any) -> Any:
    """Evaluate a fitcurve document's equation at the given independent values.

    MATLAB equivalent: ``ndi.data.evaluate_fitcurve``.

    Args:
        fitcurve_doc: A document whose ``fitcurve`` properties carry
            ``fit_equation``, ``fit_parameters``, ``fit_parameter_names``,
            ``fit_independent_variable_names`` and
            ``fit_dependent_variable_names``.
        *args: One value (scalar or array) per independent variable.

    Returns:
        The dependent variable, evaluated at *args*.

    Raises:
        FitEquationError: If the equation cannot be translated or parsed, or
            uses anything outside the permitted subset.
        ValueError: If the document declares more than one independent or
            dependent variable, or its parameter names and values disagree in
            length -- matching MATLAB, which errors on all three.

    Security:
        MATLAB evaluates the stored equation with ``eval``:

            eval([fit_equation_mod ';']);

        A fitcurve document is data, and can arrive from a shared or cloud
        dataset, so the Python port does NOT mirror that. The equation is
        parsed to an AST and walked against an allow-list: numeric constants,
        the declared names, arithmetic, and the functions in
        ``_ALLOWED_FUNCTIONS``. Attribute access, subscripting, calls to
        anything unlisted, comprehensions and lambdas are all rejected by
        node type, so an equation cannot reach the interpreter.

        This is deliberately STRICTER than MATLAB: an equation MATLAB would
        happily run may be refused here. That is the intended trade, and the
        error names what was refused so a legitimate equation can be
        supported by adding to the list rather than by loosening the walker.

    Note:
        MATLAB renames every variable to ``ndi_evaluate_fitcurve_<name>``
        before evaluating, purely so ``eval`` cannot collide with the caller's
        workspace. Binding names into a dict makes that unnecessary, so the
        renaming is not reproduced; it was an artefact of ``eval``, not part
        of the contract.
    """
    props = (
        fitcurve_doc.document_properties
        if hasattr(fitcurve_doc, "document_properties")
        else fitcurve_doc
    )
    fc = props["fitcurve"]

    equation = fc["fit_equation"]

    independent = _split_names(fc["fit_independent_variable_names"])
    if len(independent) > 1:
        raise ValueError("Do not know how to deal with more than one independent variable yet.")

    dependent = _split_names(fc["fit_dependent_variable_names"])
    if len(dependent) > 1:
        raise ValueError("Do not know how to deal with more than one dependent variable yet.")
    if not dependent:
        raise ValueError("The fitcurve document declares no dependent variable.")

    parameter_names = _split_names(fc["fit_parameter_names"])
    parameter_values = _parse_parameter_values(fc["fit_parameters"])

    if len(parameter_values) != len(parameter_names):
        raise ValueError(
            "Fit parameter names and fit parameter values do not have same number of entries."
        )

    if len(args) < len(independent):
        raise ValueError(
            f"Expected {len(independent)} value(s) for {independent}, got {len(args)}."
        )

    names: dict[str, Any] = dict(zip(parameter_names, parameter_values, strict=True))
    for i, name in enumerate(independent):
        names[name] = args[i]

    return _evaluate_equation(equation, dependent[0], names)


def _evaluate_equation(equation: str, dependent: str, names: dict[str, Any]) -> Any:
    """Translate, parse and evaluate ``<dependent> = <expression>``."""
    translated = _matlab_to_python_expression(equation)

    try:
        tree = ast.parse(translated, mode="exec")
    except SyntaxError as exc:
        raise FitEquationError(
            f"Could not parse fit equation {equation!r} "
            f"(translated to {translated!r}): {exc.msg}."
        ) from exc

    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.Assign):
        raise FitEquationError(
            f"A fit equation must be a single assignment of the form "
            f"'{dependent} = ...'; got {equation!r}."
        )

    assign = tree.body[0]
    targets = assign.targets
    if len(targets) != 1 or not isinstance(targets[0], ast.Name):
        raise FitEquationError(f"A fit equation must assign to a single name; got {equation!r}.")
    if targets[0].id != dependent:
        raise FitEquationError(
            f"The fit equation assigns to {targets[0].id!r}, but the document declares "
            f"the dependent variable as {dependent!r}."
        )

    return _evaluate_node(assign.value, names)
