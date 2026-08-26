/* The inline browser: one page from the persistent CDP Chrome, drawn in a Leela tab.
 *
 * Chrome renders offscreen and streams JPEG frames over `/browser/ws`. The page runs in a separate
 * process with fossick's profile, so it cannot reach Leela's DOM, and a site fossick is signed in
 * to is one Leela can read.
 *
 * Coordinates are 1:1, because the server pins Chrome's viewport to the canvas's CSS size. A
 * frame may carry more pixels than that box, and lands in a backing store sized to it.
 */

const wsURL = p => `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}${p}`;

// What the page should read as its own `devicePixelRatio`, so it picks the assets the display
// wants. How many pixels a frame carries is `SCALE_FLAG`, which Chrome takes at launch.
const webScale = () => Math.min(window.devicePixelRatio || 1, 2);

// Only the active tab is cast: a hidden canvas costs a JPEG encode per frame in Chrome.
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
    send({id: st.target, w, h, scale: webScale()});
  };
  sock.onerror = () => say('the inline browser socket failed', 'err');
  sock.onclose = () => { if (webView === view) say('the browser disconnected — reopen the tab', 'err'); };

  sock.onmessage = ev => {
    if (typeof ev.data !== 'string') return drawFrame(ctx, canvas, view, ev.data);
    const m = JSON.parse(ev.data);
    if (m.t === 'error') return say(m.error, 'err');
    if (m.t === 'ready') { view.size = [m.w, m.h]; sizeCanvas(canvas, m.w, m.h); paintNav(host, m);
                           say(''); warnScale(m); }
    else if (m.t === 'nav') paintNav(host, m);
  };

  // Chrome only emits a frame when something changes, so a resize re-asks for one. The server
  // restarts the cast, which always sends a fresh first frame.
  view.resizer = new ResizeObserver(() => {
    const [w, h] = measure();
    if (w === view.size[0] && h === view.size[1]) return;
    view.size = [w, h]; sizeCanvas(canvas, w, h);
    send({t: 'resize', w, h, scale: webScale()});
  });
  view.resizer.observe(body);

  wireToolbar(host, view, urlBox, say);
  wireInput(canvas, view);
  wireVisibility(view);
  canvas.focus();
}

/* Chrome takes `--force-device-scale-factor` at launch, so a browser already running when Leela
   connects goes on drawing at 1x and no restart of Leela changes it. Said once per Chrome, which
   is what the browser id keys: the server repeats the note on every `ready`. */
function warnScale(m) {
  if (!m.note) return;
  const key = 'lee-web-scale';
  if (localStorage.getItem(key) === (m.browser || '')) return;
  localStorage.setItem(key, m.browser || '');
  status(m.note, 'err');
}

/* A hidden window still has a live screencast behind it, so Chrome goes on encoding for a canvas
   nobody can see. The page stays open, and resuming asks for a frame immediately. */
function wireVisibility(view) {
  const onChange = () => {
    if (webView !== view || view.sock.readyState !== 1) return;
    if (document.visibilityState === 'hidden') view.send({t: 'pause'});
    else view.send({t: 'resume', w: view.size[0], h: view.size[1], scale: webScale()});
  };
  document.addEventListener('visibilitychange', onChange);
  view.unwatch = () => document.removeEventListener('visibilitychange', onChange);
}

/* The CSS box is the viewport, in the same pixels a click arrives in. The backing store starts
   there and `drawFrame` grows it to whatever the frame turns out to carry. */
function sizeCanvas(canvas, w, h) {
  canvas.width = w; canvas.height = h;
  canvas.style.width = `${w}px`; canvas.style.height = `${h}px`;
}

/* `createImageBitmap` decodes off the main thread, where an `<img>` with a data: URL would decode
   on it. A frame arriving mid-decode is dropped rather than queued. */
function drawFrame(ctx, canvas, view, buf) {
  if (!buf || view.drawing) return;
  view.drawing = true;
  createImageBitmap(new Blob([buf], {type: 'image/jpeg'}))
    .then(bmp => {
      // The frame is the last word on its own size. A Chrome rasterising at 2x sends twice the
      // pixels for the same viewport, and they land 1:1 in a box the display still paints at the
      // CSS size. One that does not is drawn 1:1 too, rather than stretched.
      if (bmp.width !== canvas.width || bmp.height !== canvas.height) {
        canvas.width = bmp.width; canvas.height = bmp.height;
      }
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

/* The live page as Markdown: the DOM after the scripts ran and after the login, which a fetch
   cannot reach. Comes back as research's own `Doc`, so saving it is a path that already
   exists. */
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

/* Everything is `preventDefault`ed, because the canvas stands in for a viewport: a Space that
   scrolls the page must not also scroll Leela. The keymap router treats this panel like the
   terminal, so the chords that get you out still work. */
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
  // Hover drives menus and link underlines, but at frame rate: a fast mouse fires hundreds/s.
  // The frame sends where the mouse got to, not where it was: a flick ends where it stopped.
  let moveAt = null;
  canvas.addEventListener('mousemove', e => {
    const first = !moveAt;
    moveAt = {...at(e), modifiers: mods(e)};
    if (first) requestAnimationFrame(() => {
      const m = moveAt; moveAt = null;
      view.send({t: 'mouse', kind: 'mouseMoved', ...m, button: 'none'});
    });
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

// Asked of the router itself, so the list cannot drift from the one in `findBinding`.
const isEscapeChord = e => Boolean(findBinding(e, 'web'));

// Open a URL as a tab, the entry point for research and the palette. `/browser/open` answers with
// the tab strip, like every other route that opens a tab.

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

// The counterpart to `read_url`, which shows a page's Markdown: this one shows the page.
async function browseUrl() {
  const url = await inputDialog('open a page', 'address', '', 'example.com/article');
  if (url) return openWebTab(url.trim());
}

// Adopt what Chrome already has: a page need not start in Leela to end up in Leela.
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
