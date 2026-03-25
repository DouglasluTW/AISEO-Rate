# CASEBOOK

This document summarizes the current calibration corpus for AISEO-Rate.

It is not a gold-standard benchmark yet. It is a working casebook built from
the cleaner slice of the batch crawl so the scoring rules can be explained,
challenged, and improved.

## Scope

- Query-level benchmark: 28 medium or high confidence queries
- Page-level case library: 81 scored pages
- Head-to-head pairs: 27 same-query best vs worst comparisons

The raw generated CSV files live under `results/` and are not committed by
default. This document is the checked-in summary layer.

## What This Corpus Is Good For

- validating whether the scoring model rewards decision-ready pages
- spotting false positives where a page matches terms but does not solve the task
- comparing good and bad pages inside the same intent bucket
- turning recurring patterns into repeatable AI SEO rules

## What This Corpus Is Not

- a final multilingual benchmark
- a search-engine truth set
- a citation-rate ground truth dataset

Public search endpoints were used to assemble the cases. That means some
non-English queries still have retrieval noise even inside the cleaner subset.

## Current Shape

The strongest pages in the casebook are mostly English buying or comparison
pages. They repeatedly do a few things well:

- they recommend or rank
- they use list or comparison structure
- they include strong metadata and structured data
- they show authorship, freshness, and publisher signals together
- they explain trade-offs instead of only describing features

The weakest pages tend to be one of these failure modes:

- glossary or grammar pages that match surface keywords only
- directory or store-locator pages with no decision support
- forum or community pages that mention the topic but do not resolve it
- generic portal pages that are structurally fine but off-intent

## Strong Cases

These are representative pages the current model treats as genuinely useful:

1. `What is the best espresso machine under $500 for a small apartment?`
   High-scoring pages are compact buying guides with price constraints, clear picks, and apartment-specific framing.

2. `Which laptop is best for college and light video editing under $900?`
   High-scoring pages compare options with budget constraints and usage-fit language, not just specs.

3. `Which CRM is best for a 10-person B2B startup with a small sales team?`
   Strong pages recommend by team size and role, and make trade-offs visible.

4. `What is the cheapest unlimited phone plan with good 5G coverage in 2026?`
   Strong pages combine cost, plan comparison, and carrier trade-offs.

## Weak Cases

These are representative false or weak matches that should not be treated as
good AI SEO examples even if they mention the right terms:

1. grammar pages triggered by interrogative words like `what`, `which`, or `quel`
2. city or portal pages that match geography but not the service task
3. store locator pages that do not compare or recommend
4. forum threads and unrelated community pages that only touch the topic

## Calibration Takeaways

The strongest signals from this corpus are:

- recommendation signal
- trade-off signal
- scenario split
- trust stack: author, date, publisher, citations
- machine readability: title, meta, canonical, JSON-LD
- reusable structure: lists, tables, clear sections

The weaker-than-expected signals are:

- FAQ presence by itself
- question-style headings by themselves

That is why the current model was adjusted to:

- lower the weight of FAQ-style checks
- keep recommendation and trade-off checks heavy
- cap query-fit when a page matches keywords but fails decision intent
- give more influence to query-fit in the final combined score

## How To Use This Casebook

Use it in three passes:

1. Check whether a page is discoverable and machine-readable.
2. Check whether it actually resolves the query with a recommendation or decision path.
3. Check whether trust signals are stacked strongly enough to support citation.

If a page fails step 2, do not let strong metadata hide that weakness.

## Next Upgrade

The next meaningful step is not to blindly add more queries. It is to expand
the corpus with more reviewed page-level cases.

A practical next target is:

- 120 to 150 page-level cases
- strong, mid, and weak labels
- a manually reviewed multilingual slice
- a smaller gold subset reserved for regression testing
