# MATLAB Migration Guide

This page summarizes key differences when migrating from MATLAB NDI to Python NDI.

For the complete function-by-function mapping, see [MATLAB_MAPPING.md](https://github.com/Waltham-Data-Science/NDI-python/blob/main/MATLAB_MAPPING.md).

## Key API Differences

### Query Syntax

**MATLAB:**
```matlab
q = ndi.query('base.name', 'exact_string', 'my_experiment');
q_type = ndi.query('', 'isa', 'subject');
q_combined = ndi.query(q, '&', q_type);
```

**Python:**
```python
q = Query('base.name') == 'my_experiment'
q_type = Query('').isa('subject')
q_combined = q & q_type
```

### Method Naming

MATLAB uses camelCase; Python uses snake_case:

| MATLAB | Python |
|--------|--------|
| `doc.setSessionId(sid)` | `doc.set_session_id(sid)` |
| `doc.setDependencyValue(n, v)` | `doc.set_dependency_value(n, v)` |
| `session.databaseAdd(doc)` | `session.database_add(doc)` |
| `session.databaseSearch(q)` | `session.database_search(q)` |

### Properties vs Methods

Some MATLAB methods become Python properties:

| MATLAB | Python |
|--------|--------|
| `doc.id()` | `doc.id` (property) |
| `doc.session_id()` | `doc.session_id` (property) |

Note: `session.id()` remains a **method** in Python.

### Class Construction

**MATLAB:**
```matlab
session = ndi.session.dir('my_experiment', '/path/to/data');
doc = ndi.document('base');
```

**Python:**
```python
session = DirSession('my_experiment', '/path/to/data')
doc = Document('base')
```
