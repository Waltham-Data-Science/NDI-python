"""
ndi.query - search an ndi.database for ndi.documents

Query objects define searches for ndi.documents; they are passed to the
ndi.database.search() function.

Inherits from did.query.Query, using search_structure as the single
source of truth. Provides both Pythonic query construction (via
operators) and MATLAB-compatible construction (via operation strings).

Pythonic examples:
    q = Query('element.name') == 'electrode1'
    q = (Query('element.type') == 'probe') & (Query('element.name').contains('elec'))

MATLAB-compatible examples:
    q = Query('', 'isa', 'base')
    q = Query('base.name', 'exact_string', 'test')
    q = Query.from_search('ndi_document_property.name', 'regexp', '(.*)')
"""

from typing import Any

import did.query


class Query(did.query.Query):
    """NDI query class for searching documents.

    Inherits from did.query.Query, using ``search_structure`` as the
    single source of truth.  Adds Pythonic operator overloading for
    convenient query construction.

    The query can be constructed in two ways:

    1. Pythonic (recommended)::

        q = Query('field') == 'value'
        q = Query('field').contains('substring')

    2. MATLAB-compatible::

        q = Query('', 'isa', 'base')
        q = Query('base.name', 'exact_string', 'test')
        q = Query.from_search('field', 'exact_string', 'value')

    Attributes:
        field (str): The field being queried (computed from search_structure).
        operator (str): The Python-style operator (computed from search_structure).
        value (Any): The query value (computed from search_structure).
    """

    # Map Python operators to DID-style operations
    _OP_TO_DID = {
        "==": "exact_string",
        "!=": "~exact_string",
        ">": "greaterthan",
        ">=": "greaterthaneq",
        "<": "lessthan",
        "<=": "lessthaneq",
        "contains": "contains_string",
        "match": "regexp",
    }

    # Map DID operations back to Python-style for public interface
    _DID_TO_OP = {
        "exact_string": "==",
        "exact_number": "==",
        "~exact_string": "!=",
        "greaterthan": ">",
        "greaterthaneq": ">=",
        "lessthan": "<",
        "lessthaneq": "<=",
        "contains_string": "contains",
        "regexp": "match",
    }

    def __init__(
        self,
        field: str = "",
        operation: str | None = None,
        param1: Any = None,
        param2: Any = None,
    ):
        """Create a new query.

        Supports both Pythonic and MATLAB-style construction:

        Pythonic (chain operators after construction)::

            q = Query('base.name') == 'test'

        MATLAB-compatible (pass operation and params directly)::

            q = Query('', 'isa', 'base')
            q = Query('base.name', 'exact_string', 'test')

        Args:
            field: The document field to query (e.g., 'base.name',
                   'element.type'). Can be empty string for 'isa' queries.
            operation: Optional DID-style operation string (e.g.,
                   'exact_string', 'isa', 'regexp'). When provided, the
                   query is resolved immediately via did.Query.
            param1: First parameter for the operation.
            param2: Second parameter for the operation.
        """
        if operation is not None:
            # MATLAB-style: delegate to did.Query for validation and storage
            super().__init__(
                field,
                op=operation,
                param1=param1 if param1 is not None else "",
                param2=param2 if param2 is not None else "",
            )
            self._pending_field = field
            self._resolved = True
        else:
            # Pythonic: store field for later operator chaining
            super().__init__()  # search_structure = []
            self._pending_field = field
            self._resolved = False

        self._composite = False
        self._composite_op = None
        self._queries = []

    # ------------------------------------------------------------------
    # Computed properties (read from search_structure)
    # ------------------------------------------------------------------

    @property
    def field(self) -> str:
        """The field being queried."""
        if self._composite:
            return ""
        if self.search_structure and isinstance(self.search_structure, list):
            ss = self.search_structure[0]
            if isinstance(ss, dict):
                return ss.get("field", self._pending_field)
        return self._pending_field

    @property
    def operator(self) -> str | None:
        """The Python-style operator (mapped from DID operation)."""
        if self._composite:
            return self._composite_op
        if not self._resolved:
            return None
        if self.search_structure and isinstance(self.search_structure, list):
            ss = self.search_structure[0]
            if isinstance(ss, dict):
                did_op = ss.get("operation", "")
                return self._DID_TO_OP.get(did_op, did_op)
        return None

    @property
    def value(self) -> Any:
        """The query value (param1, or (param1, param2) for depends_on)."""
        if self._composite or not self._resolved:
            return None
        if self.search_structure and isinstance(self.search_structure, list):
            ss = self.search_structure[0]
            if isinstance(ss, dict):
                did_op = ss.get("operation", "")
                if did_op == "depends_on":
                    return (ss.get("param1", ""), ss.get("param2", ""))
                return ss.get("param1", "")
        return None

    @property
    def queries(self) -> list["Query"]:
        """Get the list of sub-queries for composite queries."""
        return self._queries

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve(self, py_op: str, value: Any) -> "Query":
        """Set the query condition by building a DID search_structure entry."""
        if self._resolved:
            raise ValueError("This query has already been resolved")

        did_op = self._OP_TO_DID.get(py_op, py_op)

        # Use exact_number for numeric == comparisons
        if py_op == "==" and isinstance(value, (int, float)):
            did_op = "exact_number"

        # Handle depends_on tuple value
        if py_op == "depends_on" and isinstance(value, tuple):
            p1 = value[0]
            p2 = value[1] if len(value) > 1 else ""
        else:
            p1 = value
            p2 = ""

        self.search_structure = [
            {
                "field": self._pending_field,
                "operation": did_op,
                "param1": p1,
                "param2": p2,
            }
        ]
        self._resolved = True
        return self

    # ------------------------------------------------------------------
    # Pythonic operators
    # ------------------------------------------------------------------

    def __eq__(self, other: Any) -> "Query":
        """Equality comparison."""
        if isinstance(other, Query):
            return NotImplemented
        return self._resolve("==", other)

    def __ne__(self, other: Any) -> "Query":
        """Inequality comparison."""
        return self._resolve("!=", other)

    def __lt__(self, other: Any) -> "Query":
        """Less than comparison."""
        return self._resolve("<", other)

    def __le__(self, other: Any) -> "Query":
        """Less than or equal comparison."""
        return self._resolve("<=", other)

    def __gt__(self, other: Any) -> "Query":
        """Greater than comparison."""
        return self._resolve(">", other)

    def __ge__(self, other: Any) -> "Query":
        """Greater than or equal comparison."""
        return self._resolve(">=", other)

    def __and__(self, other: "Query") -> "Query":
        """Combine queries with AND (list concatenation of search_structures)."""
        if not isinstance(other, Query):
            return NotImplemented
        q = Query()
        q.search_structure = self.search_structure + other.search_structure
        q._resolved = True
        q._composite = True
        q._composite_op = "and"
        q._queries = [self, other]
        return q

    def __or__(self, other: "Query") -> "Query":
        """Combine queries with OR (nested 'or' operation)."""
        if not isinstance(other, Query):
            return NotImplemented
        q = Query()
        q.search_structure = [
            {
                "field": "",
                "operation": "or",
                "param1": self.search_structure,
                "param2": other.search_structure,
            }
        ]
        q._resolved = True
        q._composite = True
        q._composite_op = "or"
        q._queries = [self, other]
        return q

    def __invert__(self) -> "Query":
        """Negate a query."""
        if not self._resolved:
            raise ValueError("Cannot negate an unresolved query")
        q = Query()
        q._pending_field = self._pending_field
        q._resolved = True
        q._composite = self._composite
        q._composite_op = self._composite_op
        q._queries = self._queries
        # Copy search_structure with negated operations
        q.search_structure = []
        for ss in self.search_structure:
            new_ss = dict(ss)
            op = new_ss.get("operation", "")
            if op.startswith("~"):
                new_ss["operation"] = op[1:]  # double negation cancels
            else:
                new_ss["operation"] = "~" + op
            q.search_structure.append(new_ss)
        return q

    # ------------------------------------------------------------------
    # String methods
    # ------------------------------------------------------------------

    def contains(self, value: str) -> "Query":
        """Check if field contains substring.

        Args:
            value: The substring to search for.

        Returns:
            Resolved Query object.
        """
        return self._resolve("contains", value)

    def match(self, pattern: str) -> "Query":
        """Match field against regex pattern.

        Args:
            pattern: Regular expression pattern.

        Returns:
            Resolved Query object.
        """
        return self._resolve("match", pattern)

    def equals(self, value: Any) -> "Query":
        """Exact equality check.

        Args:
            value: The value to compare.

        Returns:
            Resolved Query object.
        """
        return self._resolve("==", value)

    # ------------------------------------------------------------------
    # Comparison methods (for explicit calls)
    # ------------------------------------------------------------------

    def less_than(self, value: Any) -> "Query":
        """Check if field is less than value."""
        return self._resolve("<", value)

    def less_than_or_equal_to(self, value: Any) -> "Query":
        """Check if field is less than or equal to value."""
        return self._resolve("<=", value)

    def greater_than(self, value: Any) -> "Query":
        """Check if field is greater than value."""
        return self._resolve(">", value)

    def greater_than_or_equal_to(self, value: Any) -> "Query":
        """Check if field is greater than or equal to value."""
        return self._resolve(">=", value)

    # ------------------------------------------------------------------
    # Field existence
    # ------------------------------------------------------------------

    def has_field(self) -> "Query":
        """Check if the field exists in the document.

        Returns:
            Resolved Query object.
        """
        return self._resolve("hasfield", True)

    def has_member(self, value: Any) -> "Query":
        """Check if field (array) contains a specific member.

        Args:
            value: The value to look for in the array.

        Returns:
            Resolved Query object.
        """
        return self._resolve("hasmember", value)

    # ------------------------------------------------------------------
    # NDI-specific queries
    # ------------------------------------------------------------------

    def isa(self, document_class: str) -> "Query":
        """Check if document is of a specific class or inherits from it.

        Args:
            document_class: The document class name to check against.

        Returns:
            Resolved Query object.
        """
        return self._resolve("isa", document_class)

    def depends_on(self, name: str, value: str = "") -> "Query":
        """Check if document depends on another document.

        Args:
            name: The dependency name.
            value: The dependency value (document ID).

        Returns:
            Resolved Query object.
        """
        return self._resolve("depends_on", (name, value))

    # ------------------------------------------------------------------
    # Static factory methods
    # ------------------------------------------------------------------

    @staticmethod
    def all() -> "Query":
        """Return a query that matches all documents.

        Returns:
            Query that matches any document with class 'base' or its subclasses.
        """
        q = Query("")
        return q.isa("base")

    @staticmethod
    def none() -> "Query":
        """Return a query that matches no documents."""
        q = Query("")
        return q.isa("_impossible_class_name_that_will_never_exist_")

    @classmethod
    def from_search(cls, field: str, operation: str, param1: Any = "", param2: Any = "") -> "Query":
        """Create a query using MATLAB-style parameters.

        This provides compatibility with MATLAB ndi.query construction.
        Delegates to did.Query for operation validation.

        Args:
            field: The field to search (e.g., 'base.name'). Empty for 'isa'.
            operation: The DID operation type. Supported operations:
                - 'exact_string': Field equals param1 exactly
                - 'exact_string_anycase': Case-insensitive exact match
                - 'contains_string': Field contains param1 as substring
                - 'regexp': Field matches regex pattern in param1
                - 'exact_number': Field equals numeric param1
                - 'lessthan': Field < param1
                - 'lessthaneq': Field <= param1
                - 'greaterthan': Field > param1
                - 'greaterthaneq': Field >= param1
                - 'hasfield': Field exists (param1 ignored)
                - 'hasmember': Field array contains param1
                - 'isa': Document is or inherits from class param1
                - 'depends_on': Document depends on doc with ID param1
                - Prefix with '~' to negate (e.g., '~exact_string')
            param1: First parameter (meaning depends on operation).
            param2: Second parameter (used by some operations).

        Returns:
            Resolved Query object.

        Example:
            q = Query.from_search('base.name', 'exact_string', 'my_document')
            q = Query.from_search('', 'isa', 'element')
        """
        # Translate Python-style aliases to DID ops
        _ALIAS = {"==": "exact_string", "notequal": "~exact_string"}
        if operation in _ALIAS:
            operation = _ALIAS[operation]
        return cls(field, operation=operation, param1=param1, param2=param2)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    @property
    def query(self) -> tuple:
        """Get the query as a tuple (field, operator, value)."""
        return (self.field, self.operator, self.value)

    def to_searchstructure(self) -> dict:
        """Convert query to a search structure dict with Python-style operators.

        Returns:
            Dictionary with keys 'field', 'operation', 'param1', 'param2',
            or for composite queries: 'operation' and 'search' list.

        Example:
            q = Query('base.name') == 'test'
            ss = q.to_searchstructure()
            # {'field': 'base.name', 'operation': '==', 'param1': 'test', 'param2': ''}
        """
        if self._composite:
            return {
                "operation": self._composite_op,
                "search": [q.to_searchstructure() for q in self._queries],
            }

        if not self.search_structure:
            return {}

        ss = self.search_structure[0]
        if not isinstance(ss, dict):
            return {}

        did_op = ss.get("operation", "")
        py_op = self._DID_TO_OP.get(did_op, did_op)

        return {
            "field": ss.get("field", ""),
            "operation": py_op,
            "param1": ss.get("param1", ""),
            "param2": ss.get("param2", ""),
        }

    def to_search_structure(self) -> dict | list[dict]:
        """Convert to DID-python compatible search structure.

        Returns ``search_structure`` (inherited from did.Query), unwrapping
        single-element lists for consistency with DID conventions:

        - Simple query -> dict
        - AND query -> list of dicts
        - OR query -> dict with 'or' operation
        """
        ss = self.search_structure
        if isinstance(ss, list) and len(ss) == 1:
            return ss[0]
        return ss

    # ------------------------------------------------------------------
    # Iteration / collection
    # ------------------------------------------------------------------

    def __iter__(self):
        """Iterate over sub-queries for composite queries."""
        return iter(self._queries)

    def __len__(self) -> int:
        """Return number of sub-queries for composite queries."""
        return len(self._queries)

    def __bool__(self) -> bool:
        """Query is truthy if it has been resolved."""
        return self._resolved

    def __repr__(self) -> str:
        if self._composite:
            return f"Query({self._composite_op}: {self._queries})"
        if self._resolved:
            return f"Query('{self.field}' {self.operator} {self.value!r})"
        return f"Query('{self.field}')"
