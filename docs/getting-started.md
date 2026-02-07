# Getting Started

## Installation

### Prerequisites

- Python 3.10 or later
- Git (for installing VH-Lab dependencies)

### Install from source

```bash
git clone https://github.com/Waltham-Data-Science/NDI-python.git
cd NDI-python

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # Linux/macOS

# Install VH-Lab dependencies (not yet on PyPI)
# DID-python has a packaging bug — use PYTHONPATH instead of pip install
git clone https://github.com/VH-Lab/DID-python.git /tmp/DID-python
git clone https://github.com/VH-Lab/vhlab-toolbox-python.git /tmp/vhlab-toolbox-python
export PYTHONPATH="/tmp/DID-python/src:/tmp/vhlab-toolbox-python:$PYTHONPATH"

# Install NDI-python (--no-deps avoids broken DID pip install)
pip install -e ".[dev]" --no-deps
pip install numpy networkx jsonschema requests pytest pytest-cov scipy
```

## Basic Usage

### Creating Documents

```python
from ndi import Document

# Create a document from a schema
doc = Document('base')
print(f"ID: {doc.id}")
print(f"Type: {doc.document_properties['document_class']['class_name']}")
```

### Querying

```python
from ndi import Query

# Exact match
q = Query('base.name') == 'my_experiment'

# Type query
q_type = Query('').isa('subject')

# Combine with logical operators
q_combined = q & q_type

# Dependency query
q_dep = Query('').depends_on('element_id', 'some-uuid')
```

### Sessions

```python
from ndi import DirSession, Document, Query

# Create a directory-backed session
session = DirSession('my_experiment', '/path/to/data')

# Add documents
doc = Document('base')
session.database_add(doc)

# Search
results = session.database_search(Query.all())
```

### Testing with MockSession

```python
from ndi.session import MockSession
from ndi import Document, Query

with MockSession('test') as session:
    session.database_add(Document('base'))
    results = session.database_search(Query('').isa('base'))
    assert len(results) == 1
```

## Running Tests

```bash
pytest tests/ -v
```
