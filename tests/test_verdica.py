from pathlib import Path

import pytest

from verdica.formats import load_decisions, parse_decision, path_matches, scope_hits
from verdica.gate import Finding, should_fail
from verdica.formats import Decision


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


def test_missing_frontmatter_rejected_in_native_dir(tmp_path):
    ddir = tmp_path / ".decisions"
    ddir.mkdir()
    p = ddir / "bad.md"
    p.write_text("no frontmatter here")
    with pytest.raises(ValueError):
        parse_decision(p)


def test_legacy_adr_read_in_place(tmp_path):
    from verdica.formats import decisions_dir, load_decisions
    adr = tmp_path / "docs" / "adr"
    adr.mkdir(parents=True)
    (adr / "0001-record-decisions.md").write_text(
        "# 1. Record architecture decisions\n\n## Status\n\nAccepted\n\n"
        "## Context\nWe need a log.\n")
    (adr / "0007-use-postgres.md").write_text(
        "# 7. Use Postgres\n\n## Status\n\nSuperseded by ADR-12\n")
    (adr / "0012-use-mysql.md").write_text("# 12. Use MySQL\n\n## Status\n\nApproved\n")
    (adr / "README.md").write_text("# Index\nnot a decision\n")
    assert decisions_dir(tmp_path) == adr
    ds = load_decisions(tmp_path)
    assert len(ds) == 3                                  # README excluded
    assert all(d.legacy and d.paths == [] for d in ds)   # digest-only until scoped
    by_title = {d.title: d for d in ds}
    assert by_title["Use Postgres"].status == "superseded"
    assert by_title["Use MySQL"].status == "accepted"    # 'Approved' normalised


def test_native_dir_wins_over_legacy(tmp_path):
    from verdica.formats import decisions_dir
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    for n in range(3):
        (tmp_path / "docs" / "adr" / f"{n}.md").write_text("# x\n")
    (tmp_path / ".decisions").mkdir()
    assert decisions_dir(tmp_path) == tmp_path / ".decisions"


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
    from verdica.miner import MinedPR  # dataclass shape stays importable
    # timeline logic lives in analyze_pr against the live API; the pure rule is:
    # cite_at <= merged_at -> cited_pre_merge, else flagged_post_merge.
    assert MinedPR(
        repo="o/r", number=1, url="u", title="t", state="closed",
        merged_at="2026-01-02T00:00:00Z", first_cite_at="2026-01-01T00:00:00Z",
        cite_source="comment", cited_ids=["ADR-1"], classification="cited_pre_merge",
    ).classification == "cited_pre_merge"


def test_bootstrap_clustering_merges_shared_tokens():
    from verdica.bootstrap import Mention, cluster_mentions
    ms = [
        Mention("lib/theme.dart", 10, "never change #6D28D9 without a decision", "comment"),
        Mention("web/legal.html", 5, "accent stays #6D28D9 on every surface", "comment"),
        Mention("docs/other.md", 3, "always run the linter before pushing", "doc"),
    ]
    clusters = cluster_mentions(ms)
    sizes = sorted(len(c.mentions) for c in clusters)
    assert sizes == [1, 2]  # the two #6D28D9 mentions merged, linter apart


def test_bootstrap_backtest_demotes_and_receipts():
    from verdica.bootstrap import Draft, Mention, Merge, backtest
    repo_ev = [Mention("src/a.py", 1, "never do the thing", "comment")]
    noisy = Draft(id="DEC-0001", title="t", tier="T3", severity="warn",
                  scope=["**"], evidence=repo_ev)
    quiet = Draft(id="DEC-0002", title="t", tier="T3", severity="warn",
                  scope=["ci/**"], evidence=repo_ev)
    merges = [Merge("a" * 10, "one", ["src/a.py"]),
              Merge("b" * 10, "two", ["src/b.py"]),
              Merge("c" * 10, "three", ["ci/x.yml"], reverted=True)]
    backtest([noisy, quiet], merges)
    assert noisy.demoted and noisy.noise == 1.0
    assert quiet.receipts and quiet.severity == "block" and not quiet.demoted


def test_bootstrap_normative_scan_filters_code_lines(tmp_path):
    import subprocess
    from verdica.bootstrap import scan_normative
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


def test_scan_notes_and_no_scope_from_notes(tmp_path):
    from verdica.bootstrap import Cluster, Mention, distill, scan_notes
    notes = tmp_path / "meetings"
    notes.mkdir()
    (notes / "retro.md").write_text(
        "# Retro\n- Deciso: la beta esterna parte solo dopo i tester interni\n"
        "- il caffè era buono\n", encoding="utf-8")
    ms = scan_notes(notes)
    assert len(ms) == 1 and ms[0].file.startswith("notes:")
    d = distill(Cluster([ms[0]]), 1)
    assert d.scope == ["**"]  # notes never contribute scope paths


def test_questions_defaults_and_choices():
    from verdica.bootstrap import Draft, Question, collect_questions, ask
    with_receipt = Draft(id="DEC-0001", title="t", tier="T2", severity="block",
                         scope=["ci/**"], evidence=[],
                         receipts=["abc revert"])
    forked = Draft(id="DEC-0002", title="t", tier="T3", severity="warn",
                   scope=["app/**", "docs/**"], evidence=[])
    qs = collect_questions([with_receipt, forked])
    assert [q.kind for q in qs] == ["confirm_block", "scope_fork"]
    log = ask(qs, answers=[2, 3], interactive=False)
    assert with_receipt.severity == "warn"      # answer 2 = warn
    assert forked.scope == ["docs/**"]           # answer 3 = second scope path
    assert len(log) == 2
    # defaults: 1 = keep block / keep all
    qs2 = collect_questions([Draft(id="D", title="t", tier="T2", severity="block",
                                   scope=["ci/**"], evidence=[], receipts=["r"])])
    ask(qs2, answers=None, interactive=False)
    assert qs2[0].draft.severity == "block"


def test_llm_provider_selection(monkeypatch):
    from verdica import llm
    for var in ("VERDICA_PROVIDER", "MISTRAL_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert llm.provider() is None and not llm.available()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert llm.provider() == "anthropic"
    monkeypatch.setenv("MISTRAL_API_KEY", "y")
    assert llm.provider() == "mistral"  # mistral preferred when both exist
    monkeypatch.setenv("VERDICA_PROVIDER", "anthropic")
    assert llm.provider() == "anthropic"  # explicit owner choice wins


def test_inrepo_meeting_notes_are_note_kind(tmp_path):
    import subprocess
    from verdica.bootstrap import Cluster, distill, scan_normative
    repo = tmp_path / "r"
    (repo / "docs" / "meetings").mkdir(parents=True)
    (repo / "docs" / "meetings" / "sync.md").write_text(
        "Deciso: il deploy si fa sempre dal branch di release.\n")
    (repo / "src").mkdir()
    (repo / "src" / "a.py").write_text("# never deploy from a feature branch\n")
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "-c", "user.email=t@t", "-c", "user.name=t",
                 "commit", "-qm", "x"]):
        subprocess.run(cmd, cwd=repo, check=True)
    ms = scan_normative(repo)
    kinds = {m.file: m.kind for m in ms}
    assert kinds["docs/meetings/sync.md"] == "note"
    assert kinds["src/a.py"] == "comment"
    # a meeting-note mention alone yields a digest-only draft (scope **)
    note = next(m for m in ms if m.kind == "note")
    assert distill(Cluster([note]), 1).scope == ["**"]


def test_digest_groups_by_category_and_flags_gating(tmp_path):
    import subprocess
    from verdica.gate import render_digest
    repo = tmp_path / "r"
    ddir = repo / ".decisions"
    ddir.mkdir(parents=True)
    (ddir / "DEC-0001-a.md").write_text(
        "---\nid: DEC-0001\ntitle: Strategy rule\nstatus: accepted\n"
        "category: strategy\nscope:\n  paths:\n    - \"**\"\n---\n\nbody\n")
    (ddir / "DEC-0002-b.md").write_text(
        "---\nid: DEC-0002\ntitle: Code rule\nstatus: accepted\nseverity: block\n"
        "category: engineering\nscope:\n  paths:\n    - \"src/**\"\n---\n\nbody\n")
    (ddir / "DEC-0003-c.md").write_text(
        "---\nid: DEC-0003\ntitle: Pending rule\nstatus: proposed\n"
        "category: product\nscope:\n  paths:\n    - \"cfg/**\"\n---\n\nbody\n")
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "-c", "user.email=t@t", "-c", "user.name=t",
                 "commit", "-qm", "x"]):
        subprocess.run(cmd, cwd=repo, check=True)
    out = render_digest(repo, "30 days ago")
    assert "### strategy (1)" in out and "### engineering (1)" in out
    assert "digest-only" in out          # ** scope never gates
    assert "[block/gates]" in out        # real scope gates
    assert "Awaiting ratification (1)" in out
    assert "### product" not in out      # proposed decisions are not standing


def test_survey_parses_decision_anatomy():
    from verdica.survey import parse_decision
    d = parse_decision("docs/adr/0007-use-postgres.md", """# 7. Use Postgres

Date: 2024-03-01

## Status

Superseded by ADR-0012

## Context
We need a store for `services/orders/` data.

## Considered Options
- MongoDB — rejected, no transactions

## Consequences
Ops must run Postgres.
""")
    assert d.number == 7 and d.status == "superseded" and d.superseded_by == 12
    assert d.date == "2024-03-01" and d.title == "7. Use Postgres"
    assert d.has_alternatives and d.has_consequences and d.scope_derivable


def test_survey_aggregate_handles_empty_and_mixed():
    from verdica.survey import RepoSurvey, aggregate
    empty = RepoSurvey(repo="a/b", error="no decision directory")
    assert aggregate([empty])["with_registry"] == 0
    full = RepoSurvey(repo="c/d", dir="adr", n=2, statuses={"accepted": 1, "superseded": 1},
                      superseded=1, pct_with_alternatives=0.5, pct_with_consequences=1.0,
                      pct_scope_derivable=1.0, median_words=300, months_since_last=25.0,
                      dormant=True, median_days_to_supersede=400.0)
    agg = aggregate([empty, full])
    assert agg["with_registry"] == 1 and agg["total_decisions"] == 2
    assert agg["pct_superseded"] == 0.5 and agg["pct_registries_dormant"] == 1.0


def test_conflict_candidates_skips_parallel_families():
    from verdica.survey import conflict_candidates
    def d(path, title):
        return {"path": path, "title": title, "status": "accepted", "date": None}
    family = [d("a.md", "0013. Installation method: Home Assistant Container"),
              d("b.md", "0016. Installation method: Home Assistant Core")]
    assert conflict_candidates(family) == []          # parallel variants
    rivals = [d("c.md", "5. Use custom testEach instead of jest each"),
              d("e.md", "16. Remove custom testEach helper entirely")]
    assert len(conflict_candidates(rivals)) == 1      # genuine reversal survives


def test_conflict_candidates_require_reversal_or_near_duplicate():
    from verdica.survey import conflict_candidates
    def d(path, title):
        return {"path": path, "title": title, "status": "accepted", "date": None}
    # umbrella + the variants it introduces: related, not conflicting
    umbrella = [d("a.md", "0012. Define supported installation method"),
                d("b.md", "0014. Installation method Home Assistant Supervised")]
    assert conflict_candidates(umbrella) == []
    # a reversal verb makes the pair worth judging
    reversal = [d("c.md", "10. Integration configuration through YAML"),
                d("f.md", "21. YAML integration configuration deprecation policy")]
    assert len(conflict_candidates(reversal)) == 1
    # two decisions with the same title are worth judging even without a verb
    dupes = [d("g.md", "9. End-to-end E2E Testing strategy"),
             d("h.md", "12. End-to-end E2E Testing strategy")]
    assert len(conflict_candidates(dupes)) == 1


def test_registry_hygiene_flags_dead_scope_and_unscoped(tmp_path):
    import subprocess
    from verdica.gate import registry_hygiene
    repo = tmp_path / "r"
    ddir = repo / ".decisions"
    ddir.mkdir(parents=True)
    (repo / "src").mkdir()
    (repo / "src" / "live.py").write_text("x = 1\n")
    (ddir / "DEC-0001-live.md").write_text(
        "---\nid: DEC-0001\ntitle: Live rule\nstatus: accepted\n"
        "scope:\n  paths:\n    - \"src/**\"\n---\n\nbody\n")
    (ddir / "DEC-0002-dead.md").write_text(
        "---\nid: DEC-0002\ntitle: Dead rule\nstatus: accepted\n"
        "scope:\n  paths:\n    - \"deleted_module/**\"\n---\n\nbody\n")
    (ddir / "DEC-0003-unscoped.md").write_text(
        "---\nid: DEC-0003\ntitle: Strategy rule\nstatus: accepted\n"
        "scope:\n  paths: []\n---\n\nbody\n")
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "-c", "user.email=t@t", "-c", "user.name=t",
                 "commit", "-qm", "x"]):
        subprocess.run(cmd, cwd=repo, check=True)
    out = "\n".join(registry_hygiene(repo))
    assert "DEC-0002" in out and "no longer exists" in out
    assert "DEC-0001" not in out                    # its scope still matches files
    assert "Not enforceable yet (1)" in out and "DEC-0003" in out


def test_status_parser_handles_the_shapes_teams_actually_write():
    from verdica.survey import parse_decision
    shapes = {
        "## Status\n\nAccepted\n": "accepted",
        "Status: Superseded by ADR-12\n": "superseded",
        "**Status**: Proposed\n": "proposed",
        "| Status | Accepted |\n": "accepted",
        "- status: rejected\n": "rejected",
        "# 3. A decision\n\nAccepted\n\n## Context\n": "accepted",
        "![](https://img.shields.io/badge/status-deprecated-red)\n": "deprecated",
    }
    for text, expected in shapes.items():
        got = parse_decision("docs/adr/0003-x.md", text).status
        assert got == expected, f"{text!r} parsed as {got}, expected {expected}"


def test_advisor_needs_an_unmistakable_mark(tmp_path):
    from verdica.formats import Decision
    from verdica.gate import _distinctive
    strong, weak = _distinctive(Decision(
        id="D", title="Design light-first, accent #6D28D9", status="accepted",
        paths=["app/theme/**"], body="Never a dark variant. See app_colors.dart."))
    assert "#6d28d9" in strong                   # a hex colour is unmistakable
    assert "app_colors" in weak                  # an identifier needs corroboration
    plain, plain_weak = _distinctive(Decision(
        id="E", title="The registry lives in the repository", status="accepted",
        paths=["**"], body="Decisions are files reviewed in pull requests."))
    assert not plain and not plain_weak          # ordinary words are not marks


def test_preview_replays_a_proposed_decision_over_history(tmp_path):
    import subprocess
    from verdica.gate import preview_decisions
    repo = tmp_path / "r"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "a.py").write_text("x = 1\n")
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True,
                                    capture_output=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    run("config", "user.email", "t@t"); run("config", "user.name", "t")
    run("add", "-A"); run("commit", "-qm", "base")
    # a merged change touching src/
    run("checkout", "-qb", "feature")
    (repo / "src" / "b.py").write_text("y = 2\n")
    run("add", "-A"); run("commit", "-qm", "add b")
    run("checkout", "-q", "master") if (repo / ".git" / "refs" / "heads" / "master").exists() \
        else run("checkout", "-q", "main")
    run("merge", "--no-ff", "-q", "feature", "-m", "Merge feature")
    base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    # now a branch that proposes a decision scoped to src/
    run("checkout", "-qb", "add-decision")
    ddir = repo / ".decisions"; ddir.mkdir()
    (ddir / "DEC-0001-x.md").write_text(
        "---\nid: DEC-0001\ntitle: Rule about src\nstatus: proposed\n"
        "scope:\n  paths:\n    - \"src/**\"\n---\n\nbody\n")
    run("add", "-A"); run("commit", "-qm", "propose")
    out = "\n".join(preview_decisions(repo, base))
    assert "DEC-0001" in out and "would have flagged **1 of the last 1 merges**" in out


def test_html_report_escapes_and_shows_impact():
    from verdica.bootstrap import Draft, Mention
    from verdica.report import render_report
    d = Draft(id="DEC-0001", title="Never ship <script> unescaped",
              tier="T2", severity="block", scope=["src/**"],
              evidence=[Mention("src/a.py", 12, "never ship <script>", "comment")],
              category="engineering", noise=0.2, receipts=["abc Revert bad merge"])
    quiet = Draft(id="DEC-0002", title="A quiet rule", tier="T3", severity="warn",
                  scope=["ci/**"], evidence=[], category="process")
    out = render_report("myrepo", [d, quiet], [], mentions=40, merges=30,
                        enforcement=[".github/workflows/ci.yml"])
    assert "&lt;script&gt;" in out and "<script>" not in out.split("<style>")[1]
    assert "Already cost a revert" in out          # receipt outranks noise
    assert "would have flagged none" in out.lower()  # a rule with no history says so
    assert "myrepo" in out and "src/**" in out


def test_nature_tradeoff_roundtrip(tmp_path):
    ddir = tmp_path / ".decisions"
    ddir.mkdir()
    (ddir / "DEC-0001-fee-hidden.md").write_text(
        "---\nid: DEC-0001\ntitle: While in-app payments are disabled, the "
        "call-out fee is not shown\nstatus: accepted\nseverity: warn\n"
        "nature: tradeoff\nrevisit_when: \"in-app payments go live\"\n"
        "scope:\n  paths:\n    - \"app/**\"\ndeciders: []\n---\n\nbody\n",
        encoding="utf-8")
    (ddir / "DEC-0002-implied.md").write_text(
        "---\nid: DEC-0002\ntitle: Implied tradeoff\nstatus: accepted\n"
        "revisit_when: \"the beta ends\"\n"
        "scope:\n  paths:\n    - \"x/**\"\ndeciders: []\n---\n\nbody\n",
        encoding="utf-8")
    from verdica.formats import load_decisions
    decisions = {d.id: d for d in load_decisions(tmp_path)}
    assert decisions["DEC-0001"].nature == "tradeoff"
    assert decisions["DEC-0001"].revisit_when == "in-app payments go live"
    assert decisions["DEC-0002"].nature == "tradeoff"  # implied by revisit_when

    from verdica.gate import Finding, render_digest, render_summary
    summary = render_summary([Finding(
        decision=decisions["DEC-0001"], touched=["app/main.dart"],
        contradicts=None, confidence=None, evidence=None)])
    assert "revisit when: in-app payments go live" in summary
    assert "supersede it" in summary

    digest = render_digest(tmp_path, "7 days ago")
    assert "Tradeoffs due for review (2)" in digest
    assert "the beta ends" in digest
