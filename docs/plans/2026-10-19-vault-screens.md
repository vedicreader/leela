# Vault screens

Goal: one calm place to add, read, find, check and fix documents. Built on vishalakshi 0.1.21 (`read_doc`, `pages`, `reparse`, `render`, `proofread`, `changes`, `accept`, `reject`, `proof_md`) and lekhaka `read_book`.

## Survey

Entry points today:
- Tools menu `open_vault`, `clip_to_vault`, `memory_notes`, `new_memory_note`: `blocks/keys/menus.py:105`. All unbound: `core/keys.py:123-126`.
- Context menus `file`, `folder`, `tab` carry `clip_to_vault`: `menus.py:17,22,45`. It opens the right-pane panel, not the workbench: `research/research.js:203-212`.
- Right pane, memory, `vault` view: `app.py:557` loads `/vault/panel` (`vault/ui.py:287-332`).
- Workbench tab `vaultwb` (browse, find, add, news, specs, topics): `vault/ui.py:28,341`, `reader.js:5-19`, `workspace.py:566`.
- Document tab `vault` (sections plus text, PII): `reader.js:94-145`, `workspace.py:558`.
- Research modal, vault mode: `research/research.js:48-62,120`.
- Agent: `@` mentions `/vault/mentions` (`agent/steer.js:518-529`), ask buttons (`reader.js:44-63`), tools `memory_*` and `ask` (`agent/ai.py:372-409`).
- Canvas refs `vault:` (`canvas/context.py:16`). The palette lists keymap labels only (`keys/palette.js:16`).
- Routes: 47 under `/vault/*` and `/jobs/*`, all in `vault/app.py:19-419`, listed in `tests/routes.txt:348-395`.

Reuse:
- Model picker `attachModelPicker` (`agent/panel.js:131`); routed jobs are `ramabana.core.JOBS` (`agent/app.py:511`). Rows carry `modalities`.
- Jobs: `report(progress, current)` and polled cards (`vault/jobs.py:43`, `ui.py:76`). No cancel.
- `diffHtml` (`nb/diffs.js:1`); git review's reviewed marks (`git/views.js:45`).
- PDF tab is an iframe (`editor/tabs.js:186`), not linked to the vault.
- `fail()` is `{ok: False, error}` (`core/web.py:50`), with no kind.

Problems:
1. Three vault surfaces (rail, workbench, research mode). Clip lands in the rail, Add in the workbench.
2. Clip uses `add_files` (`memory/memory.py:450`), so scans get no routes, flags or versions.
3. The document tab shows sections only.
4. Global search (`mod+shift+f`) skips the vault. Ask hands off to the agent.
5. No vault chord, palette entry or key scope (`core/keys.py:11`).
6. Jobs show no cost and cannot be cancelled. `read_doc` has no progress callback.
7. Pin is `vishalakshi>=0.1.17` (`pyproject.toml:71`). No lekhaka dependency.
8. No browser test covers a vault screen.

## 1. Home

- One tab, `vaultwb`, renamed **Vault**. Tabs: **Library** (browse plus Add drop zone), **Find** (search plus ask), **Review** (proofreading queue across documents), **Sources** (news, watches, specs, topics folded into one list).
- Header: vault picker, counts, a running-jobs strip (one line, expands).
- The right-pane `vault` view becomes a one-line link that says "open Vault". Attach, create, cadence and tidy move into Library > settings. `clip_to_vault` opens the Vault tab.
- Research vault mode keeps `/vault/browse` and gains an "open in Vault" link.
- PDF tab (`mountPdf`) gains "read into vault" when the file is not in the vault, and "open in vault" when it is (lookup by `source`).

## 2. Adding

- Drop zone on Library. A tree-row drag carries `data-path`. An OS drop: the native window passes a path; the browser uploads to `<vault>/inbox/`.
- `clip_to_vault` and the Add box (path or URL) open the same **Read** sheet:
  - parse: auto (default), text, OCR, model
  - preset: generic, sanskrit, tamil, tables (guessed from `flags` on a text pass)
  - model: `attachModelPicker`, filtered to image-capable models
  - hint, pages
- The last choice is remembered per folder in `ws.vault_read[folder]`. A sheet with that remembered choice opens with focus on Read, so Enter accepts it.
- The sheet estimates first: a fast text pass counts pages and flags, then shows "n pages, m need the model, about $x".
- Read starts job kind `read`. The card shows pages done, the route mix and the cost so far, with cancel.
- Cancel sets a flag that `report()` checks. The job raises `Cancelled` and keeps the pages read so far.
- URLs keep `detect` (`vault/acquire.py`). A URL that ends in PDF downloads to `inbox/` and then goes through Read.
- Seam asks:
  - vishalakshi: a `progress=` callback and a summed `cost` from `Vault.read_doc`.
  - vishalakshi: block bounding boxes, needed for crops in section 4.

## 3. Document view

- Replaces `mountVault`. Three columns: page strip, page image, page text.
- Page strip: thumbnails (`/vault/page/img?w=120`) with a route badge (text, ocr, scanned, model, proof) and flag dots. Filter by route or flag.
- Image and text are side by side. Text is shown as blocks, and the selected block is highlighted. Sections become a dropdown.
- History: a `v3` chip opens versions (`pages(history=True)`), shown with `diffHtml` between any two.
- Re-read the page or a range (`3-9`) with another model or preset. This is a job, and the new version appears when it is done.
- Pages are shown 1-based and passed 0-based, and one helper does the conversion.
- Keys (new `vault` scope, bare keys allowed like `files`):
  - `j`/`k` next/previous page; `[`/`]` next/previous flagged page
  - `r` re-read; `h` history; `p` proofread; `/` find in document; `a` ask about this page

## 4. Proofreading and review

- The proofread sheet chooses readers (two pickers by default, agree count 2) and pages, then starts job kind `proof`.
- Review queue, per document or across all: rows grouped by page, showing before → after, who proposed it, and a proposed or doubt state.
- Each row shows the page image beside it, scrolled to the word. A crop replaces this once the bounding-box seam ships.
- Keys:
  - `j`/`k` move between changes
  - `a` accept, `x` reject
  - `A` accept every proposed change on the page, `shift+A` accept every proposed change in the document
  - `d` show doubts only
  - `e` edit the after text before accepting
  - `u` undo the last decision, as a reject of a new version
- Export writes PROOFREAD.md (`proof_md`) next to the source, or downloads it.
- Stale changes (`accept` asserts on version): these rows are greyed with the label "page re-read since"; one button re-runs the proofreaders on that page.

## 5. Finding and asking

- Find takes one box and a scope chip: whole vault, this document, or pages n–m. It returns hits (`search_all`) and an **Ask** button, which streams `vault.ask` on the vault's ask model. Answers keep `cited()` markers.
- A citation opens the document view at that page with the block highlighted.
- "Send to agent" stays (`leeVaultAskAll`).
- Global search (`mod+shift+f`) gets a vault section, at most 5 rows. Opening one goes to the document view.
- Palette entries: Vault: open, find, review queue, read a file, proofread this document.

## 6. Books of verses

- In the Read sheet, the preset sanskrit or tamil offers "book of verses", which runs job kind `book` (`read_book(vault=)`).
- The result is stored in document meta as `book` (chapters, probs) through `set_meta`.
- The document view gains a **Chapters** tab: each chapter heading lists verse numbers. Clicking a verse jumps to its page.
- A problems list (missing or duplicate numbers, bad akṣaras, count mismatches) uses the same review keys. Each problem links to its page.
- Export: `book_md`.

## 7. Errors and recovery

Every route returns `{ok: true, ...}` or `{ok: false, error, kind, retry?}`, with `fail(e, code, kind=)` extended. Kinds:

| kind | when | screen |
|---|---|---|
| `model_unavailable` | no key, runtime not installed | sheet keeps the choices, "pick another model" plus link to models setup |
| `ocr_failed` | OCR engine missing or crashed | page badge `scanned`, offer re-read by model |
| `render_failed` | bad PDF page | placeholder image with the error, text still shown |
| `stale` | accept against an old version | rows greyed, re-proof button |
| `read_only` | 403 from `_writable` | write buttons disabled with the reason |
| `not_found` | doc or page gone | view says so, offers close |
| `cancelled` | job cancelled | card shows pages kept and resume |
| `busy` | job already running on this doc | card focused instead |

A job failure stores the same `{kind, error}` in `job.error`, so the card and the route agree.

## 8. Routes, modules, tests

Routes (all in `vault/app.py`; add to `tests/routes.txt`):

| route | payload |
|---|---|
| `POST /vault/read` | `src, parse, preset, model, hint, pages, vault, shelf, estimate=` → job card or `{pages, need_model, cost}` |
| `GET /vault/pages` | `doc, vault, history=` → `{pages:[{page, version, route, flags, model, at}]}` |
| `GET /vault/page/img` | `doc, page, w=` → PNG, cached by doc+page+w |
| `GET /vault/page` | `doc, page, version=` → `{text, blocks, route, flags, versions}` |
| `POST /vault/reparse` | `doc, pages, model, preset, hint` → job card |
| `POST /vault/proofread` | `doc, readers, pages, agree` → job card |
| `GET /vault/changes` | `doc?, state?, page?` → `{changes}` |
| `POST /vault/changes/accept`, `/reject` | `doc, ids` → `{accepted, pages}` or `kind: stale` |
| `GET /vault/proof.md` | `doc` → markdown |
| `POST /vault/book` | `src, preset, model, counts` → job card |
| `GET /vault/book` | `doc` → `{chapters, probs}` |
| `POST /vault/ask` | `q, doc?, pages?` → SSE answer with citations |
| `POST /jobs/{id}/cancel` | → card |

Changed:
- `/vault/workbench`, `/vault/view/{view}`: new views `library`, `review`, `sources`. The old names redirect.
- `/vault/panel` becomes the link.
- `/clip` with kind `clip` routes PDFs and images through the Read sheet.

JS: `vault/reader.js` is split into `vault/home.js` (tab, drop, sheet), `vault/doc.js` (document view, keys) and `vault/review.js` (queue). Bundle membership and the vendored `static/` bundle are updated.

Keys:
- `open_vault` gets `hyper+v` (free; `alt+shift+v` is `toggle_right`).
- New scope `vault` in `core/keys.py:11` and `keymap.js` `eventContext` (`.lee-vault-doc, .lee-vault-review`).
- `test_keys` duplicate check covers the new scope.

Tests (fast, `tests/blocks/test_vault_block.py` style, a fixture vault with a 3-page PDF and a `chat=` stub):
- read: estimate counts, job runs, per-folder choice remembered, cancel keeps pages, model missing → `model_unavailable`
- pages and history, image route returns PNG, bad page → `render_failed`
- reparse makes v2; accept after reparse → `stale`; accept/reject state changes; proof.md contents
- book stores chapters; ask returns citations with pages; global search includes vault rows
- every new route returns `ok` or `{ok: false, kind}` (one parametrised test)

Browser (`tests/test_web_slow.py` `_run`):
- clip from tree context menu → sheet → job card → document opens
- `j`/`k`/`[`/`]` move pages
- review `a`/`x`/`A` update counts
- citation click lands on page image
- `hyper+v` opens Vault

## 9. Phases

1. **Read it right.** Bump vishalakshi to 0.1.21. `/vault/read` with the sheet and remembered choice, `/vault/pages`, `/vault/page/img`, new document view (strip, image, text, `j`/`k`), `hyper+v`, `fail(kind=)`. Clip routes through it.
2. **Fix a page.** History with `diffHtml`, reparse a range, job cancel, cost on cards.
3. **Proofread.** Proofread sheet, Review tab, keys, stale handling, PROOFREAD.md.
4. **One home.** Library, Find, Review, Sources tabs; rail and research link in; scoped ask with citation jumps; global search rows; palette entries.
5. **Verses.** lekhaka dependency, book job, Chapters tab, problems list.
6. **Seams.** Crops once vishalakshi ships bounding boxes, and native progress once it ships `progress=`.

Before any editing: an independent teacher review of this plan for missing cases, as `AGENTS.md` requires.
