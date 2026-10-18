"""Unit tests for file CRC-32 support (NDI Cloud ndi-cloud-node#162) -- no network.

MATLAB counterpart: ``tests/+ndi/+unittest/FileCrc32OfflineTest.m``
(VH-Lab/NDI-matlab#1025).

* :func:`ndi.fun.file.crc32` gives the cloud's encoding: base64 of the
  4-byte big-endian CRC-32. Expected values are zlib reference values.
* ``getFileUploadURL(..., checksum_crc32=...)`` sends ``checksumCRC32``.
* ``putFiles`` / ``putFileBytes`` send the signed ``x-amz-checksum-crc32``
  header, and refuse a malformed value.
* ``lookupFiles`` posts ``{"uids": [...]}``, de-duplicates, splits at the
  server's 5000-uid limit and merges ``files`` / ``missing``.
* ``getSignedURLSetAll`` concatenates the pages' ``fileInfo``.
* ``uploadSingleFile`` sends the checksum by default.

The live round trip is ``TestFileLifecycle`` in ``tests/test_cloud_live.py``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ndi.cloud.api import files as files_api
from ndi.fun.file import crc32, crc32ToBase64

DATASET = "507f1f77bcf86cd799439011"


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


class TestCrc32Encoding:
    def test_big_endian_base64(self):
        assert crc32ToBase64(0x3610A686) == "NhCmhg=="
        assert crc32ToBase64(0) == "AAAAAA=="
        assert crc32ToBase64(0xFFFFFFFF) == "/////w=="

    @pytest.mark.parametrize("bad", [-1, 2**32, 1.5, True, "NhCmhg=="])
    def test_rejects_values_outside_32_bits(self, bad):
        with pytest.raises(ValueError):
            crc32ToBase64(bad)

    def test_file_crc_of_known_text(self, tmp_path):
        p = tmp_path / "f.bin"
        p.write_bytes(b"hello")
        assert crc32(str(p)) == "NhCmhg=="

    def test_empty_file(self, tmp_path):
        p = tmp_path / "f.bin"
        p.write_bytes(b"")
        assert crc32(str(p)) == "AAAAAA=="

    def test_chunk_size_does_not_matter(self, tmp_path):
        p = tmp_path / "f.bin"
        p.write_bytes(b"The quick brown fox jumps over the lazy dog")
        assert crc32(str(p)) == "QU+jOQ=="
        assert crc32(str(p), chunk_size=1) == "QU+jOQ=="
        assert crc32(str(p), chunk_size=7) == "QU+jOQ=="

    def test_many_chunks_and_high_bytes(self, tmp_path):
        p = tmp_path / "f.bin"
        p.write_bytes(bytes(range(256)) * 1000)
        assert crc32(str(p), chunk_size=4096) == "/HCvGg=="

    def test_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            crc32(str(tmp_path / "nope"))


# ---------------------------------------------------------------------------
# Upload URL and PUT
# ---------------------------------------------------------------------------


class TestChecksummedUpload:
    def test_upload_url_sends_checksum_query(self):
        client = MagicMock()
        client.get.return_value = {"url": "https://s3/x"}

        url = files_api.getFileUploadURL(
            "org1", DATASET, "uid1", checksum_crc32="QU+jOQ==", client=client
        )

        assert url == "https://s3/x"
        assert client.get.call_args.kwargs["params"] == {"checksumCRC32": "QU+jOQ=="}

    def test_upload_url_without_checksum_sends_no_query(self):
        client = MagicMock()
        client.get.return_value = {"url": "https://s3/x"}

        files_api.getFileUploadURL("org1", DATASET, "uid1", client=client)

        assert client.get.call_args.kwargs["params"] is None

    def test_upload_url_refuses_a_malformed_checksum(self):
        with pytest.raises(ValueError):
            files_api.getFileUploadURL(
                "org1", DATASET, "uid1", checksum_crc32="abc", client=MagicMock()
            )

    def test_put_sends_the_checksum_header(self, tmp_path):
        p = tmp_path / "f.bin"
        p.write_bytes(b"hello")
        resp = MagicMock(status_code=200)
        with patch("requests.put", return_value=resp) as put:
            assert files_api.putFiles(
                "https://bucket.s3.amazonaws.com/k", str(p), checksum_crc32="NhCmhg=="
            )
        headers = put.call_args.kwargs["headers"]
        assert headers["x-amz-checksum-crc32"] == "NhCmhg=="
        assert headers["Content-Type"] == "application/octet-stream"

    def test_put_without_checksum_sends_no_header(self, tmp_path):
        p = tmp_path / "f.bin"
        p.write_bytes(b"hello")
        with patch("requests.put", return_value=MagicMock(status_code=200)) as put:
            files_api.putFiles("https://bucket.s3.amazonaws.com/k", str(p))
        assert "x-amz-checksum-crc32" not in put.call_args.kwargs["headers"]

    def test_put_refuses_a_malformed_checksum(self, tmp_path):
        p = tmp_path / "f.bin"
        p.write_bytes(b"hello")
        with patch("requests.put") as put, pytest.raises(ValueError):
            files_api.putFiles(
                "https://bucket.s3.amazonaws.com/k", str(p), checksum_crc32="not a crc"
            )
        put.assert_not_called()

    def test_put_bytes_sends_the_checksum_header(self):
        with patch("requests.put", return_value=MagicMock(status_code=200)) as put:
            files_api.putFileBytes(
                "https://bucket.s3.amazonaws.com/k", b"hello", checksum_crc32="NhCmhg=="
            )
        assert put.call_args.kwargs["headers"]["x-amz-checksum-crc32"] == "NhCmhg=="


# ---------------------------------------------------------------------------
# lookupFiles
# ---------------------------------------------------------------------------


class _LookupServer:
    """A fake POST /files/lookup over an in-memory {uid: record} map."""

    def __init__(self, records):
        self.records = records
        self.calls = []

    def post(self, endpoint, json=None, data=None, **path_params):
        self.calls.append({"endpoint": endpoint, "json": json, "path": path_params})
        uids = json["uids"]
        assert len(uids) <= files_api.LOOKUP_MAX_UIDS, "client must split long lists"
        return {
            "files": [self.records[u] for u in uids if u in self.records],
            "missing": [u for u in uids if u not in self.records],
        }


class TestLookupFiles:
    def test_found_and_missing(self):
        server = _LookupServer(
            {
                "u1": {"uid": "u1", "uploaded": True, "size": 5, "crc32": "NhCmhg=="},
                "u2": {"uid": "u2", "uploaded": False, "size": 0, "crc32": None},
            }
        )

        result = files_api.lookupFiles(DATASET, ["u1", "u2", "u3", "u1"], client=server)

        assert len(server.calls) == 1
        call = server.calls[0]
        assert call["endpoint"] == "/datasets/{datasetId}/files/lookup"
        assert call["path"] == {"datasetId": DATASET}
        assert call["json"] == {"uids": ["u1", "u2", "u3"]}
        assert [f["uid"] for f in result["files"]] == ["u1", "u2"]
        assert result["files"][0]["crc32"] == "NhCmhg=="
        assert result["files"][1]["crc32"] is None
        assert result["missing"] == ["u3"]

    def test_splits_lists_over_the_server_limit(self):
        server = _LookupServer({"u0": {"uid": "u0", "uploaded": True, "size": 1, "crc32": None}})
        uids = [f"u{i}" for i in range(files_api.LOOKUP_MAX_UIDS + 3)]

        result = files_api.lookupFiles(DATASET, uids, client=server)

        assert [len(c["json"]["uids"]) for c in server.calls] == [files_api.LOOKUP_MAX_UIDS, 3]
        assert [f["uid"] for f in result["files"]] == ["u0"]
        assert len(result["missing"]) == len(uids) - 1

    def test_no_uids_makes_no_call(self):
        server = _LookupServer({})
        assert files_api.lookupFiles(DATASET, [], client=server) == {"files": [], "missing": []}
        assert server.calls == []


# ---------------------------------------------------------------------------
# signed-url-set fileInfo
# ---------------------------------------------------------------------------


class TestSignedURLSetFileInfo:
    def test_all_concatenates_file_info_across_pages(self):
        pages = [
            {
                "files": {"4192a3c0dd1b4e00_3fe8a1b2c3d4e5f6": "https://s3/a"},
                "fileInfo": [
                    {
                        "uid": "4192a3c0dd1b4e00_3fe8a1b2c3d4e5f6",
                        "uploaded": True,
                        "size": 5,
                        "crc32": "NhCmhg==",
                    }
                ],
                "nextCursor": "c1",
            },
            {
                "files": {"b": "https://s3/b"},
                "fileInfo": [{"uid": "b", "uploaded": True, "size": 7, "crc32": None}],
            },
        ]
        client = MagicMock()
        client.get.side_effect = pages

        merged = files_api.getSignedURLSetAll(DATASET, "doc1", client=client)

        assert [f["uid"] for f in merged["fileInfo"]] == [
            "4192a3c0dd1b4e00_3fe8a1b2c3d4e5f6",
            "b",
        ]
        assert merged["fileInfo"][0]["crc32"] == "NhCmhg=="

    def test_all_without_file_info_gives_an_empty_list(self):
        client = MagicMock()
        client.get.return_value = {"files": {"a": "https://s3/a"}}
        merged = files_api.getSignedURLSetAll(DATASET, "doc1", client=client)
        assert merged["fileInfo"] == []


# ---------------------------------------------------------------------------
# uploadSingleFile
# ---------------------------------------------------------------------------


class TestUploadSingleFileChecksum:
    def _run(self, tmp_path, **kwargs):
        from ndi.cloud.upload import uploadSingleFile

        p = tmp_path / "f.bin"
        p.write_bytes(b"hello")
        client = MagicMock()
        # The upload URL is asked for in the dataset's own organization,
        # read from the dataset record.
        client.get.return_value = {"organizationId": "org1"}
        with (
            patch.object(files_api, "getFileUploadURL", return_value="https://s3/x") as get_url,
            patch.object(files_api, "putFiles", return_value=True) as put,
        ):
            ok, err = uploadSingleFile(DATASET, "uid1", str(p), client=client, **kwargs)
        assert ok, err
        assert get_url.call_args.args[0] == "org1"
        return get_url, put

    def test_sends_the_checksum_by_default(self, tmp_path):
        get_url, put = self._run(tmp_path)
        assert get_url.call_args.kwargs["checksum_crc32"] == "NhCmhg=="
        assert put.call_args.kwargs["checksum_crc32"] == "NhCmhg=="

    def test_checksum_can_be_turned_off(self, tmp_path):
        get_url, put = self._run(tmp_path, checksum=False)
        assert get_url.call_args.kwargs["checksum_crc32"] == ""
        assert put.call_args.kwargs["checksum_crc32"] == ""
