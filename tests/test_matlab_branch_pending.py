"""The ``matlab_branch`` helpers answer correctly, against a real git repo.

MATLAB counterpart: none; this tests the bridge checks themselves.

``matlab_branch`` lets a bridge entry (and ``MATLAB_BRANCH_PENDING`` an
``ndi_common`` file) say "the MATLAB side is on this NDI-matlab branch, not
yet on main" -- section 8 of docs/developer_notes/ndi_matlab_python_bridge.yaml.
The checks exempt such a record from "file must exist in the checked-out
tree" and verify it against the branch instead, so everything rests on
:mod:`tests._matlab_branch` telling the truth. A helper that always said
"found" would let any typo through; one that never said "merged" would let
the marker outlive its branch.

The repo is built in a temporary directory, so this needs no NDI-matlab
checkout and runs in every job.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests._matlab_branch import branch_ref, is_merged, pending_branch, read_on_branch

FILE = "src/ndi/+ndi/+fun/+doc/+lightsheet/view.m"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """main with one commit; ``feature`` one commit ahead, adding FILE."""
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "user.name", "test")
    (tmp_path / "README").write_text("main\n")
    git(tmp_path, "add", "README")
    git(tmp_path, "commit", "-q", "-m", "main")
    git(tmp_path, "checkout", "-q", "-b", "feature")
    (tmp_path / FILE).parent.mkdir(parents=True)
    (tmp_path / FILE).write_text("function view()\n")
    git(tmp_path, "add", FILE)
    git(tmp_path, "commit", "-q", "-m", "feature")
    git(tmp_path, "checkout", "-q", "main")
    return tmp_path


def test_a_branch_resolves_to_its_tip(repo):
    assert branch_ref(repo, "feature") == git(repo, "rev-parse", "feature")


def test_a_missing_branch_resolves_to_nothing(repo):
    assert branch_ref(repo, "no-such-branch") is None


def test_a_file_on_the_branch_is_read_from_it(repo):
    tip = branch_ref(repo, "feature")
    assert read_on_branch(repo, tip, FILE) == b"function view()\n"
    assert not (repo / FILE).exists(), "the file is on the branch, not the checkout"


def test_a_file_not_on_the_branch_is_reported_absent(repo):
    tip = branch_ref(repo, "feature")
    assert read_on_branch(repo, tip, FILE.replace("view", "veiw")) is None


def test_an_unmerged_branch_is_not_merged(repo):
    assert not is_merged(repo, branch_ref(repo, "feature"))


def test_checking_out_the_branch_does_not_make_it_merged(repo):
    """CI checks out a same-named NDI-matlab branch when one exists. HEAD
    then contains the branch tip, which must not read as "merged"."""
    git(repo, "checkout", "-q", "feature")
    assert not is_merged(repo, branch_ref(repo, "feature"))


def test_a_branch_merged_into_main_is_merged(repo):
    git(repo, "merge", "-q", "--no-ff", "-m", "merge", "feature")
    assert is_merged(repo, branch_ref(repo, "feature"))


@pytest.mark.parametrize(
    "entry, expected",
    [
        ({"matlab_branch": "feature"}, "feature"),
        ({"matlab_branch": "  feature  "}, "feature"),
        ({}, ""),
        ({"matlab_branch": None}, ""),
    ],
)
def test_pending_branch(entry, expected):
    assert pending_branch(entry) == expected
