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

A file never adds a folder by itself. Finder, `open file.py`, a traceback link in a terminal or an agent hands Leela a file through `/hub/open?path=…&file=…`. When a window already has the file's folder open, the file opens there. When none does, the file opens in the loose window, and one line under the editor asks "This file is in <repo>. Open <repo> as a folder?" with Open and Not now. Only Open sends `folder=1`, which builds the workspace, writes `desktop.json` and moves the folder's loose tabs into the new window. A file that the loose window refuses, such as a `.env`, gets the same question in a native dialog. In a folder window, a link to a file outside the open folders is refused, and no folder is added. The agent has no way to add a folder: Leela's host does not implement `add_root`.

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
