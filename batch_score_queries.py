#!/usr/bin/env python3
"""Batch search and score query results for AEO completeness."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from aeo_score import (
    collect_suggestions,
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

RESULT_MODE_MAP = {
    "top1": 1,
    "top3": 3,
    "top5": 5,
}

LOCALE_MAP = {
    ("繁體中文", "台灣"): {"cc": "TW", "mkt": "zh-TW", "setlang": "zh-Hant"},
    ("中文", "台灣"): {"cc": "TW", "mkt": "zh-TW", "setlang": "zh-Hant"},
    ("英文", "美國"): {"cc": "US", "mkt": "en-US", "setlang": "en-US"},
    ("english", "us"): {"cc": "US", "mkt": "en-US", "setlang": "en-US"},
}


@dataclass
class SearchItem:
    rank: int
    title: str
    url: str
    description: str


class BraveSearchParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[SearchItem] = []
        self._inside_result = False
        self._result_div_depth = 0
        self._capture_title = False
        self._capture_snippet = False
        self._current: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {k: (v or "") for k, v in attrs}
        if tag == "div" and attr_map.get("data-type") == "web":
            self._inside_result = True
            self._result_div_depth = 1
            self._current = {"url": "", "title_parts": [], "snippet_parts": []}
            return

        if not self._inside_result or self._current is None:
            return

        if tag == "div":
            self._result_div_depth += 1
            if "snippet" in attr_map.get("class", ""):
                self._capture_snippet = True

        if tag == "a" and not self._current["url"] and attr_map.get("href"):
            self._current["url"] = attr_map["href"]
            self._capture_title = True

    def handle_endtag(self, tag: str) -> None:
        if not self._inside_result or self._current is None:
            return

        if tag == "a" and self._capture_title:
            self._capture_title = False

        if tag == "div":
            if self._capture_snippet:
                self._capture_snippet = False
            self._result_div_depth -= 1
            if self._result_div_depth == 0:
                title = " ".join(self._current["title_parts"]).strip()
                snippet = " ".join(self._current["snippet_parts"]).strip()
                url = self._current["url"]
                if url:
                    self.results.append(
                        SearchItem(
                            rank=len(self.results) + 1,
                            title=title,
                            url=url,
                            description=snippet,
                        )
                    )
                self._inside_result = False
                self._current = None

    def handle_data(self, data: str) -> None:
        if not self._inside_result or self._current is None:
            return
        text = " ".join(data.split()).strip()
        if not text:
            return
        if self._capture_title:
            self._current["title_parts"].append(text)
        if self._capture_snippet:
            self._current["snippet_parts"].append(text)


def fetch_text(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "application/rss+xml,application/xml,text/xml,text/html;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,zh-TW;q=0.8",
        "Cache-Control": "no-cache",
    }
    request = Request(url, headers=headers)
    with urlopen(request, timeout=20) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def normalize_locale(language: str, region: str) -> dict[str, str]:
    raw_language = (language or "").strip()
    raw_region = (region or "").strip()
    key = (raw_language, raw_region)
    if key in LOCALE_MAP:
        return LOCALE_MAP[key]
    fallback_key = (raw_language.lower(), raw_region.lower())
    if fallback_key in LOCALE_MAP:
        return LOCALE_MAP[fallback_key]
    if "台" in raw_region or raw_region.upper() == "TW":
        return {"cc": "TW", "mkt": "zh-TW", "setlang": "zh-Hant"}
    return {"cc": "US", "mkt": "en-US", "setlang": "en-US"}


def normalize_result_mode(value: str) -> int:
    normalized = (value or "top3").strip().lower()
    return RESULT_MODE_MAP.get(normalized, 3)


def search_bing_rss(query: str, language: str, region: str, result_count: int) -> list[SearchItem]:
    locale = normalize_locale(language, region)
    params = {
        "format": "rss",
        "q": query,
        "count": max(10, result_count),
        "cc": locale["cc"],
        "mkt": locale["mkt"],
        "setlang": locale["setlang"],
    }
    url = "https://www.bing.com/search?" + urlencode(params)
    payload = fetch_text(url)
    root = ET.fromstring(payload)

    seen_urls: set[str] = set()
    results: list[SearchItem] = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        description = (item.findtext("description") or "").strip()
        if not link or link in seen_urls:
            continue
        if urlparse(link).netloc.endswith("bing.com"):
            continue
        seen_urls.add(link)
        results.append(
            SearchItem(
                rank=len(results) + 1,
                title=title,
                url=link,
                description=description,
            )
        )
        if len(results) >= result_count:
            break
    return results


def search_brave(query: str, language: str, region: str, result_count: int) -> list[SearchItem]:
    locale = normalize_locale(language, region)
    params = {
        "q": query,
        "source": "web",
        "country": locale["cc"].lower(),
    }
    url = "https://search.brave.com/search?" + urlencode(params)
    payload = ""
    for delay in (0, 3, 10, 20):
        if delay:
            time.sleep(delay)
        try:
            payload = fetch_text(url)
            break
        except HTTPError as exc:
            if exc.code != 429:
                raise
    if not payload:
        raise HTTPError(url, 429, "Too Many Requests", hdrs=None, fp=None)
    parser = BraveSearchParser()
    parser.feed(payload)

    seen_urls: set[str] = set()
    results: list[SearchItem] = []
    for item in parser.results:
        if not item.url or item.url in seen_urls:
            continue
        if urlparse(item.url).netloc.endswith("search.brave.com"):
            continue
        seen_urls.add(item.url)
        results.append(
            SearchItem(
                rank=len(results) + 1,
                title=item.title,
                url=item.url,
                description=item.description,
            )
        )
        if len(results) >= result_count:
            break
    return results


def filter_search_items(items: list[SearchItem], notes: str) -> list[SearchItem]:
    note_text = (notes or "").lower()
    filtered: list[SearchItem] = []
    for item in items:
        domain = urlparse(item.url).netloc.lower()
        if "排除 reddit" in note_text or "exclude reddit" in note_text:
            if "reddit.com" in domain:
                continue
        filtered.append(item)
    return filtered


def search_with_fallback(query_row: dict[str, str], result_count: int) -> tuple[list[SearchItem], str]:
    query = query_row["題目"].strip()
    language = query_row["語言"]
    region = query_row["地區"]
    notes = query_row.get("備註", "")

    try:
        items = search_brave(query, language, region, result_count * 2)
        items = filter_search_items(items, notes)[:result_count]
        if items:
            return items, "brave"
    except Exception:
        pass

    items = search_bing_rss(query, language, region, result_count * 2)
    items = filter_search_items(items, notes)[:result_count]
    return items, "bing-rss"


def read_queries(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [row for row in rows if (row.get("題目") or "").strip()]


def score_result(query_row: dict[str, str], item: SearchItem) -> dict[str, Any]:
    try:
        html, source, http_status, fetch_warning = load_input(item.url, None)
        signals = parse_page(html, source, http_status=http_status, fetch_warning=fetch_warning)
        score, breakdowns = score_page(signals)
        breakdown_map = {entry.name: round(entry.points, 2) for entry in breakdowns}
        suggestions = collect_suggestions(signals)
        return {
            "query_id": query_row["編號"],
            "query": query_row["題目"],
            "language": query_row["語言"],
            "region": query_row["地區"],
            "result_mode": query_row["結果模式"],
            "notes": query_row["備註"],
            "search_rank": item.rank,
            "result_title": item.title,
            "result_url": item.url,
            "result_description": item.description,
            "score": score,
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
            "llms_txt_found": bool(signals.llms_txt_found),
            "internal_links": len(signals.internal_links),
            "external_links": len(signals.external_links),
            "image_alts": len(signals.image_alts),
            "paragraphs": len(signals.paragraphs),
            "word_count": len(signals.visible_text.split()),
            "technical_foundation": breakdown_map.get("Technical foundation", 0.0),
            "structured_data": breakdown_map.get("Structured data", 0.0),
            "answer_quality": breakdown_map.get("Answer quality", 0.0),
            "trust_and_entities": breakdown_map.get("Trust and entities", 0.0),
            "structure": breakdown_map.get("Structure", 0.0),
            "ai_readiness": breakdown_map.get("AI readiness", 0.0),
            "top_suggestions": suggestions[:5],
            "error": "",
        }
    except Exception as exc:
        return {
            "query_id": query_row["編號"],
            "query": query_row["題目"],
            "language": query_row["語言"],
            "region": query_row["地區"],
            "result_mode": query_row["結果模式"],
            "notes": query_row["備註"],
            "search_rank": item.rank,
            "result_title": item.title,
            "result_url": item.url,
            "result_description": item.description,
            "score": "",
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
            "llms_txt_found": "",
            "internal_links": "",
            "external_links": "",
            "image_alts": "",
            "paragraphs": "",
            "word_count": "",
            "technical_foundation": "",
            "structured_data": "",
            "answer_quality": "",
            "trust_and_entities": "",
            "structure": "",
            "ai_readiness": "",
            "top_suggestions": [],
            "error": str(exc),
        }


def write_results(rows: list[dict[str, Any]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    headers = [
        "query_id",
        "query",
        "language",
        "region",
        "result_mode",
        "notes",
        "search_rank",
        "result_title",
        "result_url",
        "result_description",
        "score",
        "http_status",
        "fetch_warning",
        "looks_like_block_page",
        "title_found",
        "meta_description_found",
        "canonical_found",
        "lang_found",
        "og_found",
        "json_ld_found",
        "schema_types",
        "author_signal",
        "date_signal",
        "publisher_signal",
        "faq_signal",
        "list_signal",
        "table_signal",
        "llms_txt_found",
        "internal_links",
        "external_links",
        "image_alts",
        "paragraphs",
        "word_count",
        "technical_foundation",
        "structured_data",
        "answer_quality",
        "trust_and_entities",
        "structure",
        "ai_readiness",
        "top_suggestions",
        "error",
    ]
    with RESULTS_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            serialized = dict(row)
            serialized["schema_types"] = "; ".join(row.get("schema_types", []))
            serialized["top_suggestions"] = " | ".join(row.get("top_suggestions", []))
            writer.writerow(serialized)
    with DETAILS_JSON.open("w", encoding="utf-8") as handle:
        json.dump(rows, handle, ensure_ascii=False, indent=2)


def write_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["query_id"]].append(row)

    summary_rows: list[dict[str, Any]] = []
    for query_id, query_rows in sorted(grouped.items(), key=lambda item: int(item[0])):
        scored = [row for row in query_rows if isinstance(row.get("score"), (int, float))]
        scored.sort(key=lambda row: row["score"], reverse=True)
        best = scored[0] if scored else {}
        average_score = round(sum(row["score"] for row in scored) / len(scored), 2) if scored else ""
        summary_rows.append(
            {
                "query_id": query_id,
                "query": query_rows[0]["query"],
                "language": query_rows[0]["language"],
                "region": query_rows[0]["region"],
                "result_mode": query_rows[0]["result_mode"],
                "average_score": average_score,
                "best_score": best.get("score", ""),
                "best_search_rank": best.get("search_rank", ""),
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
    scored = [row for row in rows if isinstance(row.get("score"), (int, float))]
    usable = [row for row in scored if not row.get("looks_like_block_page")]
    usable_sorted = sorted(usable, key=lambda row: row["score"], reverse=True)
    if not usable_sorted:
        return "# AI SEO Playbook\n\nNo usable results were scored."

    high_count = max(20, math.ceil(len(usable_sorted) * 0.25))
    low_count = max(20, math.ceil(len(usable_sorted) * 0.25))
    high = usable_sorted[:high_count]
    low = usable_sorted[-low_count:]

    features = {
        "Has meta description": "meta_description_found",
        "Has canonical": "canonical_found",
        "Has Open Graph": "og_found",
        "Has JSON-LD": "json_ld_found",
        "Has author signal": "author_signal",
        "Has date signal": "date_signal",
        "Has publisher signal": "publisher_signal",
        "Has FAQ or QA signal": "faq_signal",
        "Has list signal": "list_signal",
        "Has table signal": "table_signal",
        "Has llms.txt": "llms_txt_found",
    }

    feature_rows: list[tuple[str, str, float, float, float]] = []
    for label, key in features.items():
        high_ratio = sum(1 for row in high if row.get(key)) / len(high)
        low_ratio = sum(1 for row in low if row.get(key)) / len(low)
        lift = high_ratio - low_ratio
        feature_rows.append((label, key, high_ratio, low_ratio, lift))
    feature_rows.sort(key=lambda item: (item[4], item[2]), reverse=True)

    domain_counter = Counter(urlparse(row["result_url"]).netloc for row in high)
    top_domains = domain_counter.most_common(10)

    average_score = statistics.mean(row["score"] for row in usable_sorted)
    median_score = statistics.median(row["score"] for row in usable_sorted)
    high_avg = statistics.mean(row["score"] for row in high)
    low_avg = statistics.mean(row["score"] for row in low)

    score_bands = {
        "8.0-10.0": sum(1 for row in usable_sorted if row["score"] >= 8.0),
        "6.0-7.9": sum(1 for row in usable_sorted if 6.0 <= row["score"] < 8.0),
        "4.0-5.9": sum(1 for row in usable_sorted if 4.0 <= row["score"] < 6.0),
        "1.0-3.9": sum(1 for row in usable_sorted if row["score"] < 4.0),
    }

    lines = [
        "# AI SEO Playbook",
        "",
        "This playbook is derived from the scored pages in this batch run.",
        "",
        "## Dataset Summary",
        "",
        f"- Queries processed: {len(summaries)}",
        f"- Result pages scored: {len(scored)}",
        f"- Usable pages after excluding block or challenge pages: {len(usable_sorted)}",
        f"- Average score: {average_score:.2f}",
        f"- Median score: {median_score:.2f}",
        f"- Average score of top quartile: {high_avg:.2f}",
        f"- Average score of bottom quartile: {low_avg:.2f}",
        "",
        "### Score Distribution",
        "",
    ]
    for label, count in score_bands.items():
        lines.append(f"- {label}: {count} pages ({percent(count, len(usable_sorted))})")

    lines.extend(
        [
            "",
            "## What High-Scoring Pages Repeatedly Do",
            "",
        ]
    )
    for label, _, high_ratio, low_ratio, lift in feature_rows[:8]:
        lines.append(
            f"- {label}: {high_ratio * 100:.1f}% of top pages vs {low_ratio * 100:.1f}% of low pages "
            f"(lift {lift * 100:+.1f} pts)"
        )

    lines.extend(
        [
            "",
            "## Repeatable AI SEO Principles",
            "",
            "1. Start with an answer-first opening.",
            "Put the direct recommendation or conclusion near the top. Pages that force the reader to scroll before the first answer underperform.",
            "",
            "2. Make the page machine-readable.",
            "Use clean titles, meta descriptions, canonical tags, and JSON-LD. High-scoring pages are easier for systems to summarize because the metadata is not ambiguous.",
            "",
            "3. Turn content into extractable chunks.",
            "Use headings, lists, comparison tables, and short sections. AI systems and search snippets work better when the page has obvious extraction units.",
            "",
            "4. Ground the page with entity and trust signals.",
            "Author, publisher, update date, and external references make a page easier to trust and easier to cite.",
            "",
            "5. Match the real decision the query implies.",
            "The best pages are not just informative. They resolve the actual shopping, comparison, or selection job behind the query.",
            "",
            "6. Structure for comparison, not just description.",
            "Queries in this dataset often want tradeoffs. Good pages compare options across price, fit, risk, and use case, then recommend a clear next step.",
            "",
            "## Replicable AI SEO Checklist",
            "",
            "- Put the final recommendation in the first 1 to 2 paragraphs.",
            "- Add a concise title and summary-oriented meta description.",
            "- Add canonical and Open Graph tags.",
            "- Add JSON-LD using at least WebPage, Article, Product, FAQPage, or Organization where relevant.",
            "- Use H2 sections for decision criteria, comparisons, and FAQs.",
            "- Convert key evaluation points into bullet lists or tables.",
            "- Add author, publisher, and last-updated signals.",
            "- Cite external sources when the claim depends on trust, safety, or performance.",
            "- Include a short FAQ when the topic has recurring objections or buyer questions.",
            "- Keep the page easy to quote: tight paragraphs, explicit subheadings, and direct phrasing.",
            "",
            "## Domains That Appeared Most Often In High-Scoring Results",
            "",
        ]
    )
    for domain, count in top_domains:
        lines.append(f"- {domain}: {count}")

    lines.extend(
        [
            "",
            "## Interpretation Notes",
            "",
            "- This is a heuristic AEO score, not an official search engine metric.",
            "- Search result quality depends on the provider and locale settings used in this run.",
            "- Some pages may score lower because of bot blocking rather than weak content quality.",
        ]
    )

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Search and batch-score query results for AEO.")
    parser.add_argument("--limit", type=int, default=0, help="Only process the first N queries.")
    args = parser.parse_args()

    queries = read_queries(DEFAULT_INPUT)
    if args.limit > 0:
        queries = queries[: args.limit]
    print(f"Loaded {len(queries)} queries from {DEFAULT_INPUT.name}", flush=True)

    search_tasks: list[tuple[dict[str, str], SearchItem]] = []
    for index, query_row in enumerate(queries, start=1):
        query = query_row["題目"].strip()
        result_count = normalize_result_mode(query_row.get("結果模式", "top3"))
        query_row["結果模式"] = f"top{result_count}"
        print(f"[search {index}/{len(queries)}] {query_row['編號']}: {query}", flush=True)
        try:
            items, provider = search_with_fallback(query_row, result_count)
            print(f"  provider: {provider}, results: {len(items)}", flush=True)
        except Exception as exc:
            print(f"  search failed: {exc}", flush=True)
            continue
        if not items:
            print("  no results found", flush=True)
            continue
        for item in items:
            search_tasks.append((query_row, item))
        time.sleep(0.8)

    print(f"Queued {len(search_tasks)} result pages for scoring", flush=True)

    scored_rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        future_map = {
            executor.submit(score_result, query_row, item): (query_row["編號"], item.rank, item.url)
            for query_row, item in search_tasks
        }
        completed = 0
        total = len(future_map)
        for future in as_completed(future_map):
            completed += 1
            query_id, rank, url = future_map[future]
            try:
                row = future.result()
            except Exception as exc:
                row = {
                    "query_id": query_id,
                    "query": "",
                    "language": "",
                    "region": "",
                    "result_mode": "",
                    "notes": "",
                    "search_rank": rank,
                    "result_title": "",
                    "result_url": url,
                    "result_description": "",
                    "score": "",
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
                    "llms_txt_found": "",
                    "internal_links": "",
                    "external_links": "",
                    "image_alts": "",
                    "paragraphs": "",
                    "word_count": "",
                    "technical_foundation": "",
                    "structured_data": "",
                    "answer_quality": "",
                    "trust_and_entities": "",
                    "structure": "",
                    "ai_readiness": "",
                    "top_suggestions": [],
                    "error": str(exc),
                }
            scored_rows.append(row)
            score_display = row["score"] if row["score"] != "" else "ERR"
            print(f"[score {completed}/{total}] q{query_id} r{rank} -> {score_display}", flush=True)

    scored_rows.sort(key=lambda row: (int(row["query_id"]), int(row["search_rank"])))
    write_results(scored_rows)
    summaries = write_summary(scored_rows)
    PLAYBOOK_MD.write_text(build_playbook(scored_rows, summaries), encoding="utf-8")

    print(f"Wrote {RESULTS_CSV}", flush=True)
    print(f"Wrote {SUMMARY_CSV}", flush=True)
    print(f"Wrote {DETAILS_JSON}", flush=True)
    print(f"Wrote {PLAYBOOK_MD}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
