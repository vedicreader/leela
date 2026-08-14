# The desktop app, and the browser inside it

Why the packaged app is built the way it is. The source says what each piece does. This says
why it could not be simpler.

## Three processes, one window

A packaged Leela is a native window, an ordinary Leela server, and a headless Chrome.

The window is pywebview over the platform's own webview. It holds the main thread, because
Cocoa refuses to create a window anywhere else. The server therefore runs on a daemon thread,
and `leela_app.py` exists to arrange that order: it picks a port, starts `leela --app` on a
thread, and gives the main thread away. An app bundle calling `leela.cli.main` directly would
never get the thread back. `leela --shell webview` does the same from a checkout. That is why
`serve_ide` takes `shell` separately from `app_window`. `app_window` is the workspace shape.
`shell` is what opens on top of it.

The port is chosen rather than fixed. A frozen app is double-clicked, sometimes twice, and
sometimes while a terminal `leela` already holds 5001.

Chrome is not in the bundle and does not run inside the window. It runs beside it, on the
persistent CDP profile fossick already keeps. That is the whole point. Its cookies are why a
page reads here and not through a plain fetch. Chrome allows one process per profile, so
anything wanting a second browser (screenshots, tests) must name its own.

## Chrome starts when a page needs it, not at launch

A headless Chrome is several hundred megabytes across a dozen processes, more than the
workspace beside it, and most sessions never open a web tab. So the first page that wants one
starts it and pays for it. `LEELA_CDP_EAGER=1` trades that memory back for the second or two
the first tab would otherwise wait.

That makes availability and liveness two different questions. `Browser.available()` asks
whether a Chrome could be driven at all. It must stay cheap, because research asks it every
time a result is clicked. `Browser.alive()` asks whether one can be driven right now, and
starts it. `/browser/ready` answers the first.

## Why the server stopped importing dhrishti

`dhrishti.core` imports IPython, pandas and numpy at module scope, which is right for
something whose job is formatting live values. Leela's server never formats one. It wanted two
constant tables and a nine-line registry reader, and was paying 660ms and 45MB for them.

`leela/core/inspectors.py` holds those. dhrishti stays authoritative. `tests/test_inspectors.py`
imports the real thing and fails if the two drift, including a round trip where dhrishti's own
`register()` writes an entry and Leela's reader reads it. The kernel side is untouched.
`blocks/runtime/kernels.py` still bootstraps the real dhrishti into every kernel it launches,
which is why the dependency stays.

## Which folder a double-clicked app opens

A command line answers "which project" every time it is typed. An application icon never asks,
so `core/projects.py` remembers. Two lists, deliberately separate: `folders` is the current
open set, kept in step as roots are added and dropped, and `recent` is a longer memory that
outlives closing a project. A folder deleted or unmounted since is dropped on read rather than
offered and then failing.

`note_folder` unions rather than replaces, because under `--app` each folder is its own
`Workspace` and each would otherwise record itself as the whole session.

Launch order is the folders the desktop handed over, then the set open at last close, then
none. None opens the welcome screen. The old fallback was the home directory, which handed
kosha every file the user owns to index.

Getting a folder in without typing a path needs native help in three places:

- A browser file input yields file contents, never a directory path. `ShellApi.pick_folder`
  is the platform chooser, reached from the page as `window.pywebview.api`.
- macOS delivers "Open With" and a Dock-icon drop to the already running process as the `odoc`
  Apple Event, through no argv at all. `watch_open_events` answers it. A process that does not
  answer simply ignores the request. An Apple Event handler must be a selector on an
  Objective-C object, which is what `_OpenHandler` is for.
- Windows has no equivalent to answer. Explorer starts a new process with the path in argv,
  which `leela_app.folders()` already reads.

A folder arriving after startup goes in through the HTTP route rather than the `Workspace`
object, which the server owns on another thread and another event loop.

## The inline browser

Chrome renders. Leela draws JPEG frames on a canvas and forwards mouse and keyboard back.
Nothing parses or executes web content in Leela's process. The only structured thing that
crosses back is the Markdown `fossick.to_md` already produces for research.

Every navigation goes through `fossick.core.check_url`. That is not decoration: the browser
runs on the same loopback interface as Leela's own unauthenticated server, so `127.0.0.1` and
friends are refused unless `FOSSICK_ALLOW_PRIVATE` says otherwise.

`markdown()` falls back to `innerText` where research does not need to. `to_md` runs
readability first, which returns nothing at all for an application. An application behind a
login is most of the reason to read a page in here rather than fetch it.

### Traps in the CDP layer

These are the things that look removable and are not.

**A websocket belongs to the loop that created it.** Reusing one across loops does not raise.
It reports itself open and then never completes a read, which is a hang rather than an error.
A `Workspace` outlives any one loop, so `Browser.cdp()` checks.

**Chrome only composites a page it believes is visible**, and a target opened in the background
is not. Without `bringToFront` and focus emulation, `startScreencast` succeeds and then never
emits a frame. Focus emulation is what keeps it rendering once the next inline tab takes the
front, which is what lets two tabs hold live pages at once.

**Every frame must be acked** or the stream stops after one. The frame's own `sessionId` is
Chrome's ack token and has nothing to do with the CDP session id.

**A cancelled CDP write wedges the connection every tab in the workspace shares.** `websockets`
cannot be interrupted part-way through a send and stay usable. So CDP calls driven by a socket
are shielded. Started means finished. The screencast teardown runs detached, after the handler
is gone, because that handler is usually unwinding precisely because its task was cancelled.

**A cast has an owner** for the whole life of its socket, across every pause for a hidden
window and every resize. Handing that token back to `stop_cast` is what stops a slow teardown
from switching off a stream a reopened tab has just started.

**The viewport is pinned to the panel** so panel (x, y) is page (x, y). The alternative is
mapping every event through the frame metadata, which drifts the moment the page scrolls.

### What the picture costs

Frames cross the socket as raw JPEG rather than base64 inside the JSON envelope everything
else uses. That is a third fewer bytes, and the client hands it straight to
`createImageBitmap` instead of decoding a `data:` URL first. Decoding happens off the main
thread. A frame arriving mid-decode is dropped rather than queued, because latency on a
picture nobody will see is worth nothing. Hiding the window stops the encoding only. The tab
stays open and the page stays loaded.

`Input.dispatchKeyEvent` accepts a fixed set of fields. Anything else a DOM keydown carries is
dropped rather than forwarded, so a malformed event costs a keystroke instead of closing the
socket with a CDP error.

## Building it

`setup_app.py` is about the interpreter, not the bundle. py2app copies the stdlib's extension
modules out of the running Python as files. A uv-managed standalone build is what a Leela
checkout normally has, and it links several of them into the binary instead. `zlib` is one. So
the build dies minutes in on an import with no file behind it. When the active interpreter is
not a framework build, `setup_app.py` makes `packaging/.app-venv` against one that is and
re-runs itself inside it. `LEELA_APP_VENV` marks that re-exec, so an environment that is
somehow still not a framework build reports it rather than forking interpreters forever.

The platform definitions are `packaging/macos/setup.py` and `packaging/windows/setup.py`.
`tests/test_packaging.py` covers what a green build would not catch. A bundle missing its
fonts. A window that cannot load `http://127.0.0.1` for want of the `NSAllowsLocalNetworking`
exemption. A Windows build that zips modules a kernel subprocess then cannot import.
