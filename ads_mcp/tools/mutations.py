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

"""Tools for creating and managing Google Ads campaigns via mutation APIs."""

from datetime import date
from typing import List
from google.protobuf import field_mask_pb2
from ads_mcp.coordinator import mcp
import ads_mcp.utils as utils
from google.ads.googleads.errors import GoogleAdsException
from fastmcp.exceptions import ToolError


def _raise_google_ads_error(ex: GoogleAdsException):
    error_msgs = [
        f"Google Ads API Error: {error.message}"
        for error in ex.failure.errors
    ]
    raise ToolError(
        f"Request ID: {ex.request_id}\n" + "\n".join(error_msgs)
    )


@mcp.tool()
def create_campaign_budget(
    customer_id: str,
    name: str,
    amount_micros: int,
    delivery_method: str = "STANDARD",
    explicitly_shared: bool = False,
) -> str:
    """Creates a campaign budget in Google Ads.

    Args:
        customer_id: Customer ID without hyphens (e.g. '5132067848').
        name: Descriptive name for the budget.
        amount_micros: Daily budget in micros (1 USD = 1_000_000 micros).
            Example: 5_000_000 = $5/day.
        delivery_method: Budget delivery method. 'STANDARD' (default,
            evenly throughout the day) or 'ACCELERATED'.
        explicitly_shared: Whether the budget can be shared across
            multiple campaigns. Default False.

    Returns:
        Resource name of the created campaign budget,
        e.g. 'customers/123/campaignBudgets/456'.
    """
    client = utils.get_googleads_client()
    service = utils.get_googleads_service("CampaignBudgetService")
    operation = client.get_type("CampaignBudgetOperation")
    budget = operation.create
    budget.name = name
    budget.amount_micros = amount_micros
    budget.delivery_method = getattr(
        client.enums.BudgetDeliveryMethodEnum, delivery_method
    )
    budget.explicitly_shared = explicitly_shared

    try:
        response = service.mutate_campaign_budgets(
            customer_id=customer_id, operations=[operation]
        )
        return response.results[0].resource_name
    except GoogleAdsException as ex:
        _raise_google_ads_error(ex)


@mcp.tool()
def create_campaign(
    customer_id: str,
    name: str,
    campaign_budget_resource_name: str,
    advertising_channel_type: str,
    status: str = "PAUSED",
    start_date: str = None,
    end_date: str = None,
) -> str:
    """Creates a new Google Ads campaign.

    New campaigns are created in PAUSED status by default for safety.
    Use update_campaign_status to enable after reviewing settings.

    Supported channel types and their default bidding strategies:
    - SEARCH: Manual CPC
    - DISPLAY: Manual CPC
    - PERFORMANCE_MAX: Maximize conversion value (automatic)

    Args:
        customer_id: Customer ID without hyphens.
        name: Campaign name.
        campaign_budget_resource_name: Resource name from
            create_campaign_budget, e.g. 'customers/123/campaignBudgets/456'.
        advertising_channel_type: 'SEARCH', 'DISPLAY', or
            'PERFORMANCE_MAX'.
        status: 'PAUSED' (default) or 'ENABLED'.
        start_date: Campaign start date in YYYYMMDD format.
            Defaults to today.
        end_date: Campaign end date in YYYYMMDD format. Optional.

    Returns:
        Resource name of the created campaign,
        e.g. 'customers/123/campaigns/456'.
    """
    client = utils.get_googleads_client()
    service = utils.get_googleads_service("CampaignService")
    operation = client.get_type("CampaignOperation")
    campaign = operation.create

    campaign.name = name
    campaign.campaign_budget = campaign_budget_resource_name
    campaign.advertising_channel_type = getattr(
        client.enums.AdvertisingChannelTypeEnum, advertising_channel_type
    )
    campaign.status = getattr(client.enums.CampaignStatusEnum, status)
    campaign.start_date = start_date or date.today().strftime("%Y%m%d")
    if end_date:
        campaign.end_date = end_date

    if advertising_channel_type == "PERFORMANCE_MAX":
        campaign.maximize_conversion_value.target_roas = 0
    else:
        campaign.manual_cpc.enhanced_cpc_enabled = False

    try:
        response = service.mutate_campaigns(
            customer_id=customer_id, operations=[operation]
        )
        return response.results[0].resource_name
    except GoogleAdsException as ex:
        _raise_google_ads_error(ex)


@mcp.tool()
def create_ad_group(
    customer_id: str,
    campaign_resource_name: str,
    name: str,
    status: str = "ENABLED",
    cpc_bid_micros: int = None,
) -> str:
    """Creates an ad group within a campaign.

    Args:
        customer_id: Customer ID without hyphens.
        campaign_resource_name: Resource name of the parent campaign,
            e.g. 'customers/123/campaigns/456'.
        name: Ad group name.
        status: 'ENABLED' (default) or 'PAUSED'.
        cpc_bid_micros: Optional default CPC bid in micros for all
            keywords in this group. Example: 1_000_000 = $1 CPC.

    Returns:
        Resource name of the created ad group,
        e.g. 'customers/123/adGroups/456'.
    """
    client = utils.get_googleads_client()
    service = utils.get_googleads_service("AdGroupService")
    operation = client.get_type("AdGroupOperation")
    ad_group = operation.create

    ad_group.name = name
    ad_group.campaign = campaign_resource_name
    ad_group.status = getattr(client.enums.AdGroupStatusEnum, status)
    if cpc_bid_micros is not None:
        ad_group.cpc_bid_micros = cpc_bid_micros

    try:
        response = service.mutate_ad_groups(
            customer_id=customer_id, operations=[operation]
        )
        return response.results[0].resource_name
    except GoogleAdsException as ex:
        _raise_google_ads_error(ex)


@mcp.tool()
def add_keywords_to_ad_group(
    customer_id: str,
    ad_group_resource_name: str,
    keywords: List[str],
    match_type: str = "BROAD",
    cpc_bid_micros: int = None,
) -> List[str]:
    """Adds positive keywords to an ad group in a single batch call.

    Args:
        customer_id: Customer ID without hyphens.
        ad_group_resource_name: Resource name of the target ad group,
            e.g. 'customers/123/adGroups/456'.
        keywords: List of keyword text strings to add.
        match_type: Keyword match type. 'BROAD' (default), 'PHRASE',
            or 'EXACT'.
        cpc_bid_micros: Optional CPC bid override per keyword in micros.
            If omitted, the ad group default bid is used.

    Returns:
        List of resource names for created ad group criteria.
    """
    client = utils.get_googleads_client()
    service = utils.get_googleads_service("AdGroupCriterionService")
    match_type_enum = getattr(client.enums.KeywordMatchTypeEnum, match_type)

    operations = []
    for kw_text in keywords:
        op = client.get_type("AdGroupCriterionOperation")
        criterion = op.create
        criterion.ad_group = ad_group_resource_name
        criterion.keyword.text = kw_text
        criterion.keyword.match_type = match_type_enum
        if cpc_bid_micros is not None:
            criterion.cpc_bid_micros = cpc_bid_micros
        operations.append(op)

    try:
        response = service.mutate_ad_group_criteria(
            customer_id=customer_id, operations=operations
        )
        return [r.resource_name for r in response.results]
    except GoogleAdsException as ex:
        _raise_google_ads_error(ex)


@mcp.tool()
def add_negative_keywords(
    customer_id: str,
    keywords: List[str],
    match_type: str = "BROAD",
    ad_group_resource_name: str = None,
    campaign_resource_name: str = None,
) -> List[str]:
    """Adds negative keywords at ad group or campaign level.

    Provide exactly one of ad_group_resource_name or
    campaign_resource_name to control where negatives are added.

    Args:
        customer_id: Customer ID without hyphens.
        keywords: List of negative keyword text strings.
        match_type: Match type. 'BROAD' (default), 'PHRASE', or 'EXACT'.
        ad_group_resource_name: Target ad group resource name.
            Mutually exclusive with campaign_resource_name.
        campaign_resource_name: Target campaign resource name.
            Mutually exclusive with ad_group_resource_name.

    Returns:
        List of resource names for created negative keyword criteria.
    """
    if ad_group_resource_name and campaign_resource_name:
        raise ToolError(
            "Provide exactly one of 'ad_group_resource_name' or "
            "'campaign_resource_name', not both."
        )
    if not ad_group_resource_name and not campaign_resource_name:
        raise ToolError(
            "Provide exactly one of 'ad_group_resource_name' or "
            "'campaign_resource_name'."
        )

    client = utils.get_googleads_client()
    match_type_enum = getattr(client.enums.KeywordMatchTypeEnum, match_type)

    if ad_group_resource_name:
        service = utils.get_googleads_service("AdGroupCriterionService")
        operations = []
        for kw_text in keywords:
            op = client.get_type("AdGroupCriterionOperation")
            criterion = op.create
            criterion.ad_group = ad_group_resource_name
            criterion.negative = True
            criterion.keyword.text = kw_text
            criterion.keyword.match_type = match_type_enum
            operations.append(op)
        try:
            response = service.mutate_ad_group_criteria(
                customer_id=customer_id, operations=operations
            )
            return [r.resource_name for r in response.results]
        except GoogleAdsException as ex:
            _raise_google_ads_error(ex)
    else:
        service = utils.get_googleads_service("CampaignCriterionService")
        operations = []
        for kw_text in keywords:
            op = client.get_type("CampaignCriterionOperation")
            criterion = op.create
            criterion.campaign = campaign_resource_name
            criterion.negative = True
            criterion.keyword.text = kw_text
            criterion.keyword.match_type = match_type_enum
            operations.append(op)
        try:
            response = service.mutate_campaign_criteria(
                customer_id=customer_id, operations=operations
            )
            return [r.resource_name for r in response.results]
        except GoogleAdsException as ex:
            _raise_google_ads_error(ex)


@mcp.tool()
def update_campaign_status(
    customer_id: str,
    campaign_resource_name: str,
    status: str,
) -> str:
    """Updates the status of an existing campaign.

    Args:
        customer_id: Customer ID without hyphens.
        campaign_resource_name: Resource name of the campaign to update,
            e.g. 'customers/123/campaigns/456'.
        status: New status. 'ENABLED', 'PAUSED', or 'REMOVED'.
            Warning: 'REMOVED' is irreversible.

    Returns:
        Resource name of the updated campaign.
    """
    client = utils.get_googleads_client()
    service = utils.get_googleads_service("CampaignService")
    operation = client.get_type("CampaignOperation")
    campaign = operation.update
    campaign.resource_name = campaign_resource_name
    campaign.status = getattr(client.enums.CampaignStatusEnum, status)
    operation.update_mask.CopyFrom(
        field_mask_pb2.FieldMask(paths=["status"])
    )

    try:
        response = service.mutate_campaigns(
            customer_id=customer_id, operations=[operation]
        )
        return response.results[0].resource_name
    except GoogleAdsException as ex:
        _raise_google_ads_error(ex)


@mcp.tool()
def create_responsive_search_ad(
    customer_id: str,
    ad_group_resource_name: str,
    headlines: List[str],
    descriptions: List[str],
    final_urls: List[str],
    status: str = "PAUSED",
) -> str:
    """Creates a responsive search ad (RSA) within an ad group.

    New ads are created in PAUSED status by default. Google Ads rotates
    and tests combinations of headlines and descriptions automatically.

    Args:
        customer_id: Customer ID without hyphens.
        ad_group_resource_name: Resource name of the parent ad group,
            e.g. 'customers/123/adGroups/456'.
        headlines: List of headline strings. Requires 3-15 items,
            max 30 characters each.
        descriptions: List of description strings. Requires 2-4 items,
            max 90 characters each.
        final_urls: List of landing page URLs (at least one required).
        status: 'PAUSED' (default) or 'ENABLED'.

    Returns:
        Resource name of the created ad group ad,
        e.g. 'customers/123/adGroupAds/456~789'.
    """
    client = utils.get_googleads_client()
    service = utils.get_googleads_service("AdGroupAdService")
    operation = client.get_type("AdGroupAdOperation")
    ad_group_ad = operation.create

    ad_group_ad.ad_group = ad_group_resource_name
    ad_group_ad.status = getattr(client.enums.AdGroupAdStatusEnum, status)

    ad = ad_group_ad.ad
    ad.final_urls.extend(final_urls)

    rsa = ad.responsive_search_ad
    for headline_text in headlines:
        asset = client.get_type("AdTextAsset")
        asset.text = headline_text
        rsa.headlines.append(asset)
    for desc_text in descriptions:
        asset = client.get_type("AdTextAsset")
        asset.text = desc_text
        rsa.descriptions.append(asset)

    try:
        response = service.mutate_ad_group_ads(
            customer_id=customer_id, operations=[operation]
        )
        return response.results[0].resource_name
    except GoogleAdsException as ex:
        _raise_google_ads_error(ex)
