# Changelog

## [0.4.0] - 2026-08-13

### Added
- `mutate` module: `mutate_google_ads`, a general-purpose write tool wrapping
  `GoogleAdsService.Mutate`. Accepts operations for any mutable resource as
  plain dicts, supports `validate_only` and `partial_failure`, and derives
  `update_mask` from the fields set on an update.
- `exclusions` module: `add_account_level_exclusions`,
  `add_campaign_exclusions`, `create_shared_exclusion_list`,
  `add_criteria_to_shared_set`, `attach_shared_set_to_campaigns` and
  `remove_criteria`. Covers placement, mobile app, YouTube and content-label
  exclusions — the controls that apply to Performance Max inventory — plus
  shared negative lists. `remove_criteria` infers the resource type from each
  resource name and batches per service.
- `conversions` module: `upload_offline_conversions`,
  `upload_conversion_adjustments`, `create_conversion_action` and
  `update_conversion_action`. Enables importing CRM conversion values and
  retracting fraudulent conversions so Smart Bidding stops learning on them.
- `pmax` module: `update_asset_group_status`, `add_asset_group_signals`,
  `update_campaign_bidding`, `update_campaign` and `update_campaign_budget`.
- Every write tool takes `validate_only` for a dry run, and reports per-row
  errors where the API supports partial failure.
- Shared helpers in `utils`: `raise_google_ads_error` (now includes the field
  path), `partial_failure_errors`, `derive_update_mask` and `enum_value`,
  which reports the valid names when given an invalid enum.

### Notes
- `derive_update_mask` uses protobuf field presence rather than value
  comparison, so a field set to a default value (`False`, `0`) is still
  included in the mask. Deriving the mask from a value diff silently dropped
  such fields, making updates like `primary_for_goal=False` no-ops.
- `AssetGroupService` does not support partial failure, so
  `update_asset_group_status` applies its whole batch or nothing.

## [0.3.0] - 2026-05-25

### Added
- Google Analytics 4 integration: `list_ga4_properties`,
  `get_ga4_metadata`, `run_ga4_report`, `run_ga4_realtime_report`,
  `batch_run_ga4_reports` tools using GA4 Data API v1 and Admin API.
  Filter helper converts simple dicts to GA4 FilterExpression.
  Reuses existing FastMCP OAuth session — `analytics.readonly` scope added.
- Renamed MCP server from "Google Ads Server" to "Google Marketing Server".

## [0.2.0] - 2026-05-22

### Added
- Google Search Console integration: `list_gsc_sites`,
  `query_search_analytics`, `inspect_url` tools.
  Reuses existing FastMCP OAuth session — `webmasters` scope added
  to GoogleProvider. Requires re-authentication in Claude.ai connector
  to grant the new scope.

## [0.1.4] - 2026-05-22

### Added
- `get_keyword_historical_metrics`: now returns `monthly_search_volumes`
  (list of `{year, month, monthly_searches}` for the past 12 months) and
  `close_variants` (keywords Google merges with the queried term).

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
