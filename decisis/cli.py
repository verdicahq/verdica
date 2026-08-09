"""decisis — decisions as files, enforced on every diff."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

TEMPLATE = """---
id: DEC-0001
title: <one sentence stating the decision>
status: proposed
severity: warn
scope:
  paths:
    - "src/**"
deciders: []
---

## Decision

## Rationale

## Rejected alternatives
"""


def cmd_init(args: argparse.Namespace) -> int:
    ddir = Path(args.root) / ".decisions"
    ddir.mkdir(exist_ok=True)
    template = ddir / "DEC-0001-example.md"
    if not template.exists():
        template.write_text(TEMPLATE, encoding="utf-8")
        print(f"created {template}")
    print("Edit the template, open a PR, ratify by merging with status: accepted.")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    from .gate import render_summary, run_gate, should_fail

    findings = run_gate(Path(args.root), args.base)
    summary = render_summary(findings)
    print(summary)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write(summary)
    return 1 if should_fail(findings, args.fail_on) else 0


def cmd_mine(args: argparse.Namespace) -> int:
    from .miner import mine, summarize, to_jsonl

    results = mine(args.repo, cap=args.cap, search_hint=args.hint)
    if args.out:
        Path(args.out).write_text(to_jsonl(results), encoding="utf-8")
    print(json.dumps(summarize(results), indent=2))
    for r in results:
        if r.classification in ("revert_citing", "flagged_post_merge"):
            print(f"  [{r.classification}] {r.url}  {r.title}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="decisis", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="scaffold .decisions/ in a repository")
    p_init.add_argument("--root", default=".")
    p_init.set_defaults(func=cmd_init)

    p_check = sub.add_parser("check", help="check the current diff against recorded decisions")
    p_check.add_argument("--root", default=".")
    p_check.add_argument("--base", required=True, help="base ref, e.g. origin/main")
    p_check.add_argument("--fail-on", choices=["never", "block"], default="never")
    p_check.set_defaults(func=cmd_check)

    p_mine = sub.add_parser("mine", help="mine a repo's history for decision citations")
    p_mine.add_argument("repo", help="owner/name")
    p_mine.add_argument("--cap", type=int, default=100, help="max PRs to analyze")
    p_mine.add_argument("--hint", default="ADR-", help="search text locating citing PRs")
    p_mine.add_argument("--out", help="write per-PR results as JSONL")
    p_mine.set_defaults(func=cmd_mine)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
