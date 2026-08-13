# Clip to vault: a research workspace on the vishalakshi vault

Click a document, a codebase or an API spec into the workspace's vault shelf. Jobs carry the work,
watches keep it fresh, and `suggest_noisy` keeps it worth searching.

Scope is workstream 4 of four. Workstreams 1 (merge `cursor/primitives-consolidation-d665`) and 2
(library catch-up) are prerequisites, recorded below. Workstream 3 (the fastai leanness pass) runs
last, over the settled result, and is not specified here.

## Prerequisites

### 1. Merge the cursor branch

Cursor branched from `0f77fdc`, 66 commits behind. Its change is 31 files, +1203/-484:

- `Collapse Search and Memory onto kosha/litesearch/vishalakshi primitives` — the wiring that puts
  `memory.py` on `vishalakshi.Vault`. Leela declares `vishalakshi>=0.1.2` and imports it only in
  the migration CLI, so this commit is what first makes the dependency real at runtime.
- `Polish Cursor theme` / `Tighten Cursor chrome` — `lee-ide.css` +111, `lee-ide.js` +79.
- Adds `tests/blocks/`, `tools/shots.py`.

11 conflicted files, 38 hunks. `leela/web/` → `leela/` on this branch, so cursor's paths arrive by
rename detection; `blocks/memory/memory.py` auto-merges, `blocks/search/search.py` does not.

Resolutions:

- `leela/migrate_memory.py`, `tests/test_migrate_memory.py` (add/add, 9 + 8 hunks) — the two
  implementations are the same logic. Take cursor's structure: `memory_path` and
  `_registered_encoder` live in `memory.py`, not duplicated in the migration. Keep this branch's
  comment on the SQLite online backup — copying the single file returns a pre-checkpoint snapshot
  and resurrects deleted documents.
- `lee-ide.js` — `applyTheme` sets `style.colorScheme = theme`. Adding `'cursor'` to `THEMES` breaks
  it, because a theme name is not a valid `color-scheme` value. Map name → `color-scheme` instead.
- Remaining 7 files: ordinary resolution.

### 2. Library catch-up, including ramabana

| library | leela pins | actual | what leela gains |
|---|---|---|---|
| `vishalakshi` | `>=0.1.2` | 0.1.6 | `pii`, `quality`, `doc_marks`, `watch`/`poll`, `use_chat` |
| `fossick` | `>=0.1.8` | 0.1.11 | `search` RRF fusion, `research` `dropped`/`focus`, `pages=` |
| `ramabana` | `>=0.1.0` | 0.1.1 | `vault.VaultHost`, `spec.SpecHost` |
| `rishi` | test-only | 0.1.7 | reached through ramabana, not directly |

`fossick.rsearch` does not exist. The function is `research(q, n=5, pages=1, ...)` returning
`dict(query, sources, digest, dropped, region, curation, plan)`, each source carrying
`title, href, tier, date, queries, md`. `blocks/research/research.py` calls `f.search` and reads
only `digest` from research; it should surface `dropped` (with reasons) and `plan`.

ramabana is upgraded in the same pass rather than worked around. Its own floors are stale enough to
be wrong: `rishi>=0.1.1` against 0.1.7, `fossick>=0.1.0` against 0.1.11, and `vishalakshi>=0.0.1`
while `vault.py` calls `federate`, `web`, `ask(instruction=)` and `acquire.ACTIONS` — none of which
a 0.0.1 has. Raising them is part of the work.

Three ramabana changes come with it:

- **Shelf routing on `VaultHost`.** Fixed upstream so leela subclasses less. `VaultHost` currently
  names no shelf: `read_url` files `kind='web'`, `KIND_SHELF` has no `'web'` entry, so every write
  lands on the default `'store'`. Reads already fuse across shelves via `federate(shelves=True)`.
- **`fastspec` declared, and a host that reaches `SpecHost`.** `fastspec` is currently present only
  transitively via `ghapi` and `python-fastllm`, so `spec_ops`/`api_call` work by accident. Neither
  `cli.mk_host` nor `mcp.main` ever builds a `SpecHost`, and there are no tests. The API-spec clip
  below depends on this.
- **The `cursor` runtime.** Four gates in `ramabana/core.py`: `register_model` rejects the runtime
  it just inferred from the model id; `runtime_available` has no probe, and a `find_spec` check is
  the wrong shape because rishi probes with `cursor_bin`/`sdk_available` rather than an importable
  module; `resolve('cursor/grok-4.5')` returns `backend='remote'` and `RishiBackend._start` then
  builds a `RemoteChat` for a Cursor model, which is a silent wrong-backend bug rather than a
  missing feature; `MODELS` carries no cursor entries so the picker offers none. Two side effects
  once `backend == 'cursor'` exists: `ModelSpec.local` is `backend != 'remote'`, so a cursor spec
  reports local and reaches engine sharing in `RishiBackend.spawn` and `Agent.lend_model`, which a
  subprocess-backed CLI cannot satisfy; and `_runtime_kw` applies `tool_mode='tags'` only for
  `'remote'`, while Cursor requires the tag protocol. `leela/blocks/agent/models.py:11` mirrors the
  same `_RUNTIMES` tuple and has drifted out of step again.

### The provider socket is live

`Workspace.__init__` builds two subsystems through the registry — `workspace.py:166` for search,
`:169` for memory, importing `core.providers.build` as `build_provider`. So `LEELA_MEMORY` and
`LEELA_SEARCH` are read by `selected()` today; `LEELA_MEMORY=vishalakshi` raises
`ProviderError("unknown memory provider 'vishalakshi'; available: leela")`, which is the module's
documented "failure is loud" behaviour. The socket is wired and read, and nothing is plugged in.

Two defects in the same layer, both deferred to workstream 3 rather than fixed here:

- `@provider('runtime', DEFAULT)` registers but `build('runtime', …)` is never called, so
  `LEELA_RUNTIME` does nothing. Either wire it or drop the registration and the `ENV` entry.
- `conformance.CALLS` is a hand-maintained table of keyword names that must be updated by hand
  whenever a call site changes — the same failure mode as the drifted `_RUNTIMES` tuple. It does
  catch real signature breaks that `isinstance` would pass, so the decision is how to keep it
  honest, not simply whether to delete it.

## Architecture

Two new blocks, following `core/block.py`'s `Block` + `connect(app)` contract.

### `leela/blocks/vault/`

`LeelaVault(VaultHost)` — subclasses `ramabana.vault.VaultHost`, inheriting `memory_search`,
`memory_tree`, `memory_read`, `memory_topics`, `memory_forget`, `remember`, `read_url`, `research`,
`ask`, and `watch`/`watches`/`unwatch`/`poll`, plus the `memory` and `watch` capability
declarations that gate `memory_tools` and `watch_tools` in `ramabana/tools.py`.

Inherited unchanged: `VaultHost.ask` strips `pii` from kwargs, so a tool argument cannot route
retrieved private sections to a hosted model. Leela does not re-decide this and does not expose it
as a setting.

Shelf routing itself is fixed upstream in `VaultHost` (prerequisite 2), so the subclass carries
leela's policy — which shelf a workspace uses — rather than the mechanism.

### `LeelaVault` satisfies `MemoryPort`

`LeelaVault` registers as `@provider('memory', 'vishalakshi')`, so `LEELA_MEMORY=vishalakshi`
selects it and the two prose stores become comparable on equal terms. This is what the socket was
built for.

That requires the naming adapter `ports.py:34` predicts. `VaultHost` speaks `memory_search`,
`memory_read`, `memory_tree`, `memory_topics`, `memory_forget`; `MemoryPort` wants:

| `MemoryPort` | over `Vault` |
|---|---|
| `search(query, limit)` | `Vault.search` |
| `context(query, sections, related, max_read)` | `Vault.context` |
| `clusters(limit)` | `topic_tree` / `show_topics` |
| `toc(doc, depth)` | `memory_tree`, `_trim` at `depth` |
| `read(node_id, max_chars)` | `Vault.read` |
| `exact_text(doc_id)` | `Vault.document` |
| `remember(doc, query, force, extra_meta)` | `Vault.add` with `meta` |
| `remember_research(query, docs, digest)` | `Vault.add` per source + a digest note |
| `agent_notes` / `agent_states` / `agent_state_text` | the global `leela` shelf, filtered by `kind` |
| `remember_agent_note` / `remember_agent_state` | `Vault.note` on the `leela` shelf |
| `documents(limit)` | `Vault.sources` |
| `forget(doc_id)` | `Vault.forget` |
| `purge(ids)` | `forget` per id, or `drop_shelf` when unbounded |
| `status()` | `Vault.stats` |
| `note` (attribute) | vault path, or why it is not open |

The Protocol stays narrow. `shelf`, `watch`, `suggest_noisy`, `pii` and `set_meta` are not added to
it — they are called by the vault block's own routes, not by the shared surfaces, which is the split
`ports.py` argues for: a port names what the browser routes need, not everything the class can do.

`tests/test_providers.py` already asserts `conformance.check('memory', ws.memory) == []`; the same
check must pass with `LEELA_MEMORY=vishalakshi`.

```python
def safe_shelf(name):
    "A workspace name as a SQL identifier, with a stable fallback."
    return re.sub(r'[^a-z0-9_]+', '_', str(name or 'store').lower()).strip('_')[:64] or 'store'
```

Shelf names reach raw SQL, and leela's workspace names are folder names carrying hyphens and dots.
Sanitise once, at the boundary.

Two shelves, as the merged `memory.py` establishes: a global `leela` shelf for agent notes and
saved state, and a per-workspace shelf for clips, pages and research. Creation is lazy — opening a
shelf registers it in `vault_stores` and creates its tables. A module-level lock guards first open,
so two concurrent requests cannot both create the same FTS shadow tables.

Every document reference in the UI is the composite `f'{store}|{doc_id}'`. `doc_id` is
`hash_record(f'{source}|{title}')[:16]` and `docs` is per-shelf, so ids are unique within a shelf
and not across them. The existing memory UI passes bare ids and must change.

Judgements live in `doc_marks`, keyed `(doc_id, store)`, deliberately outside the per-shelf prefix
so re-ingesting a document cannot erase what you decided about it.

### `leela/blocks/jobs/`

One table, one state machine, no scheduler of its own.

```
jobs: id str pk, kind, target, params json, status, progress float,
      current str, result json, error, created_at, started_at, finished_at
```

`queued → running → complete | error`. `launch(jid, fn)` runs `fn` on a `fastcore.startthread`,
writing `status`/`progress`/`current` as it goes and `result` or `error` at the end. Long work
commits in batches and updates `progress` per batch, so partial results are queryable while the job
runs.

`params['_resume']` carries what a restart needs. On `connect()`, `recover_jobs()` re-queues
resumable jobs and fails the rest with an explicit "interrupted by a restart" message rather than
leaving them `running` forever.

Progress polling is client-driven and self-terminating: while `status in ('queued','running')` the
fragment carries `hx_get=/jobs/{jid}`, `hx_trigger='load delay:1200ms'`, `hx_swap='outerHTML'`. The
terminal render omits those attributes, so the loop stops by construction rather than by a
client-side guard.

Job kinds at ship: `clip`, `migrate_memory`, `tidy`, `poll`.

### Cadence

A recurring job is a `Vault.watch(target, action, every)` row — `every` parsed by
`vishalakshi.acquire.secs` (`'30m'`, `'6h'`, `'1d'`, `'1h30m'`), state in `next_run`/`last_status`.
A server-side interval tick calls `Vault.poll()` under a cross-process lock, so a second process or
a manual run cannot double-fire.

`acquire.ACTIONS` is extensible by appending and wrapping `run_watch`. Leela adds a `script` action
so a workspace can run a command on a cadence, which is what makes the job runner general rather
than clip-specific.

URL watches get `params.setdefault('force', True)`. Without it a mutable page reports
"already ingested" forever and never refreshes, because `doc_id` is content-addressed on
`source|title` and the source has not changed.

## Clip pipelines

A clip is a job. Its kind determines the pipeline, because the three things are not the same shape.

**Document** — an open editor tab, a file in the tree, a PDF, a notebook, or a page read in the
research modal. `vault.add_file` / `vault.add` into the workspace shelf, prose chunks, the normal
vishalakshi path. Meta records `clipped_from` (`tab|tree|research`), the workspace root, and the
original URL when the source was fetched. This replaces the research modal's `remember` checkbox
with a real destination.

**Codebase** — a repo root or folder. Not prose chunks. Kosha owns code, and vishalakshi already
knows it: `vishalakshi.code` has `kosha_indexed`/`code_sections`, and `Vault.context(code=…)`
federates code sections in. So: register the root with kosha (`blocks/search` already drives it),
then write one pointer document recording the index location plus a generated summary. Retrieval
federates instead of duplicating, so a clipped codebase tracks the index rather than aging into a
stale snapshot.

**API spec** — via `ramabana.spec`. `load_spec(src)` → `spec_ops(spec)` → one document per spec,
one section per operation built from `op_row(op)`:

```python
dict(group, name, verb, path, summary, signature, required, docs_url)
```

Already structured and signed by `fastcore.apisurface`. Storing per-operation sections keeps
endpoints individually retrievable and keeps `api_call` reachable from the same reference.
`MAX_OPS = 400` — beyond that a spec is a catalogue, not a working surface.

`load_spec` is JSON only: a URL, a path, or an already-parsed dict. There is no YAML path, so a
`.yaml` OpenAPI document fails at `json.loads`. The clip surface must say so, or convert.

## Tidying and PII

**Tidy** is a job kind. `suggest_noisy(k=20, min_score=1.0)` returns ranked rows with nine oriented
features (`hub`, `dup_out`, `off_centre`, `spread_chunk`, `spread_doc`, `low_idf`, `redundancy`,
`short`, `promiscuity`). The review surface shows the score and its breakdown; accept or reject
writes `noisy` to `doc_marks` via `mark_noisy_many`/`accept_noisy`. `fit_noise(save=True)` learns a
`Ranker` from accumulated judgements, and `use_noise` turns it on. `suggest_noisy` already excludes
documents judged for noise, so a reviewed document does not resurface.

This is what stops a clipped codebase's changelogs and licence files diluting retrieval.

**PII** is a badge, not a gate. `Vault.pii(ref)` on ingest stores the report; the badge shows
`kinds` and `density`, and `mark_not_pii` clears a false positive. `has_pii` is true only for
`IDENTIFYING` kinds, so an IP or a bare medical cue is reported without being called private.

The badge states its limits, because today `redact()` masks pattern kinds only and **names and
addresses are never masked**. Validators are real for the kinds it does cover — Luhn for cards,
mod-97 for IBAN, mod-11 for NHS.

That gap is closed in vishalakshi, in parallel, and leela tightens the badge when it releases. The
mechanism is already half there: `pii.py` is pure regex, but `extract.py` has `Vault.ner`,
`NER_CHARS` and the cue-scoring machinery. Wiring NER into the PII path needs three constraints:

- **Optional.** `pii_report` runs on every document at ingest with `MAX_SCAN = 200_000`; NER over
  that is far too slow to be unconditional. `ner=False` by default, `NER_CHARS` as the cap when on.
- **`IDENTIFYING` must not change meaning with a flag.** If `person` counts toward `has_pii` only
  when NER ran, the same document is private or not depending on an argument. The report carries
  `scanned_ner: bool` so a caller can never read "no names found" as "names not looked for".
- **Not on code.** A false `person` span over identifiers would over-redact source. Gate by `kind`.

Until then, leela's badge is honest rather than silent: it names the kinds it checked.

`ask(pii='local')` is not turned on. It refuses whenever the answering model's runtime is not
local, and leela routes to hosted models routinely; the refusal would read as a bug. The protection
that does apply is the inherited one: `pii` is not reachable as a tool argument.

## Data flow

```
clip request → job row (queued)
             → launch(fn) on a thread
             → pipeline by kind:
                 document  → vault.add_file → shelf
                 codebase  → kosha index + pointer doc → shelf
                 api spec  → load_spec → spec_ops → doc + sections → shelf
             → per-batch: progress, current, partial result
             → Vault.pii(ref) → meta badge
             → complete
                 ↓
UI fragment polls /jobs/{jid} at 1200ms until terminal, then stops

optional: watch(target, every) → interval tick → Vault.poll() under lock → re-clip with force=True
```

## Error handling

Every per-shelf and per-document optional step is individually guarded: one unreadable shelf or one
failed `categorize` must not fail a fan-out or an import. This is the rule chitragupta arrived at
and it holds here.

A job failure records `f'{type(e).__name__}: {str(e)[:800]}'` and stays visible with a retry that
reconstructs the target from `_resume`. A missing `fastspec` or an unloaded spec raises `SpecError`
with an actionable message, not a capability failure — `SpecHost` declares `api` and never probes
it, so the error must say what to do.

Restart is a first-class case, not an edge: `recover_jobs()` runs at `connect()`.

## Testing

Feature-flow blocks, not per-assertion units. The existing suite is 934 test functions averaging
9.7 lines, of which 451 are substring assertions against concatenated asset text. `tests/assets.py`
records the cost in its own docstring: `lee-ide.js` is one file of ~8,700 lines *because* ~200
assertions say so. New work does not add to that count.

Flows to cover:

1. **A document clips, appears in the shelf, and is retrievable.** Create workspace → clip a file →
   job reaches `complete` → the doc is in `sources()` for the right shelf → `search` finds it →
   `forget` removes it.
2. **A codebase clips as a pointer, not as prose.** Clip a repo → kosha index registered → exactly
   one pointer doc in the shelf → `context(code=…)` returns code sections → the shelf's `docs`
   count did not grow by the file count.
3. **A job survives a restart.** Launch a resumable clip → simulate restart → `recover_jobs`
   re-queues it → already-recorded paths are skipped → the result is not duplicated.
4. **A watch refreshes a changed page.** Watch a URL → change the content → `poll()` → the new
   version is filed rather than skipped as already-ingested.
5. **Tidy round-trips a judgement.** `suggest_noisy` proposes → accept → `doc_marks` holds it →
   retrieval excludes it → re-ingesting the document does not clear the mark → it does not
   resurface in `suggest_noisy`.
6. **A shelf name is sanitised and refs are composite.** A workspace named with dots and hyphens
   opens a valid shelf; two shelves holding the same source produce distinct `store|doc_id` refs.
7. **The provider swap is real.** `LEELA_MEMORY=vishalakshi` builds `LeelaVault`,
   `conformance.check('memory', ws.memory) == []` still passes, and the memory routes answer from
   the vault. An unknown provider name still raises `ProviderError` naming what is available.

Fixtures run offline (`VISHALAKSHI_OFFLINE=true`) so no test downloads a model. Per the known
baseline, TUI snapshots pass only in CI; do not `--snapshot-update` locally. Run via
`uv run --group test python -m pytest`.

## Out of scope

- Splitting `lee-ide.js`. Collapsing the 451 asset assertions unpins the architecture and makes the
  split possible later; the split itself is a separate job.
- NER-backed PII in vishalakshi. Designed above, runs in parallel in its own repo; leela ships an
  honest badge and tightens it on release.
- The dead `runtime` port and `conformance.CALLS`. Recorded above, decided in workstream 3.
- The leanness pass itself. Runs after this, as one sweep.
