"""Tests for validate_async_response."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from tastytrade.common.exceptions import (
    AsyncBadRequestError,
    AsyncServerError,
    AsyncUnauthorizedError,
    AsyncUnknownError,
)
from tastytrade.utils.validators import validate_async_response


def _make_response(status: int, text: str = "error body") -> MagicMock:
    """Create a mock aiohttp.ClientResponse with given status and text."""
    response = MagicMock()
    response.status = status
    response.text = AsyncMock(return_value=text)
    return response


@pytest.mark.asyncio
async def test_200_returns_true() -> None:
    response = _make_response(200)
    assert await validate_async_response(response) is True


@pytest.mark.asyncio
async def test_204_returns_true() -> None:
    response = _make_response(204)
    assert await validate_async_response(response) is True


@pytest.mark.asyncio
async def test_201_returns_true() -> None:
    response = _make_response(201)
    assert await validate_async_response(response) is True


@pytest.mark.asyncio
async def test_400_raises_bad_request() -> None:
    response = _make_response(400, "Bad request details")
    with pytest.raises(AsyncBadRequestError) as exc_info:
        await validate_async_response(response)
    assert exc_info.value._error_message == "Bad request details"


@pytest.mark.asyncio
async def test_401_raises_unauthorized() -> None:
    response = _make_response(401, "Invalid credentials")
    with pytest.raises(AsyncUnauthorizedError) as exc_info:
        await validate_async_response(response)
    assert exc_info.value._error_message == "Invalid credentials"


@pytest.mark.asyncio
async def test_403_raises_unauthorized() -> None:
    response = _make_response(403, "Forbidden")
    with pytest.raises(AsyncUnauthorizedError) as exc_info:
        await validate_async_response(response)
    assert exc_info.value._error_message == "Forbidden"


@pytest.mark.asyncio
async def test_404_raises_bad_request() -> None:
    response = _make_response(404, "Not found")
    with pytest.raises(AsyncBadRequestError) as exc_info:
        await validate_async_response(response)
    assert exc_info.value._error_message == "Not found"


@pytest.mark.asyncio
async def test_500_raises_server_error() -> None:
    response = _make_response(500, "Internal server error")
    with pytest.raises(AsyncServerError) as exc_info:
        await validate_async_response(response)
    assert exc_info.value._error_message == "Internal server error"


@pytest.mark.asyncio
async def test_502_raises_server_error() -> None:
    response = _make_response(502, "Bad gateway")
    with pytest.raises(AsyncServerError):
        await validate_async_response(response)


@pytest.mark.asyncio
async def test_429_raises_server_error() -> None:
    response = _make_response(429, "Rate limited")
    with pytest.raises(AsyncServerError) as exc_info:
        await validate_async_response(response)
    assert exc_info.value._error_message == "Rate limited"


@pytest.mark.asyncio
async def test_unknown_status_raises_unknown_error() -> None:
    response = _make_response(418, "I'm a teapot")
    with pytest.raises(AsyncUnknownError) as exc_info:
        await validate_async_response(response)
    assert exc_info.value._error_message == "I'm a teapot"


@pytest.mark.asyncio
async def test_error_message_attached_to_exception_str() -> None:
    response = _make_response(400, "Detailed error from API")
    with pytest.raises(AsyncBadRequestError) as exc_info:
        await validate_async_response(response)
    # Verify __str__ includes the error message
    assert "Detailed error from API" in str(exc_info.value)
