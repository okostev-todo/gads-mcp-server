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

"""Test cases for the exclusion tools."""

import unittest
from unittest.mock import patch

from fastmcp.exceptions import ToolError

from ads_mcp.tools import exclusions
from tests.tools import ads_write_utils


class ExclusionsTestCase(unittest.TestCase):
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


class TestAccountLevelExclusions(ExclusionsTestCase):
    """Test cases for add_account_level_exclusions."""

    def test_builds_one_operation_per_entity(self):
        service = self.register(
            "CustomerNegativeCriterionService",
            mutate_customer_negative_criteria=[
                "customers/123/customerNegativeCriteria/1",
                "customers/123/customerNegativeCriteria/2",
                "customers/123/customerNegativeCriteria/3",
            ],
        )

        result = exclusions.add_account_level_exclusions(
            customer_id="123",
            placements=["badsite.example"],
            youtube_videos=["abc123"],
            content_labels=["TRAGEDY"],
        )

        request = ads_write_utils.sent_request(
            service, "mutate_customer_negative_criteria"
        )
        self.assertEqual(len(request.operations), 3)
        self.assertEqual(
            request.operations[0].create.placement.url, "badsite.example"
        )
        self.assertEqual(
            request.operations[1].create.youtube_video.video_id, "abc123"
        )
        self.assertEqual(
            request.operations[2].create.content_label.type_.name, "TRAGEDY"
        )
        self.assertTrue(request.partial_failure)
        self.assertEqual(len(result["resource_names"]), 3)

    def test_mobile_app_uses_app_id(self):
        service = self.register(
            "CustomerNegativeCriterionService",
            mutate_customer_negative_criteria=[
                "customers/123/customerNegativeCriteria/9"
            ],
        )

        exclusions.add_account_level_exclusions(
            customer_id="123", mobile_apps=["1-com.example.app"]
        )

        request = ads_write_utils.sent_request(
            service, "mutate_customer_negative_criteria"
        )
        self.assertEqual(
            request.operations[0].create.mobile_application.app_id,
            "1-com.example.app",
        )

    def test_no_entities_raises(self):
        with self.assertRaises(ToolError) as ctx:
            exclusions.add_account_level_exclusions(customer_id="123")

        self.assertIn("at least one", str(ctx.exception))

    def test_invalid_content_label_lists_valid_values(self):
        with self.assertRaises(ToolError) as ctx:
            exclusions.add_account_level_exclusions(
                customer_id="123", content_labels=["NOT_A_LABEL"]
            )

        message = str(ctx.exception)
        self.assertIn("NOT_A_LABEL", message)
        self.assertIn("TRAGEDY", message)

    def test_validate_only_disables_partial_failure(self):
        service = self.register(
            "CustomerNegativeCriterionService",
            mutate_customer_negative_criteria=[],
        )

        exclusions.add_account_level_exclusions(
            customer_id="123",
            placements=["badsite.example"],
            validate_only=True,
        )

        request = ads_write_utils.sent_request(
            service, "mutate_customer_negative_criteria"
        )
        self.assertTrue(request.validate_only)
        self.assertFalse(request.partial_failure)


class TestCampaignExclusions(ExclusionsTestCase):
    """Test cases for add_campaign_exclusions."""

    def test_criteria_are_negative_and_scoped_to_campaign(self):
        service = self.register(
            "CampaignCriterionService",
            mutate_campaign_criteria=["customers/123/campaignCriteria/456~1"],
        )

        exclusions.add_campaign_exclusions(
            customer_id="123",
            campaign_resource_name="customers/123/campaigns/456",
            youtube_channels=["UCxyz"],
        )

        request = ads_write_utils.sent_request(
            service, "mutate_campaign_criteria"
        )
        criterion = request.operations[0].create
        self.assertEqual(criterion.campaign, "customers/123/campaigns/456")
        self.assertTrue(criterion.negative)
        self.assertEqual(criterion.youtube_channel.channel_id, "UCxyz")

    def test_no_entities_raises(self):
        with self.assertRaises(ToolError):
            exclusions.add_campaign_exclusions(
                customer_id="123",
                campaign_resource_name="customers/123/campaigns/456",
            )


class TestSharedSets(ExclusionsTestCase):
    """Test cases for the shared exclusion list workflow."""

    def test_create_returns_resource_name_and_sets_type(self):
        service = self.register(
            "SharedSetService",
            mutate_shared_sets=["customers/123/sharedSets/456"],
        )

        result = exclusions.create_shared_exclusion_list(
            customer_id="123",
            name="Global negatives",
            list_type="NEGATIVE_PLACEMENTS",
        )

        request = ads_write_utils.sent_request(service, "mutate_shared_sets")
        self.assertEqual(request.operations[0].create.name, "Global negatives")
        self.assertEqual(
            request.operations[0].create.type_.name, "NEGATIVE_PLACEMENTS"
        )
        self.assertEqual(result, "customers/123/sharedSets/456")

    def test_invalid_list_type_raises(self):
        with self.assertRaises(ToolError):
            exclusions.create_shared_exclusion_list(
                customer_id="123", name="x", list_type="NEGATIVE_EVERYTHING"
            )

    def test_add_criteria_handles_keywords_and_placements(self):
        service = self.register(
            "SharedCriterionService",
            mutate_shared_criteria=[
                "customers/123/sharedCriteria/456~1",
                "customers/123/sharedCriteria/456~2",
            ],
        )

        exclusions.add_criteria_to_shared_set(
            customer_id="123",
            shared_set_resource_name="customers/123/sharedSets/456",
            keywords=["free"],
            match_type="EXACT",
            placements=["spam.example"],
        )

        request = ads_write_utils.sent_request(
            service, "mutate_shared_criteria"
        )
        self.assertEqual(len(request.operations), 2)
        keyword_criterion = request.operations[0].create
        self.assertEqual(
            keyword_criterion.shared_set, "customers/123/sharedSets/456"
        )
        self.assertEqual(keyword_criterion.keyword.text, "free")
        self.assertEqual(keyword_criterion.keyword.match_type.name, "EXACT")
        self.assertEqual(
            request.operations[1].create.placement.url, "spam.example"
        )

    def test_add_criteria_without_content_raises(self):
        with self.assertRaises(ToolError):
            exclusions.add_criteria_to_shared_set(
                customer_id="123",
                shared_set_resource_name="customers/123/sharedSets/456",
            )

    def test_create_validate_only_reports_that_nothing_was_written(self):
        # A validate-only mutate returns no results, which must not be read
        # as a missing resource name.
        self.register("SharedSetService", mutate_shared_sets=[])

        result = exclusions.create_shared_exclusion_list(
            customer_id="123", name="Dry run", validate_only=True
        )

        self.assertIn("VALIDATE_ONLY", result)

    def test_attach_links_every_campaign(self):
        service = self.register(
            "CampaignSharedSetService",
            mutate_campaign_shared_sets=[
                "customers/123/campaignSharedSets/1~456",
                "customers/123/campaignSharedSets/2~456",
            ],
        )

        exclusions.attach_shared_set_to_campaigns(
            customer_id="123",
            shared_set_resource_name="customers/123/sharedSets/456",
            campaign_resource_names=[
                "customers/123/campaigns/1",
                "customers/123/campaigns/2",
            ],
        )

        request = ads_write_utils.sent_request(
            service, "mutate_campaign_shared_sets"
        )
        self.assertEqual(len(request.operations), 2)
        self.assertEqual(
            request.operations[0].create.shared_set,
            "customers/123/sharedSets/456",
        )
        self.assertEqual(
            request.operations[1].create.campaign, "customers/123/campaigns/2"
        )

    def test_attach_without_campaigns_raises(self):
        with self.assertRaises(ToolError):
            exclusions.attach_shared_set_to_campaigns(
                customer_id="123",
                shared_set_resource_name="customers/123/sharedSets/456",
                campaign_resource_names=[],
            )


class TestRemoveCriteria(ExclusionsTestCase):
    """Test cases for remove_criteria."""

    def test_routes_each_resource_type_to_its_service(self):
        campaign_service = self.register(
            "CampaignCriterionService",
            mutate_campaign_criteria=["customers/123/campaignCriteria/456~1"],
        )
        account_service = self.register(
            "CustomerNegativeCriterionService",
            mutate_customer_negative_criteria=[
                "customers/123/customerNegativeCriteria/9"
            ],
        )

        result = exclusions.remove_criteria(
            customer_id="123",
            resource_names=[
                "customers/123/campaignCriteria/456~1",
                "customers/123/customerNegativeCriteria/9",
            ],
        )

        campaign_request = ads_write_utils.sent_request(
            campaign_service, "mutate_campaign_criteria"
        )
        self.assertEqual(
            campaign_request.operations[0].remove,
            "customers/123/campaignCriteria/456~1",
        )
        account_request = ads_write_utils.sent_request(
            account_service, "mutate_customer_negative_criteria"
        )
        self.assertEqual(
            account_request.operations[0].remove,
            "customers/123/customerNegativeCriteria/9",
        )
        self.assertEqual(
            sorted(result["removed"]),
            ["campaignCriteria", "customerNegativeCriteria"],
        )

    def test_batches_same_type_into_one_call(self):
        service = self.register(
            "AssetGroupSignalService",
            mutate_asset_group_signals=[
                "customers/123/assetGroupSignals/1~2",
                "customers/123/assetGroupSignals/1~3",
            ],
        )

        exclusions.remove_criteria(
            customer_id="123",
            resource_names=[
                "customers/123/assetGroupSignals/1~2",
                "customers/123/assetGroupSignals/1~3",
            ],
        )

        service.mutate_asset_group_signals.assert_called_once()
        request = ads_write_utils.sent_request(
            service, "mutate_asset_group_signals"
        )
        self.assertEqual(len(request.operations), 2)

    def test_unsupported_resource_type_raises(self):
        with self.assertRaises(ToolError) as ctx:
            exclusions.remove_criteria(
                customer_id="123",
                resource_names=["customers/123/campaigns/456"],
            )

        message = str(ctx.exception)
        self.assertIn("campaigns", message)
        self.assertIn("mutate_google_ads", message)

    def test_empty_list_raises(self):
        with self.assertRaises(ToolError):
            exclusions.remove_criteria(customer_id="123", resource_names=[])


if __name__ == "__main__":
    unittest.main()
