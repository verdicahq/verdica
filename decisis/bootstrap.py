"""Bootstrap: extract decision candidates from what the repo already contains.

Funnel (cost scales with repo activity, not size):
  S0 inventory   — deterministic sweep: normative comments/docs, reverts,
                   enforcement configs (T1, reported but never extracted)
  S1 clustering  — group mentions about the same thing (proximity + shared
                   distinctive tokens)
  S2 distill     — the only LLM pass, per surviving cluster, evidence-anchored;
                   without a key a heuristic draft is produced instead
  S3 backtest    — replay proposed scopes over the last N merges: demote noisy
                   candidates, attach receipts (merges later reverted)
  S4 assemble    — top-K proposals as .decisions/ files (status: proposed),
                   the tail in _candidates.md, a report with the numbers

Tiers (authority comes from how the team treated the rule, not the file type):
  T1 machine-enforced (lint/CI/CODEOWNERS)  -> linked in report, never extracted
  T2 human-enforced   (reverts, repeated review objections) -> top rank
  T3 declared, untested (normative comments, convention docs) -> mid rank
  T4 implicit patterns -> never in the bootstrap PR (not implemented in v0)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

NORMATIVE = (
    r"must not|must be|must never|never |always |do not |don'?t |should not"
    r"|shouldn'?t |keep in sync|only .{3,40} (ships|deploys|releases)"
    r"|non (si |va |deve |devono )| mai | sempre |vietato|obbligatori|altrimenti"
)
COMMENT_MARK = re.compile(r"^\s*(#|//|/?\*|<!--|;|--|%)\s?")
DOC_SUFFIXES = (".md", ".rst", ".txt", ".adoc")
ENFORCEMENT_HINTS = (
    ".github/workflows/", "CODEOWNERS", ".eslintrc", "analysis_options.yaml",
    ".golangci", "ruff.toml", ".pre-commit-config.yaml", "sonar-project.properties",
    ".editorconfig", "renovate.json", "dependabot.yml",
)
SKIP_DIRS = ("vendor/", "node_modules/", "third_party/", "dist/", "build/",
             ".venv/", "generated/")
CATEGORY_HINTS = (
    ("design", ("theme", "design", "ui", "ux", "style", "color", "brand",
                "store/", "assets/")),
    ("product", ("pricing", "price", "fee", "plan", "paywall", "onboarding",
                 "copy", "config")),
    ("process", (".github/", "ci/", "workflow", "release", "version",
                 "contributing", "deploy")),
)
STOP_TOKENS = {
    "should", "always", "never", "must", "avoid", "please", "before", "after",
    "because", "cannot", "instead", "without", "sempre", "altrimenti", "github",
    "workflows", "license", "return", "string", "import", "public", "private",
}
TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{5,}|#[0-9a-fA-F]{6}\b")


@dataclass
class Mention:
    file: str
    line: int
    text: str
    kind: str  # comment | doc | revert
    ref: str = ""  # commit sha for reverts

    def tokens(self) -> set[str]:
        return {t.lower() for t in TOKEN_RE.findall(self.text)} - STOP_TOKENS


@dataclass
class Cluster:
    mentions: list[Mention] = field(default_factory=list)

    @property
    def tier(self) -> str:
        return "T2" if any(m.kind == "revert" for m in self.mentions) else "T3"

    @property
    def files(self) -> list[str]:
        return sorted({m.file for m in self.mentions if m.file})

    def score(self) -> tuple:
        return (self.tier == "T2", len(self.mentions), -min(m.line for m in self.mentions))


def guess_category(files: list[str], text: str) -> str:
    """Path- and text-based default; the LLM pass can override it."""
    haystack = " ".join(files).lower() + " " + text.lower()
    for category, hints in CATEGORY_HINTS:
        if any(h in haystack for h in hints):
            return category
    return "engineering"


@dataclass
class Draft:
    id: str
    title: str
    tier: str
    severity: str
    scope: list[str]
    evidence: list[Mention]
    category: str = "engineering"
    rationale: str = ""
    confidence: str = "low"
    noise: float = 0.0
    receipts: list[str] = field(default_factory=list)
    demoted: bool = False


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, check=False,
    ).stdout


# ---- S0: inventory ---------------------------------------------------------

def scan_normative(root: Path, cap: int = 400) -> list[Mention]:
    """Normative lines in tracked files, restricted to comments and docs."""
    out = _git(root, "grep", "-nIiE", NORMATIVE, "HEAD")
    mentions: list[Mention] = []
    for raw in out.splitlines():
        try:
            _, path, line, text = raw.split(":", 3)
        except ValueError:
            continue
        text = text.strip()
        if any(s in path for s in SKIP_DIRS):
            continue  # vendored/generated code states the library's rules, not the team's
        is_doc = path.endswith(DOC_SUFFIXES)
        if not is_doc and not COMMENT_MARK.match(text):
            continue
        if len(text) < 18 or len(text) > 300:
            continue
        mentions.append(Mention(
            file=path, line=int(line),
            text=COMMENT_MARK.sub("", text).strip(),
            kind="doc" if is_doc else "comment",
        ))
        if len(mentions) >= cap:
            break
    return mentions


def scan_reverts(root: Path, limit: int = 400) -> list[Mention]:
    log = _git(root, "log", f"-n{limit}", "--format=%H%x01%s")
    mentions = []
    for row in log.splitlines():
        sha, _, subject = row.partition("\x01")
        if re.match(r"(?i)^revert\b", subject):
            mentions.append(Mention(file="", line=0, text=subject, kind="revert", ref=sha))
    return mentions


def inventory_enforcement(root: Path) -> list[str]:
    tracked = _git(root, "ls-files").splitlines()
    return sorted({p for p in tracked if any(h in p for h in ENFORCEMENT_HINTS)})[:30]


# ---- S1: clustering --------------------------------------------------------

def cluster_mentions(mentions: list[Mention]) -> list[Cluster]:
    # pass 1: same file, nearby lines (mentions without a file — reverts —
    # become singleton clusters below)
    by_file: dict[str, list[Mention]] = defaultdict(list)
    for m in mentions:
        if m.file:
            by_file[m.file].append(m)
    clusters: list[Cluster] = []
    for file, ms in by_file.items():
        ms.sort(key=lambda m: m.line)
        current = Cluster([ms[0]])
        for m in ms[1:]:
            if m.line - current.mentions[-1].line <= 10:
                current.mentions.append(m)
            else:
                clusters.append(current)
                current = Cluster([m])
        clusters.append(current)
    for m in mentions:
        if not m.file:  # reverts: one cluster each
            clusters.append(Cluster([m]))
    # pass 2: merge clusters sharing a distinctive token
    merged = True
    while merged:
        merged = False
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                ti = set().union(*(m.tokens() for m in clusters[i].mentions))
                tj = set().union(*(m.tokens() for m in clusters[j].mentions))
                if ti & tj:
                    clusters[i].mentions.extend(clusters[j].mentions)
                    del clusters[j]
                    merged = True
                    break
            if merged:
                break
    return clusters


# ---- S2: distillation ------------------------------------------------------

DISTILL_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "rationale": {"type": "string"},
        "scope_paths": {"type": "array", "items": {"type": "string"}},
        "severity": {"type": "string", "enum": ["warn", "block"]},
        "category": {"type": "string",
                     "enum": ["strategy", "product", "design", "engineering", "process"]},
        "is_real_rule": {"type": "boolean"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["title", "rationale", "scope_paths", "severity", "category",
                 "is_real_rule", "confidence"],
    "additionalProperties": False,
}


def distill(cluster: Cluster, index: int) -> Draft | None:
    evidence = cluster.mentions[:8]
    scope = sorted({str(Path(f).parent) + "/**" if "/" in f else f
                    for f in cluster.files})[:4] or ["**"]
    all_text = " ".join(m.text for m in evidence)
    if os.environ.get("ANTHROPIC_API_KEY"):
        draft = _distill_llm(cluster, evidence, scope)
        if draft is None:
            return None
    else:
        strongest = max(evidence, key=lambda m: len(m.text))
        draft = {
            "title": strongest.text[:110],
            "rationale": "Heuristic draft - refine wording during review.",
            "scope_paths": scope,
            "severity": "warn",
            "category": guess_category(cluster.files, all_text),
            "confidence": "low",
        }
    return Draft(
        id=f"DEC-{index:04d}",
        title=draft["title"],
        tier=cluster.tier,
        severity="block" if cluster.tier == "T2" else draft["severity"],
        scope=draft["scope_paths"] or scope,
        evidence=evidence,
        category=draft.get("category") or guess_category(cluster.files, all_text),
        rationale=draft["rationale"],
        confidence=draft["confidence"],
    )


def _distill_llm(cluster: Cluster, evidence: list[Mention], scope: list[str]) -> dict | None:
    import anthropic

    client = anthropic.Anthropic()
    ev_lines = "\n".join(
        f"- {m.kind} {m.file}:{m.line} {m.ref}: {m.text}" for m in evidence)
    response = client.messages.create(
        model=os.environ.get("DECISIS_MODEL", "claude-opus-5"),
        max_tokens=2048,
        output_config={"format": {"type": "json_schema", "schema": DISTILL_SCHEMA}},
        messages=[{"role": "user", "content": (
            "These artifacts from one repository appear to state a team rule. "
            "Distill THE rule they share into a decision record: a one-sentence "
            "normative title (state the rule, not the topic), a rationale drawn "
            "only from the evidence, and scope paths (globs) derived from where "
            "the evidence lives. If they do not state a real rule, set "
            "is_real_rule=false.\n\nEvidence:\n" + ev_lines
            + f"\n\nDefault scope from evidence paths: {scope}"
        )}],
    )
    if response.stop_reason == "refusal":
        return None
    data = json.loads(next(b.text for b in response.content if b.type == "text"))
    return None if not data["is_real_rule"] else data


# ---- S3: backtest ----------------------------------------------------------

@dataclass
class Merge:
    sha: str
    subject: str
    files: list[str]
    reverted: bool = False


def recent_merges(root: Path, n: int = 50) -> list[Merge]:
    log = _git(root, "log", "--merges", f"-n{n}", "--format=%H%x01%s")
    reverts = _git(root, "log", f"-n{n * 8}", "--grep=This reverts commit",
                   "--format=%b")
    reverted_shas = set(re.findall(r"This reverts commit ([0-9a-f]{7,40})", reverts))
    revert_subjects = {
        m.group(1) for m in re.finditer(
            r'(?i)^revert "?(.{5,80}?)"?$',
            _git(root, "log", f"-n{n * 8}", "--format=%s"), re.MULTILINE)
    }
    merges = []
    for row in log.splitlines():
        sha, _, subject = row.partition("\x01")
        files = [f for f in _git(root, "diff", "--name-only",
                                 f"{sha}^1", sha).splitlines() if f]
        reverted = any(sha.startswith(r) or r.startswith(sha[:7])
                       for r in reverted_shas)
        reverted = reverted or any(s and s in subject for s in revert_subjects)
        merges.append(Merge(sha=sha[:10], subject=subject, files=files,
                            reverted=reverted))
    return merges


def backtest(drafts: list[Draft], merges: list[Merge],
             noise_threshold: float = 0.35) -> None:
    from .formats import path_matches

    for d in drafts:
        hits = [m for m in merges
                if any(path_matches(p, f) for p in d.scope for f in m.files)]
        d.noise = len(hits) / len(merges) if merges else 0.0
        d.receipts = [f"{m.sha} {m.subject}" for m in hits if m.reverted]
        if d.noise > noise_threshold:
            # a scope that flags most merges is noise — a receipt caught by an
            # over-broad net is not evidence, so noise wins over promotion
            d.demoted = True
        elif d.receipts:
            d.severity = "block"
            d.tier = "T2"


# ---- S4: assembly ----------------------------------------------------------

def next_id(root: Path) -> int:
    existing = re.findall(r"id:\s*[A-Z]+-(\d+)",
                          "\n".join(p.read_text(encoding="utf-8")
                                    for p in (root / ".decisions").glob("*.md"))
                          if (root / ".decisions").is_dir() else "")
    return max((int(x) for x in existing), default=0) + 1


def render_decision(d: Draft) -> str:
    paths = "\n".join(f'    - "{p}"' for p in d.scope)
    ev = "\n".join(
        f"- `{m.file}:{m.line}` — {m.text}" if m.file else f"- revert `{m.ref[:10]}` — {m.text}"
        for m in d.evidence)
    receipts = "".join(f"\n- would have flagged merge `{r}` (later reverted)"
                       for r in d.receipts)
    return (
        f"---\nid: {d.id}\ntitle: {d.title}\nstatus: proposed\n"
        f"category: {d.category}\nseverity: {d.severity}\n"
        f"scope:\n  paths:\n{paths}\ndeciders: []\n---\n\n"
        f"## Decision\n{d.title}\n\n## Rationale\n{d.rationale}\n\n"
        f"## Provenance\nTier {d.tier}, confidence {d.confidence}, "
        f"backtest noise {d.noise:.0%}.{receipts}\n\nEvidence:\n{ev}\n"
    )


def run_bootstrap(root: Path, top: int = 12, prs: int = 50,
                  write: bool = False) -> str:
    mentions = scan_normative(root) + scan_reverts(root)
    enforcement = inventory_enforcement(root)
    clusters = sorted(cluster_mentions(mentions),
                      key=lambda c: c.score(), reverse=True)
    start = next_id(root)
    drafts = [d for i, c in enumerate(clusters[:top * 3])
              if (d := distill(c, start + i))]
    merges = recent_merges(root, prs)
    backtest(drafts, merges)
    kept = [d for d in drafts if not d.demoted][:top]
    parked = [d for d in drafts if d.demoted] + [d for d in drafts if not d.demoted][top:]

    lines = [
        f"# decisis bootstrap — {root.name}",
        f"mentions: {len(mentions)}  clusters: {len(clusters)}  "
        f"merges backtested: {len(merges)}",
        f"proposed: {len(kept)}  parked: {len(parked)}  "
        f"already machine-enforced (T1, linked not extracted): {len(enforcement)}",
        "",
    ]
    for d in kept:
        receipt = f"  [receipt: {len(d.receipts)} reverted merge]" if d.receipts else ""
        lines.append(f"{d.id} [{d.tier}/{d.category}/{d.severity}] "
                     f"noise {d.noise:.0%}{receipt}")
        lines.append(f"  {d.title}")
        lines.append(f"  scope: {', '.join(d.scope)}")
    if enforcement:
        lines += ["", "T1 (already enforced, skipped): " + ", ".join(enforcement[:8])]

    if write:
        ddir = root / ".decisions"
        ddir.mkdir(exist_ok=True)
        for d in kept:
            slug = re.sub(r"[^a-z0-9]+", "-", d.title.lower())[:40].strip("-")
            (ddir / f"{d.id}-{slug}.md").write_text(render_decision(d),
                                                    encoding="utf-8")
        if parked:
            (ddir / "_candidates.md").write_text(
                "# Parked candidates (demoted by backtest or below top-K)\n\n"
                + "\n".join(f"- [{d.tier}] {d.title} (noise {d.noise:.0%})"
                            for d in parked),
                encoding="utf-8")
        lines.append(f"\nwrote {len(kept)} proposals to {ddir}")
    return "\n".join(lines)
