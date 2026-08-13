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
    r"|deciso|decidiamo|si è deciso|we decided|agreed to|from now on|d'ora in poi"
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
# in-repo folders that hold meeting notes (e.g. synced from Granola via
# Zapier -> "create file in repo"): their mentions are note-kind — full
# provenance, but they never contribute scope paths
MEETING_DIR_HINTS = ("meetings/", "meeting-notes/", "minutes/", "verbali/",
                     "retros/", "postmortems/")
CATEGORY_HINTS = (
    # hints are matched as substrings: keep them long enough not to hide
    # inside ordinary words ("ui" matches "build")
    ("design", ("theme", "design", "style", "color", "palette", "brand",
                "store/", "assets/", "font", "spacing")),
    ("product", ("pricing", "price", "fee", "paywall", "onboarding",
                 "plan limit", "freemium")),
    ("process", (".github/", "workflow", "release", "version", "deploy",
                 "contributing", "changelog")),
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

    @property
    def explicit(self) -> bool:
        """An explicit decision statement outranks a passing normative comment."""
        return any(re.match(r"(?i)\s*(deciso|decidiamo|regola|we decided|agreed|decision:)",
                            m.text) for m in self.mentions)

    def score(self) -> tuple:
        return (self.tier == "T2", self.explicit, len(self.mentions),
                -min(m.line for m in self.mentions))


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
        if re.match(r"-?\s*\[[ xX]\]", text):
            continue  # checklist items are work in progress, not standing rules
        is_doc = path.endswith(DOC_SUFFIXES)
        if not is_doc and not COMMENT_MARK.match(text):
            continue
        if len(text) < 18 or len(text) > 300:
            continue
        is_meeting = any(h in path.lower() for h in MEETING_DIR_HINTS)
        mentions.append(Mention(
            file=path, line=int(line),
            text=COMMENT_MARK.sub("", text).strip(),
            kind="note" if is_meeting else ("doc" if is_doc else "comment"),
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
    # pass 2 (single round): merge pairs sharing a token that appears in
    # exactly two of the proximity clusters. Computed once on the original
    # index and size-capped — iterated rare-token merging chains
    # transitively and snowballs into a mega-cluster.
    def toks(c: Cluster) -> set[str]:
        out: set[str] = set()
        for m in c.mentions:
            out |= m.tokens()
        return out

    token_owners: dict[str, list[int]] = defaultdict(list)
    for idx, c in enumerate(clusters):
        for t in toks(c):
            token_owners[t].append(idx)

    parent = list(range(len(clusters)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    size = [len(c.mentions) for c in clusters]
    for owners in token_owners.values():
        if len(owners) != 2:
            continue
        a, b = find(owners[0]), find(owners[1])
        if a != b and size[a] + size[b] <= 10:
            parent[b] = a
            size[a] += size[b]

    grouped: dict[int, list[Mention]] = defaultdict(list)
    for idx, c in enumerate(clusters):
        grouped[find(idx)].extend(c.mentions)
    return [Cluster(ms) for ms in grouped.values()]


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
    repo_files = sorted({m.file for m in cluster.mentions
                         if m.file and m.kind != "note"
                         and not m.file.startswith("notes:")})
    scope = sorted({str(Path(f).parent) + "/**" if "/" in f else f
                    for f in repo_files})[:4] or ["**"]
    from . import llm

    all_text = " ".join(m.text for m in evidence)
    if llm.available():
        draft = _distill_llm(cluster, evidence, scope)
        if draft is None:  # judged not a real rule (or refused)
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
    from . import llm

    ev_lines = "\n".join(
        f"- {m.kind} {m.file}:{m.line} {m.ref}: {m.text}" for m in evidence)
    data = llm.complete_json(
        "These artifacts from one repository appear to state a team rule. "
        "Distill THE rule they share into a decision record: a one-sentence "
        "normative title (state the rule, not the topic — keep the original "
        "language of the evidence), a rationale drawn only from the evidence, "
        "and scope paths (globs) derived from where the evidence lives. "
        "Evidence lines prefixed `notes:` come from meeting notes and must "
        "not contribute scope paths — when ALL evidence is notes, scope_paths "
        "must be exactly [\"**\"]; never invent paths that no evidence "
        "touches. Severity defaults to warn; use block only when violating "
        "the rule is irreversible or security/pricing-critical. If the "
        "artifacts do not state a real standing rule (TODOs, status updates, "
        "descriptions of code mechanics with no normative force), set "
        "is_real_rule=false.\n\n"
        "Evidence:\n" + ev_lines
        + f"\n\nDefault scope from evidence paths: {scope}",
        DISTILL_SCHEMA,
    )
    if data is None or not data.get("is_real_rule"):
        return None
    return data


# ---- source adapters -------------------------------------------------------

NORMATIVE_RE = re.compile(NORMATIVE, re.IGNORECASE)


def scan_notes(notes_dir: Path, cap: int = 200) -> list[Mention]:
    """External notes folder (meeting exports, Granola dumps, postmortems).

    Note mentions carry a `notes:` file prefix so they contribute evidence and
    provenance but never scope paths — a note lives outside the repo tree.
    """
    mentions: list[Mention] = []
    for f in sorted(list(notes_dir.rglob("*.md")) + list(notes_dir.rglob("*.txt"))):
        try:
            lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            text = line.strip().lstrip("-*# ").strip()
            if NORMATIVE_RE.search(text) and 18 <= len(text) <= 300:
                mentions.append(Mention(file=f"notes:{f.name}", line=i,
                                        text=text, kind="note"))
                if len(mentions) >= cap:
                    return mentions
    return mentions


# ---- onboarding questions --------------------------------------------------

@dataclass
class Question:
    kind: str  # confirm_block | scope_fork
    draft: Draft
    prompt: str
    options: list[str]  # option 1 is the default

    def apply(self, choice: int) -> None:
        picked = self.options[choice - 1] if 1 <= choice <= len(self.options) else self.options[0]
        if self.kind == "confirm_block":
            self.draft.severity = "block" if picked == "block" else "warn"
        elif self.kind == "scope_fork":
            self.draft.scope = [picked] if picked != "keep all" else self.draft.scope


def collect_questions(drafts: list[Draft], cap: int = 5) -> list[Question]:
    """Only genuinely undecidable calls become questions; everything else defaults."""
    questions: list[Question] = []
    for d in drafts:
        if d.demoted:
            continue
        if d.receipts:
            questions.append(Question(
                kind="confirm_block", draft=d,
                prompt=(f"{d.id} already cost a revert ({d.receipts[0][:60]}). "
                        f"Enforce as blocking?"),
                options=["block", "warn"],
            ))
        elif len(d.scope) > 1:
            tops = sorted({p.split("/", 1)[0] for p in d.scope})
            if len(tops) > 1:
                questions.append(Question(
                    kind="scope_fork", draft=d,
                    prompt=f"{d.id} spans {', '.join(tops)} — which scope applies?",
                    options=["keep all", *d.scope],
                ))
    return questions[:cap]


def ask(questions: list[Question], answers: list[int] | None,
        interactive: bool) -> list[str]:
    """Apply defaults, scripted answers, or prompt on stdin. Returns a log."""
    log = []
    for i, q in enumerate(questions):
        choice = 1
        if answers and i < len(answers):
            choice = answers[i]
        elif interactive:
            opts = "  ".join(f"[{n}] {o}" for n, o in enumerate(q.options, 1))
            print(f"\nQ{i + 1}. {q.prompt}\n     {opts}")
            try:
                choice = int(input("     > ").strip() or "1")
            except (ValueError, EOFError):
                choice = 1
        q.apply(choice)
        picked = q.options[choice - 1] if 1 <= choice <= len(q.options) else q.options[0]
        log.append(f"Q{i + 1} {q.draft.id} [{q.kind}] -> {picked}")
    return log


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
        has_repo_evidence = any(
            m.file and not m.file.startswith("notes:") for m in d.evidence)
        if not has_repo_evidence:
            # no path scope derivable (e.g. meeting-note decisions): the
            # enforcement surface is the digest, not the diff gate — the
            # backtest's noise metric does not apply
            d.noise = 0.0
            continue
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
                  write: bool = False, notes: Path | None = None,
                  answers: list[int] | None = None,
                  interactive: bool = False, html_out: Path | None = None) -> str:
    mentions = scan_normative(root) + scan_reverts(root)
    if notes and notes.is_dir():
        mentions += scan_notes(notes)
    enforcement = inventory_enforcement(root)
    clusters = sorted(cluster_mentions(mentions),
                      key=lambda c: c.score(), reverse=True)
    start = next_id(root)
    drafts: list[Draft] = []
    distill_errors = 0
    from . import llm
    for i, c in enumerate(clusters[:top * 3]):
        llm.last_error = None
        d = distill(c, start + i)
        if d:
            drafts.append(d)
        elif llm.last_error:
            distill_errors += 1
        if llm.available():
            import time as _time
            _time.sleep(0.4)  # pace provider calls
    merges = recent_merges(root, prs)
    backtest(drafts, merges)
    kept = [d for d in drafts if not d.demoted][:top]
    parked = [d for d in drafts if d.demoted] + [d for d in drafts if not d.demoted][top:]
    qa_log = ask(collect_questions(kept), answers, interactive)

    lines = [
        f"# decisis bootstrap — {root.name}",
        f"mentions: {len(mentions)}  clusters: {len(clusters)}  "
        f"merges backtested: {len(merges)}",
        f"proposed: {len(kept)}  parked: {len(parked)}  "
        f"already machine-enforced (T1, linked not extracted): {len(enforcement)}"
        + (f"  distillation errors: {distill_errors}" if distill_errors else ""),
        "",
    ]
    for d in kept:
        receipt = f"  [receipt: {len(d.receipts)} reverted merge]" if d.receipts else ""
        lines.append(f"{d.id} [{d.tier}/{d.category}/{d.severity}] "
                     f"noise {d.noise:.0%}{receipt}")
        lines.append(f"  {d.title}")
        lines.append(f"  scope: {', '.join(d.scope)}")
    if qa_log:
        lines += ["", "Onboarding answers (defaults where unanswered):", *[f"  {q}" for q in qa_log]]
    if enforcement:
        lines += ["", "T1 (already enforced, skipped): " + ", ".join(enforcement[:8])]

    if html_out:
        from .report import render_report

        html_out.write_text(render_report(
            root.resolve().name, kept, parked, len(mentions), len(merges),
            enforcement), encoding="utf-8")
        lines.append(f"\nwrote {html_out}")

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
