"""
ndi.daq.fun - Helper functions for ndi.daq systems.

MATLAB equivalent: +ndi/+daq/+fun/

Provides :func:`~ndi.daq.fun.ingest_epoch_documents.ingestEpochDocuments`,
the per-epoch work of ingestion, run serially or on worker processes.
"""

from __future__ import annotations

from .ingest_epoch_documents import ingest_epoch_documents, ingestEpochDocuments

__all__ = ["ingestEpochDocuments", "ingest_epoch_documents"]
