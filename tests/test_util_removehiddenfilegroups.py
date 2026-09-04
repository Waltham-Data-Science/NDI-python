"""A file group with a hidden member is a bad match, and goes whole.

MATLAB counterpart: ``+ndi/+util/removehiddenfilegroups.m``

A group is one regexp match -- a putative epoch, not a bag of files. So
pruning is all-or-nothing. Keeping the visible remainder of a group that
matched a hidden file leaves an epoch missing the file one of its patterns
matched, which is worse than having no epoch: downstream code gets a
malformed epoch instead of none.

Python used to strip hidden files from each group and keep whatever was
left, so a group that DEPENDED on a shadow file came out looking like a
smaller, valid epoch. ``ndi.util.removehiddenfilegroups`` now applies
MATLAB's rule instead: the group goes whole.

Which LAYER catches the shadow file still differs, and deliberately --
see :class:`TestWhereTheShadowFileIsStopped`, which pins both the reason
and the condition under which it can change.

The case this is all for: macOS AppleDouble shadow files
(``._Epoch6_g0_t0.imec0.ap.bin``) are matched by ``#``-style filematch
patterns and otherwise produce spurious duplicate epochs sharing the
genuine epoch's epoch_id.
"""

from __future__ import annotations

import pytest

from ndi.file.navigator import find_file_groups
from ndi.util import is_hidden_file, removehiddenfilegroups


class TestTheWholeGroupGoes:
    def test_a_group_that_is_only_a_shadow_file_is_dropped(self):
        groups = [["/d/data.bin"], ["/d/._data.bin"]]
        assert removehiddenfilegroups(groups) == [["/d/data.bin"]]

    def test_a_mixed_group_is_dropped_entirely_not_trimmed(self):
        """The regression. Trimming would leave ['/d/real.bin'] -- an epoch
        whose second pattern matched nothing real."""
        groups = [["/d/real.bin", "/d/._shadow.meta"]]
        assert removehiddenfilegroups(groups) == []

    def test_a_clean_group_is_untouched(self):
        groups = [["/d/a.bin", "/d/a.meta"]]
        assert removehiddenfilegroups(groups) == [["/d/a.bin", "/d/a.meta"]]

    def test_order_is_preserved(self):
        groups = [["/d/c.bin"], ["/d/._x.bin"], ["/d/a.bin"], ["/d/b.bin"]]
        assert removehiddenfilegroups(groups) == [["/d/c.bin"], ["/d/a.bin"], ["/d/b.bin"]]

    def test_an_empty_list_is_fine(self):
        assert removehiddenfilegroups([]) == []


class TestWhatCountsAsHidden:
    @pytest.mark.parametrize(
        "path",
        [
            "/d/.DS_Store",
            "/d/._Epoch6_g0_t0.imec0.ap.bin",
            ".hidden",
            "/a/b/c/.x",
        ],
    )
    def test_hidden(self, path):
        assert is_hidden_file(path)

    @pytest.mark.parametrize(
        "path",
        [
            "/d/data.bin",
            "/.hiddendir/data.bin",  # only the basename is tested
            "/d/a.b.c",
            "data",
        ],
    )
    def test_not_hidden(self, path):
        assert not is_hidden_file(path)

    def test_a_dotfile_with_no_stem_is_still_hidden(self):
        """MATLAB makes this point in a comment: splitting '.DS_Store' into
        name and extension gives an empty name, so testing the name alone
        would miss it. Both languages test the whole basename."""
        assert is_hidden_file("/d/.DS_Store")


class TestWhereTheShadowFileIsStopped:
    """Which layer catches it, and why it is not the same layer as MATLAB's.

    MATLAB's findfilegroups emits one group per EPOCH, so a shadow file
    forms its own bad group and removehiddenfilegroups drops that group
    alone. Python's find_file_groups emits one group per DIRECTORY: every
    matching file in a directory lands in a single group. Under that
    grouping a shadow file would join the genuine epoch's group, and the
    all-or-nothing rule would delete the real epoch with it -- strictly
    worse than the bug it fixes.

    So the walk is where hidden files are stopped for now, and
    removehiddenfilegroups is the correctly-shaped guard behind it. Making
    it the primary defense means grouping per epoch first; that is a
    separate change, and this class is where it will be noticed, because
    the last test below starts failing once grouping changes.
    """

    def test_the_walk_keeps_shadow_files_out(self, tmp_path):
        (tmp_path / "Epoch1.bin").write_bytes(b"")
        (tmp_path / "._Epoch1.bin").write_bytes(b"")

        found = {f for group in find_file_groups(str(tmp_path), [".*\\.bin\\>"]) for f in group}
        assert not any("._Epoch1.bin" in f for f in found)

    def test_grouping_is_per_directory_which_is_why(self, tmp_path):
        """The constraint itself, pinned. Two unrelated epochs in one
        directory come back as ONE group -- so a hidden member could not be
        dropped without taking its neighbours. When this starts returning
        two groups, the walk filter can go and removehiddenfilegroups can
        take over."""
        (tmp_path / "Epoch1.bin").write_bytes(b"")
        (tmp_path / "Epoch2.bin").write_bytes(b"")

        groups = find_file_groups(str(tmp_path), [".*\\.bin\\>"])
        assert len(groups) == 1, "grouping is per directory; see the class docstring"
        assert len(groups[0]) == 2

    @staticmethod
    def _navigator_over(directory):
        """A navigator rooted at DIRECTORY, matching any .bin."""
        from ndi.file.navigator import ndi_file_navigator

        nav = ndi_file_navigator(None, [".*\\.bin\\>"])
        nav._fileparameters = {"filematch": [".*\\.bin\\>"]}
        nav.path = lambda: str(directory)  # the session is what normally supplies this
        return nav

    def test_the_navigator_returns_no_epoch_for_a_shadow_only_directory(self, tmp_path):
        """End to end through selectfilegroups_disk: a directory holding only
        an AppleDouble file yields no epochs, not one malformed one."""
        (tmp_path / "._Epoch1.bin").write_bytes(b"")

        assert self._navigator_over(tmp_path).selectfilegroups_disk() == []

    def test_the_navigator_still_finds_a_genuine_epoch(self, tmp_path):
        """The guard must not eat real data: a clean directory is unaffected."""
        (tmp_path / "Epoch1.bin").write_bytes(b"")

        groups = self._navigator_over(tmp_path).selectfilegroups_disk()
        assert len(groups) == 1
        assert groups[0][0].endswith("Epoch1.bin")

    def test_a_genuine_epoch_beside_its_shadow_survives(self, tmp_path):
        """The real AppleDouble case: both files present. The shadow's own
        group goes; the genuine epoch stays."""
        (tmp_path / "Epoch1.bin").write_bytes(b"")
        (tmp_path / "._Epoch1.bin").write_bytes(b"")

        groups = self._navigator_over(tmp_path).selectfilegroups_disk()
        found = {f for group in groups for f in group}
        assert any(f.endswith("/Epoch1.bin") for f in found)
        assert not any("._Epoch1.bin" in f for f in found)

    def test_hidden_directories_are_still_skipped(self, tmp_path):
        """Skipping a hidden DIRECTORY is about where to look, not about
        pruning a match, and stays as it was."""
        hidden_dir = tmp_path / ".Trash"
        hidden_dir.mkdir()
        (hidden_dir / "Epoch9.bin").write_bytes(b"")
        (tmp_path / "Epoch1.bin").write_bytes(b"")

        groups = find_file_groups(str(tmp_path), [".*\\.bin\\>"])
        found = {f for group in groups for f in group}
        assert not any(".Trash" in f for f in found)


if __name__ == "__main__":
    pytest.main([__file__])
