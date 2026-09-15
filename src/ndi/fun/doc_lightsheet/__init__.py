"""ndi.fun.doc_lightsheet - lightsheet OME-Zarr document helpers (Python placeholder).

The MATLAB counterpart is `+ndi/+fun/+doc/+lightsheet/` (`fromOMEZarr`,
`makePyramid`, `makeSourceFile`, `chooseLevel`, `levelTable`,
`viewCommand`). None are ported yet; see
``ndi_matlab_python_bridge.yaml`` next to this file for the
per-function status.

This package exists so that
`test_matlab_bridge_completeness.test_every_matlab_function_is_recorded`
can find the bridge YAML that records the deferrals. When the ingest
boundary is drawn on the Python side, the functions port as a group
into a `doc_lightsheet.py` flat file (same shape as `doc_gene.py`),
and this ``__init__.py`` is replaced.
"""
