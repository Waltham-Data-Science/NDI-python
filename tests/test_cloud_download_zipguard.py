"""Zip-bomb safety guards for ndi.cloud.download._download_chunk_zip.

The bulk-download path reads a presigned ZIP fully into memory and extracts
every ``*.json`` entry. A malicious or corrupt archive could declare an
enormous uncompressed size or a huge entry count and exhaust memory during
extraction. ``_download_chunk_zip`` now enforces a total-uncompressed-bytes
cap and an entry-count cap (both overridable via env vars) BEFORE extracting
any entry, raising ``ZipBombError`` immediately rather than retrying.

These tests craft tiny ZIPs and drive the caps down via env vars so no large
payload is ever materialised.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

requests = pytest.importorskip("requests")

from ndi.cloud import download as dl  # noqa: E402


class _FakeResp:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code


def _make_zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


@pytest.fixture
def _patch_get(monkeypatch):
    """Patch requests.get to return a fixed ZIP payload."""

    def _install(zip_bytes: bytes):
        monkeypatch.setattr(
            requests, "get", lambda *a, **k: _FakeResp(zip_bytes, 200)
        )

    return _install


def test_oversize_uncompressed_raises_before_extract(_patch_get, monkeypatch):
    # One JSON entry whose UNCOMPRESSED size exceeds a deliberately tiny cap.
    # Highly compressible payload keeps the on-wire ZIP small while the declared
    # file_size in the central directory is large.
    big = b"A" * 50_000
    payload = json.dumps([{"x": big.decode()}]).encode("utf-8")
    zip_bytes = _make_zip({"doc.json": payload})
    _patch_get(zip_bytes)

    # Cap well below the entry's uncompressed size.
    monkeypatch.setenv("NDI_DOWNLOAD_MAX_UNCOMPRESSED_BYTES", "1024")

    with pytest.raises(dl.ZipBombError, match="uncompressed size"):
        dl._download_chunk_zip("http://example/zip", timeout=5.0, retry_interval=0.01)


def test_too_many_entries_raises_before_extract(_patch_get, monkeypatch):
    # Several small entries, with the entry-count cap set below that count.
    entries = {f"doc_{i}.json": b"[]" for i in range(5)}
    zip_bytes = _make_zip(entries)
    _patch_get(zip_bytes)

    monkeypatch.setenv("NDI_DOWNLOAD_MAX_ZIP_ENTRIES", "2")

    with pytest.raises(dl.ZipBombError, match="entries"):
        dl._download_chunk_zip("http://example/zip", timeout=5.0, retry_interval=0.01)


def test_within_caps_extracts_normally(_patch_get, monkeypatch):
    # A small, well-formed ZIP under both (default) caps extracts its docs.
    docs = [{"a": 1}, {"a": 2}]
    zip_bytes = _make_zip({"docs.json": json.dumps(docs).encode("utf-8")})
    _patch_get(zip_bytes)

    out = dl._download_chunk_zip("http://example/zip", timeout=5.0, retry_interval=0.01)
    assert out == docs


def test_zipbomb_error_is_valueerror_subclass():
    # Backward-compatibility: existing callers that catch ValueError still catch
    # the new guard.
    assert issubclass(dl.ZipBombError, ValueError)


def test_limits_env_override_and_defaults(monkeypatch):
    # Defaults when unset.
    monkeypatch.delenv("NDI_DOWNLOAD_MAX_UNCOMPRESSED_BYTES", raising=False)
    monkeypatch.delenv("NDI_DOWNLOAD_MAX_ZIP_ENTRIES", raising=False)
    max_bytes, max_entries = dl._zip_extraction_limits()
    assert max_bytes == dl._DEFAULT_MAX_UNCOMPRESSED_BYTES
    assert max_entries == dl._DEFAULT_MAX_ENTRIES

    # Valid overrides.
    monkeypatch.setenv("NDI_DOWNLOAD_MAX_UNCOMPRESSED_BYTES", "4096")
    monkeypatch.setenv("NDI_DOWNLOAD_MAX_ZIP_ENTRIES", "7")
    assert dl._zip_extraction_limits() == (4096, 7)

    # Non-positive / unparseable values fall back to defaults.
    monkeypatch.setenv("NDI_DOWNLOAD_MAX_UNCOMPRESSED_BYTES", "0")
    monkeypatch.setenv("NDI_DOWNLOAD_MAX_ZIP_ENTRIES", "not-a-number")
    assert dl._zip_extraction_limits() == (
        dl._DEFAULT_MAX_UNCOMPRESSED_BYTES,
        dl._DEFAULT_MAX_ENTRIES,
    )
