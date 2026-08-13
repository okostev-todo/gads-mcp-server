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

"""Shared helpers for the write-tool tests.

The write tools build real protobuf messages, and most of what can go wrong is
in that construction: a misspelled field, an enum that does not exist, an
update mask that does not match the fields actually set. So these tests use a
real GoogleAdsClient for `get_type` and `enums` and mock only the network call.
A MagicMock client would accept any field name and prove nothing.
"""

from unittest.mock import MagicMock

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException


def real_client() -> GoogleAdsClient:
    """Returns a client that builds real protos but cannot make API calls."""
    return GoogleAdsClient(
        credentials=object(), developer_token="test-token", use_proto_plus=True
    )


def mock_service(**results_by_method) -> MagicMock:
    """Builds a mock service whose mutate methods return given resource names.

    Example:
        mock_service(mutate_campaigns=["customers/1/campaigns/2"])
    """
    service = MagicMock()
    for method, resource_names in results_by_method.items():
        response = MagicMock()
        response.results = [
            MagicMock(resource_name=name) for name in resource_names
        ]
        response.partial_failure_error = None
        getattr(service, method).return_value = response
    return service


def google_ads_exception(message: str, request_id: str) -> GoogleAdsException:
    """Builds a GoogleAdsException carrying a single error message."""
    error = MagicMock()
    error.message = message
    error.location.field_path_elements = []
    failure = MagicMock()
    failure.errors = [error]
    exception = GoogleAdsException(
        MagicMock(), MagicMock(), MagicMock(), MagicMock()
    )
    exception.failure = failure
    exception.request_id = request_id
    return exception


def sent_request(service, method):
    """Returns the request proto passed to a mocked mutate/upload method."""
    return getattr(service, method).call_args.kwargs["request"]
