"""Tests for ndi.gui.nav.datasets_model.

MATLAB counterpart: the model-side private methods of ndi.gui.nav.datasetsPane

Everything here is a plain function over plain values, so everything here is
tested exactly. The failures this guards against are quiet ones -- a session
listed twice, a node labelled with the wrong variable, a dataset that could
not be checked reported as "not in the cloud" -- so the tests are written
around those cases rather than around the happy path.
"""

from __future__ import annotations

import pytest

from ndi.gui.nav import datasets_model as dm
from ndi.gui.nav.datasets_text import UNNAMED_SESSION


class FakeSession:
    """Enough of an ndi.session for the model layer."""

    def __init__(
        self,
        identifier="s1",
        path="",
        *,
        fully_ingested=True,
        in_dataset=False,
        raises=False,
    ):
        self._id = identifier
        self.path = path
        self._fully_ingested = fully_ingested
        self._in_dataset = in_dataset
        self._raises = raises
        self.reference = "ref-" + str(identifier)

    def id(self):
        return self._id

    def is_fully_ingested(self):
        if self._raises:
            raise RuntimeError("database is unreachable")
        return self._fully_ingested

    def isIngestedInDataset(self):
        if self._raises:
            raise RuntimeError("database is unreachable")
        return self._in_dataset


class FakeDataset:
    """Enough of an ndi.dataset for the model layer."""

    def __init__(
        self,
        identifier="d1",
        path="/tmp/ds",
        *,
        sessions=(),
        in_cloud=False,
        cloud_raises=False,
        list_raises=False,
    ):
        self._id = identifier
        self._path = path
        self._sessions = list(sessions)
        self._in_cloud = in_cloud
        self._cloud_raises = cloud_raises
        self._list_raises = list_raises
        self.reference = "ds-" + str(identifier)
        self.opened = []

    def id(self):
        return self._id

    def getpath(self):
        return self._path

    def session_list(self):
        if self._list_raises:
            raise RuntimeError("cannot read session list")
        refs = [ref for ref, _ in self._sessions]
        ids = [sid for _, sid in self._sessions]
        # Python's session_list returns four values, MATLAB's two.
        return refs, ids, [], ""

    def open_session(self, session_id):
        self.opened.append(session_id)
        return FakeSession(session_id)

    def is_in_cloud(self):
        if self._cloud_raises:
            raise RuntimeError("no database")
        return self._in_cloud, "cloud-id" if self._in_cloud else ""


class TestObjId:
    def test_calls_the_method(self):
        assert dm.obj_id(FakeSession("abc")) == "abc"

    def test_a_plain_attribute_also_works(self):
        class Plain:
            id = "xyz"

        assert dm.obj_id(Plain()) == "xyz"

    def test_an_object_that_cannot_say_is_not_an_error(self):
        class Mute:
            def id(self):
                raise RuntimeError("no id")

        assert dm.obj_id(Mute()) == ""

    def test_no_id_at_all(self):
        assert dm.obj_id(object()) == ""


class TestWorkspaceScanning:
    def test_finds_instances_by_class(self):
        ns = {"S": FakeSession("a"), "n": 3, "D": FakeDataset()}
        assert dm.scan_workspace(FakeSession, ns) == [ns["S"]]

    def test_dunder_names_are_skipped(self):
        ns = {"__builtins__": FakeSession("a"), "S": FakeSession("b")}
        found = dm.scan_workspace(FakeSession, ns)
        assert [dm.obj_id(s) for s in found] == ["b"]

    def test_results_are_in_variable_name_order(self):
        """Two runs over one workspace must produce the same tree; dict order
        is assignment order, which is not an order a user would recognise."""
        ns = {"zeta": FakeSession("z"), "alpha": FakeSession("a")}
        assert [dm.obj_id(s) for s in dm.scan_workspace(FakeSession, ns)] == ["a", "z"]

    def test_an_empty_namespace_is_fine(self):
        assert dm.scan_workspace(FakeSession, {}) == []

    def test_defaults_to_the_main_module(self):
        """The stand-in for MATLAB's base workspace."""
        import __main__

        marker = FakeSession("from-main")
        __main__._ndi_test_session = marker
        try:
            assert marker in dm.scan_workspace(FakeSession)
        finally:
            delattr(__main__, "_ndi_test_session")


class TestWorkspaceVarIndex:
    def test_maps_id_to_variable_names(self):
        s = FakeSession("a")
        index = dm.build_workspace_var_index(FakeSession, {"S": s})
        assert index == {"a": ["S"]}

    def test_two_variables_holding_one_object(self):
        s = FakeSession("a")
        index = dm.build_workspace_var_index(FakeSession, {"S": s, "S2": s})
        assert index["a"] == ["S", "S2"]

    def test_matches_by_id_not_identity(self):
        """A session opened twice is two objects with one id. Matching by
        identity would leave the second node undecorated."""
        index = dm.build_workspace_var_index(
            FakeSession, {"S": FakeSession("a"), "T": FakeSession("a")}
        )
        assert index["a"] == ["S", "T"]

    def test_an_object_with_no_id_contributes_nothing(self):
        class Mute(FakeSession):
            def id(self):
                return ""

        assert dm.build_workspace_var_index(FakeSession, {"S": Mute()}) == {}

    def test_accepts_several_classes(self):
        index = dm.build_workspace_var_index(
            (FakeSession, FakeDataset), {"S": FakeSession("a"), "D": FakeDataset("b")}
        )
        assert index == {"a": ["S"], "b": ["D"]}


class TestDecorateWithWorkspaceVars:
    def test_appends_quoted_names(self):
        assert dm.decorate_with_workspace_vars("myref", "a", {"a": ["S", "S2"]}) == (
            'myref "S", "S2"'
        )

    def test_an_object_with_no_variable_is_unchanged(self):
        assert dm.decorate_with_workspace_vars("myref", "a", {"b": ["S"]}) == "myref"

    def test_no_index_at_all(self):
        assert dm.decorate_with_workspace_vars("myref", "a", None) == "myref"

    def test_an_empty_id_is_never_decorated(self):
        assert dm.decorate_with_workspace_vars("myref", "", {"": ["S"]}) == "myref"


class TestNodeData:
    def test_a_session_node_starts_unknown(self):
        """Status is computed only when the user asks, so listing stays
        cheap and a node shows no badge until then."""
        nd = dm.session_node_data(FakeSession(), None, "")
        assert nd["status"] == {"ingestion": "unknown"}

    def test_status_dicts_are_not_shared_between_nodes(self):
        a = dm.session_node_data()
        b = dm.session_node_data()
        a["status"]["ingestion"] = "ingested"
        assert b["status"]["ingestion"] == "unknown"

    def test_a_dataset_child_carries_dataset_and_id(self):
        ds = FakeDataset()
        nd = dm.session_node_data(None, ds, "sid")
        assert nd["session"] is None
        assert nd["dataset"] is ds
        assert nd["session_id"] == "sid"

    def test_dataset_node_data(self):
        ds = FakeDataset()
        assert dm.dataset_node_data(ds) == {"kind": "dataset", "dataset": ds}

    def test_the_unaffiliated_root_carries_no_dataset(self):
        assert dm.dataset_node_data() == {"kind": "dataset"}


class TestResolveSession:
    def test_uses_a_stored_session_directly(self):
        s = FakeSession()
        assert dm.resolve_session(dm.session_node_data(s, None, "")) is s

    def test_opens_from_the_dataset_by_id(self):
        ds = FakeDataset()
        got = dm.resolve_session(dm.session_node_data(None, ds, "sid"))
        assert ds.opened == ["sid"]
        assert dm.obj_id(got) == "sid"

    def test_a_failed_open_returns_none_rather_than_raising(self):
        """A node whose session has gone away must not take the tree down."""

        class Broken(FakeDataset):
            def open_session(self, session_id):
                raise RuntimeError("gone")

        assert dm.resolve_session(dm.session_node_data(None, Broken(), "sid")) is None

    def test_no_session_and_no_dataset(self):
        assert dm.resolve_session(dm.session_node_data(None, None, "")) is None

    def test_a_non_mapping_is_none(self):
        assert dm.resolve_session(None) is None


class TestComputeSessionStatus:
    def test_in_a_dataset_ingested(self):
        s = FakeSession(in_dataset=True)
        status, err = dm.compute_session_status(s, {"dataset": FakeDataset()})
        assert status == {"ingestion": "ingested"}
        assert err is None

    def test_in_a_dataset_not_ingested_is_linked_not_none(self):
        """The two questions differ: inside a dataset the alternative to
        ingested is LINKED; stand-alone it is NONE."""
        s = FakeSession(in_dataset=False)
        status, _ = dm.compute_session_status(s, {"dataset": FakeDataset()})
        assert status == {"ingestion": "linked"}

    def test_stand_alone_ingested(self):
        status, _ = dm.compute_session_status(FakeSession(fully_ingested=True), {})
        assert status == {"ingestion": "ingested"}

    def test_stand_alone_not_ingested_is_none(self):
        status, _ = dm.compute_session_status(FakeSession(fully_ingested=False), {})
        assert status == {"ingestion": "none"}

    def test_no_node_data_at_all_reads_as_stand_alone(self):
        status, _ = dm.compute_session_status(FakeSession(fully_ingested=False))
        assert status == {"ingestion": "none"}

    def test_a_failure_is_unknown_and_hands_back_the_error(self):
        """Unknown draws no badge. A status we could not determine must
        never be reported as a definite 'not ingested'."""
        status, err = dm.compute_session_status(FakeSession(raises=True), {})
        assert status == {"ingestion": "unknown"}
        assert isinstance(err, RuntimeError)

    def test_the_dataset_branch_is_chosen_by_the_node_not_the_session(self):
        """A session object answers both questions; which one is asked is
        decided by where the node sits."""
        s = FakeSession(fully_ingested=True, in_dataset=False)
        in_ds, _ = dm.compute_session_status(s, {"dataset": FakeDataset()})
        alone, _ = dm.compute_session_status(s, {})
        assert in_ds == {"ingestion": "linked"}
        assert alone == {"ingestion": "ingested"}


class TestPaths:
    def test_session_path_reads_the_property(self):
        assert dm.session_path(FakeSession(path="/data/s")) == "/data/s"

    def test_dataset_path_reads_getpath(self):
        """MATLAB reads ds.path for both; the Python dataset has getpath()
        and no path property, and a silent '' here would quietly disable the
        de-duplication in unaffiliated_sessions."""
        assert dm.dataset_path(FakeDataset(path="/data/d")) == "/data/d"

    def test_no_path_is_empty_not_an_error(self):
        assert dm.session_path(object()) == ""

    def test_a_raising_path_is_empty(self):
        class Broken:
            @property
            def path(self):
                raise RuntimeError("no path")

        assert dm.session_path(Broken()) == ""


class TestUnaffiliatedSessions:
    def test_user_sessions_come_first(self):
        user = FakeSession("u", path="/a")
        ws = FakeSession("w", path="/b")
        got = dm.unaffiliated_sessions([user], FakeSession, {"W": ws})
        assert [dm.obj_id(s) for s in got] == ["u", "w"]

    def test_a_workspace_duplicate_of_a_listed_path_is_dropped(self):
        """Opening the same directory again and binding it to a variable
        must not list the session twice."""
        user = FakeSession("u", path="/same")
        ws = FakeSession("w", path="/same")
        got = dm.unaffiliated_sessions([user], FakeSession, {"W": ws})
        assert [dm.obj_id(s) for s in got] == ["u"]

    def test_sessions_without_a_path_are_never_duplicates(self):
        """Two sessions that both cannot say where they live are not
        thereby the same session."""
        got = dm.unaffiliated_sessions(
            [FakeSession("u", path="")],
            FakeSession,
            {"A": FakeSession("a", path=""), "B": FakeSession("b", path="")},
        )
        assert [dm.obj_id(s) for s in got] == ["u", "a", "b"]

    def test_two_workspace_variables_at_one_path_list_once(self):
        s1 = FakeSession("a", path="/same")
        s2 = FakeSession("b", path="/same")
        got = dm.unaffiliated_sessions([], FakeSession, {"A": s1, "B": s2})
        assert [dm.obj_id(s) for s in got] == ["a"]

    def test_no_user_sessions_and_no_workspace(self):
        assert dm.unaffiliated_sessions(None, FakeSession, {}) == []


class TestDatasetSessionRows:
    def test_one_row_per_session(self):
        ds = FakeDataset(sessions=[("refA", "idA"), ("refB", "idB")])
        rows = dm.dataset_session_rows(ds)
        assert [r["label"] for r in rows] == ["refA", "refB"]
        assert [r["node_data"]["session_id"] for r in rows] == ["idA", "idB"]

    def test_an_empty_reference_gets_the_placeholder(self):
        rows = dm.dataset_session_rows(FakeDataset(sessions=[("", "idA")]))
        assert rows[0]["label"] == UNNAMED_SESSION

    def test_labels_are_decorated_from_the_id_without_opening_the_session(self):
        ds = FakeDataset(sessions=[("refA", "idA")])
        rows = dm.dataset_session_rows(ds, {"idA": ["S"]})
        assert rows[0]["label"] == 'refA "S"'
        assert ds.opened == []

    def test_a_dataset_that_cannot_list_yields_no_rows(self):
        """One unreadable dataset must not empty the whole tree."""
        assert dm.dataset_session_rows(FakeDataset(list_raises=True)) == []

    def test_a_two_value_session_list_also_works(self):
        """MATLAB's session_list returns two values, Python's four."""

        class TwoValue(FakeDataset):
            def session_list(self):
                return ["refA"], ["idA"]

        rows = dm.dataset_session_rows(TwoValue())
        assert [r["label"] for r in rows] == ["refA"]

    def test_more_references_than_ids(self):
        class Ragged(FakeDataset):
            def session_list(self):
                return ["refA", "refB"], ["idA"], [], ""

        rows = dm.dataset_session_rows(Ragged())
        assert [r["node_data"]["session_id"] for r in rows] == ["idA", ""]


class TestDatasetRows:
    def test_user_datasets_then_workspace(self):
        user = FakeDataset("u")
        ws = FakeDataset("w")
        rows = dm.dataset_rows([user], FakeDataset, {"D": ws})
        assert [r["node_data"]["dataset"] for r in rows] == [user, ws]

    def test_each_row_carries_its_session_rows(self):
        ds = FakeDataset("u", sessions=[("refA", "idA")])
        rows = dm.dataset_rows([ds], FakeDataset, {})
        assert [s["label"] for s in rows[0]["sessions"]] == ["refA"]

    def test_labels_are_decorated(self):
        ds = FakeDataset("u")
        rows = dm.dataset_rows([ds], FakeDataset, {}, {"u": ["D"]})
        assert rows[0]["label"] == 'ds-u "D"'

    def test_nothing_anywhere(self):
        assert dm.dataset_rows(None, FakeDataset, {}) == []

    def test_search_path_discovery_is_an_empty_seam(self):
        """Empty on both sides; kept named so the two ports gain it
        together rather than one growing a different mechanism."""
        assert dm.search_path_datasets() == []


class TestUnaffiliatedRows:
    def test_label_and_payload(self):
        s = FakeSession("a")
        rows = dm.unaffiliated_rows([s])
        assert rows[0]["label"] == "ref-a"
        assert rows[0]["node_data"]["session"] is s

    def test_decorated_from_the_index(self):
        rows = dm.unaffiliated_rows([FakeSession("a")], {"a": ["S"]})
        assert rows[0]["label"] == 'ref-a "S"'

    def test_none(self):
        assert dm.unaffiliated_rows(None) == []


class TestCheckAllCloudStatus:
    def test_counts_and_states(self):
        datasets = [FakeDataset(in_cloud=True), FakeDataset(in_cloud=False)]
        report, states = dm.check_all_cloud_status(datasets)
        assert report == {"total": 2, "in_cloud": 1, "not_in_cloud": 1, "errors": 0}
        assert states == ["incloud", "notincloud"]

    def test_a_dataset_that_cannot_be_checked_is_an_error_not_a_no(self):
        """'We asked and the answer was no' and 'we could not ask' must not
        decorate a node the same way -- that is what the errors field is
        for, and what cloud_summary_message reports separately."""
        report, states = dm.check_all_cloud_status([FakeDataset(cloud_raises=True)])
        assert report["errors"] == 1
        assert report["not_in_cloud"] == 0
        assert states == ["unknown"]

    def test_no_datasets(self):
        report, states = dm.check_all_cloud_status([])
        assert report == {"total": 0, "in_cloud": 0, "not_in_cloud": 0, "errors": 0}
        assert states == []

    def test_progress_is_reported_per_dataset(self):
        seen = []
        dm.check_all_cloud_status([FakeDataset(), FakeDataset()], lambda f, m: seen.append((f, m)))
        assert [f for f, _ in seen] == [0.5, 1.0]
        assert "1 of 2" in seen[0][1]

    def test_a_bare_boolean_is_accepted(self):
        """A caller's stand-in need not model the cloud id."""

        class Bare(FakeDataset):
            def is_in_cloud(self):
                return True

        report, states = dm.check_all_cloud_status([Bare()])
        assert report["in_cloud"] == 1
        assert states == ["incloud"]

    def test_the_report_feeds_cloud_summary_message(self):
        """The two halves were ported in different PRs; this is the seam."""
        from ndi.gui.nav.datasets_text import cloud_summary_message

        report, _ = dm.check_all_cloud_status(
            [FakeDataset(in_cloud=True), FakeDataset(cloud_raises=True)]
        )
        msg = cloud_summary_message(report)
        assert "1 of 2 datasets are in NDI Cloud." in msg
        assert "1 dataset could not be checked." in msg


class TestDatasetIsInCloud:
    """ndi.dataset.is_in_cloud, ported here because the bulk check needs it."""

    def _dataset_with_docs(self, docs):
        # The base class, not ndi.dataset.ndi_dataset -- that name is an
        # alias for the directory-backed subclass, which needs a path.
        from ndi.dataset import _DatasetBase

        class FakeInnerSession:
            def database_search(self, query):
                return docs

        ds = _DatasetBase()
        ds._session = FakeInnerSession()
        return ds

    def test_no_remote_document_means_not_in_cloud(self):
        in_cloud, cloud_id = self._dataset_with_docs([]).is_in_cloud()
        assert in_cloud is False
        assert cloud_id == ""

    def test_a_remote_document_yields_its_id(self):
        class Doc:
            document_properties = {"dataset_remote": {"dataset_id": "abc123"}}

        in_cloud, cloud_id = self._dataset_with_docs([Doc()]).is_in_cloud()
        assert in_cloud is True
        assert cloud_id == "abc123"

    def test_several_remote_documents_take_the_first_rather_than_raising(self):
        """More than one is a misconfiguration, but a status check that
        throws is worse than one that picks."""

        class Doc:
            def __init__(self, i):
                self.document_properties = {"dataset_remote": {"dataset_id": i}}

        in_cloud, cloud_id = self._dataset_with_docs([Doc("first"), Doc("second")]).is_in_cloud()
        assert in_cloud is True
        assert cloud_id == "first"

    def test_a_dataset_with_no_session_is_not_in_cloud(self):
        from ndi.dataset import _DatasetBase

        assert _DatasetBase().is_in_cloud() == (False, "")


if __name__ == "__main__":
    pytest.main([__file__])
