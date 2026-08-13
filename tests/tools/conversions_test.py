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

"""Test cases for the conversion import and adjustment tools."""

import unittest
from unittest.mock import MagicMock, patch

from fastmcp.exceptions import ToolError

from ads_mcp.tools import conversions
from tests.tools import ads_write_utils

ACTION = "customers/123/conversionActions/456"


class ConversionsTestCase(unittest.TestCase):
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

    def register_upload(self, service_name, method):
        service = MagicMock()
        response = MagicMock()
        response.partial_failure_error = None
        getattr(service, method).return_value = response
        self.services[service_name] = service
        return service


class TestUploadOfflineConversions(ConversionsTestCase):
    """Test cases for upload_offline_conversions."""

    def setUp(self):
        super().setUp()
        self.service = self.register_upload(
            "ConversionUploadService", "upload_click_conversions"
        )

    def _request(self):
        return ads_write_utils.sent_request(
            self.service, "upload_click_conversions"
        )

    def test_builds_click_conversion_with_value_and_order_id(self):
        result = conversions.upload_offline_conversions(
            customer_id="123",
            conversions=[
                {
                    "conversion_action": ACTION,
                    "gclid": "Cj0KCQ",
                    "conversion_date_time": "2026-08-13 14:05:00+03:00",
                    "conversion_value": 12500,
                    "currency_code": "UAH",
                    "order_id": "SO-10432",
                }
            ],
        )

        conversion = self._request().conversions[0]
        self.assertEqual(conversion.gclid, "Cj0KCQ")
        self.assertEqual(conversion.conversion_action, ACTION)
        self.assertEqual(
            conversion.conversion_date_time, "2026-08-13 14:05:00+03:00"
        )
        self.assertEqual(conversion.conversion_value, 12500)
        self.assertEqual(conversion.currency_code, "UAH")
        self.assertEqual(conversion.order_id, "SO-10432")
        self.assertEqual(result["submitted"], 1)
        self.assertEqual(result["accepted"], 1)

    def test_partial_failure_is_always_enabled(self):
        conversions.upload_offline_conversions(
            customer_id="123",
            conversions=[
                {
                    "conversion_action": ACTION,
                    "gclid": "Cj0KCQ",
                    "conversion_date_time": "2026-08-13 14:05:00+03:00",
                }
            ],
        )

        self.assertTrue(self._request().partial_failure)

    def test_bare_conversion_action_id_is_expanded(self):
        conversions.upload_offline_conversions(
            customer_id="123",
            conversions=[
                {
                    "conversion_action": "456",
                    "wbraid": "Cj0abc",
                    "conversion_date_time": "2026-08-13 14:05:00+03:00",
                }
            ],
        )

        self.assertEqual(
            self._request().conversions[0].conversion_action, ACTION
        )

    def test_custom_variables_are_attached(self):
        conversions.upload_offline_conversions(
            customer_id="123",
            conversions=[
                {
                    "conversion_action": ACTION,
                    "gclid": "Cj0KCQ",
                    "conversion_date_time": "2026-08-13 14:05:00+03:00",
                    "custom_variables": [
                        {
                            "conversion_custom_variable": "customers/123/conversionCustomVariables/7",
                            "value": "qualified",
                        }
                    ],
                }
            ],
        )

        variable = self._request().conversions[0].custom_variables[0]
        self.assertEqual(
            variable.conversion_custom_variable,
            "customers/123/conversionCustomVariables/7",
        )
        self.assertEqual(variable.value, "qualified")

    def test_two_click_identifiers_raises(self):
        with self.assertRaises(ToolError) as ctx:
            conversions.upload_offline_conversions(
                customer_id="123",
                conversions=[
                    {
                        "conversion_action": ACTION,
                        "gclid": "Cj0KCQ",
                        "gbraid": "Cj0abc",
                        "conversion_date_time": "2026-08-13 14:05:00+03:00",
                    }
                ],
            )

        self.assertIn("exactly one", str(ctx.exception))

    def test_missing_click_identifier_raises(self):
        with self.assertRaises(ToolError):
            conversions.upload_offline_conversions(
                customer_id="123",
                conversions=[
                    {
                        "conversion_action": ACTION,
                        "conversion_date_time": "2026-08-13 14:05:00+03:00",
                    }
                ],
            )

    def test_value_without_currency_raises(self):
        with self.assertRaises(ToolError) as ctx:
            conversions.upload_offline_conversions(
                customer_id="123",
                conversions=[
                    {
                        "conversion_action": ACTION,
                        "gclid": "Cj0KCQ",
                        "conversion_date_time": "2026-08-13 14:05:00+03:00",
                        "conversion_value": 100,
                    }
                ],
            )

        self.assertIn("currency_code", str(ctx.exception))

    def test_missing_conversion_date_time_raises(self):
        with self.assertRaises(ToolError) as ctx:
            conversions.upload_offline_conversions(
                customer_id="123",
                conversions=[{"conversion_action": ACTION, "gclid": "Cj0KCQ"}],
            )

        self.assertIn("conversion_date_time", str(ctx.exception))

    def test_invalid_conversion_action_raises(self):
        with self.assertRaises(ToolError) as ctx:
            conversions.upload_offline_conversions(
                customer_id="123",
                conversions=[
                    {
                        "conversion_action": "not-an-id",
                        "gclid": "Cj0KCQ",
                        "conversion_date_time": "2026-08-13 14:05:00+03:00",
                    }
                ],
            )

        self.assertIn("conversion_action", str(ctx.exception))

    def test_empty_list_raises(self):
        with self.assertRaises(ToolError):
            conversions.upload_offline_conversions(
                customer_id="123", conversions=[]
            )


class TestUploadConversionAdjustments(ConversionsTestCase):
    """Test cases for upload_conversion_adjustments."""

    def setUp(self):
        super().setUp()
        self.service = self.register_upload(
            "ConversionAdjustmentUploadService", "upload_conversion_adjustments"
        )

    def _request(self):
        return ads_write_utils.sent_request(
            self.service, "upload_conversion_adjustments"
        )

    def test_retraction_by_gclid_pair(self):
        conversions.upload_conversion_adjustments(
            customer_id="123",
            adjustments=[
                {
                    "conversion_action": ACTION,
                    "adjustment_type": "RETRACTION",
                    "gclid": "Cj0KCQ",
                    "conversion_date_time": "2026-08-01 09:12:00+03:00",
                    "adjustment_date_time": "2026-08-13 10:00:00+03:00",
                }
            ],
        )

        adjustment = self._request().conversion_adjustments[0]
        self.assertEqual(adjustment.adjustment_type.name, "RETRACTION")
        self.assertEqual(adjustment.gclid_date_time_pair.gclid, "Cj0KCQ")
        self.assertEqual(
            adjustment.gclid_date_time_pair.conversion_date_time,
            "2026-08-01 09:12:00+03:00",
        )
        self.assertEqual(
            adjustment.adjustment_date_time, "2026-08-13 10:00:00+03:00"
        )

    def test_restatement_by_order_id_sets_value(self):
        conversions.upload_conversion_adjustments(
            customer_id="123",
            adjustments=[
                {
                    "conversion_action": ACTION,
                    "adjustment_type": "RESTATEMENT",
                    "order_id": "SO-10432",
                    "adjustment_date_time": "2026-08-13 10:00:00+03:00",
                    "adjusted_value": 8000,
                    "currency_code": "UAH",
                }
            ],
        )

        adjustment = self._request().conversion_adjustments[0]
        self.assertEqual(adjustment.order_id, "SO-10432")
        self.assertEqual(adjustment.restatement_value.adjusted_value, 8000)
        self.assertEqual(adjustment.restatement_value.currency_code, "UAH")

    def test_restatement_without_value_raises(self):
        with self.assertRaises(ToolError) as ctx:
            conversions.upload_conversion_adjustments(
                customer_id="123",
                adjustments=[
                    {
                        "conversion_action": ACTION,
                        "adjustment_type": "RESTATEMENT",
                        "order_id": "SO-1",
                        "adjustment_date_time": "2026-08-13 10:00:00+03:00",
                    }
                ],
            )

        self.assertIn("adjusted_value", str(ctx.exception))

    def test_retraction_with_value_raises(self):
        with self.assertRaises(ToolError) as ctx:
            conversions.upload_conversion_adjustments(
                customer_id="123",
                adjustments=[
                    {
                        "conversion_action": ACTION,
                        "adjustment_type": "RETRACTION",
                        "order_id": "SO-1",
                        "adjustment_date_time": "2026-08-13 10:00:00+03:00",
                        "adjusted_value": 100,
                    }
                ],
            )

        self.assertIn("RESTATEMENT", str(ctx.exception))

    def test_both_identifiers_raises(self):
        with self.assertRaises(ToolError) as ctx:
            conversions.upload_conversion_adjustments(
                customer_id="123",
                adjustments=[
                    {
                        "conversion_action": ACTION,
                        "adjustment_type": "RETRACTION",
                        "order_id": "SO-1",
                        "gclid": "Cj0KCQ",
                        "conversion_date_time": "2026-08-01 09:12:00+03:00",
                        "adjustment_date_time": "2026-08-13 10:00:00+03:00",
                    }
                ],
            )

        self.assertIn("not both", str(ctx.exception))

    def test_no_identifier_raises(self):
        with self.assertRaises(ToolError):
            conversions.upload_conversion_adjustments(
                customer_id="123",
                adjustments=[
                    {
                        "conversion_action": ACTION,
                        "adjustment_type": "RETRACTION",
                        "adjustment_date_time": "2026-08-13 10:00:00+03:00",
                    }
                ],
            )

    def test_unknown_adjustment_type_raises(self):
        with self.assertRaises(ToolError):
            conversions.upload_conversion_adjustments(
                customer_id="123",
                adjustments=[
                    {
                        "conversion_action": ACTION,
                        "adjustment_type": "CANCELLATION",
                        "order_id": "SO-1",
                        "adjustment_date_time": "2026-08-13 10:00:00+03:00",
                    }
                ],
            )


class TestConversionActions(ConversionsTestCase):
    """Test cases for conversion action management."""

    def setUp(self):
        super().setUp()
        self.service = self.services.setdefault(
            "ConversionActionService",
            ads_write_utils.mock_service(mutate_conversion_actions=[ACTION]),
        )

    def _request(self):
        return ads_write_utils.sent_request(
            self.service, "mutate_conversion_actions"
        )

    def test_create_defaults_to_upload_clicks(self):
        result = conversions.create_conversion_action(
            customer_id="123", name="Odoo qualified lead"
        )

        action = self._request().operations[0].create
        self.assertEqual(action.name, "Odoo qualified lead")
        self.assertEqual(action.type_.name, "UPLOAD_CLICKS")
        self.assertEqual(action.status.name, "ENABLED")
        self.assertTrue(action.primary_for_goal)
        self.assertEqual(result, ACTION)

    def test_create_sets_value_settings_and_lookback(self):
        conversions.create_conversion_action(
            customer_id="123",
            name="Closed won",
            category="PURCHASE",
            default_value=1000,
            default_currency_code="UAH",
            always_use_default_value=True,
            click_through_lookback_window_days=90,
        )

        action = self._request().operations[0].create
        self.assertEqual(action.category.name, "PURCHASE")
        self.assertEqual(action.value_settings.default_value, 1000)
        self.assertEqual(action.value_settings.default_currency_code, "UAH")
        self.assertTrue(action.value_settings.always_use_default_value)
        self.assertEqual(action.click_through_lookback_window_days, 90)

    def test_create_with_invalid_category_raises(self):
        with self.assertRaises(ToolError):
            conversions.create_conversion_action(
                customer_id="123", name="x", category="SOMETHING"
            )

    def test_update_masks_only_provided_fields(self):
        conversions.update_conversion_action(
            customer_id="123",
            conversion_action_resource_name=ACTION,
            primary_for_goal=False,
            click_through_lookback_window_days=60,
        )

        operation = self._request().operations[0]
        self.assertEqual(
            sorted(operation.update_mask.paths),
            ["click_through_lookback_window_days", "primary_for_goal"],
        )
        self.assertFalse(operation.update.primary_for_goal)

    def test_update_nested_value_setting_uses_leaf_path(self):
        conversions.update_conversion_action(
            customer_id="123",
            conversion_action_resource_name=ACTION,
            default_value=2500,
        )

        operation = self._request().operations[0]
        self.assertEqual(
            list(operation.update_mask.paths), ["value_settings.default_value"]
        )

    def test_update_without_fields_raises(self):
        with self.assertRaises(ToolError) as ctx:
            conversions.update_conversion_action(
                customer_id="123", conversion_action_resource_name=ACTION
            )

        self.assertIn("No fields to update", str(ctx.exception))

    def test_create_validate_only_reports_that_nothing_was_written(self):
        # A validate-only mutate returns no results, which must not be read
        # as a missing resource name.
        self.services["ConversionActionService"] = ads_write_utils.mock_service(
            mutate_conversion_actions=[]
        )

        result = conversions.create_conversion_action(
            customer_id="123", name="Dry run", validate_only=True
        )

        self.assertIn("VALIDATE_ONLY", result)


if __name__ == "__main__":
    unittest.main()
