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

"""Tools for importing offline conversions and correcting the ones already in."""

from typing import Any, Dict, List

from ads_mcp.coordinator import mcp
import ads_mcp.utils as utils
from google.ads.googleads.errors import GoogleAdsException
from fastmcp.exceptions import ToolError

# Click identifiers; exactly one identifies the click that led to the sale.
_CLICK_IDS = ("gclid", "gbraid", "wbraid")


def _conversion_action_resource_name(customer_id: str, value: Any) -> str:
    """Accepts either a full resource name or a bare conversion action id."""
    text = str(value).strip()
    if not text:
        raise ToolError("'conversion_action' must not be empty.")
    if text.startswith("customers/"):
        return text
    if not text.isdigit():
        raise ToolError(
            f"'conversion_action' must be a resource name like "
            f"'customers/{customer_id}/conversionActions/123' or a numeric "
            f"id, got '{text}'."
        )
    return f"customers/{customer_id}/conversionActions/{text}"


def _require(row: Dict[str, Any], index: int, field: str, label: str) -> Any:
    value = row.get(field)
    if value in (None, ""):
        raise ToolError(f"{label}[{index}] is missing required '{field}'.")
    return value


def _upload(
    client,
    service_name: str,
    request_type: str,
    method: str,
    payload_field: str,
    customer_id: str,
    rows: List[Any],
    validate_only: bool,
) -> Dict[str, Any]:
    """Sends an upload request and reports per-row outcomes."""
    service = utils.get_googleads_service(service_name)
    request = client.get_type(request_type)
    request.customer_id = customer_id
    getattr(request, payload_field).extend(rows)
    # Required by the upload services: valid rows are applied and rejected
    # ones come back in partial_failure_error rather than failing the batch.
    request.partial_failure = True
    request.validate_only = validate_only

    try:
        response = getattr(service, method)(request=request)
    except GoogleAdsException as ex:
        utils.raise_google_ads_error(ex)

    errors = utils.partial_failure_errors(client, response)
    return {
        "validate_only": validate_only,
        "submitted": len(rows),
        "accepted": len(rows) - len(errors),
        "errors": errors,
    }


@mcp.tool()
def upload_offline_conversions(
    customer_id: str,
    conversions: List[Dict[str, Any]],
    validate_only: bool = False,
) -> Dict[str, Any]:
    """Imports offline conversions with their real values into Google Ads.

    This closes the attribution loop: send the click identifier captured on
    the landing page back with the value the lead actually turned out to be
    worth, so Smart Bidding optimizes toward revenue instead of raw form fills.
    It is also the fix for conversions that currently report a value of zero.

    The conversion action must be of type UPLOAD_CLICKS (create one with
    create_conversion_action) and the click must be no older than the action's
    click-through lookback window.

    Each conversion is an object with:
        conversion_action (required): Resource name or numeric id of the
            conversion action to credit.
        gclid / gbraid / wbraid (exactly one required): Click identifier
            captured at landing time. gclid is the usual one; gbraid and
            wbraid appear on iOS app and web traffic respectively.
        conversion_date_time (required): When the conversion happened, as
            'yyyy-MM-dd HH:mm:ss+HH:mm'. The timezone offset is mandatory
            and the value must be at or after the click time.
        conversion_value: Value of the conversion, in the currency below.
        currency_code: ISO 4217 code, e.g. 'UAH' or 'USD'. Required whenever
            conversion_value is set.
        order_id: Your transaction id. Recommended, since it is what later
            lets you adjust or retract this exact conversion.
        custom_variables: Optional list of
            {'conversion_custom_variable': resource name, 'value': string}.

    Example:
        [{"conversion_action": "customers/123/conversionActions/456",
          "gclid": "Cj0KCQ...", "conversion_date_time":
          "2026-08-13 14:05:00+03:00", "conversion_value": 12500,
          "currency_code": "UAH", "order_id": "SO-10432"}]

    Uploads are cumulative, so re-sending the same order_id and action creates
    a duplicate rather than replacing the first. To correct a value you already
    sent, use upload_conversion_adjustments.

    Args:
        customer_id: Customer ID without hyphens (e.g. '5132067848').
        conversions: List of conversion objects as described above.
        validate_only: When True, validate without importing anything.

    Returns:
        Dict with 'submitted', 'accepted' and 'errors' (per-row messages with
        the index of each rejected conversion).
    """
    if not conversions:
        raise ToolError("'conversions' must contain at least one conversion.")

    client = utils.get_googleads_client()
    rows = []
    for index, row in enumerate(conversions):
        if not isinstance(row, dict):
            raise ToolError(f"conversions[{index}] must be an object.")

        click_ids = [key for key in _CLICK_IDS if row.get(key)]
        if len(click_ids) != 1:
            raise ToolError(
                f"conversions[{index}] must set exactly one of 'gclid', "
                f"'gbraid' or 'wbraid', got {click_ids or 'none'}."
            )
        if row.get("conversion_value") is not None and not row.get(
            "currency_code"
        ):
            raise ToolError(
                f"conversions[{index}] sets 'conversion_value' but no "
                "'currency_code'."
            )

        conversion = client.get_type("ClickConversion")
        setattr(conversion, click_ids[0], row[click_ids[0]])
        conversion.conversion_action = _conversion_action_resource_name(
            customer_id,
            _require(row, index, "conversion_action", "conversions"),
        )
        conversion.conversion_date_time = _require(
            row, index, "conversion_date_time", "conversions"
        )
        if row.get("conversion_value") is not None:
            conversion.conversion_value = float(row["conversion_value"])
        if row.get("currency_code"):
            conversion.currency_code = row["currency_code"]
        if row.get("order_id"):
            conversion.order_id = str(row["order_id"])
        for variable in row.get("custom_variables") or []:
            custom_variable = client.get_type("CustomVariable")
            custom_variable.conversion_custom_variable = variable[
                "conversion_custom_variable"
            ]
            custom_variable.value = str(variable["value"])
            conversion.custom_variables.append(custom_variable)

        rows.append(conversion)

    return _upload(
        client,
        "ConversionUploadService",
        "UploadClickConversionsRequest",
        "upload_click_conversions",
        "conversions",
        customer_id,
        rows,
        validate_only,
    )


@mcp.tool()
def upload_conversion_adjustments(
    customer_id: str,
    adjustments: List[Dict[str, Any]],
    validate_only: bool = False,
) -> Dict[str, Any]:
    """Retracts or restates conversions already recorded in Google Ads.

    Use RETRACTION to cancel a conversion that should never have counted, such
    as a fraudulent or spam lead. Retracting stops Smart Bidding from learning
    on that signal, which the Google Ads UI offers no equivalent way to do.
    Use RESTATEMENT to correct a value after the fact, e.g. once a deal closes
    at a different amount.

    Each adjustment is an object with:
        conversion_action (required): Resource name or numeric id of the
            action whose conversion is being adjusted.
        adjustment_type (required): 'RETRACTION', 'RESTATEMENT' or
            'ENHANCEMENT'.
        Identify the original conversion by either order_id (preferred, if you
        sent one) or the gclid plus conversion_date_time pair:
            order_id: Transaction id used on the original conversion.
            gclid + conversion_date_time: Click id and the original
                conversion time, 'yyyy-MM-dd HH:mm:ss+HH:mm'.
        adjustment_date_time (required): When the adjustment happened, same
            format with a timezone offset. Must be after the conversion.
        adjusted_value + currency_code: New total value. Required for
            RESTATEMENT and rejected for RETRACTION.

    Example, cancelling two fraudulent leads:
        [{"conversion_action": "customers/123/conversionActions/456",
          "adjustment_type": "RETRACTION", "gclid": "Cj0KCQ...",
          "conversion_date_time": "2026-08-01 09:12:00+03:00",
          "adjustment_date_time": "2026-08-13 10:00:00+03:00"}]

    Adjustments are permanent and a retracted conversion cannot be restored;
    it would have to be re-uploaded. Retractions apply within 55 days of the
    original conversion. Run with validate_only=True first.

    Args:
        customer_id: Customer ID without hyphens.
        adjustments: List of adjustment objects as described above.
        validate_only: When True, validate without applying.

    Returns:
        Dict with 'submitted', 'accepted' and 'errors' (per-row messages with
        the index of each rejected adjustment).
    """
    if not adjustments:
        raise ToolError("'adjustments' must contain at least one adjustment.")

    client = utils.get_googleads_client()
    rows = []
    for index, row in enumerate(adjustments):
        if not isinstance(row, dict):
            raise ToolError(f"adjustments[{index}] must be an object.")

        adjustment_type = str(
            _require(row, index, "adjustment_type", "adjustments")
        ).upper()
        has_order_id = bool(row.get("order_id"))
        has_pair = bool(row.get("gclid")) and bool(
            row.get("conversion_date_time")
        )
        if has_order_id == has_pair:
            raise ToolError(
                f"adjustments[{index}] must identify the conversion by either "
                "'order_id' or both 'gclid' and 'conversion_date_time', "
                "not neither and not both."
            )
        if (
            adjustment_type == "RESTATEMENT"
            and row.get("adjusted_value") is None
        ):
            raise ToolError(
                f"adjustments[{index}] is a RESTATEMENT and must set "
                "'adjusted_value'."
            )
        if (
            adjustment_type == "RETRACTION"
            and row.get("adjusted_value") is not None
        ):
            raise ToolError(
                f"adjustments[{index}] is a RETRACTION, which cancels the "
                "conversion outright and must not set 'adjusted_value'. Use "
                "RESTATEMENT to change a value."
            )

        adjustment = client.get_type("ConversionAdjustment")
        adjustment.conversion_action = _conversion_action_resource_name(
            customer_id,
            _require(row, index, "conversion_action", "adjustments"),
        )
        adjustment.adjustment_type = utils.enum_value(
            client, "ConversionAdjustmentTypeEnum", adjustment_type
        )
        adjustment.adjustment_date_time = _require(
            row, index, "adjustment_date_time", "adjustments"
        )
        if has_order_id:
            adjustment.order_id = str(row["order_id"])
        else:
            adjustment.gclid_date_time_pair.gclid = row["gclid"]
            adjustment.gclid_date_time_pair.conversion_date_time = row[
                "conversion_date_time"
            ]
        if row.get("adjusted_value") is not None:
            adjustment.restatement_value.adjusted_value = float(
                row["adjusted_value"]
            )
            if row.get("currency_code"):
                adjustment.restatement_value.currency_code = row[
                    "currency_code"
                ]

        rows.append(adjustment)

    return _upload(
        client,
        "ConversionAdjustmentUploadService",
        "UploadConversionAdjustmentsRequest",
        "upload_conversion_adjustments",
        "conversion_adjustments",
        customer_id,
        rows,
        validate_only,
    )


@mcp.tool()
def create_conversion_action(
    customer_id: str,
    name: str,
    category: str = "DEFAULT",
    action_type: str = "UPLOAD_CLICKS",
    status: str = "ENABLED",
    primary_for_goal: bool = True,
    counting_type: str = "ONE_PER_CLICK",
    default_value: float = None,
    default_currency_code: str = None,
    always_use_default_value: bool = False,
    click_through_lookback_window_days: int = None,
    validate_only: bool = False,
) -> str:
    """Creates a conversion action, e.g. a target for offline imports.

    To import conversions from a CRM, create an action with the default
    action_type 'UPLOAD_CLICKS' and pass its resource name to
    upload_offline_conversions.

    Args:
        customer_id: Customer ID without hyphens.
        name: Name of the conversion action, unique within the account.
        category: What the conversion represents, e.g. 'DEFAULT', 'PURCHASE',
            'CONVERTED_LEAD', 'QUALIFIED_LEAD', 'CONTACT'. An invalid name
            returns the list of valid values.
        action_type: 'UPLOAD_CLICKS' (default) for offline click imports, or
            'UPLOAD_CALLS' for call imports. Web tag types cannot be created
            through this tool.
        status: 'ENABLED' (default) or 'HIDDEN'.
        primary_for_goal: When True the action counts toward campaign bidding.
            Set False for an action you want to observe without bidding on it.
        counting_type: 'ONE_PER_CLICK' (default, for leads) or
            'MANY_PER_CLICK' (for repeated purchases).
        default_value: Value applied when an upload omits one.
        default_currency_code: ISO 4217 code for the default value,
            e.g. 'UAH'.
        always_use_default_value: When True, the default value overrides
            values sent with each conversion.
        click_through_lookback_window_days: How long after a click a
            conversion may still be credited, 1-90 days. Uploads outside this
            window are rejected, so raise it for long sales cycles.
        validate_only: When True, validate without creating.

    Returns:
        Resource name of the created conversion action,
        e.g. 'customers/123/conversionActions/456'.
    """
    client = utils.get_googleads_client()
    operation = client.get_type("ConversionActionOperation")
    action = operation.create
    action.name = name
    action.category = utils.enum_value(
        client, "ConversionActionCategoryEnum", category
    )
    action.type_ = utils.enum_value(
        client, "ConversionActionTypeEnum", action_type
    )
    action.status = utils.enum_value(
        client, "ConversionActionStatusEnum", status
    )
    action.primary_for_goal = primary_for_goal
    action.counting_type = utils.enum_value(
        client, "ConversionActionCountingTypeEnum", counting_type
    )
    if default_value is not None:
        action.value_settings.default_value = default_value
    if default_currency_code:
        action.value_settings.default_currency_code = default_currency_code
    if always_use_default_value:
        action.value_settings.always_use_default_value = True
    if click_through_lookback_window_days is not None:
        action.click_through_lookback_window_days = (
            click_through_lookback_window_days
        )

    service = utils.get_googleads_service("ConversionActionService")
    request = client.get_type("MutateConversionActionsRequest")
    request.customer_id = customer_id
    request.operations.append(operation)
    request.validate_only = validate_only

    try:
        response = service.mutate_conversion_actions(request=request)
    except GoogleAdsException as ex:
        utils.raise_google_ads_error(ex)

    return utils.first_resource_name(response, validate_only)


@mcp.tool()
def update_conversion_action(
    customer_id: str,
    conversion_action_resource_name: str,
    name: str = None,
    status: str = None,
    category: str = None,
    primary_for_goal: bool = None,
    counting_type: str = None,
    default_value: float = None,
    default_currency_code: str = None,
    always_use_default_value: bool = None,
    click_through_lookback_window_days: int = None,
    validate_only: bool = False,
) -> str:
    """Updates settings on an existing conversion action.

    Only the arguments you pass are changed; everything else is left alone.
    Common uses are adjusting a default value, taking an action out of bidding
    with primary_for_goal=False, or widening the lookback window so older
    offline conversions are still accepted.

    Args:
        customer_id: Customer ID without hyphens.
        conversion_action_resource_name: Action to update,
            e.g. 'customers/123/conversionActions/456'.
        name: New name.
        status: 'ENABLED', 'HIDDEN' or 'REMOVED'.
        category: New category, e.g. 'PURCHASE' or 'CONVERTED_LEAD'.
        primary_for_goal: Whether the action counts toward campaign bidding.
        counting_type: 'ONE_PER_CLICK' or 'MANY_PER_CLICK'.
        default_value: New default value.
        default_currency_code: New ISO 4217 currency code.
        always_use_default_value: Whether the default value overrides
            uploaded values.
        click_through_lookback_window_days: New window, 1-90 days.
        validate_only: When True, validate without applying.

    Returns:
        Resource name of the updated conversion action.
    """
    client = utils.get_googleads_client()
    operation = client.get_type("ConversionActionOperation")
    action = operation.update
    action.resource_name = conversion_action_resource_name

    if name is not None:
        action.name = name
    if status is not None:
        action.status = utils.enum_value(
            client, "ConversionActionStatusEnum", status
        )
    if category is not None:
        action.category = utils.enum_value(
            client, "ConversionActionCategoryEnum", category
        )
    if primary_for_goal is not None:
        action.primary_for_goal = primary_for_goal
    if counting_type is not None:
        action.counting_type = utils.enum_value(
            client, "ConversionActionCountingTypeEnum", counting_type
        )
    if default_value is not None:
        action.value_settings.default_value = default_value
    if default_currency_code is not None:
        action.value_settings.default_currency_code = default_currency_code
    if always_use_default_value is not None:
        action.value_settings.always_use_default_value = (
            always_use_default_value
        )
    if click_through_lookback_window_days is not None:
        action.click_through_lookback_window_days = (
            click_through_lookback_window_days
        )

    paths = utils.derive_update_mask(action)
    if not paths:
        raise ToolError(
            "No fields to update: pass at least one field to change."
        )
    operation.update_mask.paths.extend(paths)

    service = utils.get_googleads_service("ConversionActionService")
    request = client.get_type("MutateConversionActionsRequest")
    request.customer_id = customer_id
    request.operations.append(operation)
    request.validate_only = validate_only

    try:
        response = service.mutate_conversion_actions(request=request)
    except GoogleAdsException as ex:
        utils.raise_google_ads_error(ex)

    return utils.first_resource_name(response, validate_only)
