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

"""Tools for maintaining Performance Max asset groups, bidding and budgets."""

from typing import Any, Dict, List

from ads_mcp.coordinator import mcp
import ads_mcp.utils as utils
from google.ads.googleads.errors import GoogleAdsException
from fastmcp.exceptions import ToolError

# Bidding strategy name -> (campaign field, {tool argument: strategy field}).
_BIDDING_STRATEGIES = {
    "MAXIMIZE_CONVERSION_VALUE": (
        "maximize_conversion_value",
        {"target_roas": "target_roas"},
    ),
    "MAXIMIZE_CONVERSIONS": (
        "maximize_conversions",
        {"target_cpa_micros": "target_cpa_micros"},
    ),
    "TARGET_ROAS": ("target_roas", {"target_roas": "target_roas"}),
    "TARGET_CPA": ("target_cpa", {"target_cpa_micros": "target_cpa_micros"}),
    "TARGET_SPEND": ("target_spend", {}),
    "MANUAL_CPC": ("manual_cpc", {}),
}


def _mutate_one(
    client,
    service_name: str,
    request_type: str,
    method: str,
    customer_id: str,
    operation,
    validate_only: bool,
) -> str:
    """Applies a single operation and returns the affected resource name."""
    service = utils.get_googleads_service(service_name)
    request = client.get_type(request_type)
    request.customer_id = customer_id
    request.operations.append(operation)
    request.validate_only = validate_only

    try:
        response = getattr(service, method)(request=request)
    except GoogleAdsException as ex:
        utils.raise_google_ads_error(ex)

    return utils.first_resource_name(response, validate_only)


@mcp.tool()
def update_asset_group_status(
    customer_id: str,
    asset_group_resource_names: List[str],
    status: str,
    validate_only: bool = False,
) -> Dict[str, Any]:
    """Pauses, enables or removes Performance Max asset groups in bulk.

    Pausing unproductive asset groups concentrates a campaign's budget on the
    ones that convert, and is the usual way to clear out groups that never
    ramped up.

    This service does not support partial failure, so the whole batch is
    applied or nothing is. Run with validate_only=True first when the list was
    assembled from a report.

    Args:
        customer_id: Customer ID without hyphens (e.g. '5132067848').
        asset_group_resource_names: Asset groups to change, e.g.
            ['customers/123/assetGroups/456'].
        status: 'PAUSED', 'ENABLED' or 'REMOVED'. 'REMOVED' is irreversible;
            prefer 'PAUSED' unless the group must be gone for good.
        validate_only: When True, validate without applying.

    Returns:
        Dict with 'resource_names' of the affected asset groups and the
        'status' applied.
    """
    if not asset_group_resource_names:
        raise ToolError("'asset_group_resource_names' must not be empty.")

    client = utils.get_googleads_client()
    status_enum = utils.enum_value(client, "AssetGroupStatusEnum", status)

    operations = []
    for resource_name in asset_group_resource_names:
        operation = client.get_type("AssetGroupOperation")
        asset_group = operation.update
        asset_group.resource_name = resource_name
        asset_group.status = status_enum
        operation.update_mask.paths.append("status")
        operations.append(operation)

    service = utils.get_googleads_service("AssetGroupService")
    request = client.get_type("MutateAssetGroupsRequest")
    request.customer_id = customer_id
    request.operations.extend(operations)
    request.validate_only = validate_only

    try:
        response = service.mutate_asset_groups(request=request)
    except GoogleAdsException as ex:
        utils.raise_google_ads_error(ex)

    return {
        "resource_names": [result.resource_name for result in response.results],
        "status": status,
        "validate_only": validate_only,
    }


@mcp.tool()
def add_asset_group_signals(
    customer_id: str,
    asset_group_resource_name: str,
    search_themes: List[str] = None,
    audience_resource_names: List[str] = None,
    validate_only: bool = False,
) -> Dict[str, Any]:
    """Adds search themes and audience signals to a PMax asset group.

    Signals tell Performance Max where to start looking for converting users.
    They guide the campaign rather than constrain it: PMax can still serve
    outside a signal, so signals are not a substitute for exclusions.

    Signals cannot be edited, only added and removed. To replace one, add the
    new signal and pass the old one's resource name to remove_criteria.

    Args:
        customer_id: Customer ID without hyphens.
        asset_group_resource_name: Target asset group,
            e.g. 'customers/123/assetGroups/456'.
        search_themes: Free-text themes describing what customers search for,
            e.g. ['crm for small business', 'accounting software']. Each theme
            behaves like a broad hint, so keep them specific.
        audience_resource_names: Audience resource names to signal,
            e.g. ['customers/123/audiences/789']. Build audiences first;
            this tool only links existing ones.
        validate_only: When True, validate without applying.

    Returns:
        Dict with 'resource_names' of the created signals and 'errors'.
    """
    if not search_themes and not audience_resource_names:
        raise ToolError(
            "Provide at least one of 'search_themes' or "
            "'audience_resource_names'."
        )

    client = utils.get_googleads_client()
    operations = []
    for theme in search_themes or []:
        operation = client.get_type("AssetGroupSignalOperation")
        signal = operation.create
        signal.asset_group = asset_group_resource_name
        signal.search_theme.text = theme
        operations.append(operation)
    for audience in audience_resource_names or []:
        operation = client.get_type("AssetGroupSignalOperation")
        signal = operation.create
        signal.asset_group = asset_group_resource_name
        signal.audience.audience = audience
        operations.append(operation)

    service = utils.get_googleads_service("AssetGroupSignalService")
    request = client.get_type("MutateAssetGroupSignalsRequest")
    request.customer_id = customer_id
    request.operations.extend(operations)
    request.validate_only = validate_only
    if not validate_only:
        request.partial_failure = True

    try:
        response = service.mutate_asset_group_signals(request=request)
    except GoogleAdsException as ex:
        utils.raise_google_ads_error(ex)

    return {
        "resource_names": [result.resource_name for result in response.results],
        "errors": utils.partial_failure_errors(client, response),
    }


@mcp.tool()
def update_campaign_bidding(
    customer_id: str,
    campaign_resource_name: str,
    strategy: str,
    target_roas: float = None,
    target_cpa_micros: int = None,
    validate_only: bool = False,
) -> str:
    """Sets a campaign's bidding strategy and its target.

    Performance Max runs on MAXIMIZE_CONVERSION_VALUE (optionally with a
    tROAS) or MAXIMIZE_CONVERSIONS (optionally with a tCPA). Passing a target
    of 0 or omitting it lets the strategy bid without one.

    Changing the strategy or moving a target sharply resets the learning
    period, so adjust targets in steps rather than all at once.

    Args:
        customer_id: Customer ID without hyphens.
        campaign_resource_name: Campaign to update,
            e.g. 'customers/123/campaigns/456'.
        strategy: 'MAXIMIZE_CONVERSION_VALUE', 'MAXIMIZE_CONVERSIONS',
            'TARGET_ROAS', 'TARGET_CPA', 'TARGET_SPEND' or 'MANUAL_CPC'.
        target_roas: Target return on ad spend as a ratio, where 4.0 means
            400% — i.e. 4 units of conversion value per unit spent. Valid
            with MAXIMIZE_CONVERSION_VALUE and TARGET_ROAS.
        target_cpa_micros: Target cost per acquisition in micros
            (1 unit = 1,000,000 micros). Valid with MAXIMIZE_CONVERSIONS
            and TARGET_CPA.
        validate_only: When True, validate without applying.

    Returns:
        Resource name of the updated campaign.
    """
    strategy_name = strategy.upper()
    if strategy_name not in _BIDDING_STRATEGIES:
        raise ToolError(
            f"Unknown bidding strategy '{strategy}'. Valid values: "
            f"{', '.join(sorted(_BIDDING_STRATEGIES))}."
        )

    field_name, supported_targets = _BIDDING_STRATEGIES[strategy_name]
    provided = {
        "target_roas": target_roas,
        "target_cpa_micros": target_cpa_micros,
    }
    for argument, value in provided.items():
        if value is not None and argument not in supported_targets:
            raise ToolError(
                f"'{argument}' is not supported by strategy "
                f"{strategy_name}. It accepts: "
                f"{', '.join(supported_targets) or 'no target'}."
            )

    client = utils.get_googleads_client()
    operation = client.get_type("CampaignOperation")
    campaign = operation.update
    campaign.resource_name = campaign_resource_name
    # Assigning the submessage marks it present, which is what selects the
    # strategy. Merely reading the field would leave the campaign unchanged.
    setattr(campaign, field_name, {})
    strategy_message = getattr(campaign, field_name)

    for argument, strategy_field in supported_targets.items():
        value = provided[argument]
        if value is not None:
            setattr(strategy_message, strategy_field, value)

    # With no target the mask names the strategy field itself, which is what
    # switches the campaign over; with a target it names the target leaf.
    operation.update_mask.paths.extend(utils.derive_update_mask(campaign))

    return _mutate_one(
        client,
        "CampaignService",
        "MutateCampaignsRequest",
        "mutate_campaigns",
        customer_id,
        operation,
        validate_only,
    )


@mcp.tool()
def update_campaign(
    customer_id: str,
    campaign_resource_name: str,
    name: str = None,
    campaign_budget_resource_name: str = None,
    start_date: str = None,
    end_date: str = None,
    validate_only: bool = False,
) -> str:
    """Updates a campaign's name, budget link or schedule.

    Only the arguments you pass are changed. Use update_campaign_status to
    pause or enable a campaign, and update_campaign_bidding to change targets.

    Args:
        customer_id: Customer ID without hyphens.
        campaign_resource_name: Campaign to update,
            e.g. 'customers/123/campaigns/456'.
        name: New campaign name.
        campaign_budget_resource_name: Budget to switch the campaign to,
            e.g. 'customers/123/campaignBudgets/789'. Moving a campaign onto
            a different budget changes what it can spend that same day.
        start_date: New start date in YYYYMMDD format. Cannot be changed once
            the campaign has started serving.
        end_date: New end date in YYYYMMDD format. Use '20371230' to remove
            an end date and let the campaign run indefinitely.
        validate_only: When True, validate without applying.

    Returns:
        Resource name of the updated campaign.
    """
    client = utils.get_googleads_client()
    operation = client.get_type("CampaignOperation")
    campaign = operation.update
    campaign.resource_name = campaign_resource_name

    if name is not None:
        campaign.name = name
    if campaign_budget_resource_name is not None:
        campaign.campaign_budget = campaign_budget_resource_name
    if start_date is not None:
        campaign.start_date = start_date
    if end_date is not None:
        campaign.end_date = end_date

    paths = utils.derive_update_mask(campaign)
    if not paths:
        raise ToolError(
            "No fields to update: pass at least one of 'name', "
            "'campaign_budget_resource_name', 'start_date' or 'end_date'."
        )
    operation.update_mask.paths.extend(paths)

    return _mutate_one(
        client,
        "CampaignService",
        "MutateCampaignsRequest",
        "mutate_campaigns",
        customer_id,
        operation,
        validate_only,
    )


@mcp.tool()
def update_campaign_budget(
    customer_id: str,
    campaign_budget_resource_name: str,
    amount_micros: int = None,
    name: str = None,
    delivery_method: str = None,
    explicitly_shared: bool = None,
    validate_only: bool = False,
) -> str:
    """Changes the amount or settings of an existing campaign budget.

    Only the arguments you pass are changed. A budget shared by several
    campaigns affects all of them, so check what is attached before raising or
    lowering an amount.

    Args:
        customer_id: Customer ID without hyphens.
        campaign_budget_resource_name: Budget to update,
            e.g. 'customers/123/campaignBudgets/456'.
        amount_micros: New daily amount in micros
            (1 unit = 1,000,000 micros, so 5000000 is 5 per day).
        name: New budget name.
        delivery_method: 'STANDARD' or 'ACCELERATED'.
        explicitly_shared: Whether the budget may be shared across campaigns.
        validate_only: When True, validate without applying.

    Returns:
        Resource name of the updated campaign budget.
    """
    client = utils.get_googleads_client()
    operation = client.get_type("CampaignBudgetOperation")
    budget = operation.update
    budget.resource_name = campaign_budget_resource_name

    if amount_micros is not None:
        budget.amount_micros = amount_micros
    if name is not None:
        budget.name = name
    if delivery_method is not None:
        budget.delivery_method = utils.enum_value(
            client, "BudgetDeliveryMethodEnum", delivery_method
        )
    if explicitly_shared is not None:
        budget.explicitly_shared = explicitly_shared

    paths = utils.derive_update_mask(budget)
    if not paths:
        raise ToolError(
            "No fields to update: pass at least one of 'amount_micros', "
            "'name', 'delivery_method' or 'explicitly_shared'."
        )
    operation.update_mask.paths.extend(paths)

    return _mutate_one(
        client,
        "CampaignBudgetService",
        "MutateCampaignBudgetsRequest",
        "mutate_campaign_budgets",
        customer_id,
        operation,
        validate_only,
    )
