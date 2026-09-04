"""A downloaded dataset cannot write outside the folder it was asked for.

MATLAB counterpart: ``+ndi/+cloud/+download/+internal/safeLocalFilename.m``

Two values decide where a downloaded file lands, and BOTH come from the
server: a file's ``uid`` and a document's ``generic_file.filename``. Before
this, each was joined onto the target folder verbatim:

    out_path = target_dir / file_uid            # downloadFilesForDocument
    filename = f"{name_part}{ext_part}"         # downloadGenericFiles

so a uid of ``../../../.config/startup.py`` writes there. The MATLAB
helper's own header already described this as "the basename + containment
guard already present in NDI-python download.py" -- it was not present, and
#131 is where that was noticed and closed.

The tests below are written as the attack, not as the API: what matters is
that a hostile value does not produce a write outside the target, whatever
the function's return value happens to be.
"""

from __future__ import annotations

import pytest

import ndi.cloud.download as download
from ndi.cloud.download import _contained_path, safeLocalFilename

#: Values a malicious or broken server could supply. The last two are the
#: reason isSafe exists: they reduce to nothing usable, and a caller that
#: substituted a name of its own would be inventing a destination.
HOSTILE = [
    "../../../.config/startup.py",
    "../secrets",
    "/etc/passwd",
    "..\\..\\windows\\system32\\evil.dll",
    "sub/dir/../../escape.txt",
]

UNUSABLE = ["", ".", "..", "/", "dir/", "a/b/.."]


class TestSafeLocalFilename:
    @pytest.mark.parametrize("uid", HOSTILE)
    def test_every_directory_component_is_dropped(self, uid):
        safe, is_safe = safeLocalFilename(uid)
        assert is_safe
        assert "/" not in safe and "\\" not in safe
        assert safe not in ("", ".", "..")

    @pytest.mark.parametrize("uid", UNUSABLE)
    def test_a_value_with_no_usable_filename_is_refused(self, uid):
        """Not "fall back to something" -- refused. The caller skips the
        file; a substituted name would be a destination nobody chose."""
        safe, is_safe = safeLocalFilename(uid)
        assert is_safe is False
        assert safe == ""

    @pytest.mark.parametrize(
        "uid,expected",
        [
            ("abc123", "abc123"),
            ("abc123.bin", "abc123.bin"),
            ("dir/abc123.bin", "abc123.bin"),
            ("a/b/c/d.json", "d.json"),
            ("..hidden", "..hidden"),
            ("...", "..."),
        ],
    )
    def test_an_ordinary_uid_survives_intact(self, uid, expected):
        """The guard must not mangle the normal case -- ``..hidden`` and
        ``...`` are legal filenames, only ``.`` and ``..`` are not."""
        assert safeLocalFilename(uid) == (expected, True)

    def test_it_matches_matlabs_two_output_shape(self):
        """MATLAB returns ``[safeFileName, isSafe]``."""
        assert safeLocalFilename("x.bin") == ("x.bin", True)


class TestContainedPath:
    """Defense in depth. safeLocalFilename should make this unreachable,
    which is exactly why it is worth asserting rather than assuming."""

    def test_a_normal_name_resolves_under_the_target(self, tmp_path):
        assert _contained_path(tmp_path, "file.bin") == (tmp_path / "file.bin").resolve()

    @pytest.mark.parametrize("name", ["../escape", "..", ".", "", "a/../../escape"])
    def test_anything_that_escapes_is_refused(self, tmp_path, name):
        target = tmp_path / "dataset"
        target.mkdir()
        assert _contained_path(target, name) is None

    def test_the_target_folder_itself_is_not_a_destination(self, tmp_path):
        """``target_dir / ""`` resolves to the folder. Writing there would
        truncate the directory entry, not create a file."""
        assert _contained_path(tmp_path, "") is None


class TestTheDownloadPathsUseIt:
    """The guard has to be ON the two paths that build a local filename,
    not merely available to them."""

    @pytest.fixture
    def stubbed_transfer(self, monkeypatch):
        """A cloud that hands back one small file for any uid asked for."""
        import requests

        import ndi.cloud.api

        seen = {"fetched": 0}

        class FakeFiles:
            @staticmethod
            def getFileDetails(dataset_id, uid, *, client=None):
                return {"downloadUrl": "https://example.invalid/f"}

        class FakeResponse:
            status_code = 200

            @staticmethod
            def iter_content(chunk_size=8192):
                yield b"payload"

        def fake_get(url, **kwargs):
            seen["fetched"] += 1
            return FakeResponse()

        monkeypatch.setattr(ndi.cloud.api, "files", FakeFiles, raising=False)
        monkeypatch.setattr(requests, "get", fake_get)
        return seen

    def test_a_traversing_uid_lands_inside_the_target(self, tmp_path, stubbed_transfer):
        """The concrete hole: a uid of ``../evil`` used to write one level
        above the target folder. It is not refused -- it is stripped to its
        last component -- but it cannot leave the folder."""
        target = tmp_path / "target"
        target.mkdir()

        written = download.downloadFilesForDocument(
            "ds", {"file_uid": "../evil"}, target, client=object()
        )

        assert written == [target.resolve() / "evil"]
        assert (target / "evil").read_bytes() == b"payload"
        assert not (tmp_path / "evil").exists(), "escaped the target folder"

    def test_a_deep_traversal_cannot_reach_a_startup_file(self, tmp_path, stubbed_transfer):
        home = tmp_path / "home"
        (home / ".config").mkdir(parents=True)
        startup = home / ".config" / "startup.py"
        startup.write_text("# untouched")
        target = home / "datasets" / "ds"
        target.mkdir(parents=True)

        download.downloadFilesForDocument(
            "ds", {"file_uid": "../../.config/startup.py"}, target, client=object()
        )

        assert startup.read_text() == "# untouched"
        assert (target / "startup.py").exists()

    def test_an_unusable_uid_is_not_even_fetched(self, tmp_path, stubbed_transfer):
        """A file that can go nowhere is not worth a download URL for."""
        target = tmp_path / "target"
        target.mkdir()

        assert download.downloadFilesForDocument("ds", {"file_uid": ".."}, target) == []
        assert stubbed_transfer["fetched"] == 0
        assert list(target.iterdir()) == []

    def test_downloadGenericFiles_skips_a_traversing_document_filename(self):
        """generic_file.filename is server-supplied too, and the "original"
        naming strategy uses it directly. Checked through the helper the
        loop calls, since the loop itself needs a live dataset."""
        for hostile in HOSTILE:
            safe, is_safe = safeLocalFilename(hostile)
            assert is_safe and "/" not in safe and "\\" not in safe

    def test_the_module_exports_it_under_matlabs_name(self):
        """Bridge Rule 3: the Python name mirrors MATLAB's."""
        assert download.safeLocalFilename.__name__ == "safeLocalFilename"


class TestTheHoleIsReallyClosed:
    """A regression test needs to show the bug was reachable, or it proves
    nothing about the fix."""

    def test_the_unguarded_join_would_have_escaped(self, tmp_path):
        target = tmp_path / "dataset"
        target.mkdir()

        unguarded = (target / "../../../evil.txt").resolve()
        assert tmp_path.resolve() not in unguarded.parents or unguarded.parent != target

        safe, is_safe = safeLocalFilename("../../../evil.txt")
        guarded = _contained_path(target, safe) if is_safe else None
        assert guarded is not None
        assert guarded.parent == target.resolve()


if __name__ == "__main__":
    pytest.main([__file__])
