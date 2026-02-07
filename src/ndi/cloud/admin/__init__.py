"""
ndi.cloud.admin - Administrative tools for NDI Cloud.

Submodules:
    doi      — DOI generation and registration
    crossref — Crossref XML/metadata generation
"""

from . import doi
from . import crossref

__all__ = ['doi', 'crossref']
