# NDI-Python

**Neuroscience ndi_gui_Data Interface** - Python implementation.

NDI provides a unified framework for managing, querying, and analyzing neuroscience experimental data across different acquisition systems.

## Overview

NDI-Python is a complete port of the [MATLAB NDI](https://github.com/VH-ndi_gui_Lab/NDI-matlab) codebase, providing:

- **ndi_document-based metadata** with JSON schema validation
- **SQLite database** backend for persistent storage and rich queries
- **Time synchronization** across heterogeneous recording devices
- **DAQ readers** for Intan, Blackrock, CED Spike2, and SpikeGadgets
- **Application framework** for spike sorting, stimulus analysis, and tuning curves
- **Cloud integration** with NDI Cloud for sharing and collaboration
- **13 ontology providers** for standardized scientific vocabularies

## Quick Start

```python
from ndi import ndi_document, ndi_query, ndi_session_dir
from ndi.session import ndi_session_mock

# Create and query documents
with ndi_session_mock('demo') as session:
    doc = ndi_document('base')
    session.database_add(doc)
    results = session.database_search(ndi_query.all())
    print(f"Found {len(results)} documents")
```

## Installation

```bash
git clone https://github.com/Waltham-ndi_gui_Data-Science/NDI-python.git
cd NDI-python
```

See the [Getting Started guide](getting-started.md) or the [README](https://github.com/Waltham-ndi_gui_Data-Science/NDI-python#readme) for full installation instructions including VH-ndi_gui_Lab dependency setup.

## MATLAB Migration

If you're migrating from MATLAB NDI, see [MATLAB_MAPPING.md](https://github.com/Waltham-ndi_gui_Data-Science/NDI-python/blob/main/MATLAB_MAPPING.md) for a complete function-by-function reference.
