"""Pure helpers for ndi.gui.nav.datasets_pane.

MATLAB counterpart: the static methods of
``src/ndi/+ndi/+gui/+nav/datasetsPane.m``

``datasetsPane`` is 1685 lines, most of it tree and menu machinery bound to
widgets. This module is the part that is not: the message builders, the menu
enablement rule, the label decoration, the cloud-response normalisation and
the app-menu ordering. All of it is pure -- no session, no database, no Qt --
and so all of it is exactly testable.

Splitting it out is not tidiness. These are the places where a port bug is
invisible rather than loud: an off-by-one in a plural, a reversed enablement
flag, a sort that is case-sensitive on one side and not the other. None of
those raise; they just quietly say the wrong thing to a user. Every rule here
therefore has a test, and the ones with a stated reason (why "unknown" enables
everything, why an empty report says "no changes") carry that reason in the
docstring rather than only in MATLAB's.

``cloud_summary_message`` is also what ``cloudPane`` needs, so this module
unblocks that pane ahead of the rest of the datasets work.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

__all__ = [
    "append_count_phrase",
    "occupied_folder_message",
    "normalize_cloud_list",
    "cloud_dataset_id_label",
    "first_field",
    "append_workspace_var_names",
    "dataset_menu_enable",
    "cloud_summary_message",
    "cloud_check_message",
    "sync_result_message",
    "order_app_menu",
    "dataset_label",
    "session_label",
    "UNNAMED_DATASET",
    "UNNAMED_SESSION",
]

UNNAMED_DATASET = "(unnamed dataset)"
UNNAMED_SESSION = "(unnamed session)"

#: The sync-report fields summarised by :func:`sync_result_message`, with
#: their singular and plural nouns, in the order MATLAB reports them.
#:
#: Each entry lists the field names to look for, MATLAB's first.
#:
#: ndi.cloud.sync now emits MATLAB's names, so the first name is the one that
#: matches in practice. The short forms it used to emit (``uploaded`` and so
#: on) are still accepted, because reading a report under the wrong name is
#: SILENT here: a missing field and an empty one are indistinguishable, so a
#: sync that moved a hundred documents would summarise as "no changes were
#: needed". Keeping the second name costs nothing and makes that class of
#: regression impossible rather than merely unlikely.
SYNC_FIELDS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("uploaded_document_ids", "uploaded"), "document uploaded", "documents uploaded"),
    (
        ("downloaded_document_ids", "downloaded"),
        "document downloaded",
        "documents downloaded",
    ),
    (
        ("deleted_local_document_ids", "deleted_local"),
        "local document deleted",
        "local documents deleted",
    ),
    (
        ("deleted_remote_document_ids", "deleted_remote"),
        "remote document deleted",
        "remote documents deleted",
    ),
)


def append_count_phrase(
    phrases: list[str],
    report: Mapping[str, Any] | None,
    field: str | Sequence[str],
    singular: str,
    plural: str,
) -> list[str]:
    """Append "N <noun>" for a non-zero count in REPORT.

    An absent field and a zero count both contribute nothing, which is what
    lets :func:`sync_result_message` say "no changes" for a report in which
    nothing happened rather than printing a row of zeroes.

    ``field`` may be several candidate names, in which case the first one
    PRESENT in the report wins -- present, not truthy, so an explicit empty
    list under the first name is honoured rather than falling through to a
    second name that might hold something else.
    """
    if not isinstance(report, Mapping):
        return phrases
    names = (field,) if isinstance(field, str) else tuple(field)
    for name in names:
        if name in report:
            value = report[name]
            break
    else:
        return phrases
    n = len(value) if value is not None else 0
    if n == 1:
        phrases.append(f"1 {singular}")
    elif n > 1:
        phrases.append(f"{n} {plural}")
    return phrases


def occupied_folder_message(directory_type: str) -> str:
    """Explain why a folder cannot host a new session.

    ``directory_type`` is the folder's NDI directory type, already known by
    the caller not to be "none".
    """
    what = {
        "session": "an NDI session",
        "dataset": "an NDI dataset",
    }.get(str(directory_type), "an NDI directory")
    return (
        f"That folder already contains {what}. "
        "Please choose an empty folder for the new session."
    )


def normalize_cloud_list(answer: Any) -> list[Any]:
    """A cloud response to a list of dataset records.

    Accepts the modern wrapper shape (``{"datasets": [...]}``) or an answer
    that is itself the list, and normalises either into a plain list. A single
    record that is not wrapped in a sequence becomes a one-element list rather
    than being iterated character by character -- the failure a bare ``list()``
    would produce on a dict or a string.
    """
    payload = answer
    if isinstance(answer, Mapping) and "datasets" in answer:
        payload = answer["datasets"]
    if payload is None:
        return []
    if isinstance(payload, Mapping):
        return [payload]
    if isinstance(payload, (str, bytes)):
        return []
    if isinstance(payload, Iterable):
        return list(payload)
    return []


def first_field(record: Any, names: Sequence[str]) -> str:
    """The first non-empty value among candidate field NAMES."""
    if not isinstance(record, Mapping):
        return ""
    for name in names:
        value = record.get(name)
        if value:
            return value
    return ""


def cloud_dataset_id_label(record: Any) -> tuple[str, str]:
    """Extract ``(id, display label)`` from a cloud dataset record.

    Field names vary across API versions (``id`` vs ``_id``/``x_id``), so
    several candidates are tried. The label prefers a human name and falls
    back to the id, so a record with neither yields ``("", "")`` rather than
    a label like "  ()".
    """
    identifier = str(first_field(record, ("id", "x_id", "_id", "datasetId")) or "")
    name = str(first_field(record, ("name", "datasetName", "branchName", "reference")) or "")
    if not name:
        return identifier, identifier
    if not identifier:
        return identifier, name
    return identifier, f"{name}  ({identifier})"


def append_workspace_var_names(label: str, names: Sequence[str] | None) -> str:
    """Append quoted workspace variable names to a node label.

    ``append_workspace_var_names("myref", ["S", "S2"])`` gives
    ``'myref "S", "S2"'``. Empty names leave the label unchanged, so a node
    with no workspace variable is not decorated with a stray space.
    """
    label = str(label)
    if not names:
        return label
    quoted = ", ".join(f'"{n}"' for n in names)
    return f"{label} {quoted}"


def dataset_menu_enable(state: Any) -> tuple[bool, bool]:
    """Enable flags for the dataset Cloud menu items.

    Returns ``(upload_enabled, linked_enabled)``:

        ``"incloud"``    -> upload off, linked (check/sync/mirror) on
        ``"notincloud"`` -> upload on, linked off
        anything else    -> both on

    The "anything else" case is deliberate rather than a fallback: before the
    status has been checked the state is unknown, and disabling an action
    because we have not looked yet would block a user for no reason. So an
    unknown state blocks nothing.

    Booleans here rather than MATLAB's ``'on'``/``'off'`` strings, since Qt
    takes ``setEnabled(bool)``; a caller wanting the strings can format them.
    """
    text = str(state)
    if text == "incloud":
        return False, True
    if text == "notincloud":
        return True, False
    return True, True


def cloud_summary_message(report: Mapping[str, Any]) -> str:
    """Summary text for a bulk cloud-status check.

    ``report`` carries ``total``, ``in_cloud`` (or ``inCloud``) and optionally
    ``errors``. When some datasets could not be checked, a trailing note says
    how many -- so a run in which half the checks failed does not read as a
    confident answer about all of them.
    """
    total = int(report.get("total", 0) or 0)
    if total == 0:
        return "There are no datasets to check."

    in_cloud = report.get("in_cloud", report.get("inCloud", 0)) or 0
    noun = "dataset is" if total == 1 else "datasets are"
    msg = f"{int(in_cloud)} of {total} {noun} in NDI Cloud."

    errors = int(report.get("errors", 0) or 0)
    if errors == 1:
        msg += " 1 dataset could not be checked."
    elif errors > 1:
        msg += f" {errors} datasets could not be checked."
    return msg


def cloud_check_message(side: str, count: int) -> str:
    """Status text for a "Check ... for New" command.

    ``side`` is ``"remote"`` (COUNT cloud documents are missing locally) or
    ``"local"`` (COUNT local documents are missing on the cloud).
    """
    count = int(count)
    if side == "remote":
        if count == 0:
            return (
                "There are no new documents on the cloud. Your local dataset "
                "already has every cloud document."
            )
        if count == 1:
            return "There is 1 document on the cloud that is not in your local dataset."
        return f"There are {count} documents on the cloud that are not in your " "local dataset."
    if side == "local":
        if count == 0:
            return (
                "There are no new local documents. Every local document is " "already on the cloud."
            )
        if count == 1:
            return "There is 1 local document that is not on the cloud."
        return f"There are {count} local documents that are not on the cloud."
    raise ValueError("side must be 'remote' or 'local'.")


def sync_result_message(report: Mapping[str, Any] | None) -> str:
    """One-phrase-per-change summary of a sync report.

    Whichever count-bearing fields are present are summarised, one per line.
    The result is mode-agnostic, so it serves every sync operation, and a
    report with no changes says so rather than printing four zeroes.
    """
    phrases: list[str] = []
    for field, singular, plural in SYNC_FIELDS:
        append_count_phrase(phrases, report, field, singular, plural)
    if not phrases:
        return "Done. No changes were needed."
    return "Done. " + "\n".join(phrases)


def order_app_menu(apps: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """The alphabetical layout of the session "Apps" menu.

    Given app records with ``Label`` and optionally ``Category``, returns the
    top-level layout in display order. Each entry is a dict:

        ``kind``  -- ``"app"`` for an uncategorised top-level app, or
                     ``"category"`` for a submenu;
        ``label`` -- the menu text;
        ``apps``  -- for ``"app"``, the single record; for ``"category"``,
                     the category's records in alphabetical order.

    The top level interleaves uncategorised app labels and category names,
    sorted case-INSENSITIVELY. That detail matters: a case-sensitive sort puts
    every capitalised name before every lowercase one, so the two ports would
    order the same menu differently while both looking "sorted".
    """
    if not apps:
        return []

    cat_apps: dict[str, list[Mapping[str, Any]]] = {}
    top: list[tuple[str, str, Mapping[str, Any] | None]] = []

    for app in apps:
        category = str(app.get("Category", "") or "")
        if not category:
            top.append((str(app.get("Label", "")), "app", app))
        elif category not in cat_apps:
            cat_apps[category] = [app]
            top.append((category, "category", None))
        else:
            cat_apps[category].append(app)

    # Stable sort on the lowercased key, so two entries differing only in case
    # keep their discovery order rather than swapping unpredictably.
    entries: list[dict[str, Any]] = []
    for key, kind, app in sorted(top, key=lambda t: t[0].lower()):
        if kind == "app":
            entries.append({"kind": "app", "label": str(app.get("Label", "")), "apps": app})
        else:
            members = sorted(cat_apps[key], key=lambda a: str(a.get("Label", "")).lower())
            entries.append({"kind": "category", "label": key, "apps": members})
    return entries


def dataset_label(ds: Any) -> str:
    """A human-readable reference for a dataset node, best effort."""
    try:
        reference = ds.reference() if callable(ds.reference) else ds.reference
        label = str(reference or "")
    except Exception:  # noqa: BLE001 - a dataset that cannot say is still a node
        label = type(ds).__name__
    return label or UNNAMED_DATASET


def session_label(s: Any) -> str:
    """A human-readable reference for a session node, best effort."""
    try:
        label = str(s.reference or "")
    except Exception:  # noqa: BLE001
        label = type(s).__name__
    return label or UNNAMED_SESSION
