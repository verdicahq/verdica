"""Run the judge over the pinned benchmark pairs and score it.

The metric that matters is precision on high-confidence contradiction calls:
that is the only signal the gate ever blocks on (DEC-0005), so it is the one
a regression must never degrade.

Usage:
  MISTRAL_API_KEY=... python3 bench/run.py            # score and save
  MISTRAL_API_KEY=... python3 bench/run.py --check    # also fail vs baseline
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from verdica.formats import Decision  # noqa: E402
from verdica.gate import judge  # noqa: E402
from verdica import llm  # noqa: E402

REGRESSION_MARGIN = 0.05


def main() -> int:
    check = "--check" in sys.argv
    if not llm.available():
        print("no provider configured; the bench needs a judge to score")
        return 2
    pairs = [json.loads(l) for l in
             (ROOT / "bench" / "pairs.jsonl").read_text().splitlines() if l.strip()]
    rows, tp = [], 0
    counts = {"tp": 0, "fp": 0, "tn": 0, "fn": 0, "hi_tp": 0, "hi_fp": 0, "err": 0,
              "funnel_miss": 0, "funnel_silence": 0}
    for i, p in enumerate(pairs, 1):
        if "scoped_diff" in p and not p["scoped_diff"]:
            # production semantics: no scope hit, the judge never runs
            key = "funnel_miss" if p["expected_contradicts"] else "funnel_silence"
            counts[key] += 1
            print(f"[{i}/{len(pairs)}] FUNNEL {'miss' if key == 'funnel_miss' else 'ok  '} "
                  f"(no scope hit) {p['source']}", flush=True)
            continue
        decision = Decision(id=p["decision_id"], title=p["decision_id"],
                            status="accepted", paths=["**"],
                            body=p["decision_text"])
        diff = p.get("scoped_diff") or p["diff"]
        v = None
        for attempt in range(4):
            llm.last_error = None
            v = judge(decision, diff)
            if v is not None or not llm.last_error:
                break
            time.sleep(8 * (attempt + 1))  # 429s: back off and retry
        if v is None:
            counts["err"] += 1
            print(f"[{i}/{len(pairs)}] ERR {llm.last_error} {p['source']}", flush=True)
            continue
        got, conf = bool(v["contradicts"]), v.get("confidence")
        exp = p["expected_contradicts"]
        key = ("tp" if got and exp else "fp" if got else
               "fn" if exp else "tn")
        counts[key] += 1
        if got and conf == "high":
            counts["hi_tp" if exp else "hi_fp"] += 1
        rows.append({"source": p["source"], "expected": exp, "got": got,
                     "confidence": conf, "evidence": (v.get("evidence") or "")[:200]})
        print(f"[{i}/{len(pairs)}] {'OK ' if got == exp else 'MISS'} "
              f"exp={exp} got={got} ({conf}) {p['source']}", flush=True)
        time.sleep(3)

    n = counts["tp"] + counts["fp"] + counts["tn"] + counts["fn"]
    precision = counts["tp"] / max(1, counts["tp"] + counts["fp"])
    recall = counts["tp"] / max(1, counts["tp"] + counts["fn"])
    hi_calls = counts["hi_tp"] + counts["hi_fp"]
    hi_precision = counts["hi_tp"] / max(1, hi_calls)
    summary = {"date": str(date.today()), "provider": llm.provider(),
               "n": n, "errors": counts["err"],
               "precision": round(precision, 3), "recall": round(recall, 3),
               "high_conf_calls": hi_calls,
               "high_conf_precision": round(hi_precision, 3),
               "funnel_misses": counts["funnel_miss"],
               "funnel_silences": counts["funnel_silence"],
               "counts": counts}
    print("\n" + json.dumps(summary, indent=2))
    results_dir = ROOT / "bench" / "results"
    results_dir.mkdir(exist_ok=True)
    (results_dir / f"{summary['provider']}-{summary['date']}.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, indent=2), encoding="utf-8")

    baseline_path = ROOT / "bench" / "baseline.json"
    if check and baseline_path.exists():
        base = json.loads(baseline_path.read_text())
        for metric in ("high_conf_precision", "precision"):
            if summary[metric] < base[metric] - REGRESSION_MARGIN:
                print(f"\nREGRESSION: {metric} {summary[metric]} < "
                      f"baseline {base[metric]} - {REGRESSION_MARGIN}")
                return 1
        print("\nno regression vs baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
