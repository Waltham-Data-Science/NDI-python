"""
ndi.cloud.api.datasets - ndi_dataset CRUD, publish, and branch operations.

All functions accept an optional ``client`` keyword argument.  When omitted,
a client is created automatically from environment variables
(``NDI_CLOUD_TOKEN`` or ``NDI_CLOUD_USERNAME`` / ``NDI_CLOUD_PASSWORD``).

MATLAB equivalents: +ndi/+cloud/+api/+datasets/*.m,
    +implementation/+datasets/*.m
"""

from __future__ import annotations

import time
from typing import Annotated, Any

from pydantic import SkipValidation, validate_call

from ..client import APIResponse, CloudClient, _auto_client
from ._validators import VALIDATE_CONFIG, CloudId, PageNumber, PageSize

_Client = Annotated[CloudClient | None, SkipValidation()]


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
    organization_name: str = "",
    client: _Client = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """POST /organizations/{organizationId}/datasets

    MATLAB equivalent: ndi.cloud.api.datasets.createDataset

    Creates a new dataset in one of the organizations the current user
    belongs to. Name the organization with *org_id* or *organization_name*
    (mutually exclusive). If neither is given and the user may upload to
    exactly one organization, that one is used; otherwise the user is asked
    to choose (when standard input is a terminal) or a
    :class:`~ndi.cloud.exceptions.CloudOrganizationError` lists the
    organizations. See :func:`ndi.cloud.internal.chooseOrganization`.
    """
    if not name:
        raise ValueError("name is required")
    from ..internal import chooseOrganization

    org_id, _ = chooseOrganization(
        organization_name,
        org_id or "",
        require_upload=True,
        prompt_string="Create the new dataset in which organization?",
        client=client,
    )
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


_MAX_PAGES = 1000


@_auto_client
def listDatasets(
    org_id: str | None = None,
    page: int = 1,
    page_size: int = 1000,
    *,
    client: _Client = None,
) -> dict[str, Any]:
    """GET /organizations/{organizationId}/datasets?page=&pageSize=

    MATLAB equivalent: ndi.cloud.api.datasets.listDatasets

    With *org_id*, retrieves one page of the datasets within that
    organization.

    Without *org_id*, retrieves ALL datasets in ALL of the organizations the
    current user belongs to (:func:`ndi.cloud.internal.getOrganizations`).
    NDI Cloud only lists datasets per organization, so this queries each
    organization in turn and fetches every page; *page* and *page_size* are
    ignored in this mode. Each returned dataset is tagged with the keys
    ``organizationId`` and ``organizationName`` of the organization it was
    listed under, and the answer's ``page`` is 1 while ``pageSize`` and
    ``totalNumber`` are the number of datasets returned.
    """
    if org_id:
        return client.get(
            "/organizations/{organizationId}/datasets",
            params={"page": page, "pageSize": page_size},
            organizationId=org_id,
        )

    from ..internal import getOrganizations

    datasets: list[dict[str, Any]] = []
    for organization in getOrganizations(client=client):
        for dataset in _listOrganizationDatasets(organization["id"], client):
            tagged = dict(dataset)
            tagged.setdefault("organizationId", organization["id"])
            tagged["organizationName"] = organization["name"]
            datasets.append(tagged)
    answer = {
        "totalNumber": len(datasets),
        "page": 1,
        "pageSize": len(datasets),
        "datasets": datasets,
    }
    return APIResponse(answer, success=True, status_code=200, url="")


def _listOrganizationDatasets(org_id: str, client: CloudClient) -> list[dict[str, Any]]:
    """Every dataset of one organization, fetching page after page."""
    all_datasets: list[dict[str, Any]] = []
    page = 1
    while page <= _MAX_PAGES:
        result = listDatasets(org_id, page=page, client=client)
        datasets = result.get("datasets", []) or []
        all_datasets.extend(datasets)
        total = result.get("totalNumber", 0)
        if len(all_datasets) >= total or not datasets:
            break
        page += 1
    return all_datasets


@_auto_client
def listAllDatasets(org_id: str | None = None, *, client: _Client = None) -> APIResponse:
    """Auto-paginate through all datasets for an organisation.

    Without *org_id*, lists every dataset in every organization the user
    belongs to, tagged as :func:`listDatasets` does.
    """
    if not org_id:
        return APIResponse(
            listDatasets(client=client).get("datasets", []),
            success=True,
            status_code=200,
            url="",
        )
    return APIResponse(
        _listOrganizationDatasets(org_id, client), success=True, status_code=200, url=""
    )


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


# ---------------------------------------------------------------------------
# Wait helpers
# ---------------------------------------------------------------------------


def _wait_for_published_state(
    dataset_id: str,
    *,
    desired: bool,
    timeout: float,
    initial_interval: float,
    max_interval: float,
    backoff_factor: float,
    client: CloudClient | None,
) -> dict[str, Any]:
    """Shared body for :func:`waitForPublished` / :func:`waitForUnpublished`.

    Polls ``getDataset`` at exponentially growing intervals until the
    dataset's ``isPublished`` field equals *desired* or the overall
    timeout elapses.
    """
    start = time.monotonic()
    interval = initial_interval
    last: Any = None
    while True:
        elapsed = time.monotonic() - start
        try:
            ds = getDataset(dataset_id, client=client)
            last = ds
            is_published = bool(ds.get("isPublished", False)) if hasattr(ds, "get") else False
            if is_published == desired:
                return ds
        except Exception:
            # Treat transient errors as not-yet-reached; let timeout govern.
            pass
        if elapsed + interval > timeout:
            payload: dict[str, Any]
            if last is not None and hasattr(last, "data") and isinstance(last.data, dict):
                payload = dict(last.data)
            elif isinstance(last, dict):
                payload = dict(last)
            else:
                payload = {}
            payload["state"] = "timeout"
            payload["elapsed"] = time.monotonic() - start
            return payload
        time.sleep(interval)
        interval = min(interval * backoff_factor, max_interval)


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def waitForPublished(
    dataset_id: CloudId,
    *,
    timeout: float = 180.0,
    initial_interval: float = 2.0,
    max_interval: float = 30.0,
    backoff_factor: float = 2.0,
    client: _Client = None,
) -> dict[str, Any]:
    """Poll a dataset until its ``isPublished`` flag is true.

    Repeatedly calls :func:`getDataset` at exponentially growing
    intervals until the dataset's ``isPublished`` field becomes ``True``
    or the overall timeout elapses.  The backend flips ``isPublished``
    from ``False`` to ``True`` only when publishing has completed, so
    this is the canonical signal that a publish workflow is finished.

    Args:
        dataset_id: The cloud dataset ID.
        timeout: Overall deadline in seconds.  Default 180.
        initial_interval: First sleep between polls (s).  Default 2.
        max_interval: Cap on the per-poll sleep (s).  Default 30.
        backoff_factor: Multiplier applied after each poll.  Default 2.

    Returns:
        The last dataset payload from the server.  On timeout, the
        returned dict has ``state='timeout'`` and ``elapsed`` set to
        the wall-clock seconds spent polling.

    MATLAB equivalent: +cloud/+api/+datasets/waitForPublished.m
    """
    return _wait_for_published_state(
        dataset_id,
        desired=True,
        timeout=timeout,
        initial_interval=initial_interval,
        max_interval=max_interval,
        backoff_factor=backoff_factor,
        client=client,
    )


@_auto_client
@validate_call(config=VALIDATE_CONFIG)
def waitForUnpublished(
    dataset_id: CloudId,
    *,
    timeout: float = 180.0,
    initial_interval: float = 2.0,
    max_interval: float = 30.0,
    backoff_factor: float = 2.0,
    client: _Client = None,
) -> dict[str, Any]:
    """Poll a dataset until its ``isPublished`` flag is false.

    See :func:`waitForPublished` for the polling semantics; this
    function waits for the opposite transition.

    MATLAB equivalent: +cloud/+api/+datasets/waitForUnpublished.m
    """
    return _wait_for_published_state(
        dataset_id,
        desired=False,
        timeout=timeout,
        initial_interval=initial_interval,
        max_interval=max_interval,
        backoff_factor=backoff_factor,
        client=client,
    )
