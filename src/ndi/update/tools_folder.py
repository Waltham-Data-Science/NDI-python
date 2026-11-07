"""ndi.update.tools_folder - where ndi_install.py keeps its clones, and moving them.

MATLAB counterparts: ``src/ndi/+ndi/+update/toolsFolder.m`` and
``src/ndi/+ndi/+update/moveToolsFolder.m``

``python ndi_install.py`` clones the dependencies that are not on PyPI
(vhlab-toolbox-python) into a tools folder, ``~/.ndi/tools`` unless
``--tools-dir`` says otherwise, and writes ``ndi-deps.pth`` into the
environment's site-packages so Python finds them. That ``.pth`` file is the
record of where the tools folder is, the way NDI-matlab's ``startup.m`` line
is: :func:`toolsFolder` reads it, and :func:`moveToolsFolder` moves the
folder and rewrites it.

Only git installs (a clone of NDI-python set up with ``ndi_install.py``) have
a tools folder. The NDI installer (``install/install-ndi.sh``) keeps
everything in ``~/.ndi`` and has none.
"""

from __future__ import annotations

import os
import shutil
import site
import stat
import sys
import sysconfig
import warnings
from pathlib import Path
from typing import Any

from pydantic import validate_call

__all__ = [
    "PTH_FILENAME",
    "find_pth_file",
    "tools_folder_from_pth",
    "tools_folder_target",
    "toolsFolder",
    "moveToolsFolder",
]

#: The file ndi_install.py writes into site-packages (its PTH_FILENAME).
PTH_FILENAME = "ndi-deps.pth"


def _site_dirs() -> list[Path]:
    """The site-packages folders of this environment, most specific first."""
    dirs: list[Path] = []
    purelib = sysconfig.get_paths().get("purelib")
    if purelib:
        dirs.append(Path(purelib))
    try:
        dirs.extend(Path(p) for p in site.getsitepackages())
    except AttributeError:  # pragma: no cover - some embedded interpreters
        pass
    try:
        dirs.append(Path(site.getusersitepackages()))
    except AttributeError:  # pragma: no cover
        pass
    unique: list[Path] = []
    for d in dirs:
        if d not in unique:
            unique.append(d)
    return unique


def find_pth_file() -> Path | None:
    """The ``ndi-deps.pth`` that ndi_install.py wrote for this environment, or None."""
    for d in _site_dirs():
        candidate = d / PTH_FILENAME
        if candidate.is_file():
            return candidate
    return None


def _pth_entries(pth_file: Path) -> list[str]:
    """The folder lines of a .pth file (not blank lines, comments or imports)."""
    try:
        text = pth_file.read_text(encoding="utf-8")
    except OSError:
        return []
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.startswith("#") and not line.startswith("import ")
    ]


def tools_folder_from_pth(pth_file: str | Path) -> str:
    """The tools folder an ``ndi-deps.pth`` points into, or ``""``.

    Each line is a dependency folder (or a folder inside one); the tools
    folder holds the dependency clones, so it is the parent of the first
    folder, walking up from a line, that is a git clone.
    """
    for entry in _pth_entries(Path(pth_file)):
        path = Path(entry)
        for candidate in (path, *path.parents):
            if (candidate / ".git").exists():
                return str(candidate.parent)
        return str(path.parent)
    return ""


def _tools_folder(ndi_home: str = "") -> Path:
    """The tools folder of a git install, without checking that it is one.

    ``ndi_home`` (tests) means ``<ndi_home>/tools``. Otherwise the folder the
    ``ndi-deps.pth`` of this environment points into, and ``~/.ndi/tools``
    (ndi_install.py's default) if there is no such file.
    """
    if ndi_home:
        return Path(ndi_home) / "tools"
    pth = find_pth_file()
    if pth is not None:
        folder = tools_folder_from_pth(pth)
        if folder:
            return Path(folder)
    return Path.home() / ".ndi" / "tools"


@validate_call
def toolsFolder() -> str:
    """The folder ndi_install.py cloned NDI-python's dependencies into.

    MATLAB::

        FOLDER = ndi.update.toolsFolder()

    Returns ``""`` unless NDI-python is a git clone (see
    :func:`ndi.update.installType`): the NDI installer keeps everything in
    ``~/.ndi`` and has no tools folder.

    Python-specific Notes:
        MATLAB's tools folder holds NDI-matlab itself too, because
        ``ndi_install.m`` clones it there. ``ndi_install.py`` runs from a
        clone of NDI-python that you made yourself, wherever you made it, so
        this folder holds only the dependency clones; NDI-python's own clone
        is ``installType()[1]["RepoRoot"]``.
    """
    from .install_type import installType

    kind, _ = installType()
    if kind != "git":
        return ""
    return str(_tools_folder())


def tools_folder_target(picked: str | Path, current: str | Path) -> str:
    """Where the tools go, given the folder the user picked in a dialog.

    The picked folder itself if it is empty (the user made a folder for the
    tools); otherwise a folder inside it named like the current tools folder
    (usually ``tools``), so the tools are not mixed in with what is there.
    MATLAB counterpart: ``toolsFolderTarget`` in ``preferencesEditor.m``.
    """
    picked = Path(picked)
    if picked.is_dir() and not any(picked.iterdir()):
        return str(picked)
    return str(picked / Path(current).name)


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(str(a)) == os.path.normcase(str(b))


def _inside(child: Path, parent: Path) -> bool:
    child_s = os.path.normcase(str(child))
    parent_s = os.path.normcase(str(parent)).rstrip(os.sep) + os.sep
    return child_s.startswith(parent_s)


def _relocate(entry: str, from_names: list[Path], to: Path) -> str:
    """ENTRY moved from under one of FROM_NAMES to the same place under TO."""
    path = Path(entry)
    for old in from_names:
        if _same(path, old):
            return str(to)
        if _inside(path, old):
            # Sliced rather than relative_to: on Windows the two can differ in case.
            rest = str(path)[len(str(old).rstrip(os.sep)) :].lstrip(os.sep)
            return str(to / rest)
    return entry


def _count_files(folder: Path) -> int:
    return sum(len(files) for _, _, files in os.walk(folder))


def _rmtree(folder: Path) -> None:
    """shutil.rmtree that also removes read-only files (git objects on Windows)."""

    def make_writable_and_retry(func: Any, path: str, _exc: Any) -> None:
        os.chmod(path, stat.S_IWRITE)
        func(path)

    if sys.version_info >= (3, 12):
        shutil.rmtree(folder, onexc=make_writable_and_retry)
    else:  # pragma: no cover - Python 3.10/3.11
        shutil.rmtree(folder, onerror=make_writable_and_retry)


def _remove_copy(to: Path, created: bool) -> None:
    """Remove what was copied into TO (new, or empty, before). Never raises."""
    try:
        if created:
            _rmtree(to)
        else:
            for item in to.iterdir():
                if item.is_dir() and not item.is_symlink():
                    _rmtree(item)
                else:
                    item.unlink()
    except OSError:
        pass


@validate_call
def moveToolsFolder(
    newFolder: str,
    Confirm: bool = True,
    DeleteOld: bool = True,
    UpdatePath: bool = True,
    From: str = "",
    PthFile: str = "",
) -> dict[str, Any]:
    """Move the tools folder ndi_install.py cloned into, and point Python at it.

    MATLAB::

        RESULT = ndi.update.moveToolsFolder(NEWFOLDER)

    The steps, in order (as in MATLAB):

    1. Check everything first: ``newFolder`` must be a full path, must not
       exist or be an empty folder, and must not be inside the tools folder;
       ``ndi-deps.pth`` must point into the tools folder. If anything is
       wrong, nothing is changed.
    2. Copy the whole tools folder to ``newFolder`` and check that every
       file arrived. If the copy fails, the partial copy is removed and
       nothing else is changed.
    3. Rewrite ``ndi-deps.pth`` so it points into ``newFolder``. The
       previous one is kept beside it as ``ndi-deps.pth.bak``.
    4. Change ``sys.path`` of this process to match.
    5. Delete the old tools folder. If that fails, a warning says so.

    Restart Python afterwards. ``python ndi_install.py`` (and
    ``ndi.update.install``) then keep using the new folder: with no
    ``--tools-dir``, ndi_install.py uses the folder ``ndi-deps.pth`` points
    into.

    Args:
        newFolder: The new tools folder. ``~`` is expanded.
        Confirm: Describe what will happen and ask before doing it. The
            preferences editor asks in its own window and passes False.
        DeleteOld: Delete the old tools folder at the end.
        UpdatePath: Change ``sys.path`` of this process.
        From: The tools folder to move (default :func:`toolsFolder`). Tests.
        PthFile: The ``.pth`` file to rewrite (default: the one in this
            environment's site-packages). Tests.

    Returns:
        A dict with ``Moved``, ``From``, ``To``, ``PthFile``, ``PthBackup``
        and ``OldDeleted`` (MATLAB's ``StartupFile`` / ``StartupBackup`` are
        ``PthFile`` / ``PthBackup`` here).

    Raises:
        UpdateError: with MATLAB's identifiers, ``ndi:update:moveToolsFolder:``
            ``notGit``, ``noFolder``, ``relativePath``, ``sameFolder``,
            ``insideOld``, ``notEmpty``, ``noPthFile`` (MATLAB:
            ``noStartupFile``), ``noPthLine`` (MATLAB: ``noStartupLine``),
            ``copyFailed`` and ``pthWriteFailed`` (MATLAB:
            ``startupWriteFailed``).

    Python-specific Notes:
        Python rewrites ``ndi-deps.pth`` where MATLAB rewrites ``startup.m``:
        each is what tells its language where the tools are. A ``~`` in
        ``newFolder`` is expanded (MATLAB refuses it, because MATLAB does not
        expand ``~``).
    """
    from .install import UpdateError

    def fail(name: str, message: str) -> UpdateError:
        return UpdateError(f"ndi:update:moveToolsFolder:{name}", message)

    # ---- 1. checks; nothing is changed until all of them pass ----
    if From:
        from_raw = Path(From)
    else:
        folder = toolsFolder()
        if not folder:
            raise fail(
                "notGit",
                "NDI-python is not a git clone set up with ndi_install.py (it may be "
                "installed with the NDI installer, in ~/.ndi), so there is no tools "
                "folder to move.",
            )
        from_raw = Path(folder)
    if not from_raw.is_dir():
        raise fail("noFolder", f"The tools folder {from_raw} does not exist.")
    source = from_raw.resolve()
    from_names = [from_raw.absolute()]
    if source not in from_names:
        from_names.append(source)

    target_raw = Path(newFolder.strip()).expanduser()
    if not target_raw.is_absolute():
        raise fail(
            "relativePath",
            "Give the full path of the new folder, such as /Users/me/ndi-tools or "
            f"C:\\ndi-tools (not {newFolder}).",
        )
    target = target_raw.resolve()

    if _same(target, source):
        raise fail("sameFolder", f"The tools are already in {source}.")
    if _inside(target, source):
        raise fail(
            "insideOld", f"The new folder {target} is inside the current tools folder {source}."
        )
    if target.is_file() or (target.is_dir() and any(target.iterdir())):
        raise fail(
            "notEmpty",
            f"{target} already exists and is not an empty folder. Choose a new folder, "
            "or an empty one.",
        )

    pth = Path(PthFile) if PthFile else find_pth_file()
    if pth is None or not pth.is_file():
        raise fail(
            "noPthFile",
            f"There is no {PTH_FILENAME} in this environment's site-packages, so Python "
            "does not load the tools from a tools folder. Run python ndi_install.py first.",
        )
    old_text = pth.read_text(encoding="utf-8")
    new_lines: list[str] = []
    n_changed = 0
    for line in old_text.splitlines():
        moved = _relocate(line.strip(), from_names, target) if line.strip() else line
        if line.strip() and moved != line.strip():
            n_changed += 1
            new_lines.append(moved)
        else:
            new_lines.append(line)
    if n_changed == 0:
        raise fail(
            "noPthLine",
            f"{pth} has no line inside {source}, so the tools cannot be moved "
            "automatically. Move the folder yourself and run python ndi_install.py "
            "--tools-dir with the new folder.",
        )
    new_text = "\n".join(new_lines) + ("\n" if old_text.endswith("\n") else "")

    result: dict[str, Any] = {
        "Moved": False,
        "From": str(source),
        "To": str(target),
        "PthFile": str(pth),
        "PthBackup": str(pth) + ".bak",
        "OldDeleted": False,
    }

    if Confirm:
        print("This will move the NDI-python tools folder")
        print(f"    from {source}")
        print(f"    to   {target}")
        print(f"It copies the folder, checks the copy, points {pth} to the new folder,")
        if DeleteOld:
            print("and deletes the old folder. Restart Python afterwards.")
        else:
            print("and leaves the old folder in place. Restart Python afterwards.")
        reply = input("Move the tools folder? Y/N [N]: ")
        if reply.strip().lower() != "y":
            print("Nothing was changed.")
            return result

    # ---- 2. copy, and check the copy ----
    created = not target.is_dir()
    print(f"Copying {source} to {target}...")
    try:
        shutil.copytree(source, target, symlinks=True, dirs_exist_ok=True)
        n_from, n_to = _count_files(source), _count_files(target)
        if n_to < n_from:
            raise OSError(f"Only {n_to} of the {n_from} files in {source} were copied to {target}.")
    except OSError as exc:
        _remove_copy(target, created)
        raise fail(
            "copyFailed",
            f"Copying {source} to {target} failed: {exc}\n"
            "Nothing was changed; the partial copy was removed.",
        ) from exc

    # ---- 3. the .pth file ----
    try:
        shutil.copyfile(pth, result["PthBackup"])
        pth.write_text(new_text, encoding="utf-8")
    except OSError as exc:
        _remove_copy(target, created)
        raise fail(
            "pthWriteFailed",
            f"Could not update {pth}: {exc}\nNothing was changed; the copy in {target} "
            "was removed.",
        ) from exc
    print(f"Updated {pth} (the previous version is {result['PthBackup']}).")
    result["Moved"] = True

    # ---- 4. this process's sys.path ----
    if UpdatePath:
        sys.path[:] = [_relocate(p, from_names, target) if p else p for p in sys.path]

    # ---- 5. the old folder ----
    if DeleteOld:
        try:
            _rmtree(source)
            result["OldDeleted"] = True
            print(f"Deleted {source}.")
        except OSError as exc:
            warnings.warn(
                f"The tools were moved to {target}, but the old folder {source} could not "
                f"be deleted completely ({exc}). Delete it yourself after restarting Python.",
                stacklevel=2,
            )

    print(f"The NDI-python tools are now in {target}. Please restart Python.")
    return result
