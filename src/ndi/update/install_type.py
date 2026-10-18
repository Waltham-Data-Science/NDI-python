"""ndi.update.install_type - how the running copy of NDI-python was installed.

MATLAB counterpart: ``src/ndi/+ndi/+update/installType.m``

MATLAB tells a git clone (``ndi_install``) from the packaged toolbox
(Add-On Explorer). NDI-python has three kinds of install, so it answers
with one of these instead:

``"installer"``
    The NDI installer (``install/install-ndi.sh`` / ``install-ndi.ps1``,
    which NDI-matlab's ``ndi.python.install`` also runs) put it in
    ``~/.ndi/venvs``. Its ``~/.ndi/install.json`` records the commit.
``"git"``
    A clone of NDI-python, installed with ``pip install -e .`` or
    ``python ndi_install.py``.
``"pip"``
    Installed by pip into some other environment, from an archive or wheel.
``"unknown"``
    None of the above could be determined.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import validate_call

__all__ = ["installType", "ndi_home", "read_receipt"]

#: The receipt the NDI installer writes beside bin/, python/ and venvs/.
RECEIPT_NAME = "install.json"


def ndi_home() -> Path:
    """``~/.ndi``, the folder the NDI installer installs under.

    MATLAB counterpart: ``ndi.python.ndiHome``.
    """
    return Path.home() / ".ndi"


def read_receipt(home: str | Path | None = None) -> dict[str, Any] | None:
    """The NDI installer's ``install.json`` as a dict, or None.

    A missing or unreadable receipt is None: it is treated as no receipt.
    """
    path = Path(home or ndi_home()) / RECEIPT_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


@validate_call
def installType(ndiHome: str = "") -> tuple[str, dict[str, Any]]:
    """Return how the running copy of NDI-python was installed.

    MATLAB::

        [TYPE, INFO] = ndi.update.installType()

    Returns:
        ``(type, info)``. ``type`` is ``"installer"``, ``"git"``, ``"pip"`` or
        ``"unknown"`` (see the module docstring). ``info`` has:

        - ``SourceDir``: the folder holding the running ``ndi`` package
        - ``RepoRoot``: root of the git clone (``""`` unless ``"git"``)
        - ``NdiHome``: the ``~/.ndi`` folder that was examined
        - ``Receipt``: the installer's ``install.json`` (a dict) or None

    Python-specific Notes:
        ``ndiHome`` replaces ``~/.ndi`` (tests use it). MATLAB's
        ``ToolboxVersion`` and ``BothInstalled`` have no counterpart: there
        is no packaged NDI-python toolbox.
    """
    import ndi

    source_dir = Path(ndi.__file__).resolve().parent
    home = Path(ndiHome) if ndiHome else ndi_home()
    info: dict[str, Any] = {
        "SourceDir": str(source_dir),
        "RepoRoot": "",
        "NdiHome": str(home),
        "Receipt": None,
    }

    # src/ndi -> src -> repository root
    repo_root = source_dir.parent.parent
    if (repo_root / ".git").exists() and (repo_root / "pyproject.toml").is_file():
        info["RepoRoot"] = str(repo_root)
        return "git", info

    venvs = (home / "venvs").resolve()
    if venvs in source_dir.parents:
        info["Receipt"] = read_receipt(home)
        return "installer", info

    try:
        from importlib.metadata import distribution

        distribution("ndi")
    except Exception:  # noqa: BLE001 - no metadata at all
        return "unknown", info
    return "pip", info
