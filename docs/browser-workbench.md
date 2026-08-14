# Browser workbench

Leela is a browser-only IDE. Its workbench keeps project files, notebooks, live Python
state, terminals, source control, research, and the coding agent in one loopback-only app.

## Settings

Open **Tools → Settings** or press `Command+,` (`Control+,` elsewhere). Editing settings are
layered in this order: Leela defaults, `~/.config/leela/settings.json`, the project's
`.leela/settings.json`, and user/workspace language overrides. Browser-only geometry remains
in local storage. The settings header chooses User or Workspace scope and all languages,
Python, or Markdown.

JetBrains Mono and Fira Code variable fonts are bundled as WOFF2 assets, so selecting them
works offline and does not silently fall back to the system font. The ligature proof row
shows `!=`, `->`, `=>`, `<=`, `>=`, `===`, and `::` while toggling OpenType `liga` and `calt`.
Typography, wrapping, visual columns, whitespace, indentation guides, relative/hybrid line
numbers, bracket colors, cursor style, sticky symbols, and the long-file code overview update
open CodeMirror editors without remounting them.

File settings control autosave timing, final newlines, trailing whitespace, delete
confirmation, and format-on-save. Python formatting uses Ruff or Black from the selected
project environment; JSON uses Leela's structural formatter. IndexedDB recovery and external
write conflict review remain enabled independently of autosave.

## Notebook cells

Use the cell gutter to drag a cell. The cell menu includes run above/below/all, insert,
move, duplicate, copy, cut, paste above/below, split, merge, change type, clear output,
and delete. Structural operations have notebook-level undo and redo; text editing keeps
CodeMirror's character-level history. Shift-click selects a cell range, and copy, cut,
paste, delete, and gutter dragging operate on that range as one undoable operation.

## Runtime and debugging configuration

The kernel picker chooses the launcher and Python interpreter. Run configurations provide
a structured UI for command, working directory, watched module, inspector attachment,
explicit environment values, and a project-relative dotenv file such as `.env.local`.
Keep secrets in an ignored dotenv file rather than `.leela/runs.json`.

A run configuration can instead launch or attach with debugpy. Direct sessions support files,
modules, tests and applications, arguments, environment, `justMyCode`, stop-on-entry,
subprocesses, Django/Jinja/gevent options, loopback attach host/port, source breakpoints,
conditions, hit counts, logpoints, exception policy, call stacks, locals, evaluation, and
continue/step-over/step-in/step-out. Leela offers to install debugpy into the selected project
environment; it never exposes a non-loopback attach port by default. Notebook cells retain
their ipykernel Jupyter-DAP path and use the same debugger UI.

## Workspace history

Every successful file save creates a persistent checkpoint outside the repository. Open
**Tools → Workspace history** to inspect and undo checkpoints. Undo is atomic and refused
when any affected file no longer matches the recorded output, so it cannot overwrite a
newer external change.

## File conflicts

Autosave uses disk-version checks and IndexedDB recovery. If the file changed externally,
choose **merge changes** to open CodeMirror's two-pane merge view: current disk content is
on the left and the editable result is on the right. Saving the result creates a new, explicit disk version instead of silently replacing
either side. Notebooks use the same merge engine cell by cell, preserving their structural
boundaries while resolving source conflicts.

## Python language service

When `pyright-langserver` is available, Leela starts and owns it lazily for the open
project. Unsaved `.py` buffers are synchronized through LSP and Pyright diagnostics join
Python compiler diagnostics in CodeMirror. Settings reports whether Pyright is optional,
available, or connected.

## Navigation aids

Editor settings can enable a lightweight CodeMirror minimap with a viewport overview.
Sticky navigation follows the nearest Python class or function while the document scrolls.
Both are isolated editor extensions and can be changed without remounting open documents.

## Kernel failures

The kernel pill changes to a warning when its authenticated inspector cannot be reached.
Open the kernel picker to see the transport error and restart the exact kernel.
