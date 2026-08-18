---
id: DEC-0007
title: Five categories, used as routing keys - strategy, product, design, engineering, process
status: accepted
severity: warn
category: product
scope:
  paths:
    - "SPEC.md"
    - "verdica/formats.py"
    - "verdica/bootstrap.py"
deciders: ["@AlbeMiglio"]
date: 2026-08-09
---

## Decision

Every decision carries one of five categories: strategy, product, design, engineering, process. The category is a routing key, not a tag: it determines the natural enforcement surface (strategy -> digest only; product -> config/pricing paths; design -> visual surfaces; engineering -> code paths; process -> CI/manifest files), the sensible severity ceiling, and who plausibly ratifies. Extraction assigns it automatically (path/text heuristics keyless, LLM with key); the user corrects it in review like any other field.

## Rationale

A flat list of decisions stops scaling at ~20: teams need to see "the design rules" or "the pricing rules" as units, and the tool needs to know that a strategy decision cannot gate a diff while a process decision naturally gates CI files. Five is the smallest set where every real decision found in field tests fit without a "misc" bucket.

## Rejected alternatives

- **Free-form tags** - no routing semantics, immediate taxonomy drift between repos of the same org.
- **Two categories (technical / non-technical)** - loses the enforcement-surface distinction that makes the category useful to the gate.
