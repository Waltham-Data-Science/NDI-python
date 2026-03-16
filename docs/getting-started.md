# Getting Started

## Installation

### Prerequisites

- Python 3.10 or later
- Git (for installing VH-ndi_gui_Lab dependencies)

### Install from source

```bash
git clone https://github.com/Waltham-ndi_gui_Data-Science/NDI-python.git
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
from ndi import ndi_document

# Create a document from a schema
doc = ndi_document('base')
print(f"ID: {doc.id}")
print(f"Type: {doc.document_properties['document_class']['class_name']}")
```

### Querying

```python
from ndi import ndi_query

# Exact match
q = ndi_query('base.name') == 'my_experiment'

# Type query
q_type = ndi_query('').isa('subject')

# Combine with logical operators
q_combined = q & q_type

# Dependency query
q_dep = ndi_query('').depends_on('element_id', 'some-uuid')
```

### Sessions

```python
from ndi import ndi_session_dir, ndi_document, ndi_query

# Create a directory-backed session
session = ndi_session_dir('my_experiment', '/path/to/data')

# Add documents
doc = ndi_document('base')
session.database_add(doc)

# Search
results = session.database_search(ndi_query.all())
```

### Testing with ndi_session_mock

```python
from ndi.session import ndi_session_mock
from ndi import ndi_document, ndi_query

with ndi_session_mock('test') as session:
    session.database_add(ndi_document('base'))
    results = session.database_search(ndi_query('').isa('base'))
    assert len(results) == 1
```

## Running Tests

```bash
pytest tests/ -v
```
