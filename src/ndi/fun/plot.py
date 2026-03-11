"""
ndi.fun.plot - Plotting utility functions.

MATLAB equivalents: +ndi/+fun/+plot/bar3.m, multichan.m, stimulusTimeseries.m

Provides plotting utilities for NDI data visualization using matplotlib.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def bar3(
    data_table: Any,
    grouping_variables: list[str],
    plotting_variable: str,
) -> Any:
    """Create a 3-way grouped bar chart from table data.

    MATLAB equivalent: ndi.fun.plot.bar3

    Takes a pandas DataFrame and visualizes the mean of *plotting_variable*
    across three categorical factors specified in *grouping_variables*.

    Args:
        data_table: A pandas DataFrame containing the data.
        grouping_variables: List of exactly 3 column names to group by.
            Variable 1 -> subplots, Variable 2 -> x-axis clusters,
            Variable 3 -> individual bars (color-coded).
        plotting_variable: Column name of the numeric variable to plot
            (the mean is shown).

    Returns:
        The matplotlib Figure object.

    Raises:
        ImportError: If matplotlib is not installed.
        ValueError: If *grouping_variables* does not have exactly 3 elements.

    Example::

        >>> import pandas as pd
        >>> df = pd.DataFrame({
        ...     'Region': ['A','A','B','B'] * 3,
        ...     'Quarter': ['Q1','Q2'] * 6,
        ...     'Product': ['X','X','X','X','Y','Y','Y','Y','Z','Z','Z','Z'],
        ...     'Sales': range(12),
        ... })
        >>> fig = bar3(df, ['Region', 'Quarter', 'Product'], 'Sales')
    """
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ImportError(
            "matplotlib is required for ndi.fun.plot. " "Install it with: pip install matplotlib"
        ) from exc

    import pandas as pd

    if len(grouping_variables) != 3:
        raise ValueError("grouping_variables must have exactly 3 elements")

    df = data_table if isinstance(data_table, pd.DataFrame) else pd.DataFrame(data_table)

    # Extract unique groups for each variable
    groups = []
    group_indices = []
    for var in grouping_variables:
        cats = df[var].unique()
        cats_sorted = sorted(cats, key=str)
        cat_map = {c: i for i, c in enumerate(cats_sorted)}
        groups.append(cats_sorted)
        group_indices.append(df[var].map(cat_map).values)

    g1_size = len(groups[0])
    g2_size = len(groups[1])
    g3_size = len(groups[2])

    # Color map for inner group
    cmap = plt.cm.get_cmap("tab10")
    colors = [cmap(i % 10) for i in range(g3_size)]

    fig, axes = plt.subplots(1, g1_size, figsize=(5 * g1_size, 4), squeeze=False)
    axes = axes.flatten()

    for i in range(g1_size):
        ax = axes[i]
        for j in range(g2_size):
            for k in range(g3_size):
                mask = (group_indices[0] == i) & (group_indices[1] == j) & (group_indices[2] == k)
                vals = df.loc[mask, plotting_variable].values
                x = j * (g3_size + 1) + k + 1
                if len(vals) > 0:
                    ax.bar(x, np.nanmean(vals), color=colors[k])

        # Format subplot
        tick_positions = [(g3_size + 1) * j + (g3_size + 1) / 2 for j in range(g2_size)]
        ax.set_xticks(tick_positions)
        ax.set_xticklabels([str(g) for g in groups[1]])
        ax.set_title(str(groups[0][i]))
        ax.set_ylabel(plotting_variable)

        if i == g1_size - 1:
            # Add legend on last subplot
            from matplotlib.patches import Patch

            handles = [Patch(facecolor=colors[k], label=str(groups[2][k])) for k in range(g3_size)]
            ax.legend(handles=handles, frameon=False)

    fig.tight_layout()
    return fig


def multichan(
    data: np.ndarray,
    t: np.ndarray,
    space: float,
) -> list[Any]:
    """Plot multiple channels of data with vertical spacing.

    MATLAB equivalent: ndi.fun.plot.multichan

    Plots multiple channels of *data* (assumed to be
    ``num_samples x num_channels``) on the current axes, offsetting each
    channel vertically by *space*.

    Args:
        data: 2-D array of shape ``(num_samples, num_channels)``.
        t: 1-D time array of length ``num_samples``.
        space: Vertical spacing between channels.

    Returns:
        List of matplotlib Line2D objects, one per channel.

    Raises:
        ImportError: If matplotlib is not installed.
    """
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ImportError(
            "matplotlib is required for ndi.fun.plot. " "Install it with: pip install matplotlib"
        ) from exc

    data = np.asarray(data)
    t = np.asarray(t)

    if data.ndim == 1:
        data = data.reshape(-1, 1)

    num_channels = data.shape[1]
    handles = []

    ax = plt.gca()
    for i in range(num_channels):
        (h,) = ax.plot(t, i * space + data[:, i], color=(0.7, 0.7, 0.7))
        handles.append(h)

    return handles


def stimulusTimeseries(
    stimulus_probe: Any,
    timeref: Any,
    y: float,
    *,
    stimid: list | np.ndarray | None = None,
    linewidth: float = 2.0,
    linecolor: tuple[float, float, float] = (0.0, 0.0, 0.0),
    fontsize: float = 12.0,
    fontweight: str = "normal",
    fontcolor: tuple[float, float, float] = (0.0, 0.0, 0.0),
    textycoord: float | None = None,
    horizontal_alignment: str = "center",
) -> tuple[list[Any], list[Any], Any, Any]:
    """Plot stimulus occurrence as thick bars on a time series plot.

    MATLAB equivalent: ndi.fun.plot.stimulusTimeseries

    Reads stimulus timing data from a probe and plots each stimulus
    presentation as a horizontal bar at the given y-coordinate.

    Args:
        stimulus_probe: An NDI probe/element object with a
            ``readtimeseries`` method.
        timeref: An :class:`ndi.time.TimeReference` specifying the time
            reference for the plot.
        y: Y-coordinate at which to draw the stimulus bars.
        stimid: Optional stimulus ID numbers.  If *None*, the function
            attempts to read ``stimid`` from the probe data.
        linewidth: Width of the stimulus bars.
        linecolor: RGB tuple for bar color.
        fontsize: Font size for stimulus ID labels.
        fontweight: Font weight for labels (``'normal'`` or ``'bold'``).
        fontcolor: RGB tuple for label color.
        textycoord: Y-coordinate for text labels.  Defaults to ``y + 1``.
        horizontal_alignment: Horizontal alignment for labels.

    Returns:
        Tuple ``(h_lines, h_texts, stimulus_data, stimulus_time_data)``
        where *h_lines* are the line handles, *h_texts* are text handles,
        *stimulus_data* and *stimulus_time_data* are the raw data read
        from the probe.

    Raises:
        ImportError: If matplotlib is not installed.
        ValueError: If stimulus time data lacks ``stimon``/``stimoff``.
    """
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ImportError(
            "matplotlib is required for ndi.fun.plot. " "Install it with: pip install matplotlib"
        ) from exc

    # Read stimulus data from the probe
    stimulus_data, stimulus_time_data, _ = stimulus_probe.readtimeseries(
        timeref, float("-inf"), float("inf")
    )

    # Resolve stimid
    if stimid is None:
        if isinstance(stimulus_data, dict) and "stimid" in stimulus_data:
            stimid = stimulus_data["stimid"]
        elif isinstance(stimulus_data, list):
            ids = []
            for entry in stimulus_data:
                if isinstance(entry, dict) and "stimid" in entry:
                    ids.extend(
                        entry["stimid"] if isinstance(entry["stimid"], list) else [entry["stimid"]]
                    )
            stimid = ids if ids else None

    # Extract stimon / stimoff
    if isinstance(stimulus_time_data, dict):
        stimon = stimulus_time_data.get("stimon")
        stimoff = stimulus_time_data.get("stimoff")
    elif hasattr(stimulus_time_data, "stimon") and hasattr(stimulus_time_data, "stimoff"):
        stimon = stimulus_time_data.stimon
        stimoff = stimulus_time_data.stimoff
    else:
        raise ValueError("stimulus_time_data must contain 'stimon' and 'stimoff' fields")

    if stimon is None or stimoff is None:
        raise ValueError("stimulus_time_data must contain 'stimon' and 'stimoff' fields")

    stimon = np.asarray(stimon).ravel()
    stimoff = np.asarray(stimoff).ravel()

    if textycoord is None:
        textycoord = y + 1

    ax = plt.gca()
    h_lines = []
    h_texts = []

    for idx in range(len(stimon)):
        (h,) = ax.plot(
            [stimon[idx], stimoff[idx]],
            [y, y],
            linewidth=linewidth,
            color=linecolor,
            solid_capstyle="butt",
        )
        h_lines.append(h)

        if stimid is not None and idx < len(stimid):
            mid = (stimon[idx] + stimoff[idx]) / 2
            ht = ax.text(
                mid,
                textycoord,
                str(stimid[idx]),
                fontsize=fontsize,
                fontweight=fontweight,
                color=fontcolor,
                ha=horizontal_alignment,
                va="bottom",
            )
            h_texts.append(ht)

    return h_lines, h_texts, stimulus_data, stimulus_time_data
