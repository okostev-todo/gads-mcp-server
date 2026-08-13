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

"""Universal write access to the Google Ads API via GoogleAdsService.Mutate."""

from typing import Any, Dict, List

from ads_mcp.coordinator import mcp
import ads_mcp.utils as utils
from google.ads.googleads.errors import GoogleAdsException
from fastmcp.exceptions import ToolError


def _build_operation(client, index: int, operation: Dict[str, Any]):
    """Converts one plain-dict operation into a MutateOperation proto."""
    if not isinstance(operation, dict):
        raise ToolError(
            f"operations[{index}] must be an object, got "
            f"{type(operation).__name__}."
        )
    if len(operation) != 1:
        raise ToolError(
            f"operations[{index}] must contain exactly one "
            f"'<resource>_operation' key, got {sorted(operation)}."
        )

    operation_type = type(client.get_type("MutateOperation"))
    try:
        built = operation_type(operation)
    except ValueError as ex:
        raise ToolError(f"operations[{index}] is invalid: {ex}")
    except KeyError as ex:
        raise ToolError(
            f"operations[{index}] uses an unknown enum value: {ex}. "
            "Enum values are passed as their string name, e.g. 'PAUSED'."
        )
    except TypeError as ex:
        raise ToolError(f"operations[{index}] has a malformed value: {ex}")

    _fill_update_mask(operation_type, built, index)
    return built


def _fill_update_mask(operation_type, built, index: int) -> None:
    """Derives update_mask for update operations that omitted it.

    Google Ads only applies fields listed in the mask, so an update without
    one silently changes nothing. Deriving it from the populated fields makes
    the tool behave the way a caller intuitively expects.
    """
    which_resource = operation_type.pb(built).WhichOneof("operation")
    if not which_resource:
        raise ToolError(
            f"operations[{index}] did not resolve to any known operation type."
        )

    sub_operation = getattr(built, which_resource)
    sub_type = type(sub_operation)
    action = sub_type.pb(sub_operation).WhichOneof("operation")
    if action != "update":
        return

    if not hasattr(sub_operation, "update_mask"):
        return
    if list(sub_operation.update_mask.paths):
        return

    paths = utils.derive_update_mask(sub_operation.update)
    if not paths:
        raise ToolError(
            f"operations[{index}] is an update that sets no fields besides "
            "resource_name, so it would do nothing."
        )
    sub_operation.update_mask.paths.extend(paths)


def _extract_results(response) -> List[Dict[str, str]]:
    """Pulls the resource name out of each per-operation response."""
    results = []
    for item in response.mutate_operation_responses:
        which = type(item).pb(item).WhichOneof("response")
        if not which:
            results.append({"type": None, "resource_name": None})
            continue
        results.append(
            {
                "type": which,
                "resource_name": getattr(
                    getattr(item, which), "resource_name", None
                ),
            }
        )
    return results


@mcp.tool()
def mutate_google_ads(
    customer_id: str,
    operations: List[Dict[str, Any]],
    validate_only: bool = False,
    partial_failure: bool = False,
) -> Dict[str, Any]:
    """Applies arbitrary write operations to any Google Ads resource.

    This is the general-purpose write tool: it wraps GoogleAdsService.Mutate,
    which accepts operations for any mutable resource type. Prefer it when no
    dedicated tool exists for what you need, or when several changes must be
    applied together.

    Always dry-run first with validate_only=True. The API then checks every
    operation and reports errors without writing anything, which is the safe
    way to confirm an operation is well formed before it takes effect.

    Each entry in `operations` is an object with exactly one
    '<resource>_operation' key, whose value holds one of 'create', 'update' or
    'remove'. For 'update' the update_mask is derived automatically from the
    fields you set, so you normally do not pass it. For 'remove' the value is
    the resource name string. Enum fields are given as their string name, and
    monetary amounts are in micros (1 unit = 1,000,000 micros).

    Examples:
        Exclude a placement for the whole account:
        [{"customer_negative_criterion_operation": {"create": {
            "placement": {"url": "badsite.example"}}}}]

        Add a campaign-level negative keyword:
        [{"campaign_criterion_operation": {"create": {
            "campaign": "customers/123/campaigns/456", "negative": true,
            "keyword": {"text": "free", "match_type": "PHRASE"}}}}]

        Pause an asset group and raise a campaign's tROAS in one call:
        [{"asset_group_operation": {"update": {
            "resource_name": "customers/123/assetGroups/789",
            "status": "PAUSED"}}},
         {"campaign_operation": {"update": {
            "resource_name": "customers/123/campaigns/456",
            "maximize_conversion_value": {"target_roas": 4.0}}}}]

        Remove a criterion:
        [{"campaign_criterion_operation": {
            "remove": "customers/123/campaignCriteria/456~789"}}]

    Use get_resource_metadata to look up the exact field names and enum values
    for a resource before building operations against it.

    Args:
        customer_id: Customer ID without hyphens (e.g. '5132067848').
        operations: List of operation objects as described above. Operations
            are applied in order, so a later one can reference an earlier
            result by temporary id (a negative integer in the resource name).
        validate_only: When True, validate everything and write nothing.
            Strongly recommended before any real write.
        partial_failure: When True, valid operations are applied and invalid
            ones are reported in 'errors' instead of failing the whole batch.
            Cannot be combined with validate_only.

    Returns:
        Dict with 'validate_only', 'applied' (count of resources written),
        'results' (resource name per operation) and 'errors' (per-row errors
        when partial_failure is used).
    """
    if not operations:
        raise ToolError("'operations' must contain at least one operation.")
    if validate_only and partial_failure:
        raise ToolError(
            "validate_only cannot be combined with partial_failure: a "
            "validate-only request writes nothing, and it already reports "
            "every operation's errors."
        )

    client = utils.get_googleads_client()
    service = utils.get_googleads_service("GoogleAdsService")

    built_operations = [
        _build_operation(client, index, operation)
        for index, operation in enumerate(operations)
    ]

    request = client.get_type("MutateGoogleAdsRequest")
    request.customer_id = customer_id
    request.mutate_operations.extend(built_operations)
    request.validate_only = validate_only
    request.partial_failure = partial_failure

    try:
        response = service.mutate(request=request)
    except GoogleAdsException as ex:
        utils.raise_google_ads_error(ex)

    errors = utils.partial_failure_errors(client, response)
    results = _extract_results(response)
    return {
        "validate_only": validate_only,
        "applied": 0 if validate_only else len(results) - len(errors),
        "results": results,
        "errors": errors,
    }
