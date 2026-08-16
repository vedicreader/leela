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
BLOCKS = [keys_block, settings_block, search_block, memory_block, vault_block]
connect_all(app, workspace, BLOCKS, gate=gate, catalog=catalog)
```

Keep wiring order in one place.
