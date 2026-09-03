"""ndi.util.removehiddenfilegroups - drop epoch file groups that depend on hidden files.

MATLAB counterpart: ``src/ndi/+ndi/+util/removehiddenfilegroups.m``

A file group is a putative epoch: the set of files one regexp match
produced. Pruning it is therefore all-or-nothing. If any member is a
hidden file the MATCH is wrong, not merely dirty, and the whole group
goes -- keeping the visible remainder would leave an epoch missing the
file one of its patterns matched, which is worse than having no epoch at
all.

The case this exists for is macOS AppleDouble shadow files
(``._Epoch6_g0_t0.imec0.ap.bin``). They are matched by ``#``-style
filematch patterns and otherwise produce spurious duplicate epochs that
share the genuine epoch's epoch_id.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence

__all__ = ["removehiddenfilegroups", "is_hidden_file"]


def is_hidden_file(path: str) -> bool:
    """True if the final path component begins with a dot.

    The whole basename is tested, name and extension together: for a
    dotfile such as ``.DS_Store`` a name/extension split gives an empty
    name and ``.DS_Store`` as the extension, so testing the name alone
    would miss it. MATLAB's version makes the same point in a comment.
    """
    return os.path.basename(str(path)).startswith(".")


def removehiddenfilegroups(
    epochfiles_disk: Iterable[Sequence[str]],
) -> list[list[str]]:
    """Remove every file group that contains a hidden file.

    MATLAB equivalent: ndi.util.removehiddenfilegroups

    Args:
        epochfiles_disk: Groups of file names, as returned by
            ``find_file_groups`` -- each group is one putative epoch.

    Returns:
        The groups with no hidden member, in their original order.

    Example:
        >>> removehiddenfilegroups([["/d/data.bin"], ["/d/._data.bin"]])
        [['/d/data.bin']]
    """
    return [list(group) for group in epochfiles_disk if not any(is_hidden_file(f) for f in group)]
