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

"""Tools for the Google Ads Keyword Planner."""

from typing import Any, Dict, List
from ads_mcp.coordinator import mcp
from mcp.types import ToolAnnotations
import ads_mcp.utils as utils
from google.ads.googleads.errors import GoogleAdsException
from fastmcp.exceptions import ToolError


def _extract_idea_metrics(text: str, metrics) -> Dict[str, Any]:
    return {
        "text": text,
        "avg_monthly_searches": metrics.avg_monthly_searches,
        "competition": metrics.competition.name,
        "competition_index": metrics.competition_index,
        "low_top_of_page_bid_micros": metrics.low_top_of_page_bid_micros,
        "high_top_of_page_bid_micros": metrics.high_top_of_page_bid_micros,
    }


def _raise_google_ads_error(ex: GoogleAdsException):
    error_msgs = [
        f"Google Ads API Error: {error.message}" for error in ex.failure.errors
    ]
    raise ToolError(f"Request ID: {ex.request_id}\n" + "\n".join(error_msgs))


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def generate_keyword_ideas(
    customer_id: str,
    language_resource_name: str,
    geo_target_constants: List[str],
    keyword_plan_network: str,
    keywords: List[str] = None,
    url: str = None,
    page_size: int = 1000,
) -> List[Dict[str, Any]]:
    """Generates keyword ideas using seed keywords and/or a seed URL.

    Uses KeywordPlanIdeaService to generate keyword ideas with traffic
    estimates. Provide at least one of `keywords` or `url`.

    Args:
        customer_id: Customer ID without hyphens (e.g. '5132067848').
        language_resource_name: Language criterion resource name,
            e.g. 'languageConstants/1000' for English,
            'languageConstants/1014' for Ukrainian.
        geo_target_constants: List of geo target constant resource names,
            e.g. ['geoTargetConstants/2804'] for Ukraine,
            ['geoTargetConstants/2840'] for USA.
        keyword_plan_network: Network for ideas. One of:
            'GOOGLE_SEARCH' or 'GOOGLE_SEARCH_AND_PARTNERS'.
        keywords: Optional list of seed keyword strings.
        url: Optional seed URL to generate ideas from.
        page_size: Maximum number of ideas to return. Default 1000.

    Returns:
        List of dicts with keys: text, avg_monthly_searches, competition,
        competition_index, low_top_of_page_bid_micros,
        high_top_of_page_bid_micros.
    """
    if not keywords and not url:
        raise ToolError("At least one of 'keywords' or 'url' must be provided.")

    client = utils.get_googleads_client()
    service = utils.get_googleads_service("KeywordPlanIdeaService")
    request = client.get_type("GenerateKeywordIdeasRequest")

    request.customer_id = customer_id
    request.language = language_resource_name
    request.geo_target_constants.extend(geo_target_constants)
    request.keyword_plan_network = getattr(
        client.enums.KeywordPlanNetworkEnum, keyword_plan_network
    )
    request.page_size = page_size
    request.include_adult_keywords = False

    if keywords and url:
        seed = client.get_type("KeywordAndUrlSeed")
        seed.keywords.extend(keywords)
        seed.url = url
        request.keyword_and_url_seed = seed
    elif keywords:
        seed = client.get_type("KeywordSeed")
        seed.keywords.extend(keywords)
        request.keyword_seed = seed
    else:
        seed = client.get_type("UrlSeed")
        seed.url = url
        request.url_seed = seed

    try:
        response = service.generate_keyword_ideas(request=request)
        return [
            _extract_idea_metrics(idea.text, idea.keyword_idea_metrics)
            for idea in response
        ]
    except GoogleAdsException as ex:
        _raise_google_ads_error(ex)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def get_keyword_historical_metrics(
    customer_id: str,
    keywords: List[str],
    language_resource_name: str,
    geo_target_constants: List[str],
    keyword_plan_network: str,
) -> List[Dict[str, Any]]:
    """Retrieves historical metrics for a specific list of keywords.

    Uses KeywordPlanIdeaService.generate_keyword_historical_metrics() to
    return avg monthly searches, competition level, and CPC bid ranges for
    exact keyword strings.

    Args:
        customer_id: Customer ID without hyphens.
        keywords: List of exact keyword strings to get metrics for.
        language_resource_name: Language resource name,
            e.g. 'languageConstants/1000' for English.
        geo_target_constants: List of geo target constant resource names,
            e.g. ['geoTargetConstants/2804'] for Ukraine.
        keyword_plan_network: 'GOOGLE_SEARCH' or
            'GOOGLE_SEARCH_AND_PARTNERS'.

    Returns:
        List of dicts with keys: text, avg_monthly_searches, competition,
        competition_index, low_top_of_page_bid_micros,
        high_top_of_page_bid_micros.
    """
    client = utils.get_googleads_client()
    service = utils.get_googleads_service("KeywordPlanIdeaService")
    request = client.get_type("GenerateKeywordHistoricalMetricsRequest")

    request.customer_id = customer_id
    request.keywords.extend(keywords)
    request.language = language_resource_name
    request.geo_target_constants.extend(geo_target_constants)
    request.keyword_plan_network = getattr(
        client.enums.KeywordPlanNetworkEnum, keyword_plan_network
    )

    try:
        response = service.generate_keyword_historical_metrics(request=request)
        return [
            _extract_idea_metrics(item.text, item.keyword_metrics)
            for item in response.results
        ]
    except GoogleAdsException as ex:
        _raise_google_ads_error(ex)
