# Working on leela

`AGENTS.md` carries the harness-neutral rules every agent reads, vendored from `AnswerDotAI/aai-coding`,
`prompts/core.md`. Leela's own additions sit below its `## Added here` heading. Drift is one command:

    curl -sS https://raw.githubusercontent.com/AnswerDotAI/aai-coding/main/prompts/core.md | diff - AGENTS.md

Re-fetch and re-append to take an upstream change. Never edit the vendored half. This file is what is
specific to Leela and Claude.

@AGENTS.md

## Talking to me
Succinct. No essays, no preamble, no recap of what I just said. Bullets and numbers over prose.

## Code style
fastai/fastcore house style, taken to the extreme:
- Dense. No blank-line padding, no section-banner comments, no ASCII rules.
- No explanatory prose in comments or docstrings. A comment must say what the code cannot;
  never restate the line below it. A docstring is one short line, or absent.
  Design rationale goes in `docs/`, not in the source.
- One-line bodies stay on the line: `if not x: return`.
- Short names. `L`, `Path`, comprehensions, `first`/`ifnone`/`store_attr`/`patch`/`delegates`.
- Never hand-roll what a dependency does. Reach for: `fastcore`, `ramabana` (the agent core),
  `shalya` (the toolset and the host), `gheasy` (git plumbing), `vishalakshi` (vault/memory),
  `koshas` (code index), `litesearch` (ANN/peers/clusters), `fossick` (web search, CDP),
  `dhrishti` (inspection), `exhash`, `mdhtml`.
- `leela.agent` is an alias for `ramabana`, not a copy. Same for the other libs: thin seams only.
- Tools and hosts come from `shalya`, git from `gheasy.repo`, imported by name. Not through
  `ramabana.tools` or `ramabana.git`, which re-export them for one release. `tools_for` is the
  exception and stays Ramabana's: it builds the image group from the turn's model.
- A host declares a capability group by inheriting the class that names it (`WebHost`, `CodeHost`,
  …), and declaring one means writing every method it asks for. There is no `capabilities` dict;
  `Host.provides` is the only way to ask what a host supports.
- Prefer consolidating small modules over adding new ones.

## Writing
The rules live in `ramabana`'s pyskills, not here. `read_skill` finds them. No copy belongs in this repo.
- `write_docs`: docstrings, comments, READMEs, changelogs, commit messages, PR descriptions, messages
  to a person. Voiceless GDS register. Read it before writing any of them.
- `write_prose`: anything with a voice on the page: `docs/`, announcements, release notes.
- `theory`: Naur's programming-as-theory-building. Read it when asked for the Theory of something.
- `coding_patterns`: the standards behind the Code style section above. Every Ramabana briefing
  already carries it inline.

Both writing skills ban the same things: em dashes, hedging, filler transitions, restatement, the
banned-word lists, hard-wrapped paragraphs. Bullets and numbers over prose still holds here.
