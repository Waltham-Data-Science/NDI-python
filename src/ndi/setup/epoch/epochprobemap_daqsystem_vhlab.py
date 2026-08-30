"""
ndi.setup.epoch.epochprobemap_daqsystem_vhlab - vhlab epoch probe maps.

Builds epoch probe maps from the small text files vhlab writes beside each
epoch's data. This port covers the ``reference.txt`` form used by the
PrairieView 2-photon (image-series) DAQ system, which is what
``vhprairieview`` needs (issue #71).

vhlab's other forms -- ``*_channelgrouping.txt``, ``stimtimes.txt``,
``vhtaste_sync.txt`` and ``*_stimulus_triggers_log.tsv`` -- are implemented in
MATLAB's version of this class and are NOT ported here; they belong to DAQ
systems Python already handles by other means. :func:`from_file` raises for
them rather than guessing.

MATLAB equivalent: src/ndi/+ndi/+setup/+epoch/epochprobemap_daqsystem_vhlab.m
"""

from __future__ import annotations

import os

from ...epoch.epochprobemap_daqsystem import ndi_epoch_epochprobemap__daqsystem

__all__ = ["ndi_setup_epoch_epochprobemap_daqsystem_vhlab"]

#: vhlab shorthand in reference.txt -> canonical NDI probe type. The
#: channelgrouping branch does the same thing for singleEC/ntrode -> n-trode.
_PROBE_TYPE_ALIASES = {"prairietp": "two-photon-imaging"}

#: Every reference.txt row describes a probe read out through the image DAQ
#: system's single logical image channel.
_PRAIRIEVIEW_DEVICESTRING = "vhprairieview:image1"


class ndi_setup_epoch_epochprobemap_daqsystem_vhlab(ndi_epoch_epochprobemap__daqsystem):
    """Epoch probe map for vhlab DAQ systems."""

    NDI_EPOCHPROBEMAP_CLASS = "ndi.setup.epoch.epochprobemap_daqsystem_vhlab"

    @classmethod
    def from_file(cls, filename: str) -> list[ndi_setup_epoch_epochprobemap_daqsystem_vhlab]:
        """Build the probe maps described by one vhlab epoch file.

        Only ``reference.txt`` is understood; see the module docstring.
        """
        basename = os.path.basename(filename)
        if basename != "reference.txt":
            raise NotImplementedError(
                f"{basename!r} is not a vhlab epoch file this port understands. "
                "Only reference.txt (PrairieView 2-photon) is implemented; see "
                "MATLAB's epochprobemap_daqsystem_vhlab for the other forms."
            )
        return cls._from_reference_txt(filename)

    @classmethod
    def _from_reference_txt(
        cls, filename: str
    ) -> list[ndi_setup_epoch_epochprobemap_daqsystem_vhlab]:
        """Parse a PrairieView ``reference.txt``.

        The imaging probes are described directly, one per row, as
        ``name<tab>ref<tab>type`` with a header line::

            name    ref     type
            tp      1       prairieTP
        """
        subject_id = cls._read_subject_id(filename)
        rows = cls._read_table(filename)

        out = []
        for row in rows:
            # reference.txt is often written by hand, so tolerate stray
            # whitespace and any capitalization of the vhlab shorthand.
            ec_type = row["type"].strip()
            ec_type = _PROBE_TYPE_ALIASES.get(ec_type.lower(), ec_type)
            out.append(
                cls(
                    name=row["name"].strip(),
                    reference=int(row["ref"]),
                    type=ec_type,
                    devicestring=_PRAIRIEVIEW_DEVICESTRING,
                    subjectstring=subject_id,
                )
            )
        return out

    @staticmethod
    def _read_table(filename: str) -> list[dict[str, str]]:
        """Read the tab-delimited table, requiring exactly name/ref/type."""
        with open(filename, encoding="utf-8") as f:
            lines = [ln.rstrip("\n") for ln in f if ln.strip()]
        if not lines:
            raise ValueError(f"{filename} is empty.")

        header = [h.strip() for h in lines[0].split("\t")]
        if header != ["name", "ref", "type"]:
            raise ValueError(
                f"reference.txt fields must be (case-sensitive match): "
                f"name, ref, type. Got: {header}"
            )

        rows = []
        for ln in lines[1:]:
            parts = [p.strip() for p in ln.split("\t")]
            if len(parts) != len(header):
                raise ValueError(f"Malformed row in {filename}: {ln!r}")
            rows.append(dict(zip(header, parts)))
        return rows

    @staticmethod
    def _read_subject_id(filename: str) -> str:
        """Read ``subject.txt`` from the directory above the epoch directory."""
        epochdir = os.path.dirname(os.path.abspath(filename))
        parentpath = os.path.dirname(epochdir)
        subjectfile = os.path.join(parentpath, "subject.txt")
        if not os.path.isfile(subjectfile):
            raise FileNotFoundError(f"No subject.txt file found: {subjectfile}.")
        with open(subjectfile, encoding="utf-8") as f:
            return f.readline().strip()
