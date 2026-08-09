---
id: DEC-0006
title: Scopes are declared by concern; the tool proposes widenings, never invents them
status: accepted
severity: block
scope:
  paths:
    - "decisis/gate.py"
    - "decisis/formats.py"
    - "SPEC.md"
deciders: ["@AlbeMiglio"]
date: 2026-08-09
---

## Decision

A decision's scope must enumerate every surface where its concern manifests, not the one directory where it was first implemented: a design-direction decision governs the theme code AND the static web pages AND the store assets. The bootstrap proposes concern-complete scopes. A semantic advisor pass may flag changes that fall outside every declared scope but plausibly touch a decision's topic — as scope-widening suggestions in the digest, requiring a ratified scope edit to take effect. The advisor never gates: this composes with DEC-0003 (deterministic scope match is the only gate) and DEC-0005 (nothing blocks by default).

## Rationale

Field test on a real repository: a dark palette landed on web legal pages while the design decision's scope covered only `app/lib/core/theme/**` — the change was invisible to the gate. Widening to all visual surfaces caught it, and also surfaced store assets governed by the same concern. Scope quality, not judge quality, was the limiting factor. The failure mode of narrow scopes is silent misses; the failure mode of broad scopes is noise (a routing JSON caught by `app/web/**`). Both are scope-authoring problems — the tool's job is to make good scopes easy, not to replace them with inference.

## Rejected alternatives

- **Semantic matching as a fallback gate for out-of-scope changes** — re-proposes what DEC-0003 already rejected; the false-positive rate erodes trust faster than the recall earns it.
- **Auto-widening scopes without ratification** — a scope edit changes what the team promised to enforce; silent changes to that promise are exactly what this product exists to prevent.
