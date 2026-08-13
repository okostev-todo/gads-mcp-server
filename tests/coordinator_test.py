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

"""Test cases for the OAuth client synthesized for a known client_id."""

import unittest

from pydantic import AnyUrl

from ads_mcp import coordinator


class TestSynthesizeRegisteredClient(unittest.TestCase):
    """Test cases for synthesize_registered_client.

    This client is what Claude.ai authenticates against after a redeploy, and
    a redirect URI it does not accept breaks the connector with
    "Redirect URI not registered for client". The flow can only be exercised
    end to end through a browser, so these cases pin the validation rules that
    have actually broken before.
    """

    def setUp(self):
        self.client = coordinator.synthesize_registered_client(
            "6bae1d07-23ce-43fa-811e-f57e9f636d7d", "openid"
        )

    def _validate(self, uri: str):
        return self.client.validate_redirect_uri(AnyUrl(uri))

    def test_accepts_the_current_claude_callback(self):
        self.assertIsNotNone(
            self._validate("https://claude.ai/api/mcp/auth_callback")
        )

    def test_accepts_the_previous_claude_callback(self):
        # Claude.ai used oauth_callback before renaming it to auth_callback.
        self.assertIsNotNone(
            self._validate("https://claude.ai/api/mcp/oauth_callback")
        )

    def test_accepts_a_future_callback_path(self):
        # The point of matching a pattern: another rename must not require a
        # redeploy to keep the connector working.
        self.assertIsNotNone(
            self._validate("https://claude.ai/api/mcp/renamed_again")
        )

    def test_rejects_another_host(self):
        with self.assertRaises(Exception):
            self._validate("https://evil.example/api/mcp/auth_callback")

    def test_rejects_another_path_on_the_same_host(self):
        with self.assertRaises(Exception):
            self._validate("https://claude.ai/somewhere/else")

    def test_client_id_and_scope_are_carried_through(self):
        self.assertEqual(
            self.client.client_id, "6bae1d07-23ce-43fa-811e-f57e9f636d7d"
        )
        self.assertEqual(self.client.scope, "openid")

    def test_supports_refresh_so_sessions_outlive_the_access_token(self):
        self.assertIn("refresh_token", self.client.grant_types)


if __name__ == "__main__":
    unittest.main()
