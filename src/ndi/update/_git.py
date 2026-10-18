"""ndi.update._git - run git in a repository (private helper).

MATLAB counterpart: ``src/ndi/+ndi/+update/private/runGit.m``
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def run_git(repo_dir: str | Path, *args: str, timeout: float = 120) -> tuple[int, str]:
    """Run ``git -C REPO_DIR ARGS...`` and return ``(status, output)``.

    The output is stdout and stderr together with trailing whitespace removed.
    Leading whitespace is kept, because it is meaningful in
    ``git status --porcelain`` output. A missing git program, or a command
    that runs past ``timeout`` seconds, gives a non-zero status rather than
    an exception, as MATLAB's ``system`` does.
    """
    try:
        done = subprocess.run(
            ["git", "-C", str(repo_dir), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return done.returncode, (done.stdout + done.stderr).rstrip()


def git_available() -> bool:
    """True if the git program can be run."""
    status, _ = run_git(".", "--version")
    return status == 0
