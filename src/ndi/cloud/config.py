"""
ndi.cloud.config - Configuration for NDI Cloud API connections.

Reads settings from environment variables, matching MATLAB's ndi.cloud.api.url()
and authenticate() patterns.

Environment variables:
    NDI_CLOUD_TOKEN           — JWT bearer token
    NDI_CLOUD_ORGANIZATION_ID — Organisation ID
    NDI_CLOUD_URL             — Full API base URL override
    CLOUD_API_ENVIRONMENT     — 'prod' (default) or 'dev'
    NDI_CLOUD_UPLOAD_NO_ZIP   — 'true' to skip ZIP on upload
    NDI_CLOUD_USERNAME        — Email for auto-login
    NDI_CLOUD_PASSWORD        — Password for auto-login
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# ── URL presets (from MATLAB url.m) ──────────────────────────────────────
_API_URLS = {
    "prod": "https://api.ndi-cloud.com/v1",
    "dev": "https://dev-api.ndi-cloud.com/v1",
}


def _profile_stage() -> str:
    """The Stage ('prod'/'dev') of the cloud profile that would be used.

    NDI-matlab's profile.switchProfile does ``setenv('CLOUD_API_ENVIRONMENT',
    prof.Stage)`` and api/url.m reads it back, so Stage naming the API
    environment is the established contract, not an invention here.

    Empty string when there is no usable profile. Every failure mode is
    benign -- no profile file, no default set, a secrets backend that will
    not load -- and none should stop a config from being built.
    """
    try:
        from . import profile as _profile

        entry = _profile.get_current() or _profile.get_default()
        return entry.Stage if entry is not None else ""
    except Exception:  # noqa: BLE001 - see docstring
        return ""


@dataclass
class CloudConfig:
    """NDI Cloud connection configuration.

    Can be built manually or from environment variables via ``from_env()``.

    Example::

        config = CloudConfig.from_env()
        # or
        config = CloudConfig(api_url='https://api.ndi-cloud.com/v1',
                             token='eyJ...', org_id='org-123')
    """

    api_url: str = ""
    token: str = ""
    org_id: str = ""
    upload_no_zip: bool = False
    username: str = ""
    password: str = ""

    # ── Factory ───────────────────────────────────────────────────────
    @classmethod
    def from_env(cls) -> CloudConfig:
        """Create a CloudConfig from environment variables."""
        # Determine API URL. Precedence: an explicit URL, then an explicit
        # environment, then the saved profile's Stage, then prod.
        #
        # The profile step has to be HERE rather than at the point of login.
        # login() exports NDI_CLOUD_TOKEN, so every later from_env() carries a
        # valid token and authenticate() returns at its first step without
        # ever reaching the credential path -- which meant a dev profile
        # logged in against dev and then issued every subsequent request
        # against prod, where the dataset 404s.
        api_url = os.environ.get("NDI_CLOUD_URL", "")
        if not api_url:
            env = os.environ.get("CLOUD_API_ENVIRONMENT", "") or _profile_stage() or "prod"
            api_url = _API_URLS.get(env, _API_URLS["prod"])

        upload_no_zip_raw = os.environ.get("NDI_CLOUD_UPLOAD_NO_ZIP", "")
        upload_no_zip = upload_no_zip_raw.lower() in ("true", "1", "yes")

        return cls(
            api_url=api_url,
            token=os.environ.get("NDI_CLOUD_TOKEN", ""),
            org_id=os.environ.get("NDI_CLOUD_ORGANIZATION_ID", ""),
            upload_no_zip=upload_no_zip,
            username=os.environ.get("NDI_CLOUD_USERNAME", ""),
            password=os.environ.get("NDI_CLOUD_PASSWORD", ""),
        )

    # ── Helpers ───────────────────────────────────────────────────────
    @property
    def is_authenticated(self) -> bool:
        """True if a non-empty token is present."""
        return bool(self.token)

    def __repr__(self) -> str:
        masked = (self.token[:8] + "...") if len(self.token) > 8 else "***"
        return (
            f"CloudConfig(api_url={self.api_url!r}, " f"token={masked!r}, org_id={self.org_id!r})"
        )
