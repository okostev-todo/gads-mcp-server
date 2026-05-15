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

"""Test cases for the mutations tools."""

import unittest
from unittest.mock import MagicMock, patch

from ads_mcp.tools import mutations


def _make_google_ads_exception(message, request_id):
    from google.ads.googleads.errors import GoogleAdsException

    mock_error = MagicMock()
    mock_error.message = message
    mock_failure = MagicMock()
    mock_failure.errors = [mock_error]
    ex = GoogleAdsException(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    ex.failure = mock_failure
    ex.request_id = request_id
    return ex


class TestMutations(unittest.TestCase):
    """Test cases for campaign mutation tools."""

    @patch("ads_mcp.utils.get_googleads_service")
    @patch("ads_mcp.utils.get_googleads_client")
    def test_create_campaign_budget_success(
        self, mock_get_client, mock_get_service
    ):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_service.mutate_campaign_budgets.return_value.results = [
            MagicMock(resource_name="customers/123/campaignBudgets/456")
        ]

        result = mutations.create_campaign_budget(
            customer_id="123",
            name="Test Budget",
            amount_micros=5_000_000,
        )

        mock_get_service.assert_called_once_with("CampaignBudgetService")
        mock_service.mutate_campaign_budgets.assert_called_once()
        self.assertEqual(result, "customers/123/campaignBudgets/456")

    @patch("ads_mcp.utils.get_googleads_service")
    @patch("ads_mcp.utils.get_googleads_client")
    def test_create_campaign_success(self, mock_get_client, mock_get_service):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_service.mutate_campaigns.return_value.results = [
            MagicMock(resource_name="customers/123/campaigns/789")
        ]

        result = mutations.create_campaign(
            customer_id="123",
            name="Test Campaign",
            campaign_budget_resource_name="customers/123/campaignBudgets/456",
            advertising_channel_type="SEARCH",
        )

        mock_get_service.assert_called_once_with("CampaignService")
        mock_service.mutate_campaigns.assert_called_once()
        self.assertEqual(result, "customers/123/campaigns/789")

    @patch("ads_mcp.utils.get_googleads_service")
    @patch("ads_mcp.utils.get_googleads_client")
    def test_create_campaign_pmax_uses_maximize_conversion_value(
        self, mock_get_client, mock_get_service
    ):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_service.mutate_campaigns.return_value.results = [
            MagicMock(resource_name="customers/123/campaigns/999")
        ]

        mutations.create_campaign(
            customer_id="123",
            name="PMax Campaign",
            campaign_budget_resource_name="customers/123/campaignBudgets/456",
            advertising_channel_type="PERFORMANCE_MAX",
        )

        operation = mock_client.get_type.return_value
        campaign = operation.create
        self.assertEqual(campaign.maximize_conversion_value.target_roas, 0)

    @patch("ads_mcp.utils.get_googleads_service")
    @patch("ads_mcp.utils.get_googleads_client")
    def test_create_campaign_google_ads_exception(
        self, mock_get_client, mock_get_service
    ):
        from fastmcp.exceptions import ToolError

        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_get_client.return_value = MagicMock()
        mock_service.mutate_campaigns.side_effect = _make_google_ads_exception(
            "Budget not found", "req-mut-001"
        )

        with self.assertRaises(ToolError) as ctx:
            mutations.create_campaign(
                customer_id="123",
                name="Bad Campaign",
                campaign_budget_resource_name="customers/123/campaignBudgets/bad",
                advertising_channel_type="SEARCH",
            )

        self.assertIn("Budget not found", str(ctx.exception))
        self.assertIn("req-mut-001", str(ctx.exception))

    @patch("ads_mcp.utils.get_googleads_service")
    @patch("ads_mcp.utils.get_googleads_client")
    def test_create_ad_group_success(self, mock_get_client, mock_get_service):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_get_client.return_value = MagicMock()
        mock_service.mutate_ad_groups.return_value.results = [
            MagicMock(resource_name="customers/123/adGroups/111")
        ]

        result = mutations.create_ad_group(
            customer_id="123",
            campaign_resource_name="customers/123/campaigns/789",
            name="Test Ad Group",
        )

        mock_get_service.assert_called_once_with("AdGroupService")
        mock_service.mutate_ad_groups.assert_called_once()
        self.assertEqual(result, "customers/123/adGroups/111")

    @patch("ads_mcp.utils.get_googleads_service")
    @patch("ads_mcp.utils.get_googleads_client")
    def test_add_keywords_to_ad_group_success(
        self, mock_get_client, mock_get_service
    ):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_get_client.return_value = MagicMock()
        mock_service.mutate_ad_group_criteria.return_value.results = [
            MagicMock(resource_name="customers/123/adGroupCriteria/111~1"),
            MagicMock(resource_name="customers/123/adGroupCriteria/111~2"),
        ]

        results = mutations.add_keywords_to_ad_group(
            customer_id="123",
            ad_group_resource_name="customers/123/adGroups/111",
            keywords=["buy shoes", "shoe shop"],
            match_type="EXACT",
        )

        mock_get_service.assert_called_once_with("AdGroupCriterionService")
        call_args = mock_service.mutate_ad_group_criteria.call_args
        self.assertEqual(len(call_args.kwargs["operations"]), 2)
        self.assertEqual(len(results), 2)

    @patch("ads_mcp.utils.get_googleads_service")
    @patch("ads_mcp.utils.get_googleads_client")
    def test_add_negative_keywords_ad_group_level(
        self, mock_get_client, mock_get_service
    ):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_get_client.return_value = MagicMock()
        mock_service.mutate_ad_group_criteria.return_value.results = [
            MagicMock(resource_name="customers/123/adGroupCriteria/111~neg1")
        ]

        results = mutations.add_negative_keywords(
            customer_id="123",
            keywords=["free"],
            ad_group_resource_name="customers/123/adGroups/111",
        )

        mock_get_service.assert_called_once_with("AdGroupCriterionService")
        self.assertEqual(len(results), 1)

    @patch("ads_mcp.utils.get_googleads_service")
    @patch("ads_mcp.utils.get_googleads_client")
    def test_add_negative_keywords_campaign_level(
        self, mock_get_client, mock_get_service
    ):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_get_client.return_value = MagicMock()
        mock_service.mutate_campaign_criteria.return_value.results = [
            MagicMock(resource_name="customers/123/campaignCriteria/789~neg1")
        ]

        results = mutations.add_negative_keywords(
            customer_id="123",
            keywords=["free"],
            campaign_resource_name="customers/123/campaigns/789",
        )

        mock_get_service.assert_called_once_with("CampaignCriterionService")
        self.assertEqual(len(results), 1)

    def test_add_negative_keywords_both_raises(self):
        from fastmcp.exceptions import ToolError

        with self.assertRaises(ToolError) as ctx:
            mutations.add_negative_keywords(
                customer_id="123",
                keywords=["free"],
                ad_group_resource_name="customers/123/adGroups/111",
                campaign_resource_name="customers/123/campaigns/789",
            )

        self.assertIn("exactly one", str(ctx.exception))

    def test_add_negative_keywords_neither_raises(self):
        from fastmcp.exceptions import ToolError

        with self.assertRaises(ToolError) as ctx:
            mutations.add_negative_keywords(
                customer_id="123",
                keywords=["free"],
            )

        self.assertIn("exactly one", str(ctx.exception))

    @patch("ads_mcp.utils.get_googleads_service")
    @patch("ads_mcp.utils.get_googleads_client")
    def test_update_campaign_status_success(
        self, mock_get_client, mock_get_service
    ):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_get_client.return_value = MagicMock()
        mock_service.mutate_campaigns.return_value.results = [
            MagicMock(resource_name="customers/123/campaigns/789")
        ]

        result = mutations.update_campaign_status(
            customer_id="123",
            campaign_resource_name="customers/123/campaigns/789",
            status="ENABLED",
        )

        mock_get_service.assert_called_once_with("CampaignService")
        mock_service.mutate_campaigns.assert_called_once()
        self.assertEqual(result, "customers/123/campaigns/789")

    @patch("ads_mcp.utils.get_googleads_service")
    @patch("ads_mcp.utils.get_googleads_client")
    def test_create_responsive_search_ad_success(
        self, mock_get_client, mock_get_service
    ):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_get_client.return_value = MagicMock()
        mock_service.mutate_ad_group_ads.return_value.results = [
            MagicMock(resource_name="customers/123/adGroupAds/111~222")
        ]

        result = mutations.create_responsive_search_ad(
            customer_id="123",
            ad_group_resource_name="customers/123/adGroups/111",
            headlines=["Buy Now", "Best Price", "Free Shipping"],
            descriptions=["Shop today and save", "Fast delivery guaranteed"],
            final_urls=["https://example.com/shoes"],
        )

        mock_get_service.assert_called_once_with("AdGroupAdService")
        mock_service.mutate_ad_group_ads.assert_called_once()
        self.assertEqual(result, "customers/123/adGroupAds/111~222")
