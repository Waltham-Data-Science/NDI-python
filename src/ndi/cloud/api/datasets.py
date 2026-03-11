"""
ndi.cloud.api.datasets - Dataset CRUD, publish, and branch operations.

All functions accept an optional ``client`` keyword argument.  When omitted,
a client is created automatically from environment variables
(``NDI_CLOUD_TOKEN`` or ``NDI_CLOUD_USERNAME`` / ``NDI_CLOUD_PASSWORD``).

MATLAB equivalents: +ndi/+cloud/+api/+datasets/*.m,
    +implementation/+datasets/*.m
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import SkipValidation, validate_call

from ..client import APIResponse, CloudClient, _auto_client
from ._validators import VALIDATE_CONFIG, CloudId, NonEmptyStr, PageNumber, PageSize

_Client = Annotated[CloudClient | None, SkipValidation()]


def _resolve_org_id(org_id: str | None, client: CloudClient) -> str:
    """Return *org_id* if given, otherwise pull it from client config."""
    if org_id:
        return org_id
    resolved = getattr(client, "config", None)
    if resolved and getattr(resolved, "org_id", ""):
        return resolved.org_id
    raise ValueError(
        "org_id is required but was not provided and could not be "
        "resolved from the client config.  Either pass org_id explicitly "
        "or set NDI_CLOUD_ORGANIZATION_ID in the environment."
    )


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def getDataset(dataset_id: CloudId, *, client: _Client = None) -> dict[str, Any]:
    """GET /datasets/{datasetId}"""
    return client.get("/datasets/{datasetId}", datasetId=dataset_id)


@_auto_client
def createDataset(
    org_id: str | None = None,
    name: str = "",
    description: str = "",
    *,
    client: _Client = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """POST /organizations/{organizationId}/datasets

    If *org_id* is omitted it is resolved from the client's config
    (populated automatically during login), matching MATLAB behaviour.
    """
    org_id = _resolve_org_id(org_id, client)
    if not name:
        raise ValueError("name is required")
    body: dict[str, Any] = {"name": name}
    if description:
        body["description"] = description
    body.update(kwargs)
    return client.post(
        "/organizations/{organizationId}/datasets",
        json=body,
        organizationId=org_id,
    )


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def updateDataset(
    dataset_id: CloudId,
    *,
    client: _Client = None,
    **fields: Any,
) -> dict[str, Any]:
    """POST /datasets/{datasetId}"""
    return client.post(
        "/datasets/{datasetId}",
        json=fields,
        datasetId=dataset_id,
    )


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def deleteDataset(
    dataset_id: CloudId,
    when: str = "7d",
    *,
    client: _Client = None,
) -> dict[str, Any]:
    """DELETE /datasets/{datasetId}?when=...

    Soft-delete a dataset.  The *when* parameter controls how long before
    the dataset and its documents are permanently pruned:

    - ``'now'``  -- immediate hard delete
    - ``'7d'``   -- prune after 7 days (default)
    - ``'24h'``  -- prune after 24 hours
    - ``'30m'``  -- prune after 30 minutes
    """
    return client.delete(
        "/datasets/{datasetId}",
        params={"when": when},
        datasetId=dataset_id,
    )


@_auto_client
def listDatasets(
    org_id: str | None = None,
    page: int = 1,
    page_size: int = 1000,
    *,
    client: _Client = None,
) -> dict[str, Any]:
    """GET /organizations/{organizationId}/datasets?page=&pageSize=

    If *org_id* is omitted it is resolved from the client's config
    (populated automatically during login), matching MATLAB behaviour.
    """
    org_id = _resolve_org_id(org_id, client)
    return client.get(
        "/organizations/{organizationId}/datasets",
        params={"page": page, "pageSize": page_size},
        organizationId=org_id,
    )


_MAX_PAGES = 1000


@_auto_client
def listAllDatasets(org_id: str | None = None, *, client: _Client = None) -> APIResponse:
    """Auto-paginate through all datasets for an organisation.

    If *org_id* is omitted it is resolved from the client's config
    (populated automatically during login), matching MATLAB behaviour.
    """
    org_id = _resolve_org_id(org_id, client)
    all_datasets: list[dict[str, Any]] = []
    page = 1
    while page <= _MAX_PAGES:
        result = listDatasets(org_id, page=page, client=client)
        datasets = result.get("datasets", [])
        all_datasets.extend(datasets)
        total = result.get("totalNumber", 0)
        if len(all_datasets) >= total or not datasets:
            break
        page += 1
    return APIResponse(all_datasets, success=True, status_code=200, url="")


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def getPublished(
    page: PageNumber = 1,
    page_size: PageSize = 1000,
    *,
    client: _Client = None,
) -> dict[str, Any]:
    """GET /datasets/published"""
    return client.get(
        "/datasets/published",
        params={"page": page, "pageSize": page_size},
    )


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def publishDataset(dataset_id: CloudId, *, client: _Client = None) -> dict[str, Any]:
    """POST /datasets/{datasetId}/publish"""
    return client.post("/datasets/{datasetId}/publish", datasetId=dataset_id)


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def unpublishDataset(dataset_id: CloudId, *, client: _Client = None) -> dict[str, Any]:
    """POST /datasets/{datasetId}/unpublish"""
    return client.post("/datasets/{datasetId}/unpublish", datasetId=dataset_id)


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def submitDataset(dataset_id: CloudId, *, client: _Client = None) -> dict[str, Any]:
    """POST /datasets/{datasetId}/submit"""
    return client.post("/datasets/{datasetId}/submit", datasetId=dataset_id)


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def createDatasetBranch(dataset_id: CloudId, *, client: _Client = None) -> dict[str, Any]:
    """POST /datasets/{datasetId}/branch"""
    return client.post("/datasets/{datasetId}/branch", datasetId=dataset_id)


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def getBranches(dataset_id: CloudId, *, client: _Client = None) -> list[dict[str, Any]]:
    """GET /datasets/{datasetId}/branches"""
    return client.get("/datasets/{datasetId}/branches", datasetId=dataset_id)


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def getUnpublished(
    page: PageNumber = 1,
    page_size: PageSize = 20,
    *,
    client: _Client = None,
) -> dict[str, Any]:
    """GET /datasets/unpublished

    MATLAB equivalent: +cloud/+api/+datasets/getUnpublished.m
    """
    return client.get(
        "/datasets/unpublished",
        params={"page": page, "pageSize": page_size},
    )


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def undeleteDataset(dataset_id: CloudId, *, client: _Client = None) -> dict[str, Any]:
    """POST /datasets/{datasetId}/undelete

    Reverse a deferred (soft) delete before the pruner runs.
    Raises :class:`~ndi.cloud.exceptions.CloudAPIError` if the dataset
    has already been permanently deleted.
    """
    return client.post("/datasets/{datasetId}/undelete", datasetId=dataset_id)


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def listDeletedDatasets(
    page: PageNumber = 1,
    page_size: PageSize = 1000,
    *,
    client: _Client = None,
) -> dict[str, Any]:
    """GET /datasets/deleted?page=&pageSize=

    Returns soft-deleted datasets that have not yet been pruned.
    """
    return client.get(
        "/datasets/deleted",
        params={"page": page, "pageSize": page_size},
    )
