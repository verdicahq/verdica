---
id: DEC-0010
title: Open core — the engine is Apache, the convenience is sold
status: accepted
severity: block
category: strategy
scope:
  paths:
    - "LICENSE*"
deciders: [alberto]
date: 2026-08-19
---

## Decision

Verdica is open core:

- **Open forever (Apache-2.0):** the `.decisions/` format, the CLI, and the GitHub Action. Anyone can adopt the format, run the gate self-hosted with their own LLM key, and leave with their registry intact.
- **Never opened:** the hosted app — one-click GitHub App, bundled LLM judgment, cross-repo dashboard, digest delivery, meeting/email connectors, SSO. That is the product being sold, priced per repo per month and billed through GitHub Marketplace.

A pull request that touches `LICENSE*` gates against this decision.

## Rationale

- **A gatekeeper must be inspectable.** The tool reads private code and blocks pull requests; visible source is what makes teams willing to install it at all.
- **A format only wins as a commons.** Teams commit their decision registry to `.decisions/` because no vendor holds it hostage. A closed format is a dead format.
- **At zero marketing budget, the open repo is the distribution.** For an unknown solo vendor the counterfactual to "open" is not "closed and paid" — it is "closed and never discovered".
- **The buyer pays for absence of work, not for code.** Self-hosting demands a CLI, an API key, and CI wiring; the hosted app is a button. Companies with budget buy the button. This is the proven devtools pattern (Sentry, GitLab, PostHog, Supabase).

## Risk accepted

Some teams will self-host free forever. Accepted: a team that runs the gate with its own key was never a customer — it is unpaid evangelism for the format, and the format's network effect accrues to its maintainer.

## Rejected alternatives

- **Fully closed, license-per-seat** — undiscoverable at zero budget; kills the format's commons value; distrusted as an opaque gatekeeper.
- **Fully open including the server** — leaves nothing to sell but support; support is a consultancy, not a product.
- **Copyleft (GPL/AGPL) core** — legal-review friction at exactly the wrong moment: adoption. Apache removes every excuse.
