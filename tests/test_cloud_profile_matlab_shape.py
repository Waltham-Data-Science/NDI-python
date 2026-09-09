"""Reading a profiles file that NDI-matlab wrote.

The two languages deliberately share ~/.ndi/NDI_Cloud_Profiles.json, so
what MATLAB's jsonencode produces is what this reader has to accept. It
produces a different SHAPE depending on how many profiles there are: a
1x1 struct becomes a JSON object, a 1xN struct array becomes a JSON
array. MATLAB's own reader has normalizeProfiles for that; these tests
pin the Python counterpart.

The single-profile case is the one that matters most, because it is
what every new user has after making their first.
"""

from __future__ import annotations

import json

from ndi.cloud import profile
from ndi.cloud.profile import _as_profile_list, _ProfileSingleton

ONE = {
    "UID": "abc123",
    "Nickname": "steve",
    "Email": "steve@walthamdatascience.com",
    "Stage": "prod",
    "PasswordSecret": "NDI Cloud abc123",
}


def _write(tmp_path, profiles_value, default_uid="abc123"):
    f = tmp_path / "NDI_Cloud_Profiles.json"
    f.write_text(json.dumps({"Profiles": profiles_value, "DefaultUID": default_uid}))
    return f


def _load(tmp_path, monkeypatch):
    monkeypatch.setenv("NDI_PREFDIR", str(tmp_path))
    obj = _ProfileSingleton(backend="memory")
    obj._load_from_disk()
    obj._adopt_default_as_current()
    return obj


def test_a_single_profile_written_as_an_object_is_read(tmp_path, monkeypatch):
    """MATLAB writes one profile as {...}, not [{...}]. Iterating that as
    a list yields its keys, and every key was skipped as 'not a dict' --
    so the file was found, parsed, and silently read as empty."""
    _write(tmp_path, ONE)
    obj = _load(tmp_path, monkeypatch)
    assert [p.Nickname for p in obj.profiles] == ["steve"]
    assert obj.default_uid == "abc123"
    assert obj.current_uid == "abc123", "a valid default must become current"


def test_several_profiles_written_as_an_array_are_read(tmp_path, monkeypatch):
    two = [ONE, {**ONE, "UID": "def456", "Nickname": "other"}]
    _write(tmp_path, two)
    obj = _load(tmp_path, monkeypatch)
    assert [p.Nickname for p in obj.profiles] == ["steve", "other"]


def test_a_missing_or_odd_profiles_field_reads_as_none(tmp_path, monkeypatch):
    """Absent, null and a scalar all mean 'no profiles here' -- none of
    them should raise, and none should invent one."""
    for value in (None, [], "not profiles", 7):
        _write(tmp_path, value)
        obj = _load(tmp_path, monkeypatch)
        assert obj.profiles == []


def test_the_password_secret_is_filled_in_when_matlab_omitted_it(tmp_path, monkeypatch):
    """MATLAB derives it from the UID when absent; so must this, or the
    secret would be looked up under an empty name."""
    raw = dict(ONE)
    del raw["PasswordSecret"]
    _write(tmp_path, raw)
    obj = _load(tmp_path, monkeypatch)
    assert [p.PasswordSecret for p in obj.profiles] == ["NDI Cloud abc123"]


def test_the_normaliser_takes_both_shapes_and_refuses_the_rest():
    assert _as_profile_list({"UID": "x"}) == [{"UID": "x"}]
    assert _as_profile_list([{"UID": "x"}]) == [{"UID": "x"}]
    assert _as_profile_list(None) == []
    assert _as_profile_list("nope") == []


def test_the_public_api_sees_it_too(tmp_path, monkeypatch):
    monkeypatch.setenv("NDI_PREFDIR", str(tmp_path))
    monkeypatch.setattr(profile, "_singleton", None)
    _write(tmp_path, ONE)
    assert [p.Nickname for p in profile.list_profiles()] == ["steve"]
    assert profile.get_default() is not None
