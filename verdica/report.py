"""Render a bootstrap run as a page a human can review without a terminal.

Same data the CLI prints, arranged for the decision a reviewer actually makes:
keep this rule or not. Each proposal shows the evidence it came from, the scope
it would take, and what it would have done to the recent history — so the cost
of a rule is visible before anyone agrees to it.

Self-contained HTML: no network, no assets. Today it is a file the CLI writes;
the hosted flow renders the same thing and ends in a pull request.
"""

from __future__ import annotations

import html
from pathlib import Path

CSS = """
:root {
  color-scheme: dark light;
  --bg: #08080a; --panel: #0e0e11; --ink: #ededf0; --muted: #8b8b96;
  --line: #ffffff14; --line-strong: #ffffff26; --accent: #4ea3ff;
  --ok: #3fb950; --warn: #d29922; --stop: #f85149;
  --sans: ui-sans-serif, -apple-system, "Segoe UI", Inter, Roboto, sans-serif;
  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;
}
@media (prefers-color-scheme: light) {
  :root { --bg: #ffffff; --panel: #fafafa; --ink: #0a0a0a; --muted: #666672;
          --line: #0000000f; --line-strong: #00000020; --accent: #0060df; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink); font-family: var(--sans);
  font-size: 15px; line-height: 1.6; -webkit-font-smoothing: antialiased; }
main { max-width: 58rem; margin: 0 auto; padding: 4.5rem 1.5rem 8rem; }
header { margin-bottom: 3.5rem; }
h1 { font-size: clamp(1.9rem, 4vw, 2.6rem); font-weight: 600; letter-spacing: -.03em;
  line-height: 1.1; margin: 0 0 .6rem; text-wrap: balance; }
.lede { color: var(--muted); font-size: 1.02rem; margin: 0; max-width: 40rem; }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr));
  gap: 1px; background: var(--line); border: 1px solid var(--line);
  border-radius: 12px; overflow: hidden; margin: 2.5rem 0 3rem; }
.stat { background: var(--bg); padding: 1.1rem 1.25rem; }
.stat b { display: block; font-size: 1.65rem; font-weight: 600; letter-spacing: -.02em;
  font-variant-numeric: tabular-nums; line-height: 1.2; }
.stat span { color: var(--muted); font-size: .78rem; }
h2.section { font-size: .8rem; font-weight: 600; text-transform: uppercase;
  letter-spacing: .09em; color: var(--muted); margin: 0 0 1rem; }
article { background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
  padding: 1.35rem 1.5rem; margin-bottom: .75rem; transition: border-color .15s; }
article:hover { border-color: var(--line-strong); }
article h3 { font-size: 1.02rem; font-weight: 550; margin: 0 0 .75rem;
  line-height: 1.45; letter-spacing: -.01em; }
.meta { display: flex; flex-wrap: wrap; gap: .4rem; margin-bottom: .9rem; }
.tag { font-size: .7rem; font-weight: 500; letter-spacing: .03em; text-transform: uppercase;
  padding: .2rem .5rem; border-radius: 5px; background: var(--line); color: var(--muted); }
.tag.block { color: var(--stop); } .tag.warn { color: var(--warn); }
.impact { display: flex; gap: .55rem; align-items: baseline; font-size: .92rem;
  margin: 0 0 .5rem; }
.impact .dot { width: 6px; height: 6px; border-radius: 50%; flex: 0 0 6px;
  transform: translateY(-2px); }
.dot.hot { background: var(--stop); } .dot.some { background: var(--warn); }
.dot.none { background: var(--ok); }
.scope { color: var(--muted); font-size: .88rem; margin: 0; }
code { font-family: var(--mono); font-size: .85em; background: var(--line);
  padding: .1rem .35rem; border-radius: 4px; }
details { margin-top: .85rem; border-top: 1px solid var(--line); padding-top: .75rem; }
summary { cursor: pointer; color: var(--muted); font-size: .85rem; list-style: none; }
summary::-webkit-details-marker { display: none; }
summary::before { content: "› "; }
details[open] summary::before { content: "⌄ "; }
.evidence { margin: .75rem 0 0; padding: 0; list-style: none; }
.evidence li { font-size: .85rem; color: var(--muted); margin: .4rem 0;
  padding-left: .9rem; border-left: 2px solid var(--line); }
.next { margin-top: 3rem; padding: 1.35rem 1.5rem; border: 1px solid var(--line);
  border-radius: 12px; background: var(--panel); color: var(--muted); font-size: .92rem; }
.next b { color: var(--ink); font-weight: 550; }
"""


def _esc(s: str) -> str:
    return html.escape(str(s), quote=False)


def render_report(repo_name: str, drafts: list, parked: list, mentions: int,
                  merges: int, enforcement: list[str]) -> str:
    cards = []
    for d in drafts:
        if d.receipts:
            impact = (f'<span class="impact">Already cost a revert</span> — '
                      f'{_esc(d.receipts[0])}')
        elif d.noise:
            impact = (f'<span class="impact">Would have flagged '
                      f'{d.noise:.0%} of recent merges</span>')
        else:
            impact = ('<span class="impact">Would have flagged none of the recent '
                      'merges</span> — quiet by default')
        evidence = "".join(
            f"<li><code>{_esc(m.file)}:{m.line}</code> — {_esc(m.text[:180])}</li>"
            if m.file else f"<li>revert <code>{_esc(m.ref[:10])}</code> — {_esc(m.text[:160])}</li>"
            for m in d.evidence[:6])
        scope = ", ".join(f"<code>{_esc(p)}</code>" for p in d.scope)
        cards.append(f"""
    <article>
      <h2>{_esc(d.title)}</h2>
      <div class="meta">
        <span class="tag">{_esc(d.category)}</span>
        <span class="tag {_esc(d.severity)}">{_esc(d.severity)}</span>
        <span class="tag">{_esc(d.tier)} evidence</span>
      </div>
      <p>{impact}</p>
      <p class="scope">Governs {scope}</p>
      <details><summary>Where this came from ({len(d.evidence)} sources)</summary>
        <ul class="evidence">{evidence}</ul>
      </details>
    </article>""")

    parked_html = ""
    if parked:
        items = "".join(f"<li>{_esc(p.title[:120])}</li>" for p in parked[:12])
        parked_html = f"""
    <details style="margin-top:2rem">
      <summary>{len(parked)} candidates held back (too broad, or below the cut)</summary>
      <ul class="evidence">{items}</ul>
    </details>"""

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Decisions found in {_esc(repo_name)}</title>
<style>{CSS}</style></head>
<body><main>
  <h1>Decisions already in {_esc(repo_name)}</h1>
  <p class="lede">Read from the repository itself — normative comments, convention
  docs, reverts — then replayed over recent merges to show what each rule would
  cost. Keep the ones that are real, delete the rest, and merge: the pull request
  is the ratification.</p>
  <div class="stats">
    <div class="stat"><b>{len(drafts)}</b><span>proposed</span></div>
    <div class="stat"><b>{mentions}</b><span>sources read</span></div>
    <div class="stat"><b>{merges}</b><span>merges replayed</span></div>
    <div class="stat"><b>{len(enforcement)}</b><span>already enforced by CI</span></div>
  </div>
  {"".join(cards)}
  {parked_html}
  <p class="next">Next: <code>verdica bootstrap --write</code> writes these into
  <code>.decisions/</code>, <code>--pr</code> opens the pull request. Nothing is
  enforced until you merge it.</p>
</main></body></html>"""
