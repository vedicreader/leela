# Blocks

```text
leela/blocks/git/
    __init__.py
    git.py
    ui.py
    app.py
    cwd.js
    panel.js
    branchbar.js
```

- domain modules avoid web imports
- `ui.py` supplies FastHTML fragments
- `app.py` registers routes
- `__init__.py` lazy-loads route code
- `*.js` is that block's client code, concatenated into a served bundle

A block's `.js` files are the browser half of the same feature. They share one lexical scope
with every other module, so `tools/build_ide_js.py` owns the load order in `LAYERS` and refuses
to build when a file is named but absent, or present but unnamed. `leela/static/js/` holds only
the shared vocabulary: `lee`, `$`, `esc`, dispatch, focus, overlays and boot. `core.web`'s
`IDE_BUNDLES` is what the page actually loads, in order.

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

A block that serves a page of its own rather than a panel in the IDE ships its own bundle from its
own route, and `build_ide_js.OWN_BUNDLE` names it. Its modules stay out of `LAYERS` deliberately:
the IDE's three bundles share one lexical scope, and a separate document does not want to be in it.
`canvas` is the one that does this today, serving `/canvas/js`.

`CAPS` limits services exposed through `Ctx`, and must name exactly what `app.py` and `ui.py`
read as `ctx.<name>`: over-declaring grants reach nobody asked for, under-declaring is an
`AttributeError` on a route nobody exercised, and both are silent until then. `test_core.py`
compares the two. Session state that is not a capability, like `project_root`, comes through
`ctx.session`; reaching a capability that way bypasses the check, so don't.

A block's `.js` should call its own block's routes more than any other block's.
`tests/blocks/test_block_affinity.py` measures it, with an allowlist for DOM-only modules and
for a panel one block deliberately owns over another's data.

Common capabilities: `fs`, `pool`, `search`, `memory`, `research`, `runs`, `journal`, `jobs`, `vaults`, `ai`, `lsp`, `tab`, and `pending_approval`. A block without `CAPS` is unrestricted.

What the agent can reach is `WorkspaceHost.provides`, which is shalya's capability groups and nothing beside them. `docs/integration.md` is the map from a group to the block that backs it.

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

`gheasy` owns the gateway, the safepoint journal behind `undo`, the porcelain, and the git tools an agent gets inside a checkout. `blocks/git` is the browser surface over it, plus `blame_notebook` and `RepoSet`. The block sets `gateway().env_for` at import: a checkout's own virtualenv is leela's knowledge, not the harness's.
