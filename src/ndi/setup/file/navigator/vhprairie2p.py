"""
ndi.setup.file.navigator.vhPrairie2p - navigator for vhlab Prairie 2-photon sessions.

In these sessions an epoch is not one directory. It is a PAIR (rarely a small
set) of sibling directories related by a numeric suffix::

    <BASE>/reference.txt        index file; its presence marks an epoch
    <BASE>/frametrigger.txt     frame-trigger times, for syncing to another clock
    <BASE>-001/, <BASE>-002/    PrairieView acquisition directories: the TIFF
                                frames plus .xml/.pcf config

Usually only ``-001`` exists; very rarely an epoch spans ``-001``, ``-002``,
... (the cycles of one run), and those all belong to ONE epoch.

The default navigator cannot assemble this. Its grouping only relates files
that co-occur *within* one directory, whereas the ``<BASE>`` <-> ``<BASE>-NNN``
relationship lives in the directory NAMES. So this navigator overrides the
disk-scanning step with the directory-pairing rule instead.

An epoch's file group is ``reference.txt``, ``frametrigger.txt`` when present,
and the non-TIFF config/metadata files of each acquisition directory. The
frames themselves are deliberately not enumerated: the reader
(``ndi.daq.reader.image.ndr`` with ``'prairieview'``) resolves the TIFFs from
each config file's directory, which keeps the epoch file list small even when
an acquisition holds thousands of frames.

The epoch id is the ``<BASE>`` directory name.

MATLAB equivalent: src/ndi/+ndi/+setup/+file/+navigator/vhPrairie2p.m
"""

from __future__ import annotations

import os
import re

from ....file.navigator import ndi_file_navigator

__all__ = ["ndi_setup_file_navigator_vhPrairie2p"]


class ndi_setup_file_navigator_vhPrairie2p(ndi_file_navigator):
    """File navigator for vhlab PrairieView 2-photon sessions."""

    NDI_FILENAVIGATOR_CLASS = "ndi.setup.file.navigator.vhPrairie2p"

    #: Index file in <BASE> whose presence marks an epoch.
    INDEX_FILE = "reference.txt"
    #: Frame-trigger sync file in <BASE>, included in the group when present.
    SYNC_FILE = "frametrigger.txt"

    #: Frame files, resolved by the reader rather than listed in the group.
    _FRAME_EXTENSIONS = (".tif", ".tiff")

    def epochid(
        self,
        epoch_number: int,
        epochfiles: list[str] | None = None,
    ) -> str:
        """The epoch identifier: the ``<BASE>`` directory name.

        ``epochfiles[0]`` is always ``<BASE>/reference.txt``, so the parent
        directory's name is the id.
        """
        if epochfiles is None:
            epochfiles = self.getepochfiles(epoch_number)
        if not epochfiles:
            return super().epochid(epoch_number, epochfiles)
        basedir = os.path.dirname(epochfiles[0])
        return os.path.basename(basedir)

    def selectfilegroups_disk(self) -> list[list[str]]:
        """Assemble epochs from ``<BASE>`` / ``<BASE>-NNN`` directory pairs.

        Every first-level subdirectory holding a ``reference.txt`` is a
        ``<BASE>``. Each ``<BASE>`` that also has at least one sibling
        ``<BASE>-NNN`` acquisition directory yields one epoch; a ``<BASE>``
        with no acquisition directory is not a usable epoch and is skipped.
        """
        exp_path = self.path()
        if not exp_path or not os.path.isdir(exp_path):
            return []

        names = sorted(
            e
            for e in os.listdir(exp_path)
            if not e.startswith(".") and os.path.isdir(os.path.join(exp_path, e))
        )

        epochfiles_disk: list[list[str]] = []
        for base in names:
            refpath = os.path.join(exp_path, base, self.INDEX_FILE)
            if not os.path.isfile(refpath):
                continue  # not a <BASE>: no index file

            acq = self._acquisition_dirs(names, base)
            if not acq:
                continue  # no paired acquisition directory

            group = [refpath]
            syncpath = os.path.join(exp_path, base, self.SYNC_FILE)
            if os.path.isfile(syncpath):
                group.append(syncpath)
            for a in acq:
                group.extend(self._non_frame_files(os.path.join(exp_path, a)))

            epochfiles_disk.append(group)

        return epochfiles_disk

    @classmethod
    def _acquisition_dirs(cls, names: list[str], base: str) -> list[str]:
        """Sibling directory names of the form ``<base>-NNN``, sorted."""
        pattern = re.compile(r"^" + re.escape(base) + r"-\d+$")
        return sorted(n for n in names if pattern.match(n))

    @classmethod
    def _non_frame_files(cls, adir: str) -> list[str]:
        """Full paths of the non-TIFF, non-hidden files directly in ``adir``.

        These are the PrairieView config/metadata files (.xml/.pcf/.env/.cfg,
        frame-time sidecars) that anchor the acquisition directory; the image
        reader resolves the frames from each anchor's directory.
        """
        if not os.path.isdir(adir):
            return []
        out = []
        for name in sorted(os.listdir(adir)):
            full = os.path.join(adir, name)
            if name.startswith(".") or os.path.isdir(full):
                continue
            if os.path.splitext(name)[1].lower() in cls._FRAME_EXTENSIONS:
                continue
            out.append(full)
        return out

    def __repr__(self) -> str:
        return f"ndi_setup_file_navigator_vhPrairie2p(path={self.path()!r})"
