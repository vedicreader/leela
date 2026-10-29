# Present a notebook: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Leela has one presentation mode. Select a cell. Press Alt+R or click Present. Use arrows or Space. Open Audience window if you have a projector. Alt+R, the toolbar Present button and "Present from this cell" start the same presentation at the selected cell, with unsaved edits, and write nothing to disk. The audience window is an optional action inside the presentation. Only notebooks are presented.

**Architecture:** The page groups the live cells into one flat line of slides with the RISE rules in `present.js`. It posts that line, with the editor text and outputs, to `POST /present/start`. The server renders and cleans each slide block, keeps the presentation in memory in `Presentation` (`leela/blocks/nb/show.py`), and returns two copies: the presenter copy (notes, demo answers) and the room copy (neither). One shared slide renderer, `leela/blocks/nb/slides.js`, draws both copies on a 1280x720 canvas. The presenter screen is an overlay in the IDE page, because the kernel, `runCell` and the live cells are there. The audience window is a page alone, `/present/audience`, that loads `lee-slides.js`. The presenter posts each move to the server. The server keeps the state of the one presentation and sends each change to the audience windows over SSE (decision 4, changed on 29 October). reveal.js leaves Leela.

**Tech Stack:** Python 3.13, FastHTML, Starlette `TestClient`, abhyasa 0.0.12 (PyPI), rupaka 0.0.6 (PyPI, vendored bundle), `mdhtml`, `nh3`, `uv`, pytest, Node for the JS harnesses, Playwright with its bundled Chromium.

**Sources:** the design review the owner approved on 29 October (it replaces the two-mode plan at `9fe6d4a`); abhyasa `core/stage.js` and `blocks/talk/app.py` at 0.0.12 (the installed copy is the same file as abhyasa `main` at `448ae19`); `docs/decisions.md:626-639` for the theme families.

## Decisions

Owner decisions (final, 29 October):

1. Alt+R is an instant show of the live notebook, with unsaved edits. A presentation writes no file.
2. Slides come from RISE cell metadata: `slide`, `subslide`, `fragment`, `skip`, `notes`. H2 headings cut slides only when no cell is marked `slide` or `subslide`; `fragment`, `notes`, `skip` and `-` marks still allow them (session decision after the Task 1 review, matching today's boundary rule). Slides are cut per cell, so a markdown cell with several H2 headings opens one slide.
3. RISE subslides are flattened into one line.
4. There is one mode. The audience window is an optional action inside it. Changed on 29 October (`target/reviews/task4-review.md`): the audience window gets its updates through the Leela server, not over `BroadcastChannel`. The presenter (the IDE window) posts its moves to the server: slide, step, laser point, blank, demo state (`Rupaka.state`), gate settle and open, output and end. The server holds the current state of the one presentation (`Presentation` in `presentation.py`) and sends each change to the audience windows over SSE, keyed by the per-session key. A reloaded audience window gets the current state at once (slide, step, demo state, settled gates, last output). A reloaded presenter resumes from the server's state. The audience window has GET routes only. The presenter shows `Audience window: connected` or `Audience window: not connected` from the server's count of audience streams, not from timers.
5. Esc never ends the presentation.
6. Leela's themes and fonts are used everywhere. `rise.theme` is dropped.
7. Saved talks and run logs are deferred. If they return, the talk is `<notebook>.talk.json` beside the notebook and run logs go to the shared learning store.
8. "Shared themes" means Leela's own theme families and fonts (`--lee-*` tokens, `--lee-sans`, `--lee-mono`).
9. Dropped on 29 October. The fallback "Present in your browser" is not needed. Leela serves the audience page, so the Mac app opens it in the system browser and it gets the same updates from the server.
10. There is no "Present to a room" command and there are no vertical stacks. Alt+R starts the one mode.
11. No path source is in a release. A release check fails while `[tool.uv.sources] abhyasa` is there.

Kept from today: RISE metadata, fragments, `skip` and `notes` cells, start at the selected cell, live cell runs in the kernel, unsaved edits, A-/A+, the RISE editor chords (`keys.py` `slide_none` to `slide_notes`, `menus.py:40-41`).

Dropped: reveal.js and its themes, `rise.theme` and every other reveal option, vertical navigation, the align toggle, the separate notes browser page and its routes, a window that opens on its own.

Settled abhyasa contracts (abhyasa 0.0.12; the installed `abhyasa/core/stage.js` is 306 lines):

- `abhyasaStage.channel(name)` opens `BroadcastChannel('abhyasa-stage:' + name)` and drops every message that `valid` refuses (`stage.js:105-108`). `on(t)` throws for a type that is not in the table (`stage.js:116`).
- A message is valid only when `JSON.stringify(m).length` is at most 65536 UTF-16 code units (`stage.js:9` `MOST`, `stage.js:88`).
- Leela uses the v1 types `go` `{slide: 's<n>', beat: 0..50}`, `point`, `demo`, `blank`, `end`, `hello`, `here`, `answers` (`stage.js:57-83`). Leela does not change the v1 table.
- `abhyasaStage.add(t, fields, need, ok)` adds a type. It throws for a name that is there and for a name outside `^[a-z]{1,16}$` (`stage.js:94-103`).
- `abhyasaStage.audience` subscribes only to the fixed `DRAWN` list (`stage.js:124`, `:157`). A type added with `add` reaches `draw` only through an explicit `ch.on`.
- `abhyasaStage.presenter(el, ch, {keys})` takes keys only while `html` has the class `talk`. It ignores Alt, Cmd, Ctrl and held keys (`stage.js:174`), keys in a text box (`stage.js:176`) and keys in `[data-rupaka]` except Esc (`stage.js:177`). A key name is its `e.code`, with `Shift+` before it (`stage.js:178`).
- `abhyasaStage.mirror(host)` needs `Rupaka.state`, `set`, `settle`, `options` and `open` (`stage.js:217`, `:224`). It returns `{snapshot, apply, watch, answers, reveal, forget}` (`stage.js:300`). `apply` makes every gate of the audience copy `inert` (`stage.js:243`). A gate is done when no listener calls `preventDefault` on its `rk-predict` (`stage.js:229-236`).
- `room_spec` is in `abhyasa.core.stage`. Importing `abhyasa.core` loads abhyasa's web UI modules and its settings, and Leela's code imports no abhyasa web code (`tests/test_learn_pane.py`), so Leela keeps its own copy.

Decisions made in this plan (the owner can overrule each one):

- **One grouping, in the page.** `presentSlides` (`present.js:44-63`) stays the only implementation of the RISE rules. The server needs the slide content, because the audience window loads the deck after a reload, a deck is larger than one channel message, and every byte that reaches the room is cleaned on the server first. The server does not need to group. The page posts the grouped line, and the server checks its shape (every id is a posted cell, fragment groups ascend, at most 9999 slides). There is no Python RISE port.
- **The server renders slide markup for both windows.** Markdown goes through the same `mdhtml` calls as `/markdown/render` (`leela/app.py:952-955`) and then `clean_html` (`leela/core/text.py:146-150`). The presenter preview and the audience draw the same HTML, so what the presenter sees is what the room sees.
- **One shared slide renderer.** `slides.js` is in `LAYERS` for the IDE page and in `ALONE` as `lee-slides.js` for the audience page, as `blocks/learn/pane.js` is in both today (`tools/build_ide_js.py:39`, `:55`). `orphans()` (`build_ide_js.py:77-81`) needs no change.
- **reveal.js is removed**, with `leela/vendor/reveal/`, `loadReveal`, `presentFit` and the reveal options of `riseConfig`. It brought a second public keymap and the white page.
- **No channel (decision 4, changed).** The key is `secrets.token_hex(16)` from `POST /present/start`, made without `new_run`. It names the room stream `GET /present/room?k=<key>`. No window opens a `BroadcastChannel`.
- **Server events, not Leela stage types.** The room stream sends `state`, `at` (slide, step, blank and the A-/A+ size in tenths, so both windows draw the same text size), `point`, `demo`, `answers`, `look` and `end`. Task 7 adds `out` for cleaned rich output. The audience page checks each `point`, `demo` and `answers` with `abhyasaStage.valid` before it draws it. Leela adds no type with `abhyasaStage.add`.
- **Fragments on the wire.** `go.slide` is `s<n>` from 1. `go.beat` is 1 plus the number of fragment groups shown. A slide shows at most 49 fragment groups. Groups after the 49th show with the 49th, and the presenter sees a warning.
- **Notes-only slides make no slide.** Their notes join the notes of the next visible slide.
- **`riseConfig` keeps `start_slideshow_at` only.** `/tab/state` still carries `rise` (`tests/test_present.py:86-97` stays green).
- **The audience page links `lee-ide.css` for tokens and fonts**, then `lee-slides.css`. The token blocks do not move: `theme_backgrounds` reads the families from `lee-ide.css` (`leela/blocks/settings/settings.py:282-286`).
- **Last good output.** A run that fails sends the room its outputs without the `error` entry. The room never sees a traceback until the presenter chooses Show error.
- **The audience window takes F or a double-click to fill the screen**, because only a gesture in that window can do it. It takes no other key and shows no key help.

## Survey

Entry points and call paths this plan changes (branch `present-talk` at `9fe6d4a`):

- Start: `present_notebook` is `alt+r`, global (`leela/core/keys.py:157`). `present_from_cell` has no key, editor scope (`keys.py:193`). Both call `presentNotebook` (`leela/static/js/actions.js:65-66`). Toolbar button `Btn('present_notebook', 'present', ...)` (`leela/core/ui.py:54`, `leela/app.py:413`), tab menu (`leela/blocks/keys/menus.py:46`), cell menu (`menus.py:39`), View menu (`menus.py:100`), palette.
- Deck today: `presentSlides` (`leela/blocks/nb/present.js:44-63`), `presentAt` (`:66-72`), `riseConfig` (`:75-88`, `simple` at `:85`), `presentFit` (`:28-40`), `presentCell` (`:120-136`), `presentRun` (`:137-148`), `presentTitle` (`:150-156`), `presentNotesPage` (`:163`), `presentNotebook` (`:165-269`), the six-button bar (`:174-179`), the Esc handler (`:237-240`), `onOutput` (`:241-243`), the reveal theme link (`:246-247`), the Reveal instance (`:250-253`), the notes page that opens on its own (`:268`), `closePresentation` (`:271-287`, focus back at `:286`).
- Key routing: `lee.present` puts every key in scope `overlay` (`leela/blocks/keys/keymap.js:53`), and `findBinding` returns no binding there (`keymap.js:155`). During a show no Leela key fires, the interrupt key included.
- Kernel: `interrupt` posts `/kernel/interrupt` (`actions.js:37-38`). `restart` posts `/kernel/restart` and calls `markPreviousRuns` (`actions.js:41`, defined at `leela/blocks/editor/mount.js:493`). The reconnect button of the kernel dialog posts `/kernel/restart` and does not call `markPreviousRuns` (`leela/blocks/runtime/kernel.js:35`).
- Server today: `NAV` (`leela/blocks/nb/app.py:54`), `Show` (`app.py:103-121`), `show = Show()` (`app.py:714`), routes `/present/notes`, `/present/state`, `/present/nav`, `/present/events` (`app.py:715-743`). The notes page `leela/static/present-notes.html` has its own colours and fonts (`:5-7`).
- rupaka: `rupakaDraw` mounts a demo in a shadow root and keeps the host by key (`leela/static/js/core.js:617-628`). `rupakaFences` replaces each `pre > code.language-rupaka` (`core.js:678-690`). The fence language is `rupaka` (`leela/blocks/nb/lesson.py:277`). `lessonPredict` files a gate only inside `.lee-cell[data-id]` (`leela/blocks/nb/lesson.js:68-70`, listener at `:88`).
- Markup: `/markdown/render` (`leela/app.py:943-955`), `clean_html` (`leela/core/text.py:146-150`), `renderMath` (`core.js:645`), `resolveMarkdownImages` (`core.js:713-724`).
- Separate windows: `inDesktopShell`, `openTab`, `openExternal` (`core.js:730-740`). In the Mac app `openExternal` opens the system browser.
- Guard: `learn_navigation` (`leela/hub.py:128`) and `LoopbackHostGuard` (`hub.py:134`, cross-site check at `:144`), wrapped at `leela/app.py:1437`. No Leela page except `/learn` sends a CSP.
- Static: `/leestatic` serves `leela/static` then `leela/vendor` (`leela/core/web.py:33-35`, mount at `leela/app.py:919`). The Mac app copies `leela/static` without `js` (`packaging/macos/setup.py:21`). JS bundles: `LAYERS` (`tools/build_ide_js.py:24`, `present.js` at `:28`) and `ALONE` (`:55`), built at `:86`.
- Themes: `THEMES` (`leela/blocks/settings/prefs.js:4`), default `cursor:light:tight` (`prefs.js:20`), `darkQuery` (`:24`), `themeMode` (`:52`), `paintTheme` (`:54`), the system listener (`:79`). Tokens and fonts (`leela/static/lee-ide.css:11-17`), families (`lee-ide.css:33-253`). The code font is the editor setting `fontFamily` (`leela/blocks/settings/settings.py:26`).
- Tests today: `tests/test_present.py` (`_js` `:15-21`, grouping `:26-61`, `riseConfig` `:63-75`, `presentStep` `:77-79`, tab `rise` `:86-97`, one action `:99-116`, notes page `:118-142`, packaging `:149-163`); `tests/test_present_slow.py` (main test `:129-151`, long slide `:160-211`, align `:216-244`, external link `:247-257`); `tests/test_web_slow.py` (`_free_port` `:40`, `_serve` `:45`, `_launch` `:55`); `tests/conftest.py` (`XDG_CONFIG_HOME` `:13`, `ABHYASA_CONFIG` `:15`).
- `tests/routes.txt` is a hand list. No test reads it. No `/present/*` route is in it today.

## Look

The slide uses Leela's tokens and fonts only: `--lee-bg`, `--lee-bg1`, `--lee-fg`, `--lee-fg2`, `--lee-fg4`, `--lee-border`, `--lee-accent`, `--lee-output`, `--lee-red`, `--lee-sans`, `--lee-mono` (`lee-ide.css:11-17`, families per `docs/decisions.md:626-639`).

- Canvas: one 1280x720 reference canvas in both windows, scaled with `transform: scale()` to the window. Safe margins 64px left and right, 48px top and bottom. All text is left-aligned, headings included.
- Type: headings 44-46px, body 28px, code and output 24-26px in `--lee-mono`, captions 20px.
- Fit: the renderer shrinks text in steps down to a floor (body 20px, code 18px). At the floor it stops. The slide is cut at the safe margin, and the presenter sees `Slide N has more than fits. Split it or trim it.` This is the principle of abhyasa `core/talktype.js:18-31`; Leela does not copy the file.
- Blank: the page is `--lee-bg` with the notebook title in `--lee-fg4`.
- Presenter chrome: 16-24px gutters, a notes column of about 320px, notes at 18px, a thin status line at the top.
- `lee-slides.css` holds about 20-25 lines that replace `abhyasa/core/stage.css:4-25` (layout, blank, laser dot) in Leela tokens. It has no serif default and no pane rules. Leela does not serve abhyasa's `stage.css`.

The review found these defects. Task 4 fixes each one, and its tests pin them:

- `.lee-present` hard-codes `background: #fff` (`lee-ide.css:4029`).
- `riseConfig` defaults to reveal's `simple` theme (`present.js:85`).
- The notes page has its own colours and fonts (`present-notes.html:5-7`).
- Headings stay centred under `left` (`lee-ide.css:4035`). Output is `.45em` (`lee-ide.css:4037`) and run controls `.4em` (`lee-ide.css:4039`).
- The six-button 12px bar stays visible at 30% opacity (`present.js:174-179`, `lee-ide.css:4044-4048`).
- A failure shows hard-coded red on the slide (`lee-ide.css:4043`, `present.js:144-146`).

## Failure and recovery states

| state | route or call | response | task |
|---|---|---|---|
| not a notebook | `presentNotebook` | `only a notebook can be presented as slides` in the status line | 4 |
| nothing to present, or notes only | `presentNotebook`, `POST /present/start` | today's `PRESENT_NOTHING` text; 400 | 1, 3 |
| bad slide line (unknown cell id, fragment groups out of order, over 9999 slides) | `POST /present/start` | 400 with the reason; no presentation starts | 3 |
| more than 49 fragment groups on a slide | page and server | the slide shows; the presenter sees a warning with the slide number | 1, 4 |
| text over the floor | renderer | cut at the safe margin; the presenter sees `Slide N has more than fits. Split it or trim it.` | 4 |
| wrong, stale, empty, missing or non-text key | every route with `k` | 403 `This presentation link is not valid.` | 3 |
| no presentation | same | 410 `This presentation has ended.` | 3 |
| a later start arrives while a start builds | `POST /present/start` | the earlier one: 409 `A newer presentation started.`; nothing changes for it | 3 |
| malformed start or a build failure | `POST /present/start` | 400 with the reason (500 for a build fault); the live presentation, key, images and subscribers do not change | 3 |
| unknown slide, step out of range | `POST /present/at` | 400, place unchanged | 3 |
| cross-site request | every `/present/*` route | 421 from `LoopbackHostGuard` (no exemption) | 3 |
| second client starts | `POST /present/start` | old presentation ends; `presentation-ended` `{id, reason: 'replaced'}` on `/present/events`; old page shows `Another presentation started.`; old audience shows the end card | 3, 4 |
| popup refused | Audience window button | the button stays; status `The browser blocked the window. Click again.` | 4 |
| Mac app | Audience window button | the system browser opens the audience page through `openExternal`; it gets the same server events (decision 9 dropped) | 4 |
| audience window closed | presenter | the server's count of room streams falls to 0; the strip says `Audience window: not connected`; nothing on the presenter screen moves; the presentation goes on | 4 |
| Esc | presenter | dismisses one transient thing, leaves demo focus or exits fullscreen; never ends | 5 |
| reload of the IDE page | `POST /present/resume` | the presenter screen comes back at the same place with the same key and live state | 6 |
| stale `localStorage` while another presentation is live | `POST /present/resume` | 410 or 403; the page removes the entry and touches nothing | 6 |
| reload of the audience window | `GET /present/room` | the first event is `state`: the place, blank, size, theme, each demo state and the answers sent so far (Task 7 adds the last output of each cell); the presenter sends nothing | 4, 6 |
| presentation ended or replaced | `GET /present/room` | the stream sends `end` `{}` with no key and closes; the audience shows the end card; a reconnect gets 410 | 4 |
| wrong, missing or stale key on the room stream | `GET /present/room` | 403 or 410 before any event; no state | 4 |
| server restarted | `POST /present/resume` 410 | the page offers "Present again from slide N"; a new key; the audience window opens again | 6 |
| output for a cell that is not on a visible slide | `POST /present/out` | 400, nothing sent | 7 |
| stale output (older `gen` or `seq`) | `POST /present/out`, audience `cellout` | dropped; 200 `{stale: true}` | 7 |
| output over the message limit | `clip_msg` | clipped at a block edge, ends with `Output is too long for the room screen.` | 2, 7 |
| run fails | presenter | room keeps its outputs without the error; private panel with summary and traceback; Show error sends it | 7 |
| cell does not finish | presenter | Stop interrupts the kernel | 7 |
| kernel restart | presenter | output cleared on both screens; Run enabled | 7 |
| demo snapshot over the limit | presenter | not sent; status `The demo is too large for the room screen.`; audience keeps the last state | 7 |

## Global Constraints

- **Task 0 first.** It is done (`e4c3260`, checked against abhyasa main `448ae19`). No other task edits `pyproject.toml`, `uv.lock`, `leela/vendor/*` or `tests/test_abhyasa_contract.py` until Task 0 merges.
- **Plan review.** Before you edit code for a task, send that task (its survey lines, routes, failure states and tests) to an independent teacher sub-agent for a missing-cases review, as `AGENTS.md` asks. Task 5 also needs the keymap audit that `AGENTS.md` asks for before a key changes.
- **Code style.** `CLAUDE.md`: dense fastai style, one-line docstrings, no banner comments, rationale in `docs/`. Never hand-roll what abhyasa, rupaka, mdhtml, nh3, fastcore or shalya does.
- **One checked copy.** Leela keeps one copy of `room_spec`, because importing `abhyasa.core` loads abhyasa's web UI. A parity test reads `abhyasa/core/stage.py` as text and compares the two on every case. The copy goes when abhyasa makes `abhyasa.core.stage` importable on its own (asked of the abhyasa session on 29 October).
- **Tests never reach the owner's data.** `Workspace(roots=[tmp_path])`. `tests/conftest.py` sets `XDG_CONFIG_HOME` and `ABHYASA_CONFIG` under a temp folder. A slow test serves the app with `_serve(ws, _free_port())`. Never port 5001, never the running Leela on ports 5010-5019, never the owner's workspace.
- **Processes.** Never kill a process by name. A test stops only what it started.
- **Browser checks.** Playwright's bundled Chromium through `_launch` (`tests/test_web_slow.py:55`), or Chrome for Testing named by `LEELA_CHROMIUM`. Never `/Applications/Google Chrome.app`, port 9223 or `~/.cache/fastcdp/cdp-chrome`. One browser at a time, closed in a `finally`, headless, audio muted. Two windows are two pages of one context: `context.wait_for_event('page')` after the presenter's `window.open`. Browser tests go in `*_slow.py` files and run with `-m slow` (`pyproject.toml:111` has `-m 'not slow'`).
- **JS bundle.** After an edit to a module in `LAYERS` or `ALONE`, run `uv run python tools/build_ide_js.py`. It rewrites `leela/static/lee-core.js` and the other bundles, so two JS tasks never run at the same time.
- **Routes.** Add each new route to `tests/routes.txt` (house habit; no test reads it).
- **Network.** No test uses the network.
- **Prose.** UI text, docs and commit messages are ASD-STE100 Simplified Technical English, US grade 9. No em dashes. Read the `write_docs` pyskill first.
- **Commits.** One plain line for each task. No AI credit, no `Co-Authored-By`.
- **Pass gate for each task.** The task's own tests, then `uv run pytest -q -x --ignore-glob='*_slow.py'`, then the task's slow tests with `-m slow`.

## Review Focus

1. **Notes or answers reach the room before reveal.** Expected: `/present/deck`, the audience page and every room event before the presenter reveals hold no notes, no gate `answer`, no path and no editor-only id. Tests: `test_room_copy_has_no_notes_answers_or_paths` (Task 2), `test_a_gate_answer_never_reaches_the_room_before_reveal` (Task 2, Task 7).
2. **Script in a cell output or in markdown.** Expected: the server drops `<script>`, event attributes, `javascript:` and remote `src`; the audience walker drops what the server missed; the audience page sends `script-src 'self'`. Tests: `test_clean_out_keeps_text_and_images_only` (Task 2), `test_audience_walker_drops_what_the_server_missed` (Task 4), `test_audience_page_headers` (Task 3).
3. **Another page drives the presentation.** Expected: 421 for a cross-site request, 403 without the key or with a stale key on every mutation route, no framing of the audience page, no state on the room stream for a wrong key, and an audience page that has GET routes only and posts nothing. Tests: `test_every_mutation_route_refuses_cross_site_and_wrong_keys` (Task 3), `test_the_room_stream_refuses_bad_keys_with_no_state` and `test_the_audience_cannot_post` (Task 4).
4. **One stray key ends a presentation.** Expected: Esc, Alt+R, Alt+W, Alt+T, `/` and the palette chord never end or leave it. Test: `test_esc_never_ends_the_presentation` (Task 5).
5. **A reload loses the place or the live state.** Tests: `test_reload_keeps_the_place`, `test_reload_mid_run` (Task 6).
6. **Alt+R writes files.** Expected: a presentation, with runs and the audience window, writes no file under the workspace. Test: `test_a_presentation_writes_nothing` (Task 4).

## Key map

The presenter sets the class `talk` on `html` while the presentation is open. `present.js` binds this `keys` object with its own capture listener, because the IDE page does not load `stage.js` (decision 4, changed). It follows the rules of `abhyasaStage.presenter`: no held keys, no Alt, Cmd or Ctrl, no keys in a text box or a demo except Esc, and Space or Enter on a focused button presses the button. `keymap.js:53` still routes every key to scope `overlay`, and `keymap.js:155` gives no binding there, so no Leela command fires behind the presentation. Stop is a button for that reason.

| key (`e.code` name) | action |
|---|---|
| `ArrowRight`, `ArrowDown`, `Space`, `PageDown` | next fragment group, then next slide |
| `ArrowLeft`, `ArrowUp`, `Shift+Space`, `PageUp` | back one fragment group; back onto a slide shows all its groups |
| `KeyX` | laser on or off |
| `KeyB` | blank on or off |
| `Escape` | dismiss one thing, in this order: a `.lee-modal` dialog (its own handler wins), the error panel, the Notes panel on one screen, the laser, demo focus; with nothing open, nothing happens. Fullscreen: the browser takes Esc; the rule that ignores Esc within 400 ms of leaving fullscreen stays (`present.js:238`) |
| any other plain key | nothing |
| Alt+R, Alt+W, Alt+T, `/`, the palette chord | nothing (scope `overlay`) |

The strip buttons are previous, next, slide number, Audience window, Notes, A-, A+ and End, plus Run and Stop for the code cells of the current slide. The rows go into `KEYS` as a "Present" group of display rows, so the Keyboard shortcuts page and the palette list them. No new global binding is added.

---

### Task 0: Pin abhyasa 0.0.12 and rupaka 0.0.6, and write the rupaka bundle again

Goal: the lock holds abhyasa 0.0.12 from the local checkout and rupaka 0.0.6, and the vendored rupaka bundle is that version. Done in `e4c3260`, and checked again against abhyasa main `448ae19` (the final 0.0.12).

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

**Risks:** the path source records a local path in `uv.lock`, so the app bundle build and CI on another machine cannot resolve abhyasa until the line is dropped (decision 11). rupaka 0.0.3 to 0.0.6 can change the API that `rupakaDraw` and `rupakaFences` use; the rupaka and lesson tests are the check.

---

### Task 1: One slide line with fragments, shared by both windows

Goal: `presentSlides` groups with the H2 fallback and the notes-only rule, `presentLine` flattens subslides into one line, and `presentPlace` gives the start place. One case table pins the rules.

**Files:**
- Modify: `leela/blocks/nb/present.js:44-72` (`presentSlides`, `presentAt`; add `presentLine`, `presentPlace`, `presentMove`), then rebuild `leela/static/lee-core.js`
- Create: `tests/data/rise_cases.json`
- Modify: `tests/test_present.py` (add tests; `:26-61` stay as they are)

**Interfaces:**
- `presentSlides(cells, src)` keeps its `[[slide, ...subslides], ...]` shape, so `tests/test_present.py:26-61` stay green. New rule: when no non-approval cell is `slide` or `subslide` and a markdown cell has an H2 line, an H2 cell opens a slide and an untyped cell continues it. With no H2 either, each cell is its own slide (today's rule).
- As built (Task 1): H2 detection is per cell and markdown-only; it reads live editor text through `src`; it ignores `## ` inside backtick or tilde fences, including longer and unclosed fences; it accepts up to 3 leading spaces, a bare `##` and CRLF, and rejects `###`, `##tight` and 4-space indented code. In H2 mode a markdown cell marked `-` with an H2 line still opens a slide, so a notebook that Jupyter's slideshow toolbar marked all `-` does not become one slide (case `h2_dash`); outside H2 mode `-` continues the current slide as today. Approval cells (`approval != null`, matching `nb.py:194`) never switch on typed or H2 mode. Notes of a notes-only slide join the next visible slide before its own notes; trailing notes-only slides join the last visible slide; a notebook with only notes gives an empty line. More than 49 fragment groups put every extra fragment in the 49th group and set `warn`.
- `presentLine(deck) -> [{items: [{i, frag}], notes: [i], groups}]`: subslides flattened in order. A slide with notes only gives its notes to the next slide with items and is dropped. `groups` is the number of fragment groups, at most 49. `warn` is true when the notebook had more.
- `presentPlace(line, i) -> {slide, step}`: the slide that holds cell `i`, or the nearest visible cell above it. `step` is the number of fragment groups shown: 0 for a body cell, k for a cell of group k (before its fragment), as `presentAt` does today.
- `presentMove(line, at, d) -> at`: `d = 1` shows the next group, then moves to the next slide with step 0. `d = -1` hides one group, then moves back to the previous slide with all its groups shown. It stops at both ends.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_present.py: add
CASES = json.loads((ROOT/'tests'/'data'/'rise_cases.json').read_text())

def test_the_slide_line_follows_the_case_table():
    got = _js('Object.fromEntries(Object.entries(' + json.dumps({k: [_cell(t, s, kind) for kind, t, s in c['cells']] for k, c in CASES.items()}) +
              ').map(([k, v]) => [k, presentLine(presentSlides(v)).map(s => ({items: s.items.map(x => [x.i, x.frag]), notes: s.notes}))]))')
    assert got == {k: c['line'] for k, c in CASES.items()}

def test_h2_cuts_slides_only_without_slide_metadata():
    plain = [_cell(None, '## A\ntext'), _cell(None, 'x', 'code'), _cell(None, '## B'), _cell(None, 'y')]
    typed = [_cell('slide', '## A'), _cell(None, '## B')]
    got = _js(f'[{json.dumps(plain)}, {json.dumps(typed)}].map(c => presentLine(presentSlides(c)).map(s => s.items.map(x => x.i)))')
    assert got == [[[0, 1], [2, 3]], [[0, 1]]]

def test_move_and_place_walk_fragments_in_one_line():
    cells = [_cell('slide', 'a'), _cell('fragment', 'b'), _cell('subslide', 'c'), _cell('notes', 'n'), _cell('slide', 'd')]
    got = _js(f'''(() => {{ const l = presentLine(presentSlides({json.dumps(cells)})), m = presentMove;
      let a = {{slide: 0, step: 0}}, walk = [a];
      for (const d of [1, 1, 1, 1, -1, -1]) walk.push(a = m(l, a, d));
      return {{n: l.length, walk, place: [1, 3, 4].map(i => presentPlace(l, i))}}; }})()''')
    assert got['n'] == 3
    assert [(w['slide'], w['step']) for w in got['walk']] == [(0, 0), (0, 1), (1, 0), (2, 0), (2, 0), (1, 0), (0, 1)]
    assert got['place'] == [{'slide': 0, 'step': 0}, {'slide': 1, 'step': 0}, {'slide': 2, 'step': 0}]

def test_more_than_49_fragment_groups_warn():
    cells = [_cell('slide', 'a')] + [_cell('fragment', f'f{i}') for i in range(52)]
    s = _js(f'presentLine(presentSlides({json.dumps(cells)}))[0]')
    assert s['groups'] == 49 and s['warn']
```

The case table starts as the cases of `tests/test_present.py:26-61` (`typed`, `leading`, `notes_first`, `sub_first`, `untyped`, `nothing`, the skip case), each with `cells` and `line`, plus two H2 cases and one leading-notes case.

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_present.py -q -k "case_table or h2 or one_line or 49"`
Expected: FAIL with `ReferenceError: presentLine is not defined`.

- [ ] **Step 3: Implement** as the interfaces say. `presentNotebook` does not change in this task.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run python tools/build_ide_js.py && uv run pytest tests/test_present.py -q && uv run pytest -q -x --ignore-glob='*_slow.py' && uv run pytest tests/test_present_slow.py -q -m slow`
Expected: PASS. `test_present_slow.py` uses typed cells, so today's overlay counts do not change.

**Risks:** an untyped notebook with H2 headings shows fewer, longer slides (decision 2). The fit rule of Task 4 handles a long slide.

---

### Task 2: The room copy: markup, output cleaning, clipping and answer stripping

Goal: the server turns the posted slide line into a presenter copy and a room copy. The room copy holds allow-listed markup only, with no notes and no gate answer. A cell output becomes clean HTML with text and images only, clipped to the stage message limit.

**Files:**
- Create: `leela/blocks/nb/show.py` (`demo_fences`, `slide_html`, `clean_out`, `clip_msg`, `room_spec`, `decks`)
- Create: `tests/test_present_room.py`

**Interfaces:**
- `demo_fences(md) -> (str, list[dict])`: the text with every ```` ```rupaka ```` and `~~~rupaka` fence removed, and the parsed specs in order. A fence that does not parse as JSON is removed too, and gives no demo.
- `slide_html(md, base, key, images) -> str`: `mdhtml` with the options of `/markdown/render` (`leela/app.py:953-955`), `allow_raw` false, then `clean_html` (`leela/core/text.py:146-150`). Then each `img src`: a path inside a workspace root becomes `/present/img/<sha256>?k=<key>` and its bytes go into `images`; a `data:image/(png|jpeg|gif|webp);base64,` source stays; any other source is dropped.
- `clean_out(outputs, key, images) -> (room, error)`: `stream`, `text/plain`, `text/markdown` (through `slide_html`), `text/html` (through `clean_html`), `image/png`, `image/jpeg`, `image/gif` (by hash into `images`). `room` is the HTML of every output except `error`. `error` is `{ename, evalue, traceback}` with ANSI codes removed, or None. Never `<script>`, `on*` attributes, `javascript:` or a remote `src`.
- `clip_msg(msg, most=65536) -> dict`: cuts `msg['html']` so that the JSON of the whole message, counted in UTF-16 code units as `JSON.stringify` counts, is at most `most`. It drops whole trailing blocks first, then cuts the text of the last text block and escapes it again. The result is balanced markup and ends with `<p>Output is too long for the room screen.</p>` when anything was cut.
- `room_spec(spec)`: Leela's copy of `abhyasa.core.stage.room_spec`. `tests/test_present_room.py::test_room_spec_matches_abhyasa` compares it with abhyasa's source, and `tests/test_abhyasa_contract.py::test_room_spec_contract` pins abhyasa's function.
- What the room never receives (Task 2 review decision, pinned by tests): notes and skipped cells with their source, outputs, demos and images; `next` titles; tracebacks; any gate `answer` in a demo, from a markdown fence, a `text/markdown` or `text/html` output, or `application/vnd.rupaka+json`; the HTML page fallback of a rupaka output; HTML comments and `id`, `data-id` and `title` attributes; file links (only `http(s)`, `mailto` and `#` stay); any workspace path; any image source other than `/present/img/<sha256>?k=<key>`.
- Stated limits (the room can still see these; the guide says so): an answer written as plain text, stream text, escaped HTML, code source, or a rupaka example shown inside another fence; a gate whose answer is a state path or a derived value (`room_spec` removes the key, the state stays); the gate's `why`, `prompt` and `options` (parity with abhyasa); `alt` text; stderr text.
- As built (Task 2), where it differs from the lines above: `demo_fences` runs on rendered and cleaned HTML with the IDE's own selector `pre > code.language-rupaka` (as `core.js:680` does), through BeautifulSoup, so the room finds exactly the demos the page would mount; a fence that is not JSON or fails `rupaka.spec.validate` is dropped, never kept as code. `slide_html` and `room_html` return `(html, specs)`. `decks` and `clean_out` take an optional `fs` (the `Sandbox`, `ctx.fs`), and a local image is read only through `Sandbox._check`. Code blocks have `html` (source) and `out` (outputs). Images are PNG, JPEG, GIF or WebP checked from the bytes, at most 8 MB each, 16384 pixels a side, 40 million pixels, 100 images and 64 MB in total; SVG is refused. A room spec fails `validate`, so room HTML must never pass through `room_html` again. `beautifulsoup4` is declared in `pyproject.toml`.
- `decks(line, cells, base, key, title, look) -> (presenter, room, images)`: both copies are `{title, look, slides: [{id: 's<n>', groups, blocks: [{cell, frag, kind, html, demo}]}]}`. A markdown block's `html` is `slide_html` of its text after `demo_fences`; `demo` is the list of specs. A code block's `html` is its source as highlighted `<pre><code>` plus `out` from `clean_out`. The presenter copy adds `notes` (the notes cells, as `slide_html`), `next` (the next slide's title by the `presentTitle` rule) and the specs with answers. The room copy has `room_spec` of each spec, no `notes`, no `next`, and no cell id that is not on a slide. `look` is `{theme, mono}` from the saved theme and the editor `fontFamily`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_present_room.py
import json
from leela.blocks.nb.show import clean_out, clip_msg, decks, demo_fences, room_spec

def test_room_copy_has_no_notes_answers_or_paths(tmp_path): ...
    # line with a notes cell 'SPEAKER-SECRET', a demo fence with a gate answer, an image under tmp_path
    # p, r, imgs = decks(...); s = json.dumps(r)
    # 'SPEAKER-SECRET' in json.dumps(p) and 'SPEAKER-SECRET' not in s and '"answer"' not in s and str(tmp_path) not in s
    # every img src in r is '/present/img/<64 hex>?k=' + key, and each hash is in imgs

def test_a_gate_answer_never_reaches_the_room_before_reveal(tmp_path): ...
    # prose, a rupaka fence whose gate answer is {'is': 'ANSWER-7731'}, prose: 'ANSWER-7731' not in json.dumps(r), not in any block html

def test_demo_fences_leave_the_text():
    md = 'Before\n\n```rupaka\n{"slug": "d1", "gates": [{"id": "g", "type": "gate", "answer": {"is": "ANSWER-7731"}}]}\n```\n\nAfter'
    text, specs = demo_fences(md)
    assert 'ANSWER-7731' not in text and 'rupaka' not in text and 'Before' in text and 'After' in text and specs[0]['slug'] == 'd1'

def test_clean_out_keeps_text_and_images_only():
    outs = [{'output_type': 'stream', 'name': 'stdout', 'text': 'tick 0\n'},
            {'output_type': 'display_data', 'data': {'text/html': '<b onclick="x()">ok</b><script>alert(1)</script><img src="https://evil.example/a.png">'}},
            {'output_type': 'error', 'ename': 'ZeroDivisionError', 'evalue': 'division by zero', 'traceback': ['\x1b[31mZeroDivisionError\x1b[0m']}]
    room, err = clean_out(outs, 'k' * 16, {})
    assert 'tick 0' in room and '<b>ok</b>' in room and 'ZeroDivisionError' not in room
    assert 'script' not in room and 'onclick' not in room and 'evil.example' not in room
    assert err['ename'] == 'ZeroDivisionError' and '\x1b' not in ''.join(err['traceback'])

def _size(m): return len(json.dumps(m, ensure_ascii=False, separators=(',', ':')).encode('utf-16-le')) // 2

def test_clip_counts_the_whole_message(): ...
    # escape-heavy text ('"\\<\n' * 30_000), emoji text, and 2000 small image tags: each clip_msg result has _size <= 65536,
    # parses as balanced markup (html.parser with a tag stack), and ends with the 'too long' line; a small message is unchanged

# room_spec is Leela's copy; test_room_spec_matches_abhyasa compares it with abhyasa/core/stage.py, read as text
```

Write each `...` test in full; the comment lines give its assertions.

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_present_room.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'leela.blocks.nb.show'`.

- [ ] **Step 3: Implement** as the interfaces say. Resolve image paths as `resolveMarkdownImages` does (`core.js:713-724`), then refuse any file outside every workspace root.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_present_room.py -q && uv run pytest -q -x --ignore-glob='*_slow.py'`
Expected: PASS.

**Risks:** server markdown can differ from the IDE's `renderMarkdown` for Leela-only fences; those show as code. Math stays as `span.math` and `div.math`; the renderer fills it with KaTeX in both windows.

---

### Task 3: Presentation state in memory, audience assets and guarded routes

Goal: the server holds one presentation in memory, serves the audience page, deck, images and `stage.js` behind the key where needed, keeps the place, and checks the key on every mutation route. It writes no file.

**Files:**
- Create: `leela/blocks/nb/presentation.py` (`Presentation`, `Drop`, `check_start`, the routes); `leela/blocks/nb/app.py:714` calls its `connect` beside `show`, and `/present/events` sends the live id first through a bounded `Drop` queue
- Create: `leela/static/present-audience.html` (no inline script; links `lee-ide.css`, `lee-slides.css`; loads `/present/stage.js`, `/leestatic/lee-rupaka.js`, `/leestatic/lee-slides.js`)
- Modify: `tests/routes.txt`, `packaging/macos/setup.py`, `packaging/windows/setup.py` (`abhyasa` copied whole, for `abhyasa/core/stage.js`)
- Create: `tests/test_present_routes.py`

This task keeps `Show`, `/present/notes`, `/present/nav` and `/present/state` as they are. `tests/test_present.py:118-142` pins them, and Task 1 owns that file in parallel. Task 4 removes them.

**Interfaces:**
- `Presentation`: `key`, `path`, `presenter`, `room`, `images`, `at` (`{slide, step, blank, size}`), `live` (`{outs: {cell: {gen, seq, html, error}}, demo: {slug: snapshot}, answers: []}`), `started`. `begin(...)` replaces all of it. `check(k)`: 410 `This presentation has ended.` with no presentation, 403 `This is not the key of the presentation.` when `secrets.compare_digest` fails. Every route with `k` calls it first.
- `POST /present/start` JSON `{path, title, line, cells, start}` (`cells`: `id`, `cell_type`, editor text, `outputs`): when a presentation is held, it ends it and pushes `presentation-ended` on `/present/events`. Then it checks the line, builds `decks` with `off_loop`, makes `key = secrets.token_hex(8)`, and returns `{ok, key, presenter, at, audience: '/present/audience?k=<key>'}`. 400 for a non-notebook, nothing to present, or a bad line.
- `GET /present/audience?k=` the page. `GET /present/deck?k=` the room copy. `GET /present/img/{h}?k=` an image from `images` with its stored media type; 404 for an unknown hash.
- `GET /present/stage.js`: `importlib.resources.files('abhyasa.core')/'stage.js'`, `Cache-Control: no-cache`, no key. It is public library code. Leela does not call abhyasa's `serve_assets`.
- `POST /present/at` `{k, slide, step, blank, size}`: 400 for an unknown slide, a step outside `0..groups`, or a size outside 5..25.
- `POST /present/end` `{k}`: drops the presentation and pushes `presentation-ended`.
- Headers on the audience page and the deck: `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`. `LoopbackHostGuard` does not change.
- `MUTATIONS` in `tests/test_present_routes.py` lists the keyed mutation routes: `/present/at`, `/present/end`; Task 6 adds `/present/resume`; Task 7 adds `/present/out`, `/present/show-error`, `/present/demo`. `/present/start` is the one unkeyed mutation, because it makes the key; the host guard and the start checks are its only gate. The legacy unkeyed `/present/state` and `/present/nav` act on `Show` alone until Task 4 removes them.
- As built (Task 3), from the session decisions after the teacher review (`target/reviews/task3-review.md`), where they differ from the lines above:
  - `POST /present/start` checks the request first, before any rendering: at most 2000 cells, 1,000,000 characters of source and 4,000,000 characters of output text per cell, 9999 slides, 49 fragment groups, and a body of 32 MB; cells a list of objects with unique text ids and a type in `markdown`, `code`, `raw`, `prompt`; line items and notes integers (not booleans), in range and disjoint; fragment groups in order with `groups` one past the last; `start` a place `{slide, step}` (0-based slide) in the line. An empty line is 400 `There is nothing to present in this notebook.`. The path goes through `ctx.fs` without reading the file or needing it on disk; `..`, a path outside the roots, a symlink out and a path that is not `.ipynb` are refused. Every refusal is a `fail` 400 with a plain message, and the body must be `application/json`.
  - It then builds a complete candidate off the loop (`off_loop`) into new dicts, with `key = secrets.token_hex(16)` made first. Each start takes a number on the loop after its checks; the build replaces the live presentation in one step only when no later start, and no `/present/end`, came while it ran. Otherwise it answers 409 `A newer presentation started.`. A malformed start or a build failure leaves the live presentation, its key, images and subscribers as they were. The reply is `{ok, key, id, presenter, at, audience}`; `id` is a separate random id, never the key.
  - `check(k)`: 410 `This presentation has ended.` with nothing live; else 403 `This presentation link is not valid.` for a missing, empty or non-text key, before `secrets.compare_digest`. Every keyed route calls it first; `/present/img/{h}` checks the key before it looks at `h`, then needs `^[0-9a-f]{64}$` and a hash in the live store (404 `No such image.`). Images are found by key, not hash: the same hash in two presentations answers only to the live key.
  - Every change to the presentation and every event put runs on the event loop: the routes are `async`, and only the deck build leaves it.
  - `GET /present/stage.js` (GET only, no key, no path parameter) serves `files('abhyasa')/'core'/'stage.js'` read with `read_bytes`, as `text/javascript` with `Cache-Control: public, max-age=31536000, immutable` and `nosniff`. The audience page asks for it as `?v=<first 16 hex of its SHA-256>`. The route goes first in the route table, because FastHTML's `/{fname:path}.{ext:static}` route answers every `.js` path. It reads through `files('abhyasa')` and not `files('abhyasa.core')`, because importing `abhyasa.core` loads abhyasa's web UI (`leela/blocks/learn/learn.py:16`). There is no `stage.css` route.
  - Headers: the audience page and the deck send the CSP above, `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff` and `Cache-Control: no-store`; start replies, image replies and every keyed error reply send `no-store` and `nosniff`.
  - `/present/events` sends `presentation` `{id}` first (the live id, or null), then the legacy `state`. An end or a replacement sends `presentation-ended` `{id, reason: 'ended' | 'replaced'}`. Each subscriber has a `Drop` queue of 64 events that loses the oldest, and leaves the set when it disconnects. Task 4's presenter sends `end` on its stage channel when its own id ends; an audience whose presenter is gone stays on the last slide until a reload gets 410.
  - The key is a bearer capability in the audience URL and the image URLs. `no-referrer` and `noreferrer` links stop referrer leaks; history, copied links and logs can still hold it. Task 4 removes `k` from the audience address bar after load with `history.replaceState` and keeps it in `sessionStorage` for a reload.
  - The 32 MB check reads `Content-Length` and the body length in the route. `JsonBody` reads a whole `application/json` body before any route runs, so a larger body is held in memory once before it is refused.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_present_routes.py
import sys, pytest
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.hub import LoopbackHostGuard
from leela.workspace import Workspace

CELLS = [dict(id='m0', cell_type='markdown', source='# Intro\nScores become weights.', outputs=[]),
         dict(id='m1', cell_type='markdown', source='SECRET-NOTE', outputs=[]),
         dict(id='c2', cell_type='code', source='print(1)', outputs=[])]
LINE = [dict(items=[dict(i=0, frag=-1)], notes=[1]), dict(items=[dict(i=2, frag=-1)], notes=[])]
MUTATIONS = [('/present/at', dict(slide='s1', step=0, blank=False, size=10)), ('/present/end', {})]

@pytest.fixture
def rig(tmp_path):
    ws = Workspace(roots=[tmp_path], python=sys.executable)
    try:
        with TestClient(LoopbackHostGuard(ide_app(ws)), base_url='http://127.0.0.1') as c: yield c, tmp_path
    finally: ws.shutdown_now()

def start(c, root): return c.post('/present/start', json=dict(path=str(root/'a.ipynb'), title='a', line=LINE, cells=CELLS, start=dict(slide=1, step=0)))

def test_a_presentation_starts_from_the_live_cells_and_writes_nothing(rig):
    c, root = rig
    before = sorted((p, p.stat().st_mtime_ns) for p in root.rglob('*'))
    r = start(c, root).json()
    assert r['ok'] and r['at']['slide'] == 's2' and 'SECRET-NOTE' in str(r['presenter']) and len(r['key']) == 16
    d = c.get(f"/present/deck?k={r['key']}").json()
    assert 'SECRET-NOTE' not in str(d) and [s['id'] for s in d['slides']] == ['s1', 's2']
    assert c.post('/present/at', json=dict(k=r['key'], slide='s9', step=0, blank=False, size=10)).status_code == 400
    assert sorted((p, p.stat().st_mtime_ns) for p in root.rglob('*')) == before

def test_every_mutation_route_refuses_cross_site_and_wrong_keys(rig):
    c, root = rig
    old = start(c, root).json()['key']; k = start(c, root).json()['key']
    for path, body in MUTATIONS:
        assert c.post(path, json=dict(body, k=k), headers={'sec-fetch-site': 'cross-site'}).status_code == 421, path
        assert c.post(path, json=dict(body, k='0' * 16)).status_code == 403, path
        assert c.post(path, json=dict(body, k=old)).status_code == 403, path
    for p in (f'/present/audience?k={k}', f'/present/deck?k={k}'):
        assert c.get(p, headers={'sec-fetch-site': 'cross-site'}).status_code == 421
    c.post('/present/end', json=dict(k=k))
    assert c.get(f'/present/deck?k={k}').status_code == 410

def test_a_second_start_ends_the_first(rig): ...
    # a /present/events reader started before the second start gets 'presentation-ended'; the first key gives 403

def test_audience_page_headers(rig):
    c, root = rig
    r = c.get('/present/audience?k=' + start(c, root).json()['key'])
    csp = r.headers['content-security-policy']
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and r.headers['referrer-policy'] == 'no-referrer'
    assert '<script>' not in r.text and 'lee-slides.js' in r.text

def test_stage_js_comes_from_abhyasa_without_a_key(rig):
    c, _ = rig
    assert 'abhyasaStage' in c.get('/present/stage.js').text

def test_a_bad_line_says_why(rig): ...
    # an item index past the cells, fragment groups out of order, and an empty line each give 400 with the reason
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_present_routes.py -q`
Expected: FAIL with 404 on `/present/start`.

- [ ] **Step 3: Implement** as the interfaces say. Add the routes to `tests/routes.txt`.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_present_routes.py tests/test_present_room.py tests/test_present.py -q && uv run pytest -q -x --ignore-glob='*_slow.py'`
Expected: PASS.

**Risks:** `Presentation` is per `ide_app`, so two IDE pages of one workspace share one presentation; a second start ends the first and tells the first page. The key is a bearer capability: whoever holds it can read the room copy and move the presentation. `LoopbackHostGuard` is not same-origin authorisation, and this plan does not rely on it as one.

---

### Task 4: The server relay, one shared slide renderer, the look, and the optional audience window

Goal: Alt+R, the toolbar button and "Present from this cell" open the new presenter screen. The shared renderer `slides.js` draws it in Leela's tokens. The Audience window button opens the audience page. That page draws the room copy with the same renderer. The presenter posts each move to the server. The server keeps the state and sends each change to the audience windows over SSE (decision 4). reveal.js, the notes page and its routes leave. This task follows `target/reviews/task4-review.md`; where the review and an older line of this plan disagree, the review wins.

**Files:**
- Create: `leela/blocks/nb/slides.js` (`slidesSafe`, `slidesDraw`, `slidesFit`, `slidesMount`, `slidesTheme`, `slidesAudience`). It uses no global of the IDE page: each input is an argument. It is in `LAYERS` `lee-core.js` before `present.js` and in `ALONE` as `'lee-slides.js'`, as `blocks/learn/pane.js` is in both.
- Create: `leela/static/lee-slides.css` (canvas, type sizes, fragments, blank, laser dot, end card, presenter screen, strip, Notes drawer). The IDE head links it after `lee-ide.css`.
- Modify: `leela/blocks/nb/present.js` (`presentNotebook` rewritten; `riseConfig` keeps `start` only; `loadReveal`, `presentFit`, `presentCss`, `presentNotesPage`, `presentSync`, `presentAlign`, `presentCell`, `REVEAL_THEMES`, `RISE_TRANSITIONS`, `SLIDE_NUMBERS` and `NAV_CMDS` removed)
- Modify: `leela/blocks/nb/presentation.py` (`Room`, `GET /present/room`, `POST /present/move`; `/present/at` sends `at`; `/present/end` and a replacing start send `end`; `/present/events` moves here and sends `audience`)
- Modify: `leela/blocks/nb/app.py` (`NAV`, `Show`, `/present/notes`, `/present/nav`, `/present/state` and `/present/events` leave this file), `leela/blocks/nb/show.py` (`NOT_SHOWN`), `leela/static/present-audience.html` (meta tags for the rupaka CSS and KaTeX, and `lee-hl.css`), `leela/app.py` (head link), `leela/static/lee-ide.css` (the `.lee-present*` rules leave), `tests/routes.txt`
- Delete: `leela/static/present-notes.html`, `leela/vendor/reveal/` and its rows in `leela/vendor/README`
- Modify on purpose: `tests/test_present.py`, `tests/test_present_routes.py`, `tests/test_present_slow.py`, `tests/test_md_output_font.py:90-95` (see Step 1)

**Two keys** (from the teacher review of this task; it makes the owner's "the audience window can never send presenter commands" true):
- `POST /present/start` makes two keys with `secrets.token_hex(16)`: `key` for the presenter and `ak` for the audience. The reply holds both. `audience` is `/present/audience?k=<ak>`.
- The read routes (`/present/audience`, `/present/deck`, `/present/img/{h}`, `/present/room`) take either key. Every image URL in both copies holds `ak`, so the presenter key never reaches the audience page.
- The mutation routes (`/present/at`, `/present/move`, `/present/end`, and the later `/present/resume`, `/present/out`, `/present/show-error`) take `key` only. `ak` gets 403 there.
- The order of the checks stays as in Task 3: with nothing live, every key gets 410; else a missing, wrong or old key gets 403.

**Server routes** (in `presentation.py`; they use the one `Presentation` of Task 3, its `check` and its limits; there is no second store):
- `GET /present/room?k=`: the room stream (SSE). The handler runs the check, takes the live presentation and adds its queue before the stream starts, so an end that comes between them is not lost. The generator never reads `pres.cur`. A refused key gets its 403 or 410 before any event. The first event is `state` `{title, at, look, demo, answers}`: the place, the theme, the latest state of each demo and the answers sent so far. Then each change follows: `at` `{slide, step, blank, size}`, `point` `{x, y}` or `{off: true}`, `demo` `{slug, state, gates, pick}`, `answers` `{slide, slug, gates}` and `look` `{theme}`. When the presentation ends, or a later start replaces it, the stream sends `end` `{}` and closes. No event holds either key. The stream sends an SSE comment every 15 s, so the server sees a closed window and the count of streams falls.
- `POST /present/move` `{k, t, ...}`: the presenter's moves other than the place. `t` is `point`, `demo`, `answers` or `look`. The fields of `point`, `demo` and `answers` follow `stage.js`. `look` is `{theme}` with `theme` as `family:mode:density`. The check in Python has the rules of `stage.js`: no key named `__proto__`, `constructor` or `prototype`, at most 8 levels and 40000 parts, finite numbers, a boolean is never an integer, and the whole move, with `v` and `t`, is at most 65536 UTF-16 units as `JSON.stringify` counts. A `demo` or `answers` slug must be a demo of the room copy, and an `answers` slide must be a slide of it. The body of a move is at most 512 KB, because an escaped JSON body can hold 6 bytes for each UTF-16 unit. Any other move gets 400, and nothing is sent. The server stores `demo` by slug, `answers` by slug, and `look` in the room copy, for a reload. It does not store `point`. A `demo` move drops the stored answers of each gate that it does not list as done. A move to another slide drops all stored answers, as `forget` does in the audience.
- `POST /present/at` sends `at` to each room stream after it changes the place.
- Each room stream reads a `Room` queue of 64 events. A `point` that arrives while a `point` waits at the end of the queue replaces it, so the server drops old laser moves. The presenter also sends at most one `point` per animation frame and at most about 30 a second. When the queue is full, the server empties it and closes the stream. `EventSource` connects again and gets a new `state`. An `end` empties the queue and goes in alone, so it is never dropped.
- `/present/events` moves from `app.py` to `presentation.py`. It sends `presentation` `{id}` first, then `audience` `{id, n}` for the live presentation, `presentation-ended` as in Task 3, and `audience` `{id, n}` each time the number of room streams changes. The legacy `state` event leaves.
- The audience page uses only GET routes: the page, the deck, the images, `stage.js`, the rupaka bundle and the room stream. Its script holds no POST.

**Shared renderer** (`slides.js`, loaded by the IDE page in `lee-core.js` and by the audience page as `lee-slides.js`):
- `slidesSafe(html, key) -> DocumentFragment`: parses with `DOMParser`. It keeps only `p, pre, code, span, div, b, i, em, strong, br, hr, h1-h6, table, thead, tbody, tr, th, td, ul, ol, li, img, figure, figcaption, blockquote, sup, sub, del, s, kbd, a`. It keeps `class` except names that start with `lee-`, `stage-` or `rk`, so a notebook cannot cover the slide with Leela's own classes; `width` and `height` on `img`; `href` on `a` when it starts with `http:`, `https:` or `mailto:`, with `target="_blank"` and `rel="noopener noreferrer"`; and `src` on `img` only when it is `data:image/(png|jpeg|gif|webp);base64,` or exactly `/present/img/<64 hex>?k=<key>`. Both windows put every server HTML through it.
- `slidesDraw(el, deck, i, step, {key, size, mount, math})`: draws slide `i` of `deck` into the 1280x720 canvas `el`. `el` is a child of the stage root, so the laser dot and the blank screen of `stage.js` stay on the root when a slide is drawn again. A block with `frag < step` shows. A later block keeps its place and is hidden. A code block shows its source and `out`. Each `pre > code.language-rupaka` becomes a demo through `mount(spec)`. The IDE passes a `mount` built on `rupakaDraw` (`core.js:617-628`). The audience page passes `slidesMount`. `math(el)` fills `span.math` and `div.math`: `renderMath` in the IDE, the vendored KaTeX on the audience page.
- `slidesMount(spec)`: a host with a shadow root, the rupaka CSS from `meta[name="lee-rupaka-css"]` and the slide sizes, and `Rupaka.mount` on an inner element, as `rupakaDraw` does. It returns `{host, inner}`.
- `slidesFit(el) -> {fits}`: shrinks the text of the canvas in steps to the floor (body 20px, code 18px). At the floor it stops, and the slide is cut at the safe margin.
- `slidesTheme(theme, mono)`: sets `data-theme`, `data-mode` and `data-density` on `html` from `family:mode:density`. For `system` mode it follows `matchMedia` and its `change` listener. It sets `--lee-mono` when `mono` is not empty.

**Presenter screen** (`presentNotebook(start)` in `present.js`):
- It shows `Preparing slides…` in the status line, then posts the line from Task 1 and the live cells to `/present/start`. A refusal shows the server's message. For a notebook too large to send, it adds `Clear large outputs, then try again.`
- It sets `html.talk` and opens the root `role="dialog"` with `aria-label="Presentation"`. The root keeps focus.
- The slide fills the space above the strip, scaled from 1280x720. The strip is in the bottom margin and never covers the slide. It holds, in order: previous, next, `N / M`, Run (one button for each code cell of this slide), Audience window, the connection line, Notes, A-, A+, Full screen, and End at the far end. Its text is at least 14px and its buttons at least 32px, in `--lee-*` colours. The strip hides after 3 s with no input, with `opacity` and `transform`, so it stays in the focus order. Pointer movement within 80px of the bottom edge, or focus in the strip, shows it.
- Keys in this task: next (`ArrowRight`, `ArrowDown`, `Space`, `PageDown`), previous (`ArrowLeft`, `ArrowUp`, `Shift+Space`, `PageUp`), `KeyN` (Notes drawer), `KeyF` (full screen) and `Escape` (closes the Notes drawer; it never ends). Space or Enter on a focused strip button presses the button. Task 5 adds the rest of the key map.
- Each move calls `presentMove`, draws the slide and posts `/present/at`. All posts of one presenter go through one promise chain, so the server gets them in order. Right after the start the presenter posts `at` with its stored text size. A 403 or 410 on a post closes the presenter screen with `This presentation has ended.` Any other failure shows `Moves are not reaching the audience window.` The presenter screen opens only after the start returns its key.
- Notes: a drawer that the presenter opens with N or the Notes button. It holds the notes, the next slide's title and the elapsed time. It is closed by default. Nothing on the presenter screen moves when an audience window connects. The drawer says `The room can see these notes when you share this screen.`
- Audience window button: its click handler calls `window.open` with no `await` before it, with the one window name `leela-audience`. A second click focuses the open window and does not open another. A null result keeps the button and shows `The browser blocked the window. Click again.` In the Mac app it calls `openExternal`, which opens the system browser. After the window opens, a one-line hint shows: `Drag this window to the projector, then press F.`
- The connection line says `Audience window: connected` while the server counts one or more room streams, else `Audience window: not connected`. It reads the `audience` event of `/present/events`.
- A-/A+: `presentStep` (`present.js:17`) in tenths, stored per notebook as today, posted to `/present/at` as `size`.
- A theme change in the IDE posts a `look` move, so the audience follows it during the show.
- When the slide does not fit at the floor, the status line says `Slide N has more than fits. Split it or trim it.` At start the presenter measures each slide and names every slide that does not fit.
- End: the first click changes the label to `End now?`. A second click within 3 s posts `/present/end`, removes `html.talk`, and focuses the selected cell, as `closePresentation` does today (`present.js:286`). No recap opens.
- `presentation-ended` on `/present/events` for this presentation's id with `reason: 'replaced'`: the page shows `Another presentation started.` and closes its presenter screen.
- Run (minimal in this task): `runCell(i, false)`, then the presenter screen draws the cell's outputs. Task 7 sends outputs to the room.

**Audience page** (`document.body.dataset.page === 'audience'`):
- It reads `k` (the audience key `ak`) from the address and keeps it there, because a reload asks the server for the page with it. It also keeps it in `sessionStorage`, so a second click on Audience window can tell this window from an old one.
- It fetches `/present/deck?k=`, calls `slidesTheme` with `deck.look`, and opens `EventSource('/present/room?k=')`.
- It calls `abhyasaStage.audience(root, {ch, draw, title})` with a channel object built on the room stream: `on` takes the server events and returns an unsubscribe function, and `send` does nothing. The object turns `at` into the stage messages `go` and `blank`, adds `v: 1`, and drops each message that `abhyasaStage.valid` refuses. Each `state` event resets the whole view: place, blank, size, theme, demo states and answers. The page keeps the latest `demo` and `answers` of each slug and applies them again after each draw. `stage.js` draws the laser dot and the blank screen. `abhyasaStage.mirror(inner)` applies each demo state (`apply`) and the answers (`reveal`). The audience page does not call `abhyasaStage.channel`.
- It has no controls, run buttons, notes, toasts or key help. F or a double-click fills the screen.
- On `end` the page closes its `EventSource`. When the stream fails and the browser does not connect again, the page asks for the deck to tell 403 from 410. `end`, or a 410, shows the end card: the notebook title and `The presentation has ended.` on `--lee-bg`. A 403 shows `This presentation link is not valid.` It never shows an error page.

**Design decisions** (from the review; the owner did not object):
- Nothing moves when the audience window connects. Notes, the next slide title and the clock are in a drawer that the presenter opens with N or the Notes button.
- Full screen comes back: a button and the F key.
- End is at the far end of the strip and needs a second click within 3 s.
- The strip: text at least 14px, buttons at least 32px, Leela's colours, in the bottom margin, hidden when idle. Space on a focused button presses the button.
- One audience window name; a second click focuses it. The hint `Drag this window to the projector, then press F.` shows after it opens.
- The end card is calm. The audience page follows theme changes during the show.
- An output type that the room cannot show appears as `This output type is not shown in presentations.` The server writes it in both copies (`NOT_SHOWN` in `show.py`) for an output with no type that the room shows.
- `Preparing slides…` while the server builds the deck. A notebook too large gets the message to clear large outputs. A slide too long at the floor is named to the presenter at start.
- Leela's themes and fonts everywhere. Output and code are 24px on the slide, not under half the body size.

- [ ] **Step 1: Write the failing tests, and change today's tests on purpose**
  - Fast, `tests/test_present_routes.py`: `test_presenter_moves_reach_the_room_and_a_reload_gets_the_state` (the first event is `state` at the start place; `/present/at` and `/present/move` give `at`, `demo`, `answers` and `look`; a second stream gets all of them in its `state`); `test_the_room_stream_refuses_bad_keys_with_no_state` (missing, wrong and old keys get 403; after end, 410; no `state` event); `test_the_audience_cannot_post` (POST to the room stream, the deck, the page and an image gets 405; `lee-slides.js` holds no POST and names no presenter route); `test_laser_moves_are_coalesced` (a `Room` queue keeps one waiting `point` at its end and keeps the order of other events; the route relays the last point); `test_a_bad_move_sends_nothing` (an unknown `t`, an extra field, a point outside 0..1, a `demo` with a bad slug, a move over 65536: 400 and no event); `test_end_and_replace_send_end_without_the_key`; `test_the_audience_count_follows_the_room_streams`; `test_the_audience_key_reads_and_never_moves` (`ak` reads the page, the deck, an image and the room stream, and gets 403 on every mutation; no copy holds `key`). Add `/present/move` to `MUTATIONS`. Change `test_a_presentation_starts_from_the_live_cells_and_writes_nothing` on purpose: `audience` and the image URLs hold `ak`, not `key`.
  - Fast, `tests/test_present_room.py`: `test_an_output_the_room_cannot_show_says_so`.
  - Change `test_rise_settings_reach_reveal_by_name_and_nothing_else_does` to `test_rise_settings_keep_only_the_start`, because the reveal options and `rise.theme` are dropped (decision 6).
  - Remove `test_the_notes_page_follows_the_deck_and_says_when_it_has_ended`, because the notes page and its routes are dropped.
  - Change the packaging tests: the builds and the wheel carry `present-audience.html`, `lee-slides.css` and `lee-slides.js`, and no `leela/vendor/reveal/` or `present-notes.html`.
  - Change `test_reveal_themes_fetch_no_web_fonts` (`tests/test_md_output_font.py:90-95`) to `test_slides_fetch_no_web_fonts`, because `leela/vendor/reveal/` is deleted.
  - Change `test_audience_page_headers` to expect `lee-hl.css` after `lee-slides.css`, because code on a slide needs the highlight colours.
  - Slow, rewrite the main test on purpose: `.lee-present[data-ready]`; one line of 5 slides; the unsaved edit, the image from `/present/img/`, the markdown output, and no notes or skipped text on the slide; the Notes drawer shows the notes and the next title; Run shows `tick 2`; the palette chord opens nothing; End twice closes and focuses the selected cell; the IDE styles do not change; two quick starts leave one `.lee-present`; the not-a-notebook message stays. It waits for the notebook's reply buttons with `wait_for_function` before it counts them (the count raced on main).
  - Slow, replace the long-slide and align tests with `test_a_long_slide_shrinks_to_the_floor_and_text_is_left`: the overflow line names slide 1; A+ twice gives `text 120%`; the floor and ceiling messages stay `text 50%` and `text 250%`; headings and body are left-aligned.
  - Slow, `test_the_audience_window_follows`: the popup opens with `context.wait_for_event('page')`; the hint shows; the strip says connected; both windows draw the same slide markup; ArrowRight shows the fragment in the audience; a theme change in the IDE changes the audience; the walker cases of `test_audience_walker_drops_what_the_server_missed` run on the audience page; a second click with the window open focuses it; closing the popup makes the strip say not connected; with `window.open` returning null the button stays and the blocked line shows; End twice shows the end card in the audience. It saves light and dark screenshots of both windows to `target/present-shots/`.
  - Slow, `test_a_demo_in_the_room_has_no_answers_and_shows_the_verdict`: the room copy mounts the demo with no answer in its shadow root and with its gate `inert`; a `demo` move with the presenter's pick and then an `answers` move show the verdict.
  - Slow, `test_an_output_the_room_cannot_show_says_so_on_the_slide`.

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_present.py tests/test_present_room.py tests/test_present_routes.py tests/test_md_output_font.py -q && uv run pytest tests/test_present_slow.py -m slow -p no:xdist -o addopts=`
Expected: FAIL (404 on `/present/room`; `riseConfig` still returns reveal options; no `lee-slides.js`).

- [ ] **Step 3: Implement** as above. Run `uv run python tools/build_ide_js.py` after each JS edit.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run python tools/build_ide_js.py --check && uv run pytest tests/test_present.py tests/test_present_room.py tests/test_present_routes.py tests/test_abhyasa_contract.py tests/test_web.py -q && uv run pytest -q -n 6 --ignore-glob='*_slow.py' && uv run pytest tests/test_present_slow.py -m slow -p no:xdist -o addopts=`
Expected: PASS.

- As built (Task 4), where it departs from the lines above or from the review file:
  - Two keys, not one. The review file names one per-session key. With one key the audience page held the presenter's key, so it could post moves; the teacher review of this task found that this broke the owner's "the audience window can never send presenter commands". `ak` is the audience key; `key` alone moves. `test_a_presentation_starts_from_the_live_cells_and_writes_nothing` changed on purpose for it.
  - An ended presentation answers 410 on the room stream, not 404, as Task 3's `check` does for every keyed route.
  - The audience key stays in the address bar. Task 3's note planned to remove it with `history.replaceState`, but `GET /present/audience` needs `k`, so a reload without it got 403 (found by `test_a_demo_in_the_room_has_no_answers_and_shows_the_verdict`).
  - The presenter does not mirror its own demos yet. The room side (`room_spec` copies, `mirror.apply`, `reveal`, the stored state at reload) and the `demo` and `answers` moves are built and tested by posting moves. The presenter's `mirror.watch` and the `answers` on reveal stay in Task 7, which also loads `stage.js` on the IDE page.
  - Laser (`KeyX`) and blank (`KeyB`) are not bound yet: the routes, the coalescing and the audience drawing are built; Task 5 binds the keys.
  - Run in the strip draws the outputs on the presenter screen only. The room keeps the deck's outputs until Task 7.
  - Run saves a notebook with unsaved edits before it runs (`leela/blocks/nb/motion.js:94`). This is Leela's behaviour before this plan, and it conflicts with decision 1 ("a presentation writes no file") once a cell runs. The slow test checks that nothing is written up to the first Run. The owner decides whether Run in a presentation skips that save (Task 7).
  - `leela/vendor/README` had no reveal.js rows, so it did not change.
  - The design screenshots are in `target/present-shots/` (gitignored), written by `test_the_audience_window_follows` and `test_a_demo_in_the_room_has_no_answers_and_shows_the_verdict`.

**Risks:** the audience page loads all of `lee-ide.css`; a body rule there can reach the audience page. The audience key is a bearer capability in the audience URL: whoever holds it can read the room copy and the room stream, but cannot move the presentation. In the Mac app the system browser keeps the audience URL, with the key, in its history. A one-screen projection shows whatever the presenter opens, the Notes drawer included; the drawer says so. Each audience window holds one HTTP connection open for the room stream.

- As built (design pass), from the design review of 29 October (`answer_854bf101c382.txt`), on `1c3ba06`:
  - The hint is `Move the audience window to the projector. In that window, press F for full screen.` It shows on the presenter screen only. It replaces `Drag this window to the projector, then press F.` in the lines above.
  - The slide and the Notes drawer share one row (`.lee-present-main`). The drawer is `min(340px, 35vw)` wide. Opening it sets `lee-notes-open` on the presenter root, and `slidesScale` scales the preview into the space that is left. The drawer covers no part of the slide. The audience canvas does not change.
  - The drawer has the heading `Speaker notes` and a Close button. Notes has `aria-controls` and `aria-expanded`. N, Notes, Close and Esc set all three through one function. Close moves focus back to Notes. Space or Enter on a focused drawer button presses the button. The open Notes button uses `--lee-sel` and `--lee-selection-fg`. The privacy line is separated by a `--lee-border` rule in `--lee-fg2`. The next title and the clock are 16px, the clock with tabular numbers. The notes stay 18px.
  - Previous is disabled at the first step of the first slide. Next is disabled at the last step of the last slide. A focused button that becomes disabled gives focus to the presenter root. When a slide has fragment groups, the counter adds ` · step n / m`, with `m` one more than the groups. The audience slide shows no count.
  - The strip has three groups with 16px between them: Previous, Next, the count and Run; Audience window and the connection line; Notes, A-, the text size and A+, and Full screen. End is at the far end and is red. The strip wraps to a second row instead of clipping, with `min-height: 56px`. The drawer and the message sit above the strip in the same layout, so a second row covers nothing. The pointer wake zone is the strip height plus 24px, at least 80px. Notes, A-, A+ and Full screen are transparent until hover, which shows `--lee-bg2` and `--lee-border`.
  - `Text N px` beside A- and A+ is the body size after the A-/A+ step and the fit, on the 1280x720 canvas. It is not a promise of what the back row can read.
  - Decision 4 wins over the review on the connection line. The review asked for `Connected` and `Not connected`. Decision 4 names `Audience window: connected` and `Audience window: not connected`, so that text stays.
  - Demos on a slide take the slide's body size, in both windows. `SLIDES_RK` sets the rupaka sizes and Leela's colours, and `slidesRk` adds it after the sheets of the shadow root. The presenter adds it to the `rupakaDraw` mount when `done` settles. The room copy also hides `kbd` labels and an empty explanation box (`lee-empty`, set after each mirror apply), and shows a filled one as text. The vendored `lee-rupaka.css` did not change. The presenter still does not mirror its demos to the room; that stays in Task 7.
  - The end card has `The presentation has ended.` as its 44px heading and the notebook name without `.ipynb` under it at 28px. The review asked for the heading `Presentation ended`. The lines above name the sentence `The presentation has ended.`, and the slow test checks it, so the sentence is the heading. The stored path does not change. The blank screen and the window title use the same name.
  - Laser, blank and the private error panel get no layout in this pass. Task 5 binds the keys and Task 7 builds the panel.
  - The measure canvas at start draws without demos, so a slide that is long only because of a demo is not named at start. The live draw still names it.
  - Tests: `test_a_notebook_presents_as_slides_and_leaves_the_ide_as_it_found_it` checks the ends, the counter and the drawer state; `test_the_audience_window_follows` checks the hint, the drawer room, the audience canvas and the strip at 1024px and 720px; `test_a_demo_in_the_room_has_no_answers_and_shows_the_verdict` checks the demo sizes in both windows. The screenshots in `target/present-shots/` now include `presenter-demo-light.png` and `presenter-narrow-1024.png`.

---

### Task 5: One key scope

Goal: every key in the key map does what the table says, and no stray key ends the presentation.

**Files:**
- Modify: `leela/blocks/nb/present.js` (the `keys` object, the Esc order, the old `p.onKey` at `:237-240` removed)
- Modify: `leela/core/keys.py` (a "Present" group of display rows; no new global binding)
- Test: `tests/test_present.py`, `tests/test_present_slow.py`

**Interfaces:**
- `keys` as the key map says. Next and back call `presentMove` (Task 1) and post `/present/at`; the server sends `at` to the room (Task 4).
- `Escape` returns false when a `.lee-modal` is open, so the dialog's own handler takes it. Otherwise it closes the first open thing in the key map order and returns true. With nothing open it returns true and does nothing.
- `KeyX` toggles the laser. While it is on, pointer movement over the slide posts `point` moves to `/present/move`, at most one per animation frame, and leaving the slide posts `{off: true}` (the rules of `stage.js:182-192`). `KeyB` toggles blank and posts `/present/at`.

- [ ] **Step 1: Write the failing tests**
  - Fast: `test_present_keys_are_listed`: the "Present" rows in `KEYS` name every key in the `keys` object of `present.js` (read as text, as `test_keys.py` does for the Graph); `_dupes(DEFAULTS) == []`; `test_present_is_one_action_with_the_same_name_everywhere_it_appears` (`test_present.py:99-116`) stays green.
  - Slow, `test_esc_never_ends_the_presentation`: press Esc with the error panel open (it closes), with Notes open on one screen (it closes), with the laser on (it goes off), in a demo (focus leaves the demo), in fullscreen (fullscreen ends), with a `.lee-modal` open (the dialog closes), and with nothing open. After each, `.lee-present` is there and `/present/deck` answers. Then Alt+R, Alt+W, Alt+T, `/` and the palette chord: the presenter screen is still there and no tab or palette opened.
  - Slow, `test_clicker_keys`: PageDown, PageUp, Space, Shift+Space and the four arrows move one step each; a held key moves once.

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_present.py -q -k keys && uv run pytest tests/test_present_slow.py -q -m slow -k "esc or clicker"`
Expected: FAIL.

- [ ] **Step 3: Implement.** Audit first: `keys.py`, `keymap.js`, the palette and `menus.py`, as `AGENTS.md` asks. Write the audit result in the commit body.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run python tools/build_ide_js.py && uv run pytest tests/test_present.py tests/test_keys.py -q && uv run pytest -q -x --ignore-glob='*_slow.py' && uv run pytest tests/test_present_slow.py -q -m slow`
Expected: PASS.

**Risks:** a clicker that sends `.` or `F5` for blank or start does nothing. Space on a focused strip button presses the button and does not move (Task 4).

- As built (Task 5), from the teacher review of this task (`answer_1a8b3c935865.txt`), where it departs from the lines above:
  - The key map is the table above plus `KeyN` (Notes) and `KeyF` (full screen on or off; F leaves full screen too). A key is its `e.code` with `Shift+` before it, so `code: KeyB, key: x` blanks and Shift+B does nothing.
  - `present.js` ignores a key with Cmd, Ctrl, Alt or AltGraph, a key while `isComposing`, and `key: Process`. It never calls `preventDefault` on them, so Cmd or Ctrl with W, R or L stays with the browser.
  - A key in a text field (input, textarea, select, contenteditable, also inside a shadow root) or in a demo does not navigate. Esc still reaches the presenter there. Esc in a field or a demo moves focus to the presenter root when nothing before it in the order is open.
  - Space or Enter on a focused button presses only the button. A held Space or Enter on a button gets `preventDefault` on each repeat, so the button fires once. A held key moves once.
  - Each key function gets the event. A function that gives false lets the key go on. Esc gives false while a `.lee-modal` is open or while the page is in full screen, so the dialog and the browser take it. Esc within 400 ms after full screen ends does nothing (`fullscreenchange` records the time). Otherwise Esc closes the first open thing: Notes, then the laser, then demo or field focus. With nothing open it does nothing. The error panel is Task 7.
  - Focus stays in the presentation. At open, every other child of `body` gets `inert`, and a `focusin` outside the presenter root (not in a `.lee-modal`) puts focus back on the root. A dialog opened later is not inert. Close removes `inert` before it focuses the selected cell.
  - The non-modal Escape handlers on `document` in the capture phase do nothing while a presentation is open: `focus.js` (selection reply), `cells.js` (inline popover), `terminal.js` (pane full screen, unpinned pane) and `agent/panel.js` (open disclosures). The `.lee-modal` handler in `overlays.js` does not change. The audit found no other document Escape handler that can act under a presentation: `learn/pane.js` listens only in pane pages, and the gutter popup belongs to a file tab.
  - Laser: X toggles it. A point is the pointer position on the scaled `.lee-slide`, clamped to 0..1 and rounded to 4 places; a zero-size slide sends nothing. The newest point waits; at most one point is in the post chain and at most one goes in 33 ms, so slow replies queue nothing behind them and keep their order with `at` and `off`. Pointer leave, pointer cancel, toggle off, Esc, window blur and blank cancel the waiting frame first, then send `{off: true}` when a point went out. End and replacement cancel the frame and send nothing more. Points never block demo pointer input. The pointer is hidden over the presenter slide while the laser is on.
  - Blank: B toggles it and posts `/present/at`. The presenter canvas has its own `.stage-blank` (the notebook name) and `.stage-dot`, so both windows show blank and the dot. `.lee-slide.blank .stage-dot` is hidden in both windows, and blank sends `{off: true}` and stops points until it ends. The presenter dot fades after 1500 ms as the audience dot does.
  - The audience page switches the dot off on each `state` event before it sets blank and draws, so a reconnect never keeps an old dot. The server still stores blank in `at` and never stores a point (`test_a_room_that_connects_again_gets_blank_and_no_laser`).
  - The keys help shows a `present` section from `PRESENT_KEYS` in `keys.py`, through `help_rows`. These rows are not `Key` rows and not bindings, and the palette does not list them, because the palette runs the actions it lists. The help page still says that every key in it can be rebound; that sentence is not true for the `present` section.
  - Tests: `test_present_keys_are_listed_and_bind_nothing` (fast, compares the names in `p.keys` with `PRESENT_KEYS`), `test_clicker_keys`, `test_esc_never_ends_the_presentation` and `test_laser_and_blank_reach_both_windows` (slow). The reconnect check closes the audience `EventSource` and fires its `error`, so the page's own retry runs within the 1500 ms fade.

---

### Task 6: Place, output and demo recovery

Goal: a reload of the IDE page or of the audience window comes back at the same slide and step, with the same output and demo state.

**Files:**
- Modify: `leela/blocks/nb/presentation.py` (`POST /present/resume`), `leela/blocks/nb/present.js` (resume on tab load; `localStorage['lee-present:<path>'] = key`), `tests/routes.txt`. There is no replay on `hello`: the room stream sends the server's state at connect (Task 4).
- Test: `tests/test_present_routes.py`, `tests/test_present_slow.py`

**Interfaces:**
- `POST /present/resume` `{k}`: `check(k)`, then returns `{ok, key, id, presenter, at, live, look}` from the server's state. It makes no new key.
- On a notebook tab load, when `localStorage` holds a key for this path: `POST /present/resume`. On 200 the presenter screen comes back at `at` with the same key, so an open audience window keeps working. On 403 or 410 the page removes the entry. When no presentation is live at all, the page offers "Present again from slide N" (a new key; the audience window must open again). When another presentation is live, the page offers nothing and touches nothing.
- A reloaded audience window gets the server's state as the first event of `GET /present/room` (Task 4); Task 7 adds the last output of each cell to it. The presenter sends nothing for it. A reloaded presenter reads `live` from `/present/resume` and draws the same demo states and outputs.

- [ ] **Step 1: Write the failing tests**
  - Fast: `test_resume_returns_the_presentation_without_a_new_key`: start, move to s2 step 1, resume: same key, same `at`; a wrong key 403; after a second start, the first key 403. Add `/present/resume` to `MUTATIONS`.
  - Slow, `test_reload_keeps_the_place`: go to s2 step 1; reload the audience page and wait for s2 step 1 (the key comes from `sessionStorage`); reload the IDE page, wait for the presenter screen at s2 step 1, press ArrowRight, and see the audience follow without opening it again.
  - Slow, `test_reload_mid_run`: run the `tick` cell (`test_present_slow.py:23`); reload the audience page during the run and see the latest output; reload the IDE page after the run and see the same output in both windows.
  - Slow, `test_stale_entry_while_another_presentation_is_live`: write an old key for notebook A, start from notebook B in another page, open A: no presenter screen, the entry is gone, and B is still live at its place.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_present_routes.py -q -k resume && uv run pytest tests/test_present_slow.py -q -m slow -k "reload or stale_entry"`
Expected: FAIL (404 on `/present/resume`).

- [ ] **Step 3: Implement** as the interfaces say.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run python tools/build_ide_js.py && uv run pytest tests/test_present_routes.py -q && uv run pytest -q -x --ignore-glob='*_slow.py' && uv run pytest tests/test_present_slow.py -q -m slow`
Expected: PASS.

**Risks:** the key in `localStorage` is readable by any script on the origin. Same-origin script can already read the deck, so the key adds no reach on this machine. A server restart loses the presentation; the page then offers a new start.

- As built (Task 6), from the teacher review of this task (`answer_1844205d8e21.txt`), where it departs from the lines above:
  - The record is per browser tab. `sessionStorage['lee-present:<id>']` holds `{key, boot, path, at}`, keyed by the presentation id, not by the notebook path. `at` is the last place the server acknowledged: the reply to `/present/at`, not a move still in the post chain. `localStorage` holds no presenter key. `history.state.leePresent` holds `{id, path, at}` without the key, so a tab whose storage was cleared can tell that it lost its key.
  - `POST /present/resume` `{k}` takes the presenter key only. It returns the same object as `/present/start`: `key`, `ak`, `id`, `boot`, `holder`, `presenter`, `at`, `look`, `live`, `src` (the source of each code cell on a slide), `title`, `audience` and `elapsed`. It changes no place, look, demo state or room stream. It sets a new `holder` and sends `presenter` `{id, holder}` on `/present/events`. No event holds a key.
  - `/present/events` sends `presentation` `{id, boot, holder}` first. `test_a_second_start_ends_the_first` and `test_the_audience_count_follows_the_room_streams` changed on purpose for it. `Presentation.boot` is new for each server. `/present/deck` and every 410 send it in `X-Leela-Boot`, so a window can tell a restart from an end.
  - `presentResume` runs at page load, after the theme step of `boot`. A reload of the tab that holds a record resumes. A tab that holds a record but did not reload (a window that the browser copied the storage into, a duplicated tab, back and forward) shows `Present from this tab?` with Take over. Take over resumes, and the old tab closes with `The presentation moved to another tab.` A new IDE tab has no record and gets nothing. A tab with the history entry and no record shows `This tab lost its presenter key` with Start again while that presentation is live. The audience page deletes any copied record from its own storage.
  - `presentOpen(r, fresh, path)` draws the server's place, blank, text size, look and clock, and navigates by the stored deck: `p.line` comes from `presenter.slides[].groups`, never from the live cells. Blank is set before the first draw. A resumed presenter posts nothing until the presenter acts. The theme observer posts a `look` only when the IDE theme changes from the theme at open, so the look the server holds survives a reload.
  - Each connect of the presenter's `/present/events` reconciles: another id closes the presenter screen with `Another presentation started.`; another holder closes it with `The presentation moved to another tab.`; a null id closes it and asks `/present/resume` once. Only a 410 from that request offers Start again (`Leela restarted` when the boot changed, else `The presentation has ended`). A network failure offers nothing and keeps the record for a reload. A 410 on a post takes the same path. Closing drops the queued posts, because `presentPost` sends nothing for a closed presenter. A closed stream opens again after 1 s, doubling to 15 s.
  - Start again opens the stored notebook first when another tab is active, then starts a new presentation from the live cells at the stored place (`presentNotebook` takes `{slide, step}`, clamped by `presentNear`). The audience window must open again.
  - The audience page keeps one room stream and one retry at a time. Only a 403 is a bad link and only a 410 is the end. Any other deck failure, a 503 included, asks again after 1 s, doubling to 15 s. Nothing connects after the end. A 410 with a new boot adds `Leela restarted. The presenter can start again.` under `The presentation has ended.`
  - A closed or renamed notebook does not stop the show: the presenter screen comes back from the stored deck. `presentStale(p, id)` says when a code cell is gone from the open notebook or differs from `src`. Task 7 disables Run with it.
  - Moved to Task 7, which produces this state: presenter demo mirroring and gate hydration (the resume returns `live.demo` and `live.answers`; the presenter does not apply them yet), and output recovery during a run. The review asks Task 7 to send output from the server's run owner (`/nb/run/state`, `nb/app.py`), not from the presenter page, so a presenter reload during a run loses no output. `test_reload_mid_run` moves to Task 7.
  - Files: `nb/presentation.py`, `nb/present.js`, `nb/slides.js`, `static/js/boot.js`, the bundles, `tests/routes.txt`, `tests/test_present.py`, `tests/test_present_routes.py` and `tests/test_present_slow.py`. `nb/app.py` and `nb/show.py` did not change.
  - Tests: fast `test_resume_returns_the_servers_state_without_a_new_key_and_writes_nothing`, `test_the_deck_names_the_servers_boot_so_a_window_can_tell_a_restart`, `test_a_resume_tells_the_other_pages_who_holds_the_presenter_screen`, `test_run_knows_when_a_cell_no_longer_matches_the_stored_deck`, and `/present/resume` in `MUTATIONS`. Slow `test_a_reloaded_presenter_comes_back_as_the_server_holds_it` (mid-beat, blank, size and look that the presenter never drew, a notebook changed on disk, no post before the first key, no unblanked frame in either window, the audience reloaded with its storage cleared), `test_another_tab_gets_presenter_control_only_by_taking_over`, `test_a_stale_presenter_closes_on_reconnect_when_it_missed_the_end` (also a stale record at reload), `test_reconnect_storms_keep_one_audience_connection`, `test_a_lost_presenter_key_says_so_and_offers_a_deliberate_restart` and `test_a_server_restart_says_so_in_both_windows`. The restart test stops its own uvicorn server on its own free port and starts a new one there.

---

### Task 7: Live code, demos, private errors and Show error

Goal: Run and Stop sit beside each code cell of the slide in the presenter controls. Output updates live in place on both screens. A failed run keeps the room's last good output and shows the error privately. A rupaka demo is mirrored to the audience copy with no answer before reveal.

**Files:**
- Modify: `leela/blocks/nb/present.js:137-148` (`presentRun` reworked: a generation per run, a sequence per output event, Run and Stop in the strip, the error panel) and the `lee-cell-output` listener that replaces `onOutput` (`:241-243`)
- Modify: `leela/blocks/nb/slides.js` (`out` drawing; demo mirror in the presenter window; Task 4 built the audience side)
- Modify: `leela/static/js/core.js:617-628` (`rupakaDraw` keeps the inner mount element on its entry, so `abhyasaStage.mirror` can address it)
- Modify: `leela/blocks/editor/mount.js:493` (`markPreviousRuns` dispatches `lee-kernel-restart`), `leela/blocks/runtime/kernel.js:35` (the reconnect button calls `markPreviousRuns`)
- Modify: `leela/blocks/nb/presentation.py` (`POST /present/out`, `POST /present/show-error`; each stores the output in `live.outs`, sends `out` on the room stream and adds it to the `state` event), `leela/blocks/nb/show.py`, `leela/static/lee-slides.css` (error panel), `leela/app.py` (the IDE head loads `/present/stage.js` for `abhyasaStage.mirror` only; no channel), `tests/routes.txt`
- Test: `tests/test_present_routes.py`, `tests/test_present.py`, `tests/test_present_slow.py`

**Interfaces:**
- `POST /present/out` `{k, cell, gen, seq, outputs, done, ok}`: `check(k)`; 400 when `cell` is not a code cell of a visible slide; `{stale: true}` when `(gen, seq)` is not newer than `live.outs[cell]`; else `clean_out`, `images.update`, `clip_msg`, store in `live.outs`, and return `{msg, error}`. `msg` is the `cellout` for the room. `error` goes to the presenter only.
- `POST /present/show-error` `{k, cell, gen}`: builds a `cellout` whose `html` is the room output plus the error as escaped text in a `pre`, stores it, returns `{msg}`. 400 when that run has no error.
- Demo state goes through `POST /present/move` `{t: 'demo'}` (Task 4), not a route of its own.
- The presenter posts `/present/out` only for a reply whose key is current and whose `(gen, seq)` is the newest for the cell, at most once per animation frame per cell. The server sends `out` `{cell, gen, seq, html}` to the room.
- Run: `runCell(i, false)` as today (`present.js:142`). Stop: shown while a run is active; posts `/kernel/interrupt`, as `actions.js:37-38` does.
- Error panel: in the presenter controls, outside the slide preview. A `--lee-red` left border, the summary `<ename>: <evalue>`, a `<details>` with the traceback, and a "Show error" button. Esc closes it.
- Kernel restart: on `lee-kernel-restart`, the presenter clears each output box, posts an empty output with a new `gen` for each cell in `live.outs`, and enables Run.
- Demos: the presenter mounts each spec with answers through `rupakaDraw`, calls `abhyasaStage.mirror(inner).watch`, and posts each snapshot as a `demo` move. A gate pick in a slide is not filed, because `lessonPredict` returns outside `.lee-cell[data-id]` (`lesson.js:69-70`). The audience side (`room_spec` copies, `mirror(inner).apply`, `reveal`) is built in Task 4. After the presenter reveals, the presenter posts `answers` from `mirror.answers()` as an `answers` move. A snapshot over 65536 is not sent and not stored; the status line says `The demo is too large for the room screen.`

- [ ] **Step 1: Write the failing tests**
  - Fast: `test_out_only_for_visible_code_cells_in_order`: posting for `m1` (notes) and an unknown id gives 400; `gen=1, seq=2` then `gen=1, seq=1` gives `{stale: true}`; `gen=2, seq=1` is stored, sent as `out` on the room stream, and in the next `state`; a stale key 403. Add `/present/out` and `/present/show-error` to `MUTATIONS`.
  - Fast: `test_a_failed_run_keeps_the_error_private`: outputs with a stream and an error give a `msg` with the stream and no `ZeroDivisionError`, and an `error` with it; `/present/show-error` then gives a `msg` with the escaped traceback; a run with no error gives 400 there.
  - Fast: `test_outputs_load_by_hash`: an `image/png` output is then served at `/present/img/<sha>?k=`.
  - Fast (node): `test_stage_messages_never_carry_an_answer`: the move builders in `present.js` on a slide whose demo gate answer is `ANSWER-7731` give `demo` moves with no `ANSWER-7731`, and `abhyasaStage.valid` passes each one.
  - Slow, `test_a_run_streams_to_the_audience`: Run on the `tick` cell shows `tick 2` on the audience page; `1/0` shows the private panel with `ZeroDivisionError` and the audience shows no traceback; Show error sends it; a cell that prints `<script>window.hit=1</script>` as `text/html` leaves `window.hit` undefined on the audience page; 200 small images and 300 kB of `"<\\` text show with the too-long line and no channel error.
  - Slow, `test_overlapping_runs`: run a slow cell twice before the first finishes; the audience shows only the second run's output.
  - Slow, `test_stop_and_restart`: run `while True: pass`, press Stop, see `KeyboardInterrupt` in the panel; run a cell, restart the kernel from the Kernel menu; both screens clear the output and Run is enabled.
  - Slow, `test_a_demo_is_mirrored`: moving the presenter's slider changes the audience copy's state; the audience gate is `inert`; no `/lesson/predict` request is made after a gate pick; a snapshot over 65536 shows the status line and the audience keeps the last state.

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_present_routes.py tests/test_present.py -q -k "out_ or error or by_hash or answer" && uv run pytest tests/test_present_slow.py -q -m slow -k "streams or overlapping or stop or mirrored"`
Expected: FAIL.

- [ ] **Step 3: Implement** as the interfaces say.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run python tools/build_ide_js.py && uv run pytest tests/test_present.py tests/test_present_room.py tests/test_present_routes.py -q && uv run pytest -q -x --ignore-glob='*_slow.py' && uv run pytest tests/test_present_slow.py tests/test_rupaka_slow.py -q -m slow`
Expected: PASS.

**Risks:** running a cell writes its outputs into the editor's copy of the notebook, as today (`present.js:142,146`); the presentation calls no save route, and `test_a_presentation_writes_nothing` checks the file. On one screen the error panel is visible to the room while it is open. A cell with side effects runs in front of the room.

- As built (Task 7), from the teacher review of this task (`answer_674e90e869a1.txt`), where it departs from the lines above:
  - Run writes no file (decision 1). `runCell(i, advance, {save: false})` skips the save before the run and the save after it. It sends `save: false`, and `/nb/run/stream` then skips `initialize_notebook` and `initialize_empty_notebooks`. Ordinary Run does not change. `autoSaveMode()` in `cells.js` is `off` while `lee.present` is set, so the delay, focus and window autosaves do nothing during a show; the setting does not change. Opening the presenter screen cancels a waiting autosave, and closing it schedules one again for a dirty tab. Files that the user's code writes are not covered.
  - Run and Stop sit beside each code cell of the slide. Stop shows while the cell runs and Run is off then. Both come from `p.runs`, so a redraw keeps them. Stop uses the exact-cell path (`stopCell`, `/nb/interrupt`), not `/kernel/interrupt`. Run is off, with a title that says why, while `presentStale` is true.
  - One generation `gen` for each run, counted for the whole presentation, and one `seq` for each post of a run. A run first posts an empty output with `done: false`, so the room clears and the server holds the new run as the last one. Snapshots of one cell coalesce: one `/present/out` of a cell is in the post chain at a time, and only the newest waiting one goes next (`presentLatest`).
  - `POST /present/out` takes any code cell of the deck (`cur['src']`), not only the visible slide. It refuses unknown fields, a `gen` below 1, a `seq` below 0, a non-boolean `done`, more than 2,000 outputs and a body over 16 MB (`MOST_RUN`). It cleans with `clean_out` into the live image store, so the store's quota holds and an image over it falls back to its text. It clips with `clip_msg`, stores the output even with no audience window, and returns `{msg, error}`. The room `state` holds `outs`, the latest output of each code cell.
  - A failed run sends the room its other outputs, possibly none. The private panel shows `ename: evalue`, the traceback in a `<details>` and Show error. `POST /present/show-error` `{k, cell, gen}` answers `{stale: true}` when the server holds a newer run of the cell, and 400 when that run has no error. It adds 1 to `seq`, so the audience takes it. A new run of the cell closes the panel. Esc closes the panel first.
  - `POST /present/clear` `{k, gen}` is new. A kernel restart (`markPreviousRuns`, which every restart path calls, the kernel dialog's Restart kernel now too) and a Stop that restarts the kernel by force dispatch `lee-kernel-restart`. The presenter raises its floor `gen`, empties every code cell of the deck on both screens, its first outputs too, and closes the error panel. Callbacks of older runs then send nothing. Output of a run that a normal interrupt stopped stays valid.
  - A kernel that dies during a run is not seen: kunda's `alive` reads `km.has_kernel`, which stays true after the process exits, so the run waits (`os._exit(1)` waited over 90 s in a probe). Stop then restarts the kernel by force, and the clear above follows. A run that kunda settles with no count and no error also clears. The kunda fix is to check that the process is alive in `Kernel.alive` or `_wait`.
  - kunda reports no `clear_output` to `on_output` during a run (`kunda/kernel.py:300-303`), so the room can show old lines until the run ends. The final snapshot replaces the room output. The kunda fix is to call `on_output` with the clear, for `wait=False` and `wait=True`. Leela now applies it (Task 8): the receiver in `Notebook.run` empties `c.outputs` and its display-id index on a `clear_output` event, so `/nb/run/stream` and the presenter's `/present/out` post the list without the cleared output. Only the kunda 0.0.10 release remains; 0.0.9 is installed.
  - A presenter reload during a run reads each output with `done: false` from `/present/resume`, waits on `/nb/run/state` (`settleRun`) and posts the final outputs as the same run. A reloaded presenter shows the newest private error that the room has not seen.
  - Both windows draw the server's room copy of run output (`slidesDraw` `outs`, `slidesOut`). A widget with `text/plain` shows that text; a widget alone shows `NOT_SHOWN`.
  - Demos: `rupakaDraw` keeps `inner`. The presenter mounts each deck demo through it, waits for `done`, adds one `abhyasaStage.mirror(inner).watch` for each mount, and sends a first snapshot when it differs from the server's. Answers go in their own move after the post of the snapshot that holds the gate as done, never from `rk-predict`. The IDE head loads `/present/stage.js`. Try another sends a snapshot with the gate open; the server and now the audience page drop the answers of that gate. After a reload the presenter applies `live.demo` to its own copy with `Rupaka.set` and `Rupaka.settle`, keeps it writable, and counts a settled gate as done while it stays closed (`d.kept`), because the mirror does not count a gate settled that way. A demo that a run's output shows is drawn from the room copy in both windows and is not mirrored.
  - Not built: the slow check for a demo snapshot over 65536 units (the node test checks the move builder), and the overlapping-run test, because Run is off while the cell runs.
  - Files: `nb/app.py`, `nb/motion.js`, `nb/cells.js`, `nb/present.js`, `nb/slides.js`, `nb/presentation.py`, `nb/show.py`, `editor/mount.js`, `runtime/kernel.js`, `static/js/core.js`, `static/lee-slides.css`, `leela/app.py`, the bundles, `tests/routes.txt` and the three present test files. Changed on purpose: `test_a_room_that_connects_again_gets_blank_and_no_laser` (the state has `outs`) and the main slow test (the error is in the panel; no write after two runs).
  - Tests: fast `test_output_goes_to_any_code_cell_of_the_deck_in_order_and_a_reload_gets_it`, `test_a_failed_run_keeps_the_error_private_until_show_error_for_that_run`, `test_a_kernel_restart_clears_every_code_cell_and_every_private_error`, `test_run_images_go_to_the_live_store_within_its_quota`, `test_a_run_in_a_presentation_initialises_no_placeholder`, `test_stage_messages_never_carry_an_answer`, `test_streamed_output_coalesces_so_no_old_snapshot_waits_in_the_post_chain`, and the three routes in `MUTATIONS`. Slow `test_a_run_in_a_presentation_writes_no_file_and_streams_to_the_room`, `test_a_zero_byte_notebook_runs_in_a_presentation_and_stays_zero_bytes`, `test_stop_show_error_restart_and_a_dead_kernel`, `test_output_for_another_slide_and_every_reconnect_get_the_latest` (it replaces `test_reload_mid_run`) and `test_a_demo_is_mirrored_and_its_answers_follow_the_settle`.

---

### Task 8: "Present a notebook" guide

Goal: one short guide tells a user how to present.

**Files:**
- Create: `docs/present.md` (select a cell; Alt+R or Present; arrows, Space, Page Down; Audience window for a projector and private notes; Run, Stop, Show error; Esc and End; RISE cell types and the H2 fallback; the key as a bearer capability and the audience CSP)
- Modify: `CHANGELOG.md`

Gate: `uv run pytest -q -x --ignore-glob='*_slow.py'`. Read `write_prose` before writing `docs/present.md`.

- As built (Task 8), from the teacher review of this task (`answer_c3f13b11f29b.txt`), checked against the code after Tasks 5-7:
  - `docs/present.md` is the guide, written to `write_docs` (ASD-STE100). `README.md`, `docs/README.md` and `docs/desktop.md` link it. It covers the three starts and `rise.start_slideshow_at`, the audience window and the Mac system browser, the keys from `PRESENT_KEYS` with the Esc order, notes, laser and blank, text size, Run, Stop and Show error, demos, what the room never sees and what it can still see, the RISE types and the H2 rule, reload and recovery, End, the read-only audience key, and the Later list under `Not in this version`. It says that notes are not on the audience page and are visible when the presenter screen is shared. It does not say that answers are hidden.
  - The review's prerequisites are met in code: the `present` help section exists (Task 5), and Run writes no file (Task 7). The help said every key could be rebound; `showHelp` now says that every key outside the `present` section can be rebound, and the `present` section says its keys work only during a presentation, cannot be rebound, and that laser and blank have no button.
  - Removed: the reveal.js comment in `core.js` (`mountCodeSurface`) and the `Reveal.slide` wording in `present.js` (`presentAt`, still used by the grouping test only). The `riseConfig` comment states the contract without naming reveal.js. Test docstrings that record why a test changed in Task 4 keep their reveal.js mention.
  - Not done here: the release guard against `[tool.uv.sources] abhyasa` (decision 11) and a non-skippable wheel check. The review asked for both; they belong to the release task, and the brief for Task 8 did not include them.
  - `Notebook.run` applies a `clear_output` event (Follow-up A). No pin changed.
  - Tests: `tests/test_present_docs.py` (guide linked, one mode, reveal options ignored, limits and the notes warning, no Later item offered outside its section, no em dash); `test_the_keys_help_says_the_presentation_keys_cannot_be_rebound` (`tests/test_keys.py`) and the rendered help in `test_esc_never_ends_the_presentation`; `test_a_clear_output_event_empties_the_streamed_outputs_and_their_display_ids` and `test_outputs_with_no_clear_stream_as_before` (`tests/test_nb.py`).

---

## Order and sequencing

Every JS task rewrites `leela/static/lee-core.js`, so Tasks 1, 4, 5, 6 and 7 run one at a time.

| task | needs | files it changes |
|---|---|---|
| 0 Pins and rupaka bundle | none (done, `e4c3260`) | `pyproject.toml`, `uv.lock`, `leela/vendor/*`, `tests/test_abhyasa_contract.py` |
| 1 Slide line and fragments | none | `nb/present.js`, `static/lee-core.js`, `tests/test_present.py`, `tests/data/rise_cases.json` |
| 2 Room copy | none | `nb/show.py`, `tests/test_present_room.py` |
| 3 State and routes | 0, 2 | `nb/presentation.py`, `nb/app.py`, `static/present-audience.html`, `packaging/macos/setup.py`, `packaging/windows/setup.py`, `tests/routes.txt`, `tests/test_present_routes.py` |
| 4 Relay, renderer, look, audience window | 0, 1, 3 | `nb/slides.js`, `nb/present.js`, `nb/presentation.py`, `nb/app.py`, `nb/show.py`, `static/present-audience.html`, `tests/routes.txt`, `tests/test_present_routes.py`, `tests/test_present_room.py`, `tests/test_md_output_font.py`, `static/lee-slides.css`, `static/lee-ide.css`, `static/present-notes.html`, `static/lee-*.js`, `leela/app.py` (head link), `vendor/reveal/`, `vendor/README`, `tools/build_ide_js.py`, `tests/test_present.py`, `tests/test_present_slow.py` |
| 5 One key scope | 4 | `nb/present.js`, `core/keys.py`, `static/lee-core.js`, `tests/test_present.py`, `tests/test_present_slow.py` |
| 6 Recovery | 5 | `nb/app.py`, `nb/show.py`, `nb/present.js`, `static/lee-core.js`, `tests/routes.txt`, `tests/test_present_routes.py`, `tests/test_present_slow.py` |
| 7 Live code and demos | 6 | `nb/present.js`, `nb/slides.js`, `static/js/core.js`, `editor/mount.js`, `runtime/kernel.js`, `nb/app.py`, `nb/show.py`, `static/lee-slides.css`, `static/lee-*.js`, `tests/routes.txt`, `tests/test_present_routes.py`, `tests/test_present.py`, `tests/test_present_slow.py` |
| 8 Guide | 7 | `docs/present.md`, `CHANGELOG.md` |

Three writers can work at once while Task 0 finishes, on lines that touch disjoint files:

1. Writer 0: Task 0 (done, `e4c3260`).
2. Writer A (JS): Task 1.
3. Writer B (Python): Task 2, then Task 3 after Task 0 merges.

Task 1 edits no file of Task 0, Task 2 or Task 3. Task 2 creates `show.py` and its test only. Task 3 does not touch `tests/test_present.py`, which Task 1 owns. Barrier: Tasks 0, 1 and 3 merge. Then one writer takes 4, 5, 6 and 7 in order, then 8.

## Later

One opt-in feature, "Ask the room", built on `rupaka.poll`. It covers the room features of the old plan as one choice the presenter makes. Logging and a recap come with it as deliberate opt-ins, never by default. Until then Leela does not port:

- the abhyasa talk schema, `check_talk`, beat names and `public_deck`;
- saved `.talk.json` files, the run log, `recap` and `recap_html`;
- hand counts, gate-to-room questions, the `run` ask kind and the `output` type ("What does this print?");
- agent-drafted speaker notes;
- a native audience window in the Mac app (the system browser opens the audience page; decision 9 dropped);
- clicker blank keys other than B.

Upstream, found in Task 7: kunda should report `clear_output` to `on_output` during a run, and `Kernel.alive` should be false once the kernel process exits. Leela applies the clear in `Notebook.run` since Task 8 (`test_a_clear_output_event_empties_the_streamed_outputs_and_their_display_ids`). The kunda 0.0.10 release that sends it remains, with no pin change in Leela until then. The `Kernel.alive` fix is still open in kunda.

If saved talks return, decision 7 holds: the talk is `<notebook>.talk.json` beside the notebook and run logs go to the shared learning store with `Learning.put_run`.

## Open questions for the owner

1. **`room_spec` in abhyasa core.** Open. abhyasa 0.0.12 has `room_spec` in `abhyasa.core.stage`, but importing `abhyasa.core` loads its web UI and settings, which Leela's code must not do. Leela keeps its checked copy until abhyasa makes that module importable on its own.
2. **A-/A+ in the audience window.** This plan sends `size`, so both windows draw the same text size. Recommendation: keep it; the alternative is a presenter-only size, which makes the preview differ from the room.
3. **Last good output.** This plan keeps a failed run's outputs except the `error` entry. Recommendation: keep it; the alternative is to put back the previous successful run's outputs, which hides output the room has already seen.
