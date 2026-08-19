---
id: DEC-0010
title: Open core — the format, CLI and Action are Apache-2.0; the hosted tier is the product
status: accepted
severity: warn
category: strategy
scope:
  paths:
    - "LICENSE"
    - "pyproject.toml"
    - "action.yml"
deciders: [alberto]
date: 2026-08-17
---

## Decision

The `.decisions/` format, the CLI and the GitHub Action are open source under Apache-2.0, in a public repository. Revenue comes from the hosted tier: the one-click GitHub App with the LLM judgment included, cross-repo dashboards, digests and ingestion connectors. The hosted server is not published.

## Rationale

- The gate reads private code and blocks pull requests: teams do not install opaque gatekeepers. Visible source is an adoption requirement, not a courtesy.
- The format only wins as a commons. A team commits its registry to `.decisions/` only if the format is demonstrably not hostage to a vendor.
- At zero marketing budget, distribution *is* the public repository. For a solo unknown vendor the counterfactual of "open" is not "closed and paid" — it is "closed and undiscovered".
- The paying customer buys the button, not the code: hosted setup, keys managed, judgment included. Self-hosters with their own API key were never the customer.

## Boundary

Never published, regardless of pressure: the hosted server, cross-repo dashboards, email-in ingestion, SSO, billing integration. Opening any of these takes a supersession of this decision, not a pull request that "just adds a folder".

## Rejected alternatives

- **Fully closed** — maximizes theoretical capture of a market it would never reach.
- **Fully open (server included)** — donates the hosted margin to any competitor with a sales team.
- **FSL/BUSL on everything** — poisons the commons argument for the format itself; source-available is not open when the ask is "trust this gatekeeper".
