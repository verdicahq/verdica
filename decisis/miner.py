"""Mine a repository's history for decision citations and classify them.

For each PR whose thread cites a decision record (ADR-/KEP-/DEC-/RFC-style),
the miner establishes the timeline: was the decision cited during review
(before merge), or only after the fact — a slipped violation, often paired
with a revert. Timeline classification is deterministic: no LLM involved.

Classes:
  revert_citing      the PR is itself a revert whose thread cites a decision —
                     hard evidence that a violation reached the main branch
  cited_pre_merge    cited while the PR was open and later merged
  caught_unmerged    cited and the PR was closed without merging
  flagged_post_merge the first citation appeared only after the merge
  cited_open         cited, PR still open
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass

API = "https://api.github.com"
DEFAULT_PATTERN = r"\b(?:ADR|DEC|KEP|RFC)[- ]?\d+"


def _get(url: str, token: str) -> dict | list:
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "decisis-miner",
    })
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


@dataclass
class MinedPR:
    repo: str
    number: int
    url: str
    title: str
    state: str
    merged_at: str | None
    first_cite_at: str | None
    cite_source: str | None  # body | comment | review_comment
    cited_ids: list[str]
    classification: str


def search_citing_prs(repo: str, pattern_hint: str, token: str, cap: int) -> list[int]:
    """PR numbers whose text mentions the decision-record pattern."""
    numbers: list[int] = []
    page = 1
    query = urllib.parse.quote(f'repo:{repo} is:pr "{pattern_hint}"')
    while len(numbers) < cap:
        url = (f"{API}/search/issues?q={query}&advanced_search=true"
               f"&per_page=100&page={page}")
        data = _get(url, token)
        items = data.get("items", [])
        if not items:
            break
        numbers.extend(item["number"] for item in items)
        page += 1
        if page > 10:  # search API caps at 1000 results
            break
        time.sleep(2.1)  # search rate limit: 30/min
    return numbers[:cap]


def analyze_pr(repo: str, number: int, pattern: re.Pattern, token: str) -> MinedPR | None:
    pr = _get(f"{API}/repos/{repo}/pulls/{number}", token)
    cited: set[str] = set()
    first_cite: tuple[str, str] | None = None  # (timestamp, source)

    def scan(text: str | None, created_at: str, source: str) -> None:
        nonlocal first_cite
        if not text:
            return
        found = pattern.findall(text)
        if not found:
            return
        cited.update(m.upper().replace(" ", "-") for m in found)
        if first_cite is None or created_at < first_cite[0]:
            first_cite = (created_at, source)

    scan(pr.get("title"), pr["created_at"], "body")
    scan(pr.get("body"), pr["created_at"], "body")
    for endpoint in ("issues", "pulls"):
        source = "comment" if endpoint == "issues" else "review_comment"
        for page in (1, 2, 3):
            comments = _get(
                f"{API}/repos/{repo}/{endpoint}/{number}/comments?per_page=100&page={page}",
                token,
            )
            for c in comments:
                scan(c.get("body"), c["created_at"], source)
            if len(comments) < 100:
                break

    if not cited:
        return None

    merged_at = pr.get("merged_at")
    is_revert = bool(re.match(r"^revert\b", pr.get("title") or "", re.IGNORECASE))
    cite_at, cite_source = first_cite if first_cite else (None, None)

    if is_revert:
        classification = "revert_citing"
    elif merged_at is None and pr["state"] == "closed":
        classification = "caught_unmerged"
    elif merged_at is None:
        classification = "cited_open"
    elif cite_at is not None and cite_at <= merged_at:
        classification = "cited_pre_merge"
    else:
        classification = "flagged_post_merge"

    return MinedPR(
        repo=repo, number=number, url=pr["html_url"], title=pr["title"],
        state=pr["state"], merged_at=merged_at, first_cite_at=cite_at,
        cite_source=cite_source, cited_ids=sorted(cited),
        classification=classification,
    )


def mine(repo: str, token: str | None = None, cap: int = 100,
         pattern: str = DEFAULT_PATTERN, search_hint: str = "ADR-") -> list[MinedPR]:
    token = token or os.environ["GITHUB_TOKEN"]
    compiled = re.compile(pattern, re.IGNORECASE)
    results: list[MinedPR] = []
    for number in search_citing_prs(repo, search_hint, token, cap):
        mined = analyze_pr(repo, number, compiled, token)
        if mined:
            results.append(mined)
        time.sleep(0.15)  # stay well under the core rate limit
    return results


def summarize(results: list[MinedPR]) -> dict:
    counts: dict[str, int] = {}
    for r in results:
        counts[r.classification] = counts.get(r.classification, 0) + 1
    return {"total": len(results), "by_class": dict(sorted(counts.items()))}


def to_jsonl(results: list[MinedPR]) -> str:
    return "\n".join(json.dumps(asdict(r), ensure_ascii=False) for r in results)
