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

"""Tools for Google Analytics 4 Data and Admin APIs."""

from typing import Any, Dict, List, Optional
from ads_mcp.coordinator import mcp
from mcp.types import ToolAnnotations
import ads_mcp.utils as utils
from fastmcp.exceptions import ToolError


def _normalize_property_id(property_id: str) -> str:
    if not property_id.startswith("properties/"):
        return f"properties/{property_id}"
    return property_id


def _parse_metric_value(v) -> Any:
    val = v.value
    try:
        return int(val) if "." not in val else float(val)
    except (ValueError, AttributeError):
        return val


def _serialize_row(row, dim_names: List[str], metric_names: List[str]) -> Dict:
    return {
        "dimensions": {dim_names[i]: row.dimension_values[i].value for i in range(len(dim_names))},
        "metrics": {metric_names[i]: _parse_metric_value(row.metric_values[i]) for i in range(len(metric_names))},
    }


def _serialize_report_response(response) -> Dict[str, Any]:
    dim_names = [h.name for h in response.dimension_headers]
    metric_names = [h.name for h in response.metric_headers]
    rows = [_serialize_row(r, dim_names, metric_names) for r in (response.rows or [])]

    result: Dict[str, Any] = {
        "dimension_headers": dim_names,
        "metric_headers": [
            {"name": h.name, "type": h.type_.name}
            for h in response.metric_headers
        ],
        "rows": rows,
        "row_count": response.row_count,
    }

    meta = {}
    if response.metadata:
        meta["currency_code"] = response.metadata.currency_code
        meta["time_zone"] = response.metadata.time_zone
        meta["data_loss_from_other_row"] = response.metadata.data_loss_from_other_row
    result["metadata"] = meta
    return result


_STRING_MATCH_TYPES = {
    "EXACT": 1,
    "BEGINS_WITH": 2,
    "ENDS_WITH": 3,
    "CONTAINS": 4,
    "FULL_REGEXP": 5,
    "PARTIAL_REGEXP": 6,
}

_NUMERIC_OPS = {
    "EQUAL": 1,
    "LESS_THAN": 2,
    "LESS_THAN_OR_EQUAL": 3,
    "GREATER_THAN": 4,
    "GREATER_THAN_OR_EQUAL": 5,
}


def _build_filter_expression(f: Dict) -> Any:
    """Converts a simple filter dict to a GA4 FilterExpression.

    Supported shapes:
      {"field": "sessionMedium", "match": "EXACT", "value": "cpc"}
      {"field": "sessionSource", "match": "IN_LIST", "values": ["google", "fb"]}
      {"field": "sessions", "match": "GREATER_THAN", "value": 100}
      {"and": [...]}  {"or": [...]}  {"not": {...}}
    """
    from google.analytics.data_v1beta.types import (
        FilterExpression,
        FilterExpressionList,
        Filter,
        NumericValue,
    )

    if "and" in f:
        return FilterExpression(
            and_group=FilterExpressionList(
                expressions=[_build_filter_expression(x) for x in f["and"]]
            )
        )
    if "or" in f:
        return FilterExpression(
            or_group=FilterExpressionList(
                expressions=[_build_filter_expression(x) for x in f["or"]]
            )
        )
    if "not" in f:
        return FilterExpression(not_expression=_build_filter_expression(f["not"]))

    field = f["field"]
    match = f.get("match", "EXACT")

    if match == "IN_LIST":
        return FilterExpression(
            filter=Filter(
                field_name=field,
                in_list_filter=Filter.InListFilter(values=f["values"]),
            )
        )

    if match in _NUMERIC_OPS:
        return FilterExpression(
            filter=Filter(
                field_name=field,
                numeric_filter=Filter.NumericFilter(
                    operation=_NUMERIC_OPS[match],
                    value=NumericValue(int64_value=int(f["value"])),
                ),
            )
        )

    return FilterExpression(
        filter=Filter(
            field_name=field,
            string_filter=Filter.StringFilter(
                value=str(f["value"]),
                match_type=_STRING_MATCH_TYPES.get(match, 1),
            ),
        )
    )


def _build_run_report_request(
    property_id: str,
    dimensions: List[str],
    metrics: List[str],
    date_ranges: List[Dict],
    dimension_filter: Optional[Dict],
    metric_filter: Optional[Dict],
    order_bys: Optional[List[Dict]],
    limit: int,
    offset: int,
    keep_empty_rows: bool,
):
    from google.analytics.data_v1beta.types import (
        RunReportRequest,
        DateRange,
        Dimension,
        Metric,
        OrderBy,
    )

    request = RunReportRequest(
        property=_normalize_property_id(property_id),
        dimensions=[Dimension(name=d) for d in dimensions],
        metrics=[Metric(name=m) for m in metrics],
        date_ranges=[DateRange(start_date=r["start_date"], end_date=r["end_date"]) for r in date_ranges],
        limit=limit,
        offset=offset,
        keep_empty_rows=keep_empty_rows,
    )

    if dimension_filter:
        request.dimension_filter = _build_filter_expression(dimension_filter)
    if metric_filter:
        request.metric_filter = _build_filter_expression(metric_filter)

    if order_bys:
        obs = []
        for ob in order_bys:
            if "metric" in ob:
                obs.append(OrderBy(
                    metric=OrderBy.MetricOrderBy(metric_name=ob["metric"]),
                    desc=ob.get("desc", False),
                ))
            elif "dimension" in ob:
                obs.append(OrderBy(
                    dimension=OrderBy.DimensionOrderBy(dimension_name=ob["dimension"]),
                    desc=ob.get("desc", False),
                ))
        request.order_bys = obs

    return request


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def list_ga4_properties() -> List[Dict[str, Any]]:
    """Lists all GA4 accounts and properties the user has access to.

    Returns:
        List of dicts with keys: account_id, account_name, property_id,
        property_name, time_zone, currency_code.
    """
    try:
        client = utils.get_ga4_admin_client()
        results = []
        for summary in client.list_account_summaries().account_summaries:
            account_id = summary.account.split("/")[-1]
            for prop in summary.property_summaries:
                results.append({
                    "account_id": account_id,
                    "account_name": summary.display_name,
                    "property_id": prop.property,
                    "property_name": prop.display_name,
                })
        return results
    except Exception as ex:
        raise ToolError(f"GA4 Admin API Error: {ex}") from ex


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def get_ga4_metadata(property_id: str) -> Dict[str, Any]:
    """Returns all available dimensions and metrics for a GA4 property.

    Includes custom dimensions and events configured for this property.

    Args:
        property_id: GA4 property ID, e.g. 'properties/123456789' or
            just '123456789'.

    Returns:
        Dict with 'dimensions' and 'metrics' lists, each item has
        api_name, ui_name, category, custom_definition.
    """
    try:
        from google.analytics.data_v1beta.types import GetMetadataRequest
        client = utils.get_ga4_data_client()
        meta = client.get_metadata(
            request=GetMetadataRequest(
                name=f"{_normalize_property_id(property_id)}/metadata"
            )
        )
        return {
            "dimensions": [
                {
                    "api_name": d.api_name,
                    "ui_name": d.ui_name,
                    "category": d.category,
                    "custom_definition": d.custom_definition,
                }
                for d in meta.dimensions
            ],
            "metrics": [
                {
                    "api_name": m.api_name,
                    "ui_name": m.ui_name,
                    "category": m.category,
                    "custom_definition": m.custom_definition,
                }
                for m in meta.metrics
            ],
        }
    except Exception as ex:
        raise ToolError(f"GA4 API Error: {ex}") from ex


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def run_ga4_report(
    property_id: str,
    dimensions: List[str],
    metrics: List[str],
    date_ranges: List[Dict[str, str]],
    dimension_filter: Optional[Dict] = None,
    metric_filter: Optional[Dict] = None,
    order_bys: Optional[List[Dict]] = None,
    limit: int = 10000,
    offset: int = 0,
    keep_empty_rows: bool = False,
) -> Dict[str, Any]:
    """Runs a GA4 analytics report.

    Args:
        property_id: GA4 property, e.g. 'properties/123456789' or '123456789'.
        dimensions: Dimension names, e.g. ['sessionDefaultChannelGroup',
            'sessionSource', 'sessionMedium', 'landingPage', 'date',
            'yearMonth', 'country', 'deviceCategory'].
        metrics: Metric names, e.g. ['sessions', 'totalUsers', 'newUsers',
            'bounceRate', 'conversions', 'purchaseRevenue', 'averageSessionDuration'].
        date_ranges: List of date range dicts with 'start_date' and 'end_date'.
            Supports relative dates: 'today', 'yesterday', 'NdaysAgo'.
            Example: [{"start_date": "30daysAgo", "end_date": "today"}]
        dimension_filter: Optional filter dict. Examples:
            {"field": "sessionMedium", "match": "EXACT", "value": "cpc"}
            {"field": "sessionSource", "match": "IN_LIST", "values": ["google", "facebook"]}
            {"field": "pagePath", "match": "PARTIAL_REGEXP", "value": "/blog/"}
            {"and": [{"field": "sessionMedium", "match": "EXACT", "value": "cpc"},
                     {"field": "sessionSource", "match": "EXACT", "value": "google"}]}
        metric_filter: Optional filter on metrics.
            Example: {"field": "sessions", "match": "GREATER_THAN", "value": 50}
        order_bys: Optional sort order. Example:
            [{"metric": "sessions", "desc": true}]
            [{"dimension": "date", "desc": false}]
        limit: Max rows to return (1-250000). Default 10000.
        offset: Row offset for pagination. Default 0.
        keep_empty_rows: Include rows with all-zero metrics. Default false.

    Returns:
        Dict with dimension_headers, metric_headers, rows (each row has
        'dimensions' and 'metrics' dicts), row_count, and metadata
        (currency_code, time_zone, data_loss_from_other_row).
        data_loss_from_other_row=true means results were sampled.
    """
    try:
        client = utils.get_ga4_data_client()
        request = _build_run_report_request(
            property_id=property_id,
            dimensions=dimensions,
            metrics=metrics,
            date_ranges=date_ranges,
            dimension_filter=dimension_filter,
            metric_filter=metric_filter,
            order_bys=order_bys,
            limit=limit,
            offset=offset,
            keep_empty_rows=keep_empty_rows,
        )
        response = client.run_report(request=request)
        return _serialize_report_response(response)
    except Exception as ex:
        raise ToolError(f"GA4 API Error: {ex}") from ex


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def run_ga4_realtime_report(
    property_id: str,
    dimensions: List[str],
    metrics: List[str],
    dimension_filter: Optional[Dict] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    """Runs a GA4 realtime report (last 30 minutes of activity).

    Use for troubleshooting — e.g. verifying a new campaign or landing page
    is receiving traffic right now.

    Args:
        property_id: GA4 property ID, e.g. '123456789'.
        dimensions: e.g. ['country', 'deviceCategory', 'unifiedScreenName'].
        metrics: e.g. ['activeUsers', 'screenPageViews', 'eventCount'].
        dimension_filter: Optional filter dict (same format as run_ga4_report).
        limit: Max rows. Default 100.

    Returns:
        Dict with dimension_headers, metric_headers, rows, row_count.
    """
    try:
        from google.analytics.data_v1beta.types import (
            RunRealtimeReportRequest,
            Dimension,
            Metric,
        )
        client = utils.get_ga4_data_client()
        request = RunRealtimeReportRequest(
            property=_normalize_property_id(property_id),
            dimensions=[Dimension(name=d) for d in dimensions],
            metrics=[Metric(name=m) for m in metrics],
            limit=limit,
        )
        if dimension_filter:
            request.dimension_filter = _build_filter_expression(dimension_filter)

        response = client.run_realtime_report(request=request)

        dim_names = [h.name for h in response.dimension_headers]
        metric_names = [h.name for h in response.metric_headers]
        return {
            "dimension_headers": dim_names,
            "metric_headers": [h.name for h in response.metric_headers],
            "rows": [_serialize_row(r, dim_names, metric_names) for r in (response.rows or [])],
            "row_count": response.row_count,
        }
    except Exception as ex:
        raise ToolError(f"GA4 API Error: {ex}") from ex


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def batch_run_ga4_reports(
    property_id: str,
    reports: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Runs up to 5 GA4 reports in a single API call.

    More efficient than multiple run_ga4_report calls when building
    a multi-section analysis.

    Args:
        property_id: GA4 property ID, e.g. '123456789'.
        reports: List of up to 5 report configs. Each config supports the
            same keys as run_ga4_report: dimensions, metrics, date_ranges,
            dimension_filter, metric_filter, order_bys, limit, offset,
            keep_empty_rows.

    Returns:
        List of report results in the same order as input, each with the
        same structure as run_ga4_report output.
    """
    if len(reports) > 5:
        raise ToolError("batch_run_ga4_reports supports at most 5 reports per call.")
    try:
        from google.analytics.data_v1beta.types import BatchRunReportsRequest

        client = utils.get_ga4_data_client()
        prop = _normalize_property_id(property_id)

        requests = [
            _build_run_report_request(
                property_id=property_id,
                dimensions=r.get("dimensions", []),
                metrics=r.get("metrics", []),
                date_ranges=r.get("date_ranges", []),
                dimension_filter=r.get("dimension_filter"),
                metric_filter=r.get("metric_filter"),
                order_bys=r.get("order_bys"),
                limit=r.get("limit", 10000),
                offset=r.get("offset", 0),
                keep_empty_rows=r.get("keep_empty_rows", False),
            )
            for r in reports
        ]

        batch_request = BatchRunReportsRequest(property=prop, requests=requests)
        response = client.batch_run_reports(request=batch_request)
        return [_serialize_report_response(r) for r in response.reports]
    except ToolError:
        raise
    except Exception as ex:
        raise ToolError(f"GA4 API Error: {ex}") from ex
