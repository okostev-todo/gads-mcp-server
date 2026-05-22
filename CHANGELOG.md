# Changelog

## [0.1.3] - 2026-05-22

### Fixed
- `get_keyword_historical_metrics`: iterate `response.results` instead of
  `response.metrics` to match `GenerateKeywordHistoricalMetricsResponse`
  structure. Fixed corresponding mock in unit test.

## [0.1.2] - 2026-05-15

### Fixed
- OAuth client registration now survives Cloud Run revision restarts without
  depending on the ephemeral file store. Set `GOOGLE_ADS_MCP_REGISTERED_CLIENT_ID`
  env var in Cloud Run to the client ID from your Claude.ai connector — the server
  synthesizes the client in memory on every request, mirroring how FastMCP handles
  the upstream client ID internally.

## [0.1.1] - 2026-05-15

### Fixed
- Added `_pre_register_client()` startup hook (superseded by 0.1.2).

## [0.1.0] - 2026-05-15

### Added
- `keyword_planner` module: `generate_keyword_ideas` and
  `get_keyword_historical_metrics` tools using `KeywordPlanIdeaService`.
  Supports seed keywords, seed URL, or both. Returns avg monthly searches,
  competition level, and CPC bid ranges.
- `mutations` module: seven write tools for campaign management —
  `create_campaign_budget`, `create_campaign`, `create_ad_group`,
  `add_keywords_to_ad_group`, `add_negative_keywords`,
  `update_campaign_status`, `create_responsive_search_ad`.
  Supports SEARCH, DISPLAY, and PERFORMANCE_MAX campaign types.

> **Note:** Write tools require Standard Access developer token to operate
> on real accounts. Explorer-level access is limited to test accounts.

## [0.0.1] - 2026-05-04

### Added
- Initial release: `search`, `get_resource_metadata`,
  `list_accessible_customers` tools.
- Resources: `discovery-document`, `metrics`, `segments`,
  `release-notes`.
