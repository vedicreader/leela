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
| `--web` | Lets the agent search the web for sources. Topic words are sent to the web search through Leela's privacy guard. Without it, web research is off: new walks have no web sources, and the walk page says research is off in this preview. |
| `--model NAME` | Uses a model that is already configured, in place of the scripted one. Replies can then leave this machine. |
| `--state DIR` | Uses this folder again. The default is a new temporary folder. A folder under a real store is refused. |
| `--rupaka PATH` | The rupaka worktree to import first. The default is the sibling `rupaka-explorables` worktree, if there is one. The banner names the rupaka in use. If it is too old for the circuit demos (no `ghost` on `plot`), the banner says `rupaka too old for the circuit demos` and the circuit and signal ideas are not added. |
| `--port N` | Uses this port on 127.0.0.1. The default is a free port. Port 5001 is refused. |

The launcher also takes `--dhrishti PATH` and `--kunda PATH`. The default for each is the sibling `dhrishti-explorables` or `kunda-explorables` worktree, if there is one. Without them, the cell Trace button says in one line which package is too old.

## What the preview is

- Isolated. The config, data, cache, vault, Abhyasa settings and Ramabana config are all under the state folder. The launcher never reads or writes your real vault or config.
- A scripted model. The replies are canned and nothing leaves this machine. Web research is off unless you pass `--web`.
- Demo data. Without `--copy-vault`, the Learn vault holds a walk of 3 ideas from a paper with real quotes and a source link, a course, a talk, attempts from several days, and a demo check. A second subject, "Circuits and signals", has six ideas (Ohm's law, an RC circuit, the RC low-pass filter, adding sine waves, sampling and aliasing, the spectrum), each with its live rupaka demo, a course, and the walk "How a low-pass filter works". Its passages are plain statements marked "Demo data", each with a link to a public page on the topic. The launcher says on stdout that this is demo data.
- Your port. It serves on 127.0.0.1 only.

## Code, picture and numbers

The first step of "How a low-pass filter works" (Ohm's law) has a code cell. The cell and the demo below it share the names `V` and `R`.

1. Press Run. The numbers show under the code, and the demo moves to the same `V` and `R`.
2. Pick an answer in the demo and press Lock in. Then drag the `R` slider. The code changes to the new `R = ...`, the output turns pale, and the cell says `changed R to 2, run to see it`. Press Run to bring the output up to date.
3. A name that the code sets more than once, or sets to a sum, is not changed. The cell says nothing then.
4. Open the idea page "Ohm's law". The four rungs (words, picture, code, numbers) move together. You passed that idea's check, so the picture has no second lock.
5. The first Run can take 10 seconds. The cell says `Starting the kernel…` and shows a spinner.

## Scrub and trace

- In a notebook, put the caret in a code cell that has a number. A line under the cell says `Hold Option and drag the 3. Live: off. Turn on`. The line goes away after your first drag.
- With live numbers off, a drag changes the number only, and the output shows `old: run again` until the next run.
- The cell menu has `live numbers for this cell: on or off` and `trace this run`. Each code cell also has a Trace button. The step bar under the cell starts at step 1 and has Play and Pause. The Variables pane shows the same step and has no slider of its own.
- In the circuit demo "An RC low-pass filter", after Lock in, your guess shows as a dashed curve beside the true one. Drag the input dot along the curve, or press A or D.

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
