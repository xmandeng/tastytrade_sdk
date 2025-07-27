import logging

import aiohttp
import requests
from requests import JSONDecodeError

from tastytrade.common.exceptions import (
    BadRequestError,
    ResponseParsingError,
    ServerError,
    UnauthorizedError,
    UnknownError,
)

logger = logging.getLogger(__name__)


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

    elif response.status_code in range(200, 300):
        try:
            response.json()
            return True
        except JSONDecodeError as e:
            logger.error("Failed to parse JSON response: %s", e)
            raise ResponseParsingError(response)

    # Handle known error status codes
    elif error_class := error_map.get(response.status_code):
        logger.error("API error: %s - %s", response.status_code, response.text)
        raise error_class(response)

    # Handle unknown error status codes
    logger.error("Unknown error: %s - %s", response.status_code, response.text)
    raise UnknownError(response)


def validate_async_response(response: aiohttp.ClientResponse) -> bool:
    """Validate the response from the API.

    Args:
        response: The aiohttp response object
    """
    if response.status not in range(200, 300):
        error_message = "Unknown error"
        if response.headers.get("content-type") == "application/json":
            raise Exception(
                f"Request failed with status {response.status}: {error_message}"
            )
    return True
