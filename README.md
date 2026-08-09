# decisis

Team decisions as files in the repo, enforced on every diff.

Teams decide things — "integrations must not add YAML config options", "Postgres, not Mongo, for the order store" — and then the decision gets violated months later by someone who wasn't in the room. Review misses it, the change merges, and the cost is paid twice: once as an incident or a revert, once as the re-litigation of a settled question. It happens to the best-run projects: [home-assistant/core#149379](https://github.com/home-assistant/core/pull/149379) passed review and merged, then had to be [reverted](https://github.com/home-assistant/core/pull/149544) because it violated two recorded architecture decisions.

decisis keeps decisions where the code is and checks every pull request against them.

- **Decisions are files** in `.decisions/` — reviewed, ratified, and superseded through ordinary PRs. `CODEOWNERS` on the directory defines who ratifies. No lock-in: it's your repo. See [SPEC.md](SPEC.md).
- **The gate is precision-first.** A deterministic path-scope match decides *which* decisions govern a change; only on a scope hit does an LLM judge whether the diff *contradicts* the decision. No key configured → the check still reports "this change touches the scope of DEC-0007", which is most of the value at zero cost.
- **Agents read files.** Decisions in the repo are automatically part of the context of any coding agent working there — the registry is the memory that agents lack between sessions.

## Use as a GitHub Action

```yaml
# .github/workflows/decisis.yml
name: decisis
on: [pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: AlbeMiglio/decisis@main
        with:
          base: ${{ github.base_ref }}
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}  # optional
```

Runs in your CI, with your key. Nothing leaves your infrastructure except the diff hunks sent to the model you configured — and nothing at all if you run without a key.

## CLI

```bash
pip install decisis

decisis init                      # scaffold .decisions/ with a template
decisis check --base origin/main  # check the current branch's diff
decisis mine owner/repo           # mine a repo's history for decision citations
```

`decisis mine` classifies every PR that cites a decision record (ADR/KEP/DEC/RFC) by timeline: cited during review, cited only after the merge, or a revert citing a decision — the last two are violations that slipped through. Run it on your own repository to see what a gate would have caught; it needs `GITHUB_TOKEN` and nothing else.

## Severity

Each decision declares how the gate reacts to a violation: `warn` (default — the finding goes to the check summary) or `block` (the check fails, only on high-confidence contradictions). Start everything at `warn`; promote a decision to `block` when you trust it.

## Configuration

| Env var | Default | |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | enables the contradiction judge |
| `DECISIS_MODEL` | `claude-opus-5` | any Anthropic model id |
| `GITHUB_TOKEN` | — | required by `decisis mine` |

## Bootstrap (from zero to hero)

```bash
decisis bootstrap                      # report-only: what it would propose
decisis bootstrap --notes ~/meetings   # include meeting exports (Granola, retros)
decisis bootstrap --write              # write proposals into .decisions/
decisis bootstrap --pr                 # write, branch, and open the bootstrap PR
```

The bootstrap extracts decision candidates from what the repo already contains — normative comments and docs, reverts, convention files, plus any notes folder you point it at — clusters the evidence, backtests the proposals against your recent merges (noisy scopes get demoted, decisions that would have caught a reverted merge get a receipt), and asks at most five one-tap questions for the calls it genuinely cannot make alone. Everything it proposes cites its evidence; nothing is invented. Machine-enforced rules (lint, CI) are recognized and linked, never duplicated.

## License

Apache-2.0
