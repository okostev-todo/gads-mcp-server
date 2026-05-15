# Changelog

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
