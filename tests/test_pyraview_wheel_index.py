"""Pyraview installs from its pre-built release wheels, and never compiles.

Pyraview is not on PyPI. The `pyraview` extra in pyproject.toml pins it by
name, and two committed files in install/ say where its wheels are and what
they hash to:

* ``pyraview-wheels.html`` -- the ``--find-links`` flat index, one link per
  release wheel with a ``#sha256=`` fragment, and no sdist (building one needs
  CMake and a C++ compiler);
* ``pyraview-constraints.txt`` -- the same hashes as a constraints file, which
  is how uv is made to verify them.

These tests hold the pieces to each other offline. CI proves the rest with a
network: the install-pyraview-wheels matrix in ci.yml installs from them on
every platform, and regenerates them from the GitHub API to show the committed
hashes are GitHub's own digests.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX = REPO_ROOT / "install" / "pyraview-wheels.html"
CONSTRAINTS = REPO_ROOT / "install" / "pyraview-constraints.txt"
PYPROJECT = REPO_ROOT / "pyproject.toml"

_LINK = re.compile(r'<a href="([^"#]+)#sha256=([0-9a-f]{64})">([^<]+)</a>')


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def links() -> list[tuple[str, str, str]]:
    """(url, sha256, filename) for every link in the committed index."""
    found = _LINK.findall(INDEX.read_text(encoding="utf-8"))
    assert found, f"no hashed links in {INDEX}"
    return found


@pytest.fixture(scope="module")
def pinned_version() -> str:
    match = re.search(r'^pyraview = \[\s*"pyraview==([^"]+)",\s*\]', PYPROJECT.read_text(), re.M)
    assert match, 'pyproject.toml has no `pyraview = ["pyraview==..."]` extra'
    return match.group(1)


class TestTheIndex:
    def test_every_link_is_a_wheel_of_the_pinned_version(self, links, pinned_version):
        for url, _, name in links:
            assert name.endswith(".whl"), f"{name}: only wheels belong in the index"
            assert name.startswith(f"pyraview-{pinned_version}-"), name
            assert url.endswith("/" + name), (url, name)
            assert url.startswith(
                f"https://github.com/VH-Lab/Pyraview/releases/download/v{pinned_version}/"
            ), url

    def test_every_link_carries_a_hash(self):
        """A link without a fragment would slip past the regex above."""
        text = INDEX.read_text(encoding="utf-8")
        assert text.count("<a ") == len(_LINK.findall(text))

    def test_the_sdist_is_not_listed(self):
        """An sdist in the index is the one way an install could compile."""
        text = INDEX.read_text(encoding="utf-8")
        assert ".tar.gz" not in text
        assert ".zip" not in text

    @pytest.mark.parametrize(
        "platform_tag",
        [
            "manylinux_2_28_x86_64",
            "manylinux_2_28_aarch64",
            "macosx_10_13_x86_64",
            "macosx_11_0_arm64",
            "win_amd64",
        ],
    )
    def test_the_installer_python_has_a_wheel_on_every_platform(self, links, platform_tag):
        """The double-click installer bundles CPython 3.12."""
        names = [name for _, _, name in links]
        assert any("-cp312-cp312-" in n and platform_tag in n for n in names), platform_tag

    def test_every_supported_python_has_a_wheel_on_every_platform(self, links):
        """requires-python is >=3.10; ndi_install.py runs on whatever it is."""
        names = [name for _, _, name in links]
        for minor in (10, 11, 12, 13, 14):
            tag = f"-cp3{minor}-cp3{minor}-"
            for plat in ("manylinux_2_28_x86_64", "macosx_11_0_arm64", "win_amd64"):
                assert any(tag in n and plat in n for n in names), (tag, plat)
            assert any(tag in n and "macosx_" in n and "x86_64" in n for n in names), tag


class TestTheConstraints:
    def test_same_hashes_as_the_index(self, links):
        text = CONSTRAINTS.read_text(encoding="utf-8")
        assert set(re.findall(r"--hash=sha256:([0-9a-f]{64})", text)) == {h for _, h, _ in links}

    def test_pins_the_same_version(self, pinned_version):
        assert f"pyraview=={pinned_version} \\" in CONSTRAINTS.read_text(encoding="utf-8")


class TestTheGenerator:
    def test_it_reproduces_the_committed_files(self, links):
        """Both files are generated; a hand edit shows up as a mismatch."""
        gen = _load("make_pyraview_index", REPO_ROOT / "tools" / "make_pyraview_index.py")
        tag = links[0][0].split("/")[-2]
        release = {
            "tag_name": tag,
            "assets": [
                {"name": name, "digest": f"sha256:{sha}", "browser_download_url": url}
                for url, sha, name in links
            ]
            # The real release also carries these; the generator must drop them.
            + [
                {
                    "name": f"pyraview-{tag[1:]}.tar.gz",
                    "digest": "sha256:" + "0" * 64,
                    "browser_download_url": "https://example.invalid/sdist",
                },
                {
                    "name": "Pyraview.mltbx",
                    "digest": "sha256:" + "1" * 64,
                    "browser_download_url": "https://example.invalid/mltbx",
                },
            ],
        }
        wheel_list = gen.wheels(release)
        assert gen.render_index(tag, wheel_list) == INDEX.read_text(encoding="utf-8")
        assert gen.render_constraints(tag, wheel_list) == CONSTRAINTS.read_text(encoding="utf-8")


class TestPyproject:
    def test_pyraview_is_not_in_the_gui_extra(self):
        """`pip install ".[gui]"` must not need a --find-links flag."""
        match = re.search(r"^gui = \[(.*?)\]", PYPROJECT.read_text(), re.M | re.S)
        assert match and "pyraview" not in match.group(1)

    def test_it_is_named_not_a_url(self):
        text = PYPROJECT.read_text()
        assert "pyraview @" not in text.lower()
        assert "Pyraview.git" not in text


class TestNdiInstall:
    @pytest.fixture
    def installer(self):
        return _load("ndi_install_pyraview_under_test", REPO_ROOT / "ndi_install.py")

    def test_pyraview_is_no_longer_cloned(self, installer):
        assert all(dep["name"].lower() != "pyraview" for dep in installer.DEPENDENCIES)

    @pytest.mark.parametrize("include_dev", [False, True])
    def test_the_editable_install_takes_pyraview_from_the_wheel_index(
        self, installer, monkeypatch, include_dev
    ):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(installer.subprocess, "run", fake_run)
        assert installer.install_ndi_and_deps(REPO_ROOT, include_dev=include_dev)

        editable = next(c for c in calls if "-e" in c)
        assert editable[:4] == [sys.executable, "-m", "pip", "install"]
        target = editable[editable.index("-e") + 1]
        assert "pyraview" in target.split("[")[1].rstrip("]").split(",")
        index = Path(editable[editable.index("--find-links") + 1])
        assert index == INDEX and index.is_file()
        assert editable[editable.index("--only-binary") + 1] == "pyraview"
