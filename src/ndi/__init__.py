"""
NDI - Neuroscience Data Interface

Python implementation of NDI for managing neuroscience experimental data.

This package provides:
- Document management with JSON schemas
- Database operations for storing and querying documents
- Time synchronization across data sources
- Data acquisition system abstraction

Example:
    from ndi import Document, Query, Ido, Database

    # Create a new document
    doc = Document('base', **{'base.name': 'my_experiment'})

    # Create a query
    q = Query('base.name') == 'my_experiment'

    # Generate unique IDs
    ido = Ido()
    print(ido.id)

    # Open a database
    db = Database('/path/to/session')
    db.add(doc)
"""

from .ido import Ido
from .query import Query
from .document import Document
from .database import Database, open_database
from .common import PathConstants, timestamp, get_logger

# Import time module (Phase 4)
from . import time

# Import daq and file modules (Phase 5)
from . import daq
from . import file

# Import epoch module (Phase 6)
from . import epoch
from .element import Element
from .probe import Probe
from .documentservice import DocumentService

# Import session and cache modules (Phase 7)
from .cache import Cache
from . import session
from .session import Session, DirSession, empty_id

# Import Phase 8 classes
from .subject import Subject
from .element_timeseries import ElementTimeseries
from .neuron import Neuron
from .dataset import Dataset

# Import Phase 9: App framework and calculators
from .app import App
from .app.appdoc import AppDoc, DocExistsAction
from .calculator import Calculator
from . import calc

# Import Phase 10: Cloud API client
from . import cloud

# Import Phase 11: Schema validation
from . import validate

__version__ = '0.1.0'
__author__ = 'VH-Lab'


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

    url = 'https://github.com/Waltham-Data-Science/NDI-python'
    # Try git describe from the repo root
    repo = _Path(__file__).resolve().parent.parent.parent
    try:
        result = subprocess.run(
            ['git', 'describe', '--always', '--dirty'],
            capture_output=True, text=True, timeout=5,
            cwd=str(repo),
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip(), url
    except Exception:
        pass
    return __version__, url


__all__ = [
    'Ido',
    'Query',
    'Document',
    'Database',
    'open_database',
    'PathConstants',
    'timestamp',
    'get_logger',
    'time',
    'daq',
    'file',
    'epoch',
    'Element',
    'Probe',
    'DocumentService',
    'Cache',
    'session',
    'Session',
    'DirSession',
    'empty_id',
    'Subject',
    'ElementTimeseries',
    'Neuron',
    'Dataset',
    'App',
    'AppDoc',
    'DocExistsAction',
    'Calculator',
    'calc',
    'cloud',
    'validate',
    'version',
]
