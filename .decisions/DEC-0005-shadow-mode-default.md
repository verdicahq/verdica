---
id: DEC-0005
title: The gate never blocks by default; blocking is opt-in per decision
status: accepted
severity: block
scope:
  paths:
    - "verdica/gate.py"
    - "verdica/cli.py"
    - "action.yml"
deciders: ["@AlbeMiglio"]
date: 2026-08-09
---

## Decision

Default behavior is report-only (`fail-on: never`). A check may fail only when all three hold: the workflow opts in (`fail-on: block`), the decision declares `severity: block`, and the judge's confidence is `high`.

## Rationale

Trust is spent once. A single wrong blocking check gets the tool removed from CI; a weekly summary that is occasionally wrong is forgiven. Teams promote individual decisions to blocking after the tool has earned it in shadow mode.

## Rejected alternatives

- **Block-by-default with a global sensitivity knob** — maximizes headline value, but the first false positive on a team's release-day PR ends the relationship.
