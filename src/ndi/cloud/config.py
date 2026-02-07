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
from dataclasses import dataclass, field
from typing import Optional

# ── URL presets (from MATLAB url.m) ──────────────────────────────────────
_API_URLS = {
    'prod': 'https://api.ndi-cloud.com/v1',
    'dev': 'https://dev-api.ndi-cloud.com/v1',
}


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

    api_url: str = ''
    token: str = ''
    org_id: str = ''
    upload_no_zip: bool = False
    username: str = ''
    password: str = ''

    # ── Factory ───────────────────────────────────────────────────────
    @classmethod
    def from_env(cls) -> 'CloudConfig':
        """Create a CloudConfig from environment variables."""
        # Determine API URL
        api_url = os.environ.get('NDI_CLOUD_URL', '')
        if not api_url:
            env = os.environ.get('CLOUD_API_ENVIRONMENT', 'prod')
            api_url = _API_URLS.get(env, _API_URLS['prod'])

        upload_no_zip_raw = os.environ.get('NDI_CLOUD_UPLOAD_NO_ZIP', '')
        upload_no_zip = upload_no_zip_raw.lower() in ('true', '1', 'yes')

        return cls(
            api_url=api_url,
            token=os.environ.get('NDI_CLOUD_TOKEN', ''),
            org_id=os.environ.get('NDI_CLOUD_ORGANIZATION_ID', ''),
            upload_no_zip=upload_no_zip,
            username=os.environ.get('NDI_CLOUD_USERNAME', ''),
            password=os.environ.get('NDI_CLOUD_PASSWORD', ''),
        )

    # ── Helpers ───────────────────────────────────────────────────────
    @property
    def is_authenticated(self) -> bool:
        """True if a non-empty token is present."""
        return bool(self.token)

    def __repr__(self) -> str:
        masked = (self.token[:8] + '...') if len(self.token) > 8 else '***'
        return (
            f"CloudConfig(api_url={self.api_url!r}, "
            f"token={masked!r}, org_id={self.org_id!r})"
        )
