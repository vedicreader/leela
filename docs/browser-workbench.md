# Browser workbench

Leela is a browser-only IDE. Its workbench keeps project files, notebooks, live Python
state, terminals, source control, research, and the coding agent in one loopback-only app.

## Settings

Open Tools, then Settings, or press `Command+,` (`Control+,` elsewhere). Four layers decide
an editing setting, in this order: Leela's defaults, `~/.config/leela/settings.json`, the
project's `.leela/settings.json`, then the user and workspace language overrides. Local
storage keeps browser-only geometry. The settings header picks the User or Workspace scope,
and all languages, Python, or Markdown.

JetBrains Mono and Fira Code variable fonts are bundled as WOFF2 assets, so selecting them
works offline and does not silently fall back to the system font. The ligature proof row
shows `!=`, `->`, `=>`, `<=`, `>=`, `===`, and `::` while toggling OpenType `liga` and `calt`.
A change to typography, wrapping, visual columns, whitespace, indentation guides, line
numbers, bracket colors, cursor style, sticky symbols or the long-file overview updates an
open CodeMirror editor in place. None of them remount it.

File settings control autosave timing, final newlines, trailing whitespace, delete
confirmation, and format-on-save. Python formatting uses Ruff or Black from the selected
project environment. JSON uses Leela's own structural formatter. IndexedDB recovery and external
write conflict review remain enabled independently of autosave.

## Notebook cells

Use the cell gutter to drag a cell. The cell menu includes run above/below/all, insert,
move, duplicate, copy, cut, paste above/below, split, merge, change type, clear output,
and delete. Structural operations have notebook-level undo and redo. Text editing keeps CodeMirror's
character-level history. Shift-click selects a cell range, and copy, cut,
paste, delete, and gutter dragging operate on that range as one undoable operation.

## Runtime and debugging configuration

The kernel picker chooses the launcher and Python interpreter. A run configuration has a field for the command, the working
directory, the watched module, inspector attachment, explicit environment values, and a
project-relative dotenv file such as `.env.local`.
Keep secrets in an ignored dotenv file rather than `.leela/runs.json`.

A run configuration can instead launch or attach with debugpy. A direct session covers files,
modules, tests and applications. It carries arguments, environment, `justMyCode`,
stop-on-entry, subprocesses, the Django, Jinja and gevent options, and a loopback attach host
and port. While it runs you get source breakpoints, conditions, hit counts, logpoints,
exception policy, call stacks, locals, evaluation, and continue, step over, step in and step
out. Leela offers to install debugpy into the selected project environment. It never exposes
a non-loopback attach port by default. Notebook cells retain
their ipykernel Jupyter-DAP path and use the same debugger UI.

## Workspace history

Every successful file save creates a persistent checkpoint outside the repository. Open Tools,
then Workspace history, to inspect and undo them. Undo is atomic and refused
when any affected file no longer matches the recorded output, so it cannot overwrite a
newer external change.

## File conflicts

Autosave uses disk-version checks and IndexedDB recovery. If the file changed externally, choose merge
changes. CodeMirror's two-pane merge view opens with the current disk content on the left and
the editable result on the right. Saving the result creates a new disk version rather than
replacing either side. Notebooks use the same merge engine cell by cell, preserving their structural
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
