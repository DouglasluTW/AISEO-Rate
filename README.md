# AEO Score

An explainable AI SEO diagnostic system for webpages.

Instead of treating AEO as a single score, this project frames it as a
multi-state audit. A page is evaluated for whether it can be read, trusted,
cited, and chosen across search and AI answer surfaces.

## Product Narrative

You can present this project in at least three ways:

- `AI Readability Audit`
  Checks whether a page is machine-readable, extractable, and summary-friendly.
- `Citation Trust Review`
  Checks whether a page has the authorship, freshness, and evidence needed to be cited.
- `Decision Clarity Check`
  Checks whether a page actually resolves a user task instead of only presenting information.

Under the hood, the project supports both direct URL scoring and query-driven
batch workflows.

## Five Diagnostic Lenses

Every scored page is decomposed into five product-level lenses:

- `Extractability`
  Can systems reliably parse and reuse the page?
- `Resolution`
  Does the page structure help the reader reach an answer or decision?
- `Citation trust`
  Does the page look trustworthy enough to cite?
- `Surface visibility`
  Does the page have the metadata and framing to surface cleanly?
- `Content structure`
  Is the page segmented well enough to scan and repurpose?

## What It Does

- Scores a page with an explainable heuristic rubric
- Decomposes results into both raw scoring layers and product-level lenses
- Runs an extensible issue-audit catalog for site-health style diagnostics
- Supports a local browser UI for URL-based audits
- Supports query-driven batch workflows
- Emits both human-readable text and machine-readable JSON

## Current Status

This is an explainable heuristic system, not a trained ranking model.

That is intentional:

- it is easy to inspect and tune
- it is useful before labeled data exists
- it can later become a supervised model when a scored dataset is available

## Files

- `aeo_score.py`: main scoring engine
- `app.py`: local web server for the browser UI
- `web/`: static frontend files
- `aeo_queries_template.csv`: batch query template

## Quick Start

```bash
python aeo_score.py --url https://example.com
python aeo_score.py --url https://example.com --json
python aeo_score.py --file .\sample.html
```

## Browser UI

Run the local web app:

```bash
python app.py
```

Then open:

```text
http://127.0.0.1:8000
```

Paste a public URL into the form and the app will return:

- an overall score
- five diagnostic lenses
- operational layer breakdowns
- detected signals
- priority fixes

## Query Template

Use `aeo_queries_template.csv` when you want the workflow to be:

1. provide a query
2. search for candidate pages
3. read the pages
4. score them for AEO completeness

Template columns:

```text
編號, 題目, 語言, 地區, 結果模式, 備註
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
