"""
Tests for Phase 10 Batch 1: Cloud Foundation.

Tests CloudConfig, exception hierarchy, JWT helpers, CloudClient, and auth flow.
All HTTP interactions are mocked — no real API calls.
"""

import base64
import json
import os
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from ndi.cloud.auth import (
    authenticate,
    decode_jwt,
    get_active_token,
    get_token_expiration,
    login,
    logout,
    verify_token,
)

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------
from ndi.cloud.config import _API_URLS, CloudConfig
from ndi.cloud.exceptions import (
    CloudAPIError,
    CloudAuthError,
    CloudError,
    CloudNotFoundError,
    CloudSyncError,
    CloudUploadError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_jwt(payload: dict, header: dict = None) -> str:
    """Build a fake JWT (unsigned) from a payload dict."""
    header = header or {"alg": "HS256", "typ": "JWT"}

    def _b64url(data: dict) -> str:
        raw = json.dumps(data, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{_b64url(header)}.{_b64url(payload)}.fakesignature"


def _make_valid_token(exp_offset: int = 3600) -> str:
    """Return a JWT that expires *exp_offset* seconds from now."""
    return _make_jwt({"exp": int(time.time()) + exp_offset, "email": "test@ndi.org"})


def _make_expired_token() -> str:
    """Return a JWT that expired 1 hour ago."""
    return _make_jwt({"exp": int(time.time()) - 3600, "email": "old@ndi.org"})


# ===========================================================================
# CloudConfig
# ===========================================================================


class TestCloudConfig:
    def test_defaults(self):
        cfg = CloudConfig()
        assert cfg.api_url == ""
        assert cfg.token == ""
        assert cfg.org_id == ""
        assert cfg.upload_no_zip is False

    def test_manual_construction(self):
        cfg = CloudConfig(
            api_url="https://api.test.com",
            token="tok",
            org_id="org-1",
        )
        assert cfg.api_url == "https://api.test.com"
        assert cfg.token == "tok"
        assert cfg.org_id == "org-1"

    def test_from_env_prod(self, monkeypatch):
        monkeypatch.delenv("NDI_CLOUD_URL", raising=False)
        monkeypatch.delenv("CLOUD_API_ENVIRONMENT", raising=False)
        monkeypatch.setenv("NDI_CLOUD_TOKEN", "mytoken")
        monkeypatch.setenv("NDI_CLOUD_ORGANIZATION_ID", "org-42")
        cfg = CloudConfig.from_env()
        assert cfg.api_url == _API_URLS["prod"]
        assert cfg.token == "mytoken"
        assert cfg.org_id == "org-42"

    def test_from_env_dev(self, monkeypatch):
        monkeypatch.delenv("NDI_CLOUD_URL", raising=False)
        monkeypatch.setenv("CLOUD_API_ENVIRONMENT", "dev")
        monkeypatch.setenv("NDI_CLOUD_TOKEN", "")
        cfg = CloudConfig.from_env()
        assert cfg.api_url == _API_URLS["dev"]

    def test_from_env_custom_url(self, monkeypatch):
        monkeypatch.setenv("NDI_CLOUD_URL", "https://custom.api.com/v2")
        cfg = CloudConfig.from_env()
        assert cfg.api_url == "https://custom.api.com/v2"

    def test_from_env_upload_no_zip(self, monkeypatch):
        monkeypatch.delenv("NDI_CLOUD_URL", raising=False)
        monkeypatch.delenv("CLOUD_API_ENVIRONMENT", raising=False)
        monkeypatch.setenv("NDI_CLOUD_UPLOAD_NO_ZIP", "true")
        cfg = CloudConfig.from_env()
        assert cfg.upload_no_zip is True

    def test_from_env_upload_no_zip_false(self, monkeypatch):
        monkeypatch.delenv("NDI_CLOUD_URL", raising=False)
        monkeypatch.delenv("CLOUD_API_ENVIRONMENT", raising=False)
        monkeypatch.setenv("NDI_CLOUD_UPLOAD_NO_ZIP", "false")
        cfg = CloudConfig.from_env()
        assert cfg.upload_no_zip is False

    def test_is_authenticated_true(self):
        cfg = CloudConfig(token="something")
        assert cfg.is_authenticated is True

    def test_is_authenticated_false(self):
        cfg = CloudConfig(token="")
        assert cfg.is_authenticated is False

    def test_repr_masks_token(self):
        cfg = CloudConfig(api_url="url", token="abcdefghij", org_id="org")
        r = repr(cfg)
        assert "abcdefghij" not in r
        assert "abcdefgh..." in r


# ===========================================================================
# Exceptions
# ===========================================================================


class TestExceptions:
    def test_hierarchy(self):
        assert issubclass(CloudAuthError, CloudError)
        assert issubclass(CloudAPIError, CloudError)
        assert issubclass(CloudNotFoundError, CloudAPIError)
        assert issubclass(CloudSyncError, CloudError)
        assert issubclass(CloudUploadError, CloudError)

    def test_cloud_api_error_attributes(self):
        err = CloudAPIError("bad", status_code=500, response_body={"msg": "err"})
        assert err.status_code == 500
        assert err.response_body == {"msg": "err"}
        assert "bad" in str(err)

    def test_cloud_not_found_is_api_error(self):
        err = CloudNotFoundError("gone", status_code=404)
        assert isinstance(err, CloudAPIError)
        assert err.status_code == 404

    def test_cloud_error_is_exception(self):
        assert issubclass(CloudError, Exception)


# ===========================================================================
# JWT helpers
# ===========================================================================


class TestJWT:
    def test_decode_jwt(self):
        payload = {"sub": "123", "email": "a@b.com", "exp": 9999999999}
        token = _make_jwt(payload)
        decoded = decode_jwt(token)
        assert decoded["sub"] == "123"
        assert decoded["email"] == "a@b.com"

    def test_decode_jwt_bad_token(self):
        with pytest.raises(CloudAuthError, match="decode"):
            decode_jwt("not-a-jwt")

    def test_get_token_expiration(self):
        future = int(time.time()) + 7200
        token = _make_jwt({"exp": future})
        exp_dt = get_token_expiration(token)
        assert isinstance(exp_dt, datetime)
        assert exp_dt.tzinfo == timezone.utc
        assert abs(exp_dt.timestamp() - future) < 1

    def test_get_token_expiration_missing_exp(self):
        token = _make_jwt({"email": "noexp@test.com"})
        with pytest.raises(CloudAuthError, match="exp"):
            get_token_expiration(token)

    def test_verify_token_valid(self):
        assert verify_token(_make_valid_token()) is True

    def test_verify_token_expired(self):
        assert verify_token(_make_expired_token()) is False

    def test_verify_token_empty(self):
        assert verify_token("") is False

    def test_get_active_token_valid(self):
        cfg = CloudConfig(token=_make_valid_token(), org_id="org-1")
        tok, org = get_active_token(cfg)
        assert tok == cfg.token
        assert org == "org-1"

    def test_get_active_token_expired(self):
        cfg = CloudConfig(token=_make_expired_token())
        with pytest.raises(CloudAuthError, match="expired"):
            get_active_token(cfg)

    def test_get_active_token_missing(self):
        cfg = CloudConfig(token="")
        with pytest.raises(CloudAuthError, match="No token"):
            get_active_token(cfg)


# ===========================================================================
# CloudClient
# ===========================================================================


class TestCloudClient:
    @pytest.fixture
    def client(self):
        from ndi.cloud.client import CloudClient

        cfg = CloudConfig(
            api_url="https://api.test.ndi/v1",
            token="test.jwt.token",
            org_id="org-1",
        )
        return CloudClient(cfg)

    def test_build_url_simple(self, client):
        url = client._build_url("/datasets")
        assert url == "https://api.test.ndi/v1/datasets"

    def test_build_url_with_params(self, client):
        url = client._build_url(
            "/datasets/{datasetId}/documents/{documentId}",
            datasetId="ds-1",
            documentId="doc-2",
        )
        assert url == "https://api.test.ndi/v1/datasets/ds-1/documents/doc-2"

    def test_build_url_missing_param(self, client):
        with pytest.raises(ValueError, match="Missing path parameters"):
            client._build_url("/datasets/{datasetId}")

    def test_build_url_trailing_slash(self):
        from ndi.cloud.client import CloudClient

        cfg = CloudConfig(api_url="https://api.test.ndi/v1/")
        c = CloudClient(cfg)
        url = c._build_url("/datasets")
        assert url == "https://api.test.ndi/v1/datasets"

    def test_get_sends_auth_header(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"ok": true}'
        mock_resp.json.return_value = {"ok": True}

        client._session.request = MagicMock(return_value=mock_resp)
        result = client.get("/datasets")

        call_args = client._session.request.call_args
        assert call_args[1]["headers"]["Authorization"] == "Bearer test.jwt.token"
        assert result == {"ok": True}

    def test_post_sends_json(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.content = b'{"id": "new"}'
        mock_resp.json.return_value = {"id": "new"}

        client._session.request = MagicMock(return_value=mock_resp)
        result = client.post("/datasets", json={"name": "test"})

        call_args = client._session.request.call_args
        assert call_args[1]["json"] == {"name": "test"}
        assert result == {"id": "new"}

    def test_404_raises_not_found(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not found"

        client._session.request = MagicMock(return_value=mock_resp)
        with pytest.raises(CloudNotFoundError):
            client.get("/datasets/{datasetId}", datasetId="missing")

    def test_401_raises_auth_error(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"

        client._session.request = MagicMock(return_value=mock_resp)
        with pytest.raises(CloudAuthError):
            client.get("/datasets")

    def test_500_raises_api_error(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_resp.json.side_effect = Exception("not json")

        client._session.request = MagicMock(return_value=mock_resp)
        with pytest.raises(CloudAPIError) as exc_info:
            client.get("/datasets")
        assert exc_info.value.status_code == 500

    def test_empty_response_returns_none(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_resp.content = b""

        client._session.request = MagicMock(return_value=mock_resp)
        assert client.delete("/datasets/{datasetId}", datasetId="ds-1") is None

    def test_repr(self, client):
        assert "CloudClient" in repr(client)
        assert "api.test.ndi" in repr(client)


# ===========================================================================
# Auth flow (login / logout / authenticate)
# ===========================================================================


class TestAuth:
    def _mock_login_response(self, token="new.jwt.token", org_id="org-new"):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "token": token,
            "user": {"organizations": {"id": org_id}},
        }
        return resp

    @patch("requests.post")
    def test_login_success(self, mock_post, monkeypatch):
        monkeypatch.delenv("NDI_CLOUD_TOKEN", raising=False)
        monkeypatch.delenv("NDI_CLOUD_ORGANIZATION_ID", raising=False)

        mock_post.return_value = self._mock_login_response()

        cfg = CloudConfig(api_url="https://api.test.ndi/v1")
        result = login("user@ndi.org", "pass123", cfg)

        assert result.token == "new.jwt.token"
        assert result.org_id == "org-new"
        assert os.environ.get("NDI_CLOUD_TOKEN") == "new.jwt.token"
        assert os.environ.get("NDI_CLOUD_ORGANIZATION_ID") == "org-new"

        # Cleanup
        os.environ.pop("NDI_CLOUD_TOKEN", None)
        os.environ.pop("NDI_CLOUD_ORGANIZATION_ID", None)

    @patch("requests.post")
    def test_login_failure(self, mock_post):
        resp = MagicMock()
        resp.status_code = 401
        resp.text = "Invalid credentials"
        mock_post.return_value = resp

        cfg = CloudConfig(api_url="https://api.test.ndi/v1")
        with pytest.raises(CloudAuthError, match="401"):
            login("user@ndi.org", "wrong", cfg)

    def test_login_missing_credentials(self):
        cfg = CloudConfig(api_url="https://api.test.ndi/v1")
        with pytest.raises(CloudAuthError, match="required"):
            login("", "", cfg)

    @patch("requests.post")
    def test_logout_clears_env(self, mock_post, monkeypatch):
        monkeypatch.setenv("NDI_CLOUD_TOKEN", "old")
        monkeypatch.setenv("NDI_CLOUD_ORGANIZATION_ID", "old-org")

        mock_post.return_value = MagicMock(status_code=200)

        cfg = CloudConfig(api_url="https://api.test.ndi/v1", token="old")
        logout(cfg)

        assert os.environ.get("NDI_CLOUD_TOKEN") is None
        assert os.environ.get("NDI_CLOUD_ORGANIZATION_ID") is None
        assert cfg.token == ""

    def test_authenticate_with_valid_token(self):
        valid = _make_valid_token()
        cfg = CloudConfig(api_url="https://api.test.ndi/v1", token=valid)
        result = authenticate(cfg)
        assert result == valid

    def test_authenticate_no_token_no_creds(self, monkeypatch):
        monkeypatch.delenv("NDI_CLOUD_TOKEN", raising=False)
        monkeypatch.delenv("NDI_CLOUD_USERNAME", raising=False)
        monkeypatch.delenv("NDI_CLOUD_PASSWORD", raising=False)

        cfg = CloudConfig(api_url="https://api.test.ndi/v1")
        with pytest.raises(CloudAuthError, match="No valid token"):
            authenticate(cfg)

    @patch("requests.post")
    def test_login_with_org_list(self, mock_post, monkeypatch):
        """Test login when organizations is a list instead of dict."""
        monkeypatch.delenv("NDI_CLOUD_TOKEN", raising=False)
        monkeypatch.delenv("NDI_CLOUD_ORGANIZATION_ID", raising=False)

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "token": "tok",
            "user": {"organizations": [{"id": "org-list-1"}]},
        }
        mock_post.return_value = resp

        cfg = CloudConfig(api_url="https://api.test.ndi/v1")
        result = login("u@t.com", "p", cfg)
        assert result.org_id == "org-list-1"

        os.environ.pop("NDI_CLOUD_TOKEN", None)
        os.environ.pop("NDI_CLOUD_ORGANIZATION_ID", None)


# ===========================================================================
# Package-level imports
# ===========================================================================


class TestPackageImports:
    def test_import_cloud_from_ndi(self):
        import ndi

        assert hasattr(ndi, "cloud")

    def test_import_config(self):
        from ndi.cloud import CloudConfig

        assert CloudConfig is not None

    def test_import_exceptions(self):
        from ndi.cloud import CloudAuthError, CloudError

        assert issubclass(CloudAuthError, CloudError)

    def test_import_auth_functions(self):
        from ndi.cloud import authenticate, login, logout

        assert callable(authenticate)
        assert callable(login)
        assert callable(logout)

    def test_import_client_lazy(self):
        from ndi.cloud import CloudClient

        assert CloudClient is not None
