"""
ndi.cloud.admin.doi - DOI generation and registration for NDI Cloud datasets.

MATLAB equivalent: +ndi/+cloud/+admin/createNewDoi.m,
    registerDatasetDoi.m, checkSubmission.m
"""

from __future__ import annotations

import os
import uuid
from typing import TYPE_CHECKING, Any

from .crossref import CONSTANTS, create_batch_submission

if TYPE_CHECKING:
    from ..client import CloudClient


def create_new_doi(prefix: str = "") -> str:
    """Generate a new unique DOI string.

    Args:
        prefix: DOI prefix (default: CrossrefConstants.DOI_PREFIX).

    Returns:
        A DOI string like ``10.63884/ndic.a1b2c3d4``.
    """
    if not prefix:
        prefix = CONSTANTS.DOI_PREFIX
    suffix = uuid.uuid4().hex[:8]
    return f"{prefix}/ndic.{suffix}"


def register_dataset_doi(
    cloud_dataset_id: str,
    use_test: bool = False,
    *,
    client: CloudClient | None = None,
) -> dict[str, Any]:
    """Register a DOI for a cloud dataset via Crossref.

    Fetches dataset metadata from the cloud, generates Crossref XML,
    and submits to the Crossref deposit API.

    Args:
        client: Authenticated cloud client.
        cloud_dataset_id: Cloud dataset ID.
        use_test: If True, use the Crossref test deposit endpoint.

    Returns:
        Dict with ``doi``, ``xml``, ``submission_status``.

    Raises:
        CloudError: If dataset fetch or submission fails.
    """
    import requests

    from ..api import datasets as ds_api
    from ..exceptions import CloudError

    # Fetch metadata
    metadata = ds_api.get_dataset(cloud_dataset_id, client=client)
    metadata["cloud_dataset_id"] = cloud_dataset_id

    # Generate DOI
    doi = create_new_doi()

    # Build XML
    xml = create_batch_submission(metadata, doi)

    # Submit to Crossref
    deposit_url = CONSTANTS.TEST_DEPOSIT_URL if use_test else CONSTANTS.DEPOSIT_URL
    crossref_user = os.environ.get("CROSSREF_USERNAME", "")
    crossref_pass = os.environ.get("CROSSREF_PASSWORD", "")

    if not crossref_user or not crossref_pass:
        return {
            "doi": doi,
            "xml": xml,
            "submission_status": "skipped",
            "reason": "CROSSREF_USERNAME/CROSSREF_PASSWORD not set",
        }

    try:
        resp = requests.post(
            deposit_url,
            data=xml.encode("utf-8"),
            headers={"Content-Type": "application/xml"},
            auth=(crossref_user, crossref_pass),
            timeout=60,
        )
        return {
            "doi": doi,
            "xml": xml,
            "submission_status": "submitted" if resp.status_code == 200 else "failed",
            "http_status": resp.status_code,
        }
    except requests.RequestException as exc:
        raise CloudError(f"Crossref submission failed: {exc}") from exc


def check_submission(
    filename: str,
    data_type: str = "result",
    use_test: bool = False,
) -> dict[str, Any]:
    """Check the status of a Crossref submission.

    Args:
        filename: The submission filename (doi_batch_id).
        data_type: ``'result'`` or ``'content'``.
        use_test: Use test endpoint.

    Returns:
        Dict with status information.
    """
    import requests

    base = CONSTANTS.TEST_DEPOSIT_URL if use_test else CONSTANTS.DEPOSIT_URL
    url = f"{base}?doi_batch_id={filename}&type={data_type}"

    crossref_user = os.environ.get("CROSSREF_USERNAME", "")
    crossref_pass = os.environ.get("CROSSREF_PASSWORD", "")

    if not crossref_user or not crossref_pass:
        return {"status": "skipped", "reason": "No credentials"}

    try:
        resp = requests.get(
            url,
            auth=(crossref_user, crossref_pass),
            timeout=60,
        )
        return {
            "status": "ok" if resp.status_code == 200 else "error",
            "http_status": resp.status_code,
            "body": resp.text,
        }
    except requests.RequestException as exc:
        return {"status": "error", "message": str(exc)}
