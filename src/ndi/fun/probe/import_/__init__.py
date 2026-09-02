"""ndi.fun.probe.import_ - importers that bring external analysis into NDI.

MATLAB counterpart: ``src/ndi/+ndi/+fun/+probe/+import/``

THE TRAILING UNDERSCORE IS NOT A STYLE CHOICE. MATLAB's package is ``+import``
and this port mirrors MATLAB names, but ``import`` is a Python KEYWORD: a
module of that name could be reached only through importlib, and
``ndi.fun.probe.import.kilosort`` would be a syntax error wherever it was
written. ``import_`` is PEP 8's convention for exactly this collision, and is
recorded as such in the bridge file.

MATLAB also holds a ``+kiasort`` importer here; it is not ported, being
blocked on the external kiasort toolbox (see NDI-python#122).
"""

from __future__ import annotations

from . import kilosort

__all__ = ["kilosort"]
