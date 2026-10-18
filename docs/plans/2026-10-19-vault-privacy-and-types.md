# Vault privacy and types

Goal: the vault knows which documents are somebody's business and what kind of document each is, and it shows the user where every page goes before it goes. Extends `2026-10-19-vault-screens.md` (called "screens" below). It reuses that plan's Vault tab, Library, Find, Review and Sources views, the Read sheet, the document view, the review keys, `{ok: false, error, kind}` and its phases.

## Survey

Detection and marking:
- rahasya: text only. `pii_spans` returns `(start, end, kind, text)` (`rahasya/core.py:385`), `pii_report` sets `has_pii` from `IDENTIFYING` kinds (`:416`), `redact` writes `[KIND]` (`:433`), `redact_obj` (`:447`). Names need `ner=True` (`:403`). No page, block or image awareness. No stable id for a finding.
- vishalakshi marks: `doc_marks.pii_override` is `clear` or `force` (`core.py:430`, `pii.py:43-52`). `Vault.pii` scans on demand and applies the override (`pii.py:25-40`). Nothing is scanned or stored on ingest (`core.py:164`).
- vishalakshi gates: `gated` with `off|redact|refuse` on every `@gate` retrieval (`core.py:237-245`, `pii.py:124-146`). The default is `off`.
- vishalakshi ask: `ask_policy` picks `local` when a local runtime imports, else `redact` (`ask.py:203-208`). Private context goes to `pii_model_` under `PII_SP`, or is refused when the chat is not local (`ask.py:261-279`). Answers are scrubbed (`ask.py:180-189`). `explain` does the same (`ask.py:305-335`).
- vishalakshi extract: honours `pii=` (`extract.py:214-234`), but its local check uses `LOCAL_RUNTIMES` (`:232`), not `is_local` (`ask.py:40`), so a local Ollama is refused here and allowed in `ask`. `self.pii` runs without names (`:214`); `ask` runs with names.
- Leela: `ws.vault_pii` default `off` (`workspace.py:277`), one setting for all models (`app.py:748-754`, `agent/app.py:466-476`). The agent's `memory_*` tools pass it (`agent/ai.py:381-389`). Document tab shows the badge, evidence and the two overrides (`vault/reader.js:73-140`, `vault/app.py:191-239`). `pii_evidence` recomputes spans on every view (`memory/memory.py:433-449`). Clip shows a PII summary (`vault/clip.py:40-50`).

Where text leaves the machine without a check:
1. `@`-attached vault documents: `_vault_context` reads `shelf_text` ungated (`workspace.py:738-749`). The `vault_pii` setting does not apply.
2. Attached files and images: `_attachment_context` sends raw bytes (`workspace.py:752-790`). A vault document's source PDF or a scanned ID card attached by path skips every mark. This is how an attachment undoes a redaction.
3. Page reads: `read_page` sends the page image to `model` with no check (`read.py:107-116`), called by `read_doc` (`read.py:136-139`), `reparse` (`:202`) and `proofread` (`proof.py:69`). Screens phase 1 adds a cloud vision picker to the Read sheet, so a scanned passport would go to a hosted model by default.
4. Categorise: the model leg sends text to `dflt_model` with no check (`extract.py:75`). `extract` calls `categorize` with the caller's `model` before its own privacy routing (`extract.py:222`), so an undecided private document reaches a hosted model.
5. Agent file tools (shalya) read a vault source on disk with no mark check. `reach_refusal` (`agent/ai.py:434-442`) is the only model-aware gate, and it covers API specs only.
6. Web tools send the query as typed (`agent/ai.py:365-369`).
7. Screen capture (`alt+shift+p`) sends a vault document view as pixels.

Types and fields:
- varga: `guess_type` cue scores (`varga/core.py:233`), 28 doctypes (`:88-210`). None for identity documents, bank statements, payslips or tax returns. `structured` returns values without a source (`varga/schema.py:387`). `check_fields` returns `{field, value, why}` errors (`:322`).
- vishalakshi: `categorize` writes `doctype` or `doctype_proposed` into meta (`extract.py:87-90`). `proposed_types`, `accept_type`, `reject_type` (`:116-138`). `extract(save=True)` writes `extracted` with no page (`:240`).
- Leela: none of it surfaces. No route calls `categorize`, `extract` or `doctypes`.

Entry points audited: Tools menu and context menus (`menus.py:17-105`), unbound vault keys (`core/keys.py:123-126`), palette lists keymap labels only (`keys/palette.js:16`), settings toggles (`app.py:740-760`), model picker (`agent/panel.js:131`, `spec.local` via `model_local`, `agent/ai.py:1155`), prompt-bar attachment chips (`agent/steer.js:428-443`), vault access buttons (`vault/ui.py:279`, `/vault/access`). No new global shortcut is proposed.

## 1. Privacy model

- Three levels, one word each, shown as a chip everywhere a document appears:
  - **Open**: nothing found, or marked not personal. Any model reads it.
  - **Personal**: identifiers found or marked. Hosted models get it masked. Local models get it whole.
  - **Local only**: never leaves the machine, masked or not. Hosted models get "withheld".
- A document's level is its mark, else what detection found. A vault has a floor (`VaultRef.privacy`: `open`, `personal` or `local`), set beside access and agent on the vault row (`vault/ui.py:279`). A document can raise its level above the floor; only a person can lower it.
- Each model is labelled "on this Mac" or "hosted: provider" in every picker, from `spec.local`.
- A **send line** sits above every send button: Read sheet, proofread sheet, Find > Ask, prompt bar. Example: "claude-opus, hosted. 3 pages open, 2 personal pages masked, 1 local-only page withheld." It comes from one route (`/vault/send-check`), so all four surfaces say the same thing.
- `ws.vault_pii` becomes the hosted-model policy only ("when a hosted model reads Personal pages: mask or withhold"). A local turn model reads them whole. New default `redact`; a stored `off` is kept and shown as "as is (not recommended)". This changes default behaviour, so the owner decides it before phase P0.

## 2. PII in the vault

- **On ingest**: `add` and `_file_pages` run `pii_report(ner=True)` per page and store findings (fingerprint, kind, offsets, page, version, state), not the values. The values are already in the store. This replaces the per-view recompute in `pii_evidence`.
- **Model-read pages**: before a page image is sent, check the page's text layer or local OCR text. A page with no text in a Personal or Local-only document goes to a local vision model or not at all. After a read, the model's text is scanned and new findings are filed.
- **Review**: the screens Review tab gains a filter chip **Personal info** beside Proofreading. Rows show page, kind and a masked preview (`a••••@g•••.com`), with the page image. Same keys: `a` "is personal", `x` "not personal" (span-level), `A` on page, `u` undo, `j`/`k`. A document's override stays on the document view.
- **Redaction view**: the document view's text column gets a toggle **As sent** (vault-scope key `m`, free in the screens keymap). It shows exactly what a hosted model receives.
- **Guard**: one vishalakshi function, `send_check`, decides every send. It is called by ask, explain, extract, categorize, read_page, proofread and Leela's attachment path. A refusal returns `kind: pii_blocked`. "Allow once" is offered for Personal pages only and is recorded in the job or turn. Local-only has no override except changing the level or the model.

## 3. Types and fields (varga)

- Library gets a **Type** column. A proposed type shows dashed. The document view header shows the type chip.
- Proposed types join Review under a **Types** filter: `a` accept (`accept_type`), `x` reject, `e` pick another label.
- A **Fields** drawer in the document view lists each extracted field with its page and quote. Clicking a field opens that page with the block highlighted (crops once screens phase 6 ships boxes). `check_fields` errors show as a warning on the field. "Re-extract" is job kind `extract`.
- The screens Read sheet already does a fast text pass for its estimate. It also runs `guess_type` there and suggests:
  - invoice, receipt, quote, catalogue: preset `tables`
  - id_card, passport, bank_statement, payslip, tax_return, clinical_record: level Local only, model picker filtered to local vision models
  - paper, article: generic
- The mapping lives in vishalakshi as `TYPE_POLICY`, so the CLI and MCP agree with Leela.

## 4. The agent

- `memory_*` tools take the policy from the turn model: local reads whole, hosted reads through `ws.vault_pii`, and Local-only documents are always withheld for a hosted model.
- `memory_documents` and `memory_sections` rows carry `level` and `doctype`. One briefing line says what masks and withheld markers mean.
- `@`-attached vault documents go through the same gate as `memory_read`. An attached file or image whose path is a vault source (lookup by `source`, from screens) takes that document's level.
- `/agent/turn` runs `send_check` on attachments. A blocked one is answered with `kind: pii_blocked`; the chip turns red with the reason, and the turn is not sent.
- File tools: `WorkspaceHost` refuses reading a Local-only source for a hosted model, worded like `reach_refusal`. Seam ask to shalya: a `read_guard(path)` hook, if one is not already there.
- Web queries are scanned. If identifying kinds are present, the call is refused with the kinds named.
- The agent may mark a document personal or propose a type. It may never clear a mark or lower a level.

## 5. Upstream changes, in dependency order

1. **rahasya**
   - `block_spans(blocks) -> L[(block, start, end, kind, text)]`
   - `fingerprint(kind, text) -> str`, separator-insensitive
   - `redact(..., numbered=True)`: `[EMAIL_1]`, the same value always gets the same number
   - `mask_preview(text, kind)`
2. **varga**
   - Doctypes `id_card`, `passport`, `bank_statement`, `payslip`, `tax_return`, each with `sensitive=True`
   - `IdentityDoc` and `Statement` schemas
   - `structured(..., cite=True)` returns `{field: {value, quote}}`
   - `locate(fields, pages) -> {field: {page, block}}`, a local string match
3. **vishalakshi**
   - `pii_override` gains `local`; `Vault.level(ref)` and `set_level(ref, level, reason)`
   - Table `pii_findings(doc_id, store, page, version, fp, kind, start, end, state, at)`, filled on `add` and `_file_pages`; `findings`, `accept_pii`, `reject_pii`
   - `send_check(refs|pages|text, model, policy) -> {ok, send, masked, withheld, kinds, why}`, used by every model call listed in section 2
   - `read_doc`, `reparse`, `proofread`: `pii=` and `local_model=`
   - Fix `extract.py:222` and `extract.py:75` (categorize behind the guard), `extract.py:232` (`is_local`), and names on in `extract.py:214`
   - `extract(save=True)` stores `extracted_src`
   - `TYPE_POLICY`
   - Optional table `send_log(at, doc_id, pages, model, runtime, policy, kinds)`
4. **Leela**: bump the pins (vishalakshi pin `pyproject.toml:71`; add rahasya and varga floors).

## 6. Routes, responses, failures, tests, phases

Routes (in `vault/app.py`, added to `tests/routes.txt`):

| route | payload |
|---|---|
| `GET /vault/privacy` | `doc` → `{level, detected, override, kinds, findings}` |
| `POST /vault/privacy` | `doc, level, reason` → `{ok, privacy}`. Wraps `/vault/not-pii` and `/vault/pii/mark`, which stay as aliases |
| `POST /vault/access` | adds `privacy=` |
| `GET /vault/pii/findings` | `doc?, state?, page?` → `{findings}` (masked previews only) |
| `POST /vault/pii/findings/accept`, `/reject` | `doc, ids` → `{ok, privacy}` or `kind: stale` |
| `GET /vault/page` | screens route, adds `view=sent` |
| `POST /vault/send-check` | `refs, pages?, model` → `{ok, send, masked, withheld, kinds, why}` |
| `GET /vault/types` | `state=proposed` → `{types}` |
| `POST /vault/types/accept`, `/reject` | `doc, doctype?` |
| `GET /vault/fields` | `doc` → `{schema, fields, src, errors}` |
| `POST /vault/extract` | `doc, schema?, model` → job card |
| `POST /agent/turn` | may answer `kind: pii_blocked` with `{refs}` |

New kinds for the screens table:
- `pii_blocked`: the send line turns red and lists pages and kinds, with "use a local model", "mask" (Personal only) and "allow once" (Personal only).
- `local_only`: a hosted model was asked for a Local-only page. Same screen, no allow.
- `model_unavailable` with `local: true`: no local vision model. Offers OCR only, or installing one through models setup.

A job refused mid-read keeps the pages it read and stores `{kind, error, pages}` in `job.error`.

Fast tests (`tests/blocks/test_vault_block.py` fixture vault, `chat=` stub that records what it was sent):
- ingest stores findings without values; a re-read page gets new findings; a not-PII span survives a re-read (fingerprint)
- `send_check`: open, personal plus hosted masks, local-only plus hosted withholds, local model sends whole, local Ollama counts as local
- `read_doc` on a scanned image in a Local-only vault never calls the hosted stub; it calls the local stub, or the job ends `model_unavailable`
- proofread with a hosted reader on a Personal page is refused, or masked when allowed once
- `extract` on a private undecided document never reaches the hosted stub (the old `extract.py:222` leak)
- the `@` vault attachment is masked for a hosted turn model and whole for a local one; an image attachment whose path is a Local-only source gets `pii_blocked`
- web query with an email is refused
- the agent cannot clear a mark (`PermissionError`)
- `guess_type` on an invoice suggests `tables`; an id_card suggests Local only
- fields carry page and quote; a `check_fields` error is returned
- the parametrised screens test covers every new route for `ok` or `{ok: false, kind}`

Browser (`tests/test_web_slow.py`):
- Read sheet on a fixture ID scan shows Local only, a local-only picker and the send line
- Review > Personal info `a`/`x` changes counts
- `m` toggles As sent
- an `@`-attached Local-only document with a hosted model turns the chip red, and the turn is not sent
- a field click lands on its page

Phases, slotted into the screens phases:
- **P0, before screens 1.** Close leaks 1 to 4: gate `_vault_context`, guard `read_page` and `proofread` (vishalakshi), the extract fixes, the `vault_pii` default decision. Screens phase 1 must not ship a hosted vision picker without this.
- **P1, with screens 1.** Levels, vault floor, chips, `/vault/send-check` and the send line on the Read sheet. Type guess and preset suggestion in the estimate.
- **P2, with screens 3.** Findings table, Review > Personal info, As sent view.
- **P3, with screens 4.** Library Type column, Review > Types, send line on Find > Ask and the prompt bar, agent tool levels, attachment and file-tool guards, web query scan.
- **P4, after screens 5.** Fields drawer with provenance, `TYPE_POLICY`-driven presets, send log, crops with screens 6.

Before editing: an independent teacher review of this plan for missing cases, as `AGENTS.md` requires.
