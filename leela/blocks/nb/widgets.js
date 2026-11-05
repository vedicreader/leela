/* ipywidgets in notebook cells. Each notebook has one link: a socket on `/nb/comm/ws` following its
   kernel, and the vendored manager, loaded once a widget has to be drawn. A view is kept per cell,
   output and model, so re-rendering a cell's outputs moves the live widget rather than rebuilding it.
   Where a widget cannot be live its `text/plain` repr shows, with a muted line saying why. */
const WIDGET_MIME = 'application/vnd.jupyter.widget-view+json';
//: How long a drawn output waits for its model before saying so. It keeps waiting while a cell runs.
const WIDGET_WAIT = 10000;
const WIDGET_BADGE = 'interactive widget: run the cell';
const WIDGET_THEME = `:host { display: block; color: var(--lee-fg); font-size: 13px;
  --jp-layout-color0: var(--lee-bg); --jp-layout-color1: var(--lee-bg1); --jp-layout-color2: var(--lee-bg2);
  --jp-layout-color3: var(--lee-bg3); --jp-inverse-layout-color0: var(--lee-fg);
  --jp-border-color1: var(--lee-border); --jp-border-color2: var(--lee-border); --jp-border-width: 1px;
  --jp-ui-font-color0: var(--lee-fg); --jp-ui-font-color1: var(--lee-fg); --jp-ui-font-color2: var(--lee-fg2);
  --jp-content-font-color0: var(--lee-fg); --jp-content-font-color1: var(--lee-fg);
  --jp-ui-inverse-font-color0: var(--lee-bg); --jp-ui-inverse-font-color1: var(--lee-bg);
  --jp-inverse-ui-font-color0: var(--lee-bg); --jp-inverse-ui-font-color1: var(--lee-bg);
  --jp-brand-color0: var(--lee-accent); --jp-brand-color1: var(--lee-accent); --jp-brand-color2: var(--lee-accent);
  --jp-error-color0: var(--lee-red); --jp-error-color1: var(--lee-red); --jp-warn-color0: var(--lee-orange);
  --jp-warn-color1: var(--lee-orange); --jp-success-color0: var(--lee-green); --jp-success-color1: var(--lee-green);
  --jp-info-color0: var(--lee-blue); --jp-info-color1: var(--lee-blue);
  --jp-ui-font-family: inherit; --jp-ui-font-size1: 13px; --jp-code-font-family: var(--lee-mono);
  --jp-code-font-size: 13px; --jp-code-line-height: 1.4; --jp-code-padding: 2px;
  --jp-cell-prompt-width: 0px; --jp-cell-prompt-font-family: var(--lee-mono); --jp-cell-prompt-letter-spacing: 0;
  --jp-cell-prompt-opacity: 1; --jp-cell-outprompt-font-color: var(--lee-fg3);
  --jp-flat-button-height: 24px; --jp-flat-button-padding: 8px 12px; }
.lee-widget-mount { overflow: auto; }`;
const widgetLinks = new Map();
let widgetBundle = null, widgetSeq = 0, widgetSheet = null;
const widgetKey = () => lee.path || lee.tabKey || '';

function loadWidgetBundle() {
  if (window.LeeWidgets) return Promise.resolve();
  return widgetBundle ||= new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = $('meta[name="lee-widgets-src"]')?.content || '/leestatic/lee-widgets.js';
    s.onload = () => {
      for (const family of ['Font Awesome 5 Free', 'FontAwesome'])
        document.fonts.add(new FontFace(family, 'url(/leestatic/fonts/fa-solid-900.woff2)', {weight: '900'}));
      resolve();
    };
    s.onerror = () => { widgetBundle = null; reject(new Error('the widget bundle failed to load')); };
    document.head.appendChild(s);
  });
}
function widgetStyle(root) {
  const text = LeeWidgets.css + WIDGET_THEME;
  if (!('adoptedStyleSheets' in root)) return root.prepend(Object.assign(document.createElement('style'), {textContent: text}));
  if (!widgetSheet) { widgetSheet = new CSSStyleSheet(); widgetSheet.replaceSync(text); }
  root.adoptedStyleSheets = [widgetSheet];
}

function widgetLink(key) {
  let l = widgetLinks.get(key);
  if (!l) widgetLinks.set(key, l = {key, state: 'connecting', views: new Map(), dead: new Set(), logs: new Map(),
                                    queue: [], asks: new Map(), seq: 0, gen: 0, mgr: null, kernel: null});
  if (l.sock && l.sock.readyState <= WebSocket.OPEN) return l;
  l.state = 'connecting';
  l.ready = new Promise(res => l.settle = res);
  const sock = l.sock = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/nb/comm/ws?path=${encodeURIComponent(key)}`);
  sock.onmessage = e => widgetHeard(l, JSON.parse(e.data));
  sock.onclose = () => {
    if (l.sock !== sock) return;
    const live = l.state === 'ready' && [...l.views.values()].some(v => v.view);
    l.sock = null; l.state = 'closed'; l.settle();
    if (live) setTimeout(() => widgetLink(key), 1000);
  };
  return l;
}
//: A run waits for its notebook's socket to be following the kernel, so the widgets it makes are heard.
async function widgetWatch(key, cellId) {
  const l = widgetLink(key);
  l.logs.get(cellId)?.remove(); l.logs.delete(cellId);
  for (const [k, v] of l.views) if (v.log && v.cell === cellId) { widgetUnmount(v); l.views.delete(k); }
  await Promise.race([l.ready, new Promise(res => setTimeout(res, 2000))]);
}
function widgetAsk(l, f) {
  const id = `ask-${++l.seq}`;
  return new Promise(res => {
    if (l.sock?.readyState !== WebSocket.OPEN) return res({});
    l.asks.set(id, res);
    setTimeout(() => { if (l.asks.delete(id)) res({}); }, 20000);
    l.sock.send(JSON.stringify({...f, id}));
  });
}
function widgetHeard(l, m) {
  if (m.type === 'ready') {
    if (l.kernel && l.kernel !== m.kernel) widgetReset(l);
    const again = !!l.mgr;
    l.kernel = m.kernel; l.state = 'ready'; l.settle();
    if (again) widgetReconcile(l);
    else if (l.views.size || l.queue.length) widgetManager(l);
    return widgetPaintAll(l);
  }
  if (['waiting', 'kernel_gone', 'kernel_restart', 'unsupported'].includes(m.type)) {
    widgetReset(l);
    l.state = {unsupported: 'unsupported', kernel_restart: 'ready'}[m.type] || 'gone';
    if (l.state === 'gone') l.kernel = null;
    l.settle();
    return widgetPaintAll(l);
  }
  if (m.type === 'resync') return l.mgr && widgetReconcile(l);
  if (m.type === 'reply' || m.type === 'error') {
    const res = l.asks.get(m.id);
    if (res) { l.asks.delete(m.id); res(m.content || {}); }
    else if (m.type === 'error') status(`widget: ${m.error}`, 'err');
    return;
  }
  widgetClean(l, m);
  if (l.mgr) return l.mgr.receive(m);
  if (l.queue.length < 5000) l.queue.push(m);
  widgetManager(l);
}
//: The views that write a kernel string as HTML: `value` of HTML and HTMLMath, and a description with `description_allow_html`. The kernel runs code the agent can write, so the string is cleaned on its way in.
const WIDGET_HTML = new Set(['HTMLModel', 'HTMLMathModel']);
function widgetClean(l, m) {
  const c = m.content || {}, all = c.data?.states;
  // a page that loads from the kernel gets every model's state in one reply on the control comm
  if (all && typeof all === 'object') return Object.entries(all).forEach(([id, x]) => x?.state && widgetCleanState(l, id, {_model_name: x.model_name, ...x.state}, x.state));
  if (c.data?.state && typeof c.data.state === 'object' && c.comm_id) widgetCleanState(l, c.comm_id, c.data.state, c.data.state);
}
//: `st` read as model `id`'s state; the cleaned values are written to `out`.
function widgetCleanState(l, id, st, out) {
  const kinds = l.kinds ||= new Map(), was = kinds.get(id) || {};
  const now = {name: st._model_name ?? was.name, html: st.description_allow_html ?? was.html, desc: typeof st.description === 'string' ? st.description : was.desc};
  kinds.set(id, now);
  if (WIDGET_HTML.has(now.name) && typeof st.value === 'string') out.value = richString(st.value);
  // turning HTML on later draws the description already held, so it is cleaned then too
  if (now.html && typeof now.desc === 'string' && ('description' in st || 'description_allow_html' in st)) out.description = richString(now.desc);
}
function widgetReset(l) {
  const mgr = l.mgr;
  l.kinds = new Map();
  l.mgr = l.loading = null; l.loaded = false; l.queue = []; l.gen += 1;
  mgr?.kill().catch(() => {});
  for (const v of l.views.values()) { l.dead.add(v.id); widgetUnmount(v); }
}
function widgetManager(l) {
  if (l.state !== 'ready') return Promise.resolve(null);
  const gen = l.gen;
  return l.loading ||= (async () => {
    try { await loadWidgetBundle(); }
    catch (e) { if (l.gen === gen) l.loading = null; status(String(e.message || e), 'err'); return null; }
    if (l.gen !== gen || l.state !== 'ready') return null;
    const mgr = l.mgr = new LeeWidgets.Manager({
      post: f => l.sock?.readyState === WebSocket.OPEN && l.sock.send(JSON.stringify(f)),
      info: target_name => widgetAsk(l, {op: 'info', target_name}),
      output: (view, m) => widgetCallbackOutput(l, view, m),
      refused: () => widgetPaintAll(l),
      // A model can arrive after its view gave up on it: the load answered empty while a cell still ran.
      registered: id => { if (l.mgr !== mgr || !l.dead.delete(id)) return; for (const v of l.views.values()) if (v.id === id) widgetPaint(l, v); }});
    for (const m of l.queue.splice(0)) mgr.receive(m);
    widgetLoad(l, mgr);
    return mgr;
  })();
}
//: Every widget the kernel holds, so a reloaded page re-mounts the live ones.
function widgetLoad(l, mgr) {
  l.loaded = false;
  mgr._loadFromKernel().catch(() => {}).finally(() => { if (l.mgr === mgr) { l.loaded = true; widgetPaintAll(l); } });
}
//: The same kernel after a dropped socket: whatever it closed meanwhile goes, and the rest is read again.
async function widgetReconcile(l) {
  if (l.reconciling) return;
  const mgr = l.reconciling = l.mgr;
  try {
    const r = await widgetAsk(l, {op: 'info', target_name: mgr.comm_target_name});
    if (r.comms && l.mgr === mgr) await mgr.forget(r.comms);
    if (l.mgr === mgr) widgetLoad(l, mgr);
  } catch {} finally { l.reconciling = null; }
}

function widgetEl(o, c, i) {
  const d = o.data[WIDGET_MIME] || {}, text = o.data['text/plain'] || '';
  if (!c || !d.model_id || d.version_major !== 2) {
    const host = document.createElement('div'); host.className = 'lee-out result lee-widget';
    widgetFallback({host, text}, c ? 'interactive widget: made by an ipywidgets this page does not draw' : '');
    return host;
  }
  const l = widgetLink(widgetKey()), vk = `${c.id}:${i}:${d.model_id}`;
  let v = l.views.get(vk);
  if (!v) {
    const host = document.createElement('div'), root = host.attachShadow({mode: 'open'}), mount = document.createElement('div');
    host.className = 'lee-out result lee-widget'; host.dataset.cell = c.id; mount.className = 'lee-widget-mount';
    root.append(document.createElement('slot'), mount);
    for (const ev of ['pointerdown', 'keydown']) host.addEventListener(ev, () => { l.lastCell = c.id; });
    l.views.set(vk, v = {key: vk, cell: c.id, id: d.model_id, host, root, mount, text, view: null, log: String(i).startsWith('log')});
  }
  if (!v.view && !v.trying) widgetPaint(l, v);
  v.seen = widgetSeq;
  return v.host;
}
function widgetRefusal(l, id) {
  const r = l.mgr?.refusal(id);
  if (!r) return '';
  return r.module ? `interactive widget: ${r.module} is not available in Leela, so this is its text form`
    : `interactive widget: protocol ${r.protocol || 'unknown'} is not ipywidgets 8, so this is its text form`;
}
function widgetFallback(v, note) {
  if (v.note === note && v.host.firstChild) return;
  v.note = note;
  v.host.replaceChildren(Object.assign(document.createElement('span'), {textContent: v.text}));
  if (note) v.host.append(Object.assign(document.createElement('div'), {className: 'lee-dim lee-widget-note', textContent: note}));
}
function widgetPaint(l, v) {
  if (v.view) return;
  const why = l.state === 'unsupported' ? 'interactive widget: this kernel cannot run widgets'
    : l.dead.has(v.id) || l.state === 'gone' || l.state === 'closed' ? WIDGET_BADGE : widgetRefusal(l, v.id);
  if (why) return widgetFallback(v, why);
  if (!v.host.firstChild) widgetFallback(v, '');
  if (l.state === 'ready') widgetTry(l, v);
}
function widgetPaintAll(l) { for (const v of l.views.values()) widgetPaint(l, v); }
const widgetRunning = l => widgetKey() === l.key && (lee.cells || []).some(c => c.running);
async function widgetTry(l, v) {
  if (v.trying) return;
  v.trying = true;
  try {
    const mgr = await widgetManager(l), until = Date.now() + WIDGET_WAIT;
    while (mgr && l.mgr === mgr && l.views.get(v.key) === v && !v.view) {
      if (mgr.has_model(v.id)) return await widgetShow(l, mgr, v);
      if (mgr.refusal(v.id)) return;
      if (l.loaded && !widgetRunning(l)) return void l.dead.add(v.id);
      if (Date.now() > until) widgetFallback(v, 'interactive widget: waiting for the kernel to send it');
      await new Promise(res => setTimeout(res, 150));
    }
  } catch (e) {
    widgetFallback(v, `interactive widget: ${e.message || e}`);
  } finally {
    v.trying = false;
    if (!v.view && l.views.get(v.key) === v && (l.dead.has(v.id) || l.mgr?.refusal(v.id))) widgetPaint(l, v);
  }
}
async function widgetShow(l, mgr, v) {
  const view = await mgr.create_view(await mgr.get_model(v.id), {});
  // A view for a notebook no longer on screen waits briefly; the next render of its cell tries again.
  for (const until = Date.now() + 5000; !v.mount.isConnected && Date.now() < until;) await new Promise(res => setTimeout(res, 50));
  if (l.mgr !== mgr || l.views.get(v.key) !== v || v.view || !v.mount.isConnected) return view.remove();
  widgetStyle(v.root);
  v.host.replaceChildren(); v.note = null;
  v.view = view;
  await mgr.display_view(view, v.mount);
}
function widgetUnmount(v) {
  if (!v.view) return;
  try { v.view.remove(); } catch {}
  v.view = null; v.mount.replaceChildren();
}
//: `renderOutputs` empties the box; the live hosts leave it first and come back through `widgetEl`.
function widgetDetach(c) {
  widgetSeq += 1;
  for (const v of widgetLinks.get(widgetKey())?.views.values() || []) if (v.cell === c.id && !v.log) v.host.remove();
}
function widgetSweep(c) {
  const l = widgetLinks.get(widgetKey()); if (!l) return;
  for (const [k, v] of l.views) if (v.cell === c.id && !v.log && v.seen !== widgetSeq) { widgetUnmount(v); l.views.delete(k); }
  const log = l.logs.get(c.id), box = $('#out-' + c.id);
  if (log && box) box.appendChild(log);
}

function widgetAsOutput(m) {
  const t = m.msg_type, c = m.content || {};
  if (t === 'stream') return {output_type: 'stream', name: c.name, text: c.text};
  if (t === 'error') return {output_type: 'error', ename: c.ename, evalue: c.evalue, traceback: c.traceback};
  if (t === 'display_data' || t === 'execute_result' || t === 'update_display_data') return {output_type: 'display_data', data: c.data || {}, metadata: c.metadata || {}};
  return t === 'clear_output' ? {output_type: 'clear'} : null;
}
//: What a widget's own callback prints, with no Output widget to take it, goes under the widget's cell.
function widgetCallbackOutput(l, view, m) {
  const o = widgetAsOutput(m); if (!o) return;
  const id = view?.el?.getRootNode?.()?.host?.dataset?.cell || l.lastCell;
  const c = widgetKey() === l.key ? (lee.cells || []).find(x => x.id === id) : null;
  if (!c) return o.output_type === 'clear' || status(`from widget: ${String(o.text ?? o.data?.['text/plain'] ?? o.evalue ?? '').trim()}`);
  let log = l.logs.get(c.id);
  if (!log) {
    log = Object.assign(document.createElement('div'), {className: 'lee-widget-log lee-dim'});
    log.append(Object.assign(document.createElement('div'), {className: 'lee-widget-from', textContent: 'from widget'}));
    l.logs.set(c.id, log);
  }
  if (o.output_type === 'clear') log.replaceChildren(log.firstChild);
  else log.appendChild(outputEl(o, c, `log${++l.seq}`));
  const box = $('#out-' + c.id);
  if (box && log.parentNode !== box) box.appendChild(log);
}
