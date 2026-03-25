# CASEBOOK

AISEO-Rate now ships with a tracked benchmark corpus, not just a scorer.

The goal of this casebook is simple: make the scoring logic explainable,
auditable, and repeatable. Instead of claiming a single magic score, the
project keeps a visible set of pages and comparisons that show what the model is
rewarding and what it is rejecting.

## Corpus Snapshot

- Query benchmark: 28 cleaner medium or high-confidence queries
- Expanded page corpus: 139 scored pages
- Head-to-head comparisons: 28 best-vs-worst query pairs
- Language spread:
  English, Traditional Chinese, Japanese, Korean, German, French, Spanish,
  Portuguese, and Hindi

The benchmark artifacts live in [`benchmark/`](C:\NEW\benchmark):

- [queries_medium_high_top5.csv](C:\NEW\benchmark\queries_medium_high_top5.csv)
- [expanded_scored_results.csv](C:\NEW\benchmark\expanded_scored_results.csv)
- [expanded_summary.csv](C:\NEW\benchmark\expanded_summary.csv)
- [expanded_case_library.csv](C:\NEW\benchmark\expanded_case_library.csv)
- [expanded_query_pairs.csv](C:\NEW\benchmark\expanded_query_pairs.csv)
- [expanded_playbook.md](C:\NEW\benchmark\expanded_playbook.md)

## What This Corpus Is Good For

- checking whether the model rewards pages that actually resolve a task
- finding false positives where keyword overlap hides weak intent resolution
- comparing strong and weak pages inside the same query frame
- turning repeated winners into explicit AI SEO rules

## What It Is Not

- a final multilingual gold benchmark
- a search-engine truth set
- a direct measure of AI citation rates

Public search endpoints still introduce retrieval noise. The corpus is useful
for calibration, but it should not be presented as a universal ranking truth.

## What Strong Pages Repeatedly Do

Across the current expanded corpus, the strongest pages usually:

- make an explicit recommendation
- compare trade-offs instead of listing features only
- split advice by scenario, audience, or budget
- carry author, date, and publisher signals together
- expose clean metadata and structured data
- turn the answer into reusable units such as lists, ranked picks, and tables

This is why the current scoring model weights:

- task resolution
- trust stack
- machine readability
- query fit

more heavily than cosmetic FAQ-style formatting alone.

## What Weak Pages Repeatedly Look Like

The weakest cases are usually one of these:

- grammar or glossary pages matching interrogatives like `what`, `which`, or `quel`
- directory or store-locator pages with no recommendation path
- community threads that mention the topic without resolving it
- generic portal pages that match place names or nouns but miss the task

The scorer should treat these as weak even when they share surface vocabulary
with the query.

## Representative Strong Cases

1. `What is the best espresso machine under $500 for a small apartment?`
   Strong pages make a direct pick, preserve the budget constraint, and discuss
   apartment fit.

2. `Which laptop is best for college and light video editing under $900?`
   Strong pages combine budget, workload, and trade-off framing instead of only
   listing raw specs.

3. `Which CRM is best for a 10-person B2B startup with a small sales team?`
   Strong pages recommend by team size, workflow, and sales complexity.

4. `What is the cheapest unlimited phone plan with good 5G coverage in 2026?`
   Strong pages compare cost, carrier trade-offs, and coverage fit.

## Representative Failure Modes

1. Keyword collision
   Example: pages about grammar, translation, or definitions triggered by
   `what`, `which`, `quel`, or similar tokens.

2. Structural mismatch
   Example: store locators, city portals, or generic listings that are
   crawlable but not decision-ready.

3. Intent mismatch
   Example: a page about the underlying entity, but not the decision the query
   asks the user to make.

## Calibration Decisions Taken So Far

The benchmark directly changed the scorer in a few ways:

- FAQ and question-heading checks were downgraded from heavy signals to lighter
  supporting signals.
- Recommendation and trade-off signals stayed heavy.
- Query-fit now caps pages that match keywords but fail the decision task.
- Combined score gives more weight to query-fit than earlier versions.

## How To Read The Corpus

Use the corpus in this order:

1. Is the page discoverable and machine-readable?
2. Does the page actually resolve the task?
3. Is the trust stack strong enough for citation or reuse?

If a page fails step 2, strong metadata should not rescue it.

## Current Limitation

The corpus is broader now, but it is still partly search-provider constrained.
Some non-English cases remain noisy, and a few queries still retrieve weak
candidate sets even after reranking.

That is why this repository keeps both:

- the benchmark files themselves
- the explanation of what the benchmark can and cannot prove

## Next Upgrade

The next meaningful upgrade is a reviewed corpus, not just a larger one.

A practical target after this version is:

- 150 to 200 page-level cases
- a manually reviewed multilingual slice
- stable strong, mid, and weak labels
- a smaller gold regression set for scorer changes
