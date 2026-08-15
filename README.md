<p align="center">
  <img src="docs/logo.png" alt="leela" width="128" height="128">
</p>

# leela

<p align="center"><em>creative workspace that starts with coding</em></p>

A browser IDE for notebooks, files, live variables, research memory, and an agent.
The same shell opens as a native desktop window.

<video src="docs/media/leela-showcase.mp4" controls width="100%" poster="docs/screenshots/showcase-poster.png"></video>

<p align="center"><a href="docs/media/leela-showcase.mp4">Watch the walkthrough</a> · editor → agent turn → variables → git → palette → search</p>

## Install and run

```sh
pip install leela                # base
pip install "leela[github]"      # workflows, releases, deploys
pip install "leela[gateway]"     # jupygate kernel transport

leela                      # the saved workspace
leela .                    # a folder
leela src tests            # one workspace, two roots
leela --app src tests      # app windows in fossick's persistent CDP Chrome
leela --shell webview .    # native desktop window
```

`--app` picks the workspace shape. `--shell` picks what opens on top: `chrome`, `webview`, or `none`.
`leela --help` for transport, kernel, agent, and keymap flags.

## Walkthrough

Notebooks and files share CodeMirror 6. A Python tab runs as a script in its own kernel.
`▶ file` / `▶ sel`, `mod+e` for recent tabs, atomic autosave.

![Editor](docs/screenshots/web-editor.png)

Every agent call is a lifecycle card. Edit it, read the dry-run diff, approve, reject with
steering, retry, or roll it back. Autopilot, guided, and directed decide how much of that you see.
Harness: [ramabana](https://github.com/vedicreader/ramabana) (`leela.agent` is an alias).

![Agent mid turn](docs/screenshots/web-stream-1-tools.png)

![Agent answer](docs/screenshots/web-stream-3-done.png)

Each tab owns a real kernel with a [dhrishti](https://github.com/vedicreader/dhrishti) inspector
inside it. Prefix the Variables filter with `=` to evaluate against the watched runtime.

![Variables](docs/screenshots/web-variables.png)

Source control covers Changes, Review, Branches, History, and All repos.
Diffs open as editor tabs. Blame reads notebooks as cells. `leela ~/code` answers which
checkouts are dirty, behind, or unpublished.

![Git](docs/screenshots/web-git.png)

Code goes through [koshas](https://pypi.org/project/koshas/) (FTS5, embeddings, call graph)
behind `mod+shift+f`. Prose goes to a [vishalakshi](https://github.com/vedicreader/vishalakshi)
vault: pages read and sources kept, then recalled instead of fetched again.

![Code search](docs/screenshots/web-search.png)

![Memory sources](docs/screenshots/web-memory-sources.png)

Every action has a button, a palette entry (`mod+shift+p`), and a rebindable chord.
See [docs/desktop.md](docs/desktop.md) and `leela --write-keymap`.

![Palette](docs/screenshots/web-palette.png)

The desktop build is a native window over the same loopback server. Chrome for the inline
browser starts when a page needs it, not at launch. Packaging: [docs/desktop.md](docs/desktop.md).

![Desktop window](docs/screenshots/desktop-window.png)

![Welcome](docs/screenshots/desktop-welcome.png)

![Inline browser](docs/screenshots/desktop-inline-browser.png)

```sh
uv sync --extra desktop
leela --shell webview .
```

A process leela started under a run configuration is watchable. Anything else joins with one line.

```json
{"runs": [
  {"name": "api", "cmd": "uvicorn app:app --port 8000", "watch": "app"}
]}
```

```python
import dhrishti.serving as ds; ds.serve(name='api')
```

## Develop

```sh
uv venv --python 3.12
uv pip install -e . --group test
pytest tests -q
python tools/showcase.py          # refresh README stills + docs/media/leela-showcase.mp4
python tools/webshots.py          # agent-stream stills only
python tools/deskshots.py         # native window stills
```

Layout and block contract: [docs/blocks.md](docs/blocks.md).
What belongs in a dependency: [docs/integration.md](docs/integration.md).

## License

Apache-2.0
