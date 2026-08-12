# leela's part in the search and memory consolidation

Full roadmap: [`litesearch/docs/consolidation.md`](https://github.com/Karthik777/litesearch/blob/main/docs/consolidation.md).
Memory design: [`docs/superpowers/specs/2026-08-11-vishalakshi-memory-design.md`](../docs/superpowers/specs/2026-08-11-vishalakshi-memory-design.md) on the modular branch, summarised below.

## Search

`leela/search.py` is an adapter. Similarity, peers and corpus clusters live in litesearch
(`store.ann_neighbors` / `peers` / `clusters`) and, when the release carries them, kosha
(`k.anchor` / `k.similar` / `k.peers` / `k.code_clusters`).

| was in `Search` | now |
|---|---|
| `_store`, `_rows`, `_cluster`, `MIN_CLUSTERABLE` | gone — litesearch owns index plumbing and the kNN fallback |
| `_anchor` / `similar` / `peers` / `clusters` | thin wrappers that prefer kosha, else call `code_st.*` |

What stays here: `_scan` / `symbols` (live buffers), and the backend-selection policy that surfaces
`backend` / `note` to the UI.

## Memory

`leela/memory.py` wraps `vishalakshi.Vault`:

- global `leela` shelf — agent notes and saved state
- per-workspace shelf — pages and research
- `context(..., shelves=0, code=0)` so other projects and kosha code never leak in by default
- `python -m leela.migrate_memory` moves the old `leela_cfg/memory/web.db` into a vault shelf

Prose uses the vault encoder. Code stays in kosha via `Search`.
