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

"""Test cases for the universal mutate tool."""

import unittest
from unittest.mock import MagicMock, patch

from fastmcp.exceptions import ToolError
from google.protobuf.any_pb2 import Any as AnyProto
from google.rpc import status_pb2

from ads_mcp.tools import mutate
from tests.tools import ads_write_utils


def _mutate_response(client, resource_names, partial_failure_error=None):
    """Builds a MutateGoogleAdsResponse-shaped mock."""
    response = MagicMock()
    items = []
    for name in resource_names:
        item = client.get_type("MutateOperationResponse")
        item.campaign_result.resource_name = name
        items.append(item)
    response.mutate_operation_responses = items
    response.partial_failure_error = partial_failure_error
    return response


class TestMutateGoogleAds(unittest.TestCase):
    """Test cases for mutate_google_ads."""

    def setUp(self):
        self.client = ads_write_utils.real_client()
        self.service = MagicMock()
        self.service.mutate.return_value = _mutate_response(
            self.client, ["customers/123/campaigns/456"]
        )
        client_patch = patch(
            "ads_mcp.utils.get_googleads_client", return_value=self.client
        )
        service_patch = patch(
            "ads_mcp.utils.get_googleads_service", return_value=self.service
        )
        self.addCleanup(client_patch.stop)
        self.addCleanup(service_patch.stop)
        client_patch.start()
        service_patch.start()

    def _sent_request(self):
        return self.service.mutate.call_args.kwargs["request"]

    def test_builds_create_operation_from_dict(self):
        mutate.mutate_google_ads(
            customer_id="123",
            operations=[
                {
                    "campaign_criterion_operation": {
                        "create": {
                            "campaign": "customers/123/campaigns/456",
                            "negative": True,
                            "keyword": {"text": "free", "match_type": "PHRASE"},
                        }
                    }
                }
            ],
        )

        criterion = (
            self._sent_request()
            .mutate_operations[0]
            .campaign_criterion_operation.create
        )
        self.assertEqual(criterion.campaign, "customers/123/campaigns/456")
        self.assertTrue(criterion.negative)
        self.assertEqual(criterion.keyword.text, "free")
        self.assertEqual(criterion.keyword.match_type.name, "PHRASE")

    def test_derives_update_mask_from_fields_set(self):
        mutate.mutate_google_ads(
            customer_id="123",
            operations=[
                {
                    "campaign_operation": {
                        "update": {
                            "resource_name": "customers/123/campaigns/456",
                            "name": "Renamed",
                            "maximize_conversion_value": {"target_roas": 4.0},
                        }
                    }
                }
            ],
        )

        operation = self._sent_request().mutate_operations[0].campaign_operation
        self.assertEqual(
            sorted(operation.update_mask.paths),
            ["maximize_conversion_value.target_roas", "name"],
        )

    def test_explicit_update_mask_is_preserved(self):
        mutate.mutate_google_ads(
            customer_id="123",
            operations=[
                {
                    "campaign_operation": {
                        "update": {
                            "resource_name": "customers/123/campaigns/456",
                            "name": "Renamed",
                        },
                        "update_mask": {"paths": ["name"]},
                    }
                }
            ],
        )

        operation = self._sent_request().mutate_operations[0].campaign_operation
        self.assertEqual(list(operation.update_mask.paths), ["name"])

    def test_remove_operation_takes_resource_name(self):
        mutate.mutate_google_ads(
            customer_id="123",
            operations=[
                {
                    "campaign_criterion_operation": {
                        "remove": "customers/123/campaignCriteria/456~789"
                    }
                }
            ],
        )

        operation = self._sent_request().mutate_operations[0]
        self.assertEqual(
            operation.campaign_criterion_operation.remove,
            "customers/123/campaignCriteria/456~789",
        )

    def test_validate_only_is_forwarded_and_reports_nothing_applied(self):
        result = mutate.mutate_google_ads(
            customer_id="123",
            operations=[
                {"campaign_operation": {"remove": "customers/123/campaigns/4"}}
            ],
            validate_only=True,
        )

        self.assertTrue(self._sent_request().validate_only)
        self.assertTrue(result["validate_only"])
        self.assertEqual(result["applied"], 0)

    def test_unknown_field_raises_with_index(self):
        with self.assertRaises(ToolError) as ctx:
            mutate.mutate_google_ads(
                customer_id="123",
                operations=[
                    {"campaign_operation": {"create": {"nmae": "typo"}}}
                ],
            )

        self.assertIn("operations[0]", str(ctx.exception))
        self.assertIn("nmae", str(ctx.exception))

    def test_unknown_enum_value_raises(self):
        with self.assertRaises(ToolError) as ctx:
            mutate.mutate_google_ads(
                customer_id="123",
                operations=[
                    {"campaign_operation": {"create": {"status": "SLEEPING"}}}
                ],
            )

        self.assertIn("unknown enum value", str(ctx.exception))

    def test_operation_with_multiple_keys_raises(self):
        with self.assertRaises(ToolError) as ctx:
            mutate.mutate_google_ads(
                customer_id="123",
                operations=[
                    {
                        "campaign_operation": {
                            "remove": "customers/1/campaigns/2"
                        },
                        "ad_group_operation": {
                            "remove": "customers/1/adGroups/3"
                        },
                    }
                ],
            )

        self.assertIn("exactly one", str(ctx.exception))

    def test_update_without_fields_raises(self):
        with self.assertRaises(ToolError) as ctx:
            mutate.mutate_google_ads(
                customer_id="123",
                operations=[
                    {
                        "campaign_operation": {
                            "update": {
                                "resource_name": "customers/123/campaigns/456"
                            }
                        }
                    }
                ],
            )

        self.assertIn("would do nothing", str(ctx.exception))

    def test_empty_operations_raises(self):
        with self.assertRaises(ToolError):
            mutate.mutate_google_ads(customer_id="123", operations=[])

    def test_validate_only_with_partial_failure_raises(self):
        with self.assertRaises(ToolError) as ctx:
            mutate.mutate_google_ads(
                customer_id="123",
                operations=[
                    {
                        "campaign_operation": {
                            "remove": "customers/1/campaigns/2"
                        }
                    }
                ],
                validate_only=True,
                partial_failure=True,
            )

        self.assertIn("cannot be combined", str(ctx.exception))

    def test_google_ads_exception_becomes_tool_error(self):
        self.service.mutate.side_effect = ads_write_utils.google_ads_exception(
            "Budget not found", "req-42"
        )

        with self.assertRaises(ToolError) as ctx:
            mutate.mutate_google_ads(
                customer_id="123",
                operations=[
                    {
                        "campaign_operation": {
                            "remove": "customers/1/campaigns/2"
                        }
                    }
                ],
            )

        self.assertIn("Budget not found", str(ctx.exception))
        self.assertIn("req-42", str(ctx.exception))

    def test_partial_failure_errors_are_decoded_with_row_index(self):
        failure_cls = type(self.client.get_type("GoogleAdsFailure"))
        failure = failure_cls(
            {
                "errors": [
                    {
                        "message": "Placement url is invalid.",
                        "location": {
                            "field_path_elements": [
                                {"field_name": "operations", "index": 1}
                            ]
                        },
                    }
                ]
            }
        )
        detail = AnyProto()
        detail.Pack(failure_cls.pb(failure))
        status = status_pb2.Status(
            code=3, message="partial failure", details=[detail]
        )
        self.service.mutate.return_value = _mutate_response(
            self.client,
            ["customers/123/campaigns/456", "customers/123/campaigns/789"],
            partial_failure_error=status,
        )

        result = mutate.mutate_google_ads(
            customer_id="123",
            operations=[
                {"campaign_operation": {"remove": "customers/1/campaigns/2"}},
                {"campaign_operation": {"remove": "customers/1/campaigns/3"}},
            ],
            partial_failure=True,
        )

        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["index"], 1)
        self.assertIn("Placement url", result["errors"][0]["message"])
        self.assertEqual(result["applied"], 1)


if __name__ == "__main__":
    unittest.main()
