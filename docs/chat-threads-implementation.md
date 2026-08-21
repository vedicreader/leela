# Chat threads: implementation specification and test plan

This document turns [chat-threads.md](chat-threads.md) into delivery contracts. It also includes the open items from the vault's UI fixes notes. The source design note remains the authority for product decisions; this document defines implementation boundaries, failure behaviour, tests and release gates.

## Outcomes

The completed feature set must provide:

- server-owned turns that continue when an EventSource disconnects;
- up to six live chat threads per workspace, each with its own assistant, session, approvals, runs and event feed;
- durable session titles and mute state;
- steering through the main composer;
- transcripts ordered by when prose and work happened;
- thread and workspace attention states, unread counts and optional browser notifications;
- exact per-thread cancellation, approval and recovery behaviour;
- non-destructive conversation branching, true turn undo, and selectable history inclusion;
- viewport-safe modals, wrapped note text, and discoverable note and vault commands.

The work does not include native packaged-shell notifications or the F6-style move-symbol refactor. The latter requires a separate language-aware design.

## Delivery order and gates

| Slice | Repository | Deliverable | Entry gate | Exit gate |
|---|---|---|---|---|
| S0a | Ramabana | Restore `Agent.busy` | Existing run lifecycle | Focused guard tests and Ramabana checks pass |
| S0b | Ramabana | Session metadata and history refresh | S0a | Persistence and convergence tests pass |
| U0 | Leela | Viewport-safe modal primitive | None | Modal keyboard and viewport tests pass |
| S1 | Leela | Merge steering into the composer | S0a | Composer, force-steer and draft tests pass |
| S2 | Leela | Server-owned turn and replay feed | S0a | Disconnect, replay and resync tests pass |
| S2b | Leela | Ordered web timeline | S2 | Ordering and delegate-folding tests pass |
| S3 | Leela | Thread registry and thread UI | S0b, S2, S2b | Isolation, routing and eviction tests pass |
| S3b | Ramabana and Leela | Branch, undo and history selection | S2b, S3 | Context compilation, isolation and recovery tests pass |
| S4 | Leela | Attention and notifications | S3 | Deduplication, mute and permission tests pass |
| S5 | Leela | Cross-workspace and non-run activity | S3 | Catalog and stale-target tests pass |
| U1 | Leela | Note and vault UI fixes | U0; otherwise independent | Command, wrapping and accessibility tests pass |

Do not begin S3 until S0b supplies `refresh_history`. Do not add a thread parameter in S1; S1 targets the active assistant. Introduce explicit thread targeting with S3.

## Cross-cutting contracts

### Identity and ownership

A thread id is its Ramabana session id. A run id identifies one turn or child run and is unique only within the thread's assistant registry. Every endpoint that accepts a run id after S3 must also resolve a thread id; it must never search other threads for a coincidental match.

The server owns a launched turn. Closing a tab, losing the network or closing an EventSource only removes a subscriber. It does not cancel the run. Cancellation happens only through an explicit stop, cancel, terminate, force-steer or process shutdown path.

### Structured errors

Thread-aware routes return errors with `code`, `message`, `thread`, and, when known, `run`. Required codes are `thread_not_found`, `thread_closed`, `thread_busy`, `thread_limit`, `no_evictable_thread`, `run_not_found`, `turn_conflict`, `feed_resync`, and `cancellation_incomplete`. The browser keeps the draft whenever a request has not been accepted or a force cancellation has not reached a terminal state.

### Construction

Every new or resumed thread must be constructed through `Workspace.sync_agent_routing`. Summary, classify and sub-agent job models must match workspace settings. `ws.ai` remains a property returning `ws.threads.active.ai`; existing callers must not cache it across a thread switch.

### Thread state

State is derived, not independently stored:

- `waiting` when the thread has a pending intervention;
- `working` when `ai.runs(active=True)` is non-empty;
- `failed` when idle and its latest root run failed;
- `idle` otherwise.

`waiting` takes precedence over `working` because it requires a person. Unread is incremented once when a background root run reaches a terminal state and cleared when that thread becomes active and its latest sequence has been rendered.

### Required pre-implementation audit

Before each behaviour-changing slice, record:

1. every visible control and keyboard shortcut that reaches the behaviour;
2. every command-palette row and generated key label;
3. every HTTP route and internal call path;
4. normal, failure, cancellation, reconnect and stale-target states;
5. focused regression tests for each route;
6. an independent missing-cases review.

## S0a: restore run-derived busy state

Change the source notebook that exports `Agent.busy` so it returns `bool(self.runs(active=True))`. Do not restore the old lock as a second source of truth.

The following guards must all use the repaired value: model changes, sub-agent writes, local multimodal changes, session resume, CLI mutation guards, Leela new chat, resume, settings, sub-agent writes, streaming and LiteRT backend changes.

Acceptance criteria:

- A pending, running or cancelling root run makes `busy` true.
- A live child run also makes it true.
- Completed, failed, cancelled, detached and terminated runs do not.
- A second stream is rejected before its pump starts.
- New and resume cannot replace the assistant or its context during a live run.

## S0b: session metadata

Add `{history_name}-sessions.json` beside the JSONL history. Store `title`, `title_turns`, `muted` and a metadata schema version per session. Write through a temporary file and atomic replace under the same history lock used for session updates. A missing file means empty metadata. A malformed file must be reported as a problem and left untouched; it must not erase recoverable history.

Add:

- `Agent.set_title(text, sid=None)`;
- `Agent.session_meta(sid=None)`;
- `Agent.summarize_session(sid=None, force=False)`;
- `Agent.refresh_history()`;
- metadata merging in `sessions()`.

Manual titles are authoritative until explicitly changed. Automatic summarisation runs after the first completed turn and again only when the session turn count is at least twice `title_turns`. A failed summary keeps the current or first-prompt title and records a non-fatal problem. `refresh_history` re-reads both JSONL and metadata so concurrently live assistants converge.

## U0: viewport-safe modals

Extend the existing `modal()` primitive in `leela/static/js/20_overlays.js`; do not patch individual dialogs. The overlay must remain within the visual viewport, put overflow on the body, preserve the focus trap, restore prior focus, and retain `beforeClose` and `requestClose` semantics. Test short and narrow viewports, long content, keyboard dismissal, a refused close, and restoration of the previous body-overflow value after close.

## S1: merge steering into the composer

Remove `#agentsteer`, `#agentsteerqueue` and the separate Queue and Stop-and-send-next controls. `sendAgent()` uses the active assistant state: idle submits a turn; working queues a steer. `agent_send` remains Mod+Enter. Add `agent_steer_force` on Mod+Shift+Enter after checking key duplication. Replace the palette row that focuses the removed input. Rebuild `leela/static/lee-ide.js` from its source files.

The send control must expose its mode in text and accessible name: `Send`, `Steer after this call`, or `Stop and send next`. A queued steer is a dimmed user card with Cancel. Consumption removes the queued state without duplicating the card. `Interventions` emits queue and consume callbacks so replay and a second tab see the same transition.

The force path cancels the foreground root run and waits for cancelled, detached or terminated. If it reaches another state or times out, return `cancellation_incomplete`, keep the draft and do not submit it. S1 uses the active assistant only; explicit thread targeting arrives in S3.

## S2: server-owned turns and replay feed

Add `leela/blocks/agent/threads.py` with a one-thread-compatible `Feed` and turn runner. A later slice adds the registry around it.

`Feed` stores `(seq, event, data)` in `deque(maxlen=2000)` under a `Condition`. Sequence numbers increase by one and are never reused during the feed lifetime. `since(n)` returns rows with `seq > n`. `wait(n, timeout)` blocks until such a row exists or the timeout expires. If `n` predates retained history, return one `resync` event with the oldest and latest retained sequence.

Supported events are `user`, `chunk`, `activity`, `execution`, `approval`, `compaction`, `run`, `steer`, `title`, `state`, `error` and `done`. Each event includes the thread id. Run and activity events include their run or action identity and parent identity when present.

Add `POST /agent/turn`. It accepts the prompt and existing turn options, records `user` before launch, starts a dedicated daemon thread named `leela-turn-<run-id>`, and returns the thread id, run id and first feed sequence. Launch validation errors are HTTP errors and do not create a user event. Failures after acceptance are `error` followed by `done`. Attachments are captured at acceptance so later browser changes cannot alter the launched request.

Rewrite `/agent/stream` as a subscriber over `?since=`. Subscriber disconnect does not cancel. A reconnect renders only sequences newer than its acknowledged value. Duplicate EventSource delivery is ignored by sequence. A `resync` response makes the browser fetch the canonical transcript and then reconnect from the latest sequence returned with that snapshot. If snapshot fetch fails, show a retryable state and keep the last sequence; do not clear the transcript.

The runner must not use `off_loop`'s shared executor. Process shutdown cancels active runs through the existing grace and termination policy, closes feeds, and wakes subscribers. Server restart retains history but not an in-memory feed; reconnect therefore receives `resync`.

Add the new routes to `tests/routes.txt`. Replace the disconnect-cancels regression with the opposite contract. Keep stop and per-run cancel and terminate behaviour exact.

## S2b: ordered web timeline

Port the Ramabana CLI timeline ordering, not its prose-merging behaviour or terminal widgets. Prose and calls appear in creation order. Each logical prose chunk emitted by the stream renders as its own Markdown block at that position in the timeline; the renderer must not collect earlier prose into one reply at the bottom. Deltas that belong to the same chunk may grow that block until the chunk boundary, then the block is sealed. A top-level call, approval, compaction, steer, run event, explicit chunk boundary, or turn completion seals the current block. The final prose chunk remains open and readable while it streams. Successful completed calls may fold to their summary; running and failed calls remain open.

A child activity with `parent_action_id` renders inside its delegate block. It must not also render as a sibling. Children without a resolvable live parent remain top-level rather than disappearing. Approval, compaction, run-state and steer events retain their feed position. Replay must produce the same structure as live delivery.

## S3: thread registry

Add `Thread` and `Threads` in `leela/blocks/agent/threads.py`. One `Thread` owns one assistant, session id, interventions queue, run registry, feed, title, timestamps, unread count and mute state. Its `Interventions.on_ask` and `on_answer` callbacks append approval events to that thread's feed; notebook approvals remain separate. `Threads` provides `new`, `get`, `resume`, `close`, `rows` and `active`. `ws.ai` resolves to `ws.threads.active.ai`. Keep `ws.approvals` for notebook prompt-cell approvals only.

A workspace holds at most six live threads. Creating or resuming a seventh evicts the least-recently-used idle thread after history and metadata are flushed and its assistant is closed. Working and waiting threads are protected. If all six are protected, return `no_evictable_thread`. Closing a working or waiting thread is refused until the person explicitly stops or answers it; closing must never imply cancellation. An evicted thread is resumable from history, but its old feed is gone and reconnect begins with a transcript resync.

Add `GET /agent/threads`, `POST /agent/thread/new`, `POST /agent/thread/close`, and `POST /agent/thread/title`. Change `/agent/new` to create and activate a thread. The thread dropdown in the agent head lists title, state, model, turns, cost, unread and mute. Add commands for new thread, thread list or switcher, next thread, and next thread waiting for attention only after auditing the keymap and palette. Rename and close use the shared modal primitive.

### Route targeting after S3

Routes fall into three groups.

| Target | Routes and behaviour |
|---|---|
| Explicit thread, default active | approval read and answer, control, run policy, steer, approval request, rollback tool, runs, stop, cancel, terminate, transcript, status and compaction |
| Thread lifecycle | threads list, thread new, thread close, thread title, new, resume, sessions, history, branch switch, fork, revise, undo turn, history preview, history apply and retry |
| Workspace-wide | model catalog, workspace settings, attachment upload and command or tool metadata that does not mutate a session |

Every explicit-thread route accepts `thread`; omission resolves once to the active id at request start. A thread switch during an awaited request must not retarget it. `/agent/approval` also returns all waiting thread ids. Approval ids are resolved only in the selected thread. Run cancel and terminate require the selected thread and affect no other registry.

Settings that mutate an assistant are applied either to the selected thread or, when explicitly documented as workspace defaults, saved for future threads and synchronised to idle live threads. A busy thread refuses a model or context mutation rather than changing beneath a run.

## S3b: branch, undo and history selection

Extend the existing `/agent/branches`, `/agent/fork`, `/agent/revise`, `/agent/rollback-turn` and response-revision controls. Do not build a second branch system. A conversation branch is an immutable parent reference plus an ordered context manifest. Persist branch records and manifests beside the session metadata with a schema version, branch revision and atomic writes. `refresh_history` reloads them, and thread resume reconstructs the same active context after process restart. Canonical event and turn history remains append-only so the original conversation is always recoverable. Switching or editing context creates a new branch id and never rewrites another branch. All operations require an explicit thread after S3 and are refused while that thread has an active run or pending approval.

### Branch from a conversation point

Every stable timeline part has a durable part id and identifies its turn, branch and position. The response menu offers `Branch from here`. At a turn boundary it uses the existing before or after checkpoint. At a prose or activity part inside a turn, Ramabana rebuilds model history from the branch manifest through that part; it must not pretend a turn-boundary checkpoint represents a finer point. The new branch opens as a new thread by default, leaving the source thread visible and unchanged. The branch records `parent_branch_id`, `parent_turn_id`, `parent_part_id`, stage and creation time.

A branch point inside a tool exchange must compile a valid message sequence. A tool call and its result are atomic for context: include both or stop before the call. An approval request and answer are also atomic. Media stays with its user message. Invalid or unavailable points return `branch_point_invalid` without creating a thread.

### True turn undo

`Undo from conversation` creates and activates a branch at the checkpoint before the selected turn. The selected turn and every later descendant are absent from the new branch context but remain in canonical history and the source branch. Undoing several turns chooses the earliest selected turn and has the same semantics. Redo is branch switching, not reconstruction. The branch dropdown shows the active branch, its parent point and shaped or undone status; selecting another branch calls the explicit switch route and rebuilds that branch's context without creating a copy.

This is separate from file rollback. Rename the current `Undo turn` file-transaction control to `Restore files` and keep its transaction preview, irreversible-effects warning and stale-file checks. The undo dialog may offer `also restore reversible files` only when the selected turn has a valid transaction. Conversation undo succeeds when file restoration is unavailable or declined. If restoration fails, keep the new branch and report which files were not restored; never claim external effects were undone.

### Select history parts

Add `Shape history` to the thread and response menus. It opens the shared modal with the current branch as an ordered list of user messages, separate assistant Markdown blocks, tool exchanges, approvals, compactions and attachments. A person can select a contiguous range or individual parts and assign one policy:

- `keep`: include the part in compiled model context;
- `discard`: omit it from compiled model context while retaining it in canonical history;
- `auto`: let the compiler decide from dependencies, recency and the context budget.

The default policy is `auto`; existing branches with no manifest compile exactly as they do today. Explicit keep and discard override auto except where inclusion would create an invalid provider message sequence. In that case the preview groups the dependent parts and asks for one policy rather than silently overriding the person. Tool call/result pairs, approval request/answer pairs, media/user-message pairs and compaction summary/source boundaries are dependency groups.

Before applying, show the resulting ordered context, omitted-part count, estimated tokens, compacted material and every dependency adjustment. Apply creates a new branch with a persisted manifest of part ids and policies. Cancel changes nothing. `Reset to auto` creates no branch until Apply. The thread rail marks shaped branches and can show their parent and omitted count. History search and transcript export still see canonical events; model generation, title refresh and compaction consume only the active branch's compiled context.

Add `POST /agent/history/preview` and `POST /agent/history/apply`; both require `thread`, base branch id and an optimistic branch revision. Preview returns the normalized dependency groups, compiled-context summary, token estimate and proposed next revision. Apply repeats validation under the branch lock and commits the branch record and manifest atomically. Stale revisions return `history_changed` with no partial branch. Extend `/agent/fork` to accept `part_id`. Add `POST /agent/branch/switch`. Keep `/agent/rollback-turn` for file restoration and add `POST /agent/undo-turn` for true context undo. Every S3b success and failure uses the structured thread-aware response contract.

## S4: attention and notifications

Add thread state and unread count to the dropdown first. Add an attention bar above the composer when another thread is waiting; activating it switches to that exact thread and focuses the approval. Prefix `document.title` with the working count and `(!)` while any thread waits.

Browser notifications are off by default. The setting requests permission only when enabled. Handle unsupported, default, denied and granted states without repeated prompts. Notify only when the document is hidden and a background, unmuted thread either starts waiting or completes a root run. Use the terminal feed event identity as a deduplication key so replay, reconnect and multiple local subscribers do not notify twice. A mute suppresses browser notifications but not waiting state, unread or the attention bar.

If an approval is answered in another tab, remove the attention state on the next event. If its thread was closed or evicted, dismiss the stale affordance and show a non-destructive status. Switching to a thread clears only events the browser has rendered, not future events already in flight.

## S5: cross-workspace and non-run activity

Expose the workspace object on `WorkspaceSite`. Add `agent: {working, waiting, threads}` to the in-process catalog and pass it through `/workspace/info`. The workspace switcher shows a state dot and count and opens the relevant workspace; when possible it includes the waiting thread id.

Add a footer group to the thread dropdown for vault jobs, video generation and research jobs. These are not Ramabana runs and must not be inserted into the run tree. Stale catalog data is advisory: if the target workspace or thread no longer exists, refresh the catalog and show a status instead of leaving a broken selection. Counts settle after failed, cancelled, detached and completed work.

## U1: open UI-fix items from the vault

### Note and vault commands

The vault workbench already has note creation. Expose existing note creation and vault opening as named commands before assigning shortcuts. Each action must be reachable from a visible control and the command palette. Audit current global, editor and modal bindings; add only non-conflicting keys. Closing a dirty note follows existing save or discard behaviour. Do not create a second note persistence path.

### Note wrapping

Note editing and rendered note bodies wrap long prose within their container. Preserve intentional line breaks and code blocks. Long unbroken tokens may scroll or break without widening the modal or workbench.

### Separate move-symbol project

Do not implement the requested PyCharm-F6-like move method or class command as part of chat threads. Its later design must cover symbol selection, syntax support, destination creation, import and reference rewriting, conflicts, preview, atomic application, rollback, undo and project checks. Until that design exists, no shortcut or palette row is reserved for it.

The vault marks aliased-import navigation, search positioning, whole-file find, note autosave, note save and close bindings, note-modal sizing and primary control emphasis as complete. They are regression context, not new deliverables.

## Failure and recovery matrix

| Failure | Required response | Preserved state |
|---|---|---|
| Turn validation fails | Structured HTTP error | Draft and attachments |
| Runner fails after acceptance | `error`, then `done` | History written so far and feed |
| EventSource disconnects | Subscriber ends only | Run and feed |
| Sequence predates buffer | `resync` with retained bounds | Run, canonical history and client cursor |
| Transcript resync fetch fails | Retryable inline state | Existing rendered transcript and cursor |
| Thread id is stale | `thread_not_found` | Draft and active thread |
| All six threads are protected | `no_evictable_thread` | All threads and requested session history |
| Force cancellation is non-terminal | `cancellation_incomplete` | Draft; no replacement turn |
| Title summary fails | Non-fatal problem | Existing title and metadata |
| Session metadata is malformed | Report and refuse overwrite | Malformed sidecar and history |
| Notification permission denied | Disable native delivery | In-app state and setting value |
| Workspace catalog target is stale | Refresh and report | Current workspace and selection |
| Branch point is missing or splits an atomic exchange | `branch_point_invalid` with dependency details | Source thread, branch and draft |
| History changes after preview | `history_changed`; require a fresh preview | Source branch and unapplied selections |
| Optional file restoration fails after context undo | Report exact paths and irreversible effects | New conversation branch and canonical history |

## Test plan

Every behaviour-changing slice starts red: add or update the focused regression, run it to confirm the old behaviour fails, implement the change, and run it again. Ramabana changes belong in executable cells in the source notebooks plus any existing external contract tests. Never edit generated Ramabana modules directly.

### S0a tests

- Start a controllable root run and assert `busy`, model mutation, resume and a second stream are blocked.
- Register only a live child run and assert `busy`.
- Move runs through completed, failed, cancelled, detached and terminated and assert `busy` is false.
- Cancel a run, wait for terminal registration, and prove guarded operations work again.
- Run the focused notebook cell, Ramabana export and relevant Ramabana tests; then run Leela guard tests against the updated dependency.

### S0b tests

- Set a manual title and mute state, close the agent, reload it and compare metadata.
- Create two agents on one history name; write a turn in one, call `refresh_history` in the other and compare sessions.
- Assert automatic title calls at one turn and at the first doubled count, but not between.
- Assert a manual title is not replaced by automatic summarisation.
- Make summarisation fail and verify the old title and history remain.
- Supply a malformed sidecar and verify it is reported and not overwritten.
- Exercise concurrent metadata writes and verify valid JSON with both unaffected sessions.

### U0 and U1 tests

- Render a modal in short and narrow viewports; assert the overlay bounds and body overflow.
- Assert Tab trapping, Escape, prior-focus restoration, `beforeClose`, refused `requestClose`, and restoration of the previous body-overflow value.
- Assert note creation and vault opening each have one named command, a visible route and a palette row; run the key duplicate check if shortcuts are added.
- Render prose, explicit newlines, fenced code and a long token in note edit and read views; assert the container does not widen.
- Keep existing autosave, save, close and completed navigation regressions green.

### S1 tests

- Assert the old steering input and controls are absent from panel HTML and built JavaScript.
- Assert the send button and accessible name match idle, queued and force states.
- Queue a steer and verify one dimmed card, then consume it and verify the same card becomes final.
- Cancel a queued steer and verify it is removed without reaching the model.
- Exercise Mod+Enter and Mod+Shift+Enter and run the key duplicate check.
- Return a non-terminal cancellation state and verify the draft remains and no turn starts.
- Rebuild the JavaScript bundle and run the stale-bundle test.

### S2 tests

- Reject an invalid turn and assert its structured HTTP response, preserved draft and attachments, and absence of a `user` event.
- Accept a valid turn, mutate the browser attachment selection, and assert the runner uses the captured acceptance-time attachments.
- Start a turn, close its subscriber, let it complete and assert history and `done`.
- Disconnect after sequence N, generate events, reconnect with N and compare exactly the missed sequences.
- Deliver the same sequence twice and assert one DOM effect.
- Overflow a small test feed and assert one `resync` event with correct bounds.
- Fail transcript fetch during resync and assert the existing transcript and retry action remain.
- Restart with durable history but no feed and assert resync reconstructs the transcript.
- Stop, cancel and terminate through each existing entry point and compare terminal run state.
- Assert six blocked runners do not consume the shared executor.
- Shut down with an active run and waiting subscriber; assert cancellation policy, feed closure and subscriber wake-up.

### S2b tests

- Emit several logical prose chunks with no intervening tool call and assert each remains a separate Markdown block rather than merging at the bottom.
- Grow one prose chunk through several deltas and assert they update one block until its boundary without repainting earlier blocks.
- Emit prose, a call, more prose, another call and a final answer; compare creation order.
- Run the same event list live and through replay and compare the semantic DOM tree, including identical prose-block boundaries.
- Emit delegate children and assert they occur only inside the delegate block.
- Emit an orphan child and assert it remains visible at top level.
- Assert running and failed calls stay open while successful completed calls may fold.
- Place approval, steer and compaction events between prose and calls and assert their positions.

### S3 tests

- Run two threads concurrently and assert separate histories, checkpoints, feeds, approvals and run registries.
- Cancel a run in one thread and assert the other run remains active.
- Ask and answer an approval in one thread and assert both events land only in that thread's feed; an identical id in another remains untouched.
- Switch the active thread during an awaited request and assert the request remains bound to its original id.
- Assert `ws.ai` resolves to the active assistant before and after switching.
- Assert every new and resumed thread carries saved routing job models.
- Fill six slots, touch their recency, and verify exact idle least-recently-used eviction.
- Protect working and waiting threads; assert they are never evicted and all-protected returns `no_evictable_thread`.
- Close an idle thread and resume it from history; assert transcript resync and no old feed replay.
- Refuse close on working and waiting threads without explicit stop or answer.
- Assert dropdown rows include title, state, model, turns, cost, unread and mute, and exercise new, next-thread and next-waiting commands.
- For stale thread, stale run, protected-capacity and incomplete-cancellation routes, assert HTTP status, `code`, `message`, `thread`, optional `run`, and draft preservation.

### S3b tests

- Fork before and after a completed turn and compare the new branch context with the existing checkpoint behavior.
- Branch from each stable prose block and assert the new thread ends at that exact part while the source thread and branch remain unchanged.
- Attempt to branch between a tool call and result, approval request and answer, or user message and media; assert atomic grouping or `branch_point_invalid`, never malformed history.
- Branch concurrently in two threads and assert part ids, checkpoints, manifests and active branch ids do not cross.
- Undo one turn and several turns; assert a new branch before the earliest selected turn, canonical history preservation, and redo by branch switching.
- Assert `Restore files` keeps the existing transaction preview and stale-file protections and does not claim to alter model history.
- Undo conversation context with file restoration declined, unavailable, successful and failed; assert context undo always remains and exact restoration failures are reported.
- Apply keep, discard and auto to individual parts and ranges; compare the compiled provider messages, order, token estimate and omitted count with the preview.
- Assert branch parentage, revision and explicit policies persist across process restart and `refresh_history`, while an old branch with no manifest compiles byte-for-byte as before.
- Switch among source, shaped and undone branches and assert exact context restoration without creating another branch.
- Assert tool exchanges, approvals, media and compaction boundaries are dependency groups and cannot produce orphan provider messages.
- Change the branch after preview and assert `history_changed`, no new branch and no partial manifest.
- Fail the atomic branch write between record and manifest and assert neither becomes visible after reload.
- Cancel and reset the modal and assert no branch is created; Apply creates exactly one branch.
- Assert model generation, title refresh and compaction use shaped context while history search and transcript export retain canonical events.
- Exercise branch, undo, branch-switch and shape-history controls by mouse and keyboard; verify focus restoration and the keymap duplicate check if shortcuts are added.
- Add fork, branch-switch, undo-turn, history-preview and history-apply endpoints to `tests/routes.txt` and assert structured thread-aware success and error payloads.

### S4 tests

- Complete a background root run and assert one unread increment and, when hidden and enabled, one notification.
- Replay and reconnect the terminal event and assert no duplicate notification.
- Mute the thread and assert no browser notification while unread and waiting indicators remain.
- Exercise unsupported, default, denied and granted permission states without repeated prompts.
- Answer a background approval in another tab and assert the attention bar disappears.
- Switch to the waiting thread by mouse and keyboard and assert focus reaches the approval.
- Assert `document.title` tracks working count and waiting precedence.

### S5 tests

- Populate two workspace catalogs and assert working, waiting and thread counts reach the switcher.
- Click a waiting indicator and assert the correct workspace and thread open.
- Remove the workspace or thread before activation and assert refresh plus a non-destructive status.
- Complete, fail, cancel and detach work and assert catalog counts settle.
- Assert vault, video and research rows appear outside the Ramabana run tree.

## Verification commands

Use each repository's documented plain commands. At minimum for a Leela UI slice:

```bash
python tools/build_ide_js.py
pytest
```

For Ramabana, edit the source notebook and run its documented nbdev export and test commands before the relevant external tests. After export, inspect `git status` to ensure notebook and generated module agree. Do not run network or live-model tests for these contracts.

## Release gates

A slice is complete only when:

- its focused regression failed before the fix and passes after it;
- the relevant repository checks pass;
- generated JavaScript or Python is current;
- `tests/routes.txt`, keymap and palette contracts match the shipped surface;
- failure and recovery states return the documented structured response;
- an independent review of the exact changed files and tests has been checked against the actual diff and test output;
- no unrelated working-tree changes were modified.

S2 must ship single-threaded before S3. S3 must not ship without history convergence. S4 and S5 may follow independently after S3. The UI fixes U0 and U1 may ship separately, but thread rename and close depend on U0.
