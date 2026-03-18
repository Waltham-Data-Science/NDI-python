"""
NDI - Neuroscience ndi_gui_Data Interface

Python implementation of NDI for managing neuroscience experimental data.

This package provides:
- ndi_document management with JSON schemas
- ndi_database operations for storing and querying documents
- Time synchronization across data sources
- ndi_gui_Data acquisition system abstraction

Example:
    from ndi import ndi_document, ndi_query, ndi_ido, ndi_database

    # Create a new document
    doc = ndi_document('base', **{'base.name': 'my_experiment'})

    # Create a query
    q = ndi_query('base.name') == 'my_experiment'

    # Generate unique IDs
    ido = ndi_ido()
    print(ido.id)

    # Open a database
    db = ndi_database('/path/to/session')
    db.add(doc)
"""

# Import time module (Phase 4)
# Import daq and file modules (Phase 5)
# Import epoch module (Phase 6)
# Import Phase 10: Cloud API client
# Import Phase 11: Schema validation
from . import calc, cloud, common, daq, epoch, file, session, setup, time, util, validate, validators

# Import Phase 9: ndi_app framework and calculators
from .app import ndi_app
from .app.appdoc import DocExistsAction, ndi_app_appdoc

# Import session and cache modules (Phase 7)
from .cache import ndi_cache
from .calculator import ndi_calculator
from .common import getLogger, ndi_common_PathConstants, timestamp
from .database import ndi_database, open_database
from .dataset import ndi_dataset, ndi_dataset_dir
from .document import ndi_document
from .documentservice import ndi_documentservice
from .element import ndi_element
from .element_timeseries import ndi_element_timeseries
from .ido import ndi_ido
from .neuron import ndi_neuron
from .probe import ndi_probe
from .query import ndi_query
from .session import empty_id, ndi_session, ndi_session_dir

# Import Phase 8 classes
from .subject import ndi_subject

__version__ = "0.1.0"
__author__ = "VH-ndi_gui_Lab"


def version() -> tuple:
    """Return the NDI version string and repository URL.

    MATLAB equivalent: ndi.version

    Returns:
        Tuple of ``(version_string, url)``.  The version string is the
        Git commit hash when running inside a checkout, otherwise the
        package version.
    """
    import subprocess
    from pathlib import Path as _Path

    url = "https://github.com/Waltham-ndi_gui_Data-Science/NDI-python"
    # Try git describe from the repo root
    repo = _Path(__file__).resolve().parent.parent.parent
    try:
        result = subprocess.run(
            ["git", "describe", "--always", "--dirty"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(repo),
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip(), url
    except Exception:
        pass
    return __version__, url


__all__ = [
    "ndi_ido",
    "ndi_query",
    "ndi_document",
    "ndi_database",
    "open_database",
    "ndi_common_PathConstants",
    "timestamp",
    "getLogger",
    "time",
    "daq",
    "file",
    "epoch",
    "ndi_element",
    "ndi_probe",
    "ndi_documentservice",
    "ndi_cache",
    "session",
    "ndi_session",
    "ndi_session_dir",
    "empty_id",
    "ndi_subject",
    "ndi_element_timeseries",
    "ndi_neuron",
    "ndi_dataset",
    "ndi_dataset_dir",
    "ndi_app",
    "ndi_app_appdoc",
    "DocExistsAction",
    "ndi_calculator",
    "calc",
    "cloud",
    "setup",
    "util",
    "validate",
    "validators",
    "version",
]
