"""Allowlist-only domain contracts for deterministic extraction rules."""

from __future__ import annotations

import re
from typing import Annotated, Dict, List, Literal, Optional, Union

import soupsieve
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dataController.scraper.views.selector_stability import (
    selector_uses_volatile_html_id,
)

FieldName = Literal[
    "title",
    "author",
    "published_at",
    "detail_url",
    "external_id",
]
TransformName = Literal[
    "strip",
    "normalize_space",
    "urljoin",
    "date",
    "path_id",
]

_JSON_PATH_RE = re.compile(
    r"^\$(?:\.[A-Za-z_가-힣][A-Za-z0-9_가-힣-]*|\[\d+\])*$"
)
_TEMPLATE_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TEMPLATE_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_NON_PUBLISHED_JSON_DATE_PATH_RE = re.compile(
    r"(?:start|strt|begin|from|end|deadline|due|close|"
    r"시작|마감|종료|신청|접수)",
    re.IGNORECASE,
)
_SAFE_DATA_ATTRIBUTE_RE = re.compile(r"^data-[a-z0-9][a-z0-9_-]*$")
_SAFE_HTML_ATTRIBUTES = {
    "href",
    "title",
    "datetime",
    "content",
    "value",
}


class _StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HtmlFieldRule(_StrictContract):
    kind: Literal["html"]
    selector: str = Field(min_length=1, max_length=500)
    source: Literal["text", "attribute", "navigation", "onclick_literal"]
    attribute: Optional[str] = Field(default=None, min_length=1, max_length=80)
    exclude_selectors: List[str] = Field(default_factory=list, max_length=5)
    transforms: List[TransformName] = Field(default_factory=list, max_length=4)

    @field_validator("selector")
    @classmethod
    def validate_selector(cls, value: str) -> str:
        compact = value.strip()
        if not compact or "\x00" in compact or "javascript:" in compact.casefold():
            raise ValueError("안전하지 않은 CSS selector입니다.")
        if selector_uses_volatile_html_id(compact):
            raise ValueError(
                "응답마다 바뀔 가능성이 높은 동적 HTML ID는 selector에 "
                "사용할 수 없습니다."
            )
        try:
            soupsieve.compile(compact)
        except soupsieve.SelectorSyntaxError as exc:
            raise ValueError("유효하지 않은 CSS selector입니다.") from exc
        return compact

    @field_validator("exclude_selectors")
    @classmethod
    def validate_exclude_selectors(cls, values: List[str]) -> List[str]:
        normalized = [cls.validate_selector(value) for value in values]
        if any(value == ":scope" for value in normalized):
            raise ValueError("필드 루트 전체를 제외할 수 없습니다.")
        if len(set(normalized)) != len(normalized):
            raise ValueError("exclude selector는 중복될 수 없습니다.")
        return normalized

    @model_validator(mode="after")
    def validate_source_attribute(self) -> "HtmlFieldRule":
        if self.source == "text":
            if self.attribute is not None:
                raise ValueError("text source에는 attribute를 지정할 수 없습니다.")
            return self

        if self.source in {"navigation", "onclick_literal"}:
            if self.attribute is not None or self.exclude_selectors:
                raise ValueError(
                    f"{self.source} source에는 attribute/exclude_selectors를 "
                    "지정할 수 없습니다."
                )
            if any(transform not in {"strip"} for transform in self.transforms):
                raise ValueError(
                    f"{self.source} source에는 strip 외의 transform을 지정할 수 없습니다."
                )
            return self

        if self.exclude_selectors:
            raise ValueError("exclude_selectors는 text source에만 사용할 수 있습니다.")

        attribute = (self.attribute or "").casefold()
        if not attribute:
            raise ValueError("attribute source에는 attribute가 필요합니다.")
        if (
            attribute not in _SAFE_HTML_ATTRIBUTES
            and not _SAFE_DATA_ATTRIBUTE_RE.fullmatch(attribute)
        ):
            raise ValueError("허용되지 않은 HTML attribute입니다.")
        self.attribute = attribute
        return self


class JsonFieldRule(_StrictContract):
    kind: Literal["json"]
    path: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=500,
        pattern=_JSON_PATH_RE.pattern,
    )
    template: Optional[str] = Field(default=None, min_length=1, max_length=2000)
    template_fields: Dict[str, str] = Field(default_factory=dict, max_length=8)
    transforms: List[TransformName] = Field(default_factory=list, max_length=4)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        compact = value.strip()
        if not _JSON_PATH_RE.fullmatch(compact):
            raise ValueError("허용된 단순 JSON path 형식이 아닙니다.")
        return compact

    @field_validator("template")
    @classmethod
    def validate_template(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        compact = value.strip()
        if (
            not compact
            or "\x00" in compact
            or compact.casefold().startswith(("javascript:", "data:"))
        ):
            raise ValueError("안전하지 않은 JSON 템플릿입니다.")
        placeholders_removed = _TEMPLATE_PLACEHOLDER_RE.sub("", compact)
        if "{" in placeholders_removed or "}" in placeholders_removed:
            raise ValueError("허용되지 않은 JSON 템플릿 문법입니다.")
        return compact

    @field_validator("template_fields")
    @classmethod
    def validate_template_fields(cls, values: Dict[str, str]) -> Dict[str, str]:
        normalized: Dict[str, str] = {}
        for name, path in values.items():
            compact_name = name.strip()
            if not _TEMPLATE_FIELD_RE.fullmatch(compact_name):
                raise ValueError("템플릿 필드 이름이 올바르지 않습니다.")
            normalized[compact_name] = cls.validate_path(path) or ""
        return normalized

    @model_validator(mode="after")
    def validate_value_source(self) -> "JsonFieldRule":
        if self.path is not None:
            if self.template is not None or self.template_fields:
                raise ValueError("JSON path와 template은 함께 지정할 수 없습니다.")
            return self

        if self.template is None or not self.template_fields:
            raise ValueError("JSON 필드에는 path 또는 template이 필요합니다.")
        placeholders = set(_TEMPLATE_PLACEHOLDER_RE.findall(self.template))
        if placeholders != set(self.template_fields):
            raise ValueError("템플릿 placeholder와 template_fields가 일치해야 합니다.")
        return self


FieldRule = Annotated[
    Union[HtmlFieldRule, JsonFieldRule],
    Field(discriminator="kind"),
]


class ExtractedFieldRules(_StrictContract):
    title: FieldRule
    author: Optional[FieldRule] = None
    published_at: Optional[FieldRule] = None
    detail_url: Optional[FieldRule] = None
    external_id: Optional[FieldRule] = None

    def configured_rules(self) -> Dict[str, FieldRule]:
        return {
            name: rule
            for name, rule in self.__dict__.items()
            if rule is not None
        }


class ExtractorRuleV1(_StrictContract):
    """Allowlist-only rule proposed for one source schema."""

    version: Literal[1]
    source_type: Literal["html", "json"]
    record_selector: Optional[str] = Field(default=None, min_length=1, max_length=500)
    records_path: Optional[str] = Field(default=None, min_length=1, max_length=500)
    fields: ExtractedFieldRules
    evidence_ids: List[str] = Field(min_length=1, max_length=32)

    @field_validator("record_selector")
    @classmethod
    def validate_record_selector(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return HtmlFieldRule.validate_selector(value)

    @field_validator("records_path")
    @classmethod
    def validate_records_path(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return JsonFieldRule.validate_path(value)

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, values: List[str]) -> List[str]:
        normalized = [value.strip() for value in values]
        if any(not value or len(value) > 120 for value in normalized):
            raise ValueError("evidence ID는 1~120자여야 합니다.")
        if len(set(normalized)) != len(normalized):
            raise ValueError("evidence ID는 중복될 수 없습니다.")
        return normalized

    @model_validator(mode="after")
    def validate_source_contract(self) -> "ExtractorRuleV1":
        configured = self.fields.configured_rules()
        expected_kind = self.source_type
        if any(rule.kind != expected_kind for rule in configured.values()):
            raise ValueError("source_type과 field rule kind가 일치해야 합니다.")

        if self.source_type == "html":
            if not self.record_selector or self.records_path is not None:
                raise ValueError(
                    "HTML 규칙에는 record_selector만 지정해야 합니다."
                )
            if any(
                isinstance(rule, HtmlFieldRule)
                and rule.source == "navigation"
                and name != "detail_url"
                for name, rule in configured.items()
            ):
                raise ValueError(
                    "navigation source는 detail_url 필드에만 사용할 수 있습니다."
                )
            if any(
                isinstance(rule, HtmlFieldRule)
                and rule.source == "onclick_literal"
                and name != "external_id"
                for name, rule in configured.items()
            ):
                raise ValueError(
                    "onclick_literal source는 external_id 필드에만 사용할 수 있습니다."
                )
        elif not self.records_path or self.record_selector is not None:
            raise ValueError("JSON 규칙에는 records_path만 지정해야 합니다.")
        if any(
            isinstance(rule, JsonFieldRule)
            and rule.template is not None
            and name != "detail_url"
            for name, rule in configured.items()
        ):
            raise ValueError("JSON template은 detail_url 필드에만 사용할 수 있습니다.")
        published_rule = configured.get("published_at")
        if (
            isinstance(published_rule, JsonFieldRule)
            and published_rule.path
            and _NON_PUBLISHED_JSON_DATE_PATH_RE.search(published_rule.path)
        ):
            raise ValueError(
                "신청·접수 시작/마감 필드는 published_at으로 "
                "사용할 수 없습니다."
            )
        return self



def extractor_rule_json_schema() -> Dict[str, object]:
    return ExtractorRuleV1.model_json_schema()


__all__ = [
    "ExtractedFieldRules",
    "ExtractorRuleV1",
    "FieldName",
    "FieldRule",
    "HtmlFieldRule",
    "JsonFieldRule",
    "TransformName",
    "extractor_rule_json_schema",
]
