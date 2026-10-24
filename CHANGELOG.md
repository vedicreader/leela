# Release notes

<!-- do not remove -->

## Unreleased

Needs vishalakshi 0.1.33, shalya 0.1.19, uraiyadal 0.0.16, rahasya 0.0.4, varga 0.0.7, litesearch 0.1.51, kunda 0.0.5, kavacha 0.0.8, dhrishti 0.1.8, fossick 0.1.20, koshas 0.1.11, dhrona 0.1.15, gheasy 0.0.14, pullup 0.0.11, dockeasy 0.0.10, vpseasy 0.0.24 and cfeasy 0.0.6. Pins ramabana 0.2.62 and rishi 0.1.54.

- The window title names the pane that has focus: `leela — <folder> · <scope>`, with `py`, `notebook`, `terminal`, `agent`, `exec`, `files`, `vars`, `vault`, `review`, `web` or `editor:<ext>` as the scope. The token comes from the scope the key router uses. The title changes at most once in 100 ms, and only when the string changes. Leela.app sets its native window title through `window.pywebview.api.set_title`. The agent's `2⚙ (!)` marks stay in front.

- The canvas is removed: the `canvas` block and its `*.canvas.md` documents, the `+canvas` button and `hyper+j` shortcut, the `canvas_*` and `flow_canvas` agent tools, the canvas skill, and the `leela-bricks` development dependency. A saved session that lists a canvas tab opens without it.

- kavacha's interpreter probes and build steps, pullup's `gh auth status` and dhrishti's `ps` get `/dev/null` as stdin, like Leela's own child processes (kavacha 0.0.8, pullup 0.0.11, dhrishti 0.1.8).

- The `ramabana` terminal runs on teleprint 0.1.4. Ctrl+z hands the terminal back to the shell with extended keys, mouse reports and bracketed paste off, and takes it again on `fg`. Quitting from the transcript view leaves the alternate screen.

- A hosted model's tool call cut off at the output limit, or with arguments that are not JSON, goes back to the model once, at a raised output cap when cut off. A second failure fails the turn or the background delegation with `ToolCallError` and the reason, such as "openai/gpt-5.6's tool call was cut off at its 16384-token output limit". It failed with a bare `JSONDecodeError: Unterminated string`. A reply cut off while the model was still thinking is handled the same way.
- A hosted model with no `max_output_tokens` in config.toml gets its own maximum output, or 16,000 tokens for a model fastllm does not know. It got 4096, which a reasoning model's thinking could use up before it finished a tool call.
- The agent's Python stays in one kernel for the whole turn. `run_python`, `inspect_python`, `list_vars` and `promote_var` used the kernel of whichever tab was in front, so a tab the person clicked mid-turn moved the agent to another kernel and every name it had bound vanished with nothing said. The turn now keeps the kernel it first used. When a call lands in a different kernel from the last call (a restart, or a new turn in another tab), its result opens with a line saying so.
- `run_cell` on a notebook with no open tab runs in that notebook's own kernel, the one its tab will use when opened. It used to run in the kernel of the tab in front, so opening the notebook gave a fresh kernel at In[1]. A run in a kernel that restarted since the last `run_cell` there says so. The binding diff after a cell reads the kernel the cell ran in, so it no longer reports names such as `open` that only differ between two kernels.
- A transcript notebook under `_leela_agent_sessions/` or `_leela_sessions/` runs in the folder above it, so its kernel's own transcripts no longer nest a second `_leela_agent_sessions/` inside the first.
- `environment` tells the agent that kernels also import from Leela's own library path, after the project's packages, so a package that imports in a kernel can still be missing from the project.
- The packaged app copies `fastaudit` and `safepyrun` whole. safepyrun loads `fastaudit.hooks` from an entry point that no freezer scans, so every isolated `inspect_python` failed in the app with `No module named 'fastaudit.hooks'`.
- Functions defined through `run_python` have source, so `inspect.getsource`, rishi's tool schemas and tracebacks work on them (dhrishti 0.1.7).

- The vault stores one text once. A file added by a relative path, an absolute path, a symlink or a copy is one document, and a file edited since it was added replaces its old chunks (litesearch 0.1.50). litesearch's usearch probe no longer shares the terminal (litesearch 0.1.51). `Memory.by_source` finds a document by any source it is filed under, and a Local only document's list of sources is withheld with its source (vishalakshi 0.1.33).
- Nothing Leela starts itself shares the terminal any more. The login-shell environment probe, `run_cmd`, scripts and jobs, installs, nbdev and fastship steps, the Rust cell runner, pytest flows, interpreter and debugpy probes, and the repository scan get `/dev/null` as standard input. A prompt in any of them now fails at once instead of waiting until the timeout. LSP, debugpy, the Node driver, formatters and the IDE terminal keep their pipes and pty.
- The login-shell probe, installs, and nbdev and fastship steps run in their own session, so an interactive shell or a credential prompt cannot open `/dev/tty` either. A browser that `BROWSER` names, or Linux's `xdg-open`, gets `/dev/null` as standard input; macOS still opens through `osascript`.
- Nothing the agent's libraries start shares the terminal any more. `claude --version`, `ollama serve`, git through gheasy, interpreter probes, Chrome, and ramabana's own git calls get `/dev/null` as standard input (rishi 0.1.53, gheasy 0.0.14, kunda 0.0.5, fossick 0.1.20, ramabana 0.2.60).
- Dhrona's assessments and nightly rounds see long tool results whole again, read back from `agent-details/` (dhrona 0.1.15).
- A command the agent runs can no longer read the terminal or set it non-blocking; it gets `/dev/null` as standard input (shalya 0.1.19).
- The conversation log no longer keeps long tool results. Each goes whole to `agent-details/` in the agent's config folder, and the log keeps its first 600 characters (ramabana 0.2.59). A conversation's turns, and a reopened one, read only that conversation's rows and show its tool results whole. Backups include `agent-details` as "long tool results".

- A video model written as `gemini/models/<model>` starts its job instead of requesting `models/models/…`.

- A Gemini model chosen as `gemini/<model>` answers instead of returning 404. A Claude Code session that fails while connecting is tried once more, with a note in the session (rishi 0.1.52).

- The terminal agent no longer freezes and then closes its tmux session on the next key when a process that shared the terminal left it non-blocking. An exception in a key handler or a background notice shows as an error and the session carries on (ramabana 0.2.58).

- The agent's `delegate_search` and `delegate_async` take `model=` and `effort=`, one for every question or one per question. Read-only sub-agents on different models and providers run at once. A model that is not set up returns its setup message for that question and is never replaced by another. Effort maps to Claude Code's effort and OpenAI, Azure and Gemini reasoning effort; a local model runs without it and the answer says so. Tool parameters carry descriptions, and on this machine Claude Code refuses in-process MCP servers, so Claude's tool calls stay as text (ramabana 0.2.57, rishi 0.1.51, shalya 0.1.18).

- The agent settings set the sub-agent model, the sub-agent effort (`low` to `max`), and whether sub-agents and turns get native tool calls or schemas as text (ramabana 0.2.57, rishi 0.1.51, shalya 0.1.18). The palette opens each control. The workspace keeps the values, and every live and new conversation takes them. `/agent/subagent-settings`, `/agent/tool-mode`, `/subagents model|effort|tools` and `/model tools` are the routes. A model that is not set up is refused with `ok: false` and its setup message on every route. The reasoning select adds `xhigh` and `max`, and Claude turns receive the level as `effort`.

- The agent's `delegate_search` gives its sub-agents read tools unless it asks for `writes=True`, so several questions run at once. A sub-agent takes up to 80 steps, and a delegation that asks for fewer gets at least 20. Sub-agents are told that a tool result contradicting what they just saw is likely a harness fault to confirm and report, and the briefing points at the `debugging` skill. A Claude Code turn's usage counts its thinking tokens (ramabana 0.2.56, rishi 0.1.50).

- Dhrona's nightly retries and reports its errors (dhrona 0.1.14).

- The scheduled beat that runs Dhrona's nightly says when it was installed from a short `PATH`, and a session's first beat note says when the installed launcher predates the `PATH` fix or no longer finds `claude`, `git` or `git-lfs`, with the command to re-run (ramabana 0.2.55). `ramabana-tick --check` prints the same. The beat reads keys from a `chmod 600` `~/.config/ramabana/beat.env`, never from the launcher, and stops itself after `--limit` seconds so a hung run cannot block every schedule.

- Leela's agent has a `debugging` skill: find a failure's root cause from the raw error, treat a tool that contradicts what the agent has seen as a harness fault to report, and know where Ramabana keeps its config, run logs, beat launcher, scheduler entry and Dhrona's nightly summaries (ramabana 0.2.54).

- A Claude Code turn that sends nothing for 240 seconds is ended and tried once more, with a note that says so, instead of waiting 600 seconds and failing (ramabana 0.2.53, rishi 0.1.49). Text already shown is not repeated. Set the limit per model with `timeout` under `[model."NAME"]` in `~/.config/ramabana/config.toml`; a second silence fails with an error that names it.
- In Ramabana's terminal, `tab` after `@` completes files and folders, and `@folder` attaches the folder's listing (ramabana 0.2.53).

- Dhrona's nightly batch finds `claude` and `git-lfs` (ramabana 0.2.52). The beat `ramabana-tick --install` schedules ran on launchd's `/usr/bin:/bin`, so a round on Claude Code could not start and a repository using Git LFS could not be checked out. Run `ramabana-tick --install` again to take the fix.
- A `<parameter>` element a model leaves outside any tool call is stripped from the agent's reply instead of shown (ramabana 0.2.51, rishi 0.1.48, uraiyadal 0.0.15).

- A line sent to the agent while a tool result fills its size cap reaches the model (ramabana 0.2.50). The line rode at the end of the result and the backend cut it off unread. Ramabana sub-agents asked with `delegate_search(writes=False)` run at once, and `grep` with a folder as `path_filter` finds what is in it (shalya 0.1.17).
- Pictures `generate_image` draws without a `path` save under `media/` in the project's open folder (ramabana 0.2.49, shalya 0.1.16). They used to save under the process's working directory, which in Leela.app is `~/.local/share/leela`.
- No provider is chosen for you (ramabana 0.2.47, shalya 0.1.15). When the agent's model cannot run, for a missing runtime or a missing key, the agent pane lists the providers Ramabana can use, what each needs and which are set up, with a **+ model** button. **+ model** starts with a provider choice (OpenAI, Azure OpenAI, AWS Bedrock's Mantle endpoint, OpenRouter, Anthropic, Gemini, any OpenAI-compatible server) that fills the hosted API fields; the key stays in the environment. The first-run modal counts a configured hosted model whose key is set as set up. The env panel offers `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AWS_BEARER_TOKEN_BEDROCK` and `OPENROUTER_API_KEY`. Leela and `ramabana` read the same `~/.config/ramabana/config.toml`, so `[jobs]` and `[model."NAME"]` there reach the agent pane. The automatic move of a workspace's inline and completion defaults onto a configured model, from the previous change, is gone.
- `generate_video` runs on Ramabana's `video` job (ramabana 0.2.48) rather than on Gemini by name. `[jobs] video` in `~/.config/ramabana/config.toml` or `$LEELA_MODEL_VIDEO` names the model: Veo on Gemini by default, or `sora-2` on OpenAI or an Azure deployment. With no model that can run, the tool says which job to set and how, and calls no provider. A model that makes no video, such as `gemini-2.5-flash`, is refused. The Gemini key no longer follows the download's redirect to storage.
- The README installs Leela from this repository: `leela` on PyPI is an unrelated project. A Windows (WSL) section says to run Leela inside WSL, open its URL in a Windows browser, and export model keys in WSL.

- Learning can be turned off. The agent settings have a **learning** box, and `/learned on|off` in the agent pane is the same switch. Off, every live conversation is re-briefed at once without the learned folder, no lessons are kept and Dhrona proposes nothing new. The Review tab's Learned chip reads "Learned · off", and what waits there can still be accepted or rejected. The setting is ramabana's `learning`, kept in the agent's config folder's `settings.json` beside Leela's settings, which resetting Leela's settings keeps. A `settings.json` that is not valid JSON is refused rather than replaced.
- A turn too large for the model's window after compaction and trimming says so in plain words in the agent pane (ramabana 0.2.44's `ContextFull`), not as a raw `ValueError`. ramabana now trims the oldest tool results and then pictures before compacting, and keeps the window guard right after a compaction or a resume.
- A pasted or attached picture is logged as `[image]` in the conversation log, not as its bytes.
- A message too large for the model's window goes out as an excerpt rather than failing (ramabana 0.2.45). A huge paste, too many pictures or a giant tool result is cut to its head and its end, the whole kept in a file under the agent's run folder that the model is told to read in pieces. The plain-words failure is left for a briefing that alone overflows the window, and it says to start a new conversation with **+** in the agent panel, not to quit or run the `ramabana` command.
- The **learning** box and `/learned on|off` now set `learning` in ramabana's `~/.config/ramabana/config.toml`, one switch per machine, and never write Leela's `settings.json`. A choice made in `settings.json` under ramabana 0.2.44 is read and moved there the first time. A `config.toml` that is not valid TOML is refused with a message, never rewritten.

- Leela without Claude Code works. The default agent model, `claude-opus-5-5`, runs through Claude Code, and without `claude` on PATH building the assistant and opening the history failed. The agent panel now opens with a notice naming what is missing, how to install it, and a model that runs on this machine. A turn on that model fails with the same sentence, and the model picker marks it unavailable. Leela does not switch models by itself.
- **+ model** opens at once, whatever the model list does. It used to wait for `/agent/models`, the whole catalog and two machine-wide probes, and drew nothing at all if that request failed or never answered. The form now opens first with the hosted API runtime ready, so an OpenAI, Azure OpenAI or other OpenAI-compatible model can be saved without the list. A list that fails is named inside the form, a list that does not answer in 15 seconds says so, and a machine with no usable model reads "no model is set up here: add one". A refused save, remove or backend install now shows its reason in the form and the status line. Before, each was dropped without a word.
- `/agent/models` no longer answers 500. Every step is guarded, and a failure becomes a note or `ok: false` in the same shape, with the hosted runtime still offered. The answer also says whether any model is `ready`. A failed list keeps the agent pane's model pickers working over what they already hold, and the status line names the failure.
- The agent composer's **settings** popover fits the room above it and scrolls. In a short window, such as a Windows browser at 150% scaling, its top rows (the model choices) were above the screen.
- **Models and updates** has a **+ model** button, so a machine with no account set up can add a hosted model from there.
- In the Review tab's Learned queue, a candidate that no longer applies to the learned folder shows why on its row, and accepting it returns that reason word for word. After an accept, the status line says how many candidates moved onto it and which no longer apply.
- An accept refused because `AGENTS.md` would pass 2,000 characters stays on screen with a **Compact with this candidate** button. It asks Dhrona for a shorter `AGENTS.md` that includes the candidate, and accepting the result accepts the candidate too.

- A folder clip walks the folder with litesearch's `dir2files`, as vishalakshi's own folder reader does. It skips dot-folders (virtualenvs such as `.aeneas-venv` among them), `build`, `dist`, `node_modules`, `__pycache__` and `tests`, and dotfiles. It keeps `docs` and `examples`, which `dir2files` skips by default. A file named outright is clipped wherever it lives. A clip resumed from before this change drops the skipped files from its count.
- A folder clip can be cancelled from its job card. It keeps what it clipped, and resume clips the rest.
- A GitHub, arXiv, YouTube, web or crawl acquisition, and a grab of a web page, a folder or one of those, can be cancelled from its job card. It stops before the fetch or clone and between the pages, sources or batches it files; a fetch in flight finishes. What it filed is kept, its card counts what it did not file, and "run again" starts it over. Its progress shows on the card. A grab of a file, a PDF or a GitHub file, and a `pdf` acquisition, can be cancelled too; each stops before its read. A note and a harvest still cannot be cancelled.
- A clip hands its stop to vishalakshi, so a cancel that lands after a batch is handed over and before vishalakshi starts it files nothing more. A batch whose clip failed is listed as `failed`, not counted as clipped, and a retry clips it again.
- A clip files batches of 8, and vishalakshi asks for a cancel before each file of a batch, so a cancel lands after the file in flight. The files before it stay indexed and a resume skips them. A clip of 8 files or fewer was one batch and always finished `complete`.
- A cancel is stored in the job's row, in a new `cancel_at` column. A cancel from another workspace stops the clip, and a job cancelled before a quit stays cancelled at the next launch instead of resuming. A jobs file from an earlier build gains the column when it is opened, and a column from a later build is ignored. A build from before this change cannot read a jobs file this one has opened.
- Every `clip` and `clip_tree` job can be cancelled, including one started before `_cancel` existed.
- The Review tab has a fifth queue, **Learned**: what Dhrona proposes for the agent's learned folder, with its diff, accepted with `a` and rejected with `x`, and the agent's recent lessons read-only. Its chip counts what waits, and its head shows `AGENTS.md`'s size against the 2,000-character limit. The palette command "review what the agent learned" opens it. A refusal, such as a running Dhrona batch, uncommitted changes in the folder or a conflict, is shown as ramabana words it.
- A second Leela no longer fails, cancels or restarts a job the first one is running. A job row names its owning process and carries a heartbeat; opening a workspace recovers only a job whose process has gone or has not beaten for 2 minutes (`LEELA_JOB_STALE` seconds). A job taken over after a stale heartbeat stops in its old process, which can no longer write to its row. A jobs file from an earlier build gains the `owner` and `beat_at` columns when it is opened.
- Every running Leela sweeps the jobs file for orphans every minute (half of `LEELA_JOB_STALE`, or `LEELA_JOB_SWEEP` seconds; `0` turns it off). A job left by a crashed or force-quit Leela resumes, or fails if it cannot resume, without a workspace opening, and a job cancelled after its process died ends `cancelled`. Two Leelas sweeping at once take a job once. The sweep leaves a job this process runs, and a job kind it has no handler for, alone. It stops on quit and never runs in a pool worker.
- The Learned queue's head has a **Compact** button. It asks Dhrona for a shorter `AGENTS.md` (`ramabana.learned.compact`), which arrives in the queue as a new candidate and is selected. The model turn runs off the server's loop; the button reads "compacting…" until it ends, including in a tab opened meanwhile. A refusal, such as uncommitted changes or a compaction already pending, shows word for word.
- Compact asks the model the `summary` job routes to, in Leela's own process. It no longer runs a `ramabana` command, which the desktop app does not ship, so it no longer fails there with "the editor gave no answer". A model that cannot answer says why: no key, busy with another turn, or a window too small for the file.
- A folder import (`clip_tree` and its plan) walks the folder as a folder clip does: no `tests/`, hidden files, dot-folders, build output or symlinked folders. Both also leave out `venv` and `site-packages`, and the folders `LEELA_VAULT_SKIP` names, in any case. The plan no longer lists the paths it leaves out; it names the folders it skips.
- litesearch 0.1.45 starts no process pool for a batch of HTML files. litesearch 0.1.46 takes a `stop` in `add_dir`, asked before each file.
- CI: the fast tests resolve the default Claude Code model without `claude` installed, the checkout fetches full history, and the small-session refusal test no longer needs mlx. 41 tests failed on GitHub for these three reasons alone.
- CI runs the test job on macos-15 as well as Ubuntu, so the Cocoa shell, Apple Events and macOS priority-class tests run on every push and pull request. Tests that need a built `dist/Leela.app` still skip. The orphan-sweep test waits for sweep rounds instead of a fixed 300ms.
- The vault and search load on macOS 14. numkong 7.5 and later, which usearch needs, link `___sme_memset` from macOS 15 while their wheels claim macOS 11, so usearch does not import there. litesearch 0.1.48 and later search with numpy when usearch does not import, the desktop app included, and on a macos-14 runner Leela's fast suite then passes.
- Agent code search no longer hangs on litesearch 0.1.47 and 0.1.48. `_Serial` holds litesearch's `db_lock` around `Kosha.context`, whose repo and package legs run on worker threads, and in those releases the legs' first `get_index` waited on that lock. litesearch 0.1.49 loads indexes and usearch's SQL functions under a lock of its own.
- The app's `LSMinimumSystemVersion` is 14.0, the oldest macOS the suite has run on. It claimed 11.0, kavacha's default, and numpy's wheel in a bundle built on macOS 14 needs 14.
- A second launch attaches only to a Leela on the same config dir. `/hub/open` reports a hash of the config dir, and a Leela from an earlier build counts as the default `~/.config/leela`. The packaging tests launch the built app on a temporary `XDG_CONFIG_HOME`, and when the person's Leela was running it took the launch and the tests failed with "the app never began serving".
- Leela imports no private name from kunda, kavacha, fossick, rishi, pullup or dockeasy. The six kunda seams, fossick's `debug_ready`, pullup's `gheasy_core` and dockeasy's `FASTOPS_ENV` are public upstream.
- Three theme families: **github**, Primer's dark and light as on github.com, with GitHub's code colours in the editor, its green primary buttons and its orange active-tab underline; **ember**, a warm dim sepia; and **dusk**, a cool soft slate. Ember and dusk have no pure black or white and keep body text and code at 4.5:1 or better without glare. Each has a dark and a light variant, follows the system with "follow system", and is picked on the Appearance page of settings (`⌘,`, the palette's "settings", or the app menu).
- Ember and dusk draw code in palettes of their own, in the editor, in diffs and in Markdown code blocks. Ember's is warm and muted: terracotta keywords, sand functions, olive strings, sage types. Dusk's is cool and muted: slate-blue keywords, frost functions, sage strings, lilac numbers. Every code colour reaches 4.5:1 on the page and the panels in both variants, where diff and Markdown code in the light variants reached 3:1.
- A canvas tab follows the theme's dark or light variant, and repaints when the theme changes, including when the system's mode changes under "follow system". The tab used to send the theme as `[object Object]`, so a canvas was always light.
- The desktop window takes the theme's background. It opens on the saved theme's colour and changes with the theme, so opening or resizing a window no longer flashes kavacha's fixed dark grey.
- A theme cached by a newer build, or naming a family this build does not have, paints the default family on first load instead of an unstyled page. An unknown variant or density falls back the same way.
- A Local only document's title, headings and source do not reach a hosted model through the vault, and the vault's document list is gated the same way.

- Vault privacy (`vault_pii`) defaults to `redact`, not `off`. A hosted model gets a Personal vault document with its identifiers masked. A stored `off` is kept, and the settings pane labels it "as is (not recommended)". A workspace with no stored choice, or one this build does not know, gets `redact`.
- A model on this machine reads vault documents whole. `vault_pii` applies to hosted models only. A Local only document never goes to a hosted model, whatever `vault_pii` says.
- An @-attached vault document or section goes through vishalakshi's `send_check`. A Personal one is masked for a hosted model. A withheld one stops the turn before it starts.
- A file, picture, sound or selection attached by path takes the level of the vault document filed from that path. So does the open document's context. A picture, sound or PDF cannot be masked, so a hosted model gets it only when its document is Open or `vault_pii` is `off`.
- `/agent/turn` answers a withheld attachment with `{ok: false, error, kind, refs}`. `kind` is `local_only` or `pii_blocked`.
- The agent's file tools go through shalya's read guard. A vault source is sent whole, masked or refused for a hosted model by its document's level.
- `run_shell`, `run_shell_bg`, `run_python` and `inspect_python` refuse, for a hosted model, code or a command that names a vault source whose document may not go whole. The match is on the file name. A glob or a computed path is not caught.
- `/agent/vault-pii` refuses a request with no `pii`.

## 0.1.10

- The command line and macOS app default to port 5010. The desktop app tries ports 5010 through 5019 before requesting an operating-system-assigned port.
- Canvas component wiring defaults to port 5010. `BRICK_HOST` still overrides it.

## 0.1.9

Needs ramabana 0.2.6 (pinned); shalya, rishi, vishalakshi and dhrona as before.

- Cloud routing defaults: the turn is `claude-opus-5-5`, the small jobs (oneshot, classify, completion, inline, summary) `gpt-4.1`, sub-agents `claude-sonnet-5`. No local model is on a default or fallback route; without `OPENAI_API_KEY` the gpt-4.1 jobs use claude-sonnet-5 and the chat says so once. A local turn model keeps every job without a model of its own on the machine.
- A default Leela session is Opus, briefed in full; the small profile is for a local model you choose. A vault spec marked local-only is refused until one is.
- The agent panel and the model picker name ramabana's turn default before the assistant is built, not `gemma-e4b`. The inline model defaults to `gpt-4.1`, not `gpt-mini`.
- The picker's job rows apply saved per-job choices with `Routing.set`, so on a local turn a chosen sub-agent shows as chosen rather than as the local model.
- A sub-agent on the turn's own budget is not handed delegation, watches or the plan tools; ramabana 0.2.6 (`Agent.ROOT_ONLY`) enforces this on every path, not just Leela's own.
- The `--model` help and the settings pane's job help describe the new defaults.

## 0.1.8

- Needs ramabana 0.2.4 (pinned) and shalya 0.1.1: sub-agents can be handed pictures (`delegate_search(images=)`), `generate_image` can draw from reference pictures and save to a chosen path.
- `generate_image(path=...)` is a write in the agent pane too: approvals gate it in every mode (the repeat guard included), turn rollback removes the pictures it made (all of `n`) and refuses when one existed before or changed since, retry refuses it, and read-only copies are recorded.
- `create_file` no longer overwrites a picture with text; `memory_search` returns rows again.

## 0.1.7

Needs ramabana 0.2.3 (pinned) and rishi 0.1.39; shalya, vishalakshi and dhrona as before.

- Small profile for local models: ramabana's `auto` briefs a local runtime, or a window of 32k or under, with the small profile: fourteen tools (read, edit, search, run, `git_status`/`git_diff`/`git_commit`, the notebook four) and a briefing of one screen, warm start off. The default turn model is `gemma-e4b`, so a default Leela session is small: 14 tools plus Leela's `run_cell` (15 briefed, about 1.9k characters) against 52 tools and about 10.7k characters in full. `user_steering` stays dispatchable in every profile, so a refused call still resolves as steering. Canvas tools appear while a canvas is open and news tools while a feed is followed, in the small profile too; the small briefing names the open canvas in one line and clips the state and note blocks to 2k characters each. Video tools are full-profile only.
- Choosing the profile: **full** beside **warm** briefs the next new conversation in full whatever the model (`/agent/thread/new` takes `profile`); the settings pane's **briefing** select is the workspace default (`agent_profile`, `/agent/profile`). A conversation's row wears `·small`, and picking a model reports `… · small profile` or `… · full profile`. A conversation's own profile outlives its eviction the way its opt-ins do (`thread_profiles`): resuming it brings the same catalog back.
- rishi 0.1.39 serialises chats that share a LiteRT engine (`engine_lock`) and raises `EngineBusy` if a second chat steps onto the engine from the thread already mid-turn on it -- the gemma-12b `DEADLINE_EXCEEDED … Failed to lock custom tensor buffer` and empty turns. Leela has no such path: the lent chat `ask_memory` builds runs inside a tool call, where the handler has let the engine go, and every other one-shot runs from another thread or between sends. `tests/test_engine_broker.py` pins the contract.
- `gemma-12b` is a 16k window now.

## 0.1.6

Same pins as 0.1.5.

- Run a `.py` app, stop it, run it again: the terminal shows the new run. A run ends its viewers' queues when its stream ends, `/run/ws` sends `{"t": "exit"}` the way `/term/ws` does, and the run terminal is replaced when the same path comes back under another pid.
- A run keeps every `http://` URL it printed (`urls` in `/dev/list`), and a stopped run still reports the last one (`last_url`).
- Reopening the page brings the running servers back: the first `/dev/list` poll adopts each into its run terminal, and the runs menu lists every URL a running app printed as an **open** row.
- `Memory._store` opens a shelf under a lock. The poll tick and a request opening the same shelf at once built two Vaults over one file and crashed the test worker with a bus error.
- CI: the test job sets a git identity, has `timeout-minutes: 45`, and the two tests that resolve a Claude Code model skip where `claude` is not installed. The Windows desktop job is `continue-on-error` until pyghostty ships a Windows wheel; macOS is the release.

## 0.1.5

Needs ramabana 0.2.2 (pinned), shalya 0.1.0, vishalakshi 0.1.17, dhrona 0.1.4, rishi 0.1.38.

- The tool set is shalya 0.1.0's: `replace_text(path, edits)` and `edit_cell(path, cell_id, edits)` take a list of `{oldText, newText}` (a JSON string still parses this release), `ls` lists files, `inspect_python('')` reads the live namespace, `remember(key=)` upserts a note, and one `watch(kind='url'|'remind'|'search'|'folder')` replaces the watch, reminder and folder-watch tools. `edit_file` (hash-addressed edits) and `research` are opt-ins.
- Leela's own `inspect_var`, `search_all` and `api_access` are gone: `inspect_python`, `search_code` and the API paragraph of the briefing carry what they did. `user_steering` is dispatchable after a refused call and never offered, briefed, or shown in a form.
- The default workspace briefs 42 tools without a video key, 45 with one (was 77 of a backend list of 81); a sub-agent gets 42 (was 70). Canvas tools appear only while a canvas is open (+8) and news tools only while the workspace follows a feed (+6); the live backend is re-briefed at the next turn when either changes, and only then.
- Opt-ins per conversation: **research** and **exhash** toggles beside **warm** give the next new conversation shalya's slow `research` tool or `edit_file` plus the exhash skill; the settings pane holds the workspace default (`agent_optin`), and a browser's own toggle overrides it. A conversation's opt-ins survive eviction and resume, and its row wears them like `·warm`.
- Warm starts are ramabana's `Agent(warm=)`. The pane's toggle, the transcript block (with each replayed message) and assess / capture / accept are unchanged; a cold or resumed conversation gets no seeds. ramabana seeds only a model whose window admits inlined skills, so a small local model (about 24k context or less) starts cold with a note.
- Checkpoint forms edit list arguments (`edits`, `commands`, `items`, `questions`) as JSON with the error on the field; previews diff `edits` for `replace_text` and, per cell, `edit_cell`; activity rows print list arguments; Undo covers `replace_text` and `edit_cell`.
- Git in the agent pane: `git_commit`, `git_checkout`, `git_stash` and `git_remote` are briefed and go through the same approval as any write; `run_shell` refuses `git commit|push|pull|fetch|stash|switch|checkout` and names the tool. The turn card shows the git writes with their undo tokens, and **Restore files** undoes them first, then the files — refusing, and touching nothing, when HEAD or the branch moved after the turn or a file changed since. A partial undo says what it undid.
- The approval queue carries ramabana's repeat guard: the third identical gated call in a row is put to the person whatever the mode or run policy, and a read between neither counts nor resets. A folder watch opened by `watch(kind='folder')` reaches the harness's monitors.
- `ask_memory` picks its own policy (local when a local runtime exists, else redact); the vault PII setting governs retrieval only. The host remembers by `key`, answers `exists`, and `delete`s only inside the writable roots.
- `leela.agent` is one module: `leela.agent.X` is `ramabana.X`, aliased in `__init__`.
- The exhash skill is inlined only when it is discoverable on the machine (a skills directory holding it) and `edit_file` is offered.
- Tests: `pytest-timeout` bounds every test (300 s) and approvals default to a 2 s wait under pytest. `tests/fakemodel.py` gains `WIDE`, a 128k scripted window.

## 0.1.4

Needs ramabana 0.1.42, rishi 0.1.38, shalya 0.0.11 (below 0.1), dhrona 0.1.4, koshas 0.1.8, vishalakshi 0.1.15.

- Canvas: a document that runs. Bricks, the dataflow between them, trusted runs, embedded bundles, literate diff and review. `leela-bricks` is the brick set the tests resolve against.
- `_plain` is overridden, not assigned; ramabana derives it from the catalog now. Git writes still stay out of the briefing.
- Edits and commands go through shalya's public `cmds`, `edits`, `apply_edits`; `test_seams` follows the aliases.
- Runtime names come from ramabana's `RUNTIME_NAMES`; `RUNTIMES` is urai's registry.
- The refactor engine is kosha's (`kosha.refactor`); Leela's copy is gone. Its comprehension-ordering rule went upstream first.
- `kosha.refactor` is imported where it runs, so the server does not load numpy and pandas.
- The shelf registry is read from litesearch's `store_meta`, then the older `vault_stores`.
- `Memory.poll` builds the typed graph only when online; an offline vault polls its reminders without a model.
- `KernelPool.close_all` cancels kernels still starting and gives up after a bound. Leaving a workspace could hang on a kernel that never came up; so could the suite.
- `test_canvas` stays on one xdist worker (`--dist loadgroup`). `uv.lock` re-resolved.
- Agent pane: a **warm** toggle seeds the next new conversation from dhrona's reviewed rounds, a collapsed transcript block shows every replayed message and tool call and why the other rounds were skipped, and **assess** / **capture** / **accept** score a conversation, write it as a review notebook under `<root>/.dhrona/`, and install the reviewed round (`dhrona>=0.1.4`). A notebook saved in Leela keeps the metadata other tools put on its cells.
- ramabana 0.1.42: it owns the model catalog now (curated ids plus live discovery from the providers' `/v1/models` and Codex's cache), so current models appear and the caps that held aidialog and python-fastllm for its old fastllm-table reads are gone. The saved catalog probe is re-keyed so the new list shows without a manual refresh. shalya is capped below 0.1.

## 0.1.3

The first release whose macOS DMG and Windows zip are built from `uv.lock`. Both earlier releases shipped no usable desktop artefact: the v0.1.1 build failed on `No module named 'ruamel'`, and the v0.1.2 build resolved jupyasyncclient fresh from PyPI and took 0.2.14, whose `run` is a bare async generator where `GatewayKernel` reads `.reply` off a `Run`. The bundled kernel in that build answers 500 to every cell.

### Desktop builds

- Both CI jobs install from `uv export --frozen`, so py2app and py2exe freeze the set the suite ran against. The Windows job resolved from `pyproject.toml` until now.
- `jupyasyncclient` is capped at `<0.2.8`. The previous `!=0.2.8` did not exclude 0.2.14.
- `mark_namespaces` runs against whichever interpreter is about to build, not only inside `build_venv`. A framework interpreter went straight to py2app and never got the `ruamel` marker.
- `desktop-artifacts.yml` triggers on `v*` and on a bare version tag. `ship-gh` tags a Python project `0.1.3` and fastship's other flows push `v0.1.3`; only the second used to build anything.
- `build_release.py upload` looks up whichever tag spelling carries the release, and names `ship-gh` when neither does. It used to fail with `release not found` after the DMG had been built.
- `setup_app.py` skips the lock check where uv is absent rather than reporting a drift.
- `running_from` reads the process name `ps` reports. A framework build re-execs out of `Python.app` and `sys.executable` still names the symlink, so a build could overwrite a running app.

### Notebooks

- `write` moves source text onto the cells already on disk instead of replacing the file with the `# %%` document `text_at` handed out. Rolling back an agent turn that touched a notebook destroyed it. Outputs, execution counts and cell metadata survive.

### Agent

- The update check runs once an hour rather than once per process. `_latest_versions` assigned `_latest` without declaring it global and raised `UnboundLocalError` on every call after the first.
- The releases request carries the GitHub token gheasy resolves. Leela's repository is private, and an unauthenticated request answers 404 there.

### Repository

- Removed `spikes/nbship`, its tests, and the four historical design records under `docs/superpowers/`.
- Removed `docs/handoff.md`, `docs/chat-threads.md`, `docs/chat-threads-implementation.md` and `docs/multi-workspace-architecture.md`. The first was a dated status note. The next two specified `blocks/agent/threads.py`, which is written. The last described `LeelaDaemon`, `WorkspaceRegistry`, `WorkspaceSession` and `ClientSession`, none of which exist.

## 0.1.2

- `mark_namespaces` runs against the building interpreter.
- The update check works more than once per process and authenticates.
- CI installs into uv's own environment. `uv pip install --system` is refused by the runner's externally managed `/usr`.

## 0.1.1

- Every package a tool schema is read from ships its source in the bundle.
- The DMG is staged outside the repository. A `/Applications` symlink left under `build/` is a path from the checkout into the real folder.
- `leela.core.inspectors` reads the registry from `dhrishti.registry` and the import classifier from `kunda.support`.
