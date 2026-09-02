"""ndi.fun.probe.import.kilosort.promptrawbinary - choose the raw recording.

MATLAB counterpart: ``+ndi/+fun/+probe/+import/+kilosort/promptrawbinary.m``

Reached when the binary could not be located automatically -- data sorted
outside NDI has no ``.metadata`` sidecar -- and three things are needed before
the recording can be read: the file, the Neuropixels generation (which fixes
the int16-to-volts units), and the READ STRIDE in channels.

THE STRIDE IS THE DANGEROUS ONE. A wrong channel count does not fail; it
silently reinterprets the file and yields noise shaped like a waveform. So it
is taken from the SpikeGLX ``.meta`` sidecar where possible, never from
``n_channels_dat`` (which describes the sorted file, typically 384, not the
raw AP band's 385 = 384 electrodes + 1 sync), and is then CHECKED against the
file: the usable byte count must divide exactly by the stride, and the implied
duration must match the probe's own sample count. Both checks raise rather
than proceed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .neuropixels_multiplier import neuropixelsmultiplier
from .read_spikeglx_meta import readspikeglxmeta

__all__ = ["promptrawbinary", "prompt_raw_binary"]

#: Bytes per sample for the dtypes a raw stream arrives in.
_BYTES_PER = {
    "int16": 2,
    "uint16": 2,
    "short": 2,
    "ushort": 2,
    "int32": 4,
    "int": 4,
    "single": 4,
    "float": 4,
    "float32": 4,
    "double": 8,
    "float64": 8,
}


def promptrawbinary(
    baseinfo: dict[str, Any],
    *,
    RawFile: str = "",  # noqa: N803 - MATLAB's parameter name
    ProbeType: str = "",  # noqa: N803 - MATLAB's parameter name
    PromptForRawFile: bool = True,  # noqa: N803 - MATLAB's parameter name
    num_channels: float = float("nan"),
    expectedSamples: float = float("nan"),  # noqa: N803 - MATLAB's parameter name
    ask: Any = None,
) -> dict[str, Any]:
    """Complete BASEINFO with a raw recording chosen by the caller or the user.

    Returns a copy of BASEINFO with ``file``, ``num_channels``,
    ``multiplier``, ``probe_type`` and ``found`` filled in. ``found`` stays
    False when the user cancels any of the three prompts -- cancelling is not
    an error, it means "fall back to the template waveforms".

    ``ask`` is an optional object supplying the three prompts
    (``raw_file()``, ``probe_type()``, ``channel_count(default)``), which is
    how the GUI hands its own dialogs in and how a test drives this without
    one. When it is None and ``PromptForRawFile`` is true, Qt dialogs are used
    if a display is available; with ``PromptForRawFile`` false, a missing
    value raises instead of blocking a headless run.
    """
    info = dict(baseinfo)
    info["found"] = False
    info.setdefault("probe_type", "")

    prompts = ask if ask is not None else (_QtPrompts() if PromptForRawFile else None)

    # --- 1. the raw file ---------------------------------------------------
    if RawFile:
        if not Path(RawFile).is_file():
            raise FileNotFoundError(f"Specified RawFile was not found: {RawFile}.")
        binfile = RawFile
    elif prompts is not None:
        binfile = prompts.raw_file()
        if not binfile:
            return info  # cancelled
    else:
        raise ValueError(
            "No raw recording available: pass RawFile (PromptForRawFile is false, so "
            "no dialog is shown)."
        )

    # --- 2. the probe generation -> encode multiplier ----------------------
    probe_type = ProbeType
    if not probe_type:
        if prompts is None:
            raise ValueError(
                "No probe generation available: pass ProbeType ('NP1' or 'NP2'; "
                "PromptForRawFile is false, so no dialog is shown)."
            )
        probe_type = prompts.probe_type(binfile)
        if not probe_type:
            return info  # cancelled
    multiplier, type_info = neuropixelsmultiplier(probe_type)

    # --- 3. the read stride ------------------------------------------------
    bytes_per = _BYTES_PER.get(str(baseinfo.get("dtype", "int16")).lower(), 2)
    usable_bytes = os.path.getsize(binfile) - int(baseinfo.get("headerOffsetBytes", 0))

    # a stride implied by the file size and the probe's sample count, used only
    # to pre-fill the prompt with something sensible
    suggested = None
    if _is_number(expectedSamples) and expectedSamples >= 1:
        candidate = usable_bytes / (bytes_per * expectedSamples)
        if candidate >= 1 and abs(candidate - round(candidate)) < 1e-6:
            suggested = int(round(candidate))

    channels = None
    source = ""
    if _is_number(num_channels):
        channels = float(num_channels)
        source = "num_channels override"
    else:
        meta, _ = readspikeglxmeta(binfile)
        saved = (meta or {}).get("nSavedChans")
        if isinstance(saved, (int, float)) and saved >= 1:
            channels = float(saved)
            source = "SpikeGLX .meta (nSavedChans)"

    if channels is None:
        if prompts is None:
            raise ValueError(
                f"Could not determine the number of channels for the selected raw "
                f"recording {binfile}: no num_channels override and no SpikeGLX '.meta' "
                "sidecar was found next to it. Pass num_channels explicitly "
                "(PromptForRawFile is false, so no dialog is shown)."
            )
        answer = prompts.channel_count(binfile, suggested)
        if answer is None:
            return info  # cancelled
        channels = float(answer)
        source = "user prompt"

    if not (channels >= 1 and channels == round(channels)):
        raise ValueError(
            f"The number of channels for {binfile} must be a positive integer " f"(got {channels})."
        )
    channels = int(channels)

    # --- 4. validate the stride against the file --------------------------
    if usable_bytes % (bytes_per * channels) != 0:
        raise ValueError(
            f"The raw file {binfile} holds {usable_bytes} usable bytes, which is not an "
            f"exact multiple of {channels} channels x {bytes_per} bytes/sample. The "
            f"channel count ({channels}, from {source}) is almost certainly wrong. A "
            "Neuropixels AP raw file usually has 385 channels (384 electrodes + 1 sync); "
            "an NDI export has only the electrodes (e.g. 384)."
        )
    implied_samples = usable_bytes / (bytes_per * channels)
    if _is_number(expectedSamples) and expectedSamples >= 1:
        relative = abs(implied_samples - expectedSamples) / expectedSamples
        if relative > 1e-3:
            raise ValueError(
                f"The raw file {binfile} implies {implied_samples:g} samples/channel at "
                f"{channels} channels (from {source}), but this probe's epochs span "
                f"{expectedSamples:g} samples - a {100 * relative:.2f}% mismatch. The "
                "channel count is likely wrong, or the selected file is not the "
                "recording that was sorted."
            )

    info["file"] = str(binfile)
    info["num_channels"] = channels
    info["multiplier"] = multiplier
    info["probe_type"] = type_info["name"]
    info["found"] = True
    return info


class _QtPrompts:
    """The three dialogs, asked through Qt when a display is available.

    Every prompt degrades to "cancelled" when Qt is missing, which is what
    keeps an import on a headless machine falling back to template waveforms
    instead of raising for want of a dialog it could never have shown.
    """

    def raw_file(self) -> str:
        widgets = _qt()
        if widgets is None:
            return ""
        name, _ = widgets.QFileDialog.getOpenFileName(
            None,
            "Select the raw Neuropixels/SpikeGLX recording for spike-shape recalculation",
            "",
            "Raw recording (*.bin *.dat);;All files (*)",
        )
        return name or ""

    def probe_type(self, binfile: str) -> str:
        widgets = _qt()
        if widgets is None:
            return ""
        choice, ok = widgets.QInputDialog.getItem(
            None,
            "Probe generation",
            f"Which Neuropixels probe generation produced {binfile}?",
            ["Neuropixels 1.0", "Neuropixels 2.0"],
            0,
            False,
        )
        if not ok:
            return ""
        return "NP1" if "1.0" in choice else "NP2"

    def channel_count(self, binfile: str, suggested: int | None) -> int | None:
        widgets = _qt()
        if widgets is None:
            return None
        value, ok = widgets.QInputDialog.getInt(
            None,
            "Raw file channel count",
            f"Number of channels in {binfile}. A Neuropixels AP raw file is usually 385 "
            "(384 electrodes + 1 sync); an NDI export has only the electrodes (e.g. 384):",
            suggested or 385,
            1,
            100000,
        )
        return value if ok else None


def _qt() -> Any:
    """Qt's widgets, or None when no dialog can be shown.

    THE DISPLAY CHECK IS NOT OPTIONAL. Constructing a QApplication with no
    usable platform plugin ABORTS THE PROCESS -- a native abort, which no
    ``except`` can catch -- so an automated import on a headless machine would
    die here rather than falling back to template waveforms. MATLAB's
    ``uigetfile`` merely errors under ``-nodisplay``, and an error is
    catchable; this is the Python-side cost of the same situation, and the
    only defence is to not attempt it.
    """
    if not _display_available():
        return None
    try:
        from .....gui._qt_helpers import get_or_create_app, require_qt

        require_qt()
        get_or_create_app()
        from PySide6 import QtWidgets

        return QtWidgets
    except Exception:  # noqa: BLE001 - no Qt, no dialog, no import failure
        return None


def _display_available() -> bool:
    """Whether a Qt platform plugin can be expected to start.

    An application that is ALREADY running is proof enough. Otherwise: on
    Linux, Qt needs either an explicit ``QT_QPA_PLATFORM`` (``offscreen``
    included) or a display server; on macOS and Windows the native platform
    is always there.
    """
    import os
    import sys

    try:
        from PySide6 import QtWidgets

        if QtWidgets.QApplication.instance() is not None:
            return True
    except Exception:  # noqa: BLE001 - no PySide6 at all
        return False

    if sys.platform.startswith("linux"):
        return bool(
            os.environ.get("QT_QPA_PLATFORM")
            or os.environ.get("DISPLAY")
            or os.environ.get("WAYLAND_DISPLAY")
        )
    return True


def _is_number(value: Any) -> bool:
    """True for a real number that is not NaN (MATLAB's ~isnan guard)."""
    return isinstance(value, (int, float)) and value == value


#: The readable spelling beside MATLAB's.
prompt_raw_binary = promptrawbinary
