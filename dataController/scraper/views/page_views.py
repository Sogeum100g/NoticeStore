"""Immutable HTML source views and parser-text derivation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Dict

from bs4 import BeautifulSoup, Comment

@dataclass(frozen=True)
class HtmlSourceViews:
    """Keep immutable source HTML separate from derived analysis text."""

    raw_html: str
    analysis_text: str
    raw_hash: str
    analysis_hash: str

    def metrics(self) -> Dict[str, Any]:
        return {
            "raw_chars": len(self.raw_html),
            "analysis_chars": len(self.analysis_text),
            "raw_hash": self.raw_hash,
            "analysis_hash": self.analysis_hash,
        }

with files("dataController").joinpath("tag.json").open(
    "r", encoding="utf-8"
) as json_file:
    tag_data = json.load(json_file)

def remove_json_nulls(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: remove_json_nulls(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [remove_json_nulls(item) for item in obj]
    return obj


def preprocessing(soup: BeautifulSoup) -> str:
    for element in soup.find_all(tag_data["trash_tags"]):
        element.decompose()

    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    return soup.get_text(separator="\n", strip=True)


def clean_html_text(raw_data: str) -> str:
    clean = re.sub(r"[\"']?\w+[\"']?\s*[:=]\s*(null|none|nan|undefined),?", "", raw_data, flags=re.IGNORECASE)
    clean = re.sub(r",+", ",", clean)
    return clean.replace(",}", "}").replace(",]", "]").strip()


def build_parser_text(response_text: str, parser_name: str = "lxml") -> str:
    soup = BeautifulSoup(response_text, parser_name)
    try:
        return clean_html_text(preprocessing(soup))
    finally:
        soup.decompose()


def build_html_source_views(
    response_text: str,
    parser_name: str = "lxml",
) -> HtmlSourceViews:
    raw_html = str(response_text or "")
    analysis_text = build_parser_text(raw_html, parser_name)
    return HtmlSourceViews(
        raw_html=raw_html,
        analysis_text=analysis_text,
        raw_hash=get_text_hash(raw_html),
        analysis_hash=get_text_hash(analysis_text),
    )


def normalize_string(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\W+", "", text).lower()


def get_text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()



__all__ = [
    "HtmlSourceViews",
    "build_html_source_views",
    "build_parser_text",
    "clean_html_text",
    "get_text_hash",
    "normalize_string",
    "preprocessing",
    "remove_json_nulls",
]
