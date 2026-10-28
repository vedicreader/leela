# Learn from abhyasa: Leela's side

Status: design, 28 Oct 2026. Not built. The plan is `2026-10-28-learn-from-abhyasa.md` in this folder.

The brief that both apps follow is `abhyasa-designs/leela-reuse.md` (paths are relative to `/Users/71293/code/personal/orgs/`). Section 6 of that brief is the source for this design. The abhyasa side is the walk spec and plan in `abhyasa-walk/docs/superpowers/` (spec 6.10 and 6.12, plan Tasks 11 and 14). Facts about Leela are from main at `58af242`.

## 1. Intent

abhyasa teaches ideas from papers, topics and docs links, one step at a time (a walk). It runs only short stdlib code checks. The owner decided on 28 Oct 2026 that code with a library, tool environments, code lookup and an agent tutor for tools live in Leela, because Leela already has `uv`, kosha and the ramabana agent. abhyasa gives a link. Leela opens the step as a lesson, lets the learner write real code against the library, and writes the result back to the shared learning store.

This design also closes four gaps that the research for the brief found in Leela today:

1. Leela does not log rupaka predictions. A gate in a lesson demo sends `rk-predict`, and nothing listens.
2. The vendored rupaka bundle (`leela/vendor/lee-rupaka.js`, 0.0.1) and the installed rupaka that validates specs can be different versions. `test_rupaka_vendor_version` marks a difference as an expected failure, so it never stops a release.
3. `leela/blocks/nb/lesson.py` imports `TUTOR_SP` as fixed text. The owner's edits to the tutor prompt on abhyasa's Settings page do not reach Leela.
4. `check_solution` in `leela/blocks/nb/exercise.py` repeats part of `abhyasa.check.run_isolated`.

## 2. Goals

- `GET /learn?walk=<jid>&step=<i>&topic=<name>` opens a walk step or a topic from abhyasa. The query is read only with `abhyasa.journey.read_handoff`.
- A lesson opened from a walk logs every check through `Learning.record` with the walk meta: `walk`, `step`, `section`, `from = "<jid>/<i>"` and `app = "leela"`. Leela never changes the journey document.
- A rupaka gate in a lesson notebook is logged as one attempt of kind `demo`.
- The vendored rupaka bundle and the installed rupaka are the same version, and a test fails when they are not.
- The tutor charter reads the tutor prompt through `abhyasa.prompts.prompt('tutor')` each time Leela builds it.
- The split editor can hold a local Leela page, and it follows the pane contract of `abhyasa/core/pane.py`.
- The side pane shows kosha results for the library of the lesson.
- A lesson on a library gets its own tool environment (made with `uv`, wheels only, cached for each set of packages). Graded code runs in a closed process with that environment's Python and with no network.
- The ramabana agent tutors a tool lesson with the step, the owner's tutor prompt and kosha lookup.

## 3. Non-goals

- Leela does not show abhyasa pages in its pane. The pane holds Leela pages only (same origin).
- Leela does not write to a journey, a walk state or a demo record of abhyasa.
- Leela does not call abhyasa over the network. Both apps read the same store.
- No `leela://` URL scheme. abhyasa links to the loopback URL in `serving.json` (abhyasa spec 6.12).
- No new keyboard shortcut. The split editor already has buttons; a key for the pane needs the keymap audit that `AGENTS.md` asks for, and that is a separate change.
- No board, timeline, `image` block or `resolve` hook here. They wait for rupaka 0.0.2 and later (brief, section 4).
- No "walk this notebook" (`journey_from_pages`). That is a later plan.
- Learner runs in the live kernel do not change. Only the graded check moves to a closed process.

## 4. The handoff as Leela implements it

### 4.1 What abhyasa sends

abhyasa reads `$XDG_CONFIG_HOME/leela/serving.json` (written by `now_serving`, `leela/core/projects.py:117`) and checks that its `pid` is alive. It links to `<url>/learn?…`, built by `abhyasa.journey.handoff(jid, i, topic)`. The link opens in a new browser tab. abhyasa never connects to Leela.

Leela must keep these stable:

- `serving.json` with `url` and `pid`, written while Leela answers and removed when it stops. In the hub (the desktop app), `url` is `http://127.0.0.1:<port>/`, and the hub sends a request on that host to its default workspace.
- The path `/learn` and the keys `walk`, `step` and `topic`. `read_handoff` ignores other keys, so Leela can add its own.

### 4.2 The guard

`LoopbackHostGuard` (`leela/hub.py:128`) refuses any request with `Sec-Fetch-Site: cross-site`. A link from abhyasa on `localhost:<port>` to Leela on `127.0.0.1:<port>` is cross-site, so today the link fails. The guard gets one narrow exception: `GET /learn` with `Sec-Fetch-Mode: navigate` and `Sec-Fetch-Dest: document` passes. The Host check stays. All other routes keep the current rule. A cross-site POST to any route, `/learn/open` included, is still refused.

### 4.3 `GET /learn`: show, never act

The route calls `read_handoff` on the raw query string.

| input | answer |
|---|---|
| `read_handoff` raises `ValueError` | 400, with the error text as plain text |
| a `walk` that is not in the store | 200, one line: "This walk is not in your learning store." |
| `walk` and `step` | the step page: the walk title, the section, the passage (`step['read']['text']`), the tutor note (`step['note']`), the concept name, and an "Open as a lesson" button |
| `walk` and no `step` | the same, for `walk_state(j).current`; a walk with no current step shows "This walk is done." |
| a `step` out of range | 400, "step: this walk has no step <i>" |
| only `topic` | the concept page for `slugify(topic)`, or the name when the concept is not on the shelf, with "Open as a lesson" |
| the store is locked or cannot be read | 503, "The learning store is locked or cannot be read." |

Rules for the page:

- It reads the store under `_open_lock` and writes nothing: no file, no tab, no attempt, no job.
- It runs no code and installs nothing.
- It sends `Content-Security-Policy: frame-ancestors 'self'` and `Referrer-Policy: no-referrer`, so another site cannot frame it and press the button.
- The passage and the note are text from the store. They are escaped as text, never rendered as HTML or Markdown with raw HTML.
- With `pane=1` in the query, the page has no page chrome and runs the pane script (section 5).

### 4.4 `POST /learn/open`: make or reopen the lesson

The button posts `walk`, `step` and `topic` back to `/learn/open`. The request is same-origin, so the guard lets it through. The route reads the values with `read_handoff` again (it never trusts the form more than the link).

- With a project folder open, it writes `lessons/<walk>-<step>.ipynb` (or `lessons/<slug>.ipynb` for a topic) through `ctx.fs`, as `/lesson/new` does (`leela/blocks/tabs/app.py:82`). When that file exists and its meta names the same walk and step, it opens the file again and writes nothing.
- The notebook is `lesson_notebook(name, step=…)`. Its first cell holds the passage and the note. Its meta holds `lesson.walk = {walk, step, section}`.
- It calls `ws.open_external(path)` (`leela/workspace.py:548`). That focuses the tab and tells each page that shows the workspace.
- With no folder open, it answers "Open a folder in Leela, then open this link again." and writes nothing.
- The browser tab then shows one line: "Opened in Leela." When the request came from Leela's own window, it shows the notebook.

### 4.5 What Leela writes back

Each check in a lesson with `lesson.walk` meta goes through `Learning.record` with these meta keys added:

```python
dict(walk=jid, step=i, section=section, **{'from': f'{jid}/{i}'}, app='leela')   # section only when the step has one
```

| check | kind | depth | where |
|---|---|---|---|
| predict card | `predict` | 1 | `record_card` (as today) |
| rupaka gate | `demo` | 2, or 3 with a why | `record_prediction` (new) |
| exercise full pass | `code` | 4 | `record_exercise` (as today) |

Leela never calls `put_journey`, `walk_step` or `journey_step`. A test reads the journey before and after and finds it the same.

### 4.6 The tool marker

The owner decided that the walk marker is `tool: bool` on the journey, not `kind`. Leela reads `j.get('tool')` and a step's `leela` flag only to choose what the lesson offers (the tool environment and kosha). Neither flag is ever a reason to run code.

## 5. The pane as Leela implements it

The contract is the docstring of `abhyasa-walk/abhyasa/core/pane.py`. Leela is a host. It maps the pane onto its split editor (`mountSecondary` and `leeCloseSplit`, `leela/static/lee-core.js:2249-2277`).

- A new split kind, `page`, holds an `iframe` of a local Leela URL with `pane=1`. `leePane.open(url, title)` mounts it beside the active tab. `leePane.close()` is `leeCloseSplit()`.
- The pane state is one local URL. abhyasa keeps it in `?rh=`. Leela's page URL does not carry tab state, so Leela keeps it where the split already lives: `localStorage['lee-editor-split'] = {page: url, title, direction}`. A reload mounts it again.
- The host takes a message only when `e.origin === location.origin` and `e.source === frame.contentWindow`. Every URL in a message must pass `isLocal`, the same test as `is_local` in `pane.py`.
- `rh:at {url, title, trail}`: store the new URL and title. `rh:open {url}`: load the URL in the same pane. `rh:close`: close. `rh:close {level: 1}`: go back one part of the trail, or close when there is no part.
- `rh:done {slug, outcome}`: send it on as the DOM event `abhyasa:rh-done` on `document`, with `detail = {slug, outcome}`. The detail is data that the host cannot trust: a listener uses it only as text, never as HTML or a URL.
- A page with `pane=1` sends `rh:at` on load, and sends `rh:close {level: 1}` on Esc when the focus is not in a text box.
- Leela copies `is_local` (three lines). abhyasa's version lives in `abhyasa.core`, whose `__init__` imports abhyasa's web UI, and Leela imports no abhyasa web code. The copy has a reason comment, and a contract test runs both on the same cases.

## 6. Tool and code learning

### 6.1 Tool environments

- One environment for each set of packages: the key is the first 16 hex chars of the SHA-256 of the Python `major.minor` and the sorted package names. The folder is `xdg_data_home()/leela/tools/<key>/`, with the environment in `.venv` and a `ready` file when it is complete. The `.venv` name lets kosha find the environment's `site-packages` (`kosha.core.env_path`).
- The learner (or the agent, with the learner's yes) names the packages. Each name matches a plain pattern: a name, an optional extra and an optional version. At most 5 names. No URL, no path, no `-e`, no option, no leading `-`.
- The install runs as a Leela job (`ws.jobs`, kind `tool_env`), outside the learner's code: `uv venv`, then `uv pip install --only-binary :all:`. Each name is a separate argument. No shell. This is the only network use of tool learning.
- A package with no wheel fails the install. The lesson says "<name> has no wheel for this computer, so Leela cannot install it."
- A half-made folder (no `ready`) is removed before the next try.

### 6.2 Library code checks

- A graded check on a library lesson runs `abhyasa.check.run_isolated(..., sandbox=True)` with the Python of the tool environment. This needs two engine options: `python=` (the interpreter in place of `sys.executable`) and a switch that lets the audit hook and the `sandbox-exec` profile allow a local `AF_UNIX` socket pair. Leela asks abhyasa for both. Until abhyasa ships them, Leela keeps its own runner, with a comment that gives the reason and names `leela-reuse.md` 6.4.
- asyncio needs a local socket pair to start (PydanticAI's `run_sync`). Allow `socket.socket` with `AF_UNIX` only. `connect`, `bind`, `getaddrinfo` and `sendto` stay refused.
- A library check has a 20 s total. The 2 s limit for each test stays.
- `-I -B` keeps the environment's own `site-packages` and drops the user site and the `PYTHON*` variables.
- Model tests still pass `safe_test` and `validate_exercise`. The reference solution never leaves the server.
- `check_solution` (the agent's reference-solution check) moves to `run_isolated` too, so Leela has no second copy for stdlib exercises.

### 6.3 Code lookup in the side pane

- `GET /learn/lookup?q=…&tool=<key>` is a pane page. It shows kosha results: name, package, signature, docstring and a short snippet. With `tool`, it searches the packages of that tool environment. With no `tool`, it searches the project environment through `Search` (`leela/blocks/search/search.py`).
- "Put in a scratch cell" adds a new code cell with `extra.lesson.role = 'scratch'` after the last cell. It never changes the graded exercise cell.

### 6.4 The agent as a tutor for tools

- The lesson charter becomes a function, `lesson_charter(step=None)`. It reads `prompt('tutor')` each call, and with a step it adds the passage, the note, the concept and the check.
- Leela registers its own prompt, `leela.library`, with `abhyasa.prompts.register`: the code runs with no network and no API key; use the library's offline test helpers (for PydanticAI, `TestModel` and `FunctionModel`); for a package with no known helpers, set a task on its pure functions only.
- The agent gets a lesson tool, `look_up_code(q)`, which returns the same rows as the lookup page.
- The agent follows abhyasa's anti-goals: no answer, rubric or solution before the learner tries; one check for each idea; no score or timer.

## 7. rupaka predictions and the bundle

- `lesson.js` listens for `rk-predict` on `document`. The event is `composed`, so it leaves the demo's shadow root. The listener finds the `.lee-cell[data-id]` that holds the demo and posts `{path, cell_id, gate, picked, why}` to `/lesson/predict`.
- The server finds the gate in the rupaka fences of that cell and computes `ok` itself. It ignores the `ok` and `ans` that the page sends.
- One attempt for each gate, for each version of the cell source (`card_key = "<cell id>:<source hash>:<gate>"`). "Try again" in the demo does not log a second attempt.
- Only a lesson notebook logs. In any other notebook the route answers `{ok: true, logged: false}`.
- Leela pins rupaka to one exact version. The vendored bundle is written from that wheel. `test_rupaka_vendor_version` fails on a difference, and `test_rupaka.py` reads the version from rupaka in place of the fixed `'0.0.1'`.

## 8. KaTeX

Leela already loads KaTeX from `leela/vendor/katex/` through `loadKatex` (`lee-core.js:628`), and it does not use mdhtml's `page()`, the only place that names the CDN. So Leela has no CDN load today. The plan adds a guard test only. When mdhtml ships its local loader, Leela can switch to it in a later change.

## 9. Security

| threat | what stops it |
|---|---|
| another web page links to `/learn` | the GET writes nothing and runs nothing; the page cannot be framed; the button is a same-origin POST, and the guard refuses a cross-site POST |
| a hostile query (`walk=../x`, a negative step, a long topic, unknown keys) | `read_handoff` refuses it before the store is opened; a step out of range is 400; an unknown walk is one line |
| text from the store that holds HTML | the step page escapes the passage, the note and the title |
| a forged `rk-predict` | the server reads the gate from the notebook and computes `ok`; a gate that is not in the cell is refused; one attempt for each key |
| a pane message from another origin or frame, or an off-app URL | origin and source checks; `isLocal` on every URL; `rh:done` detail is text only |
| a package name that is an option or a URL | the name pattern, at most 5, separate arguments, no shell |
| a build script at install time | `--only-binary :all:` |
| learner code that uses the network, starts a process, writes files or hangs | the closed process: the audit hook, rlimits, `sandbox-exec` on macOS, a 20 s total, a nonce on the result line; the only socket allowed is an `AF_UNIX` pair |
| tests that reach the owner's real data | an isolated `Workspace` and `Memory` under `tmp_path`, `ABHYASA_CONFIG` set to a temp folder (abhyasa's `cfg_dir` ignores `XDG_CONFIG_HOME`), the patched `projects.SERVING` |

The closed process is not a security boundary. Docs say "a closed process with no network", never "a security sandbox".

## 10. Decisions left to the builder

- The HTML of the step page and the lookup page: FastHTML FT in the `learn` block, with Leela's existing CSS variables. One muted line per state, no boxes.
- Where the pane script lives: `leela/blocks/learn/pane.js`, loaded by `lee-core.js` through the block's static route, or one function in `lee-core.js`. Prefer the block file, so the Node test loads it alone.
- How the desktop window comes to the front after `/learn/open`. Use a kavacha call if one exists. If none exists, ask for it in kavacha and keep the line "Opened in Leela."
- The kosha query shape for one tool environment (a `where` on `package`, or one `Kosha(dir=<tool dir>)` handle for each environment), after a look at the index size.
- Whether the `sandbox-exec` profile needs `(allow network* (local unix))` for the socket pair. Test it on macOS before you choose.
- The text of every message, in STE.

## 11. Decisions for the owner

1. **The abhyasa release.** Every task needs the abhyasa release that carries the walk (`abhyasa.journey.handoff`, `abhyasa.prompts`, `abhyasa.check.run_isolated`). The walk branch says 0.0.11 today. Which number, and which exact rupaka version does it require?
2. **`run_isolated(python=…, unix=True)`.** Put both options into that same abhyasa release (then Leela has no runner copy), or ship the walk first and let Leela keep a copy with a reason until a later release?
3. **No folder open.** `/learn/open` refuses with "Open a folder in Leela, then open this link again.", as `/lesson/new` does. The other choice is a fixed folder, for example `~/Leela/lessons`, that Leela opens as a workspace.
4. **Gate tries.** One attempt for each gate and cell version (the first prediction counts), or one for each try, as abhyasa logs?
5. **uv settings.** Installs use the owner's own uv config (index, certificates). The other choice is `--no-config`, which drops the owner's TLS settings.
6. **Prompt edits for Leela's own prompt.** `abhyasa.prompts.saved()` reads abhyasa's `settings.json`, so an edit made in Leela lands in abhyasa's file, and abhyasa's Settings page does not list Leela's prompt. Keep it this way, or ask abhyasa for a `store=` argument?
7. **Hints.** Leela has no hint counter, so an attempt from Leela has no `hints` value. Add a counter in a later change, or leave it out?
8. **A key for the pane.** None in this plan. Add one after the keymap audit?
