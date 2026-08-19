# Chat threads: turns that outlive the tab

The agent pane has one conversation, owned by whichever browser tab opened it. This is the
implementation spec for making it several conversations, owned by the server, with titles, a
list of what is running, notifications across them, and steering folded into the composer.

It replans an earlier pass that could only read Leela. Ramabana and Rishi are readable here, and
three of that pass's premises turn out to be wrong.

## What is true today

- `Workspace.ai` builds one `Assistant` lazily and holds it forever (`workspace.py:197`).
  `/agent/new` throws that object away and closes it (`app.py:1691`).
- The turn belongs to the tab. `/agent/stream` runs `ws.ask_stream` on an executor and its
  `finally` calls `a.cancel()` whenever the request disconnects (`app.py:2079`). Closing the
  EventSource is how a turn ends, so nothing can finish while you are elsewhere.
- `Agent.busy` is one lock per `Agent` (`ramabana/agent.py:1161`), so two `Assistant` objects
  can already run at once. Nothing builds a second one.
- Approvals are a queue of one. `Approvals.current` is a single slot
  (`ramabana/agent.py:394`), `Interventions` inherits it (`ai.py:92`), and one `Interventions`
  is shared by the agent pane and the prompt cells (`workspace.py:195`, 206, 216).
- Sessions have no title in Leela. `_history_sessions` groups turns by session id and keeps
  start, end, models, turn count and kernel runs (`app.py:292`); the picker labels each one
  with a timestamp (`12_agent.js:584`).
- Steering is a second input with Queue and Force buttons (`app.py:658`), a chip above it, and
  a main composer that refuses to send while busy (`12_agent.js:1565`, `app.py:2092`). A steer
  never appears in the transcript.
- `approvalLoop` polls `/agent/approval` only when the window is visible and only for this
  workspace (`12_agent.js:1228`).
- The agent keymap is three actions: `agent_send`, `agent_stop`, `agent_tools`
  (`core/keys.py:219`). The palette adds eight hardcoded agent rows (`21_similar.js:239`).

## Four corrections to the earlier plan

1. **Rishi cancels.** `Chat.cancel` sets a cooperative event that the loops honour between
   chunks and between tool calls (`rishi/core.py:853`), and the backends check it mid-stream
   (`rishi/remote.py:266`, `rishi/claude.py:370`). The docstring on `Assistant.cancel`
   (`ai.py:729`) says Rishi has no `cancel`; that has been stale since Rishi 0.1.19. Stop is a
   real interrupt today, so force-steer's stop-then-resend does not need rebuilding, and the
   docstring should be corrected in whichever slice touches that file.
2. **Ramabana already derives a title.** `Agent.sessions()` returns one per session, cut from
   the first prompt at 72 characters (`ramabana/agent.py:1354`). Leela's `_history_sessions`
   recomputes the grouping from raw turns and drops it. Titling is a plumbing fix plus a
   summary pass, not new machinery.
3. **The approval collision exists now.** Because one `Interventions` serves both the agent
   pane and prompt cells, a prompt cell that proposes a write while the pane is mid-turn
   already overwrites `current`. Moving approvals onto the conversation fixes a live bug, not
   only a future one.
4. **Cross-workspace state costs nothing.** Under `--app` every workspace is a `WorkspaceSite`
   in one process (`app.py:2395`), so `hub.catalog()` can read each `Workspace` directly. No
   HTTP fan-out, no polling between sites. `WorkspaceSite` needs one more field.

One thing the earlier plan did not reach: history is a single JSONL per `history_name`
(`ramabana/agent.py:1322`), loaded into memory once per `Agent`. Two live threads append to the
same file and neither sees the other's turns, so the history panel goes stale as soon as a
second thread exists.

## Decisions

| | Question | Recommendation |
|---|---|---|
| D1 | Is a chat thread the same noun as `docs/parallel-threads.md`'s worktree thread? | Yes. One board, one word. Build the rail so a worktree thread is another row kind, and ship chat rows first. |
| D2 | Does the event buffer live in Leela or Ramabana? | Leela. The event shapes carry tool schemas and data URLs, which are frontend concerns. Ramabana gets titles and nothing else. |
| D3 | How many live threads? | Six, with idle least-recently-used eviction. A closed thread is still resumable from history. Never evict one that is working or waiting on a person. |
| D4 | Rail shape? | A dropdown from the chat head, plus an attention bar that appears only when another thread wants something. A permanent strip costs width the pane does not have. |
| D5 | Keep `/agent/stream?prompt=`? | No. The browser is the only client; the route stays, its contract changes. |
| D6 | Native notifications in the packaged shell? | Later. Web `Notification` covers the Chrome shell, which is the shipped default. |

## The design

### Thread

One `Thread` is one `Assistant`, one Ramabana session id, one approvals queue, and one event
feed. `leela/blocks/agent/threads.py`, new:

```python
class Thread:
    id          # the Assistant's session_id
    ai          # Assistant, with its own Interventions
    feed        # Feed, below
    title       # from Ramabana's session sidecar
    state       # idle | working | waiting | failed
    unread      # turns finished since this thread was last read
    muted
    created, last_active
```

`Threads` is the registry on `Workspace`: `new()`, `get(id)`, `resume(session_id)`, `close(id)`,
`active`, `rows()`. `ws.ai` stays as a property returning `ws.threads.active.ai`, because sixty
call sites depend on it and none of them care which thread they are on.

Eviction is by D3. `refresh_history()` (new, Ramabana) is called on the active thread before
`/agent/history` answers, so the panel reflects every thread's turns.

### Feed

```python
class Feed:
    put(event, data) -> seq       # appends, wakes waiters
    since(n) -> [(seq, event, data)]
    wait(n, timeout) -> rows      # blocks until seq > n
```

A `deque(maxlen=2000)` and a `Condition`. Events are the ones the SSE route already emits
(`chunk`, `activity`, `execution`, `approval`, `compaction`, `error`, `done`) plus four new
ones: `user` (the prompt, so a reconnecting tab sees its own message), `steer`, `title`,
`state`. When `since` is older than the oldest retained row the feed answers `resync`, and the
browser refetches the transcript rather than rendering a hole.

The runner is a plain `threading.Thread` named `leela-turn-<id>`, as `Jobs.launch` does
(`blocks/vault/jobs.py:107`). It must not use `off_loop`'s shared executor: six agents holding
workers at long timeouts is the starvation `docs/parallel-threads.md` predicts.

### Approvals per thread

Each `Thread` builds its own `Interventions`, with `on_ask` and `on_answer` writing an
`approval` event into that thread's feed. `ws.approvals` stays as the prompt-cell queue, since
`notebook_approvals` exists to write into a notebook and only `ask_cell_stream` ever sets a
target. Every route that reads `ws.approvals` takes a `thread` parameter defaulting to the
active one: `/agent/approval`, `/agent/approve`, `/agent/control`, `/agent/run-policy`,
`/agent/steer`, `/agent/approval/request`, `/agent/rollback-tool`. That is twenty call sites in
`app.py` and four in `workspace.py`.

`/agent/approval` also returns `waiting: [thread ids]`, which is what the attention bar and the
badge read.

### Titles

Ramabana, `nbs/03_agent.ipynb`:

- A sidecar beside the history log, `{history_name}-sessions.json`, holding
  `{sid: {title, title_turns, muted}}`.
- `Agent.set_title(text, sid=None)` and `Agent.session_meta(sid=None)`.
- `sessions()` merges the sidecar over the first-prompt title it already derives.
- `Agent.summarize_session(sid=None, force=False)`: one line from the `summary` job through
  `oneshot` (`ramabana/agent.py:1521`), over the session's first turns. Re-derives only when
  the turn count has doubled since `title_turns`, so a drifting conversation is renamed and a
  steady one is not re-summarised every turn.
- `Agent.refresh_history()`: re-read the JSONL, for the sibling-threads problem above.

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
`agent: {working, waiting, threads}`, `/workspace/info` passes it through
(`blocks/workspace/app.py:22`), and `leeWorkspaceMenu` (`20_overlays.js:253`) draws a dot per
workspace with a count on the pill.

### Steering in the composer

The cheapest large win, and the only slice that depends on nothing else.

Delete `#agentsteer`, `#agentsteerqueue`, Queue and Force (`app.py:658`). `/agent/steer` keeps
its contract, including the force path, and gains a `thread` parameter and a feed event.

- `sendAgent()` branches on `lee.agentBusy`: idle posts a turn, busy posts a steer.
- `agent_send` (mod+enter) sends or queues. A new `agent_steer_force` (mod+shift+enter)
  interrupts and sends now.
- The Send button relabels through Send, "Steer after this call", "Interrupt and send now", so
  the state is legible without a second control.
- The steer renders as a real user card in the transcript, dimmed with a Cancel while queued,
  undimmed when the model takes it. `Interventions` gains an `on_steer` callback fired from
  `queue_steer` and `consume_steer` (`ai.py:124`, 132), which the runner turns into the event.
  Conversation order stays intact, so reading the log later shows when you intervened.

## Slices

Each slice ships on its own. S1 can jump the queue.

### S0 Session titles (Ramabana)

`nbs/03_agent.ipynb` only: sidecar, `set_title`, `session_meta`, `summarize_session`,
`refresh_history`, `sessions()` merge. Then `nbdev-export`, `nbdev-test`, `pytest`.

Tests: an executable cell in the notebook for the merge and the doubling rule; a
`tests/test_agent.py` contract that a title survives a reload and that two `Agent`s on one
`history_name` converge after `refresh_history`.

### S1 Composer merge (Leela)

`app.py:618` panel, `12_agent.js` (`sendAgent`, `leeQueueSteer`, `leeForceSteer`,
`setQueuedSteer`, `updateAgentRunstrip`), `core/keys.py` for `agent_steer_force`,
`21_similar.js:248` whose palette row focuses an input that will not exist, `lee-ide.css` for
the dimmed steer card. Rebuild with `tools/build_ide_js.py`.

Tests: `tests/test_web.py` asserts the two inputs are gone and the relabelling exists in the JS
corpus; `tests/test_keys.py` covers the new chord and the duplicate check; `tests/test_agent.py`
covers a steer reaching the transcript in order and a cancel while queued.

### S2 Turn ownership (Leela)

`blocks/agent/threads.py` with `Feed` and the runner, `POST /agent/turn`, `/agent/stream`
rewritten to replay from `?since=`, disconnect no longer cancelling, `/agent/stop` unchanged.
One thread only, so the UI change is limited to reconnect. Add both routes to
`tests/routes.txt`.

Tests: a turn survives the subscriber closing; a reconnect with `since` replays exactly the
missed events; an overflowed buffer answers `resync`; `/agent/stop` still ends the turn.

### S3 Threads (Leela)

The registry, per-thread approvals, `/agent/threads`, `/agent/thread/new`,
`/agent/thread/close`, `/agent/thread/title`, `/agent/new` starting a thread instead of
refusing while busy, the head dropdown, and keys for new chat, next thread and next thread
wanting attention.

Tests: two threads run at once without sharing a checkpoint; an approval on one names its
thread; eviction never takes a working or waiting thread; `ws.ai` still resolves.

### S4 Notifications (Leela)

Attention bar, unread counts, `document.title`, the `Notification` setting, per-thread mute.

Tests: a completed turn on a background thread raises exactly one notification; a muted thread
raises none; the title prefix tracks the working count.

### S5 One work-in-flight surface (Leela)

`WorkspaceSite.ws`, catalog agent state, the switcher dots, and a footer row on the rail for
vault jobs, video jobs and delegated sub-agents, each linking to where it already lives.
Native `ShellApi.notify` if D6 flips.

## Audit of what already exists

Required before adding a shortcut, panel or setting.

- Keymap (`core/keys.py`): `agent_send`, `agent_stop`, `agent_tools` in the agent scope,
  `focus_agent`, `agent_selection` and `toggle_right` global. New: `agent_steer_force` (S1),
  `agent_new`, `agent_threads`, `agent_next_waiting` (S3). `_dupes` enforces uniqueness per
  scope and `_GENERATED_DEFAULT_MIGRATIONS` needs nothing for new actions.
- Palette (`21_similar.js:239`): eight agent rows, one of which focuses `#agentsteer` and must
  change in S1. New rows for thread switching arrive automatically from labelled keys.
- Agent head (`app.py:618`): new chat, history, memory, state, expand. The dropdown replaces the
  static `state active` badge next to the status dot with title, model, turns and cost, which
  are already on the `done` event and in `status()`.
- Workspace switcher (`20_overlays.js:253`): lists other workspaces and says nothing about
  them. S5's dots go here rather than in a new menu.
- Runstrip (`12_agent.js:1146`): already the per-turn state line. It becomes per-thread rather
  than a second surface.

## Risks

- **The S2 rewrite is the risky one.** Every event the pane draws flows through the route being
  replaced. Do it single-threaded, with the replay tests green, before S3 adds a second thread.
- **History convergence.** Without `refresh_history` the panel silently omits other threads'
  turns. S0 carries it, so S3 cannot ship without it.
- **Engine contention.** Threads share the `EngineBroker` (`ai.py:689`). Two local turns on one
  LiteRT engine will serialise. Measure before promising parallelism on local models; the cloud
  path is unaffected.
- **Cost.** Six live conversations is six contexts against the same budget. The rail shows
  per-thread usage from `session_usage`, which already exists on the `done` event.
