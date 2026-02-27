"""
Tests for ndi.cloud.filehandler — ndic:// protocol and on-demand file fetching.

Unit tests (offline): parse_ndic_uri, rewrite_file_info_for_cloud,
_try_cloud_fetch with mocks.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# parse_ndic_uri
# ---------------------------------------------------------------------------


class TestParseNdicUri:
    """Tests for parse_ndic_uri."""

    def test_valid_uri(self):
        from ndi.cloud.filehandler import parse_ndic_uri

        ds_id, file_uid = parse_ndic_uri("ndic://abc123/file456")
        assert ds_id == "abc123"
        assert file_uid == "file456"

    def test_valid_uri_with_long_ids(self):
        from ndi.cloud.filehandler import parse_ndic_uri

        ds_id, file_uid = parse_ndic_uri("ndic://668b0539f13096e04f1feccd/9a1b2c3d4e5f")
        assert ds_id == "668b0539f13096e04f1feccd"
        assert file_uid == "9a1b2c3d4e5f"

    def test_not_ndic_scheme(self):
        from ndi.cloud.filehandler import parse_ndic_uri

        with pytest.raises(ValueError, match="Not an ndic://"):
            parse_ndic_uri("https://example.com/file")

    def test_empty_string(self):
        from ndi.cloud.filehandler import parse_ndic_uri

        with pytest.raises(ValueError, match="Not an ndic://"):
            parse_ndic_uri("")

    def test_missing_file_uid(self):
        from ndi.cloud.filehandler import parse_ndic_uri

        with pytest.raises(ValueError, match="Invalid ndic://"):
            parse_ndic_uri("ndic://abc123/")

    def test_missing_dataset_id(self):
        from ndi.cloud.filehandler import parse_ndic_uri

        with pytest.raises(ValueError, match="Invalid ndic://"):
            parse_ndic_uri("ndic:///file456")

    def test_no_slash(self):
        from ndi.cloud.filehandler import parse_ndic_uri

        with pytest.raises(ValueError, match="Invalid ndic://"):
            parse_ndic_uri("ndic://abc123")


# ---------------------------------------------------------------------------
# rewrite_file_info_for_cloud
# ---------------------------------------------------------------------------


class TestRewriteFileInfoForCloud:
    """Tests for rewrite_file_info_for_cloud."""

    def test_list_style_file_info(self):
        """Standard list-style file_info and locations."""
        from ndi.cloud.filehandler import rewrite_file_info_for_cloud

        doc = {
            "files": {
                "file_info": [
                    {
                        "name": "data.bin",
                        "locations": [
                            {
                                "uid": "uid_001",
                                "location": "https://s3.amazonaws.com/bucket/uid_001",
                                "location_type": "url",
                                "ingest": 1,
                                "delete_original": 0,
                            }
                        ],
                    }
                ]
            }
        }

        rewrite_file_info_for_cloud(doc, "ds_abc")

        loc = doc["files"]["file_info"][0]["locations"][0]
        assert loc["location"] == "ndic://ds_abc/uid_001"
        assert loc["location_type"] == "ndicloud"
        assert loc["ingest"] == 0
        assert loc["delete_original"] == 0

    def test_dict_style_file_info(self):
        """MATLAB struct-style: file_info is a dict, locations is a dict."""
        from ndi.cloud.filehandler import rewrite_file_info_for_cloud

        doc = {
            "files": {
                "file_info": {
                    "name": "data.bin",
                    "locations": {
                        "uid": "uid_002",
                        "location": "https://s3.amazonaws.com/bucket/uid_002",
                        "location_type": "url",
                        "ingest": 1,
                        "delete_original": 1,
                    },
                }
            }
        }

        rewrite_file_info_for_cloud(doc, "ds_xyz")

        # Should still be a dict (structure preserved)
        fi = doc["files"]["file_info"]
        assert isinstance(fi, dict)
        loc = fi["locations"]
        assert isinstance(loc, dict)
        assert loc["location"] == "ndic://ds_xyz/uid_002"
        assert loc["location_type"] == "ndicloud"
        assert loc["ingest"] == 0
        assert loc["delete_original"] == 0

    def test_multiple_locations(self):
        """Multiple locations per file_info entry."""
        from ndi.cloud.filehandler import rewrite_file_info_for_cloud

        doc = {
            "files": {
                "file_info": [
                    {
                        "name": "data.bin",
                        "locations": [
                            {"uid": "uid_a", "location": "/old/path/a", "location_type": "file"},
                            {"uid": "uid_b", "location": "/old/path/b", "location_type": "file"},
                        ],
                    }
                ]
            }
        }

        rewrite_file_info_for_cloud(doc, "ds_multi")

        locs = doc["files"]["file_info"][0]["locations"]
        assert locs[0]["location"] == "ndic://ds_multi/uid_a"
        assert locs[1]["location"] == "ndic://ds_multi/uid_b"

    def test_no_files_key(self):
        """Documents without files are not modified."""
        from ndi.cloud.filehandler import rewrite_file_info_for_cloud

        doc = {"base": {"id": "test"}}
        rewrite_file_info_for_cloud(doc, "ds_abc")
        assert "files" not in doc

    def test_empty_file_info(self):
        """Documents with empty file_info are not modified."""
        from ndi.cloud.filehandler import rewrite_file_info_for_cloud

        doc = {"files": {"file_info": []}}
        rewrite_file_info_for_cloud(doc, "ds_abc")
        assert doc["files"]["file_info"] == []

    def test_no_uid_skipped(self):
        """Locations without uid are skipped."""
        from ndi.cloud.filehandler import rewrite_file_info_for_cloud

        doc = {
            "files": {
                "file_info": [
                    {
                        "name": "data.bin",
                        "locations": [
                            {"location": "/old/path", "location_type": "file"},
                        ],
                    }
                ]
            }
        }

        rewrite_file_info_for_cloud(doc, "ds_abc")
        # location unchanged since no uid
        assert doc["files"]["file_info"][0]["locations"][0]["location"] == "/old/path"


# ---------------------------------------------------------------------------
# fetch_cloud_file
# ---------------------------------------------------------------------------


class TestFetchCloudFile:
    """Tests for fetch_cloud_file with mocked API calls."""

    def test_fetch_success(self, tmp_path):
        from ndi.cloud.filehandler import fetch_cloud_file

        target = tmp_path / "downloaded_file.bin"
        mock_client = MagicMock()

        with (
            patch("ndi.cloud.api.files.get_file_details") as mock_details,
            patch("ndi.cloud.api.files.get_file") as mock_get_file,
        ):
            mock_details.return_value = {"downloadUrl": "https://s3.example.com/file"}

            # Simulate successful download: create .tmp then get_file returns True
            def fake_get_file(url, path, timeout=300):
                Path(path).write_bytes(b"fake binary data")
                return True

            mock_get_file.side_effect = fake_get_file

            result = fetch_cloud_file("ndic://ds123/uid456", target, client=mock_client)

        assert result is True
        assert target.exists()
        assert target.read_bytes() == b"fake binary data"
        mock_details.assert_called_once_with(mock_client, "ds123", "uid456")

    def test_fetch_no_download_url(self, tmp_path):
        from ndi.cloud.exceptions import CloudError
        from ndi.cloud.filehandler import fetch_cloud_file

        target = tmp_path / "file.bin"
        mock_client = MagicMock()

        with patch("ndi.cloud.api.files.get_file_details") as mock_details:
            mock_details.return_value = {}

            with pytest.raises(CloudError, match="No downloadUrl"):
                fetch_cloud_file("ndic://ds123/uid456", target, client=mock_client)

    def test_fetch_invalid_uri(self, tmp_path):
        from ndi.cloud.filehandler import fetch_cloud_file

        with pytest.raises(ValueError, match="Not an ndic://"):
            fetch_cloud_file("https://example.com/file", tmp_path / "out.bin")

    def test_fetch_fallback_to_env_client(self, tmp_path):
        from ndi.cloud.filehandler import fetch_cloud_file

        target = tmp_path / "file.bin"

        with (
            patch("ndi.cloud.filehandler.get_or_create_cloud_client") as mock_auto,
            patch("ndi.cloud.api.files.get_file_details") as mock_details,
            patch("ndi.cloud.api.files.get_file") as mock_get_file,
        ):
            mock_auto.return_value = MagicMock()
            mock_details.return_value = {"downloadUrl": "https://s3.example.com/f"}

            def fake_get_file(url, path, timeout=300):
                Path(path).write_bytes(b"data")
                return True

            mock_get_file.side_effect = fake_get_file

            result = fetch_cloud_file("ndic://ds/uid", target, client=None)

        assert result is True
        mock_auto.assert_called_once()


# ---------------------------------------------------------------------------
# get_or_create_cloud_client
# ---------------------------------------------------------------------------


class TestGetOrCreateCloudClient:
    """Tests for get_or_create_cloud_client."""

    def test_missing_env_vars(self):
        from ndi.cloud.exceptions import CloudAuthError
        from ndi.cloud.filehandler import get_or_create_cloud_client

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(CloudAuthError, match="NDI_CLOUD_USERNAME"):
                get_or_create_cloud_client()

    def test_env_vars_present(self):
        from ndi.cloud.filehandler import get_or_create_cloud_client

        mock_client = MagicMock()

        with patch(
            "ndi.cloud.client.CloudClient.from_env", return_value=mock_client
        ) as mock_from_env:
            result = get_or_create_cloud_client()

        mock_from_env.assert_called_once()
        assert result is mock_client


# ---------------------------------------------------------------------------
# _try_cloud_fetch (session integration)
# ---------------------------------------------------------------------------


class TestTryCloudFetch:
    """Tests for Session._try_cloud_fetch with mocked cloud calls."""

    def _make_session_with_doc(self, tmp_path, file_info):
        """Create a DirSession with a document containing given file_info."""
        from ndi.session.dir import DirSession

        session_dir = tmp_path / "session"
        session_dir.mkdir()
        session = DirSession("test_session", session_dir)

        # Create and add a document with file_info
        from ndi.document import Document

        doc = Document("base")
        doc = doc.set_session_id(session.id())

        # Inject file_info into the document properties
        props = doc.document_properties
        props["files"] = {"file_info": file_info}

        session.database_add(doc)
        return session, doc

    def test_try_cloud_fetch_with_ndic_uri(self, tmp_path):
        """_try_cloud_fetch returns True when ndic:// location is found and fetch succeeds."""
        file_info = [
            {
                "name": "recording.dat",
                "locations": [
                    {
                        "uid": "uid_test",
                        "location": "ndic://ds_test/uid_test",
                        "location_type": "ndicloud",
                        "ingest": 0,
                        "delete_original": 0,
                    }
                ],
            }
        ]

        session, doc = self._make_session_with_doc(tmp_path, file_info)

        with patch("ndi.cloud.filehandler.fetch_cloud_file") as mock_fetch:
            mock_fetch.return_value = True
            target = tmp_path / "target.bin"
            result = session._try_cloud_fetch(doc, "recording.dat", target)

        assert result is True
        mock_fetch.assert_called_once()

    def test_try_cloud_fetch_no_ndic_uri(self, tmp_path):
        """_try_cloud_fetch returns False when no ndic:// location matches."""
        file_info = [
            {
                "name": "recording.dat",
                "locations": [
                    {
                        "uid": "uid_test",
                        "location": "/local/path/recording.dat",
                        "location_type": "file",
                    }
                ],
            }
        ]

        session, doc = self._make_session_with_doc(tmp_path, file_info)
        target = tmp_path / "target.bin"
        result = session._try_cloud_fetch(doc, "recording.dat", target)

        assert result is False

    def test_try_cloud_fetch_wrong_filename(self, tmp_path):
        """_try_cloud_fetch returns False when filename doesn't match."""
        file_info = [
            {
                "name": "other_file.dat",
                "locations": [
                    {
                        "uid": "uid_test",
                        "location": "ndic://ds_test/uid_test",
                        "location_type": "ndicloud",
                    }
                ],
            }
        ]

        session, doc = self._make_session_with_doc(tmp_path, file_info)
        target = tmp_path / "target.bin"
        result = session._try_cloud_fetch(doc, "recording.dat", target)

        assert result is False

    def test_try_cloud_fetch_no_file_info(self, tmp_path):
        """_try_cloud_fetch returns False for documents without file_info."""
        session, doc = self._make_session_with_doc(tmp_path, [])
        target = tmp_path / "target.bin"
        result = session._try_cloud_fetch(doc, "recording.dat", target)

        assert result is False


# ---------------------------------------------------------------------------
# Rewrite test with real carbon fiber documents
# ---------------------------------------------------------------------------

CARBON_FIBER_DOCS = Path(
    os.path.expanduser("~/Documents/ndi-projects/datasets/carbon-fiber/documents")
)


@pytest.mark.skipif(
    not CARBON_FIBER_DOCS.exists(),
    reason="Carbon fiber dataset not available locally",
)
class TestRewriteWithRealDocs:
    """Test rewrite_file_info_for_cloud on actual carbon fiber dataset documents."""

    def test_rewrite_preserves_structure(self):
        """Load real carbon fiber docs, rewrite, verify ndic:// URIs."""
        import json as json_mod

        from ndi.cloud.filehandler import NDIC_SCHEME, rewrite_file_info_for_cloud

        json_files = sorted(CARBON_FIBER_DOCS.glob("*.json"))
        assert len(json_files) > 0

        rewritten_count = 0
        for jf in json_files:
            with open(jf) as fh:
                doc = json_mod.load(fh)

            rewrite_file_info_for_cloud(doc, "668b0539f13096e04f1feccd")

            files = doc.get("files", {})
            if not isinstance(files, dict):
                continue
            file_info = files.get("file_info")
            if file_info is None:
                continue

            fi_list = [file_info] if isinstance(file_info, dict) else file_info
            for fi in fi_list:
                locs = fi.get("locations")
                if locs is None:
                    continue
                loc_list = [locs] if isinstance(locs, dict) else locs
                for loc in loc_list:
                    if loc.get("uid"):
                        assert loc["location"].startswith(NDIC_SCHEME)
                        assert loc["location_type"] == "ndicloud"
                        assert loc["ingest"] == 0
                        assert loc["delete_original"] == 0
                        rewritten_count += 1

        # Carbon fiber has 66 docs with files
        assert rewritten_count >= 60, f"Expected >=60 rewritten locations, got {rewritten_count}"

    def test_load_dataset_with_cloud_id(self, tmp_path):
        """load_dataset_from_json_dir with cloud_dataset_id rewrites file_info."""
        from ndi.cloud.filehandler import NDIC_SCHEME
        from ndi.cloud.orchestration import load_dataset_from_json_dir

        dataset = load_dataset_from_json_dir(
            CARBON_FIBER_DOCS,
            target_folder=tmp_path / "cf_ds",
            verbose=False,
            cloud_dataset_id="668b0539f13096e04f1feccd",
        )

        # Find documents with file_info and verify ndic:// URIs
        from ndi.query import Query

        all_docs = dataset.database_search(Query("").isa("base"))
        ndic_count = 0
        for doc in all_docs:
            props = doc.document_properties
            files = props.get("files", {})
            if not isinstance(files, dict):
                continue
            fi = files.get("file_info")
            if fi is None:
                continue
            fi_list = [fi] if isinstance(fi, dict) else fi
            for entry in fi_list:
                locs = entry.get("locations")
                if locs is None:
                    continue
                loc_list = [locs] if isinstance(locs, dict) else locs
                for loc in loc_list:
                    if loc.get("location", "").startswith(NDIC_SCHEME):
                        ndic_count += 1

        assert ndic_count >= 60
