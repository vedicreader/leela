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
- `uv`: what uv gets. `UV_NO_CONFIG=1`, the cache, the Python folder, `UV_PYTHON_PREFERENCE=only-managed`, the exact Python, the env folder, `UV_FROZEN=1`, `UV_NO_PROGRESS=1`, `UV_LINK_MODE=clone`.
- `server`: what the server also gets. `PYTHONNOUSERSITE=1`, `VIRTUAL_ENV`, and the env's `bin` first on `PATH`.
- `sync`: the build command, `uv sync --frozen --no-install-project --project <locks/n>`. `extra` adds `--extra <name>` per extra; `inexact` adds `--inexact` when an extra goes into a running env.
- `server_args`: `--app --shell none --port <port> --gateway-port 0`.

## The contract between the launcher and the server (API 1)

The launcher starts the server with these environment variables:

| Name | Value |
|---|---|
| `LEELA_HOST_URL` | `http://127.0.0.1:<port>` of the launcher's control server |
| `LEELA_HOST_TOKEN` | a random token for this launch |
| `LEELA_APP_VERSION` | the app version, such as `1.0.0` |
| `LEELA_APP_BUNDLE` | the path of `Leela.app` |
| `LEELA_LOCK_N` | the number of the lock the env came from |
| `LEELA_ENV_HASH` | the lock hash of the env |
| `LEELA_UV` | the path of the bundled uv |

The server takes `LEELA_HOST_URL` and `LEELA_HOST_TOKEN` out of its environment at start (`leela.core.host.take`), so no kernel, terminal or agent shell gets the token. In host mode the server does not use the old extras folder, and the login shell or a stored value cannot replace `PYTHONPATH`, `VIRTUAL_ENV`, `UV_*` or any `LEELA_HOST_*`, `LEELA_LOCK_N`, `LEELA_ENV_HASH`.

### Control routes in the launcher

Every request carries `Authorization: Bearer <token>`. A wrong token gets 401.

| Route | Body | Answer |
|---|---|---|
| `POST /confirm` | `{question}` | `{answer: bool}` from an NSAlert. Any other answer is "no window", never a No. |
| `POST /extras` | `{name}` (`mlx`, `llama`, `langserver`) | `{ok}`; the state is in `/status` |
| `POST /update` | `{kind}` (`app` or `lock`) | `{state, line}` |
| `GET /update` | | `{state, line}`; `state` is `idle`, `running`, `ready`, `same`, `unavailable` or `error` |
| `POST /restart` | `{}` | `{ok}`; the launcher stops the server, switches env if one is pending, and starts it again |
| `GET /status` | | `{app_version, api, brew, lock: {current_n, newest_n, newer, needs_app, app_min}, extras: {name: {state, log}}, env}` |

The server maps the launcher's `ready` to the page's `done`, so "Restart to update" uses the existing `/update/restart` route.

### Server routes for the launcher

| Route | Token | Answer |
|---|---|---|
| `GET /health` (and `HEAD`) | no | `{status: "ok", version, lock_n}` |
| `POST /hub/open?path=` | `X-Leela-Host-Token` | the open row; with the token the folder and each `also` folder are trusted, as a Finder or Dock open was in the old app |
| `POST /hub/grant?path=` | `X-Leela-Host-Token` | `{ok, root}`; a folder picked in the app's own dialog opens next with no question |
| `GET /app/menu.json` | `X-Leela-Host-Token` | `{menus: [{title, items: [{title, action \| selector \| js, key, mask} \| {sep: true}]}]}` from `blocks/keys/menus.BAR` and the keymap |
| `GET /app/recent` | `X-Leela-Host-Token` | `{recent: [path]}` for the Dock menu |

All of these sit behind `LoopbackHostGuard`, so a page on another host name gets 421.

### The window bridge

The launcher injects `window.pywebview.api` into each page, so the page JavaScript does not change: `open_folder`, `pick_folder`, `recent`, `set_background`, `set_title`. Each call goes through one `WKScriptMessageHandlerWithReply`. `BridgeRouter` maps a call to an action and is tested without a window.

## The lock

The pinned project is `packaging/lock/`: `pyproject.toml`, `uv.lock`, `.python-version`. `tools/lock.py make` writes it.

- `leela==<V>`, `requires-python = "==3.12.*"`, the exact Python in `.python-version`.
- Leela is not on PyPI (the PyPI name `leela` belongs to another project). The lock takes the Leela wheel from GitHub release `V` (`make lock-wheel V=` builds it from the tag and attaches it), and checks its sha256 against the digest GitHub gives.
- The extras `mlx`, `llama` and `langserver` are pinned with `==`. `llama-cpp-python` comes only in the `llama` extra, from abetlen's prebuilt Metal wheel, pinned by URL and sha256.
- `environments` and `required-environments` are macOS arm64 only.
- `exclude-newer` is 7 days before the lock. The owner's own packages are exempt (`exclude-newer-package` set to the lock time). `UV_NO_CONFIG=1` also drops these settings from `[tool.uv]`, so `make lock` passes them as `--exclude-newer` flags too, and `make lock` refuses a `uv.lock` that records no cooldown. A test against a local index shows both sides: an owner's release from yesterday is locked, a third-party one is held back.
- `PIN=<constraint>` adds one constraint, such as `PIN=ramabana==0.2.109`.
- `make lock` refuses another index, an editable, git or path source, a package with no wheel for CPython 3.12 on macOS arm64, and `llama-cpp-python` in the base env.

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
- A pointer is `{n, manifest_sha256, published, expires, channel}`. The app refuses a pointer whose `channel` is not the one it asked for (a test pointer served as stable) and a pointer past `expires` (180 days after it was published), so an old pointer cannot freeze updates.

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
4. `make lock-test` (`FRESH=1` empty cache, `EXTRAS=1` each extra): build in a temp folder with the same uv, childenv and command as the app. Then `uv pip check`, imports, the server in host mode with a temp `XDG_CONFIG_HOME` and `XDG_DATA_HOME`, `/health`, `/hub/open` on a temp folder, one kernel cell that gives 2, and each extra. A pass writes `packaging/lock/tested/<hash>.json`. Commit it.
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

The newest app comes from the `app-v*` releases, not from `releases/latest`. The server never takes a `lock-*` or `app-v*` tag as a Leela release.

## Security notes

- The Python code arrives after notarization. Trust comes from the signed lock and the per-file hashes in `uv.lock`. The pinned uv checks the managed Python.
- Test: change one hash in a copy of a lock; the build must fail.
- An attacker on PyPI can only publish new versions. These reach people only through `make lock`, after the 7-day cooldown, `lock-diff` and `lock-test`.
- An attacker on GitHub cannot sign a lock, replay an older one, or notarize an app. They can hide new locks.
- The private keys are in `~/.ssh`, encrypted with their passphrase, and the keychain keeps the passphrase. Back them up as you back up any SSH key, in a place you choose. Never put them in a git repository, a dotfiles sync, or CI.
- A stolen main key: ship an app update that drops it, and sign with the emergency key.

## Manual checks of the windows (no automated test opens a window)

1. A folder from Finder (drag on the Dock icon, "Open With") opens its own window with no question.
2. "Open Folder…" in a page opens the app's folder dialog; the folder opens with no second question.
3. A page that asks to add a folder shows the app's dialog; No refuses it.
4. Every menu bar row runs its action in the front window; Cut, Copy and Paste work in the editor.
5. The Dock menu lists recent folders; one opens its window.
6. A theme change repaints the window background; a tab title change retitles the window.
7. Closing the last window keeps the app and its server running; clicking the Dock icon opens a window.

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
