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

"""Test cases for the Performance Max maintenance tools."""

import unittest
from unittest.mock import patch

from fastmcp.exceptions import ToolError

from ads_mcp.tools import pmax
from tests.tools import ads_write_utils

CAMPAIGN = "customers/123/campaigns/456"


class PmaxTestCase(unittest.TestCase):
    """Base case wiring a real proto client to a mocked service."""

    def setUp(self):
        self.client = ads_write_utils.real_client()
        self.services = {}
        client_patch = patch(
            "ads_mcp.utils.get_googleads_client", return_value=self.client
        )
        service_patch = patch(
            "ads_mcp.utils.get_googleads_service", side_effect=self._service
        )
        self.addCleanup(client_patch.stop)
        self.addCleanup(service_patch.stop)
        client_patch.start()
        service_patch.start()

    def _service(self, name):
        return self.services[name]

    def register(self, service_name, **results_by_method):
        self.services[service_name] = ads_write_utils.mock_service(
            **results_by_method
        )
        return self.services[service_name]


class TestUpdateAssetGroupStatus(PmaxTestCase):
    """Test cases for update_asset_group_status."""

    def test_pauses_every_group_in_one_call(self):
        service = self.register(
            "AssetGroupService",
            mutate_asset_groups=[
                "customers/123/assetGroups/1",
                "customers/123/assetGroups/2",
            ],
        )

        result = pmax.update_asset_group_status(
            customer_id="123",
            asset_group_resource_names=[
                "customers/123/assetGroups/1",
                "customers/123/assetGroups/2",
            ],
            status="PAUSED",
        )

        service.mutate_asset_groups.assert_called_once()
        request = ads_write_utils.sent_request(service, "mutate_asset_groups")
        self.assertEqual(len(request.operations), 2)
        first = request.operations[0]
        self.assertEqual(
            first.update.resource_name, "customers/123/assetGroups/1"
        )
        self.assertEqual(first.update.status.name, "PAUSED")
        self.assertEqual(list(first.update_mask.paths), ["status"])
        self.assertEqual(result["status"], "PAUSED")
        self.assertEqual(len(result["resource_names"]), 2)

    def test_invalid_status_lists_valid_values(self):
        with self.assertRaises(ToolError) as ctx:
            pmax.update_asset_group_status(
                customer_id="123",
                asset_group_resource_names=["customers/123/assetGroups/1"],
                status="SLEEPING",
            )

        message = str(ctx.exception)
        self.assertIn("SLEEPING", message)
        self.assertIn("PAUSED", message)

    def test_empty_list_raises(self):
        with self.assertRaises(ToolError):
            pmax.update_asset_group_status(
                customer_id="123",
                asset_group_resource_names=[],
                status="PAUSED",
            )

    def test_google_ads_exception_becomes_tool_error(self):
        service = self.register("AssetGroupService", mutate_asset_groups=[])
        service.mutate_asset_groups.side_effect = (
            ads_write_utils.google_ads_exception("Not found", "req-7")
        )

        with self.assertRaises(ToolError) as ctx:
            pmax.update_asset_group_status(
                customer_id="123",
                asset_group_resource_names=["customers/123/assetGroups/1"],
                status="PAUSED",
            )

        self.assertIn("Not found", str(ctx.exception))
        self.assertIn("req-7", str(ctx.exception))


class TestAssetGroupSignals(PmaxTestCase):
    """Test cases for add_asset_group_signals."""

    def test_adds_search_themes_and_audiences(self):
        service = self.register(
            "AssetGroupSignalService",
            mutate_asset_group_signals=[
                "customers/123/assetGroupSignals/1~1",
                "customers/123/assetGroupSignals/1~2",
            ],
        )

        pmax.add_asset_group_signals(
            customer_id="123",
            asset_group_resource_name="customers/123/assetGroups/1",
            search_themes=["crm for small business"],
            audience_resource_names=["customers/123/audiences/789"],
        )

        request = ads_write_utils.sent_request(
            service, "mutate_asset_group_signals"
        )
        self.assertEqual(len(request.operations), 2)
        theme_signal = request.operations[0].create
        self.assertEqual(
            theme_signal.asset_group, "customers/123/assetGroups/1"
        )
        self.assertEqual(
            theme_signal.search_theme.text, "crm for small business"
        )
        self.assertEqual(
            request.operations[1].create.audience.audience,
            "customers/123/audiences/789",
        )
        self.assertTrue(request.partial_failure)

    def test_no_signals_raises(self):
        with self.assertRaises(ToolError):
            pmax.add_asset_group_signals(
                customer_id="123",
                asset_group_resource_name="customers/123/assetGroups/1",
            )


class TestUpdateCampaignBidding(PmaxTestCase):
    """Test cases for update_campaign_bidding."""

    def setUp(self):
        super().setUp()
        self.service = self.register(
            "CampaignService", mutate_campaigns=[CAMPAIGN]
        )

    def _operation(self):
        request = ads_write_utils.sent_request(self.service, "mutate_campaigns")
        return request.operations[0]

    def test_maximize_conversion_value_with_target_roas(self):
        result = pmax.update_campaign_bidding(
            customer_id="123",
            campaign_resource_name=CAMPAIGN,
            strategy="MAXIMIZE_CONVERSION_VALUE",
            target_roas=4.0,
        )

        operation = self._operation()
        self.assertEqual(
            operation.update.maximize_conversion_value.target_roas, 4.0
        )
        self.assertEqual(
            list(operation.update_mask.paths),
            ["maximize_conversion_value.target_roas"],
        )
        self.assertEqual(result, CAMPAIGN)

    def test_strategy_without_target_masks_the_strategy_field(self):
        pmax.update_campaign_bidding(
            customer_id="123",
            campaign_resource_name=CAMPAIGN,
            strategy="MAXIMIZE_CONVERSIONS",
        )

        operation = self._operation()
        self.assertEqual(
            list(operation.update_mask.paths), ["maximize_conversions"]
        )
        # The strategy has to actually be present, or the update would clear
        # the campaign's bidding instead of switching it.
        update = operation.update
        self.assertTrue(
            type(update).pb(update).HasField("maximize_conversions")
        )

    def test_target_cpa_with_maximize_conversions(self):
        pmax.update_campaign_bidding(
            customer_id="123",
            campaign_resource_name=CAMPAIGN,
            strategy="MAXIMIZE_CONVERSIONS",
            target_cpa_micros=5_000_000,
        )

        operation = self._operation()
        self.assertEqual(
            operation.update.maximize_conversions.target_cpa_micros, 5_000_000
        )
        self.assertEqual(
            list(operation.update_mask.paths),
            ["maximize_conversions.target_cpa_micros"],
        )

    def test_target_not_supported_by_strategy_raises(self):
        with self.assertRaises(ToolError) as ctx:
            pmax.update_campaign_bidding(
                customer_id="123",
                campaign_resource_name=CAMPAIGN,
                strategy="MAXIMIZE_CONVERSION_VALUE",
                target_cpa_micros=5_000_000,
            )

        message = str(ctx.exception)
        self.assertIn("target_cpa_micros", message)
        self.assertIn("target_roas", message)

    def test_manual_cpc_accepts_no_target(self):
        with self.assertRaises(ToolError) as ctx:
            pmax.update_campaign_bidding(
                customer_id="123",
                campaign_resource_name=CAMPAIGN,
                strategy="MANUAL_CPC",
                target_roas=3.0,
            )

        self.assertIn("no target", str(ctx.exception))

    def test_unknown_strategy_raises(self):
        with self.assertRaises(ToolError) as ctx:
            pmax.update_campaign_bidding(
                customer_id="123",
                campaign_resource_name=CAMPAIGN,
                strategy="MAXIMIZE_VIBES",
            )

        self.assertIn("MAXIMIZE_VIBES", str(ctx.exception))

    def test_zero_target_roas_means_the_strategy_bids_without_a_target(self):
        pmax.update_campaign_bidding(
            customer_id="123",
            campaign_resource_name=CAMPAIGN,
            strategy="MAXIMIZE_CONVERSION_VALUE",
            target_roas=0,
        )

        # target_roas has no field presence, so a zero target leaves the
        # strategy submessage empty. The mask then names the strategy itself,
        # which is how Google Ads expresses 'this strategy, no target'.
        operation = self._operation()
        self.assertEqual(
            list(operation.update_mask.paths), ["maximize_conversion_value"]
        )
        update = operation.update
        self.assertTrue(
            type(update).pb(update).HasField("maximize_conversion_value")
        )


class TestUpdateCampaign(PmaxTestCase):
    """Test cases for update_campaign."""

    def setUp(self):
        super().setUp()
        self.service = self.register(
            "CampaignService", mutate_campaigns=[CAMPAIGN]
        )

    def test_updates_only_provided_fields(self):
        pmax.update_campaign(
            customer_id="123",
            campaign_resource_name=CAMPAIGN,
            name="Renamed",
            campaign_budget_resource_name="customers/123/campaignBudgets/789",
        )

        request = ads_write_utils.sent_request(self.service, "mutate_campaigns")
        operation = request.operations[0]
        self.assertEqual(operation.update.name, "Renamed")
        self.assertEqual(
            operation.update.campaign_budget,
            "customers/123/campaignBudgets/789",
        )
        self.assertEqual(
            sorted(operation.update_mask.paths), ["campaign_budget", "name"]
        )

    def test_validate_only_reports_that_nothing_was_written(self):
        # A validate-only mutate returns no results, which must not be read
        # as a missing resource name.
        self.register("CampaignService", mutate_campaigns=[])

        result = pmax.update_campaign(
            customer_id="123",
            campaign_resource_name=CAMPAIGN,
            name="Renamed",
            validate_only=True,
        )

        self.assertIn("VALIDATE_ONLY", result)

    def test_no_fields_raises(self):
        with self.assertRaises(ToolError) as ctx:
            pmax.update_campaign(
                customer_id="123", campaign_resource_name=CAMPAIGN
            )

        self.assertIn("No fields to update", str(ctx.exception))


class TestUpdateCampaignBudget(PmaxTestCase):
    """Test cases for update_campaign_budget."""

    def setUp(self):
        super().setUp()
        self.budget = "customers/123/campaignBudgets/456"
        self.service = self.register(
            "CampaignBudgetService", mutate_campaign_budgets=[self.budget]
        )

    def test_updates_amount(self):
        result = pmax.update_campaign_budget(
            customer_id="123",
            campaign_budget_resource_name=self.budget,
            amount_micros=8_000_000,
        )

        request = ads_write_utils.sent_request(
            self.service, "mutate_campaign_budgets"
        )
        operation = request.operations[0]
        self.assertEqual(operation.update.amount_micros, 8_000_000)
        self.assertEqual(list(operation.update_mask.paths), ["amount_micros"])
        self.assertEqual(result, self.budget)

    def test_explicitly_shared_false_is_kept_in_the_mask(self):
        pmax.update_campaign_budget(
            customer_id="123",
            campaign_budget_resource_name=self.budget,
            explicitly_shared=False,
        )

        request = ads_write_utils.sent_request(
            self.service, "mutate_campaign_budgets"
        )
        self.assertEqual(
            list(request.operations[0].update_mask.paths),
            ["explicitly_shared"],
        )

    def test_invalid_delivery_method_raises(self):
        with self.assertRaises(ToolError):
            pmax.update_campaign_budget(
                customer_id="123",
                campaign_budget_resource_name=self.budget,
                delivery_method="TURBO",
            )

    def test_no_fields_raises(self):
        with self.assertRaises(ToolError):
            pmax.update_campaign_budget(
                customer_id="123", campaign_budget_resource_name=self.budget
            )


if __name__ == "__main__":
    unittest.main()
