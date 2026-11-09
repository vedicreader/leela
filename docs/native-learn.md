# Native Learn

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

## Delivery slices

Files below define scope, not claims that new files already exist. Resolve exact extension symbols before editing. Use only the two native worktrees. Commit locally and do not push or release during slices.

| Slice | Files and behavior | Targeted proof | Owner demo |
| --- | --- | --- | --- |
| S1 | `blocks/settings/settings.py`, settings dialog and Learn section registration | Registry round-trip, reset preservation, workspace trust, browser rendering | Open Settings, then Learn |
| S2 | Abhyasa engine source notebooks and pilot test; later Leela agent/job adapter | One `walk_from_topic` call through session routing and privacy guards in a cancellable job | Ask for a module and inspect its job card |
| S3 | `blocks/learn` native FT rendering, `tabs/app.py`, tab persistence | Native state response, quotes, ungrounded state, tab restore | Open the created walk and its source |
| S4 | Existing agent controls, conversation metadata and tool refresh | Same session, idle lock, approval/queue refusal, resume and mode-off dispatch | Toggle Learn without losing the conversation |
| S5 | Abhyasa assessment source notebook and native check/gauge view | Canonical grading, attempt retry/conflict, next-turn state | Answer in the view or pane and see updated understanding |
| S6 | Shared speech action and Abhyasa transcription seam | Permission, stop/error and isolated transcription checks | Dictate through one microphone action |
| S7 | Knowledge and graph blocks, tab/dock integration | Live theme refresh and tab restore | Open Knowledge and dock the graph |
| S8 | Slides/search/vault integration and old handoff removal | Feature parity, migration on copies and route audit | Present a talk, search sources and import existing learning |

Run targeted tests per slice. Run both full suites once after S5 for the first product milestone, not after each slice. Later S6-S8 changes require their own final affected-suite verification before release. Send Claude one completion message per slice with commit IDs, exact isolated demo commands, URL if running, UI screenshot path, test counts and known gaps. Start independent next work while review proceeds.

## Native walk tab

Use Leela's existing FT page and control conventions. Render step text in the existing markdown content component, a quote in `Blockquote` with an `A` source link, a check in `Form` with the existing input/button styles, and understanding in a compact status strip. Confirm exact component imports during S3 rather than copying Abhyasa's page renderer. Use only `--lee-*` colors and existing fonts.

`GET /learn/state` supplies `vault`, `walk`, `step`, `revision`, step content, source quote/link or `ungrounded`, check specification, engine understanding/recall and previous/next step IDs. Next/back controls request those IDs without changing the agent conversation. Empty state offers New module. Loading preserves current content and shows busy status. Error state retains selection and offers the permitted retry. Controls follow normal tab order and keep visible focus. No new shortcut is added. Persist only vault/walk/step identity in the tab descriptor; restore fresh engine state after restart and show a missing-vault or missing-walk message rather than stale content.

S4 audits the current agent control row before adding Learn beside the existing mode controls. Its states are Off, On and Busy. Busy disables mutation and explains the active turn, queue or approval. The palette invokes the same endpoint. Do not create another pane.

## First-run learning import

On first Learn open, inspect the configured existing learning shelf through the vault registry in the running product. Development tests use temporary copies only. If existing data is found, show Attach and Back up and copy before presenting an empty managed vault. Attach selects the existing registry entry when the path is already registered; it does not create an alias. Copy creates the managed Learn destination after a backup and preserves source files and assets. Existing data remains accessible if copy fails. Explicit Skip starts empty; never choose it silently. Test populated, empty, already-attached, read-only and failed-copy cases on temporary files. S2-S5 use explicit isolated fixture vaults until this first-run UI is complete in S8.

## Retirement and release

S1 and S2 delete no handoff routes. S3 replaces `/learn` page rendering and the old `pane.js` page embedding with native tabs while retaining valid notebook-open contracts. S4 replaces mode-related navigation with the shared agent switch. S5 uses native answer/state paths. S6 removes any remaining external speech dependence. S7 replaces graph/library navigation. S8 removes `serving.json` lookup, standalone URL helpers and the `pane=1` shell guard after auditing callers. Retain `/lesson/due`, `/learn/open`, `/learn/env`, `/learn/lookup`, `/learn/scratch` and `/learn/tool` only where they still implement native notebook contracts. Update route inventory and remove dead callers rather than retaining compatibility with the rejected shell.

S1-S5 require Abhyasa settings-provider injection, learning tool operations and attempt-id support. Edit source notebooks and run `nbdev-prepare`. Develop Leela against a non-editable local path source. After the milestone gates, prepare one Abhyasa release containing those engine changes, then pin Leela to its released version and remove the path source. No early publication bypasses owner acceptance or separate push/tag/PyPI approval. Abhyasa releases before Leela.

For the real-model pilot use an already configured local model through Leela routing, or ask the owner to supply a credential specifically to the isolated check. Do not read real key files or copy them into the preview. Without either option report the real-model smoke blocked, not passed. A deterministic callback test is useful but does not establish live routing or privacy behavior.

## Review status

The expanded teacher review completed and requested corrections. This draft incorporates its settings trust, mode lifecycle, tab delivery, job and idempotency requirements. The reset collision was independently verified in `Settings.reset`. The reported A2 contradiction is resolved explicitly by including passage selection in the first slice; multi-source creation remains later. Claude approved the settings slice and parallel model-callback pilot. D2 is owner-confirmed. The model callback bridge, job cancellation, settings injection and canonical assessment persistence need bounded source checks or pilots before their implementation steps. Approval of the independent settings-registry step need not wait for D2. Do not expand research into another full repository survey.
