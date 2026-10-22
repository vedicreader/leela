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
with every other module. `tools/build_ide_js.py` therefore owns the load order in `LAYERS`. It refuses to build when
`LAYERS` names an absent file, and when it misses a file that is present. `leela/static/js/` holds only
the shared vocabulary: `lee`, `$`, `esc`, dispatch, focus, overlays and boot. `core.web`'s
`IDE_BUNDLES` names what the page loads, in order.

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

`CAPS` limits the services `Ctx` exposes. It must name exactly what `app.py` and `ui.py` read as
`ctx.<name>`. Over-declaring grants reach nobody asked for, and under-declaring raises an
`AttributeError` on a route nobody exercised. Both faults stay silent until then, and
`test_core.py` compares the two lists. Session state that is not a capability, such as
`project_root`, comes through `ctx.session`. Never reach a capability that way, because it
bypasses the check.

A block's `.js` should call its own block's routes more than any other block's.
`tests/blocks/test_block_affinity.py` measures it, with an allowlist for DOM-only modules and
for a panel one block deliberately owns over another's data.

Common capabilities: `fs`, `pool`, `search`, `memory`, `research`, `runs`, `journal`, `jobs`, `vaults`, `ai`, `lsp`, `tab`, and `pending_approval`. A block without `CAPS` is unrestricted.

What the agent can reach is `WorkspaceHost.provides`, which is shalya's capability groups and nothing beside them. `docs/integration.md` is the map from a group to the block that backs it.

```python
from .blocks import BLOCKS
connect_all(app, workspace, BLOCKS, docs=docs, debug=debug, running=running, gate=gate, catalog=catalog)
```

`leela/blocks/__init__.py`'s `NAMES` fixes the wiring order. To add a block, make the folder and
name it there. `test_core.py` asserts `NAMES` and the folders on disk agree.

`core.session` holds what an application session owns and hands to blocks. `DocStore` holds open
documents as `ctx.docs`. `DebugState` holds whichever debugger has stopped, as `ctx.debug`.
`RunState` holds in-flight cells as `ctx.running`.

`blocks/agent` is the largest. `turns.py` builds one turn for the browser, `models.py` is the
picker's catalogue, `ai.py` the assistant, and `app.py` the 56 routes. `blocks/nb` owns the notebook
document and the routes that run and save it. `blocks/debug` owns both debuggers, the direct
debugpy session and the notebook one, over the single `DebugState`.

`gheasy` owns the gateway, the safepoint journal behind `undo`, the porcelain, and the git tools an agent gets inside a checkout. `blocks/git` is the browser surface over it, plus `blame_notebook` and `RepoSet`. The block sets `gateway().env_for` at import: a checkout's own virtualenv is leela's knowledge, not the harness's.
