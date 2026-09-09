"""Tests for ndi.fun.file.elementDirectory.

MATLAB counterpart: +ndi/+fun/+file/elementDirectory.m

The point of this function is that NDI once wrote per-element folders with a
'|' in the name and now writes '-'. If it returned only the new name, an
export beside an old folder would leave two folders holding the same probe
and no indication which a sorter had read; if it always preferred the old
one, Windows could not write at all. So both the preference and the fallback
are pinned here.
"""

from __future__ import annotations

import sys

import pytest

from ndi.fun.file import elementDirectory, elementDirectoryName

# The legacy fallback is what the port carries the ``|`` name for at all; the
# tests that exercise it must create a folder called ``ctx_|_1`` first.
# Windows forbids ``|`` in a filename outright (WinError 123), so those
# tests cannot even set themselves up there. Skip them on Windows and let
# the same fixture stand up the folder on POSIX. Mirrors NDI-matlab's
# ``ElementDirectoryTest``, which skips the same case with ``assumeFalse(ispc())``.
_SKIP_ON_WINDOWS = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows filesystems forbid '|' in filenames; legacy folder is unreachable",
)


class FakeProbe:
    def elementstring(self):
        return "ctx | 1"


def test_the_new_name_is_used_when_nothing_exists_yet(tmp_path):
    path, name, is_legacy = elementDirectory(tmp_path, FakeProbe())
    assert name == "ctx_-_1"
    assert path == str(tmp_path / "ctx_-_1")
    assert is_legacy is False


@_SKIP_ON_WINDOWS
def test_an_existing_legacy_folder_is_used_instead(tmp_path):
    (tmp_path / "ctx_|_1").mkdir()
    path, name, is_legacy = elementDirectory(tmp_path, FakeProbe())
    assert name == "ctx_|_1"
    assert path == str(tmp_path / "ctx_|_1")
    assert is_legacy is True


@_SKIP_ON_WINDOWS
def test_the_new_folder_wins_when_both_exist(tmp_path):
    """Both present means the data has already been migrated; reading the
    old one would return whatever was left behind."""
    (tmp_path / "ctx_|_1").mkdir()
    (tmp_path / "ctx_-_1").mkdir()
    _path, name, is_legacy = elementDirectory(tmp_path, FakeProbe())
    assert name == "ctx_-_1"
    assert is_legacy is False


def test_an_element_string_is_accepted_in_place_of_an_object(tmp_path):
    _path, name, _ = elementDirectory(tmp_path, "ctx | 1")
    assert name == "ctx_-_1"


def test_a_name_needing_no_rewrite_has_no_legacy_form(tmp_path):
    """When the two names coincide there is nothing to fall back to, and the
    lookup must not go hunting for a folder that cannot exist."""
    assert elementDirectoryName("ctx_1") == ("ctx_1", "ctx_1")
    _path, name, is_legacy = elementDirectory(tmp_path, "ctx_1")
    assert (name, is_legacy) == ("ctx_1", False)
