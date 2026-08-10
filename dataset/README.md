# Decision-regression dataset v1

Built with `decisis mine` (timeline classification) + a Mistral labeling pass
over the real PR threads (`violation yes/no/unclear`). 18 repositories with
ADR/KEP cultures, 207 decision-citing PRs, 53 known-outcome events, 51 labeled.

Headline: 23 confirmed decision violations — 21 blocked manually in review,
2 slipped past it (PR-level slipped rate 8.7%; ~4-9% counting by violation
event, since a revert and its original PR are one event). Only about half of
decision-citing closures are actual violations: naive citation counting
overstates human enforcement.

All content is public GitHub data (URLs, titles, timestamps, labels).
