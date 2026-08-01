# leela

> creative workspace that starts with coding

leela is an IDE for notebooks, files and **live variables** — in the terminal or in
the browser, over the same workspace. It grew up inside
[dhrishti](https://github.com/vedicreader/dhrishti) and now lives here, on its own.

The split is deliberate. dhrishti is the library: live variable inspection and
manipulation for Python runtimes, authored literately in notebooks under nbdev.
leela is the application built on top of it — a few thousand lines of Textual and
FastHTML wiring — and depends on dhrishti like any other package.

## Install

```sh
pip install leela
```

> **Live variables need an unreleased dhrishti.** The in-kernel inspector is started
> through `dhrishti.serving.serve_in_kernel`, which is in dhrishti's repository but
> not in the published 0.0.5 wheel. With only PyPI dhrishti installed, kernels start
> and run code normally but the variable panel stays empty and the kernel reports a
> `boot_error`. Until dhrishti cuts a release with it, install dhrishti from a
> checkout alongside leela:
>
> ```sh
> uv pip install -e ../dhrishti
> ```

## Use

```sh
leela                      # open the saved workspace in the terminal
leela .                    # open a folder in the terminal
leela --web src tests      # open two folders in the browser
```

Both frontends drive one `Workspace`, so the terminal and the browser show the same
folders, tabs and kernels.

## What it does

- **Notebooks and files** side by side, with a real editor in each frontend
  (Textual in the terminal, CodeMirror 6 in the browser).
- **Live variables** from the notebook's own kernel. Each notebook tab owns a real
  ipykernel process with a dhrishti inspector running *inside* it, so the variable
  tree stays responsive even while a long cell is running.
- **Shared kernels per folder.** Tabs bind per root, not per tab: the exec strip,
  the scratch box and two open notebooks all see the same variables. A tab can opt
  out and take a private kernel.
- **Prompt cells.** Ask a question in the notebook and the answer is saved *in the
  cell* — re-runnable, read in order with everything else. Written as markdown with
  the reply in metadata, so the file stays valid and legible in plain Jupyter.
- **An assistant** that sees what you see: the code index, the open files, the live
  namespace, and the IDE's own screen.
- **Code search** over [kosha](https://pypi.org/project/koshas/) — FTS5, embeddings
  and a call graph — falling back to a literal scan when the index is unavailable.
- **A dev server** that runs your app under a live inspector, so its module
  namespace shows up in the variable panel while it serves.
- **A terminal**, and lazygit if you have it.

## Layout

```
leela/
  cli.py          the `leela` entry point
  workspace.py    open folders, open tabs, and which kernel each tab talks to
  kernels.py      managed ipykernels, each hosting its own dhrishti inspector
  nb.py           the notebook document: cells, outputs, running them
  ai.py           the assistant and inline completion
  search.py       code search over kosha, with a plain-scan fallback
  diffs.py        the diff engine both frontends render
  keys.py         single-source keymap for both frontends
  fs.py           filesystem access, confined to the open folders
  term.py         terminals and lazygit
  research.py     web search and fetch
  devserver.py    run an app under a live inspector
  tui/            the terminal frontend (Textual)
  web/            the browser frontend (FastHTML), with vendored browser bundles
```

`keys.py` is the single source of the keymap: the TUI builds its bindings from it
and the web client generates its handlers from it, so the two frontends cannot
drift apart on shortcuts.

## Develop

```sh
uv venv --python 3.12
uv pip install -e . --group test
pytest tests -q
```

The suite covers the notebook document, the diff engine, the keymap, and SVG
snapshots of the terminal frontend. Kernels are faked in `tests/conftest.py` rather
than launched, so the tests are fast and do not need a working ipykernel.

The browser bundles in `leela/web/static` are committed so users never need node.
To rebuild them:

```sh
cd leela/web/src && npm install && npm run build
```

## License

Apache-2.0
