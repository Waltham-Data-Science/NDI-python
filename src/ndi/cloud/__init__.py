"""
ndi.cloud - NDI Cloud REST API client, sync engine, and admin tools.

Provides authenticated access to the NDI Cloud platform for dataset
management, document CRUD, file transfer, sync, and DOI administration.

Quick start::

    from ndi.cloud import CloudConfig, CloudClient, login, logout

    config = login('user@example.com', 'password')
    client = CloudClient(config)

Requires the ``requests`` package.  Install with::

    pip install ndi[cloud]
"""

from .config import CloudConfig
from .exceptions import (
    CloudAPIError,
    CloudAuthError,
    CloudError,
    CloudNotFoundError,
    CloudSyncError,
    CloudUploadError,
)
from .auth import (
    authenticate, login, logout,
    change_password, reset_password, verify_user, resend_confirmation,
)

__all__ = [
    'CloudConfig',
    'CloudError',
    'CloudAPIError',
    'CloudAuthError',
    'CloudNotFoundError',
    'CloudSyncError',
    'CloudUploadError',
    'authenticate',
    'login',
    'logout',
    'change_password',
    'reset_password',
    'verify_user',
    'resend_confirmation',
]

# Lazy import for CloudClient (requires requests)


def __getattr__(name: str):
    if name == 'CloudClient':
        from .client import CloudClient
        return CloudClient
    raise AttributeError(f"module 'ndi.cloud' has no attribute {name!r}")
