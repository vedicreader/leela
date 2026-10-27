// xterm.js wrapper for the leela IDE.
//
// Bundled to ../static/lee-term.js and committed, so the IDE works offline and a user
// installing from PyPI never needs node. Rebuild with `npm run build`.
//
// Same contract as lee-cm6.js: the page talks to one small surface (`window.LeeTerm`)
// rather than importing xterm itself, so Python keeps owning the layout and the keymap.
//
// The socket carries raw bytes in both directions, because that is what a pty is. Only
// two things are *not* raw: the first frame the client sends (a JSON hello carrying the
// terminal token and the initial size) and any later resize. Both are tagged so the
// server can tell control from keystrokes without escaping anything.

import {Terminal} from "@xterm/xterm";
import {FitAddon} from "@xterm/addon-fit";

// Colours come from the app's CSS custom properties, so the terminal follows the IDE's
// theme instead of carrying its own palette (same rule as the editor).
//
// Every name here has to be one the stylesheet actually defines. `--lee-primary` and
// `--lee-gray` were not: an undefined property reads as `''`, becomes `undefined`, and
// xterm falls back to its own default -- which for the cursor is **white**, whatever the
// theme. On the dark theme that passed for correct; in light mode it is a white cursor on
// a white background, which is why the terminal looked like it had no cursor at all.
// `cursorAccent` is the character *under* a block cursor, so it has to be the background.
function themeFrom(el) {
  const v = n => getComputedStyle(el).getPropertyValue(n).trim() || undefined;
  return {
    background: v('--lee-bg'), foreground: v('--lee-fg'),
    cursor: v('--lee-accent'), cursorAccent: v('--lee-bg'), selectionBackground: v('--lee-sel'),
    // `--lee-blue` is the same purple as `--lee-magenta` in the IDE's palette, which is
    // fine for a file tree and wrong for a terminal: ls, git and every prompt in the world
    // expect blue to be blue.
    black: v('--lee-bg1'), red: v('--lee-red'), green: v('--lee-green'), yellow: v('--lee-yellow'),
    blue: v('--lee-accent'), magenta: v('--lee-purple'), cyan: v('--lee-aqua'), white: v('--lee-fg2'),
    brightBlack: v('--lee-fg4'), brightRed: v('--lee-red'), brightGreen: v('--lee-green'),
    brightYellow: v('--lee-orange'), brightBlue: v('--lee-accent'), brightMagenta: v('--lee-purple'),
    brightCyan: v('--lee-aqua'), brightWhite: v('--lee-fg'),
  };
}

class LeeTerminal {
  constructor(el, {token, url, cwd, kind, id, onExit, onStatus}) {
    this.el = el;
    this.onExit = onExit || (() => {});
    this.onStatus = onStatus || (() => {});
    const {optionMeta = true, mode} = window.leeTermDefaults?.() || {};
    this.mode = mode;
    this.term = new Terminal({
      fontFamily: getComputedStyle(el).getPropertyValue('--lee-mono').trim() || 'monospace',
      fontSize: parseFloat(getComputedStyle(el).getPropertyValue('--lee-code-size')), cursorBlink: true, scrollback: 5000,
      allowProposedApi: true, theme: themeFrom(el), macOptionIsMeta: optionMeta,
    });
    this.fit = new FitAddon();
    this.term.loadAddon(this.fit);
    this.term.open(el);
    this.refit();

    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    this.ws = new WebSocket(`${proto}//${location.host}${url || '/term/ws'}`);
    this.ws.binaryType = 'arraybuffer';

    this.ws.onopen = () => {
      // The hello must be first: the server refuses everything until it has the token.
      // `id` keys the pty on the server. Without it every shell falls back to the kind, so a
      // second terminal attaches to the first one's pty and takes its reader with it.
      this.send({t: 'hello', token, cwd, kind: kind || 'shell', id, mode: this.mode,
                 cols: this.term.cols, rows: this.term.rows});
      this.onStatus('connected');
    };
    this.ws.onmessage = ev => {
      if (typeof ev.data === 'string') {
        let m; try { m = JSON.parse(ev.data); } catch { return; }
        if (m.t === 'exit')  { this.term.write(`\r\n\x1b[90m${m.note || '[exited]'}\x1b[0m\r\n`); this.onExit(m); }
        if (m.t === 'error') { this.term.write(`\r\n\x1b[31m${m.error}\x1b[0m\r\n`); this.onStatus(m.error); }
        return;
      }
      this.term.write(new Uint8Array(ev.data));
    };
    this.ws.onclose = () => this.onStatus('disconnected');

    this.term.onData(d => this.raw(d));
    this._ro = new ResizeObserver(() => this.refit());
    this._ro.observe(el);
  }

  // Both guard on the socket *existing*, not just being open: `refit()` runs during
  // construction to size the terminal before connecting, and the ResizeObserver can
  // fire after `dispose()`. Either would otherwise read readyState off undefined.
  send(obj) { if (this.ws && this.ws.readyState === 1) this.ws.send(JSON.stringify(obj)); }
  raw(s)    { if (this.ws && this.ws.readyState === 1) this.ws.send(new TextEncoder().encode(s)); }

  refit() {
    try { this.fit.fit(); } catch { return; }
    this.send({t: 'size', cols: this.term.cols, rows: this.term.rows});
  }

  focus()  { this.term.focus(); }
  clear()  { this.term.clear(); }
  paste(s) { this.raw(s); }

  // The theme is read from CSS once, at construction. macOS flips the whole system
  // between light and dark while apps are running, and the IDE follows it through a
  // media query -- so the terminal has to be told, or it keeps a dark palette on a
  // light page and the cursor goes invisible again from the other direction.
  retheme() { try { this.term.options.theme = themeFrom(this.el); } catch {} }

  // With it off, Option plus a key types the composed character; on, the key reaches the shell as Alt.
  setOptionMeta(on) { this.term.options.macOptionIsMeta = on; }

  dispose() {
    try { this._ro.disconnect(); } catch {}
    try { this.ws.close(); } catch {}
    try { this.term.dispose(); } catch {}
  }
}

window.LeeTerm = {
  create(el, opts) { return new LeeTerminal(el, opts); },
};
