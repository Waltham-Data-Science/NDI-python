"""A failed cloud call says what the server said.

MATLAB counterpart: ``+ndi/+cloud/+internal/formatApiError.m``

``CloudAPIError`` has always carried the server's body on
``.response_body``, but its MESSAGE was ``"API error (HTTP 400)"`` -- so
anything that printed or logged the exception, which is most things,
reported a code and dropped the explanation. The server's 400 for a
missing MATLAB BYOL license says ``MATLAB_LICENSE_REQUIRED`` and names the
release; the user saw ``400``.

MATLAB wrote its version of this after #624, where the error FORMATTER
crashed: it assumed a struct body with a ``message`` field, so a response
carrying a string body, no body, or a differently shaped error replaced
the real failure with an indexing error about the formatter. Every branch
here is therefore tolerant, and the tests below are mostly about the
shapes that are not the expected one -- a formatter that can itself fail
hides the thing it was called to report.
"""

from __future__ import annotations

import types

import pytest

from ndi.cloud.internal import formatApiError


def response(status=400, reason="Bad Request", body=None, text=""):
    """Something shaped like a ``requests.Response``."""

    def json():
        if body is None:
            raise ValueError("no json")
        return body

    return types.SimpleNamespace(status_code=status, reason=reason, json=json, text=text)


class TestTheNormalCase:
    def test_status_and_message_together(self):
        assert (
            formatApiError(response(body={"message": "dataset not found"}))
            == "HTTP 400 Bad Request - dataset not found"
        )

    def test_error_is_read_when_there_is_no_message(self):
        assert (
            formatApiError(response(body={"error": "bad key"})) == "HTTP 400 Bad Request - bad key"
        )

    def test_message_wins_over_error(self):
        formatted = formatApiError(response(body={"message": "first", "error": "second"}))
        assert formatted == "HTTP 400 Bad Request - first"

    def test_a_string_body_is_the_message(self):
        assert formatApiError(response(body=None, text="upstream timeout")).endswith(
            "- upstream timeout"
        )


class TestTheShapesThatBrokeMatlab:
    """#624: the formatter itself must not be the thing that fails."""

    def test_none(self):
        assert formatApiError(None) == "no response from server"

    def test_a_response_with_no_usable_body(self):
        assert formatApiError(response(body=None, text="")) == "HTTP 400 Bad Request"

    def test_a_body_that_is_not_a_mapping(self):
        assert formatApiError(response(body=[1, 2, 3])) == "HTTP 400 Bad Request"

    def test_a_body_whose_message_is_empty(self):
        assert formatApiError(response(body={"message": ""})) == "HTTP 400 Bad Request"

    def test_an_object_with_neither_status_nor_body(self):
        assert formatApiError(types.SimpleNamespace()) == "unknown error"

    def test_a_bare_parsed_body(self):
        """The caller may only have the decoded payload."""
        assert formatApiError({"message": "no license"}) == "no license"

    def test_a_bare_string(self):
        assert formatApiError("something went wrong") == "something went wrong"

    def test_it_never_returns_an_empty_string(self):
        for value in (None, "", {}, [], 0, types.SimpleNamespace(), response(body={})):
            assert formatApiError(value).strip()


class TestTheAPIResponseShape:
    """``APIResponse`` keeps the parsed body on ``.data``, not behind
    ``.json()`` -- so the reader has to know both."""

    def test_it_reads_data(self):
        from ndi.cloud.client import APIResponse

        wrapped = APIResponse(
            {"message": "conflict"},
            success=False,
            status_code=409,
            reason="Conflict",
        )
        assert formatApiError(wrapped) == "HTTP 409 Conflict - conflict"


class TestTheClientUsesIt:
    """The point of the helper: it is on the path that raises."""

    def test_the_raised_message_carries_the_servers_words(self):
        from ndi.cloud.client import CloudClient
        from ndi.cloud.config import CloudConfig
        from ndi.cloud.exceptions import CloudAPIError

        client = CloudClient.__new__(CloudClient)
        client.config = CloudConfig()

        failing = response(
            status=400,
            reason="Bad Request",
            body={"code": "MATLAB_LICENSE_REQUIRED", "message": "no license for R2024b"},
        )

        with pytest.raises(CloudAPIError) as caught:
            client._handle_response(failing)

        assert "no license for R2024b" in str(caught.value)
        assert caught.value.status_code == 400
        assert caught.value.response_body["code"] == "MATLAB_LICENSE_REQUIRED"

    def test_401_and_404_keep_their_own_exception_types(self):
        """Formatting the message must not flatten the hierarchy: callers
        branch on CloudAuthError and CloudNotFoundError."""
        from ndi.cloud.client import CloudClient
        from ndi.cloud.config import CloudConfig
        from ndi.cloud.exceptions import CloudAuthError, CloudNotFoundError

        client = CloudClient.__new__(CloudClient)
        client.config = CloudConfig()

        with pytest.raises(CloudAuthError):
            client._handle_response(response(status=401, reason="Unauthorized", text="nope"))
        with pytest.raises(CloudNotFoundError):
            client._handle_response(response(status=404, reason="Not Found", text="nope"))


if __name__ == "__main__":
    pytest.main([__file__])
