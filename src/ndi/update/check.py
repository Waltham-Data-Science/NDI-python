"""ndi.update.check - is a newer NDI-python available?

MATLAB counterpart: ``src/ndi/+ndi/+update/check.m`` (and, for the installer
case, ``checkPython.m``, which is how NDI-matlab checks this same install).

NDI-python has no releases: every kind of install follows the ``main``
branch on GitHub, so "newer" always means "main has commits this copy
lacks". How that is found depends on the install (see
:func:`ndi.update.installType`):

* **git** -- ``git fetch origin main`` (which changes no files) and a count of
  the commits on ``origin/main`` that ``HEAD`` lacks, as MATLAB does for its
  own clone. The repositories ``ndi_install.py`` cloned into
  ``~/.ndi/tools`` are compared with their upstream branches too, and the
  user's own changes are recorded (``Modifications``).
* **installer** -- the commit in ``~/.ndi/install.json`` is compared with
  main through GitHub's compare API. A receipt with no commit (the installer
  could not reach GitHub's API) gives only its install time, and the commits
  made on main since then are counted; an install older than the receipt
  falls back to the time uv recorded it.
* **pip** -- nothing reliable records what was installed: Status "unknown".
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, validate_call

from ._git import git_available, run_git
from ._github import github_api
from .install_type import installType, read_receipt

__all__ = ["check", "REPOSITORY"]

#: The GitHub repository installs are compared with.
REPOSITORY = "Waltham-Data-Science/NDI-python"

INSTALL_HINT = "Run ndi.update.install() (or `ndi update` in a terminal) to update."


def _empty_result(install_type: str, repo_root: str) -> dict[str, Any]:
    return {
        "InstallType": install_type,
        "Status": "unknown",
        "UpdateAvailable": False,
        "CanInstall": False,
        "CurrentVersion": "",
        "LatestVersion": "",
        "InstalledAt": "",
        "Message": "",
        "Branch": "",
        "CommitsBehind": None,
        "CommitsAhead": None,
        "HasModifications": False,
        "Modifications": [],
        "Dependencies": [],
        "Calculators": [],
        "CalculatorUpdateAvailable": False,
        "RepoRoot": repo_root,
    }


@validate_call(config=ConfigDict(arbitrary_types_allowed=True))
def check(
    IncludeDependencies: bool = True,
    Verbose: bool = True,
    Timeout: float = 10,
    RepoRoot: str = "",
    NdiHome: str = "",
    GitHubApi: Callable[[str, float], Any] | None = None,
) -> dict[str, Any]:
    """Check whether a newer version of NDI-python is available.

    MATLAB::

        RESULT = ndi.update.check()
        RESULT = ndi.update.check(Name, Value)

    Args:
        IncludeDependencies: Also check the repositories ``ndi_install.py``
            cloned into ``~/.ndi/tools`` (git installs only).
        Verbose: Print the summary.
        Timeout: Seconds to wait for GitHub.
        RepoRoot: Check the NDI-python git clone in this folder instead of
            the running copy.
        NdiHome: Check the installer install under this folder (in place of
            ``~/.ndi``) instead of the running copy. Used by tests.
        GitHubApi: ``f(api_path, timeout)`` used to query GitHub in place of
            the REST API. Used by tests.

    Returns:
        A dict with MATLAB's field names: ``InstallType``, ``Status``
        (``"upToDate"``, ``"updateAvailable"``, ``"ahead"`` or ``"unknown"``),
        ``UpdateAvailable``, ``CurrentVersion``, ``LatestVersion``,
        ``Message``, ``Branch``, ``CommitsBehind``, ``CommitsAhead``,
        ``HasModifications``, ``Modifications`` (one dict per repository
        where updating touches the user's work, with ``Name``, ``Path``,
        ``ChangedFiles``, ``BlockingFiles`` -- untracked files at a path the
        update adds a file to, which git will not overwrite -- and
        ``CommitsAhead``; other untracked files are left alone and not
        listed), ``Dependencies`` (``Name``, ``Path``, ``Status``,
        ``CommitsBehind``, ``CurrentVersion`` and ``LatestVersion`` -- short
        commit hashes, or ``""`` -- and ``Url``), ``Calculators``,
        ``CalculatorUpdateAvailable`` and ``RepoRoot``.

    Python-specific Notes:
        Also ``CanInstall`` (``ndi.update.install`` can update this kind of
        install) and ``InstalledAt`` (the install time, when that is all an
        installer receipt gives), the fields NDI-matlab's ``checkPython``
        reports for this same install. A missing count is None where MATLAB
        has NaN. MATLAB's ``ReleaseUrl``, ``MltbxUrl`` and ``BothInstalled``
        belong to its packaged toolbox, which NDI-python does not have.
        ``Calculators`` is always empty and ``CalculatorUpdateAvailable``
        False: MATLAB checks the NDIcalc-*-matlab git clones beside
        NDI-matlab, while NDI-python gets the calculator definitions it uses
        (ndicalc-vis-matlab) as a pip dependency, updated with NDI-python.
        A dependency's ``Url`` is ``""``: the clones in ``~/.ndi/tools`` come
        from ``ndi_install.py``, not from a requirements.txt line.
    """
    api = GitHubApi or github_api
    if RepoRoot:
        install_type, info = "git", {"RepoRoot": RepoRoot, "NdiHome": NdiHome or ""}
    elif NdiHome:
        install_type, info = "installer", {"RepoRoot": "", "NdiHome": NdiHome}
        info["Receipt"] = read_receipt(NdiHome)
    else:
        install_type, info = installType()

    result = _empty_result(install_type, info.get("RepoRoot", ""))
    if install_type == "git":
        result = _check_git(result, info, IncludeDependencies)
    elif install_type == "installer":
        result = _check_installer(result, info, api, Timeout)
    elif install_type == "pip":
        result["Message"] = (
            "NDI-python was installed with pip, which records no version this "
            "check can compare with main. Reinstall it the way you installed it "
            "to update, or use the NDI installer (install/install-ndi.sh)."
        )
    else:
        result["Message"] = (
            "Could not tell how NDI-python was installed, so cannot check for updates."
        )

    if Verbose:
        print(result["Message"])
    return result


# ---------------------------------------------------------------------------
# git installs
# ---------------------------------------------------------------------------


def _check_git(result: dict[str, Any], info: dict[str, Any], include_deps: bool) -> dict[str, Any]:
    repo = info["RepoRoot"]
    if not git_available():
        result["Message"] = (
            "This is a git install of NDI-python, but the git program was not "
            "found, so cannot check for updates."
        )
        return result

    result["CanInstall"] = True
    _, result["Branch"] = run_git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    _, local_hash = run_git(repo, "rev-parse", "HEAD")
    result["CurrentVersion"] = local_hash[:7]

    status, out = run_git(repo, "fetch", "--quiet", "origin", "main")
    if status != 0:
        result["Message"] = (
            "Could not reach the NDI-python repository on GitHub to check for " f"updates: {out}"
        )
        return result

    _, remote_hash = run_git(repo, "rev-parse", "origin/main")
    _, behind = run_git(repo, "rev-list", "--count", "HEAD..origin/main")
    _, ahead = run_git(repo, "rev-list", "--count", "origin/main..HEAD")
    result["LatestVersion"] = remote_hash[:7]
    result["CommitsBehind"] = _to_int(behind)
    result["CommitsAhead"] = _to_int(ahead)

    mods = _local_modifications(
        "NDI-python", repo, result["CommitsAhead"], _incoming_new_files(repo, "origin/main")
    )
    if include_deps:
        tools = Path(info.get("NdiHome") or Path.home() / ".ndi") / "tools"
        deps, dep_mods = _check_dependencies(tools)
        result["Dependencies"] = deps
        mods.extend(dep_mods)
    result["Modifications"] = mods
    result["HasModifications"] = bool(mods)

    deps_behind = [d["Name"] for d in result["Dependencies"] if d["Status"] == "behind"]
    if (result["CommitsBehind"] or 0) > 0:
        result["Status"] = "updateAvailable"
        result["Message"] = (
            "An NDI-python update is available: the main branch on GitHub has "
            f"{result['CommitsBehind']} commit(s) that you do not have (you have "
            f"{result['CurrentVersion']}, latest is {result['LatestVersion']})."
        )
    elif deps_behind:
        result["Status"] = "updateAvailable"
        result["Message"] = (
            "NDI-python is up to date with main, but updates are available for: "
            + ", ".join(deps_behind)
            + "."
        )
    elif (result["CommitsAhead"] or 0) > 0:
        result["Status"] = "ahead"
        result["Message"] = (
            f"NDI-python has all commits from main, plus {result['CommitsAhead']} "
            f"local commit(s) not on main (branch {result['Branch']})."
        )
    else:
        result["Status"] = "upToDate"
        result["Message"] = (
            f"NDI-python is up to date with the main branch on GitHub "
            f"({result['CurrentVersion']})."
        )
    result["UpdateAvailable"] = result["Status"] == "updateAvailable"

    if result["UpdateAvailable"]:
        notes = []
        if result["Branch"] != "main":
            notes.append(
                f"Note: you are on branch '{result['Branch']}', not main. Run "
                f"'git checkout main' in {repo} before updating."
            )
        if result["HasModifications"]:
            names = ", ".join(m["Name"] for m in mods)
            notes.append(
                f"Note: you have changed code in {names}. ndi.update.install will "
                "list the changes and ask before updating."
            )
        notes.append(INSTALL_HINT)
        result["Message"] = "\n".join([result["Message"], *notes])
    return result


def _check_dependencies(tools: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The git clones ndi_install.py keeps in ~/.ndi/tools, against upstream."""
    deps: list[dict[str, Any]] = []
    mods: list[dict[str, Any]] = []
    if not tools.is_dir():
        return deps, mods
    for path in sorted(p for p in tools.iterdir() if (p / ".git").exists()):
        dep = _repo_entry(path.name, path)
        _, local_hash = run_git(path, "rev-parse", "HEAD")
        dep["CurrentVersion"] = local_hash[:7]
        fetched, _ = run_git(path, "fetch", "--quiet")
        counted, behind = run_git(path, "rev-list", "--count", "HEAD..@{u}")
        ahead_status, ahead = run_git(path, "rev-list", "--count", "@{u}..HEAD")
        mods.extend(
            _local_modifications(
                path.name,
                path,
                _to_int(ahead) if ahead_status == 0 else 0,
                _incoming_new_files(path, "@{u}"),
            )
        )
        if fetched == 0 and counted == 0:
            _, upstream_hash = run_git(path, "rev-parse", "@{u}")
            dep["LatestVersion"] = upstream_hash[:7]
            dep["CommitsBehind"] = _to_int(behind)
            dep["Status"] = "behind" if (dep["CommitsBehind"] or 0) > 0 else "upToDate"
        deps.append(dep)
    return deps, mods


def _repo_entry(name: str, path: str | Path) -> dict[str, Any]:
    """A Dependencies entry, as MATLAB's repoEntry."""
    return {
        "Name": name,
        "Path": str(path),
        "Status": "unknown",
        "CommitsBehind": None,
        "CurrentVersion": "",
        "LatestVersion": "",
        "Url": "",
    }


def _local_modifications(
    name: str, repo: str | Path, commits_ahead: int | None, incoming: list[str]
) -> list[dict[str, Any]]:
    """A one-element list if updating REPO would touch the user's work, else [].

    That is: edited tracked files, commits not upstream, or untracked files
    at a path the update adds a file to (``incoming``). Other untracked files
    are not the update's business: git stash and git pull leave them alone.
    """
    # --untracked-files=all lists each file, not just an untracked folder, so
    # an untracked file can be matched against the update's new paths.
    status, out = run_git(repo, "status", "--porcelain", "--untracked-files=all")
    if status != 0:
        return []
    lines = [line for line in out.splitlines() if len(line) > 3]
    changed = [line[3:] for line in lines if not line.startswith("??")]
    incoming_set = set(incoming)
    blocking = [line[3:] for line in lines if line.startswith("??") and line[3:] in incoming_set]
    commits_ahead = commits_ahead or 0
    if not changed and not blocking and commits_ahead == 0:
        return []
    return [
        {
            "Name": name,
            "Path": str(repo),
            "ChangedFiles": changed,
            "BlockingFiles": blocking,
            "CommitsAhead": commits_ahead,
        }
    ]


def _incoming_new_files(repo: str | Path, upstream: str) -> list[str]:
    """Paths that the update (HEAD -> UPSTREAM) adds as new files."""
    status, out = run_git(repo, "diff", "--name-only", "--diff-filter=A", "HEAD", upstream)
    if status != 0:
        return []
    return [line for line in out.splitlines() if line]


# ---------------------------------------------------------------------------
# installer installs
# ---------------------------------------------------------------------------


def _check_installer(
    result: dict[str, Any], info: dict[str, Any], api: Callable[[str, float], Any], timeout: float
) -> dict[str, Any]:
    result["CanInstall"] = True
    home = Path(info["NdiHome"])
    receipt = info.get("Receipt") or {}
    repo = f"repos/{REPOSITORY}"
    try:
        head = api(f"{repo}/commits/main", timeout)
        result["LatestVersion"] = str(head["sha"])[:7]
        sha = receipt.get("commit") or ""
        since_text = ""
        if sha:
            result["CurrentVersion"] = sha[:7]
            compared = api(f"{repo}/compare/{sha}...main", timeout)
            result["CommitsBehind"] = int(compared["ahead_by"])
        else:
            installed_at = _install_time(receipt, home)
            if installed_at is None:
                result["Message"] = (
                    "NDI-python was installed by the NDI installer, but which "
                    "version could not be determined. Run ndi.update.install() "
                    "to reinstall the latest."
                )
                return result
            stamp = installed_at.strftime("%Y-%m-%dT%H:%M:%SZ")
            result["InstalledAt"] = stamp
            result["CurrentVersion"] = "installed " + stamp[:10]
            commits = api(f"{repo}/commits?sha=main&per_page=100&since={stamp}", timeout)
            result["CommitsBehind"] = len(commits)
            since_text = f" since it was installed on {stamp[:10]}"
    except Exception as exc:  # noqa: BLE001 - offline or rate-limited: say so, never raise
        result["Status"] = "unknown"
        result["Message"] = f"Could not reach GitHub to check NDI-python for updates: {exc}"
        return result

    behind = result["CommitsBehind"]
    if behind > 0:
        count = "100 or more" if since_text and behind >= 100 else str(behind)
        result["Status"] = "updateAvailable"
        result["UpdateAvailable"] = True
        result["Message"] = (
            f"An NDI-python update is available: main has {count} commit(s)"
            f"{since_text} that the installed copy lacks (latest is "
            f"{result['LatestVersion']}).\n{INSTALL_HINT}"
        )
    else:
        result["Status"] = "upToDate"
        result["Message"] = f"NDI-python is up to date with main ({result['LatestVersion']})."
    return result


def _install_time(receipt: dict[str, Any], home: Path) -> datetime | None:
    """When the installer last installed NDI, from the receipt or uv's record."""
    stamp = receipt.get("installedAt")
    if stamp:
        try:
            return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    # Installs made before the installer wrote receipts: uv rewrites this
    # file each time it installs the 'ndi' tool.
    uv_receipt = home / "venvs" / "ndi" / "uv-receipt.toml"
    if uv_receipt.is_file():
        return datetime.fromtimestamp(uv_receipt.stat().st_mtime, tz=timezone.utc)
    return None


def _to_int(text: str) -> int | None:
    try:
        return int(text.strip())
    except (ValueError, AttributeError):
        return None
