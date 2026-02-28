"""
ndi.cloud.api.datasets - Dataset CRUD, publish, and branch operations.

All functions accept an optional ``client`` keyword argument.  When omitted,
a client is created automatically from environment variables
(``NDI_CLOUD_TOKEN`` or ``NDI_CLOUD_USERNAME`` / ``NDI_CLOUD_PASSWORD``).

MATLAB equivalents: +ndi/+cloud/+api/+datasets/*.m,
    +implementation/+datasets/*.m
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..client import APIResponse, _auto_client

if TYPE_CHECKING:
    from ..client import CloudClient


@_auto_client
def get_dataset(dataset_id: str, *, client: CloudClient | None = None) -> dict[str, Any]:
    """GET /datasets/{datasetId}"""
    return client.get("/datasets/{datasetId}", datasetId=dataset_id)


@_auto_client
def create_dataset(
    org_id: str,
    name: str,
    description: str = "",
    *,
    client: CloudClient | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """POST /organizations/{organizationId}/datasets"""
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
def update_dataset(
    dataset_id: str,
    *,
    client: CloudClient | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """POST /datasets/{datasetId}"""
    return client.post(
        "/datasets/{datasetId}",
        json=fields,
        datasetId=dataset_id,
    )


@_auto_client
def delete_dataset(
    dataset_id: str,
    when: str = "7d",
    *,
    client: CloudClient | None = None,
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
def list_datasets(
    org_id: str,
    page: int = 1,
    page_size: int = 1000,
    *,
    client: CloudClient | None = None,
) -> dict[str, Any]:
    """GET /organizations/{organizationId}/datasets?page=&pageSize="""
    return client.get(
        "/organizations/{organizationId}/datasets",
        params={"page": page, "pageSize": page_size},
        organizationId=org_id,
    )


_MAX_PAGES = 1000


@_auto_client
def list_all_datasets(org_id: str, *, client: CloudClient | None = None) -> list[dict[str, Any]]:
    """Auto-paginate through all datasets for an organisation."""
    all_datasets: list[dict[str, Any]] = []
    page = 1
    while page <= _MAX_PAGES:
        result = list_datasets(org_id, page=page, client=client)
        datasets = result.get("datasets", [])
        all_datasets.extend(datasets)
        total = result.get("totalNumber", 0)
        if len(all_datasets) >= total or not datasets:
            break
        page += 1
    return APIResponse(all_datasets, success=True, status_code=200, url="")


@_auto_client
def get_published_datasets(
    page: int = 1,
    page_size: int = 1000,
    *,
    client: CloudClient | None = None,
) -> dict[str, Any]:
    """GET /datasets/published"""
    return client.get(
        "/datasets/published",
        params={"page": page, "pageSize": page_size},
    )


@_auto_client
def publish_dataset(dataset_id: str, *, client: CloudClient | None = None) -> dict[str, Any]:
    """POST /datasets/{datasetId}/publish"""
    return client.post("/datasets/{datasetId}/publish", datasetId=dataset_id)


@_auto_client
def unpublish_dataset(dataset_id: str, *, client: CloudClient | None = None) -> dict[str, Any]:
    """POST /datasets/{datasetId}/unpublish"""
    return client.post("/datasets/{datasetId}/unpublish", datasetId=dataset_id)


@_auto_client
def submit_dataset(dataset_id: str, *, client: CloudClient | None = None) -> dict[str, Any]:
    """POST /datasets/{datasetId}/submit"""
    return client.post("/datasets/{datasetId}/submit", datasetId=dataset_id)


@_auto_client
def create_branch(dataset_id: str, *, client: CloudClient | None = None) -> dict[str, Any]:
    """POST /datasets/{datasetId}/branch"""
    return client.post("/datasets/{datasetId}/branch", datasetId=dataset_id)


@_auto_client
def get_branches(dataset_id: str, *, client: CloudClient | None = None) -> list[dict[str, Any]]:
    """GET /datasets/{datasetId}/branches"""
    return client.get("/datasets/{datasetId}/branches", datasetId=dataset_id)


@_auto_client
def get_unpublished(
    page: int = 1,
    page_size: int = 20,
    *,
    client: CloudClient | None = None,
) -> dict[str, Any]:
    """GET /datasets/unpublished

    MATLAB equivalent: +cloud/+api/+datasets/getUnpublished.m
    """
    return client.get(
        "/datasets/unpublished",
        params={"page": page, "pageSize": page_size},
    )


@_auto_client
def undelete_dataset(dataset_id: str, *, client: CloudClient | None = None) -> dict[str, Any]:
    """POST /datasets/{datasetId}/undelete

    Reverse a deferred (soft) delete before the pruner runs.
    Raises :class:`~ndi.cloud.exceptions.CloudAPIError` if the dataset
    has already been permanently deleted.
    """
    return client.post("/datasets/{datasetId}/undelete", datasetId=dataset_id)


@_auto_client
def list_deleted_datasets(
    page: int = 1,
    page_size: int = 1000,
    *,
    client: CloudClient | None = None,
) -> dict[str, Any]:
    """GET /datasets/deleted?page=&pageSize=

    Returns soft-deleted datasets that have not yet been pruned.
    """
    return client.get(
        "/datasets/deleted",
        params={"page": page, "pageSize": page_size},
    )
