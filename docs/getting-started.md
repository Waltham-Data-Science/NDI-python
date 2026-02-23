# Getting Started

## Installation

### Prerequisites

- Python 3.10 or later
- Git (for installing VH-Lab dependencies)

### Install from source

```bash
git clone https://github.com/Waltham-Data-Science/NDI-python.git
cd NDI-python
python -m venv venv
source venv/bin/activate  # Linux/macOS (venv\Scripts\activate on Windows)
python ndi_install.py
```

The installer clones all dependencies, installs packages, and validates your setup.
Run `python -m ndi check` at any time to verify your installation.

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
