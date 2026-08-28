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

"""Test cases for the Google Tag Manager tools."""

import unittest
from unittest.mock import MagicMock, patch

import httplib2
from fastmcp.exceptions import ToolError
from googleapiclient.errors import HttpError

from ads_mcp.tools import tag_manager

WORKSPACE = "accounts/123/containers/456/workspaces/7"
CONTAINER = "accounts/123/containers/456"


def _http_error(status: int) -> HttpError:
    return HttpError(httplib2.Response({"status": status}), b"{}")


def _paged(collection, pages):
    """Wires a collection mock to return the given list-reply pages.

    list_next must be stubbed explicitly: a bare MagicMock returns a new mock
    (truthy) forever, which would spin _list_all into an infinite loop.
    """
    request = MagicMock()
    request.execute.side_effect = pages
    collection.list.return_value = request
    collection.list_next.side_effect = [request] * (len(pages) - 1) + [None]
    return collection


class TagManagerTestCase(unittest.TestCase):
    """Base case exposing the mocked GTM service."""

    def setUp(self):
        self.service = MagicMock()
        service_patch = patch(
            "ads_mcp.utils.get_gtm_service", return_value=self.service
        )
        self.addCleanup(service_patch.stop)
        service_patch.start()
        self.workspaces = (
            self.service.accounts.return_value.containers.return_value.workspaces.return_value
        )


class TestListContainers(TagManagerTestCase):
    """Test cases for list_gtm_containers."""

    def test_nests_containers_under_their_account(self):
        _paged(
            self.service.accounts.return_value,
            [{"account": [{"path": "accounts/123", "name": "Main"}]}],
        )
        _paged(
            self.service.accounts.return_value.containers.return_value,
            [
                {
                    "container": [
                        {
                            "path": CONTAINER,
                            "publicId": "GTM-ABC123",
                            "name": "todo.ltd web",
                            "usageContext": ["WEB"],
                        }
                    ]
                }
            ],
        )

        results = tag_manager.list_gtm_containers()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["path"], "accounts/123")
        self.assertEqual(results[0]["containers"][0]["publicId"], "GTM-ABC123")

    def test_http_error_becomes_tool_error(self):
        self.service.accounts.return_value.list.side_effect = _http_error(429)

        with self.assertRaises(ToolError) as ctx:
            tag_manager.list_gtm_containers()

        self.assertIn("429", str(ctx.exception))


class TestListEntities(TagManagerTestCase):
    """Test cases for list_gtm_entities."""

    def test_drains_pagination_and_maps_reply_key(self):
        collection = _paged(
            self.workspaces.tags.return_value,
            [
                {"tag": [{"path": f"{WORKSPACE}/tags/1", "name": "GA4"}]},
                {"tag": [{"path": f"{WORKSPACE}/tags/2", "name": "Ads"}]},
            ],
        )

        results = tag_manager.list_gtm_entities(WORKSPACE, "tag")

        collection.list.assert_called_once_with(parent=WORKSPACE)
        self.assertEqual([t["name"] for t in results], ["GA4", "Ads"])

    def test_built_in_variables_use_camel_case_reply_key(self):
        _paged(
            self.workspaces.built_in_variables.return_value,
            [{"builtInVariable": [{"type": "clickUrl"}]}],
        )

        results = tag_manager.list_gtm_entities(WORKSPACE, "built_in_variable")

        self.assertEqual(results[0]["type"], "clickUrl")

    def test_unknown_entity_type_lists_valid_values(self):
        with self.assertRaises(ToolError) as ctx:
            tag_manager.list_gtm_entities(WORKSPACE, "pixel")

        message = str(ctx.exception)
        self.assertIn("pixel", message)
        self.assertIn("trigger", message)


class TestEntityCrud(TagManagerTestCase):
    """Test cases for create/get/update/delete of workspace entities."""

    def test_create_posts_body_to_workspace(self):
        collection = self.workspaces.triggers.return_value
        collection.create.return_value.execute.return_value = {
            "path": f"{WORKSPACE}/triggers/9"
        }
        entity = {"name": "Lead form", "type": "customEvent"}

        result = tag_manager.create_gtm_entity(WORKSPACE, "trigger", entity)

        collection.create.assert_called_once_with(parent=WORKSPACE, body=entity)
        self.assertEqual(result["path"], f"{WORKSPACE}/triggers/9")

    def test_create_built_in_variable_is_redirected(self):
        with self.assertRaises(ToolError) as ctx:
            tag_manager.create_gtm_entity(
                WORKSPACE, "built_in_variable", {"type": ["clickUrl"]}
            )

        self.assertIn("enable_gtm_built_in_variables", str(ctx.exception))

    def test_get_fetches_by_path(self):
        collection = self.workspaces.tags.return_value
        collection.get.return_value.execute.return_value = {"name": "GA4"}

        result = tag_manager.get_gtm_entity(f"{WORKSPACE}/tags/1", "tag")

        collection.get.assert_called_once_with(path=f"{WORKSPACE}/tags/1")
        self.assertEqual(result["name"], "GA4")

    def test_update_replaces_by_path(self):
        collection = self.workspaces.variables.return_value
        collection.update.return_value.execute.return_value = {"name": "v2"}
        entity = {"name": "v2", "type": "jsm"}

        tag_manager.update_gtm_entity(
            f"{WORKSPACE}/variables/3", "variable", entity
        )

        collection.update.assert_called_once_with(
            path=f"{WORKSPACE}/variables/3", body=entity
        )

    def test_delete_returns_the_deleted_path(self):
        result = tag_manager.delete_gtm_entity(f"{WORKSPACE}/tags/1", "tag")

        self.workspaces.tags.return_value.delete.assert_called_once_with(
            path=f"{WORKSPACE}/tags/1"
        )
        self.assertEqual(result, f"{WORKSPACE}/tags/1")


class TestBuiltInVariables(TagManagerTestCase):
    """Test cases for enable_gtm_built_in_variables."""

    def test_enables_types_via_query_parameter(self):
        collection = self.workspaces.built_in_variables.return_value
        collection.create.return_value.execute.return_value = {
            "builtInVariable": [{"type": "clickUrl"}, {"type": "pagePath"}]
        }

        results = tag_manager.enable_gtm_built_in_variables(
            WORKSPACE, ["clickUrl", "pagePath"]
        )

        collection.create.assert_called_once_with(
            parent=WORKSPACE, type=["clickUrl", "pagePath"]
        )
        self.assertEqual(len(results), 2)

    def test_empty_types_raises(self):
        with self.assertRaises(ToolError):
            tag_manager.enable_gtm_built_in_variables(WORKSPACE, [])


class TestWorkspacesAndVersions(TagManagerTestCase):
    """Test cases for the workspace -> version -> publish flow."""

    def test_create_workspace_includes_description_when_given(self):
        self.workspaces.create.return_value.execute.return_value = {
            "path": WORKSPACE
        }

        tag_manager.create_gtm_workspace(
            CONTAINER, "Cleanup", description="Remove stale pixels"
        )

        self.workspaces.create.assert_called_once_with(
            parent=CONTAINER,
            body={"name": "Cleanup", "description": "Remove stale pixels"},
        )

    def test_workspace_status_is_fetched_by_path(self):
        self.workspaces.getStatus.return_value.execute.return_value = {
            "workspaceChange": [],
            "mergeConflict": [],
        }

        result = tag_manager.get_gtm_workspace_status(WORKSPACE)

        self.workspaces.getStatus.assert_called_once_with(path=WORKSPACE)
        self.assertEqual(result["mergeConflict"], [])

    def test_create_version_submits_the_workspace(self):
        self.workspaces.create_version.return_value.execute.return_value = {
            "containerVersion": {"path": f"{CONTAINER}/versions/12"},
            "compilerError": False,
        }

        result = tag_manager.create_gtm_version(
            WORKSPACE, "August cleanup", notes="Removed stale pixels"
        )

        self.workspaces.create_version.assert_called_once_with(
            path=WORKSPACE,
            body={"name": "August cleanup", "notes": "Removed stale pixels"},
        )
        self.assertFalse(result["compilerError"])

    def test_publish_targets_the_version_path(self):
        versions = (
            self.service.accounts.return_value.containers.return_value.versions.return_value
        )
        versions.publish.return_value.execute.return_value = {
            "containerVersion": {"containerVersionId": "12"}
        }

        result = tag_manager.publish_gtm_version(f"{CONTAINER}/versions/12")

        versions.publish.assert_called_once_with(
            path=f"{CONTAINER}/versions/12"
        )
        self.assertEqual(result["containerVersion"]["containerVersionId"], "12")

    def test_list_versions_reports_missing_live_version_as_none(self):
        containers = self.service.accounts.return_value.containers.return_value
        _paged(
            containers.version_headers.return_value,
            [{"containerVersionHeader": [{"containerVersionId": "11"}]}],
        )
        containers.versions.return_value.live.side_effect = _http_error(404)

        result = tag_manager.list_gtm_versions(CONTAINER)

        self.assertIsNone(result["liveVersion"])
        self.assertEqual(len(result["versions"]), 1)


class TestRealClientContract(unittest.TestCase):
    """Runs every tool against the real discovery client, mocking only I/O.

    MagicMock services accept any keyword argument, so a call like
    accounts().list(parent=...) - which the real client rejects, since
    accounts is a top-level collection - sailed through the unit tests and
    failed in production. The real client validates parameters while building
    a request, before any network I/O, so patching only HttpRequest.execute
    exercises that validation.
    """

    def setUp(self):
        from googleapiclient.discovery import build

        service = build(
            "tagmanager", "v2", developerKey="x", static_discovery=True
        )
        service_patch = patch(
            "ads_mcp.utils.get_gtm_service", return_value=service
        )
        # An empty reply satisfies every tool: no items, no nextPageToken.
        execute_patch = patch(
            "googleapiclient.http.HttpRequest.execute", return_value={}
        )
        self.addCleanup(service_patch.stop)
        self.addCleanup(execute_patch.stop)
        service_patch.start()
        execute_patch.start()

    def test_every_tool_builds_valid_requests(self):
        tag_manager.list_gtm_containers()
        tag_manager.list_gtm_workspaces(CONTAINER)
        tag_manager.get_gtm_workspace_status(WORKSPACE)
        for entity_type in ("tag", "trigger", "variable", "built_in_variable"):
            tag_manager.list_gtm_entities(WORKSPACE, entity_type)
        tag_manager.get_gtm_entity(f"{WORKSPACE}/tags/1", "tag")
        tag_manager.create_gtm_entity(WORKSPACE, "tag", {"name": "t"})
        tag_manager.update_gtm_entity(
            f"{WORKSPACE}/tags/1", "tag", {"name": "t"}
        )
        tag_manager.delete_gtm_entity(f"{WORKSPACE}/tags/1", "tag")
        tag_manager.enable_gtm_built_in_variables(WORKSPACE, ["clickUrl"])
        tag_manager.create_gtm_workspace(CONTAINER, "ws", description="d")
        tag_manager.create_gtm_version(WORKSPACE, "v1", notes="n")
        tag_manager.publish_gtm_version(f"{CONTAINER}/versions/12")
        tag_manager.list_gtm_versions(CONTAINER)


if __name__ == "__main__":
    unittest.main()
