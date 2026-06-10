"""
ndi.fun.probe.import_ - import probe data from external pipelines into NDI.

MATLAB equivalent: +ndi/+fun/+probe/+import/

NAMING DIVERGENCE (single, unavoidable): the MATLAB package is
``+ndi/+fun/+probe/+import``. ``import`` is a reserved word in Python, so this
subpackage is named ``import_`` and the importable path is
``ndi.fun.probe.import_`` (e.g. ``ndi.fun.probe.import_.kilosort.session``).
This is documented in this package's ``ndi_matlab_python_bridge.yaml``.
"""

from __future__ import annotations

from . import kilosort

__all__ = ["kilosort"]
