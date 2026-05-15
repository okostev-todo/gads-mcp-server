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

"""Test cases for the keyword_planner tools."""

import unittest
from unittest.mock import MagicMock, patch

from ads_mcp.tools import keyword_planner


def _make_mock_idea(text, avg_monthly, competition_name, comp_idx, low, high):
    idea = MagicMock()
    idea.text = text
    idea.keyword_idea_metrics.avg_monthly_searches = avg_monthly
    idea.keyword_idea_metrics.competition.name = competition_name
    idea.keyword_idea_metrics.competition_index = comp_idx
    idea.keyword_idea_metrics.low_top_of_page_bid_micros = low
    idea.keyword_idea_metrics.high_top_of_page_bid_micros = high
    return idea


class TestKeywordPlanner(unittest.TestCase):
    """Test cases for keyword_planner tools."""

    @patch("ads_mcp.utils.get_googleads_service")
    @patch("ads_mcp.utils.get_googleads_client")
    def test_generate_keyword_ideas_keywords_only(
        self, mock_get_client, mock_get_service
    ):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_idea = _make_mock_idea("buy shoes", 5000, "HIGH", 90, 500000, 2000000)
        mock_service.generate_keyword_ideas.return_value = [mock_idea]

        results = keyword_planner.generate_keyword_ideas(
            customer_id="1234567890",
            language_resource_name="languageConstants/1000",
            geo_target_constants=["geoTargetConstants/2804"],
            keyword_plan_network="GOOGLE_SEARCH",
            keywords=["buy shoes", "shoe shop"],
        )

        mock_get_service.assert_called_once_with("KeywordPlanIdeaService")
        mock_service.generate_keyword_ideas.assert_called_once()
        mock_client.get_type.assert_any_call("KeywordSeed")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["text"], "buy shoes")
        self.assertEqual(results[0]["avg_monthly_searches"], 5000)
        self.assertEqual(results[0]["competition"], "HIGH")
        self.assertEqual(results[0]["competition_index"], 90)

    @patch("ads_mcp.utils.get_googleads_service")
    @patch("ads_mcp.utils.get_googleads_client")
    def test_generate_keyword_ideas_url_only(
        self, mock_get_client, mock_get_service
    ):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_service.generate_keyword_ideas.return_value = []

        keyword_planner.generate_keyword_ideas(
            customer_id="1234567890",
            language_resource_name="languageConstants/1000",
            geo_target_constants=["geoTargetConstants/2804"],
            keyword_plan_network="GOOGLE_SEARCH",
            url="https://example.com",
        )

        mock_client.get_type.assert_any_call("UrlSeed")

    @patch("ads_mcp.utils.get_googleads_service")
    @patch("ads_mcp.utils.get_googleads_client")
    def test_generate_keyword_ideas_keywords_and_url(
        self, mock_get_client, mock_get_service
    ):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_service.generate_keyword_ideas.return_value = []

        keyword_planner.generate_keyword_ideas(
            customer_id="1234567890",
            language_resource_name="languageConstants/1000",
            geo_target_constants=["geoTargetConstants/2804"],
            keyword_plan_network="GOOGLE_SEARCH",
            keywords=["shoes"],
            url="https://example.com",
        )

        mock_client.get_type.assert_any_call("KeywordAndUrlSeed")

    def test_generate_keyword_ideas_no_seed_raises(self):
        from fastmcp.exceptions import ToolError

        with self.assertRaises(ToolError) as ctx:
            keyword_planner.generate_keyword_ideas(
                customer_id="1234567890",
                language_resource_name="languageConstants/1000",
                geo_target_constants=["geoTargetConstants/2804"],
                keyword_plan_network="GOOGLE_SEARCH",
            )

        self.assertIn("At least one of", str(ctx.exception))

    @patch("ads_mcp.utils.get_googleads_service")
    @patch("ads_mcp.utils.get_googleads_client")
    def test_generate_keyword_ideas_google_ads_exception(
        self, mock_get_client, mock_get_service
    ):
        from google.ads.googleads.errors import GoogleAdsException
        from fastmcp.exceptions import ToolError

        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_get_client.return_value = MagicMock()

        mock_error = MagicMock()
        mock_error.message = "Quota exceeded"
        mock_failure = MagicMock()
        mock_failure.errors = [mock_error]
        ex = GoogleAdsException(
            MagicMock(), MagicMock(), MagicMock(), MagicMock()
        )
        ex.failure = mock_failure
        ex.request_id = "req-kp-001"
        mock_service.generate_keyword_ideas.side_effect = ex

        with self.assertRaises(ToolError) as ctx:
            keyword_planner.generate_keyword_ideas(
                customer_id="1234567890",
                language_resource_name="languageConstants/1000",
                geo_target_constants=["geoTargetConstants/2804"],
                keyword_plan_network="GOOGLE_SEARCH",
                keywords=["shoes"],
            )

        self.assertIn("Quota exceeded", str(ctx.exception))
        self.assertIn("req-kp-001", str(ctx.exception))

    @patch("ads_mcp.utils.get_googleads_service")
    @patch("ads_mcp.utils.get_googleads_client")
    def test_get_keyword_historical_metrics_success(
        self, mock_get_client, mock_get_service
    ):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_get_client.return_value = MagicMock()

        mock_item = MagicMock()
        mock_item.text = "running shoes"
        mock_item.keyword_metrics.avg_monthly_searches = 3000
        mock_item.keyword_metrics.competition.name = "MEDIUM"
        mock_item.keyword_metrics.competition_index = 55
        mock_item.keyword_metrics.low_top_of_page_bid_micros = 300000
        mock_item.keyword_metrics.high_top_of_page_bid_micros = 1500000
        mock_service.generate_keyword_historical_metrics.return_value.metrics = [
            mock_item
        ]

        results = keyword_planner.get_keyword_historical_metrics(
            customer_id="1234567890",
            keywords=["running shoes"],
            language_resource_name="languageConstants/1000",
            geo_target_constants=["geoTargetConstants/2804"],
            keyword_plan_network="GOOGLE_SEARCH",
        )

        mock_get_service.assert_called_once_with("KeywordPlanIdeaService")
        mock_service.generate_keyword_historical_metrics.assert_called_once()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["text"], "running shoes")
        self.assertEqual(results[0]["avg_monthly_searches"], 3000)
        self.assertEqual(results[0]["competition"], "MEDIUM")

    @patch("ads_mcp.utils.get_googleads_service")
    @patch("ads_mcp.utils.get_googleads_client")
    def test_get_keyword_historical_metrics_google_ads_exception(
        self, mock_get_client, mock_get_service
    ):
        from google.ads.googleads.errors import GoogleAdsException
        from fastmcp.exceptions import ToolError

        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_get_client.return_value = MagicMock()

        mock_error = MagicMock()
        mock_error.message = "Invalid customer ID"
        mock_failure = MagicMock()
        mock_failure.errors = [mock_error]
        ex = GoogleAdsException(
            MagicMock(), MagicMock(), MagicMock(), MagicMock()
        )
        ex.failure = mock_failure
        ex.request_id = "req-kp-002"
        mock_service.generate_keyword_historical_metrics.side_effect = ex

        with self.assertRaises(ToolError) as ctx:
            keyword_planner.get_keyword_historical_metrics(
                customer_id="bad-id",
                keywords=["shoes"],
                language_resource_name="languageConstants/1000",
                geo_target_constants=["geoTargetConstants/2804"],
                keyword_plan_network="GOOGLE_SEARCH",
            )

        self.assertIn("Invalid customer ID", str(ctx.exception))
        self.assertIn("req-kp-002", str(ctx.exception))
