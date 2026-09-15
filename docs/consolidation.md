# Search and memory

Roadmap: [litesearch](https://github.com/Karthik777/litesearch/blob/main/docs/consolidation.md).

## Search

`blocks/search/search.py` adapts litesearch and kosha. The member-by-member table this file used to carry named four members that no longer exist (`_store`, `_rows`, `_cluster`, `MIN_CLUSTERABLE`), so it read as unstarted work that had already landed. What follows is the state as it is.

Done upstream. `Table.clusters` and `Table.peers` are litesearch's, in `litesearch/topics.py`, and `Search` reaches them through `k.code_st`.

Not done, and it runs the other way from a move. `Search.similar`, `clusters`, `peers` and `_anchor` each carry two branches: a `hasattr` probe for a Kosha convenience method, and a fallback that drives `code_st` itself.

| probe | `search.py` | what kosha would add |
|---|---|---|
| `k.anchor(path, line)` | `:526` | the store rowid covering a file position |
| `k.similar(path, line, graph=)` | `:550` | `ann_neighbors` off that anchor |
| `k.code_clusters(limit, min_count, max_count)` | `:569` | `code_st.clusters` with the code columns |
| `k.peers(path, line, graph=)` | `:590` | `code_st.peers` off that anchor |

None of the four exists in koshas 0.1.7, so every call takes the fallback. The work is four methods in kosha, after which Leela deletes the fallback halves, roughly sixty lines. Moving `Search` out of Leela is not the shape of it.

Staying in Leela whatever happens: `Hit` and `Cluster`, which are the browser's view model, and `backend`/`note`, which say which engine answered and whether an empty result means nothing matched or nothing could tell. Also `_scan` and `_rg`, and the Python module resolution (`env_roots`, `module_file`, `imported_module`, `import_package`, `env_definitions`).

## Memory

`blocks/memory/memory.py` wraps `vishalakshi.Vault`. `Memory` is not code vishalakshi is missing; it is a shelf-routing policy over a `Vault`, and nearly every method forwards to one.

- `leela` shelf: agent notes and state
- workspace shelf: pages and research
- `context(..., shelves=0, code=0)`: no cross-project or code results
- `python -m leela.migrate_memory`: migrate `leela_cfg/memory/web.db`

What is genuinely Leela's and stays: the two-shelf policy itself, `remember_agent_state`, `remember_agent_note`, `remember_research`, `_across`, and the PII gate wiring.

What is duplication rather than a candidate for moving: `blocks/vault/clip.py` defines its own `DOC_EXTS`, which litesearch already exports and vishalakshi already imports from there; and its `clip_*` job handlers re-implement against Leela's `Memory` what vishalakshi's `_job_ingest`, `_job_index_code` and `_job_connect` already do against a `Vault`.

Prose uses vishalakshi. Code uses kosha.
