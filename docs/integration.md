# vishalakshi and ramabana integration

`WorkspaceHost` in `leela/blocks/agent/ai.py` is what Leela hands the agent. It is a `shalya.Host`
that declares its capability groups by inheriting the class naming each one, and `Host.provides` is
the only way to ask what it supports. A host that declares a group and leaves one of that group's
methods unwritten refuses to be built, so the declaration cannot drift from the implementation.
`shalya.tools.tools_for` reads `provides` and builds exactly the tools the host can back.

| group | what it is | where Leela implements it |
|---|---|---|
| `file` | the path boundary every host has | `blocks.fs.fs.Sandbox`, through `WorkspaceHost.check` |
| `code` | search, symbols, peers, public API | `blocks.search.search.Search` |
| `notebook` | cell listing, insertion, one live run | `blocks.nb.nb` and the kernel pool |
| `web` | search, one page, a cited digest | `blocks.research.research.Research` over `shalya.host.read_page` |
| `memory` | pages, research, agent notes and state | `blocks.memory.memory.Memory` over `vishalakshi.Vault` |
| `ask` | model-backed answers out of memory | `blocks.memory.vaults.Vaults` |
| `watch` | standing work that outlives the turn | `blocks.vault.jobs.Jobs` |
| `api` | a loaded spec, its operations, one call | `blocks.vault.spec` |
| `session` | the live namespace and the terminals | `blocks.runtime` and `blocks.term` |
| `shell` | one command, through the project env | `blocks.term.term` |
| `git` | status, divergence, a rehearsed rebase | `blocks.git.git` over `gheasy.repo` |

`without` is the runtime half. A group whose backend was never attached, or whose package never
imported, goes there and `provides` drops it, so the tools for it are never built.

Two settings sit beside the groups rather than inside one. `agent_read_outside` widens reads past
the open folders while writes stay confined to them, and `mk_chat = None` is what lets the vault
answer on the session's own model through `Agent.lend_model`.

Memory and code search stay separate: source code is an AST corpus, prose is a document tree, and
the retrieval that answers well for one answers badly for the other.

`ramabana.runtime.Backend` is the model session, and `leela.agent.runtime` aliases it. Nothing in
Leela constructs one: `Agent` resolves the model for each routed job itself, from `Routing`.

## dhrona warm starts

`Assistant(warm=True)` passes `warm=` through to `Agent.__init__`; the warm start is ramabana's.
Its `_prepare` calls `warm_start()` before turn 1's `before` checkpoint, fits dhrona's accepted rounds
to `_plain` (`dhrona.core.fit_rounds`), hands the replayed messages to the backend through
`resume_hist`, sets `plan.warm` to the rounds used, and fires `on_warm(report)` with the used and
skipped rows. It seeds only when the model's window admits inlined skills (`budget.inline`), so a
small local model starts cold with a note, and a resumed conversation gets none. Leela's part is the
transcript block: `Thread._warmed` is the `on_warm` hook, `blocks/agent/warm.py` `with_messages`
reads each used round back from the library and adds its messages to the report, and
`/agent/thread/turns` returns that report (or `null` for a cold conversation). `warm.py` also holds
`assess_session`, `capture_round` and `accept_round`, importing dhrona lazily so a missing package is
a note in the pane, not a failed turn.

`capture` writes the review notebook to `<first root>/.dhrona/<name>.ipynb`, and `accept` -- which
takes only a notebook under that folder -- writes the compiled `<name>.json` beside it before
installing a copy into `~/.config/dhrona/rounds`. The folder is the workspace's, so `/tab/open`
reaches it; it holds working material, and a project may want it in `.gitignore`.

## The learned review queue

What Dhrona proposes for `<cfg>/learned` waits on a `pending/<id>` branch of that folder's git repository until a person accepts or rejects it. The queue is ramabana's (`ramabana.learned`: `pending`, `diff`, `accept`, `reject`), and Leela's part is the Review tab's fifth queue, **Learned**, beside Proofreading, Personal info, Types and Verses. The palette command "review what the agent learned" (`learned_review`, Tools menu) opens it. The folder is `learned_folder(cfg)`, with `cfg` the live assistant's config or `agent_cfg()` when none is built, so the queue is reviewed whether or not the agent briefs from the folder. `Agent.learned_dir` is None when it does not.

The queue keeps the Review tab's keys: `j` and `k` step, `a` accepts and `x` rejects. A candidate is its own commit, so an accept is applied at once rather than staged, and neither an accept nor a reject is undone from the tab. The active candidate's diff is painted below the list, with the newest only, so a fast `j` cannot paint a stale one. The live agent's recent lessons (`Agent.lessons`) are listed read-only below it, and the head shows `AGENTS.md`'s size against `LEARNED_MAX`. The **Compact** button beside it (`data-learned-compact`) posts to `/agent/learned/compact`, which runs `ramabana.learned.compact` with a `chat` on the agent pane's `summary` route (`compact_chat`), so no `ramabana` executable runs: one model call that proposes a shorter `AGENTS.md` as a new pending candidate. The tab selects that candidate when it arrives.

A candidate that no longer applies to HEAD carries `stale`, ramabana's reason, and its row shows it. An accept moves the other pending candidates onto the new HEAD (`moved`) and names those that no longer pick cleanly (`stale`); the status line counts the first and lists the second. An accept refused for size carries `length`, and the refusal stays on screen with a **Compact with this candidate** button that posts `{id}` to `/agent/learned/compact`, so the compaction folds that candidate in and accepting it accepts both.

`/agent/learned` lists the queue, and `/agent/learned/diff`, `/accept` and `/reject` take `{id}`. Each returns ramabana's dict as it is: `{ok: true, id, ...}` with HTTP 200, or `{ok: false, id, error}` with HTTP 409, and the tab shows `error` word for word. A git command ramabana does not expect to fail, such as a diff of a root commit, raises in ramabana, and the route returns it in the same shape. The learned queue is fetched apart from the vault's four, so a failure shows in its own mode and leaves the others.

`/agent/learned/compact` takes a POST only, since it spends a model turn, and an optional `{id}` of a candidate to fold in. It answers `{ok: true, id, before, after}`, sizes in characters, or `{ok: false, error}`, with the same 200 and 409. The turn runs on a worker thread, so the server's loop stays free, and a process-wide lock lets one compaction run at a time; a second press gets `a compaction is already running`. `/agent/learned` reports `compacting` while the lock is held, and the tab polls it every 3 seconds while it is true, so a request the webview dropped, or a compaction started from another tab, still clears the pending state. A compaction from the CLI or another Leela holds Dhrona's learned lock, not this one, so the button does not show it; pressing then returns Dhrona's refusal for a running batch.

## Learning on and off

Learning is ramabana's switch, `learning` in `<cfg>/settings.json` (`ramabana.learned.enabled` and `set_enabled`). Off, a briefing leaves out the learned folder and its skills, no lessons are kept, and Dhrona's batch proposes nothing; the queue can still be decided. Leela has three ways to it: the **learning** box in the agent settings, `/learned on|off|status` typed in the agent pane, and the Review tab, which reads it. `cfg` is the one `_learned_folder` resolves, and by default it is Leela's own config folder, so the key sits beside Leela's settings in one file. `Settings.save` and `Settings.reset` keep a top-level key that is not one of Leela's sections.

`POST /agent/learning` takes `{enabled}` and the command route takes `/learned on|off`. Both write the setting once, through the first live conversation on that folder (`/learned on|off`, which re-briefs it), and re-brief every other live conversation on it, so the change applies without a restart. Both answer with `enabled` and `cfg`; the settings route adds `note`, and the command route the command's own `text`. A `settings.json` that is not a JSON object is refused with `{ok: false, error}` and left as it is, since ramabana would replace it with `{}`. `/agent/learned` carries `learning`, the Learned chip reads "Learned · off" when it is false, and the queue's head says what off means. ramabana's own schedule skips Dhrona's batch while learning is off. Leela's warm start, assess and capture (`warm.py`) are not gated by it.

## Adding to the host

1. Declare the group by inheriting shalya's class for it, and implement every method it names.
   An incomplete declaration fails at construction rather than at the first tool call.
2. Put the group in `without` when its backend is absent, so `provides` tells the truth.
3. Import the implementation's dependencies inside the method, not at module scope: the server's
   boot path is what pays for a module-level import.
4. A capability that belongs to every agent belongs in shalya, and one that belongs to every
   Ramabana session belongs in Ramabana. Say so rather than implementing it on Leela's side.

There was a second answer to all of this: `leela/core/ports.py` and `leela/conformance.py`, three
Protocols with a provider registry, an environment override and a hand-kept table of parameter
names to check an implementation against. One provider was ever registered per port, all three
named `leela`, and the swap it existed to permit never happened once. `tests/test_core.py` holds
the test that keeps it retired.

## Providers, Azure OpenAI and AWS Bedrock

The model route is Ramabana's, so Leela and the `ramabana` CLI agree on it: both read `~/.config/ramabana/config.toml` (or `$RAMABANA_CONFIG`) and the same env vars. Nothing chooses a provider for a person. When the agent's model cannot run here, a missing runtime or a missing key, the agent pane says why and lists every provider Ramabana can use, what it needs and whether it is set up (`providers()`, from Ramabana's `PROVIDERS`), with a **+ model** button. The first-run modal counts any configured hosted model whose key is set as set up (`setup_plan`); a credential with no model named is not one.

**+ model** starts with a provider choice. Picking one sets the runtime to the hosted API and fills the base URL hint, the key's env var and the API transport: OpenAI, Azure OpenAI (`https://NAME.openai.azure.com/openai/v1`, the deployment name as the model ID, Responses), AWS Bedrock (the Mantle endpoint `https://bedrock-mantle.<region>.api.aws/v1`, `AWS_BEARER_TOKEN_BEDROCK`), OpenRouter, Anthropic, Gemini, or any OpenAI-compatible server. The model is saved in Leela's `~/.config/leela/models.json`, and the key stays in the environment. The env panel offers `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AWS_BEARER_TOKEN_BEDROCK` and `OPENROUTER_API_KEY` beside the other keys.

The same in config.toml, which the CLI's `ramabana setup` writes:

```toml
[azure]
endpoint = "https://NAME.openai.azure.com"   # or $AZURE_OPENAI_ENDPOINT; the key stays in $AZURE_OPENAI_API_KEY

[model."bedrock-gpt"]
model_id = "openai.gpt-5.4"
base_url = "https://bedrock-mantle.us-east-1.api.aws/v1"
api_key_env = "AWS_BEARER_TOKEN_BEDROCK"
api_name = "openai"

[jobs]
turn = "azure/gpt-5.4"                        # an Azure deployment, by name
summary = "bedrock-gpt"
```

Claude on Bedrock, and anything that needs Bedrock's native Converse API, AWS profiles or SigV4 signing, is not supported: fastllm, which makes the requests, implements none of them. The agent pane's default model comes from Ramabana's routing (`default_model`), so `[jobs] turn` reaches it unless the workspace saved a model of its own. A model saved in the settings pane wins over nothing in config.toml; a name config.toml defines wins over a saved one, and saving that name is refused. `leela/blocks/agent/video.py` still asks Gemini for video by name; it is not routed yet.
