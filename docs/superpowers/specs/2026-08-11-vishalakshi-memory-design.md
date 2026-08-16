# Vishalakshi memory design

Status: historical design record.

Use vishalakshi for prose memory and kosha for code search.

Stores:

- global `leela`: agent notes and state
- workspace shelf: pages and research

Requirements:

- section-level retrieval
- citations with source metadata
- explicit shelf selection
- offline operation
- migration from the prior web database

`MemoryPort` remains the Leela boundary. `python -m leela.migrate_memory` performs migration.
