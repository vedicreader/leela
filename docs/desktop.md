# Desktop app

A packaged app combines a native window, a Leela server, and Chrome through CDP.

## Processes

pywebview owns the main thread. `leela_app.py` starts the server on a daemon thread. `leela --shell webview` uses the same shape.

Chrome runs outside the app bundle on fossick's persistent profile. It provides authenticated pages for the inline browser. Screenshots and tests require separate profiles.

## Browser lifecycle

Chrome starts on first page request. `Browser.available()` checks whether Chrome can run. `Browser.alive()` starts or checks the current process. `/browser/ready` reports availability.

## Folder selection

Project folders come from launch arguments, saved folders, native folder pickers, macOS `odoc` events, or Windows argv.

A folder is a workspace, and a workspace is a window. A folder opened while Leela is running goes to `/hub/open`. That builds a workspace with a state file and a kernel pool of its own, registers it with the hub, and returns the `*.localhost` URL for a new window. Open a folder that is already open and it raises the window that folder has. `add_root` is the other action: it puts a second folder in the window you are in.

A file never adds a folder by itself. Finder, `open file.py`, a traceback link in a terminal or an agent hands Leela a file through `/hub/open?path=…&file=…`. When a window already has the file's folder open, the file opens there. When none does, the file opens in the loose window, and one line under the editor asks "This file is in <repo>. Open <repo> as a folder?" with Open and Not now. Only Open sends `folder=1`, which builds the workspace, writes `desktop.json` and moves the folder's loose tabs into the new window. A file that the loose window refuses, such as a `.env`, gets the gate's native dialog. In a folder window, a link to a file outside the open folders is refused, and no folder is added. The agent has no way to add a folder: Leela's host does not implement `add_root`.

### The folder gate

No HTTP route adds a folder by itself. The agent's approved shell commands can reach every route on loopback, and so can a script in any page on this computer. `/hub/open` (a folder, or a file with `folder=1`), `/fs/add_root`, `/fs/add-root` and the new-package action of the pipeline panel take POST only, and each passes through `hub.admit_folder`.

- The gate does nothing when the folder is already open in a window, or when it is the loose root.
- In the desktop app, `leela_app.run()` registers a confirmer. The gate asks in a native dialog in the server's own process: "Add the folder <full path> to <window>?" One dialog shows at a time, on the window in front. With no window, the home window opens first. When no window comes, the request gets a 403 with "No Leela window is open to ask in." and a loose tab keeps its offer.
- A No is a 403 `{ok: false, declined: true, offer, error}`. Nothing is added, written to `desktop.json` or opened. For 10 minutes the gate refuses that folder with no dialog, and a loose tab in it gets no offer. A confirmer that fails counts as a No. A page shows a declined answer as a status line, not as an error.
- Some opens are trusted. A folder from the Dock menu or from Finder gets a grant before its request goes out, and a folder chosen in the native picker gets one through kavacha's `ShellApi.on_picked`. A grant lets one add of that folder through, for 60 seconds. A folder that the page asks for through `pywebview.api.open_folder` goes through `ShellApi.on_page_folder` and is asked about. A second `leela <path>` launch is another process, so the server asks.
- A lesson handoff (`/learn?go`, `POST /learn/open`) adds no folder. In a folder window that does not have the notebook's project open, it answers 409 with the question and an Open button that posts to `/hub/open`. In the loose window the notebook opens as a loose tab, and the offer names the project. For abhyasa's learning copy, one question adds the project and the copies folder (`also=`). With no folder open, a lesson is written to the lessons folder and opens as a loose tab, and the lessons folder is not added.
- The guard refuses a request that changes something, and a websocket, when its `Origin` is not the `Host`, port included, as abhyasa's `LocalOnly` does.
- A window's saved state file still restores the folders it had open, with no question.

In browser mode and dev mode there is no confirmer. The gate then lets an add through only with `Sec-Fetch-Site: same-origin` and an `Origin` equal to the `Host`, which is what a Leela page's own `fetch` sends. **Browser mode cannot stop a forged request from the agent's shell**: `curl` can send any header. Use the desktop app when the agent runs shell commands.

The request goes over HTTP because the server owns the workspaces on another thread and another event loop. The window never goes up on the thread the request arrived on. `webview.create_window` builds nothing from the main thread once `webview.start` owns it, and the Dock menu and the `odoc` handler both arrive there.

## Inline browser

Chrome renders pages. Leela sends JPEG frames to a canvas and forwards input through CDP. Navigation uses `fossick.core.check_url`; private addresses require `FOSSICK_ALLOW_PRIVATE`.

The driven Chrome is for ramabana and fossick. A link you click in a feed item, an agent reply or a vault document goes to your own browser instead, through `openExternal`: `window.open` where there is a tab strip, and `/browser/external` where there is not, which hands the URL to the machine's default browser. The automation profile carries none of your sessions. A story read through it meets a bot wall. The same story in your own Chrome does not. `/browser/open` stays the deliberate "put this page in a Leela tab" action.

The audience window of a presentation also goes to the system browser through `openExternal`. The packaged app opens no audience window of its own. Move the browser window to the projector and press F there. See [present.md](present.md#the-audience-window).

CDP constraints:

- use a socket only from its creating loop
- focus background pages before screencast
- acknowledge every frame
- shield socket writes
- retain cast ownership through resize and visibility changes
- pin the viewport to panel coordinates, in CSS pixels
- a screencast frame carries one image pixel per CSS pixel whatever a page's `deviceScaleFactor`
  says; `--force-device-scale-factor` at launch is the only setting that changes it
- close the page when its tab closes, unless the page was adopted from the user's own Chrome

## Build

`setup_app.py` prepares a framework Python when needed. Platform definitions live in `packaging/macos/setup.py` and `packaging/windows/setup.py`. Run `tests/test_packaging.py` for bundle checks.

## The menu bar

macOS gets a real menu bar: Leela, File, Edit, View, Run, Tools, Debug, Window, Help. `leela/blocks/keys/menus.py` `BAR` declares it beside the contextual menus. Its rows name keymap actions, so the labels come from the keymap. A row naming an action the keymap does not declare raises at import.

Two kinds of row are not keymap actions. `Std` rows hand a raw selector to AppKit with a nil target. Cut, Copy, Paste, Select All, Minimize, Zoom and Enter Full Screen then reach the web view down the responder chain. `Js` rows carry an expression instead, which is how Debug gets in: it has no keymap actions, only functions on the page.

A row shows a shortcut only where one is safe. AppKit reads a menu shortcut before the page does, and this keymap is scoped and full of bare letters, so a row takes one only when its action is global and carries a modifier.
