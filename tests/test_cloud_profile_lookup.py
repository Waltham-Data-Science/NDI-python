"""ndi.cloud.profile: lookup by UID / Nickname / Email.

Verifies that after issue #168 the profile lookup accepts a UID, an exact
Nickname, or a case-insensitive Email, and rejects ambiguous or unknown
keys with a helpful message. Every module-level function that resolved
a UID before (get, remove, set_current, set_default, get_password,
set_password, get_stage, set_stage, switch_profile) now goes through
the widened lookup, so a test on the shared helper covers all of them.
"""

from __future__ import annotations

import os

import pytest

from ndi.cloud import profile


@pytest.fixture(autouse=True)
def _isolated_profile_store(tmp_path, monkeypatch):
    """Redirect the singleton to a scratch prefdir and use the memory backend."""
    monkeypatch.setenv("NDI_PREFDIR", str(tmp_path))
    profile.reload()
    profile.use_backend("memory")
    profile.reset()
    yield
    profile.reset()


def _add_lab_and_dev():
    lab = profile.add("lab-primary", "me@lab.org", "pw-lab")
    dev = profile.add("dev-account", "dev@lab.org", "pw-dev")
    return lab, dev


def test_lookup_by_uid_still_works():
    lab, _ = _add_lab_and_dev()
    assert profile.get(lab).Nickname == "lab-primary"


def test_lookup_by_nickname():
    lab, _ = _add_lab_and_dev()
    assert profile.get("lab-primary").UID == lab


def test_lookup_by_email_is_case_insensitive():
    lab, _ = _add_lab_and_dev()
    assert profile.get("ME@LAB.ORG").UID == lab


def test_ambiguous_nickname_raises_and_names_candidates():
    a = profile.add("shared-nickname", "a@lab.org", "pw-a")
    b = profile.add("shared-nickname", "b@lab.org", "pw-b")
    with pytest.raises(KeyError) as info:
        profile.get("shared-nickname")
    msg = str(info.value)
    assert a in msg and b in msg


def test_unknown_key_raises_with_key_echoed():
    _add_lab_and_dev()
    with pytest.raises(KeyError) as info:
        profile.get("does-not-exist")
    assert "does-not-exist" in str(info.value)


def test_set_current_stores_the_resolved_uid_not_the_key():
    lab, _ = _add_lab_and_dev()
    profile.set_current("lab-primary")
    current = profile.get_current()
    assert current is not None
    assert current.UID == lab


def test_set_default_stores_the_resolved_uid_not_the_key():
    lab, _ = _add_lab_and_dev()
    profile.set_default("me@lab.org")
    default = profile.get_default()
    assert default is not None
    assert default.UID == lab


def test_remove_by_nickname_clears_current_and_default_if_matched():
    lab, _ = _add_lab_and_dev()
    profile.set_current(lab)
    profile.set_default(lab)
    profile.remove("lab-primary")
    assert profile.get_current() is None
    assert profile.get_default() is None


def test_switch_profile_by_nickname_sets_env_from_the_saved_profile():
    _add_lab_and_dev()
    for var in ("CLOUD_API_ENVIRONMENT", "NDI_CLOUD_USERNAME", "NDI_CLOUD_PASSWORD"):
        os.environ.pop(var, None)
    profile.switch_profile("lab-primary")
    assert os.environ["NDI_CLOUD_USERNAME"] == "me@lab.org"
    assert os.environ["NDI_CLOUD_PASSWORD"] == "pw-lab"
    assert os.environ["CLOUD_API_ENVIRONMENT"] == "prod"
    current = profile.get_current()
    assert current is not None
    assert current.Nickname == "lab-primary"
