# Present a notebook as a talk: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Leela's present mode gets abhyasa's group talk, Option A: a presenter view and an audience window in step over `abhyasaStage`, hands up for questions, a run log and a recap. A notebook becomes a talk in abhyasa's deck shape. Live cell output reaches the audience screen. The agent drafts speaker notes. The reveal.js overlay stays as the one-screen show, and ⌥R stays an instant show of the live notebook. Only notebooks are presented (owner decision).

**Architecture:** The domain code is one new module, `leela/blocks/nb/talk.py`: `rise_slides`, `demo_fences`, `talk_from_notebook`, `audience_deck`, `clean_out`, `clip_msg`, `out_text`, `ws_resolver`, `room_spec` (a copy with a parity test) and the save calls. The routes stay in `leela/blocks/nb/app.py` beside the present routes. `Show` holds the one live talk, its run, its run key, its image map and its live state (latest output per cell, the open question, the result, the demo snapshots). The presenter view is a mode of the existing overlay in `present.js`, inside the IDE page, because the live cells, `runCell` and the kernel are there. The audience window is a new page, `/present/audience`, drawn by a new page-alone module `leela/blocks/nb/audience.js`, which also defines Leela's stage type `out` for both windows. It loads abhyasa's `stage.js` and `stage.css` through a Leela route. abhyasa gives the deck shape, `check_talk`, `public_deck`, the run log, `recap`, `recap_html` and the stage. Leela adds no copy of them, except `room_spec`.

**Tech Stack:** Python 3.13, FastHTML, Starlette `TestClient`, abhyasa 0.0.12 (path source until it is on PyPI), rupaka 0.0.6 (PyPI, vendored bundle), `uv`, pytest, Node for the JS harnesses, Playwright with its bundled Chromium.

**Sources:** abhyasa `docs/superpowers/specs/2026-10-29-group-talk-design.md` (cited as "spec"), abhyasa `docs/superpowers/plans/2026-10-29-group-talk.md` section "Leela handoff" (lines 1953-1978), `abhyasa-designs/presentation/leela-reuse.md` (out of date where it disagrees with the decisions below), the three reports in `~/.config/ramabana/runs/agent_20261028-162038-181873/` (`answer_502cbd31a446.txt`, `answer_78cf97213513.txt`, `answer_b934783c15b2.txt`), and the independent review of this plan at `2396512`, folded in below.

## Decisions

Owner decisions (final):

1. ⌥R stays an instant show of the live notebook, unsaved edits included. A saved talk is made only when a room feature is used: a question, the run log or the recap.
2. Slides come from RISE cell metadata (`slide`, `subslide`, `fragment`, `skip`, `notes`). Fragments become beats. H2 headings cut slides only when a notebook has no slide metadata.
3. RISE vertical subslides are flattened into one line.
4. Two windows (presenter and audience) through `abhyasaStage` over `BroadcastChannel`. The reveal.js overlay stays as the one-screen fallback.
5. In two-window mode Esc never ends a talk. It closes one thing. The one-screen overlay keeps Esc to close.
6. The two-window talk always uses Leela's shared themes and fonts. The overlay keeps a notebook's `rise.theme` as an option, else it uses the reveal theme closest to the current shared theme.
7. A saved talk is `<notebook>.talk.json` beside the notebook. Run logs go to the shared learning store with `Learning.put_run`. (Owner, 29 October.)
8. "Shared themes and fonts" means Leela's own theme families and fonts (`--lee-*` tokens, `--lee-sans`, `--lee-mono`), so the audience matches the IDE. (Owner, 29 October.)
9. In the Mac app, if two app windows do not share a `BroadcastChannel`, the two-window talk offers "Present in your browser". There is no second messaging path. (Owner, 29 October.)
10. The one-screen overlay keeps reveal's vertical stacks. ⌥R always opens the one-screen overlay, also with a second screen attached. The two-window talk starts from its own button and command, "Present to a room". (Owner, 29 October.)
11. Before any Leela release, the abhyasa path source is removed, and a release check fails while it is there. (Owner, 29 October.)

Kept from today: start at the selected cell; live cell runs in the kernel; notes cells; the RISE editor chords; A−/A+ where it still makes sense.

Settled abhyasa contracts (abhyasa owner; the built code is the authority; checked against abhyasa `main` at `21fc333`):

- Channel name: `'abhyasa-stage:' + tid + ':' + run.key` (`stage.js:100`, `channel(tid + ':' + key)`).
- Beats count from 1 in the deck and the run log. `go.beat` 0 means before the first beat. `go.beat` is at most 50 (`stage.js:55`, `int(0, 50)`).
- A message is valid only when `JSON.stringify(m).length` is at most 65536 (`stage.js:9` `MOST`, `stage.js:81`). The length is in UTF-16 code units.
- Host contract `room.show(slide_id, beat=1)` (spec 17.7, line 715).
- Stage stays `v: 1`. Leela does not change the v1 table. A Leela type comes through `abhyasaStage.add` (`stage.js:87-96`), which throws for a name that is there.
- `abhyasaStage.audience` subscribes only to the fixed `DRAWN` list (`stage.js:117`, `:150`). A type added with `add` reaches `draw` only through an explicit `ch.on`.
- On `main` today the v1 `ask` rule accepts only the kinds `choice`, `order`, `words`, `scale` (`stage.js:49`), and `result` the same four (`stage.js:62`). abhyasa is changing this before 0.0.12 ships (owner of abhyasa, final): `ask` and `result` accept kind `run` (`q`, optional 2 to 6 string options, no answer before the run; the result carries the output or the matching option); a new shared v1 type `output` `{slide, text}` carries the run's plain text, no HTML, clipped so the serialised message fits the 65536 limit; `output` is in `DRAWN`, so `abhyasaStage.audience` forwards it with no extra `ch.on`; `TALK_CASES` gets a `run` row (accepted with no answer, refused with an answer or with 1 option). The change goes to branch `answer-fixes`, then `main`.
- `public_deck` returns `title`, `slides` and `images`, and no talk id (`abhyasa/talk.py:319-327`).
- `new_run` sets `at` to `{slide, beat, blank, pane, ask}` (`talk.py:335`). `log_go` updates `slide` and `beat` only (`talk.py:347`).
- `log_question` always appends a new question (`talk.py:373-377`). abhyasa has no call that edits a question's note.
- `md_html` renders a fenced block as a `pre` and does not remove rupaka fences (`abhyasa/core/ui.py:145-150`).
- abhyasa commit `e68823c` (branch `answer-fixes`, not on `main` yet) adds the ask kind `run` to `ASK_KINDS`, `check_talk` rules (2 to 6 string options, or none; no answer), `log_output(run, slide, text)` (keeps characters `>= ' '` except DEL, plus `\n` and `\t`, then clips to 2000 characters), `recap(...).slides[i].output`, and `recap_html` that shows the output escaped in a `pre`. Task 12 waits for the `main` commit that has both `e68823c` and the stage change above.
- Option C (room server, phones, board) is not built. This plan is Option A only.

Decisions made in this plan (the owner can overrule each one; the open questions at the end repeat the ones that matter):

- **The presenter view lives in the IDE page.** It is the overlay in a second mode (`p.mode = 'two'`), not a new page. Only the audience window is new. A presenter page outside the IDE would need its own kernel client and its own copy of `runCell`.
- **The deck is built on the server.** The page posts the live cells (editor text from `mdSource`, outputs, `extra.slideshow`) to `POST /present/talk`. Python builds the talk. `check_talk(t, schemes=('ws',))` runs on every start, and unsaved edits still show.
- **Demo fences leave the markdown before anything else is built.** `demo_fences(md)` takes every ```` ```rupaka ```` fence out of a markdown cell's text. The passage, the audience blocks and the recap are built from the text without fences. The spec goes only to `show.demo` on the presenter copy and, through `room_spec`, to the audience deck.
- **Beat names stay inside `check_talk`'s list.** Beat 1 is the slide body: `passage` when the slide has text, else `out`. Fragment group k is beat k+1, named `lit:#<id of the first cell of the group>` (`_beat_ok`, `talk.py:42-44`, accepts `lit:#` with no check). Leela's own `draw` reveals the group. A slide has at most 50 beats, so at most 49 fragment groups.
- **Notes-only slides get no audience slide.** A slide whose cells are all `notes` makes no talk slide. Its notes join the notes of the next visible slide. A notebook with only notes cells is "nothing to present".
- **Leela's one stage type, `out`.** `audience.js` defines it once, in `talkTypes(S)`, and both windows call it before they open the channel. Its fields, all required: `cell` (the stage `ID` rule), `gen` (int 0..1e9), `seq` (int 0..1e9), `html` (string). The presenter sends it with cleaned rich markup (text and images, no script); the whole message is at most 65536. Run answers do not use `out`: they use abhyasa's `output` and `log_output` with plain text (Task 12).
- **Flattening applies to the two-window talk only.** The overlay keeps reveal's vertical stacks, because reveal draws them and `test_present_slow.py:129-151` pins them. See open question 4.
- **The H2 rule applies to both modes**, in `presentSlides` and in `rise_slides`, with one shared case table.
- **Leela serves the two stage files itself** (`GET /present/stage/{name}`, two names, no key), and does not call `abhyasa.core.ui.serve_assets`, which inserts `/assets/{name}` and mounts abhyasa's `/vendor` before Leela's routes (`abhyasa/core/ui.py:34-44`).
- **One image URL contract.** Every image the audience loads by URL is `/present/img/{sha256}?k=<run key>`. The server route, `clean_out`, `audience_deck` and the audience walker's `safeHtml` use this one form. `Show.images` maps a sha256 to `(bytes, media type)`. `begin` fills it from `public_deck`'s images. `POST /present/out` adds the images that `clean_out` moved out of the markup. `finish` keeps it for the recap. The next `begin` clears it.
- **The run key is a bearer capability.** Whoever holds it can read the audience deck and images and, with the presenter routes, drive the talk. It lives in the audience URL, in `localStorage['lee-talk:<path>']` and in `Show`. `Show.finish` keeps it only for the recap routes. The next `begin` drops it. `LoopbackHostGuard` refuses cross-site requests and foreign Host headers. It is not same-origin authorisation, and this plan does not rely on it as one.
- **A−/A+ stays in the overlay only.** The audience window uses `stage.css` sizes. The presenter view hides A−/A+.
- **rupaka moves to `==0.0.6` in Task 0.** abhyasa 0.0.12 requires `rupaka>=0.0.6` (`abhyasa/pyproject.toml:27`), so Leela's `rupaka==0.0.3` (`pyproject.toml:21`) cannot resolve with it. The mirror needs 0.0.6 too (`stage.js:210, 217`).

## Survey

Entry points and call paths this plan changes (branch `present-talk` at `2396512`):

- Start: `present_notebook` is `alt+r`, global (`leela/core/keys.py:157`); `present_from_cell` has no key, editor scope (`keys.py:193`). Both reach `presentNotebook` (`leela/static/js/actions.js:65-66`). Toolbar button (`leela/app.py:413`), tab menu (`leela/blocks/keys/menus.py:46`), cell menu (`menus.py:39`), View menu (`menus.py:100`), palette.
- Slide types: `slide_none` to `slide_notes` (`keys.py:195-200`, `menus.py:40-41`), `SLIDE_TYPES` (`leela/blocks/nb/nb.py:32`), `Notebook.set_slide` (`nb.py:482-496`), `Notebook.rise` (`nb.py:266-268`). `Cell` has `extra`, not `metadata` (`nb.py:151-173`); the slide type is `cell.extra['slideshow']['slide_type']`.
- Deck: `presentSlides` (`leela/blocks/nb/present.js:44-63`), `presentAt` (`:66-72`), `riseConfig` (`:75-88`), `presentCell` (`:120-136`), `presentRun` (`:137-148`), `presentNotesPage` (`:163`), `presentNotebook` (`:165-269`), the bar (`:174-180`), the Esc handler (`:237-240`), `onOutput` (`:241-243`), the reveal theme link (`:246-247`), the Reveal instance and its `keyboardCondition` (`:250-253`), `closePresentation` (`:271-287`).
- Key routing: `lee.present` puts every key in scope `overlay` (`leela/blocks/keys/keymap.js:53`), and `findBinding` returns no binding in scope `overlay` (`keymap.js:155`). During a show no Leela key fires, the interrupt key included.
- Kernel: `interrupt` posts `/kernel/interrupt` (`actions.js:37-38`); `restart` posts `/kernel/restart` and calls `markPreviousRuns` (`actions.js:41`, defined at `leela/blocks/editor/mount.js:493`). Every page restart path calls `markPreviousRuns` except the "Restart kernel" button of the inspector error (`leela/blocks/runtime/kernel.js:35`). Routes at `leela/blocks/runtime/app.py:123,137`.
- Server: `NAV` (`leela/blocks/nb/app.py:54`), `Show` (`app.py:103-121`), routes `/present/notes`, `/present/state`, `/present/nav`, `/present/events` (`app.py:714-743`).
- Separate pages: `inDesktopShell`, `openTab`, `openExternal` (`leela/static/js/core.js:726-740`); in the Mac app `openExternal` opens the system browser. `kavacha.window.open_window(url, title=None, key=None, url_wait=90)` returns the existing window for a known `key` and raises it without navigating it, and returns a native `Window` object (`kavacha/kavacha/window.py:464-475`). `leela/desktop.py:29-38` patches `ShellApi.set_title`; `ShellApi` has no `open_window` method today.
- Guard: `learn_navigation` and `LoopbackHostGuard` (`leela/hub.py:128-148`), wrapped at `leela/app.py:1437`. No Leela page except `/learn` sends a CSP.
- Static: `/leestatic` serves `leela/static` then `leela/vendor` (`leela/core/web.py:33-35`, route at `leela/app.py:919`). The Mac app copies `leela/static` without its `js` folder (`packaging/macos/setup.py:21`). JS bundles: `LAYERS` and `ALONE` (`tools/build_ide_js.py:24-55`). `orphans()` reports any `blocks/*/*.js` that `modules()` does not name, and `modules()` reads `LAYERS` only (`build_ide_js.py:59-62`, `:77-85`).
- Themes: `THEMES` (`leela/blocks/settings/prefs.js:4-16`), default `cursor:light:tight` (`prefs.js:20`); `themeMode` resolves `system` (`prefs.js:52`); `paintTheme` writes `data-theme` and `data-mode` (`prefs.js:56-59`); a media listener repaints for `system` (`prefs.js:79`). Tokens per family in `leela/static/lee-ide.css:33-230`, fonts `--lee-sans`, `--lee-mono` (`lee-ide.css:15-17`). The code font is the editor setting `fontFamily` (`leela/blocks/settings/settings.py:26`).
- Agent tools: `_session_tools` (`leela/blocks/agent/ai.py:922-1003`), the `tools` property (`ai.py:1334-1346`).
- Lesson meta: `walk_meta` (`leela/blocks/nb/lesson.py:92-94`); the rupaka fence writer `fence` (`lesson.py:277`).
- Pins: `abhyasa>=0.0.11,<0.1` and `rupaka==0.0.3` (`pyproject.toml:20-21`); `[tool.uv.sources]` (`pyproject.toml:120-122`). The installed abhyasa is 0.0.11 and has no `core/stage.js`. abhyasa `main` is `0.0.12`.
- Tests today: `tests/test_present.py` (node harness `_js` at `:15-21`, grouping `:26-61`, `riseConfig` `:63-75`, one action everywhere `:99-116`, `Show` from `:118`, packaging `:149-163`); `tests/test_present_slow.py` (`_real_page` at `:11`, main test `:129-151`); `tests/test_web_slow.py` (`_free_port` `:40-43`, `_serve` `:45-51`, `_launch` `:55-62`); `tests/test_abhyasa_contract.py` (`test_rupaka_vendor_version` `:34`, `test_abhyasa_dependency_floor` `:42`); `tests/conftest.py` (`XDG_CONFIG_HOME` `:13`, `ABHYASA_CONFIG` `:15`).
- `tests/routes.txt` is a hand list. No test reads it. The `/present/*` routes are not in it today.

## Failure and recovery states

| state | route or call | response | test |
|---|---|---|---|
| not a notebook | `presentNotebook`, `POST /present/talk` | today's message `only a notebook can be presented as slides`; 400 | Task 4 |
| nothing to present, or notes only | same | today's `PRESENT_NOTHING` text, 400 | Task 1, Task 4 |
| `check_talk` problems, more than 50 beats on a slide | `POST /present/talk` | 400 with the problems joined by `; `; the overlay still opens | Task 1, Task 4 |
| wrong or stale run key | every route with `k` | 403 `This is not the key of the talk.` | Task 4 |
| no live talk | same | 410 `This talk has ended.` | Task 4 |
| talk finished | mutation routes, `/present/deck` | 410 `This talk has ended.`; `/present/recap` and `/present/recap.html` still 200 with the old key | Task 10 |
| unknown slide, beat out of range | `POST /present/at` | 400, place unchanged | Task 4 |
| output for a cell that is not a visible slide cell | `POST /present/out` | 400, nothing sent | Task 9 |
| stale output reply (older `gen` or `seq`) | `POST /present/out`, audience `out` | dropped, 200 with `{stale: true}` | Task 9 |
| output over the message limit | `clip_msg` | clipped at a block edge, with `Output is too long for the room screen.` | Task 9 |
| demo snapshot over the message limit | presenter | not sent; status line `The demo is too large for the room screen.`; audience keeps the last state | Task 9 |
| cross-site request | every `/present/*` route | 421 from `LoopbackHostGuard` (no exemption added) | Task 4 |
| second talk starts | `POST /present/talk` | old run ends and is saved if `saved`; `end` on the old channel; old presenter shows `Another talk started.` | Task 4, Task 6 |
| popup refused | presenter view | the button "Open the audience window" stays | Task 6 |
| Mac app | presenter view | a native window keyed by run through the shell bridge, else "Present in your browser" with the URL and a copy button | Task 6 |
| audience window closed | presenter view | after 5 s with no `here`: "The audience window is closed. Open it again." | Task 6 |
| cell does not finish | presenter view | the Stop button interrupts the kernel | Task 9 |
| kernel restart | presenter view | stale output cleared on both screens, a pending run reveal cancelled, the run button enabled | Task 9 |
| reload of the IDE | `POST /present/resume` | the presenter view comes back at `run.at` with its live state, same key, no new run | Task 8 |
| stale `localStorage` while another talk is live | `POST /present/resume` | 410; the page clears the entry; the live talk is not touched | Task 8 |
| reload of the audience window | `hello` | the presenter replays `go`, `blank`, the open `ask`, `result`, `output`, `out` per cell, `demo`, `answers` | Task 8 |
| server restarted | `POST /present/resume` 410 | the overlay offers "Go on from slide N"; a new run starts there; the audience window must open again (new key) | Task 8 |
| save fails | the save call | the talk goes on; the status line says why; the run stays in memory | Task 10 |

## Global Constraints

- **Task 0 first.** Every other task needs abhyasa 0.0.12 and rupaka 0.0.6 in the lock.
- **Plan review.** Before you edit code for a task, send that task (its survey lines, routes, failure states and tests) to an independent teacher sub-agent for a missing-cases review, as `AGENTS.md` asks. Task 7 also needs the keymap audit that `AGENTS.md` asks for before a new key.
- **Code style.** `CLAUDE.md`: dense fastai style, one-line docstrings, no banner comments, rationale in `docs/`. Never hand-roll what abhyasa, rupaka, fastcore or shalya does.
- **No second copy without a reason.** A copy of an abhyasa function needs a one-line comment with the reason and a test that pins it to abhyasa's version.
- **Tests never reach the owner's data.** `Workspace(roots=[tmp_path])`, `Memory(path=tmp_path/'vault.db', offline=True)`. `tests/conftest.py` already sets `XDG_CONFIG_HOME` and `ABHYASA_CONFIG` under a temp folder. A slow test serves the app with `_serve(ws, _free_port())`. Never use port 5001, never the running Leela on ports 5010-5019, never the owner's workspace.
- **Processes.** Never kill a process by name. A test stops only what it started.
- **Browser checks.** Playwright's bundled Chromium through `_launch` (`tests/test_web_slow.py:55-62`), or Chrome for Testing named by `LEELA_CHROMIUM`. Never `/Applications/Google Chrome.app`, port 9223 or `~/.cache/fastcdp/cdp-chrome`. One browser at a time, closed in a `finally`, headless, audio muted. Two windows are two pages of one context: `context.wait_for_event('page')` after the presenter's `window.open`. Browser tests go in `*_slow.py` files and run with `-m slow` (`pyproject.toml:111` has `-m 'not slow'`).
- **JS bundle.** After an edit to a module in `LAYERS`, run `uv run python tools/build_ide_js.py`. It writes `leela/static/lee-core.js` and the other bundles. A page-alone module goes into `ALONE`.
- **Routes.** Add each new route to `tests/routes.txt` (house habit; no test reads it).
- **Network.** No test uses the network. Task 0 downloads one wheel by hand, as `leela/vendor/README` says.
- **Prose.** UI text, docs and commit messages are ASD-STE100 Simplified Technical English, US grade 9. No em dashes. Read the `write_docs` pyskill first.
- **Commits.** One plain line for each task. No AI credit, no `Co-Authored-By`.
- **Pass gate for each task.** The task's own tests, then `uv run pytest -q -x --ignore-glob='*_slow.py'`, then the task's slow tests with `-m slow`.

## Review Focus

1. **Notes or answers reach the audience before reveal.** Expected: `/present/deck`, the audience page and every channel message before R hold no `notes`, no `answer`, no gate answer value, no path and no `src`. After R, `result.right` and `answers` carry the answer by design. Tests: `test_audience_deck_has_no_notes_answers_or_paths` (Task 3), `test_a_gate_answer_never_reaches_the_audience_before_reveal` (Task 3, Task 9).
2. **Script in a cell output or in markdown.** Expected: `clean_out` and the audience walker drop `<script>`, event attributes, `javascript:` and remote `src`; the audience page CSP has `script-src 'self'`. Tests: `test_clean_out_keeps_text_and_images_only` (Task 3), `test_audience_walker_drops_what_the_server_missed` (Task 5), `test_audience_page_headers` (Task 4).
3. **Another page drives the talk.** Expected: 421 for a cross-site request to any `/present/*` route, 403 without the run key or with a stale key on every mutation route, no way to frame the audience page, and the presenter ignores every channel message from the audience except `hello` and `here`. Tests: `test_every_mutation_route_refuses_cross_site_and_wrong_keys` (Task 4), `test_presenter_ignores_presenter_messages_from_the_channel` (Task 6).
4. **One stray key ends a live talk.** Expected: Esc, ⌥R, ⌥W, ⌥T, ⌥C, ⌥G, ⌥D and `/` never end or leave a two-window talk. Test: `test_esc_never_ends_a_two_window_talk` (Task 7).
5. **A reload loses the place or the live state.** Expected: either window comes back at the same slide and beat, with the same output, open question, result and demo. Tests: `test_reload_keeps_slide_and_beat`, `test_reload_mid_run`, `test_reload_after_reveal` (Task 8).
6. **⌥R writes files.** Expected: a show that uses no room feature writes no talk file, no run and no store row. Test: `test_a_plain_show_saves_nothing` (Task 10).

## Key map in talk scope

Two-window mode sets the class `talk` on `html` while the presenter view is open. `abhyasaStage.presenter(el, ch, {keys})` binds the plain keys (`stage.js:163-202`). It ignores ⌥, ⌘ and Ctrl (`stage.js:167`), and keys in a text box (`stage.js:169`), so Leela's own capture listener in `present.js` takes ⌥S. `keymap.js:53` routes every key to scope `overlay` while `lee.present` is set, and `keymap.js:155` gives no binding there, so no Leela command fires behind the talk. The interrupt key does not fire either. The presenter view has a Stop button for that (Task 9).

| key | two-window talk (presenter view) | one-screen overlay | clash resolved |
|---|---|---|---|
| D, Space, Page Down, → , ↓ | next beat, then next slide | reveal next (↓: next vertical) | ↓ is "next" in the talk, because subslides are flattened (decision 3) |
| A, Shift+Space, Page Up, ←, ↑ | back one beat; back onto a slide shows its last beat | reveal previous | same as above |
| Q | open the slide's question; Q again closes it | unbound | none |
| R | show the result and the right answer | unbound | none |
| 1-6 | with a question open: the option most hands chose (`log_main`) | unbound | after G, digits pick a slide (spec 11, rule 5) |
| G, then digits | go to slide N (two digits within 1 s) | reveal default | talk uses abhyasa's rule; reveal keeps its own in the overlay |
| X | laser on or off | unbound | none |
| B | blank the audience screen (page colour and title) | reveal black screen | each mode keeps its own |
| E | focus into the demo; Esc leaves it | unbound | none |
| F | nothing in the presenter view; fill the screen in the audience window only | reveal full screen and the ⛶ button | the presenter keeps the ⛶ button |
| O, N, P, H, J, K, L | nothing | reveal defaults | unbound in the talk |
| Esc | close one thing: a confirm dialog, the question, the demo focus, the laser, the "After the talk" panel, fullscreen; never ends the talk | closes the overlay (`present.js:237-240`) | decision 5 |
| ⌥S | the main button: ask, vote again, end the talk on the last slide | unbound | Leela has no `alt+s` (only `save_all` `alt+shift+s`, `keys.py:108`) |
| ⌥B, ⌥Z | nothing (no side pane in this plan) | nothing | left for a later plan |
| ⌥R, ⌥W, ⌥T, ⌥C, ⌥G, ⌥D, `/` | nothing | nothing | scope `overlay` blocks them (`keymap.js:53,155`); test pins it |
| ⇧I, ⇧B, ⇧G | editor scope only | editor scope only | no clash (report 3) |
| A−/A+ buttons | hidden | kept (`present.js:211-217`) | decision in this plan |

The talk keys go into `KEYS` as a "Talk" group (`TALK_KEYS` rows from `abhyasa/core/stage.py:53`, without the rows for ⌥B, ⌥Z and the side pane), so the Keyboard shortcuts page and the palette show them.

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
Expected: FAIL. The floor test fails, and `test_stage_contract` fails with `ModuleNotFoundError: No module named 'abhyasa.core.stage'`.

- [ ] **Step 3: Implement**
  - Edit `pyproject.toml`. Run `uv lock --upgrade-package abhyasa --upgrade-package rupaka`, then `uv sync`. Check that `uv.lock` names abhyasa 0.0.12 from the path and rupaka 0.0.6. Do not edit `uv.lock` by hand.
  - Follow `leela/vendor/README`: download the 0.0.6 wheel into a new empty folder, check its SHA-256 against PyPI, write both bundles with the wheel's own `rupaka.render.bundle` through `uv run --no-project --with <wheel> python -I`. Update the README line.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_abhyasa_contract.py tests/test_rupaka.py tests/test_lesson*.py -q && uv run pytest -q -x --ignore-glob='*_slow.py' && uv run pytest tests/test_rupaka_slow.py tests/test_lesson_slow.py -q -m slow`
Expected: PASS.

**Risks:** the path source records a local path in `uv.lock`, so the app bundle build and CI on another machine cannot resolve abhyasa until the line is dropped. rupaka 0.0.3 to 0.0.6 can change the API that `rupakaDraw` and `rupakaFences` use; the rupaka and lesson tests are the check.

---

### Task 1: `talk_from_notebook` and `demo_fences`

Goal: a notebook becomes a talk in abhyasa's deck shape that passes `check_talk(t, schemes=('ws',))`, with demo fences taken out of the slide text.

**Files:**
- Create: `leela/blocks/nb/talk.py`
- Create: `tests/data/rise_cases.json` (the shared grouping case table; Task 2 reads it too)
- Test: `tests/test_talk_deck.py`

**Interfaces:**
- `rise_slides(cells, src=lambda c: c.source) -> list[dict]`: the flat line of slides, each `{items: [{i, frag}], notes: [i]}`. The same rules as `presentSlides` (`present.js:44-63`), subslides flattened into the line. With no `slide` or `subslide` type in any cell: a markdown cell whose text has a line `^## ` starts a slide; with no H2 either, every cell is its own slide (today's rule). Approval cells and empty cells are dropped; `skip` drops a cell; `notes` goes to `notes`. A slide with no items gives its notes to the next slide with items and is dropped.
- `demo_fences(md) -> (str, list[dict])`: the text with every ```` ```rupaka ```` or `~~~rupaka` fence removed, and the parsed specs in order. A fence that does not parse as JSON is removed too, and its slide gets no demo.
- `talk_from_notebook(nb, path:str, root, note:str='') -> dict`: `dict(id, kind='talk', schema=1, title, src={'notebook': rel}, made, minutes=0, phones=False, live=None, slides=[...])`. `id` is `slugify(stem) + '-' + sha1(rel)[:4]` (`slugify` from `abhyasa.store`). Each slide: `id='s<n>'` from 1; `kind='code'` when it holds a code cell, else `idea`; `title` by the `presentTitle` rule (`present.js:150-156`); `section` the nearest H1 above, or `''`; `notes` the notes cells joined by a blank line (for a lesson, `note` first); `mins=1`; `show=dict(passage=<plain text of the body markdown after demo_fences>, figure='ws:<rel path of the first local image>' or None, demo=<slug of the first fence> or None, specs=[...], cells=[{id, frag}], code={'path': rel, 'cell': id} for a code slide)`; `beats` per the beat decision; `ask=None`, or `ask_from_gate(spec, gate)` for the first gate of a demo; `step=walk_meta(nb)` for a lesson notebook. Raises `ValueError` with `slide <n> has more than 50 beats` or `more than 9999 slides`.
- `start_place(t, cell_id) -> (slide_id, beat)`: the slide that holds the cell, or the nearest visible cell above it; beat 1 for a body cell; beat k for fragment group k (before its fragment), as `presentAt` does today.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_talk_deck.py
import json, pytest
from pathlib import Path
from abhyasa.talk import check_talk
from leela.blocks.nb.nb import Cell, Notebook
from leela.blocks.nb.talk import rise_slides, talk_from_notebook, start_place, demo_fences

CASES = json.loads((Path(__file__).parent/'data'/'rise_cases.json').read_text())

def nb_of(rows): return Notebook([Cell(source=s, cell_type=k, extra={'slideshow': {'slide_type': t}} if t else {}) for k, t, s in rows])

def test_rise_slides_follow_the_case_table():
    for name, case in CASES.items():
        assert [s['items'] for s in rise_slides(nb_of(case['cells']).cells)] == case['flat'], name

def test_h2_cuts_slides_only_without_slide_metadata():
    plain = nb_of([('markdown', None, '## A\ntext'), ('code', None, 'x'), ('markdown', None, '## B'), ('markdown', None, 'y')])
    assert [[x['i'] for x in s['items']] for s in rise_slides(plain.cells)] == [[0, 1], [2, 3]]
    typed = nb_of([('markdown', 'slide', '## A'), ('markdown', None, '## B')])
    assert len(rise_slides(typed.cells)) == 1

def test_notes_only_slides_make_no_slide(tmp_path):
    nb = nb_of([('markdown', 'notes', 'LEAD'), ('markdown', 'slide', '# A'), ('markdown', 'slide', ''), ('markdown', 'notes', 'TAIL')])
    t = talk_from_notebook(nb, str(tmp_path/'a.ipynb'), tmp_path)
    assert [s['id'] for s in t['slides']] == ['s1'] and t['slides'][0]['notes'].startswith('LEAD')
    with pytest.raises(ValueError): talk_from_notebook(nb_of([('markdown', 'notes', 'only')]), str(tmp_path/'b.ipynb'), tmp_path)

def test_a_slide_has_at_most_50_beats(tmp_path):
    nb = nb_of([('markdown', 'slide', '# A')] + [('markdown', 'fragment', f'f{i}') for i in range(50)])
    with pytest.raises(ValueError, match='more than 50 beats'): talk_from_notebook(nb, str(tmp_path/'a.ipynb'), tmp_path)

def test_demo_fences_leave_the_text():
    md = 'Before\n\n```rupaka\n{"slug": "d1", "gates": [{"id": "g", "type": "gate", "answer": {"is": "ANSWER-7731"}}]}\n```\n\nAfter'
    text, specs = demo_fences(md)
    assert 'ANSWER-7731' not in text and 'rupaka' not in text and 'Before' in text and 'After' in text and specs[0]['slug'] == 'd1'

def test_a_notebook_talk_passes_check_talk(tmp_path):
    (tmp_path/'img').mkdir(); (tmp_path/'img'/'dot.png').write_bytes(b'\x89PNG\r\n\x1a\n')
    nb = nb_of([('markdown', 'slide', '# Intro\n\n![d](img/dot.png)\n\nScores become weights.'), ('markdown', 'fragment', 'later'),
                ('markdown', 'notes', 'SPEAKER'), ('code', 'subslide', 'print(1)'), ('markdown', 'skip', 'GONE')])
    t = talk_from_notebook(nb, str(tmp_path/'a.ipynb'), tmp_path)
    assert check_talk(t, schemes=('ws',)) == []
    s1, s2 = t['slides']
    assert (s1['id'], s1['kind'], s1['beats'][0], s1['beats'][1]) == ('s1', 'idea', 'passage', f'lit:#{nb.cells[1].id}')
    assert s1['show']['figure'] == 'ws:img/dot.png' and s1['notes'] == 'SPEAKER' and 'GONE' not in json.dumps(t)
    assert (s2['kind'], s2['show']['code']) == ('code', {'path': 'a.ipynb', 'cell': nb.cells[3].id})
    assert start_place(t, nb.cells[1].id) == ('s1', 1) and start_place(t, nb.cells[4].id) == ('s2', 1)

def test_a_lesson_keeps_its_step_and_note(tmp_path):
    nb = nb_of([('markdown', 'slide', '# Step')]); nb.meta['lesson'] = {'name': 'Softmax', 'walk': {'walk': 'w-1', 'step': 2, 'section': ''}}
    t = talk_from_notebook(nb, str(tmp_path/'l.ipynb'), tmp_path, note='Watch the sum.')
    assert t['slides'][0]['step']['step'] == 2 and t['slides'][0]['notes'].startswith('Watch the sum.')
```

The case table starts as the cases of `tests/test_present.py:26-61` (`typed`, `leading`, `notes_first`, `sub_first`, `untyped`, `nothing`, and the skip case), each with `cells` and `flat`, plus two H2 cases and one leading-notes case.

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_talk_deck.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'leela.blocks.nb.talk'`.

- [ ] **Step 3: Implement.** Read `slide_type` from `cell.extra['slideshow']` (`nb.py:173`). The page posts it as `extra.slideshow` too. Make images `ws:` ids relative to the first workspace root that holds them, and drop an image outside every root. Use the fence language `rupaka`, as `lesson.py:277` writes it.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_talk_deck.py tests/test_abhyasa_contract.py -q && uv run pytest -q -x --ignore-glob='*_slow.py'`
Expected: PASS.

**Risks:** two implementations of the RISE rules (`presentSlides` in JS, `rise_slides` in Python) can drift; the shared case table in Task 2 is the guard.

---

### Task 2: The H2 rule in the overlay, and one case table for both

Goal: the overlay cuts a notebook with no slide metadata at its H2 headings, and both groupings pass the same case table.

**Files:**
- Modify: `leela/blocks/nb/present.js:44-63` (`presentSlides`), then rebuild `leela/static/lee-core.js`
- Modify: `tests/test_present.py:26-61` (read `tests/data/rise_cases.json`; do not change the table)
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
Expected: FAIL on the two H2 cases and the leading-notes case.

- [ ] **Step 3: Implement.** In `presentSlides`, when `typed` is false and any markdown cell has a line `^## `, an untyped cell continues the slide and an H2 cell opens one. A slide with notes only gives its notes to the next slide. `presentAt` does not change.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run python tools/build_ide_js.py && uv run pytest tests/test_present.py tests/test_talk_deck.py -q && uv run pytest -q -x --ignore-glob='*_slow.py' && uv run pytest tests/test_present_slow.py -q -m slow`
Expected: PASS. `test_present_slow.py` uses typed cells, so its counts stay 4 horizontal and 5 leaf slides.

**Risks:** an owner's untyped notebook with H2 headings now shows fewer, longer slides in the overlay. That is decision 2. `presentFit` (`present.js:28-40`) zooms or scrolls a long slide.

---

### Task 3: The audience deck, the output cleaner and the message clip

Goal: the audience gets only an allow-listed copy of the talk, with cleaned markup and no demo answer, and a cell output becomes `out` HTML with text and images only, clipped to the stage message limit.

**Files:**
- Modify: `leela/blocks/nb/talk.py` (`ws_resolver`, `audience_deck`, `clean_out`, `clip_msg`, `cell_html`, `room_spec`)
- Test: `tests/test_talk_audience.py`

**Interfaces:**
- `ws_resolver(roots) -> Callable[[str], Path|None]`: `ws:<rel>` to a file inside a root, with a suffix in `abhyasa.talk.IMAGE_SUFFIXES`; None for anything else (the same checks as `asset_resolver`, `talk.py:290-297`).
- `audience_deck(t, nb, resolve, tid, key, look) -> (dict, images)`: `public_deck(t, resolve)` (`talk.py:319-327`) plus `tid` and `look` (`{theme, mono}`, from the saved theme and the editor `fontFamily`), and for each slide `beats` (a count) and `blocks=[{id, frag, html}]` built from `show.cells` with `cell_html` on the text after `demo_fences`. Demo slides add `specs=[room_spec(s) for s in show.specs]`. `images` maps sha256 to `(bytes, type)` for `Show.images`. The deck's image map is sha256 to `/present/img/<sha>?k=<key>`. Never `notes`, `answer`, `src`, `step`, a path or an editor id that is not a cell id.
- `cell_html(cell, base) -> str`: markdown to HTML through `abhyasa.core.ui.md_html` and `clean_html`, on text that `demo_fences` already cleaned. Check that their allow-list keeps `pre`, `code`, tables and `img`, and drops script and event attributes, before using them; else use `mdhtml` and `nh3` with Leela's own allow-list. Code cells as `<pre><code>` text.
- `clean_out(outputs, key) -> (str, images)`: `stream`, `text/plain`, `text/markdown` (cleaned), `image/png`, `image/jpeg`, `image/gif`; `text/html` cleaned to text-level tags; errors as the traceback text with ANSI codes removed. Images go by hash as `/present/img/<sha>?k=<key>`, and `images` maps each sha256 to `(bytes, type)`. Never `<script>`, never `on*` attributes, never `javascript:` or a remote `src`.
- `clip_msg(msg, most=65536) -> dict`: the message with its `html` cut so that `len(json.dumps(msg, ensure_ascii=False, separators=(',', ':')))`, counted in UTF-16 code units as `JSON.stringify` counts, is at most `most`. It drops whole trailing blocks first, then cuts the text of the last text block and escapes it again. The result is valid markup and ends with `<p>Output is too long for the room screen.</p>` when anything was cut.
- `room_spec(spec)`: a copy of `abhyasa/blocks/talk/app.py:139-145`, with the comment `# copy: importing abhyasa.blocks.talk.app builds the talk app`, and a parity test. The test reads the source of `room_spec` from the abhyasa install path (found with `importlib.util.find_spec('abhyasa').submodule_search_locations`, without importing `abhyasa.blocks.talk`), runs it with `ast` and `exec` in a namespace that has `deepcopy`, and compares both on a case set. Drop the copy when abhyasa moves `room_spec` into `abhyasa.talk` or core.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_talk_audience.py
import json
from leela.blocks.nb.talk import audience_deck, clean_out, clip_msg, room_spec, talk_from_notebook, ws_resolver

def test_audience_deck_has_no_notes_answers_or_paths(tmp_path): ...
    # notebook: a notes cell 'SPEAKER-SECRET', a demo fence with a gate answer, an image under tmp_path
    # d, imgs = audience_deck(t, nb, ws_resolver([tmp_path]), 'tid-1', 'k' * 16, look); s = json.dumps(d)
    # assert 'SPEAKER-SECRET' not in s and '"answer"' not in s and str(tmp_path) not in s and '/Users/' not in s and d['tid'] == 'tid-1'
    # assert d['slides'][0]['blocks'][0]['html'].startswith('<') and all(v == f'/present/img/{h}?k=' + 'k' * 16 for h, v in d['images'].items())

def test_a_gate_answer_never_reaches_the_audience_before_reveal(tmp_path): ...
    # a markdown cell with prose, a rupaka fence whose gate answer is {'is': 'ANSWER-7731'}, and prose after it
    # 'ANSWER-7731' not in json.dumps(audience_deck(...)), not in any block html, not in public_deck passage

def test_clean_out_keeps_text_and_images_only():
    outs = [{'output_type': 'stream', 'name': 'stdout', 'text': 'tick 0\n'},
            {'output_type': 'display_data', 'data': {'text/html': '<b onclick="x()">ok</b><script>alert(1)</script><img src="https://evil.example/a.png">'}},
            {'output_type': 'error', 'ename': 'ZeroDivisionError', 'evalue': 'division by zero', 'traceback': ['\x1b[31mZeroDivisionError\x1b[0m']}]
    h, _ = clean_out(outs, 'k' * 16)
    assert 'tick 0' in h and '<b>ok</b>' in h and 'ZeroDivisionError' in h
    assert 'script' not in h and 'onclick' not in h and 'evil.example' not in h and '\x1b' not in h

def test_images_go_by_hash_with_the_key():
    h, imgs = clean_out([{'output_type': 'display_data', 'data': {'image/png': 'iVBORw0KGgo' + 'A' * 90_000}}], 'k' * 16)
    assert f'/present/img/{next(iter(imgs))}?k=' + 'k' * 16 in h and len(imgs) == 1

def _size(m): return len(json.dumps(m, ensure_ascii=False, separators=(',', ':')).encode('utf-16-le')) // 2

def test_clip_counts_the_whole_message(): ...
    # escape-heavy text ('"\\<\n' * 30_000), emoji text, and 2000 small image tags: each clip_msg result has _size <= 65536,
    # parses as balanced markup (html.parser with a tag stack), and ends with the 'too long' line; a small message is unchanged

def test_room_spec_matches_abhyasa(): ...
    # read abhyasa/blocks/talk/app.py from the install path, exec its room_spec with ast; compare on nested gate cases
```

Write each `...` test in full; the comment lines give its assertions.

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_talk_audience.py -q`
Expected: FAIL with `ImportError: cannot import name 'audience_deck'`.

- [ ] **Step 3: Implement** as the interfaces say. `public_deck` reads `talks.image_mb` from abhyasa's settings (`talk.py:307`); `ABHYASA_CONFIG` in `conftest.py:15` keeps the tests off the owner's file.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_talk_audience.py tests/test_talk_deck.py -q && uv run pytest -q -x --ignore-glob='*_slow.py'`
Expected: PASS.

**Risks:** server-side markdown can differ from the IDE's `renderMarkdown` (KaTeX, Leela's own fences). The audience page loads the vendored KaTeX (`leela/vendor/katex/`) for math; other Leela-only markup shows as text.

---

### Task 4: Talk routes on the server, and the stage asset route

Goal: the server builds and holds the live talk, serves the audience page, deck and images behind the run key, serves the two stage files without a key, keeps the place, and checks the key on every mutation route.

**Files:**
- Modify: `leela/blocks/nb/app.py:103-121` (`Show` gets `talk`, `run`, `key`, `tid`, `deck`, `images`, `path`, `live`, `ended`; methods `begin`, `check(k)`, `at`, `finish`), `app.py:714-743` (new routes beside the present routes)
- Create: `leela/static/present-audience.html` (no inline script; loads `/present/stage/stage.js` and `/leestatic/lee-audience.js`)
- Modify: `tests/routes.txt`
- Test: `tests/test_talk_routes.py`

**Interfaces:**
- `Show.check(k, live=True)`: 410 `This talk has ended.` when no talk is held, or (with `live`) when it is finished; 403 `This is not the key of the talk.` when `secrets.compare_digest(k, self.key)` fails. Every route with `k` calls it first.
- `POST /present/talk` JSON `{path, cells, start_cell}` (cells: `id`, `cell_type`, editor text, `outputs`, `extra.slideshow`): when a talk is held, ends its run, saves it when `saved` (Task 10), pushes `talk-ended` `{tid}` on `/present/events`, and keeps `{tid, key}` of the old run as `replaced`. Then it builds the talk with `talk_from_notebook`, runs `check_talk(t, schemes=('ws',))`, makes `new_run(t)`, moves it with `log_go` to `start_place`, fills `Show.images`, and returns `{ok, tid, key, talk, at, replaced, audience: '/present/audience?k=<key>'}`. `at` is the whole `run['at']` dict. The presenter copy holds notes and answers. 400 for a non-notebook, nothing to present, or `check_talk` problems.
- `GET /present/audience?k=` the page; `GET /present/deck?k=` the audience deck with `tid`; `GET /present/img/{h}?k=` an image from `Show.images`, with its stored media type; 404 for an unknown hash.
- `POST /present/at` `{k, slide, beat, blank}`: `log_go`; 400 for an unknown slide or a beat outside `0..max(1, len(beats))`.
- `POST /present/finish` `{k}`: `end_run`; returns `{recap}` (Task 10 adds the save and the recap routes).
- `GET /present/state` keeps its shape and adds `talk: {tid, path, at}` when a talk is live (no key, no notes).
- `GET /present/stage/{name}`: only `stage.js` and `stage.css`, read with `importlib.resources.files('abhyasa.core')`, `Cache-Control: no-cache`, 404 for any other name. No key: the files are public library code.
- Headers on the audience page and the deck: `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`. `LoopbackHostGuard` does not change. A typed URL sends `Sec-Fetch-Site: none`.
- Mutation routes, the list every security test walks: `/present/at`, `/present/finish` (this task), `/present/out` (Task 9), `/present/ask`, `/present/hands`, `/present/question` (Task 10), `/present/run-output` (Task 12). The read routes with a key are `/present/deck`, `/present/img/{h}`, `/present/resume` (Task 8), `/present/recap`, `/present/recap.html` (Task 10). Keep the list as `MUTATIONS` in `tests/test_talk_routes.py` and extend it in each task.

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
AT = lambda s, b=1: dict(slide=s, beat=b, blank=False, pane=None, ask=None)
MUTATIONS = [('/present/at', dict(slide='s1', beat=1, blank=False)), ('/present/finish', {})]

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
    assert r['ok'] and r['at'] == AT('s2') and r['talk']['slides'][0]['notes'] == 'SECRET-NOTE' and r['replaced'] is None
    d = c.get(f"/present/deck?k={r['key']}").json()
    assert 'SECRET-NOTE' not in str(d) and [s['id'] for s in d['slides']] == ['s1', 's2'] and d['tid'] == r['tid']
    assert c.post('/present/at', json=dict(k=r['key'], slide='s1', beat=1, blank=False)).status_code == 200
    assert c.post('/present/at', json=dict(k=r['key'], slide='s9', beat=1, blank=False)).status_code == 400
    assert c.post('/present/at', json=dict(k=r['key'], slide='s1', beat=7, blank=False)).status_code == 400
    assert c.get('/present/state').json()['talk']['at'] == AT('s1')

def test_every_mutation_route_refuses_cross_site_and_wrong_keys(rig):
    c, root = rig
    old = start(c, root).json()['key']
    k = start(c, root).json()['key']                                  # a second start: the old key is stale
    for path, body in MUTATIONS:
        assert c.post(path, json=dict(body, k=k), headers={'sec-fetch-site': 'cross-site'}).status_code == 421, path
        assert c.post(path, json=dict(body, k='0' * 16)).status_code == 403, path
        assert c.post(path, json=dict(body, k=old)).status_code == 403, path
    for p in (f'/present/audience?k={k}', f'/present/deck?k={k}'):
        assert c.get(p, headers={'sec-fetch-site': 'cross-site'}).status_code == 421
    c.post('/present/finish', json=dict(k=k))
    assert c.get(f'/present/deck?k={k}').status_code == 410
    for path, body in MUTATIONS: assert c.post(path, json=dict(body, k=k)).status_code == 410, path

def test_a_second_start_ends_the_first(rig):
    c, root = rig
    a, b = start(c, root).json(), start(c, root).json()
    assert b['replaced'] == {'tid': a['tid'], 'key': a['key']} and c.get(f"/present/deck?k={a['key']}").status_code == 403
    # a /present/events reader started before the second start gets 'talk-ended' with a's tid

def test_audience_page_headers(rig):
    c, root = rig
    r = c.get('/present/audience?k=' + start(c, root).json()['key'])
    csp = r.headers['content-security-policy']
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and r.headers['referrer-policy'] == 'no-referrer'
    assert '<script>' not in r.text and 'lee-audience.js' in r.text

def test_stage_files_come_from_abhyasa_without_a_key(rig):
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

- [ ] **Step 3: Implement.** Keep `Show.update` for the notes page as it is (`test_present.py:118-142` pins it). Build the `Notebook` from the posted cells with the editor text, so unsaved edits show. Run the build with `off_loop`. Add the new routes to `tests/routes.txt`.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_talk_routes.py tests/test_present.py -q && uv run pytest -q -x --ignore-glob='*_slow.py'`
Expected: PASS.

**Risks:** `Show` is per `ide_app` (`app.py:714`), so two IDE pages of one workspace share one live talk; a second start ends the first and tells the first page.

---

### Task 5: The audience window

Goal: the audience page draws the slide, its beats, live output and the mirrored demo from the deck and the channel, in Leela's theme and fonts.

**Files:**
- Create: `leela/blocks/nb/audience.js` (`ALONE` entry `'lee-audience.js'` in `tools/build_ide_js.py:55`)
- Create: `leela/static/audience.css` (served by `/leestatic`, copied by `packaging/macos/setup.py:21`)
- Create: `leela/static/lee-tokens.css` (the theme and font token blocks moved out of `lee-ide.css:15-230`)
- Modify: `leela/static/lee-ide.css` (the token blocks leave), `leela/app.py` (the IDE head links `lee-tokens.css` before `lee-ide.css`)
- Modify: `tools/build_ide_js.py:77-81` (`orphans()` counts the `ALONE` modules as named)
- Modify: `leela/static/present-audience.html` (from Task 4), `tests/test_present.py:149-163` (packaging lists `lee-audience.js`, `audience.css`, `lee-tokens.css`, `present-audience.html`)
- Test: `tests/test_talk_audience_js.py` (node), `tests/test_talk_slow.py` (browser)

**Interfaces:**
- `talkTypes(S)`: calls `S.add('out', ...)` with the fields of the `out` decision, once per page; a second call is a no-op for the page (it checks a flag), and `S.add` itself throws on a repeat. The presenter view loads `lee-audience.js` too and calls the same function. Leela writes its own field rule functions; it uses `abhyasaStage` helpers only when `stage.js` exports them.
- On load (only when `document.body.dataset.page === 'audience'`): read `k`, `fetch('/present/deck?k=')`, call `talkTypes(abhyasaStage)`, open `ch = abhyasaStage.channel(deck.tid + ':' + k)`, call `abhyasaStage.audience(el, {ch, draw, title})`, then `off = ch.on('out', draw)`, because `out` is not in `DRAWN`. abhyasa's types, `output` included, reach `draw` through `audience`. On `end` the page calls `off()` and `stop()`.
- `draw(msg)`: `go` shows slide `slide` with blocks whose group is below `beat` (beat 1 the body, beat k+1 adds group k, beat 0 the title only); `ask` shows the question card (`textContent`); `result` shows the hands line; `demo` and `answers` go to `mirror(host).apply` and `reveal`; `end` shows "Thank you" and the title; `out` replaces the output box of `cell` after `safeHtml`, only when `(gen, seq)` is newer than the last one for that cell. Task 12 adds `output` (the run's text in a `pre`, by `textContent`) and the `run` kind of `ask` and `result`.
- `safeHtml(html, key, parser) -> DocumentFragment`: keep only `p, pre, code, span, div, b, i, em, strong, br, table, thead, tbody, tr, th, td, ul, ol, li, img`, keep only `class`, and `src` on `img` when it matches `^data:image/(png|jpeg|gif|webp);base64,` or exactly `/present/img/<64 hex>?k=<key>`.
- Theme: `<html class="talk" data-theme data-mode>` from `deck.look.theme`. `system` resolves through `matchMedia('(prefers-color-scheme: dark)')` and a `change` listener, as `prefs.js:52,79` does. A `storage` event on `lee-theme` repaints. `--lee-mono` comes from `deck.look.mono`. The page links `lee-tokens.css` and `audience.css`, not `lee-ide.css`. `audience.css` maps stage tokens to Leela tokens: `--bg: var(--lee-bg); --fg: var(--lee-fg); --ink2: var(--lee-fg2); --mute: var(--lee-fg4); --line: var(--lee-border); --rule: var(--lee-border); --acc: var(--lee-accent); --serif: var(--lee-sans); --head: var(--lee-sans); --mono: var(--lee-mono)`, and `--ok`, `--no` from Leela's success and error tokens.
- F fills the screen. Any other key shows "Keys work in the presenter window" for 3 s (spec 9.1). The page sends only `hello` and `here` (from `abhyasaStage.audience`).

- [ ] **Step 1: Write the failing tests**
  - Node: `test_audience_walker_drops_what_the_server_missed`: `safeHtml` on `<img src=x onerror=alert(1)>`, `<a href="javascript:x">`, `<svg><script>`, `<img src="https://evil.example/a">`, `/present/img/<hash>?k=<other key>`, and a good `data:image/png` image keeps the good image and text only. `safeHtml` takes the parser as an argument; if node has no `DOMParser`, the slow test runs the same cases in the browser.
  - Node: `test_out_type_is_added_once`: after `talkTypes(S)`, `valid` accepts `{v:1, t:'out', cell:'c2', gen:1, seq:1, html:'<pre>1</pre>'}`; it refuses an `out` whose JSON is over 65536, an extra field, and a missing `gen` or `seq`. A second `talkTypes(S)` does not throw. `ch.on('out', ...)` in the audience page receives an `out` sent from another page.
  - Node: `test_build_counts_alone_modules`: `orphans()` is empty with `audience.js` in `ALONE` only.
  - Slow, `test_the_audience_window_follows_go_and_blank`: start a talk through `POST /present/talk`, open the audience page in a second page of the same context, send `go` s1 beat 1, `go` s1 beat 2 (the fragment shows), `blank` on (the title shows), and `out` for `c2`, from a third page that opens the same channel and calls `talkTypes`. Assert the computed background equals `--lee-bg` of the theme.
  - Slow, `test_audience_images_load`: a deck figure and an `out` image by hash both load (`img.naturalWidth > 0`); the same URL with a wrong key fails to load.
  - Slow, `test_audience_theme_follows_system_and_code_font`: theme `cursor:system:tight` with `page.emulate_media(color_scheme='dark')` then `'light'` changes `data-mode`; a custom `fontFamily` reaches `--lee-mono`; the IDE page's computed `--lee-bg` is the same as before the token move.

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_talk_audience_js.py -q && uv run pytest tests/test_talk_slow.py -q -m slow -k audience`
Expected: FAIL with 404 for `/leestatic/lee-audience.js`.

- [ ] **Step 3: Implement.** Load rupaka from the vendored bundle the IDE already serves. Load KaTeX from `/leestatic` only when a block has math.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run python tools/build_ide_js.py && uv run pytest tests/test_talk_audience_js.py tests/test_talk_routes.py tests/test_present.py -q && uv run pytest -q -x --ignore-glob='*_slow.py' && uv run pytest tests/test_talk_slow.py tests/test_web_slow.py -q -m slow -k "audience or theme"`
Expected: PASS.

**Risks:** `stage.css` expects abhyasa's token names; a missing token falls back to the browser default. Moving the token blocks changes the IDE's stylesheet order; the slow theme test is the check.

---

### Task 6: The presenter view and opening the audience window

Goal: from the overlay, the presenter turns on two-window mode, which opens the audience window on a click and shows the slide, notes, next slide, clock and question card in the IDE page.

**Files:**
- Modify: `leela/blocks/nb/present.js:165-287` (`presentTalk`, `p.mode`, the bar button "audience", the presenter layout, `closePresentation`)
- Modify: `leela/static/js/actions.js:65-66` (add `present_talk`), `leela/core/keys.py:193` region (`Key('present_talk', '', 'editor', 'present with an audience window')`), `leela/blocks/keys/menus.py:39,46,100` (one row each), `leela/static/lee-ide.css` (`.lee-present.two` rules)
- Modify: `leela/desktop.py:29-38` (patch `ShellApi.open_window(url, title, run)`)
- Test: `tests/test_present.py`, `tests/test_talk_slow.py`

**Interfaces:**
- `presentTalk(start)`: posts `/present/talk`, sends `end` on the channel in `replaced` when it is set, sets `p.mode = 'two'`, adds `talk` to `html`, loads `/present/stage/stage.js` and `/leestatic/lee-audience.js`, calls `talkTypes(abhyasaStage)`, opens `ch = abhyasaStage.channel(tid + ':' + key)`, and draws the presenter layout: the slide (Leela's own `presentCell` per block, so ▶ still runs the real cell), the rail of slides, the notes (rendered with `allow_raw:false`), the next slide's title, the clock (time used, and the slot from a number field stored per notebook in `localStorage`), and the question card. It does not open `/present/notes`. Task 7 installs the stage keys.
- From the overlay: the overlay's Reveal instance stops taking keys before the presenter view starts. `presentTalk` calls `p.reveal.destroy()` (`present.js:250-253`), or `p.reveal.configure({keyboard: false})` when the vendored reveal has no `destroy`, and removes the reveal theme link (`present.js:247`).
- The presenter listens on the channel for `hello` and `here` only. It never registers a handler for `go`, `end`, `pane` or any other type, so an audience page cannot move the talk.
- The bar gets a button "audience" in the one-screen overlay; it calls `presentTalk` at the current slide. `present_talk` from the palette, cell menu, tab menu and View menu does the same at the selected cell. ⌥R does not change (decision 1).
- Opening: the presenter view shows the button "Open the audience window". Its click handler calls `window.open('/present/audience?k=' + key, 'leela-audience-' + tid, 'popup,width=1280,height=720')` at once, with no `await` before it, so the browser treats it as a user action. The first click starts the talk; this second click is the normal open. With `inDesktopShell()`: `window.pywebview.api.open_window(url, 'Audience', run_id)`. When the browser returns null, the button stays and the status line says "The browser blocked the window. Click again." In the shell, when the spike fails, the view shows "Present in your browser" with `location.origin` and a copy button (spec 9.4).
- `ShellApi.open_window(url, title, run)`: calls `kavacha.window.open_window(url, title, key='leela-audience:' + run)`, so each run has its own window and a new run never gets an old window on an old URL. It returns `{'ok': True}`, or `{'ok': False, 'error': str}`, never the native `Window`.
- Liveness: `hello` gets the place; with no `here` for 5 s the view shows "The audience window is closed. Open it again."
- `talk-ended` on `/present/events` for this `tid`: the view sends `end` on its own channel, shows `Another talk started.` and leaves two-window mode.
- `closePresentation` in two-window mode sends `end` only through "End the talk" (Task 10); × asks "End the talk?" first.

- [ ] **Step 1: Spike (manual, on the Mac app, before code).** Two pywebview windows opened with `kavacha.window.open_window` on one origin: does a `BroadcastChannel` message from one reach the other? Write the answer in the task's commit body. Two WKWebViews share a channel only when they share a website data store; this is not verified. With no shared channel, build "Present in your browser" only and skip the bridge.
- [ ] **Step 2: Write the failing tests**
  - Fast: `test_present_talk_is_one_action_everywhere` (as `test_present.py:99-116`): `lookup('present_talk')`, the tab, cell and View menu rows, `present_talk:` in `actions.js`, and `_dupes(DEFAULTS) == []`.
  - Fast: `test_the_shell_bridge_returns_json`: after `import leela.desktop`, `ShellApi.open_window` exists; with `kavacha.window.open_window` patched to record its call and return an object, the result is `{'ok': True}`, `json.dumps` accepts it, and the key holds the run id; two run ids give two keys.
  - Slow, `test_two_windows_follow_each_other`: open a notebook, run `present_talk`, click "Open the audience window", catch the popup with `context.wait_for_event('page')`, press D in the presenter view, and wait until the audience shows the next beat; close the audience page and wait for the "closed" line; with `window.open` made to return null (`page.add_init_script`), the button stays and the status line shows.
  - Slow, `test_presenter_ignores_presenter_messages_from_the_channel`: from a third page on the channel, send `go` s1 beat 1, `end` and `pane`; the presenter's place and mode do not change and `/present/state` still has the talk.
  - Slow, `test_reveal_keys_stop_in_the_presenter_view`: open the overlay, switch to two-window mode, press → and Space; only one beat moves per key, and `.reveal` gets no `navigate-right`.
  - Slow, `test_a_second_client_ends_the_first_talk`: two IDE pages; page 1 starts a talk with its audience open; page 2 starts another; page 1 shows `Another talk started.` and its audience shows "Thank you".
- [ ] **Step 3: Run the tests to see them fail**

Run: `uv run pytest tests/test_present.py -q -k "present_talk or shell_bridge" && uv run pytest tests/test_talk_slow.py -q -m slow -k "two_windows or ignores or reveal_keys or second_client"`
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
- `keys`: `KeyD`, `Space`, `PageDown`, `ArrowRight`, `ArrowDown` next; `KeyA`, `Shift+Space`, `PageUp`, `ArrowLeft`, `ArrowUp` back; `KeyQ`, `KeyR`, `KeyX`, `KeyB`, `KeyE`, `KeyG` and `1`-`6` as the table says.
- `Escape` closes one thing, in this order: a `.lee-modal` confirm dialog (its own handler wins; the talk key returns false), fullscreen (the browser takes it; the rule at `present.js:238` that ignores Esc within 400 ms of leaving fullscreen stays), the demo focus, the open question, the laser, the "After the talk" panel. With nothing open it returns true, so the key stops there. Esc in the question field blurs the field and closes nothing else (`stage.js:169` passes text boxes on; Leela's field handler does it).
- `p.onKey` (`present.js:237-240`) returns at once when `p.mode === 'two'`.
- ⌥S: a capture listener active only in two-window mode.
- Next and back post `/present/at` and send `go`. Back onto a slide goes to its last beat (spec 7.4).

- [ ] **Step 1: Write the failing tests**
  - Fast: `test_talk_keys_are_listed_and_left_hand`: the "Talk" rows in `KEYS` equal `TALK_KEYS` without the ⌥B, ⌥Z rows; every plain letter is in `present.js`'s `keys` object (read as text, as `test_keys.py` does for the Graph).
  - Fast (node): `test_next_and_back_walk_beats_in_one_line`: a pure `step(deck, at, d)` in `present.js` gives `s1:1 -> s1:2 -> s2:1` forward and `s2:1 -> s1:2` back.
  - Slow, `test_esc_never_ends_a_two_window_talk`: in two-window mode, press Esc in each case: in the question field (the field blurs, the question stays open), with a question open (it closes), in a demo after E (focus leaves the demo), with the "End the talk?" dialog open (the dialog closes, the talk goes on), in fullscreen (fullscreen ends, the talk goes on), with the "After the talk" panel open (the panel closes). After each, `/present/state` still has `talk` (except after the panel, where the talk was ended on purpose). Then ⌥R, ⌥W, ⌥T, `/`: the view is still there and no new tab or palette opened. In the one-screen overlay Esc still closes (the existing test stays green).
- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_present.py -q -k "talk_keys or beats_in_one_line" && uv run pytest tests/test_talk_slow.py -q -m slow -k esc`
Expected: FAIL.

- [ ] **Step 3: Implement.** Audit first: `keys.py`, `keymap.js`, the palette and `menus.py`, as `AGENTS.md` asks; write the audit result in the commit body.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run python tools/build_ide_js.py && uv run pytest tests/test_present.py tests/test_keys.py -q && uv run pytest -q -x --ignore-glob='*_slow.py' && uv run pytest tests/test_present_slow.py tests/test_talk_slow.py -q -m slow`
Expected: PASS.

**Risks:** a clicker that sends `B` or `.` for blank works as reveal's in the overlay and as abhyasa's in the talk. `Space` on a focused bar button: `stage.js:173` calls `preventDefault`, and the bar already returns focus to the root (`present.js:224`).

---

### Task 8: Reload keeps the place and the live state

Goal: a reload of the IDE page or of the audience window comes back at the same slide and beat, with the same output, question, result and demo.

**Files:**
- Modify: `leela/blocks/nb/app.py` (`POST /present/resume`; `Show.live`), `leela/blocks/nb/present.js` (resume on tab load; `localStorage['lee-talk:<path>'] = {tid, key}`; replay on `hello`), `tests/routes.txt`
- Test: `tests/test_talk_routes.py`, `tests/test_talk_slow.py`

**Interfaces:**
- `Show.live`: `{outs: {cell: {gen, seq, html}}, ask: <the open ask message> or None, result: <the last result message> or None, output: <the last output message> or None, demo: {slug: snapshot}, answers: [<answers messages>], blank: bool}`. `Show` owns it. `POST /present/out` writes `outs` (Task 9); `POST /present/ask` and R write `ask` and `result` (Task 10); a `POST /present/demo` `{k, slug, state}` writes `demo` (Task 9). A new slide clears `ask`, `result`, `output` and `answers`. `begin` clears all of it.
- `POST /present/resume` `{tid, k}`: `Show.check(k)`, then 410 when `tid` is not the held talk's. Returns `{ok, tid, key, talk, at, live}`, the presenter copy, and never calls `new_run`.
- On a notebook tab load, when `localStorage` holds an entry for this path: `POST /present/resume`. On 200, `presentTalk` comes back at `at` with the same key and `live`, so the open audience window keeps working. On 403 or 410, the page removes the entry. When `/present/state` has no live talk at all, the overlay offers "Go on from slide N"; a new run starts there with a new key. When another talk is live, the page offers nothing and touches nothing.
- The audience window: `hello` on load; the presenter replays `go` at `at`, `blank`, the open `ask`, `result`, `output`, one `out` per entry of `outs`, each `demo` snapshot, and the `answers` messages (spec 9.2, `hello` row).

- [ ] **Step 1: Write the failing tests**
  - Fast: `test_resume_returns_the_run_without_a_new_one`: start, move to s2, resume with the right tid and key: same `run['id']`, same key, `at == AT('s2')`; resume with a wrong key 403, with another tid 410; after a second start, resume with the first entry 403.
  - Slow, `test_reload_keeps_slide_and_beat`: go to s2 beat 2, reload the audience page, wait for s2 beat 2; reload the IDE page, wait for the presenter view at s2 beat 2, press D, and see the audience follow without opening it again.
  - Slow, `test_reload_mid_run`: run the `tick` cell of `test_present_slow.py:23`; reload the audience page during the run and see the latest output; reload the IDE page after the run and see the same output in both windows.
  - Slow, `test_reload_after_reveal`: open a gate question, set hands, press R; reload both pages; the result and the answers show again, and the question card is not open again as unanswered.
  - Slow, `test_stale_entry_while_another_talk_is_live`: write an old `{tid, key}` into `localStorage` for notebook A, start a talk from notebook B in another page, open A: no presenter view, the entry is gone, and B's talk is still live at its place.
- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_talk_routes.py -q -k resume && uv run pytest tests/test_talk_slow.py -q -m slow -k "reload or stale_entry"`
Expected: FAIL (404 on `/present/resume`; the overlay does not come back after a reload).

- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run python tools/build_ide_js.py && uv run pytest tests/test_talk_routes.py -q && uv run pytest -q -x --ignore-glob='*_slow.py' && uv run pytest tests/test_talk_slow.py -q -m slow`
Expected: PASS.

**Risks:** the key in `localStorage` is readable by any script on the origin. Same-origin script can already read the deck, so the key adds no reach on this machine.

---

### Task 9: Live output, demos, Stop and kernel restart

Goal: a cell run in the presenter view shows its cleaned output on the audience screen in order, a rupaka demo cell is mirrored there, Stop interrupts the kernel, and a kernel restart leaves no stale output.

**Files:**
- Modify: `leela/blocks/nb/present.js:137-148` (`presentRun`) and `:241-243` (`onOutput`): in two-window mode, count a generation per cell run and a sequence per output event, post `/present/out`, and send the returned `out` message
- Modify: `leela/blocks/nb/present.js` (demo cells: `abhyasaStage.mirror(host)` on the cell's rupaka mount, `watch` posts `/present/demo` and sends `demo`; the gate's `rk-predict` gets `preventDefault()` and `detail.settle(true)`, so nothing is logged, spec 10 lines 381-383; the Stop button; the restart handler)
- Modify: `leela/blocks/editor/mount.js:493` (`markPreviousRuns` dispatches `lee-kernel-restart`), `leela/blocks/runtime/kernel.js:35` (the inspector's "Restart kernel" button calls `markPreviousRuns`)
- Modify: `leela/blocks/nb/app.py` (`POST /present/out` `{k, cell, gen, seq, outputs}`, `POST /present/demo` `{k, slug, state}`), `leela/blocks/nb/audience.js` (`out`, `demo`, `answers`), `tests/routes.txt`
- Test: `tests/test_talk_routes.py`, `tests/test_talk_slow.py`, `tests/test_present.py`

**Interfaces:**
- `POST /present/out`: `Show.check(k)`; 400 when `cell` is not a cell of a visible slide of the held talk (a `skip` cell, a `notes` cell, an unknown id); `{stale: true}` when `(gen, seq)` is not newer than `live.outs[cell]`; else `clean_out`, `Show.images.update`, `clip_msg`, store in `live.outs`, and return `{msg}`.
- The presenter sends `out` only for a reply whose `tid` and key are the current ones and whose `(gen, seq)` is the newest it has for the cell. It sends at most one `out` per animation frame per cell; the last output wins.
- Stop: a button in the presenter view's bar, shown while a cell runs. It posts `/kernel/interrupt`, as the `interrupt` action does (`actions.js:37-38`).
- Kernel restart: on `lee-kernel-restart` in two-window mode, the presenter clears each output box, sends an empty `out` for each cell in `live.outs` with a new `gen`, cancels a pending run reveal (Task 12), and enables the run button.
- A `demo` message over the limit is not sent and not stored. The status line says `The demo is too large for the room screen.`

- [ ] **Step 1: Write the failing tests**
  - Fast: `test_out_only_for_visible_cells_in_order`: posting for `m1` (notes) and an unknown id gives 400; `gen=1, seq=2` then `gen=1, seq=1` gives `{stale: true}`; `gen=2, seq=1` is stored; a stale key 403. Add `/present/out` and `/present/demo` to `MUTATIONS`.
  - Fast: `test_outputs_from_a_run_load_by_hash`: an `image/png` output posted to `/present/out` is then served at `/present/img/<sha>?k=`.
  - Fast (node): `test_stage_messages_never_carry_an_answer`: the pure message builders in `present.js` (`askMsg`, `outMsg`, `demoMsg`) on a slide whose ask has `answer` and whose demo gate answer is `ANSWER-7731` give messages with no `answer` key and no `ANSWER-7731`, and `abhyasaStage.valid` passes each one after `talkTypes`.
  - Slow, `test_a_run_streams_to_the_audience`: the `tick` cell run from the presenter view shows `tick 2` on the audience page; `1/0` shows `ZeroDivisionError`; a cell that prints `<script>window.hit=1</script>` as `text/html` leaves `window.hit` undefined in the audience page; a cell that displays 200 small images and one that prints 300 kB of `"<\\` text both show with the "too long" line and no channel error.
  - Slow, `test_overlapping_runs_and_switching_talks`: run a slow cell, run it again before the first finishes; the audience shows only the second run's output. Start a run, start another talk before it finishes; no output of the old run reaches the new audience.
  - Slow, `test_stop_and_restart`: run `while True: pass`, press Stop, see `KeyboardInterrupt`; run a cell, restart the kernel from the Kernel menu; both screens clear the output and the run button is enabled.
  - Slow, `test_a_demo_is_mirrored`: a rupaka fence slide; moving the presenter's slider changes the audience copy's state; the audience gate is `inert`; `lr.attempts()` is unchanged after a gate pick; a demo whose snapshot is over 65536 shows the status line and the audience keeps the last state.
- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_talk_routes.py tests/test_present.py -q -k "out_ or answer or by_hash" && uv run pytest tests/test_talk_slow.py -q -m slow -k "streams or overlapping or stop or mirrored"`
Expected: FAIL.

- [ ] **Step 3: Implement** as the interfaces say.
- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run python tools/build_ide_js.py && uv run pytest tests/test_present.py tests/test_talk_audience.py tests/test_talk_routes.py -q && uv run pytest -q -x --ignore-glob='*_slow.py' && uv run pytest tests/test_talk_slow.py tests/test_rupaka_slow.py -q -m slow`
Expected: PASS.

**Risks:** running a cell writes its outputs into the notebook (`present.js:142,146`), as today (report 3, row 7).

---

### Task 10: Room features, the saved talk and the recap

Goal: questions with hands, room questions and the run log save the talk and the run only when used, and "After the talk" shows the recap and saves the recap file, also after the talk has ended.

**Files:**
- Modify: `leela/blocks/nb/talk.py` (`save_talk`, `save_run`, behind the store chosen in open question 1)
- Modify: `leela/blocks/nb/app.py` (`POST /present/ask` `{k, slide, open}`, `POST /present/hands` `{k, slide, main}`, `POST /present/question` `{k, text}` and `{k, id, note}`, `GET /present/recap?k=`, `GET /present/recap.html?k=`; `POST /present/finish` saves), `tests/routes.txt`
- Modify: `leela/blocks/nb/present.js` (question card, 1-6, the "Add a question from the room" field, "End the talk", the "After the talk" panel)
- Test: `tests/test_talk_room.py`, `tests/test_talk_slow.py`

**Interfaces:**
- The first room action (`ask`, `hands`, `question`) saves the talk once and marks the run `saved`; each later change saves the run. Navigation alone saves nothing.
- `hands` calls `log_main(run, slide, kind, main)`; `ask` sends `ask` with `public_ask` and stores it in `live.ask`; R sends `result` with `right` from the presenter copy and stores it in `live.result`.
- `POST /present/question` with `text` calls `log_question`. With `id` and `note` it sets the note of that question in `run['questions']` in place, because `log_question` always appends (`talk.py:373-377`); 404 for an unknown id. It saves the run.
- `Show.finish(k)`: `end_run`, save when `saved`, set `ended`, keep the talk, the run, the key and `Show.images`. After it, the mutation routes and `/present/deck` give 410; `/present/recap` and `/present/recap.html` give 200 with the old key until the next `begin`. A second start also flushes a `saved` run before it drops it (Task 4).
- `GET /present/recap?k=`: `recap(t, run)`. "After the talk" lists `unsure`, the slides with time, and the room questions with a note field. "Save the recap as one file" downloads `GET /present/recap.html?k=`, which is `recap_html(t, run, ws_resolver(roots))` as `<stem>-recap.html`, with `Content-Disposition: attachment`. abhyasa's "Make a follow-up walk" is not in Leela.
- Neither path calls `Learning.record` (spec 17.3).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_talk_room.py (uses the rig, CELLS, AT and MUTATIONS of tests/test_talk_routes.py, with a demo slide that has a gate)
def test_a_plain_show_saves_nothing(rig): ...
    # start, move through every slide, finish: no '*.talk.json' under root, no run in the store, recap['slides'] lists the slides
def test_hands_save_the_talk_and_the_run_once(rig): ...
    # start, ask on the demo slide, hands main=1, question 'Why?', finish: one talk saved, its run has asks[s].main == 1 and questions[0].text == 'Why?'
    # Learning(...).attempts() is unchanged
def test_a_note_edit_does_not_add_a_question(rig): ...
    # question 'Why?', then {id: 'q1', note: 'later'} twice: one question, note 'later'; id 'q9' gives 404
def test_recap_after_finish_for_saved_and_unsaved_talks(rig): ...
    # unsaved: finish, then /present/recap and /present/recap.html 200; /present/at and /present/hands 410
    # saved: the same, and the saved run has 'ended' set; after a new start, the old key gives 403 on the recap routes
def test_recap_file_has_no_notes_and_no_script(rig): ...
    # GET /present/recap.html?k=: 200, attachment, 'SECRET-NOTE' not in text, '<script' not in text, the right answer is marked
```

Write each test in full; the comment lines give the assertions. Add the new mutation routes to `MUTATIONS`.

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_talk_room.py -q`
Expected: FAIL with 404 on `/present/ask`.

- [ ] **Step 3: Implement.** With the shared store, `put_talk` runs `check_talk(t)` with no `schemes` (`abhyasa/talk.py:243`) and refuses `ws:` figures: that path needs an abhyasa change first (open question 1).
- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_talk_room.py tests/test_talk_routes.py -q && uv run pytest -q -x --ignore-glob='*_slow.py' && uv run pytest tests/test_talk_slow.py -q -m slow`
Expected: PASS.

**Risks:** a save that fails (read-only folder, locked vault) does not stop the talk: the status line says why and the run stays in memory until "End the talk". `recap_html` shows passages only for slides whose beats include `passage` (`talk.py:313-316`); beat 1 is `passage` for that reason.

---

### Task 11: Themes for both modes

Goal: the overlay uses `rise.theme` when a notebook sets it, else the reveal theme closest to the current Leela theme with `system` resolved; the two-window talk uses Leela's theme and fonts and no reveal theme.

**Files:**
- Modify: `leela/blocks/nb/present.js:75-88` (`riseConfig` gives `theme: null` when `rise.theme` is not a reveal theme; `revealThemeFor(theme)` picks one), `:246-247` (the theme link)
- Test: `tests/test_present.py:63-75`, `tests/test_talk_slow.py`

**Interfaces:**
- `revealThemeFor({family, mode})`: resolves `mode === 'system'` with `themeMode` (`prefs.js:52`) first. Then `solarized` light to `solarized`; `dracula` dark to `dracula`; `gruvbox` and `ember` light to `beige`; any other dark to `black`; any other light to `white`.
- The overlay follows a system change while it is open: the `prefs.js:79` listener repaints the page, and the overlay swaps its theme link when `rise.theme` is not set.
- The two-window talk never loads a reveal theme; Task 6 removes the link on conversion.

- [ ] **Step 1: Write the failing tests.** Change `test_rise_settings_reach_reveal_by_name_and_nothing_else_does`: an empty or bad `rise` gives `theme: null`; add `revealThemeFor` cases for each family in `prefs.js:4-16` in `dark`, `light` and `system` (with a stub `darkQuery`). Slow, `test_two_window_talk_ignores_rise_theme`: a notebook with `rise.theme = 'sky'`, a custom code font and theme mode `system`; after conversion no `reveal/theme/` link is in the page, the presenter and audience backgrounds equal `--lee-bg`, and `emulate_media(color_scheme=...)` flips both windows.
- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_present.py -q -k rise_settings && uv run pytest tests/test_talk_slow.py -q -m slow -k rise_theme`
Expected: FAIL (`simple` where `null` is expected).

- [ ] **Step 3: Implement.** `presentNotebook` uses `cfg.theme || revealThemeFor(lee.theme)`.
- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run python tools/build_ide_js.py && uv run pytest tests/test_present.py -q && uv run pytest -q -x --ignore-glob='*_slow.py' && uv run pytest tests/test_present_slow.py tests/test_talk_slow.py -q -m slow`
Expected: PASS.

**Risks:** a notebook with no `rise.theme` changes look from `simple` to `white` or `black`. That is decision 6. The slow half of this task needs Task 6; run it after Task 6 when Task 11 merges first.

---

### Task 12: "What does this print?" (waits on abhyasa's run-ask commit on `main`)

Goal: on a code slide the presenter asks the room what the cell prints, takes hands, runs the cell, and the plain-text output is the answer.

**Needs abhyasa:** the `main` commit that has `e68823c` and the stage change in the settled contracts: kind `run` in the `ask` and `result` rules, the shared v1 type `output` `{slide, text}` in `DRAWN`, and the `run` row in `TALK_CASES`. Both are on branch `answer-fixes` first. Pin the first abhyasa version that has them in this task. Leela adds no stage type for a run question.

**Files:**
- Modify: `leela/blocks/nb/talk.py` (`ask_for_cell(cell, options=None)`, `out_text(outputs)`), `leela/blocks/nb/app.py` (`POST /present/run-output` `{k, slide, text}`), `leela/blocks/nb/present.js` (Q on a code slide with no ask opens a run question; R runs the cell, then reveals), `leela/blocks/nb/audience.js` (draws the `run` kind of `ask` and `result`, and `output`), `pyproject.toml` (abhyasa floor), `tests/routes.txt`
- Modify: `leela/blocks/agent/ai.py:922-1003` (optional: a session tool `draft_run_options(path, cell_id)` that returns 3 wrong outputs as a draft)
- Test: `tests/test_talk_run.py`, `tests/test_abhyasa_contract.py`, `tests/test_talk_slow.py`

**Interfaces:**
- `ask_for_cell(cell, options=None) -> dict`: `{kind: 'run', q: 'What does this print?'}`, plus `options` when given (2 to 6 strings).
- `out_text(outputs) -> str`: the `stream` text and `text/plain` data of the outputs, and the error name and value, as plain text. No HTML and no images.
- Q: `POST /present/ask` stores the run question; the presenter sends `{t: 'ask', slide, ask: public_ask(ask)}` with kind `run`. Hands use `log_main(run, slide, 'run', main)` when the question has options.
- R: the presenter runs the cell; when it finishes, it posts `/present/run-output` with `out_text`. The route calls `log_output(run, slide, text)` and returns `{text: run['asks'][slide]['output']}`. The presenter sends `{t: 'output', slide, text}`, clipped so the serialised message is at most 65536, and then `result` with kind `run` and the output or the matching option, with the field names that abhyasa's `result` rule gives at that commit. It stores both in `live.output` and `live.result`. Run answers never go in `out` and never carry HTML. A kernel restart or Stop before the run finishes cancels the reveal; the question stays open.
- The order is ask, hands, (talk, hands again), run. The run is the presenter's own press of R, never automatic.

- [ ] **Step 1: Write the failing tests.** In `tests/test_abhyasa_contract.py`, `test_talk_contract` already runs every `TALK_CASES` row; add an assertion that a `run` row is there (accepted with no answer, refused with an answer or with 1 option), and that `STAGE_TYPES` has `output`. Leela's own tests in `tests/test_talk_run.py`:
  - `test_run_question_options_are_optional`: `check_talk` accepts a code slide with `ask_for_cell(cell)` and with 2 and 6 options, and refuses 1 option and a non-string option.
  - `test_matching_and_non_matching_output`: options `['1', '2', '3']`, hands main 0, output `2`: `weak` lists the slide with `top_wrong == '1'`; output `no option`: the slide is not in `weak`.
  - `test_output_is_clipped_and_cleaned`: `POST /present/run-output` with `'<b>2</b>\x00\x07\n' + 'x' * 3000` returns 2000 characters with no `\x00` or `\x07`.
  - `test_recap_escapes_the_output`: `recap_html` holds `<pre>&lt;b&gt;2&lt;/b&gt;</pre>` and not `<b>2</b>`.
  - `test_run_ask_never_carries_an_answer`: the `ask` message of a run question has no `answer` and no output before R, and `valid` accepts it; an `output` message with HTML in `text` reaches the audience page as text.
  - Slow, `test_what_does_this_print`: Q on a code slide shows the question on the audience page, R runs the cell, the audience shows the output by `textContent` through `audience`'s own forwarding (no `ch.on('output')` in `audience.js`), and a restart during the run leaves the question open.
- [ ] **Steps 2 to 4:** as in the other tasks. Gate: `uv run pytest tests/test_talk_run.py tests/test_talk_room.py tests/test_abhyasa_contract.py -q && uv run pytest -q -x --ignore-glob='*_slow.py' && uv run pytest tests/test_talk_slow.py -q -m slow -k print`

**Risks:** a cell with side effects runs in front of the room. A cell that does not finish leaves the question open; Stop interrupts it (Task 9).

---

### Task 13: Speaker notes drafted by the agent

Goal: the agent writes a draft notes cell for a slide, which the presenter then edits; the agent never changes notes the presenter wrote.

The agent can already read cells (`notebook_cells`) and run them (`run_cell`, `ai.py:925`), but no tool sets a cell's slide type, so it cannot make a notes cell today.

**Files:**
- Modify: `leela/blocks/agent/ai.py:922-1003` (`draft_notes` in `_session_tools`, added to the list at `:1003`)
- Modify: `leela/blocks/nb/talk.py` (`NOTES_PROMPT = register('leela.notes', 'Speaker notes', 'What the agent writes as a draft speaker note for a slide.', dflt)` with `abhyasa.prompts.register`)
- Modify: `leela/static/js/actions.js`, `leela/core/keys.py` (`Key('draft_notes', '', 'editor', 'draft speaker notes for this slide')`), `leela/blocks/keys/menus.py:39-41` (cell menu row): the action sends the agent one message built from `prompt('leela.notes')`, the path and the cell id, through the same path as `agent_selection` (`keys.py:123`); then rebuild `leela/static/lee-core.js`
- Test: `tests/test_talk_notes.py`

**Interfaces:**
- `draft_notes(path:str, cell_id:str, text:str) -> str`: finds the slide that holds `cell_id` with `rise_slides` on the saved notebook; inserts a markdown cell after the slide's last cell with `slideshow.slide_type = 'notes'` (`Notebook.set_slide`, `nb.py:482`) and `extra['leela'] = {'draft': sha1(text)}`; saves with `nb.save(p, sandbox=host.ws.fs)` as `add_exercise` does (`ai.py:979-986`). When the slide already has a draft cell whose source still hashes to its `draft` value, it replaces that text. When the presenter changed the draft, or wrote their own notes cell, it adds nothing and returns `the slide has notes the presenter wrote; nothing changed`. It refuses a path that is not an `.ipynb`.
- The default prompt: notes are short spoken lines for the presenter, about the slide's cells only; no new facts that the slide does not show; at most 5 lines.

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

Run: `uv run python tools/build_ide_js.py && uv run pytest tests/test_talk_notes.py tests/test_present.py -q && uv run pytest -q -x --ignore-glob='*_slow.py'`
Expected: PASS.

**Risks:** the tool writes the file while the tab can hold unsaved edits; it uses the same save path as `add_exercise`, so the tab's reload behaviour is the same as for an added exercise. The draft hash is lost when another tool rewrites the cell's `extra`.

---

### Task 14: Docs

Goal: one design note says how the two modes differ and why.

**Files:**
- Create: `docs/present.md` (the two modes, the key map, the beat names, the stage types, where talks and runs are kept, the run key as a bearer capability, the CSP)
- Modify: `CHANGELOG.md`

Gate: `uv run pytest -q -x --ignore-glob='*_slow.py'`. Read `write_prose` before writing `docs/present.md`.

---

## Order and sequencing

Every task that edits a module in `LAYERS` regenerates `leela/static/lee-core.js` (or another bundle), so two such tasks never run at the same time. Those tasks are 2, 6, 7, 8, 9, 10, 11, 12 and 13.

| task | needs | files it changes |
|---|---|---|
| 0 Pins and rupaka bundle | none | `pyproject.toml`, `uv.lock`, `leela/vendor/*`, `tests/test_abhyasa_contract.py` |
| 1 `talk_from_notebook` | 0 | `nb/talk.py`, `tests/data/rise_cases.json`, `tests/test_talk_deck.py` |
| 2 H2 rule in the overlay | 1 (reads the case table) | `present.js`, `lee-core.js`, `tests/test_present.py` |
| 3 Audience deck, cleaner, clip | 1 | `nb/talk.py`, `tests/test_talk_audience.py` |
| 4 Routes and stage assets | 3 | `nb/app.py`, `static/present-audience.html`, `tests/routes.txt`, `tests/test_talk_routes.py` |
| 5 Audience window | 4 | `nb/audience.js`, `static/audience.css`, `static/lee-tokens.css`, `static/lee-ide.css`, `leela/app.py`, `static/present-audience.html`, `tools/build_ide_js.py`, `static/lee-audience.js`, `tests/test_present.py` (packaging rows), `tests/test_talk_audience_js.py`, `tests/test_talk_slow.py` |
| 11 Themes (fast half) | 0 | `present.js`, `lee-core.js`, `tests/test_present.py` |
| 13 Notes draft tool | 1 | `agent/ai.py`, `nb/talk.py` (`NOTES_PROMPT` only), `actions.js`, `keys.py`, `menus.py`, `lee-core.js`, `tests/test_talk_notes.py` |
| barrier | 5 and 13 merged | |
| 6 Presenter view, opening | barrier | `present.js`, `actions.js`, `keys.py`, `menus.py`, `lee-ide.css`, `desktop.py`, `lee-core.js`, `tests/test_present.py`, `tests/test_talk_slow.py` |
| 7 Talk keys | 6 | `present.js`, `keys.py`, `lee-core.js`, `tests/test_present.py`, `tests/test_talk_slow.py` |
| 8 Reload | 7 | `nb/app.py`, `present.js`, `lee-core.js`, `tests/routes.txt`, `tests/test_talk_routes.py`, `tests/test_talk_slow.py` |
| 9 Live output, Stop, restart | 8 | `present.js`, `editor/mount.js`, `runtime/kernel.js`, `nb/app.py`, `audience.js`, `lee-core.js`, `lee-audience.js`, `tests/routes.txt`, `tests/test_talk_routes.py`, `tests/test_present.py`, `tests/test_talk_slow.py` |
| 10 Room features and recap | 9; open question 1 answered | `nb/talk.py`, `nb/app.py`, `present.js`, `lee-core.js`, `tests/routes.txt`, `tests/test_talk_room.py`, `tests/test_talk_slow.py` |
| 11 Themes (slow half) | 6 | `tests/test_talk_slow.py` |
| 12 "What does this print?" | 10 and abhyasa's run-ask commit on `main` | `nb/talk.py`, `nb/app.py`, `present.js`, `audience.js`, `agent/ai.py`, `pyproject.toml`, `uv.lock`, `lee-core.js`, `lee-audience.js`, `tests/routes.txt`, `tests/test_talk_run.py`, `tests/test_talk_slow.py` |
| 14 Docs | 10 | `docs/present.md`, `CHANGELOG.md` |

Two writers after Task 0, on lines that touch disjoint files:

1. Writer A (Python): 1, then 3, then 4, then 5.
2. Writer B (bundle): 11 (fast half) at once. After Task 1 merges: 2, then 13.

Writer A's files and writer B's files do not overlap: A never edits a `LAYERS` module, and Task 5's build run rewrites `lee-core.js` with no change because Task 5 edits no `LAYERS` module. Task 2 reads `rise_cases.json` and does not change it. Task 13 edits `nb/talk.py` while A is on 3 or 4 only if B reaches 13 early; start 13 only after Task 4 merges.

Barrier: 5 and 13 merge. Then one writer takes 6, 7, 8, 9, 10 in order, then the slow half of 11, then 14. Task 12 starts when abhyasa's run-ask commit is on `main`, after 10.

## Open questions for the owner

The owner answered questions 1, 2, 3, 4, 6 and 7 on 29 October with the recommendation each time. They are decisions 7 to 11 above. Questions 5 and 8 stay with the recommendation unless the owner says otherwise.

1. **Decided (decision 7). Where a saved talk and its run log live.** Choices: abhyasa's shared store (`put_talk`, `put_run`), or `<notebook>.talk.json` beside the notebook. Recommendation: the talk as `<notebook>.talk.json` beside the notebook (it goes with the project and into git, as `leela-reuse.md:250-252` proposes), and the run logs in the shared learning store with `Learning.put_run` (room data stays out of git; `put_run` runs no check). The shared store for the talk itself needs an abhyasa change first: `put_talk` checks with no `schemes` (`abhyasa/talk.py:243`) and refuses `ws:` figures.
2. **Decided (decision 8). What "shared themes and fonts" names.** This plan reads it as Leela's theme families and its fonts (`--lee-*` tokens, `--lee-sans`, `--lee-mono`). If it means abhyasa's themes (paper, ink, manuscript) and its Literata and Libre Baskerville fonts, only `audience.css` changes. Recommendation: Leela's own, so the audience matches the IDE the presenter uses.
3. **Decided (decision 9). The Mac app.** If the Task 6 spike shows that two pywebview windows do not share a `BroadcastChannel`, choose between "Present in your browser" (abhyasa's answer, spec 9.4) and a server relay over the existing `/present/events` stream (not `BroadcastChannel`, so outside decision 4). Recommendation: "Present in your browser" now; the relay only if the owner allows a second channel.
4. **Decided (decision 10). Flatten subslides in the overlay too?** Decision 3 is applied to the two-window talk only. Recommendation: keep reveal's vertical stacks in the overlay, because reveal draws them and RISE users expect them there.
5. **Fragment beat names.** This plan uses `lit:#<cell id>` for a fragment group, inside `check_talk`'s list. Recommendation: keep it, or ask abhyasa for a `frag:<n>` beat if abhyasa will ever draw a Leela talk.
6. **Decided (decision 11). Drop the path source.** `[tool.uv.sources] abhyasa` must go when abhyasa 0.0.12 is on PyPI, before any Leela release. Recommendation: make that a release check in `pullup`'s release workflow, so a release with a path source fails.
7. **Decided (decision 10). Should ⌥R open two windows when a second screen is attached?** Decision 1 keeps ⌥R instant. Recommendation: no; ⌥R stays the one-screen overlay, and the "audience" button or `present_talk` turns on two-window mode.
8. **`room_spec` in abhyasa core.** Leela keeps a copy with a parity test. Recommendation: ask abhyasa to move `room_spec` into `abhyasa.talk`, then drop the copy.
