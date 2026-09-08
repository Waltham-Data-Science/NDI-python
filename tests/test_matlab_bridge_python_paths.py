"""``python_path`` names a file this repo actually has.

MATLAB counterpart: none -- like ``status``, this checks a convention of the
bridge files themselves, so it needs no NDI-matlab checkout and runs in every
job.

THE FAILURE THIS CATCHES. ``matlab_path`` has been guarded since
:meth:`TestTheBridgeFilesAreComplete.
test_every_recorded_matlab_path_points_at_a_real_file` -- an entry naming a
MATLAB file that no longer exists "looks maintained while describing a file
that does not exist", and that check found three. The mirror image was never
guarded at all, and it is the more consequential half: ``matlab_path`` says
what is being mirrored, ``python_path`` says *where the mirror is*, and it is
the field a reader follows to check a port.

Nine entries pointed at nothing. All nine were in ``+ndi/+gui/``, and all
nine had a real port sitting beside the recorded path under its plain name --
``ndi/gui/docViewer.py`` recorded as
``ndi/gui/ndi_gui_docViewer.py``,
``ndi/gui/component/internal/ProgressTracker.py`` recorded as
``ndi/gui/component/internal/ndi_gui_component_internal_ProgressTracker.py``,
and so on. A mechanical class-rename pass had run over the FILE PATHS as
well as the class names, and nothing read them afterwards.

WHY IT MATTERED, beyond being untidy. An entry whose ``python_path`` names no
file claims a port nobody can find, and no check could contradict it -- the
same silent false assurance as an entry with no ``matlab_last_sync_hash``
(NDI-python#211). It also quietly weakens the hash-justification rule, which
exempts a hash change when one of the entry's ``python_path`` files is in the
diff: a path that names no file can never be in any diff.

NOT CHECKED HERE: whether the file's CONTENT corresponds to the MATLAB. No
test can settle that, which is exactly why the bridge records a commit and a
decision_log instead. This checks only that the path resolves -- the cheap
half, which was missing.
"""

from __future__ import annotations

from typing import Any

import yaml

from tests.test_matlab_bridge_completeness import REPO_ROOT
from tests.test_matlab_bridge_hashes import bridge_files, display_path

#: Where a ``python_path`` is rooted. The values are written relative to
#: ``src/``, e.g. ``ndi/gui/docViewer.py``.
PYTHON_ROOT = REPO_ROOT / "src"


def python_paths(entry: dict[str, Any]) -> list[str]:
    """The entry's ``python_path`` values, as a list.

    Both spellings are in use -- a single string, and a list of them for an
    entry whose MATLAB counterpart is split across modules.
    """
    value = entry.get("python_path")
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def entries_with_a_python_path(node: Any) -> list[dict[str, Any]]:
    """Every mapping carrying a ``python_path``, at any depth.

    Recursive for the same reason as the other guards: bridge entries live
    at several depths and a nested one counts.
    """
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if python_paths(node):
            found.append(node)
        for value in node.values():
            found.extend(entries_with_a_python_path(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(entries_with_a_python_path(item))
    return found


def names_a_module(path: str) -> bool:
    """Is this value a path to a Python file, rather than prose?

    A handful of entries use the field to say something a path cannot, such
    as ``"n/a"`` or a bare module name. Only ``.py`` paths are checked, so
    those are left to the ``status``/``decision_log`` guards rather than
    being reported as missing files.
    """
    return path.strip().endswith(".py")


def offenders() -> list[str]:
    found: list[str] = []
    for source in bridge_files():
        data = yaml.safe_load(source.read_text(encoding="utf-8"))
        for entry in entries_with_a_python_path(data):
            for path in python_paths(entry):
                if not names_a_module(path):
                    continue
                if not (PYTHON_ROOT / path.strip()).is_file():
                    name = entry.get("name", "<unnamed>")
                    found.append(f"{display_path(source)}: {name} -- src/{path.strip()}")
    return found


class TestEveryPythonPathResolves:
    def test_no_entry_points_at_a_missing_module(self):
        assert not offenders(), (
            "these bridge entries record a python_path that does not exist:\n  "
            + "\n  ".join(offenders())
            + "\n\nAn entry whose python_path names no file claims a port nobody can "
            "follow, and nothing else in the suite can contradict it. Point it at "
            "the real module, or -- if there is genuinely no Python side -- drop "
            "the field and give the entry a status and a decision_log saying so."
        )


class TestTheGuardWouldActuallyCatchOne:
    """A path check that has never been seen to fail is indistinguishable
    from one that resolves everything it is given."""

    def test_a_missing_module_is_reported(self, tmp_path):
        source = tmp_path / "ndi_matlab_python_bridge.yaml"
        source.write_text(
            "functions:\n"
            "  - name: notReal\n"
            '    matlab_path: "+ndi/+gui/docViewer.m"\n'
            '    python_path: "ndi/gui/no_such_module.py"\n',
            encoding="utf-8",
        )
        data = yaml.safe_load(source.read_text(encoding="utf-8"))
        entries = entries_with_a_python_path(data)
        assert len(entries) == 1
        assert not (PYTHON_ROOT / python_paths(entries[0])[0]).is_file()

    def test_a_real_module_passes(self):
        assert (PYTHON_ROOT / "ndi/gui/docViewer.py").is_file()

    def test_a_nested_entry_is_found(self):
        data = {"a": {"b": [{"name": "x", "python_path": "ndi/gui/docViewer.py"}]}}
        assert [e["name"] for e in entries_with_a_python_path(data)] == ["x"]

    def test_a_list_valued_python_path_is_expanded(self):
        entry = {"name": "x", "python_path": ["ndi/gui/gui.py", "ndi/gui/lab.py"]}
        assert python_paths(entry) == ["ndi/gui/gui.py", "ndi/gui/lab.py"]

    def test_prose_is_not_treated_as_a_path(self):
        assert not names_a_module("n/a (Python only)")
        assert names_a_module("ndi/gui/docViewer.py")


def test_the_check_actually_looked_at_something():
    """A guard that collected nothing passes for the wrong reason."""
    seen = 0
    for source in bridge_files():
        data = yaml.safe_load(source.read_text(encoding="utf-8"))
        for entry in entries_with_a_python_path(data):
            seen += sum(1 for p in python_paths(entry) if names_a_module(p))
    assert seen > 400, f"only {seen} python_path values collected; expected the full bridge"
