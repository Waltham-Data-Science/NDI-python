"""
ndi.setup.file.navigator.vhPrairie2p - navigator for vhlab Prairie 2-photon sessions.

In vhlab PrairieView 2-photon sessions an epoch is not contained in a
single directory: it is defined by a PAIR (rarely a small set) of sibling
directories whose names are related by a numeric suffix::

    <BASE>/reference.txt      index file written by the master acquisition
                              system; its presence marks an epoch.
    <BASE>/frametrigger.txt   frame-trigger times used to synchronize this
                              recording to another clock (e.g. vhspike2).
    <BASE>-001/, <BASE>-002/  PrairieView acquisition directories holding the
                              TIFF frames and the .xml/.pcf config. Usually
                              only -001 exists; very rarely an epoch spans
                              -001, -002, ... (the cycles of the run), and
                              those all belong to ONE epoch.

The default navigator cannot assemble these epochs: it only groups files
that co-occur WITHIN a single directory, and its ``#`` same-string symbol
matches within one directory's file names. The ``<BASE>`` <-> ``<BASE>-NNN``
relationship lives in the directory NAMES, which ``#`` cannot express.
This navigator therefore overrides ``selectfilegroups_disk`` with the
directory-pairing rule.

An epoch's file group is ``<BASE>/reference.txt``,
``<BASE>/frametrigger.txt`` (if present), and the non-TIFF config/metadata
files of each ``<BASE>-NNN`` acquisition directory. The image frames
themselves are not enumerated: the reader
(``ndi.daq.reader.image.ndr('prairieview')``) resolves the TIFFs from each
config file's directory. This keeps the epoch file list compact even when
an acquisition contains thousands of TIFFs.

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

    #: index file in <BASE> whose presence marks an epoch
    INDEX_FILE = "reference.txt"
    #: frame-trigger sync file in <BASE>
    SYNC_FILE = "frametrigger.txt"

    #: extensions of the image frames, which the reader resolves itself
    FRAME_EXTENSIONS = (".tif", ".tiff")

    def epochid(
        self,
        epoch_number: int,
        epochfiles: list[str] | None = None,
    ) -> str:
        """Return the epoch identifier: the ``<BASE>`` directory name."""
        if epochfiles is None:
            epochfiles = self.getepochfiles_number(epoch_number)

        if self.isingested(epochfiles):
            return self.ingestedfiles_epochid(epochfiles)

        # epochfiles[0] is always <BASE>/reference.txt; its parent folder
        # name is the epoch id.
        basedir = os.path.dirname(epochfiles[0])
        return os.path.basename(basedir)

    def selectfilegroups_disk(self) -> list[list[str]]:
        """Assemble epochs from ``<BASE>`` / ``<BASE>-NNN`` directory pairs.

        Each first-level subdirectory of the session that contains a
        ``reference.txt`` is a ``<BASE>``. For each ``<BASE>`` that also has
        at least one sibling ``<BASE>-NNN`` acquisition directory, one epoch
        is returned. A ``<BASE>`` with no paired acquisition directory is
        not a usable epoch and is skipped.
        """
        try:
            base_path = self.path()
        except ValueError:
            return []

        if not os.path.isdir(base_path):
            return []

        names = sorted(
            e
            for e in os.listdir(base_path)
            if not e.startswith(".") and os.path.isdir(os.path.join(base_path, e))
        )

        groups: list[list[str]] = []
        for base in names:
            refpath = os.path.join(base_path, base, self.INDEX_FILE)
            if not os.path.isfile(refpath):
                continue  # not a <BASE>: no index file

            acq = self._acquisition_dirs(names, base)
            if not acq:
                continue  # no paired acquisition directory -> not a usable epoch

            group = [refpath]
            syncpath = os.path.join(base_path, base, self.SYNC_FILE)
            if os.path.isfile(syncpath):
                group.append(syncpath)
            for a in acq:
                group.extend(self._non_frame_files(os.path.join(base_path, a)))

            groups.append(group)

        return groups

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @classmethod
    def _acquisition_dirs(cls, names: list[str], base: str) -> list[str]:
        """Sibling directory names of the form ``<base>-NNN``, sorted."""
        pat = re.compile(rf"^{re.escape(base)}-\d+$")
        return sorted(n for n in names if pat.match(n))

    @classmethod
    def _non_frame_files(cls, adir: str) -> list[str]:
        """Full paths of the non-TIFF, non-hidden files directly in ``adir``.

        These are the PrairieView config/metadata files (.xml/.pcf/.env/.cfg,
        frame-time sidecars) that anchor the acquisition directory; the image
        reader resolves the TIFF frames from each anchor's directory.
        """
        if not os.path.isdir(adir):
            return []
        out = []
        for name in sorted(os.listdir(adir)):
            if name.startswith("."):
                continue
            full = os.path.join(adir, name)
            if not os.path.isfile(full):
                continue
            if os.path.splitext(name)[1].lower() in cls.FRAME_EXTENSIONS:
                continue  # frames are resolved by the reader, not listed here
            out.append(full)
        return out
