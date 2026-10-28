"""ndi.update.packageStatus - one row per package for an update dialog.

MATLAB counterpart: ``src/ndi/+ndi/+update/packageStatus.m``
"""

from __future__ import annotations

import os
from typing import Any

__all__ = ["packageStatus", "package_status"]

_LEVELS = ["", "info", "warning", "error"]


def packageStatus(result: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Describe each package :func:`ndi.update.install` would look at.

    MATLAB::

        [ROWS, SUMMARY] = ndi.update.packageStatus(RESULT)

    Given RESULT from :func:`ndi.update.check`, lists the packages in the
    order an update dialog shows them:

    * git installs: NDI-python, then each dependency clone in ``~/.ndi/tools``
    * installer installs: NDI-python

    Args:
        result: The dict returned by :func:`ndi.update.check`.

    Returns:
        ``(rows, summary)``. Each row is a dict with MATLAB's fields: ``Name``,
        ``Kind`` (``"ndi"``, ``"installer"`` or ``"dependency"``), ``Path``,
        ``Installed``, ``Latest``, ``Status`` (short text, e.g. ``"3 new
        commits"``), ``WillUpdate``, ``Notes``, ``NoteLevels`` (``"info"``,
        ``"warning"`` or ``"error"`` per note), ``NoteLevel`` (the most
        serious, or ``""``), ``Details`` (longer text: path, notes, files),
        ``Blocked``, ``TouchesChanges`` (updating stashes, merges or
        overwrites code you changed), ``Files`` (``"changed:    ..."`` /
        ``"in the way: ..."``), ``Selectable`` (``WillUpdate`` and not
        ``Blocked``) and ``Selected`` (starts ticked: selectable and not
        touching your changes). ``summary`` has ``CanUpdate``, ``AnyUpdate``,
        ``Blocked``, ``HasUserChanges`` and ``Message``.

        ``WillUpdate``, ``TouchesChanges`` and the notes describe what
        happens to a package if it is ticked: ``ndi.update.install(Packages=
        ...)`` updates only the packages named.

    Python-specific Notes:
        MATLAB's toolbox row has no counterpart; an installer install is one
        ``"installer"`` row for NDI-python, updated by running the NDI
        installer again. There are no calculator rows (see
        :func:`ndi.update.check`) and no separate NDI-python row: NDI-python
        is the package being checked.
    """
    kind = result.get("InstallType")
    if kind == "git":
        rows = _git_rows(result)
    elif kind == "installer":
        rows = [_installer_row(result)]
    else:
        r = _new_row("NDI-python", "ndi", "")
        r["Status"] = "Could not check"
        _add_note(r, "info", _first_line(result.get("Message", "")))
        rows = [r]

    for r in rows:
        r["Details"] = _details(r)
        r["Selectable"] = r["WillUpdate"] and not r["Blocked"]
        # Leave out, at first, packages where you have work of your own.
        r["Selected"] = r["Selectable"] and not r["TouchesChanges"]

    n = sum(r["Selectable"] for r in rows)
    summary: dict[str, Any] = {
        "AnyUpdate": any(r["WillUpdate"] for r in rows),
        "Blocked": any(r["Blocked"] for r in rows),
        "CanUpdate": n > 0,
        "HasUserChanges": any(r["TouchesChanges"] for r in rows),
    }
    if summary["AnyUpdate"] and n == 0:
        summary["Message"] = (
            "Updates are available, but none can be installed yet: see the "
            "packages marked with an error."
        )
    elif summary["AnyUpdate"]:
        summary["Message"] = f"{n} package(s) can be updated. Tick the ones to update."
        if summary["Blocked"]:
            summary["Message"] += " Packages marked with an error cannot be updated yet."
    else:
        summary["Message"] = "Everything is up to date."
    return rows, summary


#: Snake-case alias for MATLAB's name; one function under two names.
package_status = packageStatus


def _git_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    r = _new_row("NDI-python", "ndi", result.get("RepoRoot", ""))
    r["Installed"] = result.get("CurrentVersion", "")
    r["Latest"] = result.get("LatestVersion", "")
    behind = result.get("CommitsBehind") or 0
    ahead = result.get("CommitsAhead") or 0
    r["WillUpdate"] = behind > 0
    if behind > 0:
        r["Status"] = _commits_text(behind)
    elif result.get("Status") == "unknown":
        r["Status"] = "Could not check"
    elif ahead > 0:
        r["Status"] = f"{ahead} local commit(s)"
    else:
        r["Status"] = "Up to date"
    if result.get("Status") == "unknown":
        _add_note(r, "info", _first_line(result.get("Message", "")))
    if result.get("UpdateAvailable") and result.get("Branch") != "main":
        _add_note(
            r,
            "error",
            f"On branch '{result.get('Branch')}', not main. Run 'git checkout main' in "
            f"{result.get('RepoRoot')} first.",
        )
        r["Blocked"] = True
    _modification_notes(r, result, r["WillUpdate"])
    rows = [r]

    for d in result.get("Dependencies", []):
        r = _repo_row(d, "dependency")
        r["WillUpdate"] = d.get("Status") in ("behind", "missing")
        if d.get("Status") == "notGit":
            _add_note(r, "info", "Not a git clone, so it is not updated here.")
        _modification_notes(r, result, r["WillUpdate"])
        rows.append(r)
    return rows


def _installer_row(result: dict[str, Any]) -> dict[str, Any]:
    r = _new_row("NDI-python", "installer", "")
    r["Installed"] = result.get("CurrentVersion", "")
    r["Latest"] = result.get("LatestVersion", "")
    r["WillUpdate"] = bool(result.get("UpdateAvailable") and result.get("CanInstall"))
    status = result.get("Status")
    behind = result.get("CommitsBehind")
    if status == "updateAvailable":
        r["Status"] = _commits_text(behind) if behind else "Update available"
    elif status == "upToDate":
        r["Status"] = "Up to date"
    else:
        r["Status"] = "Could not check"
        _add_note(r, "info", _first_line(result.get("Message", "")))
    if r["WillUpdate"]:
        _add_note(r, "info", "Updated by running the NDI installer again.")
        if os.name == "nt":
            _add_note(
                r,
                "info",
                "The installer opens in its own window and finishes after you close NDI.",
            )
        _add_note(r, "info", "Restart NDI after updating.")
    return r


def _repo_row(d: dict[str, Any], kind: str) -> dict[str, Any]:
    r = _new_row(d.get("Name", ""), kind, d.get("Path", ""))
    r["Installed"] = d.get("CurrentVersion", "")
    r["Latest"] = d.get("LatestVersion", "")
    status = d.get("Status")
    r["Status"] = {
        "missing": "Not installed; will be added",
        "upToDate": "Up to date",
        "pinned": "Pinned",
        "notFound": "Not found",
        "notGit": "Not a git clone",
    }.get(status, "Could not check")
    if status == "behind":
        r["Status"] = _commits_text(d.get("CommitsBehind") or 0)
    return r


def _modification_notes(r: dict[str, Any], result: dict[str, Any], affected: bool) -> None:
    """Notes on what updating does to the user's own changes in R's repository.

    AFFECTED: the update runs git stash and git pull there.
    """
    mods = [m for m in result.get("Modifications") or [] if m.get("Name") == r["Name"]]
    if not mods:
        return
    m = mods[0]
    changed = list(m.get("ChangedFiles") or [])
    blocking = list(m.get("BlockingFiles") or [])
    ahead = m.get("CommitsAhead") or 0
    if blocking:
        _add_note(
            r,
            "error",
            f"{len(blocking)} untracked file(s) are where the update adds files; "
            "move or rename them first.",
        )
        r["Blocked"] = True
    if affected:
        r["TouchesChanges"] = bool(changed) or ahead > 0
        if changed:
            _add_note(
                r,
                "warning",
                f"{len(changed)} changed file(s) will be stashed and put back after the update.",
            )
        if ahead > 0:
            _add_note(r, "warning", f"{ahead} local commit(s) will be merged with the update.")
    elif changed or ahead > 0:
        _add_note(r, "info", "You have changed code here; it is not touched.")
    r["Files"] = [f"changed:    {f}" for f in changed] + [f"in the way: {f}" for f in blocking]


def _details(r: dict[str, Any]) -> str:
    parts = [r["Name"]]
    if r["Path"]:
        parts.append(r["Path"])
    parts.append(f"Status: {r['Status']}")
    if r["Notes"]:
        parts.append("")
        parts.extend(f"- [{lvl}] {note}" for lvl, note in zip(r["NoteLevels"], r["Notes"]))
    if r["Files"]:
        shown = r["Files"][:25]
        parts.append("")
        parts.extend(f"  {f}" for f in shown)
        if len(r["Files"]) > len(shown):
            parts.append(f"  ... and {len(r['Files']) - len(shown)} more")
    return "\n".join(parts)


def _add_note(r: dict[str, Any], level: str, text: str) -> None:
    r["Notes"].append(str(text))
    r["NoteLevels"].append(level)
    if _LEVELS.index(level) > _LEVELS.index(r["NoteLevel"]):
        r["NoteLevel"] = level


def _commits_text(n: int) -> str:
    return "1 new commit" if n == 1 else f"{n} new commits"


def _first_line(text: str) -> str:
    return str(text).splitlines()[0] if str(text) else ""


def _new_row(name: str, kind: str, folder: str) -> dict[str, Any]:
    return {
        "Name": str(name),
        "Kind": kind,
        "Path": str(folder),
        "Installed": "",
        "Latest": "",
        "Status": "",
        "WillUpdate": False,
        "Notes": [],
        "NoteLevels": [],
        "NoteLevel": "",
        "Details": "",
        "Blocked": False,
        "TouchesChanges": False,
        "Files": [],
        "Selectable": False,
        "Selected": False,
    }
