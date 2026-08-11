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

---

# Registry survey (`registry-survey.jsonl`)

A second, independent dataset: not how decisions are *cited*, but how the
registries themselves are *kept*. 326 repositories discovered by fingerprint,
166 with a real registry, **1,926 decisions**.

| Measure | Value |
|---|---|
| Decisions whose text yields a derivable scope | 90.3% |
| Decisions documenting consequences | 89.9% |
| Decisions documenting rejected alternatives | 25.7% |
| Decisions marked superseded | 1.0% |
| Registries that ever marked one superseded | 7% (11/166) |
| Registries dormant (no new decision in >12mo, repo still shipping) | 47.9% |
| Median days to supersession, when it happens | 671 |
| Median decisions per repo | 7 |

The story: teams write decisions and follow the template, then stop maintaining
the registry and effectively never retire anything. A reader cannot tell what is
still in force. Dormant is not unused — Home Assistant's registry took its last
decision in 2024 and caused a revert in 2026.

Caveat: 26.3% of decisions carry an unrecognized status string, so the 1%
supersession rate is a lower bound.
