# Review before 1.0

A review of main at 2623b616 (7 Nov 2026). Each item has an ID, the owner package and a size. Tick an item when its fix and its regression test are on main.

## Blockers

### A. Server guard and file serving (leela, gheasy)
- [ ] A1. `/file/raw` serves `.svg` inline at Leela's origin with no CSP. A script in an SVG reads `/term/info` and gets the terminal token. Serve with `Content-Security-Policy: sandbox; default-src 'none'`; send SVG as an attachment or only in `<img>`. (leela, S)
- [ ] A2. `GET /git/history?ref=--output=<path>` overwrites a file outside the roots. Put `--end-of-options` before each caller ref in gheasy (history, blame, compare, file, diff); refuse a ref that starts with `-` in Leela. (gheasy, leela, S)
- [ ] A3. The guard refuses only `Sec-Fetch-Site: cross-site`, so a page on another local port reaches GET routes that change state (`/dev/start`, `/vault/not-pii`, `/vault/watch`, `/vault/move`, `/browser/external`, `/term/external`). Allow only `same-origin` and `none`; make each state change POST only; test every route in `tests/routes.txt` with `same-site`. (leela, M)
- [ ] A4. A per-launch secret for the page: the launcher sets a cookie from a one-time URL, and the guard refuses a request without it. `/term/info` stops giving the terminal token to any caller. Needed for Linux and WSL. (kavacha contract, leela, M)

### B. The agent's approval gate (leela, shalya, ramabana, dockeasy)
- [ ] B1. `inspect_python` with `scope='overlay'` runs any code with no question. Gate it as a write, or allow only `isolated`. (shalya, leela, S)
- [ ] B2. `watch` and `poll` read any file into the vault with no path check and no question; a `url` watch can send data out. Check the target with `self.check(target, reading=True)`; gate `watch`, `poll`, `unwatch` and `remember`. (leela, S)
- [ ] B3. `api_call` sends DELETE or POST with stored keys with no question; `generate_image` and `generate_video` spend money with no question. Gate verbs other than GET and HEAD; gate the generate tools. (ramabana, leela, S)
- [ ] B4. Keys saved on the vault API page go into `~/.config/fastops/.env` and `os.environ`, so every kernel and shell sees them. Keychain only, with a 0600 file when no keychain exists; never `os.environ`; strip `LEELA_API_*` from children. (dockeasy, leela, S-M)
- [ ] B5. In `edits` mode the agent writes `.git/hooks/*`, `.git/config` and `.venv/bin/python` with no question. Always ask for writes under `.git/`, `.venv/` and `.leela/`. (leela, S)
- [ ] B6. A repo's `.leela/settings.json` sets `terminal.shell` and `shellArgs`. Read `terminal.*` and `agent.configFolder` from the user layer only. (leela, S)
- [ ] B7. The agent's notebook tools work on the file on disk, not on the open tab, so `run_cell` runs old code; `check_exercise` runs code with no question. (leela, M)

### C. Data safety (leela)
- [x] C1. A non-UTF-8 file opens as editable and a save corrupts it (`fs.py:245`, `:255`). Decode strictly; open such files read-only with a note; refuse the write. (S)
- [x] C2. Streamed cell output grows quadratically (`nb/app.py:198`, `nb.py:527`): 2000 prints gave 137 MB of SSE and 505 MB RSS. Merge stream outputs, send deltas at most every 50-100 ms, cap text per output. (M)

### D. Header layout (leela)
- [x] D1. The tab strip collapses to one tab and "+N" at 1440 px (`actions.js:412-432` measures `#tabbar`). `test_nb_races_slow.py::test_saving_one_scratch_notebook_keeps_another_scratch_notebooks_unsaved_text` fails. (S)
- [x] D2. Git pane rows show no file name: hidden buttons keep their width (`lee-ide.css:2701`). (S)
- [x] D3. A full-screen side pane covers the header (`inset: 34px`, `lee-ide.css:602`). (S)
- [x] D4. Files pane header buttons spill over the editor (`.lee-phead`, `lee-ide.css:520`). (S)

## Should fix

### Settings, files, notebooks, editor (leela)
- [ ] S4. A typo in the user settings file wipes all user settings at the next save. Refuse to save over a file that does not parse; keep a `.bad` copy. (S)
- [ ] S5. A clone can go into any folder (`git/app.py:282 _clone_into`). (S)
- [x] S7. A save after an outside rewrite undoes deletes and moves and drops in-memory outputs (`_rebase_notebook`, `nb/app.py:30`). (M)
- [x] S8. Two windows on one notebook lose each other's edits (`core.js:303`). Send changed cells with the source each page last saw. (M)
- [x] S9. CRLF files become LF on save. (S)
- [x] S10. Rename-symbol uses code points where LSP sends UTF-16 units, and splits with `splitlines` (`lsp/app.py:14-33`). (S)
- [ ] S11. Go-to-file stops at 20000 files and says `partial: False` (`fs.py:57`, `fs/app.py:325`); the same cap limits replace. (S)
- [ ] S12. The trash is never emptied and moves folders across disks (`core/session.py:239`). (S)
- [ ] S13. FileHistory blobs are not atomic; two processes overwrite `index.json` and prune each other's blobs (`session.py:76-81`). (S)
- [ ] S14. Rust cells: a second run gives `E0428`; Stop and Restart do not kill the process (`runtime/runners.py`). (S-M)

### Performance (leela)
- [ ] S15. Start takes 7-9 s; `from IPython.core.display import ImageFormat` in `blocks/nb/show.py:10` costs 1.3 s. (S)
- [x] S16. A 77 MB notebook: `/tab/state` sends 76 MB; each save adds about 85 MB RSS. (M)
- [ ] S17. On Linux, inotify still watches ignored folders such as `node_modules` and `.venv` (`fs/watch.py:93`). (M)

### UX and prose (leela)
- [ ] S18. Dim text fails WCAG AA in both themes (dark 3.76:1, light 4.27:1). (S)
- [ ] S19. The welcome screen uses package words, two em dashes and raw chords such as `mod+o` (`app.py:462-489`). (S)
- [ ] S20. With no folder, the git pill says "git …" for ever (`git/cwd.js:236`). (S)
- [ ] S21. The agent's first message is long, nested and shows literal backticks; "Set up agent state" shows with no folder. (ramabana text, leela card, S)
- [ ] S22. Quick open with no match shows an empty box; row 2 has two buttons named "File". (S)
- [ ] S23. Visual: pandas tables with white borders in dark mode (`nb/cells.js:679`); palette rows end in " · global"; palette and cell menu run off screen; focus rings on whole tree and menu; toasts over the TERMINAL / EXEC pill; terminal echoes the `export PATH` prelude (`term.py:67`); the approval card label goes vertical (`lee-ide.css:1318`); mixed menu casing; absolute `/private/var` paths in go-to-file and settings. (S each)
- [ ] S24. Docs: the guide names `ctrl+alt+d`/`ctrl+alt+e` and `hyper`; ⌘O, ⌘P, ⌘1-5, Jupyter letters, the venv notice and the header are missing; `present.md` says "toolbar"; 30 hard-wrapped paragraphs. (M)
- [ ] S25. UI text has 104 em dashes and hedges. (M)

### Tests and CI (leela)
- [ ] T1. One isolation helper that sets XDG, `VISHALAKSHI_VAULT`, `LEELA_SEARCH_VAULT`, `ABHYASA_CONFIG`, `RAMABANA_CONFIG` and `LEELA_MEMORY_OFFLINE=1`; guard those folders in conftest; an autouse fake keyring; AGENTS.md rule. ramabana writes probes to a fixed `~/.config/ramabana/probes`. (S)
- [ ] T2. CI runs none of the 283 slow tests and only Python 3.12; the app ships 3.13. A nightly `-m slow` job and a 3.13 matrix. (M)
- [ ] T3. Flaky under load: `test_runtime.py::test_stopping_a_run_ends_its_viewers_and_starting_again_is_a_fresh_stream`, `test_core.py::test_a_hung_interactive_shell_is_asked_again_as_a_login_shell`, `test_refactor` silent server, `test_watchdog::test_idle_writes_nothing`, `test_agent` timeout children, `test_nb_check::test_home_is_the_work_folder`. (S each)
- [ ] T5. Slow tests that fail on main: `test_the_keymap_answers_every_chord_it_claims_in_one_browser_session` ("reading 'hyper'"), `test_markdown_links_never_navigate_the_desktop_shell` (link list mismatch). (S)
- [ ] T4. No test for: many streamed outputs, non-UTF-8 and CRLF round trips, LSP UTF-16 rename, rebase with delete/move/insert, two-page saves, the walk cap, the same-site guard, the SVG CSP.

### Other packages
- [ ] P1. Each kernel's inspector takes port 8000 (`kunda/pool.py:89`, `dhrishti/serving.py:46`); bind port 0. (kunda, dhrishti, S)
- [ ] P2. `.kosha/` shows as untracked in the person's repo; write `.kosha/.gitignore` with `*`. (koshas, S)
- [ ] P3. The thin first install downloads about 392 MB: claude-agent-sdk, playwright, patchright, jupyterlab and notebook through dockeasy, litert-lm-api, matplotlib. Move them to extras, after a test of Leela with none of them (an OpenRouter key, Ollama models). (dockeasy, fossick, rishi, safepyrun, leela, M)
- [ ] P4. diskcache 5.6.3 has PYSEC-2026-2447 with no fix (fossick, uraiyadal). (S-M)
- [ ] P5. html2text is GPL-3.0, through fossick; replace it, with fossick's own converter if it has one. (fossick, S)
- [ ] P6. The thin launcher appends `server.log` for ever; 0.1.x has no log a person can send. (kavacha, S)
- [ ] P7. The cask zap list misses `~/Library/Logs/Leela`. (homebrew-tap, S)
- [ ] P8. `lee-cm6.js`, `lee-term.js` and htmx ship with no licence notice and no lockfile (`frontend/package.json`). (leela, S)

## Nice to have
- [ ] N1. The update thread stays "running" if `_run` raises; a pipeline timeout kills only the direct child (`pipelines/app.py:44`); a backup restore swallows errors (`core/backups.py:316`); a read-only file is overwritten; Stop interrupts the active tab's kernel, not the busy one; settings types: a non-dict `languages` entry raises, "false" becomes True.
- [ ] N2. Accessibility: `lang`, landmarks and an h1, tablist roles, the palette's accessible name, Tab out of the exec box, the empty-folder hint, ⌘O in a browser tab waits 1.5 s.
- [ ] N3. Code health: dead code in `app.py` (`_project_state_context`, `_inline_values`, `_assigned_lines`, `_history_sessions`); `blocks/git/repos.py` copies `gheasy.repos`; `vault/spec.py:36-100` parses OpenAPI by hand (ramabana.spec does it); `learn/tools.py` makes venvs without kunda `make_venv`; `core/envs.py:140` copies pullup's `EnvStore.unset`; the unused `script` job kind is still reachable through `/jobs/{id}/retry`; `jobs.py:135` leaves SQLite connections open; the output sanitizer in `nb/cells.js:575-622` has only a slow test; `ai.py` is 1589 lines.
- [ ] N4. Pins and metadata: `nh3==0.3.7` exact pin; abhyasa, kernmini, ipymini, mdhtml, fasthtml, starlette and rgapi are behind; `laghu-rs` and `pobblebonk` ship no LICENSE; litesearch's author field is "71293".
- [ ] N5. Drop the `LEGACY` chords in `core/keys.py:354`, promised for one release in 0.1.23.
- [ ] N6. The `leela` skill: say what each approval mode lets through; cover `.leela/settings.json`, Set up .venv and updates; `_palette_extras` must not return an empty list quietly.
