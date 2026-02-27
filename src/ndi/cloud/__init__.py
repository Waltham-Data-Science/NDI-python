"""
ndi.cloud - NDI Cloud REST API client, sync engine, and admin tools.

Provides authenticated access to the NDI Cloud platform for dataset
management, document CRUD, file transfer, sync, and DOI administration.

Quick start::

    # Option 1: Explicit client
    from ndi.cloud import CloudConfig, CloudClient, login

    config = login('user@example.com', 'password')
    client = CloudClient(config)
    ndi.cloud.api.datasets.get_dataset(dataset_id, client=client)

    # Option 2: Auto-client from environment variables (no client needed)
    #   Set NDI_CLOUD_USERNAME, NDI_CLOUD_PASSWORD (or NDI_CLOUD_TOKEN)
    ndi.cloud.api.datasets.get_dataset(dataset_id)

All ``ndi.cloud.api.*`` functions accept an optional ``client`` keyword
parameter.  If omitted, a client is built automatically from environment
variables.

Requires the ``requests`` package.  Install with::

    pip install ndi[cloud]
"""

from .auth import (
    authenticate,
    change_password,
    login,
    logout,
    resend_confirmation,
    reset_password,
    verify_user,
)
from .config import CloudConfig
from .exceptions import (
    CloudAPIError,
    CloudAuthError,
    CloudError,
    CloudNotFoundError,
    CloudSyncError,
    CloudUploadError,
)

__all__ = [
    "CloudConfig",
    "CloudError",
    "CloudAPIError",
    "CloudAuthError",
    "CloudNotFoundError",
    "CloudSyncError",
    "CloudUploadError",
    "authenticate",
    "login",
    "logout",
    "change_password",
    "reset_password",
    "verify_user",
    "resend_confirmation",
    # Top-level convenience functions (mirror MATLAB ndi.cloud.*)
    "download_dataset",
    "upload_dataset",
    "sync_dataset",
    "upload_single_file",
    "fetch_cloud_file",
]

# Lazy imports for symbols that depend on requests.
# CloudClient and the orchestration/upload convenience functions are
# resolved on first access so that ``import ndi.cloud`` never fails
# when requests is not installed.

_LAZY_IMPORTS = {
    # Python-style (primary)
    "APIResponse": ("client", "APIResponse"),
    "CloudClient": ("client", "CloudClient"),
    "download_dataset": ("orchestration", "download_dataset"),
    "upload_dataset": ("orchestration", "upload_dataset"),
    "sync_dataset": ("orchestration", "sync_dataset"),
    "upload_single_file": ("upload", "upload_single_file"),
    "fetch_cloud_file": ("filehandler", "fetch_cloud_file"),
    # MATLAB-style aliases (for users migrating from MATLAB)
    "downloadDataset": ("orchestration", "download_dataset"),
    "uploadDataset": ("orchestration", "upload_dataset"),
    "syncDataset": ("orchestration", "sync_dataset"),
    "uploadSingleFile": ("upload", "upload_single_file"),
}


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        module_name, attr = _LAZY_IMPORTS[name]
        import importlib

        mod = importlib.import_module(f".{module_name}", __name__)
        return getattr(mod, attr)
    raise AttributeError(f"module 'ndi.cloud' has no attribute {name!r}")
