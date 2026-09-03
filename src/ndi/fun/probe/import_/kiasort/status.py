"""ndi.fun.probe.import.kiasort.status - where a probe stands in the KIASORT pipeline.

MATLAB counterpart: ``+ndi/+fun/+probe/+import/+kiasort/status.m``

Three yes/no questions answered from the filesystem: has the probe been
exported, has KIASORT been run on it, has the result been curated. Each is
the presence of the file that step produces, which is why this costs nothing
and can be called for every probe in a list.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = ["status", "Status"]


class Status:
    """MATLAB's status struct, field for field."""

    def __init__(
        self,
        directory: str,
        output_directory: str,
        exported: bool,
        run: bool,
        curated: bool,
    ):
        #: ``<session>/<kiasort_dir>/<probe folder>``.
        self.directory = directory
        #: The KIASORT output subfolder, which holds ``RES_Sorted``.
        self.output_directory = output_directory
        #: The exported binary exists, so KIASORT can be run.
        self.exported = exported
        #: KIASORT results exist.
        self.run = run
        #: Curated results exist.
        self.curated = curated

    def words(self) -> list[str]:
        """The states that hold, in pipeline order. Python only.

        The GUI renders these; having the order defined once here keeps
        "exported, run" from ever coming back as "run, exported".
        """
        return [
            name
            for name, held in (
                ("exported", self.exported),
                ("run", self.run),
                ("curated", self.curated),
            )
            if held
        ]

    def __repr__(self) -> str:
        return f"Status({', '.join(self.words()) or 'not exported'})"


def status(
    S: Any,  # noqa: N803 - MATLAB's parameter name
    probe: Any,
    *,
    kiasort_dir: str = "kiasort",
    binaryFileName: str = "kiasort.bin",  # noqa: N803 - MATLAB's parameter name
    subdir: str = "kiasort_output",
) -> Status:
    """Report where PROBE stands in the KIASORT pipeline for session S.

    MATLAB equivalent: ``ndi.fun.probe.import.kiasort.status``.
    """
    from ....file import elementDirectory

    directory = Path(elementDirectory(Path(S.path) / kiasort_dir, probe)[0])
    output_directory = directory / subdir
    res = output_directory / "RES_Sorted"

    return Status(
        directory=str(directory),
        output_directory=str(output_directory),
        exported=(directory / binaryFileName).is_file(),
        run=(res / "spike_idx.h5").is_file(),
        curated=(res / "spike_idx_curated.h5").is_file(),
    )
