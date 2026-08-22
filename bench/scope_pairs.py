"""Add production-shaped scoped diffs to the benchmark pairs.

Production never judges an unscoped decision: the funnel derives which files a
decision governs, cuts the diff to those hunks, and only then asks the judge.
This script reproduces that: one scope derivation per distinct decision
(committed to scopes.json, reviewable and correctable like any scope), then a
per-file cut of each pair's diff.

Usage: MISTRAL_API_KEY=... python3 bench/scope_pairs.py
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from verdica import llm  # noqa: E402
from verdica.formats import path_matches  # noqa: E402

SCOPE_SCHEMA = {
    "type": "object",
    "properties": {
        "globs": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["globs"],
    "additionalProperties": False,
}

FILE_RE = re.compile(r"^diff --git a/(\S+) b/\S+", re.MULTILINE)


def split_diff(diff: str) -> dict[str, str]:
    """Map changed path -> its chunk of the unified diff."""
    parts: dict[str, str] = {}
    matches = list(FILE_RE.finditer(diff))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(diff)
        parts[m.group(1)] = diff[m.start():end]
    return parts


def derive_scope(decision_text: str, sample_files: list[str]) -> list[str]:
    data = llm.complete_json(
        "A team recorded this decision. Derive the scope: glob patterns for "
        "the repository paths this decision governs — the files where a "
        "violating change would live. Be as narrow as the decision allows; "
        "use '**' only if the decision genuinely governs the whole tree. "
        "Ground your globs in the real path vocabulary of this repository, "
        "sampled below.\n\nDecision:\n" + decision_text[:8000]
        + "\n\nSample of real paths in this repository:\n"
        + "\n".join(sample_files[:40]),
        SCOPE_SCHEMA)
    return (data or {}).get("globs") or ["**"]


def main() -> None:
    if not llm.available():
        print("needs a provider key")
        raise SystemExit(2)
    pairs = [json.loads(l) for l in
             (ROOT / "bench" / "pairs.jsonl").read_text().splitlines() if l.strip()]

    scopes_path = ROOT / "bench" / "scopes.json"
    scopes: dict[str, list[str]] = (
        json.loads(scopes_path.read_text()) if scopes_path.exists() else {})
    by_decision: dict[str, list[dict]] = {}
    for p in pairs:
        by_decision.setdefault(f"{p['decision_repo']}:{p['decision_file']}", []).append(p)

    for key, group in by_decision.items():
        if key in scopes:
            continue
        sample = sorted({f for p in group for f in split_diff(p["diff"])})
        scopes[key] = derive_scope(group[0]["decision_text"], sample)
        print(f"{key} -> {scopes[key]}", flush=True)
        time.sleep(2)
    scopes_path.write_text(json.dumps(scopes, indent=2, ensure_ascii=False) + "\n")

    scoped_nonempty = 0
    for p in pairs:
        globs = scopes[f"{p['decision_repo']}:{p['decision_file']}"]
        parts = split_diff(p["diff"])
        keep = {f: chunk for f, chunk in parts.items()
                if any(path_matches(g, f) for g in globs)}
        p["scope_globs"] = globs
        p["scoped_diff"] = "".join(keep.values())
        scoped_nonempty += bool(p["scoped_diff"])
    (ROOT / "bench" / "pairs.jsonl").write_text(
        "\n".join(json.dumps(p, ensure_ascii=False) for p in pairs) + "\n")
    print(f"\n{scoped_nonempty}/{len(pairs)} pairs reach the judge after the funnel")


if __name__ == "__main__":
    main()
