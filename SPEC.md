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
| `category` | no | `strategy` \| `product` \| `design` \| `engineering` (default) \| `process`. See "Categories" below — the category routes where and how the decision is enforced. |
| `scope.paths` | yes | Glob patterns relative to the repo root. `dir/**` matches everything under `dir/`; elsewhere `*` matches across path separators (fnmatch semantics), so `*.tf` matches at any depth. A decision with no meaningful path scope may use `["**"]`, at the cost of being checked on every change. |
| `deciders` | no | GitHub handles of the people who ratified it. |
| `date` | no | ISO date of ratification. |
| `supersedes` / `superseded_by` | no | The supersession chain. A superseded decision keeps `status: superseded` and points forward. |

## Nature: standing vs tradeoff

Not every decision is meant to last. `nature: standing` (the default) marks a
deliberate lasting choice. `nature: tradeoff` marks a temporary compromise tied
to a contingent requirement — a feature currently disabled, a launch that has
not happened, a provider limit. A tradeoff carries `revisit_when`, the event
that should reopen it, stated in plain language:

```yaml
nature: tradeoff
revisit_when: "in-app payments go live"
```

Semantics: a tradeoff gates like any accepted decision, but every gate report
labels it and names its condition; the digest lists all standing tradeoffs
under "Tradeoffs due for review" until each is either promoted to `standing`
or superseded. A diff that fulfils the condition is grounds for supersession,
not a violation. A `revisit_when` without `nature` implies `tradeoff`.

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

## Categories

The category is a routing key, not a label: it determines the natural enforcement surface, the sensible default severity, and who plausibly ratifies.

| Category | Typical decision | Natural enforcement surface | Severity ceiling |
|---|---|---|---|
| `strategy` | target market, business model, build-vs-buy | digest and supersession review only — rarely diff-checkable | warn |
| `product` | pricing values, feature scope, plan limits | config/copy/pricing paths in the gate | block |
| `design` | palette, typography, interaction rules | theme code, static pages, store assets (image surfaces need a vision judge) | warn |
| `engineering` | architecture, stack, patterns, invariants | code paths in the PR gate — the core case | block |
| `process` | versioning, release flow, review rules | CI/workflow files, manifest files | block |

A `strategy` decision that never gates still earns its file: it is the thing later decisions cite in `supersedes` chains, and the first thing the re-alignment surfaces show.

## Sources and provenance

Decisions enter the registry from anywhere the team actually decides; the file records where each came from. Bootstrap extraction reads the repository itself (normative comments, convention docs, reverts, review threads). Additional source adapters feed the same pipeline as plain mentions-with-provenance: meeting notes (e.g. Granola exports dropped in a watched folder or pushed via API), postmortems and retro documents — the natural home of **lessons learned**, which are decisions whose rationale cites the incident that taught them. A tool must never invent a decision without citable provenance.

## Ratification model

The format defines no approval mechanism of its own — it reuses the host platform's:

- A **new decision** is a PR adding a file with `status: proposed`; merging it after review with the status flipped to `accepted` is the ratification.
- **Changing or retiring** a decision is a PR adding a successor file and setting `superseded_by` on the old one.
- A `CODEOWNERS` entry for `.decisions/` defines who must approve — the quorum, expressed in a mechanism reviewers already know.

## Compatibility

Existing ADRs in the MADR or adr-tools formats convert mechanically: title → `title`, status line → `status`, the ID from the filename. Converters should preserve the original body verbatim below the frontmatter.

## Organization scope

Decisions that apply across repositories live in the organization's `.github` repository under `.github/decisions/`, same format. Repository-local decisions extend or narrow them; on a scope conflict the more specific (repository-level) decision wins.
