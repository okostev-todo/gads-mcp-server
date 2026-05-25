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

"""Module declaring the singleton MCP instance.

The singleton allows other modules to register their tools with the same MCP
server using `@mcp.tool` annotations, thereby 'coordinating' the bootstrapping
of the server.
"""

import os
from fastmcp import FastMCP
from fastmcp.server.auth.providers.google import GoogleProvider

_CLIENT_ID = os.environ.get("GOOGLE_ADS_MCP_OAUTH_CLIENT_ID")
_CLIENT_SECRET = os.environ.get("GOOGLE_ADS_MCP_OAUTH_CLIENT_SECRET")
_BASE_URL = os.environ.get("GOOGLE_ADS_MCP_BASE_URL", "http://localhost:8080")
_REGISTERED_CLIENT_ID = os.environ.get("GOOGLE_ADS_MCP_REGISTERED_CLIENT_ID")

if _CLIENT_ID and _CLIENT_SECRET:
    auth = GoogleProvider(
        client_id=_CLIENT_ID,
        client_secret=_CLIENT_SECRET,
        base_url=_BASE_URL,
        required_scopes=[
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
            "https://www.googleapis.com/auth/adwords",
            "https://www.googleapis.com/auth/webmasters",
            "https://www.googleapis.com/auth/analytics.readonly",
        ],
    )

    if _REGISTERED_CLIENT_ID:
        # Synthesize a client in memory so the known client_id survives
        # Cloud Run revision restarts without depending on the ephemeral file store.
        # This mirrors what OAuthProxy already does for the upstream client_id.
        _orig_get_client = auth.get_client

        async def _get_client_with_fixed_registration(client_id: str):
            if client_id == _REGISTERED_CLIENT_ID:
                from fastmcp.server.auth.oauth_proxy.models import (
                    ProxyDCRClient,
                )
                from pydantic import AnyUrl

                return ProxyDCRClient(
                    client_id=client_id,
                    client_secret=None,
                    redirect_uris=[
                        AnyUrl("https://claude.ai/api/mcp/oauth_callback")
                    ],
                    grant_types=["authorization_code", "refresh_token"],
                    scope=auth._default_scope_str,
                    token_endpoint_auth_method="none",
                    allowed_redirect_uri_patterns=None,
                )
            return await _orig_get_client(client_id)

        auth.get_client = _get_client_with_fixed_registration

    mcp = FastMCP("Google Marketing Server", auth=auth)
else:
    mcp = FastMCP("Google Marketing Server")
