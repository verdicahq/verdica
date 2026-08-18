---
id: DEC-0003
title: Scope matching is deterministic (path globs); the LLM judges only scope hits
status: accepted
severity: block
scope:
  paths:
    - "verdica/gate.py"
    - "verdica/formats.py"
deciders: ["@AlbeMiglio"]
date: 2026-08-09
---

## Decision

Which decisions govern a change is decided by path-glob matching — no model involved. The LLM is consulted only after a scope hit, and only to judge contradiction.

## Rationale

Precision failures kill adoption: a wrong blocking comment on a PR gets the tool uninstalled. Path matching has near-zero structural false positives and costs nothing; the expensive, fallible judgment is reserved for the few changes that already touch a governed area. Semantic-only matching (embeddings over the whole diff) was measured in exploration to be too noisy to ship as a default.

## Rejected alternatives

- **Semantic matching as the primary filter** — recalls violations outside declared scopes, but at a false-positive rate that erodes trust faster than the extra recall earns it. Revisit as an *additional* opt-in signal, never as the default gate.
