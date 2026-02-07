"""
ndi.query - search an ndi.database for ndi.documents

Query objects define searches for ndi.documents; they are passed to the
ndi.database.search() function.

This module provides both Pythonic query construction (via operators) and
MATLAB-compatible construction (via operation strings).

Pythonic examples:
    q = Query('element.name') == 'electrode1'
    q = (Query('element.type') == 'probe') & (Query('element.name').contains('elec'))

MATLAB-compatible examples:
    q = Query.from_search('ndi_document_property.id', 'exact_string', '12345678')
    q = Query.from_search('ndi_document_property.name', 'regexp', '(.*)')
    q = Query.from_search('', 'isa', 'ndi.document.base')
"""

from typing import Any, List, Optional, Tuple, Union


class Query:
    """NDI query class for searching documents.

    The query can be constructed in two ways:

    1. Pythonic (recommended):
        q = Query('field') == 'value'
        q = Query('field').contains('substring')
        q = Query.isa('document_class')

    2. MATLAB-compatible:
        q = Query.from_search('field', 'exact_string', 'value')
        q = Query.from_search('', 'isa', 'document_class')

    Attributes:
        field (str): The field to query.
        operator (str): The comparison operator.
        value (Any): The value to compare against.
    """

    # Map Python operators to MATLAB-style for internal use
    _OP_TO_MATLAB = {
        '==': 'exact_string',
        '!=': 'notequal',
        '>': 'greaterthan',
        '>=': 'greaterthaneq',
        '<': 'lessthan',
        '<=': 'lessthaneq',
        'contains': 'contains_string',
        'match': 'regexp',
    }

    # Map MATLAB operators to Python-style for public interface
    _MATLAB_TO_OP = {
        'exact_string': '==',
        'exact_number': '==',
        'notequal': '!=',
        'greaterthan': '>',
        'greaterthaneq': '>=',
        'lessthan': '<',
        'lessthaneq': '<=',
        'contains_string': 'contains',
        'regexp': 'match',
    }

    def __init__(self, field: str = ''):
        """Create a new query for the specified field.

        Args:
            field: The document field to query (e.g., 'base.name',
                   'element.type'). Can be empty string for 'isa' queries.
        """
        self.field = field
        self.operator = None
        self.value = None
        self._resolved = False
        self._composite = False
        self._composite_op = None
        self._queries = []

    def _resolve(self, operator: str, value: Any) -> 'Query':
        """Internal method to set the query condition."""
        if self._resolved:
            raise ValueError('This query has already been resolved')
        self.operator = operator
        self.value = value
        self._resolved = True
        return self

    @property
    def queries(self) -> List['Query']:
        """Get the list of sub-queries for composite queries."""
        return self._queries

    # === Pythonic operators ===

    def __eq__(self, other: Any) -> 'Query':
        """Equality comparison."""
        if isinstance(other, Query):
            # This is comparing two Query objects, not a query condition
            return NotImplemented
        return self._resolve('==', other)

    def __ne__(self, other: Any) -> 'Query':
        """Inequality comparison."""
        return self._resolve('!=', other)

    def __lt__(self, other: Any) -> 'Query':
        """Less than comparison."""
        return self._resolve('<', other)

    def __le__(self, other: Any) -> 'Query':
        """Less than or equal comparison."""
        return self._resolve('<=', other)

    def __gt__(self, other: Any) -> 'Query':
        """Greater than comparison."""
        return self._resolve('>', other)

    def __ge__(self, other: Any) -> 'Query':
        """Greater than or equal comparison."""
        return self._resolve('>=', other)

    def __and__(self, other: 'Query') -> 'Query':
        """Combine queries with AND."""
        if not isinstance(other, Query):
            return NotImplemented
        q = Query()
        q._composite = True
        q._composite_op = 'and'
        q._queries = [self, other]
        q._resolved = True
        return q

    def __or__(self, other: 'Query') -> 'Query':
        """Combine queries with OR."""
        if not isinstance(other, Query):
            return NotImplemented
        q = Query()
        q._composite = True
        q._composite_op = 'or'
        q._queries = [self, other]
        q._resolved = True
        return q

    def __invert__(self) -> 'Query':
        """Negate a query."""
        if not self._resolved:
            raise ValueError('Cannot negate an unresolved query')
        q = Query(self.field)
        q.operator = '~' + self.operator
        q.value = self.value
        q._resolved = True
        q._composite = self._composite
        q._composite_op = self._composite_op
        q._queries = self._queries
        return q

    # === String methods ===

    def contains(self, value: str) -> 'Query':
        """Check if field contains substring.

        Args:
            value: The substring to search for.

        Returns:
            Resolved Query object.
        """
        return self._resolve('contains', value)

    def match(self, pattern: str) -> 'Query':
        """Match field against regex pattern.

        Args:
            pattern: Regular expression pattern.

        Returns:
            Resolved Query object.
        """
        return self._resolve('match', pattern)

    def equals(self, value: Any) -> 'Query':
        """Exact equality check.

        Args:
            value: The value to compare.

        Returns:
            Resolved Query object.
        """
        return self._resolve('==', value)

    # === Comparison methods (for explicit calls) ===

    def less_than(self, value: Any) -> 'Query':
        """Check if field is less than value."""
        return self._resolve('<', value)

    def less_than_or_equal_to(self, value: Any) -> 'Query':
        """Check if field is less than or equal to value."""
        return self._resolve('<=', value)

    def greater_than(self, value: Any) -> 'Query':
        """Check if field is greater than value."""
        return self._resolve('>', value)

    def greater_than_or_equal_to(self, value: Any) -> 'Query':
        """Check if field is greater than or equal to value."""
        return self._resolve('>=', value)

    # === Field existence ===

    def has_field(self) -> 'Query':
        """Check if the field exists in the document.

        Returns:
            Resolved Query object.
        """
        return self._resolve('hasfield', True)

    def has_member(self, value: Any) -> 'Query':
        """Check if field (array) contains a specific member.

        Args:
            value: The value to look for in the array.

        Returns:
            Resolved Query object.
        """
        return self._resolve('hasmember', value)

    # === NDI-specific queries ===

    def isa(self, document_class: str) -> 'Query':
        """Check if document is of a specific class or inherits from it.

        Instance method version.

        Args:
            document_class: The document class name to check against.

        Returns:
            Resolved Query object.
        """
        return self._resolve('isa', document_class)

    def depends_on(self, name: str, value: str = '') -> 'Query':
        """Check if document depends on another document.

        Instance method version.

        Args:
            name: The dependency name.
            value: The dependency value (document ID).

        Returns:
            Resolved Query object.
        """
        return self._resolve('depends_on', (name, value))

    # === Static factory methods ===

    @staticmethod
    def all() -> 'Query':
        """Return a query that matches all documents.

        Returns:
            Query that matches any document with class 'base' or its subclasses.
        """
        q = Query('')
        return q.isa('base')

    @staticmethod
    def none() -> 'Query':
        """Return a query that matches no documents."""
        q = Query('')
        return q.isa('_impossible_class_name_that_will_never_exist_')

    @classmethod
    def from_search(
        cls,
        field: str,
        operation: str,
        param1: Any = '',
        param2: Any = ''
    ) -> 'Query':
        """Create a query using MATLAB-style parameters.

        This provides compatibility with MATLAB ndi.query construction.

        Args:
            field: The field to search (e.g., 'base.name'). Empty for 'isa'.
            operation: The operation type. Supported operations:
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
        negated = operation.startswith('~')
        if negated:
            operation = operation[1:]

        q = cls(field)

        if operation == 'exact_string':
            q = q.equals(param1)
        elif operation == 'exact_string_anycase':
            q._resolve('exact_string_anycase', param1)
        elif operation == 'contains_string':
            q = q.contains(param1)
        elif operation == 'regexp':
            q = q.match(param1)
        elif operation == 'exact_number':
            q = q.equals(param1)
        elif operation == 'lessthan':
            q = q.less_than(param1)
        elif operation == 'lessthaneq':
            q = q.less_than_or_equal_to(param1)
        elif operation == 'greaterthan':
            q = q.greater_than(param1)
        elif operation == 'greaterthaneq':
            q = q.greater_than_or_equal_to(param1)
        elif operation == 'hasfield':
            q = q.has_field()
        elif operation == 'hasmember':
            q = q.has_member(param1)
        elif operation == 'isa':
            q = q.isa(param1)
        elif operation == 'depends_on':
            q = q.depends_on(param1, param2)
        elif operation == '==':
            q = q.equals(param1)
        elif operation == 'notequal':
            q._resolve('!=', param1)
        else:
            raise ValueError(f"Unknown operation: {operation}")

        if negated:
            q.operator = '~' + q.operator

        return q

    @property
    def query(self) -> tuple:
        """Get the query as a tuple (field, operator, value)."""
        return (self.field, self.operator, self.value)

    def to_searchstructure(self) -> dict:
        """Convert query to a search structure dictionary.

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
                'operation': self._composite_op,
                'search': [q.to_searchstructure() for q in self._queries]
            }

        # Keep Python-style operators in public interface
        op = self.operator

        # Handle depends_on tuple value
        if self.operator == 'depends_on' and isinstance(self.value, tuple):
            return {
                'field': self.field,
                'operation': op,
                'param1': self.value[0],
                'param2': self.value[1] if len(self.value) > 1 else ''
            }

        return {
            'field': self.field,
            'operation': op,
            'param1': self.value,
            'param2': ''
        }

    def to_search_structure(self) -> Union[dict, List[dict]]:
        """Convert query to DID-python compatible search structure.

        This method converts Python-style operators to MATLAB/DID-style
        operators for compatibility with DID-python's field_search() function.

        Returns:
            Dictionary or list of dictionaries compatible with DID-python.
        """
        return self._convert_to_did_format(self.to_searchstructure())

    def _convert_to_did_format(self, ss: dict) -> Union[dict, List[dict]]:
        """Convert a search structure to DID-python format.

        Args:
            ss: Search structure dictionary.

        Returns:
            DID-python compatible search structure.
        """
        # Handle composite queries (and/or)
        op = ss.get('operation', '')

        if op == 'and':
            # DID-python expects a list for AND operations
            return [self._convert_to_did_format(s) for s in ss.get('search', [])]
        elif op == 'or':
            # DID-python expects 'or' operation with param1/param2
            sub_queries = ss.get('search', [])
            if len(sub_queries) >= 2:
                return {
                    'field': '',
                    'operation': 'or',
                    'param1': self._convert_to_did_format(sub_queries[0]),
                    'param2': self._convert_to_did_format(sub_queries[1])
                }
            return ss

        # Map Python operators to MATLAB/DID operators
        op_map = {
            '==': 'exact_string',
            '!=': '~exact_string',
            '<': 'lessthan',
            '<=': 'lessthaneq',
            '>': 'greaterthan',
            '>=': 'greaterthaneq',
            'contains': 'contains_string',
            'match': 'regexp',
            'hasfield': 'hasfield',
            'hasmember': 'hasmember',
            'isa': 'isa',
            'depends_on': 'depends_on',
            'exact_string_anycase': 'exact_string_anycase',
        }

        # Handle negated operators
        negated = False
        check_op = op
        if op and op.startswith('~'):
            negated = True
            check_op = op[1:]

        # Convert operator
        did_op = op_map.get(check_op, check_op)
        if negated and not did_op.startswith('~'):
            did_op = '~' + did_op

        return {
            'field': ss.get('field', ''),
            'operation': did_op,
            'param1': ss.get('param1', ss.get('value', '')),
            'param2': ss.get('param2', '')
        }

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
