# Making leela's assistant an agent

A plan for turning `leela.ai` — one Rishi chat with fifteen tools — into a coding agent
that can reach cloud models, spend cheap tokens on cheap work, survive a long
conversation, learn the skills of whatever is installed, and be extended without a fork.

Written after reading, in full: [rishi](https://pypi.org/project/rishi/) `0.0.2`,
[fastllm](https://github.com/AnswerDotAI/fastllm),
[aidialog](https://github.com/AnswerDotAI/aidialog),
[aai-coding](https://github.com/AnswerDotAI/aai-coding), and
[tau](https://github.com/huggingface/tau). The point of the exercise was to find what is
*genuinely new* for leela rather than what merely sounds like a feature, so the first
section is about what we already have and must not rebuild.

---

## 1. What leela already has

Rishi is a fastllm-shaped `Chat` over `litert_lm` — local Gemma, on device, synchronous.
Reading it against fastllm and tau, most of what a coding agent needs is already under us:

| Capability | Where it already lives |
| --- | --- |
| Tool loop, schemas from type hints + docstrings | `rishi.core.Chat`, `ChatToolHandler` |
| Human-in-the-loop tool approval | `rishi.core.hitl_policy` → `ai.confirm_writes` |
| Ordered callbacks (`before_send`, `after_response`, `before_tool_calls`, …) | `rishi.core.ChatCallback` |
| Token usage, `pct_full`, cancel, tokenize | `rishi.core.UsageStats`, `Chat.cancel` |
| Streaming + markdown formatting of thinking/tool calls | `rishi.core.StreamFormatter` |
| One-shot classify / structured output / LLM-judge | `Chat.classify`, `Chat.structured`, `Chat.grades` |
| Multimodal input | `mk_content` sniffs image/audio bytes; `ai.ask_with` uses it |
| Sandboxed python-fence execution | `Chat.run_py`, `PyFenceCallback`, `safepyrun` |
| Code search over the repo *and installed packages* | `leela.search` over kosha |
| Hash-verified editing that fails on a stale read | exhash, via `edit_file` / `edit_cell` |
| Restricted execution over the user's live namespace | `leela.inspect.agent.AgentSession` |
| Per-turn diff of what actually changed on disk | `Assistant.changes()` |
| Transcript notebook of every attempted cell | `AgentSession._log`, `conversation_logger` |
| Replies stored *in* the notebook, re-runnable | `nb.Cell.reply`, `Workspace.ask_cell` |

That is a lot. Tau's `tau_agent` is mostly an implementation of the top half of this
table, so **we should port ideas from tau, not code.** The same goes for fastllm's chat
loop: we want its *reach* (providers, pricing, caching), not a second callback system.

Two things in the table are worth calling out because they are already halfway to
features below:

- `ai.system_prompt` quotes `exhash.skill.__doc__` verbatim into the briefing. That is a
  hand-wired **pyskill**, one package deep. §5 generalises it.
- `leela.inspect.agent.load_inspectors` already loads user Python from
  `~/.config/leela/inspectors.py` and merges it into a policy. That is a hand-wired
  **extension point**, one hook deep. §7 generalises it.

Both features already exist as a special case. Neither needs a new concept — only the
general version of one we shipped.

---

## 2. The gaps, ranked

Ordered by how much each changes the feel of using leela, not by how hard it is.

### 2.1 Cloud models (fastllm) — the unlock

Rishi is local-only, and a 2–4B on-device Gemma cannot drive a multi-step edit loop over
a real repo. `python-fastllm` is the same shape from the same lineage: `AsyncChat(model,
sp=, tools=, hist=, cbs=)`, ordered `ChatCallback`s, `UsageStats`, `StreamFormatter`,
`structured`. Its tool contract is `toolslm`'s `get_schema` — plain functions with type
hints and docstrings, *exactly what `ide_tools` already returns*. The fifteen tools move
across untouched.

Three real differences to design around, not around which to hand-wave:

1. **fastllm is async, Rishi is sync.** Both frontends already call the assistant through
   a worker (`asyncio.to_thread` in the TUI, `_off_loop` in the web app), so there is no
   running loop on the calling thread and Rishi's own `run_coro` idiom drives the async
   chat from sync code. The facade stays sync; nothing above `leela/agent/` changes.
2. **fastllm has no tool approval.** Its `_call` fires tools through `parallel_async`
   with no gate. `confirm_writes` therefore cannot be a `hitl_policy` on that path — it
   becomes a `before_tool_calls` callback that filters the call list. This is the one
   place Rishi is genuinely ahead, and worth contributing back (§8).
3. **`Completer` reaches into `chat.engine.create_conversation`.** That is litert's API,
   not a shared one. It needs a `oneshot(sp, prompt, max_tokens)` method on the backend
   protocol — the throwaway-conversation trick generalised.

### 2.2 Routing cheap work to the local model — the genuinely new bit

Nothing in the reference set does this. Tau has `/model` and a provider catalog; aai-coding
has a table of short names; fastllm knows every model's price and context window. All of
them switch models *because a person asked*. None of them decide.

leela is unusually well placed to, because **it already knows what kind of question it is
asking.** The calls are separate code paths, not one undifferentiated chat:

| Job | Route | Why |
| --- | --- | --- |
| Inline completion (`Completer.complete`) | always local | four lines of code, must feel instant, fires constantly, costs nothing on-device |
| `classify` / title a session / summarise a diff | always local | one label out; a frontier model is pure waste |
| Compaction summary (§2.3) | local by default | it reads a transcript we already hold and writes prose |
| Sub-agent fan-out (§2.6) | local by default | "grep-and-report" burns tool results, not reasoning |
| The prompt cell / chat turn | cloud by default | this is the work |

Route by **job**, with an explicit override, and never by classifying the user's prompt
with another model call — that buys unpredictability and latency to save a few cents. The
policy is a dict from job name to model name and lives in config, so "use flash for
summaries" is one line and not a code change.

The delight here is concrete: the local engine is *already loaded* for completions, so
routing summaries and fan-out to it costs nothing extra and keeps them off the wire. A
laptop with no API key still gets a working, if slower, agent — which is the same promise
`Assistant.ready` already makes about the model being allowed to be missing.

### 2.3 Compaction

Neither Rishi nor fastllm has any. Rishi exposes `pct_full` and `ctx_limit` and *nothing
uses them*. Tau has the whole thing and it is the cleanest part of that codebase:
`context_window.py` gives a deterministic token estimate, a threshold at
`context_window - 16k`, a structured summary prompt (Goal / Constraints / Progress:
Done-InProgress-Blocked / Key Decisions / Next Steps / Critical Context), and — the part
people forget — a *separate* prompt for updating an existing summary rather than
summarising a summary. Port the prompts and the threshold arithmetic; skip its message
types, since we have fastllm's `Msg`/`Part` and Rishi's dicts.

The leela-specific twist, and the reason this is more than a port: **write the compaction
into the notebook.** When a prompt-cell conversation compacts, insert a markdown cell
carrying the summary. The user can read what the model chose to remember, edit it, and
re-run from there. Everywhere else compaction is an invisible event you discover by
noticing the agent forgot something; here it is a cell in a document you already own. It
also falls straight out of the design we have — a reply already lives in a cell.

Estimating tokens honestly is easy on both sides: Rishi has a real tokenizer
(`Chat.count_tokens`), fastllm reports real usage per request, and tau's 4-chars-per-token
estimate is the fallback for the not-yet-sent case.

### 2.4 Skills from installed packages (pyskills)

`aidialog` and `aai-coding` both publish this in `pyproject.toml`:

```toml
[project.entry-points.pyskills]
"aidialog.dlgskill" = "aidialog.dlgskill"
```

The convention: a skill is a **module docstring**, discovered through an entry-point group,
read with `doc()`. `aidialog.dlgskill`'s docstring is a fully-formed skill — how to read a
notebook, when to drop to raw JSON, which editing primitive fits which edit. `exhash.skill`
is another, and we already paste it into our system prompt by hand.

So: discover the `pyskills` entry-point group, plus `SKILL.md` files under
`.agents/skills/` and `~/.config/leela/skills/` (tau's precedence order, which is the
Agent Skills spec everyone now follows). Put only **names and one-line descriptions** in
the system prompt; give the model a `read_skill(name)` tool for the body. Progressive
disclosure — tau is explicit about this and it is right: a dozen full skill texts would
crowd out the code we actually want the model looking at.

Two things make this compound rather than merely work in leela:

- Our search index already covers installed packages. A skill that mentions
  `lnhashview_msg` is one `search_code` away from its implementation and every call site.
  Elsewhere a skill is prose about code the agent cannot see.
- Installing `aidialog` would hand our agent competent notebook-editing know-how **with
  no code written on our side**. That is the test of whether this feature is real, and it
  passes.

### 2.5 Extensions

Tau's shape is the right one and it costs almost nothing: a Python file defining
`setup(tau)`, discovered from `~/.tau/extensions/`, with project-local extensions **off
by default** behind an explicit flag because they execute arbitrary code from a repo you
may have just cloned. Registration surface: tools, slash commands, lifecycle observers,
tool-call interceptors.

We already do this once — `load_inspectors()` runs `~/.config/leela/inspectors.py` through
`runpy.run_path` and appends what it finds to the AST policy. So extensions should be
*the same shape and the same directory*: `~/.config/leela/extensions/*.py`, each defining
`setup(agent)`, registering tools / callbacks / approval policies / commands. A user who
has written an inspector already knows the idiom.

The natural first-party extension, and a good test of the seam: an inspector pack. The
second: a `looker`-style visual checker (§2.6).

### 2.6 Sub-agents / isolated delegation

`aai-coding`'s `looker` is a small, sharp idea: answer a question about images by sending
them to a **fresh ephemeral thread** with a narrow charter, and return only the answer.
The images never enter the caller's context.

We already have both halves. `Chat.classify`, `Chat.check` and our own `Completer` all
open throwaway conversations on the loaded engine; `AgentSession` already knows how to run
restricted code. Generalise to `subagent(prompt, tools=…, model=…)`: a turn on a chosen
backend with a chosen tool subset, returning text. "Find every place we already do X"
costs twenty tool results in the main window and yields three lines of conclusion — that
is exactly the trade a sub-agent is for, and by §2.2 it runs local and free.

### 2.7 Streaming, cost, and caching

Small, and the most *visible* per line of code:

- **Streaming.** Both `StreamFormatter`s exist; we use neither. A local turn is short
  enough to block on; a cloud tool loop is not. Today the pane sits still until the whole
  turn returns. This is most of the difference between "an assistant" and "an agent" as a
  felt experience.
- **Cost.** fastllm's `UsageStats` carries cost, cache-hit rate and model; Rishi's carries
  tokens. Unify on the richer one, show it in the status bar, add a `/cost` command.
- **Prompt caching.** fastllm gives Anthropic caching for `cache=True` plus cache
  breakpoints. Our system prompt is large and about to grow a skill index; the notebook
  context above a prompt cell is stable across a run of questions. This is a real,
  immediate saving for one constructor argument.

---

## 3. Architecture: `leela/agent/` as a portable harness

The harness is going to move to its own package once it has been driven in anger, so the
seam has to be real from the first commit rather than discovered later. Tau states the
split we want:

```
AgentHarness  = the reusable brain
CodingSession = the coding-agent environment
TUI           = one possible frontend
```

For us:

```
leela/agent/          the harness — no import of leela.workspace, leela.tui, leela.web
  host.py             the Host protocol: what an application must supply
  backend.py          the Backend protocol; rishi and fastllm adapters; oneshot/cancel/close
  models.py           name -> (backend, model id, context window); the job->model routing policy
  chat.py             the sync facade: ask, stream, usage, changes, cancel
  compact.py          token estimate, threshold, summary prompts (ported from tau)
  skills.py           pyskills entry points + SKILL.md discovery; read_skill
  extensions.py       setup(agent) discovery and the registration surface
  tools/              tools written against Host, not against Workspace
leela/ai.py           thin: binds a Workspace to the Host protocol and builds the agent
```

**The one rule:** `leela/agent/` may import fastcore, rishi, fastllm and aidialog; it may
not import anything else from `leela`. Everything IDE-specific arrives through `Host`:

```python
class Host(Protocol):
    def roots(self): ...                      # open folders, for the briefing and the sandbox
    def read(self, path): ...                 # sandboxed
    def write(self, path, text): ...          # sandboxed
    def search(self, query, limit): ...       # kosha, or a literal scan
    def research(self, query): ...            # fossick
    def terminal_text(self, lines): ...       # what the user is looking at
    def run_python(self, code): ...           # the restricted AgentSession
    def confirm(self, tool_call): ...         # the frontend's approval prompt
```

`Workspace` satisfies this today, in fact if not in name — every method above already
exists on it or on something it holds. So phase 0 is close to a move, and the day we
extract the package the diff is deleting one file.

---

## 4. Phases

Each phase leaves the IDE working and is worth shipping alone.

**Phase 0 — the seam.** Create `leela/agent/`, define `Host`, move `system_prompt`,
`ide_tools`, `Assistant`, `Completer` behind it. No behaviour change; the existing tests
should pass untouched. *This is the phase to not skip* — every later phase is cheap
because of it and expensive without it.

**Phase 1 — cloud.** `Backend` protocol; adapters for Rishi (sync, local) and fastllm
(async, cloud) with `send`/`stream`/`oneshot`/`cancel`/`close`/`usage`. A `models.py`
name table in aai-coding's style. `leela --model sonnet`, and switching at runtime from
both frontends. Approval reimplemented as a `before_tool_calls` callback on the fastllm
path.

**Phase 2 — routing and cost.** Job→model policy in config. Completions, classification,
summaries and sub-agents to the local backend; turns to the configured one. Unified
`UsageStats` with cost, in the status bar. Prompt caching on.

**Phase 3 — compaction.** Tau's estimator, threshold and prompts. Auto-compact at
`ctx_limit − reserve`, manual `/compact`. Compaction of a prompt-cell conversation writes
a summary cell into the notebook.

**Phase 4 — skills.** `pyskills` entry-point discovery + `SKILL.md` directories with tau's
precedence. Names and descriptions in the briefing, `read_skill` for bodies. Retire the
hand-wired exhash paste — it becomes the first discovered skill instead of a special case.

**Phase 5 — extensions and sub-agents.** `setup(agent)` from
`~/.config/leela/extensions/`, project extensions behind a flag. `subagent()` on a chosen
backend and tool subset. Streaming into both frontends.

**Phase 6 — extract.** Lift `leela/agent/` into its own package; leela depends on it and
keeps `leela/ai.py` as the binding.

---

## 5. What to take from aidialog, and what to leave

Our `nb.py` and aidialog's `Dialog` are the same idea — a notebook of code / note / prompt
messages where a prompt's reply is saved in the document — reached independently from
Solveit. The honest read is that **`nb.py` is not the thing to replace.** It is 274 lines,
keeps outputs in nbformat shape end to end so a round-trip cannot lose what the kernel
sent, and stores a prompt cell as markdown-plus-metadata so plain Jupyter can still open
the file. Swapping in `Dialog` means adopting attachments, `msg_type`, `ai_output`,
`meta_attrs` and a different persistence path, for no capability we are missing today.

Two pieces are worth taking, both small:

- **`msg_parts.fmt2hist` / `hist2fmt` / `mk_tr_details`** — the round-trip between a
  reply rendered as markdown and a real message list *with its tool calls intact*. We
  currently store `reply` (text) beside `calls` (a lossy `{tool, args[:300]}` list), which
  is fine for showing what happened and useless for reconstructing a conversation. Adopting
  this format is what makes "compact this notebook's conversation" and "resume from a
  notebook I opened yesterday" possible at all — so it is a §2.3 dependency, not a tidy-up.
- **`aidialog.dlgskill` as a discovered pyskill** — zero code, once §2.4 exists. It is a
  better notebook-editing skill than we would write, and it stays current by `pip install
  -U`.

Leave `Dialog`, `ipynb.py` and the attachment model. Revisit only if we ever want leela to
open Solveit dialogs directly, which is a feature request, not a refactor.

---

## 6. What to float back into Rishi

Reading fastllm and tau against Rishi turns up four gaps that are Rishi's to fix, not
ours to work around:

1. **A tool-call budget.** fastllm has `max_steps` plus a `final_prompt` that asks the
   model to summarise when the budget runs out. Rishi's loop has no cap at all, and a
   small local model in a tool loop is *exactly* the thing that loops forever. This is the
   most valuable of the four.
2. **Context-window recovery.** fastllm catches `ContextWindowExceededError`, truncates
   the offending tool results in place, and retries with `tool_choice='none'` so the turn
   ends with an explanation instead of a traceback.
3. **Parallel tool calls.** fastllm fans out through `parallel_async`; Rishi's handler is
   strictly sequential. Four independent `search_code` calls should not be four round
   trips.
4. **Cost//model in `UsageStats`.** Free locally, but the field being absent is what forces
   a harness to carry two usage types.

And the reverse, worth saying out loud: **Rishi's HITL approval has no equivalent in
fastllm.** `hitl_policy` with per-tool `approved`/`check`/`dont_run` modes, gating inside
the tool handler, is the better design, and it is what `confirm_writes` is built on. That
is a contribution to make upstream rather than a wheel to reinvent privately.

---

## 7. Deliberately not doing

- **Tau's provider catalog, OAuth flows, updater and session-export format.** fastllm's
  `get_model_info` already carries context windows, capabilities and pricing. A second
  hand-maintained catalog is pure upkeep.
- **A second message model.** fastllm/aidialog `Msg`/`Part` on one side, Rishi's litert
  dicts on the other, normalised at the backend boundary. Not a third canonical type.
- **A second callback/event system.** Both backends have ordered callbacks with the same
  vocabulary. The facade exposes those, and does not wrap them in tau-style events.
- **Auto-routing by classifying the user's prompt.** Latency and unpredictability to save
  cents. Route by job (§2.2); let the user override.
- **Replacing `nb.py`.** §5.

---

## 8. The shortest path to something worth using

If only two phases ever land, make them **0 and 1**: the seam, and cloud models behind it.
Everything else in this document is a small addition to a harness that exists, and nothing
else is possible until it does.
