"""A MATLAB class's PUBLIC properties must be public on the Python port.

MATLAB counterpart: every ``classdef`` with a ``properties`` block that a
``ndi_matlab_python_bridge.yaml`` entry names a ``python_class`` for.

WHY THIS GATE EXISTS, and why it is not just tidiness. A MATLAB property
declared ``GetAccess=public`` is part of the class's contract: callers read
``obj.name`` without asking what class ``obj`` is. When the Python port keeps
the same value as ``_name`` only, that contract is silently broken -- and the
word to hold on to is SILENTLY. These gaps do not raise ``AttributeError``.
The caller that matters writes::

    path = getattr(session, "path", None)
    if path is None:
        return None

so a missing public name is indistinguishable from a value that is genuinely
absent, and the program takes the wrong branch and fails somewhere else.

That is not hypothetical. ``ndi.dataset.dir`` has declared a public ``path``
since it was written; ``ndi_dataset_dir`` kept it as ``_path``. The gene
pyramid viewer's tile fetcher reopens whatever it is handed at its own path,
using exactly the ``getattr`` above. ``ndi_session_dir`` answered it and could
be reopened; ``ndi_dataset_dir`` returned ``None``, so the fetcher had no
handle to build and could only explain itself and stop::

    RuntimeError: Cannot fetch 'tile.bin_262' from thread
    ThreadPoolExecutor-1_0: this session cannot be reopened for another
    thread, and NDI's database may only be used from the thread that
    opened it.

A threading error, three layers from a missing property. See NDI-python#295.

WHAT "PUBLIC" MEANS HERE. MATLAB's default is public, but a block may narrow
it, and the narrowing is the whole point of reading the attributes rather than
the names::

    properties (GetAccess=public, SetAccess=protected)   % public: checked
    properties (Access = protected)                      % NOT public: skipped
    properties (SetAccess = private)                     % public to read: checked
    properties (Constant)                                % public: checked

A grep that prints property names without their block's attributes over-reports
badly: it reads ``ndi.dataset``'s ``session``, ``session_info`` and
``session_array`` as public when all three sit under ``Access = protected``,
and demanding a port expose another class's protected state is how a gate
teaches people to ignore it. ``Hidden`` properties are skipped for the same
reason -- MATLAB keeps them out of ``properties()``, display and tab
completion, so they are not the public contract either.

WHAT COUNTS AS EXPOSED ON THE PYTHON SIDE. The check is static -- it parses
with ``ast`` and imports nothing. That is not only caution about import side
effects: the CI job that checks the bridge installs ``pytest`` and ``pyyaml``
and nothing else, so an importing check could not run there at all, which is
the same reason :mod:`tests.test_matlab_bridge_python_paths` resolves paths on
disk rather than by import. A name counts as exposed when the class or any of
its base classes declares it as a method (``@property`` included), a class
attribute, an annotated field, or an ``self.name = ...`` assignment anywhere in
the class body. Bases are resolved by name across ``src/``, so
``ndi_dataset_dir`` inherits what ``ndi_dataset`` exposes, exactly as MATLAB's
``dir < ndi.dataset`` does.

A STALE ``python_class`` IS A FAILURE, NOT A SKIP. An entry naming a class that
does not exist can never be checked, so skipping it would report "no gaps" for
a class nobody looked at -- the same false assurance an entry with no
``matlab_last_sync_hash`` gives the drift gate. One such entry was already
there: ``+ndi/preferences.m`` recorded ``python_class: "Preferences"`` while
the class is ``ndi_preferences``, and nothing had noticed.

THE ALLOWLIST is ``tests/bridge_property_allowlist.yaml``, in the shape and
spirit of ``tests/bridge_drift_allowlist.yaml``: every line is an IOU with a
reason, the gate is ON for everything not listed, and
:class:`TestThePropertyAllowlistOnlyShrinks` fails if a listed gap has been
closed, so the file can only shrink. It is a separate file rather than a
section of the drift list because the two gates burn down independently and
the drift list's prose is about drift; the mechanism -- a keyed YAML burn-down
that a reviewer must edit deliberately -- is deliberately the same.

WHERE THE MATLAB TREE COMES FROM. Same rule as the guards it sits beside:
absent, the check skips -- unless ``NDI_BRIDGE_CHECK_STRICT`` is set, which CI
does after checking the repo out, so a workflow that stops providing the tree
fails instead of quietly passing (issue #77).
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from tests.test_matlab_bridge_completeness import (
    REPO_ROOT,
    normalize_matlab_path,
    require_matlab_root,
)
from tests.test_matlab_bridge_hashes import (
    MATLAB_PATH_PREFIX,
    bridge_files,
    display_path,
)

ALLOWLIST = REPO_ROOT / "tests" / "bridge_property_allowlist.yaml"

# ---------------------------------------------------------------------------
# Reading MATLAB
# ---------------------------------------------------------------------------

#: A ``properties`` line, with its optional attribute list. The attributes are
#: captured rather than discarded because they decide whether the block is
#: public at all -- see the module docstring.
_PROPERTIES_BLOCK = re.compile(r"^\s*properties\b(?P<attrs>\s*\(.*\))?\s*(%.*)?$", re.I)

#: MATLAB keywords that open a block of their own and so must be balanced
#: against ``end`` while scanning. A property's validator or default value can
#: contain none of these at statement start, but ``methods``/``enumeration``
#: after a malformed block would otherwise swallow the closing ``end``.
_BLOCK_OPENERS = (
    "if",
    "for",
    "while",
    "switch",
    "try",
    "parfor",
    "function",
    "arguments",
    "spmd",
    "classdef",
    "methods",
    "properties",
    "enumeration",
    "events",
)


@dataclass(frozen=True)
class MatlabProperty:
    """One declared property and the two facts that decide if it is checked."""

    name: str
    public: bool
    hidden: bool

    @property
    def is_contract(self) -> bool:
        """Is this part of the class's public contract?"""
        return self.public and not self.hidden


def _block_visibility(attrs: str) -> tuple[bool, bool]:
    """``(public, hidden)`` for a ``properties`` block's attribute list.

    ``Access`` sets both halves; ``GetAccess`` sets the readable half alone and
    wins for our purposes, since a property a caller can READ is one a
    ``getattr`` can find. Whitespace around ``=`` is stripped first: MATLAB
    writes both ``Access=protected`` and ``Access = protected`` and a splitter
    that does not normalise reads the second as three unrelated tokens and
    falls back to the public default -- silently checking protected state.
    """
    normalized = re.sub(r"\s*=\s*", "=", attrs.strip()).strip("()").lower()
    public, hidden = True, False
    for part in re.split(r"[,\s]+", normalized):
        if not part:
            continue
        if "=" in part:
            key, value = part.split("=", 1)
            if key in ("access", "getaccess"):
                public = value == "public"
            elif key == "hidden":
                hidden = value == "true"
        elif part == "hidden":
            hidden = True
    return public, hidden


def matlab_properties(source: str) -> list[MatlabProperty]:
    """Every property declared by a MATLAB class, with its visibility.

    A hand-rolled scan rather than a MATLAB parser, because the grammar that
    matters here is small: a ``properties`` line, one declaration per line
    until the matching ``end``, and line continuations. Declarations may carry
    a size, a class, a validator block and a default
    (``TempFolder {mustBeWritable} = fullfile(tempdir, 'nditemp')``), so only
    the leading identifier is taken -- and a continued line is skipped
    entirely, or the second half of ``DocumentFolder {...} = ...\\n
    fullfile(...)`` would be read as a property named ``fullfile``.
    """
    found: list[MatlabProperty] = []
    lines = source.splitlines()
    index = 0
    while index < len(lines):
        header = _PROPERTIES_BLOCK.match(lines[index])
        if not header:
            index += 1
            continue
        public, hidden = _block_visibility(header.group("attrs") or "")
        index += 1
        depth = 0
        continued = False
        while index < len(lines):
            stripped = lines[index].strip()
            code = "" if stripped.startswith("%") else re.sub(r"%.*$", "", stripped).strip()
            if not continued:
                if re.match(r"^end\b", code):
                    if depth == 0:
                        index += 1
                        break
                    depth -= 1
                elif any(re.match(rf"^{word}\b", code) for word in _BLOCK_OPENERS):
                    depth += 1
                elif code and depth == 0:
                    name = re.split(r"[\s(={;,]", code, maxsplit=1)[0]
                    if re.fullmatch(r"[A-Za-z]\w*", name or ""):
                        found.append(MatlabProperty(name, public, hidden))
            continued = code.endswith("...")
            index += 1
    return found


# ---------------------------------------------------------------------------
# Reading Python
# ---------------------------------------------------------------------------


def python_class_index(root: Path) -> dict[str, list[ast.ClassDef]]:
    """Every ``class`` statement under *root*, keyed by name.

    A list per name because a name may legitimately appear more than once
    across the tree; the union of what they expose is used, which can only
    make the check more permissive and never invent a failure.
    """
    index: dict[str, list[ast.ClassDef]] = {}
    for source in sorted(root.glob("**/*.py")):
        try:
            tree = ast.parse(source.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:  # pragma: no cover -- src/ parses or CI is already red
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                index.setdefault(node.name, []).append(node)
    return index


def _declared_names(node: ast.ClassDef) -> set[str]:
    """Names one class body makes reachable on an instance.

    Methods and ``@property`` (both are ``FunctionDef``), class attributes,
    annotated fields including dataclass fields, and every ``self.x = ...``
    anywhere inside the body -- the last because most of this port sets its
    attributes in ``__init__``, where no class-level declaration exists to
    find.
    """
    names: set[str] = set()
    for statement in node.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(statement.name)
        elif isinstance(statement, ast.Assign):
            names |= {t.id for t in statement.targets if isinstance(t, ast.Name)}
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            names.add(statement.target.id)
    for inner in ast.walk(node):
        if isinstance(inner, ast.Assign):
            targets: list[ast.expr] = list(inner.targets)
        elif isinstance(inner, (ast.AnnAssign, ast.AugAssign)):
            targets = [inner.target]
        else:
            continue
        for target in targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
            ):
                names.add(target.attr)
    return names


def _base_name(base: ast.expr) -> str | None:
    """The bare name of a base class, ``a.b.C`` included."""
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr
    return None


def public_names(
    class_name: str,
    index: dict[str, list[ast.ClassDef]],
    seen: frozenset[str] = frozenset(),
) -> set[str]:
    """Everything *class_name* exposes, its base classes included.

    Inheritance is followed because MATLAB inherits too: ``ndi.dataset.dir``
    reads ``session`` from ``ndi.dataset``, and a check that looked only at
    the subclass would demand the subclass redeclare it. Bases are matched by
    bare name across the tree, which is unambiguous here -- ``src/`` declares
    175 classes and shares a name only once, on a class no bridge entry
    points at. ``seen`` breaks cycles.
    """
    if class_name in seen or class_name not in index:
        return set()
    seen = seen | {class_name}
    names: set[str] = set()
    for node in index[class_name]:
        names |= _declared_names(node)
        for base in node.bases:
            name = _base_name(base)
            if name:
                names |= public_names(name, index, seen)
    return names


# ---------------------------------------------------------------------------
# Reading the bridge
# ---------------------------------------------------------------------------


def entries_with_a_python_class(node: Any) -> list[dict[str, Any]]:
    """Every mapping naming both a ``matlab_path`` and a ``python_class``.

    Recursive, like every other bridge walk here: entries live at several
    depths and a nested one counts.
    """
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if isinstance(node.get("matlab_path"), str) and isinstance(node.get("python_class"), str):
            found.append(node)
        for value in node.values():
            found.extend(entries_with_a_python_class(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(entries_with_a_python_class(item))
    return found


def matlab_class_file(entry: dict[str, Any]) -> str:
    """The entry's MATLAB path when it names a real ``.m`` file, else ``""``."""
    path = normalize_matlab_path(entry.get("matlab_path") or "")
    if not path.startswith(MATLAB_PATH_PREFIX) or not path.endswith(".m"):
        return ""
    return path


def allowlisted() -> set[tuple[str, str]]:
    """Recorded divergences, as ``(python_class, property name)`` keys.

    Keyed on the Python class rather than the MATLAB path because that is what
    a reader chasing a missing attribute has in hand, and because two bridge
    entries may name the same MATLAB file.
    """
    data = yaml.safe_load(ALLOWLIST.read_text(encoding="utf-8")) or {}
    return {(e["python_class"], e["property"]) for e in (data.get("not_exposed") or [])}


def gaps(matlab_root: Path) -> tuple[list[str], list[str], int]:
    """``(missing, unresolvable, checked)`` across every bridge entry.

    ``missing`` is a public MATLAB property with no public Python name;
    ``unresolvable`` is an entry whose ``python_class`` names nothing.
    ``checked`` counts the properties actually compared, so a check that
    silently stopped looking can be told from one that found nothing wrong.
    """
    index = python_class_index(REPO_ROOT / "src")
    allowed = allowlisted()
    missing: list[str] = []
    unresolvable: list[str] = []
    checked = 0
    for source in bridge_files():
        data = yaml.safe_load(source.read_text(encoding="utf-8"))
        for entry in entries_with_a_python_class(data):
            path = matlab_class_file(entry)
            if not path:
                continue
            full = matlab_root / path
            if not full.exists():
                # A stale matlab_path is the completeness guard's business, and
                # failing here too would report one mistake as two.
                continue
            contract = [
                p.name
                for p in matlab_properties(full.read_text(encoding="utf-8", errors="replace"))
                if p.is_contract
            ]
            if not contract:
                continue
            python_class = entry["python_class"]
            if python_class not in index:
                unresolvable.append(
                    f"{display_path(source)}: {entry.get('name', '<unnamed>')} "
                    f"({path}) -- python_class {python_class!r} names no class in src/"
                )
                continue
            exposed = public_names(python_class, index)
            for name in contract:
                if (python_class, name) in allowed:
                    continue
                checked += 1
                if name not in exposed:
                    missing.append(f"{python_class}.{name} ({path}, {display_path(source)})")
    return missing, unresolvable, checked


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


class TestPublicMatlabPropertiesArePublicInPython:
    """The gate. NDI-python#295."""

    def test_no_public_matlab_property_is_private_in_python(self):
        matlab_root = require_matlab_root()
        missing, _, checked = gaps(matlab_root)
        assert checked, (
            "no property was compared at all, so this check proved nothing. "
            "Either every bridge entry lost its python_class or the MATLAB "
            "tree is not the one it claims to be."
        )
        assert not missing, (
            "these MATLAB properties are public but their Python counterpart "
            "exposes no such name:\n  "
            + "\n  ".join(sorted(missing))
            + "\n\nAdd a property returning the existing private attribute -- "
            "additive, and it cannot break a caller:\n"
            "    @property\n"
            "    def path(self) -> Path:\n"
            "        return self._path\n"
            "Do NOT rename the private attribute; adding the public name "
            "beside it is enough. If Python diverges on purpose, record it in "
            "tests/bridge_property_allowlist.yaml with a reason, and in the "
            "entry's decision_log in its ndi_matlab_python_bridge.yaml.\n\n"
            "This does not surface as AttributeError. Callers write "
            'getattr(obj, "path", None) and take the None branch, so the '
            "symptom appears somewhere else entirely. See #295."
        )

    def test_every_python_class_resolves(self):
        """An entry naming a class that does not exist can never be checked,
        so it would report a clean bill for a class nobody looked at."""
        matlab_root = require_matlab_root()
        _, unresolvable, _ = gaps(matlab_root)
        assert not unresolvable, (
            "these bridge entries name a python_class that does not exist, so "
            "their properties are never compared against MATLAB:\n  "
            + "\n  ".join(sorted(unresolvable))
            + "\n\nCorrect the python_class to the class actually defined at "
            "the entry's python_path."
        )


class TestThePropertyAllowlistOnlyShrinks:
    """A burn-down list that keeps entries it no longer needs is just a
    permanent exemption with extra steps. Same rule as the drift list.
    """

    def test_the_allowlist_has_no_stale_entries(self):
        matlab_root = require_matlab_root()
        index = python_class_index(REPO_ROOT / "src")
        live: set[tuple[str, str]] = set()
        known_classes: set[str] = set()
        for source in bridge_files():
            data = yaml.safe_load(source.read_text(encoding="utf-8"))
            for entry in entries_with_a_python_class(data):
                path = matlab_class_file(entry)
                if not path:
                    continue
                full = matlab_root / path
                if not full.exists():
                    continue
                python_class = entry["python_class"]
                if python_class not in index:
                    continue
                known_classes.add(python_class)
                exposed = public_names(python_class, index)
                for prop in matlab_properties(full.read_text(encoding="utf-8", errors="replace")):
                    if prop.is_contract and prop.name not in exposed:
                        live.add((python_class, prop.name))
        # A class the bridge no longer reaches is not evidence its listed gaps
        # were closed, so those stay; only a gap on a class still being checked
        # can be shown to be fixed.
        stale = sorted(
            f"{cls}.{name}" for cls, name in allowlisted() - live if cls in known_classes
        )
        assert not stale, (
            "these entries are listed in tests/bridge_property_allowlist.yaml "
            "but the property is now exposed -- delete them from it:\n  "
            + "\n  ".join(stale)
            + "\n\nThe list is a burn-down, not a permanent exemption: an entry "
            "that has been fixed must leave it in the same PR, so the file only "
            "shrinks."
        )

    def test_every_allowlist_entry_carries_a_reason(self):
        """A bare exemption teaches the next reader nothing, which is the hole
        this whole issue was about."""
        data = yaml.safe_load(ALLOWLIST.read_text(encoding="utf-8")) or {}
        offenders = [
            f"{e.get('python_class')}.{e.get('property')}"
            for e in (data.get("not_exposed") or [])
            if not str(e.get("reason") or "").strip()
        ]
        assert not offenders, "these allowlist entries record no reason:\n  " + "\n  ".join(
            offenders
        )


class TestTheGuardWouldActuallyCatchOne:
    """The check passes on a clean tree, which is also what a check that
    inspects nothing does. These exercise the parser and the comparison on
    inputs built by hand.
    """

    def test_a_bare_properties_block_is_public(self):
        props = matlab_properties("classdef c\n properties\n  a\n  b\n end\nend\n")
        assert [p.name for p in props] == ["a", "b"]
        assert all(p.is_contract for p in props)

    def test_a_protected_block_is_not_public(self):
        props = matlab_properties("classdef c\n properties (Access = protected)\n  a\n end\nend\n")
        assert [(p.name, p.is_contract) for p in props] == [("a", False)]

    def test_getaccess_public_with_a_protected_setter_is_public(self):
        source = (
            "classdef c\n properties (GetAccess=public, SetAccess=protected)\n  path\n end\nend\n"
        )
        assert [(p.name, p.is_contract) for p in matlab_properties(source)] == [("path", True)]

    def test_a_private_setter_alone_leaves_reading_public(self):
        props = matlab_properties(
            "classdef c\n properties (SetAccess = private)\n  Items\n end\nend\n"
        )
        assert [(p.name, p.is_contract) for p in props] == [("Items", True)]

    def test_a_hidden_block_is_not_the_contract(self):
        props = matlab_properties("classdef c\n properties (Hidden)\n  a\n end\nend\n")
        assert [(p.name, p.is_contract) for p in props] == [("a", False)]

    def test_a_constant_block_is_public(self):
        props = matlab_properties(
            'classdef c\n properties (Constant)\n  DOIPrefix = "10.1"\n end\nend\n'
        )
        assert [(p.name, p.is_contract) for p in props] == [("DOIPrefix", True)]

    def test_a_continued_line_is_not_a_second_property(self):
        source = (
            "classdef c\n properties (Constant)\n"
            "  DocumentFolder {mustBeText(DocumentFolder)} = ...\n"
            "      fullfile(a, 'b')\n end\nend\n"
        )
        assert [p.name for p in matlab_properties(source)] == ["DocumentFolder"]

    def test_a_comment_line_is_not_a_property(self):
        source = "classdef c\n properties\n  % RootFolder - the root\n  RootFolder\n end\nend\n"
        assert [p.name for p in matlab_properties(source)] == ["RootFolder"]

    def test_a_trailing_comment_does_not_join_the_name(self):
        props = matlab_properties("classdef c\n properties\n  path    % the file path\n end\nend\n")
        assert [p.name for p in props] == ["path"]

    def test_methods_after_the_block_are_not_properties(self):
        source = (
            "classdef c\n properties\n  a\n end\n"
            " methods\n  function y = f(x)\n   y = x;\n  end\n end\nend\n"
        )
        assert [p.name for p in matlab_properties(source)] == ["a"]

    def test_a_property_set_in_init_counts_as_exposed(self, tmp_path):
        (tmp_path / "m.py").write_text("class A:\n    def __init__(self):\n        self.path = 1\n")
        index = python_class_index(tmp_path)
        assert "path" in public_names("A", index)

    def test_a_private_attribute_does_not_count(self, tmp_path):
        (tmp_path / "m.py").write_text(
            "class A:\n    def __init__(self):\n        self._path = 1\n"
        )
        index = python_class_index(tmp_path)
        assert "path" not in public_names("A", index)

    def test_a_property_decorator_counts(self, tmp_path):
        (tmp_path / "m.py").write_text(
            "class A:\n    @property\n    def path(self):\n        return self._path\n"
        )
        index = python_class_index(tmp_path)
        assert "path" in public_names("A", index)

    def test_an_inherited_name_counts(self, tmp_path):
        (tmp_path / "m.py").write_text(
            "class A:\n    @property\n    def session(self):\n        return 1\n"
            "\n\nclass B(A):\n    pass\n"
        )
        index = python_class_index(tmp_path)
        assert "session" in public_names("B", index)

    def test_a_dataclass_field_counts(self, tmp_path):
        (tmp_path / "m.py").write_text("class A:\n    devicename: str = ''\n")
        index = python_class_index(tmp_path)
        assert "devicename" in public_names("A", index)

    def test_a_cycle_in_the_bases_terminates(self, tmp_path):
        (tmp_path / "m.py").write_text("class A(B):\n    x = 1\n\n\nclass B(A):\n    y = 2\n")
        index = python_class_index(tmp_path)
        assert public_names("A", index) == {"x", "y"}


def test_the_check_actually_looked_at_something():
    """Guards against the whole gate degrading to a no-op -- the failure mode
    a green check cannot otherwise be told apart from."""
    matlab_root = require_matlab_root()
    _, _, checked = gaps(matlab_root)
    assert checked > 100, f"only {checked} properties were compared; expected the full sweep"
