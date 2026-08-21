# Blocks

```text
leela/blocks/git/
    __init__.py
    git.py
    ui.py
    app.py
    git.css
    git.js
```

- domain modules avoid web imports
- `ui.py` supplies FastHTML fragments
- `app.py` registers routes
- `__init__.py` lazy-loads route code

```python
from .._lazy import lazy_app
__all__ = ['connect', 'CAPS']
__getattr__ = lazy_app(globals())

CAPS = ('fs', 'jobs')
def connect(app, ctx):
    rt = app.route
    @rt('/git/info')
    def git_info(): return ui.info(ctx.fs)
```

`CAPS` limits services exposed through `Ctx`. Session state is available through `ctx.session`.

Common capabilities: `fs`, `pool`, `search`, `memory`, `research`, `runs`, `journal`, `jobs`, `vaults`, `ai`, `lsp`, `tab`, and `pending_approval`. A block without `CAPS` is unrestricted.

`leela/core/ports.py` defines `MemoryPort`, `SearchPort`, and `RuntimePort`. Owning blocks register default providers. Run `python -m leela.conformance <port> <name>` for alternates.

```python
from .blocks import BLOCKS
connect_all(app, workspace, BLOCKS, docs=docs, debug=debug, running=running, gate=gate, catalog=catalog)
```

Wiring order is `leela/blocks/__init__.py`'s `NAMES`, so a block is added by making the folder
and naming it there. `test_core.py` asserts `NAMES` and the folders on disk agree.

`core.session` holds what an application session owns and hands to blocks: `DocStore` for open
documents (`ctx.docs`), `DebugState` for whichever debugger is paused (`ctx.debug`), `RunState`
for in-flight cells (`ctx.running`).

`blocks/agent` is the largest: `turns.py` shapes one turn for the browser, `models.py` is the
picker's catalogue, `ai.py` the assistant, `app.py` the 56 routes. `blocks/nb` owns the notebook
document and the routes that run and save it. `blocks/debug` owns both debuggers, the direct
debugpy session and the notebook one, over the single `DebugState`.

`ramabana.git` owns the gateway, the safepoint journal behind `undo`, the porcelain, and the git tools an agent gets inside a checkout. `blocks/git` is the browser surface over it, plus `blame_notebook` and `RepoSet`. The block sets `gateway().env_for` at import: a checkout's own virtualenv is leela's knowledge, not the harness's.
