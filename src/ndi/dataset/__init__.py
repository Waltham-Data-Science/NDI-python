"""
ndi.dataset - Multi-session dataset container.

A ndi_dataset manages multiple sessions, either linked (by reference) or
ingested (copied into the dataset's own database). Datasets have their
own session for storing dataset-level documents and metadata.

MATLAB equivalents:
    ndi.dataset      -> ndi.dataset.ndi_dataset (or ndi.ndi_dataset)
    ndi.dataset.dir  -> ndi.dataset.dir (constructor for directory-based datasets)
"""

from ._dataset import ndi_dataset as _DatasetBase  # noqa: F401
from ._dataset import ndi_dataset_dir

# For backward compatibility, ``ndi.dataset.ndi_dataset`` is ``ndi_dataset_dir``.
# The base class is available as ``ndi.dataset._DatasetBase`` if needed.
ndi_dataset = ndi_dataset_dir

# MATLAB compatibility: ``ndi.dataset.dir(path)`` creates a directory-based
# dataset, mirroring the MATLAB constructor ``ndi.dataset.dir``.
dir = ndi_dataset_dir

__all__ = [
    "ndi_dataset",
    "ndi_dataset_dir",
    "dir",
]
