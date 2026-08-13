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

# Where Claude.ai expects the authorization code to be sent back.
CLAUDE_REDIRECT_URI = "https://claude.ai/api/mcp/auth_callback"
# Claude.ai has renamed this callback path once already
# (oauth_callback -> auth_callback), and a synthesized client with no patterns
# accepts only the exact URIs it was built with, which fails the flow with
# "Redirect URI not registered for client". Matching on the path prefix
# survives another rename while still pinning the host.
CLAUDE_REDIRECT_URI_PATTERN = "https://claude.ai/api/mcp/*"


def synthesize_registered_client(client_id: str, scope: str):
    """Builds an in-memory OAuth client for an already-registered client_id.

    Cloud Run gives each revision a fresh filesystem, so a client registered
    through DCR is lost on redeploy and Claude.ai then fails to authenticate
    with a client_id the server no longer recognizes. Rebuilding that client
    from configuration keeps the known client_id valid across revisions, which
    mirrors what OAuthProxy already does for the upstream client_id.
    """
    from fastmcp.server.auth.oauth_proxy.models import ProxyDCRClient
    from pydantic import AnyUrl

    return ProxyDCRClient(
        client_id=client_id,
        client_secret=None,
        redirect_uris=[AnyUrl(CLAUDE_REDIRECT_URI)],
        grant_types=["authorization_code", "refresh_token"],
        scope=scope,
        token_endpoint_auth_method="none",
        allowed_redirect_uri_patterns=[CLAUDE_REDIRECT_URI_PATTERN],
    )


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
        _orig_get_client = auth.get_client

        async def _get_client_with_fixed_registration(client_id: str):
            if client_id == _REGISTERED_CLIENT_ID:
                return synthesize_registered_client(
                    client_id, auth._default_scope_str
                )
            return await _orig_get_client(client_id)

        auth.get_client = _get_client_with_fixed_registration

    mcp = FastMCP("Google Marketing Server", auth=auth)
else:
    mcp = FastMCP("Google Marketing Server")
