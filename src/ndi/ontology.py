"""
ndi.ontology - Ontology lookup across biological and scientific ontologies.

MATLAB equivalent: ndi.ontology, implemented in ndi-ontology-matlab.

The implementation lives in the ``ndi_ontology`` distribution
(https://github.com/Waltham-Data-Science/ndi-ontology-python), the Python
companion to ndi-ontology-matlab. This module re-exports it, so call sites in
NDI-python keep reading::

    from ndi.ontology import lookup

which is what keeps them mirroring MATLAB's ``ndi.ontology.lookup``.

Why the implementation is not in this repository: NDI-matlab no longer
contains ``+ndi/ontology.m`` either. The ontology code was extracted into
ndi-ontology-matlab and is pulled back in through ``requirements.txt``; this
module is the same split, so that the Python port tracks the repository the
MATLAB code now actually lives in.

Why the distribution is named ``ndi_ontology`` rather than ``ndi.ontology``:
MATLAB merges the ``ndi`` namespace across every folder on the path, so
ndi-ontology-matlab contributes to the same namespace for free. Python cannot
do that for a *regular* package, and ``ndi`` is a regular package because
``ndi/__init__.py`` carries the public API. Making ``ndi`` a PEP 420 namespace
package would restore the exact mirror at the cost of moving that entire API
surface and reworking packaging and the symmetry harness -- disproportionate
to this split. The reasoning is recorded in ndi-ontology-python's
``ndi_matlab_python_bridge.yaml``.
"""

from __future__ import annotations

import sys

from ndi_ontology import OntologyResult, clearCache, lookup, providers

# Resolve `from ndi.ontology.providers import CLProvider` to the real module
# rather than an AttributeError. Aliasing rather than re-implementing keeps a
# single module object, so PROVIDER_REGISTRY and the lookup cache have one
# home no matter which name a caller imports through.
sys.modules[__name__ + ".providers"] = providers

__all__ = ["OntologyResult", "lookup", "clearCache", "providers"]
