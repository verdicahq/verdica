# Examples

`meeting-note-template.md` — the shape a meeting note needs for extraction to
work well, with any notetaker or none. Two things matter:

- **the marker**: lines starting with `Deciso:` / `Decided:` / `Regola:` /
  `From now on` are ranked as explicit decisions above passing normative
  comments;
- **the why**: a decision without its rationale is unenforceable six months
  later — nobody can tell whether the constraint still holds.

Drop filled notes in a folder and run `verdica bootstrap --notes <folder>`,
or commit them under `meetings/` in the repo.
