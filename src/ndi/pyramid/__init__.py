"""Napari-independent multiscale image pyramid loader for NDI.

This package holds the retrieval logic for a ``lightsheetZarrPyramid``
document: enumerating level documents, building lazy dask arrays per
level, resolving ``chunk.bin_#`` files through the NDI cloud API,
pre-fetching the coarsest level at launch, and (opt-in) substituting
coarser cached data under unfinished fine tiles so the picture never
paints black holes on a slow link.

The classes here KNOW NOTHING about napari. That is deliberate: the
same loader can drive napari, matplotlib, Jupyter notebooks, headless
batch analyses, or a MATLAB comparison harness once the sibling
namespace is written under ``+ndi/+pyramid/`` in NDI-matlab.

Public surface:

* :class:`ImagePyramidLoader` -- the facade a caller talks to.
* :mod:`multiscale` -- dask assembly + level-document parsing.
* :mod:`upsample_fallback` -- geometry + upsample reader.
"""

from __future__ import annotations
