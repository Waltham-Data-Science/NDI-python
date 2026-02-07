"""
ndi.calculator - Base class for NDI calculators.

A Calculator is an App that can discover input parameters,
check for existing results, and run computations that produce
Documents stored in the session database.

MATLAB equivalent: src/ndi/+ndi/calculator.m
"""

from __future__ import annotations

import itertools
import logging
from typing import TYPE_CHECKING

from .app import App
from .app.appdoc import AppDoc, DocExistsAction

if TYPE_CHECKING:
    from .document import Document
    from .session.session_base import Session

logger = logging.getLogger(__name__)


class Calculator(App, AppDoc):
    """
    Base class for NDI calculators.

    A Calculator discovers inputs from the database, checks for
    existing results, runs computations, and stores output documents.
    Subclasses override `calculate()` to implement specific analyses.

    The `run()` method implements the main pipeline:
    1. Discover input parameter sets via search_for_input_parameters()
    2. For each parameter set, check for existing calculator docs
    3. Handle existing docs per doc_exists_action
    4. Call calculate() for new computations
    5. Store results in the session database

    Example:
        >>> calc = MyCalculator(session)
        >>> docs = calc.run(DocExistsAction.REPLACE)
    """

    def __init__(
        self,
        session: Session | None = None,
        document_type: str = "",
        path_to_doc_type: str = "",
    ):
        """
        Create a new Calculator.

        Args:
            session: Session for database access
            document_type: NDI document type for calculator outputs
            path_to_doc_type: Path to the document type schema
        """
        # Initialize App (session + name from class)
        name = type(self).__name__
        App.__init__(self, session=session, name=name)

        # Initialize AppDoc
        doc_types = [document_type] if document_type else []
        doc_document_types = [path_to_doc_type or document_type] if document_type else []
        AppDoc.__init__(
            self,
            doc_types=doc_types,
            doc_document_types=doc_document_types,
            doc_session=session,
        )

    # =========================================================================
    # Core Pipeline
    # =========================================================================

    def run(
        self,
        doc_exists_action: DocExistsAction = DocExistsAction.ERROR,
        parameters: dict | None = None,
    ) -> list[Document]:
        """
        Run the calculator pipeline.

        Discovers inputs, checks for existing results, and computes
        new results as needed.

        Args:
            doc_exists_action: How to handle existing calculator docs
            parameters: Search parameters, or None for defaults

        Returns:
            List of all result Documents (existing + newly computed)
        """
        if parameters is None:
            parameters = self.default_search_for_input_parameters()

        # Find all valid input parameter sets
        all_parameters = self.search_for_input_parameters(parameters)

        logger.debug(
            "Beginning calculator %s: %d parameter sets",
            type(self).__name__,
            len(all_parameters),
        )

        docs: list[Document] = []
        docs_to_add: list[Document] = []

        for i, params in enumerate(all_parameters):
            logger.debug("Processing parameter set %d of %d", i + 1, len(all_parameters))

            # Check for existing calculator documents
            existing = self.search_for_calculator_docs(params)

            do_calc = False

            if existing:
                if doc_exists_action == DocExistsAction.ERROR:
                    raise RuntimeError(
                        f"Calculator document already exists for parameter set {i + 1}"
                    )
                elif doc_exists_action == DocExistsAction.NO_ACTION:
                    docs.extend(existing)
                    continue
                elif doc_exists_action == DocExistsAction.REPLACE_IF_DIFFERENT:
                    # Check if inputs match
                    equivalent = False
                    for edoc in existing:
                        existing_params = self._extract_input_parameters(edoc)
                        if existing_params is not None:
                            if self.are_input_parameters_equivalent(
                                params.get("input_parameters", {}),
                                existing_params,
                            ):
                                equivalent = True
                                break

                    if equivalent:
                        docs.extend(existing)
                        continue
                    else:
                        # Different - remove existing and recalculate
                        self._remove_docs(existing)
                        do_calc = True
                elif doc_exists_action == DocExistsAction.REPLACE:
                    self._remove_docs(existing)
                    do_calc = True
            else:
                do_calc = True

            if do_calc:
                new_docs = self.calculate(params)
                if new_docs is None:
                    new_docs = []
                elif not isinstance(new_docs, list):
                    new_docs = [new_docs]

                docs.extend(new_docs)
                docs_to_add.extend(new_docs)

        # Add new documents to the database
        if docs_to_add and self._session is not None:
            # Create app document for tracking
            app_doc = self.newdocument()
            try:
                self._session.database_add(app_doc)
            except Exception:
                pass  # App doc may already exist

            for doc in docs_to_add:
                try:
                    self._session.database_add(doc)
                except Exception:
                    logger.warning("Failed to add calculator doc to database")

        logger.debug("Concluding calculator %s", type(self).__name__)
        return docs

    def calculate(self, parameters: dict) -> list[Document]:
        """
        Perform the calculation.

        Subclasses must override this method to implement their
        specific analysis logic.

        Args:
            parameters: Dict with 'input_parameters' and 'depends_on'

        Returns:
            List of result Documents
        """
        return []

    # =========================================================================
    # Input Discovery
    # =========================================================================

    def default_search_for_input_parameters(self) -> dict:
        """
        Return default parameters for input discovery.

        Subclasses override to specify what inputs to search for.

        Returns:
            Dict with 'input_parameters', 'depends_on', and optionally 'query'
        """
        return {
            "input_parameters": {},
            "depends_on": [],
        }

    def search_for_input_parameters(
        self,
        parameters_specification: dict,
    ) -> list[dict]:
        """
        Search the database for all valid input parameter sets.

        Uses the query specifications to find matching documents,
        then generates the cartesian product of all matches.

        Args:
            parameters_specification: Dict with:
                - input_parameters: Fixed parameters
                - depends_on: Fixed dependencies [{name, value}, ...]
                - query: Optional list of query specs [{name, query}, ...]

        Returns:
            List of parameter dicts, each with 'input_parameters' and 'depends_on'
        """
        fixed_inputs = parameters_specification.get("input_parameters", {})
        fixed_depends_on = parameters_specification.get("depends_on", [])
        queries = parameters_specification.get("query", None)

        # Normalize queries to list
        if queries is not None and not isinstance(queries, list):
            queries = [queries]

        # If no queries, return single parameter set with fixed values
        if not queries:
            return [
                {
                    "input_parameters": fixed_inputs,
                    "depends_on": fixed_depends_on if fixed_depends_on else [],
                }
            ]

        if self._session is None:
            return []

        # Search database for each query
        doc_lists = []
        for q_spec in queries:
            query_obj = q_spec.get("query")
            if query_obj is not None:
                results = self._session.database_search(query_obj)
                doc_lists.append(results)
            else:
                doc_lists.append([])

        # Filter out empty results
        non_empty = [dl for dl in doc_lists if dl]
        if not non_empty:
            return []

        # Generate cartesian product of all query results
        all_parameters = []
        for combo in itertools.product(*doc_lists):
            # Build depends_on entries for this combination
            extra_depends = []
            valid = True

            for idx, doc in enumerate(combo):
                q_spec = queries[idx]
                dep_name = q_spec.get("name", f"input_{idx + 1}")

                dep_entry = {
                    "name": dep_name,
                    "value": doc.id,
                }

                # Validate this dependency
                if not self.is_valid_dependency_input(dep_name, doc.id):
                    valid = False
                    break

                extra_depends.append(dep_entry)

            if not valid:
                continue

            # Combine fixed and query-derived dependencies
            all_depends = list(fixed_depends_on) + extra_depends

            all_parameters.append(
                {
                    "input_parameters": dict(fixed_inputs),
                    "depends_on": all_depends,
                }
            )

        return all_parameters

    def default_parameters_query(
        self,
        parameters_specification: dict,
    ) -> list[dict]:
        """
        Return default query structures for parameter search.

        Base class returns empty list. Subclasses can override.

        Args:
            parameters_specification: Current parameter spec

        Returns:
            List of query spec dicts [{name, query}, ...]
        """
        return []

    # =========================================================================
    # Output Discovery
    # =========================================================================

    def search_for_calculator_docs(
        self,
        parameters: dict,
    ) -> list[Document]:
        """
        Find existing calculator documents matching the given parameters.

        Searches for documents of the calculator's type that have
        matching dependencies and input parameters.

        Args:
            parameters: Dict with 'input_parameters' and 'depends_on'

        Returns:
            List of matching Documents
        """
        if self._session is None or not self.doc_types:
            return []

        from .query import Query

        # Build query for calculator class name (not schema path)
        doc_type = self.doc_types[0]
        q = Query("").isa(doc_type)

        # Add dependency constraints
        depends_on = parameters.get("depends_on", [])
        for dep in depends_on:
            dep_name = dep.get("name", "")
            dep_value = dep.get("value", "")
            if dep_value:
                q = q & Query("").depends_on(dep_name, dep_value)

        # Search database
        candidates = self._session.database_search(q)

        # Filter by input parameters
        input_params = parameters.get("input_parameters", {})
        if not input_params:
            return candidates

        matching = []
        for doc in candidates:
            existing_params = self._extract_input_parameters(doc)
            if existing_params is not None:
                if self.are_input_parameters_equivalent(input_params, existing_params):
                    matching.append(doc)

        return matching

    # =========================================================================
    # Validation and Comparison
    # =========================================================================

    def are_input_parameters_equivalent(
        self,
        params1: dict,
        params2: dict,
    ) -> bool:
        """
        Compare two input parameter sets for equivalence.

        Args:
            params1: First parameter set
            params2: Second parameter set

        Returns:
            True if equivalent
        """
        return params1 == params2

    def is_valid_dependency_input(
        self,
        name: str,
        value: str,
    ) -> bool:
        """
        Check if a dependency input is valid.

        Base class always returns True. Subclasses can override
        to filter out invalid input combinations.

        Args:
            name: Dependency name
            value: Document ID

        Returns:
            True if valid
        """
        return True

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    def _extract_input_parameters(self, doc: Document) -> dict | None:
        """Extract input_parameters from a calculator document."""
        props = doc.document_properties
        doc_type = self.doc_types[0] if self.doc_types else ""
        if doc_type:
            section = props.get(doc_type, {})
            return section.get("input_parameters")
        return None

    def _remove_docs(self, docs: list[Document]) -> None:
        """Remove documents from the database."""
        if self._session is None:
            return
        for doc in docs:
            try:
                self._session.database_rm(doc)
            except Exception:
                pass

    def __repr__(self) -> str:
        doc_type = self.doc_document_types[0] if self.doc_document_types else "none"
        return f"Calculator({self._name}, type={doc_type})"
