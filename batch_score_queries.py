#!/usr/bin/env python3
"""Batch search and score query results for AI SEO / AEO readiness."""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from aeo_score import (
    build_payload,
    collect_suggestions,
    has_conclusion_first_signal,
    has_recommendation_signal,
    has_scenario_split_signal,
    has_tradeoff_signal,
    load_input,
    looks_like_block_page,
    parse_page,
    score_page,
)


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = BASE_DIR / "aeo_queries_template.csv"
OUTPUT_DIR = BASE_DIR / "results"
DETAILS_JSON = OUTPUT_DIR / "aeo_scored_results.json"
RESULTS_CSV = OUTPUT_DIR / "aeo_scored_results.csv"
SUMMARY_CSV = OUTPUT_DIR / "aeo_query_summary.csv"
PLAYBOOK_MD = OUTPUT_DIR / "ai_seo_playbook.md"

RESULT_MODE_MAP = {"top1": 1, "top3": 3, "top5": 5}
FIELD_ALIASES = {
    "query_id": ("編號", "id", "query_id"),
    "query": ("題目", "query"),
    "language": ("語言", "language"),
    "region": ("地區", "region"),
    "result_mode": ("結果模式", "result_mode"),
    "notes": ("備註", "notes"),
}

EN_STOPWORDS = {
    "a", "an", "and", "are", "best", "better", "for", "from", "i", "if", "in",
    "is", "it", "more", "my", "of", "or", "should", "than", "that", "the", "to",
    "use", "using", "vs", "what", "where", "which", "with", "worth",
}

CJK_FILLERS = (
    "哪台", "哪個", "哪一家", "哪些", "比較", "適合", "如何", "怎麼", "值不值得",
    "值得買", "還是", "跟", "和", "與", "可以", "通常", "內", "怎麼挑", "怎麼選",
    "要選", "預算", "送禮", "買", "的",
)

UGC_DOMAIN_HINTS = (
    "reddit.com", "zhihu.com", "ptt.cc", "dcard.tw", "quora.com", "forum",
    "bbs.", "baidu.com",
)

EN_QUERY_PREFIX_PATTERNS = (
    r"^what is the best\s+",
    r"^what is\s+",
    r"^which\s+",
    r"^where should i\s+",
    r"^where can i\s+",
    r"^is\s+",
    r"^how do i\s+",
    r"^how to\s+",
    r"^what are\s+",
)

SEARCH_QUERY_FILLERS = (
    "哪裡可以", "哪裡", "哪些", "哪個", "哪台", "怎麼挑", "怎麼選", "怎麼",
    "如何", "值不值得", "比較適合", "容易買到不踩雷", "又不會太高", "有沒有",
)


@dataclass
class QueryRow:
    query_id: str
    query: str
    language: str
    region: str
    result_mode: str
    result_count: int
    notes: str


@dataclass
class SearchItem:
    rank: int
    title: str
    url: str
    description: str
    provider: str
    search_relevance: float = 0.0
    rerank_position: int = 0


class DuckDuckGoHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[SearchItem] = []
        self._current_url = ""
        self._title_parts: list[str] = []
        self._snippet_parts: list[str] = []
        self._title_depth = 0
        self._snippet_depth = 0

    def _flush(self) -> None:
        title = " ".join(self._title_parts).strip()
        snippet = " ".join(self._snippet_parts).strip()
        url = normalize_duckduckgo_url(self._current_url)
        if title and url:
            self.results.append(
                SearchItem(
                    rank=len(self.results) + 1,
                    title=unescape(title),
                    url=url,
                    description=unescape(snippet),
                    provider="duckduckgo-html",
                )
            )
        self._current_url = ""
        self._title_parts = []
        self._snippet_parts = []
        self._title_depth = 0
        self._snippet_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: (value or "") for key, value in attrs}
        classes = attr_map.get("class", "")
        if tag == "a" and "result__a" in classes:
            self._flush()
            self._current_url = attr_map.get("href", "")
            self._title_depth = 1
            return
        if self._title_depth:
            self._title_depth += 1
        if "result__snippet" in classes:
            self._snippet_depth = 1
            return
        if self._snippet_depth:
            self._snippet_depth += 1

    def handle_endtag(self, _tag: str) -> None:
        if self._title_depth:
            self._title_depth -= 1
        if self._snippet_depth:
            self._snippet_depth -= 1

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split()).strip()
        if not text:
            return
        if self._title_depth:
            self._title_parts.append(text)
        if self._snippet_depth:
            self._snippet_parts.append(text)

    def close(self) -> None:
        super().close()
        self._flush()


def clean_html_fragment(value: str) -> str:
    stripped = re.sub(r"<[^>]+>", " ", value)
    return unescape(re.sub(r"\s+", " ", stripped)).strip()


def fetch_text(url: str, *, accept_html: bool = True) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9,zh-TW;q=0.8",
        "Cache-Control": "no-cache",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"
        if accept_html else "application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.8",
    }
    request = Request(url, headers=headers)
    with urlopen(request, timeout=20) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def normalize_duckduckgo_url(url: str) -> str:
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    if "duckduckgo.com" in parsed.netloc and parsed.path == "/l/":
        redirect = parse_qs(parsed.query).get("uddg", [])
        if redirect:
            return redirect[0]
    return url


def normalize_locale(language: str, region: str) -> dict[str, str]:
    raw_language = (language or "").strip().lower()
    raw_region = (region or "").strip().lower()
    if raw_region in {"台灣", "台湾", "tw", "taiwan"} or "繁體" in raw_language:
        return {"kl": "tw-tzh", "cc": "TW", "mkt": "zh-TW", "setlang": "zh-Hant"}
    if raw_region in {"香港", "hk", "hong kong"}:
        return {"kl": "hk-tzh", "cc": "HK", "mkt": "zh-HK", "setlang": "zh-Hant"}
    return {"kl": "us-en", "cc": "US", "mkt": "en-US", "setlang": "en-US"}


def normalize_result_mode(value: str) -> tuple[str, int]:
    normalized = (value or "top3").strip().lower()
    return normalized, RESULT_MODE_MAP.get(normalized, 3)


def resolve_headers(fieldnames: list[str] | None) -> dict[str, str]:
    if not fieldnames:
        raise ValueError("Input CSV has no header row.")
    resolved: dict[str, str] = {}
    for target, aliases in FIELD_ALIASES.items():
        for name in fieldnames:
            if name in aliases:
                resolved[target] = name
                break
        if target not in resolved:
            raise ValueError(f"Missing required CSV column for {target}.")
    return resolved


def read_queries(path: Path) -> list[QueryRow]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = resolve_headers(reader.fieldnames)
        rows: list[QueryRow] = []
        for raw_row in reader:
            query = (raw_row.get(headers["query"]) or "").strip()
            if not query:
                continue
            normalized_mode, result_count = normalize_result_mode(raw_row.get(headers["result_mode"], "top3"))
            rows.append(
                QueryRow(
                    query_id=(raw_row.get(headers["query_id"]) or "").strip(),
                    query=query,
                    language=(raw_row.get(headers["language"]) or "").strip(),
                    region=(raw_row.get(headers["region"]) or "").strip(),
                    result_mode=normalized_mode,
                    result_count=result_count,
                    notes=(raw_row.get(headers["notes"]) or "").strip(),
                )
            )
    return rows


def search_duckduckgo(query: str, language: str, region: str, result_count: int) -> list[SearchItem]:
    locale = normalize_locale(language, region)
    search_query = build_search_query(query)
    url = "https://html.duckduckgo.com/html/?" + urlencode({"q": search_query, "kl": locale["kl"]})
    payload = fetch_text(url, accept_html=True)

    title_matches = re.findall(
        r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        payload,
        flags=re.IGNORECASE | re.DOTALL,
    )
    snippet_matches = re.findall(
        r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
        payload,
        flags=re.IGNORECASE | re.DOTALL,
    )

    seen_urls: set[str] = set()
    results: list[SearchItem] = []
    for index, (raw_url, raw_title) in enumerate(title_matches):
        item = SearchItem(
            rank=index + 1,
            title=clean_html_fragment(raw_title),
            url=normalize_duckduckgo_url(raw_url),
            description=clean_html_fragment(snippet_matches[index]) if index < len(snippet_matches) else "",
            provider="duckduckgo-html",
        )
        netloc = urlparse(item.url).netloc.lower()
        if not item.url or item.url in seen_urls or "duckduckgo.com" in netloc:
            continue
        seen_urls.add(item.url)
        item.rank = len(results) + 1
        results.append(item)
        if len(results) >= result_count:
            break
    return results


def search_bing_rss(query: str, language: str, region: str, result_count: int) -> list[SearchItem]:
    locale = normalize_locale(language, region)
    search_query = build_search_query(query)
    params = {
        "format": "rss",
        "q": search_query,
        "count": max(10, result_count),
        "cc": locale["cc"],
        "mkt": locale["mkt"],
        "setlang": locale["setlang"],
    }
    payload = fetch_text("https://www.bing.com/search?" + urlencode(params), accept_html=False)
    root = ET.fromstring(payload)

    seen_urls: set[str] = set()
    results: list[SearchItem] = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        description = (item.findtext("description") or "").strip()
        netloc = urlparse(link).netloc.lower()
        if not link or link in seen_urls or netloc.endswith("bing.com"):
            continue
        seen_urls.add(link)
        results.append(SearchItem(len(results) + 1, title, link, description, "bing-rss"))
        if len(results) >= result_count:
            break
    return results


def extract_keywords(query: str) -> set[str]:
    lowered = query.lower()
    tokens: set[str] = set()

    for token in re.findall(r"[a-z0-9][a-z0-9+.#-]{1,}", lowered):
        if token not in EN_STOPWORDS:
            tokens.add(token)

    for phrase in re.findall(r"[\u4e00-\u9fff]{2,}", query):
        cleaned = phrase
        for filler in CJK_FILLERS:
            cleaned = cleaned.replace(filler, " ")
        for part in cleaned.split():
            if len(part) >= 2:
                tokens.add(part)

    return {token for token in tokens if token}


def extract_numeric_constraints(query: str) -> set[str]:
    matches = re.findall(
        r"(?:nt\$|us\$|\$)?\d+(?:[.,]\d+)?\s?(?:元|塊|坪|人|年|月|天|小時|分鐘|mah|gb|tb|inch|inches|product|products)?",
        query.lower(),
    )
    return {match.strip() for match in matches if match.strip()}


def detect_query_intent(query: str) -> str:
    lowered = query.lower()
    if any(term in lowered for term in (" vs ", "versus", "compare", "comparison", "比較", "怎麼選", "哪個", "哪台", "還是")):
        return "comparison"
    if any(term in lowered for term in ("best", "worth", "which", "推薦", "首選", "最值得", "值得買", "怎麼挑")):
        return "recommendation"
    if any(term in lowered for term in ("where", "near me", "台北", "當天", "哪裡", "附近")):
        return "local"
    if any(term in lowered for term in ("how", "guide", "如何", "怎麼")):
        return "howto"
    return "informational"


def normalize_text_for_match(text: str) -> str:
    lowered = text.lower().replace("-", " ")
    return re.sub(r"\s+", " ", lowered)


def build_search_query(query: str) -> str:
    cleaned = query.strip()
    for char in ("？", "?", "，", ",", "。", "：", "、", "(", ")", "「", "」", "“", "”", '"'):
        cleaned = cleaned.replace(char, " ")

    lowered = cleaned.lower()
    for pattern in EN_QUERY_PREFIX_PATTERNS:
        lowered = re.sub(pattern, "", lowered)
    cleaned = lowered

    for filler in SEARCH_QUERY_FILLERS:
        cleaned = cleaned.replace(filler, " ")

    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or query.strip()


def keyword_coverage(query: str, text: str) -> tuple[float, list[str], list[str]]:
    keywords = sorted(extract_keywords(query))
    if not keywords:
        return 0.0, [], []
    normalized_text = normalize_text_for_match(text)
    matched = [token for token in keywords if token.lower() in normalized_text]
    return len(matched) / len(keywords), matched, keywords


def domain_penalty(domain: str) -> float:
    lowered = domain.lower()
    if any(hint in lowered for hint in UGC_DOMAIN_HINTS):
        return 12.0
    return 0.0


def note_excludes(domain: str, notes: str) -> bool:
    lowered_notes = (notes or "").lower()
    lowered_domain = domain.lower()
    if ("排除 reddit" in lowered_notes or "exclude reddit" in lowered_notes) and "reddit.com" in lowered_domain:
        return True
    return False


def search_result_relevance(query_row: QueryRow, item: SearchItem) -> float:
    text = " ".join(part for part in (item.title, item.description, item.url) if part)
    coverage, matched, keywords = keyword_coverage(query_row.query, text)
    score = coverage * 70.0

    numeric_constraints = extract_numeric_constraints(query_row.query)
    if numeric_constraints and any(token in normalize_text_for_match(text) for token in numeric_constraints):
        score += 10.0

    intent = detect_query_intent(query_row.query)
    normalized = normalize_text_for_match(text)
    if intent == "comparison" and any(term in normalized for term in ("vs", "versus", "比較", "compare", "comparison")):
        score += 10.0
    if intent == "recommendation" and any(term in normalized for term in ("best", "recommend", "top", "推薦", "首選", "最值得")):
        score += 10.0
    if intent == "local" and any(term in normalized for term in ("台北", "taipei", "near", "same day", "當天", "附近")):
        score += 10.0

    locale = normalize_locale(query_row.language, query_row.region)
    domain = urlparse(item.url).netloc.lower()
    if locale["cc"] == "TW" and (domain.endswith(".tw") or ".tw/" in item.url.lower()):
        score += 4.0

    if keywords and not matched:
        score -= 20.0

    score -= domain_penalty(domain)
    if note_excludes(domain, query_row.notes):
        score -= 100.0
    return round(score, 2)


def query_fit_score(query_row: QueryRow, signals: Any, item: SearchItem) -> tuple[float, list[str], list[str]]:
    page_text = " ".join(
        [
            signals.title,
            " ".join(text for _, text in signals.headings[:8]),
            " ".join(signals.paragraphs[:4]),
            " ".join(signals.list_items[:6]),
            item.title,
            item.description,
        ]
    )
    coverage, matched, keywords = keyword_coverage(query_row.query, page_text)
    score = 1.0 + coverage * 5.5
    reasons: list[str] = []

    if keywords:
        reasons.append(f"Matched {len(matched)}/{len(keywords)} query keywords.")

    numeric_constraints = extract_numeric_constraints(query_row.query)
    if numeric_constraints and any(token in normalize_text_for_match(page_text) for token in numeric_constraints):
        score += 1.2
        reasons.append("Page reflects numeric or budget constraints from the query.")

    intent = detect_query_intent(query_row.query)
    if intent in {"comparison", "recommendation"} and has_recommendation_signal(signals):
        score += 0.9
        reasons.append("Page makes an explicit recommendation.")
    if intent == "comparison" and (has_tradeoff_signal(signals) or signals.has_table):
        score += 1.0
        reasons.append("Page surfaces comparison or trade-off structure.")
    if intent == "local" and any(term in page_text for term in ("台北", "taipei", "same day", "當天", "附近")):
        score += 0.8
        reasons.append("Page looks aligned to local-service intent.")
    if intent == "howto" and any(term in normalize_text_for_match(page_text) for term in ("how", "steps", "step", "如何", "步驟")):
        score += 0.8
        reasons.append("Page uses how-to framing.")

    if has_conclusion_first_signal(signals):
        score += 0.4
    if has_scenario_split_signal(signals):
        score += 0.4

    if intent in {"comparison", "recommendation"}:
        if not has_recommendation_signal(signals) and not has_tradeoff_signal(signals) and not signals.has_table and len(signals.list_items) < 3:
            score = min(score, 2.8)
            reasons.append("Page matches keywords but does not complete the decision intent.")
        elif not has_recommendation_signal(signals):
            score = min(score, 3.6)
            reasons.append("Page is relevant but still weak on recommendation intent.")
    if intent == "local" and not any(term in page_text for term in ("台北", "taipei", "same day", "當天", "附近")):
        score = min(score, 3.0)
        reasons.append("Page does not show enough local-service alignment.")
    if intent == "howto" and not any(term in normalize_text_for_match(page_text) for term in ("how", "steps", "step", "如何", "步驟")):
        score = min(score, 3.2)
        reasons.append("Page is not clearly structured as a how-to answer.")
    if keywords and len(matched) < max(1, len(keywords) // 2):
        score = min(score, 3.2)
        reasons.append("Page only matches a small share of the query constraints.")

    score -= domain_penalty(urlparse(item.url).netloc.lower()) / 12.0
    return round(max(1.0, min(10.0, score)), 1), matched, reasons


def search_with_fallback(query_row: QueryRow, candidate_count: int) -> tuple[list[SearchItem], str]:
    try:
        items = search_duckduckgo(query_row.query, query_row.language, query_row.region, candidate_count)
        if items:
            return items, "duckduckgo-html"
    except HTTPError as exc:
        if exc.code not in {403, 429}:
            raise
    except Exception:
        pass
    return search_bing_rss(query_row.query, query_row.language, query_row.region, candidate_count), "bing-rss"


def choose_candidates(query_row: QueryRow, candidate_count: int) -> tuple[list[SearchItem], str]:
    items, provider = search_with_fallback(query_row, candidate_count)
    filtered: list[SearchItem] = []
    for item in items:
        domain = urlparse(item.url).netloc.lower()
        if note_excludes(domain, query_row.notes):
            continue
        item.search_relevance = search_result_relevance(query_row, item)
        filtered.append(item)

    filtered.sort(key=lambda item: (-item.search_relevance, item.rank))
    selected = filtered[: query_row.result_count]
    for position, item in enumerate(selected, start=1):
        item.rerank_position = position
    return selected, provider


def score_result(query_row: QueryRow, item: SearchItem, provider: str) -> dict[str, Any]:
    try:
        html, source, http_status, fetch_warning = load_input(item.url, None)
        signals = parse_page(html, source, http_status=http_status, fetch_warning=fetch_warning)
        page_score, breakdowns = score_page(signals)
        payload = build_payload(page_score, breakdowns, signals)
        query_fit, matched_keywords, fit_reasons = query_fit_score(query_row, signals, item)
        combined_score = round(max(1.0, min(10.0, page_score * 0.60 + query_fit * 0.40)), 1)
        breakdown_map = {entry.name: round(entry.points, 2) for entry in breakdowns}
        suggestions = collect_suggestions(signals)
        issue_keys = [issue["key"] for issue in payload["audit"]["issues"][:8]]

        return {
            "query_id": query_row.query_id,
            "query": query_row.query,
            "language": query_row.language,
            "region": query_row.region,
            "result_mode": query_row.result_mode,
            "notes": query_row.notes,
            "search_provider": provider,
            "search_rank": item.rank,
            "rerank_position": item.rerank_position,
            "search_relevance": item.search_relevance,
            "result_title": item.title,
            "result_url": item.url,
            "result_description": item.description,
            "page_score": page_score,
            "query_fit_score": query_fit,
            "combined_score": combined_score,
            "matched_keywords": matched_keywords,
            "query_fit_reasons": fit_reasons[:4],
            "http_status": signals.http_status,
            "fetch_warning": signals.fetch_warning,
            "looks_like_block_page": looks_like_block_page(signals),
            "title_found": bool(signals.title),
            "meta_description_found": bool(signals.meta_description),
            "canonical_found": bool(signals.canonical),
            "lang_found": bool(signals.lang),
            "og_found": bool(signals.og_title or signals.og_description),
            "json_ld_found": bool(signals.json_ld_blocks),
            "schema_types": sorted(signals.schema_types),
            "author_signal": bool(signals.author_mentions or signals.schema_has_author),
            "date_signal": bool(signals.date_mentions or signals.schema_has_date),
            "publisher_signal": bool(signals.organization_mentions or signals.schema_has_publisher),
            "faq_signal": bool(signals.has_faq_section or "faqpage" in signals.schema_types or "qapage" in signals.schema_types),
            "list_signal": len(signals.list_items) >= 3,
            "table_signal": bool(signals.has_table),
            "conclusion_first": payload["signals"]["conclusion_first"],
            "recommendation_signal": payload["signals"]["recommendation_signal"],
            "scenario_split": payload["signals"]["scenario_split"],
            "tradeoff_signal": payload["signals"]["tradeoff_signal"],
            "next_step_signal": payload["signals"]["next_step_signal"],
            "topic_risk": payload["signals"]["topic_risk"],
            "specificity_markers": payload["signals"]["specificity_markers"],
            "llms_txt_found": bool(signals.llms_txt_found),
            "internal_links": len(signals.internal_links),
            "external_links": len(signals.external_links),
            "image_alts": len(signals.image_alts),
            "paragraphs": len(signals.paragraphs),
            "word_count": len(signals.visible_text.split()),
            "discovery_and_indexability": breakdown_map.get("Discovery and indexability", 0.0),
            "machine_readability": breakdown_map.get("Machine readability", 0.0),
            "answer_extractability": breakdown_map.get("Answer extractability", 0.0),
            "trust_and_citation": breakdown_map.get("Trust and citation", 0.0),
            "added_value": breakdown_map.get("Added value", 0.0),
            "task_resolution": breakdown_map.get("Task resolution", 0.0),
            "top_issue_keys": issue_keys,
            "top_suggestions": suggestions[:5],
            "error": "",
        }
    except Exception as exc:
        return {
            "query_id": query_row.query_id,
            "query": query_row.query,
            "language": query_row.language,
            "region": query_row.region,
            "result_mode": query_row.result_mode,
            "notes": query_row.notes,
            "search_provider": provider,
            "search_rank": item.rank,
            "rerank_position": item.rerank_position,
            "search_relevance": item.search_relevance,
            "result_title": item.title,
            "result_url": item.url,
            "result_description": item.description,
            "page_score": "",
            "query_fit_score": "",
            "combined_score": "",
            "matched_keywords": [],
            "query_fit_reasons": [],
            "http_status": "",
            "fetch_warning": "",
            "looks_like_block_page": "",
            "title_found": "",
            "meta_description_found": "",
            "canonical_found": "",
            "lang_found": "",
            "og_found": "",
            "json_ld_found": "",
            "schema_types": [],
            "author_signal": "",
            "date_signal": "",
            "publisher_signal": "",
            "faq_signal": "",
            "list_signal": "",
            "table_signal": "",
            "conclusion_first": "",
            "recommendation_signal": "",
            "scenario_split": "",
            "tradeoff_signal": "",
            "next_step_signal": "",
            "topic_risk": "",
            "specificity_markers": "",
            "llms_txt_found": "",
            "internal_links": "",
            "external_links": "",
            "image_alts": "",
            "paragraphs": "",
            "word_count": "",
            "discovery_and_indexability": "",
            "machine_readability": "",
            "answer_extractability": "",
            "trust_and_citation": "",
            "added_value": "",
            "task_resolution": "",
            "top_issue_keys": [],
            "top_suggestions": [],
            "error": str(exc),
        }


def write_results(rows: list[dict[str, Any]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    headers = [
        "query_id", "query", "language", "region", "result_mode", "notes",
        "search_provider", "search_rank", "rerank_position", "search_relevance",
        "result_title", "result_url", "result_description", "page_score",
        "query_fit_score", "combined_score", "matched_keywords", "query_fit_reasons",
        "http_status", "fetch_warning", "looks_like_block_page", "title_found",
        "meta_description_found", "canonical_found", "lang_found", "og_found",
        "json_ld_found", "schema_types", "author_signal", "date_signal",
        "publisher_signal", "faq_signal", "list_signal", "table_signal",
        "conclusion_first", "recommendation_signal", "scenario_split",
        "tradeoff_signal", "next_step_signal", "topic_risk", "specificity_markers",
        "llms_txt_found", "internal_links", "external_links", "image_alts",
        "paragraphs", "word_count", "discovery_and_indexability",
        "machine_readability", "answer_extractability", "trust_and_citation",
        "added_value", "task_resolution", "top_issue_keys", "top_suggestions", "error",
    ]
    with RESULTS_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            serialized = dict(row)
            serialized["matched_keywords"] = " | ".join(row.get("matched_keywords", []))
            serialized["query_fit_reasons"] = " | ".join(row.get("query_fit_reasons", []))
            serialized["schema_types"] = "; ".join(row.get("schema_types", []))
            serialized["top_issue_keys"] = " | ".join(row.get("top_issue_keys", []))
            serialized["top_suggestions"] = " | ".join(row.get("top_suggestions", []))
            writer.writerow(serialized)
    with DETAILS_JSON.open("w", encoding="utf-8") as handle:
        json.dump(rows, handle, ensure_ascii=False, indent=2)


def mean_or_blank(values: list[float]) -> float | str:
    if not values:
        return ""
    return round(sum(values) / len(values), 2)


def classify_serp_confidence(query_rows: list[dict[str, Any]]) -> str:
    relevance_scores = [
        float(row["search_relevance"])
        for row in query_rows
        if row.get("search_relevance") not in {"", None}
    ]
    if not relevance_scores:
        return "low"
    best = max(relevance_scores)
    if best >= 40:
        return "high"
    if best >= 20:
        return "medium"
    return "low"


def write_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["query_id"], []).append(row)

    summary_rows: list[dict[str, Any]] = []
    for query_id, query_rows in sorted(grouped.items(), key=lambda item: int(item[0])):
        scored = [row for row in query_rows if isinstance(row.get("combined_score"), (int, float))]
        scored.sort(key=lambda row: row["combined_score"], reverse=True)
        best = scored[0] if scored else {}
        combined_scores = [row["combined_score"] for row in scored]
        page_scores = [row["page_score"] for row in scored if isinstance(row.get("page_score"), (int, float))]
        query_fit_scores = [row["query_fit_score"] for row in scored if isinstance(row.get("query_fit_score"), (int, float))]
        summary_rows.append(
            {
                "query_id": query_id,
                "query": query_rows[0]["query"],
                "language": query_rows[0]["language"],
                "region": query_rows[0]["region"],
                "result_mode": query_rows[0]["result_mode"],
                "search_provider": best.get("search_provider", ""),
                "average_combined_score": mean_or_blank(combined_scores),
                "average_page_score": mean_or_blank(page_scores),
                "average_query_fit_score": mean_or_blank(query_fit_scores),
                "best_combined_score": best.get("combined_score", ""),
                "best_page_score": best.get("page_score", ""),
                "best_query_fit_score": best.get("query_fit_score", ""),
                "best_search_rank": best.get("search_rank", ""),
                "best_search_relevance": best.get("search_relevance", ""),
                "serp_confidence": classify_serp_confidence(query_rows),
                "best_result_title": best.get("result_title", ""),
                "best_result_url": best.get("result_url", ""),
                "scored_results": len(scored),
                "blocked_results": sum(1 for row in scored if row.get("looks_like_block_page")),
                "errored_results": sum(1 for row in query_rows if row.get("error")),
            }
        )

    with SUMMARY_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0].keys()))
        writer.writeheader()
        writer.writerows(summary_rows)
    return summary_rows


def percent(part: int, total: int) -> str:
    if total == 0:
        return "0.0%"
    return f"{(part / total) * 100:.1f}%"


def build_playbook(rows: list[dict[str, Any]], summaries: list[dict[str, Any]]) -> str:
    scored = [row for row in rows if isinstance(row.get("combined_score"), (int, float))]
    if not scored:
        return "# AI SEO Playbook\n\nNo scored results were produced.\n"

    combined_scores = [row["combined_score"] for row in scored]
    threshold = statistics.quantiles(combined_scores, n=4)[2] if len(combined_scores) >= 4 else max(combined_scores)
    strong = [row for row in scored if row["combined_score"] >= threshold]
    weak = [row for row in scored if row["combined_score"] < threshold]
    low_confidence_queries = sum(1 for row in summaries if row.get("serp_confidence") == "low")

    issue_counter: dict[str, int] = {}
    for row in scored:
        for key in row.get("top_issue_keys", []):
            issue_counter[key] = issue_counter.get(key, 0) + 1

    def signal_rate(name: str, subset: list[dict[str, Any]]) -> str:
        return percent(sum(1 for row in subset if row.get(name)), len(subset))

    lines = [
        "# AI SEO Playbook",
        "",
        "## Dataset Snapshot",
        f"- Queries processed: {len(summaries)}",
        f"- Result rows scored: {len(scored)}",
        f"- Average combined score: {mean_or_blank(combined_scores)}",
        f"- Median combined score: {round(statistics.median(combined_scores), 2)}",
        f"- Blocked pages: {percent(sum(1 for row in scored if row.get('looks_like_block_page')), len(scored))}",
        f"- Low-confidence SERP queries: {low_confidence_queries}/{len(summaries)}",
        "",
        "## What Strong Pages Repeatedly Do",
        f"- State an answer early: {signal_rate('conclusion_first', strong)} of top pages",
        f"- Make an explicit recommendation: {signal_rate('recommendation_signal', strong)} of top pages",
        f"- Split by scenario or audience: {signal_rate('scenario_split', strong)} of top pages",
        f"- Explain trade-offs: {signal_rate('tradeoff_signal', strong)} of top pages",
        f"- Carry visible trust signals (author/date/publisher): {percent(sum(1 for row in strong if row.get('author_signal') and row.get('date_signal') and row.get('publisher_signal')), len(strong))}",
        f"- Use structured data: {signal_rate('json_ld_found', strong)} of top pages",
        "",
        "## Common Failure Modes",
        f"- Weak task resolution among lower pages: {signal_rate('recommendation_signal', weak)} show a recommendation",
        f"- Low citation support among lower pages: {percent(sum(1 for row in weak if row.get('external_links', 0) >= 1), len(weak))} link out to supporting sources",
        f"- Thin specificity among lower pages: {percent(sum(1 for row in weak if isinstance(row.get('specificity_markers'), int) and row['specificity_markers'] >= 4), len(weak))} include enough concrete detail",
        "",
        "## Repeatable AI SEO Rules",
        "- Lead with the answer, not scene-setting. The first 1 to 2 blocks should already choose, rank, or frame the decision.",
        "- Turn information into decision support. Comparison, trade-offs, scenario splits, and next steps matter more than generic explanation.",
        "- Keep pages machine-readable. Title, meta description, canonical, Open Graph, and JSON-LD remain the discovery baseline.",
        "- Build a trust stack. Author, date, publisher, and citations should appear together, especially on higher-risk topics.",
        "- Add specifics. Numbers, limits, prices, dates, dimensions, and named constraints help pages feel reusable instead of generic.",
        "",
        "## Most Frequent Audit Gaps",
    ]
    for key, count in sorted(issue_counter.items(), key=lambda item: item[1], reverse=True)[:8]:
        lines.append(f"- `{key}`: {count}")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search and score webpages against AI SEO heuristics.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="CSV file containing query rows.")
    parser.add_argument("--offset", type=int, default=0, help="Skip this many query rows before running.")
    parser.add_argument("--limit", type=int, default=0, help="Only process this many query rows. 0 means all.")
    parser.add_argument("--candidate-count", type=int, default=10, help="Search results fetched before reranking.")
    parser.add_argument("--workers", type=int, default=6, help="Concurrent page fetch workers.")
    parser.add_argument("--search-delay", type=float, default=0.8, help="Delay between search engine requests.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    queries = read_queries(Path(args.input))
    if args.offset:
        queries = queries[args.offset :]
    if args.limit:
        queries = queries[: args.limit]
    if not queries:
        raise SystemExit("No queries selected.")

    selected_results: list[tuple[QueryRow, SearchItem, str]] = []
    for index, query_row in enumerate(queries, start=1):
        items, provider = choose_candidates(query_row, max(query_row.result_count, args.candidate_count))
        for item in items:
            selected_results.append((query_row, item, provider))
        if index < len(queries):
            time.sleep(max(0.0, args.search_delay))

    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        future_map = {
            executor.submit(score_result, query_row, item, provider): (query_row.query_id, item.url)
            for query_row, item, provider in selected_results
        }
        for future in as_completed(future_map):
            rows.append(future.result())

    rows.sort(
        key=lambda row: (
            int(row["query_id"]),
            int(row["rerank_position"] or 999),
            int(row["search_rank"] or 999),
        )
    )

    write_results(rows)
    summaries = write_summary(rows)
    PLAYBOOK_MD.write_text(build_playbook(rows, summaries), encoding="utf-8")

    successful = sum(1 for row in rows if isinstance(row.get("combined_score"), (int, float)))
    print(f"Processed {len(queries)} queries -> {len(rows)} rows, {successful} scored successfully.")
    print(f"Results: {RESULTS_CSV}")
    print(f"Summary: {SUMMARY_CSV}")
    print(f"Playbook: {PLAYBOOK_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
