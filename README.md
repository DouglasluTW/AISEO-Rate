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
- `Added value`
  Does the page contribute concrete detail, comparisons, or synthesis beyond generic copy?

The scoring model is intentionally biased toward current AI-search realities:

- pages must be discoverable and machine-readable
- pages must be easy to extract and summarize
- pages must be trustworthy enough to cite
- pages must actually resolve the user task
- high-risk topics are held to a higher trust bar

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
- `CASEBOOK.md`: benchmark and calibration casebook
- `benchmark/`: tracked benchmark corpus and summaries

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

## Deploy Public URL

The simplest public deployment path for the current app is a Python web service
on Render.

This repo is now deployment-ready for that flow:

- `app.py` reads `HOST` and `PORT` from environment variables
- `render.yaml` is included for Render deployment
- `requirements.txt` is included for simple Python build steps

Basic Render flow:

1. Push this repository to GitHub.
2. Go to [Render](https://render.com/) and create a new `Web Service`.
3. Connect the GitHub repo.
4. Render should detect `render.yaml`, or you can set:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python app.py`
5. Deploy. Render will give you a public `https://...onrender.com` URL.

Important:

- GitHub Pages is not enough for this app because the scoring API is Python backend code.
- For a public URL, you need a backend host such as Render, Railway, Fly.io, or your own server.

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

`結果模式` means how many organic search results should be evaluated:

- `top1`
- `top3`
- `top5`

## Rubric

Current scoring dimensions:

- Discovery and indexability
  - title, meta description, canonical, lang, robots, fetch status, Open Graph
- Machine readability
  - JSON-LD, schema types, heading structure, internal links, image alts
- Answer extractability
  - opening paragraph, lists, tables, heading chunking, paragraph density
- Trust and citation
  - author, date, publisher, citations, depth, risk-sensitive trust expectations
- Added value
  - specifics, comparisons, trade-offs, structured synthesis
- Task resolution
  - conclusion first, recommendation signal, scenario split, trade-offs, next step

## Benchmark

This repository now includes a tracked benchmark corpus:

- cleaner query benchmark: 28 queries expanded to top-5 retrieval
- expanded page corpus: 139 scored pages
- same-query comparisons: 28 best-vs-worst pairs

Start with `CASEBOOK.md`, then inspect the files under `benchmark/`.

## Limitations

- Some websites block automated fetches and may return `403` or challenge pages
- Public search endpoints can degrade or rate-limit long batch runs, which affects candidate quality
- AEO is not a single formal standard, so the current score is a practical proxy

## Roadmap

- broader reviewed multilingual benchmark
- tunable weights per vertical or locale
- labeled dataset support
- supervised model training

## License

MIT
