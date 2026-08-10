# Collapsing `leela/web/` into the package root

Design for removing the `web/` subpackage, moving each domain module into the block that owns
it, and rewriting the block contract so a block holds its own domain logic.

## Why

`leela/web/` is not a layer. It holds one fat module (`app.py`, 2,466 lines, 88 routes), one
mount helper (`workspaces.py`), one browser launcher (`cdp.py`), and an asset folder. The
indirection it creates is real: `web/app.py` loads a block from `blocks/git/`, which loads the
actual git code from `leela/git.py` at the root. Three levels to reach one feature.

At the same time the package root carries 24 modules, most of which belong to exactly one
block. `git.py` is used by the git block. `settings.py` is used by the settings block.
Keeping them at the root means a feature is never in one place.

The end state is a root of five files, and a feature you can read by opening one folder.

## Decisions taken

| question | decision |
|---|---|
| how far domain modules move | into their blocks; rule 1 is relaxed to allow it |
| naming inside a block | keep the domain name — `blocks/git/git.py`, not `svc.py` |
| relation to the ongoing route extraction | collapse first as pure relocation, extract afterwards |
| asset layout | authored `static/` split from generated/vendored `vendor/` |
| esbuild inputs | top-level `frontend/`, out of the shipped package |
| modules whose block has no routes yet | pre-place as domain-only blocks |
| `cdp.py` | upstream `cdp_app` to fossick, delete the file |

## Target tree

```
leela/
  __init__.py        # errstr, Dictable, leela_cfg, __version__
  app.py             # <- web/app.py       (2,466 lines; shrinks as routes extract)
  cli.py
  hub.py             # <- web/workspaces.py
  workspace.py       # the composer over block domains

  static/            # authored: lee-ide.js, lee-ide.css, favicon.svg
  vendor/            # generated + vendored: lee-cm6.js, lee-term.js, lee-term.css,
                     #   htmx.min.js, fonts/

  core/              # imports no block
    block.py ctx.py ports.py providers.py session.py ui.py web.py conformance.py
    buttons.py diffs.py journal.py keys.py

  blocks/
    fs/       { fs.py  ui.py  app.py }
    git/      { git.py  app.py }
    search/   { search.py  app.py }
    memory/   { memory.py  app.py }
    research/ { research.py  app.py }
    runs/     { runs.py  app.py }
    term/     { term.py  app.py }
    settings/ { settings.py  app.py }
    lsp/      { lsp.py  app.py }
    keys/     { menus.py  app.py }
    runtime/  { kernels.py  devserver.py  support.py  app.py }
    tabs/     { ui.py  app.py }
    editor/   { app.py }
    vars/     { app.py }
    workspace/{ app.py }
    nb/       { nb.py }        # domain-only, not connected
    debug/    { debug.py }     # domain-only, not connected
    agent/    { agent.py runtime.py tools.py core.py testing.py ai.py models.py }

frontend/            # <- web/src: editor.js, term.js, package.json
```

### Module mapping

| today | after |
|---|---|
| `web/app.py` | `app.py` |
| `web/workspaces.py` | `hub.py` |
| `web/cdp.py` | deleted; `fossick.cdp.cdp_app` |
| `web/static/*` | `static/` (authored) + `vendor/` (generated, vendored, fonts) |
| `web/src/*` | `frontend/` |
| `buttons.py` `diffs.py` `journal.py` `keys.py` | `core/` |
| `fs.py` | `blocks/fs/fs.py` |
| `git.py` | `blocks/git/git.py` |
| `search.py` | `blocks/search/search.py` |
| `memory.py` | `blocks/memory/memory.py` |
| `research.py` | `blocks/research/research.py` |
| `runs.py` | `blocks/runs/runs.py` |
| `term.py` | `blocks/term/term.py` |
| `settings.py` | `blocks/settings/settings.py` |
| `lsp.py` | `blocks/lsp/lsp.py` |
| `menus.py` | `blocks/keys/menus.py` |
| `kernels.py` | `blocks/runtime/kernels.py` |
| `devserver.py` | `blocks/runtime/devserver.py` |
| `runtime_support.py` | `blocks/runtime/support.py` |
| `nb.py` | `blocks/nb/nb.py` |
| `debug.py` | `blocks/debug/debug.py` |
| `ai.py` | `blocks/agent/ai.py` |
| `model_store.py` | `blocks/agent/models.py` |
| `agent/{core,agent,runtime,tools,testing}.py` | `blocks/agent/` |
| `__init__.py` `cli.py` `workspace.py` | unchanged |

`keys.py` goes to `core/`, not `blocks/keys/`. The chain `core/ui.py` → `buttons.py` →
`keys.py` means a block-owned `keys.py` would make `core` import a block. Four things read the
keymap (`buttons`, `menus`, `core/ui`, the keys block), so it is shared vocabulary. Only
`menus.py`, which nothing but the keys block imports, moves into the block.

`workspace.py` stays outside `core/` for the same reason in reverse: it composes block domains,
and `core` imports no block.

## The block contract, rewritten

`docs/blocks.md` rule 1 today:

> Blocks import `leela.core`. `leela.core` imports no block. Blocks do not import each other.

After:

1. `leela.core` imports no block. Unchanged, and now the only hard directional rule.
2. A block may import another block's **domain module** — `from ..git import GitRepo`. It may
   never import another block's `app.py` or `ui.py`.
3. The domain-module import graph stays acyclic.

Rule 2 legalises two imports that already exist and would otherwise break the move:
`blocks/fs/ui.py` → `git.GitRepo`, and `blocks/agent/ai.py` → `fs.Unsafe`.

Enforced rather than documented, in `tests/test_blocks.py`: for each block, import its domain
module in a subprocess with a clean `sys.modules` and assert no `blocks.*.app` or
`blocks.*.ui` was pulled in; then build the domain import graph and assert it has no cycle.

### Providers move to the blocks that satisfy them

`core/providers.py:99-114` registers the three built-in providers with the implementation
imported inside each factory:

```python
@provider('search', DEFAULT)
def _leela_search(fs, **kw):
    from ..search import Search
    return Search(fs, **kw)
```

After the move those become `core` → `blocks`, which rule 1 still forbids. The fix is better
than a workaround: each block registers its own default beside its domain module.

```python
# blocks/memory/__init__.py
from .memory import Memory
from ...core import provider

@provider('memory', 'leela')
def _memory(kosha=None, path=None, **kw): return Memory(kosha=kosha, path=path, **kw)
```

`core/providers.py` then holds only the registry mechanism and names no implementation at all.
`LEELA_MEMORY=vishalakshi` swaps one folder for one package, and the built-in and the
alternate register through an identical path — the "compared on equal terms" property
`docs/integration.md` argues for, made structural.

Registration timing needs one deliberate hook. Registrations run at block import and
`Workspace.__init__` calls `build(...)`, so `blocks/__init__.py` eagerly imports the three
provider-owning blocks and `workspace.py` imports `leela.blocks`. Factory bodies stay lazy, so
naming a provider still constructs nothing.

## Serving two asset directories under one URL

`/leestatic` is one mount today, and `lee-ide.css` references `/leestatic/fonts/*.woff2`.
Starlette's `Mount` does not fall through when the inner `StaticFiles` returns 404, so two
mounts on one prefix cannot work, and rewriting 183KB of CSS is not a relocation.

`core/web.py` gains `static_dirs()` returning `[authored, vendored]` — each with the py2app and
py2exe frozen candidates that `static_dir()` already computes — `asset()` resolves the mtime
across both, and one shim picks the directory holding the file:

```python
class Assets:
    "Serve /leestatic from the authored dir first, then the vendored one."
    def __init__(self, *dirs):
        self.dirs = [Path(d) for d in dirs]
        self.apps = [StaticFiles(directory=str(d)) for d in self.dirs]
    async def __call__(self, scope, receive, send):
        rel = scope['path'].lstrip('/')
        for d, app in zip(self.dirs, self.apps):
            if (d/rel).is_file(): return await app(scope, receive, send)
        return await self.apps[0](scope, receive, send)   # let it produce the 404
```

Every URL, every `asset('lee-ide.js')` call site, and the CSS stay untouched.

`tests/assets.py` keeps a `VENDOR = {'lee-cm6.js', 'lee-term.js', 'htmx.min.js'}` filename set
so its `JS` corpus covers authored code only. `vendor/` expresses that as a directory, so the
set is deleted and `JS` becomes the tree under `static/`.

### Packaging bug fixed in passing

`packaging/macos/setup.py:17` and `packaging/windows/setup.py:15`:

```python
data_files=[('leela/web/static', [str(p) for p in STATIC.iterdir() if p.is_file()])]
```

`iterdir()` is not recursive and is filtered to files, so `fonts/` is skipped entirely — the
frozen desktop app ships no woff2 and silently falls back to a system monospace. Both lines are
being rewritten for the new paths, so they are fixed to recurse at the same time.

## cdp

fossick 0.1.7 is the latest release, matches the local checkout byte-for-byte, and contains no
app-window support: the `cdp_*` surface is `cdp_setup`, `cdp_connect`, `cdp_ws`, `cdp_cookies`,
and `--app` appears nowhere in the package.

- `cdp_ready` is redundant — `fossick.cdp._debug_ready(port)` is the same `/json/version`
  probe. It returns a bool where leela returns the metadata dict, and only
  `tests/test_web_workspaces.py:79` reads the dict. Deleted.
- `open_cdp_app` is upstreamed as `fossick.cdp.cdp_app(url, port=9223, user_data_dir=None,
  wait=15)`, released as fossick 0.1.8. `cdp_setup` cannot express it: it unconditionally
  starts a Chrome and waits on the endpoint, where the whole point is asking an
  already-running profile owner for an app window. The `/json/list` target poll that yields
  `reused` has no equivalent either, and `cli.py --app` and the workspace test both assert on
  it.

leela pins `fossick>=0.1.8` and deletes `web/cdp.py` with nothing replacing it.

## Blast radius

`tests/assets.py` absorbs most of it by design — it reads trees rather than files precisely so
modules can move without test edits, so ~200 assertions survive on 5 path-string updates.

| | |
|---|---|
| ~35 test imports | `from leela.web.app import X` → `from leela.app import X` |
| `test_web_workspaces.py` | `leela.web.cdp` → `fossick.cdp`; `leela.web.workspaces` → `leela.hub` |
| `test_editor_diagnostics.py:11-12` | `leela/web/src/{editor.js,package.json}` → `frontend/` |
| `test_web_usability.py:326` | `lee-cm6.js` size assertion → `vendor/` |
| `test_route_owners.py` | reported owning modules change |
| docs | `blocks.md` (rules 1 and 4, shape block, extraction table), `browser-workbench.md`, `multi-workspace-architecture.md` |
| other | `README.md:408,412`, `tools/webshots.py:19`, `cli.py:76`, `leela_app.py`, `setup_app.py`, `.gitignore:152-154`, `.github/workflows/desktop-artifacts.yml` |

## Invariants

1. **`tests/routes.txt` is byte-identical at every commit.** It has been through every
   extraction so far, and it is what proves no route moved or was shadowed.
2. **Every commit is behaviour-identical.** Nothing is rewritten, split or reconstructed — only
   moved. `docs/blocks.md` records that the two breakages during earlier extractions both came
   from reconstructing code from memory rather than moving it.
3. **The built wheel still contains the assets.** Hatchling's default file selection is what
   ships `web/static` today; `uv build` and an inspection of the wheel confirm `static/` and
   `vendor/` are included and `frontend/` is not.
4. Full suite green per step: `uv run --group test python -m pytest`.

## Commit sequence

| # | step | repo |
|---|---|---|
| 1 | add `cdp_app`, `nbdev-prepare`, release 0.1.8 | fossick |
| 2 | bump pin, delete `web/cdp.py`, rewire 2 call sites and 1 test | leela |
| 3 | `web/workspaces.py` → `hub.py` | leela |
| 4 | `web/app.py` → `app.py`, fix relative imports, delete `web/__init__.py` | leela |
| 5 | `web/static` → `static/` + `vendor/`, `web/src` → `frontend/`, `Assets`, packaging fix — **`leela/web/` is gone** | leela |
| 6 | `buttons.py` `diffs.py` `journal.py` `keys.py` → `core/` | leela |
| 7 | domain modules into their 12 existing blocks | leela |
| 8 | provider registrations → `blocks/{search,memory,agent}/__init__.py` | leela |
| 9 | pre-place `blocks/{nb,debug,agent}/` | leela |
| 10 | contract-enforcement test, `docs/blocks.md` rewrite | leela |

## Out of scope

- Extracting the remaining 88 routes from `app.py` (`nb`, `debug`, `agent`, `exec`, `run`,
  `history`, `diff`, `lint`, `markdown`, `screen`, the shell). They extract afterwards, into
  the final layout.
- Splitting `lee-ide.js` per block, which `docs/blocks.md` rule 4 anticipates. That is a
  rewrite, not a relocation, and it needs the routes extracted first.
- Any change to `core/ports.py` or the vishalakshi/ramabana protocols themselves.
