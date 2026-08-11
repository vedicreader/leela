# Memory on a vishalakshi vault

Design for replacing leela's litesearch-backed `Memory` with a `vishalakshi.Vault`: a global
`leela` shelf for the agent's own notes and state, a shelf per workspace for project memory, on the
file ramabana will later share.

## Why

`MemoryPort` was extracted with this substitution in mind — `core/ports.py` already names
`vishalakshi.Vault` as the intended alternate. Two things make it worth doing now rather than
later.

The vault is **one corpus with several readers**. `ramabana.vault.VaultHost` already exists: a
`LocalHost` backed by a `Vault`, exposing `memory_search`, a `federate`-backed `search`, `research`
and `watch` as agent tools. Once leela opens the vault, the CLI agent and leela's agent stop being
two agents with two memories. That is the payoff, and it costs nothing extra here beyond choosing
the file.

And leela's own memory is **less good than what it would inherit**. `Workspace` passes
`kosha=self.search._kosha` so `Memory` reuses Kosha's resident embedder — which is code-trained.
leela embeds prose with a code encoder to save RAM, the mistake vishalakshi's own documentation
argues against in both directions.

## Decisions taken

| question | decision |
|---|---|
| vault file | `$VISHALAKSHI_VAULT`, else `~/.vishalakshi/vault.db` — the same file the CLI and MCP use |
| partitioning | a global `leela` shelf for agent notes and state; a shelf per workspace, named by `hub.workspace_slug()`, for project memory |
| default | the Vault is the default; the litesearch `Memory` is deleted |
| encoder | vishalakshi's default, `potion-multilingual-128M` — one encoder for prose, whatever the language |
| migration | a separate one-off command, not implicit at startup |
| kosha | leela's `Search` block keeps sole ownership; the vault indexes no code |

## The adapter

`blocks/memory/vault.py`. It **wraps** a `Vault` rather than subclassing it, which is what resolves
the one real conflict: `MemoryPort.note` is a status string every leela surface reads, while
`Vault.note()` is a method that files a note. Wrapping keeps both.

```python
GLOBAL = 'leela'          # the agent's own notes and state, whatever project is open

class VaultMemory:
    "MemoryPort over a vishalakshi vault: one store per project, one shared by all of them."
    def __init__(self, shelf=GLOBAL, path=None, encoder=None, offline=False):
        self.shelf_name, self.path, self.encoder, self.offline = shelf, path, encoder, offline
        self._stores, self.note = {}, 'vault not opened yet'

    def _store(self, name):
        """One store, opened directly rather than through the root vault.

        `Vault(path).shelf(name)` builds the root store on the way, and a vault whose main store
        was written by another encoder then warns about mixed distances -- for a store this is not
        touching. Opening `store=` reaches the same partition and never builds the root.
        """
        if name not in self._stores:
            from vishalakshi import Vault
            self._stores[name] = v = Vault(self.path, store=name, encoder=self.encoder,
                                           offline=self.offline)
            self.note = f'vault at {v.path} · {self.shelf_name}'
        return self._stores[name]

    def _open(self): return self._store(self.shelf_name)     # this workspace's project memory
    def _agent(self): return self._store(GLOBAL)             # notes and state, shared

    @property
    def vault(self):
        "The project store, for handing to ramabana's VaultHost."
        return self._open()
```

`agent_notes`, `agent_states` and their `remember_*` counterparts address `_agent()`; everything
else addresses `_open()`. A workspace whose slug *is* `leela` gets one store for both, which is
harmless — the `kind` filter already separates notes and state from project reading.

Laziness is not an optimisation. `Workspace.__init__` builds memory eagerly, and opening a vault
loads an encoder; leela's current `Memory` defers the same way with `_open()`.

### The port, method by method

Thirteen `MemoryPort` members are absent from `Vault` (measured with
`python -m leela.conformance`). None needs storage inventing:

| MemoryPort | Vault |
|---|---|
| `remember(doc, query, force, extra_meta)` | `add(text, title, source=url, kind=…, meta=…, force=…)` — identity is content-addressed over `source\|title`, so the repeat-URL no-op leela hand-rolls comes free |
| `remember_research(query, docs, digest)` | `add(digest, title, source='research://…', kind='research', meta={'query': …})` |
| `remember_agent_note(title, text, previous_id)` | `add(…, kind='agent-note', meta={'agent': {'parent': previous_id}})` |
| `remember_agent_state(title, text, meta)` | `add(…, kind='agent-state', meta={'agent': {'revision': n, 'parent_revision': …}})` |
| `agent_notes(limit)` / `agent_states(limit)` | `sources(kind='agent-note')` / `sources(kind='agent-state')` |
| `agent_state_text(doc_id)` / `exact_text(doc_id)` | `document(doc_id)` |
| `clusters(limit)` | `topic_tree()` |
| `documents(limit)` | `sources()` |
| `status()` | `stats()` |
| `purge(ids)` | `forget()` per id |
| `search` `context` `toc` `read` `forget` | native |

`kind` is the seam throughout. vishalakshi pushes a kind filter into the SQL rather than filtering
afterwards, so `agent-note` and `agent-state` are ordinary documents that the graph, the topics and
`context()` all see — which is what leela wants, since an agent's own notes should come back beside
the evidence they were drawn from.

### Two defaults leela pins rather than inherits

`Vault.context()` is a superset of `MemoryPort.context()`, and two of its defaults would change
behaviour silently:

- **`shelves=2`** appends sections from *other* shelves. The shelf is the workspace, so inheriting
  this leaks one project's notes into another project's agent context, invisibly. The adapter
  passes `shelves=0`.
- **`code=None`** appends code sections whenever kosha has indexed the repo. leela's `Search` block
  already owns that index and the agent already has `search_code`; inheriting this would give one
  index two owners and make the agent's context depend on whether `.kosha/code.db` happens to
  exist. The adapter passes `code=0`.

Both stay reachable deliberately. Cross-shelf recall is a good *explicit* action for the memory
panel — "search other projects" — just not an implicit default. This is the mechanism/policy line
`docs/blocks.md` already draws for `RuntimePort`: vishalakshi supplies mechanism, leela decides how
to use it.

### One encoder for prose, and code excepted

`potion-retrieval-32M` loads in 0.408s against 0.877s for the multilingual default, and is tuned
for search rather than similarity. It is also English-only, and this vault is meant to hold
Sanskrit alongside notes about kernels — so the default is the multilingual one, and the extra half
second is paid lazily, once per process.

The exception is code, deliberately. kosha embeds identifiers with a code-trained model because
code embeds badly under a prose encoder, and leela's `Search` block owns that index. The vault
never indexes code, which is what `code=0` above enforces.

## Registration and lifecycle

`blocks/memory/__init__.py` registers it as the port's default, beside the module that satisfies
it, exactly as the block contract requires:

```python
@provider('memory', DEFAULT)
def _vault(shelf=None, path=None, **kw): return VaultMemory(shelf or 'main', path)
```

`Workspace.__init__` passes the workspace slug. `hub.workspace_slug()` already names the
`*.localhost` host for a workspace, so the shelf and the URL agree — one project, one name, in both
places.

Requires `vishalakshi>=0.1.2`. Earlier releases rebuilt the encoder for every shelf (1.9s each,
measured) and did not carry `offline=True` into a new shelf; both were fixed upstream as part of
this work.

## Two things the migration settled

Written and run before the adapter, and both change how the adapter should open a vault.

**Open the store directly, not through the root.** `Vault(path).shelf(name)` instantiates the root
store on the way, so a vault whose main store was written by a different encoder warns about mixed
distances on every open — about a store leela is not touching. `Vault(path, store=name,
encoder=…)` reaches the same store and never builds the root. Verified warning-free under
`-W error::UserWarning`.

**A store's own encoder outranks the caller's preference.** The encoder is recorded per store, and
two in one store is exactly what that warning is about. The adapter reads the registry (cheap, no
Vault needed) and adopts what wrote the store, falling back to `retrieval` only when the store is
new.

**Agent notes and state are global, and live in the `leela` shelf.** The old memory was one file
for every workspace, and what was in it — three system prompts and a working state — is about how
leela works, not about any project. Per-workspace shelves hold project memory: what was read while
working on *this* repository. So the adapter opens two stores, not one, and `agent_notes`,
`agent_states` and their `remember_*` counterparts always address the global shelf.

## Migration

`python -m leela.migrate_memory`, following the `python -m leela.conformance` precedent rather than
adding a subcommand to leela's argparse CLI. Reports what it would move; `--apply` performs it.

It reads the old `leela_cfg/memory/web.db` directly and re-adds each document into the shelf,
preserving `title`, `source`, `kind` and `meta` — so `agent-state` revision chains and
`agent-note` parents survive rather than becoming a flat pile of notes. It skips documents whose
`source` is already present, so it is safe to run twice, and it never writes to the old file, which
is therefore its own backup.

## Tests

`tests/test_memory.py` is rewritten against `VaultMemory`. The fixture is what makes that
affordable:

```python
v = Vault(tmp/'vault.db', offline=True)     # 0.016s: hash encoder, no model load
shelf = v.shelf('test')                     # 0.003s since vishalakshi 0.1.2
```

against ~3.2s for the naive version. Session-scoped, and `conftest.py`'s config isolation already
keeps it out of `~/.vishalakshi`.

Retrieval assertions use the hash encoder, so they must be lexical rather than semantic — an
`offline` vault is FTS plus hashed n-grams, and a test asserting that a paraphrase ranks first
would be testing the encoder, not leela.

## What goes, and what does not

**Deleted:** `blocks/memory/memory.py` (282 lines) and the litesearch-specific tests.

**Unchanged:** `blocks/memory/app.py` and every `/memory/*` route. Only the object behind
`ctx.memory` changes, so `tests/routes.txt` stays byte-identical — the invariant every extraction
on this branch has held.

**Deliberately not built:** the ramabana handoff. `VaultMemory.vault` exposes the shelf so
`blocks/agent` can hand it to `ramabana.vault.VaultHost`, which already implements the memory,
federated-search, research and watch tools over exactly this object. That belongs in an agent-block
spec, not here.

## Out of scope

- `Research` → vishalakshi acquisition (`grab`, `crawl`, `harvest`). The larger deletion, and it
  needs leela's sandbox confinement preserved on top; its own spec.
- `SearchPort`. vishalakshi's code leg lacks `completion_patches`, `merge_completions`,
  `package_api`, `symbols`, `definitions`, `usages`, `peers` and `similar` — measured, 15 gaps. It
  is additive, not a substitution, whatever `docs/blocks.md` currently predicts.
- New capabilities: `ask`/`ask_doc` citations, `watch`/`poll`, `categorize`/`extract`, `federate`,
  `topic_tree` in the panel.
- CLI/leela conversation sharing beyond the vault: a shared `--cfg` default for ramabana, then
  session resume. Live shared sessions need the `ClientSession` daemon in
  `docs/multi-workspace-architecture.md`.
