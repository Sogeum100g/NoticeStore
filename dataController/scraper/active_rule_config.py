"""Compatibility facade for active extraction-rule configuration."""

from dataController.scraper.extraction.rules.active_config import (
    ACTIVE_RULE_FORMAT,
    DETAIL_URL_BASE_VERSION,
    JSON_DATE_ROLE_VERSION,
    JSON_DETAIL_TEMPLATE_VERSION,
    activation_as_extraction_result,
    build_active_rule_config,
    canonicalize_detail_url_for_target,
    execute_active_rule_config,
    is_active_rule_config,
    load_active_rule,
    rule_schema_hash,
)

__all__ = [
    "ACTIVE_RULE_FORMAT",
    "DETAIL_URL_BASE_VERSION",
    "JSON_DATE_ROLE_VERSION",
    "JSON_DETAIL_TEMPLATE_VERSION",
    "activation_as_extraction_result",
    "build_active_rule_config",
    "canonicalize_detail_url_for_target",
    "execute_active_rule_config",
    "is_active_rule_config",
    "load_active_rule",
    "rule_schema_hash",
]
