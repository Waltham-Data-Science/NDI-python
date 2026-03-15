# Instructions: Update DID-python to Match DID-matlab SQLite Behavior

## Background

DID-python (`pip show did`, installed at `/usr/local/lib/python3.11/dist-packages/did/`) is a Python port of [VH-Lab/DID-matlab](https://github.com/VH-Lab/DID-matlab). The SQLite implementation has two critical gaps versus the MATLAB original:

1. **`_do_add_doc` does not populate `fields`/`doc_data` tables** — it only stores JSON blobs in `docs`. The MATLAB version (`did.implementations.sqlitedb.do_add_doc`) uses `did.implementations.doc2sql` to flatten documents and populate both tables.

2. **`search` uses brute-force JSON deserialization** instead of SQL queries against `doc_data`. The MATLAB version builds SQL queries from query structs and runs them directly.

This means databases created by Python cannot be searched by MATLAB, and vice versa (MATLAB's search relies on `doc_data`).

## Reference Files

**DID-matlab** (authoritative, on `main` branch of https://github.com/VH-Lab/DID-matlab):
- `src/did/+did/+implementations/sqlitedb.m` — SQLite implementation (uses mksqlite)
- `src/did/+did/+implementations/doc2sql.m` — Document-to-SQL flattener
- `src/did/+did/database.m` — Base class with `search_doc_ids`, `get_sql_query_str`, `query_struct_to_sql_str`
- `src/did/+did/query.m` — Query class with `to_searchstructure` resolving `isa`/`depends_on`
- `src/did/+did/+datastructures/fieldsearch.m` — In-memory field search (used by non-SQL backends)

**DID-python** (to be updated):
- `/usr/local/lib/python3.11/dist-packages/did/implementations/sqlitedb.py`
- `/usr/local/lib/python3.11/dist-packages/did/implementations/doc2sql.py`
- `/usr/local/lib/python3.11/dist-packages/did/database.py`
- `/usr/local/lib/python3.11/dist-packages/did/query.py`
- `/usr/local/lib/python3.11/dist-packages/did/datastructures.py`

**NDI-python** (consumer — has workarounds to remove after DID is fixed):
- `/home/user/NDI-python/src/ndi/database.py` — `SQLiteDriver` class with `_populate_doc_data` workaround

## Task 1: Populate `fields`/`doc_data` in `_do_add_doc`

### What MATLAB Does

In `sqlitedb.m`, `do_add_doc` (line ~256-404):

1. Calls `did.implementations.doc2sql(document_obj)` to produce a struct array of "meta-tables"
2. The first meta-table is always `"meta"` with columns: `doc_id`, `class`, `superclass`, `datestamp`, `creation`, `deletion`, `depends_on`
3. Subsequent meta-tables are named after top-level document fields (e.g., `"base"`, `"element"`, `"daqsystem"`) with sub-field columns
4. For each column (skipping `doc_id`), it calls `get_field_idx(group_name, field_name)` to look up or create a `fields` row
5. Inserts all `(doc_idx, field_idx, value)` triples into `doc_data` in bulk

### How `doc2sql` Flattens Documents

Given a document with properties:
```json
{
  "document_class": {"class_name": "element", "superclasses": [{"definition": "$NDIDOCUMENTPATH/base.json"}]},
  "base": {"id": "abc", "name": "elec1", "session_id": "sess1", "datestamp": "2024-01-01"},
  "element": {"type": "probe", "reference": 1},
  "depends_on": [{"name": "subject_id", "value": "xyz"}]
}
```

`doc2sql` produces:

**Meta table** (`name="meta"`):
| column name | value |
|---|---|
| doc_id | `"abc"` |
| class | `"element"` |
| superclass | `"base"` (extracted from definitions, stripped path and `.json`) |
| datestamp | `"2024-01-01"` |
| creation | `""` |
| deletion | `""` |
| depends_on | `"subject_id,xyz;"` (formatted as `name,value;name,value;...`) |

**Base table** (`name="base"`):
| column name | value |
|---|---|
| doc_id | `"abc"` |
| id | `"abc"` |
| name | `"elec1"` |
| session_id | `"sess1"` |
| datestamp | `"2024-01-01"` |

**Element table** (`name="element"`):
| column name | value |
|---|---|
| doc_id | `"abc"` |
| type | `"probe"` |
| reference | `1` |

### How `get_field_idx` Works

The field name stored in the `fields` table uses the format `{group_name}.{field_name}` — e.g., `"meta.class"`, `"base.name"`, `"element.type"`.

Triple-underscores in column names from `doc2sql` are converted back to dots: `"___"` → `"."`.

The `fields` table columns are:
- `class`: the group/table name (e.g., `"meta"`, `"base"`, `"element"`)
- `field_name`: the dot-separated path (e.g., `"meta.class"`, `"base.name"`)
- `json_name`: dots replaced with `___` (e.g., `"meta___class"`)
- `field_idx`: auto-increment primary key

A `fields_cache` (in-memory dict) avoids repeated DB lookups.

### What to Change in DID-python

In `sqlitedb.py`, method `_do_add_doc` (currently lines 145-180):

After the `docs` INSERT (line 168) and before the `branch_docs` INSERT (line 173), add logic to:

1. Call a Python equivalent of `doc2sql` to flatten the document
2. For each (field_name, value) pair, look up or create a `field_idx` in the `fields` table
3. Bulk-insert all `(doc_idx, field_idx, value)` triples into `doc_data`

You can either:
- **Option A**: Update the existing `doc2sql.py` to match MATLAB's `doc2sql.m` and call it from `_do_add_doc`
- **Option B**: Implement the flattening inline in `_do_add_doc` (simpler)

**Critical**: The field names in the `fields` table MUST match what MATLAB's `query_struct_to_sql_str` expects. Specifically, the search queries use these field names:
- `"meta.class"` — the document class name (from `document_class.class_name`)
- `"meta.superclass"` — comma-separated superclass names (extracted from `document_class.superclasses[].definition`, with path and `.json` stripped)
- `"meta.depends_on"` — semicolon-separated `name,value;` pairs
- `"meta.datestamp"` — from `base.datestamp`
- `"{group}.{field}"` — for all other top-level groups and their sub-fields (e.g., `"base.name"`, `"element.type"`)

### Superclass Extraction

MATLAB extracts superclass names from the `definition` field of each superclass entry:
```matlab
superclass = getField(doc_props, 'document_class.superclasses');
if isstruct(superclass)
    superclass = regexprep({superclass.definition},{'.+/','\..+$'},'');
    superclass = strjoin(unique(superclass), ', ');
end
```

This takes `"$NDIDOCUMENTPATH/daq/daqsystem.json"` → strips path → strips extension → `"daqsystem"`.

Multiple superclasses are joined as `"base, daqsystem"` (comma-space separated, alphabetically sorted/unique).

### Depends_on Serialization

MATLAB serializes `depends_on` as:
```matlab
allData = [{dependsOn.name}; {dependsOn.value}];
dependsOn = sprintf('%s,%s;',allData{:});
```

This produces: `"filenavigator_id,abc123;daqreader_id,def456;"`.

The search query for `depends_on` uses `LIKE "%name,value;%"`.

### Nested Struct Fields (via `getMetaTableFrom`)

For each top-level field group (excluding `depends_on`, `document_class`, `files`), MATLAB creates a "meta-table" with:
- A `doc_id` column
- One column per sub-field, with nested structs flattened using `___` separator

Example: if `element` has `{"type": "probe", "details": {"count": 3}}`, the columns would be:
- `type` → `"probe"` (stored as field `element.type`)
- `details___count` → `3` (stored as field `element.details.count` after `___` → `.` conversion)

## Task 2: Update `query.to_search_structure` to Resolve `isa` and `depends_on`

### What MATLAB Does

In `query.m`, the `to_searchstructure` method (line ~173-227) resolves `isa` and `depends_on` into lower-level operations BEFORE passing to search:

**`isa` resolution** — converts to `OR(hasanysubfield_contains_string, contains_string)`:
```matlab
if strcmpi('isa', operation)
    findinsubfield = struct('field','document_class.superclasses',...
        'operation','hasanysubfield_contains_string',...
        'param1','definition', 'param2', classname);
    findinmainfield = struct('field','document_class.definition', ...
        'operation','contains_string', 'param1', classname, 'param2', '');
    ss.field = '';
    ss.operation = 'or';
    ss.param1 = findinsubfield;
    ss.param2 = findinmainfield;
end
```

**`depends_on` resolution** — converts to `hasanysubfield_exact_string`:
```matlab
if strcmpi('depends_on', operation)
    param1 = {'name','value'};
    param2 = {name_param, value_param};
    if strcmp(param2{1},'*')  % wildcard: ignore name
        param1 = param1(2);
        param2 = param2(2);
    end
    ss = struct('field','depends_on','operation','hasanysubfield_exact_string');
    ss.param1 = param1;
    ss.param2 = param2;
end
```

### What DID-python Currently Does

In `query.py` line 52-55:
```python
def to_search_structure(self):
    # A full implementation would recursively resolve 'isa', 'depends_on', etc.
    # This is a simplified version for now.
    return self.search_structure
```

It passes `isa` and `depends_on` through unchanged, relying on `field_search` in `datastructures.py` to handle them directly. This works for brute-force search but NOT for SQL-based search.

### What to Change

Update `query.py`'s `to_search_structure` to resolve `isa` and `depends_on` into lower-level operations, matching MATLAB's logic. This is needed so the SQL query builder can translate them.

However, note that `datastructures.py`'s `field_search` also handles `isa` and `depends_on` directly (for non-SQL backends), so you should NOT break that path. The cleanest approach: resolve in `to_search_structure` and let `field_search` handle the resolved operations.

## Task 3: Add SQL-Based Search (Optional but Recommended)

### What MATLAB Does

MATLAB's `did.database` base class (on `main` branch) has a SQL-based `do_search` that:

1. Calls `search_doc_ids(query_struct, branch_id)` which recursively:
   - For AND queries (struct arrays): intersects results from each sub-query
   - For OR queries: unions results from each sub-query
   - For leaf queries: calls `get_sql_query_str` → runs SQL → returns doc_ids

2. `get_sql_query_str` builds:
```sql
SELECT DISTINCT docs.doc_id
FROM docs, branch_docs, doc_data, fields
WHERE docs.doc_idx = doc_data.doc_idx
  AND docs.doc_idx = branch_docs.doc_idx
  AND branch_docs.branch_id = "a"
  AND fields.field_idx = doc_data.field_idx
  AND {per-operation clause}
```

3. `query_struct_to_sql_str` maps operations to SQL:
   - `exact_string` → `fields.field_name="X" AND doc_data.value = "Y"`
   - `contains_string` → `fields.field_name="X" AND doc_data.value LIKE "%Y%"`
   - `regexp` → `fields.field_name="X" AND regex(doc_data.value, "Y") NOT NULL`
     - Note: MATLAB uses mksqlite's built-in `regex()` function. Python's sqlite3 does NOT have regex by default — you'd need `connection.create_function("regexp", 2, ...)`.
   - `isa` → `(fields.field_name="meta.class" AND doc_data.value = "X") OR (fields.field_name="meta.superclass" AND regex(doc_data.value, "(^|, )X(,|$)") NOT NULL)`
   - `depends_on` → `fields.field_name="meta.depends_on" AND doc_data.value LIKE "%name,value;%"`
   - `hasfield` → `fields.field_name="X" OR fields.field_name LIKE "X.%"`
   - Numeric comparisons: `doc_data.value < Y`, etc.
   - `NOT` prefix: adds `NOT` before the value check

### What to Change

You can either:
- **Option A (Recommended for parity)**: Override `search` in `SQLiteDB` to build SQL queries against `doc_data`, matching MATLAB's `query_struct_to_sql_str` logic
- **Option B (Minimum viable)**: Keep the brute-force `field_search` approach in `database.py` but ensure `doc_data` is populated (Task 1) so MATLAB can search Python-created DBs

Option A gives full symmetry. Option B gives cross-language write compatibility but not search performance parity.

## Task 4: Remove NDI-python Workarounds

After DID-python is updated, remove the workaround code from NDI-python's `database.py`:

1. Remove `SQLiteDriver._flatten_document()` (static method)
2. Remove `SQLiteDriver._get_or_create_field_idx()`
3. Remove `SQLiteDriver._populate_doc_data()`
4. Remove `SQLiteDriver._populate_doc_data_with_cursor()`
5. Remove the `_populate_doc_data` calls in `add()`, `bulk_add()`, and `update()`
6. Remove the `doc_data` cleanup in `update()`

The `bulk_add` method bypasses DID-python's `_do_add_doc` for performance — after DID is fixed, either:
- Route `bulk_add` through DID's `add_docs` (simpler, slightly slower), or
- Keep the direct SQL but call DID's flattening logic instead of NDI's

## Testing

1. Create a fresh database with Python, add documents, verify `fields` and `doc_data` tables are populated correctly
2. Search the Python-created database with MATLAB — verify `isa`, `depends_on`, `exact_string` queries all work
3. Create a database with MATLAB, search it with Python — verify all query types work
4. Run the existing symmetry tests in `/home/user/NDI-python/tests/symmetry/`

## Key Gotcha: Field Name Format

The most critical detail for cross-language compatibility is that **field names in the `fields` table must match between MATLAB and Python**. MATLAB uses `doc2sql` which produces:

- `meta.class` (not `document_class.class_name`)
- `meta.superclass` (not `document_class.superclasses`)
- `meta.depends_on` (not `depends_on`)
- `meta.datestamp` (not `base.datestamp`)
- `base.id`, `base.name`, etc.
- `element.type`, `element.reference`, etc.

Python's current workaround in NDI uses raw dotted paths like `document_class.class_name` and `depends_on(0).name` — these do NOT match what MATLAB expects. The Python `doc2sql` must match MATLAB's `doc2sql` field naming exactly.
