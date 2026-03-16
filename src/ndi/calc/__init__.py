"""
ndi.calc - NDI calculator implementations.

Contains concrete calculator classes organized by domain.

Submodules:
    example: Example/demo calculators (ndi_calc_example_simple)
"""

from . import example, stimulus
from .tuning_fit import ndi_calc_tuning__fit

__all__ = ["example", "stimulus", "ndi_calc_tuning__fit"]
