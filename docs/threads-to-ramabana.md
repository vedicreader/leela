# Moving the server-owned turn feed into ramabana

`Feed`, `TurnError`, `Thread`, `Threads` and `TurnRunner` can move to a new `ramabana.threads`,
behind one new abstract base class on ramabana's side. Shalya needs one cell. The fourteen
`Workspace` reaches collapse to five methods and one hook: eleven of them are three questions
wearing fourteen hats, which are *make me an assistant*, *run a turn in it*, and *keep what the turn
emitted*. Of the roughly forty reaches onto `ai`, all but four are already ramabana `Agent` API.

Read section 8 before starting. Two of its three findings are real and one changes the shape of the
move.

## 1. Inventory

### 1.1 `threads.py` onto `Workspace`

`a` is agent-core, `b` is Leela-specific and stays behind a protocol, `c` is already available from
shalya's `Host` or ramabana's `Agent`.

| line(s) | reach | class | lands as |
|---|---|---|---|
| 100, 219 | `workspace.approvals_mode` | b | `AgentApp.new_agent()` |
| 101, 221 | `workspace.model` | b | `AgentApp.new_agent()` |
| 102, 222 | `workspace.local_multimodal` | b | `AgentApp.new_agent()` |
| 102, 222 | `workspace._compacted` | b | `AgentApp.new_agent()` |
| 104 | `workspace.sync_agent_routing(self.ai)` | b | `AgentApp.new_agent()` |
| 122 | `workspace.threads.active_id` | a | `Thread.owner.active_id`, its own registry |
| 163, 165, 170, 248, 253, 404, 455, 506 | `workspace._ai` | b | `AgentApp.activated(thread)` |
| 163, 164, 170, 248, 253 | `workspace._turn_runner` | b | `AgentApp.activated(thread)` |
| 225 | `workspace.fresh_history(source.ai)` | a | `Agent.fresh_history()` |
| 228 | `workspace.guard_history(reason)` | b | `AgentApp.guard(agent, reason)` |
| 267 | `getattr(workspace, 'approvals', None)` | b | deleted: `Thread` always passes `approvals` |
| 329 | `workspace.save_timeline(sid, turn_id, parts)` | b | `AgentApp.retain(thread_id, turn_id, rows)` |
| 345, 464 | `workspace.ai` | b | deleted: `self.ai` is always set by `Thread` |
| 356 | `workspace.ask_stream(...)` | b | `AgentApp.stream(agent, prompt, **kw)` |

Five of the fourteen are one constructor call, two are one activation hook, two are dead fallbacks.

### 1.2 `threads.py` onto `Agent` and `Approvals`

Class `c`, already ramabana: `set_model`, `host`, `session_id`, `busy`, `run`, `set_muted`,
`session_meta`, `sessions`, `current_branch_id`, `close`, `history`, `refresh_history`,
`resume_session`, `approvals`, `set_title`, `compactor.count/.strategy/.note/.last`, `runs`,
`activity.rows`/`activity._mark`, `current_turn_id`, `ready`, `note`, `turn_use`, `use`,
`model.name`, `problems`, `changes()`, `summarize_session`, `cancel`, `Ask.dict()`,
`approvals.pending`, `approvals.listen()`.

The only four that are not ramabana today:

| line | reach | owner | disposition |
|---|---|---|---|
| 231 | `ai.mark_surface()` | Leela `Assistant` | `AgentApp.resumed(agent)`, default no-op |
| 316 | `ai.turn_capabilities(turn_id)` | Leela `Assistant` | split, see 4.3 |
| 315 | `turn_media(ai)` reading `ai.turn_media` | Leela `Assistant` | fall back to `Agent.last_media` |
| 284, 339 | `self.approvals.state()` | Leela `Interventions` | `getattr(approvals, 'state', dict)()` |

### 1.3 `threads.py` onto the Leela package

| line | reach | class | disposition |
|---|---|---|---|
| 6 | `from ... import errstr` | c | `shalya.core.host_err` is byte-identical |
| 7 | `from .turns import edit_diffs, tool_schemas, turn_media` | mixed | those three move, the rest does not |
| 97, 217 | `from .ai import Assistant, Interventions, WRITE_TOOLS` | b | vanishes behind `new_agent()` |

### 1.4 `turns.py`

| line | reach | class | disposition |
|---|---|---|---|
| 10 | `leela.core.web.diff_payload` | b now, c after 3 | `shalya.core.diff_rows` |
| 54 | `ws.fs.walk(limit=max_files)` | b | `Host.walk()` takes no `limit`. Stays in Leela. |
| 61 | `ws.fs.read(path)` | c | `Host.read` |
| 69 | `ws.fs.roots` | c | `Host.roots` |
| 78, 84, 91 | `agent.host.text_at(path)` | c | `Host.text_at` |
| 81 | `from ...agent.tools import _cmds` | c | `shalya.core.cmds`, and a `CLAUDE.md` violation today |
| 89 | `from ...agent.tools import _apply_edits, _edits` | c | `shalya.core.apply_edits`, `shalya.core.edits` |
| 164 | `from .ai import WRITE_TOOLS` inside `tool_schemas` | b | becomes a `writes=` parameter |
| 15, 26, 34 | `SURFACES_FILE`, the `cfg` sidecar | b | Leela's own surface mark. Stays. |
| 155 | `a.changes()` in `edit_diffs` | c | `Agent.changes` |

Lines 81 and 89 reach `ramabana.tools._cmds`, a private alias in a re-export module `CLAUDE.md` says
not to reach through. Fix that regardless of whether this move happens.

## 2. The protocol

It is not a shalya capability group. It is a ramabana-side ABC built in shalya's shape.

The reason is mechanical. `shalya/tools.py:680` pairs each group name with a tool factory, and
`tools_for` at `:693` is `[t for g, f in GROUPS if host.can(g) for t in f(host, mx)]`. A capability
group is a tool-construction contract: declaring one means `tools_for` builds those tools and the
model sees those schemas. Nothing a `Thread` asks its workspace for is a tool. `save_timeline` never
reaches a model, and `ask_stream` is the thing that drives the model. A `ThreadHost` group would be
the first entry in `GROUPS` with no factory, `Host.provides` would return a name nothing consults,
and `nbs/01_host.ipynb` cell `b8cfad34` would need a carve-out. That is the pattern breaking, not
the pattern being followed.

Leela's `WorkspaceHost` (`ai.py:263`) and Leela's `Workspace` are also different objects. The host
is what tools call, the workspace is what owns conversations. Putting conversation ownership on the
host forces `WorkspaceHost` to hold a `Threads` it has no business knowing about.

What to build instead, copying shalya's structure:

    class AgentApp(ABC):
        "The application that owns conversations: how it makes one, runs a turn, and keeps what a turn emitted."
        @abstractmethod
        def new_agent(self): ...                       # -> (agent, approvals)
        @abstractmethod
        def stream(self, agent, prompt, **kw): ...     # -> iterator of str
        @abstractmethod
        def retain(self, thread_id, turn_id, rows): ...
        def guard(self, agent, reason=''): return None
        def activated(self, thread): pass
        def resumed(self, agent): pass

Three abstract, three hooks with no-op defaults. `LocalApp` implements the three over `Agent(...)`,
`agent.stream_with(...)` and a JSON file beside `agent.sessions_path`. Same inheritance-declares,
same construct-time refusal from `ABCMeta`, same `Local*` naming as `LocalHost`.

No `provides`, no `can`, no group registry. There is one contract, not nine, so there is nothing to
ask about. Copying shalya's pattern here means copying its mechanism, not its vocabulary: `provides`
exists because `tools_for` branches, and nothing here branches.

`AgentApp` rather than a second `Host`: `Host` is "the application under an agent", and this is the
application around it.

## 3. Shalya, one cell

`nbs/00_core.ipynb`, one `#| export` cell after cell `c6041489`, the `diff_text` cell.

- `DiffRow`, a `path`-free `kind`/`text`/`line` dataclass with `.dict()`; `diff_rows(before, after)`;
  `diff_label(before, after)`. Ported from `leela/core/text.py:17-53`.
- `diff_view(before, after)` returning `{'label', 'rows'}`, so callers do not each re-assemble it.
- `shalya.core` already owns the unified-diff producer at `:195`. `diff_rows` is the same diff in the
  structured form a surface paints, and it has two callers outside Leela: ramabana's `preview_for`
  (`agent.py:229`), which returns raw text for an edit, and `racp.Session._body` (`racp.py:249`),
  which can only send a diff for `create_file`.
- Two companion cells: one markdown paragraph, one `test_eq` over an add/delete/context triple
  pinning that `line` counts against the new text.

Do not add `limit=` to `Host.walk`. It is the only thing blocking `project_state_context` from being
host-shaped, and that function is not part of this move. Named here so it is a decision rather than
an oversight.

## 4. Ramabana

### 4.1 New notebook `nbs/18_threads.ipynb`

`#| default_exp threads`. `03_agent.ipynb` is 359 cells; this does not go in it.

Export cells in order: imports and `TERMINAL_CANCEL`; `Feed` verbatim from `threads.py:11-79`;
`TurnError` verbatim from `:82-93`; `AgentApp` and `LocalApp`; `Thread` from `:96-157` with
`__init__(self, app, ai=None, approvals=None, feed=None, owner=None)`; `Threads` from `:160-258`
with `__init__(self, app, limit=6, adopt=None)`; `TurnRunner` from `:261-511`; then
`tool_schemas(agent, writes=(), group=None)`, `edit_diffs(agent)` and `turn_media(agent)` from
`turns.py:159-181, 154-155, 183-192`.

Two markdown cells have to exist. One names the distinction between `Activity`, the tool-call stream
inside a turn, and `Feed`, the numbered replayable log around turns; without it two things in one
package are called the feed. The other says why `AgentApp` is not a shalya group.

Notebook tests, `test_eq` style, no model: `Feed` emit, `since`, resync after the deque rolls,
`settle`, `finished`, a `user` event resetting `settled_seq`; `Feed.anext` waking without a worker
thread; an `AgentApp` with an unwritten abstract method refusing to construct, mirroring
`01_host.ipynb` cell `aecd5d77`; `LocalApp` plus `fake_agent` driving one whole turn into a `Feed`.

### 4.2 `nbs/03_agent.ipynb`, cell `d29d008a`

`Agent.fresh_history()`: reread the log only when its `mtime_ns:size` stamp moved. This is
`workspace.py:361-368` plus `history_stamp` at `:353-359`, and it is about `Agent.history_path` and
nothing else. Leela's `Workspace.fresh_history` becomes a one-line forward for one release. Test
cell: write the log twice with the same content and assert one reread, touch it and assert a second.

### 4.3 `nbs/03_agent.ipynb`, near cell `f47f136e`

`Agent.turn_capabilities(turn_id)` returning the half ramabana can answer from `self.checkpoints`:
`revisable`, `branchable`, `known`. Leela's `Assistant.turn_capabilities` (`ai.py:965-974`) becomes
`{**super().turn_capabilities(turn_id), 'undoable': ..., 'files': ..., 'irreversible': ...}`, since
only Leela has `turn_transactions`.

### 4.4 `ramabana/tools.py`, `ramabana/git.py`

Nothing. Leela imports `ramabana.threads` by name, the same rule as shalya and gheasy.

## 5. What stays in Leela

`turns.py` keeps everything except the three functions in 4.1.

- `SURFACES_FILE`, `surfaces`, `mark_surface`, `latest_started_here`: the mark that says a session
  was started by Leela and not by the CLI. It exists to distinguish Leela from ramabana, so it
  cannot live in ramabana without inverting its meaning.
- `history_sessions`: tags each group from that same mark.
- `project_state_context`: reaches `ws.fs.walk(limit=)`, which `Host` cannot express.
- `TOOL_GROUPS`, `tool_group`: a browser taxonomy over Leela's tool names. Ramabana already has
  `Act.kind` (`agent.py:83-84`) and `racp.KIND`/`racp.TOOL`; a fourth would be worse than leaving
  this one beside its consumer. `tool_schemas(agent, group=tool_group)` is how it reaches the moved
  function.
- `tool_preview`: repoint its imports at `shalya.core` and pin that with a test, do not move it.
- `activity_changes`, `with_capabilities`: single-caller helpers.

`threads.py` becomes a thin module holding `LeelaApp(AgentApp)` and re-exporting `Feed`,
`TurnError`, `Thread`, `Threads`, `TurnRunner` and `TERMINAL_CANCEL`, so `app.py`'s eight import
sites at `:17, 57, 138, 765, 848` do not move. `LeelaApp.new_agent` is `ai.py:101-104` and
`:219-224`; `stream` is `workspace.ask_stream`; `retain` is `workspace.save_timeline` including
`_retained` (`workspace.py:322-336`) and `TIMELINE_KEEP`; `guard` is `workspace.guard_history`;
`activated` writes `_ai`/`_turn_runner`; `resumed` calls `agent.mark_surface()`.

All of `blocks/agent/app.py` stays: routes, SSE, `off_loop`, the `TurnError` to 409 mapping.
Ramabana ships no HTTP surface for this.

`Threads.dicts()` (`:180-185`) hides untitled idle conversations, which is a Leela card rule. Move
the method and expect Leela to override it.

`leela/core/text.py` keeps the diff helpers as re-exports from `shalya.core` for one release, so the
eleven `diff_payload` call sites are untouched.

## 6. Tests

### Ramabana notebook

The cells listed in 4.1. Notebooks carry the readable examples, `tests/` asserts contracts in bulk.

### Ramabana `tests/test_threads.py`, new

Ported from `leela/tests/blocks/test_agent_threads.py`. Each name is the regression it pins.

| ported from | pins |
|---|---|
| `:40` | a browser that missed events gets `resync`, and `settled_seq` resets on a new `user` event |
| `:53` | `close()` wakes a waiter instead of stranding it |
| `:603` | `anext` does not park a shared pool thread for its whole wait |
| `:614` | a finite subscriber leaves a producer that never settles |
| `:103` | attachments are snapshotted at accept, not read later |
| `:119` | the `current_turn_id != before` guard in `_watch` |
| `:144` | `_retain`'s `== before` early return keeps the previous timeline |
| `:164` | error then exactly one `done` |
| `:181` | acceptance lands before the first chunk |
| `:197` | a late registration is cancelled through `run.cancel()`, not `ai.cancel` |
| `:213`, `:516` | `thread_busy` before any `user` event reaches the feed |
| `:241`, `:275` | `turn_conflict` carries the reason and the pane stays usable |
| `:262`, `:1407`, `:1425`, `:1434` | `_reap` drops a dead worker and a quiet stale turn |
| `:321`, `:338` | stop cancels the live root, and leaves a finished root's live sub-agent alone |
| `:349`, `:365` | a closed feed refuses registration and cancels the run |
| `:375` | `_done`'s per-key failure becomes a `problems` entry, not a lost event |
| `:541`, `:561` | no chunk before acceptance; a finished run is announced only by `done` |
| `:776`, `:790`, `:826` | LRU eviction, `no_evictable_thread`, no retarget of a resolved thread |
| `:869`, `:891` | unread only for an unwatched conversation, and the attention aggregate |
| `:1013` | `shutdown` returns problems rather than raising |
| new | `AgentApp` with a missing abstract method refuses to construct |
| new | `LocalApp.retain` round-trips through its own file |

### Ramabana, two additions rather than a new file

`tests/test_resume.py`: `fresh_history` rereads only when the stamp moved. `tests/test_turn.py`:
`turn_capabilities` on a checkpointed turn and on an unknown id.

### Shalya `nbs/00_core.ipynb`

`diff_rows` line numbering across a hunk boundary; `diff_label` on identical inputs is `''`.

### Leela

`tests/blocks/test_agent_threads.py` stays, but narrows to the seam and the routes.

- Keep unchanged: every `client.get('/agent/threads')` test at `:391, 481, 837, 1197, 1219, 1237,
  1273`, the branch/shape/undo group `:932-1044`, the boot-resume group `:1546-1584`.
- Keep as seam tests: `:11` becomes the `LeelaApp.activated` contract; `:645, 658, 682` pin
  `LeelaApp.retain`; `:1392` becomes a forwarding test to `Agent.fresh_history`; `:1546, 1567` pin
  the `mark_surface` filter through `LeelaApp.resumed`.
- Delete once the ramabana port lands: the pure-`Feed` and pure-`TurnRunner` unit tests above.
  Keeping both copies means two suites drift and one is not run by ramabana's CI.
- Rewrite, because they assert file text: `tests/test_backups.py:224-229` reads `threads.py` source
  and asserts `guard_history` appears before `resume_session(`; make it a `LeelaApp` double
  recording call order. `tests/blocks/test_agent_threads.py:590-600` asserts a source substring;
  make it an approval event carrying a non-empty `schemas` list.
- `tests/blocks/test_agent_block.py:80-95` asserts `TOOL_GROUPS`, `tool_group` and `tool_preview`
  have exactly one home in `turns.py`. All three stay, so it should pass unchanged. Confirm rather
  than assume.
- New: `LeelaApp` satisfies `AgentApp`, which is the whole enforcement mechanism; `tool_preview`
  reaches `shalya.core` and not `ramabana.tools._cmds`; `leela.blocks.agent.threads` still exports
  the six names `app.py` imports.
- Re-run untouched: `tests/test_agent.py`, `tests/test_web.py:420, 610, 674, 1498`,
  `tests/blocks/test_agent_block.py:74, 100, 131`, `tests/test_backups.py`.

## 7. Sequencing

Leela pins `ramabana[cli]==0.1.32` and `shalya>=0.0.5` from PyPI (`pyproject.toml:30, 35`). Nothing
in Leela can point at a moved name until a release ships.

1. Shalya: the `diff_rows` cell. Export, test, clean. Release **0.0.6** with the refactor work
   already on the branch.
2. Ramabana: `Agent.fresh_history` and `Agent.turn_capabilities`. Additive, no caller changes. Bump
   the shalya floor to `>=0.0.6`.
3. Ramabana: `nbs/18_threads.ipynb` and `tests/test_threads.py`.
4. Ramabana release **0.1.33**. This is the gate; nothing below can start before it.
5. Leela: bump to `ramabana[cli]==0.1.33`, `shalya>=0.0.6`, regenerate `uv.lock`. One commit, no
   behaviour.
6. Leela: rewrite `blocks/agent/threads.py` to hold `LeelaApp` and re-export. Delete the ported test
   bodies, rewrite the three source-text tests. Full `pytest`, including `-m slow`.
7. Leela: `turns.py` cleanup. `diff_payload` to `shalya.core.diff_view`, the three private aliases to
   `shalya.core`, `tool_schemas` forwarded with `writes=WRITE_TOOLS, group=tool_group`.
8. Leela: `docs/chat-threads-implementation.md` and `docs/integration.md` name the new seam, and
   `CLAUDE.md`'s "what lives where" gains one sentence.

Steps 1 to 4 land in the upstream repos alone. Steps 5 to 8 are the Leela half and cannot be
interleaved. If step 4 slips, nothing in Leela is half-migrated.

Do not reach for a `[tool.uv.sources]` local override to skip the release gate. The 0.1.32 changelog
records that those overrides were deliberately removed.

## 8. What contradicts the premise

### 8.1 Nothing in ramabana would use this on the day it lands

Ramabana has two turn-driving surfaces and neither wants a `Feed`. `cli.Ui` (`cli.py:706`) is a
local terminal: if the process dies the terminal is gone, so there is nothing to replay to.
`racp.Session` (`racp.py:185`) pushes to a connected editor over live JSON-RPC, and ACP has no
resume-after-restart. `Feed` exists so a browser that missed events can ask to replay, and that has
no consumer in ramabana on day one. `ramabana/threads.py` would be a module ramabana maintains and
Leela alone runs, which is the alias-not-copy seam pointing the wrong way.

There is one latent consumer. `ramabana mcp --transport sse|streamable-http` (`mcp.py:126`) already
serves over HTTP, and `_mount_ask` (`:99`) is a whole turn behind one call whose tool loop is
discarded. A `Feed` is what would let it report progress instead of blocking. Nobody has asked for
it.

Recommendation: move it, and commit to rewriting `racp.Session._act`/`_send` over `Feed` in the same
release or the next. `Session` hand-rolls the same problem today: `self.seen` is an ad-hoc dedupe of
what `Feed.since` does properly, and `_act` re-derives per-call state `_watch` already computes. If
that rewrite is not going to happen, the defensible split is smaller: move `Feed` and `TurnError`
into `ramabana.core`, roughly 90 generic lines with no Leela reaches, add `AgentApp` to
`ramabana.agent`, and leave `Thread`, `Threads` and `TurnRunner` in Leela behind the protocol. Decide
which before writing the notebook.

### 8.2 `Threads` carries Leela product decisions

`limit=6` is a parameter and fine. But `dicts()` (`:180-185`) hides untitled idle conversations
because that is Leela's card rule, `finished_turn` (`:121-124`) increments `unread` only for an
unwatched conversation because that is Leela's badge rule, and `attention()` (`:187-191`) is shaped
for Leela's attention bar. Moving these exports one frontend's decisions as a library default, and
the next frontend inherits them by accident. Mitigation is in section 5: move the methods, expect
Leela to override `dicts()`, and say in the notebook that `unread` is a hint and not a contract.

### 8.3 The `Threads.__init__` adoption branch is dead

`threads.py:163-167` reads `workspace._ai` and `workspace._turn_runner` to adopt a pre-existing
assistant. Every assignment to those two names: `workspace.py:237-238` sets them to `None` at
construction, and the only other writers are `Threads._activate` (`:170`), `Threads.close` (`:248`)
and `Threads.shutdown` (`:253`), all of which run after `Threads.__init__`. In shipping Leela the
branch cannot fire. The only callers that make it fire are four tests injecting a fake runner
(`test_agent.py:1446, 1722, 1737`, `test_agent_threads.py:496, 630`).

It is a test seam wearing a compatibility shim. Port it as an explicit `Threads(app, adopt=(ai,
runner))` and change those four tests. Porting it unchanged carries a branch into ramabana that
ramabana can never reach.
