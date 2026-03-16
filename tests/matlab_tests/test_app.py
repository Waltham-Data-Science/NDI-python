"""
Port of MATLAB ndi.unittest.app.TestMarkGarbage tests.

MATLAB source files:
  +app/TestMarkGarbage.m → TestMarkGarbage

Tests the ndi_app_markgarbage app for marking, loading, and clearing
valid time intervals on recording elements.

The MATLAB tests require a full session with Intan data and probes.
We provide:
  - Tests with mocked session (database_add/search/remove) but REAL
    ndi_document creation — ensuring the schema path and ndi_document API work.
  - Integration tests (skip if ndi_session_dir unavailable) for full flow.
"""

from unittest.mock import MagicMock

import pytest

from ndi.document import ndi_document

# ===========================================================================
# TestMarkGarbageInstantiation — Basic API tests
# ===========================================================================


class TestMarkGarbageInstantiation:
    """Port of ndi.unittest.app.TestMarkGarbage — instantiation tests."""

    def test_create_without_session(self):
        """ndi_app_markgarbage can be created without a session."""
        from ndi.app.markgarbage import ndi_app_markgarbage

        app = ndi_app_markgarbage()
        assert app is not None
        assert app.session is None
        assert app.name == "ndi_app_markgarbage"

    def test_create_with_session(self):
        """ndi_app_markgarbage can be created with a session."""
        from ndi.app.markgarbage import ndi_app_markgarbage

        session = MagicMock()
        session.id.return_value = "session-123"
        app = ndi_app_markgarbage(session)
        assert app.session is session

    def test_repr(self):
        """ndi_app_markgarbage has a useful repr."""
        from ndi.app.markgarbage import ndi_app_markgarbage

        app = ndi_app_markgarbage()
        assert "ndi_app_markgarbage" in repr(app)

    def test_repr_with_session(self):
        """ndi_app_markgarbage repr reflects session state."""
        from ndi.app.markgarbage import ndi_app_markgarbage

        session = MagicMock()
        app = ndi_app_markgarbage(session)
        r = repr(app)
        assert "ndi_app_markgarbage" in r
        assert "True" in r  # session=True

    def test_inherits_from_app(self):
        """ndi_app_markgarbage inherits from ndi_app."""
        from ndi.app import ndi_app
        from ndi.app.markgarbage import ndi_app_markgarbage

        app = ndi_app_markgarbage()
        assert isinstance(app, ndi_app)


# ===========================================================================
# TestMarkGarbageMocked — Tests with real ndi_document, mocked session
# ===========================================================================


class TestMarkGarbageMocked:
    """Port of ndi.unittest.app.TestMarkGarbage — mocked database tests.

    These tests use a mock session (database_add/search/remove) but let
    markvalidinterval create REAL ndi_document objects from the actual
    apps/markgarbage/valid_interval schema. This ensures the schema
    path, ndi_document constructor, set_session_id, and set_dependency_value
    all work correctly.
    """

    def _make_app_and_probe(self):
        """Create a ndi_app_markgarbage app with mocked session and probe."""
        from ndi.app.markgarbage import ndi_app_markgarbage

        session = MagicMock()
        session.id.return_value = "session-test-123"
        session.database_add = MagicMock()
        session.database_search = MagicMock(return_value=[])
        session.database_remove = MagicMock()

        probe = MagicMock()
        probe.id = "probe-001"
        probe.name = "cortex"
        probe.reference = 1

        timeref = MagicMock()
        timeref.__str__ = MagicMock(return_value="timeref-epoch1")

        app = ndi_app_markgarbage(session)
        return app, session, probe, timeref

    def test_markvalidinterval_calls_database_add(self):
        """markvalidinterval creates a real ndi_document and adds to database."""
        app, session, probe, timeref = self._make_app_and_probe()

        app.markvalidinterval(probe, 1.0, timeref, 3.0, timeref)

        session.database_add.assert_called_once()
        doc = session.database_add.call_args[0][0]
        # Verify it's a real ndi_document, not a mock
        assert isinstance(doc, ndi_document)

    def test_markvalidinterval_creates_correct_document(self):
        """markvalidinterval creates ndi_document with correct schema and properties."""
        app, session, probe, timeref = self._make_app_and_probe()

        app.markvalidinterval(probe, 1.0, timeref, 3.0, timeref)

        doc = session.database_add.call_args[0][0]
        props = doc.document_properties

        # Verify schema class
        doc_class = props.get("document_class", {})
        assert doc_class.get("class_name") == "valid_interval"

        # Verify interval values stored
        vi = props.get("valid_interval")
        assert vi is not None
        assert vi["t0"] == 1.0
        assert vi["t1"] == 3.0

    def test_markvalidinterval_sets_session_id(self):
        """markvalidinterval sets the session ID on the ndi_document."""
        app, session, probe, timeref = self._make_app_and_probe()

        app.markvalidinterval(probe, 1.0, timeref, 3.0, timeref)

        doc = session.database_add.call_args[0][0]
        assert doc.session_id == "session-test-123"

    def test_markvalidinterval_sets_dependency(self):
        """markvalidinterval sets element_id dependency on the ndi_document."""
        app, session, probe, timeref = self._make_app_and_probe()

        app.markvalidinterval(probe, 1.0, timeref, 3.0, timeref)

        doc = session.database_add.call_args[0][0]
        deps = doc.document_properties.get("depends_on", [])
        dep_names = {d["name"]: d["value"] for d in deps}
        assert dep_names.get("element_id") == "probe-001"

    def test_clearvalidinterval_removes_docs(self):
        """clearvalidinterval removes all interval docs for probe."""
        app, session, probe, timeref = self._make_app_and_probe()

        mock_doc1 = MagicMock()
        mock_doc2 = MagicMock()
        session.database_search.return_value = [mock_doc1, mock_doc2]

        app.clearvalidinterval(probe)

        assert session.database_remove.call_count == 2

    def test_clearvalidinterval_empty_no_error(self):
        """clearvalidinterval with no existing docs doesn't error."""
        app, session, probe, timeref = self._make_app_and_probe()
        session.database_search.return_value = []

        app.clearvalidinterval(probe)
        session.database_remove.assert_not_called()

    def test_loadvalidinterval_returns_tuple(self):
        """loadvalidinterval returns a (intervals, docs) tuple."""
        app, session, probe, timeref = self._make_app_and_probe()
        session.database_search.return_value = []

        result = app.loadvalidinterval(probe)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert result[0] == []
        assert result[1] == []

    def test_loadvalidinterval_with_real_documents(self):
        """loadvalidinterval correctly reads intervals from real Documents."""
        app, session, probe, timeref = self._make_app_and_probe()

        # Create a real ndi_document (as markvalidinterval would)
        interval = {"t0": 1.0, "timeref_t0": "tr", "t1": 3.0, "timeref_t1": "tr"}
        real_doc = ndi_document(
            "apps/markgarbage/valid_interval",
            valid_interval=interval,
        )
        session.database_search.return_value = [real_doc]

        intervals, docs = app.loadvalidinterval(probe)
        assert len(intervals) == 1
        assert intervals[0]["t0"] == 1.0
        assert intervals[0]["t1"] == 3.0
        assert len(docs) == 1

    def test_markvalidinterval_no_session_raises(self):
        """markvalidinterval without session raises RuntimeError."""
        from ndi.app.markgarbage import ndi_app_markgarbage

        app = ndi_app_markgarbage()  # No session
        probe = MagicMock()
        probe.id = "probe-001"
        timeref = MagicMock()

        with pytest.raises(RuntimeError, match="No session"):
            app.markvalidinterval(probe, 1.0, timeref, 3.0, timeref)

    def test_clearvalidinterval_no_session_noop(self):
        """clearvalidinterval without session is a no-op."""
        from ndi.app.markgarbage import ndi_app_markgarbage

        app = ndi_app_markgarbage()
        probe = MagicMock()
        app.clearvalidinterval(probe)

    def test_loadvalidinterval_no_session_returns_empty(self):
        """loadvalidinterval without session returns empty tuple."""
        from ndi.app.markgarbage import ndi_app_markgarbage

        app = ndi_app_markgarbage()
        probe = MagicMock()

        intervals, docs = app.loadvalidinterval(probe)
        assert intervals == []
        assert docs == []

    def test_mark_then_load_workflow(self):
        """Full mark → load workflow using real Documents."""
        app, session, probe, timeref = self._make_app_and_probe()

        # Mark an interval (creates real ndi_document internally)
        app.markvalidinterval(probe, 2.0, timeref, 5.0, timeref)
        session.database_add.assert_called_once()

        # Capture the real ndi_document that was added
        added_doc = session.database_add.call_args[0][0]
        assert isinstance(added_doc, ndi_document)

        # Mock the search to return that same real ndi_document
        session.database_search.return_value = [added_doc]

        intervals, docs = app.loadvalidinterval(probe)
        assert len(intervals) == 1
        assert intervals[0]["t0"] == 2.0
        assert intervals[0]["t1"] == 5.0

    def test_mark_then_clear_workflow(self):
        """Full mark → clear → load workflow using real Documents."""
        app, session, probe, timeref = self._make_app_and_probe()

        # Mark
        app.markvalidinterval(probe, 1.0, timeref, 3.0, timeref)
        added_doc = session.database_add.call_args[0][0]

        # Clear (mock search returns the real doc to remove)
        session.database_search.return_value = [added_doc]
        app.clearvalidinterval(probe)
        session.database_remove.assert_called_once_with(added_doc)

        # Load after clear (empty)
        session.database_search.return_value = []
        intervals, docs = app.loadvalidinterval(probe)
        assert len(intervals) == 0

    def test_multiple_intervals_workflow(self):
        """Mark multiple intervals, then load all using real Documents."""
        app, session, probe, timeref = self._make_app_and_probe()

        # Mark two intervals
        app.markvalidinterval(probe, 2.0, timeref, 4.0, timeref)
        app.markvalidinterval(probe, 8.0, timeref, 10.0, timeref)
        assert session.database_add.call_count == 2

        # Capture both real Documents
        doc1 = session.database_add.call_args_list[0][0][0]
        doc2 = session.database_add.call_args_list[1][0][0]
        assert isinstance(doc1, ndi_document)
        assert isinstance(doc2, ndi_document)

        # Mock search returning both real docs
        session.database_search.return_value = [doc1, doc2]

        intervals, docs = app.loadvalidinterval(probe)
        assert len(intervals) == 2
        times = sorted([(i["t0"], i["t1"]) for i in intervals])
        assert times[0] == (2.0, 4.0)
        assert times[1] == (8.0, 10.0)
