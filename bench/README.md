# Judge benchmark

A pinned cohort of real (decision, diff, outcome) pairs, used to measure the
contradiction judge and to gate every change to it (DEC-0012).

## What it measures — and what it does not

Each pair gives the judge a decision's full text and a pull request's diff,
and asks the production question: does this diff contradict this decision?
Scores here are a **floor**, not the gate's field quality: the bench feeds the
judge the whole PR patch (capped), while the production funnel first narrows
the diff to the hunks inside the decision's scope — a strictly easier input.

The guarded metric is **high_conf_precision**: precision of high-confidence
contradiction calls, because that is the only signal the gate can ever block
on (DEC-0005). Recall is reported but not guarded; on this cohort it is
structurally understated (see label provenance).

## Where the labels come from

Events were mined from public repositories whose PRs cite a decision record,
then labeled from the full thread outcome (was this actually a violation?).
A thread sees things a diff cannot — process violations, discussion-only
breaches — so some positive labels are invisible to any diff-only judge.
Labels are corrigible: when adjudication shows the judge right and the label
wrong, the label changes by explicit commit with a note.

Adjudication example (2026-08-22): home-assistant#99324 looked like a judge
win (new YAML config vs ADR-0010) until the full ADR text showed the
transport-category carve-out that permits YAML for GPIO integrations — the
label was right, and the miss traced to the bench truncating the decision
text. The cap was raised; the pair stayed.

## Rules of the cohort

- `pairs.jsonl` is committed and only changes by explicit commit, never by
  re-mining in place. A benchmark whose population moves is not a benchmark.
- PRs that touch the registry itself are excluded: judging a decision against
  the diff that introduces it is not the production task.
- `baseline.json` holds the scores every change must not regress
  (`run.py --check`, margin in the script).

## Running it

```
GITHUB_TOKEN=... python3 bench/build_pairs.py   # only to grow the cohort
MISTRAL_API_KEY=... python3 bench/run.py        # score
MISTRAL_API_KEY=... python3 bench/run.py --check  # score + fail on regression
```

CI runs `--check` on every push touching the judge (.github/workflows/bench.yml).
