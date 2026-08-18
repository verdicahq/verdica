---
id: DEC-0001
title: The product is named "Verdica"
status: accepted
severity: warn
scope:
  paths:
    - "README.md"
    - "pyproject.toml"
    - "action.yml"
deciders: [alberto]
date: 2026-08-17
---

## Decision

The product is named **Verdica** — a working name, chosen deliberately and revisitable at the first paying customer. Until then the name is settled: no relitigating it per commit.

## Rationale

- *Verdict* comes from **vere dictum** — "truly said". Verdica is the feminine coinage of that root: the recorded pronouncement the team stands by.
- To an Italian ear it sits one step from **verifica** — and verifying recorded verdicts on every diff is literally what the gate does.
- Sound profile matches the brand register we validated: hard consonant core, three open syllables, clean `-a` ending, pronounceable identically in Italian and English.
- Availability at decision time (2026-08-17): `verdica.dev`, PyPI `verdica`, npm `verdica` free; GitHub org `verdicahq` free.

## Known risk, accepted

**Vertica** (the OpenText/ex-HP analytics database) is one consonant away and near-homophone in fast speech. Accepted because the corridors are distant (analytics DB vs. decision gate), Vertica's brand is enterprise-legacy and fading post-acquisition, and written contexts — where a devtool lives — are unambiguous.

## Rejected alternatives

~150 candidates verified across ten registers (2026-08-09 → 2026-08-17). Representative rejections:

- **decisis** — the original working name; rejected on sound (three syllables, double sibilant, legal dust).
- **deciso, decided, decisor, decisia, decisio** — the same root, all owned: Deciso B.V. (OPNsense), squatters, Lexum, Decisio Health. On the *decid-* root only the Latin plurals were free.
- **kiaro** — killed by kiaro.io (live B2B SaaS) and Kiaro!® (AstroNova registered mark).
- **still, stable, charter, ontrack** — concept-right, namespace-gone (Stability AI, stablecoins, Kroll Ontrack; charter survives but generic SERP).
- **holds, stands, givens** — available and exact, but no gut signal from the founder.
- **traietta, rettavia, dirittura** — fully clean coinages, rejected on register (diminutive/moralistic).
