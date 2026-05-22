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

"""Test cases for the search_console tools."""

import unittest
from unittest.mock import MagicMock, patch

from ads_mcp.tools import search_console


class TestSearchConsole(unittest.TestCase):

    @patch("ads_mcp.utils.get_gsc_service")
    def test_list_gsc_sites_returns_entries(self, mock_get_service):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_service.sites().list().execute.return_value = {
            "siteEntry": [
                {"siteUrl": "sc-domain:example.com", "permissionLevel": "siteOwner"}
            ]
        }

        results = search_console.list_gsc_sites()

        mock_service.sites().list().execute.assert_called_once()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["siteUrl"], "sc-domain:example.com")

    @patch("ads_mcp.utils.get_gsc_service")
    def test_list_gsc_sites_empty(self, mock_get_service):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_service.sites().list().execute.return_value = {}

        results = search_console.list_gsc_sites()

        self.assertEqual(results, [])

    @patch("ads_mcp.utils.get_gsc_service")
    def test_query_search_analytics_default_dimensions(self, mock_get_service):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_service.searchanalytics().query().execute.return_value = {
            "rows": [
                {
                    "keys": ["running shoes"],
                    "clicks": 120,
                    "impressions": 3000,
                    "ctr": 0.04,
                    "position": 5.2,
                }
            ]
        }

        results = search_console.query_search_analytics(
            site_url="sc-domain:example.com",
            start_date="2026-01-01",
            end_date="2026-05-01",
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["keys"], ["running shoes"])
        self.assertEqual(results[0]["clicks"], 120)

        # Verify default dimension is 'query'
        call_kwargs = mock_service.searchanalytics().query.call_args
        body = call_kwargs[1]["body"]
        self.assertEqual(body["dimensions"], ["query"])

    @patch("ads_mcp.utils.get_gsc_service")
    def test_query_search_analytics_custom_dimensions(self, mock_get_service):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_service.searchanalytics().query().execute.return_value = {"rows": []}

        search_console.query_search_analytics(
            site_url="sc-domain:example.com",
            start_date="2026-01-01",
            end_date="2026-05-01",
            dimensions=["page", "date"],
            row_limit=500,
        )

        call_kwargs = mock_service.searchanalytics().query.call_args
        body = call_kwargs[1]["body"]
        self.assertEqual(body["dimensions"], ["page", "date"])
        self.assertEqual(body["rowLimit"], 500)

    @patch("ads_mcp.utils.get_gsc_service")
    def test_inspect_url_returns_result(self, mock_get_service):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        expected = {
            "inspectionResultLink": "https://search.google.com/...",
            "indexStatusResult": {"coverageState": "Submitted and indexed"},
        }
        mock_service.urlInspection().index().inspect().execute.return_value = expected

        result = search_console.inspect_url(
            site_url="sc-domain:example.com",
            inspection_url="https://example.com/page",
        )

        self.assertEqual(result["indexStatusResult"]["coverageState"], "Submitted and indexed")

        call_kwargs = mock_service.urlInspection().index().inspect.call_args
        body = call_kwargs[1]["body"]
        self.assertEqual(body["inspectionUrl"], "https://example.com/page")
        self.assertEqual(body["siteUrl"], "sc-domain:example.com")

    @patch("ads_mcp.utils.get_gsc_service")
    def test_list_gsc_sites_http_error(self, mock_get_service):
        from googleapiclient.errors import HttpError
        from fastmcp.exceptions import ToolError

        mock_service = MagicMock()
        mock_get_service.return_value = mock_service

        mock_resp = MagicMock()
        mock_resp.status = 403
        ex = HttpError(resp=mock_resp, content=b"Forbidden")
        mock_service.sites().list().execute.side_effect = ex

        with self.assertRaises(ToolError):
            search_console.list_gsc_sites()
