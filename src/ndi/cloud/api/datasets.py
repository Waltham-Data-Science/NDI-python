"""
ndi.cloud.api.datasets - Dataset CRUD, publish, and branch operations.

All functions accept a :class:`~ndi.cloud.client.CloudClient` as the
first argument.

MATLAB equivalents: +ndi/+cloud/+api/+datasets/*.m,
    +implementation/+datasets/*.m
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..client import CloudClient


def get_dataset(client: CloudClient, dataset_id: str) -> dict[str, Any]:
    """GET /datasets/{datasetId}"""
    return client.get("/datasets/{datasetId}", datasetId=dataset_id)


def create_dataset(
    client: CloudClient,
    org_id: str,
    name: str,
    description: str = "",
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


def update_dataset(
    client: CloudClient,
    dataset_id: str,
    **fields: Any,
) -> dict[str, Any]:
    """POST /datasets/{datasetId}"""
    return client.post(
        "/datasets/{datasetId}",
        json=fields,
        datasetId=dataset_id,
    )


def delete_dataset(
    client: CloudClient,
    dataset_id: str,
    when: str = "7d",
) -> dict[str, Any]:
    """DELETE /datasets/{datasetId}?when=...

    Soft-delete a dataset.  The *when* parameter controls how long before
    the dataset and its documents are permanently pruned:

    - ``'now'``  — immediate hard delete
    - ``'7d'``   — prune after 7 days (default)
    - ``'24h'``  — prune after 24 hours
    - ``'30m'``  — prune after 30 minutes
    """
    return client.delete(
        "/datasets/{datasetId}",
        params={"when": when},
        datasetId=dataset_id,
    )


def list_datasets(
    client: CloudClient,
    org_id: str,
    page: int = 1,
    page_size: int = 1000,
) -> dict[str, Any]:
    """GET /organizations/{organizationId}/datasets?page=&pageSize="""
    return client.get(
        "/organizations/{organizationId}/datasets",
        params={"page": page, "pageSize": page_size},
        organizationId=org_id,
    )


_MAX_PAGES = 1000


def list_all_datasets(client: CloudClient, org_id: str) -> list[dict[str, Any]]:
    """Auto-paginate through all datasets for an organisation."""
    all_datasets: list[dict[str, Any]] = []
    page = 1
    while page <= _MAX_PAGES:
        result = list_datasets(client, org_id, page=page)
        datasets = result.get("datasets", [])
        all_datasets.extend(datasets)
        total = result.get("totalNumber", 0)
        if len(all_datasets) >= total or not datasets:
            break
        page += 1
    return all_datasets


def get_published_datasets(
    client: CloudClient,
    page: int = 1,
    page_size: int = 1000,
) -> dict[str, Any]:
    """GET /datasets/published"""
    return client.get(
        "/datasets/published",
        params={"page": page, "pageSize": page_size},
    )


def publish_dataset(client: CloudClient, dataset_id: str) -> dict[str, Any]:
    """POST /datasets/{datasetId}/publish"""
    return client.post("/datasets/{datasetId}/publish", datasetId=dataset_id)


def unpublish_dataset(client: CloudClient, dataset_id: str) -> dict[str, Any]:
    """POST /datasets/{datasetId}/unpublish"""
    return client.post("/datasets/{datasetId}/unpublish", datasetId=dataset_id)


def submit_dataset(client: CloudClient, dataset_id: str) -> dict[str, Any]:
    """POST /datasets/{datasetId}/submit"""
    return client.post("/datasets/{datasetId}/submit", datasetId=dataset_id)


def create_branch(client: CloudClient, dataset_id: str) -> dict[str, Any]:
    """POST /datasets/{datasetId}/branch"""
    return client.post("/datasets/{datasetId}/branch", datasetId=dataset_id)


def get_branches(client: CloudClient, dataset_id: str) -> list[dict[str, Any]]:
    """GET /datasets/{datasetId}/branches"""
    return client.get("/datasets/{datasetId}/branches", datasetId=dataset_id)


def get_unpublished(
    client: CloudClient,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """GET /datasets/unpublished

    MATLAB equivalent: +cloud/+api/+datasets/getUnpublished.m
    """
    return client.get(
        "/datasets/unpublished",
        params={"page": page, "pageSize": page_size},
    )


def undelete_dataset(client: CloudClient, dataset_id: str) -> dict[str, Any]:
    """POST /datasets/{datasetId}/undelete

    Reverse a deferred (soft) delete before the pruner runs.
    Raises :class:`~ndi.cloud.exceptions.CloudAPIError` if the dataset
    has already been permanently deleted.
    """
    return client.post("/datasets/{datasetId}/undelete", datasetId=dataset_id)


def list_deleted_datasets(
    client: CloudClient,
    page: int = 1,
    page_size: int = 1000,
) -> dict[str, Any]:
    """GET /datasets/deleted?page=&pageSize=

    Returns soft-deleted datasets that have not yet been pruned.
    """
    return client.get(
        "/datasets/deleted",
        params={"page": page, "pageSize": page_size},
    )
