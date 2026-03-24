#!/usr/bin/env python3
"""Explainable AEO (AI SEO) completeness scorer.

This tool reads a public URL or local HTML file and returns a 1.0-10.0 score,
plus category breakdowns and practical fixes.
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


QUESTION_WORDS = (
    "what",
    "why",
    "how",
    "when",
    "where",
    "who",
    "which",
    "can",
    "should",
    "is",
    "are",
    "does",
    "do",
)

BLOCK_TERMS = (
    "access denied",
    "forbidden",
    "captcha",
    "verify you are human",
    "blocked",
    "temporarily unavailable",
    "security check",
    "cloudflare",
)

RELEVANT_SCHEMA_TYPES = {
    "article",
    "blogposting",
    "newsarticle",
    "webpage",
    "faqpage",
    "howto",
    "product",
    "softwareapplication",
    "organization",
    "person",
    "breadcrumblist",
    "qapage",
}


@dataclass
class PageSignals:
    source: str
    base_url: str | None = None
    html: str = ""
    title: str = ""
    meta_description: str = ""
    canonical: str = ""
    lang: str = ""
    robots: str = ""
    og_title: str = ""
    og_description: str = ""
    json_ld_blocks: list[str] = field(default_factory=list)
    schema_types: set[str] = field(default_factory=set)
    schema_has_author: bool = False
    schema_has_publisher: bool = False
    schema_has_date: bool = False
    headings: list[tuple[str, str]] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)
    list_items: list[str] = field(default_factory=list)
    internal_links: list[str] = field(default_factory=list)
    external_links: list[str] = field(default_factory=list)
    image_alts: list[str] = field(default_factory=list)
    has_table: bool = False
    has_faq_section: bool = False
    author_mentions: list[str] = field(default_factory=list)
    date_mentions: list[str] = field(default_factory=list)
    organization_mentions: list[str] = field(default_factory=list)
    visible_text: str = ""
    llms_txt_found: bool = False
    http_status: int | None = None
    fetch_warning: str = ""


@dataclass
class ScoreBreakdown:
    name: str
    points: float
    max_points: float
    reasons: list[str]


class SignalHTMLParser(HTMLParser):
    def __init__(self, base_url: str | None) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.signals = PageSignals(source=base_url or "local-file", base_url=base_url)
        self._ignored_tags = {"script", "style", "noscript", "svg"}
        self._tag_stack: list[str] = []
        self._current_text_parts: list[str] = []
        self._current_heading_tag: str | None = None
        self._current_paragraph_tag: str | None = None
        self._capture_title = False
        self._capture_json_ld = False
        self._current_json_ld_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        lowered_tag = tag.lower()
        self._tag_stack.append(lowered_tag)

        if lowered_tag == "html":
            self.signals.lang = attr_map.get("lang", "").strip()

        if lowered_tag == "title":
            self._capture_title = True

        if lowered_tag == "meta":
            name = attr_map.get("name", "").lower()
            prop = attr_map.get("property", "").lower()
            content = attr_map.get("content", "").strip()
            if name == "description":
                self.signals.meta_description = content
            elif name == "robots":
                self.signals.robots = content.lower()
            elif prop == "og:title":
                self.signals.og_title = content
            elif prop == "og:description":
                self.signals.og_description = content

        if lowered_tag == "link":
            rel = attr_map.get("rel", "").lower()
            href = attr_map.get("href", "").strip()
            if "canonical" in rel:
                self.signals.canonical = href
            if href and "llms.txt" in href.lower():
                self.signals.llms_txt_found = True

        if lowered_tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._current_heading_tag = lowered_tag
            self._current_text_parts = []

        if lowered_tag in {"p", "li"}:
            self._current_paragraph_tag = lowered_tag
            self._current_text_parts = []

        if lowered_tag == "a":
            href = attr_map.get("href", "").strip()
            if href:
                absolute = urljoin(self.base_url, href) if self.base_url else href
                if self._is_internal_link(absolute):
                    self.signals.internal_links.append(absolute)
                else:
                    self.signals.external_links.append(absolute)
                if "llms.txt" in absolute.lower():
                    self.signals.llms_txt_found = True

        if lowered_tag == "img":
            alt = attr_map.get("alt", "").strip()
            if alt:
                self.signals.image_alts.append(alt)

        if lowered_tag == "table":
            self.signals.has_table = True

        if lowered_tag == "script" and attr_map.get("type", "").lower() == "application/ld+json":
            self._capture_json_ld = True
            self._current_json_ld_parts = []

    def handle_data(self, data: str) -> None:
        if self._capture_title:
            self.signals.title += data
        if self._capture_json_ld:
            self._current_json_ld_parts.append(data)
        if not any(tag in self._ignored_tags for tag in self._tag_stack):
            cleaned = normalize_space(data)
            if cleaned:
                self.signals.visible_text += cleaned + " "
                if self._current_heading_tag or self._current_paragraph_tag:
                    self._current_text_parts.append(cleaned)

    def handle_endtag(self, tag: str) -> None:
        lowered_tag = tag.lower()

        if lowered_tag == "title":
            self._capture_title = False
            self.signals.title = normalize_space(self.signals.title)

        if lowered_tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and self._current_heading_tag == lowered_tag:
            text = normalize_space(" ".join(self._current_text_parts))
            if text:
                self.signals.headings.append((lowered_tag, text))
                if "faq" in text.lower():
                    self.signals.has_faq_section = True
            self._current_heading_tag = None
            self._current_text_parts = []

        if lowered_tag in {"p", "li"} and self._current_paragraph_tag == lowered_tag:
            text = normalize_space(" ".join(self._current_text_parts))
            if text:
                if lowered_tag == "p":
                    self.signals.paragraphs.append(text)
                else:
                    self.signals.list_items.append(text)
            self._current_paragraph_tag = None
            self._current_text_parts = []

        if lowered_tag == "script" and self._capture_json_ld:
            block = "".join(self._current_json_ld_parts).strip()
            if block:
                self.signals.json_ld_blocks.append(block)
            self._capture_json_ld = False
            self._current_json_ld_parts = []

        if self._tag_stack:
            self._tag_stack.pop()

    def _is_internal_link(self, absolute_url: str) -> bool:
        if not self.base_url:
            return absolute_url.startswith("#") or absolute_url.startswith("/")
        base_host = urlparse(self.base_url).netloc
        target = urlparse(absolute_url)
        return not target.netloc or target.netloc == base_host


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip()


def fetch_url(url: str) -> tuple[str, int | None, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,zh-TW;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    try:
        import requests  # type: ignore

        response = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
        warning = ""
        if response.status_code >= 400:
            warning = f"HTTP {response.status_code}; content may be a block page instead of the real article."
        return response.text, response.status_code, warning
    except Exception:
        request = Request(url, headers=headers)
        context = ssl.create_default_context()
        with urlopen(request, context=context, timeout=20) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace"), response.status, ""


def load_input(url: str | None, file_path: str | None) -> tuple[str, str, int | None, str]:
    if url:
        html, status, warning = fetch_url(url)
        return html, url, status, warning
    if file_path:
        path = Path(file_path)
        return path.read_text(encoding="utf-8", errors="replace"), str(path.resolve()), None, ""
    raise ValueError("Either a URL or file path is required.")


def parse_page(html: str, source: str, http_status: int | None = None, fetch_warning: str = "") -> PageSignals:
    base_url = source if source.startswith(("http://", "https://")) else None
    parser = SignalHTMLParser(base_url=base_url)
    parser.feed(html)
    signals = parser.signals
    signals.html = html
    signals.source = source
    signals.http_status = http_status
    signals.fetch_warning = fetch_warning
    extract_schema_signals(signals)
    extract_entity_signals(signals)
    detect_llms_txt(signals)
    return signals


def extract_schema_signals(signals: PageSignals) -> None:
    for block in signals.json_ld_blocks:
        compact = compact_json(block.lower())
        for schema_type in RELEVANT_SCHEMA_TYPES:
            if f'"@type":"{schema_type}"' in compact or f'"@type":["{schema_type}"' in compact:
                signals.schema_types.add(schema_type)
        if '"author"' in compact:
            signals.schema_has_author = True
        if '"publisher"' in compact:
            signals.schema_has_publisher = True
        if '"datepublished"' in compact or '"datemodified"' in compact:
            signals.schema_has_date = True


def compact_json(value: str) -> str:
    return re.sub(r"\s+", "", value)


def extract_entity_signals(signals: PageSignals) -> None:
    text = signals.visible_text
    lowered = text.lower()

    author_patterns = [
        r"\bby\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}",
        r"written by\s+[A-Za-z][A-Za-z \-]{1,40}",
        r"author\s*:\s*[A-Za-z0-9 _\-]{2,60}",
    ]
    date_patterns = [
        r"\b(?:20|19)\d{2}[/-](?:0?[1-9]|1[0-2])[/-](?:0?[1-9]|[12]\d|3[01])\b",
        r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2},\s+(?:20|19)\d{2}\b",
        r"(?:updated|published|last updated)\s*:?[\s,]*(?:20|19)\d{2}",
    ]
    org_patterns = [
        r"\binc\.?\b",
        r"\bltd\.?\b",
        r"\bcorp\.?\b",
        r"\bllc\b",
        r"about us",
        r"contact us",
    ]

    signals.author_mentions = collect_pattern_matches(text, author_patterns)
    signals.date_mentions = collect_pattern_matches(lowered, date_patterns, lowered_input=True)
    signals.organization_mentions = collect_pattern_matches(lowered, org_patterns, lowered_input=True)

    if any("faq" in heading.lower() for _, heading in signals.headings):
        signals.has_faq_section = True


def collect_pattern_matches(text: str, patterns: Iterable[str], lowered_input: bool = False) -> list[str]:
    matches: list[str] = []
    flags = re.IGNORECASE if lowered_input else 0
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=flags):
            matches.append(" ".join(match) if isinstance(match, tuple) else str(match))
    return matches


def detect_llms_txt(signals: PageSignals) -> None:
    if signals.llms_txt_found or not signals.base_url:
        return
    root = urlparse(signals.base_url)
    candidate = f"{root.scheme}://{root.netloc}/llms.txt"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; AEOScoreBot/0.1)"}
    try:
        request = Request(candidate, headers=headers)
        with urlopen(request, timeout=5) as response:
            if response.status == 200:
                signals.llms_txt_found = True
    except Exception:
        signals.llms_txt_found = False


def score_page(signals: PageSignals) -> tuple[float, list[ScoreBreakdown]]:
    breakdowns = [
        score_technical_foundation(signals),
        score_schema(signals),
        score_answer_quality(signals),
        score_trust_and_entities(signals),
        score_structure(signals),
        score_ai_readiness(signals),
    ]
    raw = sum(item.points for item in breakdowns)
    normalized = 1.0 + (raw / 100.0) * 9.0
    return round(min(10.0, max(1.0, normalized)), 1), breakdowns


def score_technical_foundation(signals: PageSignals) -> ScoreBreakdown:
    points = 0.0
    reasons: list[str] = []

    title_len = len(signals.title)
    if 30 <= title_len <= 65:
        points += 4
        reasons.append("Title length is in a healthy range.")
    elif signals.title:
        points += 2
        reasons.append("Title exists but can be tuned.")
    else:
        reasons.append("Missing title.")

    desc_len = len(signals.meta_description)
    if 80 <= desc_len <= 180:
        points += 4
        reasons.append("Meta description is summary-friendly.")
    elif signals.meta_description:
        points += 2
        reasons.append("Meta description exists but can be sharper.")
    else:
        reasons.append("Missing meta description.")

    if signals.canonical:
        points += 3
        reasons.append("Canonical is present.")
    else:
        reasons.append("Missing canonical.")

    if signals.lang:
        points += 2
        reasons.append("HTML lang is present.")
    else:
        reasons.append("Missing HTML lang.")

    if "noindex" not in signals.robots:
        points += 4
        reasons.append("No noindex directive detected.")
    else:
        reasons.append("Page appears to be noindex.")

    if signals.og_title and signals.og_description:
        points += 3
        reasons.append("Open Graph summary fields exist.")
    elif signals.og_title or signals.og_description:
        points += 1
        reasons.append("Open Graph is partial.")
    else:
        reasons.append("Missing Open Graph summary fields.")

    return ScoreBreakdown("Technical foundation", points, 20, reasons)


def score_schema(signals: PageSignals) -> ScoreBreakdown:
    points = 0.0
    reasons: list[str] = []

    if signals.json_ld_blocks:
        points += 8
        reasons.append("JSON-LD was found.")
    else:
        reasons.append("No JSON-LD found.")

    if signals.schema_types:
        points += min(8, 3 + len(signals.schema_types))
        reasons.append(f"Detected schema types: {', '.join(sorted(signals.schema_types))}.")
    else:
        reasons.append("No common schema types detected.")

    schema_detail_hits = sum(
        [
            signals.schema_has_author,
            signals.schema_has_publisher,
            signals.schema_has_date,
        ]
    )
    if schema_detail_hits:
        points += min(4, schema_detail_hits * 1.5)
        reasons.append("Schema includes author, publisher, or date details.")
    else:
        reasons.append("Schema lacks author, publisher, and date detail.")

    return ScoreBreakdown("Structured data", points, 20, reasons)


def score_answer_quality(signals: PageSignals) -> ScoreBreakdown:
    points = 0.0
    reasons: list[str] = []

    h1s = [text for tag, text in signals.headings if tag == "h1"]
    if h1s:
        points += 4
        reasons.append("Page has an H1.")
    else:
        reasons.append("Missing H1.")

    first_paragraph = signals.paragraphs[0] if signals.paragraphs else ""
    first_word_count = word_count(first_paragraph)
    if 35 <= first_word_count <= 90:
        points += 7
        reasons.append("Opening paragraph is answer-snippet friendly.")
    elif first_paragraph:
        points += 3
        reasons.append("Opening paragraph exists but is not strongly answer-first.")
    else:
        reasons.append("Missing a clear body opening paragraph.")

    question_headings = sum(1 for _, text in signals.headings if is_question_like(text))
    if question_headings >= 2 or signals.has_faq_section:
        points += 6
        reasons.append("Page has FAQ or question-driven headings.")
    elif question_headings == 1:
        points += 3
        reasons.append("Page has at least one question-driven heading.")
    else:
        reasons.append("Missing FAQ or question-driven sections.")

    if len(signals.list_items) >= 3:
        points += 4
        reasons.append("Bulleted content exists and is extractable.")
    elif signals.list_items:
        points += 2
        reasons.append("Some list content exists.")
    else:
        reasons.append("Missing list-style content.")

    if signals.has_table:
        points += 2
        reasons.append("Table content exists.")
    else:
        reasons.append("No table content found.")

    avg_paragraph_words = average(word_count(p) for p in signals.paragraphs[:8])
    if 30 <= avg_paragraph_words <= 110:
        points += 2
        reasons.append("Paragraph density is reasonable.")
    elif signals.paragraphs:
        reasons.append("Paragraphs are likely too short or too long.")
    else:
        reasons.append("Little to no paragraph content found.")

    return ScoreBreakdown("Answer quality", points, 25, reasons)


def score_trust_and_entities(signals: PageSignals) -> ScoreBreakdown:
    points = 0.0
    reasons: list[str] = []

    if signals.author_mentions or signals.schema_has_author:
        points += 5
        reasons.append("Author signal exists.")
    else:
        reasons.append("Missing author signal.")

    if signals.date_mentions or signals.schema_has_date:
        points += 5
        reasons.append("Publish or update date exists.")
    else:
        reasons.append("Missing freshness signal.")

    external_domains = unique_domains(signals.external_links)
    if len(external_domains) >= 2:
        points += 4
        reasons.append("Page cites multiple external domains.")
    elif external_domains:
        points += 2
        reasons.append("Page cites at least one external domain.")
    else:
        reasons.append("Missing external citation signals.")

    if signals.organization_mentions or signals.schema_has_publisher:
        points += 3
        reasons.append("Publisher or organization signal exists.")
    else:
        reasons.append("Missing publisher or organization signal.")

    wc = word_count(signals.visible_text)
    if wc >= 600:
        points += 3
        reasons.append("Content depth is substantial.")
    elif wc >= 250:
        points += 1.5
        reasons.append("Content depth is moderate.")
    else:
        reasons.append("Content depth is thin.")

    return ScoreBreakdown("Trust and entities", points, 20, reasons)


def score_structure(signals: PageSignals) -> ScoreBreakdown:
    points = 0.0
    reasons: list[str] = []

    h2_count = sum(1 for tag, _ in signals.headings if tag == "h2")
    h3_count = sum(1 for tag, _ in signals.headings if tag == "h3")
    if h2_count >= 2:
        points += 4
        reasons.append("H2 structure is clear.")
    elif h2_count == 1:
        points += 2
        reasons.append("Basic H2 structure exists.")
    else:
        reasons.append("Weak H2 structure.")

    if h3_count >= 2:
        points += 2
        reasons.append("Secondary structure is strong.")
    elif h3_count:
        points += 1
        reasons.append("Some secondary structure exists.")
    else:
        reasons.append("Weak secondary structure.")

    internal_count = len(signals.internal_links)
    if internal_count >= 5:
        points += 2
        reasons.append("Internal linking is healthy.")
    elif internal_count >= 1:
        points += 1
        reasons.append("Some internal linking exists.")
    else:
        reasons.append("No internal links found.")

    if len(signals.image_alts) >= 2:
        points += 2
        reasons.append("Image alt signals exist.")
    elif signals.image_alts:
        points += 1
        reasons.append("Some image alt signals exist.")
    else:
        reasons.append("No image alt signals found.")

    return ScoreBreakdown("Structure", points, 10, reasons)


def score_ai_readiness(signals: PageSignals) -> ScoreBreakdown:
    points = 0.0
    reasons: list[str] = []

    if signals.llms_txt_found:
        points += 3
        reasons.append("llms.txt was detected.")
    else:
        reasons.append("llms.txt was not detected.")

    if signals.has_faq_section or "faqpage" in signals.schema_types or "qapage" in signals.schema_types:
        points += 2
        reasons.append("FAQ or QA signal exists.")
    else:
        reasons.append("FAQ or QA signal is weak.")

    return ScoreBreakdown("AI readiness", points, 5, reasons)


def average(values: Iterable[float]) -> float:
    collected = list(values)
    if not collected:
        return 0.0
    return sum(collected) / len(collected)


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w\u4e00-\u9fff]+\b", text))


def is_question_like(text: str) -> bool:
    lowered = text.strip().lower()
    if "?" in lowered or "faq" in lowered:
        return True
    return any(lowered.startswith(word + " ") for word in QUESTION_WORDS)


def unique_domains(urls: Iterable[str]) -> set[str]:
    domains = set()
    for url in urls:
        parsed = urlparse(url)
        if parsed.netloc:
            domains.add(parsed.netloc)
    return domains


def looks_like_block_page(signals: PageSignals) -> bool:
    combined = " ".join(
        part for part in [signals.title, signals.meta_description, signals.visible_text[:500]] if part
    ).lower()
    return any(term in combined for term in BLOCK_TERMS)


def collect_suggestions(signals: PageSignals) -> list[str]:
    suggestions: list[str] = []
    if not signals.json_ld_blocks:
        suggestions.append("Add JSON-LD, at least WebPage, Article, or Organization.")
    if not signals.has_faq_section:
        suggestions.append("Add FAQ or question-style sections for extractable answers.")
    if not signals.author_mentions and not signals.schema_has_author:
        suggestions.append("Add author or editor attribution.")
    if not signals.date_mentions and not signals.schema_has_date:
        suggestions.append("Add published and updated dates.")
    if not signals.canonical:
        suggestions.append("Add a canonical URL.")
    if not signals.meta_description:
        suggestions.append("Write a summary-focused meta description.")
    if not signals.llms_txt_found:
        suggestions.append("Consider adding llms.txt at the site root.")
    if len(signals.list_items) < 3:
        suggestions.append("Turn key sections into lists for easier extraction.")
    if not signals.external_links:
        suggestions.append("Add external citations or references.")
    if not suggestions:
        suggestions.append("Strong baseline. Next step: tune paragraph length and schema detail.")
    return suggestions


def render_report(score: float, breakdowns: list[ScoreBreakdown], signals: PageSignals) -> str:
    strongest = sorted(breakdowns, key=lambda item: item.points / item.max_points, reverse=True)[:2]
    weakest = sorted(breakdowns, key=lambda item: item.points / item.max_points)[:2]
    suggestions = collect_suggestions(signals)

    lines = [
        f"AEO completeness score: {score:.1f}/10.0",
        f"Source: {signals.source}",
    ]
    if signals.fetch_warning:
        lines.append(f"Warning: {signals.fetch_warning}")
    if looks_like_block_page(signals):
        lines.append("Warning: page looks like a challenge or access-denied response.")

    lines.extend(["", "Category breakdown:"])
    for item in breakdowns:
        lines.append(f"- {item.name}: {item.points:.1f}/{item.max_points:.1f}")

    lines.extend(
        [
            "",
            "Strongest areas:",
            *(f"- {item.name}" for item in strongest),
            "",
            "Weakest areas:",
            *(f"- {item.name}" for item in weakest),
            "",
            "Priority fixes:",
            *(f"- {tip}" for tip in suggestions[:5]),
        ]
    )
    return "\n".join(lines)


def render_json(score: float, breakdowns: list[ScoreBreakdown], signals: PageSignals) -> str:
    payload = build_payload(score, breakdowns, signals)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_payload(score: float, breakdowns: list[ScoreBreakdown], signals: PageSignals) -> dict[str, object]:
    lenses = derive_lenses(breakdowns, signals)
    return {
        "score": score,
        "source": signals.source,
        "http_status": signals.http_status,
        "fetch_warning": signals.fetch_warning,
        "looks_like_block_page": looks_like_block_page(signals),
        "posture": classify_posture(score),
        "breakdown": [
            {
                "name": item.name,
                "points": round(item.points, 2),
                "max_points": item.max_points,
                "reasons": item.reasons,
            }
            for item in breakdowns
        ],
        "lenses": lenses,
        "signals": {
            "title": signals.title,
            "meta_description": signals.meta_description,
            "canonical": signals.canonical,
            "lang": signals.lang,
            "schema_types": sorted(signals.schema_types),
            "has_faq_section": signals.has_faq_section,
            "internal_links": len(signals.internal_links),
            "external_links": len(signals.external_links),
            "image_alts": len(signals.image_alts),
            "paragraphs": len(signals.paragraphs),
            "list_items": len(signals.list_items),
            "word_count": word_count(signals.visible_text),
            "llms_txt_found": signals.llms_txt_found,
        },
        "suggestions": collect_suggestions(signals),
    }


def classify_posture(score: float) -> str:
    if score >= 8.5:
        return "This page is structurally strong enough to be read, cited, and reused."
    if score >= 7.0:
        return "This page has a solid base, but a few missing signals are holding it back."
    if score >= 5.0:
        return "This page is understandable, but not consistently machine-ready."
    if score >= 3.0:
        return "This page has content, but its answer structure is still weak."
    return "This page is not yet shaped like a reusable answer."


def derive_lenses(breakdowns: list[ScoreBreakdown], signals: PageSignals) -> list[dict[str, object]]:
    breakdown_map = {item.name: item for item in breakdowns}

    tech_ratio = normalized_ratio(breakdown_map["Technical foundation"])
    schema_ratio = normalized_ratio(breakdown_map["Structured data"])
    answer_ratio = normalized_ratio(breakdown_map["Answer quality"])
    trust_ratio = normalized_ratio(breakdown_map["Trust and entities"])
    structure_ratio = normalized_ratio(breakdown_map["Structure"])
    ai_ratio = normalized_ratio(breakdown_map["AI readiness"])

    lenses = [
        {
            "name": "Extractability",
            "score": weighted_score(
                answer_ratio * 0.40
                + structure_ratio * 0.20
                + schema_ratio * 0.25
                + ai_ratio * 0.15
            ),
            "summary": summarize_extractability(signals),
        },
        {
            "name": "Resolution",
            "score": weighted_score(
                answer_ratio * 0.55
                + trust_ratio * 0.20
                + structure_ratio * 0.15
                + tech_ratio * 0.10
            ),
            "summary": summarize_resolution(signals),
        },
        {
            "name": "Citation trust",
            "score": weighted_score(
                trust_ratio * 0.60
                + schema_ratio * 0.20
                + tech_ratio * 0.10
                + ai_ratio * 0.10
            ),
            "summary": summarize_trust(signals),
        },
        {
            "name": "Surface visibility",
            "score": weighted_score(
                tech_ratio * 0.35
                + answer_ratio * 0.25
                + schema_ratio * 0.20
                + trust_ratio * 0.10
                + ai_ratio * 0.10
            ),
            "summary": summarize_visibility(signals),
        },
        {
            "name": "Content structure",
            "score": weighted_score(
                structure_ratio * 0.45
                + answer_ratio * 0.25
                + tech_ratio * 0.15
                + schema_ratio * 0.15
            ),
            "summary": summarize_structure(signals),
        },
    ]
    return lenses


def normalized_ratio(item: ScoreBreakdown) -> float:
    if item.max_points == 0:
        return 0.0
    return item.points / item.max_points


def weighted_score(value: float) -> float:
    return round(max(1.0, min(10.0, value * 10.0)), 1)


def summarize_extractability(signals: PageSignals) -> str:
    parts: list[str] = []
    if signals.json_ld_blocks:
        parts.append("schema exists")
    if signals.has_faq_section:
        parts.append("FAQ exists")
    if len(signals.list_items) >= 3:
        parts.append("list structure exists")
    if not parts:
        return "Low extraction support. Add schema, lists, and FAQ-style blocks."
    return "Good extraction shape with " + ", ".join(parts[:3]) + "."


def summarize_resolution(signals: PageSignals) -> str:
    if signals.paragraphs and len(signals.list_items) >= 3:
        return "The page gives content and comparison structure, but may still need a clearer conclusion."
    if signals.paragraphs:
        return "The page starts to answer the topic, but the decision path is still thin."
    return "The page lacks a strong answer-first body."


def summarize_trust(signals: PageSignals) -> str:
    trust_parts: list[str] = []
    if signals.author_mentions or signals.schema_has_author:
        trust_parts.append("author")
    if signals.date_mentions or signals.schema_has_date:
        trust_parts.append("date")
    if signals.organization_mentions or signals.schema_has_publisher:
        trust_parts.append("publisher")
    if len(unique_domains(signals.external_links)) >= 1:
        trust_parts.append("citations")
    if not trust_parts:
        return "Trust signals are weak. Add authorship, freshness, and verifiable references."
    return "Trust layer includes " + ", ".join(trust_parts[:4]) + "."


def summarize_visibility(signals: PageSignals) -> str:
    if signals.meta_description and signals.canonical and (signals.og_title or signals.og_description):
        return "Metadata is helping the page surface cleanly across search and social contexts."
    if signals.title:
        return "The page has some visibility signals, but metadata is incomplete."
    return "The page lacks the baseline metadata needed for broader visibility."


def summarize_structure(signals: PageSignals) -> str:
    h2_count = sum(1 for tag, _ in signals.headings if tag == "h2")
    if h2_count >= 2 and len(signals.internal_links) >= 1:
        return "The page is segmented well enough for scanning and reuse."
    if h2_count >= 1:
        return "The page has basic structure, but secondary organization is still weak."
    return "The page needs clearer sectioning and internal architecture."


def score_target(url: str | None = None, file_path: str | None = None) -> dict[str, object]:
    html, source, http_status, fetch_warning = load_input(url, file_path)
    signals = parse_page(html, source, http_status=http_status, fetch_warning=fetch_warning)
    score, breakdowns = score_page(signals)
    return build_payload(score, breakdowns, signals)


def main() -> int:
    parser = argparse.ArgumentParser(description="Score a webpage for AEO completeness.")
    parser.add_argument("--url", help="Public URL to analyze.")
    parser.add_argument("--file", help="Local HTML file to analyze.")
    parser.add_argument("--json", action="store_true", help="Return machine-readable JSON.")
    args = parser.parse_args()

    if not args.url and not args.file:
        parser.error("Provide either --url or --file.")
    if args.url and args.file:
        parser.error("Use only one of --url or --file.")

    try:
        payload = score_target(args.url, args.file)
        if args.json:
            output = json.dumps(payload, ensure_ascii=False, indent=2)
        else:
            breakdowns = [
                ScoreBreakdown(
                    name=item["name"],
                    points=float(item["points"]),
                    max_points=float(item["max_points"]),
                    reasons=list(item["reasons"]),
                )
                for item in payload["breakdown"]
            ]
            signals = PageSignals(
                source=str(payload["source"]),
                http_status=payload["http_status"],
                fetch_warning=str(payload["fetch_warning"]),
            )
            signals.meta_description = str(payload["signals"]["meta_description"])
            signals.canonical = str(payload["signals"]["canonical"])
            signals.lang = str(payload["signals"]["lang"])
            signals.llms_txt_found = bool(payload["signals"]["llms_txt_found"])
            signals.has_faq_section = bool(payload["signals"]["has_faq_section"])
            output = render_report(float(payload["score"]), breakdowns, signals)
        print(output)
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
