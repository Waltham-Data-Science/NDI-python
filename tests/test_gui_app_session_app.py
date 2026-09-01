"""Tests for ndi.gui.app.session_app.

MATLAB counterpart: ndi.gui.app.sessionApp

Discovery is the whole of this module, so the tests give it something to
discover: a package written to a temp directory and put on sys.path, holding
a concrete app, an app with a Category, an abstract one, an app in a
subpackage, and a module that raises on import. That last one is the point of
several tests -- a broken app must cost its own entry and nothing else.

No display is needed anywhere here: an "app" in these tests is a plain class
that records the session it was constructed with.
"""

from __future__ import annotations

import sys
import textwrap
from abc import ABC, abstractmethod

import pytest

from ndi.gui.app.session_app import (
    BUILTIN_PACKAGES,
    PACKAGES_PREFERENCE,
    SessionApp,
    class_name,
    resolve_class,
    sessionApp,
    unique_stable,
    walk_modules,
)

PACKAGE = "ndi_test_apps_pkg"

#: A package holding one of everything discovery has to cope with.
SOURCES = {
    "__init__.py": "",
    "viewer.py": """
        from ndi.gui.app.session_app import SessionApp

        class viewer(SessionApp):
            Name = "Viewer"

            def __init__(self, session):
                self.session = session
    """,
    "sorter.py": """
        from ndi.gui.app.session_app import SessionApp

        class sorter(SessionApp):
            Name = "Sorter"
            Category = "Spike Sorters"

            def __init__(self, session):
                self.session = session

        class halfBuilt(SessionApp):
            # No Name: abstract, in MATLAB's sense and in this port's.
            def __init__(self, session):
                self.session = session

        class notAnApp:
            Name = "Not An App"
    """,
    "broken.py": """
        raise RuntimeError("this app module does not import")
    """,
    "deeper/__init__.py": "",
    "deeper/nested.py": """
        from ndi.gui.app.session_app import SessionApp

        class nested(SessionApp):
            Name = "Nested"
            Category = "Spike Sorters"

            def __init__(self, session):
                self.session = session
    """,
}


@pytest.fixture
def apps_package(tmp_path):
    """Write SOURCES to a temp package on sys.path; yield its name."""
    root = tmp_path / PACKAGE
    for relative, source in SOURCES.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")

    sys.path.insert(0, str(tmp_path))
    try:
        yield PACKAGE
    finally:
        sys.path.remove(str(tmp_path))
        for name in [n for n in sys.modules if n == PACKAGE or n.startswith(PACKAGE + ".")]:
            del sys.modules[name]


def labels(apps):
    return [app["Name"] for app in apps]


class TestList:
    def test_it_finds_the_apps_in_a_package(self, apps_package):
        assert sorted(labels(SessionApp.list([apps_package]))) == [
            "Nested",
            "Sorter",
            "Viewer",
        ]

    def test_it_recurses_into_subpackages(self, apps_package):
        found = SessionApp.list([apps_package])
        nested = [app for app in found if app["Name"] == "Nested"]
        assert nested[0]["Class"] == f"{apps_package}.deeper.nested.nested"

    def test_an_app_without_a_name_is_abstract_and_is_skipped(self, apps_package):
        """MATLAB's Name is an abstract constant, so a subclass that supplies
        none is abstract; here it simply has no such attribute."""
        assert "halfBuilt" not in labels(SessionApp.list([apps_package]))

    def test_a_class_that_does_not_adopt_the_interface_is_skipped(self, apps_package):
        """Having a Name is not enough -- notAnApp has one and is not an app."""
        assert "Not An App" not in labels(SessionApp.list([apps_package]))

    def test_the_interface_itself_is_never_listed(self):
        found = SessionApp.list(["ndi.gui.app"])
        assert "SessionApp" not in [app["Class"].rsplit(".", 1)[-1] for app in found]

    def test_a_module_that_will_not_import_costs_only_itself(self, apps_package):
        """broken.py raises on import. The apps beside it still appear."""
        assert len(SessionApp.list([apps_package])) == 3

    def test_a_package_that_does_not_exist_is_not_an_error(self):
        assert SessionApp.list(["no.such.package.anywhere"]) == []

    def test_the_category_comes_through_and_defaults_to_empty(self, apps_package):
        found = {app["Name"]: app["Category"] for app in SessionApp.list([apps_package])}
        assert found == {"Viewer": "", "Sorter": "Spike Sorters", "Nested": "Spike Sorters"}

    def test_the_class_name_is_fully_qualified(self, apps_package):
        found = {app["Name"]: app["Class"] for app in SessionApp.list([apps_package])}
        assert found["Viewer"] == f"{apps_package}.viewer.viewer"

    def test_an_app_is_reported_once_even_when_re_exported(self, apps_package, tmp_path):
        """A package __init__ that re-exports its apps must not double them."""
        init = tmp_path / apps_package / "__init__.py"
        init.write_text("from .viewer import viewer\n", encoding="utf-8")
        assert labels(SessionApp.list([apps_package])).count("Viewer") == 1

    def test_scanning_the_built_ins_works_and_does_not_raise(self):
        """NDI ships no session apps yet, so this is empty today -- what is
        asserted is that the default scan runs and reports a list."""
        assert isinstance(SessionApp.list(), list)


class TestDefaultPackages:
    def test_the_built_ins_come_first(self, monkeypatch):
        monkeypatch.setattr("ndi.preferences.get", lambda path: "")
        assert SessionApp.default_packages() == list(BUILTIN_PACKAGES)

    def test_the_users_packages_are_appended(self, monkeypatch):
        seen = {}

        def fake_get(path):
            seen["path"] = path
            return "mylab.apps; otherlab.gui"

        monkeypatch.setattr("ndi.preferences.get", fake_get)
        assert SessionApp.default_packages() == [
            *BUILTIN_PACKAGES,
            "mylab.apps",
            "otherlab.gui",
        ]
        assert seen["path"] == PACKAGES_PREFERENCE

    def test_a_package_named_twice_is_scanned_once(self, monkeypatch):
        monkeypatch.setattr("ndi.preferences.get", lambda path: "ndi.app, mylab.apps")
        assert SessionApp.default_packages() == [*BUILTIN_PACKAGES, "mylab.apps"]

    def test_an_unreadable_preference_leaves_the_built_ins(self, monkeypatch):
        """A missing user setting must not cost the user NDI's own apps."""

        def boom(path):
            raise KeyError(path)

        monkeypatch.setattr("ndi.preferences.get", boom)
        assert SessionApp.default_packages() == list(BUILTIN_PACKAGES)

    def test_the_preference_is_registered_with_matlabs_path(self):
        import ndi.preferences as ndi_preferences

        assert ndi_preferences.has(PACKAGES_PREFERENCE)
        assert ndi_preferences.get(PACKAGES_PREFERENCE) == ""

    def test_a_users_packages_are_actually_scanned(self, apps_package, monkeypatch):
        """The end of the extension path: name a package in the preference and
        its apps reach the menu, with no edit to NDI."""
        monkeypatch.setattr("ndi.preferences.get", lambda path: apps_package)
        assert "Viewer" in labels(SessionApp.list())


class TestParsePackageList:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("", []),
            (None, []),
            ("mylab.apps", ["mylab.apps"]),
            ("a;b", ["a", "b"]),
            ("a,b", ["a", "b"]),
            ("  a ; , b  ;", ["a", "b"]),
            (["a;b", "c"], ["a", "b", "c"]),
            (("a", "b"), ["a", "b"]),
        ],
    )
    def test_it_splits_on_semicolons_and_commas(self, value, expected):
        assert SessionApp.parse_package_list(value) == expected


class TestLaunch:
    def test_it_constructs_the_class_with_the_session(self, apps_package):
        session = object()
        found = SessionApp.list([apps_package])
        viewer = [app for app in found if app["Name"] == "Viewer"][0]
        app = SessionApp.launch(viewer["Class"], session)
        assert app.session is session

    def test_it_accepts_the_class_itself(self):
        class local(SessionApp):
            Name = "Local"

            def __init__(self, session):
                self.session = session

        session = object()
        assert SessionApp.launch(local, session).session is session

    def test_it_returns_the_app_so_the_caller_can_keep_it_alive(self, apps_package):
        """MATLAB's figure holds its app through guidata; nothing holds a
        Python app but the reference this returns."""
        found = SessionApp.list([apps_package])
        app = SessionApp.launch(found[0]["Class"], object())
        assert app is not None

    def test_an_unresolvable_class_says_so(self):
        with pytest.raises(ValueError, match="no.such.module.someApp"):
            SessionApp.launch("no.such.module.someApp", object())

    def test_a_name_that_is_not_a_class_says_so(self):
        with pytest.raises(ValueError):
            resolve_class("ndi.gui.app.session_app.BUILTIN_PACKAGES")


class TestClassChecks:
    def test_an_abc_abstract_class_is_abstract(self):
        class partial(SessionApp, ABC):
            Name = "Partial"

            @abstractmethod
            def run(self): ...

        assert SessionApp.is_abstract(partial)

    def test_a_class_with_a_name_is_concrete(self):
        class ready(SessionApp):
            Name = "Ready"

        assert not SessionApp.is_abstract(ready)

    def test_the_label_falls_back_to_the_class_name(self):
        class unnamed(SessionApp):
            Name = ""

        assert SessionApp.read_name(unnamed) == "unnamed"

    def test_a_category_that_will_not_stringify_reads_as_none(self):
        class unprintable:
            def __str__(self):
                raise RuntimeError("no")

        class awkward(SessionApp):
            Name = "Awkward"
            Category = unprintable()

        assert SessionApp.read_category(awkward) == ""
        assert SessionApp.read_name(awkward) == "Awkward"

    def test_the_interface_is_not_a_session_app(self):
        assert not SessionApp.is_session_app(SessionApp)
        assert not SessionApp.is_session_app("ndi.gui.app.session_app.SessionApp")


class TestHelpers:
    def test_walk_modules_returns_nothing_for_a_missing_package(self):
        assert walk_modules("no.such.package.anywhere") == []

    def test_walk_modules_accepts_a_plain_module(self):
        modules = walk_modules("ndi.gui.app.session_app")
        assert [module.__name__ for module in modules] == ["ndi.gui.app.session_app"]

    def test_class_name_is_module_plus_qualname(self):
        assert class_name(SessionApp) == "ndi.gui.app.session_app.SessionApp"

    def test_unique_stable_keeps_first_seen_order(self):
        assert unique_stable(["b", "a", "b", "c"]) == ["b", "a", "c"]

    def test_matlabs_spelling_names_the_same_class(self):
        assert sessionApp is SessionApp
