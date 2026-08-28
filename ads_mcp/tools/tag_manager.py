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

"""Tools for Google Tag Manager API v2.

The GTM change flow mirrors the UI: edits land in a workspace, a workspace is
frozen into a container version, and publishing a version is what changes the
tags actually running on the site. Only publish_gtm_version affects the live
site; everything else stages changes.

Note: the GTM API has a very low default quota (around 15 requests per
minute). Batch reads with list_gtm_entities rather than fetching entities one
by one, and expect 429 errors when iterating quickly.
"""

from typing import Any, Dict, List, Optional

from ads_mcp.coordinator import mcp
from mcp.types import ToolAnnotations
import ads_mcp.utils as utils
from fastmcp.exceptions import ToolError

# entity_type argument -> (API collection, key holding items in a list reply)
_ENTITY_COLLECTIONS = {
    "tag": ("tags", "tag"),
    "trigger": ("triggers", "trigger"),
    "variable": ("variables", "variable"),
    "built_in_variable": ("built_in_variables", "builtInVariable"),
}


def _raise_gtm_error(ex):
    raise ToolError(f"GTM API Error {ex.status_code}: {ex.reason}")


def _workspaces():
    return utils.get_gtm_service().accounts().containers().workspaces()


def _entity_collection(entity_type: str):
    """Resolves an entity_type argument to its API collection and list key."""
    if entity_type not in _ENTITY_COLLECTIONS:
        raise ToolError(
            f"Unknown entity_type '{entity_type}'. Valid values: "
            f"{', '.join(sorted(_ENTITY_COLLECTIONS))}."
        )
    collection_name, list_key = _ENTITY_COLLECTIONS[entity_type]
    return getattr(_workspaces(), collection_name)(), list_key


def _list_all(collection, list_key: str, parent: str) -> List[Dict[str, Any]]:
    """Drains a paginated list call."""
    items: List[Dict[str, Any]] = []
    request = collection.list(parent=parent)
    while request is not None:
        response = request.execute()
        items.extend(response.get(list_key, []))
        request = collection.list_next(request, response)
    return items


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def list_gtm_containers() -> List[Dict[str, Any]]:
    """Lists GTM accounts and the containers in each of them.

    Start here: the 'path' values in the reply (accounts/123 and
    accounts/123/containers/456) are what every other GTM tool takes as
    input. The container's publicId is the GTM-XXXXXXX id seen in the site's
    source code.

    Returns:
        List of account dicts, each with 'containers' holding that account's
        containers (path, publicId, name, usageContext).
    """
    from googleapiclient.errors import HttpError

    try:
        service = utils.get_gtm_service()
        accounts = _list_all(service.accounts(), "account", parent="")
        results = []
        for account in accounts:
            containers = _list_all(
                service.accounts().containers(),
                "container",
                parent=account["path"],
            )
            results.append(
                {
                    "path": account["path"],
                    "name": account.get("name"),
                    "containers": [
                        {
                            "path": container["path"],
                            "publicId": container.get("publicId"),
                            "name": container.get("name"),
                            "usageContext": container.get("usageContext"),
                        }
                        for container in containers
                    ],
                }
            )
        return results
    except HttpError as ex:
        _raise_gtm_error(ex)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def list_gtm_workspaces(container_path: str) -> List[Dict[str, Any]]:
    """Lists the workspaces of a GTM container.

    A workspace is where unpublished edits live, like a branch. The 'Default
    Workspace' always exists; create_gtm_workspace makes an isolated one for
    a batch of related changes.

    Args:
        container_path: Container path, e.g. 'accounts/123/containers/456'.

    Returns:
        List of workspace dicts (path, name, description).
    """
    from googleapiclient.errors import HttpError

    try:
        return _list_all(_workspaces(), "workspace", parent=container_path)
    except HttpError as ex:
        _raise_gtm_error(ex)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def get_gtm_workspace_status(workspace_path: str) -> Dict[str, Any]:
    """Shows the pending changes and merge conflicts of a workspace.

    Use before create_gtm_version to review exactly what would ship. A
    conflict means the live container moved since the workspace was created;
    resolve it in the GTM UI or discard the workspace.

    Args:
        workspace_path: Workspace path,
            e.g. 'accounts/123/containers/456/workspaces/7'.

    Returns:
        Dict with 'workspaceChange' (list of pending changes) and
        'mergeConflict' (list of conflicts, empty when clean).
    """
    from googleapiclient.errors import HttpError

    try:
        return _workspaces().getStatus(path=workspace_path).execute()
    except HttpError as ex:
        _raise_gtm_error(ex)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def list_gtm_entities(
    workspace_path: str, entity_type: str
) -> List[Dict[str, Any]]:
    """Lists tags, triggers or variables in a GTM workspace.

    The listing shows the workspace's view of the container: published
    entities plus this workspace's unpublished edits.

    Args:
        workspace_path: Workspace path,
            e.g. 'accounts/123/containers/456/workspaces/7'.
        entity_type: 'tag', 'trigger', 'variable' or 'built_in_variable'.

    Returns:
        List of entity dicts. Each has 'path' (input for get/update/delete),
        a numeric id field, 'name', 'type' and its type-specific parameters.
    """
    from googleapiclient.errors import HttpError

    collection, list_key = _entity_collection(entity_type)
    try:
        return _list_all(collection, list_key, parent=workspace_path)
    except HttpError as ex:
        _raise_gtm_error(ex)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def get_gtm_entity(entity_path: str, entity_type: str) -> Dict[str, Any]:
    """Fetches one GTM tag, trigger or variable with full details.

    Args:
        entity_path: Entity path from a listing,
            e.g. 'accounts/123/containers/456/workspaces/7/tags/8'.
        entity_type: 'tag', 'trigger' or 'variable'.

    Returns:
        The full entity dict, in the same shape create/update accept.
    """
    from googleapiclient.errors import HttpError

    if entity_type == "built_in_variable":
        raise ToolError(
            "Built-in variables have no individual get; use "
            "list_gtm_entities with entity_type='built_in_variable'."
        )
    collection, _ = _entity_collection(entity_type)
    try:
        return collection.get(path=entity_path).execute()
    except HttpError as ex:
        _raise_gtm_error(ex)


@mcp.tool()
def create_gtm_entity(
    workspace_path: str, entity_type: str, entity: Dict[str, Any]
) -> Dict[str, Any]:
    """Creates a tag, trigger or variable in a GTM workspace.

    The entity dict uses the GTM API v2 resource shape. The easiest way to
    get it right is to fetch a similar existing entity with get_gtm_entity
    and use it as a template: a GA4 event tag is
    {"name": "...", "type": "gaawe", "parameter": [...],
    "firingTriggerId": ["<triggerId>"]}, a custom-event trigger is
    {"name": "...", "type": "customEvent", "customEventFilter": [...]}.

    The change stays unpublished in the workspace until a version is created
    and published, so this does not affect the live site.

    Args:
        workspace_path: Workspace to create in,
            e.g. 'accounts/123/containers/456/workspaces/7'.
        entity_type: 'tag', 'trigger' or 'variable'.
        entity: The entity resource dict as described above.

    Returns:
        The created entity, including its assigned id and path.
    """
    from googleapiclient.errors import HttpError

    if entity_type == "built_in_variable":
        raise ToolError(
            "Use enable_gtm_built_in_variables for built-in variables."
        )
    collection, _ = _entity_collection(entity_type)
    try:
        return collection.create(parent=workspace_path, body=entity).execute()
    except HttpError as ex:
        _raise_gtm_error(ex)


@mcp.tool()
def update_gtm_entity(
    entity_path: str, entity_type: str, entity: Dict[str, Any]
) -> Dict[str, Any]:
    """Updates a tag, trigger or variable in a GTM workspace.

    The update replaces the whole entity, not just the fields provided:
    fetch the current entity with get_gtm_entity, modify it, and send the
    complete dict back. Sending a partial dict silently drops the omitted
    settings.

    Args:
        entity_path: Entity path,
            e.g. 'accounts/123/containers/456/workspaces/7/tags/8'.
        entity_type: 'tag', 'trigger' or 'variable'.
        entity: The complete entity resource dict.

    Returns:
        The updated entity.
    """
    from googleapiclient.errors import HttpError

    if entity_type == "built_in_variable":
        raise ToolError(
            "Built-in variables cannot be updated; they are only enabled "
            "(enable_gtm_built_in_variables) or disabled."
        )
    collection, _ = _entity_collection(entity_type)
    try:
        return collection.update(path=entity_path, body=entity).execute()
    except HttpError as ex:
        _raise_gtm_error(ex)


@mcp.tool()
def delete_gtm_entity(entity_path: str, entity_type: str) -> str:
    """Deletes a tag, trigger or variable from a GTM workspace.

    The deletion is staged in the workspace like any other edit and reaches
    the live site only when a version is created and published. A tag whose
    only firing trigger is deleted stops firing, so check references first.

    Args:
        entity_path: Entity path,
            e.g. 'accounts/123/containers/456/workspaces/7/tags/8'.
        entity_type: 'tag', 'trigger' or 'variable'.

    Returns:
        The path of the deleted entity.
    """
    from googleapiclient.errors import HttpError

    if entity_type == "built_in_variable":
        raise ToolError(
            "Built-in variables are disabled, not deleted; there is no "
            "delete tool for them yet."
        )
    collection, _ = _entity_collection(entity_type)
    try:
        collection.delete(path=entity_path).execute()
        return entity_path
    except HttpError as ex:
        _raise_gtm_error(ex)


@mcp.tool()
def enable_gtm_built_in_variables(
    workspace_path: str, types: List[str]
) -> List[Dict[str, Any]]:
    """Enables built-in variables in a GTM workspace.

    Built-in variables (Click URL, Page Path, Event and so on) exist in every
    container but are disabled by default; a tag or trigger referencing a
    disabled one gets an empty value. Type names use the API's camelCase, so
    'clickUrl', 'pagePath', 'eventName', 'formId'.

    Args:
        workspace_path: Workspace path,
            e.g. 'accounts/123/containers/456/workspaces/7'.
        types: Built-in variable type names to enable.

    Returns:
        List of the enabled built-in variable dicts.
    """
    from googleapiclient.errors import HttpError

    if not types:
        raise ToolError("'types' must not be empty.")
    try:
        response = (
            _workspaces()
            .built_in_variables()
            .create(parent=workspace_path, type=types)
            .execute()
        )
        return response.get("builtInVariable", [])
    except HttpError as ex:
        _raise_gtm_error(ex)


@mcp.tool()
def create_gtm_workspace(
    container_path: str, name: str, description: str = None
) -> Dict[str, Any]:
    """Creates a new workspace in a GTM container.

    A separate workspace keeps a batch of related changes isolated from other
    edits until they ship together, and is cheap to discard if the approach
    changes.

    Args:
        container_path: Container path, e.g. 'accounts/123/containers/456'.
        name: Workspace name.
        description: Optional description of what the workspace is for.

    Returns:
        The created workspace dict; its 'path' is what the entity tools take.
    """
    from googleapiclient.errors import HttpError

    body = {"name": name}
    if description:
        body["description"] = description
    try:
        return _workspaces().create(parent=container_path, body=body).execute()
    except HttpError as ex:
        _raise_gtm_error(ex)


@mcp.tool()
def create_gtm_version(
    workspace_path: str, name: str, notes: str = None
) -> Dict[str, Any]:
    """Freezes a GTM workspace into a container version.

    This is GTM's Submit step: the workspace's changes become an immutable
    version and the workspace is consumed. The version does NOT go live until
    publish_gtm_version - so this is still safe, and the right place to stop
    for a human review.

    Check 'compilerError' in the reply: when true, the version was not
    created and 'syncStatus'/'mergeConflict' explain why (usually the
    workspace is behind the live container).

    Args:
        workspace_path: Workspace to freeze,
            e.g. 'accounts/123/containers/456/workspaces/7'.
        name: Version name shown in the GTM versions list.
        notes: Optional notes describing the changes.

    Returns:
        Dict with 'containerVersion' (its 'path' is the publish input) and
        'compilerError'.
    """
    from googleapiclient.errors import HttpError

    body = {"name": name}
    if notes:
        body["notes"] = notes
    try:
        return (
            _workspaces()
            .create_version(path=workspace_path, body=body)
            .execute()
        )
    except HttpError as ex:
        _raise_gtm_error(ex)


@mcp.tool()
def publish_gtm_version(version_path: str) -> Dict[str, Any]:
    """Publishes a container version, making it live on the site.

    This is the one GTM tool with immediate real-world effect: every page
    loading this container starts serving the version's tags right away.
    Confirm with the user before calling it unless they explicitly asked to
    publish. Rollback is republishing the previous version from the versions
    list, so note the currently live version id first (list_gtm_versions
    shows it).

    Args:
        version_path: Version path from create_gtm_version,
            e.g. 'accounts/123/containers/456/versions/12'.

    Returns:
        Dict with 'containerVersion' of the now-live version.
    """
    from googleapiclient.errors import HttpError

    try:
        return (
            utils.get_gtm_service()
            .accounts()
            .containers()
            .versions()
            .publish(path=version_path)
            .execute()
        )
    except HttpError as ex:
        _raise_gtm_error(ex)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def list_gtm_versions(
    container_path: str, include_deleted: bool = False
) -> Dict[str, Any]:
    """Lists a container's versions and identifies the live one.

    Use to review history before publishing and to find the version to roll
    back to.

    Args:
        container_path: Container path, e.g. 'accounts/123/containers/456'.
        include_deleted: Also list deleted versions. Default False.

    Returns:
        Dict with 'liveVersion' (the currently published version's header,
        None if nothing is published) and 'versions' (all version headers,
        newest last).
    """
    from googleapiclient.errors import HttpError

    service = utils.get_gtm_service()
    try:
        headers_collection = service.accounts().containers().version_headers()
        items: List[Dict[str, Any]] = []
        request = headers_collection.list(
            parent=container_path, includeDeleted=include_deleted
        )
        while request is not None:
            response = request.execute()
            items.extend(response.get("containerVersionHeader", []))
            request = headers_collection.list_next(request, response)

        live: Optional[Dict[str, Any]] = None
        try:
            live = (
                service.accounts()
                .containers()
                .versions()
                .live(parent=container_path)
                .execute()
            )
        except HttpError:
            # No published version yet; leave live as None.
            pass

        return {
            "liveVersion": (
                {
                    "path": live.get("path"),
                    "containerVersionId": live.get("containerVersionId"),
                    "name": live.get("name"),
                }
                if live
                else None
            ),
            "versions": items,
        }
    except HttpError as ex:
        _raise_gtm_error(ex)
