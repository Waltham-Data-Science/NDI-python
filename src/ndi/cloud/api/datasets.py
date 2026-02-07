"""
ndi.cloud.api.datasets - Dataset CRUD, publish, and branch operations.

All functions accept a :class:`~ndi.cloud.client.CloudClient` as the
first argument.

MATLAB equivalents: +ndi/+cloud/+api/+datasets/*.m,
    +implementation/+datasets/*.m
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..client import CloudClient


def get_dataset(client: 'CloudClient', dataset_id: str) -> Dict[str, Any]:
    """GET /datasets/{datasetId}"""
    return client.get('/datasets/{datasetId}', datasetId=dataset_id)


def create_dataset(
    client: 'CloudClient',
    org_id: str,
    name: str,
    description: str = '',
    **kwargs: Any,
) -> Dict[str, Any]:
    """POST /organizations/{organizationId}/datasets"""
    body: Dict[str, Any] = {'name': name}
    if description:
        body['description'] = description
    body.update(kwargs)
    return client.post(
        '/organizations/{organizationId}/datasets',
        json=body,
        organizationId=org_id,
    )


def update_dataset(
    client: 'CloudClient',
    dataset_id: str,
    **fields: Any,
) -> Dict[str, Any]:
    """PUT /datasets/{datasetId}"""
    return client.put(
        '/datasets/{datasetId}',
        json=fields,
        datasetId=dataset_id,
    )


def delete_dataset(client: 'CloudClient', dataset_id: str) -> bool:
    """DELETE /datasets/{datasetId}"""
    client.delete('/datasets/{datasetId}', datasetId=dataset_id)
    return True


def list_datasets(
    client: 'CloudClient',
    org_id: str,
    page: int = 1,
    page_size: int = 1000,
) -> Dict[str, Any]:
    """GET /organizations/{organizationId}/datasets?page=&pageSize="""
    return client.get(
        '/organizations/{organizationId}/datasets',
        params={'page': page, 'pageSize': page_size},
        organizationId=org_id,
    )


_MAX_PAGES = 1000


def list_all_datasets(client: 'CloudClient', org_id: str) -> List[Dict[str, Any]]:
    """Auto-paginate through all datasets for an organisation."""
    all_datasets: List[Dict[str, Any]] = []
    page = 1
    while page <= _MAX_PAGES:
        result = list_datasets(client, org_id, page=page)
        datasets = result.get('datasets', [])
        all_datasets.extend(datasets)
        total = result.get('totalNumber', 0)
        if len(all_datasets) >= total or not datasets:
            break
        page += 1
    return all_datasets


def get_published_datasets(
    client: 'CloudClient',
    page: int = 1,
    page_size: int = 1000,
) -> Dict[str, Any]:
    """GET /datasets/published"""
    return client.get(
        '/datasets/published',
        params={'page': page, 'pageSize': page_size},
    )


def publish_dataset(client: 'CloudClient', dataset_id: str) -> Dict[str, Any]:
    """POST /datasets/{datasetId}/publish"""
    return client.post('/datasets/{datasetId}/publish', datasetId=dataset_id)


def unpublish_dataset(client: 'CloudClient', dataset_id: str) -> Dict[str, Any]:
    """POST /datasets/{datasetId}/unpublish"""
    return client.post('/datasets/{datasetId}/unpublish', datasetId=dataset_id)


def submit_dataset(client: 'CloudClient', dataset_id: str) -> Dict[str, Any]:
    """POST /datasets/{datasetId}/submit"""
    return client.post('/datasets/{datasetId}/submit', datasetId=dataset_id)


def create_branch(client: 'CloudClient', dataset_id: str) -> Dict[str, Any]:
    """POST /datasets/{datasetId}/branch"""
    return client.post('/datasets/{datasetId}/branch', datasetId=dataset_id)


def get_branches(client: 'CloudClient', dataset_id: str) -> List[Dict[str, Any]]:
    """GET /datasets/{datasetId}/branches"""
    return client.get('/datasets/{datasetId}/branches', datasetId=dataset_id)


def get_unpublished(
    client: 'CloudClient',
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """GET /datasets/unpublished

    MATLAB equivalent: +cloud/+api/+datasets/getUnpublished.m
    """
    return client.get(
        '/datasets/unpublished',
        params={'page': page, 'pageSize': page_size},
    )
