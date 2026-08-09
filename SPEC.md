# The `.decisions/` format — v0.1

A decision record is a Markdown file with YAML frontmatter, stored in the repository under `.decisions/`. The repository is the source of truth: decisions are reviewed, ratified, and superseded through ordinary pull requests. Any tool that reads this format sees the same registry.

## File layout

```
.decisions/
  DEC-0001-integrations-no-yaml-config.md
  DEC-0002-postgres-over-mongo.md
```

Filename: `<id>-<kebab-case-slug>.md`. The `id` in frontmatter is authoritative; the filename is for humans.

## Frontmatter fields

```yaml
---
id: DEC-0001
title: Integrations must not add YAML config options
status: accepted          # proposed | accepted | superseded
severity: warn            # warn | block  (how the gate reacts to violations)
scope:
  paths:
    - "homeassistant/components/**"
deciders: ["@alice", "@marco"]
date: 2026-03-12
supersedes: null          # id of the decision this replaces, if any
superseded_by: null       # filled when a later decision replaces this one
---
```

| Field | Required | Notes |
|---|---|---|
| `id` | yes | Unique, immutable. `DEC-` prefix recommended; tools must accept any `[A-Z]+-\d+` scheme (`ADR-`, `RFC-`, …). |
| `title` | yes | One sentence stating the decision, not the topic. "Use Postgres for the order store", not "Database choice". |
| `status` | yes | `proposed` → `accepted` → `superseded`. Never delete a file; supersede it. |
| `severity` | no | `warn` (default): findings go to the digest/summary. `block`: the gate fails the check. |
| `scope.paths` | yes | Glob patterns relative to the repo root. `dir/**` matches everything under `dir/`; elsewhere `*` matches across path separators (fnmatch semantics), so `*.tf` matches at any depth. A decision with no meaningful path scope may use `["**"]`, at the cost of being checked on every change. |
| `deciders` | no | GitHub handles of the people who ratified it. |
| `date` | no | ISO date of ratification. |
| `supersedes` / `superseded_by` | no | The supersession chain. A superseded decision keeps `status: superseded` and points forward. |

## Body

Free Markdown. Recommended sections, in this order:

```markdown
## Decision
The single statement, expanded if needed.

## Rationale
Why — including the constraints that were true at the time.

## Rejected alternatives
- **Option B** — why it lost.
```

The `## Rejected alternatives` section matters: most decision regressions re-propose an alternative that was already considered and rejected.

## Ratification model

The format defines no approval mechanism of its own — it reuses the host platform's:

- A **new decision** is a PR adding a file with `status: proposed`; merging it after review with the status flipped to `accepted` is the ratification.
- **Changing or retiring** a decision is a PR adding a successor file and setting `superseded_by` on the old one.
- A `CODEOWNERS` entry for `.decisions/` defines who must approve — the quorum, expressed in a mechanism reviewers already know.

## Compatibility

Existing ADRs in the MADR or adr-tools formats convert mechanically: title → `title`, status line → `status`, the ID from the filename. Converters should preserve the original body verbatim below the frontmatter.

## Organization scope

Decisions that apply across repositories live in the organization's `.github` repository under `.github/decisions/`, same format. Repository-local decisions extend or narrow them; on a scope conflict the more specific (repository-level) decision wins.
