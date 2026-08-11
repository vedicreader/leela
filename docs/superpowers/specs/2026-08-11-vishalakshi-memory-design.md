# Memory on a vishalakshi vault

Design for replacing leela's litesearch-backed `Memory` with a `vishalakshi.Vault`, partitioned by
a shelf per workspace, on the file ramabana will later share.

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
| partitioning | one shelf per workspace, named by `hub.workspace_slug()` |
| default | the Vault is the default; the litesearch `Memory` is deleted |
| encoder | `'retrieval'` (`potion-retrieval-32M`) — 0.487s load vs 1.220s, 0.4ms vs 1.0ms per query |
| migration | a separate one-off command, not implicit at startup |
| kosha | leela's `Search` block keeps sole ownership; the vault indexes no code |

## The adapter

`blocks/memory/vault.py`. It **wraps** a `Vault` rather than subclassing it, which is what resolves
the one real conflict: `MemoryPort.note` is a status string every leela surface reads, while
`Vault.note()` is a method that files a note. Wrapping keeps both.

```python
class VaultMemory:
    "MemoryPort over one shelf of a vishalakshi vault."
    def __init__(self, shelf='main', path=None, encoder='retrieval', offline=False):
        self.shelf_name, self.path, self.encoder, self.offline = shelf, path, encoder, offline
        self._v, self.note = None, 'vault not opened yet'

    def _open(self):
        "Deferred: opening a vault loads an encoder, and Workspace.__init__ must stay cheap."
        if self._v is None:
            from vishalakshi import Vault
            v = Vault(self.path, encoder=self.encoder, offline=self.offline)
            self._v = v.shelf(self.shelf_name)
            self.note = f'vault at {v.path} · shelf {self.shelf_name}'
        return self._v

    @property
    def vault(self):
        "The underlying shelf, for handing to ramabana's VaultHost."
        return self._open()
```

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
