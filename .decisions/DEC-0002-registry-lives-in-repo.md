---
id: DEC-0002
title: The decision registry lives in the customer's repository as files
status: accepted
severity: block
scope:
  paths:
    - "verdica/**"
    - "SPEC.md"
deciders: ["@AlbeMiglio"]
date: 2026-08-09
---

## Decision

Decisions are Markdown files in `.decisions/` inside the governed repository. Any hosted service builds indexes *over* these files; it never becomes the source of truth.

## Rationale

Files in the repo mean: zero lock-in (uninstall and keep everything), ratification through the platform's own PR review and CODEOWNERS, and automatic visibility to coding agents, which read the repository as context. This property is the product's main trust argument and must not be traded away for server-side convenience.

## Rejected alternatives

- **Server-side database as source of truth** — easier to query and index, but converts the trust pitch into a lock-in pitch and hides decisions from agents.
