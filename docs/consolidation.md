# Search and memory

Roadmap: [litesearch](https://github.com/Karthik777/litesearch/blob/main/docs/consolidation.md). Memory design: [vault design](superpowers/specs/2026-08-11-vishalakshi-memory-design.md).

`blocks/search/search.py` adapts litesearch and kosha.

| old `Search` members | replacement |
|---|---|
| `_store`, `_rows`, `_cluster`, `MIN_CLUSTERABLE` | litesearch |
| `_anchor`, `similar`, `peers`, `clusters` | kosha or `code_st.*` |

`_scan`, `symbols`, `backend`, and `note` remain in Leela.

`blocks/memory/memory.py` wraps `vishalakshi.Vault`.

- `leela` shelf: agent notes and state
- workspace shelf: pages and research
- `context(..., shelves=0, code=0)`: no cross-project or code results
- `python -m leela.migrate_memory`: migrate `leela_cfg/memory/web.db`

Prose uses vishalakshi. Code uses kosha.
