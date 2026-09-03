"""Every installer subprocess declares its timeout through a named constant.

Issue: Waltham-Data-Science/NDI-python#165

ndi_install.py capped its editable install at 120 seconds. The install takes
about 80 on a healthy GitHub runner, and `pip install -e .` has to resolve six
git-URL dependencies from pyproject.toml, so a slow clone crossed the line
often enough to fail CI at random. The failure was especially unhelpful: it
happened during install, so no test ran and the job merely looked red.

The guard here is on the SHAPE of the fix, not on a particular number. Raising
NETWORK_TIMEOUT further never fails these tests; writing a bare `timeout=120`
into a network-bound step does. That is the mistake worth preventing, because
120 looks generous right up until you remember the six clones behind it.

Two literals are allowed, each for a stated reason, and adding a third means
deciding here whether it deserves one.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parent.parent / "ndi_install.py"

#: The floor a network-bound timeout has to clear. Deliberately below the
#: current NETWORK_TIMEOUT so raising it never fails this; 120 is what broke.
MINIMUM_NETWORK_TIMEOUT = 300

#: Literal timeouts that are allowed to stay literal, and why. A subprocess
#: not covered by one of these has to use NETWORK_TIMEOUT or LOCAL_TIMEOUT,
#: which is what makes "is this network-bound?" a question the author answers
#: rather than skips.
ALLOWED_LITERALS = {
    10: "git --version: a version string, on no network",
    1800: "the Pyraview build: COMPILES a C++ library, so its cost is the "
    "machine's rather than the network's",
}


@pytest.fixture(scope="module")
def source():
    return INSTALLER.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def tree(source):
    return ast.parse(source)


@pytest.fixture(scope="module")
def constants(tree):
    """The module-level integer constants, by name."""
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name) and isinstance(node.value.value, int):
                    found[target.id] = node.value.value
    return found


def _subprocess_timeouts(tree) -> list[tuple[int, ast.expr]]:
    """``(line, timeout expression)`` for every subprocess.run in the module."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if not (
            isinstance(target, ast.Attribute)
            and target.attr == "run"
            and isinstance(target.value, ast.Name)
            and target.value.id == "subprocess"
        ):
            continue
        for keyword in node.keywords:
            if keyword.arg == "timeout":
                found.append((node.lineno, keyword.value))
    return found


class TestTheConstants:
    def test_the_network_timeout_is_generous(self, constants):
        assert constants["NETWORK_TIMEOUT"] >= MINIMUM_NETWORK_TIMEOUT

    def test_the_local_timeout_stays_tight(self, constants):
        """A purely local git command taking this long is stuck, not slow."""
        assert constants["LOCAL_TIMEOUT"] <= 60


class TestEverySubprocess:
    def test_each_one_names_its_timeout_or_is_an_allowed_literal(self, tree, constants):
        unexplained = []
        for line, node in _subprocess_timeouts(tree):
            if isinstance(node, ast.Name):
                assert node.id in constants, f"line {line}: unknown constant {node.id}"
                continue
            if isinstance(node, ast.Constant) and node.value in ALLOWED_LITERALS:
                continue
            unexplained.append((line, ast.dump(node)))

        assert not unexplained, (
            "these subprocess.run calls carry a bare timeout: "
            f"{unexplained}. Use NETWORK_TIMEOUT when the command talks to the "
            "network (a clone, a pull, any pip install) or LOCAL_TIMEOUT when "
            "it does not -- or add it to ALLOWED_LITERALS here with a reason. "
            "See #165: a bare 120 on the editable install failed CI at random."
        )

    def test_there_is_something_to_check(self, tree):
        """Guards the guard: a refactor that moved every subprocess call out
        of this file would otherwise make the test above vacuously pass."""
        assert len(_subprocess_timeouts(tree)) >= 8


class TestTheCallThatBroke:
    def test_the_editable_install_uses_the_network_timeout(self, source, tree):
        """Named specifically, so a refactor that moves this call cannot
        quietly drop the one step that was actually failing."""
        function = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "install_ndi_and_deps"
        )
        segment = ast.get_source_segment(source, function)
        assert '"-e"' in segment
        assert "timeout=NETWORK_TIMEOUT" in segment

    def test_the_clone_and_pull_use_it_too(self, source, tree):
        """The two siblings flagged in #165: same runners, same budget."""
        functions = {
            node.name: ast.get_source_segment(source, node)
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
        }
        assert "timeout=NETWORK_TIMEOUT" in functions["git_clone"]
        assert "timeout=NETWORK_TIMEOUT" in functions["git_update"]
        # and git_update's LOCAL stash calls are not swept up with them
        assert "timeout=LOCAL_TIMEOUT" in functions["git_update"]
