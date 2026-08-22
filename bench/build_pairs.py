"""Build judge benchmark pairs from the labeled event dataset.

Each labeled event (dataset/labeled.jsonl) references a real PR and the
decision it cited; this script fetches the decision text and the PR diff and
emits one (decision, diff, expected) pair per event it can reconstruct.
The output is committed: the cohort is pinned, because a benchmark whose
population moves is not a benchmark (we learned this the hard way).

Usage: GITHUB_TOKEN=... python3 bench/build_pairs.py
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_DIRS = (".decisions", "docs/adr", "doc/adr", "docs/decisions",
                 "docs/architecture/decisions", "adr", "docs/adrs", "decisions",
                 "docs/arch/adr", "architecture/decisions", "docs/architecture")
DIFF_CAP = 15000
BODY_CAP = 12000


def gh(path: str, accept: str = "application/vnd.github+json") -> bytes:
    req = urllib.request.Request(
        "https://api.github.com" + path,
        headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                 "Accept": accept, "User-Agent": "verdica-bench"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


# Some projects keep the registry in a sibling repo (home-assistant/core cites
# ADRs living in home-assistant/architecture). Try the PR's repo first, then
# the known siblings.
REGISTRY_REPO_ALIASES = {"home-assistant/core": ["home-assistant/architecture"]}


def find_decision_file(pr_repo: str, cited: str) -> tuple[str, str, str] | None:
    """Locate the cited decision and return (registry_repo, path, text)."""
    for repo in [pr_repo] + REGISTRY_REPO_ALIASES.get(pr_repo, []):
        hit = _find_in_repo(repo, cited)
        if hit:
            return repo, hit[0], hit[1]
    return None


def _find_in_repo(repo: str, cited: str) -> tuple[str, str] | None:
    num = re.sub(r"\D", "", cited)
    if not num:
        return None
    stems = {num, num.zfill(3), num.zfill(4), num.lstrip("0") or num}
    for d in REGISTRY_DIRS:
        try:
            listing = json.loads(gh(f"/repos/{repo}/contents/{d}"))
        except (urllib.error.HTTPError, urllib.error.URLError, OSError):
            continue
        if not isinstance(listing, list):
            continue
        for item in listing:
            name = item.get("name", "")
            if not name.endswith(".md"):
                continue
            file_nums = re.findall(r"\d+", name)
            if any(fn in stems or (fn.lstrip("0") or fn) in stems
                   for fn in file_nums[:1]):
                try:
                    raw = gh(f"/repos/{repo}/contents/{d}/{name}",
                             accept="application/vnd.github.raw+json")
                    return f"{d}/{name}", raw.decode("utf-8", "replace")
                except (urllib.error.HTTPError, OSError):
                    return None
    return None


def main() -> None:
    events = [json.loads(l) for l in
              (ROOT / "dataset" / "labeled.jsonl").read_text().splitlines() if l.strip()]
    pairs, skipped = [], []
    for e in events:
        cited = (e.get("cited_ids") or [None])[0]
        if not cited:
            skipped.append((e["url"], "no cited id"))
            continue
        found = find_decision_file(e["repo"], cited)
        if not found:
            skipped.append((e["url"], f"decision {cited} not found"))
            continue
        drepo, dpath, dtext = found
        try:
            diff = gh(f"/repos/{e['repo']}/pulls/{e['number']}",
                      accept="application/vnd.github.diff").decode("utf-8", "replace")
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as ex:
            skipped.append((e["url"], f"diff: {type(ex).__name__}"))
            continue
        added_registry_file = any(
            f"+++ b/{d}/" in diff for d in REGISTRY_DIRS)
        if f"+++ b/{dpath}" in diff or added_registry_file:
            skipped.append((e["url"], "PR touches the registry itself"))
            continue
        pairs.append({
            "source": e["url"],
            "repo": e["repo"],
            "decision_id": cited,
            "decision_repo": drepo,
            "decision_file": dpath,
            "decision_text": dtext[:BODY_CAP],
            "diff": diff[:DIFF_CAP],
            "expected_contradicts": e["label"] == "yes",
            "classification": e.get("classification"),
        })
        time.sleep(0.5)
    out = ROOT / "bench" / "pairs.jsonl"
    out.write_text("\n".join(json.dumps(p, ensure_ascii=False) for p in pairs) + "\n",
                   encoding="utf-8")
    pos = sum(p["expected_contradicts"] for p in pairs)
    print(f"pairs: {len(pairs)} ({pos} positive, {len(pairs) - pos} negative)")
    print(f"skipped: {len(skipped)}")
    for url, why in skipped:
        print(f"  - {url}: {why}")


if __name__ == "__main__":
    main()
