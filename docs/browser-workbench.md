# Browser workbench guide

The interaction model of the browser IDE: what draws what, where focus lives, and how
running code reaches the page.

## The split: server owns structure, browser owns text

One rule explains most of the frontend:

> The server owns state and structure. The browser owns anything with a text cursor.

Everything with a caret — notebook cells, file editors, the exec strip, the agent composer
— is CodeMirror 6, talking JSON to routes. Everything else — the file tree, the variable
tree, the tab bar, the git panel, the status line — is server-rendered htmx that reuses the
same fragment builders Leela already has (`_tab_bar`, `_files_panel`, `_vars_panel`, and
friends in `leela/web/app.py`).

That split is why there is no client-side store and no rendering framework. A panel changes
because a route returned new markup for it, not because a model updated and a view reacted.
The consequence worth knowing: after any mutation, the server's fragment is the truth, and
the browser's job is to swap it in — not to predict it.

## Layout

```
┌───────────────────────────────────────────────────────────────┐
│ header — tabs · kernel pill · menus · action bar               │
├──────────┬─────────────────────────────────────────┬───────────┤
│ left     │ editor stage                            │ right     │
│          │   primary  [ · secondary when split ]   │           │
│ files    │                                         │ vars      │
│ git      ├─────────────────────────────────────────┤ memory    │
│ symbols  │ exec strip — live / isolated            │ agent     │
├──────────┴─────────────────────────────────────────┴───────────┤
│ bottom dock — terminal                                          │
├─────────────────────────────────────────────────────────────────┤
│ footer — status · toasts                                        │
└─────────────────────────────────────────────────────────────────┘
```

Both side workspaces and the dock collapse. The editor stage splits vertically or
horizontally into `primary` and `secondary` views; the split, the open panels and the
per-tab buffers survive a reload because they are persisted client-side (localStorage, and
IndexedDB for editor drafts).

## Focus is a scope, and scope decides the keymap

The keymap is not global. A binding fires when its scope is the focused pane, or when its
scope is `global` (`leela/keys.py`):

```
global · files · editor · exec · vars · agent · term
```

Four of those are *editing* scopes — `editor`, `exec`, `agent`, `term` — where a bare
letter belongs to the text field, not to a command. `Key` enforces this at import: a bare
character cannot be bound in an editing scope or in `global`, so a binding that would eat
typing cannot be added by accident. Bindings that fire inside text entry must carry a
modifier or be a function key.

The keymap is data, served to the browser as `/keys.json` and rendered into the help toast
and the context bar, so the page never hardcodes a chord. `mod+` displays as `⌘` on Apple
platforms and `ctrl+` elsewhere.

`ctrl+tab` is deliberately *not* the recent-files gesture: browsers reserve it and it
cannot be intercepted reliably. The JetBrains-style MRU switcher is `mod+e`; `alt+[` and
`alt+]` still move positionally through the tab strip.

## Running things

Three gestures, three different runtimes:

| gesture | what runs | where |
|---|---|---|
| `▶ cell` | one notebook cell | the tab's kernel |
| `▶ file` (`mod+alt+enter`) | the whole `.py` file as a **script** | the tab's kernel, with `__main__` and an argv |
| `▶ sel` | the current selection | the tab's kernel |
| exec strip, `live` | typed expression | the tab's kernel, sharing the notebook namespace |
| exec strip, `isolated` | typed expression | the agent session's safepyrun sandbox |

The exec strip's two scopes are genuinely different runtimes rather than a flag. `live`
shares the notebook's namespace. `isolated` routes through the sandbox, where writes are
discarded and escapes refused — which is what makes the label true. An earlier
`scope='isolated'` that shallow-copied the namespace dict was not isolated at all, because
a mutating call still reached the real object.

Scripts start at the containing Git repository root by default. The `cwd` pill sets a
per-tab directory or returns to automatic discovery.

## Streaming

Anything long-running is Server-Sent Events over a POST, not polling. Three streams matter:

- `/nb/run/stream` — cell outputs as they are emitted, plus execution state.
- `/nb/ask/stream` — agent tokens, tool calls, approvals and compaction notices.
- `/nb/debug/stream` — debugger state and output while stopped at a breakpoint.

`postEvents` in `lee-ide.js` is the single reader: it POSTs, then parses `event:`/`data:`
frames off the response body, buffering on `\n\n` boundaries. Frames carry JSON, and the
handler decides what to swap.

The reason for POST-with-SSE rather than `EventSource`: the request bodies are large
(notebook context, attachments, selections) and `EventSource` is GET-only.

## Markdown and the raw-HTML rule

Markdown reaches the page from three places, and they are not equally trusted:

- **Fetched pages and model output** — cannot execute raw-HTML fences. Research digests and
  agent responses go through `mdhtml`'s bounded conversion.
- **Authored notebook Markdown** — may still use raw HTML, because you wrote it.

This is a per-source decision (`renderMarkdown(el, text, allowRaw)`), not a global setting,
so pasting a web page into a notebook does not silently gain privileges.

## Variables

The variable panel is dhrishti's node tree over the live kernel namespace, proxied through
the workspace's own app rather than fetched from the kernel's inspector port directly. See
[Multi-workspace architecture](multi-workspace-architecture.md#kernel-transports) for why.

Values expand lazily, grids render in place, and `vars/promote` lifts a value into a new
cell. A script run populates the panel with everything it defined when it finishes, which
is the main reason running a `.py` file as a script is a first-class gesture rather than a
notebook workaround.

## Persistence in the browser

| what | where | why |
|---|---|---|
| editor drafts | IndexedDB (`leela-editor-drafts`) | survives a crash before save |
| tab buffers | localStorage | unsaved text across reloads |
| breakpoints | localStorage | per path, with condition details |
| split layout, open panels | localStorage | restores the workspace shape |
| editor prefs (font, size) | localStorage | applied before first paint |
| recent-tab order | in-memory + localStorage | drives the `mod+e` MRU switcher |

None of it is authoritative. Everything here is a convenience over server state, and losing
it costs a reload, not work.

## Where this is going

`lee-ide.js` is one 6,000-line file with ~200 top-level functions and ~40 `window.lee*`
globals, most of which exist because server-rendered markup calls them from inline
`onclick` handlers. The planned split mirrors the Python blocks — one module per block,
bundled by the existing esbuild setup in `leela/web/src/` so what gets served does not
change. `tests/assets.py` already reads the whole static tree rather than one file, so that
split does not require touching the assertions that describe this behaviour.
