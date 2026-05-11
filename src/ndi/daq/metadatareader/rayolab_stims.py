"""ndi.daq.metadatareader.RayoLabStims - Trivial RayoLab stimulator metadata reader.

The RayoLab stimulator emits a single stimulus type whose only parameter
is its stimulus id, which is always 1. This metadata reader does not read
any per-stimulus content from disk; it returns one constant parameter
set::

    parameters[0] = {"stimid": 1}

The single entry is keyed at index 1 to match the stimulus id reported on
the mk2 marker channel by
``ndi.setup.daq.reader.mfdaq.stimulus.rayolab_intanseries`` (MATLAB).

The constructor accepts the same arguments as
:class:`ndi_daq_metadatareader` (typically a filename regular expression
identifying the metadata file inside an epoch's file list); the pattern
is stored but not consulted, since the parameters are constant.

MATLAB equivalent: ``src/ndi/+ndi/+daq/+metadatareader/RayoLabStims.m``
"""

from __future__ import annotations

from typing import Any

from ..metadatareader import ndi_daq_metadatareader


class ndi_daq_metadatareader_RayoLabStims(ndi_daq_metadatareader):
    """Constant metadata reader for the RayoLab stimulator.

    Always returns a single-element parameter list ``[{"stimid": 1}]``,
    regardless of which epoch files are passed in.

    Example:
        >>> reader = ndi_daq_metadatareader_RayoLabStims()
        >>> reader.readmetadata(["some_epoch_file.rhd"])
        [{'stimid': 1}]
    """

    def __init__(
        self,
        tsv_pattern: str = "",
        identifier: str | None = None,
        session: Any | None = None,
        document: Any | None = None,
    ):
        super().__init__(
            tsv_pattern=tsv_pattern,
            identifier=identifier,
            session=session,
            document=document,
        )

    def readmetadata(
        self,
        epochfiles: list[str],
    ) -> list[dict[str, Any]]:
        """Return the constant RayoLab parameter set.

        Args:
            epochfiles: Ignored.

        Returns:
            ``[{"stimid": 1}]``
        """
        return [{"stimid": 1}]

    def readmetadatafromfile(
        self,
        filepath: str,
    ) -> list[dict[str, Any]]:
        """Return the constant RayoLab parameter set.

        Args:
            filepath: Ignored.

        Returns:
            ``[{"stimid": 1}]``
        """
        return [{"stimid": 1}]

    def __repr__(self) -> str:
        return f"ndi_daq_metadatareader_RayoLabStims(id='{self.id[:8]}...')"
