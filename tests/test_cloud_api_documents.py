"""Unit tests for ndi.cloud.api.documents — no network required."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _make_client() -> MagicMock:
    """Return a mock CloudClient."""
    client = MagicMock()
    client.config.org_id = "org-123"
    client.config.api_url = "https://api.ndi-cloud.com/v1"
    return client


# --- 24-char hex helper for bulkFetch --------------------------------------
_HEX24_A = "a" * 24
_HEX24_B = "b" * 24


class TestBulkFetch:
    """bulkFetch validates inputs and POSTs to /documents/bulk-fetch."""

    def test_returns_documents_list(self):
        from ndi.cloud.api.documents import bulkFetch

        client = _make_client()
        client.post.return_value = {
            "documents": [{"id": _HEX24_A, "name": "d1"}, {"id": _HEX24_B, "name": "d2"}]
        }

        docs = bulkFetch("ds-1", [_HEX24_A, _HEX24_B], client=client)

        client.post.assert_called_once()
        call = client.post.call_args
        assert call.args[0] == "/datasets/{datasetId}/documents/bulk-fetch"
        assert call.kwargs["datasetId"] == "ds-1"
        assert call.kwargs["json"] == {"documentIds": [_HEX24_A, _HEX24_B]}
        assert [d["name"] for d in docs] == ["d1", "d2"]

    def test_empty_doc_ids_raises(self):
        from ndi.cloud.api.documents import bulkFetch

        with pytest.raises(ValueError, match="non-empty"):
            bulkFetch("ds-1", [], client=_make_client())

    def test_over_500_raises(self):
        from ndi.cloud.api.documents import bulkFetch

        ids = [_HEX24_A] * 501
        with pytest.raises(ValueError, match="at most 500"):
            bulkFetch("ds-1", ids, client=_make_client())

    def test_non_hex_id_raises(self):
        from ndi.cloud.api.documents import bulkFetch

        with pytest.raises(ValueError, match="24-character hex"):
            bulkFetch("ds-1", ["not-a-hex-id"], client=_make_client())

    def test_missing_documents_field_returns_empty(self):
        from ndi.cloud.api.documents import bulkFetch

        client = _make_client()
        client.post.return_value = {}
        docs = bulkFetch("ds-1", [_HEX24_A], client=client)
        assert docs == []


class TestDocumentClassCounts:
    """documentClassCounts GETs /document-class-counts and returns the struct."""

    def test_returns_response_dict(self):
        from ndi.cloud.api.documents import documentClassCounts

        client = _make_client()
        client.get.return_value = {
            "datasetId": "ds-1",
            "totalDocuments": 3,
            "classCounts": {"ndi_document_probe": 2, "unknown": 1},
        }

        result = documentClassCounts("ds-1", client=client)

        client.get.assert_called_once()
        call = client.get.call_args
        assert call.args[0] == "/datasets/{datasetId}/document-class-counts"
        assert call.kwargs["datasetId"] == "ds-1"
        assert result["totalDocuments"] == 3
        assert result["classCounts"]["ndi_document_probe"] == 2
