"""
ndi.dataset - Multi-session dataset container.

A Dataset manages multiple sessions, either linked (by reference) or
ingested (copied into the dataset's own database). Datasets have their
own session for storing dataset-level documents and metadata.

MATLAB equivalents:
    ndi.dataset      -> ndi.dataset.Dataset (or ndi.Dataset)
    ndi.dataset.dir  -> ndi.dataset.dir (constructor for directory-based datasets)
"""

from ._dataset import Dataset as _DatasetBase  # noqa: F401
from ._dataset import DatasetDir

# For backward compatibility, ``ndi.dataset.Dataset`` is ``DatasetDir``.
# The base class is available as ``ndi.dataset._DatasetBase`` if needed.
Dataset = DatasetDir

# MATLAB compatibility: ``ndi.dataset.dir(path)`` creates a directory-based
# dataset, mirroring the MATLAB constructor ``ndi.dataset.dir``.
dir = DatasetDir

__all__ = [
    "Dataset",
    "DatasetDir",
    "dir",
]
