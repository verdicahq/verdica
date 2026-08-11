"""Survey public decision registries: how teams actually run them.

`mine` looks at how decisions are *cited* in pull requests. `survey` looks at
the registry itself — the anatomy of the decision files a team keeps — and
answers questions nobody has measured at scale:

  - how long a decision lives before it is superseded (decision half-life)
  - how many registries go dormant (no new decision while the repo keeps shipping)
  - how many decisions are diff-checkable at all (scope derivable from text)
  - whether teams record the alternatives they rejected
  - which format they use, and whether they follow it

Everything here is deterministic and cheap: file listing + raw fetch, no LLM.
The optional deep pass (category assignment, conflict candidates) is separate,
mirroring the product's own funnel (DEC-0003).
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

API = "https://api.github.com"

CANDIDATE_DIRS = (
    "docs/adr", "docs/decisions", "docs/architecture/decisions", "adr",
    "doc/adr", "docs/arch/adr", "architecture/decisions", "docs/adrs",
    "decisions", "docs/rfc", "rfcs", ".decisions",
)
STATUS_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:##+\s*)?(?:\*\*)?status(?:\*\*)?\s*[:\|]?\s*(?:\*\*)?"
    r"(proposed|accepted|superseded|deprecated|rejected|draft|obsolete|"
    r"implemented|approved|done)", re.IGNORECASE | re.MULTILINE)
DATE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:##+\s*)?(?:\*\*)?date(?:\*\*)?\s*[:\|]?\s*(?:\*\*)?\s*"
    r"(\d{4}-\d{2}-\d{2})", re.IGNORECASE | re.MULTILINE)
SUPERSEDED_BY_RE = re.compile(
    r"superseded\s*(?:by)?\s*[:\-]?\s*\[?(?:adr[- ]?)?(\d{1,4})", re.IGNORECASE)
ALTERNATIVES_RE = re.compile(
    r"(considered\s+options|alternatives?\s+considered|rejected\s+alternatives?|"
    r"other\s+options|options\s+considered|pros\s+and\s+cons)", re.IGNORECASE)
CONSEQUENCES_RE = re.compile(r"^#{1,4}\s*consequences", re.IGNORECASE | re.MULTILINE)
# a decision is diff-checkable when its text names something a path can match:
# a file, a directory, an extension, or a concrete code identifier
PATHISH_RE = re.compile(
    r"`[^`\n]*[/.][^`\n]*`|\b\w+/\w+|\.\w{2,4}\b|\b[a-z]+_[a-z_]+\b", re.IGNORECASE)
NUM_RE = re.compile(r"(\d{1,4})")


def _get(url: str, token: str, accept: str = "application/vnd.github+json"):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}", "Accept": accept,
        "User-Agent": "decisis-survey",
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read() if accept.startswith("application/vnd.github.raw") \
            else json.load(resp)


@dataclass
class DecisionFile:
    path: str
    number: int | None
    title: str
    status: str
    date: str | None
    superseded_by: int | None
    has_alternatives: bool
    has_consequences: bool
    scope_derivable: bool
    words: int


@dataclass
class RepoSurvey:
    repo: str
    dir: str = ""
    stars: int = 0
    pushed_at: str = ""
    n: int = 0
    statuses: dict = field(default_factory=dict)
    first_date: str | None = None
    last_date: str | None = None
    months_since_last: float | None = None
    dormant: bool | None = None  # no new decision in >12mo while the repo ships;
    # dormant is NOT unused: Home Assistant's registry went dormant in 2024 and
    # still caused a revert in 2026. It measures writing, not enforcement.
    superseded: int = 0
    median_days_to_supersede: float | None = None
    pct_with_alternatives: float = 0.0
    pct_with_consequences: float = 0.0
    pct_scope_derivable: float = 0.0
    median_words: int = 0
    decisions: list = field(default_factory=list)
    error: str = ""


def find_dir(repo: str, token: str) -> str:
    for d in CANDIDATE_DIRS:
        try:
            listing = _get(f"{API}/repos/{repo}/contents/{urllib.parse.quote(d)}", token)
        except (urllib.error.HTTPError, OSError):
            continue
        if isinstance(listing, list) and sum(
                1 for f in listing if f["name"].endswith((".md", ".markdown"))) >= 3:
            return d
    return ""


def parse_decision(path: str, text: str) -> DecisionFile:
    head = text[:4000]
    num_match = NUM_RE.search(os.path.basename(path))
    status_match = STATUS_RE.search(head)
    date_match = DATE_RE.search(head)
    sup = SUPERSEDED_BY_RE.search(head)
    title = ""
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
        if line.lower().startswith("title:"):
            title = line.split(":", 1)[1].strip()
            break
    return DecisionFile(
        path=path,
        number=int(num_match.group(1)) if num_match else None,
        title=title[:200],
        status=(status_match.group(1).lower() if status_match else "unstated"),
        date=date_match.group(1) if date_match else None,
        superseded_by=int(sup.group(1)) if sup else None,
        has_alternatives=bool(ALTERNATIVES_RE.search(text)),
        has_consequences=bool(CONSEQUENCES_RE.search(text)),
        scope_derivable=bool(PATHISH_RE.search(text)),
        words=len(text.split()),
    )


def survey_repo(repo: str, token: str, max_files: int = 120) -> RepoSurvey:
    out = RepoSurvey(repo=repo)
    try:
        meta = _get(f"{API}/repos/{repo}", token)
        out.stars, out.pushed_at = meta.get("stargazers_count", 0), meta.get("pushed_at", "")
        out.dir = find_dir(repo, token)
        if not out.dir:
            out.error = "no decision directory"
            return out
        listing = _get(f"{API}/repos/{repo}/contents/{urllib.parse.quote(out.dir)}", token)
        files = [f for f in listing if f["name"].endswith((".md", ".markdown"))][:max_files]
        parsed: list[DecisionFile] = []
        for f in files:
            try:
                raw = _get(f["url"], token, "application/vnd.github.raw+json")
            except (urllib.error.HTTPError, OSError):
                continue
            parsed.append(parse_decision(f["path"], raw.decode("utf-8", "ignore")))
            time.sleep(0.05)
    except urllib.error.HTTPError as e:
        out.error = f"http {e.code}"
        return out
    except (OSError, KeyError, ValueError) as e:  # OSError covers URLError + socket timeouts
        out.error = type(e).__name__
        return out

    out.n = len(parsed)
    if not parsed:
        out.error = out.error or "no decision files"
        return out
    out.decisions = [asdict(d) for d in parsed]
    counts: dict[str, int] = {}
    for d in parsed:
        counts[d.status] = counts.get(d.status, 0) + 1
    out.statuses = dict(sorted(counts.items()))
    out.superseded = counts.get("superseded", 0) + counts.get("obsolete", 0)
    out.pct_with_alternatives = round(
        sum(d.has_alternatives for d in parsed) / len(parsed), 3)
    out.pct_with_consequences = round(
        sum(d.has_consequences for d in parsed) / len(parsed), 3)
    out.pct_scope_derivable = round(
        sum(d.scope_derivable for d in parsed) / len(parsed), 3)
    out.median_words = sorted(d.words for d in parsed)[len(parsed) // 2]

    dated = sorted(d for d in (x.date for x in parsed) if d)
    if dated:
        out.first_date, out.last_date = dated[0], dated[-1]
        last = datetime.strptime(dated[-1], "%Y-%m-%d").date()
        out.months_since_last = round((date.today() - last).days / 30.44, 1)
        if out.pushed_at:
            repo_active = out.pushed_at[:10] > dated[-1]
            out.dormant = bool(out.months_since_last > 12 and repo_active)

    # decision half-life: days between a decision's date and its superseder's
    by_num = {d.number: d for d in parsed if d.number is not None}
    spans = []
    for d in parsed:
        target = by_num.get(d.superseded_by) if d.superseded_by else None
        if d.date and target and target.date:
            delta = (datetime.strptime(target.date, "%Y-%m-%d")
                     - datetime.strptime(d.date, "%Y-%m-%d")).days
            if delta > 0:
                spans.append(delta)
    if spans:
        spans.sort()
        out.median_days_to_supersede = float(spans[len(spans) // 2])
    return out


def discover(fingerprints: tuple[str, ...], token: str, cap: int) -> list[str]:
    """Repos whose file tree matches a decision-registry fingerprint."""
    found: list[str] = []
    seen: set[str] = set()
    for fp in fingerprints:
        for page in range(1, 11):
            if len(found) >= cap:
                return found
            q = urllib.parse.quote(fp)
            try:
                data = _get(f"{API}/search/code?q={q}&per_page=100&page={page}", token)
            except urllib.error.HTTPError as e:
                if e.code in (403, 422):  # rate limit or page cap
                    time.sleep(20)
                    break
                raise
            items = data.get("items", [])
            if not items:
                break
            for it in items:
                name = it["repository"]["full_name"]
                if name not in seen:
                    seen.add(name)
                    found.append(name)
            time.sleep(6.5)  # code search: ~10 req/min
    return found[:cap]


def aggregate(surveys: list[RepoSurvey]) -> dict:
    ok = [s for s in surveys if s.n]
    if not ok:
        return {"repos_surveyed": len(surveys), "with_registry": 0}

    def med(values):
        v = sorted(values)
        return v[len(v) // 2] if v else None

    dated = [s for s in ok if s.months_since_last is not None]
    judged = [s for s in ok if s.dormant is not None]
    spans = [s.median_days_to_supersede for s in ok if s.median_days_to_supersede]
    all_statuses: dict[str, int] = {}
    for s in ok:
        for k, v in s.statuses.items():
            all_statuses[k] = all_statuses.get(k, 0) + v
    total = sum(all_statuses.values())
    return {
        "repos_surveyed": len(surveys),
        "with_registry": len(ok),
        "total_decisions": total,
        "median_decisions_per_repo": med([s.n for s in ok]),
        "status_mix": {k: round(v / total, 3) for k, v in
                       sorted(all_statuses.items(), key=lambda kv: -kv[1])},
        "pct_superseded": round(sum(s.superseded for s in ok) / total, 3),
        "median_days_to_supersede": med(spans),
        "median_months_since_last_decision": med([s.months_since_last for s in dated]),
        "pct_registries_dormant": (
            round(sum(s.dormant for s in judged) / len(judged), 3) if judged else None),
        "pct_decisions_with_alternatives": round(
            sum(s.pct_with_alternatives * s.n for s in ok) / total, 3),
        "pct_decisions_with_consequences": round(
            sum(s.pct_with_consequences * s.n for s in ok) / total, 3),
        "pct_decisions_scope_derivable": round(
            sum(s.pct_scope_derivable * s.n for s in ok) / total, 3),
        "median_words_per_decision": med([s.median_words for s in ok]),
        "dirs_used": dict(sorted(
            ((d, sum(1 for s in ok if s.dir == d)) for d in {s.dir for s in ok}),
            key=lambda kv: -kv[1])),
    }


# ---- deep pass: taxonomy + self-conflicts (LLM, per DEC-0003 kept separate) --

CATEGORY_SCHEMA = {
    "type": "object",
    "properties": {
        "categories": {
            "type": "array",
            "items": {"type": "string",
                      "enum": ["strategy", "product", "design", "engineering",
                               "process", "none"]},
        },
    },
    "required": ["categories"],
    "additionalProperties": False,
}
CONFLICT_SCHEMA = {
    "type": "object",
    "properties": {
        "conflict": {"type": "string", "enum": ["yes", "no", "unclear"]},
        "kind": {"type": "string",
                 "enum": ["contradiction", "silent_supersession", "overlap", "none"]},
        "explanation": {"type": "string"},
    },
    "required": ["conflict", "kind", "explanation"],
    "additionalProperties": False,
}


def classify_titles(titles: list[str]) -> list[str]:
    """Assign one category per title, in batches. Empty list on failure."""
    from . import llm

    out: list[str] = []
    for start in range(0, len(titles), 20):
        batch = titles[start:start + 20]
        listed = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(batch))
        data = llm.complete_json(
            "Classify each architecture decision title into exactly one "
            "category: strategy (market, business model, build-vs-buy), "
            "product (pricing, feature scope, user-facing behaviour), design "
            "(visual, interaction, UX), engineering (architecture, stack, code "
            "invariants), process (versioning, release, review, ways of "
            "working). Use 'none' only if the title states no decision. Return "
            f"one category per title, in order.\n\n{listed}",
            CATEGORY_SCHEMA)
        if not data:
            return []
        out.extend(data["categories"][:len(batch)])
        time.sleep(2.0)
    return out


def conflict_candidates(decisions: list[dict], cap: int = 12) -> list[tuple[dict, dict]]:
    """Pairs of active decisions sharing distinctive vocabulary — the only
    pairs worth spending a judgment on."""
    stop = {"the", "and", "for", "with", "use", "using", "adr", "decision",
            "record", "architecture", "should", "will", "our", "from", "into"}

    def toks(d: dict) -> set[str]:
        return {w.lower().strip("`*()[],.:") for w in d["title"].split()
                if len(w) > 4} - stop

    active = [d for d in decisions
              if d["status"] not in ("superseded", "rejected", "obsolete", "deprecated")
              and d["title"]]
    pairs = []
    for i in range(len(active)):
        for j in range(i + 1, len(active)):
            shared = toks(active[i]) & toks(active[j])
            if len(shared) >= 2:
                pairs.append((len(shared), active[i], active[j]))
    pairs.sort(key=lambda p: -p[0])
    return [(a, b) for _, a, b in pairs[:cap]]


def judge_conflict(a: dict, b: dict, repo: str) -> dict | None:
    from . import llm

    return llm.complete_json(
        f"Two decision records coexist as active in {repo}:\n\n"
        f"A ({a['path']}, status {a['status']}): {a['title']}\n"
        f"B ({b['path']}, status {b['status']}): {b['title']}\n\n"
        "Do they conflict? 'contradiction' = they mandate incompatible things; "
        "'silent_supersession' = B clearly replaces A but A was never marked "
        "superseded; 'overlap' = same ground, compatible; 'none' = unrelated. "
        "Titles alone may be insufficient — answer 'unclear' rather than guess.",
        CONFLICT_SCHEMA)
