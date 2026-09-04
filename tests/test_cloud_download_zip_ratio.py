"""A bulk-download ZIP with an implausible expansion ratio is refused.

The bulk-download endpoint hands the client a presigned URL and the client
opens the response as a ZIP. If a corrupt or hostile object at that URL
declared, say, 10 GB of uncompressed content in a 1 KB pack, an unguarded
``ZipFile.read`` walked in memory would OOM the caller.

Real bulk-download payloads are JSON documents -- text, which compresses
into the single-digit-x range and hits maybe 15x on the very best days.
A ceiling at 100x sits far above real data and orders of magnitude below
what a bomb needs to be worth crafting.

Item 3 of ndi-python#92.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

import ndi.cloud.download as download
from ndi.cloud.download import _ZIP_MAX_RATIO, _check_zip_ratio


def _zip_with_bytes(entries: dict[str, bytes], *, compression: int) -> bytes:
    """Build a ZIP in memory from ``{name: raw_bytes}``."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=compression) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


class TestPreflightRatio:
    def test_a_realistic_json_zip_passes(self):
        """Real bulk-download payloads are JSON dicts; ratio sits well under
        the ceiling. Highly compressible but nowhere near bomb territory."""
        doc = {"base": {"id": "x" * 32, "name": "sample"}, "notes": "a" * 200}
        payload = json.dumps(doc).encode("utf-8")
        raw = _zip_with_bytes(
            {f"doc_{i}.json": payload for i in range(50)},
            compression=zipfile.ZIP_DEFLATED,
        )
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            _check_zip_ratio(zf)  # does not raise

    def test_an_uncompressed_zip_passes(self):
        """Ratio ~1x."""
        raw = _zip_with_bytes(
            {"a.json": b'{"x": 1}', "b.json": b'{"y": 2}'},
            compression=zipfile.ZIP_STORED,
        )
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            _check_zip_ratio(zf)

    def test_a_bomb_is_refused_before_a_byte_is_extracted(self):
        """A single member declaring millions of bytes of zeros compressed
        into a hundred is the shape a real bomb has. The check reads
        ``infolist()`` only, so nothing is extracted before the raise."""
        bomb = b"\x00" * (2 * 1024 * 1024)  # 2 MB of zeros -> tiny compressed
        raw = _zip_with_bytes({"bomb.json": bomb}, compression=zipfile.ZIP_DEFLATED)

        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            info = zf.infolist()[0]
            ratio = info.file_size / max(info.compress_size, 1)
            assert ratio > _ZIP_MAX_RATIO, "test fixture must actually exceed the ceiling"

            with pytest.raises(ValueError, match="implausible compression ratio"):
                _check_zip_ratio(zf)

    def test_the_error_names_the_ratio_and_the_ceiling(self):
        bomb = b"\x00" * (2 * 1024 * 1024)
        raw = _zip_with_bytes({"bomb.json": bomb}, compression=zipfile.ZIP_DEFLATED)
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            with pytest.raises(ValueError) as exc:
                _check_zip_ratio(zf)
        msg = str(exc.value)
        assert "ceiling is" in msg and str(_ZIP_MAX_RATIO) in msg

    def test_an_empty_zip_is_not_a_division_by_zero(self):
        raw = _zip_with_bytes({}, compression=zipfile.ZIP_STORED)
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            _check_zip_ratio(zf)  # does not raise


class TestChunkDownloadGuardsAgainstBomb:
    """The check has to be ON the download path, not merely available."""

    def _serve_zip(self, monkeypatch, raw: bytes) -> None:
        """Stub ``requests.get`` inside download.py to hand back ``raw``."""

        class FakeResponse:
            status_code = 200
            content = raw

        class FakeRequests:
            @staticmethod
            def get(url, **kwargs):
                return FakeResponse()

        # download.py does ``import requests`` inside _download_chunk_zip, so
        # patch the top-level module the import resolves to.
        import requests

        monkeypatch.setattr(requests, "get", FakeRequests.get)

    def test_a_bomb_causes_the_chunk_download_to_time_out_rather_than_extract(self, monkeypatch):
        """Inside ``_download_chunk_zip`` any extraction failure is caught
        and retried until the timeout. A bomb triggers a ValueError, so the
        chunk times out with the ValueError as its ``last_exc`` -- crucially,
        no ``zf.read`` runs and no gigabytes materialise."""
        bomb = b"\x00" * (2 * 1024 * 1024)
        raw = _zip_with_bytes({"bomb.json": bomb}, compression=zipfile.ZIP_DEFLATED)
        self._serve_zip(monkeypatch, raw)

        with pytest.raises(TimeoutError, match="implausible compression ratio"):
            download._download_chunk_zip(
                "https://example.invalid/zip", timeout=0.2, retry_interval=0.05
            )

    def test_a_normal_json_zip_extracts_end_to_end(self, monkeypatch):
        """Happy path: the ratio guard does not touch legitimate payloads."""
        payload = json.dumps({"base": {"id": "abc"}, "note": "ok"}).encode("utf-8")
        raw = _zip_with_bytes(
            {f"doc_{i}.json": payload for i in range(10)},
            compression=zipfile.ZIP_DEFLATED,
        )
        self._serve_zip(monkeypatch, raw)

        docs = download._download_chunk_zip(
            "https://example.invalid/zip", timeout=1.0, retry_interval=0.05
        )
        assert len(docs) == 10
        assert docs[0]["base"]["id"] == "abc"


if __name__ == "__main__":
    pytest.main([__file__])
