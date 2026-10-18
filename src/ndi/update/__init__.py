"""ndi.update - check for, and install, a newer NDI-python.

MATLAB counterpart: ``src/ndi/+ndi/+update/`` (NDI-matlab)

NDI-python has no releases: every install follows the ``main`` branch on
GitHub, so an update is always "the commits main has that this copy lacks".

    >>> import ndi.update
    >>> result = ndi.update.check()     # report; changes nothing
    >>> ndi.update.install()            # update, after asking

From a terminal: ``ndi update --check`` and ``ndi update``.

NDI-matlab's ``ndi.update.check`` also checks an NDI-python that the NDI
installer put in ``~/.ndi`` (its ``checkPython``), reading the same
``~/.ndi/install.json`` receipt this package does.
"""

from .check import check
from .check_on_startup import checkOnStartup
from .install import UpdateError, install
from .install_type import installType
from .modification_summary import modificationSummary

__all__ = [
    "check",
    "checkOnStartup",
    "install",
    "installType",
    "modificationSummary",
    "UpdateError",
]
