"""
ndi.calc - NDI calculator implementations.

Contains concrete calculator classes organized by domain.

Submodules:
    example: Example/demo calculators (SimpleCalc)
"""

from . import example, stimulus
from .tuning_fit import TuningFit

__all__ = ["example", "stimulus", "TuningFit"]
