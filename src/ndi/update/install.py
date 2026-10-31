"""ndi.update.install - update NDI-python to the newest version on main.

MATLAB counterpart: ``src/ndi/+ndi/+update/install.m``
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, validate_call

from ._git import run_git
from .check import check
from .modification_summary import modificationSummary

__all__ = ["install", "UpdateError", "INSTALLER_URL"]

#: Where the NDI installer scripts are published.
INSTALLER_URL = "https://raw.githubusercontent.com/Waltham-Data-Science/NDI-python/main/install"


class UpdateError(RuntimeError):
    """An update that cannot go ahead. ``identifier`` is MATLAB's error id."""

    def __init__(self, identifier: str, message: str):
        super().__init__(message)
        self.identifier = identifier


@validate_call(config=ConfigDict(arbitrary_types_allowed=True))
def install(
    Confirm: bool = True,
    Force: bool = False,
    AllowModified: bool = False,
    Timeout: float = 10,
    RepoRoot: str = "",
    NdiHome: str = "",
    GitHubApi: Callable[[str, float], Any] | None = None,
    Ask: Callable[[str], str] | None = None,
    Packages: list[str] | None = None,
) -> dict[str, Any]:
    """Update NDI-python to the newest version on its main branch.

    MATLAB::

        RESULT = ndi.update.install()
        RESULT = ndi.update.install(Name, Value)

    Checks with :func:`ndi.update.check` and, after asking (``Confirm``),
    installs the update the way NDI-python was installed:

    * **git**: ``git pull origin main`` in the clone (when it is behind),
      then ``python ndi_install.py --update``, which updates the clones in
      ``~/.ndi/tools`` and reinstalls NDI-python and its dependencies into
      this environment. Changed files are stashed for each pull and put back
      afterwards; local commits are merged with the update. The clone must
      be on main. If you have changed code
      (edited tracked files, or local commits) in NDI-python or a
      dependency, the changes are listed first and you are asked whether to
      update anyway; the default answer is No. Untracked files of your own
      are left alone and need no answer, unless one is at a path the update
      adds a file to: git will not overwrite it, so the update stops before
      starting and asks you to move it.
    * **installer**: runs the NDI installer again (``install-ndi.sh --yes
      --no-path``), which reinstalls NDI-python and all its dependencies
      from main. On Windows the running ``ndi`` cannot be replaced while it
      runs, so the installer is started in its own window and waits for
      this process to exit.

    Afterwards NDI's in-memory caches are cleared (``ndi.fun.clearAllCaches``).
    Restart Python (and the navigator) to use the new version.

    Args:
        Confirm: Ask before installing.
        Force: Install even if no update was found.
        AllowModified: With ``Confirm=False``, update even if you have
            changed code. Otherwise an :class:`UpdateError` listing the
            changes is raised. Ignored when ``Confirm`` is true.
        Timeout: Seconds to wait for GitHub.
        RepoRoot: Update the git clone in this folder, not the running copy.
        NdiHome: Treat the installer install under this folder as the one
            to update (tests).
        GitHubApi: Passed to :func:`ndi.update.check` (tests).
        Ask: ``f(prompt) -> reply`` used for questions (default ``input``).
        Packages: Update only these packages (default: all that need it):
            ``"NDI-python"`` and names of dependencies (as in
            :func:`ndi.update.check`'s ``Dependencies``). Named packages that
            are up to date are skipped. For a git install, named
            dependencies are pulled in ``~/.ndi/tools`` and the others are
            not touched; ``"NDI-python"`` pulls main and reinstalls with
            ``ndi_install.py`` without updating the dependency clones; and
            the clone need not be on main unless ``"NDI-python"`` is named.
            Only changes in the named packages need consent.

    Returns:
        The dict :func:`ndi.update.check` returned before updating.

    Raises:
        UpdateError: ``ndi:update:install:notOnMain``,
            ``ndi:update:install:untrackedFilesInTheWay``,
            ``ndi:update:install:localModifications``,
            ``ndi:update:install:noInstaller``,
            ``ndi:update:install:pullFailed``,
            ``ndi:update:install:installFailed``,
            ``ndi:update:install:unknownPackage`` or
            ``ndi:update:install:cannotInstall`` (a pip install).

    Python-specific Notes:
        MATLAB's ``Dependencies`` option (which ndi_install dependency set)
        has no counterpart: NDI-python's dependencies are fixed by
        pyproject.toml. ``Ask`` stands in for MATLAB's ``input``. MATLAB's
        ``IncludeCalculators`` and ``IncludePython`` have no counterpart
        (see :func:`ndi.update.check`); neither do the package names
        ``"NDI-matlab"`` and calculator repositories.
    """
    ask = Ask or input
    result = check(
        Verbose=True, Timeout=Timeout, RepoRoot=RepoRoot, NdiHome=NdiHome, GitHubApi=GitHubApi
    )
    sel = _select_packages(result, Packages)
    kind = result["InstallType"]
    if sel["All"]:
        if not result["UpdateAvailable"] and not Force:
            return result
    elif not sel["Ndi"] and not sel["DepNames"]:
        return result

    if kind == "git":
        _install_git(result, Confirm, AllowModified, ask, sel)
    elif kind == "installer":
        _install_installer(result, Confirm, ask)
    else:
        raise UpdateError(
            "ndi:update:install:cannotInstall",
            "This copy of NDI-python was not installed by the NDI installer or "
            "from a git clone, so ndi.update cannot update it. Update it the "
            "way you installed it.",
        )
    return result


def _install_git(
    result: dict[str, Any],
    confirm: bool,
    allow_modified: bool,
    ask: Callable,
    sel: dict[str, Any],
) -> None:
    """Update NDI-python and its dependencies, or, with SEL naming packages, just those."""
    repo = Path(result["RepoRoot"])
    if sel["All"]:
        pull_ndi = (result["CommitsBehind"] or 0) > 0
        dep_paths = []
        mods = result["Modifications"]
        touched = []
    else:
        pull_ndi = sel["Ndi"]
        dep_paths = [d["Path"] for d in result["Dependencies"] if d["Name"] in sel["DepNames"]]
        touched = list(sel["DepNames"]) + (["NDI-python"] if pull_ndi else [])
        mods = [m for m in result["Modifications"] if m["Name"] in touched]

    # Updating only dependencies leaves NDI-python's branch alone.
    if (sel["All"] or pull_ndi) and result["Branch"] != "main":
        raise UpdateError(
            "ndi:update:install:notOnMain",
            f"NDI-python in {repo} is on branch '{result['Branch']}'. Updates come "
            "from main; run 'git checkout main' there first.",
        )

    blocking = [str(Path(m["Path"]) / f) for m in mods for f in m["BlockingFiles"]]
    if blocking:
        # git pull would stop part-way rather than overwrite these, so no answer
        # to "update anyway?" could make the update work.
        raise UpdateError(
            "ndi:update:install:untrackedFilesInTheWay",
            "The update adds files at these paths, where you have untracked files "
            "of your own. git will not overwrite them, so the update would stop "
            "part-way. Move or rename them, then update again:\n"
            + "\n".join(f"  {f}" for f in blocking),
        )

    if mods:
        summary = modificationSummary({"Modifications": mods}, MaxFiles=25)
        if confirm:
            print(summary)
            if not _confirmed(ask, "Update anyway? Y/N [N]: ", default=False):
                print("Update cancelled; your changes were not touched.")
                return
        elif not allow_modified:
            raise UpdateError(
                "ndi:update:install:localModifications",
                f"{summary}\n\nUpdate cancelled. Commit, move or discard these "
                "changes, or call ndi.update.install(Confirm=False, "
                "AllowModified=True) to update anyway.",
            )
    elif confirm:
        if sel["All"]:
            prompt = (
                f"This will pull main into {repo} and run ndi_install.py --update.\n"
                "Continue? Y/N [Y]: "
            )
        else:
            prompt = f"This will update {', '.join(touched)}.\nContinue? Y/N [Y]: "
        if not _confirmed(ask, prompt):
            print("Update cancelled.")
            return

    run_installer = sel["All"] or pull_ndi
    installer = repo / "ndi_install.py"
    if run_installer and not installer.is_file():
        raise UpdateError(
            "ndi:update:install:noInstaller", f"Could not find ndi_install.py in {repo}."
        )

    if pull_ndi:
        print(f"Updating NDI-python in {repo}...")
        _pull_repo(repo, "origin", "main")
    for path in dep_paths:
        print(f"Updating {Path(path).name} in {path}...")
        _pull_repo(Path(path))

    if run_installer:
        # With every package, ndi_install.py --update also pulls the clones in
        # ~/.ndi/tools; with NDI-python named alone it reinstalls without
        # touching them.
        args = [sys.executable, str(installer)] + (["--update"] if sel["All"] else [])
        done = subprocess.run(args, cwd=str(repo))
        if done.returncode != 0:
            raise UpdateError(
                "ndi:update:install:installFailed",
                f"{installer.name} exited with status {done.returncode} (see above).",
            )
    _clear_caches()
    print("NDI-python update finished. Restart Python to use the new version.")


def _pull_repo(repo: Path, *pull_args: str) -> None:
    """Pull a git clone, setting aside and restoring the user's edits.

    MATLAB counterpart: ``+ndi/+update/private/pullRepo.m``. Edits to tracked
    files are stashed for the pull and put back afterwards; untracked files
    are left alone. If the edits no longer apply cleanly they stay in
    ``git stash list`` and a warning says so. Raises
    ``ndi:update:install:pullFailed`` if the pull fails (the edits are put
    back first). PULL_ARGS go to ``git pull`` (default: the branch's
    upstream); local commits are merged with the update.
    """
    status, out = run_git(repo, "status", "--porcelain", "--untracked-files=no")
    if status != 0:
        raise UpdateError(
            "ndi:update:install:pullFailed", f"Could not read the git status of {repo}: {out}"
        )
    stashed = False
    if out.strip():
        print(f"Setting aside your changes in {repo} while it is updated...")
        # 'git stash' also succeeds when it stashes nothing, and popping then
        # would restore an older, unrelated stash: compare the ref.
        _, before = run_git(repo, "rev-parse", "-q", "--verify", "refs/stash")
        status, out = run_git(repo, "stash")
        _, after = run_git(repo, "rev-parse", "-q", "--verify", "refs/stash")
        if status != 0:
            raise UpdateError(
                "ndi:update:install:pullFailed",
                f"Could not set aside your changes in {repo}: {out}",
            )
        stashed = bool(after) and after != before

    status, pull_out = run_git(repo, "pull", "--no-edit", *pull_args, timeout=600)

    if stashed:
        popped, _ = run_git(repo, "stash", "pop")
        if popped == 0:
            print(f"Your changes in {repo} were put back.")
        else:
            print(
                f"Warning: your changes in {repo} could not be put back cleanly after "
                f'the update. They are still saved: see "git -C {repo} stash list", '
                'and use "git stash pop" there once any conflicts are resolved.'
            )
    if status != 0:
        raise UpdateError("ndi:update:install:pullFailed", f"Updating {repo} failed: {pull_out}")


def _select_packages(result: dict[str, Any], packages: list[str] | None) -> dict[str, Any]:
    """Which packages to update, as MATLAB's selectPackages.

    With no PACKAGES, all that need it (``All``). Otherwise only the named
    ones; those that are up to date are left alone.
    """
    sel: dict[str, Any] = {"All": not packages, "Ndi": False, "DepNames": []}
    if sel["All"]:
        return sel
    dep_names = [d["Name"] for d in result["Dependencies"]]
    known = ["NDI-python", *dep_names]
    unknown = [p for p in packages if p not in known]
    if unknown:
        raise UpdateError(
            "ndi:update:install:unknownPackage",
            f"Unknown package(s): {', '.join(unknown)}. The packages are: {', '.join(known)}.",
        )
    if "NDI-python" in packages:
        if result["InstallType"] == "git":
            sel["Ndi"] = (result["CommitsBehind"] or 0) > 0
        else:
            sel["Ndi"] = bool(result["UpdateAvailable"])
    sel["DepNames"] = [
        d["Name"]
        for d in result["Dependencies"]
        if d["Name"] in packages and d["Status"] in ("behind", "missing")
    ]
    return sel


def _install_installer(result: dict[str, Any], confirm: bool, ask: Callable) -> None:
    if confirm:
        prompt = (
            f"This will run the NDI installer to update NDI-python "
            f"({result['CurrentVersion']} -> {result['LatestVersion']}).\n"
            "Continue? Y/N [Y]: "
        )
        if not _confirmed(ask, prompt):
            print("Update cancelled.")
            return

    windows = os.name == "nt"
    name = "install-ndi.ps1" if windows else "install-ndi.sh"
    work = Path(tempfile.mkdtemp(prefix="ndi-update-"))
    script = work / name
    try:
        urllib.request.urlretrieve(
            f"{INSTALLER_URL}/{name}", script
        )  # noqa: S310 - fixed https host
    except Exception as exc:  # noqa: BLE001
        raise UpdateError(
            "ndi:update:install:installFailed",
            f"Could not download the NDI installer from {INSTALLER_URL}/{name}: {exc}",
        ) from exc

    if windows:
        # The running ndi.exe / python.exe cannot be replaced while they run, so
        # the installer waits in its own window for this process to exit.
        quoted = str(script).replace("'", "''")  # PowerShell single-quoted string
        command = (
            f"Wait-Process -Id {os.getpid()} -ErrorAction SilentlyContinue; "
            f"& '{quoted}' -Yes -NoPath; Read-Host 'Press Enter to close'"
        )
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
        print(
            "The NDI installer has opened in a new window. Close NDI (this "
            "program) to let it finish, then start NDI again."
        )
        return

    try:
        done = subprocess.run(["sh", str(script), "--yes", "--no-path"])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if done.returncode != 0:
        raise UpdateError(
            "ndi:update:install:installFailed",
            f"The NDI installer exited with status {done.returncode} (see above).",
        )
    _clear_caches()
    print("NDI-python update finished. Restart NDI to use the new version.")


def _clear_caches() -> None:
    """Drop in-memory copies the old version built; never fails the update."""
    try:
        from ..fun.cache import clear_all_caches

        clear_all_caches()
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: could not clear NDI caches after updating: {exc}")


def _confirmed(ask: Callable[[str], str], prompt: str, default: bool = True) -> bool:
    """Ask a Y/N question; an empty reply gives DEFAULT."""
    reply = (ask(prompt) or "").strip().lower()
    if not reply:
        return default
    return reply in ("y", "yes")
