"""The NDI Cloud actions behind the datasets pane's menu.

MATLAB counterpart: the cloud action methods of
``src/ndi/+ndi/+gui/+nav/datasetsPane.m`` (``cloudCheckStatus``,
``cloudUploadDataset``, ``cloudCheckForNew``, ``cloudSync``, ``cloudMirror``)

Each action here does the work and RETURNS what happened. It never shows a
dialog, never touches a widget and never raises: a failure comes back as a
result with ``ok`` False and the reason in ``message``. The pane's job is
then only to display it.

That shape is what makes these testable at all -- MATLAB's versions are
interleaved with ``uiprogressdlg`` and ``uialert`` calls, so the decision of
WHAT to tell the user cannot be checked without a display. Here it can.

TWO THINGS THE PORT HAD TO BRIDGE

MATLAB's sync functions take a dataset (``ndi.cloud.sync.uploadNew(ds)``);
Python's take a path and a resolved cloud id
(``uploadNew(dataset_path, cloud_dataset_id)``). :func:`resolve_cloud_target`
does that resolution once, and turns "this dataset is not linked to the
cloud" into a clear message rather than a stack trace.

MATLAB's sync reports name their fields ``uploaded_document_ids`` and so on;
Python's name them ``uploaded``. ``sync_result_message`` accepts both, so a
real sync report is summarised correctly whichever layer produced it. See
its note -- the underlying divergence is a library-level question, not a GUI
one.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from .datasets_text import cloud_check_message, sync_result_message

__all__ = [
    "CloudActionResult",
    "SYNC_MODES",
    "MIRROR_MODES",
    "mirror_prompt",
    "resolve_cloud_target",
    "check_cloud_status",
    "upload_dataset",
    "check_for_new",
    "sync_dataset",
    "mirror_dataset",
]


class CloudActionResult(NamedTuple):
    """What an action did, in the terms the pane needs to report it.

    ``state`` is the dataset's new cloud state (``"incloud"`` /
    ``"notincloud"``) when the action established one, and None when it did
    not. An action that FAILED never reports a state: not knowing must not
    be recorded as a definite answer.
    """

    ok: bool
    title: str
    message: str
    icon: str = "info"
    state: str | None = None


#: The additive sync modes, mapping the pane's command to the sync function
#: name and the dialog title. None of these delete anything, which is why
#: they need no confirmation.
SYNC_MODES: dict[str, tuple[str, str]] = {
    "download_new": ("downloadNew", "Download New from Cloud"),
    "upload_new": ("uploadNew", "Upload New to Cloud"),
    "two_way_sync": ("twoWaySync", "Two-Way Sync"),
}

#: The mirror modes. Both DELETE documents, so each is gated on a
#: confirmation the pane must obtain first -- see :func:`mirror_prompt`.
MIRROR_MODES: dict[str, tuple[str, str]] = {
    "from_remote": ("mirrorFromRemote", "Mirror from Cloud"),
    "to_remote": ("mirrorToRemote", "Mirror to Cloud"),
}

_MIRROR_PROMPTS: dict[str, str] = {
    "from_remote": (
        "Mirror from Cloud will make this local dataset an exact copy of the "
        "cloud dataset. Any local documents that are not on the cloud will be "
        "permanently DELETED from the local dataset. This cannot be undone. "
        "Are you sure?"
    ),
    "to_remote": (
        "Mirror to Cloud will make the cloud dataset an exact copy of this "
        "local dataset. Any cloud documents that are not present locally will "
        "be permanently DELETED from the cloud dataset. This cannot be undone. "
        "Are you sure?"
    ),
}


def mirror_prompt(direction: str) -> tuple[str, str]:
    """The confirmation ``(title, prompt)`` for a mirror DIRECTION.

    Kept separate from :func:`mirror_dataset` so the warning text is
    checkable on its own, and so the destructive step cannot be reached
    without the caller having asked for the prompt. Both directions delete
    documents permanently, and the prompt says which side loses them --
    a mirror that deletes the wrong side is not recoverable.
    """
    if direction not in _MIRROR_PROMPTS:
        raise ValueError(f"direction must be one of {sorted(_MIRROR_PROMPTS)}; got {direction!r}.")
    return MIRROR_MODES[direction][1], _MIRROR_PROMPTS[direction]


def resolve_cloud_target(dataset: Any) -> tuple[str, str]:
    """The ``(dataset_path, cloud_dataset_id)`` the sync functions need.

    MATLAB's sync functions take the dataset itself; Python's take a path
    and an already-resolved cloud id, so this does that step once.

    Raises:
        ValueError: When the dataset is not linked to a cloud dataset, with
            the message the user should see. "Not linked" is a different
            situation from "nothing to sync" and must not be reported as a
            successful no-op.
    """
    from ...cloud.internal import getCloudDatasetIdForLocalDataset

    try:
        cloud_id, _ = getCloudDatasetIdForLocalDataset(dataset)
    except Exception as exc:  # noqa: BLE001 - turned into a user-facing message
        raise ValueError(f"Could not determine the cloud dataset id: {exc}") from exc
    if not cloud_id:
        raise ValueError(
            "This dataset is not linked to a cloud dataset. Use "
            '"Upload to Cloud" to add it first.'
        )
    return _dataset_path(dataset), cloud_id


def _dataset_path(dataset: Any) -> str:
    for name in ("getpath", "path"):
        attr = getattr(dataset, name, None)
        if attr is None:
            continue
        value = attr() if callable(attr) else attr
        if value:
            return str(value)
    raise ValueError("This dataset has no local path.")


def check_cloud_status(dataset: Any) -> CloudActionResult:
    """Is DATASET linked to NDI Cloud? (the "Check Cloud status" command)

    The only cloud action that asks the dataset itself rather than the
    network: ``is_in_cloud`` is a local check for the ``dataset_remote``
    document. Because it is on demand, the cost is paid when the user asks
    rather than on every refresh.
    """
    title = "Check Cloud Status"
    try:
        answer = dataset.is_in_cloud()
        in_cloud = answer[0] if isinstance(answer, tuple) else answer
    except Exception as exc:  # noqa: BLE001
        return CloudActionResult(False, title, str(exc), "error", None)

    if in_cloud:
        return CloudActionResult(
            True, title, "This dataset is linked to NDI Cloud.", "success", "incloud"
        )
    return CloudActionResult(
        True,
        title,
        'This dataset is not in NDI Cloud. Use "Upload to Cloud" to add it.',
        "info",
        "notincloud",
    )


def upload_dataset(dataset: Any) -> CloudActionResult:
    """Upload DATASET's documents and files to NDI Cloud.

    Creates the remote dataset on a first upload and otherwise sends
    whatever is missing. A successful upload is what LINKS the dataset to
    the cloud, so the new state is known without another query -- which is
    why success reports ``"incloud"`` directly.
    """
    title = "Upload to Cloud"
    from ...cloud.orchestration import uploadDataset

    try:
        success, _cloud_id, message = uploadDataset(dataset, verbose=False)
    except Exception as exc:  # noqa: BLE001
        return CloudActionResult(False, title, str(exc), "error", None)

    if success:
        return CloudActionResult(
            True, title, "The dataset was uploaded to NDI Cloud.", "success", "incloud"
        )
    return CloudActionResult(False, title, f"Upload did not complete: {message}", "error", None)


def check_for_new(dataset: Any, side: str) -> CloudActionResult:
    """How many documents are new on one SIDE. Reads ids only; changes nothing.

    ``side`` is ``"remote"`` (cloud documents missing locally) or
    ``"local"`` (local documents missing on the cloud).
    """
    if side not in ("remote", "local"):
        raise ValueError(f"side must be 'remote' or 'local'; got {side!r}.")
    title = "Check Cloud for New" if side == "remote" else "Check Local for New"

    from ...cloud.sync import documentDifference

    try:
        report = documentDifference(dataset)
    except Exception as exc:  # noqa: BLE001
        return CloudActionResult(False, title, str(exc), "error", None)

    count = report["num_remote_only"] if side == "remote" else report["num_local_only"]
    return CloudActionResult(True, title, cloud_check_message(side, count), "info", None)


def sync_dataset(dataset: Any, mode: str) -> CloudActionResult:
    """Run an additive sync MODE and report what changed.

    ``mode`` is a key of :data:`SYNC_MODES`. None of these delete documents,
    so no confirmation is required.
    """
    if mode not in SYNC_MODES:
        raise ValueError(f"mode must be one of {sorted(SYNC_MODES)}; got {mode!r}.")
    return _run_sync(dataset, *SYNC_MODES[mode], failure_verb="Sync")


def mirror_dataset(dataset: Any, direction: str) -> CloudActionResult:
    """Mirror one side onto the other. THE CALLER MUST HAVE CONFIRMED FIRST.

    ``direction`` is a key of :data:`MIRROR_MODES`. Both directions delete
    documents permanently; this function does not ask, because a confirmation
    obtained from the user is the pane's responsibility and
    :func:`mirror_prompt` supplies the wording.
    """
    if direction not in MIRROR_MODES:
        raise ValueError(f"direction must be one of {sorted(MIRROR_MODES)}; got {direction!r}.")
    return _run_sync(dataset, *MIRROR_MODES[direction], failure_verb="Mirror")


def _run_sync(
    dataset: Any, function_name: str, title: str, *, failure_verb: str
) -> CloudActionResult:
    """Resolve the target, call one sync function, and summarise the report."""
    from ...cloud import sync as sync_module

    try:
        dataset_path, cloud_id = resolve_cloud_target(dataset)
    except ValueError as exc:
        return CloudActionResult(False, title, str(exc), "error", None)

    operation = getattr(sync_module, function_name)
    try:
        report = operation(dataset_path, cloud_id)
    except Exception as exc:  # noqa: BLE001
        return CloudActionResult(
            False, title, f"{failure_verb} did not complete: {exc}", "error", None
        )

    # No state is reported, matching MATLAB: cloudSync and cloudMirror leave
    # the node's cloud badge alone. A successful sync does imply the dataset
    # is linked -- resolve_cloud_target only succeeds when it is -- so
    # returning "incloud" here would be true. It is left out anyway, because
    # this port's job is to mirror MATLAB's behaviour rather than quietly
    # improve on it; a badge that updates in one language and not the other
    # is exactly the kind of drift the symmetry work exists to prevent.
    return CloudActionResult(True, title, sync_result_message(report), "success", None)
