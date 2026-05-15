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

"""Entry point for the MCP server."""

import os

import anyio
from ads_mcp.coordinator import mcp

# The following imports are necessary to register the tools with the `mcp`
# object, even though they are not directly used in this file.
# The `# noqa: F401` comment tells the linter to ignore the "unused import"
# warning.
from ads_mcp.tools import (
    search,
    core,
    get_resource_metadata,
    keyword_planner,
    mutations,
)  # noqa: F401
from ads_mcp.resources import (
    discovery,
    metrics,
    release_notes,
    segments,
)  # noqa: F401


async def _pre_register_client() -> None:
    """Pre-register OAuth client on startup to survive Cloud Run revision restarts.

    Reads GOOGLE_ADS_MCP_REGISTERED_CLIENT_ID from the environment and registers
    it with the OAuth provider so Claude.ai can connect without requiring a manual
    /register call after every deploy.
    """
    client_id = os.environ.get("GOOGLE_ADS_MCP_REGISTERED_CLIENT_ID")
    if not client_id or not mcp.auth:
        return
    from mcp.shared.auth import OAuthClientInformationFull

    client_info = OAuthClientInformationFull(
        client_id=client_id,
        redirect_uris=["https://claude.ai/api/mcp/oauth_callback"],
    )
    await mcp.auth.register_client(client_info)


def run_server() -> None:
    _CLIENT_ID = os.environ.get("GOOGLE_ADS_MCP_OAUTH_CLIENT_ID")
    _CLIENT_SECRET = os.environ.get("GOOGLE_ADS_MCP_OAUTH_CLIENT_SECRET")
    port = int(os.environ.get("PORT", "8080"))

    if _CLIENT_ID and _CLIENT_SECRET:

        async def _run() -> None:
            await _pre_register_client()
            await mcp.run_async(
                transport="streamable-http", port=port, host="0.0.0.0"
            )

        anyio.run(_run)
    else:
        mcp.run()


if __name__ == "__main__":
    run_server()
