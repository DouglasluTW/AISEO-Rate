# Benchmark Files

This folder contains the tracked benchmark artifacts used to calibrate
AISEO-Rate.

## Files

- `queries_medium_high_top5.csv`
  The 28 cleaner benchmark queries expanded to `top5` retrieval.

- `expanded_scored_results.csv`
  Raw scored rows from the expanded benchmark run.

- `expanded_summary.csv`
  One-row-per-query summary with best result, score averages, and SERP
  confidence.

- `expanded_case_library.csv`
  Page-level case library with `strong`, `mid`, and `weak` benchmark labels.

- `expanded_query_pairs.csv`
  Same-query best-vs-worst comparisons for fast calibration review.

- `expanded_playbook.md`
  A generated summary of recurring signals and common failures.

## Intended Use

Use these files for:

- scorer calibration
- regression checks after weighting changes
- manual review of strong and weak page patterns

Do not treat this folder as a universal ranking truth set. It is a practical
benchmark corpus assembled from public search sources and is still affected by
retrieval quality.
