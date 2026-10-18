"""
ndi.cloud.ui.dialog - Choosing among NDI Cloud items by name.

MATLAB equivalents: +ndi/+cloud/+ui/+dialog/organizationLabels.m,
    +ndi/+cloud/+ui/+dialog/selectOrganization.m
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..client import CloudClient


def organizationLabels(organizationName: list, organizationID: list) -> list[str]:
    """Build unique display labels for a list of organizations.

    MATLAB equivalent: ndi.cloud.ui.dialog.organizationLabels

    Given parallel lists of organization names and ids, returns a list of
    display labels suitable for a name-based picker.

    The label for each organization is its name. Two rules keep the labels
    usable as unique keys in a list dialog:

        * An organization with no name falls back to its id.
        * When a name is shared by more than one organization (or a name
          collides with another organization's id/label), the organization id
          is appended in parentheses so every label is distinct.

    Args:
        organizationName: Organization names, parallel to ORGANIZATIONID. May
            be shorter than ORGANIZATIONID, in which case the missing names
            are treated as empty.
        organizationID: Organization ids.

    Returns:
        One label per organization, in the input order, all distinct.
    """
    ids = [str(i) for i in organizationID]
    names = [
        str(organizationName[i]) if i < len(organizationName) and organizationName[i] else ""
        for i in range(len(ids))
    ]
    base = [name or ident for name, ident in zip(names, ids, strict=True)]
    return [
        f"{label}  ({ident})" if base.count(label) > 1 and ident else label
        for label, ident in zip(base, ids, strict=True)
    ]


def selectOrganization(
    *,
    auto_select_single: bool = True,
    require_upload: bool = False,
    prompt_string: str = "Select an organization:",
    chooser: Callable[[list[str], str], int | None] | None = None,
    client: CloudClient | None = None,
) -> tuple[str, str]:
    """Choose one of the current user's NDI Cloud organizations by name.

    MATLAB equivalent: ndi.cloud.ui.dialog.selectOrganization

    Lists, by name, the organizations that the currently authenticated NDI
    Cloud user belongs to, and returns the chosen organization's id and name.
    The list comes from :func:`ndi.cloud.internal.getOrganizations` (cached at
    login).

    This is the always-interactive form of
    :func:`ndi.cloud.internal.chooseOrganization`.

    Args:
        auto_select_single: When True (default) and only one organization
            qualifies, it is returned without asking. False always asks.
        require_upload: Only list organizations in which the user may create
            datasets.
        prompt_string: Prompt shown above the list.
        chooser: Called as ``chooser(labels, prompt_string)``; returns the
            0-based index of the chosen label, or None to cancel. Default: a
            numbered prompt on the console.
        client: Authenticated cloud client (auto-created if omitted).

    Returns:
        Tuple of ``(organization_id, organization_name)``.

    Raises:
        CloudOrganizationError: ``NDI:CloudDialog:UserCanceled`` if the user
            cancels, or any error of :func:`~ndi.cloud.internal.chooseOrganization`.

    Python-specific Notes:
        MATLAB opens a modal dialog. Python asks on the console unless a
        CHOOSER is given (the Qt navigator passes its list dialog).
    """
    from ..internal import chooseOrganization

    return chooseOrganization(
        interactive=True,
        always_ask=not auto_select_single,
        require_upload=require_upload,
        prompt_string=prompt_string,
        chooser=chooser,
        client=client,
    )
