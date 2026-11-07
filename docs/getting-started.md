# Getting Started

## Installation

To *use* NDI (the `ndi` command and the napari viewers, also from NDI-matlab)
without setting up Python yourself, use the double-click installer in
[`install/`](https://github.com/Waltham-Data-Science/NDI-python/tree/main/install):
it needs no Python, git or compiler and puts everything in `~/.ndi`. The rest
of this page is for working with NDI from your own Python environment.

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

### Choosing where the dependencies are cloned

`ndi_install.py` clones the dependencies that are not on PyPI into a tools
folder, `~/.ndi/tools` by default. To put them somewhere else, give the folder:

```bash
python ndi_install.py --tools-dir /path/to/ndi-tools
```

The installer records the folder in an `ndi-deps.pth` file in your
environment, so Python finds the tools, and later runs of `ndi_install.py` (and
`ndi.update.install()`) keep using it without `--tools-dir`.

To move an existing tools folder, click **Tools folder...** in the preferences
editor (`ndi.gui.preferences_editor()`), or from Python:

```python
import ndi.update
ndi.update.toolsFolder()                          # where the tools are now
ndi.update.moveToolsFolder("/path/to/ndi-tools")  # move them; restart Python afterwards
```

This copies the folder and checks the copy, points `ndi-deps.pth` at the new
folder (keeping the old file as `ndi-deps.pth.bak`) and deletes the old
folder. If something goes wrong before `ndi-deps.pth` is changed, nothing is
changed. The NDI installer (`install/`) always uses `~/.ndi` and has no tools
folder to move.

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
