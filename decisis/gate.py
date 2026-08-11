"""The gate: does this diff contradict a recorded decision?

Deterministic layer first (path scope match), LLM judge only on scope hits
and only when an Anthropic API key is available. Without a key the gate
still produces the awareness summary — "this change touches the scope of
DEC-NNNN" — which is useful on its own and costs nothing.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .formats import Decision, load_decisions, scope_hits

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "contradicts": {"type": "boolean"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "evidence": {"type": "string"},
    },
    "required": ["contradicts", "confidence", "evidence"],
    "additionalProperties": False,
}

MAX_DIFF_CHARS = 60_000


@dataclass
class Finding:
    decision: Decision
    touched: list[str]
    contradicts: bool | None  # None = judge not run
    confidence: str | None
    evidence: str | None


def changed_files(base: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def diff_for(base: str, paths: list[str]) -> str:
    out = subprocess.run(
        ["git", "diff", f"{base}...HEAD", "--", *paths],
        check=True, capture_output=True, text=True,
    ).stdout
    if len(out) > MAX_DIFF_CHARS:
        out = out[:MAX_DIFF_CHARS] + "\n[diff truncated]"
    return out


def judge(decision: Decision, diff: str) -> dict | None:
    """Ask the configured model whether the diff contradicts the decision.

    None when no provider is configured (DEC-0008) — the gate then reports
    scope awareness only.
    """
    from . import llm

    if not llm.available():
        return None
    prompt = (
        "A team recorded this decision:\n\n"
        f"# {decision.id}: {decision.title}\n{decision.body.strip()}\n\n"
        "Below is a diff that touches files inside the decision's scope. "
        "Judge whether the diff CONTRADICTS the decision — i.e. does what the "
        "decision ruled out, or undoes what it mandates. Touching the scope "
        "without contradicting the decision is not a violation. Cite the "
        "specific hunk in `evidence` if it contradicts; keep evidence short.\n\n"
        f"```diff\n{diff}\n```"
    )
    return llm.complete_json(prompt, VERDICT_SCHEMA)


def run_gate(root: Path, base: str) -> list[Finding]:
    decisions = load_decisions(root)
    changed = changed_files(base)
    hits = scope_hits(decisions, changed)
    by_id = {d.id: d for d in decisions}
    findings: list[Finding] = []
    for dec_id, touched in hits.items():
        decision = by_id[dec_id]
        verdict = judge(decision, diff_for(base, touched))
        findings.append(Finding(
            decision=decision,
            touched=touched,
            contradicts=None if verdict is None else bool(verdict["contradicts"]),
            confidence=None if verdict is None else verdict["confidence"],
            evidence=None if verdict is None else verdict["evidence"],
        ))
    return findings


def render_summary(findings: list[Finding]) -> str:
    if not findings:
        return "No recorded decision governs the changed files.\n"
    lines = ["## Decisions governing this change\n"]
    for f in findings:
        d = f.decision
        head = f"### {d.id} — {d.title}"
        lines.append(head)
        lines.append(f"Touched in scope: {', '.join(f.touched)}")
        if f.contradicts is None:
            lines.append("Verdict: not evaluated (no API key) — review against the decision above.")
        elif f.contradicts:
            lines.append(f"**Verdict: contradicts** (confidence: {f.confidence})")
            lines.append(f"Evidence: {f.evidence}")
        else:
            lines.append(f"Verdict: consistent (confidence: {f.confidence})")
        lines.append("")
    return "\n".join(lines)


def render_digest(root: Path, since: str) -> str:
    """Weekly digest: decisions ratified/proposed since `since`, plus the
    standing registry grouped by category. The non-gating half of the product —
    what a team reads on Monday, and the only surface where strategy-category
    decisions (never diff-checkable) actually show up."""
    from .formats import load_decisions

    decisions = load_decisions(root)
    if not decisions:
        return "No decisions recorded yet. Run `decisis bootstrap`.\n"
    changed = subprocess.run(
        ["git", "-C", str(root), "log", f"--since={since}", "--name-status",
         "--diff-filter=AM", "--format=", "--", ".decisions"],
        capture_output=True, text=True, check=False,
    ).stdout
    touched = {line.split("\t")[-1] for line in changed.splitlines() if "\t" in line}
    # d.file is whatever path load_decisions saw; git reports repo-relative
    by_relpath = {str(Path(d.file).relative_to(root)) if Path(d.file).is_absolute()
                  else str(Path(d.file)): d for d in decisions}
    recent = [by_relpath[p] for p in sorted(touched) if p in by_relpath]

    lines = [f"# Decision digest — last {since}\n"]
    if recent:
        lines.append("## New or updated\n")
        for d in recent:
            lines.append(f"- **{d.id}** [{d.category}/{d.status}] {d.title}")
        lines.append("")
    else:
        lines.append("_No decisions added or changed in this period._\n")
    lines.append("## Standing registry\n")
    for category in ("strategy", "product", "design", "engineering", "process"):
        group = [d for d in decisions if d.category == category and d.active]
        if not group:
            continue
        lines.append(f"### {category} ({len(group)})")
        for d in group:
            gate = "gates" if d.paths and d.paths != ["**"] else "digest-only"
            lines.append(f"- {d.id} [{d.severity}/{gate}] {d.title}")
        lines.append("")
    proposed = [d for d in decisions if d.status == "proposed"]
    if proposed:
        lines.append(f"## Awaiting ratification ({len(proposed)})\n")
        lines += [f"- {d.id} {d.title}" for d in proposed]
    return "\n".join(lines) + "\n"


def should_fail(findings: list[Finding], fail_on: str) -> bool:
    """fail_on: 'never' | 'block' (block-severity, high-confidence contradictions)."""
    if fail_on == "never":
        return False
    return any(
        f.contradicts and f.confidence == "high" and f.decision.severity == "block"
        for f in findings
    )
