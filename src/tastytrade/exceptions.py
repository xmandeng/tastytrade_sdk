import logging
from abc import ABC
from typing import Optional

import aiohttp
import requests
from requests import JSONDecodeError

logger = logging.getLogger(__name__)


class TastytradeSdkError(Exception, ABC):
    """Base exception for Tastytrade SDK."""

    def __init__(self, message: str, response: Optional[requests.Response] = None):
        super().__init__(message)
        self.response = response

    def __str__(self) -> str:
        base_message = super().__str__()
        if self.response is not None:
            # Attempt to extract a more readable error message from the response
            try:
                error_info = self.response.json()
                error_message = error_info.get("error", {}).get(
                    "message", "No detailed error message available."
                )
            except JSONDecodeError:
                error_message = self.response.text  # Fallback to raw text if JSON parsing fails

            return f"{base_message} (Status: {self.response.status_code}, Message: {error_message})"
        return base_message


class InvalidArgumentError(TastytradeSdkError):
    """Raised when an invalid argument is provided."""

    def __init__(self, context: str):
        super().__init__(f"Invalid argument: {context}")


class UnauthorizedError(TastytradeSdkError):
    """Raised on 401 authentication errors."""

    def __init__(self, response: Optional[requests.Response] = None):
        super().__init__("UnauthorizedError - Please check your credentials", response)


class BadRequestError(TastytradeSdkError):
    """Raised on 400 bad request errors."""

    def __init__(self, response: Optional[requests.Response] = None):
        super().__init__("Bad request - Please check your input parameters", response)


class ServerError(TastytradeSdkError):
    """Raised on 5XX server errors."""

    def __init__(self, response: Optional[requests.Response] = None):
        super().__init__("Server error - Please try again later", response)


class ResponseParsingError(TastytradeSdkError):
    """Raised when response parsing fails."""

    def __init__(self, response: requests.Response):
        super().__init__("Failed to parse JSON response", response)


class UnknownError(TastytradeSdkError):
    """Raised for unexpected errors."""

    def __init__(self, response: Optional[requests.Response] = None):
        super().__init__("An unexpected error occurred", response)


def validate_response(response: requests.Response) -> bool:
    """
    Handle the error response from the Tastytrade API.

    Args:
        response: The response object from the API call

    Raises
        Various TastytradeSdkError subclasses based on the error condition
    """
    error_map = {
        400: BadRequestError,
        401: UnauthorizedError,
        403: UnauthorizedError,
        404: BadRequestError,
        429: ServerError,  # Rate limiting
        500: ServerError,
        502: ServerError,
        503: ServerError,
        504: ServerError,
    }

    # Handle successful responses
    if response.status_code == 204:
        return True

    elif 200 <= response.status_code < 300:

        try:
            response.json()
            return True
        except JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            raise ResponseParsingError(response)

    # Handle known error status codes
    elif error_class := error_map.get(response.status_code):
        logger.error(f"API error: {response.status_code} - {response.text}")
        raise error_class(response)

    # Handle unknown error status codes
    logger.error(f"Unknown error: {response.status_code} - {response.text}")
    raise UnknownError(response)


class AsyncTastytradeSdkError(Exception, ABC):
    """Base exception for Async Tastytrade SDK."""

    def __init__(self, message: str, response: Optional[aiohttp.ClientResponse] = None):
        super().__init__(message)
        self.response = response
        self._error_message: Optional[str] = None

    def __str__(self) -> str:
        base_message = super().__str__()
        if self.response is not None and self._error_message:
            return (
                f"{base_message} (Status: {self.response.status}, Message: {self._error_message})"
            )
        return base_message

    async def get_error_details(self) -> str:
        """Asynchronously get error details from response."""
        if self.response is not None:
            try:
                error_info = await self.response.json()
                self._error_message = error_info.get("error", {}).get(
                    "message", "No detailed error message available."
                )
            except aiohttp.ContentTypeError:
                self._error_message = await self.response.text()

            return f"(Status: {self.response.status}, Message: {self._error_message})"
        return ""


class AsyncUnauthorizedError(AsyncTastytradeSdkError):
    """Raised on 401 authentication errors in async context."""

    def __init__(self, response: Optional[aiohttp.ClientResponse] = None):
        super().__init__("UnauthorizedError - Please check your credentials", response)


class AsyncBadRequestError(AsyncTastytradeSdkError):
    """Raised on 400 bad request errors in async context."""

    def __init__(self, response: Optional[aiohttp.ClientResponse] = None):
        super().__init__("Bad request - Please check your input parameters", response)


class AsyncServerError(AsyncTastytradeSdkError):
    """Raised on 5XX server errors in async context."""

    def __init__(self, response: Optional[aiohttp.ClientResponse] = None):
        super().__init__("Server error - Please try again later", response)


class AsyncResponseParsingError(AsyncTastytradeSdkError):
    """Raised when async response parsing fails."""

    def __init__(self, response: aiohttp.ClientResponse):
        super().__init__("Failed to parse JSON response", response)


class AsyncUnknownError(AsyncTastytradeSdkError):
    """Raised for unexpected errors in async context."""

    def __init__(self, response: Optional[aiohttp.ClientResponse] = None):
        super().__init__("An unexpected error occurred", response)


async def validate_async_response(response: aiohttp.ClientResponse) -> bool:
    """
    Handle the error response from the Async Tastytrade API.

    Args:
        response: The aiohttp ClientResponse object from the API call

    Raises
        Various AsyncTastytradeSdkError subclasses based on the error condition
    """
    error_map = {
        400: AsyncBadRequestError,
        401: AsyncUnauthorizedError,
        403: AsyncUnauthorizedError,
        404: AsyncBadRequestError,
        429: AsyncServerError,  # Rate limiting
        500: AsyncServerError,
        502: AsyncServerError,
        503: AsyncServerError,
        504: AsyncServerError,
    }

    # Handle successful responses
    if response.status == 204:
        return True

    elif 200 <= response.status < 300:
        try:
            await response.json()
            return True
        except JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            raise AsyncResponseParsingError(response)

    # Handle known error status codes
    elif error_class := error_map.get(response.status):
        error_text = await response.text()
        logger.error(f"API error: {response.status} - {error_text}")
        raise error_class(response)

    # Handle unknown error status codes
    error_text = await response.text()
    logger.error(f"Unknown error: {response.status} - {error_text}")
    raise AsyncUnknownError(response)
