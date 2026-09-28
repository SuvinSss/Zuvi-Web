# Search suggestions and spelling recovery

Implemented locally on `codex/search-suggestions` after the preceding UI release
was deployed successfully to UAT at commit `353734c`.

## Customer behavior

- Header and catalogue-field suggestions begin after one character and a 200 ms pause.
- Up to six products and two matching categories, plus View all results.
- Exact product names and prefixes rank before other exact or close matches.
- Product-name spelling recovery uses PostgreSQL word-trigram similarity.
  Examples verified: `bred` → Whole wheat bread; `tomatoe` and `tomtaoes` → Fresh tomatoes.
- Very short queries use exact matching only. Similarity is approximate, not a
  guarantee that every misspelling or synonym is understood.
- Results default to Best match for a search. Explicit price/name/date sorting
  and existing category, brand and price filters remain available.
- Close-match results are labeled rather than silently replacing the query.
- Arrow keys, Enter, Escape, click and touch are supported. Suggestions expose
  combobox/listbox states; requests are debounced, cancelled on input changes,
  and stale responses cannot replace newer results. Normal form submission
  remains available when suggestions fail or JavaScript is unavailable.

## Data and deployment

The same public-product queryset enforces approval, active stores/categories,
sellable stock and expiry. Suggestions expose name, final price and public links
only. No merchant identity, cost, margin or internal stock data is returned.
No search history or customer profiling is stored.

Before deploying this branch, run `python manage.py migrate` to enable `pg_trgm`
via migration `catalog.0007_search_trigrams`. Applied only to the isolated local
review database so far. The deployment database role needs permission to create
this PostgreSQL extension. This upgrade has not been pushed or deployed.

Similarity scoring is performed in PostgreSQL, with a bounded response and no
Python catalogue scan. Large-catalogue latency/load has not been benchmarked;
before broad rollout, measure query plans against representative data and add
an indexed search document/candidate lookup if needed. No speculative GIN index
was added for a score comparison that would not use it.

Implementation reference: [Django PostgreSQL search documentation](https://docs.djangoproject.com/en/5.2/ref/contrib/postgres/search/).

## Verification

- 33 search/public-catalogue tests passed, including typo recovery, exact-first
  ranking, visibility protection, multiple tags, bounded query input and filters.
- JavaScript syntax and git whitespace checks passed. No missing model migrations.
- Browser: mobile 390 × 844 and desktop 1440 × 1000; mobile width stayed 390px.
- Verified typo suggestion, categories, empty suggestions, short-input dismissal,
  arrow-key selection, Escape, Enter navigation and Best match result ordering.
- Screenshots: `artifacts/ui-ux/search-suggestions-mobile.png` and
  `artifacts/ui-ux/search-suggestions-desktop.png`.
- Live network-failure behavior, formal screen-reader testing and production
  performance have not been certified.
