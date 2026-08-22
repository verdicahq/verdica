---
id: DEC-0012
title: No judge or prompt change ships without benchmark non-regression
status: accepted
severity: block
category: engineering
scope:
  paths:
    - "verdica/gate.py"
    - "verdica/llm.py"
    - "bench/**"
deciders: [alberto]
date: 2026-08-22
---

## Decision

The judge's quality is measured, not assumed. `bench/pairs.jsonl` is a pinned
cohort of real (decision, diff, outcome) pairs from labeled history; every
change to the judge, its prompt, or the provider layer must run `bench/run.py
--check` and not regress `high_conf_precision` (the only signal the gate ever
blocks on) beyond the stated margin. The cohort only grows by explicit commit,
never by re-mining in place: a benchmark whose population moves between runs
is not a benchmark.

## Rationale

Quality direction set by Alberto (2026-08-22): first a benchmark that hardens
over time, then, on top of it, a fine-tuned model for the judging task once
volume justifies it. The bench is the prerequisite for the fine-tune: you
cannot train what you cannot measure. Precision is the guarded metric because
of DEC-0005: a gate that blocks on a wrong verdict spends trust it cannot buy
back.

## Rejected alternatives

- **Unit tests only** — they pin code paths, not judgment quality.
- **Trusting provider upgrades** — a model swap is exactly the change most
  likely to shift verdicts silently.
- **Live cohort re-mined per run** — population drift masquerades as quality
  movement (measured on this project: a growing pool silently changed a
  "top 20" selection cohort).
