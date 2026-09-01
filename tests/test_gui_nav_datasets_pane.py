"""Tests for ndi.gui.nav.datasets_pane.

MATLAB counterpart: ndi.gui.nav.datasetsPane

The decisions this pane makes live in datasets_model, datasets_text and
datasets_cloud, each tested on its own. What is tested here is the WIRING:
that the tree draws the rows the model computed, that a menu item reaches the
action it names, that a destructive action is gated on a confirmation, and
that a failure is reported rather than raised.

Qt tests skip without PySide6, as elsewhere in this package.
"""

from __future__ import annotations

import os

import pytest

from ndi.gui.nav import datasets_model
from ndi.gui.nav.datasets_pane import (
    GRIP_HEIGHT,
    REFRESH_WIDTH,
    UNAFFILIATED_TEXT,
    DatasetsPane,
    session_apps,
)


class FakeSession:
    def __init__(self, identifier="s1", path="", *, ingested=True, raises=False):
        self._id = identifier
        self.path = path
        self.reference = "ref-" + str(identifier)
        self._ingested = ingested
        self._raises = raises
        self.ingested_calls = 0
        self.cache = FakeCache()

    def id(self):
        return self._id

    def is_fully_ingested(self):
        if self._raises:
            raise RuntimeError("database is unreachable")
        return self._ingested

    def isIngestedInDataset(self):
        return self._ingested

    def ingest(self):
        self.ingested_calls += 1
        return True, ""


class FakeCache:
    def __init__(self):
        self.cleared = 0

    def clear(self):
        self.cleared += 1


class FakeDataset:
    def __init__(self, identifier="d1", *, sessions=(), in_cloud=False):
        self._id = identifier
        self.reference = "ds-" + str(identifier)
        self._sessions = list(sessions)
        self._in_cloud = in_cloud

    def id(self):
        return self._id

    def getpath(self):
        return "/data/" + str(self._id)

    def session_list(self):
        return [r for r, _ in self._sessions], [i for _, i in self._sessions], [], ""

    def open_session(self, session_id):
        return FakeSession(session_id)

    def is_in_cloud(self):
        return self._in_cloud, "cid" if self._in_cloud else ""


def _pane(navigator=None, **kwargs):
    pane = DatasetsPane(navigator)
    for key, value in kwargs.items():
        setattr(pane, key, value)
    return pane


class TestPaneShape:
    def test_it_is_the_elastic_pane(self):
        """Resizable, collapsible and engaged -- the three conditions the
        layout module requires before a pane absorbs leftover height."""
        from ndi.gui.nav import layout as nav_layout

        pane = DatasetsPane()
        assert nav_layout.is_elastic(pane)

    def test_it_has_a_body_and_matlabs_right_width(self):
        pane = DatasetsPane()
        assert pane.has_body()
        assert pane.right_width() == REFRESH_WIDTH

    def test_title_and_minimum(self):
        pane = DatasetsPane()
        assert pane.title == "Datasets"
        assert pane.min_height == 100
        assert pane.height == 220

    def test_grip_height_matches_matlab(self):
        assert GRIP_HEIGHT == 6


class TestSessionApps:
    def test_no_apps_are_discovered_yet(self):
        """ndi.gui.app.sessionApp is not ported. Nothing is hardcoded on
        either side, so this fills itself when that subsystem lands."""
        assert session_apps() == []


class TestTreeRows:
    def test_the_unaffiliated_root_comes_first(self):
        rows = _pane().tree_rows()
        assert rows[0]["label"] == UNAFFILIATED_TEXT
        assert rows[0]["node_data"] == {"kind": "dataset"}

    def test_user_sessions_hang_under_the_root(self):
        pane = _pane(user_sessions=[FakeSession("a", path="/s/a")])
        rows = pane.tree_rows()
        assert [c["label"] for c in rows[0]["children"]] == ["ref-a"]

    def test_a_dataset_and_its_sessions(self):
        ds = FakeDataset("d", sessions=[("refA", "idA"), ("refB", "idB")])
        rows = _pane(user_datasets=[ds]).tree_rows()
        assert rows[1]["label"] == "ds-d"
        assert rows[1]["node_data"]["dataset"] is ds
        assert [c["label"] for c in rows[1]["children"]] == ["refA", "refB"]

    def test_a_session_child_carries_its_parent_dataset(self):
        ds = FakeDataset("d", sessions=[("refA", "idA")])
        child = _pane(user_datasets=[ds]).tree_rows()[1]["children"][0]
        assert child["node_data"]["dataset"] is ds
        assert child["node_data"]["session_id"] == "idA"

    def test_an_empty_workspace_still_shows_the_root(self):
        """The root is always drawn, so 'no sessions' reads as an empty list
        rather than as a missing feature."""
        rows = _pane().tree_rows()
        assert len(rows) == 1


class TestNodeMenuEnablement:
    """The Cloud menu greys out from the state CACHED on the node."""

    class FakeAction:
        def __init__(self):
            self.enabled = None

        def setEnabled(self, tf):
            self.enabled = tf

    class FakeNode:
        def __init__(self, data):
            self._data = data

        def data(self, column, role):
            return self._data

        def setData(self, column, role, value):
            self._data = value

    def test_unknown_enables_everything(self):
        """Before the status has been checked, blocking an action would stop
        a user for no reason."""
        pane = DatasetsPane()
        upload = self.FakeAction()
        linked = [self.FakeAction(), self.FakeAction()]
        assert pane.update_dataset_menu_enable(
            self.FakeNode({"kind": "dataset"}), upload, linked
        ) == (True, True)
        assert upload.enabled is True
        assert all(a.enabled for a in linked)

    def test_in_cloud_disables_upload_and_enables_the_rest(self):
        pane = DatasetsPane()
        upload = self.FakeAction()
        linked = [self.FakeAction()]
        node = self.FakeNode({"cloud": "incloud"})
        assert pane.update_dataset_menu_enable(node, upload, linked) == (False, True)

    def test_not_in_cloud_is_the_reverse(self):
        pane = DatasetsPane()
        upload = self.FakeAction()
        linked = [self.FakeAction()]
        node = self.FakeNode({"cloud": "notincloud"})
        assert pane.update_dataset_menu_enable(node, upload, linked) == (True, False)


# ----------------------------------------------------------------------
# Qt
# ----------------------------------------------------------------------
def _qt_or_skip():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from ndi.gui._qt_helpers import get_or_create_app

        return get_or_create_app()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no usable Qt platform plugin: {exc}")


def _built_pane(navigator=None, **kwargs):
    """A DatasetsPane with real widgets, inside a real navigator window.

    The navigator's alert is replaced with a recorder. Navigator.alert opens
    a MODAL QMessageBox, which under the offscreen platform blocks forever
    with nothing to dismiss it -- so a test that triggers any success or
    failure message would hang rather than fail. Recording instead also lets
    a test assert what the user would have been told.
    """
    from ndi.gui.navigator import Navigator

    nav = navigator if navigator is not None else Navigator()
    nav.alerts = []
    nav.alert = lambda m, t, success=True: nav.alerts.append((m, t, success))
    # By TYPE, not by index: the stack order changes as panes are ported
    # (CloudPane landing ahead of Datasets moved it from 1 to 2), and a test
    # that hardcodes a position breaks for a reason that has nothing to do
    # with what it is testing.
    pane = nav.datasets_pane_handle()
    if pane is None:  # pragma: no cover - only if the stack changes
        pytest.skip("no datasets pane in the stack")
    for key, value in kwargs.items():
        setattr(pane, key, value)
    return nav, pane


class TestTreeWidget:
    def test_the_tree_draws_the_rows_the_model_computed(self):
        _qt_or_skip()
        ds = FakeDataset("d", sessions=[("refA", "idA")])
        nav, pane = _built_pane(user_datasets=[ds])
        rows = pane.populate_tree()
        assert pane.tree.topLevelItemCount() == len(rows)
        assert pane.tree.topLevelItem(1).text(0) == "ds-d"
        assert pane.tree.topLevelItem(1).child(0).text(0) == "refA"

    def test_refresh_rebuilds_rather_than_appends(self):
        """Calling refresh twice must not double the tree."""
        _qt_or_skip()
        nav, pane = _built_pane(user_datasets=[FakeDataset("d")])
        pane.refresh()
        first = pane.tree.topLevelItemCount()
        pane.refresh()
        assert pane.tree.topLevelItemCount() == first

    def test_dataset_nodes_excludes_the_unaffiliated_root(self):
        """The root is top-level but holds no dataset; a bulk action must
        not treat it as one."""
        _qt_or_skip()
        nav, pane = _built_pane(user_datasets=[FakeDataset("d")])
        pane.populate_tree()
        nodes = pane.dataset_nodes()
        assert len(nodes) == 1
        assert nodes[0].text(0) == "ds-d"

    def test_node_payloads_survive_the_round_trip_through_qt(self):
        _qt_or_skip()
        ds = FakeDataset("d", sessions=[("refA", "idA")])
        nav, pane = _built_pane(user_datasets=[ds])
        pane.populate_tree()
        child = pane.tree.topLevelItem(1).child(0)
        assert datasets_model.resolve_session(child.data(0, 32)) is not None


class TestCloudStateCaching:
    def test_state_is_stored_on_the_node_for_the_menu_to_read(self):
        """Cached so opening the menu needs no database query."""
        _qt_or_skip()
        nav, pane = _built_pane(user_datasets=[FakeDataset("d")])
        pane.populate_tree()
        node = pane.dataset_nodes()[0]
        pane.set_dataset_cloud_state(node, "incloud")
        assert node.data(0, 32)["cloud"] == "incloud"

    def test_check_all_badges_every_dataset(self):
        _qt_or_skip()
        nav, pane = _built_pane(user_datasets=[FakeDataset("a", in_cloud=True), FakeDataset("b")])
        pane.populate_tree()
        report = pane.check_all_cloud_status()
        assert report == {"total": 2, "in_cloud": 1, "not_in_cloud": 1, "errors": 0}
        states = [n.data(0, 32).get("cloud") for n in pane.dataset_nodes()]
        assert states == ["incloud", "notincloud"]

    def test_a_dataset_that_cannot_be_checked_gets_no_badge(self):
        """'We could not ask' must not be drawn as 'not in the cloud'."""
        _qt_or_skip()

        class Broken(FakeDataset):
            def is_in_cloud(self):
                raise RuntimeError("no database")

        nav, pane = _built_pane(user_datasets=[Broken("x")])
        pane.populate_tree()
        report = pane.check_all_cloud_status()
        assert report["errors"] == 1
        assert "cloud" not in pane.dataset_nodes()[0].data(0, 32)


class TestSessionActions:
    def _session_node(self, pane, session):
        pane.user_sessions = [session]
        pane.populate_tree()
        return pane.tree.topLevelItem(0).child(0)

    def test_clear_cache_reaches_the_session(self):
        _qt_or_skip()
        nav, pane = _built_pane()
        session = FakeSession("a", path="/s/a")
        node = self._session_node(pane, session)
        assert pane.clear_session_cache(node) is True
        assert session.cache.cleared == 1

    def test_a_failing_clear_is_reported_not_raised(self):
        _qt_or_skip()
        nav, pane = _built_pane()
        session = FakeSession("a", path="/s/a")
        session.cache.clear = _raise("cache is locked")
        node = self._session_node(pane, session)
        assert pane.clear_session_cache(node) is False
        assert nav.alerts and "cache is locked" in nav.alerts[0][0]

    def test_ingestion_status_badges_the_node_on_demand(self):
        """Status is computed here and nowhere else, so listing stays cheap."""
        _qt_or_skip()
        nav, pane = _built_pane()
        node = self._session_node(pane, FakeSession("a", path="/s/a", ingested=True))
        assert node.data(0, 32)["status"] == {"ingestion": "unknown"}
        assert pane.update_session_status(node) == {"ingestion": "ingested"}
        assert node.data(0, 32)["status"] == {"ingestion": "ingested"}

    def test_a_status_that_cannot_be_determined_stays_unknown_and_says_so(self):
        _qt_or_skip()
        nav, pane = _built_pane()
        node = self._session_node(pane, FakeSession("a", path="/s/a", raises=True))
        assert pane.update_session_status(node) == {"ingestion": "unknown"}
        assert any("Could not determine" in m for m, _, _ in nav.alerts)

    def test_a_node_whose_session_cannot_be_opened_reports_it(self):
        _qt_or_skip()
        nav, pane = _built_pane()
        node = self._session_node(pane, FakeSession("a", path="/s/a"))
        node.setData(0, 32, {"kind": "session", "session": None, "dataset": None})
        assert pane.clear_session_cache(node) is False
        assert any("Could not open the session" in m for m, _, _ in nav.alerts)


class TestIngestConfirmation:
    def test_declining_the_confirmation_does_not_ingest(self):
        """A long, irreversible action must not run on a stray click."""
        _qt_or_skip()
        nav, pane = _built_pane()
        session = FakeSession("a", path="/s/a")
        pane.user_sessions = [session]
        pane.populate_tree()
        node = pane.tree.topLevelItem(0).child(0)
        pane._confirm = lambda *a, **k: False
        assert pane.ingest_session_node(node) is False
        assert session.ingested_calls == 0

    def test_accepting_ingests_and_refreshes_the_badge(self):
        _qt_or_skip()
        nav, pane = _built_pane()
        session = FakeSession("a", path="/s/a", ingested=True)
        pane.user_sessions = [session]
        pane.populate_tree()
        node = pane.tree.topLevelItem(0).child(0)
        pane._confirm = lambda *a, **k: True
        assert pane.ingest_session_node(node) is True
        assert session.ingested_calls == 1
        assert node.data(0, 32)["status"] == {"ingestion": "ingested"}


class TestMirrorConfirmation:
    def test_declining_never_calls_the_destructive_operation(self):
        """Both mirror directions delete documents permanently; the call must
        be unreachable without the user having seen the warning."""
        _qt_or_skip()
        from ndi.gui.nav import datasets_cloud

        nav, pane = _built_pane(user_datasets=[FakeDataset("d")])
        pane.populate_tree()
        node = pane.dataset_nodes()[0]

        calls = []
        original = datasets_cloud.mirror_dataset
        datasets_cloud.mirror_dataset = lambda ds, d: calls.append((ds, d))
        try:
            pane._confirm = lambda *a, **k: False
            assert pane._run_mirror(node, FakeDataset("d"), "to_remote") is None
        finally:
            datasets_cloud.mirror_dataset = original
        assert calls == []

    def test_accepting_runs_it(self):
        _qt_or_skip()
        from ndi.gui.nav import datasets_cloud

        nav, pane = _built_pane(user_datasets=[FakeDataset("d")])
        pane.populate_tree()
        node = pane.dataset_nodes()[0]

        original = datasets_cloud.mirror_dataset
        datasets_cloud.mirror_dataset = lambda ds, d: datasets_cloud.CloudActionResult(
            True, "Mirror to Cloud", "Done. 1 document uploaded", "success", None
        )
        try:
            pane._confirm = lambda *a, **k: True
            result = pane._run_mirror(node, FakeDataset("d"), "to_remote")
        finally:
            datasets_cloud.mirror_dataset = original
        assert result.ok
        assert nav.alerts[0][1] == "Mirror to Cloud"


class TestMenusAreBuilt:
    def test_a_session_node_gets_apps_and_session_submenus(self):
        _qt_or_skip()
        nav, pane = _built_pane()
        pane.user_sessions = [FakeSession("a", path="/s/a")]
        pane.populate_tree()
        node = pane.tree.topLevelItem(0).child(0)
        menu = pane.build_node_menu(node)
        assert [a.text() for a in menu.actions()] == ["Apps", "Session"]

    def test_the_apps_menu_is_present_but_empty(self):
        """Empty says 'no apps found'. Omitting it would say 'sessions have
        no apps', which is false."""
        _qt_or_skip()
        nav, pane = _built_pane()
        pane.user_sessions = [FakeSession("a", path="/s/a")]
        pane.populate_tree()
        menu = pane.build_node_menu(pane.tree.topLevelItem(0).child(0))
        apps = menu.actions()[0].menu()
        assert apps is not None
        assert apps.actions() == []

    def test_the_session_menu_items_are_alphabetical(self):
        _qt_or_skip()
        nav, pane = _built_pane()
        pane.user_sessions = [FakeSession("a", path="/s/a")]
        pane.populate_tree()
        menu = pane.build_node_menu(pane.tree.topLevelItem(0).child(0))
        items = [a.text() for a in menu.actions()[1].menu().actions()]
        assert items == ["Clear Cache", "Info...", "Ingest", "Ingestion Status"]

    def test_a_dataset_node_gets_the_cloud_menu_in_matlabs_order(self):
        _qt_or_skip()
        nav, pane = _built_pane(user_datasets=[FakeDataset("d")])
        pane.populate_tree()
        menu = pane.build_node_menu(pane.dataset_nodes()[0])
        cloud = menu.actions()[0].menu()
        labels = [a.text() for a in cloud.actions() if a.text()]
        assert labels == [
            "Check Cloud status",
            "Upload to Cloud",
            "Check Cloud for New",
            "Check Local for New",
            "Download New from Cloud",
            "Upload New to Cloud",
            "Two Way Sync",
            "Mirror from Cloud",
            "Mirror to Cloud",
        ]

    def test_the_unaffiliated_root_has_no_menu_until_the_add_flows_land(self):
        """Its two items create and open sessions, both in the next slice.
        Omitted entirely rather than shown dead."""
        _qt_or_skip()
        nav, pane = _built_pane()
        pane.populate_tree()
        assert pane.build_node_menu(pane.tree.topLevelItem(0)) is None


def _raise(message):
    def boom(*args, **kwargs):
        raise RuntimeError(message)

    return boom


if __name__ == "__main__":
    pytest.main([__file__])
