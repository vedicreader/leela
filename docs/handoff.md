# Handoff

Branch `main`, **7 commits ahead of `origin/main`, unpushed**. Karthik has not approved the push.
Suite **1644 passed, 3 skipped, 127 deselected**.

One test fails and is meant to: `test_the_built_app_matches_the_tree_it_was_built_from`. It compares
`/Applications/Leela.app/Contents/Resources/leela-build.json` against `HEAD` and fails whenever the
bundle is older than the tree. It is a guard, not a defect. A rebuild clears it.

Read `CLAUDE.md` and `AGENTS.md` first. The house style is enforced by review, not by a linter.

## Read this before anything else

**Karthik tests the web app, not the packaged app.** Every bug in this session was found in a
browser against the dev server, not in `/Applications/Leela.app`. Advice to rebuild and install was
mostly beside the point, and cost time. To put a change in front of him, restart the dev server. He
will say so explicitly when he means the bundle.

**He wants plain English.** Short sentences, no filler, lead with the answer. He said so directly.

**Report findings and stop when he is asking a question.** Several times the deliverable was an
assessment, not a change.

## What landed

| commit | what |
|---|---|
| `c793efd` | Leela closes the Chrome it started and leaves the one it adopted. Ownership is per port; the last window out closes it. |
| `aebd140` | The git pill repaints after a shell swap, and a failed request no longer renders as `no git`. |
| `8b67cc4` | `note_folder` moved into the hub, so a folder opened from a browser tab is remembered like one opened from the app. |
| `6ce63a6` | A finished run's clock stops and loses its Stop button. Pairs with ramabana 0.1.28. |
| `d171759` | `nbdev-prepare` runs for a project configured through `[tool.nbdev]`, not only `settings.ini`. Takes ramabana 0.1.28. |
| `6905b25` | `venv_env` no longer sets `UV_PROJECT_ENVIRONMENT`; pipeline steps go through `uv run` where uv owns the project. |
| `ec7f70d` | uv is handed the spelling the project has, so a step named `nbdev_prepare` reaches `nbdev-prepare`. |

Released separately: **ramabana 0.1.28**, carrying the fix that drops finished subagents from
`runs(active=True)`. Leela's pin is bumped and the lock updated.

## Open, in the order they matter

1. **Push `main`.** Seven commits. Karthik decides, not you.
2. **Single-pane workspaces.** He has approved the direction: one window holding many repos is the
   default, and "open in a new window" becomes an explicit action. Clone already adds a root, so
   nothing needs flipping there. What is left is the folder picker, which still opens a new window.
   Before editing, read the missing-cases review below.
3. **The browser's `open folder` does nothing.** `openFolderWindow` calls `nativeFolder()`, which
   returns null when `shellReady()` is false. In a browser tab there is no pywebview bridge, so `o`,
   the `open…` button and two menu entries silently do nothing after a 1500 ms wait.
4. **The packaged app cannot load `vishalakshi`.** `packaging/macos/setup.py:58` excludes `litert_lm`,
   but `vishalakshi/__init__.py` imports `rishi.litert`, which imports it at module level. So
   `from vishalakshi import Vault` raises inside the bundle and crashes `Workspace.load` for any
   workspace whose saved state carries agent text. Found by an agent, reproduced, not fixed.
5. **`resolve_script` falls back to PATH.** For a project uv does not manage, it can pick up an
   unrelated interpreter's copy of a tool. A Python 3.8 nbdev on this machine did exactly that.
   Karthik has been told and has not asked for a change.
6. **Notebook scrollbar.** Three mechanisms fixed in an earlier session, his case survives all three.
7. **Notarisation and the v0.1.0 tag.** Parked by him until the app is release-ready.
8. **`scratchpad/litert-bug-report.md`** is written and he will post it.

## The single-pane plan, and what a review found wrong with it

An independent review rejected the riskiest item. `leela/blocks/fs/files.js:430` is not a separate
picker; it is the submit handler inside `addRoot()` at `files.js:355`. That one function is reached
by `O`, the FILES `add…` button, four menu-bar menus, the palette row, `findRepo()` and the welcome
screen's primary button. Retargeting it would leave no UI anywhere reaching `/fs/add-root`, which
removes the cross-repo workflow Karthik calls the point of the product.

Other findings worth carrying:

- `/hub/open` does not test containment, so opening a folder inside an existing root builds a second
  workspace over the same tree: two watchers, two kernel pools, two agents. `add_root` collapses that
  case today.
- There are two clone paths. The branchbar clones beside the roots; `RepoSet.clone` requires the
  parent to be inside one. No rule says which applies.
- `assign_slugs` persists the slug map, so a clone into a previously-slugged, since-deleted path
  inherits that workspace's old state file.
- `ShellApi.open_folder` returns `True` as soon as the work is queued and reports failures by
  printing to stdout, so the desktop leg cannot report a failure the browser leg can.
- Git has a second scope. `RepoSet` keeps an `extra` list of repositories outside `fs.roots`, and
  `/git/clone` writes outside them. "`fs.roots` is the only scope" is true for the filesystem
  sandbox, Search and the agent's `grep`, and false for Git.

## Traps that cost time in this session

- **Do not run `uv sync` in one repo from a terminal rooted in another.** It emptied ramabana's venv
  of ramabana. That is fixed in `6905b25`, but any already-broken venv needs `uv sync` to repair.
- **`nbdev_prepare` with an underscore does not exist in a current venv.** It resolves to whatever is
  on PATH. Use `uv run nbdev-prepare`.
- **ramabana is nbdev, and `nbdev` CLI commands are blocked by safecmd.** Call `nbdev_export`,
  `nbdev_test` and `nbdev_clean` through their Python API. ramabana's venv can run them; leela's venv
  can too if you put the ramabana repo on `PYTHONPATH`.
- **Editing a block's `.js` requires `tools/build_ide_js.py`.** The bundles are committed and
  `tests/blocks/test_ide_bundle.py` fails on drift. One source file can feed more than one bundle:
  a commit that staged only `lee-ide.js` shipped a stale `lee-core.js`.
- **node is blocked here.** Ask Karthik to run `! node --check leela/static/lee-ide.js`.
- **Test doubles go stale.** `FakeBrowser` had no `quit`; three kernel doubles had no `touch`. When a
  real class grows a method the teardown calls, the doubles need it too.

## The pattern behind most of these

A failure and an absence rendered the same. The git pill said `no git` for a broken request and for a
folder with no repository. `runs(active=True)` could not tell a finished subagent from a running one.
The pipeline said "not an nbdev project" when it could not find a script. When you fix one of these,
check whether the code can distinguish "no" from "I could not tell", and make it say which.
