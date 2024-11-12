import logging
from abc import ABC
from typing import Optional

import requests
from requests import JSONDecodeError

logger = logging.getLogger(__name__)

# TODO Fix the raised exception message


class TastytradeSdkException(Exception, ABC):
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


class InvalidArgument(TastytradeSdkException):
    """Raised when an invalid argument is provided."""

    def __init__(self, context: str):
        super().__init__(f"Invalid argument: {context}")


class Unauthorized(TastytradeSdkException):
    """Raised on 401 authentication errors."""

    def __init__(self, response: Optional[requests.Response] = None):
        super().__init__("Unauthorized - Please check your credentials", response)


class BadRequest(TastytradeSdkException):
    """Raised on 400 bad request errors."""

    def __init__(self, response: Optional[requests.Response] = None):
        super().__init__("Bad request - Please check your input parameters", response)


class ServerError(TastytradeSdkException):
    """Raised on 5XX server errors."""

    def __init__(self, response: Optional[requests.Response] = None):
        super().__init__("Server error - Please try again later", response)


class ResponseParsingError(TastytradeSdkException):
    """Raised when response parsing fails."""

    def __init__(self, response: requests.Response):
        super().__init__("Failed to parse JSON response", response)


class UnknownError(TastytradeSdkException):
    """Raised for unexpected errors."""

    def __init__(self, response: Optional[requests.Response] = None):
        super().__init__("An unexpected error occurred", response)


def validate_response(response: requests.Response) -> bool:
    """
    Handle the error response from the Tastytrade API.

    Args:
        response: The response object from the API call

    Raises:
        Various TastytradeSdkException subclasses based on the error condition
    """
    error_map = {
        400: BadRequest,
        401: Unauthorized,
        403: Unauthorized,
        404: BadRequest,
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
