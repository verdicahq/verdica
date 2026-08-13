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
  color-scheme: light dark;
  --ink: #17151a; --muted: #5c5866; --line: #17151a1a; --bg: #fbfaf8;
  --card: #ffffff; --accent: #3d5a3d; --warn: #8a5a1a; --block: #8a2f2f;
}
@media (prefers-color-scheme: dark) {
  :root { --ink: #ece9f0; --muted: #a29daa; --line: #ffffff1f; --bg: #131116;
          --card: #1b1920; --accent: #9dbf9d; --warn: #d9a35c; --block: #d98080; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.6 ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 54rem; margin: 0 auto; padding: 3rem 1.25rem 6rem; }
h1 { font-size: 1.75rem; letter-spacing: -.02em; margin: 0 0 .3em; text-wrap: balance; }
.lede { color: var(--muted); margin: 0 0 2.5rem; max-width: 42rem; }
.stats { display: flex; flex-wrap: wrap; gap: 2rem; margin: 0 0 2.5rem;
  padding-bottom: 1.5rem; border-bottom: 1px solid var(--line); }
.stat b { display: block; font-size: 1.5rem; font-variant-numeric: tabular-nums; }
.stat span { color: var(--muted); font-size: .8rem; text-transform: uppercase;
  letter-spacing: .06em; }
article { background: var(--card); border: 1px solid var(--line); border-radius: 10px;
  padding: 1.25rem 1.4rem; margin: 0 0 1rem; }
article h2 { font-size: 1.05rem; margin: 0 0 .5rem; line-height: 1.45; }
.meta { display: flex; flex-wrap: wrap; gap: .45rem; margin: 0 0 .9rem; }
.tag { font-size: .72rem; letter-spacing: .04em; text-transform: uppercase;
  padding: .16rem .5rem; border: 1px solid var(--line); border-radius: 99px;
  color: var(--muted); }
.tag.warn { color: var(--warn); border-color: currentColor; }
.tag.block { color: var(--block); border-color: currentColor; }
.impact { color: var(--accent); font-weight: 600; }
.scope code { font-size: .82rem; }
details { margin-top: .7rem; }
summary { cursor: pointer; color: var(--muted); font-size: .85rem; }
.evidence { margin: .6rem 0 0; padding: 0 0 0 .9rem; border-left: 2px solid var(--line);
  list-style: none; }
.evidence li { font-size: .84rem; color: var(--muted); margin: .35rem 0; }
.evidence code { color: var(--ink); }
.next { margin-top: 2.5rem; padding-top: 1.5rem; border-top: 1px solid var(--line);
  color: var(--muted); font-size: .9rem; }
.next code { background: var(--card); padding: .15rem .4rem; border-radius: 4px;
  border: 1px solid var(--line); }
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
  <p class="next">Next: <code>decisis bootstrap --write</code> writes these into
  <code>.decisions/</code>, <code>--pr</code> opens the pull request. Nothing is
  enforced until you merge it.</p>
</main></body></html>"""
