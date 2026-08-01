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
function themeFrom(el) {
  const v = n => getComputedStyle(el).getPropertyValue(n).trim() || undefined;
  return {
    background: v('--lee-bg'), foreground: v('--lee-fg'),
    cursor: v('--lee-primary'), selectionBackground: v('--lee-bg2'),
    black: v('--lee-bg1'), red: v('--lee-red'), green: v('--lee-green'), yellow: v('--lee-yellow'),
    blue: v('--lee-blue'), magenta: v('--lee-purple'), cyan: v('--lee-aqua'), white: v('--lee-fg2'),
    brightBlack: v('--lee-gray'), brightRed: v('--lee-red'), brightGreen: v('--lee-green'),
    brightYellow: v('--lee-yellow'), brightBlue: v('--lee-blue'), brightMagenta: v('--lee-purple'),
    brightCyan: v('--lee-aqua'), brightWhite: v('--lee-fg'),
  };
}

class LeeTerminal {
  constructor(el, {token, url, cwd, kind, onExit, onStatus}) {
    this.el = el;
    this.onExit = onExit || (() => {});
    this.onStatus = onStatus || (() => {});
    this.term = new Terminal({
      fontFamily: getComputedStyle(el).getPropertyValue('--lee-mono').trim() || 'monospace',
      fontSize: 13, cursorBlink: true, scrollback: 5000,
      allowProposedApi: true, theme: themeFrom(el),
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
      this.send({t: 'hello', token, cwd, kind: kind || 'shell',
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

  dispose() {
    try { this._ro.disconnect(); } catch {}
    try { this.ws.close(); } catch {}
    try { this.term.dispose(); } catch {}
  }
}

window.LeeTerm = {
  create(el, opts) { return new LeeTerminal(el, opts); },
};
