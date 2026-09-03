"""ndi.fun.probe.import_ - importers that bring external analysis into NDI.

MATLAB counterpart: ``src/ndi/+ndi/+fun/+probe/+import/``

THE TRAILING UNDERSCORE IS NOT A STYLE CHOICE. MATLAB's package is ``+import``
and this port mirrors MATLAB names, but ``import`` is a Python KEYWORD: a
module of that name could be reached only through importlib, and
``ndi.fun.probe.import.kilosort`` would be a syntax error wherever it was
written. ``import_`` is PEP 8's convention for exactly this collision, and is
recorded as such in the bridge file.

MATLAB's ``+kiasort`` importer is here too. Its IMPORT side is ported in
full; its ``run`` and ``curate``, which drive the KIASORT MATLAB toolbox,
are not and cannot be (see :mod:`ndi.fun.probe.import_.kiasort`).
"""

from __future__ import annotations

from . import epoch_map, kiasort, kilosort

__all__ = ["epoch_map", "kiasort", "kilosort"]
