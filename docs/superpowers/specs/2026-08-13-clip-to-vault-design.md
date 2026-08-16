# Clip to vault design

Status: historical design record.

Clip files, folders, codebases, API specifications, and acquired web sources into vault shelves.

Requirements:

- resumable batch jobs
- visible progress and errors
- shelf and category assignment
- generated-path exclusion
- PII summaries
- document and section references

`clip`, `clip_tree`, `clip_codebase`, and `clip_api_spec` are job handlers. The workbench previews folder plans before indexing.
