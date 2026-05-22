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

"""Tools for Google Search Console API."""

from typing import Any, Dict, List, Optional
from ads_mcp.coordinator import mcp
from mcp.types import ToolAnnotations
import ads_mcp.utils as utils
from fastmcp.exceptions import ToolError


def _raise_gsc_error(ex):
    raise ToolError(f"GSC API Error {ex.status_code}: {ex.reason}")


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def list_gsc_sites() -> List[Dict[str, Any]]:
    """Lists all sites the authenticated user has in Google Search Console.

    Returns:
        List of dicts with keys: siteUrl, permissionLevel.
    """
    try:
        from googleapiclient.errors import HttpError
        resp = utils.get_gsc_service().sites().list().execute()
        return resp.get("siteEntry", [])
    except HttpError as ex:
        _raise_gsc_error(ex)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def query_search_analytics(
    site_url: str,
    start_date: str,
    end_date: str,
    dimensions: Optional[List[str]] = None,
    row_limit: int = 1000,
) -> List[Dict[str, Any]]:
    """Queries Google Search Console search analytics data.

    Args:
        site_url: GSC property URL, e.g. 'sc-domain:example.com' or
            'https://example.com/'.
        start_date: Start date in YYYY-MM-DD format.
        end_date: End date in YYYY-MM-DD format.
        dimensions: Dimensions to group by. Options: 'query', 'page',
            'country', 'device', 'date'. Default: ['query'].
        row_limit: Max rows to return (1-25000). Default 1000.

    Returns:
        List of dicts with keys: keys (list of dimension values),
        clicks, impressions, ctr, position.
    """
    from googleapiclient.errors import HttpError

    if dimensions is None:
        dimensions = ["query"]

    body = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": dimensions,
        "rowLimit": row_limit,
    }
    try:
        resp = (
            utils.get_gsc_service()
            .searchanalytics()
            .query(siteUrl=site_url, body=body)
            .execute()
        )
        return resp.get("rows", [])
    except HttpError as ex:
        _raise_gsc_error(ex)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def inspect_url(site_url: str, inspection_url: str) -> Dict[str, Any]:
    """Inspects a URL's indexing status in Google Search Console.

    Args:
        site_url: GSC property that owns the URL,
            e.g. 'sc-domain:example.com'.
        inspection_url: The exact URL to inspect,
            e.g. 'https://example.com/page'.

    Returns:
        Dict with indexStatusResult, mobileUsabilityResult,
        richResultsResult and inspectionResultLink.
    """
    from googleapiclient.errors import HttpError

    body = {"inspectionUrl": inspection_url, "siteUrl": site_url}
    try:
        return (
            utils.get_gsc_service()
            .urlInspection()
            .index()
            .inspect(body=body)
            .execute()
        )
    except HttpError as ex:
        _raise_gsc_error(ex)
