"""
ndi.cloud.exceptions - Exception hierarchy for NDI Cloud operations.

MATLAB equivalent: error IDs like NDI:Cloud:AuthenticationFailed, etc.
"""

from __future__ import annotations


class CloudError(Exception):
    """Base exception for all NDI Cloud operations."""


class CloudAuthError(CloudError):
    """Authentication or authorization failure (401/403)."""


class CloudAPIError(CloudError):
    """HTTP error from the NDI Cloud API.

    Attributes:
        status_code: HTTP status code.
        response_body: Raw response body (str or dict).
    """

    def __init__(
        self,
        message: str,
        status_code: int = 0,
        response_body: object = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class CloudNotFoundError(CloudAPIError):
    """Resource not found (404)."""


class CloudSyncError(CloudError):
    """Sync engine failure."""


class CloudUploadError(CloudError):
    """Upload operation failure."""
