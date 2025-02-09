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


class MessageProcessingError(Exception):
    """Custom exception for errors during message processing."""

    def __init__(self, message: str, original_exception: Optional[Exception] = None):
        super().__init__(message)
        self.original_exception = original_exception


__all__ = [
    "TastytradeSdkError",
    "InvalidArgumentError",
    "UnauthorizedError",
    "BadRequestError",
    "ServerError",
    "ResponseParsingError",
    "UnknownError",
    "AsyncTastytradeSdkError",
    "AsyncUnauthorizedError",
    "AsyncBadRequestError",
    "AsyncServerError",
    "AsyncResponseParsingError",
    "AsyncUnknownError",
]
