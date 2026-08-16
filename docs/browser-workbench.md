# Browser workbench

Loopback-only browser IDE for files, notebooks, kernels, terminals, Git, research, and agents.

## Settings

Tools > Settings, or Command+, / Control+,.

Settings order:

1. Leela defaults
2. `~/.config/leela/settings.json`
3. `.leela/settings.json`
4. user and workspace language overrides

Browser geometry uses local storage. File settings cover autosave, whitespace, final newlines, confirmation, and formatting. Python uses Ruff or Black from the selected environment.

## Notebooks

The gutter supports drag, run, insert, move, duplicate, copy, cut, paste, split, merge, type changes, and output clearing. Structural edits have notebook undo and redo.

Each cell banner carries its position, kind, and line count. The gutter's `[n]` is the execution count, which is neither: it is blank until the cell runs and renumbers on every rerun. Hovering the label adds the character count, the last run's duration, and its output count. Clicking it copies the cell id.

## Runtime and debugging

The kernel picker selects the launcher and interpreter. Run configurations support command, directory, module watch, environment, dotenv files, and debugpy. Debugging supports breakpoints, conditions, hit counts, logpoints, stacks, locals, evaluation, and stepping. Attach binds to loopback only.

## History and conflicts

File saves create persistent checkpoints outside the repository. Workspace history can inspect and undo unchanged outputs. External changes open CodeMirror merge. Notebook merges operate per cell.

## Language service

Leela starts `pyright-langserver` lazily when available. Unsaved Python buffers use LSP diagnostics with compiler diagnostics.

## Navigation

Optional minimap and sticky symbols update open editors without remounting them.

## Kernel failures

The kernel pill reports inspector failures. The kernel picker shows the error and restarts the selected kernel.
