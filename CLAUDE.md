# Working on leela

## Talking to me
Succinct. No essays, no preamble, no recap of what I just said. Bullets and numbers over prose.

## Code style
fastai/fastcore house style, taken to the extreme:
- Dense. No blank-line padding, no section-banner comments, no ASCII rules.
- No explanatory prose in comments or docstrings. A docstring is one short line, or absent.
  Design rationale goes in `docs/`, not in the source.
- One-line bodies stay on the line: `if not x: return`.
- Short names. `L`, `Path`, comprehensions, `first`/`ifnone`/`store_attr`/`patch`/`delegates`.
- Never hand-roll what a dependency does. Reach for: `fastcore`, `ramabana` (the agent core),
  `vishalakshi` (vault/memory), `koshas` (code index), `litesearch` (ANN/peers/clusters),
  `fossick` (web search, CDP), `dhrishti` (inspection), `exhash`, `mdhtml`.
- `leela.agent` is an alias for `ramabana`, not a copy. Same for the other libs: thin seams only.
- Prefer consolidating small modules over adding new ones.
