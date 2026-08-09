from pathlib import Path

import pytest

from decisis.formats import load_decisions, parse_decision, path_matches, scope_hits
from decisis.gate import Finding, should_fail
from decisis.formats import Decision


def write_decision(ddir: Path, id: str, status: str = "accepted",
                   severity: str = "warn", paths: list[str] | None = None) -> Path:
    ddir.mkdir(exist_ok=True)
    p = ddir / f"{id}-test.md"
    paths_yaml = "\n".join(f'    - "{x}"' for x in (paths or ["src/**"]))
    p.write_text(
        f"---\nid: {id}\ntitle: A test decision\nstatus: {status}\n"
        f"severity: {severity}\nscope:\n  paths:\n{paths_yaml}\n---\n\n"
        "## Decision\nBody text.\n",
        encoding="utf-8")
    return p


def test_parse_roundtrip(tmp_path):
    p = write_decision(tmp_path / ".decisions", "DEC-0001", paths=["a/**", "b.py"])
    d = parse_decision(p)
    assert d.id == "DEC-0001"
    assert d.active
    assert d.paths == ["a/**", "b.py"]
    assert "Body text" in d.body


def test_missing_frontmatter_rejected(tmp_path):
    p = tmp_path / "bad.md"
    p.write_text("no frontmatter here")
    with pytest.raises(ValueError):
        parse_decision(p)


def test_duplicate_ids_rejected(tmp_path):
    ddir = tmp_path / ".decisions"
    write_decision(ddir, "DEC-0001")
    (ddir / "DEC-0001-copy.md").write_text(
        (ddir / "DEC-0001-test.md").read_text(), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_decisions(tmp_path)


def test_path_matching():
    assert path_matches("services/orders/**", "services/orders/api/handler.py")
    assert path_matches("services/orders/**", "services/orders")
    assert not path_matches("services/orders/**", "services/ordersx/file.py")
    assert path_matches("*.tf", "main.tf")
    assert path_matches("*.tf", "modules/main.tf")  # fnmatch: '*' crosses '/'
    assert path_matches("**", "anything/at/all")


def test_scope_hits_ignores_inactive(tmp_path):
    ddir = tmp_path / ".decisions"
    write_decision(ddir, "DEC-0001", paths=["src/**"])
    write_decision(ddir, "DEC-0002", status="superseded", paths=["src/**"])
    decisions = load_decisions(tmp_path)
    hits = scope_hits(decisions, ["src/a.py", "docs/readme.md"])
    assert hits == {"DEC-0001": ["src/a.py"]}


def _finding(severity: str, contradicts, confidence) -> Finding:
    d = Decision(id="DEC-0001", title="t", status="accepted",
                 paths=["**"], severity=severity)
    return Finding(decision=d, touched=["a.py"], contradicts=contradicts,
                   confidence=confidence, evidence=None)


def test_should_fail_only_on_high_confidence_block():
    assert should_fail([_finding("block", True, "high")], "block")
    assert not should_fail([_finding("block", True, "medium")], "block")
    assert not should_fail([_finding("warn", True, "high")], "block")
    assert not should_fail([_finding("block", False, "high")], "block")
    assert not should_fail([_finding("block", True, "high")], "never")


def test_miner_classification():
    from decisis.miner import MinedPR  # dataclass shape stays importable
    # timeline logic lives in analyze_pr against the live API; the pure rule is:
    # cite_at <= merged_at -> cited_pre_merge, else flagged_post_merge.
    assert MinedPR(
        repo="o/r", number=1, url="u", title="t", state="closed",
        merged_at="2026-01-02T00:00:00Z", first_cite_at="2026-01-01T00:00:00Z",
        cite_source="comment", cited_ids=["ADR-1"], classification="cited_pre_merge",
    ).classification == "cited_pre_merge"


def test_bootstrap_clustering_merges_shared_tokens():
    from decisis.bootstrap import Mention, cluster_mentions
    ms = [
        Mention("lib/theme.dart", 10, "never change #6D28D9 without a decision", "comment"),
        Mention("web/legal.html", 5, "accent stays #6D28D9 on every surface", "comment"),
        Mention("docs/other.md", 3, "always run the linter before pushing", "doc"),
    ]
    clusters = cluster_mentions(ms)
    sizes = sorted(len(c.mentions) for c in clusters)
    assert sizes == [1, 2]  # the two #6D28D9 mentions merged, linter apart


def test_bootstrap_backtest_demotes_and_receipts():
    from decisis.bootstrap import Draft, Merge, backtest
    noisy = Draft(id="DEC-0001", title="t", tier="T3", severity="warn",
                  scope=["**"], evidence=[])
    quiet = Draft(id="DEC-0002", title="t", tier="T3", severity="warn",
                  scope=["ci/**"], evidence=[])
    merges = [Merge("a" * 10, "one", ["src/a.py"]),
              Merge("b" * 10, "two", ["src/b.py"]),
              Merge("c" * 10, "three", ["ci/x.yml"], reverted=True)]
    backtest([noisy, quiet], merges)
    assert noisy.demoted and noisy.noise == 1.0
    assert quiet.receipts and quiet.severity == "block" and not quiet.demoted


def test_bootstrap_normative_scan_filters_code_lines(tmp_path):
    import subprocess
    from decisis.bootstrap import scan_normative
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / "a.py").write_text(
        "# never commit the plain jar, always run the obfuscation step first\n"
        "x = 'must be a string but this is code, not a comment line here'\n")
    (repo / "notes.md").write_text("Deploys always go through the release job only.\n")
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "-c", "user.email=t@t", "-c", "user.name=t",
                 "commit", "-qm", "x"]):
        subprocess.run(cmd, cwd=repo, check=True)
    got = {m.file for m in scan_normative(repo)}
    assert "a.py" in got and "notes.md" in got
    texts = " ".join(m.text for m in scan_normative(repo))
    assert "not a comment line" not in texts
