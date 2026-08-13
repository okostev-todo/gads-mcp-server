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

"""Tools for excluding placements, apps, videos and keywords from serving."""

from typing import Any, Dict, List

from ads_mcp.coordinator import mcp
import ads_mcp.utils as utils
from google.ads.googleads.errors import GoogleAdsException
from fastmcp.exceptions import ToolError

# Maps the collection segment of a resource name to the service that mutates
# it, so removals can be routed without the caller naming a resource type.
_REMOVABLE = {
    "campaignCriteria": (
        "CampaignCriterionService",
        "CampaignCriterionOperation",
        "MutateCampaignCriteriaRequest",
        "mutate_campaign_criteria",
    ),
    "customerNegativeCriteria": (
        "CustomerNegativeCriterionService",
        "CustomerNegativeCriterionOperation",
        "MutateCustomerNegativeCriteriaRequest",
        "mutate_customer_negative_criteria",
    ),
    "adGroupCriteria": (
        "AdGroupCriterionService",
        "AdGroupCriterionOperation",
        "MutateAdGroupCriteriaRequest",
        "mutate_ad_group_criteria",
    ),
    "sharedCriteria": (
        "SharedCriterionService",
        "SharedCriterionOperation",
        "MutateSharedCriteriaRequest",
        "mutate_shared_criteria",
    ),
    "sharedSets": (
        "SharedSetService",
        "SharedSetOperation",
        "MutateSharedSetsRequest",
        "mutate_shared_sets",
    ),
    "campaignSharedSets": (
        "CampaignSharedSetService",
        "CampaignSharedSetOperation",
        "MutateCampaignSharedSetsRequest",
        "mutate_campaign_shared_sets",
    ),
    "assetGroupSignals": (
        "AssetGroupSignalService",
        "AssetGroupSignalOperation",
        "MutateAssetGroupSignalsRequest",
        "mutate_asset_group_signals",
    ),
}


def _submit(
    client,
    service_name: str,
    request_type: str,
    method: str,
    customer_id: str,
    operations: List[Any],
    validate_only: bool,
    partial_failure: bool = False,
) -> Dict[str, Any]:
    """Sends one batch of operations and normalizes the response."""
    service = utils.get_googleads_service(service_name)
    request = client.get_type(request_type)
    request.customer_id = customer_id
    request.operations.extend(operations)
    request.validate_only = validate_only
    if partial_failure:
        request.partial_failure = True

    try:
        response = getattr(service, method)(request=request)
    except GoogleAdsException as ex:
        utils.raise_google_ads_error(ex)

    errors = utils.partial_failure_errors(client, response)
    return {
        "resource_names": [result.resource_name for result in response.results],
        "errors": errors,
    }


def _build_criteria(
    client,
    operation_type: str,
    parent_field: str,
    parent_value: str,
    placements: List[str],
    youtube_videos: List[str],
    youtube_channels: List[str],
    mobile_apps: List[str],
    content_labels: List[str],
    negative: bool,
) -> List[Any]:
    """Builds one criterion operation per excluded entity."""
    operations = []

    def new_criterion():
        operation = client.get_type(operation_type)
        criterion = operation.create
        if parent_field:
            setattr(criterion, parent_field, parent_value)
        if negative:
            criterion.negative = True
        operations.append(operation)
        return criterion

    for url in placements or []:
        new_criterion().placement.url = url
    for video_id in youtube_videos or []:
        new_criterion().youtube_video.video_id = video_id
    for channel_id in youtube_channels or []:
        new_criterion().youtube_channel.channel_id = channel_id
    for app_id in mobile_apps or []:
        new_criterion().mobile_application.app_id = app_id
    for label in content_labels or []:
        new_criterion().content_label.type_ = utils.enum_value(
            client, "ContentLabelTypeEnum", label
        )

    return operations


@mcp.tool()
def add_account_level_exclusions(
    customer_id: str,
    placements: List[str] = None,
    youtube_videos: List[str] = None,
    youtube_channels: List[str] = None,
    mobile_apps: List[str] = None,
    content_labels: List[str] = None,
    validate_only: bool = False,
) -> Dict[str, Any]:
    """Excludes placements, apps, videos or content types account-wide.

    These exclusions apply to every campaign in the account, including
    Performance Max, and are the only reliable way to stop PMax from serving
    on specific Display placements, mobile apps or YouTube inventory. Use this
    to clear out junk placements found in a placement report.

    Exclusions are additive and take effect immediately. To undo one, pass its
    resource name to remove_criteria.

    Args:
        customer_id: Customer ID without hyphens (e.g. '5132067848').
        placements: Website domains or URLs to exclude,
            e.g. ['badsite.example', 'example.com/spam-page'].
        youtube_videos: YouTube video IDs to exclude (the 11-character id
            from the watch URL, not the full URL).
        youtube_channels: YouTube channel IDs to exclude, e.g. ['UCxxxx'].
        mobile_apps: Mobile app IDs to exclude. Android uses the package
            name and iOS uses the numeric store id, both prefixed by
            platform, e.g. ['1-com.example.app', '2-123456789'].
        content_labels: Sensitive content categories to exclude, e.g.
            ['TRAGEDY', 'SEXUALLY_SUGGESTIVE', 'PROFANITY']. An invalid name
            returns the full list of valid values.
        validate_only: When True, validate without applying. Recommended for
            a first pass on a large list.

    Returns:
        Dict with 'resource_names' of the created exclusions and 'errors'
        for any rows the API rejected.
    """
    client = utils.get_googleads_client()
    operations = _build_criteria(
        client,
        "CustomerNegativeCriterionOperation",
        None,
        None,
        placements,
        youtube_videos,
        youtube_channels,
        mobile_apps,
        content_labels,
        negative=False,
    )
    if not operations:
        raise ToolError(
            "Provide at least one of 'placements', 'youtube_videos', "
            "'youtube_channels', 'mobile_apps' or 'content_labels'."
        )

    return _submit(
        client,
        "CustomerNegativeCriterionService",
        "MutateCustomerNegativeCriteriaRequest",
        "mutate_customer_negative_criteria",
        customer_id,
        operations,
        validate_only,
        partial_failure=not validate_only,
    )


@mcp.tool()
def add_campaign_exclusions(
    customer_id: str,
    campaign_resource_name: str,
    placements: List[str] = None,
    youtube_videos: List[str] = None,
    youtube_channels: List[str] = None,
    mobile_apps: List[str] = None,
    content_labels: List[str] = None,
    validate_only: bool = False,
) -> Dict[str, Any]:
    """Excludes placements, apps, videos or content types for one campaign.

    Same inventory controls as add_account_level_exclusions but scoped to a
    single campaign, for when other campaigns should still be allowed to serve
    there. For negative keywords use add_negative_keywords instead.

    Args:
        customer_id: Customer ID without hyphens.
        campaign_resource_name: Target campaign,
            e.g. 'customers/123/campaigns/456'.
        placements: Website domains or URLs to exclude.
        youtube_videos: YouTube video IDs to exclude.
        youtube_channels: YouTube channel IDs to exclude.
        mobile_apps: Mobile app IDs to exclude, platform-prefixed.
        content_labels: Sensitive content categories to exclude.
        validate_only: When True, validate without applying.

    Returns:
        Dict with 'resource_names' of the created criteria and 'errors'.
    """
    client = utils.get_googleads_client()
    operations = _build_criteria(
        client,
        "CampaignCriterionOperation",
        "campaign",
        campaign_resource_name,
        placements,
        youtube_videos,
        youtube_channels,
        mobile_apps,
        content_labels,
        negative=True,
    )
    if not operations:
        raise ToolError(
            "Provide at least one of 'placements', 'youtube_videos', "
            "'youtube_channels', 'mobile_apps' or 'content_labels'."
        )

    return _submit(
        client,
        "CampaignCriterionService",
        "MutateCampaignCriteriaRequest",
        "mutate_campaign_criteria",
        customer_id,
        operations,
        validate_only,
        partial_failure=not validate_only,
    )


@mcp.tool()
def create_shared_exclusion_list(
    customer_id: str,
    name: str,
    list_type: str = "NEGATIVE_KEYWORDS",
    validate_only: bool = False,
) -> str:
    """Creates an empty shared exclusion list.

    A shared list is maintained once and attached to many campaigns, which is
    the maintainable way to run a common negative list. The full flow is:
    create the list here, fill it with add_criteria_to_shared_set, then link it
    to campaigns with attach_shared_set_to_campaigns.

    Args:
        customer_id: Customer ID without hyphens.
        name: List name, unique within the account.
        list_type: 'NEGATIVE_KEYWORDS' (default) or 'NEGATIVE_PLACEMENTS'.
            A list holds only its own kind of criterion.
        validate_only: When True, validate without applying.

    Returns:
        Resource name of the created shared set,
        e.g. 'customers/123/sharedSets/456'.
    """
    client = utils.get_googleads_client()
    operation = client.get_type("SharedSetOperation")
    shared_set = operation.create
    shared_set.name = name
    shared_set.type_ = utils.enum_value(client, "SharedSetTypeEnum", list_type)

    result = _submit(
        client,
        "SharedSetService",
        "MutateSharedSetsRequest",
        "mutate_shared_sets",
        customer_id,
        [operation],
        validate_only,
    )
    names = result["resource_names"]
    return names[0] if names else utils.VALIDATED_NO_CHANGES


@mcp.tool()
def add_criteria_to_shared_set(
    customer_id: str,
    shared_set_resource_name: str,
    keywords: List[str] = None,
    match_type: str = "BROAD",
    placements: List[str] = None,
    validate_only: bool = False,
) -> Dict[str, Any]:
    """Adds negative keywords or placements to a shared exclusion list.

    Use this both to fill a new list and to top up an existing one. The
    criterion kind must match the list's type: keywords go into a
    NEGATIVE_KEYWORDS list, placements into a NEGATIVE_PLACEMENTS list.

    Every campaign already linked to the list picks up the additions
    immediately, with no need to re-attach.

    Args:
        customer_id: Customer ID without hyphens.
        shared_set_resource_name: Target list,
            e.g. 'customers/123/sharedSets/456'.
        keywords: Negative keyword texts to add.
        match_type: Match type for keywords. 'BROAD' (default), 'PHRASE'
            or 'EXACT'.
        placements: Domains or URLs to add.
        validate_only: When True, validate without applying.

    Returns:
        Dict with 'resource_names' of the created criteria and 'errors'.
    """
    if not keywords and not placements:
        raise ToolError("Provide at least one of 'keywords' or 'placements'.")

    client = utils.get_googleads_client()
    match_type_enum = utils.enum_value(
        client, "KeywordMatchTypeEnum", match_type
    )

    operations = []
    for text in keywords or []:
        operation = client.get_type("SharedCriterionOperation")
        criterion = operation.create
        criterion.shared_set = shared_set_resource_name
        criterion.keyword.text = text
        criterion.keyword.match_type = match_type_enum
        operations.append(operation)
    for url in placements or []:
        operation = client.get_type("SharedCriterionOperation")
        criterion = operation.create
        criterion.shared_set = shared_set_resource_name
        criterion.placement.url = url
        operations.append(operation)

    return _submit(
        client,
        "SharedCriterionService",
        "MutateSharedCriteriaRequest",
        "mutate_shared_criteria",
        customer_id,
        operations,
        validate_only,
        partial_failure=not validate_only,
    )


@mcp.tool()
def attach_shared_set_to_campaigns(
    customer_id: str,
    shared_set_resource_name: str,
    campaign_resource_names: List[str],
    validate_only: bool = False,
) -> Dict[str, Any]:
    """Links a shared exclusion list to one or more campaigns.

    Args:
        customer_id: Customer ID without hyphens.
        shared_set_resource_name: List to attach,
            e.g. 'customers/123/sharedSets/456'.
        campaign_resource_names: Campaigns that should use the list.
        validate_only: When True, validate without applying.

    Returns:
        Dict with 'resource_names' of the created links and 'errors'.
        Pass a link's resource name to remove_criteria to detach it.
    """
    if not campaign_resource_names:
        raise ToolError("'campaign_resource_names' must not be empty.")

    client = utils.get_googleads_client()
    operations = []
    for campaign in campaign_resource_names:
        operation = client.get_type("CampaignSharedSetOperation")
        link = operation.create
        link.campaign = campaign
        link.shared_set = shared_set_resource_name
        operations.append(operation)

    return _submit(
        client,
        "CampaignSharedSetService",
        "MutateCampaignSharedSetsRequest",
        "mutate_campaign_shared_sets",
        customer_id,
        operations,
        validate_only,
        partial_failure=not validate_only,
    )


@mcp.tool()
def remove_criteria(
    customer_id: str,
    resource_names: List[str],
    validate_only: bool = False,
) -> Dict[str, Any]:
    """Removes criteria, shared lists or signals by resource name.

    The resource type is inferred from each name, so a single call can undo
    exclusions of different kinds. Supported types: campaignCriteria,
    customerNegativeCriteria, adGroupCriteria, sharedCriteria, sharedSets,
    campaignSharedSets and assetGroupSignals.

    Removal is permanent: the criterion has to be recreated to come back, and
    it loses its accumulated statistics. Run with validate_only=True first if
    the list was assembled programmatically.

    Args:
        customer_id: Customer ID without hyphens.
        resource_names: Resource names to remove, e.g.
            ['customers/123/campaignCriteria/456~789',
             'customers/123/customerNegativeCriteria/321'].
        validate_only: When True, validate without applying.

    Returns:
        Dict with 'removed' (resource names, grouped by type) and 'errors'.
    """
    if not resource_names:
        raise ToolError("'resource_names' must not be empty.")

    grouped: Dict[str, List[str]] = {}
    for resource_name in resource_names:
        parts = resource_name.split("/")
        collection = parts[2] if len(parts) > 2 else None
        if collection not in _REMOVABLE:
            raise ToolError(
                f"Cannot remove '{resource_name}': unsupported resource type "
                f"'{collection}'. Supported types: "
                f"{', '.join(sorted(_REMOVABLE))}. Use mutate_google_ads for "
                "anything else."
            )
        grouped.setdefault(collection, []).append(resource_name)

    client = utils.get_googleads_client()
    removed: Dict[str, List[str]] = {}
    errors: List[Dict[str, Any]] = []

    for collection, names in grouped.items():
        service_name, operation_type, request_type, method = _REMOVABLE[
            collection
        ]
        operations = []
        for name in names:
            operation = client.get_type(operation_type)
            operation.remove = name
            operations.append(operation)

        result = _submit(
            client,
            service_name,
            request_type,
            method,
            customer_id,
            operations,
            validate_only,
            partial_failure=not validate_only,
        )
        removed[collection] = result["resource_names"]
        errors.extend(result["errors"])

    return {"removed": removed, "errors": errors}
