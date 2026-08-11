"""Parse .decisions/ files (SPEC.md v0.1)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
# Existing registries: 82 of the 166 public registries surveyed live in
# docs/adr, 33 in doc/adr. Reading them where they are is the difference
# between "adopt this tool" and "migrate your registry first".
LEGACY_DIRS = ("docs/adr", "doc/adr", "docs/decisions", "docs/architecture/decisions",
               "adr", "docs/adrs", "decisions", "docs/arch/adr", "architecture/decisions")
LEGACY_STATUS_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:#{1,4}\s*)?(?:\*\*)?status(?:\*\*)?\s*[:|]?\s*(?:\*\*)?\s*"
    r"\n?\s*(proposed|accepted|superseded|deprecated|rejected|draft|obsolete|"
    r"approved|implemented|done)", re.IGNORECASE | re.MULTILINE)
LEGACY_TITLE_RE = re.compile(r"^#\s+(?:\d+[.)]?\s*)?(.+)$", re.MULTILINE)
STATUS_ALIASES = {"approved": "accepted", "implemented": "accepted", "done": "accepted",
                  "obsolete": "superseded", "draft": "proposed"}


@dataclass
class Decision:
    id: str
    title: str
    status: str  # proposed | accepted | superseded
    paths: list[str]
    severity: str = "warn"  # warn | block
    category: str = "engineering"  # strategy | product | design | engineering | process
    deciders: list[str] = field(default_factory=list)
    superseded_by: str | None = None
    body: str = ""
    file: str = ""
    legacy: bool = False  # read from an existing ADR registry, not .decisions/

    @property
    def active(self) -> bool:
        return self.status == "accepted"


def parse_legacy(path: Path, text: str) -> Decision:
    """An ADR in the shape teams already write (Nygard / MADR, no frontmatter).

    It carries no scope, so it is digest-only until someone adds one — the
    decision is visible and citable from day one, enforceable when the team
    decides which paths it governs."""
    title = LEGACY_TITLE_RE.search(text)
    status = LEGACY_STATUS_RE.search(text)
    raw = (status.group(1).lower() if status else "accepted")
    return Decision(
        id=path.stem.split("-")[0].lstrip("0") and f"ADR-{path.stem.split('-')[0]}"
           or path.stem,
        title=(title.group(1).strip() if title else path.stem)[:200],
        status=STATUS_ALIASES.get(raw, raw),
        paths=[],  # digest-only until scoped
        body=text,
        file=str(path),
        legacy=True,
    )


def parse_decision(path: Path) -> Decision:
    text = path.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(text)
    if not m:
        if path.parent.name != ".decisions":
            return parse_legacy(path, text)
        raise ValueError(f"{path}: missing YAML frontmatter")
    meta = yaml.safe_load(m.group(1)) or {}
    for required in ("id", "title", "status"):
        if not meta.get(required):
            raise ValueError(f"{path}: missing required field '{required}'")
    scope = meta.get("scope") or {}
    return Decision(
        id=str(meta["id"]),
        title=str(meta["title"]),
        status=str(meta["status"]),
        paths=[str(p) for p in (scope.get("paths") or [])],
        severity=str(meta.get("severity") or "warn"),
        category=str(meta.get("category") or "engineering"),
        deciders=[str(d) for d in (meta.get("deciders") or [])],
        superseded_by=meta.get("superseded_by"),
        body=text[m.end():],
        file=str(path),
    )


def decisions_dir(root: Path) -> Path | None:
    """.decisions/ if present, else the repo's existing registry directory."""
    native = root / ".decisions"
    if native.is_dir():
        return native
    for d in LEGACY_DIRS:
        candidate = root / d
        if candidate.is_dir() and len(list(candidate.glob("*.md"))) >= 3:
            return candidate
    return None


def load_decisions(root: Path) -> list[Decision]:
    """Load every decision from the repo's registry, sorted by id."""
    ddir = decisions_dir(root)
    if ddir is None:
        return []
    decisions = [parse_decision(p) for p in sorted(ddir.glob("*.md"))
                 if p.name not in ("README.md", "index.md", "_candidates.md",
                                   "template.md", "0000-template.md")]
    ids = [d.id for d in decisions]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate decision ids: {', '.join(sorted(dupes))}")
    return decisions


def path_matches(pattern: str, path: str) -> bool:
    """Glob match with '**' meaning 'anything under this prefix'."""
    import fnmatch

    if pattern in ("**", "*"):
        return True
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        return path == prefix or path.startswith(prefix + "/")
    return fnmatch.fnmatch(path, pattern)


def scope_hits(decisions: list[Decision], changed: list[str]) -> dict[str, list[str]]:
    """Map decision id -> changed paths inside its scope (active decisions only)."""
    hits: dict[str, list[str]] = {}
    for d in decisions:
        if not d.active:
            continue
        touched = [p for p in changed if any(path_matches(pat, p) for pat in d.paths)]
        if touched:
            hits[d.id] = touched
    return hits
