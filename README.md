# AEO Score

A lightweight AEO (AI SEO) scoring tool for webpages.

This project reads a public webpage or local HTML file, extracts explainable
signals, and returns an AEO completeness score from `1.0` to `10.0`.

## What It Does

- Scores a page with an explainable heuristic rubric
- Breaks scoring into technical, schema, answer quality, trust, structure, and AI readiness
- Supports both direct page scoring and query-driven batch workflows
- Emits either human-readable text or machine-readable JSON

## Current Status

This is an explainable heuristic scorer, not a trained ranking model.

That is intentional:

- it is easy to inspect and tune
- it is useful before labeled data exists
- it can later become a supervised model when a scored dataset is available

## Files

- `aeo_score.py`: main scoring script
- `aeo_queries_template.csv`: batch query template

## Quick Start

```bash
python aeo_score.py --url https://example.com
python aeo_score.py --url https://example.com --json
python aeo_score.py --file .\sample.html
```

## Query Template

Use `aeo_queries_template.csv` when you want the workflow to be:

1. provide a query
2. search for candidate pages
3. read the pages
4. score them for AEO completeness

Template columns:

```text
id, query, language, region, result_mode, notes
```

`result_mode` currently means how many organic search results should be evaluated:

- `top1`
- `top3`
- `top5`

## Rubric

Current scoring dimensions:

- Technical foundation
  - title, meta description, canonical, lang, Open Graph, robots
- Structured data
  - JSON-LD, schema types, author, publisher, date
- Answer quality
  - H1, opening paragraph, FAQ, lists, tables, paragraph density
- Trust and entities
  - author, date, citations, publisher, content depth
- Structure
  - H2/H3, internal links, image alts
- AI readiness
  - `llms.txt`, FAQ and QA signals

## Limitations

- Some websites block automated fetches and may return `403` or challenge pages
- AEO is not a single formal standard, so the current score is a practical proxy
- The search-driven batch pipeline is the next step; this repository currently contains the scoring core and input template

## Roadmap

- query-to-search-result pipeline
- CSV batch scoring output
- tunable weights per vertical or locale
- labeled dataset support
- supervised model training

## License

MIT
