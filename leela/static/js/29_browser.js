/* The inline browser: one page from the persistent CDP Chrome, drawn in a Leela tab.
 *
 * The tab holds no web content of its own. Chrome renders the page offscreen and streams JPEG
 * frames over `/browser/ws`; this module paints them on a canvas and sends mouse and keyboard
 * events back. That indirection is the point rather than a compromise -- the page runs in a
 * separate browser process with fossick's profile and cookies, so it cannot reach Leela's DOM,
 * and a site that needs a login is one Leela can read because fossick is already signed in.
 *
 * Coordinates are 1:1: the server pins Chrome's viewport to the canvas's CSS size, so a click
 * at (x, y) here is a click at (x, y) there and nothing has to be mapped through frame
 * metadata that changes whenever the page scrolls.
 */

const wsURL = p => `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}${p}`;

// The one live inline browser. Only the active tab is cast: a hidden canvas costs a JPEG
// encode per animation frame in Chrome and buys nothing.
let webView = null;

function closeWebView() {
  if (!webView) return;
  const v = webView; webView = null;
  v.resizer?.disconnect();
  v.unwatch?.();
  try { v.sock.close(); } catch (_) {}
}

function mountWeb(host, st) {
  closeWebView();
  host.innerHTML =
    `<div class="lee-doc lee-webview">` +
    `<div class="lee-doc-head lee-webbar">` +
    `<button class="lee-btn" data-web="back" title="back" aria-label="back" disabled>‹</button>` +
    `<button class="lee-btn" data-web="forward" title="forward" aria-label="forward" disabled>›</button>` +
    `<button class="lee-btn" data-web="reload" title="reload" aria-label="reload">⟳</button>` +
    `<input class="lee-input lee-weburl" data-web="url" spellcheck="false" autocomplete="off"` +
    ` aria-label="page address" placeholder="type a URL and press enter">` +
    `<span class="lee-spacer"></span>` +
    `<button class="lee-btn" data-web="markdown" title="read this page as markdown">read</button>` +
    `<button class="lee-btn" data-web="remember" title="read it and keep it in the vault">remember</button>` +
    `</div>` +
    `<div class="lee-doc-body lee-webbody" data-web="body">` +
    `<canvas class="lee-webcanvas" data-web="canvas" tabindex="0"` +
    ` aria-label="${esc(st.title || 'web page')} — rendered by the CDP browser"></canvas>` +
    `<div class="lee-webnote lee-dim" data-web="note">connecting to the browser…</div>` +
    `</div></div>`;

  const el = s => $(`[data-web="${s}"]`, host);
  const canvas = el('canvas'), note = el('note'), body = el('body'), urlBox = el('url');
  const ctx = canvas.getContext('2d', {alpha: false});
  const sock = new WebSocket(wsURL('/browser/ws'));
  // Frames arrive as raw JPEG rather than base64 in JSON: a third fewer bytes, and no data:
  // URL to parse before drawing. Everything else on this socket is still JSON.
  sock.binaryType = 'arraybuffer';
  const view = {sock, canvas, target: st.target, resizer: null, size: [0, 0], drawing: false};
  webView = view;

  const say = (msg, kind) => { note.textContent = msg || ''; note.hidden = !msg;
                               note.className = `lee-webnote ${kind === 'err' ? 'lee-err' : 'lee-dim'}`; };
  const send = m => { if (sock.readyState === 1) sock.send(JSON.stringify(m)); };
  view.send = send;

  const measure = () => {
    const r = body.getBoundingClientRect();
    return [Math.max(240, Math.round(r.width)), Math.max(180, Math.round(r.height))];
  };

  sock.onopen = () => {
    const [w, h] = measure();
    send({id: st.target, w, h, scale: 1});
  };
  sock.onerror = () => say('the inline browser socket failed', 'err');
  sock.onclose = () => { if (webView === view) say('the browser disconnected — reopen the tab', 'err'); };

  sock.onmessage = ev => {
    if (typeof ev.data !== 'string') return drawFrame(ctx, canvas, view, ev.data);
    const m = JSON.parse(ev.data);
    if (m.t === 'error') return say(m.error, 'err');
    if (m.t === 'ready') { view.size = [m.w, m.h]; sizeCanvas(canvas, m.w, m.h); paintNav(host, m); say(''); }
    else if (m.t === 'nav') paintNav(host, m);
  };

  // Chrome only emits a frame when something changes, so a resize has to re-ask for one; the
  // server restarts the cast, which always sends a fresh first frame.
  view.resizer = new ResizeObserver(() => {
    const [w, h] = measure();
    if (w === view.size[0] && h === view.size[1]) return;
    view.size = [w, h]; sizeCanvas(canvas, w, h); send({t: 'resize', w, h, scale: 1});
  });
  view.resizer.observe(body);

  wireToolbar(host, view, urlBox, say);
  wireInput(canvas, view);
  wireVisibility(view);
  canvas.focus();
}

/* A minimised or hidden window is still a window with a live screencast behind it, and Chrome
   goes on encoding a JPEG per animation frame for a canvas nobody can see. Stopping the cast
   while hidden is the difference between a background Leela costing nothing and costing a
   core; the page itself stays open, and resuming re-requests a frame immediately. */
function wireVisibility(view) {
  const onChange = () => {
    if (webView !== view || view.sock.readyState !== 1) return;
    if (document.visibilityState === 'hidden') view.send({t: 'pause'});
    else view.send({t: 'resume', w: view.size[0], h: view.size[1], scale: 1});
  };
  document.addEventListener('visibilitychange', onChange);
  view.unwatch = () => document.removeEventListener('visibilitychange', onChange);
}

function sizeCanvas(canvas, w, h) {
  // The backing store matches the CSS box exactly. A device-pixel-ratio canvas would look
  // sharper and would also ask Chrome to encode four times the JPEG per frame.
  canvas.width = w; canvas.height = h;
  canvas.style.width = `${w}px`; canvas.style.height = `${h}px`;
}

/* Draw one JPEG. `createImageBitmap` decodes off the main thread and hands back something
   `drawImage` can take directly, where an `<img>` with a data: URL would parse a URL, decode
   on the main thread, and fire an event. A frame that arrives while the previous one is still
   decoding is dropped rather than queued: on a page that is animating faster than the canvas
   can keep up, a backlog only adds latency to a picture nobody will see. */
function drawFrame(ctx, canvas, view, buf) {
  if (!buf || view.drawing) return;
  view.drawing = true;
  createImageBitmap(new Blob([buf], {type: 'image/jpeg'}))
    .then(bmp => {
      ctx.drawImage(bmp, 0, 0, canvas.width, canvas.height);
      bmp.close();
    })
    .catch(() => {})
    .finally(() => { view.drawing = false; });
}

function paintNav(host, m) {
  const el = s => $(`[data-web="${s}"]`, host);
  const url = el('url');
  // Never overwrite a URL half-typed: `nav` frames arrive whenever the page redirects.
  if (url && document.activeElement !== url) url.value = m.url || '';
  el('back').disabled = !m.back;
  el('forward').disabled = !m.forward;
  const tab = $('.lee-tab.active .lee-tab-name');
  if (tab && m.title) tab.textContent = m.title;
}

function wireToolbar(host, view, urlBox, say) {
  const on = (name, fn) => $(`[data-web="${name}"]`, host).addEventListener('click', fn);
  on('back', () => view.send({t: 'back'}));
  on('forward', () => view.send({t: 'forward'}));
  on('reload', () => view.send({t: 'reload'}));
  urlBox.addEventListener('keydown', e => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    view.send({t: 'goto', url: urlBox.value.trim()});
    view.canvas.focus();
  });
  on('markdown', () => readWeb(view, false, say));
  on('remember', () => readWeb(view, true, say));
}

/* Lift the live page out as Markdown. This is the payoff of rendering in Chrome rather than
   fetching: the DOM being read is the one after the scripts ran and after the login, so an
   app or a paywalled article reads the same way a static page does. What comes back is a
   `Doc` in research's own shape, so saving it and remembering it are the paths that exist. */
async function readWeb(view, remember, say) {
  say(remember ? 'reading and remembering…' : 'reading…');
  let d;
  try { d = await api(`/browser/markdown?id=${encodeURIComponent(view.target)}&remember=${remember ? 1 : 0}`); }
  catch (e) { return say(String(e.message || e), 'err'); }
  say('');
  if (remember) status(d.note || 'remembered', 'ok');
  lee.lastDoc = {title: d.title || d.url || 'page', url: d.url || '', text: d.markdown || ''};
  showWebMarkdown(lee.lastDoc);
}

// The same reader research uses for a fetched page, over the page that is on screen.
function showWebMarkdown(doc) {
  const m = modal(
    `<div class="lee-mhead"><span>${esc(doc.title)}</span><span class="lee-spacer"></span>` +
    `<button class="lee-btn" data-md="save">save markdown</button>` +
    `<button class="lee-btn" data-md="notebook">save as notebook</button></div>` +
    `<div class="lee-mbody lee-reader"><div class="lee-md" data-md="body"></div></div>`,
    null, null, {className: 'lee-research-modal', storageKey: 'web-read'});
  renderMarkdown($('[data-md="body"]', m), doc.text || '(the page had no readable text)');
  $('[data-md="save"]', m).onclick = () => saveDoc(doc, 'md');
  $('[data-md="notebook"]', m).onclick = () => saveDoc(doc, 'notebook');
}

/* Input forwarding. Everything is `preventDefault`ed: the canvas is standing in for a browser
   viewport, so a Space that scrolls the page must not also scroll Leela, and a Tab must move
   focus inside the page rather than out of it. The keymap router already treats this panel
   like the terminal, so the chords that get you out still work. */
function wireInput(canvas, view) {
  const at = e => { const r = canvas.getBoundingClientRect();
                    return {x: e.clientX - r.left, y: e.clientY - r.top}; };
  const mods = e => (e.altKey ? 1 : 0) | (e.ctrlKey ? 2 : 0) | (e.metaKey ? 4 : 0) | (e.shiftKey ? 8 : 0);
  const BUTTONS = ['left', 'middle', 'right'];

  canvas.addEventListener('mousedown', e => {
    e.preventDefault(); canvas.focus();
    view.send({t: 'mouse', kind: 'mousePressed', ...at(e), button: BUTTONS[e.button] || 'left',
               clicks: e.detail || 1, modifiers: mods(e)});
  });
  canvas.addEventListener('mouseup', e => {
    e.preventDefault();
    view.send({t: 'mouse', kind: 'mouseReleased', ...at(e), button: BUTTONS[e.button] || 'left',
               clicks: e.detail || 1, modifiers: mods(e)});
  });
  // Hover drives menus and link underlines, so it is worth sending -- but at the frame rate
  // rather than the event rate, which for a fast mouse is several hundred a second.
  let moveDue = false;
  canvas.addEventListener('mousemove', e => {
    if (moveDue) return;
    moveDue = true;
    requestAnimationFrame(() => { moveDue = false;
      view.send({t: 'mouse', kind: 'mouseMoved', ...at(e), button: 'none', modifiers: mods(e)}); });
  });
  canvas.addEventListener('contextmenu', e => e.preventDefault());
  canvas.addEventListener('wheel', e => {
    e.preventDefault();
    view.send({t: 'mouse', kind: 'mouseWheel', ...at(e), dx: -e.deltaX, dy: -e.deltaY,
               modifiers: mods(e)});
  }, {passive: false});

  canvas.addEventListener('keydown', e => {
    if (isEscapeChord(e)) return;          // let Leela's router have it
    e.preventDefault();
    view.send({t: 'key', kind: printable(e) ? 'keyDown' : 'rawKeyDown', ...keyFields(e)});
    if (printable(e)) view.send({t: 'key', kind: 'char', text: e.key, ...keyFields(e)});
  });
  canvas.addEventListener('keyup', e => {
    if (isEscapeChord(e)) return;
    e.preventDefault();
    view.send({t: 'key', kind: 'keyUp', ...keyFields(e)});
  });
  canvas.addEventListener('paste', e => {
    e.preventDefault();
    const text = e.clipboardData?.getData('text') || '';
    if (text) view.send({t: 'text', text});
  });
}

const printable = e => e.key.length === 1 && !e.ctrlKey && !e.metaKey;

// `windowsVirtualKeyCode` is what Chrome actually dispatches on for non-text keys; without it
// Enter, Backspace and the arrows arrive as no-ops.
const VKEY = {Backspace: 8, Tab: 9, Enter: 13, Shift: 16, Control: 17, Alt: 18, Escape: 27,
              ' ': 32, PageUp: 33, PageDown: 34, End: 35, Home: 36, ArrowLeft: 37, ArrowUp: 38,
              ArrowRight: 39, ArrowDown: 40, Insert: 45, Delete: 46, Meta: 91};

function keyFields(e) {
  const m = (e.altKey ? 1 : 0) | (e.ctrlKey ? 2 : 0) | (e.metaKey ? 4 : 0) | (e.shiftKey ? 8 : 0);
  const vk = VKEY[e.key] ?? (e.key.length === 1 ? e.key.toUpperCase().charCodeAt(0) : 0);
  return {key: e.key, code: e.code, modifiers: m, windowsVirtualKeyCode: vk,
          nativeVirtualKeyCode: vk, text: printable(e) ? e.key : ''};
}

// The chords the keymap router still answers while the page has focus. Asking it directly
// keeps this list from drifting away from the one in `findBinding`.
function isEscapeChord(e) {
  const match = findBinding(e, 'web');
  return Boolean(match);
}

/* Open a URL as a tab. The entry point for research, the agent, and the command palette:
   everything that used to `window.open` a page can bring it in here instead.
   Both routes answer with the tab strip, like every other route that opens a tab. */
async function openWebTab(url, title = '') {
  if (!url) return status('no URL to open', 'err');
  status('opening in the inline browser…');
  try {
    await htmxPost(`/browser/open?url=${encodeURIComponent(url)}` +
                   (title ? `&title=${encodeURIComponent(title)}` : ''));
    await mountTab();
    status('');
  } catch (e) { status(`inline browser: ${e.message || e}`, 'err'); }
}
window.leeOpenWeb = openWebTab;

// Ask for an address, then open it here. The counterpart to `read_url`, which fetches a page
// and shows its Markdown: this one shows the page.
async function browseUrl() {
  const url = await inputDialog('open a page', 'address', '', 'example.com/article');
  if (url) return openWebTab(url.trim());
}

// Adopt whatever the CDP Chrome already has open -- a window fossick opened, a tab a link
// spawned. This is the other half of "the browser is shared": a page does not have to start
// in Leela to end up in Leela.
async function pickWebTab(anchor) {
  let d;
  try { d = await api('/browser/tabs'); }
  catch (e) { return status(`inline browser: ${e.message || e}`, 'err'); }
  if (!d.ok) return status(d.error, 'err');
  const pages = (d.tabs || []).filter(t => !/^(chrome|devtools|about):/.test(t.url || ''));
  if (!pages.length) return status('the browser has no pages open', 'err');
  openChromeMenu(anchor || $('#tabbar') || document.body, pages.map(p => ({
    label: p.title || p.url, detail: researchDomain(p.url),
    run: async () => {
      await htmxPost(`/browser/attach?id=${encodeURIComponent(p.id)}`);
      await mountTab();
    },
  })));
}
window.leePickWeb = pickWebTab;
