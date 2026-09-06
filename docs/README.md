# docs

Design rationale and reference, kept out of the source. The README is the product description; this is what a contributor reads before changing something.

## Using Leela

- [browser-workbench.md](browser-workbench.md): settings, notebooks, runtime and debugging, history, the language service.
- [desktop.md](desktop.md): the packaged application. Processes, browser lifecycle, folder selection, the macOS menu bar.
- [languages.md](languages.md): Rust and JavaScript notebooks, and what stays Python.
- [search.md](search.md): the code search dialog, its modes and its keys.
- [vault.md](vault.md): shelves, imports, feeds and the workbench.
- [canvas.md](canvas.md): the living document. Prose, code, embedded components and simulations in one markdown file, the dataflow between them, and the skill Leela pushes to the agent when one is open.

## Building on Leela

- [blocks.md](blocks.md): the block contract. `CAPS`, `connect(app, ctx)`, wiring order, and where a block's JavaScript goes.
- [integration.md](integration.md): the capability groups `WorkspaceHost` declares, and the block backing each one.
- [decisions.md](decisions.md): why a symbol has the shape it has. Read the entry before rewriting the symbol.
- [regressions.md](regressions.md): a fault the code still guards against, and the fix that holds it off. Read the entry before touching the guard.
- [performance.md](performance.md): a profiling pass over the server and the browser, with the numbers it was measured at.

## Not built yet

- [parallel-threads.md](parallel-threads.md): one worktree, branch and agent session per task. The shared-state git lock has to come first.
- [threads-to-ramabana.md](threads-to-ramabana.md): whether `Feed`, `Thread`, `Threads` and `TurnRunner` move to ramabana. Section 8 is three reasons not to do it as written.
- [consolidation.md](consolidation.md): the four kosha methods that would delete the fallback halves of `Search.similar`, `clusters`, `peers` and `_anchor`.
