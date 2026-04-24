"""HTTP response assertion helpers for test suite.

Provides common assertion functions for validating HTTP responses,
reducing boilerplate in test code and standardizing response validation.
"""

from typing import Any, Dict, List, Optional


def assert_created(response, expected_keys: Optional[List[str]] = None) -> Dict[str, Any]:
    """Assert 201 Created response and optional key presence.

    Args:
        response: FastAPI/Starlette TestResponse object
        expected_keys: Optional list of keys expected in response JSON

    Returns:
        The response JSON data for further assertions

    Raises:
        AssertionError: If status code != 201 or expected keys missing
    """
    assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
    data = response.json()

    if expected_keys:
        missing = set(expected_keys) - set(data.keys())
        assert not missing, f"Missing keys in response: {missing}"

    return data


def assert_ok(response, expected_keys: Optional[List[str]] = None) -> Dict[str, Any]:
    """Assert 200 OK response and optional key presence.

    Args:
        response: FastAPI/Starlette TestResponse object
        expected_keys: Optional list of keys expected in response JSON

    Returns:
        The response JSON data for further assertions

    Raises:
        AssertionError: If status code != 200 or expected keys missing
    """
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()

    if expected_keys:
        missing = set(expected_keys) - set(data.keys())
        assert not missing, f"Missing keys in response: {missing}"

    return data


def assert_paginated(response, expected_total: Optional[int] = None) -> Dict[str, Any]:
    """Assert 200 OK paginated response with items and metadata.

    Args:
        response: FastAPI/Starlette TestResponse object
        expected_total: Optional expected total count

    Returns:
        The response JSON data for further assertions

    Raises:
        AssertionError: If status code != 200 or pagination structure invalid
    """
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()

    # Check pagination structure
    assert "items" in data, "Missing 'items' key in paginated response"
    assert isinstance(data["items"], list), "'items' must be a list"

    if expected_total is not None:
        assert data.get("total") == expected_total, \
            f"Expected total={expected_total}, got {data.get('total')}"

    return data


def assert_bad_request(response, error_msg: Optional[str] = None) -> Dict[str, Any]:
    """Assert 400 Bad Request response.

    Args:
        response: FastAPI/Starlette TestResponse object
        error_msg: Optional expected error message substring

    Returns:
        The response JSON data for further assertions

    Raises:
        AssertionError: If status code != 400
    """
    assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"
    data = response.json()

    if error_msg:
        response_text = str(data)
        assert error_msg in response_text, \
            f"Expected error message '{error_msg}' in response: {response_text}"

    return data


def assert_unauthorized(response) -> Dict[str, Any]:
    """Assert 401 Unauthorized response.

    Args:
        response: FastAPI/Starlette TestResponse object

    Returns:
        The response JSON data for further assertions

    Raises:
        AssertionError: If status code != 401
    """
    assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"
    return response.json()


def assert_forbidden(response) -> Dict[str, Any]:
    """Assert 403 Forbidden response.

    Args:
        response: FastAPI/Starlette TestResponse object

    Returns:
        The response JSON data for further assertions

    Raises:
        AssertionError: If status code != 403
    """
    assert response.status_code == 403, f"Expected 403, got {response.status_code}: {response.text}"
    return response.json()


def assert_not_found(response) -> Dict[str, Any]:
    """Assert 404 Not Found response.

    Args:
        response: FastAPI/Starlette TestResponse object

    Returns:
        The response JSON data for further assertions

    Raises:
        AssertionError: If status code != 404
    """
    assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"
    return response.json()


def assert_conflict(response, error_msg: Optional[str] = None) -> Dict[str, Any]:
    """Assert 409 Conflict response.

    Args:
        response: FastAPI/Starlette TestResponse object
        error_msg: Optional expected error message substring

    Returns:
        The response JSON data for further assertions

    Raises:
        AssertionError: If status code != 409
    """
    assert response.status_code == 409, f"Expected 409, got {response.status_code}: {response.text}"
    data = response.json()

    if error_msg:
        response_text = str(data)
        assert error_msg in response_text, \
            f"Expected error message '{error_msg}' in response: {response_text}"

    return data


def assert_server_error(response) -> str:
    """Assert 500 Internal Server Error response.

    Args:
        response: FastAPI/Starlette TestResponse object

    Returns:
        The response text for error inspection

    Raises:
        AssertionError: If status code != 500
    """
    assert response.status_code == 500, f"Expected 500, got {response.status_code}: {response.text}"
    return response.text
