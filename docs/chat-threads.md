# Chat threads: turns that outlive the tab

The agent pane has one conversation, owned by whichever browser tab opened it. This is the
implementation spec for making it several conversations, owned by the server, with titles, a
list of what is running, notifications across them, and steering folded into the composer.

Written against Leela at `fe77edf`, Ramabana at `4afcf65` and Rishi at `c5dc269`. The run
lifecycle that landed in Ramabana between the first pass and this one supplies half of what the
first pass proposed building, and invalidates one of its slices outright.

## What is true today

- `Workspace.ai` builds one `Assistant` lazily and holds it forever (`workspace.py:197`).
  `/agent/new` throws that object away and closes it (`app.py:1692`).
- **A turn is a `Run`** (`ramabana/runtime.py:952`): an id, a kind of root or child, the
  question, the model, a parent, and a state machine of pending, running, cancelling,
  cancelled, detached, terminated, completed, failed. `Agent.runs(active=True)`,
  `Agent.run(id)`, `Agent.cancel(id, grace)` and `Agent.terminate(id)` are the API
  (`ramabana/agent.py:1951` onward), the last hundred are retained, and `current_run()` is a
  contextvar. Delegated sub-agents register as child runs before they start
  (`ramabana/tools.py`, `delegate` and `delegate_many`), so the tree is the whole turn.
- The runstrip already draws that tree. `updateAgentRunstrip` flattens roots and children, one
  row each with elapsed time and a Stop button that cancels exactly that run
  (`12_agent.js:1169`), served by `/agent/runs`, `/agent/runs/{id}/cancel` and
  `/agent/runs/{id}/terminate` (`app.py:2081`).
- The turn still belongs to the tab. `/agent/stream` runs `ws.ask_stream` on an executor, and
  its `finally` waits up to `cancel_grace` to learn the run id and then cancels it
  (`app.py:2103` onward). Closing the EventSource is how a turn ends, so nothing can finish
  while you are elsewhere. `test_stream_disconnect_waits_only_for_the_exact_run_registration`
  pins this.
- Approvals are a queue of one. `Approvals.current` is a single slot
  (`ramabana/agent.py:394`), `Interventions` inherits it (`ai.py:92`), and one `Interventions`
  is shared by the agent pane and the prompt cells (`workspace.py:195`).
- Sessions have no title in Leela. Ramabana's `sessions()` cuts one from the first prompt
  (`ramabana/agent.py:1380`); `_history_sessions` regroups from raw turns and drops it
  (`app.py:292`), and the picker labels each conversation with a timestamp
  (`12_agent.js:607`).
- Steering is still a second input, with Queue and Stop and send next (`app.py:658`). The force
  path is now exact: it cancels the foreground run, reports the terminal state, and keeps the
  draft when the state is not terminal (`12_agent.js:1224`). A steer still never appears in the
  transcript.
- Every activity row of a turn is appended to one `.lee-agent-steps` block above the reply
  (`12_agent.js:1608`), so a turn's calls all sit above its answer whatever order they happened
  in.
- `approvalLoop` polls `/agent/approval` only when the window is visible and only for this
  workspace (`12_agent.js:1252`).
- The agent keymap is three actions: `agent_send`, `agent_stop`, `agent_tools`
  (`core/keys.py:219`). The palette adds eight hardcoded agent rows (`21_similar.js:239`).

## One live regression to fix first

`Agent.busy` is `self.lock.locked()` (`ramabana/agent.py:1187`), and the `@patch`ed `ask` and
`stream` that replaced the class-body versions no longer take that lock
(`ramabana/agent.py:1987`, 2008). Single flight moved into `_new_run`, which raises
`RuntimeError('the assistant is already running')` when a non-terminal run exists. So `busy` is
now false forever, and every guard written against it is a no-op:

- Ramabana: `set_model`, `set_subagent_writes`, `set_local_multimodal`, `resume_session`
  (`agent.py:1210`, 1232, 1241, 1409), and `cli.py:636`.
- Leela: `/agent/resume` (`app.py:1685`), `/agent/new` (`app.py:1693`), `/agent/settings`
  (1794), `/agent/subagent-writes` (1815), `/agent/stream` (2103), and `set_litert_backend`
  (`ai.py:667`).

What that costs today, before any of this spec is built:

1. New chat during a live turn no longer refuses. It builds a replacement `Assistant` and calls
   `close()` on the old one, and the new `close()` cancels active runs, so the turn dies with
   no message and the open EventSource errors out.
2. Resume during a live turn no longer refuses, and swaps the model's context under a run.
3. A second `/agent/stream` gets `RuntimeError` as an inline `error` event rather than the 409
   the route means to send, because the guard passes and the failure happens in the pump
   thread.

The fix is one patch in Ramabana beside the others: `busy` returns `bool(self.runs(active=True))`.
Every guard above then works again, in both repositories, with no Leela change. `status()`
already reports the run-derived value (`agent.py:2053`), so nothing else moves.

## What the run lifecycle changes about the plan

- **S2 shrinks.** The first pass proposed inventing a turn id and a state row. Both exist. What
  is left is the event buffer and moving ownership off the subscriber.
- **S5 shrinks.** The per-run rows with Stop, including sub-agents, already ship. What is left
  is rows for other threads and other workspaces, and for the work that is not a run: vault
  jobs, video jobs, research.
- **S2 now inverts a deliberate contract.** Disconnect-cancels is not an oversight; it was
  hardened and pinned this week. Changing it means rewriting that test to assert the opposite,
  and deciding what happens to a run nobody is watching.
- **A new slice appears.** Ramabana's CLI now orders a turn's narration, calls and answer by
  creation, folds a delegate's sub-calls under the delegate, and pins all of it in
  `tests/test_timeline.py`. That file's opening paragraph describes Leela's web pane exactly:
  narration in one place, calls in another, the answer at the bottom of the narration. Threads
  make a long log longer, so the ordering is worth porting.
- **Thread creation has a new obligation.** `Workspace.sync_agent_routing` (`workspace.py:196`)
  reapplies saved job models to a live assistant, and `/agent/new` calls it. Every thread must
  be built through it or its sub-agent, summary and classify models silently reset.

## Decisions

| | Question | Recommendation |
|---|---|---|
| D1 | Is a chat thread the same noun as `docs/parallel-threads.md`'s worktree thread? | Yes. One board, one word. Build the rail so a worktree thread is another row kind, and ship chat rows first. |
| D2 | Does the event buffer live in Leela or Ramabana? | Leela. The event shapes carry tool schemas and data URLs, which are frontend concerns. Ramabana gets `busy`, titles, and nothing else. |
| D3 | What happens to a run nobody is watching? | It keeps running. No auto-cancel, no idle timeout. The rail is what makes it visible, and Stop is what ends it. |
| D4 | How many live threads? | Six, with idle least-recently-used eviction. A closed thread is still resumable from history. Never evict one that is working or waiting on a person. |
| D5 | Rail shape? | A dropdown from the chat head, plus an attention bar that appears only when another thread wants something. A permanent strip costs width the pane does not have. |
| D6 | Port the CLI's timeline ordering to the web transcript? | Yes, as S2b, after turn ownership and before threads. It is the difference between a readable log and a wall. |
| D7 | Native notifications in the packaged shell? | Later. Web `Notification` covers the Chrome shell, which is the shipped default. |

## The design

### Thread

One `Thread` is one `Assistant`, one Ramabana session id, one approvals queue, one run
registry and one event feed. `leela/blocks/agent/threads.py`, new:

```python
class Thread:
    id          # the Assistant's session_id
    ai          # Assistant, with its own Interventions and its own runs
    feed        # Feed, below
    title       # from Ramabana's session sidecar
    state       # idle | working | waiting | failed, derived from runs and approvals
    unread      # turns finished since this thread was last read
    muted
    created, last_active
```

`Threads` is the registry on `Workspace`: `new()`, `get(id)`, `resume(session_id)`, `close(id)`,
`active`, `rows()`. Every construction path goes through `sync_agent_routing`. `ws.ai` stays as
a property returning `ws.threads.active.ai`, because sixty call sites depend on it and none of
them care which thread they are on.

`state` is computed, not stored: `ai.runs(active=True)` gives working, the thread's
`approvals.pending` gives waiting, and the last run's terminal state gives failed.

### Feed

```python
class Feed:
    put(event, data) -> seq       # appends, wakes waiters
    since(n) -> [(seq, event, data)]
    wait(n, timeout) -> rows      # blocks until seq > n
```

A `deque(maxlen=2000)` and a `Condition`. Events are the ones the SSE route already emits
(`chunk`, `activity`, `execution`, `approval`, `compaction`, `run`, `error`, `done`) plus four
new ones: `user` (the prompt, so a reconnecting tab sees its own message), `steer`, `title`,
`state`. When `since` is older than the oldest retained row the feed answers `resync`, and the
browser refetches the transcript rather than rendering a hole.

The runner is a plain `threading.Thread` named `leela-turn-<run_id>`, as `Jobs.launch` does
(`blocks/vault/jobs.py:107`). It must not use `off_loop`'s shared executor: six agents holding
workers at long timeouts is the starvation `docs/parallel-threads.md` predicts.

### Approvals per thread

Each `Thread` builds its own `Interventions`, with `on_ask` and `on_answer` writing an
`approval` event into that thread's feed. `ws.approvals` stays as the prompt-cell queue, since
`notebook_approvals` exists to write into a notebook and only `ask_cell_stream` ever sets a
target. Every route that reads `ws.approvals` takes a `thread` parameter defaulting to the
active one: `/agent/approval`, `/agent/approve`, `/agent/control`, `/agent/run-policy`,
`/agent/steer`, `/agent/approval/request`, `/agent/rollback-tool`. The run routes take the same
parameter, since the registry is per `Agent`.

`/agent/approval` also returns `waiting: [thread ids]`, which is what the attention bar and the
badge read.

### Titles

Ramabana, `nbs/03_agent.ipynb`:

- A sidecar beside the history log, `{history_name}-sessions.json`, holding
  `{sid: {title, title_turns, muted}}`.
- `Agent.set_title(text, sid=None)` and `Agent.session_meta(sid=None)`.
- `sessions()` merges the sidecar over the first-prompt title it already derives.
- `Agent.summarize_session(sid=None, force=False)`: one line from the `summary` job through
  `oneshot` (`ramabana/agent.py:1564`), over the session's first turns. Re-derives only when
  the turn count has doubled since `title_turns`, so a drifting conversation is renamed and a
  steady one is not re-summarised every turn.
- `Agent.refresh_history()`: re-read the JSONL. History is one file per `history_name`, loaded
  into memory once per `Agent`, so without this two live threads never see each other's turns
  and the history panel goes stale.

Leela calls `summarize_session` from the turn runner after the first turn completes and puts a
`title` event on the feed. `/agent/thread/title` renames by hand.

### Notifications

In value order, because an approval blocking another thread is the one that costs time:

1. Thread row state and an unread count in the rail.
2. An attention bar above the composer when another thread is waiting on a person, naming it
   and jumping to it on click. `status()` is footer-only and addressed to nothing
   (`00_core.js:478`), so it cannot carry this.
3. `document.title` prefixed with the working count, and `(!)` when something waits.
4. The `Notification` API when `document.hidden`, behind a settings checkbox that requests
   permission when it is turned on. Off by default.
5. Per-thread mute, stored in the Ramabana sidecar alongside the title.

Cross-workspace: `WorkspaceSite` gains `ws`, `hub.catalog()` gains
`agent: {working, waiting, threads}` read in process rather than over HTTP
(`app.py:2420` builds every site in one process), `/workspace/info` passes it through
(`blocks/workspace/app.py:22`), and `leeWorkspaceMenu` (`20_overlays.js:258`) draws a dot per
workspace with a count on the pill.

### Steering in the composer

The cheapest large win, and the only slice that depends on nothing else.

Delete `#agentsteer`, `#agentsteerqueue`, Queue and Stop and send next (`app.py:658`).
`/agent/steer` keeps its contract, force path included, and gains a `thread` parameter and a
feed event.

- `sendAgent()` branches on whether the thread has an active run: idle posts a turn, working
  posts a steer.
- `agent_send` (mod+enter) sends or queues. A new `agent_steer_force` (mod+shift+enter)
  cancels and sends now.
- The Send button relabels through Send, "Steer after this call", "Stop and send next", so the
  state is legible without a second control.
- The force path keeps its current precision: if the cancelled run does not reach cancelled,
  detached or terminated, the draft stays in the box and the status says why
  (`12_agent.js:1224`). That behaviour moves into the composer unchanged.
- The steer renders as a real user card in the transcript, dimmed with a Cancel while queued,
  undimmed when the model takes it. `Interventions` gains an `on_steer` callback fired from
  `queue_steer` and `consume_steer` (`ai.py:124`, 132), which the runner turns into the event.

Six assertions pin the two-box UI and must be rewritten with it: `test_agent.py:2111`, 2112,
2113, 2131, 2245, 2259, and `test_web.py:1371`.

## Slices

### S0a Revive `busy` (Ramabana)

One patch, `busy` from active runs. Fixes eleven dead guards across both repositories. Ship it
on its own, ahead of everything.

Tests: a guard refuses while a run is live and allows once it is terminal; a cancelled run
leaves `busy` false.

### S0b Session titles (Ramabana)

`nbs/03_agent.ipynb`: sidecar, `set_title`, `session_meta`, `summarize_session`,
`refresh_history`, `sessions()` merge. Then `nbdev-export`, `nbdev-test`, `pytest`.

Tests: an executable cell for the merge and the doubling rule; a `tests/` contract that a title
survives a reload and that two `Agent`s on one `history_name` converge after `refresh_history`.

### S1 Composer merge (Leela)

`app.py:618` panel, `12_agent.js` (`sendAgent`, `leeQueueSteer`, `leeForceSteer`,
`setQueuedSteer`, `updateAgentRunstrip`), `core/keys.py` for `agent_steer_force`,
`21_similar.js:248` whose palette row focuses an input that will not exist, `lee-ide.css` for
the dimmed steer card. Rebuild with `tools/build_ide_js.py`.

Tests: the two inputs are gone and the relabelling exists in the JS corpus; the new chord and
the duplicate check; a steer reaching the transcript in order; a cancel while queued; the
non-terminal force path still keeping the draft.

### S2 Turn ownership (Leela)

`blocks/agent/threads.py` with `Feed` and the runner, `POST /agent/turn` returning the run id,
`/agent/stream` rewritten to replay from `?since=`, disconnect no longer cancelling. One thread
only, so the UI change is limited to reconnect. Add both routes to `tests/routes.txt`.

Tests: a run survives the subscriber closing, which is the inverse of
`test_stream_disconnect_waits_only_for_the_exact_run_registration` and replaces it; a reconnect
with `since` replays exactly the missed events; an overflowed buffer answers `resync`;
`/agent/stop` and the per-run cancel routes still end it.

### S2b Timeline ordering (Leela)

Interleave activity rows and reply text in creation order in the web transcript, and fold a
delegate's child runs under the delegate, as `ramabana/tests/test_timeline.py` specifies for
the CLI. The run tree already carries the parent link that makes the folding possible.

Tests: a turn with calls before and after prose renders in that order; a delegate's sub-calls
render under it and not scattered; a failed call does not fold.

### S3 Threads (Leela)

The registry, per-thread approvals, `/agent/threads`, `/agent/thread/new`,
`/agent/thread/close`, `/agent/thread/title`, `/agent/new` starting a thread instead of
refusing, the head dropdown, and keys for new chat, next thread and next thread wanting
attention.

Tests: two threads run at once without sharing a checkpoint; an approval on one names its
thread; a per-run Stop on one thread does not touch another; eviction never takes a working or
waiting thread; `ws.ai` still resolves; every thread carries the saved job models.

### S4 Notifications (Leela)

Attention bar, unread counts, `document.title`, the `Notification` setting, per-thread mute.

Tests: a completed turn on a background thread raises exactly one notification; a muted thread
raises none; the title prefix tracks the working count.

### S5 Cross-thread and cross-workspace rows (Leela)

`WorkspaceSite.ws`, catalog agent state, the switcher dots, and a footer row on the rail for
vault jobs, video jobs and research, which are not runs and so are not in the run tree.

## Audit of what already exists

Required before adding a shortcut, panel or setting.

- Keymap (`core/keys.py`): `agent_send`, `agent_stop`, `agent_tools` in the agent scope,
  `focus_agent`, `agent_selection` and `toggle_right` global. New: `agent_steer_force` (S1),
  `agent_new`, `agent_threads`, `agent_next_waiting` (S3). `_dupes` enforces uniqueness per
  scope, and `_GENERATED_DEFAULT_MIGRATIONS` needs nothing for new actions.
- Palette (`21_similar.js:239`): eight agent rows, one of which focuses `#agentsteer` and must
  change in S1. Rows for thread switching arrive automatically from labelled keys.
- Agent head (`app.py:618`): new chat, history, memory, state, expand. The dropdown replaces the
  static `state active` badge next to the status dot with title, model, turns and cost, which
  are already on the `done` event and in `status()`.
- Runstrip (`12_agent.js:1169`): already per-run, with Stop per row including sub-agents. It
  becomes per-thread rather than a second surface. Note that the rewrite dropped the click to
  scroll to a waiting approval; the attention bar in S4 restores that affordance.
- Modals (`20_overlays.js:2`): `modal()` now supports `beforeClose` and `requestClose`, which
  the thread rename and close dialogs should use rather than inventing their own.
- Workspace switcher (`20_overlays.js:258`): lists other workspaces and says nothing about
  them. S5's dots go here rather than in a new menu.

## Risks

- **The S2 rewrite is the risky one.** Every event the pane draws flows through the route being
  replaced, and it inverts a contract that was hardened this week. Do it single-threaded, with
  the replay tests green, before S3 adds a second thread.
- **History convergence.** Without `refresh_history` the panel silently omits other threads'
  turns. S0b carries it, so S3 cannot ship without it.
- **Engine contention.** Threads share the `EngineBroker` (`ai.py:689`), and
  `runtime.py:632` declines a second generation on a busy engine rather than queueing it.
  Two local turns will serialise, and one of them will be told so. Measure before promising
  parallelism on local models; the cloud path is unaffected.
- **Detached runs.** A cancelled provider call that does not stop within `cancel_grace` is
  marked detached and its backend is dropped from the pool (`_release_run`). With threads there
  can be several of those at once. Rishi closes live Claude sessions at exit
  (`rishi/claude.py:272` onward), which bounds the worst case to the process lifetime, not beyond it.
- **Cost.** Six live conversations is six contexts against the same budget. The rail shows
  per-thread usage from `session_usage`, which already exists on the `done` event.
