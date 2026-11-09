# Native Learn

## Upstream later

- Add a public group-registration hook in `shalya.tools` for contextual host toolsets.
- Add a public `set_meta` in Ramabana for conversation-owned host metadata.
- Add a public alias for `show._confuses` in Abhyasa.

Status: Claude approved S1 and the parallel S2 model-callback pilot. D2 is owner-confirmed. Later implementation follows the per-slice review protocol. The native branches start at Leela `02eb8133` and Abhyasa `e5292a1`. The hosting prototype remains unmerged.

## Product and ownership

The existing Leela agent pane creates and edits learning modules. Learn mode changes the tools and context of that same session. It preserves the backend, conversation and coding tools. Leela owns tabs, dock, settings, themes, keys, editor and kernels. Abhyasa owns learning state, source checks, assessment and learning tools. Its standalone app remains available outside Leela.

Replace the existing URL-handoff shell in `blocks/learn`. Do not add another shell beside it. Keep the notebook contract, due-review behavior, result filing and tool-environment jobs where they do not depend on the standalone server. Remove native dependencies on `serving.json`, Abhyasa page links, iframe panes and a second port.

## Decisions awaiting owner confirmation

| Decision | Proposed default | Open constraint |
| --- | --- | --- |
| D1 | Engine and learning tools in Abhyasa; native blocks in Leela; standalone app stays | Matches the accepted product boundary |
| D2 | A managed separate Learn vault file registered in Leela, using shelf `learning` | Owner confirmed. Existing data stays in place until explicit attach or backup-and-copy migration. No duplicate alias of the workspace file |
| D3 | Package-fed settings sections and shared speech now; model settings UI later | Leela model routing and privacy guards are mandatory from the first engine call |

Proposed D2 behavior: Learn uses the selected learning vault, initially the managed Learn entry. Resolve its identity and permissions when a tool starts and store that identity in job parameters. Changing the general vault picker does not redirect an in-flight write. Creating a managed entry does not silently enable agent writes. Require the existing user permission and agent-write authorization before mutation. An attached read-only vault returns `read_only`. Detach leaves files intact and prevents new operations. Running jobs retain their captured handle until they stop or finish.

Migration offers attach or backup followed by an explicit copy of the learning shelf and its assets. It never deletes the old vault, settings, `.sesskey` or `keys.env`. Test migration only on temporary copies. Do not open the person's real config or vault during development.

## Settings contract

`blocks/settings/settings.py` has a fixed `DEFAULT_SETTINGS` dictionary. Add a package-fed section registry before adding Learn controls. Use section key `learn`, never `learning`: Ramabana stores unrelated data under `learning` in the same user file. Preserve that data on reset. The schema must cover `_merge`, `_validated`, `_compact_legacy_snapshot`, `describe`, defaults, reset, enum and range validation, `_repo_safe`, `_user_only` and dialog rendering. Register sections at app setup and reject conflicting registrations. Audit the current dialog and settings routes before changing them. Do not embed Abhyasa's settings page.

Learn settings are user-only in the first slice. Repository and repository-language overrides cannot set prompts, model routing, credentials, source roots or learning behavior. Profile rows remain vault-owned. The focused registry test must fail before implementation, then pass for save, effective values, describe origins and reset. A full reset must preserve Ramabana's `learning` data. Test rejected workspace overrides at both top-level and language scope.

| Abhyasa setting group | Native destination |
| --- | --- |
| `look.theme`, `look.mode`, floating keys | Leela appearance and keys; drop duplicate controls |
| `voice.*`, `stt.*` | One shared speech section and microphone action |
| `models.*`, token limits | Existing Leela model routing; later model UI integration |
| Prompts | Advanced settings |
| Learning, checks, review, walks, talks, links, research, lists, guide | Learn section with the existing More distinction |
| Profile-backed learning rows | Selected learning vault, not global settings |
| OpenAI key | Leela Environment; no private key file fallback |
| `sources.roots` | Existing folder and vault controls |

Native engine calls must not read the old Abhyasa settings file. The worker found module-level settings reads in the engine. An injected settings provider is proposed upstream in the source notebooks. Verify its call sites before implementation. Standalone defaults must remain unchanged. Pass a per-call settings provider with the captured vault identity. Never use a mutable module-global settings cache. Test reset, validation, profile persistence and simultaneous calls using different learning stores and settings.

## Vault evidence and required pilot

Verified directly: `blocks/learn/app.py` uses `Learning(memory._store('learning'))`. `blocks/memory/vaults.py` deduplicates attached paths and refuses creation over an existing file.

Worker source finding, not yet independently tested: `Memory._store('learning')` and `Learning(vault).vault.shelf('learning')` select the same table prefix in the same database. The handles differ in connection and encoder setup. Before building on this claim, run a temporary-file pilot that writes through each path and reads through the other. Success means the same concept, attempt and walk are visible without duplicate tables. Also verify access permissions, detach and stale selections.

## First implementation slice

Implement the settings registry first. Then add Abhyasa-owned engine tools and the native Leela projection. Use source notebooks for engine changes. Do not edit generated engine Python.

Proposed tools are `learn_create`, `learn_state` and `learn_answer`. Final public names and registration must follow the existing shalya tool conventions. Do not keep a second list of group tools in Leela. Reuse the existing session refresh path after verifying its turn and approval locks.

| Entry point | Proposed call path | Result and recovery |
| --- | --- | --- |
| Agent Learn switch and palette Learn mode | Conversation-owned idle-only mode mutation; proposed `POST /learn/mode` | Atomic tool/context refresh or `thread_busy`; preserve history |
| Agent request or palette New module | `learn_create` -> `ctx.jobs` -> `path.walk_from_topic` with session-supplied model callback | Job card with progress and stop; structured walk id or failure |
| Native walk tab | Proposed `GET /learn/state` and native tab renderer | Selected vault, walk, step, source links and assessment state |
| View check or agent answer | Proposed `POST /learn/answer` and `learn_answer` -> one canonical assessment operation | Same attempt result and authoritative state on both surfaces |
| Notebook step | Existing `/learn/open` and notebook contract | Existing editor and kernel; structured refusal on invalid selection |
| Settings dialog | Existing settings endpoints extended by registry | Validated values; no separate Learn settings page |

Audit all current `/learn` routes before replacement: `/lesson/due`, `/learn`, `/learn/open`, `/learn/env`, `/learn/lookup`, `/learn/scratch`, and both methods of `/learn/tool`. Preserve external notebook handoff where it remains valid. Every route that changes the same state must return the same structured result.

Proposed result fields are `status`, `operation_id`, `vault`, `walk`, `step`, `revision`, `data` and `error`. Errors distinguish `vault_locked`, `vault_missing`, `read_only`, `source_missing`, `model_refused`, `cancelled`, `thread_busy` and `stale_state`. Do not report a completed mutation as a failed transport request. A retry returns the committed result rather than repeating grading.

Use stable attempt IDs across both answer surfaces. Abhyasa owns duplicate detection and authoritative post-operation state. Verify whether an existing version primitive is sufficient before adding a revision counter. Never infer correctness or gauge changes in Leela. Gauge means the engine's understanding and recall projection; it is not a new scoring algorithm.

## Session, result and job contracts

Store Learn mode in conversation metadata. Restore it with that conversation after restart. Browser tabs that share a conversation observe the same mode. Switching conversations restores each conversation's own selection. Repository branch changes do not reset conversation mode. Keep historical tool cards readable after mode off. Test provider resume with historical learning tool calls and no current learning tools.

Leela owns the mode endpoint and native presentation. Abhyasa owns learning operations. A required host capability primitive belongs in shalya, with its group membership owned there. Generic atomic session/tool refresh behavior belongs in Ramabana, not a Leela copy. Verify existing extension support before adding either upstream primitive. Hold the same lock as turn acceptance during mode mutation. Refuse queued messages, active turns and pending approval. Commit metadata and tool/context refresh together or retain the prior mode.

A successful create result carries the native tab descriptor with vault and walk identity. Leela handles it through its existing tab action path. A completed job updates its original conversation's card. Auto-open only when that conversation is still active, Learn is on and the requester remains present. Otherwise retain an explicit Open walk action without stealing focus. Mode off removes new learning dispatch but does not cancel an accepted job. The existing job card remains stoppable and readable.

Register job kinds during app setup. Verify `ctx.jobs` access from the tool host and its cooperative stop contract before implementation. Check stop between model calls and before mutation. Do not promise interruption inside a provider call unless the provider supports it. A committed result remains completed even if stop arrives afterward.

`operation_id` identifies a job or request. `attempt_id` is the client-supplied assessment idempotency key scoped to vault, walk and step. Repeating the same attempt returns its stored result. Reusing its ID for another answer returns `attempt_conflict`. An equivalent in-flight create returns the existing job rather than starting another. Read gauge state at turn start. An answer from the view can update state between turns; a tool using an old revision returns `stale_state`.

Also distinguish `privacy_refused`, `walk_missing`, `step_missing` and `mode_off`. Learner answers, vault passages and notes can leave the machine through model calls. Apply the session privacy checks before transmission. Native calls ignore Abhyasa-private model settings and key files. No research or worker path can bypass the session callback.

## Engine model-call audit

The entries below come from worker source research. Verify exact call bodies before implementing their wrappers. This is not yet a complete transitive audit.

| Operation | Reported engine path | Native wrapper and failure |
| --- | --- | --- |
| Topic module | `path.walk_from_topic`, `plan`, `_topic_walk` | `learn_create` job; model refusal, no source, cancellation |
| Source extraction | `journey_from_source`, `journey_from_text`, `journey_from_sources`, `sources.extract` | Later source-backed creation jobs; same routing and failure contract |
| Verbatim source selection | `sources.pick_passage`; pure `verbatim` validation | Included in the first creation slice for available source passages; show an exact linked quote or label the step ungrounded |
| Assessment | `Tutor.answer`, `_grade`, `_close` | `learn_answer`; canonical grading and one persisted attempt |
| Question and teaching | `ask_on`, `hint`, `_lesson`, `teach`, `_observe` | Later teaching tools; refusal and cancellation must preserve committed state |
| Research | `research_walk`, `gather`, `ramabana_lead`, `ramabana_worker` | Do not expose until audited for session-owned jobs; no private agent session |

Engine model calls are allowed inside the existing session's tools or jobs. They must use Leela's configured routing and privacy guards. They appear as tool or job cards with progress and stop. Long generation and research use `ctx.jobs`, not a blocked chat turn. A new user conversation or private agent session is prohibited. Verify the model callback and job stop APIs before implementing the bridge.

Confusion must not become a fabricated incorrect answer. The worker found `Tutor.answer(dont_know=True)` and `give_up`; verify whether those semantics match explicit learner confusion before using them. General confusion feedback and graded attempts remain distinct.

## Complete feature map

| Existing feature | Native destination |
| --- | --- |
| Today | Home Learn entry |
| Walk, session, course | Learn tab kind |
| Talk and slides | Leela presentation and slides; no Abhyasa stage shell |
| Guide | Existing notebook explanation action and same agent pane |
| Demo | Notebook cell output |
| Detour | Native split pane |
| Concepts, strengths, history, profile | Knowledge tab |
| Graph | Dockable graph tab using live Leela theme tokens |
| Search | Existing search dialog leg |
| Add | New module palette action and agent tool |
| Build page | Removed from native UI; same agent tools |
| Sources and vault | Leela vault library and document view |
| Jobs | `ctx.jobs` and existing progress cards |
| Keys | Leela keys panel; audit clashes before adding bindings |
| Settings and voice | Shared settings and speech path |
| Notebook lessons | Existing editor, lesson contract and kernel |

Audit tab persistence, dock, split and restoration contracts before adding kinds. Verify graph theme refresh rather than copying static colors. No new keyboard shortcut is proposed. The table is full product scope, not a claim that the first slice implements all features.

## Acceptance and tests

| ID | Contract |
| --- | --- |
| A1 | Ask for a module in the existing pane; an Abhyasa-created walk opens in a native tab |
| A2 | Sources are verbatim and linked, or explicitly labelled ungrounded |
| A3 | Confusion uses engine-owned feedback and adaptation; no invented incorrect answer |
| A4 | View and agent checks share grading; retries do not double-record; next turn sees the gauge |
| A5 | Mode off removes advertised and dispatchable tools and context; backend and history remain |
| A6 | Theme and setting changes update native surfaces |
| A7 | No iframe, bridge, second server, port or user chat; engine model calls follow the session rules |
| A8 | Structured failures, cancellation and retry preserve state and permit recovery |

The first end-to-end slice covers A1, A2, A4, A5 and A7. It does not waive A3, A6 or A8 for the product. Every mutation requires its relevant A8 failure checks from the first slice.

| Owner check | Required observation |
| --- | --- |
| 1 | Theme change restyles all learning surfaces without reload |
| 2 | No Abhyasa logo, navigation or second header |
| 3 | One settings dialog with Learn; no runtime old-config reads |
| 4 | One palette with New module, Open graph and Learn mode |
| 5 | Learning keys appear in Leela's keys panel without clashes |
| 6 | Module creation shows tool cards with approval and retry |
| 7 | Learn switch retains the same session id |
| 8 | One app port; no dependency on a running Abhyasa server |
| 9 | Learn storage appears in the vault picker; attach and detach work |
| 10 | Graph, walk and notebook tabs dock, split and restore |
| 11 | One microphone action and one speech setting |
| 12 | Lesson code runs in Leela's editor and kernel |

Focused tests must fail before behavior changes and pass afterward. Use `isolate()` before Leela imports and `temp_learning()` for engine tests. Test vault permissions, duplicate attempts, cancellation after commit, stale responses, session isolation, busy approvals and off-mode direct dispatch. Run browser checks serially in the test browser. Include a real-model smoke with isolated data before acceptance; mocked callbacks alone do not prove routing.

After focused tests and peer review, run each full suite once on the final code. Record counts and failures. Provide a running isolated preview and copied-vault Mac-window check for owner acceptance. Main pushes, tags and publication still need separate exact-command approval.

## Parity approach

Acceptance is parity. Each Abhyasa surface must look and behave at least as well as it does in Abhyasa, in Leela's theme. S1 to S5 prove the integration: one agent session, the Learn tools, the Learn settings, the creation job and a Leela tab. The walk tab from S3 is new markup over `walk_state`. It does not meet parity, and no new markup of that kind is written.

These facts were measured on 2026-11-09 in the `abhyasa-native-learn` worktree, with Abhyasa's own test fixtures and a temporary config.

| Fact | Value |
| --- | --- |
| Routes that `mk_app` registers | 210 |
| Paths that clash exactly with Leela | `/`, `/learn`, `/search`, `/settings` |
| First segments shared with Leela, besides those | `/keys` |
| Size of the step page in pane form (`/w/{jid}/1?pane=1`) | 11,278 bytes |
| Scripts and stylesheets that page loads | 12 and 12 |
| Local URLs in that page | 39 |
| Rules on bare elements in `core/base.css` | 41 |
| Theme variables in `core/themes.css` | 13 |

Abhyasa builds each page inside a block's `connect(app, ctx)` closure. The context holds `learning`, `tutor`, `ask`, `transcribe`, `speech`, `speaker`, `pool`, `sessions`, `sources` and `research`. `StepPage` takes the walk, its `walk_state`, the concept map, and parts from other blocks through the hooks `step_needs`, `walk_actions`, `model_chip`, `check_show`, `check_stuck` and `answer_tools`. Reuse therefore runs Abhyasa's routes. No pure render function exists for a surface.

`Page` in pane form (`pane=True` or `?pane=1`) has no nav, no crumbs and no gear. Its `<body>` sets `hx-boost="true"`. Its `<html>` sets `data-theme` and `data-mode` from Abhyasa's `look` settings. It loads its own htmx and `fasthtml.js` from `/vendor/`, and its block assets from `/assets/`. Its links go to `/w/{jid}/...`, `/v/store/...`, `/demo/ask`, `/keys`, `/settings/chip` and `/talk/new`.

`mk_app` calls `hooks.clear()` and resets `RouteOverrides`. A second build in one process replaces the hooks of the first. Building the app starts a speech model download of 9 files and three worker threads: `speech_0`, `research_0` and the app pool. A host must give Abhyasa Leela's one transcribe function, so no second model loads.

The proposed approach follows. It is not built, and it waits for the design audit and for agreement.

1. Leela builds Abhyasa's app once, in its own process, over the Learn vault. It passes Leela's model router as `ask` and Leela's transcribe function as `transcribe`. Leela mounts the app as its last route, so every Leela route matches first. No second server, port or iframe exists.
2. A Learn tab requests an Abhyasa page in pane form and puts the page's `<main>` into a container in the tab. The tab loads Abhyasa's stylesheets and scripts once.
3. Abhyasa's stylesheets apply inside the container only. The pilot chooses between a shadow root and stylesheets with every selector prefixed by the container class. htmx and `walk.js` in a shadow root are not tested.
4. The container sets Abhyasa's 13 theme variables from Leela tokens: `--bg` from `--lee-bg`, `--fg` from `--lee-fg`, `--line` and `--rule` from `--lee-border`, `--acc` from `--lee-accent`, `--mute` from `--lee-fg4`, `--ink2` from `--lee-fg2`, `--head` from `--lee-bg1`, `--bad` and `--no` from `--lee-log`, `--mono` from `--lee-mono`. `--ok` and `--serif` have no Leela token yet. Abhyasa's `look` setting does not apply in Leela.
5. Inside the container, a boosted link or form swaps the container, not the document, and does not push a browser URL. Links to the four clashing paths and to `/keys` open the Leela equivalent.
6. Leela's htmx 2.0.7 serves both. Abhyasa's own htmx copy does not load in Leela.

The first-surface proof is the real `StepPage` of a fixture walk in a Leela tab, themed by Leela tokens, with an answered check. It is shown beside a screenshot of the same step in Abhyasa. It is not done.

### Parity slices

These slices replace S3 and S6 to S8 in the table below. S1, S2, S4, S5 and S5V stay. Each reference screenshot comes from the design audit of the real Abhyasa. Local copies are in `target/parity-ref/`. The acceptance for every row is the same: the surface looks and behaves like its reference, in Leela's theme, with Abhyasa's tests for that block passing.

| Slice | Abhyasa surface | Abhyasa block | Reference | Status |
| --- | --- | --- | --- | --- |
| P0 | The host: the in-process app, the tab container, the token map and link handling | `abhyasa/app.py`, `core/ui.py` | `abhyasa-step0.png`, `abhyasa-step0-dark.png` | Done (host and real step page; verified 9 Nov by tests) |
| P1 | Walk step with its check, feedback, hints and next | `walk` | `abhyasa-step0.png`, `abhyasa-step0-answered.png`, `abhyasa-step1.png` | Not started |
| P2 | Walk page, plan and history | `walk` | `abhyasa-walk-overview.png`, `abhyasa-walks.png`, `abhyasa-walk-history.png` | Not started |
| P3 | Today | `today` | `abhyasa-today.png`, `abhyasa-today-dark.png` | Not started |
| P4 | Course and concepts | `course`, `concepts` | `abhyasa-concept.png`, `abhyasa-concept-seq.png` | Not started |
| P5 | Strengths, history and profile | `strengths`, `history`, `profile` | `abhyasa-you.png`, `abhyasa-profile.png` | Not started |
| P6 | Graph | `graph` | `abhyasa-graph.png`, `abhyasa-graph-dark.png` | Not started |
| P7 | Demo checks | `demo` | `abhyasa-step2-demo.png` | Not started |
| P8 | Talk and slides | `talk` | `abhyasa-talk.png`, `abhyasa-talks.png` | Not started |
| P9 | Search, library and sources, with research gather as a job of the Leela session | `search`, `add`, `sources` | `abhyasa-search.png`, `abhyasa-library.png`, `abhyasa-sources.png`, `abhyasa-gather.png` | Not started |
| P10 | Builder: create and change a module from the Leela agent pane | `build` | `abhyasa-build.png` | Not started |
| P11 | Voice through Leela's one speech path | `voice` | none | Built, tests pass; real microphone and real model download not verified |
| P12 | Removal of the S3 walk tab markup and the old handoff pane | Leela `blocks/learn` | none | Done: a walk is the Learn tab at `/w/<jid>/<step>`; the walk markup, its HTML and JSON routes and the `learn_walk` tab kind are gone; saved `learn_walk` tabs restore as the Learn tab |
| P13 | Guide: "I don't get this" and "Ask about what you see" through the Leela agent | `guide` | `abhyasa-guide.png` | Not started |

## Delivery slices

Files below define scope, not claims that new files already exist. Resolve exact extension symbols before editing. Use only the two native worktrees. Commit locally and do not push or release during slices.

| Slice | Files and behavior | Targeted proof | Owner demo |
| --- | --- | --- | --- |
| S1 | `blocks/settings/settings.py`, settings dialog and Learn section registration | Registry round-trip, reset preservation, workspace trust, browser rendering | Open Settings, then Learn |
| S2 | Abhyasa engine source notebooks and pilot test; later Leela agent/job adapter | One `walk_from_topic` call through session routing and privacy guards in a cancellable job | Ask for a module and inspect its job card |
| S3 | `blocks/learn` native FT rendering, `tabs/app.py`, tab persistence | Native state response, quotes, ungrounded state, tab restore | Open the created walk and its source |
| S4 | Existing agent controls, conversation metadata and tool refresh | Same session, idle lock, approval/queue refusal, resume and mode-off dispatch | Toggle Learn without losing the conversation |
| S5 | Abhyasa assessment source notebook and native check/gauge view | Canonical grading, attempt retry/conflict, next-turn state | Answer in the view or pane and see updated understanding |
| S5V | The managed Learn vault entry in Leela's vault list and the first-run import | Populated, empty, already-attached, read-only and failed-copy cases on temporary files | Open Learn on a copied vault, then attach or back up and copy |
| S6 | Shared speech action and Abhyasa transcription seam | Permission, stop/error and isolated transcription checks | Dictate through one microphone action |
| S7 | Knowledge and graph blocks, tab/dock integration | Live theme refresh and tab restore | Open Knowledge and dock the graph |
| S8 | Slides/search integration and old handoff removal | Feature parity and route audit | Present a talk and search sources |

S5V comes before the owner is asked to try Learn on real data. Run targeted tests per slice. Run both full suites once after S5 for the first product milestone, not after each slice. Later S6-S8 changes require their own final affected-suite verification before release. Send Claude one completion message per slice with commit IDs, exact isolated demo commands, URL if running, UI screenshot path, test counts and known gaps. Start independent next work while review proceeds.

## Native walk tab

Use Leela's existing FT page and control conventions. Render step text in the existing markdown content component, a quote in `Blockquote` with an `A` source link, a check in `Form` with the existing input/button styles, and understanding in a compact status strip. Confirm exact component imports during S3 rather than copying Abhyasa's page renderer. Use only `--lee-*` colors and existing fonts.

`GET /learn/state` supplies `vault`, `walk`, `step`, `revision`, step content, source quote/link or `ungrounded`, check specification, engine understanding/recall and previous/next step IDs. Next/back controls request those IDs without changing the agent conversation. Empty state offers New module. Loading preserves current content and shows busy status. Error state retains selection and offers the permitted retry. Controls follow normal tab order and keep visible focus. No new shortcut is added. Persist only vault/walk/step identity in the tab descriptor; restore fresh engine state after restart and show a missing-vault or missing-walk message rather than stale content.

S4 audits the current agent control row before adding Learn beside the existing mode controls. Its states are Off, On and Busy. Busy disables mutation and explains the active turn, queue or approval. The palette invokes the same endpoint. Do not create another pane.

## First-run learning import

On first Learn open, inspect the configured existing learning shelf through the vault registry in the running product. Development tests use temporary copies only. If existing data is found, show Attach and Back up and copy before presenting an empty managed vault. Attach selects the existing registry entry when the path is already registered; it does not create an alias. Copy creates the managed Learn destination after a backup and preserves source files and assets. Existing data remains accessible if copy fails. Explicit Skip starts empty; never choose it silently. Test populated, empty, already-attached, read-only and failed-copy cases on temporary files. S2-S5 use explicit isolated fixture vaults until this first-run UI is complete in S5V.

## Known gaps

These hold at Leela `49d4adea` and Abhyasa `1879564`.

| Gap | Effect | Closed by |
| --- | --- | --- |
| In the hosted app, `show.vision_ask` sends no picture (Abhyasa `2008ebc`). | Figure labels and screen pictures do not reach the model. The page must say so in words where the person meets it. | Pictures through Leela's `Assistant.oneshot`, if it takes images; else a stated limit. |
| In the hosted app, research gather takes the plain routed search, not its lead agent (Abhyasa `2008ebc`). | Research finds fewer and shallower sources. The page must say why, and never show a silent empty result. | P9: gather as a job of the Leela session that uses the Leela agent. |
| The hosted app leaves out the `build` and `guide` blocks, because each runs its own agent. | No builder chat and no guide board in the tab. | P10 and P13 |
| The isolated preview does not name its vault. | The owner cannot see which vault a demo writes to. | The preview launcher prints and shows the vault name and path. |
| No presence signal for the person who started a job exists. | The walk tab auto-opens on the active conversation with Learn on, without a presence check. | A later presence signal; the Open walk action in the job card covers the rest. |
| No engine call reads the Learn settings outside the three tools that take `settings=`. | Other Learn settings rows have no effect yet. | Each later slice that adds an engine call. |

Closed since the last revision, each proven by a passing targeted suite on 9 Nov:

- The Learn vault is a managed registry entry and the first-run import (attach, back up and copy, skip, read-only, failed copy) runs at `GET /learn/import` (`tests/test_learn_vault.py`, `tests/blocks/test_vault_*.py`). This closes the `learn_store(ws)` gap.
- Host defects in Abhyasa: background pools keep the calling context (`e4c8cb6`), `LocalOnly` takes dotted hosts (`1879564`), the host owns the session cookie, the privacy guard and the settings rows, a withheld check is told to the learner, and an answer to an old walk revision is refused (`2008ebc`, `8fb2b9e`, `8f104f5`, `d83cf64`). The full Abhyasa suite passes (1260 passed, 24 skipped).
- The walk answer route takes a JSON answer with a kept attempt id (`53189f36`, `05d1b17c`; `tests/test_learn_abh_tab.py`).

## Release pins

`HOST_API` in `abhyasa/core/hostapi.py` is the host contract number, and `HOST_API_NEEDED` in `leela/blocks/learn/tools.py` is what Leela needs. `contract_missing()` returns one line when Abhyasa has no `HOST_API` or a lower one: `Abhyasa too old: needs host API N, has M` (`has none` for no number). Learn mode, the Learn button, `/learn/abh/open` (503) and the log carry that line. Raise both numbers together whenever `host.py` starts to use a new Abhyasa name or signature.

After the Abhyasa release that first contains `HOST_API`, change these lines in Leela:

1. `pyproject.toml`: `"abhyasa>=0.0.16"` becomes `"abhyasa>=<new version>"`.
2. Run `uv lock --refresh-package abhyasa`.
3. Check that `uv.lock` has no `path` or `editable` source for `abhyasa`, and that its version is the new one.
4. In `tests/test_learn_contract_names.py`, set `FIRST_HOST_API_RELEASE` to the new version and remove the `xfail` mark.
5. Check that the pinned release has `HOST_API >= HOST_API_NEEDED` (the pin guarantees host API 1).

Do not change the pin to a version that is not on PyPI.

## Retirement and release

S1 and S2 delete no handoff routes. S3 replaces `/learn` page rendering and the old `pane.js` page embedding with native tabs while retaining valid notebook-open contracts. S4 replaces mode-related navigation with the shared agent switch. S5 uses native answer/state paths. S6 removes any remaining external speech dependence. S7 replaces graph/library navigation. S8 removes `serving.json` lookup, standalone URL helpers and the `pane=1` shell guard after auditing callers. Retain `/lesson/due`, `/learn/open`, `/learn/env`, `/learn/lookup`, `/learn/scratch` and `/learn/tool` only where they still implement native notebook contracts. Update route inventory and remove dead callers rather than retaining compatibility with the rejected shell.

S1-S5 require Abhyasa settings-provider injection, learning tool operations and attempt-id support. Edit source notebooks and run `nbdev-prepare`. Develop Leela against a non-editable local path source. After the milestone gates, prepare one Abhyasa release containing those engine changes, then pin Leela to its released version and remove the path source. No early publication bypasses owner acceptance or separate push/tag/PyPI approval. Abhyasa releases before Leela.

For the real-model pilot use an already configured local model through Leela routing, or ask the owner to supply a credential specifically to the isolated check. Do not read real key files or copy them into the preview. Without either option report the real-model smoke blocked, not passed. A deterministic callback test is useful but does not establish live routing or privacy behavior.

## Review status

The expanded teacher review completed and requested corrections. This draft incorporates its settings trust, mode lifecycle, tab delivery, job and idempotency requirements. The reset collision was independently verified in `Settings.reset`. The reported A2 contradiction is resolved explicitly by including passage selection in the first slice; multi-source creation remains later. Claude approved the settings slice and parallel model-callback pilot. D2 is owner-confirmed. The model callback bridge, job cancellation, settings injection and canonical assessment persistence need bounded source checks or pilots before their implementation steps. Approval of the independent settings-registry step need not wait for D2. Do not expand research into another full repository survey.

## Agent-pane builder and page context

The agent pane builds and changes a walk through the one Leela session. Abhyasa owns the logic (`agent_tools`), and Leela owns routing and privacy: each model call goes through `learn_ask` with a task name.

- `change_walk` is a `learn_change` job, as `create_walk` is a `learn_walk` job: cancellable, task `plan`, run by the job runner outside the turn. A stop, a refusal or a walk that changed during the model calls leaves the walk as it was. One change has one Undo.
- `keep_idea`, `drop_idea`, `move_idea`, `add_source`, `list_versions` and `restore_version` call no model. Each change is one entry in the history of the walk, which the tab shows as Earlier versions. Writers need approval; `list_versions` and `walk_state` are in `READS`.
- `explain_here(note)` makes no model call: a nested call inside a turn waits for the lock that the turn holds. Leela gives it the walk and step on screen (the active Learn tab's saved page, `Tab.page`, read by `page_of`). It keeps the confusion and returns the statement, the verbatim quote or `ungrounded`, the gauge, the level line and the rules, and the one agent session writes the explanation. `change_walk` and `add_source` do not nest: `change_walk` is a `learn_change` job on its own thread, and `add_source` calls no model.
- `learn_context` puts the page on screen first, so "I don't get this" is about the step the learner sees: its quote or `ungrounded`, and its gauge. A graph, library, talk or concept page is named in one line.
- The skill text stays under its cap: four wordy feature sentences were cut to pay for the new tool names.

UI still to build: a button in the Learn tab, and a chord, that sends "I don't get this" to the agent pane (the guide board of the standalone app); the tab must reload its page after a `learn_change` job ends or a hand change.

## Modes

A mode is a named workspace preset. `code` is the base mode. `learn` registers itself when the Learn block connects. A new mode is one `register_mode(Mode(...))` call.

Built (Python side):
- `leela/blocks/modes/modes.py`: `Mode`, `register_mode`, `get_mode`, `modes`, and `cell_anchor`. A second mode with the same id is refused.
- `Assistant.mode` is a string ('code' by default) in place of the old `learn_mode` flag. `Thread.set_mode(mode)` keeps every guarantee of the old switch: idle only, under the turn lock, tools and context refresh together, rollback on failure, refused while a turn, a queued message or an approval is pending, and refused with `contract_missing` when the mode's contract check fails.
- A tool from another mode answers the `mode_off` error. `data` holds `mode` (the current mode) and `needs` (the mode that owns the tool).
- Saved modes: `agent-modes.json` holds `{thread: mode}`. The old `agent-learn.json` is read as 'learn' and is never written.
- `Workspace.mode`, `mode_layouts` and `mode_focus` are saved and restored. Switching closes nothing. Learn focuses the one `learn` tab at its last page, and makes it at `/` if it is absent. Code focuses the last editor tab.
- In Code mode the agent turn context ends with the active notebook cell (`cell_anchor`): its source, the last error, and clipped output. `POST /agent/turn` takes an optional `cell` (a cell id) and the workspace remembers it on the tab.

JSON for the UI:
- `GET /workspace/mode`: `{mode, modes: [{id, title, layout, palette, bar, tab_kinds}], layouts: {mode: layout}}`.
- `POST /workspace/mode {mode, thread?}`: `{ok, mode, layout, focus: {kind, path}}`. It switches the agent conversation first. When the agent refuses, the workspace mode does not change and the refusal comes back with status 409 (`{ok: false, code, message, thread}`). An unknown mode gives 400.
- `POST /workspace/layout {mode, layout}`: `{ok, mode, layout}`. Layout keys: `files`, `exec`, `exec_handle`, `agent` (booleans) and `main` (string).
- `POST /agent/mode {mode, thread?}`: `{ok, mode, on, thread}`. `POST /agent/learn-mode {on}` stays one release as an alias.
- `GET /agent/threads` adds `modes` (`{thread: mode}`) and `mode` (the workspace mode). It keeps `learn_modes` (`{thread: bool}`). Each thread row has `mode` and `learn_mode`.
- The agent feed emits `mode {mode}` and, for the old page code, `learn_mode {on}`.

First run: with no tab open, the page offers three choices: Open a folder, Learn something (`leeFirstLearn`: `POST /workspace/mode {mode: 'learn'}`, then the Learn tab, then focus on the Start box) and Write or run code. A line points to the top-bar switch.

Deferred: the title-bar switch and the mode bar (JS), the palette commands `Mode: Code` and `Mode: Learn`, the `Learn about this` command, per-mode key sets, and a `create` mode.

## Hosted route audit

Abhyasa's app has 210 route entries under Leela's origin (the catch-all mount and `/learn/abh`). `tests/test_learn_route_security.py` lists them from the built app and puts each in one group. A route that fits no group fails the test.

| Group | Routes | What it can reach | Rule |
| --- | --- | --- | --- |
| Read pages | 67 GET | The vault, read only | Same guard as every route |
| Changes | 46 POST | The vault: answers, plans, talks, concepts, profile | Cross-site and foreign-port POST refused |
| Model calls and jobs | 35 POST | The model of Leela, background jobs, the microphone | Same guard; the model call goes through Leela's assistant |
| Files | 17 | A folder or file in the home folder, a dropped file, a notebook | Only the home folder, not hidden, no link (`source_root_why`, `file_why`) |
| Files that Abhyasa serves | 19 GET | Its own assets, vendor files, figures, pictures, JSON | Fixed folders, or the vault |
| Settings and keys | 25 | Abhyasa's settings file and key file | Blocked, except `/settings/chip` and `/settings/catalog` |
| Catch-all static | 1 GET | The working folder | Never answers: `_known` refuses a path when this route is the first match |

Three layers apply to every request:

1. `LoopbackHostGuard` of Leela, which `serve_ide` puts outside the whole app. It refuses a foreign Host, a foreign Origin, `Sec-Fetch-Site: cross-site` and a change from another port. Hosted routes do not need a second guard.
2. `Hosted` calls `LocalOnly.refuse`, so the same rules hold when the guard is not there. It answers 403.
3. Each response has `frame-ancestors 'self'` and `X-Frame-Options: SAMEORIGIN`.

Findings that the tests showed, and what changed:

- A path such as `/c/x.txt` fits a known route and the static catch-all. The catch-all came first and served `x.txt` from the working folder, and `/v/%2e%2e/x.txt` read one level up. Fixed: `_known` now looks at the first route that matches.
- Abhyasa pages had no frame header. Fixed in `Hosted._serve`.
- Settings writes (`/settings/value`, `/settings/key`, `/settings/model`, `/keys/float`, and the others) were live. They wrote a settings file and a `keys.env` that Leela never reads. Fixed: they answer 404. The model chip of a check card keeps `/settings/chip` and `/settings/catalog`. Leela owns settings and keys.
- A cross-site request gets 421 (foreign Host or site) or 403 (foreign Origin on a change) from the guard, the same as a route of Leela.

Open:

- `/learn/pick` opens a macOS folder chooser. It needs a loopback client and passes both guards, so only a Leela page can ask.
- The GET routes that start work (`/w/{jid}/gather`, `/improve`, `/replan`, `/s/{sid}/end`, `/w/{jid}/{i}/done`) are safe from other sites by the guard. A page of Leela itself can still call them.

## Names

- `learn`: the Leela block (`leela/blocks/learn`), the settings section, and the tab kind. Everything of Leela is spelled `learn`.
- `abh`: the URL base `/learn/abh` and the `abh.css` and `abh.js` assets that carry Abhyasa pages inside a Leela tab.
- `abhyasa`: the Python package that teaches. Leela imports it by name and never copies it.
- `walk`: an Abhyasa walk, the path of steps through one goal, and the pages that show it (`/w/{jid}/{i}`).
- `hosted`: Abhyasa in hosted mode, where Leela serves its routes inside its own app and owns the guard, the settings and the keys.
- `native`: the plan docs and test names for this work (`native-learn`), where Learn is a part of Leela and not a separate window.
