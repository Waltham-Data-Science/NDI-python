"""The model behind ndi.gui.nav.datasets_pane: what the tree shows.

MATLAB counterpart: the model-side private methods of
``src/ndi/+ndi/+gui/+nav/datasetsPane.m``

``datasetsPane`` is 1685 lines. Its pure text and menu-enablement helpers are
already ported in :mod:`ndi.gui.nav.datasets_text`. This module is the next
layer up: everything that decides WHAT the tree shows -- which datasets and
sessions exist, what each node is labelled, what a node carries, and what a
session's ingestion state is -- with no widget anywhere in it.

Splitting the model off the widgets is the same bet the navigator's layout
module makes. A wrong node label, a session listed twice, a status badge
computed from the wrong branch: none of those raise. They just show a user
something untrue about their own data. Every rule here is therefore a plain
function over plain values, and every one has a test.

WHAT IS DELIBERATELY NOT HERE
The cloud ACTIONS -- upload, sync, mirror, check-for-new, fetching the cloud
catalogue -- are a separate slice. :func:`check_all_cloud_status` is here
because it is a status read rather than an action: it only asks each dataset
the local question :meth:`ndi.dataset.ndi_dataset.is_in_cloud`, and the NDI
Cloud pane's bulk "C" button needs it.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from .datasets_text import (
    UNNAMED_SESSION,
    append_workspace_var_names,
    dataset_label,
    session_label,
)

__all__ = [
    "WORKSPACE_MODULE",
    "obj_id",
    "workspace_namespace",
    "scan_workspace",
    "build_workspace_var_index",
    "decorate_with_workspace_vars",
    "search_path_datasets",
    "session_node_data",
    "dataset_node_data",
    "resolve_session",
    "compute_session_status",
    "session_path",
    "dataset_path",
    "unaffiliated_sessions",
    "dataset_session_rows",
    "dataset_rows",
    "unaffiliated_rows",
    "check_all_cloud_status",
    "UNKNOWN_STATUS",
]

#: The module whose globals stand in for MATLAB's base workspace.
#:
#: MATLAB reads the user's variables with ``evalin('base', 'whos')``. Python
#: has no base workspace, and the honest analogue is the ``__main__`` module:
#: in a REPL, a script or a notebook that is exactly where the user's names
#: live, and when NDI is imported as a library by some other program it holds
#: that program's names, which is why every function here takes an explicit
#: namespace argument as well. A caller with a different idea of "the user's
#: variables" passes its own mapping instead of being stuck with this one.
WORKSPACE_MODULE = "__main__"

#: A session node's status before anyone has asked for it. MATLAB starts every
#: node here and computes the real value only on the "Ingestion Status"
#: command, so that listing sessions stays cheap; "unknown" draws no badge.
UNKNOWN_STATUS: dict[str, str] = {"ingestion": "unknown"}


def obj_id(obj: Any) -> str:
    """Best-effort id of a session or dataset, ``""`` when it cannot say."""
    try:
        identifier = obj.id() if callable(obj.id) else obj.id
        return str(identifier or "")
    except Exception:  # noqa: BLE001 - an object that cannot say is not an error
        return ""


def workspace_namespace(namespace: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
    """The mapping to read the user's variables from.

    Defaults to :data:`WORKSPACE_MODULE`'s globals, and yields an empty
    mapping when that module is not importable, so a caller never has to
    guard the lookup.
    """
    if namespace is not None:
        return namespace
    module = sys.modules.get(WORKSPACE_MODULE)
    return getattr(module, "__dict__", {}) if module is not None else {}


def scan_workspace(
    cls: type | tuple[type, ...],
    namespace: Mapping[str, Any] | None = None,
) -> list[Any]:
    """The user's variables that are instances of CLS, in name order.

    Sorted by variable name rather than left in dict order so that two runs
    over the same workspace produce the same tree. Python 3.7+ dicts preserve
    insertion order, which for ``__main__`` is assignment order -- stable
    within a session but not something a user would recognise as an order.

    Never raises: a name that cannot be read contributes nothing, matching
    MATLAB's per-variable ``try``.
    """
    found: list[Any] = []
    for name in sorted(workspace_namespace(namespace)):
        if name.startswith("__"):
            continue
        try:
            value = workspace_namespace(namespace)[name]
            if isinstance(value, cls):
                found.append(value)
        except Exception:  # noqa: BLE001
            continue
    return found


def build_workspace_var_index(
    classes: type | tuple[type, ...],
    namespace: Mapping[str, Any] | None = None,
) -> dict[str, list[str]]:
    """Map object id -> the user's variable names that hold that object.

    Keyed by ID RATHER THAN BY IDENTITY, which is the point: a distinct
    instance of the same session opened twice still matches, so a node is
    labelled with the variable holding "that session" even when it is not
    literally the same object. An object that cannot report an id
    contributes nothing.
    """
    index: dict[str, list[str]] = {}
    for name in sorted(workspace_namespace(namespace)):
        if name.startswith("__"):
            continue
        try:
            value = workspace_namespace(namespace)[name]
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(value, classes):
            continue
        key = obj_id(value)
        if not key:
            continue
        index.setdefault(key, []).append(name)
    return index


def decorate_with_workspace_vars(
    label: str, identifier: str, index: Mapping[str, Sequence[str]] | None
) -> str:
    """Append the user's variable names for IDENTIFIER to LABEL.

    ``decorate_with_workspace_vars("myref", id, {id: ["S", "S2"]})`` gives
    ``'myref "S", "S2"'``. An object with no such variable -- the common
    case -- comes back unchanged rather than gaining a trailing space.
    """
    label = str(label)
    identifier = str(identifier or "")
    if not identifier or not index or identifier not in index:
        return label
    return append_workspace_var_names(label, list(index[identifier]))


def search_path_datasets() -> list[Any]:
    """Datasets discovered on the search path.

    Empty, as in MATLAB: search-path discovery is not configured on either
    side yet. Kept as the same named seam so the two ports gain it together
    rather than one growing a different mechanism.
    """
    return []


def session_node_data(
    session_obj: Any = None, dataset: Any = None, session_id: str = ""
) -> dict[str, Any]:
    """Node payload for a session.

    Carries the resolved session when it is known, or the parent dataset and
    the session id so it can be opened on demand. The shape is uniform so
    :func:`resolve_session` can read any session node the same way, and the
    status starts :data:`UNKNOWN_STATUS`.
    """
    return {
        "kind": "session",
        "session": session_obj,
        "dataset": dataset,
        "session_id": str(session_id or ""),
        "status": dict(UNKNOWN_STATUS),
    }


def dataset_node_data(dataset: Any = None) -> dict[str, Any]:
    """Node payload for a dataset, or for the "Unaffiliated sessions" root.

    The dataset handle is stored on the node so a bulk action can act on
    every dataset without re-deriving the list.
    """
    data: dict[str, Any] = {"kind": "dataset"}
    if dataset is not None:
        data["dataset"] = dataset
    return data


def resolve_session(node_data: Mapping[str, Any] | None) -> Any | None:
    """The session for a session node, opening it from its dataset if needed.

    Returns None rather than raising when the session cannot be opened: the
    caller reports that to the user, and a node whose session has gone away
    must not take the tree down with it.
    """
    if not isinstance(node_data, Mapping):
        return None

    session = node_data.get("session")
    if session is not None:
        return session

    dataset = node_data.get("dataset")
    session_id = node_data.get("session_id") or ""
    if dataset is None or not session_id:
        return None
    try:
        return dataset.open_session(session_id)
    except Exception:  # noqa: BLE001
        return None


def compute_session_status(
    session: Any, node_data: Mapping[str, Any] | None = None
) -> tuple[dict[str, str], Exception | None]:
    """The ingestion state of a session, and whatever went wrong finding it.

    Returns ``(status, error)``. The two questions are different, and which
    one applies is decided by whether the node sits under a dataset:

        in a dataset     -> ingested vs LINKED
        stand-alone      -> ingested vs NONE

    Any failure leaves the status ``"unknown"`` -- which draws no badge --
    and hands the exception back rather than swallowing it, so the caller can
    tell the user why the status is blank. A status this function could not
    determine must never be reported as a definite "not ingested".
    """
    status = dict(UNKNOWN_STATUS)
    in_dataset = bool(isinstance(node_data, Mapping) and node_data.get("dataset") is not None)
    try:
        if in_dataset:
            status["ingestion"] = "ingested" if session.isIngestedInDataset() else "linked"
        else:
            status["ingestion"] = "ingested" if session.is_fully_ingested() else "none"
    except Exception as exc:  # noqa: BLE001 - handed back, not swallowed
        return dict(UNKNOWN_STATUS), exc
    return status, None


def session_path(session: Any) -> str:
    """Best-effort local path of a session, ``""`` when it has none."""
    return _best_effort_path(session)


def dataset_path(dataset: Any) -> str:
    """Best-effort local path of a dataset, ``""`` when it has none.

    MATLAB reads ``ds.path`` for both, but the Python dataset exposes
    ``getpath()`` and no ``path`` property, so both are tried. Getting this
    wrong would not raise -- it would silently return ``""`` for every
    dataset, and the de-duplication in :func:`unaffiliated_sessions` would
    quietly stop working.
    """
    return _best_effort_path(dataset)


def _best_effort_path(obj: Any) -> str:
    for name in ("getpath", "path"):
        try:
            attr = getattr(obj, name)
        except Exception:  # noqa: BLE001
            continue
        try:
            value = attr() if callable(attr) else attr
        except Exception:  # noqa: BLE001
            continue
        if value:
            return str(value)
    return ""


def unaffiliated_sessions(
    user_sessions: Sequence[Any] | None,
    session_class: type | tuple[type, ...],
    namespace: Mapping[str, Any] | None = None,
) -> list[Any]:
    """Sessions to show under "Unaffiliated sessions".

    The sessions the user created or opened here, followed by the session
    objects found in their workspace, with a workspace session dropped when
    its path is already listed. De-duplicating by PATH rather than by
    identity is what stops a session from appearing twice after the user
    opens the same directory again and binds it to a variable.

    A session with no path is never treated as a duplicate: two sessions that
    both cannot say where they live are not thereby the same session.
    """
    sessions: list[Any] = list(user_sessions or [])
    known = {p for p in (session_path(s) for s in sessions) if p}

    for candidate in scan_workspace(session_class, namespace):
        path = session_path(candidate)
        if path and path in known:
            continue
        sessions.append(candidate)
        if path:
            known.add(path)
    return sessions


def dataset_session_rows(
    dataset: Any, index: Mapping[str, Sequence[str]] | None = None
) -> list[dict[str, Any]]:
    """One row per session in DATASET: its label and its node payload.

    Each row is ``{"label": str, "node_data": dict}``. The session id is
    known here without opening the session, so a workspace variable holding
    that same session can be shown on the label cheaply.

    A dataset whose session list cannot be read yields no rows rather than
    raising -- one unreadable dataset must not empty the whole tree.
    """
    try:
        listed = dataset.session_list()
    except Exception:  # noqa: BLE001
        return []

    # MATLAB's session_list returns [refList, idList]; Python's returns four
    # values, adding the session-document ids. Taking the first two by slicing
    # keeps this working under either arity.
    if not isinstance(listed, (tuple, list)) or len(listed) < 2:
        return []
    ref_list, id_list = listed[0], listed[1]

    rows: list[dict[str, Any]] = []
    for k, ref in enumerate(ref_list or []):
        label = str(ref or "") or UNNAMED_SESSION
        session_id = id_list[k] if id_list is not None and k < len(id_list) else ""
        rows.append(
            {
                "label": decorate_with_workspace_vars(label, str(session_id or ""), index),
                "node_data": session_node_data(None, dataset, session_id),
            }
        )
    return rows


def dataset_rows(
    user_datasets: Sequence[Any] | None,
    dataset_class: type | tuple[type, ...],
    namespace: Mapping[str, Any] | None = None,
    index: Mapping[str, Sequence[str]] | None = None,
) -> list[dict[str, Any]]:
    """One row per dataset to show: label, node payload and session rows.

    The order is MATLAB's: the datasets the user added with "+", then the
    search path, then the workspace.
    """
    datasets = list(user_datasets or [])
    datasets += search_path_datasets()
    datasets += scan_workspace(dataset_class, namespace)

    rows: list[dict[str, Any]] = []
    for ds in datasets:
        rows.append(
            {
                "label": decorate_with_workspace_vars(dataset_label(ds), obj_id(ds), index),
                "node_data": dataset_node_data(ds),
                "sessions": dataset_session_rows(ds, index),
            }
        )
    return rows


def unaffiliated_rows(
    sessions: Sequence[Any] | None, index: Mapping[str, Sequence[str]] | None = None
) -> list[dict[str, Any]]:
    """One row per unaffiliated session: its label and its node payload."""
    rows: list[dict[str, Any]] = []
    for s in sessions or []:
        rows.append(
            {
                "label": decorate_with_workspace_vars(session_label(s), obj_id(s), index),
                "node_data": session_node_data(s, None, ""),
            }
        )
    return rows


def check_all_cloud_status(
    datasets: Iterable[Any],
    on_progress: Callable[[float, str], None] | None = None,
) -> tuple[dict[str, int], list[str]]:
    """Ask every dataset whether it is linked to NDI Cloud.

    This is the bulk action behind the NDI Cloud pane's "C" button. Each
    dataset is asked the purely local question
    :meth:`ndi.dataset.ndi_dataset.is_in_cloud`, so no network traffic is
    involved.

    ``on_progress`` is called as ``(fraction, message)`` before each dataset,
    which is what drives a progress dialog without this module knowing that
    dialogs exist.

    Returns ``(report, states)``. The report counts ``total``, ``in_cloud``,
    ``not_in_cloud`` and ``errors``; ``states`` is the per-dataset state in
    the same order, one of ``"incloud"``, ``"notincloud"`` or ``"unknown"``,
    for the caller to apply as badges. MATLAB-style keys ``inCloud`` and
    ``notInCloud`` are included as aliases so a consumer that reads the
    report by either name gets the same number; without the aliases such a
    consumer would silently read zero.

    A dataset that cannot be checked counts as an ERROR and gets
    ``"unknown"``, never ``"notincloud"``. The distinction is the whole point
    of the errors field: "we asked and the answer was no" and "we could not
    ask" must not decorate a node the same way.
    """
    items = list(datasets)
    report = {"total": len(items), "in_cloud": 0, "not_in_cloud": 0, "errors": 0}
    states: list[str] = []

    for k, ds in enumerate(items):
        if on_progress is not None:
            on_progress((k + 1) / len(items), f"Checking dataset {k + 1} of {len(items)}...")
        try:
            in_cloud = ds.is_in_cloud()
            # is_in_cloud returns (bool, cloud_id); a bare bool is accepted
            # too, so a caller's stand-in does not have to model the id.
            if isinstance(in_cloud, tuple):
                in_cloud = in_cloud[0]
        except Exception:  # noqa: BLE001
            report["errors"] += 1
            states.append("unknown")
            continue
        if in_cloud:
            report["in_cloud"] += 1
            states.append("incloud")
        else:
            report["not_in_cloud"] += 1
            states.append("notincloud")
    report["inCloud"] = report["in_cloud"]
    report["notInCloud"] = report["not_in_cloud"]
    return report, states
