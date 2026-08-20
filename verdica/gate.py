"""The gate: does this diff contradict a recorded decision?

Deterministic layer first (path scope match), LLM judge only on scope hits
and only when an Anthropic API key is available. Without a key the gate
still produces the awareness summary — "this change touches the scope of
DEC-NNNN" — which is useful on its own and costs nothing.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .formats import Decision, load_decisions, path_matches, scope_hits

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


def changed_files(base: str, root: Path | str = ".") -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-only", f"{base}...HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def diff_for(base: str, paths: list[str], root: Path | str = ".") -> str:
    out = subprocess.run(
        ["git", "-C", str(root), "diff", f"{base}...HEAD", "--", *paths],
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
        + (f"NOTE: this decision is a TEMPORARY TRADEOFF, valid while its "
           f"condition holds (revisit when: {decision.revisit_when}). A diff "
           f"that fulfils that condition calls for superseding the decision, "
           f"not for a violation verdict — if that is what you see, say so "
           f"in `evidence`.\n\n" if decision.nature == "tradeoff" else "")
        + "Below is a diff that touches files inside the decision's scope. "
        "Judge whether the diff CONTRADICTS the decision — i.e. does what the "
        "decision ruled out, or undoes what it mandates. Touching the scope "
        "without contradicting the decision is not a violation. Cite the "
        "specific hunk in `evidence` if it contradicts; keep evidence short.\n\n"
        f"```diff\n{diff}\n```"
    )
    return llm.complete_json(prompt, VERDICT_SCHEMA)


def run_gate(root: Path, base: str) -> list[Finding]:
    decisions = load_decisions(root)
    changed = changed_files(base, root)
    hits = scope_hits(decisions, changed)
    by_id = {d.id: d for d in decisions}
    findings: list[Finding] = []
    for dec_id, touched in hits.items():
        decision = by_id[dec_id]
        verdict = judge(decision, diff_for(base, touched, root))
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
        if d.nature == "tradeoff":
            lines.append(f"_Tradeoff — revisit when: "
                         f"{d.revisit_when or 'unstated'}. If that has "
                         f"happened, supersede it rather than code around it._")
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
        return "No decisions recorded yet. Run `verdica bootstrap`.\n"
    from .formats import decisions_dir

    ddir = decisions_dir(root)
    rel_ddir = str(ddir.relative_to(root)) if ddir else ".decisions"
    changed = subprocess.run(
        ["git", "-C", str(root), "log", f"--since={since}", "--name-status",
         "--diff-filter=AM", "--format=", "--", rel_ddir],
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
        lines.append("")
    tradeoffs = [d for d in decisions if d.active and d.nature == "tradeoff"]
    if tradeoffs:
        lines.append(f"## Tradeoffs due for review ({len(tradeoffs)})\n")
        lines += [f"- {d.id} — {d.title} (revisit when: "
                  f"{d.revisit_when or 'unstated'})" for d in tradeoffs]
        lines.append("")
    hygiene = registry_hygiene(root)
    if hygiene:
        lines.append("## Registry hygiene\n")
        lines += hygiene
    return "\n".join(lines) + "\n"


def registry_hygiene(root: Path) -> list[str]:
    """What the registry itself is hiding.

    Surveying 166 public registries: 93% never marked a single decision
    superseded, and half take no new decision for over a year while the code
    keeps changing. The failure is not writing decisions - it is that nobody
    goes back. These checks are the going back, and they are deterministic.
    """
    from .formats import load_decisions
    from .survey import conflict_candidates

    decisions = [d for d in load_decisions(root) if d.active]
    if not decisions:
        return []
    lines: list[str] = []

    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files"],
        capture_output=True, text=True, check=False).stdout.splitlines()
    dead = [d for d in decisions
            if d.paths and not any(path_matches(p, f) for p in d.paths for f in tracked)]
    if dead:
        lines.append("### Decisions pointing at code that no longer exists\n")
        lines += [f"- **{d.id}** {d.title} — scope: {', '.join(d.paths)}" for d in dead]
        lines.append("")

    unscoped = [d for d in decisions if not d.paths]
    if unscoped:
        lines.append(f"### Not enforceable yet ({len(unscoped)})\n")
        lines.append("Add a `scope.paths` to gate these on pull requests:\n")
        lines += [f"- {d.id} {d.title}" for d in unscoped[:10]]
        if len(unscoped) > 10:
            lines.append(f"- …and {len(unscoped) - 10} more")
        lines.append("")

    pairs = conflict_candidates(
        [{"path": d.file, "title": d.title, "status": d.status, "date": None}
         for d in decisions])
    if pairs:
        lines.append("### Possibly superseded in practice\n")
        lines.append("Both active, but one appears to reverse the other — "
                     "supersede one, or say why both stand:\n")
        lines += [f"- **{a['title']}**  ⟷  **{b['title']}**" for a, b in pairs[:5]]
        lines.append("")
    return lines


def should_fail(findings: list[Finding], fail_on: str) -> bool:
    """fail_on: 'never' | 'block' (block-severity, high-confidence contradictions)."""
    if fail_on == "never":
        return False
    return any(
        f.contradicts and f.confidence == "high" and f.decision.severity == "block"
        for f in findings
    )


# ---- scope advisor (DEC-0006: propose widenings, never invent them) ---------

ADVISOR_STOP = {
    "decision", "decisions", "record", "records", "architecture", "should",
    "always", "never", "must", "using", "under", "which", "these", "those",
    "their", "there", "where", "while", "about", "other", "every", "without",
    "before", "after", "value", "values", "change", "changes", "default",
}


def _distinctive(decision: Decision) -> tuple[set[str], set[str]]:
    """A decision's subject, as things that cannot be said by accident.

    Only code-shaped tokens qualify: hex colours, snake_case and dotted
    identifiers. Ordinary words from a title ("registry", "configuration")
    appear all over a repository and produced three noisy suggestions per
    commit when they were included. Returns (strong, weak): a hex colour is
    strong enough alone, other identifiers need corroboration."""
    text = f"{decision.title} {decision.body[:1500]}"
    strong = {t.lower() for t in re.findall(r"#[0-9a-fA-F]{6}\b", text)}
    weak = {t.lower() for t in
            re.findall(r"\b[a-zA-Z]\w*_\w+\b|\b[a-zA-Z]\w*\.[a-z]{2,4}\b", text)}
    return strong, weak - ADVISOR_STOP


def advise_scope(root: Path, base: str, changed: list[str]) -> list[str]:
    """Changed files that sit outside every scope yet carry a decision's own
    vocabulary. Suggestions only: widening a ratified scope changes what the
    team promised to enforce, so it takes a ratified edit (DEC-0006)."""
    decisions = [d for d in load_decisions(root) if d.active and d.paths]
    if not decisions:
        return []
    suggestions: list[str] = []
    for d in decisions:
        outside = [f for f in changed if not any(path_matches(p, f) for p in d.paths)]
        if not outside:
            continue
        strong, weak = _distinctive(d)
        if not (strong or weak):
            continue
        hits = []
        for f in outside[:60]:
            blob = subprocess.run(
                ["git", "-C", str(root), "diff", f"{base}...HEAD", "--", f],
                capture_output=True, text=True, check=False).stdout.lower()
            hay = blob + " " + f.lower()
            # one unmistakable mark, or two ordinary identifiers together
            if any(m in hay for m in strong) or sum(m in hay for m in weak) >= 2:
                hits.append(f)
        if hits:
            suggestions.append(
                f"- **{d.id}** ({d.title}) — its subject appears in "
                f"{', '.join(hits[:4])}{' …' if len(hits) > 4 else ''}, outside its "
                f"scope ({', '.join(d.paths)}). Widen the scope in a PR if it should "
                f"govern these too.")
    return suggestions


# ---- PR comment (upsert, never spam) ---------------------------------------

MARKER = "<!-- verdica -->"


def post_pr_comment(body: str) -> str:
    """Upsert one comment on the PR this Action runs for.

    A gate that adds a comment per run trains reviewers to mute it, so the
    same comment is edited in place, identified by a hidden marker.
    """
    import json
    import urllib.error
    import urllib.request

    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not (token and repo and event_path and Path(event_path).exists()):
        return "no PR context"
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    number = (event.get("pull_request") or {}).get("number")
    if not number:
        return "not a pull_request event"

    api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    headers = {"Authorization": f"Bearer {token}",
               "Accept": "application/vnd.github+json",
               "User-Agent": "verdica"}

    def call(url: str, data: dict | None = None, method: str = "GET"):
        req = urllib.request.Request(
            url, headers={**headers, "Content-Type": "application/json"},
            data=json.dumps(data).encode() if data else None, method=method)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)

    payload = {"body": f"{MARKER}\n{body}"}
    try:
        existing = call(f"{api}/repos/{repo}/issues/{number}/comments?per_page=100")
        mine = next((c for c in existing if MARKER in (c.get("body") or "")), None)
        if mine:
            call(f"{api}/repos/{repo}/issues/comments/{mine['id']}", payload, "PATCH")
            return f"updated comment {mine['id']}"
        call(f"{api}/repos/{repo}/issues/{number}/comments", payload, "POST")
        return "posted comment"
    except urllib.error.HTTPError as e:
        return f"comment failed: http {e.code}"
    except OSError as e:
        return f"comment failed: {type(e).__name__}"


# ---- decision preview (what a proposed rule would have done) ----------------

def preview_decisions(root: Path, base: str, merges: int = 50) -> list[str]:
    """For each decision this branch adds or edits, replay it over the recent
    history: which already-merged changes it would have flagged.

    A rule is easy to agree with in the abstract and expensive in practice.
    Deploy previews work because they answer "what will this look like after
    the merge" before the merge; this answers the same question about a rule.
    """
    from .bootstrap import recent_merges
    from .formats import decisions_dir, parse_decision

    ddir = decisions_dir(root)
    if ddir is None:
        return []
    rel = str(ddir.relative_to(root)) if ddir.is_absolute() else str(ddir)
    touched = [f for f in changed_files(base, root) if f.startswith(rel + "/")
               and f.endswith(".md")]
    if not touched:
        return []

    history = recent_merges(root, merges)
    lines: list[str] = []
    for f in touched:
        path = root / f
        if not path.exists():
            continue
        try:
            d = parse_decision(path)
        except ValueError:
            continue
        if not d.paths:
            lines.append(f"- **{d.id}** {d.title} — no scope yet, so it will "
                         f"appear in the digest but gate nothing.")
            continue
        hits = [m for m in history
                if any(path_matches(p, cf) for p in d.paths for cf in m.files)]
        if not hits:
            lines.append(f"- **{d.id}** {d.title} — would have flagged **none** "
                         f"of the last {len(history)} merges.")
            continue
        reverted = [m for m in hits if m.reverted]
        detail = ", ".join(f"`{m.sha}` {m.subject[:60]}" for m in hits[:3])
        lines.append(
            f"- **{d.id}** {d.title} — would have flagged **{len(hits)} of the "
            f"last {len(history)} merges**"
            + (f", including {len(reverted)} later reverted" if reverted else "")
            + f": {detail}{' …' if len(hits) > 3 else ''}")
    return lines
