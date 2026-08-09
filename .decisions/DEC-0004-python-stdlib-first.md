---
id: DEC-0004
title: One language (Python), stdlib-first, minimal dependencies
status: accepted
severity: warn
scope:
  paths:
    - "decisis/**"
    - "pyproject.toml"
deciders: ["@AlbeMiglio"]
date: 2026-08-09
---

## Decision

The whole tool — miner, gate, CLI — is Python. Dependencies are limited to what the stdlib genuinely cannot do: `pyyaml` (frontmatter), `anthropic` (judge). HTTP to GitHub uses `urllib` from the stdlib.

## Rationale

One language keeps miner and gate sharing the same format code, keeps the Action a two-step composite (`pip install` + run), and keeps the audit surface small for people deciding whether to run this in their CI.

## Rejected alternatives

- **TypeScript for the Action, Python for the miner** — idiomatic for GitHub Actions, but splits the format logic in two and doubles the maintenance for a solo maintainer.
