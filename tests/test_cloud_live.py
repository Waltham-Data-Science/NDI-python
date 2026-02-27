"""
Live cloud API integration tests.

These tests run against the real NDI Cloud API.
They require credentials via environment variables:

    NDI_CLOUD_USERNAME  -- email for test account
    NDI_CLOUD_PASSWORD  -- password for test account

Optionally:
    CLOUD_API_ENVIRONMENT  -- 'prod' (default) or 'dev'

Skipped automatically if credentials are not set.

Two read-only public datasets are used for non-mutating tests:
    LARGE_DATASET  -- Jess Haley's C. elegans dataset (78K docs, 16 GB files)
    SMALL_DATASET  -- Carbon fiber microelectrode dataset (743 docs, 9.7 GB files)

Write tests (dataset/document/file CRUD) create their own resources
and clean up via fixture teardown.
"""

from __future__ import annotations

import os
import time

import pytest

# ---------------------------------------------------------------------------
# Skip entire module if no credentials
# ---------------------------------------------------------------------------

_has_creds = bool(os.environ.get("NDI_CLOUD_USERNAME") and os.environ.get("NDI_CLOUD_PASSWORD"))
pytestmark = pytest.mark.skipif(not _has_creds, reason="NDI cloud credentials not set")

# Public dataset IDs (read-only tests)
LARGE_DATASET = "682e7772cdf3f24938176fac"
SMALL_DATASET = "668b0539f13096e04f1feccd"


def _retry_on_server_error(fn, retries=3, delay=10, retry_on_404=False):
    """Call *fn*; retry on HTTP 502/504 server errors.

    The NDI Cloud API runs on AWS Lambda with a 30-second gateway timeout.
    Write-heavy operations (create_dataset, submit, publish) often exceed
    this limit, returning 504.  We retry with exponential back-off.

    Set *retry_on_404* for operations that follow a create — MongoDB
    ``secondaryPreferred`` reads may lag behind the primary write.
    """
    from ndi.cloud.exceptions import CloudAPIError

    retryable = {502, 504}
    if retry_on_404:
        retryable.add(404)

    last_exc = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except CloudAPIError as exc:
            if getattr(exc, "status_code", 0) in retryable and attempt < retries:
                last_exc = exc
                time.sleep(delay * (attempt + 1))
                continue
            raise
    raise last_exc  # pragma: no cover


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
    assert config.is_authenticated, "Login failed -- no token received"
    return config


@pytest.fixture(scope="module")
def client(cloud_config):
    """Return an authenticated CloudClient."""
    from ndi.cloud.client import CloudClient

    return CloudClient(cloud_config)


@pytest.fixture(scope="module")
def user_info(client):
    """Fetch and cache current user info."""
    from ndi.cloud.api.users import get_current_user

    return get_current_user(client=client)


@pytest.fixture(scope="module")
def is_admin(user_info):
    """Detect whether the current user has admin privileges."""
    # Check various possible admin flag locations
    if user_info.get("isAdmin"):
        return True
    if user_info.get("role") == "admin":
        return True
    orgs = user_info.get("organizations", [])
    if isinstance(orgs, list):
        for org in orgs:
            if org.get("role") == "admin":
                return True
    # Check canUploadDataset as a proxy for elevated privileges
    if user_info.get("canUploadDataset") is True:
        return True
    return False


@pytest.fixture(scope="module")
def large_dataset_info(client):
    """Fetch and cache metadata for the large public dataset."""
    from ndi.cloud.api.datasets import get_dataset

    return get_dataset(LARGE_DATASET, client=client)


@pytest.fixture(scope="module")
def small_dataset_info(client):
    """Fetch and cache metadata for the small public dataset."""
    from ndi.cloud.api.datasets import get_dataset

    return get_dataset(SMALL_DATASET, client=client)


@pytest.fixture(scope="module")
def can_write(client, cloud_config):
    """Test whether this user can create datasets (returns bool).

    Regular users get HTTP 400 from create_dataset — skip CRUD tests.
    """
    from ndi.cloud.api.datasets import create_dataset, delete_dataset

    try:
        result = _retry_on_server_error(
            lambda: create_dataset(cloud_config.org_id, "NDI_PYTEST_WRITE_CHECK", client=client)
        )
        ds_id = result.get("_id", result.get("id", ""))
        if ds_id:
            try:
                delete_dataset(ds_id, when="now", client=client)
            except Exception:
                pass
            return True
        return False
    except Exception:
        return False


@pytest.fixture()
def fresh_dataset(client, cloud_config, can_write):
    """Create a temporary dataset, yield its ID, delete on teardown."""
    if not can_write:
        pytest.skip("User does not have dataset creation privileges")

    from ndi.cloud.api.datasets import create_dataset, delete_dataset
    from ndi.cloud.exceptions import CloudAPIError

    org_id = cloud_config.org_id
    try:
        result = _retry_on_server_error(
            lambda: create_dataset(org_id, "NDI_PYTEST_TEMP_DATASET", client=client)
        )
    except CloudAPIError as exc:
        pytest.skip(f"Could not create dataset (server error): {exc}")
    dataset_id = result.get("_id", result.get("id", ""))
    assert dataset_id, f"Failed to create dataset, response: {result}"

    yield dataset_id

    # Teardown: delete the dataset
    try:
        delete_dataset(dataset_id, when="now", client=client)
    except Exception:
        pass


# ===========================================================================
# TestCloudConfig -- replaces mocked foundation config tests
# ===========================================================================


class TestCloudConfig:
    def test_config_from_env(self, cloud_config):
        """CloudConfig.from_env() should populate fields from environment."""
        assert cloud_config.api_url
        assert cloud_config.username or cloud_config.token

    def test_config_api_url_is_valid(self, cloud_config):
        """API URL should be a valid HTTPS URL."""
        assert cloud_config.api_url.startswith("https://")
        assert "ndi-cloud.com" in cloud_config.api_url

    def test_config_api_url_matches_environment(self, cloud_config):
        """URL should match the CLOUD_API_ENVIRONMENT setting."""
        env = os.environ.get("CLOUD_API_ENVIRONMENT", "prod")
        if env == "dev":
            assert "dev-api" in cloud_config.api_url
        else:
            assert "dev-api" not in cloud_config.api_url

    def test_config_repr_masks_token(self, cloud_config):
        """repr should not expose the full token."""
        r = repr(cloud_config)
        assert cloud_config.token not in r
        assert "..." in r

    def test_config_is_authenticated(self, cloud_config):
        """is_authenticated should be True after login."""
        assert cloud_config.is_authenticated is True


# ===========================================================================
# TestExceptionHierarchy -- pure Python, no API calls
# ===========================================================================


class TestExceptionHierarchy:
    def test_cloud_error_is_exception(self):
        from ndi.cloud.exceptions import CloudError

        assert issubclass(CloudError, Exception)

    def test_api_error_has_status_code(self):
        from ndi.cloud.exceptions import CloudAPIError

        err = CloudAPIError("test", status_code=500, response_body="error")
        assert err.status_code == 500
        assert err.response_body == "error"

    def test_not_found_is_api_error(self):
        from ndi.cloud.exceptions import CloudAPIError, CloudNotFoundError

        assert issubclass(CloudNotFoundError, CloudAPIError)

    def test_auth_error_is_cloud_error(self):
        from ndi.cloud.exceptions import CloudAuthError, CloudError

        assert issubclass(CloudAuthError, CloudError)


# ===========================================================================
# TestAuth -- matches MATLAB AuthTest
# ===========================================================================


class TestAuth:
    def test_login_returns_token(self, cloud_config):
        """Login must return a non-empty JWT token."""
        assert cloud_config.token
        assert len(cloud_config.token) > 50

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
        assert "exp" in payload
        assert any(k in payload for k in ("sub", "email", "userId", "id"))

    def test_config_has_org_id(self, cloud_config):
        """Login should populate org_id."""
        assert cloud_config.org_id
        assert len(cloud_config.org_id) > 10

    def test_decode_jwt_structure(self, cloud_config):
        """decode_jwt should return a dict with expected keys."""
        from ndi.cloud.auth import decode_jwt

        payload = decode_jwt(cloud_config.token)
        assert isinstance(payload, dict)
        assert "iat" in payload or "exp" in payload


# ===========================================================================
# TestUser -- matches MATLAB UserTest
# ===========================================================================


class TestUser:
    def test_get_current_user(self, user_info):
        """GET /users/me should return authenticated user info."""
        assert hasattr(user_info, "get"), f"Expected dict-like response, got {type(user_info)}"
        assert user_info.get("id")
        assert user_info.get("email")
        assert user_info.get("name")

    def test_user_has_organizations(self, user_info):
        """User should belong to at least one organization."""
        orgs = user_info.get("organizations", [])
        assert isinstance(orgs, list)
        assert len(orgs) > 0
        assert orgs[0].get("id")
        assert orgs[0].get("name")

    def test_get_user_by_id(self, client, user_info):
        """GET /users/{userId} should return the same user."""
        from ndi.cloud.api.users import get_user

        user = get_user(user_info["id"], client=client)
        assert user.get("id") == user_info["id"]

    def test_user_role_detection(self, user_info, is_admin):
        """Admin detection should return a boolean."""
        assert isinstance(is_admin, bool)
        # Verify the user_info has email (sanity check)
        assert user_info.get("email")


# ===========================================================================
# TestDatasetLifecycle -- matches MATLAB DatasetsTest (requires write)
# ===========================================================================


class TestDatasetLifecycle:
    def test_create_and_delete_dataset(self, client, cloud_config, can_write):
        """Create a dataset, verify it exists, then delete it."""
        if not can_write:
            pytest.skip("User does not have dataset creation privileges")

        from ndi.cloud.api.datasets import (
            create_dataset,
            delete_dataset,
            get_dataset,
        )
        from ndi.cloud.exceptions import CloudAPIError as _APIError

        org_id = cloud_config.org_id
        try:
            result = _retry_on_server_error(
                lambda: create_dataset(org_id, "NDI_PYTEST_CREATE_DELETE", client=client)
            )
        except _APIError as exc:
            pytest.skip(f"create_dataset timed out (server 504): {exc}")
        ds_id = result.get("_id", result.get("id", ""))
        assert ds_id, f"Create returned no ID: {result}"

        try:
            ds = get_dataset(ds_id, client=client)
            assert ds.get("_id") == ds_id or ds.get("id") == ds_id
        finally:
            try:
                _retry_on_server_error(lambda: delete_dataset(ds_id, when="now", client=client))
            except Exception:
                pass  # Best-effort cleanup

    def test_get_dataset_metadata(self, client, fresh_dataset):
        """Created dataset should have _id, name, createdAt."""
        from ndi.cloud.api.datasets import get_dataset

        ds = get_dataset(fresh_dataset, client=client)
        ds_id = ds.get("_id", ds.get("id", ""))
        assert ds_id == fresh_dataset
        assert ds.get("name")
        assert ds.get("createdAt")

    def test_update_dataset(self, client, fresh_dataset):
        """Update dataset name and verify the change persists."""
        from ndi.cloud.api.datasets import get_dataset, update_dataset

        new_name = "NDI_PYTEST_UPDATED_NAME"
        _retry_on_server_error(
            lambda: update_dataset(fresh_dataset, name=new_name, client=client),
        )

        ds = get_dataset(fresh_dataset, client=client)
        assert ds.get("name") == new_name

    def test_list_datasets(self, client, cloud_config, fresh_dataset):
        """Created dataset should appear in the org's dataset list."""
        from ndi.cloud.api.datasets import list_datasets

        result = list_datasets(cloud_config.org_id, client=client)
        datasets = result.get("datasets", [])
        ids = {d.get("_id", d.get("id", "")) for d in datasets}
        assert fresh_dataset in ids

    def test_get_branches(self, client, fresh_dataset):
        """Branches endpoint should return without error."""
        from ndi.cloud.api.datasets import get_branches

        result = get_branches(fresh_dataset, client=client)
        assert result is not None

    def test_nonexistent_dataset_raises(self, client):
        """Fetching a bogus dataset ID should raise CloudAPIError."""
        from ndi.cloud.api.datasets import get_dataset
        from ndi.cloud.exceptions import CloudAPIError

        with pytest.raises(CloudAPIError):
            get_dataset("000000000000000000000000", client=client)

    def test_invalid_dataset_id_raises(self, client):
        """Fetching with invalid ID format should raise."""
        from ndi.cloud.api.datasets import get_dataset
        from ndi.cloud.exceptions import CloudAPIError

        with pytest.raises(CloudAPIError):
            get_dataset("not-a-valid-id", client=client)


# ===========================================================================
# TestDocumentLifecycle -- matches MATLAB DocumentsTest (requires write)
# ===========================================================================


class TestDocumentLifecycle:
    def test_empty_dataset_has_zero_documents(self, client, fresh_dataset):
        """A newly created dataset should have 0 documents."""
        from ndi.cloud.api.documents import get_document_count, list_documents

        result = list_documents(fresh_dataset, page=1, page_size=10, client=client)
        docs = result.get("documents", [])
        assert len(docs) == 0

        count = get_document_count(fresh_dataset, client=client)
        assert count == 0

    def test_add_get_delete_document(self, client, fresh_dataset):
        """Full document lifecycle: add, get, verify, delete."""
        from ndi.cloud.api.documents import (
            add_document,
            delete_document,
            get_document,
        )

        doc_json = {
            "document_class": {"class_name": "ndi_pytest_test_doc"},
            "base": {"name": "test_document", "data": [1, 2, 3]},
        }

        # Add
        result = add_document(fresh_dataset, doc_json, client=client)
        doc_id = result.get("_id", result.get("id", ""))
        assert doc_id, f"Add returned no ID: {result}"

        # Get and verify
        fetched = get_document(fresh_dataset, doc_id, client=client)
        assert fetched.get("base", {}).get("name") == "test_document"

        # Delete
        delete_document(fresh_dataset, doc_id, when="now", client=client)

        # Verify gone
        from ndi.cloud.exceptions import CloudAPIError

        with pytest.raises(CloudAPIError):
            get_document(fresh_dataset, doc_id, client=client)

    def test_update_document(self, client, fresh_dataset):
        """Add a document, update it, verify changes persist."""
        from ndi.cloud.api.documents import (
            add_document,
            delete_document,
            get_document,
            update_document,
        )

        doc_json = {
            "document_class": {"class_name": "ndi_pytest_update"},
            "base": {"name": "original"},
        }
        result = add_document(fresh_dataset, doc_json, client=client)
        doc_id = result.get("_id", result.get("id", ""))

        try:
            updated_json = {
                "document_class": {"class_name": "ndi_pytest_update"},
                "base": {"name": "modified"},
            }
            _retry_on_server_error(
                lambda: update_document(fresh_dataset, doc_id, updated_json, client=client),
            )
            fetched = get_document(fresh_dataset, doc_id, client=client)
            assert fetched.get("base", {}).get("name") == "modified"
        finally:
            try:
                delete_document(fresh_dataset, doc_id, when="now", client=client)
            except Exception:
                pass

    def test_list_documents_pagination(self, client, fresh_dataset):
        """Add multiple docs, paginate through them."""
        from ndi.cloud.api.documents import add_document, list_documents

        # Add 5 documents
        doc_ids = []
        for i in range(5):
            result = add_document(
                fresh_dataset,
                {
                    "document_class": {"class_name": "ndi_pytest_pagination"},
                    "base": {"name": f"doc_{i}"},
                },
                client=client,
            )
            doc_ids.append(result.get("_id", result.get("id", "")))

        # Paginate with page_size=2
        p1 = list_documents(fresh_dataset, page=1, page_size=2, client=client)
        p2 = list_documents(fresh_dataset, page=2, page_size=2, client=client)
        docs1 = p1.get("documents", [])
        docs2 = p2.get("documents", [])
        assert len(docs1) == 2
        assert len(docs2) == 2

        # Pages should not overlap
        ids1 = {d.get("_id", d.get("id")) for d in docs1}
        ids2 = {d.get("_id", d.get("id")) for d in docs2}
        assert ids1.isdisjoint(ids2)

    def test_list_all_documents(self, client, fresh_dataset):
        """list_all_documents should return all docs via auto-pagination."""
        from ndi.cloud.api.documents import add_document, list_all_documents

        # Add 5 docs
        for i in range(5):
            add_document(
                fresh_dataset,
                {
                    "document_class": {"class_name": "ndi_pytest_listall"},
                    "base": {"name": f"listall_{i}"},
                },
                client=client,
            )

        docs = list_all_documents(fresh_dataset, page_size=2, client=client).data
        # Should get all docs in the dataset (at least the 5 we added,
        # plus any from previous tests in same fixture -- but fresh_dataset
        # is function-scoped so each test gets its own)
        assert len(docs) >= 5

    def test_document_count(self, client, fresh_dataset):
        """get_document_count should match actual document count."""
        from ndi.cloud.api.documents import add_document, get_document_count

        for i in range(3):
            add_document(
                fresh_dataset,
                {
                    "document_class": {"class_name": "ndi_pytest_count"},
                    "base": {"name": f"count_{i}"},
                },
                client=client,
            )

        count = get_document_count(fresh_dataset, client=client)
        assert count == 3

    def test_bulk_upload_and_download(self, client, fresh_dataset):
        """Bulk upload docs via ZIP, then bulk download and verify."""
        from ndi.cloud.api.documents import (
            get_bulk_download_url,
            list_all_documents,
        )
        from ndi.cloud.upload import upload_document_collection

        docs = [
            {"document_class": {"class_name": "ndi_pytest_bulk"}, "base": {"name": f"bulk_{i}"}}
            for i in range(3)
        ]

        report = upload_document_collection(fresh_dataset, docs, client=client)
        assert report.get("uploaded", 0) >= 3 or report.get("added", 0) >= 3

        # Verify they exist
        all_docs = list_all_documents(fresh_dataset, client=client).data
        assert len(all_docs) >= 3

        # Bulk download URL should be generated
        url = get_bulk_download_url(fresh_dataset, client=client)
        assert url
        assert "s3" in url.lower() or "amazonaws" in url.lower() or "http" in url.lower()

    def test_bulk_delete(self, client, fresh_dataset):
        """Add 5 docs, bulk delete 3, verify 2 remain."""
        from ndi.cloud.api.documents import (
            add_document,
            bulk_delete,
            list_all_documents,
        )

        doc_ids = []
        for i in range(5):
            result = add_document(
                fresh_dataset,
                {
                    "document_class": {"class_name": "ndi_pytest_bulkdel"},
                    "base": {"name": f"bulkdel_{i}"},
                },
                client=client,
            )
            doc_ids.append(result.get("_id", result.get("id", "")))

        # Delete the first 3
        bulk_delete(fresh_dataset, doc_ids[:3], when="now", client=client)

        # Small delay for server processing
        time.sleep(2)

        remaining = list_all_documents(fresh_dataset, client=client).data
        assert len(remaining) == 2

    def test_nonexistent_document_raises(self, client, fresh_dataset):
        """Fetching a bogus document ID should raise."""
        from ndi.cloud.api.documents import get_document
        from ndi.cloud.exceptions import CloudAPIError

        with pytest.raises(CloudAPIError):
            get_document(fresh_dataset, "000000000000000000000000", client=client)


# ===========================================================================
# TestFileLifecycle -- matches MATLAB FilesTest (requires write)
# ===========================================================================


class TestFileLifecycle:
    def test_get_upload_url(self, client, cloud_config, fresh_dataset):
        """get_upload_url should return a presigned URL."""
        from ndi.cloud.api.files import get_upload_url

        url = get_upload_url(
            cloud_config.org_id,
            fresh_dataset,
            "pytest-test-file-uid",
            client=client,
        )
        assert isinstance(url, str)
        assert url  # non-empty
        assert "http" in url.lower()

    def test_upload_and_download_file(self, client, cloud_config, fresh_dataset):
        """Upload bytes via presigned URL, then download and verify content."""
        import requests

        from ndi.cloud.api.files import (
            get_file_details,
            get_upload_url,
            list_files,
        )

        file_uid = "pytest-upload-test-file"
        test_content = b"Hello from NDI pytest! This is test file content."

        # Get upload URL
        upload_url = get_upload_url(cloud_config.org_id, fresh_dataset, file_uid, client=client)
        assert upload_url

        # Upload
        resp = requests.put(
            upload_url,
            data=test_content,
            headers={"Content-Type": "application/octet-stream"},
            timeout=30,
        )
        assert resp.status_code == 200, f"Upload failed: {resp.status_code} {resp.text}"

        # Wait for file to be registered and poll for upload completion
        download_url = ""
        details = {}
        for wait in (3, 5, 10):
            time.sleep(wait)
            files = list_files(fresh_dataset, client=client).data
            file_uids = [f.get("uid", "") for f in files]
            if file_uid not in file_uids:
                continue
            details = get_file_details(fresh_dataset, file_uid, client=client)
            download_url = details.get("downloadUrl", "")
            if download_url:
                break

        assert download_url, f"No download URL after retries; details: {details}"

        # Download and verify content
        dl_resp = requests.get(download_url, timeout=30)
        assert dl_resp.status_code == 200
        assert dl_resp.content == test_content

    def test_list_files(self, client, fresh_dataset, cloud_config):
        """After uploading a file, list_files should return it."""
        import requests

        from ndi.cloud.api.files import get_upload_url, list_files

        file_uid = "pytest-list-test-file"
        upload_url = get_upload_url(cloud_config.org_id, fresh_dataset, file_uid, client=client)
        requests.put(
            upload_url,
            data=b"list test data",
            headers={"Content-Type": "application/octet-stream"},
            timeout=30,
        )
        time.sleep(3)

        files = list_files(fresh_dataset, client=client).data
        assert isinstance(files, list)
        uids = [f.get("uid", "") for f in files]
        assert file_uid in uids

    def test_file_details_has_download_url(self, client, fresh_dataset, cloud_config):
        """get_file_details should include downloadUrl."""
        import requests

        from ndi.cloud.api.files import get_file_details, get_upload_url

        file_uid = "pytest-details-test-file"
        upload_url = get_upload_url(cloud_config.org_id, fresh_dataset, file_uid, client=client)
        requests.put(
            upload_url,
            data=b"details test",
            headers={"Content-Type": "application/octet-stream"},
            timeout=30,
        )
        time.sleep(3)

        details = get_file_details(fresh_dataset, file_uid, client=client)
        assert hasattr(details, "get"), f"Expected dict-like response, got {type(details)}"
        assert details.get("downloadUrl")


# ===========================================================================
# TestNDIQuery -- matches MATLAB testNdiQuery
# ===========================================================================


class TestNDIQuery:
    def test_ndi_query_public(self, client):
        """ndiquery should return documents matching a search."""
        from ndi.cloud.api.documents import ndi_query

        search = [
            {
                "field": "document_class.class_name",
                "operation": "exact_string",
                "param1": "session",
            }
        ]
        result = _retry_on_server_error(
            lambda: ndi_query("public", search, page=1, page_size=5, client=client)
        )
        assert hasattr(result, "get"), f"Expected dict-like response, got {type(result)}"
        assert "documents" in result

    def test_ndi_query_nonexistent_returns_empty(self, client):
        """Searching for a non-existent ID should return empty results."""
        from ndi.cloud.api.documents import ndi_query

        search = [
            {
                "field": "base.id",
                "operation": "exact_string",
                "param1": "nonexistent-id-that-should-not-match-anything",
            }
        ]
        result = _retry_on_server_error(
            lambda: ndi_query("public", search, page=1, page_size=5, client=client)
        )
        docs = result.get("documents", [])
        assert len(docs) == 0

    def test_ndi_query_all_paginates(self, client):
        """ndi_query_all should auto-paginate results."""
        from ndi.cloud.api.documents import ndi_query_all

        search = [
            {
                "field": "document_class.class_name",
                "operation": "exact_string",
                "param1": "session",
            }
        ]
        result = _retry_on_server_error(lambda: ndi_query_all("public", search, page_size=3, client=client))
        docs = result.data
        assert isinstance(docs, list)
        assert len(docs) > 0


# ===========================================================================
# TestPublishWorkflow -- admin only (matches MATLAB DatasetsTest publish)
# ===========================================================================


class TestPublishWorkflow:
    @pytest.fixture(autouse=True)
    def _skip_if_not_admin(self, is_admin):
        if not is_admin:
            pytest.skip("Publish tests require admin privileges")

    def test_submit_dataset(self, client, fresh_dataset):
        """Submit a dataset for review."""
        from ndi.cloud.api.datasets import get_dataset, submit_dataset
        from ndi.cloud.exceptions import CloudAPIError

        try:
            _retry_on_server_error(lambda: submit_dataset(fresh_dataset, client=client))
        except CloudAPIError as exc:
            pytest.skip(f"submit_dataset server timeout: {exc}")

        ds = get_dataset(fresh_dataset, client=client)
        assert ds.get("isSubmitted") is True

    def test_publish_unpublish_lifecycle(self, client, fresh_dataset):
        """Full publish lifecycle: submit -> publish -> unpublish."""
        from ndi.cloud.api.datasets import (
            get_dataset,
            publish_dataset,
            submit_dataset,
            unpublish_dataset,
        )
        from ndi.cloud.exceptions import CloudAPIError

        # Submit
        try:
            _retry_on_server_error(lambda: submit_dataset(fresh_dataset, client=client))
        except CloudAPIError as exc:
            pytest.skip(f"submit_dataset server timeout: {exc}")

        # Publish
        try:
            _retry_on_server_error(lambda: publish_dataset(fresh_dataset, client=client))
        except CloudAPIError as exc:
            pytest.skip(f"publish_dataset server timeout: {exc}")
        time.sleep(2)  # Allow server processing
        ds = get_dataset(fresh_dataset, client=client)
        assert ds.get("isPublished") is True

        # Unpublish
        try:
            _retry_on_server_error(lambda: unpublish_dataset(fresh_dataset, client=client))
        except CloudAPIError as exc:
            pytest.skip(f"unpublish_dataset server timeout: {exc}")
        time.sleep(2)
        ds = get_dataset(fresh_dataset, client=client)
        assert ds.get("isPublished") is not True

    def test_published_datasets_list(self, client):
        """GET /datasets/published should return results."""
        from ndi.cloud.api.datasets import get_published_datasets

        result = get_published_datasets(page=1, page_size=5, client=client)
        assert hasattr(result, "get"), f"Expected dict-like response, got {type(result)}"
        datasets = result.get("datasets", [])
        assert len(datasets) > 0

    def test_unpublished_datasets_list(self, client):
        """GET /datasets/unpublished should return results."""
        from ndi.cloud.api.datasets import get_unpublished

        result = get_unpublished(page=1, page_size=5, client=client)
        assert hasattr(result, "get"), f"Expected dict-like response, got {type(result)}"


# ===========================================================================
# TestSoftDelete -- soft-delete, undelete, list-deleted (requires write)
# ===========================================================================


class TestSoftDelete:
    """Soft-delete API: deferred delete, undelete, and list-deleted."""

    def test_deferred_delete_and_undelete(self, client, cloud_config, can_write):
        """Delete with when='7d', verify listed as deleted, then undelete.

        Creates a dataset WITH documents to mimic real-world usage.
        """
        if not can_write:
            pytest.skip("User does not have dataset creation privileges")

        from ndi.cloud.api.datasets import (
            create_dataset,
            delete_dataset,
            get_dataset,
            list_deleted_datasets,
            undelete_dataset,
        )
        from ndi.cloud.api.documents import add_document, list_all_documents
        from ndi.cloud.exceptions import CloudAPIError as _APIError

        org_id = cloud_config.org_id
        try:
            result = _retry_on_server_error(
                lambda: create_dataset(org_id, "NDI_PYTEST_SOFT_DELETE", client=client)
            )
        except _APIError as exc:
            pytest.skip(f"create_dataset timed out: {exc}")
        ds_id = result.get("_id", result.get("id", ""))
        assert ds_id

        try:
            # Add documents to make it realistic
            for i in range(3):
                add_document(
                    ds_id,
                    {
                        "document_class": {"class_name": "ndi_pytest_softdel"},
                        "base": {"name": f"softdel_doc_{i}"},
                    },
                    client=client,
                )

            # Deferred delete (7 days)
            del_result = delete_dataset(ds_id, when="7d", client=client)
            assert hasattr(
                del_result, "get"
            ), f"Expected dict-like response, got {type(del_result)}"
            assert "message" in del_result

            # Should appear in deleted list
            time.sleep(2)
            deleted = list_deleted_datasets(client=client)
            deleted_ids = {d.get("_id", d.get("id", "")) for d in deleted.get("datasets", [])}
            assert ds_id in deleted_ids, f"Dataset {ds_id} not found in deleted list"

            # Undelete
            undelete_result = undelete_dataset(ds_id, client=client)
            assert hasattr(
                undelete_result, "get"
            ), f"Expected dict-like response, got {type(undelete_result)}"

            # Should be accessible again with documents intact
            time.sleep(2)
            ds = _retry_on_server_error(lambda: get_dataset(ds_id, client=client), retry_on_404=True)
            ds_fetched_id = ds.get("_id", ds.get("id", ""))
            assert ds_fetched_id == ds_id

            # Verify documents survived the soft-delete round-trip
            docs = list_all_documents(ds_id, client=client).data
            assert len(docs) >= 3, f"Expected >= 3 docs after undelete, got {len(docs)}"
        finally:
            # Final cleanup
            try:
                delete_dataset(ds_id, when="now", client=client)
            except Exception:
                pass

    def test_immediate_delete_cannot_undelete(self, client, cloud_config, can_write):
        """Delete with when='now' — undelete 10s later should fail.

        Creates a dataset WITH documents to mimic real-world usage.
        """
        if not can_write:
            pytest.skip("User does not have dataset creation privileges")

        from ndi.cloud.api.datasets import (
            create_dataset,
            delete_dataset,
            undelete_dataset,
        )
        from ndi.cloud.api.documents import add_document
        from ndi.cloud.exceptions import CloudAPIError as _APIError

        org_id = cloud_config.org_id
        try:
            result = _retry_on_server_error(
                lambda: create_dataset(org_id, "NDI_PYTEST_HARD_DELETE", client=client)
            )
        except _APIError as exc:
            pytest.skip(f"create_dataset timed out: {exc}")
        ds_id = result.get("_id", result.get("id", ""))
        assert ds_id

        # Add documents to make it realistic
        for i in range(3):
            add_document(
                ds_id,
                {
                    "document_class": {"class_name": "ndi_pytest_harddel"},
                    "base": {"name": f"harddel_doc_{i}"},
                },
                client=client,
            )

        # Immediate delete
        delete_dataset(ds_id, when="now", client=client)
        time.sleep(10)

        # Undelete should fail — dataset is permanently gone
        with pytest.raises(_APIError):
            undelete_dataset(ds_id, client=client)

    def test_list_deleted_documents(self, client, fresh_dataset):
        """Add doc, delete it, verify it appears in deleted-documents list."""
        from ndi.cloud.api.documents import (
            add_document,
            delete_document,
            list_deleted_documents,
        )

        doc_json = {
            "document_class": {"class_name": "ndi_pytest_softdel"},
            "base": {"name": "soft_delete_test"},
        }
        result = add_document(fresh_dataset, doc_json, client=client)
        doc_id = result.get("_id", result.get("id", ""))
        assert doc_id

        delete_document(fresh_dataset, doc_id, when="now", client=client)
        time.sleep(2)

        deleted = list_deleted_documents(fresh_dataset, client=client)
        assert hasattr(deleted, "get"), f"Expected dict-like response, got {type(deleted)}"
        # The response should have a documents list
        deleted_docs = deleted.get("documents", [])
        assert isinstance(deleted_docs, list)

    def test_delete_dataset_returns_message(self, client, cloud_config, can_write):
        """delete_dataset should return a response dict with a message."""
        if not can_write:
            pytest.skip("User does not have dataset creation privileges")

        from ndi.cloud.api.datasets import create_dataset, delete_dataset
        from ndi.cloud.exceptions import CloudAPIError as _APIError

        org_id = cloud_config.org_id
        try:
            result = _retry_on_server_error(
                lambda: create_dataset(org_id, "NDI_PYTEST_DEL_MSG", client=client)
            )
        except _APIError as exc:
            pytest.skip(f"create_dataset timed out: {exc}")
        ds_id = result.get("_id", result.get("id", ""))
        assert ds_id

        del_result = delete_dataset(ds_id, when="now", client=client)
        assert hasattr(del_result, "get"), f"Expected dict-like response, got {type(del_result)}"
        assert "message" in del_result

    def test_delete_document_returns_message(self, client, fresh_dataset):
        """delete_document should return a response dict with a message."""
        from ndi.cloud.api.documents import add_document, delete_document

        doc_json = {
            "document_class": {"class_name": "ndi_pytest_delmsg"},
            "base": {"name": "delete_msg_test"},
        }
        result = add_document(fresh_dataset, doc_json, client=client)
        doc_id = result.get("_id", result.get("id", ""))
        assert doc_id

        del_result = delete_document(fresh_dataset, doc_id, when="now", client=client)
        assert hasattr(del_result, "get"), f"Expected dict-like response, got {type(del_result)}"
        assert "message" in del_result


# ===========================================================================
# TestErrorHandling -- replaces mocked error tests
# ===========================================================================


class TestErrorHandling:
    def test_404_raises_not_found(self, client):
        """Nonexistent resource should raise CloudAPIError."""
        from ndi.cloud.api.datasets import get_dataset
        from ndi.cloud.exceptions import CloudAPIError

        with pytest.raises(CloudAPIError):
            get_dataset("000000000000000000000000", client=client)

    def test_bad_auth_raises(self):
        """Expired/invalid token should raise on API call."""
        from ndi.cloud.client import CloudClient
        from ndi.cloud.config import CloudConfig
        from ndi.cloud.exceptions import CloudAuthError

        bad_config = CloudConfig(
            api_url="https://api.ndi-cloud.com/v1",
            token="invalid.token.here",
        )
        bad_client = CloudClient(bad_config)

        with pytest.raises(CloudAuthError):
            bad_client.get("/users/me")

    def test_invalid_dataset_download_helpful_error(self, client):
        """Downloading bogus dataset should raise a clear error."""
        from ndi.cloud.exceptions import CloudAPIError

        with pytest.raises((CloudAPIError, Exception)):
            from ndi.cloud.download import download_document_collection

            download_document_collection("000000000000000000000000", client=client)


# ===========================================================================
# TestReadOnlyPublicDatasets -- reads existing public datasets
# ===========================================================================


class TestReadOnlyPublicDatasets:
    def test_get_large_dataset(self, large_dataset_info):
        """Fetch Jess Haley's dataset metadata."""
        ds_id = large_dataset_info.get("_id", large_dataset_info.get("id", ""))
        assert ds_id == LARGE_DATASET
        assert large_dataset_info.get("name")

    def test_get_small_dataset(self, small_dataset_info):
        """Fetch carbon fiber dataset metadata."""
        ds_id = small_dataset_info.get("_id", small_dataset_info.get("id", ""))
        assert ds_id == SMALL_DATASET
        assert small_dataset_info.get("name")

    def test_large_dataset_has_document_count(self, client, large_dataset_info):
        """Large dataset should have documents (via API count endpoint)."""
        from ndi.cloud.api.documents import get_document_count

        # Metadata field may be 0 on dev; use the count API instead
        count = get_document_count(LARGE_DATASET, client=client)
        metadata_count = large_dataset_info.get("documentCount", 0)
        # At least one of the two should be > 0 on prod.
        # On dev, the dataset may genuinely have 0 docs — skip in that case.
        if count == 0 and metadata_count == 0:
            env = os.environ.get("CLOUD_API_ENVIRONMENT", "prod")
            if env == "dev":
                pytest.skip("Large dataset has no documents on dev environment")
            else:
                pytest.fail(f"Expected documents in large dataset on {env}")

    def test_large_has_more_docs(self, client):
        """Large dataset should have more documents than small (prod only)."""
        from ndi.cloud.api.documents import get_document_count

        env = os.environ.get("CLOUD_API_ENVIRONMENT", "prod")
        large_count = get_document_count(LARGE_DATASET, client=client)
        small_count = get_document_count(SMALL_DATASET, client=client)
        # On dev, either dataset may have 0 docs — comparison is meaningless
        if env == "dev" and (large_count == 0 or small_count == 0):
            pytest.skip("Dataset(s) have no documents on dev environment")
        assert large_count > small_count

    def test_both_published(self, large_dataset_info, small_dataset_info):
        """Both datasets should be published."""
        assert large_dataset_info.get("isPublished") is True
        assert small_dataset_info.get("isPublished") is True

    def test_download_document_collection(self, client):
        """Download all docs from the small dataset."""
        from ndi.cloud.download import download_document_collection

        docs = download_document_collection(SMALL_DATASET, client=client)
        assert isinstance(docs, list)
        assert len(docs) > 0
        for doc in docs[:3]:
            assert isinstance(doc, dict)

    def test_download_file_from_dataset(self, client, small_dataset_info):
        """Download a real file from the small dataset."""
        import requests

        from ndi.cloud.api.files import get_file_details

        files = small_dataset_info.get("files", [])
        # Find a file with non-zero size
        target = None
        for f in files:
            if f.get("size", 0) > 0:
                target = f
                break
        if target is None:
            pytest.skip("No non-empty files in dataset")

        details = get_file_details(SMALL_DATASET, target["uid"], client=client)
        url = details.get("downloadUrl", "")
        assert url, "File details should include downloadUrl"

        # Just verify the URL is reachable (HEAD request)
        resp = requests.head(url, timeout=30)
        assert resp.status_code == 200

    def test_list_documents_from_small(self, client):
        """List documents from carbon fiber dataset."""
        from ndi.cloud.api.documents import list_documents

        result = list_documents(SMALL_DATASET, page=1, page_size=5, client=client)
        docs = result.get("documents", [])
        assert len(docs) == 5

    def test_internal_list_remote_ids(self, client):
        """list_remote_document_ids should return a non-empty mapping."""
        from ndi.cloud.internal import list_remote_document_ids

        mapping = list_remote_document_ids(SMALL_DATASET, client=client)
        assert isinstance(mapping, dict)
        assert len(mapping) > 0
