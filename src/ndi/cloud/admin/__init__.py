"""
ndi.cloud.admin - Administrative tools for NDI Cloud.

Submodules:
    doi      — DOI generation and registration
    crossref — Crossref XML/metadata generation
"""

from . import crossref, doi

__all__ = ["doi", "crossref"]
