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

"""Test cases for the analytics (GA4) tools."""

import unittest
from unittest.mock import MagicMock, patch

from ads_mcp.tools import analytics
from ads_mcp.tools.analytics import _build_filter_expression, _normalize_property_id


class TestNormalizePropertyId(unittest.TestCase):
    def test_adds_prefix_when_missing(self):
        self.assertEqual(_normalize_property_id("123456789"), "properties/123456789")

    def test_leaves_prefix_intact(self):
        self.assertEqual(_normalize_property_id("properties/123456789"), "properties/123456789")


class TestBuildFilterExpression(unittest.TestCase):
    def test_exact_string_filter(self):
        from google.analytics.data_v1beta.types import FilterExpression
        fe = _build_filter_expression({"field": "sessionMedium", "match": "EXACT", "value": "cpc"})
        self.assertIsInstance(fe, FilterExpression)
        self.assertEqual(fe.filter.field_name, "sessionMedium")
        self.assertEqual(fe.filter.string_filter.value, "cpc")

    def test_in_list_filter(self):
        from google.analytics.data_v1beta.types import FilterExpression
        fe = _build_filter_expression({"field": "sessionSource", "match": "IN_LIST", "values": ["google", "facebook"]})
        self.assertIsInstance(fe, FilterExpression)
        self.assertIn("google", list(fe.filter.in_list_filter.values))

    def test_numeric_greater_than(self):
        from google.analytics.data_v1beta.types import FilterExpression
        fe = _build_filter_expression({"field": "sessions", "match": "GREATER_THAN", "value": 100})
        self.assertIsInstance(fe, FilterExpression)
        self.assertEqual(fe.filter.field_name, "sessions")
        self.assertEqual(fe.filter.numeric_filter.value.int64_value, 100)

    def test_and_filter(self):
        from google.analytics.data_v1beta.types import FilterExpression
        fe = _build_filter_expression({"and": [
            {"field": "sessionMedium", "match": "EXACT", "value": "cpc"},
            {"field": "sessionSource", "match": "EXACT", "value": "google"},
        ]})
        self.assertIsInstance(fe, FilterExpression)
        self.assertEqual(len(fe.and_group.expressions), 2)

    def test_or_filter(self):
        from google.analytics.data_v1beta.types import FilterExpression
        fe = _build_filter_expression({"or": [
            {"field": "deviceCategory", "match": "EXACT", "value": "mobile"},
            {"field": "deviceCategory", "match": "EXACT", "value": "tablet"},
        ]})
        self.assertEqual(len(fe.or_group.expressions), 2)

    def test_not_filter(self):
        from google.analytics.data_v1beta.types import FilterExpression
        fe = _build_filter_expression({"not": {"field": "sessionMedium", "match": "EXACT", "value": "organic"}})
        self.assertIsInstance(fe.not_expression, FilterExpression)


class TestListGa4Properties(unittest.TestCase):
    @patch("ads_mcp.utils.get_ga4_admin_client")
    def test_returns_properties(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        summary = MagicMock()
        summary.account = "accounts/111"
        summary.display_name = "My Account"
        prop = MagicMock()
        prop.property = "properties/999"
        prop.display_name = "My Property"
        summary.property_summaries = [prop]
        mock_client.list_account_summaries.return_value.account_summaries = [summary]

        results = analytics.list_ga4_properties()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["account_id"], "111")
        self.assertEqual(results[0]["property_id"], "properties/999")
        self.assertEqual(results[0]["property_name"], "My Property")


class TestRunGa4Report(unittest.TestCase):
    def _make_mock_header(self, n):
        h = MagicMock()
        h.name = n
        return h

    def _make_mock_response(self, dim_names, metric_names, row_data):
        response = MagicMock()
        response.dimension_headers = [self._make_mock_header(n) for n in dim_names]
        mh_list = []
        for n in metric_names:
            h = MagicMock()
            h.name = n
            h.type_.name = "TYPE_INTEGER"
            mh_list.append(h)
        response.metric_headers = mh_list
        response.row_count = len(row_data)
        response.metadata.currency_code = "UAH"
        response.metadata.time_zone = "Europe/Kyiv"
        response.metadata.data_loss_from_other_row = False

        rows = []
        for dims, metrics in row_data:
            row = MagicMock()
            row.dimension_values = [MagicMock(value=d) for d in dims]
            row.metric_values = [MagicMock(value=str(m)) for m in metrics]
            rows.append(row)
        response.rows = rows
        return response

    @patch("ads_mcp.utils.get_ga4_data_client")
    def test_run_report_basic(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.run_report.return_value = self._make_mock_response(
            dim_names=["sessionDefaultChannelGroup"],
            metric_names=["sessions", "totalUsers"],
            row_data=[
                (["Paid Search"], [1523, 1100]),
                (["Organic Search"], [890, 750]),
            ],
        )

        result = analytics.run_ga4_report(
            property_id="123456789",
            dimensions=["sessionDefaultChannelGroup"],
            metrics=["sessions", "totalUsers"],
            date_ranges=[{"start_date": "30daysAgo", "end_date": "today"}],
        )

        self.assertEqual(result["row_count"], 2)
        self.assertEqual(result["rows"][0]["dimensions"]["sessionDefaultChannelGroup"], "Paid Search")
        self.assertEqual(result["rows"][0]["metrics"]["sessions"], 1523)
        self.assertEqual(result["metadata"]["currency_code"], "UAH")
        self.assertFalse(result["metadata"]["data_loss_from_other_row"])

    @patch("ads_mcp.utils.get_ga4_data_client")
    def test_run_report_with_filter(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.run_report.return_value = self._make_mock_response(
            dim_names=["landingPage"],
            metric_names=["sessions"],
            row_data=[(["/landing-page"], [500])],
        )

        analytics.run_ga4_report(
            property_id="123456789",
            dimensions=["landingPage"],
            metrics=["sessions"],
            date_ranges=[{"start_date": "30daysAgo", "end_date": "today"}],
            metric_filter={"field": "sessions", "match": "GREATER_THAN", "value": 50},
        )

        call_args = mock_client.run_report.call_args
        request = call_args[1]["request"]
        self.assertIsNotNone(request.metric_filter)

    @patch("ads_mcp.utils.get_ga4_data_client")
    def test_run_report_empty_rows(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        response = MagicMock()
        response.dimension_headers = [MagicMock(name="sessionSource")]
        response.metric_headers = [MagicMock(name="sessions", type_=MagicMock(name="TYPE_INTEGER"))]
        response.rows = None
        response.row_count = 0
        response.metadata = MagicMock()
        response.metadata.currency_code = "USD"
        response.metadata.time_zone = "UTC"
        response.metadata.data_loss_from_other_row = False
        mock_client.run_report.return_value = response

        result = analytics.run_ga4_report(
            property_id="123456789",
            dimensions=["sessionSource"],
            metrics=["sessions"],
            date_ranges=[{"start_date": "7daysAgo", "end_date": "today"}],
        )

        self.assertEqual(result["rows"], [])


class TestBatchRunGa4Reports(unittest.TestCase):
    @patch("ads_mcp.utils.get_ga4_data_client")
    def test_batch_too_many_reports(self, mock_get_client):
        from fastmcp.exceptions import ToolError
        with self.assertRaises(ToolError) as ctx:
            analytics.batch_run_ga4_reports(
                property_id="123456789",
                reports=[{} for _ in range(6)],
            )
        self.assertIn("5", str(ctx.exception))
