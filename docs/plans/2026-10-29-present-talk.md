# Present a notebook as a talk: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Leela's present mode gets abhyasa's group talk, Option A: a presenter view and an audience window in step over `abhyasaStage`, hands up for questions, a run log and a recap. A notebook or a code file becomes a talk in abhyasa's deck shape. Live cell output reaches the audience screen. The agent drafts speaker notes. The reveal.js overlay stays as the one-screen show, and ⌥R stays an instant show of the live notebook.

**Architecture:** The domain code is one new module, `leela/blocks/nb/talk.py`: `rise_slides`, `talk_from_notebook`, `talk_from_file`, `audience_deck`, `clean_out`, `ws_resolver` and the save calls. The routes stay in `leela/blocks/nb/app.py` beside the present routes, and `Show` holds the one live talk and its run in memory. The presenter view is a mode of the existing overlay in `present.js`, inside the IDE page, because the live cells, `runCell` and the kernel are there. The audience window is a new page, `/present/audience`, drawn by a new block module `leela/blocks/nb/audience.js` that loads abhyasa's `stage.js` and `stage.css` through a Leela route. abhyasa gives the deck shape, `check_talk`, `public_deck`, the run log, `recap`, `recap_html` and the stage. Leela adds no copy of them.

**Tech Stack:** Python 3.13, FastHTML, Starlette `TestClient`, abhyasa 0.0.12 (path source until it is on PyPI), rupaka 0.0.6 (PyPI, vendored bundle), `uv`, pytest, Node for the JS harnesses, Playwright with its bundled Chromium.

**Sources:** abhyasa `docs/superpowers/specs/2026-10-29-group-talk-design.md` (cited as "spec"), abhyasa `docs/superpowers/plans/2026-10-29-group-talk.md` section "Leela handoff" (lines 1953-1978), `abhyasa-designs/presentation/leela-reuse.md` (out of date where it disagrees with the decisions below), and the three reports in `~/.config/ramabana/runs/agent_20261028-162038-181873/` (`answer_502cbd31a446.txt`, `answer_78cf97213513.txt`, `answer_b934783c15b2.txt`).

## Decisions

Owner decisions (final):

1. ⌥R stays an instant show of the live notebook, unsaved edits included. A saved talk is made only when a room feature is used: a question, the run log or the recap.
2. Slides come from RISE cell metadata (`slide`, `subslide`, `fragment`, `skip`, `notes`). Fragments become beats. H2 headings cut slides only when a notebook has no slide metadata.
3. RISE vertical subslides are flattened into one line.
4. Two windows (presenter and audience) through `abhyasaStage` over `BroadcastChannel`. The reveal.js overlay stays as the one-screen fallback.
5. In two-window mode Esc never ends a talk. It closes one thing. The one-screen overlay keeps Esc to close.
6. The two-window talk always uses Leela's shared themes and fonts. The overlay keeps a notebook's `rise.theme` as an option, else it uses the reveal theme closest to the current shared theme.

Kept from today: start at the selected cell; live cell runs in the kernel; notes cells; the RISE editor chords; A−/A+ where it still makes sense.

Settled abhyasa contracts (abhyasa owner; the built code is the authority):

- Channel name: `'abhyasa-stage:' + tid + ':' + run.key` (`stage.js:100`, `channel(tid + ':' + key)`).
- Beats count from 1 in the deck and the run log. `go.beat` 0 means before the first beat (`stage.js:55`, spec 7.4 lines 182-184).
- Host contract `room.show(slide_id, beat=1)` (spec 17.7, line 715).
- Stage stays `v: 1`. A new type comes through `abhyasaStage.add` (`stage.js:87-96`). The v1 table is frozen.
- Leela registers `out` `{cell, html}`, with cleaned text and images only, and no script.
- abhyasa adds an ask kind `run`: the answer comes after the run, options are optional, the reveal shows the run output, `check_talk` accepts it, the recap shows the output as the answer. Its exact shape comes later. Task 12 waits on it.
- Option C (room server, phones, board) is not built. This plan is Option A only.

Decisions made in this plan (the owner can overrule each one; the open questions at the end repeat the ones that matter):

- **The presenter view lives in the IDE page.** It is the overlay in a second mode (`p.mode = 'two'`), not a new page. Only the audience window is new. Reason: a presenter page outside the IDE would need its own kernel client and its own copy of `runCell`.
- **The deck is built on the server.** The page posts the live cells (editor text from `mdSource`, outputs, slide types) to `POST /present/talk`. Python builds the talk, so `check_talk(t, schemes=('ws',))` runs on every start, and unsaved edits still show.
- **Beat names stay inside `check_talk`'s list.** Beat 1 is the slide body: `passage` when the slide has text, else `out`. Fragment group k is beat k+1, named `lit:#<id of the first cell of the group>` (`_beat_ok`, `talk.py:42-44`, accepts `lit:#` with no check). Leela's own `draw` reveals the group. abhyasa never draws a `code` slide (spec 7.2), so the name does not collide with abhyasa's "light" meaning in practice.
- **Flattening applies to the two-window talk only.** The overlay keeps reveal's vertical stacks, because reveal draws them and `test_present_slow.py:129-151` pins them. See open question 4.
- **The H2 rule applies to both modes**, in `presentSlides` and in `rise_slides`, with one shared case table, so the overlay and the talk cut a notebook the same way.
- **Leela serves the two stage files itself** (`GET /present/stage/{name}`, two names), and does not call `abhyasa.core.ui.serve_assets`, which inserts `/assets/{name}` and mounts abhyasa's `/vendor` before Leela's routes (`abhyasa/core/ui.py:34-44`).
- **A−/A+ stays in the overlay only.** The audience window uses `stage.css` sizes (46 px titles, 28 px passages at 1280 by 720, scaled). The presenter view hides A−/A+.
- **rupaka moves to `==0.0.6` in Task 0.** abhyasa 0.0.12 requires `rupaka>=0.0.6` (`abhyasa/pyproject.toml:27`), so Leela's `rupaka==0.0.3` (`pyproject.toml:21`) cannot resolve with it. The mirror needs 0.0.6 too (`stage.js:210, 217`), and Task 9 calls `abhyasaStage.mirror` for demo cells.

## Survey

Entry points and call paths this plan changes (branch `present-talk` at `0a75751`):

- Start: `present_notebook` is `alt+r`, global (`leela/core/keys.py:157`); `present_from_cell` has no key, editor scope (`keys.py:193`). Both reach `presentNotebook` (`leela/static/js/actions.js:65-66`). Toolbar button (`leela/app.py:413`), tab menu (`leela/blocks/keys/menus.py:46`), cell menu (`menus.py:39`), View menu (`menus.py:100`), palette.
- Slide types: `slide_none` to `slide_notes` (`keys.py:195-200`, `menus.py:40-41`), `SLIDE_TYPES` (`leela/blocks/nb/nb.py:32`), `Notebook.set_slide` (`nb.py:482-496`), `Notebook.rise` (`nb.py:266-268`).
- Deck: `presentSlides` (`leela/blocks/nb/present.js:44-63`), `presentAt` (`:66-72`), `riseConfig` with the `simple` default (`:75-88`, `:85`), `presentCell` (`:120-136`), `presentRun` (`:137-148`), `presentNotesPage` (`:163`), `presentNotebook` (`:165-269`), the bar (`:174-180`), the Esc handler (`:237-240`), `onOutput` (`:241-243`), `closePresentation` (`:271-287`).
- Key routing: `lee.present` puts every key in scope `overlay` (`leela/blocks/keys/keymap.js:53`).
- Server: `NAV` (`leela/blocks/nb/app.py:54`), `Show` (`app.py:103-121`), routes `/present/notes`, `/present/state`, `/present/nav`, `/present/events` (`app.py:714-743`).
- Separate pages: `inDesktopShell`, `openTab`, `openExternal` (`leela/static/js/core.js:726-740`); in the Mac app `openExternal` posts to `/browser/external`, which opens the system browser. `kavacha.window.open_window(url, title=None, key=None, url_wait=90)` opens a keyed native window (installed kavacha). `leela/desktop.py:29-38` patches `ShellApi.set_title`; `ShellApi` has no `open_window` method today.
- Guard: `learn_navigation` and `LoopbackHostGuard` (`leela/hub.py:128-148`), wrapped at `leela/app.py:1437`. No Leela page except `/learn` sends a CSP.
- Static: `/leestatic` (`leela/app.py:919`). JS bundles: `LAYERS` and `ALONE` (`tools/build_ide_js.py:24-55`).
- Agent tools: `_session_tools` (`leela/blocks/agent/ai.py:922-1003`), the `tools` property (`ai.py:1334-1346`).
- Lesson meta: `walk_meta` (`leela/blocks/nb/lesson.py:92-94`); the step brief with its note is read from the store at `lesson.py:54-57`.
- Themes: `THEMES` families with dark and light modes (`leela/blocks/settings/prefs.js:4-16`), default `cursor:light:tight` (`prefs.js:20`); tokens `--lee-bg`, `--lee-fg`, `--lee-fg2`, `--lee-fg4`, `--lee-border`, `--lee-accent` per family (`leela/static/lee-ide.css:33-230`); fonts `--lee-sans`, `--lee-mono` (`lee-ide.css:15-17`).
- Pins: `abhyasa>=0.0.11,<0.1` and `rupaka==0.0.3` (`pyproject.toml:20-21`); `[tool.uv.sources]` (`pyproject.toml:120-122`). The installed abhyasa is 0.0.11 and has no `core/stage.js` (checked with `importlib.resources`). abhyasa `main` is `0.0.12` (`abhyasa/__init__.py:11`).
- Tests today: `tests/test_present.py` (node harness `_js` at `:15-21`, grouping `:26-61`, `riseConfig` `:63-75`, one action everywhere `:99-116`, `Show` from `:118`); `tests/test_present_slow.py` (`_real_page` at `:11`, main test `:129-151`); `tests/test_web_slow.py` (`_free_port` `:40-43`, `_serve` `:45-51`, `_launch` `:55-62`); `tests/test_abhyasa_contract.py` (`test_rupaka_vendor_version` `:34`, `test_abhyasa_dependency_floor` `:42`); `tests/conftest.py` (`XDG_CONFIG_HOME` `:13`, `ABHYASA_CONFIG` `:15`, fixture `abhyasa_cfg` `:116-118`).
- `tests/routes.txt` is a hand list. No test reads it (grep). The `/present/*` routes are not in it today.

## Failure and recovery states

| state | route or call | response | test |
|---|---|---|---|
| not a notebook or code file | `presentNotebook`, `POST /present/talk` | today's message `only a notebook can be presented as slides` (for a code file: the two-window talk only) | Task 3, Task 6 |
| nothing to present | same | today's `PRESENT_NOTHING` text, 400 from the route | Task 1, Task 3 |
| `check_talk` finds problems | `POST /present/talk` | 400 with the problems joined by `; `; the overlay still opens | Task 3 |
| audience key wrong | `GET /present/audience`, `/present/deck`, `/present/img/{h}` | 403 `This is not the key of the talk.` | Task 3 |
| no live talk | same, and `POST /present/at` | 410 `This talk has ended.` | Task 3 |
| unknown slide, beat out of range | `POST /present/at` | 400, place unchanged | Task 3 |
| cross-site request | every `/present/*` route | 421 from `LoopbackHostGuard` (no exemption added) | Task 3 |
| popup refused | presenter view | a link "Open the audience window" with the same URL | Task 6 |
| Mac app | presenter view | a native window through the shell bridge, else "Present in your browser" with the URL and a copy button | Task 6 |
| audience window closed | presenter view | after 5 s with no `here`: "The audience window is closed. Open it again." | Task 6 |
| reload of the IDE | `GET /present/state` | the presenter view comes back at `run.at` | Task 8 |
| reload of the audience window | `hello` | the presenter answers with `go`, `blank`, `ask`, `result`, `demo` | Task 8 |
| server restarted | `GET /present/state` live false | the old place in `localStorage` starts a new run there; the audience window must open again (new key) | Task 8 |
| save fails | the save call | the talk goes on; the status line says why; the run stays in memory | Task 10 |

## Global Constraints

- **Task 0 first.** Every other task needs abhyasa 0.0.12 and rupaka 0.0.6 in the lock.
- **Plan review.** Before you edit code for a task, send that task (its survey lines, routes, failure states and tests) to an independent teacher sub-agent for a missing-cases review, as `AGENTS.md` asks. Task 7 also needs the keymap audit that `AGENTS.md` asks for before a new key.
- **Code style.** `CLAUDE.md`: dense fastai style, one-line docstrings, no banner comments, rationale in `docs/`. Never hand-roll what abhyasa, rupaka, fastcore or shalya does.
- **No second copy without a reason.** A copy of an abhyasa function needs a one-line comment with the reason and a test that pins it to abhyasa's version.
- **Tests never reach the owner's data.** `Workspace(roots=[tmp_path])`, `Memory(path=tmp_path/'vault.db', offline=True)`. `tests/conftest.py` already sets `XDG_CONFIG_HOME` and `ABHYASA_CONFIG` under a temp folder. A slow test serves the app with `_serve(ws, _free_port())`. Never use port 5001, never the running Leela on ports 5010-5019, never the owner's workspace.
- **Processes.** Never kill a process by name. A test stops only what it started.
- **Browser checks.** Playwright's bundled Chromium through `_launch` (`tests/test_web_slow.py:55-62`), or Chrome for Testing named by `LEELA_CHROMIUM`. Never `/Applications/Google Chrome.app`, port 9223 or `~/.cache/fastcdp/cdp-chrome`. One browser at a time, closed in a `finally`, headless, audio muted. Two windows are two pages of one context: `context.wait_for_event('page')` after the presenter's `window.open`. Browser tests go in `*_slow.py` files and run with `-m slow` (the `addopts` at `pyproject.toml:111` has `-m 'not slow'`).
- **JS bundle.** After an edit to a module in `LAYERS`, run `uv run python tools/build_ide_js.py`. A page-alone module goes into `ALONE`.
- **Routes.** Add each new route to `tests/routes.txt` (house habit; no test reads it).
- **Network.** No test uses the network. Task 0 downloads one wheel by hand, as `leela/vendor/README` says.
- **Prose.** UI text, docs and commit messages are ASD-STE100 Simplified Technical English, US grade 9. No em dashes. Read the `write_docs` pyskill first.
- **Commits.** One plain line for each task. No AI credit, no `Co-Authored-By`.
- **Pass gate for each task.** The task's own tests, then `uv run pytest -q -x --ignore-glob='*_slow.py'`, then the task's slow tests with `-m slow`.

## Review Focus

1. **Notes or answers reach the audience.** Expected: `/present/deck` and every channel message hold no `notes`, no `answer`, no path and no `src`. Tests: `test_audience_deck_has_no_notes_answers_or_paths` (Task 2), `test_stage_messages_never_carry_an_answer` (Task 9).
2. **Script in a cell output or in markdown.** Expected: `clean_out` and the audience walker drop `<script>`, event attributes, `javascript:` and remote `src`; the audience page CSP has `script-src 'self'`. Tests: `test_clean_out_keeps_text_and_images_only` (Task 2), `test_audience_walker_drops_what_the_server_missed` (Task 5), `test_audience_page_headers` (Task 3).
3. **Another site drives the talk.** Expected: 421 for a cross-site request to any `/present/*` route, 403 without the run key, and no way to frame the audience page. Test: `test_talk_routes_refuse_cross_site_and_wrong_keys` (Task 3).
4. **One stray key ends a live talk.** Expected: Esc, ⌥R, ⌥W, ⌥T, ⌥C, ⌥G, ⌥D and `/` never end or leave a two-window talk. Test: `test_esc_never_ends_a_two_window_talk` (Task 7).
5. **A reload loses the place.** Expected: either window comes back at the same slide and beat. Test: `test_reload_keeps_slide_and_beat` (Task 8).
6. **⌥R writes files.** Expected: a show that uses no room feature writes no talk file, no run and no store row. Test: `test_a_plain_show_saves_nothing` (Task 10).

## Key map in talk scope

Two-window mode sets the class `talk` on `html` while the presenter view is open. `abhyasaStage.presenter(el, ch, {keys})` binds the plain keys (`stage.js:163-202`). It ignores ⌥, ⌘ and Ctrl (`stage.js:167`), so Leela's own capture listener in `present.js` takes ⌥S. `keymap.js:53` already routes every key to scope `overlay` while `lee.present` is set, so no global command fires behind the talk.

| key | two-window talk (presenter view) | one-screen overlay | clash resolved |
|---|---|---|---|
| D, Space, Page Down, → , ↓ | next beat, then next slide | reveal next (↓: next vertical) | ↓ is "next" in the talk, because subslides are flattened (decision 3) |
| A, Shift+Space, Page Up, ←, ↑ | back one beat; back onto a slide shows its last beat | reveal previous | same as above |
| Q | open the slide's question; Q again closes it | unbound | none |
| R | show the result and the right answer | unbound | none |
| 1-6 | with a question open: the option most hands chose (`log_main`) | unbound | after G, digits pick a slide (spec 11, rule 5) |
| G, then digits | go to slide N (two digits within 1 s) | reveal default | talk uses abhyasa's rule; reveal keeps its own in the overlay |
| X | laser on or off | unbound | none |
| B | blank the audience screen (page colour and title) | reveal black screen | each mode keeps its own; the talk uses abhyasa's blank |
| E | focus into the demo; Esc leaves it | unbound | none |
| F | nothing in the presenter view; fill the screen in the audience window only | reveal full screen and the ⛶ button | the presenter keeps the ⛶ button |
| O, N, P, H, J, K, L | nothing | reveal defaults | unbound in the talk |
| Esc | close one thing: the question, the demo focus, the laser, the "After the talk" panel; never ends the talk | closes the overlay (`present.js:237-240`) | decision 5 |
| ⌥S | the main button: ask, vote again, end the talk on the last slide | unbound | Leela has no `alt+s` (only `save_all` `alt+shift+s`, `keys.py:108`) |
| ⌥B, ⌥Z | nothing (no side pane in this plan) | nothing | left for a later plan |
| ⌥R, ⌥W, ⌥T, ⌥C, ⌥G, ⌥D, `/` | nothing | nothing | scope `overlay` blocks them (`keymap.js:53`); test pins it |
| ⇧I, ⇧B, ⇧G | editor scope only | editor scope only | no clash (report 3) |
| A−/A+ buttons | hidden | kept (`present.js:211-217`) | decision in this plan |

The talk keys go into `KEYS` as a "Talk" group (`TALK_KEYS` rows from `abhyasa/core/stage.py:53-60`, without the rows for ⌥B, ⌥Z and the side pane), so the Keyboard shortcuts page and the palette show them.

---

### Task 0: Pin abhyasa 0.0.12 and rupaka 0.0.6, and write the rupaka bundle again

Goal: the lock holds abhyasa 0.0.12 from the local checkout and rupaka 0.0.6, and the vendored rupaka bundle is that version.

**Files:**
- Modify: `pyproject.toml:20-21` (`"abhyasa>=0.0.12,<0.1"`, `"rupaka==0.0.6"`), `pyproject.toml:120-122` (add `abhyasa = { path = "../abhyasa", editable = false }`, with the comment `# until abhyasa 0.0.12 is on PyPI: drop this line at that release`), `uv.lock`
- Modify: `leela/vendor/lee-rupaka.js`, `leela/vendor/lee-rupaka.css`, `leela/vendor/README:11-14` (wheel name, URL and SHA-256 of `rupaka-0.0.6-py3-none-any.whl`, read from PyPI at the time; do not copy a digest from anywhere else)
- Test: `tests/test_abhyasa_contract.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_abhyasa_contract.py: change test_abhyasa_dependency_floor (:42), add two tests
def test_abhyasa_dependency_floor():
    deps = tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['dependencies']
    assert 'abhyasa>=0.0.12,<0.1' in deps and 'rupaka==0.0.6' in deps

def test_talk_contract():
    from abhyasa.talk import TALK_SCHEMA, TALK_CASES, check_talk, new_run
    assert TALK_SCHEMA == 1
    for t, want in TALK_CASES: assert check_talk(t) == want
    run = new_run(TALK_CASES[0][0], now=1.)
    assert run['at'] == dict(slide='s1', beat=1, blank=False, pane=None, ask=None) and len(run['key']) == 16

def test_stage_contract():
    from importlib.resources import files
    from abhyasa.core.stage import STAGE_V, STAGE_TYPES, STAGE_CASES
    js = (files('abhyasa.core')/'stage.js').read_text()
    assert STAGE_V == 1 and 'out' not in STAGE_TYPES and (files('abhyasa.core')/'stage.css').is_file()
    src = js + f'\nprocess.stdout.write(JSON.stringify({json.dumps([m for m, _ in STAGE_CASES])}.map(abhyasaStage.valid)));'
    got = json.loads(subprocess.run(['node', '-'], input=src, capture_output=True, text=True, check=True).stdout)
    assert got == [ok for _, ok in STAGE_CASES]
```

Add `abhyasa.talk, abhyasa.core.stage` to the import line of `test_pure_imports_in_isolated_python` (`:27`).

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_abhyasa_contract.py -q`
Expected: FAIL. The floor test fails, and `test_stage_contract` fails with `ModuleNotFoundError: No module named 'abhyasa.core.stage'` (0.0.11 has no stage).

- [ ] **Step 3: Implement**
  - Edit `pyproject.toml`. Run `uv lock --upgrade-package abhyasa --upgrade-package rupaka`, then `uv sync`. Check that `uv.lock` names abhyasa 0.0.12 from the path and rupaka 0.0.6. Do not edit `uv.lock` by hand.
  - Follow `leela/vendor/README`: download the 0.0.6 wheel into a new empty folder, check its SHA-256 against PyPI, write both bundles with the wheel's own `rupaka.render.bundle` through `uv run --no-project --with <wheel> python -I`. Update the README line.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_abhyasa_contract.py tests/test_rupaka.py tests/test_lesson*.py -q && uv run pytest -q -x --ignore-glob='*_slow.py' && uv run pytest tests/test_rupaka_slow.py tests/test_lesson_slow.py -q -m slow`
Expected: PASS. `test_rupaka_vendor_version` (`:34`) passes with the new bundle.

**Risks:** the path source records a local path in `uv.lock`, so the app bundle build and CI on another machine cannot resolve abhyasa until the line is dropped (the comment at `pyproject.toml:121` already warns about sibling checkouts). rupaka 0.0.3 to 0.0.6 can change the API that `rupakaDraw` and `rupakaFences` use; the rupaka and lesson tests are the check.

---

### Task 1: `talk_from_notebook` and `talk_from_file`

Goal: a notebook or a code file becomes a talk in abhyasa's deck shape that passes `check_talk(t, schemes=('ws',))`.

**Files:**
- Create: `leela/blocks/nb/talk.py`
- Create: `tests/data/rise_cases.json` (the shared grouping case table; Task 2 reads it too)
- Test: `tests/test_talk_deck.py`

**Interfaces:**
- `rise_slides(cells, src=lambda c: c.source) -> list[dict]`: the flat line of slides, each `{items: [{i, frag}], notes: [i]}`. The same rules as `presentSlides` (`present.js:44-63`), subslides flattened into the line. With no `slide` or `subslide` type in any cell: a markdown cell whose text has a line `^## ` starts a slide; with no H2 either, every cell is its own slide (today's rule). Approval cells and empty cells are dropped; `skip` drops a cell; `notes` goes to `notes`.
- `talk_from_notebook(nb, path:str, root, note:str='') -> dict`: `dict(id, kind='talk', schema=1, title, src={'notebook': rel}, made, minutes=0, phones=False, live=None, slides=[...])`. `id` is `slugify(stem) + '-' + sha1(rel)[:4]` (`slugify` from `abhyasa.store`). Each slide: `id='s<n>'` from 1; `kind='code'` when it holds a code cell, else `idea`; `title` by the `presentTitle` rule (`present.js:150-156`); `section` the nearest H1 above, or `''`; `notes` the notes cells joined by a blank line (for a lesson, `note` first); `mins=1`; `show=dict(passage=<plain text of the body markdown>, figure='ws:<rel path of the first local image>' or None, demo=<slug of a rupaka fence> or None, cells=[{id, frag}], code={'path': rel, 'cell': id} for a code slide)`; `beats` per the beat decision; `ask=None`, or `ask_from_gate(spec, gate)` for the first gate of a demo; `step=walk_meta(nb)` for a lesson notebook (`lesson.py:92-94`).
- `talk_from_file(path, text, root) -> dict`: slides cut at lines matching `^# %%`; with none, one slide. `kind='code'`, `show.code={'path': rel, 'lines': [a, b]}`, beats `lines:a-b` cut at `# beat` comment lines, else one `lines:1-n` beat. `src={'file': rel}`.
- `start_place(t, cell_id) -> (slide_id, beat)`: the slide that holds the cell, or the nearest visible cell above it; beat 1 for a body cell; beat k for fragment group k (before its fragment), as `presentAt` does today.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_talk_deck.py
import json
from pathlib import Path
from abhyasa.talk import check_talk
from leela.blocks.nb.nb import Cell, Notebook
from leela.blocks.nb.talk import rise_slides, talk_from_notebook, talk_from_file, start_place

CASES = json.loads((Path(__file__).parent/'data'/'rise_cases.json').read_text())

def nb_of(rows): return Notebook([Cell(source=s, cell_type=k, metadata={'slideshow': {'slide_type': t}} if t else {}) for k, t, s in rows])

def test_rise_slides_follow_the_case_table():
    for name, case in CASES.items():
        assert [s['items'] for s in rise_slides(nb_of(case['cells']).cells)] == case['flat'], name

def test_h2_cuts_slides_only_without_slide_metadata():
    plain = nb_of([('markdown', None, '## A\ntext'), ('code', None, 'x'), ('markdown', None, '## B'), ('markdown', None, 'y')])
    assert [[x['i'] for x in s['items']] for s in rise_slides(plain.cells)] == [[0, 1], [2, 3]]
    typed = nb_of([('markdown', 'slide', '## A'), ('markdown', None, '## B')])
    assert len(rise_slides(typed.cells)) == 1

def test_a_notebook_talk_passes_check_talk(tmp_path):
    (tmp_path/'img').mkdir(); (tmp_path/'img'/'dot.png').write_bytes(b'\x89PNG\r\n\x1a\n')
    nb = nb_of([('markdown', 'slide', '# Intro\n\n![d](img/dot.png)\n\nScores become weights.'), ('markdown', 'fragment', 'later'),
                ('markdown', 'notes', 'SPEAKER'), ('code', 'subslide', 'print(1)'), ('markdown', 'skip', 'GONE')])
    t = talk_from_notebook(nb, str(tmp_path/'a.ipynb'), tmp_path)
    assert check_talk(t, schemes=('ws',)) == []
    s1, s2 = t['slides']
    assert (s1['id'], s1['kind'], s1['beats'][0], s1['beats'][1]) == ('s1', 'idea', 'passage', f'lit:#{nb.cells[1].id}')
    assert s1['show']['figure'] == 'ws:img/dot.png' and s1['notes'] == 'SPEAKER' and 'GONE' not in json.dumps(t)
    assert (s2['kind'], s2['show']['code']) == ('code', {'path': 'a.ipynb', 'cell': nb.cells[3].id})   # the subslide is the next slide
    assert start_place(t, nb.cells[1].id) == ('s1', 1) and start_place(t, nb.cells[4].id) == ('s2', 1)

def test_a_code_file_talk_has_line_beats(tmp_path):
    t = talk_from_file(str(tmp_path/'m.py'), '# %% load\nimport os\n# beat\nx = 1\n# %% use\nprint(x)\n', tmp_path)
    assert check_talk(t, schemes=('ws',)) == [] and [s['beats'] for s in t['slides']] == [['lines:1-2', 'lines:3-4'], ['lines:5-6']]

def test_a_lesson_keeps_its_step_and_note(tmp_path):
    nb = nb_of([('markdown', 'slide', '# Step')]); nb.meta['lesson'] = {'name': 'Softmax', 'walk': {'walk': 'w-1', 'step': 2, 'section': ''}}
    t = talk_from_notebook(nb, str(tmp_path/'l.ipynb'), tmp_path, note='Watch the sum.')
    assert t['slides'][0]['step']['step'] == 2 and t['slides'][0]['notes'].startswith('Watch the sum.')
```

The case table starts as the cases of `tests/test_present.py:26-61` (`typed`, `leading`, `notes_first`, `sub_first`, `untyped`, `nothing`, and the skip case), each with `cells` and `flat` (the flattened items), plus two H2 cases.

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_talk_deck.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'leela.blocks.nb.talk'`.

- [ ] **Step 3: Implement.** Read `slide_type` from `Cell.metadata['slideshow']` as `nb.py` stores it (the page sends it as `extra.slideshow`; check `Cell` for the attribute name before writing). Make images `ws:` ids relative to the first workspace root that holds them, and drop an image outside every root.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_talk_deck.py tests/test_abhyasa_contract.py -q && uv run pytest -q -x --ignore-glob='*_slow.py'`
Expected: PASS.

**Risks:** two implementations of the RISE rules (`presentSlides` in JS, `rise_slides` in Python) can drift; the shared case table in Task 2 is the guard. A notebook with more than 9999 slides has no valid slide id (`^s[0-9]{1,4}$`); refuse it with a message.

---

### Task 2: The H2 rule in the overlay, and one case table for both

Goal: the overlay cuts a notebook with no slide metadata at its H2 headings, and both groupings pass the same case table.

**Files:**
- Modify: `leela/blocks/nb/present.js:44-63` (`presentSlides`)
- Modify: `tests/test_present.py:26-61` (read `tests/data/rise_cases.json`), then rebuild `lee-core.js`
- Test: `tests/test_present.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_present.py: add
def test_both_groupings_follow_one_case_table():
    cases = json.loads((ROOT/'tests'/'data'/'rise_cases.json').read_text())
    got = _js('Object.fromEntries(Object.entries(' + json.dumps({k: [_cell(t, s, kind) for kind, t, s in c['cells']] for k, c in cases.items()}) +
              ').map(([k, v]) => [k, presentSlides(v).flat().map(s => s.items)]))')
    assert got == {k: c['flat'] for k, c in cases.items()}
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/test_present.py -q -k case_table`
Expected: FAIL on the two H2 cases (today every untyped cell is its own slide).

- [ ] **Step 3: Implement.** In `presentSlides`, when `typed` is false and any markdown cell has a line `^## `, an untyped cell continues the slide and an H2 cell opens one. `presentAt` does not change.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run python tools/build_ide_js.py && uv run pytest tests/test_present.py tests/test_talk_deck.py -q && uv run pytest -q -x --ignore-glob='*_slow.py' && uv run pytest tests/test_present_slow.py -q -m slow`
Expected: PASS. `test_present_slow.py` uses typed cells, so its counts stay 4 horizontal and 5 leaf slides.

**Risks:** an owner's untyped notebook with H2 headings now shows fewer, longer slides in the overlay. That is decision 2. `presentFit` (`present.js:28-40`) zooms or scrolls a long slide.

---

### Task 3: The audience deck and the output cleaner

Goal: the audience gets only an allow-listed copy of the talk, with cleaned markup, and a cell output becomes `out` HTML with text and images only.

**Files:**
- Modify: `leela/blocks/nb/talk.py` (`ws_resolver`, `audience_deck`, `clean_out`, `cell_html`)
- Test: `tests/test_talk_audience.py`

**Interfaces:**
- `ws_resolver(roots) -> Callable[[str], Path|None]`: `ws:<rel>` to a file inside a root, with a suffix in `abhyasa.talk.IMAGE_SUFFIXES`; None for anything else (the same checks as `asset_resolver`, `talk.py:290-297`).
- `audience_deck(t, nb, resolve) -> dict`: `public_deck(t, resolve)` (`talk.py:319-327`) plus, for each slide, `beats` (a count) and `blocks=[{id, frag, html}]` built from `show.cells` with `cell_html`; demo slides add `spec=room_spec(spec)`. Images are a map of sha256 to `/present/img/<sha>`. Never `notes`, `answer`, `src`, `step`, a path or an editor id that is not a cell id.
- `cell_html(cell, base) -> str`: markdown to HTML through `abhyasa.core.ui.md_html` and `clean_html` (check that their allow-list keeps `pre`, `code`, tables and `img`, and drops script and event attributes, before using them; else use `mdhtml` and `nh3` with Leela's own allow-list). Code cells as `<pre><code>` text.
- `clean_out(outputs, most=60_000) -> str`: `stream`, `text/plain`, `text/markdown` (cleaned), `image/png`, `image/jpeg`, `image/gif` as `data:` URLs; `text/html` cleaned to text-level tags; errors as the traceback text with ANSI codes removed. Any image that makes the HTML longer than `most` becomes `/present/img/<sha>` and goes into the image map. Never `<script>`, never `on*` attributes, never `javascript:` or a remote `src`.
- `room_spec`: import `from abhyasa.blocks.talk.app import room_spec` when `test_pure_imports_in_isolated_python` shows that the import has no side effects; else copy its six lines (`abhyasa/blocks/talk/app.py:139-145`) with a reason comment and a parity test, and ask abhyasa to move it into `abhyasa.talk`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_talk_audience.py
import json
from leela.blocks.nb.talk import audience_deck, clean_out, talk_from_notebook, ws_resolver

def test_audience_deck_has_no_notes_answers_or_paths(tmp_path): ...
    # notebook: a notes cell 'SPEAKER-SECRET', a demo fence with a gate answer, an image under tmp_path
    # d = audience_deck(t, nb, ws_resolver([tmp_path])); s = json.dumps(d)
    # assert 'SPEAKER-SECRET' not in s and '"answer"' not in s and str(tmp_path) not in s and '/Users/' not in s
    # assert d['slides'][0]['blocks'][0]['html'].startswith('<') and d['images'] and all(v.startswith('/present/img/') for v in d['images'].values())

def test_clean_out_keeps_text_and_images_only():
    outs = [{'output_type': 'stream', 'name': 'stdout', 'text': 'tick 0\n'},
            {'output_type': 'display_data', 'data': {'text/html': '<b onclick="x()">ok</b><script>alert(1)</script><img src="https://evil.example/a.png">'}},
            {'output_type': 'error', 'ename': 'ZeroDivisionError', 'evalue': 'division by zero', 'traceback': ['\x1b[31mZeroDivisionError\x1b[0m']}]
    h = clean_out(outs)
    assert 'tick 0' in h and '<b>ok</b>' in h and 'ZeroDivisionError' in h
    assert 'script' not in h and 'onclick' not in h and 'evil.example' not in h and '\x1b' not in h

def test_a_big_image_goes_by_hash():
    big = {'output_type': 'display_data', 'data': {'image/png': 'iVBORw0KGgo' + 'A' * 90_000}}
    h, imgs = clean_out([big], most=60_000, images=True)
    assert len(h) < 60_000 and '/present/img/' in h and len(imgs) == 1
```

Write the first test in full; the comment lines above give its assertions.

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_talk_audience.py -q`
Expected: FAIL with `ImportError: cannot import name 'audience_deck'`.

- [ ] **Step 3: Implement** as the interfaces say. `public_deck` reads `talks.image_mb` from abhyasa's settings (`talk.py:307`); `ABHYASA_CONFIG` in `conftest.py:15` keeps the tests off the owner's file.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_talk_audience.py tests/test_talk_deck.py -q && uv run pytest -q -x --ignore-glob='*_slow.py'`
Expected: PASS.

**Risks:** server-side markdown can differ from the IDE's `renderMarkdown` (KaTeX, Leela's own fences). The audience page loads the vendored KaTeX (`leela/vendor/katex/`) for math; other Leela-only markup shows as text. Calling `public_deck` reads abhyasa's settings file, as report 1 section 6 says.

---

### Task 4: Talk routes on the server, and the stage asset route

Goal: the server builds and holds the live talk, serves the audience page, deck, images and stage files behind the run key, and keeps the place.

**Files:**
- Modify: `leela/blocks/nb/app.py:103-121` (`Show` gets `talk`, `run`, `deck`, `images`, `path`; methods `begin`, `at`, `finish`), `app.py:714-743` (new routes beside the present routes)
- Create: `leela/static/present-audience.html` (no inline script; loads `/leestatic/lee-audience.js`)
- Modify: `tests/routes.txt`
- Test: `tests/test_talk_routes.py`

**Interfaces:**
- `POST /present/talk` JSON `{path, cells, start_cell}` (cells as the page has them: `id`, `cell_type`, editor text, `outputs`, `extra.slideshow`): builds the talk (`talk_from_notebook`, or `talk_from_file` for a code tab), runs `check_talk(t, schemes=('ws',))`, makes `new_run(t)`, moves it with `log_go` to `start_place`, and returns `{ok, tid, key, talk, at, audience: '/present/audience?k=<key>'}`. The presenter copy holds notes and answers. 400 for a non-notebook, nothing to present, or `check_talk` problems. A second start ends the first talk.
- `GET /present/audience?k=` the page; `GET /present/deck?k=` the audience deck; `GET /present/img/{h}?k=` an image from the deck or `clean_out` map, with its media type from `image_type`. 403 for a wrong key (`secrets.compare_digest`), 410 when no talk is live.
- `POST /present/at` `{k, slide, beat, blank}`: `log_go`; 400 for an unknown slide or a beat outside `0..max(1, len(beats))`; 403, 410 as above.
- `POST /present/out` `{k, outputs}` returns `{html}` from `clean_out`.
- `POST /present/finish` `{k}`: `end_run`; returns `{recap}` (Task 10 adds the save).
- `GET /present/state` keeps its shape and adds `talk: {tid, path, at}` when a talk is live (no key, no notes).
- `GET /present/stage/{name}`: only `stage.js` and `stage.css`, read with `importlib.resources.files('abhyasa.core')`, `Cache-Control: no-cache`, 404 for any other name.
- Headers on the audience page and the deck: `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`. `LoopbackHostGuard` does not change: the audience window is same-origin, and a typed URL sends `Sec-Fetch-Site: none`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_talk_routes.py
import sys
import pytest
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.hub import LoopbackHostGuard
from leela.workspace import Workspace

CELLS = [dict(id='m0', cell_type='markdown', source='# Intro\nScores become weights.', extra={'slideshow': {'slide_type': 'slide'}}, outputs=[]),
         dict(id='m1', cell_type='markdown', source='SECRET-NOTE', extra={'slideshow': {'slide_type': 'notes'}}, outputs=[]),
         dict(id='c2', cell_type='code', source='print(1)', extra={'slideshow': {'slide_type': 'slide'}}, outputs=[])]

@pytest.fixture
def rig(tmp_path):
    ws = Workspace(roots=[tmp_path], python=sys.executable)
    try:
        with TestClient(LoopbackHostGuard(ide_app(ws)), base_url='http://127.0.0.1') as c: yield c, tmp_path
    finally: ws.shutdown_now()

def start(c, root, **kw): return c.post('/present/talk', json=dict(path=str(root/'a.ipynb'), cells=CELLS, start_cell='c2', **kw))

def test_a_talk_starts_from_the_live_cells_at_the_selected_cell(rig):
    c, root = rig
    r = start(c, root).json()
    assert r['ok'] and r['at'] == {'slide': 's2', 'beat': 1} and r['talk']['slides'][0]['notes'] == 'SECRET-NOTE'
    d = c.get(f"/present/deck?k={r['key']}").json()
    assert 'SECRET-NOTE' not in str(d) and [s['id'] for s in d['slides']] == ['s1', 's2']
    assert c.post('/present/at', json=dict(k=r['key'], slide='s1', beat=1, blank=False)).status_code == 200
    assert c.post('/present/at', json=dict(k=r['key'], slide='s9', beat=1, blank=False)).status_code == 400
    assert c.post('/present/at', json=dict(k=r['key'], slide='s1', beat=7, blank=False)).status_code == 400
    assert c.get('/present/state').json()['talk']['at'] == {'slide': 's1', 'beat': 1}

def test_talk_routes_refuse_cross_site_and_wrong_keys(rig):
    c, root = rig
    k = start(c, root).json()['key']
    assert c.get('/present/deck?k=' + '0' * 16).status_code == 403
    for p in (f'/present/audience?k={k}', f'/present/deck?k={k}'):
        assert c.get(p, headers={'sec-fetch-site': 'cross-site'}).status_code == 421
    c.post('/present/finish', json=dict(k=k))
    assert c.get(f'/present/deck?k={k}').status_code == 410

def test_audience_page_headers(rig):
    c, root = rig
    r = c.get('/present/audience?k=' + start(c, root).json()['key'])
    csp = r.headers['content-security-policy']
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and r.headers['referrer-policy'] == 'no-referrer'
    assert '<script>' not in r.text and 'lee-audience.js' in r.text

def test_stage_files_come_from_abhyasa(rig):
    c, _ = rig
    assert 'abhyasaStage' in c.get('/present/stage/stage.js').text and c.get('/present/stage/stage.css').status_code == 200
    assert c.get('/present/stage/talk.js').status_code == 404 and c.get('/present/stage/..%2Fui.py').status_code == 404

def test_a_bad_start_says_why(rig):
    c, root = rig
    assert c.post('/present/talk', json=dict(path=str(root/'a.ipynb'), cells=[], start_cell='')).status_code == 400
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_talk_routes.py -q`
Expected: FAIL with 404 on `/present/talk`.

- [ ] **Step 3: Implement.** Keep `Show.update` for the notes page as it is (`test_present.py:118-142` pins it). Build the `Notebook` from the posted cells with the editor text, so unsaved edits show. Run the build with `off_loop`. Add the seven routes to `tests/routes.txt`.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_talk_routes.py tests/test_present.py -q && uv run pytest -q -x --ignore-glob='*_slow.py'`
Expected: PASS.

**Risks:** `Show` is per `ide_app` (`app.py:714`), so two IDE pages of one workspace share one live talk; a second start ends the first. The run key is in the audience URL; `Referrer-Policy: no-referrer` and same-origin keep it local.

---

### Task 5: The audience window

Goal: the audience page draws the slide, its beats, live output and the mirrored demo from the deck and the channel, in Leela's theme and fonts.

**Files:**
- Create: `leela/blocks/nb/audience.js` (`ALONE` entry `'lee-audience.js'` in `tools/build_ide_js.py:55`), `leela/blocks/nb/audience.css`
- Modify: `leela/static/present-audience.html` (from Task 4)
- Test: `tests/test_talk_audience_js.py` (node), `tests/test_talk_slow.py` (browser)

**Interfaces:**
- On load: read `k` from the query, `fetch('/present/deck?k=')`, then `abhyasaStage.add('out', {cell: ID, html: str(60000)})` with `ID` the stage id rule (`^[A-Za-z0-9_-]{1,64}$`) and `need` both fields, then `ch = abhyasaStage.channel(tid + ':' + k)`, then `abhyasaStage.audience(el, {ch, draw, title})`.
- `draw(msg)`: `go` shows slide `slide` with blocks whose group is below `beat` (beat 1 shows the body, beat k+1 adds group k, beat 0 shows the title only); `ask` shows the question card (text by `textContent`); `result` shows the hands line; `demo` and `answers` go to `mirror(host).apply` and `reveal`; `end` shows "Thank you" and the title; `out` replaces the output box of cell `cell` after `safeHtml`.
- `safeHtml(html) -> DocumentFragment`: parse with `DOMParser`, keep only `p, pre, code, span, div, b, i, em, strong, br, table, thead, tbody, tr, th, td, ul, ol, li, img`, keep only `class`, and `src` on `img` when it matches `^data:image/(png|jpeg|gif|webp);base64,` or `^/present/img/[0-9a-f]{64}$`.
- Theme: `<html class="talk" data-theme data-mode>` from the saved theme (`settings.py:279-289` reads it), and `audience.css` maps stage tokens to Leela tokens: `--bg: var(--lee-bg); --fg: var(--lee-fg); --ink2: var(--lee-fg2); --mute: var(--lee-fg4); --line: var(--lee-border); --rule: var(--lee-border); --acc: var(--lee-accent); --serif: var(--lee-sans); --head: var(--lee-sans); --mono: var(--lee-mono)` and `--ok`, `--no` from Leela's success and error tokens. The page loads `lee-ide.css` for the token blocks only through a `link`. A `storage` event on `lee-theme` changes the attributes.
- F fills the screen. Any other key shows "Keys work in the presenter window" for 3 s (spec 9.1).

- [ ] **Step 1: Write the failing tests**
  - Node: `test_audience_walker_drops_what_the_server_missed`: `safeHtml` on `<img src=x onerror=alert(1)>`, `<a href="javascript:x">`, `<svg><script>`, `<img src="https://evil.example/a">`, and a good `data:image/png` image keeps the good image and text only. Use a minimal DOM in node (`linkedom` is not a dependency: give `safeHtml` the parser as an argument and test it with the browser in the slow test if node has no DOMParser).
  - Node: `test_out_type_is_added_once`: after `abhyasaStage.add('out', ...)`, `valid({v:1, t:'out', cell:'c2', html:'<pre>1</pre>'})` is true, a 70 kB `html` and an extra field are false, and a second `add('out')` throws.
  - Slow, `test_the_audience_window_follows_go_and_blank`: start a talk through `POST /present/talk`, open the audience page in a second page of the same context, send `go` s1 beat 1, `go` s1 beat 2 (the fragment shows), `blank` on (the title shows), from a third page that opens the same channel. Assert the computed background equals `--lee-bg` of the theme.

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_talk_audience_js.py -q && uv run pytest tests/test_talk_slow.py -q -m slow -k audience`
Expected: FAIL with 404 for `/leestatic/lee-audience.js`.

- [ ] **Step 3: Implement.** Load rupaka from the vendored bundle the IDE already serves. Load KaTeX from `/leestatic` only when a block has math.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run python tools/build_ide_js.py && uv run pytest tests/test_talk_audience_js.py tests/test_talk_routes.py -q && uv run pytest -q -x --ignore-glob='*_slow.py' && uv run pytest tests/test_talk_slow.py -q -m slow -k audience`
Expected: PASS.

**Risks:** `stage.css` expects abhyasa's token names (report 1 section 6); a missing token falls back to the browser default. The packaging tests (`test_present.py:149-163`) must also ship `lee-audience.js`, `audience.css` and `present-audience.html`; add them there.

---

### Task 6: The presenter view and opening the audience window

Goal: from the overlay, the presenter turns on two-window mode, which opens the audience window and shows the slide, notes, next slide, clock and question card in the IDE page.

**Files:**
- Modify: `leela/blocks/nb/present.js:165-287` (`presentTalk`, `p.mode`, the bar button "audience", the presenter layout, `closePresentation`)
- Modify: `leela/static/js/actions.js:65-66` (add `present_talk`), `leela/core/keys.py:193` region (`Key('present_talk', '', 'editor', 'present with an audience window')`), `leela/blocks/keys/menus.py:39,46,100` (one row each), `leela/static/lee-ide.css:4029-4054` (`.lee-present.two` rules)
- Modify: `leela/desktop.py:29-38` (patch `ShellApi.open_window(url, title)` to `kavacha.window.open_window(url, title, key='leela-audience')`)
- Test: `tests/test_present.py`, `tests/test_talk_slow.py`

**Interfaces:**
- `presentTalk(start)`: posts `/present/talk`, sets `p.mode = 'two'`, adds `talk` to `html`, opens `ch = abhyasaStage.channel(tid + ':' + key)` after loading `/present/stage/stage.js`, registers `out`, calls `abhyasaStage.presenter(slideEl, ch, {keys})`, and draws the presenter layout: the slide (Leela's own `presentCell` per block, so ▶ still runs the real cell), the rail of slides, the notes (rendered with `allow_raw:false`), the next slide's title, the clock (time used, and the slot from a number field stored per notebook in `localStorage`), and the question card. It does not open `/present/notes`.
- The bar gets a button "audience" in the one-screen overlay; it calls `presentTalk` at the current slide. `present_talk` from the palette, cell menu, tab menu and View menu does the same at the selected cell. ⌥R does not change (decision 1).
- Opening: on the first click or key, `window.open('/present/audience?k=' + key, 'leela-audience-' + tid, 'popup,width=1280,height=720')`. With `inDesktopShell()`: `window.pywebview.api.open_window(url, 'Audience')`. When either gives nothing, the view shows the link "Open the audience window". In the shell, when the spike below fails, it shows "Present in your browser" with `location.origin` and a copy button (spec 9.4, lines 369-372).
- Liveness: `hello` gets the place; with no `here` for 5 s the view shows "The audience window is closed. Open it again."
- `closePresentation` in two-window mode sends `end` only through "End the talk" (Task 10); × asks "End the talk?" first.

- [ ] **Step 1: Spike (manual, on the Mac app, before code).** Two pywebview windows opened with `kavacha.window.open_window` on one origin: does a `BroadcastChannel` message from one reach the other? Write the answer in the task's commit body. Two WKWebViews share a channel only when they share a website data store; this is not verified.
- [ ] **Step 2: Write the failing tests**
  - Fast: `test_present_talk_is_one_action_everywhere` (as `test_present.py:99-116`): `lookup('present_talk')`, the tab, cell and View menu rows, `present_talk:` in `actions.js`, and `_dupes(DEFAULTS) == []`.
  - Fast: `test_the_shell_bridge_can_open_a_window`: `hasattr(ShellApi, 'open_window')` after `import leela.desktop`, with `open_window` patched to record its call.
  - Slow, `test_two_windows_follow_each_other`: open a notebook, run `present_talk`, catch the popup with `context.wait_for_event('page')`, press D in the presenter view, and wait until the audience shows the next beat; close the audience page and wait for the "closed" line; `window.open` refused (`page.add_init_script` that makes it return null) shows the link.
- [ ] **Step 3: Run the tests to see them fail**

Run: `uv run pytest tests/test_present.py -q -k "present_talk or shell_bridge" && uv run pytest tests/test_talk_slow.py -q -m slow -k two_windows`
Expected: FAIL with `KeyError` from `lookup('present_talk')`.

- [ ] **Step 4: Implement** as the interfaces say. Keep the one-screen overlay paths and tests as they are.

- [ ] **Step 5: Run the tests to see them pass**

Run: `uv run python tools/build_ide_js.py && uv run pytest tests/test_present.py -q && uv run pytest -q -x --ignore-glob='*_slow.py' && uv run pytest tests/test_present_slow.py tests/test_talk_slow.py -q -m slow`
Expected: PASS.

**Risks:** in the Mac app, `openExternal` sends a page to the system browser (`core.js:735-740`), which shares no `BroadcastChannel` with WKWebView. The native-window path depends on the spike. The "Present in your browser" fallback opens a second IDE client on the same workspace.

---

### Task 7: The talk key map

Goal: every key in the key map table above does what the table says, and no stray key ends a two-window talk.

**Files:**
- Modify: `leela/blocks/nb/present.js` (the `keys` object for `abhyasaStage.presenter`, the ⌥S listener, the Esc rule at `:237-240`)
- Modify: `leela/core/keys.py` (a "Talk" group from `TALK_KEYS`, as display rows; no new global binding)
- Test: `tests/test_present.py`, `tests/test_talk_slow.py`

**Interfaces:**
- `keys`: `KeyD`, `Space`, `PageDown`, `ArrowRight`, `ArrowDown` next; `KeyA`, `Shift+Space`, `PageUp`, `ArrowLeft`, `ArrowUp` back; `KeyQ`, `KeyR`, `KeyX`, `KeyB`, `KeyE`, `KeyG` and `1`-`6` as the table says; `Escape` closes one thing and returns true when nothing is open, so the key stops there.
- `p.onKey` (`present.js:237-240`) returns at once when `p.mode === 'two'`.
- ⌥S: a capture listener active only in two-window mode.
- Next and back post `/present/at` and send `go`. Back onto a slide goes to its last beat (spec 7.4).

- [ ] **Step 1: Write the failing tests**
  - Fast: `test_talk_keys_are_listed_and_left_hand`: the "Talk" rows in `KEYS` equal `TALK_KEYS` without the ⌥B, ⌥Z rows; every plain letter is in `present.js`'s `keys` object (read as text, as `test_keys.py` does for the Graph).
  - Fast (node): `test_next_and_back_walk_beats_in_one_line`: a pure `step(deck, at, d)` in `present.js` gives `s1:1 -> s1:2 -> s2:1` forward and `s2:1 -> s1:2` back.
  - Slow, `test_esc_never_ends_a_two_window_talk`: in two-window mode, press Esc with a question open (it closes), Esc again (talk still live: `/present/state` has `talk`), then ⌥R, ⌥W, ⌥T, `/`: the overlay is still there and no new tab or palette opened. In the one-screen overlay Esc still closes (the existing test stays green).
- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_present.py -q -k "talk_keys or beats_in_one_line" && uv run pytest tests/test_talk_slow.py -q -m slow -k esc`
Expected: FAIL.

- [ ] **Step 3: Implement.** Audit first: `keys.py`, `keymap.js`, the palette and `menus.py`, as `AGENTS.md` asks; write the audit result in the commit body.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run python tools/build_ide_js.py && uv run pytest tests/test_present.py tests/test_keys.py -q && uv run pytest -q -x --ignore-glob='*_slow.py' && uv run pytest tests/test_present_slow.py tests/test_talk_slow.py -q -m slow`
Expected: PASS.

**Risks:** a clicker that sends `B` or `.` for blank works as reveal's in the overlay and as abhyasa's in the talk. `Space` on a focused bar button: `stage.js:173` calls `preventDefault`, and the bar already returns focus to the root (`present.js:224`).

---

### Task 8: Reload keeps the slide and the beat

Goal: a reload of the IDE page or of the audience window comes back at the same slide and beat.

**Files:**
- Modify: `leela/blocks/nb/present.js` (resume on tab load; `localStorage['lee-talk:<path>'] = {tid, key, slide, beat}`), `leela/blocks/nb/app.py` (`GET /present/state` already carries `talk.at` from Task 4)
- Test: `tests/test_talk_slow.py`

**Interfaces:**
- On a notebook tab load, when `/present/state` has a live talk for this path and `localStorage` holds its key: `presentTalk` resumes at `talk.at` with the same key, so the open audience window keeps working. With no live talk but a stored place: the overlay offers "Go on from slide N"; a new run starts there with a new key.
- The audience window: `hello` on load; the presenter answers with `go`, `blank`, `ask`, `result`, `demo`, and `answers` after R (spec 9.2, `hello` row).

- [ ] **Step 1: Write the failing test.** Slow, `test_reload_keeps_slide_and_beat`: go to s2 beat 2, reload the audience page, wait for s2 beat 2; reload the IDE page, wait for the presenter view at s2 beat 2, press D, and see the audience follow without opening it again.
- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/test_talk_slow.py -q -m slow -k reload`
Expected: FAIL (the overlay does not come back after a reload).

- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run python tools/build_ide_js.py && uv run pytest -q -x --ignore-glob='*_slow.py' && uv run pytest tests/test_talk_slow.py -q -m slow`
Expected: PASS.

**Risks:** the key in `localStorage` is readable by any script on the origin; it already reads the deck by being same-origin, so the key adds no reach.

---

### Task 9: Live output and demos on the audience screen

Goal: a cell run in the presenter view shows its cleaned output on the audience screen, and a rupaka demo cell is mirrored there.

**Files:**
- Modify: `leela/blocks/nb/present.js:137-148` (`presentRun`) and `:241-243` (`onOutput`): in two-window mode, post `/present/out` and send `{t: 'out', cell, html}`
- Modify: `leela/blocks/nb/present.js` (demo cells: `abhyasaStage.mirror(host)` on the cell's rupaka mount, `watch` sends `demo`; the gate's `rk-predict` gets `preventDefault()` and `detail.settle(true)`, so nothing is logged, spec 10 lines 381-383)
- Modify: `leela/blocks/nb/audience.js` (`out`, `demo`, `answers`)
- Test: `tests/test_talk_slow.py`, `tests/test_present.py`

- [ ] **Step 1: Write the failing tests**
  - Fast (node): `test_stage_messages_never_carry_an_answer`: the pure message builders in `present.js` (`askMsg`, `outMsg`, `demoMsg`) on a slide whose ask has `answer` give messages with no `answer` key, and `abhyasaStage.valid` passes each one.
  - Slow, `test_a_run_streams_to_the_audience`: the `tick` cell of `test_present_slow.py:23` run from the presenter view shows `tick 2` on the audience page; `1/0` shows `ZeroDivisionError`; a cell that prints `<script>window.hit=1</script>` as `text/html` leaves `window.hit` undefined in the audience page.
  - Slow, `test_a_demo_is_mirrored`: a rupaka fence slide; moving the presenter's slider changes the audience copy's state; the audience gate is `inert`; `lr.attempts()` is unchanged after a gate pick.
- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_present.py -q -k answer && uv run pytest tests/test_talk_slow.py -q -m slow -k "streams or mirrored"`
Expected: FAIL.

- [ ] **Step 3: Implement.** Send `out` at most once per animation frame per cell; the last output wins.
- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run python tools/build_ide_js.py && uv run pytest tests/test_present.py tests/test_talk_audience.py -q && uv run pytest -q -x --ignore-glob='*_slow.py' && uv run pytest tests/test_talk_slow.py tests/test_rupaka_slow.py -q -m slow`
Expected: PASS.

**Risks:** running a cell writes its outputs into the notebook (`present.js:142,146`), as today (report 3, row 7). Output larger than 64 kB after image hashing is cut with "Output is too long for the room screen.".

---

### Task 10: Room features, the saved talk and the recap

Goal: questions with hands, room questions and the run log save the talk and the run only when used, and "After the talk" shows the recap and saves the recap file.

**Files:**
- Modify: `leela/blocks/nb/talk.py` (`save_talk`, `save_run`, behind the store chosen in open question 1)
- Modify: `leela/blocks/nb/app.py` (`POST /present/ask` `{k, slide, open}`, `POST /present/hands` `{k, slide, main}`, `POST /present/question` `{k, text, note}`, `GET /present/recap.html?k=`; `POST /present/finish` saves), `tests/routes.txt`
- Modify: `leela/blocks/nb/present.js` (question card, 1-6, the "Add a question from the room" field, "End the talk", the "After the talk" panel)
- Test: `tests/test_talk_room.py`, `tests/test_talk_slow.py`

**Interfaces:**
- The first room action (`ask`, `hands`, `question`) saves the talk once and marks the run `saved`; each later change saves the run. Navigation alone saves nothing.
- `hands` calls `log_main(run, slide, kind, main)`; `ask` sends `ask` with `public_ask`; R sends `result` with `right` from the presenter copy.
- `finish`: `end_run`, save when `saved`, return `recap(t, run)`. "After the talk" lists `unsure`, the slides with time, and the room questions with a note field (`POST /present/question` with `note`). "Save the recap as one file" downloads `recap_html(t, run, ws_resolver(roots))` as `<stem>-recap.html`. abhyasa's "Make a follow-up walk" is not in Leela.
- Neither path calls `Learning.record` (spec 17.3).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_talk_room.py (uses the rig and CELLS of tests/test_talk_routes.py, with a demo slide that has a gate)
def test_a_plain_show_saves_nothing(rig): ...
    # start, move through every slide, finish: no '*.talk.json' under root, no run in the store, recap['slides'] lists the slides
def test_hands_save_the_talk_and_the_run_once(rig): ...
    # start, ask on the demo slide, hands main=1, question 'Why?', finish: one talk saved, its run has asks[s].main == 1 and questions[0].text == 'Why?'
    # Learning(...).attempts() is unchanged
def test_recap_file_has_no_notes_and_no_script(rig): ...
    # GET /present/recap.html?k=: 200, attachment, 'SECRET-NOTE' not in text, '<script' not in text, the right answer is marked
```

Write each test in full; the comment lines give the assertions.

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_talk_room.py -q`
Expected: FAIL with 404 on `/present/ask`.

- [ ] **Step 3: Implement.** With the shared store, `put_talk` runs `check_talk(t)` with `('asset',)` (`abhyasa/talk.py:243`) and refuses `ws:` figures: that path needs an abhyasa change first (open question 1).
- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_talk_room.py tests/test_talk_routes.py -q && uv run pytest -q -x --ignore-glob='*_slow.py' && uv run pytest tests/test_talk_slow.py -q -m slow`
Expected: PASS.

**Risks:** a save that fails (read-only folder, locked vault) must not stop the talk: the status line says why and the run stays in memory until "End the talk". `recap_html` shows passages only for slides whose beats include `passage` (`talk.py:313-316`), which is why beat 1 is `passage`.

---

### Task 11: Themes for both modes

Goal: the overlay uses `rise.theme` when a notebook sets it, else the reveal theme closest to the current Leela theme; the two-window talk uses Leela's theme and fonts.

**Files:**
- Modify: `leela/blocks/nb/present.js:75-88` (`riseConfig` gives `theme: null` when `rise.theme` is not a reveal theme; `revealThemeFor(theme)` picks one), `:246-247` (the theme link)
- Test: `tests/test_present.py:63-75`

**Interfaces:**
- `revealThemeFor({family, mode})`: `solarized` light to `solarized`; `dracula` dark to `dracula`; `gruvbox` and `ember` light to `beige`; any other dark to `black`; any other light to `white`.

- [ ] **Step 1: Write the failing test.** Change `test_rise_settings_reach_reveal_by_name_and_nothing_else_does`: an empty or bad `rise` gives `theme: null`; add `revealThemeFor` cases for each family in `prefs.js:4-16` in both modes.
- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/test_present.py -q -k rise_settings`
Expected: FAIL (`simple` where `null` is expected).

- [ ] **Step 3: Implement.** `presentNotebook` uses `cfg.theme || revealThemeFor(lee.theme)`.
- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run python tools/build_ide_js.py && uv run pytest tests/test_present.py -q && uv run pytest -q -x --ignore-glob='*_slow.py' && uv run pytest tests/test_present_slow.py -q -m slow`
Expected: PASS.

**Risks:** a notebook with no `rise.theme` changes look from `simple` to `white` or `black`. That is decision 6.

---

### Task 12: "What does this print?" (waits on abhyasa's `run` ask kind)

Goal: on a code slide the presenter asks the room what the cell prints, takes hands, runs the cell, and the output is the answer.

**Needs abhyasa:** the `run` ask kind in `ASK_KINDS` and `check_talk`, its `public_ask` shape, its `ask` stage message rule (the v1 `ASK` rule at `stage.js:49` allows only `choice`, `order`, `words`, `scale`), and the recap that shows the output. Its exact shape is not given yet. Do not start this task before the abhyasa release that has it, and pin that version in this task.

**Files:**
- Modify: `leela/blocks/nb/talk.py` (`ask_for_cell(cell, options=None)`), `leela/blocks/nb/app.py` (`POST /present/run-answer` `{k, slide, html}` logs the output as the answer), `leela/blocks/nb/present.js` (Q on a code slide with no ask opens a `run` ask; R runs the cell, then reveals), `leela/blocks/nb/audience.js`, `pyproject.toml` (abhyasa floor)
- Modify: `leela/blocks/agent/ai.py:922-1003` (optional: a session tool `draft_run_options(path, cell_id)` that returns 3 wrong outputs as a draft; drop it if abhyasa's shape has no options)
- Test: `tests/test_talk_room.py`, `tests/test_abhyasa_contract.py` (the `run` case in `TALK_CASES`), `tests/test_talk_slow.py`

- [ ] **Step 1: Write the failing tests** against abhyasa's published shape: `check_talk` accepts the `run` ask from `ask_for_cell`; the `ask` message holds no answer before the run; after R the run log holds the output and `recap_html` shows it; the order is ask, hands, (talk, hands again), run.
- [ ] **Steps 2 to 4:** as in the other tasks. Gate: `uv run pytest tests/test_talk_room.py tests/test_abhyasa_contract.py -q && uv run pytest -q -x --ignore-glob='*_slow.py' && uv run pytest tests/test_talk_slow.py -q -m slow -k print`

**Risks:** a cell with side effects runs in front of the room; the run is the presenter's own press of R, never automatic. A cell that does not finish leaves the question open; Esc closes it and the interrupt key still works in the IDE.

---

### Task 13: Speaker notes drafted by the agent

Goal: the agent writes a draft notes cell for a slide, which the presenter then edits; the agent never changes notes the presenter wrote.

The smallest change is one session tool and one action. The agent can already read cells (`notebook_cells`) and run them (`run_cell`, `ai.py:925`), but no tool sets a cell's slide type, so it cannot make a notes cell today.

**Files:**
- Modify: `leela/blocks/agent/ai.py:922-1003` (`draft_notes` in `_session_tools`, added to the list at `:1003`)
- Modify: `leela/blocks/nb/talk.py` (`NOTES_PROMPT = register('leela.notes', 'Speaker notes', 'What the agent writes as a draft speaker note for a slide.', dflt)` with `abhyasa.prompts.register`)
- Modify: `leela/static/js/actions.js`, `leela/core/keys.py` (`Key('draft_notes', '', 'editor', 'draft speaker notes for this slide')`), `leela/blocks/keys/menus.py:39-41` (cell menu row): the action sends the agent one message built from `prompt('leela.notes')`, the path and the cell id, through the same path as `agent_selection` (`keys.py:123`)
- Test: `tests/test_talk_notes.py`

**Interfaces:**
- `draft_notes(path:str, cell_id:str, text:str) -> str`: finds the slide that holds `cell_id` with `rise_slides` on the saved notebook; inserts a markdown cell after the slide's last cell with `slideshow.slide_type = 'notes'` (`Notebook.set_slide`, `nb.py:482`) and `metadata.leela.draft = sha1(text)`; saves with `nb.save(p, sandbox=host.ws.fs)` as `add_exercise` does (`ai.py:979-986`). When the slide already has a draft cell whose source still hashes to its `draft` value, it replaces that text. When the presenter changed the draft, or wrote their own notes cell, it adds nothing and returns `the slide has notes the presenter wrote; nothing changed`. It refuses a path that is not an `.ipynb`.
- The default prompt: notes are short spoken lines for the presenter, about the slide's cells only; no new facts that the slide does not show; at most 5 lines. Saved edits go to abhyasa's prompt settings, as `leela.library` does in the earlier plan.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_talk_notes.py
def test_draft_notes_adds_one_notes_cell_and_keeps_the_presenters(tmp_path): ...
    # a notebook with two slides; draft_notes(p, first-slide cell, 'Say hi.') adds one notes cell after slide 1 with the draft hash
    # a second call with 'Say hello.' replaces that text (one notes cell, not two)
    # edit the cell source by hand, then call again: the result names the presenter's notes and the file is unchanged
    # a slide with a notes cell that has no draft mark: nothing changes
    # the notes reach talk_from_notebook(...)['slides'][0]['notes'] and never audience_deck(...)
def test_draft_notes_is_a_session_tool(): ...
    # 'draft_notes' in the names of _session_tools(host) with a stub host
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_talk_notes.py -q`
Expected: FAIL with `ImportError` or a missing tool name.

- [ ] **Step 3: Implement** as the interfaces say.
- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_talk_notes.py tests/test_present.py -q && uv run pytest -q -x --ignore-glob='*_slow.py'`
Expected: PASS.

**Risks:** the tool writes the file while the tab can hold unsaved edits; it uses the same save path as `add_exercise`, so the tab's reload behaviour is the same as for an added exercise. The draft hash is lost when another tool rewrites the cell metadata.

---

### Task 14: Docs

Goal: one design note says how the two modes differ and why.

**Files:**
- Create: `docs/present.md` (the two modes, the key map, the beat names, where talks and runs are kept, the run key and CSP)
- Modify: `CHANGELOG.md`

Gate: `uv run pytest -q -x --ignore-glob='*_slow.py'`. Read `write_prose` before writing `docs/present.md`.

---

## Order and sequencing

| task | needs | files it changes | can run beside |
|---|---|---|---|
| 0 Pins and rupaka bundle | none | `pyproject.toml`, `uv.lock`, `leela/vendor/*`, `tests/test_abhyasa_contract.py` | nothing (first) |
| 1 `talk_from_notebook` | 0 | `leela/blocks/nb/talk.py`, `tests/data/rise_cases.json`, `tests/test_talk_deck.py` | 2, 11, 13 (13 after 1's `rise_slides` merges) |
| 2 H2 rule in the overlay | 0; the shared-table test after 1 | `present.js`, `tests/test_present.py` | 1, 3, 4 |
| 3 Audience deck and cleaner | 1 | `talk.py`, `tests/test_talk_audience.py` | 2, 11 |
| 4 Routes and stage assets | 1, 3 | `nb/app.py`, `static/present-audience.html`, `tests/routes.txt`, `tests/test_talk_routes.py` | 2, 11, 13 |
| 5 Audience window | 4 | `nb/audience.js`, `nb/audience.css`, `present-audience.html`, `tools/build_ide_js.py`, `tests/test_talk_audience_js.py`, `tests/test_talk_slow.py` | 11, 13 |
| 6 Presenter view, opening | 4, 5 | `present.js`, `actions.js`, `keys.py`, `menus.py`, `lee-ide.css`, `desktop.py`, `tests/test_present.py`, `tests/test_talk_slow.py` | 13 (after 13's `keys.py` and `menus.py` rows merge, or rebase) |
| 7 Talk keys | 6 | `present.js`, `keys.py`, `tests/test_present.py`, `tests/test_talk_slow.py` | 13 |
| 8 Reload | 7 | `present.js`, `tests/test_talk_slow.py` | 13 |
| 9 Live output and demos | 6 | `present.js`, `audience.js`, `tests/test_present.py`, `tests/test_talk_slow.py` | 13 |
| 10 Room features and recap | 8, 9; open question 1 answered | `talk.py`, `nb/app.py`, `present.js`, `tests/routes.txt`, `tests/test_talk_room.py`, `tests/test_talk_slow.py` | 13 |
| 11 Themes | 0 | `present.js:75-88, 246-247`, `tests/test_present.py` | 1, 3, 4, 5 |
| 12 "What does this print?" | 10 and abhyasa's `run` kind | `talk.py`, `nb/app.py`, `present.js`, `audience.js`, `ai.py`, `pyproject.toml`, tests | nothing (waits) |
| 13 Notes draft tool | 1 | `ai.py`, `talk.py` (`NOTES_PROMPT` only), `actions.js`, `keys.py`, `menus.py`, `tests/test_talk_notes.py` | 2 to 11 |
| 14 Docs | 10 | `docs/present.md`, `CHANGELOG.md` | 12 |

Shared files, so these tasks run one after another or rebase: `present.js` (2, 6, 7, 8, 9, 10, 11, 12), `talk.py` (1, 3, 10, 12, 13), `nb/app.py` (4, 10, 12), `keys.py` and `menus.py` (6, 7, 13), `actions.js` (6, 13), `tests/test_present.py` (2, 6, 7, 9, 11), `tests/test_talk_slow.py` (5 to 10, 12), `ai.py` (12, 13), `tests/routes.txt` (4, 10).

Two writers in parallel after Task 0: writer A takes the Python line 1, 3, 4; writer B takes the JS line 2, then 11. After Task 4, writer A takes 13 (agent and notes) while writer B takes 5, 6, 7, 8, 9. Task 10 needs both lines and the owner's answer to open question 1.

## Open questions for the owner

1. **Where a saved talk and its run log live.** Choices: abhyasa's shared store (`put_talk`, `put_run`), or `<notebook>.talk.json` beside the notebook. Recommendation: the talk as `<notebook>.talk.json` beside the notebook (it goes with the project and into git, as `leela-reuse.md:250-252` proposes), and the run logs in the shared learning store with `Learning.put_run` (room data stays out of git; `put_run` runs no check). The shared store for the talk itself needs an abhyasa change first: `put_talk` checks with `('asset',)` only (`abhyasa/talk.py:243`) and refuses `ws:` figures.
2. **What "shared themes and fonts" names.** This plan reads it as Leela's theme families and its fonts (`--lee-*` tokens, `--lee-sans`, `--lee-mono`). If it means abhyasa's themes (paper, ink, manuscript) and its Literata and Libre Baskerville fonts, only `audience.css` changes. Recommendation: Leela's own, so the audience matches the IDE the presenter uses.
3. **The Mac app.** If the Task 6 spike shows that two pywebview windows do not share a `BroadcastChannel`, choose between "Present in your browser" (abhyasa's answer, spec 9.4) and a server relay over the existing `/present/events` stream (not `BroadcastChannel`, so outside decision 4). Recommendation: "Present in your browser" now; the relay only if the owner allows a second channel.
4. **Flatten subslides in the overlay too?** Decision 3 is applied to the two-window talk only. Recommendation: keep reveal's vertical stacks in the overlay, because reveal draws them and RISE users expect them there.
5. **Fragment beat names.** This plan uses `lit:#<cell id>` for a fragment group, inside `check_talk`'s list. Recommendation: keep it, or ask abhyasa for a `frag:<n>` beat if abhyasa will ever draw a Leela talk.
6. **Drop the path source.** `[tool.uv.sources] abhyasa` must go when abhyasa 0.0.12 is on PyPI, before any Leela release. Recommendation: make that a release check in `pullup`'s release workflow, so a release with a path source fails.
7. **Should ⌥R open two windows when a second screen is attached?** Decision 1 keeps ⌥R instant. Recommendation: no; ⌥R stays the one-screen overlay, and the "audience" button or `present_talk` turns on two-window mode.
