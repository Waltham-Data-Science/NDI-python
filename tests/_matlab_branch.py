"""Reading a named NDI-matlab branch, for counterparts not yet on its main.

Some NDI-python work lands before its MATLAB half: the lightsheet OME-Zarr
documents and functions, and ``resolveOrganizationId``, were written as a
pair with VH-Lab/NDI-matlab ``claude/lightsheet-zarr-ndi-viewer-djp5vk`` and
merged here while that branch was still open. The bridge checks compare
against the checked-out NDI-matlab tree (its ``main`` unless a branch of the
same name exists), so those records looked stale -- a MATLAB file "that does
not exist" -- when the truth is "exists, not merged yet".

A bridge entry says so with ``matlab_branch: <NDI-matlab branch>``, and an
``ndi_common`` file with an entry in ``MATLAB_BRANCH_PENDING``. The checks
then verify the claim against that branch instead of skipping it: the file
must be there, drift is measured against the branch tip, and once the branch
is merged the marker must go (see section 8 of
docs/developer_notes/ndi_matlab_python_bridge.yaml).

These helpers read the branch through git, so they need the NDI-matlab
checkout's remote branches -- which ``actions/checkout`` provides with
``fetch-depth: 0``, and the bridge job already asks for that.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def pending_branch(entry: dict[str, Any]) -> str:
    """The entry's ``matlab_branch``, or ``""`` when it names none."""
    value = entry.get("matlab_branch")
    return value.strip() if isinstance(value, str) else ""


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=False)


def branch_ref(repo: Path, branch: str) -> str | None:
    """The commit at the tip of BRANCH in REPO, or None if it is not there.

    Tries the remote-tracking ref first, since that is what a CI checkout
    holds, then a local branch of that name.
    """
    for ref in (f"refs/remotes/origin/{branch}", f"refs/heads/{branch}"):
        result = _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        if result.returncode == 0:
            return result.stdout.decode().strip()
    return None


def read_on_branch(repo: Path, commit: str, repo_path: str) -> bytes | None:
    """The bytes of REPO_PATH (relative to the repo root) at COMMIT, or None."""
    result = _git(repo, "show", f"{commit}:{repo_path}")
    return result.stdout if result.returncode == 0 else None


#: NDI-matlab's default branch. "Merged" means merged here, not into whatever
#: happens to be checked out: CI checks out a same-named NDI-matlab branch
#: when one exists, and on the pending branch itself HEAD contains its own
#: tip by definition.
MAIN_BRANCH = "main"


def is_merged(repo: Path, commit: str) -> bool:
    """True if COMMIT is already part of NDI-matlab main."""
    main = branch_ref(repo, MAIN_BRANCH)
    if main is None:
        return False
    return _git(repo, "merge-base", "--is-ancestor", commit, main).returncode == 0
