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
from collections.abc import Callable
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

DECISION_TERMS = (
    "recommend",
    "recommended",
    "best",
    "should choose",
    "worth it",
    "pick",
    "ideal",
    "top choice",
    "建議",
    "推薦",
    "最適合",
    "最好",
    "首選",
    "值得",
    "怎麼選",
)

SCENARIO_TERMS = (
    "if you",
    "for teams",
    "for beginners",
    "for small",
    "for side sleepers",
    "depending on",
    "if your",
    "如果",
    "若你",
    "適合",
    "適用",
    "對於",
    "想要",
    "需要",
    "預算",
)

TRADEOFF_TERMS = (
    "however",
    "but",
    "on the other hand",
    "compared",
    "vs",
    "versus",
    "pros",
    "cons",
    "trade-off",
    "取捨",
    "比較",
    "差異",
    "優點",
    "缺點",
    "但",
    "不過",
)

NEXT_STEP_TERMS = (
    "start with",
    "choose",
    "buy",
    "book",
    "sign up",
    "contact",
    "try",
    "go with",
    "從",
    "開始",
    "選擇",
    "購買",
    "預約",
    "申請",
    "先從",
)

HIGH_RISK_TERMS = (
    "insurance",
    "loan",
    "mortgage",
    "investment",
    "credit card",
    "tax",
    "retirement",
    "legal",
    "lawyer",
    "attorney",
    "medical",
    "symptom",
    "treatment",
    "diagnosis",
    "drug",
    "保險",
    "貸款",
    "投資",
    "信用卡",
    "稅",
    "法律",
    "律師",
    "醫療",
    "症狀",
    "治療",
    "診斷",
    "藥",
)

MEDIUM_RISK_TERMS = (
    "travel insurance",
    "supplement",
    "safety",
    "warranty",
    "certification",
    "認證",
    "安全",
    "保固",
    "比較",
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


@dataclass
class AuditCheck:
    key: str
    title: str
    category: str
    severity: str
    description: str
    fix: str
    predicate: Callable[["PageSignals"], bool]


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
        score_discovery_and_indexability(signals),
        score_machine_readability(signals),
        score_answer_extractability(signals),
        score_trust_and_citation(signals),
        score_added_value(signals),
        score_task_resolution(signals),
    ]
    raw = sum(item.points for item in breakdowns)
    total = sum(item.max_points for item in breakdowns) or 100.0
    normalized = 1.0 + (raw / total) * 9.0
    return round(min(10.0, max(1.0, normalized)), 1), breakdowns


def score_discovery_and_indexability(signals: PageSignals) -> ScoreBreakdown:
    points = 0.0
    reasons: list[str] = []

    title_len = len(signals.title)
    if 30 <= title_len <= 65:
        points += 2
        reasons.append("Title gives a usable discovery signal.")
    elif signals.title:
        points += 1
        reasons.append("Title exists but is not yet ideal for discovery.")
    else:
        reasons.append("Missing title.")

    desc_len = len(signals.meta_description)
    if 80 <= desc_len <= 180:
        points += 2
        reasons.append("Meta description supports clean snippet generation.")
    elif signals.meta_description:
        points += 1
        reasons.append("Meta description exists but can be sharper.")
    else:
        reasons.append("Missing meta description.")

    if signals.canonical:
        points += 2
        reasons.append("Canonical is present.")
    else:
        reasons.append("Missing canonical.")

    if signals.lang:
        points += 1
        reasons.append("HTML lang is present.")
    else:
        reasons.append("Missing HTML lang.")

    if signals.http_status is None or 200 <= signals.http_status < 300:
        points += 3
        reasons.append("Fetch status is index-friendly.")
    else:
        reasons.append("Fetch status may block normal discovery.")

    if "noindex" not in signals.robots:
        points += 3
        reasons.append("No noindex directive detected.")
    else:
        reasons.append("Page appears to be noindex.")

    if signals.og_title and signals.og_description:
        points += 2
        reasons.append("Open Graph summary fields exist.")
    elif signals.og_title or signals.og_description:
        points += 1
        reasons.append("Open Graph is partial.")
    else:
        reasons.append("Missing Open Graph summary fields.")

    if signals.llms_txt_found:
        points += 1
        reasons.append("llms.txt exists, but this is only a minor discovery signal.")
    else:
        reasons.append("llms.txt is absent, but this is not a core blocker.")

    return ScoreBreakdown("Discovery and indexability", points, 15, reasons)


def score_machine_readability(signals: PageSignals) -> ScoreBreakdown:
    points = 0.0
    reasons: list[str] = []

    if signals.json_ld_blocks:
        points += 6
        reasons.append("JSON-LD was found.")
    else:
        reasons.append("No JSON-LD found.")

    if signals.schema_types:
        points += min(5, 2 + len(signals.schema_types))
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
        points += min(3, schema_detail_hits * 1.0)
        reasons.append("Schema includes author, publisher, or date details.")
    else:
        reasons.append("Schema lacks author, publisher, and date detail.")

    h1s = [text for tag, text in signals.headings if tag == "h1"]
    if h1s:
        points += 2
        reasons.append("Page has an H1.")
    else:
        reasons.append("Missing H1.")

    h2_count = sum(1 for tag, _ in signals.headings if tag == "h2")
    h3_count = sum(1 for tag, _ in signals.headings if tag == "h3")
    if h2_count >= 2:
        points += 2
        reasons.append("H2 structure is clear.")
    elif h2_count == 1:
        points += 1
        reasons.append("Basic H2 structure exists.")
    else:
        reasons.append("Weak H2 structure.")

    if h3_count >= 2:
        points += 1
        reasons.append("Secondary structure is strong.")
    elif h3_count:
        points += 0.5
        reasons.append("Some secondary structure exists.")
    else:
        reasons.append("Weak secondary structure.")

    if len(signals.internal_links) >= 3:
        points += 1
        reasons.append("Internal linking supports machine understanding.")
    elif signals.internal_links:
        points += 0.5
        reasons.append("Some internal linking exists.")
    else:
        reasons.append("No internal links found.")

    if len(signals.image_alts) >= 2:
        points += 1
        reasons.append("Image alt signals exist.")
    elif signals.image_alts:
        points += 0.5
        reasons.append("Some image alt signals exist.")
    else:
        reasons.append("No image alt signals found.")

    return ScoreBreakdown("Machine readability", points, 20, reasons)


def score_answer_extractability(signals: PageSignals) -> ScoreBreakdown:
    points = 0.0
    reasons: list[str] = []

    first_paragraph = signals.paragraphs[0] if signals.paragraphs else ""
    first_word_count = word_count(first_paragraph)
    if 35 <= first_word_count <= 90:
        points += 4
        reasons.append("Opening paragraph is answer-snippet friendly.")
    elif first_paragraph:
        points += 2
        reasons.append("Opening paragraph exists but is not strongly answer-first.")
    else:
        reasons.append("Missing a clear body opening paragraph.")

    question_headings = sum(1 for _, text in signals.headings if is_question_like(text))
    if question_headings >= 2 or signals.has_faq_section:
        points += 3
        reasons.append("Page has FAQ or question-driven headings.")
    elif question_headings == 1:
        points += 1.5
        reasons.append("Page has at least one question-driven heading.")
    else:
        reasons.append("Missing FAQ or question-driven sections.")

    if len(signals.list_items) >= 3:
        points += 3
        reasons.append("Bulleted content exists and is extractable.")
    elif signals.list_items:
        points += 1.5
        reasons.append("Some list content exists.")
    else:
        reasons.append("Missing list-style content.")

    if signals.has_table:
        points += 1.5
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

    if len(signals.headings) >= 4:
        points += 1.5
        reasons.append("The page has enough heading chunks to be reusable.")
    elif signals.headings:
        points += 0.5
        reasons.append("The page has some heading chunking.")
    else:
        reasons.append("The page lacks reusable heading chunks.")

    return ScoreBreakdown("Answer extractability", points, 15, reasons)


def score_trust_and_citation(signals: PageSignals) -> ScoreBreakdown:
    points = 0.0
    reasons: list[str] = []

    if signals.author_mentions or signals.schema_has_author:
        points += 3
        reasons.append("Author signal exists.")
    else:
        reasons.append("Missing author signal.")

    if signals.date_mentions or signals.schema_has_date:
        points += 3
        reasons.append("Publish or update date exists.")
    else:
        reasons.append("Missing freshness signal.")

    external_domains = unique_domains(signals.external_links)
    if len(external_domains) >= 2:
        points += 3
        reasons.append("Page cites multiple external domains.")
    elif external_domains:
        points += 1.5
        reasons.append("Page cites at least one external domain.")
    else:
        reasons.append("Missing external citation signals.")

    if signals.organization_mentions or signals.schema_has_publisher:
        points += 2
        reasons.append("Publisher or organization signal exists.")
    else:
        reasons.append("Missing publisher or organization signal.")

    wc = word_count(signals.visible_text)
    if wc >= 600:
        points += 2
        reasons.append("Content depth is substantial.")
    elif wc >= 250:
        points += 1
        reasons.append("Content depth is moderate.")
    else:
        reasons.append("Content depth is thin.")

    topic_risk = classify_topic_risk(signals)
    if topic_risk == "high":
        reasons.append("High-risk topic detected; the trust bar is higher.")
        if not (signals.author_mentions or signals.schema_has_author):
            points -= 1.5
        if not (signals.date_mentions or signals.schema_has_date):
            points -= 1.5
        if len(external_domains) == 0:
            points -= 1.5
    elif topic_risk == "medium":
        reasons.append("Medium-risk topic detected; trust signals still matter.")
        if len(external_domains) == 0:
            points -= 0.5

    return ScoreBreakdown("Trust and citation", max(0.0, points), 15, reasons)


def score_added_value(signals: PageSignals) -> ScoreBreakdown:
    points = 0.0
    reasons: list[str] = []

    specificity = count_specificity_markers(signals)
    if specificity >= 8:
        points += 5
        reasons.append("The page uses concrete details, numbers, or constraints.")
    elif specificity >= 4:
        points += 3
        reasons.append("The page includes some specific detail.")
    else:
        reasons.append("The page lacks enough concrete specifics.")

    if has_tradeoff_signal(signals):
        points += 4
        reasons.append("The page explains trade-offs instead of listing features only.")
    else:
        reasons.append("The page does not surface clear trade-offs.")

    if signals.has_table or len(signals.list_items) >= 3:
        points += 3
        reasons.append("The page synthesizes information into reusable structures.")
    else:
        reasons.append("The page does not yet synthesize information into comparison structures.")

    if visible_word_count(signals) >= 600 and external_domain_count(signals) >= 1:
        points += 2
        reasons.append("The page combines depth with some evidence.")
    elif visible_word_count(signals) >= 300:
        points += 1
        reasons.append("The page has moderate detail.")
    else:
        reasons.append("The page still feels thin on original or synthesized detail.")

    if signals.date_mentions or signals.schema_has_date:
        points += 1
        reasons.append("Visible freshness helps the page carry current value.")

    return ScoreBreakdown("Added value", points, 15, reasons)


def score_task_resolution(signals: PageSignals) -> ScoreBreakdown:
    points = 0.0
    reasons: list[str] = []

    if has_conclusion_first_signal(signals):
        points += 5
        reasons.append("The page surfaces a conclusion early.")
    else:
        reasons.append("The page does not state the answer early enough.")

    if has_recommendation_signal(signals):
        points += 4
        reasons.append("The page makes a recommendation, not just an observation.")
    else:
        reasons.append("The page does not clearly recommend or choose.")

    if has_scenario_split_signal(signals):
        points += 4
        reasons.append("The page differentiates by audience or use case.")
    else:
        reasons.append("The page does not split the answer by scenario or persona.")

    if has_tradeoff_signal(signals):
        points += 4
        reasons.append("The page clarifies trade-offs.")
    else:
        reasons.append("The page does not make trade-offs explicit.")

    if has_next_step_signal(signals):
        points += 3
        reasons.append("The page gives an actionable next step.")
    else:
        reasons.append("The page does not guide the next action clearly.")

    return ScoreBreakdown("Task resolution", points, 20, reasons)


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
    if not has_conclusion_first_signal(signals):
        suggestions.append("State the answer or recommendation in the first 1 to 2 paragraphs.")
    if not has_recommendation_signal(signals):
        suggestions.append("Make the page choose, recommend, or rank instead of only describing options.")
    if not has_scenario_split_signal(signals):
        suggestions.append("Split the advice by scenario, budget, or user type.")
    if not has_tradeoff_signal(signals):
        suggestions.append("Explain trade-offs, not just features.")
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
    if classify_topic_risk(signals) == "high" and not signals.external_links:
        suggestions.append("For high-risk topics, support claims with visible citations and stronger authorship.")
    if len(signals.list_items) < 3:
        suggestions.append("Turn key sections into lists for easier extraction.")
    if not signals.external_links:
        suggestions.append("Add external citations or references.")
    if count_specificity_markers(signals) < 4:
        suggestions.append("Add concrete numbers, constraints, prices, or dated specifics to create real added value.")
    if not signals.llms_txt_found:
        suggestions.append("Consider adding llms.txt at the site root, but do not treat it as a core ranking fix.")
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
    audit = run_issue_audit(signals)
    return {
        "score": score,
        "source": signals.source,
        "http_status": signals.http_status,
        "fetch_warning": signals.fetch_warning,
        "looks_like_block_page": looks_like_block_page(signals),
        "posture": classify_posture(score),
        "audit": audit,
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
            "topic_risk": classify_topic_risk(signals),
            "conclusion_first": has_conclusion_first_signal(signals),
            "recommendation_signal": has_recommendation_signal(signals),
            "scenario_split": has_scenario_split_signal(signals),
            "tradeoff_signal": has_tradeoff_signal(signals),
            "next_step_signal": has_next_step_signal(signals),
            "specificity_markers": count_specificity_markers(signals),
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

    discovery_ratio = normalized_ratio(breakdown_map["Discovery and indexability"])
    readability_ratio = normalized_ratio(breakdown_map["Machine readability"])
    extractability_ratio = normalized_ratio(breakdown_map["Answer extractability"])
    trust_ratio = normalized_ratio(breakdown_map["Trust and citation"])
    added_value_ratio = normalized_ratio(breakdown_map["Added value"])
    resolution_ratio = normalized_ratio(breakdown_map["Task resolution"])

    lenses = [
        {
            "name": "Extractability",
            "score": weighted_score(
                readability_ratio * 0.40
                + extractability_ratio * 0.45
                + discovery_ratio * 0.15
            ),
            "summary": summarize_extractability(signals),
        },
        {
            "name": "Resolution",
            "score": weighted_score(
                resolution_ratio * 0.60
                + extractability_ratio * 0.20
                + added_value_ratio * 0.20
            ),
            "summary": summarize_resolution(signals),
        },
        {
            "name": "Citation trust",
            "score": weighted_score(
                trust_ratio * 0.60
                + discovery_ratio * 0.15
                + readability_ratio * 0.10
                + added_value_ratio * 0.15
            ),
            "summary": summarize_trust(signals),
        },
        {
            "name": "Surface visibility",
            "score": weighted_score(
                discovery_ratio * 0.40
                + readability_ratio * 0.25
                + extractability_ratio * 0.15
                + trust_ratio * 0.10
                + resolution_ratio * 0.10
            ),
            "summary": summarize_visibility(signals),
        },
        {
            "name": "Added value",
            "score": weighted_score(
                added_value_ratio * 0.60
                + trust_ratio * 0.10
                + extractability_ratio * 0.15
                + resolution_ratio * 0.15
            ),
            "summary": summarize_added_value(signals),
        },
    ]
    return lenses


def normalized_ratio(item: ScoreBreakdown) -> float:
    if item.max_points == 0:
        return 0.0
    return item.points / item.max_points


def weighted_score(value: float) -> float:
    return round(max(1.0, min(10.0, value * 10.0)), 1)


def first_blocks_text(signals: PageSignals, count: int = 2) -> str:
    parts = signals.paragraphs[:count]
    if not parts:
        parts = [text for _, text in signals.headings[:count]]
    return " ".join(parts).lower()


def has_any_term(text: str, terms: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


def has_conclusion_first_signal(signals: PageSignals) -> bool:
    opening = first_blocks_text(signals, 2)
    return bool(opening) and has_any_term(opening, DECISION_TERMS)


def has_recommendation_signal(signals: PageSignals) -> bool:
    window = " ".join(signals.paragraphs[:4] + signals.list_items[:6]).lower()
    return has_any_term(window, DECISION_TERMS)


def has_scenario_split_signal(signals: PageSignals) -> bool:
    blocks = " ".join([text for _, text in signals.headings[:8]] + signals.paragraphs[:5] + signals.list_items[:8]).lower()
    return has_any_term(blocks, SCENARIO_TERMS)


def has_tradeoff_signal(signals: PageSignals) -> bool:
    window = " ".join([text for _, text in signals.headings[:10]] + signals.paragraphs[:8] + signals.list_items[:8]).lower()
    return has_any_term(window, TRADEOFF_TERMS)


def has_next_step_signal(signals: PageSignals) -> bool:
    body = " ".join(signals.paragraphs[-3:] + signals.list_items[-6:]).lower()
    return has_any_term(body, NEXT_STEP_TERMS)


def count_specificity_markers(signals: PageSignals) -> int:
    text = signals.visible_text[:4000]
    patterns = [
        r"\$\d+",
        r"\d+\s?(?:usd|eur|gbp|ntd|twd|kg|km|gb|tb|w|hz|mah|inch|坪|元|年|月|天|人)",
        r"\d+%",
        r"\b20\d{2}\b",
        r"\bunder\s+\$?\d+",
        r"\bbelow\s+\$?\d+",
    ]
    total = 0
    for pattern in patterns:
        total += len(re.findall(pattern, text, flags=re.IGNORECASE))
    return total


def classify_topic_risk(signals: PageSignals) -> str:
    text = (signals.title + " " + " ".join(text for _, text in signals.headings[:8]) + " " + signals.visible_text[:1500]).lower()
    if has_any_term(text, HIGH_RISK_TERMS):
        return "high"
    if has_any_term(text, MEDIUM_RISK_TERMS):
        return "medium"
    return "low"


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
    if has_conclusion_first_signal(signals) and has_tradeoff_signal(signals):
        return "The page starts with a point of view and explains trade-offs."
    if has_conclusion_first_signal(signals):
        return "The page starts to resolve the query, but the decision path is still incomplete."
    return "The page does not state the answer early enough."


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
    topic_risk = classify_topic_risk(signals)
    suffix = " High-risk topic detected." if topic_risk == "high" else ""
    return "Trust layer includes " + ", ".join(trust_parts[:4]) + "." + suffix


def summarize_visibility(signals: PageSignals) -> str:
    if signals.meta_description and signals.canonical and (signals.og_title or signals.og_description):
        return "Metadata is helping the page surface cleanly across search and social contexts."
    if signals.title:
        return "The page has some visibility signals, but metadata is incomplete."
    return "The page lacks the baseline metadata needed for broader visibility."


def summarize_added_value(signals: PageSignals) -> str:
    if count_specificity_markers(signals) >= 8 and has_tradeoff_signal(signals):
        return "The page uses concrete specifics and trade-offs, which feels more like added value."
    if count_specificity_markers(signals) >= 4:
        return "The page includes some concrete detail, but the synthesis layer can be stronger."
    return "The page still reads more like generic information than a value-added answer."


def heading_count(signals: PageSignals, level: str) -> int:
    return sum(1 for tag, _ in signals.headings if tag == level)


def visible_word_count(signals: PageSignals) -> int:
    return word_count(signals.visible_text)


def external_domain_count(signals: PageSignals) -> int:
    return len(unique_domains(signals.external_links))


def get_issue_catalog() -> list[AuditCheck]:
    return [
        AuditCheck("title_missing", "Missing title", "technical", "critical", "The page does not expose a title.", "Add a clear title tag.", lambda s: not s.title),
        AuditCheck("title_short", "Title too short", "technical", "medium", "Short titles are less descriptive in search and AI surfaces.", "Expand the title to describe the page outcome.", lambda s: bool(s.title) and len(s.title) < 30),
        AuditCheck("title_long", "Title too long", "technical", "medium", "Long titles are harder to surface cleanly.", "Trim the title to a tighter outcome-led version.", lambda s: len(s.title) > 65),
        AuditCheck("meta_missing", "Missing meta description", "technical", "high", "The page is missing a summary snippet.", "Write a concise summary-oriented meta description.", lambda s: not s.meta_description),
        AuditCheck("meta_short", "Meta description too short", "technical", "low", "Short descriptions often undersell the page.", "Expand the description to summarize the page answer.", lambda s: bool(s.meta_description) and len(s.meta_description) < 70),
        AuditCheck("meta_long", "Meta description too long", "technical", "low", "Long descriptions lose clarity.", "Trim the description to the most useful promise.", lambda s: len(s.meta_description) > 180),
        AuditCheck("canonical_missing", "Missing canonical", "technical", "high", "Canonical signals are missing.", "Add a canonical URL.", lambda s: not s.canonical),
        AuditCheck("lang_missing", "Missing HTML lang", "technical", "medium", "Language metadata is missing.", "Add the correct lang attribute on the html tag.", lambda s: not s.lang),
        AuditCheck("robots_noindex", "Page marked noindex", "technical", "critical", "The page appears blocked from indexability.", "Remove noindex if the page should be discoverable.", lambda s: "noindex" in s.robots),
        AuditCheck("og_title_missing", "Missing Open Graph title", "technical", "medium", "The page lacks an OG title.", "Add og:title metadata.", lambda s: not s.og_title),
        AuditCheck("og_description_missing", "Missing Open Graph description", "technical", "medium", "The page lacks an OG description.", "Add og:description metadata.", lambda s: not s.og_description),
        AuditCheck("og_bundle_missing", "Open Graph not configured", "technical", "low", "The page has no complete Open Graph summary layer.", "Add both og:title and og:description.", lambda s: not s.og_title and not s.og_description),
        AuditCheck("jsonld_missing", "Missing JSON-LD", "schema", "high", "Structured data is absent.", "Add JSON-LD using a relevant schema type.", lambda s: not s.json_ld_blocks),
        AuditCheck("schema_type_missing", "No relevant schema type", "schema", "high", "No useful schema type was detected.", "Add WebPage, Article, Product, FAQPage, or another relevant type.", lambda s: not s.schema_types),
        AuditCheck("schema_author_missing", "Schema missing author", "schema", "medium", "The schema layer does not name an author.", "Add author to structured data where relevant.", lambda s: s.json_ld_blocks and not s.schema_has_author),
        AuditCheck("schema_publisher_missing", "Schema missing publisher", "schema", "medium", "The schema layer does not name a publisher.", "Add publisher to structured data.", lambda s: s.json_ld_blocks and not s.schema_has_publisher),
        AuditCheck("schema_date_missing", "Schema missing date", "schema", "medium", "Structured data has no freshness field.", "Add datePublished or dateModified.", lambda s: s.json_ld_blocks and not s.schema_has_date),
        AuditCheck("faq_schema_missing", "Missing FAQ or QA schema", "schema", "low", "No FAQPage or QAPage schema was found.", "Use FAQPage or QAPage where the content fits.", lambda s: "faqpage" not in s.schema_types and "qapage" not in s.schema_types),
        AuditCheck("breadcrumb_schema_missing", "Missing breadcrumb schema", "schema", "low", "Breadcrumb schema was not detected.", "Add breadcrumb schema if the page sits in a content hierarchy.", lambda s: "breadcrumblist" not in s.schema_types),
        AuditCheck("page_schema_missing", "Missing page-level schema", "schema", "low", "No WebPage or Article-like schema is present.", "Add a page-level schema type to frame the document.", lambda s: not ({"webpage", "article", "blogposting", "newsarticle"} & s.schema_types)),
        AuditCheck("h1_missing", "Missing H1", "answer", "high", "The page lacks a primary heading.", "Add one clear H1 that matches the page intent.", lambda s: heading_count(s, "h1") == 0),
        AuditCheck("h2_missing", "Missing H2 sections", "answer", "medium", "The page lacks section anchors.", "Add H2 sections for the main ideas or decision criteria.", lambda s: heading_count(s, "h2") == 0),
        AuditCheck("h3_missing", "Missing H3 depth", "answer", "low", "The page has limited secondary structure.", "Add H3 headings where subtopics need chunking.", lambda s: heading_count(s, "h3") == 0),
        AuditCheck("question_heading_missing", "No question-style headings", "answer", "medium", "The page is not framed around extractable questions.", "Add question-style subheads or FAQ blocks.", lambda s: not any(is_question_like(text) for _, text in s.headings)),
        AuditCheck("faq_missing", "Missing FAQ section", "answer", "medium", "The page has no FAQ section.", "Add an FAQ section to capture recurring objections.", lambda s: not s.has_faq_section),
        AuditCheck("list_missing", "Missing list structure", "answer", "medium", "The page lacks bullet-style answer chunks.", "Turn key comparison or takeaway sections into lists.", lambda s: len(s.list_items) == 0),
        AuditCheck("list_thin", "List structure is thin", "answer", "low", "The page has only a small amount of list structure.", "Expand comparison or takeaway lists.", lambda s: 0 < len(s.list_items) < 3),
        AuditCheck("table_missing", "Missing comparison table", "answer", "low", "No table was found for structured comparison.", "Add a table when the page compares options or specs.", lambda s: not s.has_table),
        AuditCheck("opening_missing", "Missing clear opening paragraph", "answer", "high", "The page lacks a strong opening answer block.", "Add a top paragraph that states the answer or recommendation.", lambda s: len(s.paragraphs) == 0),
        AuditCheck("paragraph_count_low", "Too few body paragraphs", "answer", "medium", "The page has thin paragraph structure.", "Add more explanatory paragraphs around key decisions.", lambda s: 0 < len(s.paragraphs) < 3),
        AuditCheck("content_thin", "Content depth is thin", "answer", "medium", "The page may not have enough depth to support citation or decision-making.", "Add more original analysis, comparisons, and supporting detail.", lambda s: visible_word_count(s) < 300),
        AuditCheck("content_not_deep", "Content depth is not substantial", "answer", "low", "The page may still feel lightweight for high-intent topics.", "Add deeper sections for edge cases, trade-offs, or FAQs.", lambda s: 300 <= visible_word_count(s) < 600),
        AuditCheck("author_missing", "Missing author signal", "trust", "high", "No author signal was detected.", "Add author attribution in page copy or schema.", lambda s: not (s.author_mentions or s.schema_has_author)),
        AuditCheck("date_missing", "Missing publish or update date", "trust", "high", "Freshness is not visible.", "Add published and updated dates.", lambda s: not (s.date_mentions or s.schema_has_date)),
        AuditCheck("publisher_missing", "Missing publisher signal", "trust", "medium", "The publishing entity is unclear.", "Add brand or publisher information in copy or schema.", lambda s: not (s.organization_mentions or s.schema_has_publisher)),
        AuditCheck("external_citations_missing", "Missing external citations", "trust", "medium", "The page does not point to supporting outside sources.", "Add references or source links for key claims.", lambda s: external_domain_count(s) == 0),
        AuditCheck("external_citations_low", "Low citation diversity", "trust", "low", "The page cites only one external domain.", "Add a wider base of references if claims depend on trust.", lambda s: external_domain_count(s) == 1),
        AuditCheck("internal_links_missing", "Missing internal links", "structure", "medium", "The page has no internal pathways to related content.", "Add internal links to related workflows, guides, or product pages.", lambda s: len(s.internal_links) == 0),
        AuditCheck("internal_links_low", "Internal linking is thin", "structure", "low", "The page has only a small amount of internal linking.", "Add more internal links to deepen the information architecture.", lambda s: 0 < len(s.internal_links) < 3),
        AuditCheck("image_alt_missing", "Missing image alt text", "structure", "medium", "No image alt signals were found.", "Add meaningful alt text to informative images.", lambda s: len(s.image_alts) == 0),
        AuditCheck("image_alt_low", "Image alt coverage is low", "structure", "low", "Only a small amount of image alt text was found.", "Expand alt coverage on important images or diagrams.", lambda s: 0 < len(s.image_alts) < 2),
        AuditCheck("secondary_structure_missing", "Secondary structure is weak", "structure", "medium", "The page lacks multi-level sectioning.", "Use H2 and H3 headings to separate major and minor ideas.", lambda s: heading_count(s, "h2") < 2 and heading_count(s, "h3") < 2),
        AuditCheck("extractable_units_missing", "Missing extractable answer units", "ai", "high", "The page is not broken into reusable answer chunks.", "Add lists, FAQs, or comparison blocks.", lambda s: len(s.list_items) == 0 and not s.has_table and not s.has_faq_section),
        AuditCheck("llmstxt_missing", "Missing llms.txt", "ai", "low", "No llms.txt file was detected.", "Consider publishing llms.txt at the site root.", lambda s: not s.llms_txt_found),
        AuditCheck("ai_qa_signal_missing", "Weak AI question-answer signal", "ai", "medium", "The page lacks explicit QA framing.", "Add FAQ or question-led sections.", lambda s: not s.has_faq_section and not any(is_question_like(text) for _, text in s.headings)),
        AuditCheck("answer_decision_support_low", "Weak decision-support structure", "ai", "medium", "The page may be informative but not strongly decision-ready.", "Add comparisons, criteria, and a recommendation path.", lambda s: not s.has_table and len(s.list_items) < 3),
        AuditCheck("conclusion_first_missing", "Answer is not stated early", "resolution", "high", "The page does not state its conclusion in the opening blocks.", "Put the recommendation or decision in the first 1 to 2 paragraphs.", lambda s: not has_conclusion_first_signal(s)),
        AuditCheck("recommendation_missing", "No clear recommendation", "resolution", "high", "The page describes the topic but does not clearly choose or recommend.", "Add a recommendation, ranking, or pick-by-scenario conclusion.", lambda s: not has_recommendation_signal(s)),
        AuditCheck("scenario_split_missing", "No scenario split", "resolution", "medium", "The page does not adapt the answer by audience, use case, or budget.", "Split the answer by use case, budget, or user type.", lambda s: not has_scenario_split_signal(s)),
        AuditCheck("tradeoff_missing", "Trade-offs are not explicit", "resolution", "medium", "The page does not explain what the reader gains or gives up.", "Add pros, cons, and trade-off framing.", lambda s: not has_tradeoff_signal(s)),
        AuditCheck("next_step_missing", "No next action", "resolution", "low", "The page does not tell the reader what to do next.", "Add a direct next step or choice path.", lambda s: not has_next_step_signal(s)),
        AuditCheck("specificity_low", "Low specificity", "value", "medium", "The page lacks enough concrete detail to feel genuinely useful.", "Add prices, limits, dates, specs, or other concrete constraints.", lambda s: count_specificity_markers(s) < 4),
        AuditCheck("specificity_moderate", "Specificity could be stronger", "value", "low", "The page has some specifics, but not enough to feel differentiated.", "Add more concrete numbers and constraints.", lambda s: 4 <= count_specificity_markers(s) < 8),
        AuditCheck("risk_trust_gap", "High-risk topic with weak trust stack", "trust", "critical", "This looks like a high-risk topic, but trust signals are incomplete.", "For high-risk topics, add author, date, publisher, and citations together.", lambda s: classify_topic_risk(s) == "high" and sum([bool(s.author_mentions or s.schema_has_author), bool(s.date_mentions or s.schema_has_date), bool(s.organization_mentions or s.schema_has_publisher), external_domain_count(s) >= 1]) <= 2),
        AuditCheck("trust_stack_thin", "Trust stack is thin", "trust", "medium", "Too many trust signals are missing at once.", "Add author, date, publisher, and references as a stack.", lambda s: sum([bool(s.author_mentions or s.schema_has_author), bool(s.date_mentions or s.schema_has_date), bool(s.organization_mentions or s.schema_has_publisher), external_domain_count(s) >= 1]) <= 1),
        AuditCheck("metadata_stack_thin", "Metadata stack is thin", "technical", "medium", "The page is missing too many metadata layers at once.", "Complete title, meta description, canonical, and OG coverage.", lambda s: sum([bool(s.title), bool(s.meta_description), bool(s.canonical), bool(s.og_title or s.og_description)]) <= 1),
    ]


def run_issue_audit(signals: PageSignals) -> dict[str, object]:
    catalog = get_issue_catalog()
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    issues = []
    for check in catalog:
        if check.predicate(signals):
            issues.append(
                {
                    "key": check.key,
                    "title": check.title,
                    "category": check.category,
                    "severity": check.severity,
                    "description": check.description,
                    "fix": check.fix,
                }
            )
    issues.sort(key=lambda item: (severity_order[item["severity"]], item["category"], item["title"]))
    return {
        "checks_run": len(catalog),
        "issues_found": len(issues),
        "issues": issues,
    }


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
        html, source, http_status, fetch_warning = load_input(args.url, args.file)
        signals = parse_page(html, source, http_status=http_status, fetch_warning=fetch_warning)
        score, breakdowns = score_page(signals)
        payload = build_payload(score, breakdowns, signals)
        if args.json:
            output = json.dumps(payload, ensure_ascii=False, indent=2)
        else:
            output = render_report(score, breakdowns, signals)
        print(output)
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
