"""
ndi.epoch.functions - Epoch utility functions.

MATLAB equivalents:
- src/ndi/+ndi/+epoch/epochrange.m
- src/ndi/+ndi/+epoch/findepochnode.m
"""

from __future__ import annotations

from typing import Any

from ..time import ClockType


def epochrange(
    epochset_obj: Any,
    clocktype: ClockType,
    first_epoch: int | str,
    last_epoch: int | str,
) -> tuple[list[str], list[dict], list[tuple[float, float]]]:
    """
    Return range of epochs between first and last epoch.

    Args:
        epochset_obj: An object with epochtable() method (EpochSet, Element, etc.)
        clocktype: Clock type to use for t0_t1
        first_epoch: First epoch number (1-indexed) or epoch_id string
        last_epoch: Last epoch number (1-indexed) or epoch_id string

    Returns:
        Tuple of:
        - epoch_ids: List of epoch ID strings
        - epoch_table: List of epoch table entries
        - t0_t1: List of (t0, t1) tuples for each epoch

    Raises:
        ValueError: If epochs are not found or range is invalid
    """
    et = epochset_obj.epochtable()

    if not et:
        return [], [], []

    # Resolve first_epoch to index
    first_idx = _resolve_epoch_index(et, first_epoch)
    last_idx = _resolve_epoch_index(et, last_epoch)

    if first_idx > last_idx:
        raise ValueError(f"first_epoch ({first_epoch}) is after last_epoch ({last_epoch})")

    # Extract the range
    epoch_ids = []
    epoch_table = []
    t0_t1_list = []

    for i in range(first_idx, last_idx + 1):
        entry = et[i]
        epoch_ids.append(entry["epoch_id"])
        epoch_table.append(entry)

        # Get t0_t1 for the requested clock type
        t0_t1 = entry.get("t0_t1", [(float("nan"), float("nan"))])
        epoch_clocks = entry.get("epoch_clock", [])

        # Try to find matching clock type
        found = False
        for j, clk in enumerate(epoch_clocks):
            if hasattr(clk, "type") and clk.type == clocktype.type:
                if j < len(t0_t1):
                    t0_t1_list.append(t0_t1[j])
                    found = True
                    break
            elif clk == clocktype:
                if j < len(t0_t1):
                    t0_t1_list.append(t0_t1[j])
                    found = True
                    break

        if not found:
            # Use first available t0_t1
            if t0_t1:
                t0_t1_list.append(t0_t1[0])
            else:
                t0_t1_list.append((float("nan"), float("nan")))

    return epoch_ids, epoch_table, t0_t1_list


def _resolve_epoch_index(
    epoch_table: list[dict],
    epoch: int | str,
) -> int:
    """
    Resolve an epoch number or ID to a 0-based index.

    Args:
        epoch_table: The epoch table
        epoch: Epoch number (1-indexed) or epoch_id string

    Returns:
        0-based index into epoch_table

    Raises:
        ValueError: If epoch not found
    """
    if isinstance(epoch, int):
        idx = epoch - 1  # Convert 1-indexed to 0-indexed
        if idx < 0 or idx >= len(epoch_table):
            raise ValueError(f"Epoch number {epoch} out of range [1, {len(epoch_table)}]")
        return idx

    # Search by epoch_id
    for i, entry in enumerate(epoch_table):
        if entry.get("epoch_id") == epoch:
            return i

    raise ValueError(f"Epoch ID '{epoch}' not found")


def find_epoch_node(
    epoch_node: dict[str, Any],
    epoch_node_array: list[dict[str, Any]],
) -> list[int]:
    """
    Find occurrences of an epoch node in an array of epoch nodes.

    Searches *epoch_node_array* for entries that match *epoch_node*.
    Any field in *epoch_node* that is empty, None, or missing is treated
    as a wildcard (not used for filtering).  If *epoch_node* is fully
    populated, only exact matches are returned.

    Compared fields (strings use ``==``):
        objectname, objectclass, epoch_id, epoch_session_id

    Special fields:
        epoch_clock  - uses ``==`` (ClockType equality)
        time_value   - checks whether the value falls within the
                       candidate's ``t0_t1`` range ``[t0, t1]``

    Note: the ``epochprobemap`` field is intentionally not compared,
    matching the MATLAB implementation.

    Args:
        epoch_node: A single epoch-node dict to search for.
        epoch_node_array: List of epoch-node dicts to search through.

    Returns:
        List of 0-based indices where matches occur.

    Example:
        >>> nodes = [
        ...     {'epoch_id': 'e1', 'objectname': 'probe1'},
        ...     {'epoch_id': 'e2', 'objectname': 'probe2'},
        ... ]
        >>> find_epoch_node({'epoch_id': 'e1'}, nodes)
        [0]
        >>> find_epoch_node({}, nodes)  # empty = match all
        [0, 1]
    """
    STRING_FIELDS = (
        "objectname",
        "objectclass",
        "epoch_id",
        "epoch_session_id",
    )

    candidates = list(range(len(epoch_node_array)))

    # --- string fields ---
    for field in STRING_FIELDS:
        value = epoch_node.get(field)
        if not value:  # None, '', or missing → wildcard
            continue
        candidates = [i for i in candidates if epoch_node_array[i].get(field) == value]

    # --- epoch_clock ---
    clock_val = epoch_node.get("epoch_clock")
    if clock_val is not None:
        candidates = [i for i in candidates if epoch_node_array[i].get("epoch_clock") == clock_val]

    # --- time_value (checked against t0_t1 of each candidate) ---
    time_val = epoch_node.get("time_value")
    if time_val is not None:
        filtered = []
        for i in candidates:
            t0_t1 = epoch_node_array[i].get("t0_t1")
            if t0_t1 is None:
                continue
            # t0_t1 may be a tuple/list [t0, t1] or a nested structure
            try:
                t0, t1 = t0_t1[0], t0_t1[1]
                if t0 <= time_val <= t1:
                    filtered.append(i)
            except (IndexError, TypeError):
                continue
        candidates = filtered

    return candidates
