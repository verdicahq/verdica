# Decision-regression dataset v1.1

Built with `decisis mine` (deterministic timeline classification) plus a
labeling pass over the real PR threads via `decisis.llm` (Mistral):
violation yes / no / unclear.

34 repositories with ADR/KEP cultures scanned, 16 carrying decision-citation
signal, 225 decision-citing PRs classified, 54 known-outcome events, all
labeled.

| Outcome | caught_unmerged | flagged_post_merge | revert_citing |
|---|---|---|---|
| Confirmed violation | 21 | 1 | 1 |
| Process citation (no) | 25 | 1 | 0 |
| Unclear | 4 | 1 | 0 |

Headline: **23 confirmed decision violations - 21 blocked by hand in review,
2 slipped past it.** PR-level slipped rate 8.7%; ~4-9% counting by violation
event (a revert and its original PR are one event).

Second finding: **fewer than half of decision-citing closures are actual
violations** (21 yes vs 25 no). Counting citations without labeling
overstates human enforcement roughly twofold - which is why the pipeline
separates deterministic timeline classification from semantic judgment.

All content is public GitHub data (URLs, titles, timestamps, labels).
