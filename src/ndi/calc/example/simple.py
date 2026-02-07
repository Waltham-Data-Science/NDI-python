"""
ndi.calc.example.simple - Simple demonstration calculator.

A minimal calculator that demonstrates the ndi.Calculator pattern.
It takes an 'answer' input parameter and stores it in a simple_calc
document.

MATLAB equivalent: src/ndi/+ndi/+calc/+example/simple.m
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...calculator import Calculator

if TYPE_CHECKING:
    from ...document import Document
    from ...session.session_base import Session


class SimpleCalc(Calculator):
    """
    Simple demonstration calculator.

    Creates a 'simple_calc' document where the output answer
    equals the input answer parameter. Used primarily for testing
    and as a template for new calculators.

    Example:
        >>> calc = SimpleCalc(session)
        >>> docs = calc.run(DocExistsAction.REPLACE)
    """

    def __init__(self, session: Session | None = None):
        super().__init__(
            session=session,
            document_type="simple_calc",
            path_to_doc_type="apps/calculators/simple_calc",
        )

    def calculate(self, parameters: dict) -> list[Document]:
        """
        Perform the simple calculation.

        Creates a simple_calc document where the answer field
        equals the input_parameters.answer value.

        Args:
            parameters: Dict with 'input_parameters' and 'depends_on'

        Returns:
            List containing one simple_calc Document
        """
        from ...document import Document

        input_params = parameters.get("input_parameters", {})

        # Build the simple_calc content
        simple_calc_data = {
            "input_parameters": input_params,
            "answer": input_params.get("answer", 0),
        }

        # Create document using full schema path
        doc = Document(
            "apps/calculators/simple_calc",
            **{"simple_calc": simple_calc_data},
        )

        # Set session ID
        if self._session is not None:
            doc = doc.set_session_id(self._session.id())

        # Add dependency if specified
        depends_on = parameters.get("depends_on", [])
        if depends_on:
            dep = depends_on[0]
            doc = doc.set_dependency_value(
                dep.get("name", "document_id"),
                dep.get("value", ""),
            )

        return [doc]

    def default_search_for_input_parameters(self) -> dict:
        """
        Return default search parameters.

        By default, searches for any 'base' document and uses
        answer=5 as the input parameter.

        Returns:
            Parameter specification dict
        """
        from ...query import Query

        return {
            "input_parameters": {"answer": 5},
            "depends_on": [],
            "query": [
                {
                    "name": "document_id",
                    "query": Query("").isa("base"),
                },
            ],
        }

    def __repr__(self) -> str:
        return f"SimpleCalc(session={self._session is not None})"
