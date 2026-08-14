# leela's part in the search and memory consolidation

Full roadmap: [`litesearch/docs/consolidation.md`](https://github.com/Karthik777/litesearch/blob/main/docs/consolidation.md).
Memory design: [`docs/superpowers/specs/2026-08-11-vishalakshi-memory-design.md`](superpowers/specs/2026-08-11-vishalakshi-memory-design.md).

## Search

`leela/blocks/search/search.py` is an adapter. Similarity, peers and corpus clusters live in
litesearch (`store.ann_neighbors`, `peers`, `clusters`) and, when the release carries them,
in kosha (`k.anchor`, `k.similar`, `k.peers`, `k.code_clusters`).

| was in `Search` | now |
|---|---|
| `_store`, `_rows`, `_cluster`, `MIN_CLUSTERABLE` | gone. litesearch owns the index plumbing and the kNN fallback |
| `_anchor`, `similar`, `peers`, `clusters` | thin wrappers that prefer kosha and otherwise call `code_st.*` |

Two things stay here: `_scan` and `symbols`, which read live buffers, and the
backend-selection policy that surfaces `backend` and `note` to the UI.

## Memory

`leela/blocks/memory/memory.py` wraps `vishalakshi.Vault`:

- a global `leela` shelf for agent notes and saved state
- a shelf per workspace for pages and research
- `context(..., shelves=0, code=0)`, so another project and kosha's code never leak in by default
- `python -m leela.migrate_memory`, which moves the old `leela_cfg/memory/web.db` into a vault shelf

Prose uses the vault encoder. Code stays in kosha, behind `Search`.
