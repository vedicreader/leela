# Desktop app

A packaged app combines a native window, a Leela server, and Chrome through CDP.

## Processes

pywebview owns the main thread. `leela_app.py` starts the server on a daemon thread. `leela --shell webview` uses the same shape.

Chrome runs outside the app bundle on fossick's persistent profile. It provides authenticated pages for the inline browser. Screenshots and tests require separate profiles.

## Browser lifecycle

Chrome starts on first page request. `Browser.available()` checks whether Chrome can run. `Browser.alive()` starts or checks the current process. `/browser/ready` reports availability.

## Folder selection

Project folders come from launch arguments, saved folders, native folder pickers, macOS `odoc` events, or Windows argv. Late folder requests use the HTTP route.

## Inline browser

Chrome renders pages. Leela sends JPEG frames to a canvas and forwards input through CDP. Navigation uses `fossick.core.check_url`; private addresses require `FOSSICK_ALLOW_PRIVATE`.

The driven Chrome is for ramabana and fossick. A link you click in a feed item, an agent reply or a vault document goes to your own browser instead, through `openExternal`: `window.open` where there is a tab strip, and `/browser/external` where there is not, which hands the URL to the machine's default browser. The automation profile carries none of your sessions. A story read through it meets a bot wall. The same story in your own Chrome does not. `/browser/open` stays the deliberate "put this page in a Leela tab" action.

CDP constraints:

- use a socket only from its creating loop
- focus background pages before screencast
- acknowledge every frame
- shield socket writes
- retain cast ownership through resize and visibility changes
- pin the viewport to panel coordinates

## Build

`setup_app.py` prepares a framework Python when needed. Platform definitions live in `packaging/macos/setup.py` and `packaging/windows/setup.py`. Run `tests/test_packaging.py` for bundle checks.
