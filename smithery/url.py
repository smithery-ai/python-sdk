import json
import base64
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse


def create_smithery_url(base_url, config={}):
    """
    Create a Smithery URL with optional configuration parameters encoded in base64.

    Args:
        base_url (str): The base URL to use
        config (dict, optional): Configuration object to encode and add as a query parameter

    Returns:
        str: The complete URL with any configuration parameters added
    """
    # Parse the URL
    parsed_url = urlparse(base_url)

    # Convert config to JSON string and encode in base64
    config_json = json.dumps(config)
    config_base64 = base64.b64encode(config_json.encode("utf-8")).decode("utf-8")

    # Parse existing query parameters and add the config parameter
    query_params = parse_qs(parsed_url.query)
    query_params["config"] = [config_base64]

    # Rebuild the query string
    new_query = urlencode(query_params, doseq=True)

    # Rebuild the URL with the new query string
    url = urlunparse(
        (
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            parsed_url.params,
            new_query,
            parsed_url.fragment,
        )
    )
    return url
