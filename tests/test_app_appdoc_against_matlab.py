"""ndi.app.appdoc against MATLAB's +ndi/+app/appdoc.m.

appdoc is the base every NDI app's document handling sits on, so a
divergence here is one every app inherits. Three were there: the
ReplaceIfDifferent rule kept documents MATLAB replaces, a failed removal
was swallowed and then written beside, and an ndi.document handed in where
a struct goes was passed through untouched.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from ndi.app.appdoc import DocExistsAction, ndi_app_appdoc
from ndi.document import ndi_document


class Recording(ndi_app_appdoc):
    """A subclass that records what it was asked to do."""

    def __init__(self, session, existing=None, struct=None):
        super().__init__(
            doc_types=["test_type"],
            doc_document_types=["app/test"],
            doc_session=session,
        )
        self.existing = list(existing or [])
        self.struct = struct or {}
        self.made: list[Any] = []

    def find_appdoc(self, appdoc_type, *args, **kwargs):
        return list(self.existing)

    def doc2struct(self, appdoc_type, doc):
        return self.struct

    def defaultstruct_appdoc(self, appdoc_type):
        return {"from": "defaults"}

    def struct2doc(self, appdoc_type, appdoc_struct, *args, **kwargs):
        self.made.append(appdoc_struct)
        return ndi_document("base")


@pytest.fixture
def session():
    return MagicMock()


def existing_doc():
    return ndi_document("base")


class TestReplaceIfDifferent:
    """MATLAB: more than one existing document counts as different."""

    def test_one_equal_document_is_left_alone(self, session):
        app = Recording(session, existing=[existing_doc()], struct={"a": 1})
        result = app.add_appdoc("test_type", {"a": 1}, DocExistsAction.REPLACE_IF_DIFFERENT)
        assert result == app.existing
        assert app.made == []
        session.database_rm.assert_not_called()

    def test_one_different_document_is_replaced(self, session):
        app = Recording(session, existing=[existing_doc()], struct={"a": 1})
        app.add_appdoc("test_type", {"a": 2}, DocExistsAction.REPLACE_IF_DIFFERENT)
        assert session.database_rm.call_count == 1
        assert app.made == [{"a": 2}]

    def test_several_documents_are_replaced_even_if_one_matches(self, session):
        # "there are multiple versions, must be different". This used to
        # return as soon as ANY existing document matched, leaving the rest
        # in the database.
        app = Recording(session, existing=[existing_doc(), existing_doc()], struct={"a": 1})
        app.add_appdoc("test_type", {"a": 1}, DocExistsAction.REPLACE_IF_DIFFERENT)
        assert session.database_rm.call_count == 2
        assert app.made == [{"a": 1}]

    def test_replace_does_not_compare_at_all(self, session):
        app = Recording(session, existing=[existing_doc()], struct={"a": 1})
        app.add_appdoc("test_type", {"a": 1}, DocExistsAction.REPLACE)
        assert session.database_rm.call_count == 1
        assert app.made == [{"a": 1}]


class TestFailedRemoval:
    def test_a_failed_removal_stops_the_replacement(self, session):
        # Removing under `except Exception: pass` reported success, and a new
        # document was then written beside the ones that never went away.
        session.database_rm.side_effect = RuntimeError("database is read-only")
        app = Recording(session, existing=[existing_doc()], struct={"a": 1})
        with pytest.raises(RuntimeError, match="read-only"):
            app.add_appdoc("test_type", {"a": 2}, DocExistsAction.REPLACE)
        assert app.made == []

    def test_clear_appdoc_lets_the_error_out(self, session):
        session.database_rm.side_effect = RuntimeError("nope")
        app = Recording(session, existing=[existing_doc()])
        with pytest.raises(RuntimeError, match="nope"):
            app.clear_appdoc("test_type")

    def test_clear_appdoc_is_false_when_there_is_nothing_to_clear(self, session):
        assert Recording(session).clear_appdoc("test_type") is False


class TestAppdocStructResolution:
    """MATLAB accepts empty, an ndi.document, or a struct; else it errors."""

    def test_none_uses_the_defaults(self, session):
        app = Recording(session)
        app.add_appdoc("test_type", None)
        assert app.made == [{"from": "defaults"}]

    def test_a_document_is_converted_back_to_a_struct(self, session):
        app = Recording(session, struct={"converted": True})
        app.add_appdoc("test_type", ndi_document("base"))
        assert app.made == [{"converted": True}]

    def test_a_dict_passes_through(self, session):
        app = Recording(session)
        app.add_appdoc("test_type", {"a": 1})
        assert app.made == [{"a": 1}]

    def test_anything_else_is_refused(self, session):
        app = Recording(session)
        with pytest.raises(TypeError, match="Do not know how to process"):
            app.add_appdoc("test_type", 17)


class TestErrorAndNoAction:
    def test_error_names_the_count_and_the_type(self, session):
        app = Recording(session, existing=[existing_doc(), existing_doc()])
        with pytest.raises(RuntimeError, match=r"2 document\(s\).*'test_type' already exist"):
            app.add_appdoc("test_type", {}, DocExistsAction.ERROR)

    def test_noaction_returns_what_was_there(self, session):
        app = Recording(session, existing=[existing_doc()])
        assert app.add_appdoc("test_type", {}, DocExistsAction.NO_ACTION) == app.existing
        assert app.made == []

    def test_an_unknown_action_is_refused(self, session):
        app = Recording(session, existing=[existing_doc()])
        with pytest.raises(ValueError, match="Unknown doc_exists_action"):
            app.add_appdoc("test_type", {}, "Sideways")


class TestAppdocDescription:
    """MATLAB has appdoc_description on the base class; this had nothing."""

    def test_it_exists(self):
        assert callable(getattr(ndi_app_appdoc, "appdoc_description", None))

    def test_it_lists_the_declared_types(self, session):
        text = Recording(session).appdoc_description()
        assert "test_type" in text
        assert "app/test" in text

    def test_a_class_with_no_types_says_so(self):
        assert "(none)" in ndi_app_appdoc().appdoc_description()
