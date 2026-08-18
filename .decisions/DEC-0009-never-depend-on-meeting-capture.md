---
id: DEC-0009
title: Ingestion never depends on meeting capture; the repository is the load-bearing source
status: accepted
severity: block
category: product
scope:
  paths:
    - "verdica/bootstrap.py"
    - "README.md"
    - "SPEC.md"
deciders: ["@AlbeMiglio"]
date: 2026-08-10
---

## Decision

Every feature must produce its full value from repository evidence alone. Meeting notes, chat exports and any future source adapter are additive: they enrich provenance and catch decisions the code cannot show, but no onboarding step, demo, or headline capability may require them.

## Rationale

Field evidence from three consecutive attempts to capture one real team meeting: the notetaker was not installed, then it was not used, then no notes were taken at all. Meeting capture depends on a human remembering, in the moment, to run a tool - the least reliable link in the chain. Meanwhile the same repository yielded extractable decisions from its own comments, docs and history with nothing required of anyone. A product whose first-run value waits on a note that may never exist has an adoption cliff at step one.

## Rejected alternatives

- **Meeting-first onboarding ("connect your notetaker to get started")** - fails whenever capture fails, which field-tested at three times out of three.
- **Treating note sources as equal-rank inputs** - would let a missing note degrade extraction quality rather than merely narrow it.
