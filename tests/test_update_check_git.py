"""ndi.update.check and ndi.update.install on git clones.

MATLAB counterpart: tests/+ndi/+unittest/+update/TestCheckGitClone.m

Hermetic: each test builds bare repositories that stand in for GitHub, plus
an NDI-python clone and an ``~/.ndi/tools`` dependency clone of them, in a
temp folder, and points check/install at them with RepoRoot and NdiHome. No
network. The fake NDI-python has no ndi_install.py, so install can never
run the real installer.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from ndi.update import UpdateError, check, install, modificationSummary

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs the git program")

IDENTITY = [
    "-c",
    "user.name=ndiTest",
    "-c",
    "user.email=ndi@example.com",
    "-c",
    "commit.gpgsign=false",
]


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *IDENTITY, "-C", str(repo), *args], capture_output=True, text=True
    )
    assert done.returncode == 0, f"git {' '.join(args)} failed: {done.stdout}{done.stderr}"
    return done.stdout


def commit_all(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


class Clones:
    """Upstream seeds, bare 'GitHub' remotes, and the installed clones."""

    def __init__(self, root: Path):
        self.root = root
        self.seeds = root / "seed"
        self.home = root / "home" / ".ndi"
        self.ndi = root / "work" / "NDI-python"
        remotes = root / "remotes"
        installed = {
            "NDI-python": self.ndi,
            "vhlab-toolbox-python": self.home / "tools" / "vhlab-toolbox-python",
        }
        for name, target in installed.items():
            seed = self.seeds / name
            seed.mkdir(parents=True)
            git(seed, "init", "-q", "-b", "main")
            (seed / "README.md").write_text("hello")
            commit_all(seed, "initial")
            bare = remotes / f"{name}.git"
            git(root, "clone", "-q", "--bare", str(seed), str(bare))
            git(seed, "remote", "add", "origin", str(bare))
            target.parent.mkdir(parents=True, exist_ok=True)
            git(root, "clone", "-q", str(bare), str(target))
        self.dep = installed["vhlab-toolbox-python"]

    def push_upstream(self, name: str, file: str = "README.md", text: str = "more") -> None:
        seed = self.seeds / name
        path = seed / file
        path.write_text(path.read_text() + "\n" + text if path.exists() else text)
        commit_all(seed, "upstream change")
        git(seed, "push", "-q", "origin", "main")


@pytest.fixture
def clones(tmp_path: Path) -> Clones:
    return Clones(tmp_path)


def run_check(clones: Clones, **kw) -> dict:
    return check(RepoRoot=str(clones.ndi), NdiHome=str(clones.home), Verbose=False, **kw)


def run_install(clones: Clones, **kw) -> dict:
    return install(RepoRoot=str(clones.ndi), NdiHome=str(clones.home), Confirm=False, **kw)


def test_up_to_date(clones):
    r = run_check(clones)
    assert r["InstallType"] == "git"
    assert r["Status"] == "upToDate"
    assert r["UpdateAvailable"] is False
    assert r["CommitsBehind"] == 0
    assert r["Branch"] == "main"
    assert r["HasModifications"] is False
    assert r["CurrentVersion"] == r["LatestVersion"]
    assert [(d["Name"], d["Status"]) for d in r["Dependencies"]] == [
        ("vhlab-toolbox-python", "upToDate")
    ]


def test_behind_main(clones):
    clones.push_upstream("NDI-python")
    r = run_check(clones)
    assert r["Status"] == "updateAvailable"
    assert r["UpdateAvailable"] is True
    assert r["CommitsBehind"] == 1
    assert r["CurrentVersion"] != r["LatestVersion"]
    assert "1 commit(s)" in r["Message"]
    assert "ndi.update.install()" in r["Message"]


def test_dependency_behind(clones):
    clones.push_upstream("vhlab-toolbox-python")
    r = run_check(clones)
    assert r["CommitsBehind"] == 0
    assert r["Status"] == "updateAvailable"
    assert r["Dependencies"][0]["Status"] == "behind"
    assert r["Dependencies"][0]["CommitsBehind"] == 1
    assert "vhlab-toolbox-python" in r["Message"]


def test_dependencies_can_be_skipped(clones):
    clones.push_upstream("vhlab-toolbox-python")
    r = run_check(clones, IncludeDependencies=False)
    assert r["Dependencies"] == []
    assert r["Status"] == "upToDate"


def test_local_commits_are_ahead(clones):
    (clones.ndi / "local.py").write_text("x = 1\n")
    commit_all(clones.ndi, "local work")
    r = run_check(clones)
    assert r["Status"] == "ahead"
    assert r["UpdateAvailable"] is False
    assert r["CommitsAhead"] == 1
    assert r["HasModifications"] is True
    assert r["Modifications"][0]["CommitsAhead"] == 1


def test_modifications_are_listed(clones):
    clones.push_upstream("NDI-python")
    (clones.ndi / "README.md").write_text("my edit")
    (clones.ndi / "mine.py").write_text("y = 2\n")
    (clones.dep / "extra.py").write_text("z = 3\n")
    commit_all(clones.dep, "local dependency commit")

    r = run_check(clones)
    assert r["HasModifications"] is True
    by_name = {m["Name"]: m for m in r["Modifications"]}
    assert set(by_name) == {"NDI-python", "vhlab-toolbox-python"}
    assert by_name["NDI-python"]["ChangedFiles"] == ["README.md"]
    assert by_name["NDI-python"]["NewFiles"] == ["mine.py"]
    assert by_name["NDI-python"]["CommitsAhead"] == 0
    assert by_name["vhlab-toolbox-python"]["CommitsAhead"] == 1
    assert "changed code in" in r["Message"]

    txt = modificationSummary(r)
    assert "changed: README.md" in txt
    assert "new:     mine.py" in txt
    assert "1 local commit(s)" in txt


def test_install_with_no_update_does_nothing(clones):
    r = run_install(clones)
    assert r["UpdateAvailable"] is False


def test_install_refuses_modified_code(clones):
    clones.push_upstream("NDI-python")
    (clones.ndi / "README.md").write_text("my edit")
    with pytest.raises(UpdateError) as err:
        run_install(clones)
    assert err.value.identifier == "ndi:update:install:localModifications"
    assert (clones.ndi / "README.md").read_text() == "my edit"


def test_install_allow_modified_goes_on(clones):
    # Past the modification guard, the next step needs ndi_install.py,
    # which the fake clone lacks.
    clones.push_upstream("NDI-python")
    (clones.ndi / "mine.py").write_text("y = 2\n")
    with pytest.raises(UpdateError) as err:
        run_install(clones, AllowModified=True)
    assert err.value.identifier == "ndi:update:install:noInstaller"


def test_install_refuses_other_branch(clones):
    clones.push_upstream("NDI-python")
    git(clones.ndi, "checkout", "-q", "-b", "myFeature")
    r = run_check(clones)
    assert r["Branch"] == "myFeature"
    assert "git checkout main" in r["Message"]
    with pytest.raises(UpdateError) as err:
        run_install(clones)
    assert err.value.identifier == "ndi:update:install:notOnMain"


def test_confirm_defaults_to_no_when_code_is_modified(clones):
    clones.push_upstream("NDI-python")
    (clones.ndi / "README.md").write_text("my edit")
    asked = []
    install(
        RepoRoot=str(clones.ndi),
        NdiHome=str(clones.home),
        Ask=lambda prompt: asked.append(prompt) or "",
    )
    assert asked == ["Update anyway? Y/N [N]: "]
    assert (clones.ndi / "README.md").read_text() == "my edit"


def test_install_pulls_and_runs_ndi_install(clones):
    # A stand-in ndi_install.py records that it ran with --update.
    marker = clones.root / "ran.txt"
    seed = clones.seeds / "NDI-python"
    (seed / "ndi_install.py").write_text(
        "import pathlib, sys\n"
        f"pathlib.Path({str(marker)!r}).write_text(' '.join(sys.argv[1:]))\n"
    )
    commit_all(seed, "add installer")
    git(seed, "push", "-q", "origin", "main")
    git(clones.ndi, "pull", "-q", "--ff-only")
    clones.push_upstream("NDI-python", text="the update")

    r = run_install(clones)
    assert r["CommitsBehind"] == 1
    assert "the update" in (clones.ndi / "README.md").read_text()  # pulled
    assert marker.read_text() == "--update"
    assert run_check(clones)["Status"] == "upToDate"


def test_changed_files_survive_an_update(clones):
    # A tracked file the user edited is stashed for the pull and put back.
    seed = clones.seeds / "NDI-python"
    (seed / "ndi_install.py").write_text("print('stand-in installer')\n")
    (seed / "notes.txt").write_text("original\n")
    commit_all(seed, "add files")
    git(seed, "push", "-q", "origin", "main")
    git(clones.ndi, "pull", "-q", "--ff-only")
    clones.push_upstream("NDI-python", text="the update")
    (clones.ndi / "notes.txt").write_text("my notes\n")

    run_install(clones, AllowModified=True)
    assert (clones.ndi / "notes.txt").read_text() == "my notes\n"
    assert "the update" in (clones.ndi / "README.md").read_text()
