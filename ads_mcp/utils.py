#!/usr/bin/env python

# Copyright 2026 Google LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Common utilities used by the MCP server."""

from typing import Any, Dict, List
import proto
import logging
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from google.ads.googleads.v24.services.services.google_ads_service import (
    GoogleAdsServiceClient,
)

from google.ads.googleads.util import get_nested_attr
import google.auth
from fastmcp.exceptions import ToolError
from ads_mcp.mcp_header_interceptor import MCPHeaderInterceptor
import os
import importlib.resources

# filename for generated field information used by search
_GAQL_FILENAME = "gaql_resources.txt"

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# OAuth scopes used by this server.
_ADS_SCOPE = "https://www.googleapis.com/auth/adwords"
_GSC_SCOPE = "https://www.googleapis.com/auth/webmasters"


def _create_credentials() -> google.auth.credentials.Credentials:
    """Returns Application Default Credentials with the Google Ads scope, or the FastMCP token if found."""
    from fastmcp.server.dependencies import get_access_token
    from google.oauth2.credentials import Credentials

    token_obj = get_access_token()
    if token_obj and token_obj.token:
        # Create credentials using the access token provided by FastMCP
        return Credentials(token=token_obj.token)

    credentials, _ = google.auth.default(scopes=[_ADS_SCOPE, _GSC_SCOPE])
    return credentials


def _get_developer_token() -> str:
    """Returns the developer token from the environment variable GOOGLE_ADS_DEVELOPER_TOKEN."""
    dev_token = os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN")
    if dev_token is None:
        raise ValueError(
            "GOOGLE_ADS_DEVELOPER_TOKEN environment variable not set."
        )
    return dev_token


def _get_login_customer_id() -> str | None:
    """Returns login customer id, if set, from the environment variable GOOGLE_ADS_LOGIN_CUSTOMER_ID."""
    return os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID")


def _get_googleads_client() -> GoogleAdsClient:
    args = {
        "credentials": _create_credentials(),
        "developer_token": _get_developer_token(),
        "use_proto_plus": True,
    }

    # If the login-customer-id is not set, avoid setting None.
    login_customer_id = _get_login_customer_id()

    if login_customer_id:
        args["login_customer_id"] = login_customer_id

    client = GoogleAdsClient(**args)

    return client


def get_googleads_service(serviceName: str) -> GoogleAdsServiceClient:
    return _get_googleads_client().get_service(
        serviceName, interceptors=[MCPHeaderInterceptor()]
    )


def get_googleads_type(typeName: str):
    return _get_googleads_client().get_type(typeName)


def get_googleads_client():
    return _get_googleads_client()


def get_gsc_service():
    """Returns an authenticated Google Search Console API client."""
    from googleapiclient.discovery import build

    return build("searchconsole", "v1", credentials=_create_credentials())


def get_ga4_data_client():
    """Returns an authenticated GA4 Data API client."""
    from google.analytics.data_v1beta import BetaAnalyticsDataClient

    return BetaAnalyticsDataClient(credentials=_create_credentials())


def get_ga4_admin_client():
    """Returns an authenticated GA4 Admin API client."""
    from google.analytics.admin_v1beta import AnalyticsAdminServiceClient

    return AnalyticsAdminServiceClient(credentials=_create_credentials())


def format_output_value(value: Any) -> Any:
    if isinstance(value, proto.Enum):
        return value.name
    elif isinstance(value, proto.Message):
        return proto.Message.to_dict(value)
    elif hasattr(value, "__iter__") and not isinstance(value, (str, bytes)):
        return [format_output_value(v) for v in value]
    else:
        return value


def format_output_row(row: proto.Message, attributes):
    return {
        attr: format_output_value(get_nested_attr(row, attr))
        for attr in attributes
    }


def get_gaql_resources_filepath():
    package_root = importlib.resources.files("ads_mcp")
    file_path = package_root.joinpath(_GAQL_FILENAME)
    return file_path


def raise_google_ads_error(ex: GoogleAdsException):
    """Converts a GoogleAdsException into a ToolError the host LLM can read."""
    error_msgs = []
    for error in ex.failure.errors:
        message = f"Google Ads API Error: {error.message}"
        field_path = ".".join(
            element.field_name for element in error.location.field_path_elements
        )
        if field_path:
            message += f" (at {field_path})"
        error_msgs.append(message)
    raise ToolError(f"Request ID: {ex.request_id}\n" + "\n".join(error_msgs))


def partial_failure_errors(client, response) -> List[Dict[str, Any]]:
    """Decodes per-row errors from a partial-failure enabled response.

    When partial_failure is set, the API applies the valid rows and reports
    the rejected ones in `partial_failure_error` instead of raising. Each
    returned dict carries the index of the offending row so the caller can
    tell which input was rejected.
    """
    status = getattr(response, "partial_failure_error", None)
    if status is None or not getattr(status, "code", 0):
        return []

    details = getattr(status, "details", None) or []
    if not details:
        return [{"index": None, "message": getattr(status, "message", "")}]

    failure_cls = type(client.get_type("GoogleAdsFailure"))
    errors = []
    for detail in details:
        try:
            failure = failure_cls.deserialize(detail.value)
        except Exception:  # pragma: no cover - defensive
            errors.append({"index": None, "message": str(detail)})
            continue
        for error in failure.errors:
            index = None
            for element in error.location.field_path_elements:
                if "index" in element:
                    index = element.index
                    break
            errors.append({"index": index, "message": error.message})
    return errors


VALIDATED_NO_CHANGES = (
    "VALIDATE_ONLY: the request is valid. Nothing was written, so there is no "
    "resource name yet."
)


def first_resource_name(response, validate_only: bool) -> str:
    """Returns the single resource name a mutate produced.

    A validate-only request writes nothing and comes back with no results, so
    return a message saying exactly that rather than failing on an empty list.
    """
    if response.results:
        return response.results[0].resource_name
    if validate_only:
        return VALIDATED_NO_CHANGES
    raise ToolError("The API reported success but returned no resource name.")


def _mask_paths(message, prefix: str) -> List[str]:
    """Collects the mask path of every explicitly set field in `message`."""
    paths = []
    # ListFields yields only fields that are set, using presence where the
    # field has it. That matters because a field assigned its default value
    # (False, 0) is still an intentional change and must appear in the mask.
    for descriptor, value in message.ListFields():
        path = f"{prefix}{descriptor.name}"
        if descriptor.is_repeated:
            paths.append(path)
        elif descriptor.type == descriptor.TYPE_MESSAGE:
            nested = _mask_paths(value, f"{path}.")
            # An empty submessage has no leaves to name, so name the
            # submessage itself; this is how a bidding strategy with no
            # target gets applied.
            paths.extend(nested or [path])
        else:
            paths.append(path)
    return paths


def derive_update_mask(resource) -> List[str]:
    """Returns the field mask paths for every field set on `resource`.

    Google Ads update operations only touch fields named in the update mask,
    so the mask has to mirror exactly what the caller populated. `resource_name`
    identifies the row rather than updating it and is therefore excluded.

    Note that a field left unset cannot be distinguished from one never
    mentioned, so clearing a field requires an explicitly supplied mask.
    """
    paths = _mask_paths(type(resource).pb(resource), "")
    return [path for path in paths if path != "resource_name"]


def enum_value(client, enum_name: str, value: str):
    """Resolves a string like 'PAUSED' to its Google Ads enum member.

    Raises a ToolError listing the accepted names when the value is unknown,
    which is far more actionable for an LLM than an AttributeError.
    """
    enum_type = getattr(client.enums, enum_name)
    try:
        return getattr(enum_type, value)
    except AttributeError:
        valid = sorted(
            name
            for name in dir(enum_type)
            if name.isupper() and name not in ("UNKNOWN", "UNSPECIFIED")
        )
        raise ToolError(
            f"Invalid value '{value}' for {enum_name}. "
            f"Valid values: {', '.join(valid)}"
        )
