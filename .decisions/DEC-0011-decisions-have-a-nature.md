---
id: DEC-0011
title: Decisions declare their nature — standing choice or temporary tradeoff
status: accepted
severity: block
category: product
scope:
  paths:
    - "SPEC.md"
    - "verdica/formats.py"
    - "verdica/bootstrap.py"
deciders: [alberto]
date: 2026-08-20
---

## Decision

Every decision carries `nature: standing | tradeoff`; tradeoffs carry
`revisit_when`, the plain-language event that reopens them. The distiller
classifies nature and must cite the motivating requirement; the gate labels
tradeoff findings with their condition; the digest resurfaces open tradeoffs
until promoted or superseded.

## Rationale

Field evidence from the first hosted deployment (pluggers-it/mvp, PR #145):
the bootstrap extracted "the call-out fee is not shown" as a rule, when the
truth was contingent — payments are disabled until launch, and the fee hides
only while no money flows through the app. A registry that freezes snapshots
as laws will later fight the very change that was always intended. Decisions
must be integrated with their motivations; a decision motivated by a
contingent requirement inherits that requirement's expiry.

## Rejected alternatives

- **Status quo (everything standing)** — turns temporary states into permanent
  law; the gate would flag reintroducing the call-out fee when payments ship.
- **A sunset date instead of a condition** — compromises expire on events, not
  calendars; "when payments go live" cannot be a date.
- **Dropping contingent rules entirely** — loses real protection: while the
  condition holds, the tradeoff is exactly as enforceable as any rule.
