# The thin Mac app

Leela.app 1.0 is a small Swift launcher. It owns the windows. Python runs headless as its child: `leela --app --shell none`. The Python packages do not ship in the app. They come from a signed environment lock, which has its own number and its own channel. A new lock reaches people without a new app build.

The old py2app app (`make ship`, `docs/desktop.md`) stays for one release while this one ships.

## What is in the bundle

```
Leela.app/Contents/
  MacOS/Leela              the Swift launcher (packaging/mac)
  Helpers/uv               the pinned uv (packaging/uv.version, packaging/uv.sha256), signed with the app
  Resources/Lock/          the bootstrap lock: manifest.json, manifest.sig, pyproject.toml, uv.lock, .python-version
  Resources/lock-keys.pub  the two public keys that may sign a lock (main and emergency)
  Resources/childenv.json  the clean child environment, shared with tools/lock.py
  Info.plist               bundle id org.vedicreader.leela, document types, NSAllowsLocalNetworking
```

- The bundle id is the same as the old app, so WebKit storage carries over.
- `make -C packaging/mac verify` fails above 60 MB on disk or 25 MB zipped.

## Where the app keeps its files

```
~/Library/Application Support/Leela/
  locks/<n>/                 each lock the app accepted
  envs/<hash16>/             one env per lock hash; .leela-env.json is written last
  python/                    the managed Pythons uv downloads
  state.json                 {current, previous, pending, highest_n, bad: []}
  logs/sync-<hash16>.log, logs/server.log
  run.lock                   flock: one launcher at a time
~/Library/Caches/Leela/uv    the uv cache
```

- The lock hash is sha256 over the name and the bytes of `pyproject.toml`, `uv.lock` and `.python-version`, then `uv` and the uv version. Swift (`LockHash`) and Python (`lock_hash`) compute the same value; both test suites pin one vector.
- The app builds a new env in place in `envs/<hash16>`. The marker is written last. A folder with no marker is a partial build, and garbage collection removes it.
- The app switches env only at launch or at "Restart to update". It writes `state.json.tmp`, then renames it.
- When `/health` does not answer in 120 s, or a new env crashes twice before it is ready, the app goes back to the previous env and adds the hash to `bad`. The menu item "Leela > Use Previous Version" does the same by hand.
- Garbage collection keeps current, previous, pending and the env in use. The app runs `uv cache prune` once a week.

## The child environment: `packaging/childenv.json`

Swift (`ChildEnv`) and `tools/lock.py` read the same file.

- `drop` and `drop_prefixes`: names removed from the launcher's environment. These include `VIRTUAL_ENV`, `CONDA_PREFIX`, `PYTHONHOME`, `PYTHONPATH`, `PYTHONSTARTUP`, `PYTHONUSERBASE` and every `UV_*`.
- `set`: `LANG` and `NO_COLOR`, for the launcher's own uv runs only.
- `uv`: what the launcher's own uv runs get (the build, an extra, `uv cache prune`), and nothing else. `UV_NO_CONFIG=1`, the cache, the Python folder, `UV_PYTHON_PREFERENCE=only-managed`, the exact Python, the env folder, `UV_FROZEN=1`, `UV_NO_PROGRESS=1`, `UV_LINK_MODE=clone`.
- `server`: what the server also gets: `PYTHONUNBUFFERED=1`. The server gets the person's environment, less `drop` and `drop_prefixes`, with `tool_dirs` on `PATH`. It gets no `uv` key, no `VIRTUAL_ENV`, no `PYTHONNOUSERSITE` and not the env's `bin`, because every kernel, terminal, agent shell and project `uv` run inherits the server's environment. The launcher starts `envs/<hash16>/bin/leela` by its absolute path, and its shebang names the env's Python, so the server needs none of them.
- App 1.0.0 gave the server all of these. A newer lock still runs under it: `leela.core.host.setup` first takes out every `UV_*`, `PYTHONNOUSERSITE`, `NO_COLOR=1`, a `VIRTUAL_ENV` that is the env, and the env's `bin` on `PATH`. The login shell and Leela's stored values then fill in the person's own, `UV_*` among them: a `UV_INDEX_URL` the person set reaches their kernels, terminals and project `uv` runs, as in the old app. The app's own uv settings go only to the launcher's uv runs.
- The language server of the `langserver` extra is in the env's `bin`, so in host mode `find_server` also looks in the server's own scripts folder.
- An agent's shell runs the console scripts of the owner's packages in the env (`host.AGENT_TOOLS`: `ramabana`, `kosha`, `exhash`, `fossick` and the rest), never `python`, `pip` or `uv`. At each start the server links them into `~/Library/Application Support/Leela/bin` (`host.link_tools`), so an env switch changes them, and only the agent's shell gets that folder on `PATH`, after the project's `.venv/bin` and before the person's own folders. The old app had none of them there.
- A new launcher with an env from an older lock (Use Previous Version) runs a server that does not look in its scripts folder, so the Python language server is missing until the person updates again.
- `sync`: the build command, `uv sync --frozen --no-install-project --project <locks/n>`. `extra` adds `--extra <name>` per extra; `inexact` adds `--inexact` when an extra goes into a running env.
- `server_args`: `--app --shell none --port <port> --gateway-port 0`.

## The contract between the launcher and the server (API 1)

The launcher starts the server with these environment variables:

| Name | Value |
|---|---|
| `LEELA_HOST_URL` | `http://127.0.0.1:<port>` of the launcher's control server |
| `LEELA_APP_VERSION` | the app version, such as `1.0.0` |
| `LEELA_APP_BUNDLE` | the path of `Leela.app` |
| `LEELA_LOCK_N` | the number of the lock the env came from |
| `LEELA_ENV_HASH` | the lock hash of the env |
| `LEELA_UV` | the path of the bundled uv |

The token is never in argv, the environment, a file or a log. The launcher starts the server with a pipe as stdin, writes one line `<token>` to it right after the start, and closes its end. In host mode the server reads that one line first (`leela.core.host.take`, 5 s at most), keeps it in memory, and reopens stdin on /dev/null. No line, an empty line or a late line stops the server with a plain error. A `LEELA_HOST_TOKEN` in the environment is ignored, with a warning. The server also takes `LEELA_HOST_URL` out of its environment, so no kernel, terminal or agent shell gets it. In host mode the server does not use the old extras folder, and the login shell or a stored value cannot replace `PYTHONPATH`, `VIRTUAL_ENV` or any `LEELA_HOST_*`, `LEELA_LOCK_N`, `LEELA_ENV_HASH`.

### Control routes in the launcher

The control server listens before the launcher starts the server. Only the server calls it, and every request carries `Authorization: Bearer <token>`. A wrong token gets 401.

| Route | Body | Answer |
|---|---|---|
| `POST /confirm` | `{question}` | `{answer: bool}` from an NSAlert. Any other answer is "no window", never a No. |
| `POST /extras` | `{name}` (`mlx`, `llama`, `langserver`) | `{ok}`; the state is in `/status` |
| `POST /update` | `{kind}` (`app` or `lock`) | `{state, line}` |
| `GET /update` | | `{state, line}`; `state` is `idle`, `running`, `ready`, `same`, `unavailable` or `error` |
| `POST /restart` | `{}` | `{ok}`; the launcher stops the server, switches env if one is pending, and starts it again |
| `GET /status` | | `{app_version, api, brew, lock: {current_n, newest_n, newer, needs_app, app_min}, extras: {name: {state, log}}, env}` |
| `POST /grant` | `{nonce, path}` | `{ok}`: true once, when the launcher issued `nonce` for `path` in the last minute |

The server maps the launcher's `ready` to the page's `done`, so "Restart to update" uses the existing `/update/restart` route.

### Server routes for the launcher

| Route | Proof | Answer |
|---|---|---|
| `GET /health` (and `HEAD`) | no | `{status: "ok", version, lock_n}` |
| `POST /hub/open?path=&grant=` | a one-time `grant` | the open row; with a grant the server asks the launcher's `/grant`, and on yes the folder and each `also` folder are trusted, as a Finder or Dock open was in the old app |
| `POST /hub/grant?path=&grant=` | a one-time `grant` | `{ok, root}`; a folder picked in the app's own dialog opens next with no question |
| `GET /app/menu.json` | none | `{menus: [{title, items: [{title, action \| selector \| js, key, mask} \| {sep: true}]}]}` from `blocks/keys/menus.BAR` and the keymap |
| `GET /app/recent` | none | `{recent: [path]}` for the Dock menu |
| `GET /app/sites` | none | `{sites: [{id, name, root, url}], port}`: each workspace and its own port, for window keys and after a restart |
| `GET /hub/go/<slug>` | none | 307 to that workspace's own port; 404 when no such workspace is open. It builds nothing |

Each workspace answers on a loopback port of its own (`WorkspaceHub.bind`, `listen`): a second uvicorn server on the same loop serves the same guarded app, and `site_for` picks the workspace by the port a request came in on. A workspace gets the port it had last time (`workspaces/ports.json`) when nothing listens there, so the page's origin and what it keeps per origin (layout, theme) stay. The main port is the home window's and the launcher's. Cookies are shared by every port of one host; no Leela route reads a cookie or the session, and a test checks that no page sets one. A page cannot post to another workspace: the guard refuses a change whose `Origin` is another port.

Merge plan: this hub change is Leela code the old py2app app also runs (`leela_app.run` opens its first windows at `/hub/go/<slug>`). It goes to `main` with the thin-app branch; before that merge, `make ship` builds the old app and its windows are checked by hand: open two folders, drop a file, quit and reopen, and each window keeps its layout.

All of these sit behind `LoopbackHostGuard`, so a page on another host name gets 421. The launcher sends the server nothing secret: a process that takes the server's port first gets only a nonce for one path, good once, and never the token.

### The window bridge

The launcher injects `window.pywebview.api` into each page, so the page JavaScript does not change: `open_folder`, `pick_folder`, `recent`, `set_background`, `set_title`. Each call goes through one `WKScriptMessageHandlerWithReply`. `BridgeRouter` maps a call to an action and is tested without a window.

## The lock

The pinned project is `packaging/lock/`: `pyproject.toml`, `uv.lock`, `.python-version`. `tools/lock.py make` writes it.

- `leela==<V>`, `requires-python = "==3.13.*"`, the exact Python in `.python-version` (3.13.18). 3.13 is the old app's minor: kunda's kernel bootstrap gives a kernel Leela's own packages only when its Python has the same minor, and projects on 3.13 used that in the old app.
- Leela is not on PyPI (the PyPI name `leela` belongs to another project). The lock takes the Leela wheel from GitHub release `V` (`make lock-wheel V=` builds it from the tag and attaches it), and checks its sha256 against the digest GitHub gives.
- The extras `mlx`, `llama` and `langserver` are pinned with `==`. `llama-cpp-python` comes only in the `llama` extra, from abetlen's prebuilt Metal wheel, pinned by URL and sha256.
- `environments` and `required-environments` are macOS arm64 only.
- `exclude-newer` is 7 days before the lock. The owner's own packages are exempt (`exclude-newer-package` set to the lock time). `UV_NO_CONFIG=1` also drops these settings from `[tool.uv]`, so `make lock` passes them as `--exclude-newer` flags too, and `make lock` refuses a `uv.lock` that records no cooldown. A test against a local index shows both sides: an owner's release from yesterday is locked, a third-party one is held back.
- `PIN=<constraint>` adds one constraint, such as `PIN=ramabana==0.2.109`.
- `make lock` refuses another index, an editable, git or path source, a package with no wheel for CPython 3.13 on macOS arm64, and `llama-cpp-python` in the base env.

### The manifest

`manifest.json` is signed into `manifest.sig`.

| Key | Meaning |
|---|---|
| `n` | the lock number; the app refuses a number it already passed |
| `hash` | the lock hash |
| `files` | `{name: sha256}` for the three lock files |
| `leela` | the Leela version in the lock |
| `python` | the exact Python |
| `uv_min` | the uv version the lock was tested with; a newer bundled uv is needed when this is higher |
| `launcher_api_min` | the lowest launcher API that can run it |
| `platform` | `darwin-arm64` |
| `macos_min` | the lowest macOS |
| `download_bytes` | about how much a first install downloads |

### The channel

Each lock is a release `lock-<n>` (`--latest=false --prerelease`) with the three lock files (`.python-version` is the asset `python-version`), `manifest.json`, `manifest.sig` and `tested.json`. The release `lock-channel` holds the pointers, replaced with `--clobber`:

- `channel.json` + `channel.sig`: the stable pointer.
- `channel-test.json` + `channel-test.sig`: the test pointer. `LEELA_LOCK_CHANNEL=test` points an app at it.
- A pointer is `{n, manifest_sha256, published, channel}`. The app refuses a pointer whose `channel` is not the one it asked for (a test pointer served as stable). Pointers do not expire: an expiry would refuse a lock that simply had no change for a long time. The replay check (`n` above `highest_n`), the channel name check and the SSH signatures stay. An old pointer with an `expires` field still parses; the field is ignored.

The app refuses a lock when the signature or a hash is wrong, when `n` is not above `highest_n`, or when the platform or macOS is wrong. It shows "needs a newer Leela app" when `uv_min` is above the bundled uv or `launcher_api_min` is above the app's API.

## Signing keys

The keys are SSH Ed25519 keys:

- `~/.ssh/leela_lock_ed25519` (main) and `~/.ssh/leela_lock_emergency_ed25519` (emergency).
- `make lock-key` makes both with `ssh-keygen -t ed25519`, with a passphrase. It adds them to the agent with `ssh-add --apple-use-keychain`, so the macOS keychain keeps the passphrase. It refuses to overwrite a key. It prints the public keys and writes `packaging/lock/keys.pub`. Commit that file.
- Signing is `ssh-keygen -Y sign -n leela-lock` (SSHSIG). It goes through the agent.
- `tools/lock.py` checks with `ssh-keygen -Y verify` and an allowed signers file made from `keys.pub`. The launcher checks SSHSIG itself with CryptoKit: the key must be one of the two embedded keys, the namespace must be `leela-lock`, and the Ed25519 signature must hold over the SSHSIG signed data.

## The owner's flow

1. `make lock-wheel V=<leela version>`: build the wheel from the tag and attach it to the release.
2. `make lock V=<leela version>`: write the pin, lock with the pinned uv, check, print the hash.
3. `make lock-diff`: what changed against the published lock (`AGAINST=<folder>` compares with a local lock). It flags an owner package version with no git tag.
4. `make lock-test` (`FRESH=1` empty cache, `EXTRAS=1` each extra): build in a temp folder with the same uv, childenv and command as the app. Then `uv pip check`, imports, the server in host mode with a temp `XDG_CONFIG_HOME` and `XDG_DATA_HOME`, `/health`, `/hub/open` on a temp folder, one kernel cell that gives 2, a project with its own `.venv` (a marker module the app env lacks), whose notebook cell runs through `/hub/open`, `/tab/open` and `/nb/run` on the project's Python with no `UV_*`, `PYTHONNOUSERSITE`, app `VIRTUAL_ENV` or app `bin` in its environment, the same cell under app 1.0.0's server environment, a stored `UV_INDEX_URL` that reaches that cell when no app `UV_*` does, an agent's shell in the project that runs `ramabana --help` and `kosha --help` from the linked folder while `python` is the project's, and each extra. The project `.venv` borrows ipykernel from the app env by a `.pth`, so the test needs no network. A pass writes `packaging/lock/tested/<hash>.json`. Commit it.
5. `make lock-publish`: refuses unless the tree is clean and pushed, a passing record for this hash is less than 7 days old, the record's uv is the pinned uv, the test code is unchanged, and Leela is not lower than the last lock (`ALLOW_DOWNGRADE=1` to roll back). Then it signs, makes `lock-<n>`, downloads and checks it, and points the test channel at it.
6. `make lock-promote N=<n>`: copy the test pointer to the stable pointer and check it.
7. `make lock-verify [CHANNEL=test]`: check a channel as the app does.
8. Roll back: publish the old lock content again as n+1.

`make ship-app V=<app version>` builds the app with the lock the stable channel serves, signs it with the Developer ID, notarizes, staples, zips, uploads to `app-v<V>` with `--latest=false`, and writes the cask from `packaging/mac/cask/leela.rb`.

## Update notices

| Newer app | Newer lock | Lock needs newer app | Homebrew | Kind | Update does |
|---|---|---|---|---|---|
| yes | any | any | yes | `app` | the launcher runs `brew upgrade --cask leela`, then restarts |
| no | yes | no | any | `lock` | the launcher builds the new env, then "Restart to update" |
| no | yes | yes | yes | `app-needed` | the notice names the app version that is needed |
| yes, or a lock that needs an app | any | any | no | `download` | the notice opens the release page |

A lock that comes inside a newer app (the bundled lock, with an `n` above the env in use) is not offered: the launcher builds it at launch, behind the setup window, and runs it, with the env it had kept as previous. A failed build leaves the env in use running and offers the lock. After "Use Previous Version" the app's own lock is offered, not forced. Each choice is a line in `logs/setup.log`.

The newest app comes from the `app-v*` releases, not from `releases/latest`. The server never takes a `lock-*` or `app-v*` tag as a Leela release.

## Security notes

- The Python code arrives after notarization. Trust comes from the signed lock and the per-file hashes in `uv.lock`. The pinned uv checks the managed Python.
- Test: change one hash in a copy of a lock; the build must fail.
- An attacker on PyPI can only publish new versions. These reach people only through `make lock`, after the 7-day cooldown, `lock-diff` and `lock-test`.
- An attacker on GitHub cannot sign a lock, replay an older one, or notarize an app. They can hide new locks.
- The private keys are in `~/.ssh`, encrypted with their passphrase, and the keychain keeps the passphrase. Back them up as you back up any SSH key, in a place you choose. Never put them in a git repository, a dotfiles sync, or CI.
- A stolen main key: ship an app update that drops it, and sign with the emergency key.

## Window parity with the old app

The old app's window layer is pywebview's Cocoa backend (`webview/platforms/cocoa.py`, here C), `kavacha/window.py` (K), `leela/desktop.py` (D) and `leela_app.py` (A). The menu bar comes from `leela/blocks/keys/menus.py` (M) in both apps. The thin side is `packaging/mac/Sources/Leela/Windows.swift` (W) and `AppDelegate.swift` (AD). Status: same, fixed (it was missing or different, and now matches), or different (on purpose, with the reason).

### Menus and keys

| Behaviour | Old app | Thin app | Status |
|---|---|---|---|
| Menu rows from `BAR`: keymap actions, `Std` selectors, `Js` rows, `__app__` rows in the app menu | M:82, K:650 `menu_bar`, C:1021 | `/app/menu.json` (M:142), W:309 `build`, W:380 `item` | same |
| A keymap action row runs `leeAct("<action>")` in the focused window | D:40 `_act`, K:672 `eval_js` | W:171 `run(js:)`, W:295 `MenuRunner` | same |
| Chords onto rows, selectors onto `Std` rows (the patch `install_menu_patch` / `_decorate`) | K:687, K:707 | the server sends `key`, `mask` and `selector`; W:380 sets them, with nil target so the responder chain gets the selector | same |
| ⇧ in a chord | K:620 `mac_key` gives a lower case key plus the shift flag | W:423 `appKit` gives the shifted character with no shift flag (`O`, `?`, `!`) | fixed. AppKit matches shift by the character it makes. With a lower case key and the shift flag, no ⇧ chord fired from the menu, and ⌥I ran ⌥⇧I (Interrupt kernel) instead of Live / isolated. The page gets each key first (WebKit), so only keys the page did not take reached the menu. The old app has the same fault: `mac_key` belongs to kavacha, fix it there. The punctuation and digit map is the US keyboard's. |
| Cut ⌘X, Copy ⌘C, Paste ⌘V, Select All ⌘A | `Std` rows (M:90) and C:512 `keyDown_` | `Std` rows; the web view is the first responder (W:70) | same; the first responder is now set when the window opens (fixed: before, nothing was first responder until a click) |
| Undo ⌘Z, Redo ⇧⌘Z | C:533 `keyDown_` runs the native undo manager when the page does not take the key | W:364 adds Undo and Redo to Edit, selectors `undo:` and `redo:` to the window, which uses the web view's undo manager | fixed. The page sees ⌘Z first, so the editor's and the notebook's own undo still win. |
| Enter Full Screen ⌃⌘F | `Std` row (M:101) | `Std` row; windows are `fullScreenPrimary` (W:70) | same |
| Minimize ⌘M, Zoom, Bring All to Front | `Std` rows (M:122) | `Std` rows; the Window menu is `NSApp.windowsMenu` | same |
| Close Window ⌘W | C:540 `keyDown_` calls `performClose:` | W:372 adds "Close Window" to File | fixed |
| About, Services, Hide ⌘H, Hide Others ⌥⌘H, Show All, Quit ⌘Q | C:1070 `_add_app_menu` | W:314 to W:329 | fixed (Services, Hide Others and Show All were missing) |
| "Use Previous Version", "Show Server Log" | none | W:318 | thin only |
| The launcher's own chords (Quit, Hide, Close Window ⇧⌘W, Undo, Minimize, Full Screen) | kavacha's `LAUNCHER_ROWS` | `/app/menu.json` gives `launcher` (`menus.launcher_json`), and `Menus.own` puts each chord on its row; `Menus.launcher` is the same list before the server answers, and a Swift test keeps the two equal | same |
| A chord with shift on a key with no case (⌥⇧↩) | the page | `LeelaBar` fires the row whose chord is exactly the event's; AppKit let ⌥↩ take ⌥⇧↩ | fixed |
| A menu bar before the server answers | built before `webview.start` (K:515) | W:359 `fallback` at launch (AD:37); replaced when `/app/menu.json` comes (AD:84), kept when it does not | fixed: before, the setup window had no ⌘Q, ⌘C or ⌘H |
| Zoom keys ⌘+ and ⌘- | none | none | same: the keymap has none |
| Find in page | the keymap's `find_in_file` ⌘F | the same row | same |

### Windows and the page

| Behaviour | Old app | Thin app | Status |
|---|---|---|---|
| Size 1440×900, smallest 900×560 | K:51, K:54 | W:41, W:70 | fixed (it was 1400×900 with no minimum) |
| Bridge: `open_folder`, `pick_folder`, `recent`, `set_background`, `set_title` | K:82 `ShellApi`, D:30 | `Bridge.route`, W:200 to W:206 | same |
| Background repaints the window and what WebKit draws past the page | K:67 `paint_background` | W:215 `paint` | fixed (the area past the page edge was not painted) |
| Smart quotes, dashes and autocorrect off | K:379 `quiet_text_substitution` | W:56, called at AD:36 | fixed: before, `"` typed in the editor could become a curly quote |
| Native context menu | empty unless debug (C:508) | empty unless `LEELA_WEBVIEW_DEBUG` (W:11) | fixed: before, it offered Reload, which drops the page |
| Web inspector | `LEELA_WEBVIEW_DEBUG` (K:516, C:657) | `isInspectable` with the same variable (W:76) | fixed |
| One window per folder, raised and not opened twice | K:466 `open_window`, `keyed_windows` | `show`, keyed by the workspace's slug, which `learn` takes from each `/hub/open` row and from `/app/sites` | same |
| Where a workspace's page is | `http://<slug>.localhost:<port>/` | `http://127.0.0.1:<port>/`, a loopback port of the workspace's own; the main port is the home window. After a restart, `reopenWorkspaces` (AD) asks `/app/sites`, opens any other folder again with a grant, and loads each window's new URL | fixed: the app's process never reached a `*.localhost` name (it waited 90 s, with Local Network on); an IP address needs no lookup |
| A new window waits for its page, and a page that does not come says so | K:480 `_point`: `wait_for_http`, then the page, else an "unreachable" page | W:123 `point`, W:132 `answers`; W:148 a failed load and W:158 a crashed page are not left blank; W:100 `reuse` loads a failed page again and takes the new title on the next open | fixed: before, the window loaded at once and kept a blank page on any failure, and a second drop only raised it |
| A window comes forward and the app activates | K:454 `bring_forward`, C:748 | W:91, W:182 call `NSApp.activate()` | fixed |
| Closing a window hides it; the Dock icon brings the last one back as it was | K:255 `dock_delegates` | W:174 `windowShouldClose`, W:182 `reopen`, AD:180 | fixed: before, the window and its page were gone, and the Dock icon opened the home page |
| Closing the last window keeps the app | K:392 `keep_running_in_dock` | AD:178 | same |
| `alert()` | C:190, activates the app | W:271, activates the app | same |
| `confirm()` | C:217 | W:275 | same |
| `prompt()` (the agent's round name) | C:228 | W:280 | fixed: before, `prompt()` gave null and the round could not be named |
| `<input type=file>` | C:239, takes the accepted types | W:287, takes "directories" | different: WebKit gives the accepted types only through a private API |
| `<a download>` and attachments | `ALLOW_DOWNLOADS` is off (C:279), so a download link showed the file in place of Leela | W:226 `policy`, W:234 `saves`, W:253, W:256: a save panel in Downloads | fixed in the thin app (it also showed the file in place of Leela) |
| Links out of the page | C:261, C:272: `target=_blank` opens the browser; a plain link changed the window | W:226: a click to http, https or mailto opens the browser; the server's pages stay; anything else is refused | different, on purpose: a plain link no longer replaces Leela |
| `window.open` of a server page | nothing (C:261 returns nil) | W:266 opens or raises that folder's window | different; the page calls it only outside the desktop shell |
| The presenter's audience popup (`window.open('', …)`) | nothing | nothing | same |
| A file or folder dropped on the window | WebKit loads it in place of Leela | W:29 `performDragOperation`, W:77: a drop from another app goes to `application(_:open:)` (AD:111), as a Finder open: a folder opens its own window; a file opens in its folder's window or the loose window, and the server asks before it adds the folder. A drag inside the page (a tab, a cell) stays the page's. | fixed: the owner chose Finder's behaviour |
| `window.print()` | C:394, a print panel | no print panel | different: no page calls it |
| Back navigation by the Delete key | turned off (C:283, C:649) | WebKit has it off by default; swipes are off | same |
| Clipboard (`navigator.clipboard.writeText`) | WKWebView | WKWebView | same |
| Notifications (`new Notification`) | none: WKWebView has no Notification API | none | same; the page says so |
| Microphone and camera | none: no page uses `getUserMedia`; the voice is `speechSynthesis` | none; no `NSMicrophoneUsageDescription` and no audio entitlement | same. A feature that records needs `NSMicrophoneUsageDescription`, the `com.apple.security.device.audio-input` entitlement and `requestMediaCapturePermissionFor`. |
| Screen capture (`getDisplayMedia`) | none in WKWebView | none | same; the page falls back |

### Folders, the Dock and quitting

| Behaviour | Old app | Thin app | Status |
|---|---|---|---|
| `open_folder` from the page asks first | A:143 `on_page_folder`, trusted false | W:200, AD:125 with no grant | same |
| `pick_folder` trusts the picked folder | K:91, A:115 `on_picked = grant` | AD:159 and `/hub/grant` | same |
| Finder and Dock open events, `application:openFile(s):` | K:272, K:551 `watch_open_events`, K:537 `open_paths` | AD:111 `application(_:open:)` | same; one path, so no two-second de-duplication is needed |
| Opens before the server is ready | `on_ready` (A:145) | queued, then opened on every ready (AD:90) | fixed: before, a queue made during a restart was dropped |
| A file from Finder opens in the folder that holds it, else the loose window | A:175 `open_file` | AD:145; the server finds the folder (`site_covering`) | same |
| The loose window refuses the file: ask to add its folder | A:183 | AD:150 | fixed |
| Window title after a file open | the folder's name, or the file's in the loose window (A:187) | the file's name | different; the page sets the title when it loads |
| A question from the server (`/confirm`) | A:197 opens a window when none is visible | AD:196 asks on the key window, a visible one, or the last closed one brought back (W:188) | fixed: before, the sheet could go on a hidden window and wait for ever |
| Dock menu: 8 recent folders, "No recent folders" when none, the path as tooltip | K:222 `dock_menu` | W:438 `dock`, AD:173 | fixed (it was 10 rows, an empty menu, and no tooltip) |
| Quit stops kernels and servers | K:310 `quit_cleanly`, up to 15 s | `applicationWillTerminate` (AD): the windows go at once and drop their pages (`hideAll`), then SIGTERM to the server, SIGKILL only after 15 s. The server waits at most `QUIT_GRACE` (1 s) for open requests, then stops kernels, terminals and dev servers: about 1.3 s with two workspaces and two kernels | fixed: every window holds an endless `/fs/events` stream, so uvicorn never finished a SIGTERM; each quit took the full 15 s and ended in SIGKILL |
| SIGTERM to the app quits as ⌘Q does | K:349 `quit_on_sigterm` | AD:188 | fixed: before, SIGTERM killed the launcher and left the server running |

`menu_json` builds the launcher's menu from kavacha's vocabulary in Leela. It belongs in kavacha, next to `menu_bar`, with the shift fix in `mac_key`.

### The automated checks

`make -C packaging/mac test` writes `build/menu.json` from the Python source with an empty keymap folder, then runs the Swift tests with it. `Tests/LeelaTests` builds the launcher's menu bar from that file and, with no window on screen:

- each row has its key and mask;
- a key-down as the US keyboard sends it reaches its row through `NSMenu.performKeyEquivalent`, and the row runs `leeAct("<action>")` through a runner the test gives, or sends its selector to a probe;
- no two different rows share a chord, and no action row takes ⌘Z;
- Cut, Copy, Paste and Select All stop at the web view in the responder chain, and Undo and Redo at its window;
- the navigation policy, the download rule, hiding on close, the context menu, the background and the Dock menu.

`tests/test_packaging.py` checks that the launcher keeps kavacha's sizes, Dock length and text substitution keys.

The tests send keys to the menu, not to a loaded page. A page that acts on a chord and does not call `preventDefault` would run the action twice, once in the page and once from the menu. Only the manual check below sees that.

## Manual checks of the windows (no automated test puts a window on screen)

1. A folder from Finder (drag on the Dock icon, "Open With") opens its own window with no question.
2. "Open Folder…" in a page opens the app's folder dialog; the folder opens with no second question.
3. A page that asks to add a folder shows the app's dialog; No refuses it.
4. Every menu bar row runs its action in the front window; Cut, Copy and Paste work in the editor.
5. The Dock menu lists recent folders; one opens its window.
6. A theme change repaints the window background; a tab title change retitles the window.
7. Closing the last window (⌘W or the red button) keeps the app and its server running; clicking the Dock icon brings that window back with its tabs as they were.
8. With the editor focused, ⇧⌘P opens the palette once, ⌥I toggles Live / isolated (not Interrupt), ⌘Z undoes in the editor and in a plain text field, and ⌥⇧1 focuses Files. Each action runs once.
9. A file's "download" button opens a save panel in Downloads, and Leela stays on screen.
10. The agent's "round" button asks for a name in a text field.
11. Typing `"` and `--` in the editor gives `"` and `--`, not curly quotes or a dash.
12. A right-click on an empty part of the page shows no Reload row.
13. `kill <launcher pid>` quits Leela, and the server and its kernels stop.

`make -C packaging/mac lock-test-launcher LOCK_DIR=<lock> WORK=<empty folder>` runs the built launcher's headless `--lock-test`: it builds the env with the bundled uv and the Swift code, with no window. Its env hash equals the one `tools/lock.py` prints.

## End-to-end checklist on a clean macOS user (step 19)

1. `brew install --cask vedicreader/tap/leela` on a new macOS user with no Python and no uv. The first run is online: the setup window shows each phase, then a window opens.
2. Quit, turn the network off, open Leela. It starts with the env it has.
3. Turn the network off with no env (remove `~/Library/Application Support/Leela/envs`). The setup window says it needs the internet and tries again by itself when the network comes back.
4. Publish lock n+1 to the test channel. Start the app with `LEELA_LOCK_CHANNEL=test`. The notice offers the update; Update builds the env; "Restart to update" switches to it; `/health` shows the new `lock_n`.
5. "Leela > Use Previous Version" goes back to lock n.
6. Publish a lock whose server cannot start. The app goes back to the previous env by itself and marks the hash bad.
7. Ship app 1.0.1; the notice offers it; Update runs `brew upgrade --cask leela` and restarts into 1.0.1.
8. Uninstall with `brew uninstall --zap --cask leela`; the folders in the zap list are gone.

### First lock update: ramabana 0.2.110

App 1.0.0 embeds lock 1, which pins what Leela uses today (ramabana 0.2.109). Lock 2 changes only ramabana, with no new app build. This is the first real test of the channel.

1. Lock 1, before `make ship-app V=1.0.0`: `make lock-wheel V=<leela version>`, then `make lock V=<leela version> PIN=ramabana==0.2.109`, `make lock-test FRESH=1 EXTRAS=1`, commit the record, `make lock-publish`, `make lock-promote N=1`, then `make ship-app V=1.0.0`.
2. Lock 2: `make lock V=<leela version>` with no `PIN`. ramabana is the owner's package, so the 7-day cooldown does not hold back 0.2.110.
3. `make lock-diff` shows `~ ramabana 0.2.109 -> 0.2.110` and nothing else, unless ramabana 0.2.110 pulls in new packages.
4. `make lock-test FRESH=1 EXTRAS=1`; commit the record and push.
5. `make lock-publish`. It makes `lock-2` and points the test channel at it. `make lock-verify CHANNEL=test`.
6. On a Mac with app 1.0.0 installed: quit Leela, then `launchctl setenv LEELA_LOCK_CHANNEL test` and open Leela (or start `/Applications/Leela.app/Contents/MacOS/Leela` from a terminal with that variable set). The notice offers the new packages.
7. Update builds the new env while Leela runs. "Restart to update" switches to it; `curl -s http://127.0.0.1:<port>/health` shows `"lock_n": 2`, and `import ramabana; ramabana.__version__` in a cell gives 0.2.110.
8. "Leela > Use Previous Version" goes back to lock 1 (ramabana 0.2.109). Restart with the update again to return to lock 2.
9. `launchctl unsetenv LEELA_LOCK_CHANNEL`, then `make lock-promote N=2` and `make lock-verify`.
