"""Tests for ndi.util.choose_directory.

MATLAB counterparts: ndi.util.chooseDatasetOrSession, chooseSession,
chooseDataset

The picker's promise is that a returned path IS an NDI directory of a kind
the caller asked for, so the caller never re-checks. That promise is what the
loop tests here assert. The wording tests matter for a quieter reason: a
wrong message does not raise, it just tells someone their folder is the wrong
sort of thing for the wrong reason, and each of the three cases needs a
different next move from the user.
"""

from __future__ import annotations

import pytest

from ndi.util import choose_directory as cd


class TestIsAccepted:
    def test_a_wanted_kind(self):
        assert cd.is_accepted("session", ("session",))

    def test_an_unwanted_kind(self):
        assert not cd.is_accepted("dataset", ("session",))

    def test_unknown_is_in_accept_all(self):
        assert cd.is_accepted("unknown", cd.ACCEPT_ALL)

    def test_but_not_in_a_kind_specific_picker(self):
        """An unconfirmed folder could be either kind, so a picker that
        promises one must not accept it."""
        assert not cd.is_accepted("unknown", ("session",))
        assert not cd.is_accepted("unknown", ("dataset",))


class TestTitlesAndPhrases:
    @pytest.mark.parametrize(
        "accept,expected",
        [
            (("session",), "Select an NDI session directory"),
            (("dataset",), "Select an NDI dataset directory"),
            (cd.ACCEPT_ALL, "Select an NDI session or dataset directory"),
        ],
    )
    def test_default_title(self, accept, expected):
        assert cd.default_title(accept) == expected

    @pytest.mark.parametrize(
        "accept,expected",
        [
            (("session",), "an NDI session"),
            (("dataset",), "an NDI dataset"),
            (cd.ACCEPT_ALL, "an NDI session or dataset"),
        ],
    )
    def test_accepted_kinds_phrase(self, accept, expected):
        assert cd.accepted_kinds_phrase(accept) == expected


class TestMismatchMessage:
    def test_not_an_ndi_folder_at_all(self):
        message = cd.mismatch_message("none", ("session",))
        assert "not an NDI session or dataset directory" in message
        assert "an NDI session" in message

    def test_an_unconfirmed_folder_says_how_to_resolve_it(self):
        """It may well be the right kind. The message must point at the fix,
        not imply the folder is unusable."""
        message = cd.mismatch_message("unknown", ("session",))
        assert "predates object-type markers" in message
        assert "Open it once" in message

    def test_the_other_kind_is_named_precisely(self):
        """A near miss: naming what it actually is saves a second guess."""
        message = cd.mismatch_message("dataset", ("session",))
        assert "is an NDI dataset" in message
        assert "an NDI session is required" in message

    def test_the_three_cases_read_differently(self):
        messages = {cd.mismatch_message(t, ("session",)) for t in ("none", "unknown", "dataset")}
        assert len(messages) == 3


class _Picker:
    """A stand-in for the folder dialog, returning a scripted sequence."""

    def __init__(self, *selections):
        self.selections = list(selections)
        self.starts = []
        self.titles = []

    def __call__(self, start, title, parent):
        self.starts.append(start)
        self.titles.append(title)
        return self.selections.pop(0) if self.selections else ""


class _Explainer:
    def __init__(self):
        self.messages = []

    def __call__(self, message, title, parent):
        self.messages.append(message)


def _types(mapping):
    return lambda path: mapping.get(path, "none")


class TestTheLoop:
    def _run(self, monkeypatch, types, picker, explainer, **kwargs):
        monkeypatch.setattr(cd, "_directory_type", _types(types))
        return cd.choose_dataset_or_session(_pick=picker, _explain=explainer, **kwargs)

    def test_an_accepted_folder_is_returned_first_time(self, monkeypatch):
        picker = _Picker("/a")
        result = self._run(
            monkeypatch, {"/a": "session"}, picker, _Explainer(), accept=("session",)
        )
        assert result == ("/a", "session")

    def test_cancelling_returns_empty(self, monkeypatch):
        result = self._run(monkeypatch, {}, _Picker(""), _Explainer())
        assert result == ("", "")

    def test_a_wrong_kind_is_explained_and_asked_again(self, monkeypatch):
        picker = _Picker("/wrong", "/right")
        explainer = _Explainer()
        result = self._run(
            monkeypatch,
            {"/wrong": "dataset", "/right": "session"},
            picker,
            explainer,
            accept=("session",),
        )
        assert result == ("/right", "session")
        assert len(explainer.messages) == 1
        assert "is an NDI dataset" in explainer.messages[0]

    def test_it_reopens_at_the_folder_just_chosen(self, monkeypatch):
        """Someone who lands one level from the right directory should not
        have to navigate there twice."""
        picker = _Picker("/wrong", "/right")
        self._run(
            monkeypatch,
            {"/wrong": "none", "/right": "session"},
            picker,
            _Explainer(),
            accept=("session",),
            start_path="/start",
        )
        assert picker.starts == ["/start", "/wrong"]

    def test_cancelling_after_a_wrong_choice_still_returns_empty(self, monkeypatch):
        picker = _Picker("/wrong", "")
        result = self._run(
            monkeypatch, {"/wrong": "none"}, picker, _Explainer(), accept=("session",)
        )
        assert result == ("", "")

    def test_an_explicit_title_is_used_and_kept_across_retries(self, monkeypatch):
        picker = _Picker("/wrong", "/right")
        self._run(
            monkeypatch,
            {"/wrong": "none", "/right": "session"},
            picker,
            _Explainer(),
            accept=("session",),
            title="Pick one",
        )
        assert picker.titles == ["Pick one", "Pick one"]

    def test_the_default_title_describes_the_accepted_kinds(self, monkeypatch):
        picker = _Picker("/a")
        self._run(monkeypatch, {"/a": "dataset"}, picker, _Explainer(), accept=("dataset",))
        assert picker.titles == ["Select an NDI dataset directory"]


class TestTheKindSpecificWrappers:
    def test_choose_session_rejects_a_dataset(self, monkeypatch):
        """The guarantee open_session relies on: it cannot be handed a
        dataset by mistake."""
        monkeypatch.setattr(cd, "_directory_type", _types({"/d": "dataset", "/s": "session"}))
        picker = _Picker("/d", "/s")
        explainer = _Explainer()
        assert cd.choose_session(_pick=picker, _explain=explainer) == ("/s", "session")
        assert len(explainer.messages) == 1

    def test_choose_dataset_rejects_a_session(self, monkeypatch):
        monkeypatch.setattr(cd, "_directory_type", _types({"/s": "session", "/d": "dataset"}))
        picker = _Picker("/s", "/d")
        assert cd.choose_dataset(_pick=picker, _explain=_Explainer()) == ("/d", "dataset")

    def test_neither_accepts_an_unconfirmed_folder(self, monkeypatch):
        monkeypatch.setattr(cd, "_directory_type", _types({"/u": "unknown", "/s": "session"}))
        explainer = _Explainer()
        cd.choose_session(_pick=_Picker("/u", "/s"), _explain=explainer)
        assert "predates object-type markers" in explainer.messages[0]


class TestAgainstRealDirectories:
    """The one place the real directorytype is used, so the wiring is proven."""

    def test_an_empty_folder_is_none(self, tmp_path):
        from ndi.session.dir import ndi_session_dir

        assert ndi_session_dir.directorytype(tmp_path) == "none"

    def test_a_plain_folder_is_rejected_by_the_picker(self, tmp_path):
        picker = _Picker(str(tmp_path), "")
        explainer = _Explainer()
        result = cd.choose_session(_pick=picker, _explain=explainer)
        assert result == ("", "")
        assert "not an NDI session or dataset directory" in explainer.messages[0]


if __name__ == "__main__":
    pytest.main([__file__])
