---
id: DEC-0008
title: The LLM provider is pluggable and chosen by the repo owner; Mistral is the reference default
status: accepted
severity: block
category: engineering
scope:
  paths:
    - "verdica/llm.py"
    - "verdica/gate.py"
    - "verdica/bootstrap.py"
    - "pyproject.toml"
deciders: ["@AlbeMiglio"]
date: 2026-08-09
---

## Decision

All model calls go through one provider-neutral layer (`verdica/llm.py`): a single JSON-in/JSON-out completion function. The repo owner picks the provider via their credentials and `VERDICA_PROVIDER`; auto-detection prefers Mistral when both keys are present. No provider SDK is a required dependency (Mistral speaks stdlib HTTP; the Anthropic SDK is an optional extra). Every feature must degrade to keyless mode.

## Rationale

The gate runs inside the customer's CI with the customer's key: which model bills them is their decision, not the tool's. Hardcoding a vendor would also contradict the product's own trust pitch (no lock-in, files are yours).

## Rejected alternatives

- **Anthropic-only** — the initial implementation; rejected the moment it met a real deployment preference.
- **A heavyweight abstraction (LiteLLM-style dependency)** — one function over two HTTP dialects does not justify a dependency tree in a tool teams audit before running in CI.
