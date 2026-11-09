# Try native Learn

This page tells you how to try native Learn on your Mac without risk to your data. One command starts Leela from this worktree. Every store is new and private to that run.

## Run it

```
/Users/71293/code/personal/orgs/leela/.venv/bin/python /Users/71293/code/personal/orgs/leela-native-learn/tools/try_native_learn.py
```

The launcher puts both worktrees on `sys.path` itself, so you do not set `PYTHONPATH`. It prints the process id, the URL, the state folder, the Learn vault name and file, the model, and 12 things to try. Open the URL in a browser. Press Ctrl+C to stop. The stop closes the Abhyasa pools, the kernels and the jobs.

## Flags

| Flag | What it does |
| --- | --- |
| `--copy-vault PATH` | Copies the vault file (and its `-wal` and `-shm` files) into the state folder. The original is only read. The copy is the standalone vault. The first Learn open shows the import offer: Attach, Back up and copy, or Skip. No demo data is added. |
| `--no-seed` | Leaves the new Learn vault empty. |
| `--model NAME` | Uses a model that is already configured, in place of the scripted one. Replies can then leave this machine. |
| `--state DIR` | Uses this folder again. The default is a new temporary folder. A folder under a real store is refused. |
| `--port N` | Uses this port on 127.0.0.1. The default is a free port. Port 5001 is refused. |

## What the preview is

- Isolated. The config, data, cache, vault, Abhyasa settings and Ramabana config are all under the state folder. The launcher never reads or writes your real vault or config.
- A scripted model. The replies are canned and nothing leaves this machine.
- Demo data. Without `--copy-vault`, the Learn vault holds a walk of 3 ideas from a paper with real quotes and a source link, a course, a talk, attempts from several days, and a demo check. The launcher says on stdout that this is demo data.
- Your port. It serves on 127.0.0.1 only.

## What the preview is not

- The real microphone is not checked. Dictation is built and its tests pass, but no person has spoken to it.
- A real speech model download is not checked.
- It is not the signed Mac app. It runs in a browser.
- Real model routing is not checked, unless you pass `--model`.

## Browser and packaged app

The packaged app is kavacha's launcher. It owns the native window, and Python runs headless as its child. The Python packages come from a signed environment lock, not from the app. A build uses `make ship` and `make ship-app`; this page does not run them. See `docs/thin-app.md`. The native window check, with menus, the window frame and the real keys, needs that build. Until it exists, use this browser preview and treat the window as not checked.

## What to check

Reference pictures are in `target/parity-ref/`.

| Surface | What to see | Reference |
| --- | --- | --- |
| Walk step | Quote, source link, check, feedback, hints, next | `abhyasa-step0.png`, `abhyasa-step0-answered.png`, `abhyasa-step1.png` |
| Walk page and history | Plan, versions, history | `abhyasa-walk-overview.png`, `abhyasa-walks.png`, `abhyasa-walk-history.png` |
| Today | Home entry, due reviews | `abhyasa-today.png`, `abhyasa-today-dark.png` |
| Course and concepts | The demo course and its idea pages | `abhyasa-concept.png`, `abhyasa-concept-seq.png` |
| Strengths and profile | Understanding by idea | `abhyasa-you.png`, `abhyasa-profile.png` |
| Graph | Dockable, themed | `abhyasa-graph.png`, `abhyasa-graph-dark.png` |
| Demo check | The softmax demo step | `abhyasa-step2-demo.png` |
| Talk and Present | Four or more slides, Present, Esc, End | `abhyasa-talk.png`, `abhyasa-talks.png` |
| Search, library, sources | Find the paper and its passage | `abhyasa-search.png`, `abhyasa-library.png`, `abhyasa-sources.png` |
| Guide | "I don't get this" in the agent pane | `abhyasa-guide.png` |
| Builder | Change a module from the agent pane | `abhyasa-build.png` |
| Settings | One dialog, with Learn | `abhyasa-settings.png` |
| Import offer | With `--copy-vault`: Attach, Back up and copy, Skip | none |
| Voice | Dictate an answer | none |
