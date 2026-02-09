"""
Live cloud API integration tests.

These tests run against the real NDI Cloud API (https://api.ndi-cloud.com/v1).
They require credentials via environment variables:

    NDI_CLOUD_USERNAME  — email for test account
    NDI_CLOUD_PASSWORD  — password for test account

Skipped automatically if credentials are not set.

The tests are READ-ONLY — they authenticate, list datasets, fetch documents,
and download metadata, but never create, modify, or delete anything.
"""

from __future__ import annotations

import os

import pytest

# Skip entire module if no credentials
_has_creds = bool(os.environ.get("NDI_CLOUD_USERNAME") and os.environ.get("NDI_CLOUD_PASSWORD"))
pytestmark = pytest.mark.skipif(not _has_creds, reason="NDI cloud credentials not set")

# Jess Haley's public dataset
DATASET_ID = "682e7772cdf3f24938176fac"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cloud_config():
    """Authenticate once for the entire module and return config."""
    from ndi.cloud.auth import login
    from ndi.cloud.config import CloudConfig

    config = CloudConfig.from_env()
    config = login(config=config)
    assert config.is_authenticated, "Login failed — no token received"
    return config


@pytest.fixture(scope="module")
def client(cloud_config):
    """Return an authenticated CloudClient."""
    from ndi.cloud.client import CloudClient

    return CloudClient(cloud_config)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


class TestAuthentication:
    def test_login_returns_token(self, cloud_config):
        """Login must return a non-empty JWT token."""
        assert cloud_config.token
        assert len(cloud_config.token) > 50  # JWTs are long

    def test_token_is_valid_jwt(self, cloud_config):
        """Token must be a valid 3-part JWT."""
        parts = cloud_config.token.split(".")
        assert len(parts) == 3

    def test_token_not_expired(self, cloud_config):
        """Token must not be expired."""
        from ndi.cloud.auth import verify_token

        assert verify_token(cloud_config.token)

    def test_jwt_has_expected_claims(self, cloud_config):
        """JWT payload should contain standard claims."""
        from ndi.cloud.auth import decode_jwt

        payload = decode_jwt(cloud_config.token)
        assert "exp" in payload  # expiration
        # Should have some user identifier
        assert any(k in payload for k in ("sub", "email", "userId", "id"))


# ---------------------------------------------------------------------------
# Dataset API (read-only)
# ---------------------------------------------------------------------------


class TestDatasetAPI:
    def test_get_dataset(self, client):
        """Fetch dataset metadata by ID."""
        from ndi.cloud.api.datasets import get_dataset

        ds = get_dataset(client, DATASET_ID)
        assert isinstance(ds, dict)
        assert ds.get("_id") == DATASET_ID or ds.get("id") == DATASET_ID

    def test_dataset_has_name(self, client):
        """Dataset should have a name field."""
        from ndi.cloud.api.datasets import get_dataset

        ds = get_dataset(client, DATASET_ID)
        name = ds.get("name", "")
        assert name, f"Dataset has no name, keys: {list(ds.keys())}"

    def test_dataset_has_metadata(self, client):
        """Dataset should have standard metadata fields."""
        from ndi.cloud.api.datasets import get_dataset

        ds = get_dataset(client, DATASET_ID)
        # At minimum should have some organizational fields
        assert any(
            k in ds for k in ("name", "description", "organization", "createdAt", "owner")
        ), f"Missing expected metadata, keys: {list(ds.keys())}"

    def test_nonexistent_dataset_raises(self, client):
        """Fetching a bogus dataset ID should raise CloudNotFoundError."""
        from ndi.cloud.api.datasets import get_dataset
        from ndi.cloud.exceptions import CloudAPIError

        with pytest.raises(CloudAPIError):
            get_dataset(client, "000000000000000000000000")


# ---------------------------------------------------------------------------
# Document API (read-only)
# ---------------------------------------------------------------------------


class TestDocumentAPI:
    def test_list_documents(self, client):
        """List documents in the dataset — should return at least one."""
        from ndi.cloud.api.documents import list_documents

        result = list_documents(client, DATASET_ID, page=1, page_size=10)
        assert isinstance(result, dict)
        docs = result.get("documents", [])
        assert len(docs) > 0, f"Dataset has no documents, keys: {list(result.keys())}"

    def test_list_all_documents(self, client):
        """Auto-paginate all documents."""
        from ndi.cloud.api.documents import list_all_documents

        docs = list_all_documents(client, DATASET_ID)
        assert isinstance(docs, list)
        assert len(docs) > 0

    def test_document_count(self, client):
        """get_document_count should return a positive integer."""
        from ndi.cloud.api.documents import get_document_count

        count = get_document_count(client, DATASET_ID)
        assert isinstance(count, int)
        assert count > 0

    def test_get_single_document(self, client):
        """Fetch a single document by ID."""
        from ndi.cloud.api.documents import get_document, list_documents

        # Get first document ID
        result = list_documents(client, DATASET_ID, page=1, page_size=1)
        docs = result.get("documents", [])
        assert docs, "No documents to fetch"
        doc_id = docs[0].get("_id", docs[0].get("id", ""))
        assert doc_id

        # Fetch it individually
        doc = get_document(client, DATASET_ID, doc_id)
        assert isinstance(doc, dict)

    def test_documents_have_structure(self, client):
        """Documents should have recognizable NDI structure."""
        from ndi.cloud.api.documents import list_documents

        result = list_documents(client, DATASET_ID, page=1, page_size=5)
        docs = result.get("documents", [])
        assert docs

        for doc in docs:
            # Each doc should at least have an ID
            assert doc.get("_id") or doc.get("id") or doc.get("ndiId")


# ---------------------------------------------------------------------------
# Internal utilities against live API
# ---------------------------------------------------------------------------


class TestInternalUtils:
    def test_list_remote_document_ids(self, client):
        """list_remote_document_ids should return a non-empty mapping."""
        from ndi.cloud.internal import list_remote_document_ids

        mapping = list_remote_document_ids(client, DATASET_ID)
        assert isinstance(mapping, dict)
        assert len(mapping) > 0
        # Values should be API IDs (strings)
        for ndi_id, api_id in mapping.items():
            assert isinstance(ndi_id, str)
            assert isinstance(api_id, str)


# ---------------------------------------------------------------------------
# Download (read-only)
# ---------------------------------------------------------------------------


class TestDownload:
    def test_download_document_collection(self, client):
        """Download all documents as dicts."""
        from ndi.cloud.download import download_document_collection

        docs = download_document_collection(client, DATASET_ID)
        assert isinstance(docs, list)
        assert len(docs) > 0
        # Each should be a dict
        for doc in docs[:3]:
            assert isinstance(doc, dict)

    def test_download_specific_documents(self, client):
        """Download specific documents by ID."""
        from ndi.cloud.api.documents import list_documents
        from ndi.cloud.download import download_document_collection

        # Get first 2 document IDs
        result = list_documents(client, DATASET_ID, page=1, page_size=2)
        doc_list = result.get("documents", [])
        ids = [d.get("_id", d.get("id", "")) for d in doc_list]
        ids = [i for i in ids if i]
        assert ids

        docs = download_document_collection(client, DATASET_ID, doc_ids=ids)
        assert len(docs) == len(ids)
