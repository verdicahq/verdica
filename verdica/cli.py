"""verdica — decisions as files, enforced on every diff."""

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
    from .gate import (advise_scope, changed_files, post_pr_comment,
                       preview_decisions, render_summary, run_gate, should_fail)

    root = Path(args.root)
    findings = run_gate(root, args.base)
    summary = render_summary(findings)
    if not args.no_advisor:
        suggestions = advise_scope(root, args.base, changed_files(args.base, root))
        if suggestions:
            summary += ("\n## Scope suggestions\n\nNot enforced — a scope widening "
                        "takes a ratified edit:\n\n" + "\n".join(suggestions) + "\n")
    preview = preview_decisions(root, args.base)
    if preview:
        summary += ("\n## If you merge this, the rules change\n\nReplayed over "
                    "the recent history:\n\n" + "\n".join(preview) + "\n")
    print(summary)
    if args.comment:
        print(post_pr_comment(summary))
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write(summary)
    return 1 if should_fail(findings, args.fail_on) else 0


def cmd_digest(args: argparse.Namespace) -> int:
    from .gate import render_digest

    digest = render_digest(Path(args.root), args.since)
    print(digest)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write(digest)
    return 0


def cmd_bootstrap(args: argparse.Namespace) -> int:
    import subprocess
    import sys as _sys

    from .bootstrap import run_bootstrap

    answers = [int(x) for x in args.answers.split(",") if x.strip()] if args.answers else None
    interactive = args.interactive or (answers is None and _sys.stdin.isatty())
    report = run_bootstrap(
        Path(args.root), top=args.top, prs=args.prs,
        write=args.write or args.pr,
        notes=Path(args.notes) if args.notes else None,
        answers=answers, interactive=interactive and not answers,
        html_out=Path(args.html) if args.html else None,
    )
    print(report)
    if args.pr:
        root = Path(args.root)
        dirty = subprocess.run(["git", "-C", root, "status", "--porcelain"],
                               capture_output=True, text=True).stdout
        if any(not line[3:].startswith(".decisions/") for line in dirty.splitlines()):
            print("\nrefusing --pr: working tree has changes outside .decisions/")
            return 1
        for cmd in (["git", "-C", root, "checkout", "-b", "verdica/bootstrap"],
                    ["git", "-C", root, "add", ".decisions"],
                    ["git", "-C", root, "commit", "-m",
                     "Bootstrap the decision registry\n\nProposed by verdica "
                     "bootstrap from the repository's own evidence. Review each "
                     "decision, delete what is wrong, merge to ratify."],
                    ["git", "-C", root, "push", "-u", "origin", "verdica/bootstrap"]):
            if subprocess.run(cmd).returncode != 0:
                return 1
        pr = subprocess.run(
            ["gh", "pr", "create", "--title", "Bootstrap the decision registry",
             "--body", f"```\n{report}\n```\n\nMerging this PR ratifies the "
             "decisions left in `.decisions/` — delete or edit before merging."],
            cwd=root)
        return pr.returncode
    return 0


def cmd_survey(args: argparse.Namespace) -> int:
    from dataclasses import asdict

    from .survey import aggregate, discover, survey_repo

    token = os.environ["GITHUB_TOKEN"]
    if args.discover:
        repos = discover(tuple(args.discover.split("|")), token, args.cap)
        print("\n".join(repos))
        if args.out:
            Path(args.out).write_text("\n".join(repos), encoding="utf-8")
        return 0
    if args.repos_file:
        repos = [r.strip() for r in Path(args.repos_file).read_text().splitlines() if r.strip()]
    else:
        repos = [args.repo]
    surveys = []
    if args.out and Path(args.out).exists():  # resume: skip what is already written
        from .survey import RepoSurvey

        done = set()
        for line in Path(args.out).read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                done.add(row["repo"])
                surveys.append(RepoSurvey(**row))
        repos = [r for r in repos if r not in done]
        print(f"resuming: {len(done)} already surveyed, {len(repos)} to go")
    for i, repo in enumerate(repos, 1):
        s = survey_repo(repo, token)
        surveys.append(s)
        print(f"[{i}/{len(repos)}] {repo}: "
              + (s.error or f"{s.n} decisions in {s.dir}, "
                            f"{s.superseded} superseded, "
                            f"last {s.months_since_last}mo ago"), flush=True)
        if args.out:
            with open(args.out, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(s), ensure_ascii=False) + "\n")
    print("\n" + json.dumps(aggregate(surveys), indent=2))
    return 0


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
    parser = argparse.ArgumentParser(prog="verdica", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="scaffold .decisions/ in a repository")
    p_init.add_argument("--root", default=".")
    p_init.set_defaults(func=cmd_init)

    p_check = sub.add_parser("check", help="check the current diff against recorded decisions")
    p_check.add_argument("--root", default=".")
    p_check.add_argument("--base", required=True, help="base ref, e.g. origin/main")
    p_check.add_argument("--fail-on", choices=["never", "block"], default="never")
    p_check.add_argument("--comment", action="store_true",
                         help="upsert the summary as a PR comment (needs GITHUB_TOKEN)")
    p_check.add_argument("--no-advisor", action="store_true",
                         help="skip out-of-scope suggestions")
    p_check.set_defaults(func=cmd_check)

    p_digest = sub.add_parser(
        "digest", help="what changed in the registry, and what stands")
    p_digest.add_argument("--root", default=".")
    p_digest.add_argument("--since", default="7 days ago")
    p_digest.set_defaults(func=cmd_digest)

    p_boot = sub.add_parser(
        "bootstrap",
        help="extract decision candidates from the repo itself (report-only by default)")
    p_boot.add_argument("--root", default=".")
    p_boot.add_argument("--top", type=int, default=12)
    p_boot.add_argument("--prs", type=int, default=50, help="merges to backtest")
    p_boot.add_argument("--write", action="store_true",
                        help="write proposals into .decisions/")
    p_boot.add_argument("--html", help="also write a reviewable HTML report here")
    p_boot.add_argument("--notes", help="external notes folder (meeting exports, postmortems)")
    p_boot.add_argument("--interactive", action="store_true",
                        help="force the onboarding questions on stdin")
    p_boot.add_argument("--answers", help="scripted answers, e.g. '1,2,1'")
    p_boot.add_argument("--pr", action="store_true",
                        help="write, branch, and open the bootstrap PR (needs gh)")
    p_boot.set_defaults(func=cmd_bootstrap)

    p_survey = sub.add_parser(
        "survey", help="survey public decision registries (anatomy, not citations)")
    p_survey.add_argument("repo", nargs="?", help="owner/name")
    p_survey.add_argument("--repos-file", help="file with one owner/name per line")
    p_survey.add_argument("--discover", help="'|'-separated code-search fingerprints")
    p_survey.add_argument("--cap", type=int, default=200)
    p_survey.add_argument("--out", help="append per-repo JSONL here")
    p_survey.set_defaults(func=cmd_survey)

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
