/* The run trace beside the code (Bret Victor's "Inventing on Principle"): each traced line of a cell ends in a muted strip of the values
 * it made, one column per pass, and a step bar under the cell scrubs the run. The strips are CodeMirror decorations and the bar is
 * ordinary DOM, so the text and the undo history are never touched. An edit to the cell removes them. `trace.js` owns the run and the step. */
const leeLensCols = 8, leeLensClipTo = 14;
const leeLensCss = `
.cm-lee-trace-line { background: color-mix(in srgb, var(--lee-accent) 13%, transparent); }
.lee-lens { display: inline-flex; align-items: baseline; margin-left: 2.5ch; font: 11px/1.35 var(--lee-mono); color: var(--lee-fg4); user-select: none; white-space: pre; vertical-align: baseline; font-variant-ligatures: none; }
.lee-lc { padding: 0 .7em; border-left: 1px solid var(--lee-guide); cursor: pointer; }
.lee-lc.future { opacity: .45; }
.lee-lc.cur { outline: 1px solid var(--lee-accent); outline-offset: -1px; border-radius: 3px; background: var(--lee-bg1); opacity: 1; }
.lee-lp { margin-right: .8em; }
.lee-lp:last-child { margin-right: 0; }
.lee-lp .n { cursor: pointer; }
.lee-lp .n:hover { color: var(--lee-accent); text-decoration: underline; }
.lee-lp .v { color: var(--lee-fg4); }
.lee-lp.chg .v { color: var(--lee-fg); font-weight: 700; }
.lee-lp s { color: var(--lee-fg4); opacity: .7; margin-right: .4em; }
.lee-lf { font: inherit; color: var(--lee-accent); background: none; border: 0; padding: 0 .7em; cursor: pointer; }
.lee-lf:hover { text-decoration: underline; }
.lee-lskip { font-style: italic; padding: 0 .7em; border-left: 1px solid var(--lee-guide); }
.lee-trbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin: 2px 0 0; padding: 3px 8px; font: 11px/1.4 var(--lee-sans); color: var(--lee-fg4); background: var(--lee-bg1); border-top: 1px solid var(--lee-guide); }
.lee-trbar:focus-within, .lee-trbar:focus { outline: 1px solid var(--lee-accent); outline-offset: -1px; }
.lee-trbar input[type=range] { flex: 1 1 120px; min-width: 80px; max-width: 360px; accent-color: var(--lee-accent); }
.lee-trbar button, .lee-trtop button { font: inherit; color: var(--lee-fg2); background: var(--lee-bg); border: 1px solid var(--lee-border); border-radius: 4px; padding: 0 8px; cursor: pointer; }
.lee-trbar button:hover, .lee-trtop button:hover { border-color: var(--lee-accent); color: var(--lee-fg); }
.lee-trbar .lee-trinfo { flex: 1 1 0; min-width: 0; text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lee-trtop { display: flex; gap: 10px; align-items: center; padding: 3px 8px; font: 11px/1.4 var(--lee-mono); color: var(--lee-fg4); background: var(--lee-bg1); border-bottom: 1px solid var(--lee-guide); }
.lee-trtop b { color: var(--lee-fg); }
.lee-trtop svg { cursor: crosshair; flex: none; }
.lee-trcleared { padding: 2px 8px; font: 11px/1.4 var(--lee-sans); color: var(--lee-fg4); }
:root[data-density="tight"] .lee-lens { font-size: 10px; }
:root[data-density="tight"] .lee-trbar, :root[data-density="tight"] .lee-trtop { padding-top: 1px; padding-bottom: 1px; }
`;
const leeLens = {kit: undefined, view: null, id: null, on: false, pin: {}, seen: new WeakSet(), css: false};

//: Pure part: the model and a step in, the text of each strip out. Tested in node.
const leeLensClip = (s, n = leeLensClipTo) => { s = String(s ?? ''); return s.length > n ? s.slice(0, n - 1) + '…' : s; };
const leeLensRowsOf = new WeakMap();
//: Per line, the passes that kept values (skips apart) and the count skipped; and the index of each step number among the states.
function leeLensRows(m) {
  let r = leeLensRowsOf.get(m); if (r) return r;
  const rows = new Map(), idx = new Map();
  for (const row of m.table.lines) rows.set(row.line, {its: row.iterations.filter(x => x.skip == null), skipped: row.skipped || 0});
  m.states.forEach((s, i) => idx.set(s.step, i));
  r = {rows, idx}; leeLensRowsOf.set(m, r); return r;
}
//: The index of the last pass at or before `step`, or -1 when the line has not run yet.
function leeLensAt(its, step) {
  let lo = 0, hi = its.length - 1, at = -1;
  while (lo <= hi) { const k = (lo + hi) >> 1; if (its[k].step <= step) { at = k; lo = k + 1; } else hi = k - 1; }
  return at;
}
//: Roughly how wide a column draws, in px, in the 11px strip font.
const leeLensPx = c => (c.parts.reduce((n, q) => n + q.n.length + 2 + Math.min(String(q.v).length, leeLensClipTo) + (q.was != null ? Math.min(String(q.was).length, leeLensClipTo) + 1 : 0), 0) + 2) * 6.7 + 4;
/* One line's strip at `step`: at most `leeLensCols` columns round the current pass, or from `pin`, and fewer when `room` px would not hold them,
 * dropping the ones farthest from the current pass. Null when the line made no values. */
function leeLensLine(m, step, line, pin, room = Infinity) {
  const row = leeLensRows(m).rows.get(line);
  if (!row || !row.its.some(x => Object.keys(x.values).length)) return null;
  const its = row.its, n = its.length, cur = leeLensAt(its, step), W = leeLensCols;
  let from = n <= W ? 0 : Math.max(0, Math.min(pin ?? Math.max(cur, 0) - 3, n - W));
  let cols = its.slice(from, from + W).map((x, k) => ({i: from + k, step: x.step, cur: from + k === cur, future: from + k > cur,
    parts: Object.keys(x.values).map(nm => ({n: nm, v: x.values[nm], was: x.was && nm in x.was ? (x.was[nm] ?? '–') : null, chg: (x.changed || []).includes(nm)}))}));
  const fixed = (row.skipped ? 170 : 0) + (n > cols.length ? 60 : 0);
  let used = cols.reduce((t, c) => t + leeLensPx(c), fixed);
  while (cols.length > 1 && used > room) {
    const drop = Math.abs(cur - cols[0].i) > Math.abs(cols[cols.length - 1].i - cur) ? 0 : cols.length - 1;
    used -= leeLensPx(cols[drop]); cols = drop ? cols.slice(0, -1) : cols.slice(1);
  }
  from = cols[0].i;
  return {line, cols, before: from, after: n - from - cols.length, skipped: row.skipped, cur, total: n};
}
//: The text of one column, `mid=3  low=4`, with `2→3` for a value that differs from the last run.
const leeLensText = c => c.parts.map(p => `${p.n}=${p.was != null ? p.was + '→' : ''}${p.v}`).join('  ');
//: Every line that has a strip at `step`, as {line: text of its current column}.
function leeLensTexts(m, step) {
  const out = {};
  for (const line of leeLensRows(m).rows.keys()) { const p = leeLensLine(m, step, line); const c = p && p.cols.find(x => x.cur); if (c) out[line] = leeLensText(c); }
  return out;
}

//: The strip as DOM. A name plots its series; a column jumps to its step; a fold slides the window.
function leeLensEl(p) {
  const el = document.createElement('span'); el.className = 'lee-lens'; el.setAttribute('role', 'group'); el.setAttribute('aria-label', `values of line ${p.line}`);
  const fold = (txt, from, title) => { const b = document.createElement('button'); b.type = 'button'; b.className = 'lee-lf'; b.textContent = txt; b.title = title;
    b.onmousedown = e => { e.preventDefault(); e.stopPropagation(); }; b.onclick = e => { e.preventDefault(); e.stopPropagation(); leeLensPin(p.line, from); }; el.append(b); };
  if (p.before) fold(`‹ ${p.before}`, p.before - leeLensCols, `${p.before} earlier passes`);
  for (const c of p.cols) {
    const col = document.createElement('span'); col.className = 'lee-lc' + (c.cur ? ' cur' : '') + (c.future ? ' future' : ''); col.dataset.step = c.step; col.dataset.i = c.i;
    col.title = `pass ${c.i + 1} of ${p.total}: ${leeLensText(c)}`;
    col.onclick = e => { e.preventDefault(); e.stopPropagation(); leeTraceJump(c.step); };
    c.parts.forEach((q, k) => {
      if (k) col.append(' ');
      const part = document.createElement('span'); part.className = 'lee-lp' + (q.chg ? ' chg' : '');
      const nm = Object.assign(document.createElement('span'), {className: 'n', textContent: q.n, title: `plot ${q.n}`});
      nm.onclick = e => { e.preventDefault(); e.stopPropagation(); leeTracePlot(q.n); };
      part.append(nm, '=');
      if (q.was != null) part.append(Object.assign(document.createElement('s'), {textContent: leeLensClip(q.was), title: `last run: ${q.was}`}));
      part.append(Object.assign(document.createElement('span'), {className: 'v', textContent: leeLensClip(q.v), title: String(q.v)}));
      col.append(part);
    });
    if (!c.parts.length) col.textContent = '·';
    el.append(col);
  }
  if (p.skipped) el.append(Object.assign(document.createElement('span'), {className: 'lee-lskip', textContent: `⋯ skipped ${p.skipped} passes`, title: 'the tracer keeps the first passes and counts the rest'}));
  if (p.after) fold(`+${p.after} ›`, p.before + leeLensCols, `${p.after} later passes`);
  return el;
}

//: CodeMirror's own classes, taken from a view that is already running, so no second copy of the editor loads. Null when they are not there.
function leeLensKit(view) {
  if (leeLens.kit !== undefined) return leeLens.kit;
  try {
    let eff; LeeCM.setInlineValues({dispatch: tr => { eff = tr.effects; }}, []);
    const StateEffect = eff.constructor, EditorView = view.constructor, probe = LeeCM.create(document.createElement('div'), {doc: 'x'});
    LeeCM.setInlineValues(probe, [{line: 1, name: 'x', value: '', type: ''}]);
    let dec; for (const s of probe.state.facet(EditorView.decorations)) { if (typeof s === 'function') continue; const c = s.iter(); if (c.value?.widget) { dec = c.value; break; } }
    LeeCM.destroy(probe);
    const WidgetType = Object.getPrototypeOf(dec.widget.constructor), Decoration = Object.getPrototypeOf(dec.constructor);
    if (typeof Decoration.widget !== 'function' || typeof StateEffect.appendConfig?.of !== 'function') throw new Error('no decoration api');
    class LensWidget extends WidgetType {
      constructor(p) { super(); this.p = p; this.key = JSON.stringify(p); }
      eq(o) { return o.key === this.key; }
      toDOM() { return leeLensEl(this.p); }
    }
    const poke = StateEffect.define();
    const deco = v => {
      const L = leeLens, m = lee.trace?.model;
      if (!L.on || L.view !== v || !m) return Decoration.none;
      const step = m.states[lee.trace.step]?.step, cur = m.states[lee.trace.step]?.line, doc = v.state.doc, seen = new Set(), out = [];
      for (const r of v.visibleRanges) for (let n = doc.lineAt(r.from).number, end = doc.lineAt(r.to).number; n <= end; n++) {
        if (seen.has(n)) continue; seen.add(n);
        const line = doc.line(n);
        if (n === cur) out.push(Decoration.line({class: 'cm-lee-trace-line'}).range(line.from));
        const p = leeLensLine(m, step, n, L.pin[n], v.scrollDOM.clientWidth - 40 - line.length * v.defaultCharacterWidth);
        if (p) out.push(Decoration.widget({widget: new LensWidget(p), side: 1}).range(line.to));
      }
      return Decoration.set(out, true);
    };
    const ext = [EditorView.decorations.of(deco), EditorView.updateListener.of(u => { if (u.docChanged && leeLens.on && leeLens.view === u.view) leeLensEdited(); })];
    return leeLens.kit = {StateEffect, EditorView, poke, ext};
  } catch (e) { console.warn('inline trace unavailable', e); return leeLens.kit = null; }
}
function leeLensPoke(view = leeLens.view) {
  const k = leeLens.kit; if (!view || !k) return;
  try { view.dispatch({effects: k.poke.of(1)}); } catch (e) { /* the editor is gone */ }
}
function leeLensPin(line, from) { leeLens.pin[line] = Math.max(0, from); leeLensPoke(); }

function leeLensStyle() {
  if (leeLens.css || typeof document === 'undefined') return;
  leeLens.css = true; document.head.append(Object.assign(document.createElement('style'), {id: 'lee-lens-css', textContent: leeLensCss}));
}

//: The step bar under the cell: prev, slider, next, where we are, a note, and a plain close. Arrows step and Escape closes while it has focus.
function leeLensBar() {
  const t = lee.trace, m = t.model, id = leeLens.id, host = $('#cm-' + id); if (!m || !host) return;
  let bar = $('#trbar-' + id);
  if (!bar) {
    bar = Object.assign(document.createElement('div'), {id: 'trbar-' + id, className: 'lee-trbar', tabIndex: 0});
    bar.setAttribute('role', 'group'); bar.setAttribute('aria-label', 'Run trace. Left and right arrows step through the run. Escape closes it.');
    bar.innerHTML = `<button type="button" data-d="-1" title="previous step (Left)">‹ prev</button>` +
      `<input type="range" min="0" value="0" aria-label="step of the traced run" tabindex="-1">` +
      `<button type="button" data-d="1" title="next step (Right)">next ›</button><span class="lee-trpos" role="status" aria-live="polite"></span>` +
      `<span class="lee-trinfo"></span><button type="button" data-close title="remove the trace from the cell (Escape)">close trace</button>`;
    bar.oninput = e => { if (e.target.matches('input')) leeTraceScrub(+e.target.value); };
    bar.onclick = e => { const b = e.target.closest('button'); if (!b) return; if (b.dataset.close != null) leeTraceClose(); else leeTraceScrub(lee.trace.step + +b.dataset.d); };
    bar.onkeydown = e => {
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      const d = {ArrowLeft: -1, ArrowRight: 1, Home: -1e9, End: 1e9}[e.key];
      if (d != null) { e.preventDefault(); e.stopPropagation(); leeTraceScrub(lee.trace.step + d); }
      else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); leeTraceClose(); }
    };
    host.after(bar);
  }
  const r = $('input', bar); r.max = Math.max(0, m.states.length - 1); r.value = t.step;
  $('.lee-trpos', bar).textContent = `step ${t.step + 1} of ${m.states.length} · line ${m.states[t.step]?.line ?? ''}`;
  const info = $('.lee-trinfo', bar); info.textContent = info.title = leeTraceInfo();
  return bar;
}

//: The plot of one name above the code: its numbers over the whole run, a dot at this step; a click on the plot jumps there.
function leeLensTop() {
  const t = lee.trace, m = t.model, id = leeLens.id, host = $('#cm-' + id); if (!m || !host) return;
  let top = $('#trtop-' + id);
  if (!t.plot || !m.series[t.plot]) { top?.remove(); return; }
  if (!top) { top = Object.assign(document.createElement('div'), {id: 'trtop-' + id, className: 'lee-trtop'}); host.before(top); }
  const s = m.series[t.plot], st = m.states[t.step], W = 280, H = 34, svg = leeTraceSpark(s, st?.step ?? 0, W, H);
  const nums = s.points.filter(p => p.value != null).map(p => p.value);
  top.innerHTML = `<b>${esc(t.plot)}</b>` + (svg || `<span>no numbers to plot: ${esc(s.points.length)} values</span>`) +
    (svg ? `<span>${esc(Math.min(...nums))} to ${esc(Math.max(...nums))}</span>` : '') + `<button type="button" title="hide this plot">hide</button>`;
  $('button', top).onclick = () => leeTracePlot(t.plot);
  const sv = $('svg', top);
  if (sv) sv.onclick = e => {
    const pts = s.points.filter(p => p.value != null), box = sv.getBoundingClientRect();
    const k = Math.round((e.clientX - box.left - 1) / (box.width - 2) * (pts.length - 1)); leeTraceJump(pts[Math.max(0, Math.min(k, pts.length - 1))].step);
  };
}

//: Draw the strips and the bar for the run in `lee.trace`. False when the cell has no editor to draw on.
function leeLensShow() {
  const t = lee.trace, i = lee.cells?.findIndex(c => c.id === t.id);
  if (!t.model || i == null || i < 0) return false;
  const view = lee.editors.get(t.id) || ensureCellMounted(i), kit = view && leeLensKit(view);
  if (!kit) return false;
  leeLensStyle(); leeLensHide();
  if (!leeLens.seen.has(view)) { view.dispatch({effects: kit.StateEffect.appendConfig.of(kit.ext)}); leeLens.seen.add(view); }
  Object.assign(leeLens, {view, id: t.id, on: true, pin: {}});
  $('#trcleared-' + t.id)?.remove();
  leeLensBar(); leeLensTop(); leeLensPoke(); leeLensScroll();
  return true;
}
//: The step moved: redraw the bar, the plot and the strips, and keep the current line in view.
function leeLensStep() {
  if (!leeLens.on) return;
  if (lee.editors.get(leeLens.id) !== leeLens.view) return leeLensHide();
  leeLens.pin = {}; leeLensBar(); leeLensTop(); leeLensPoke(); leeLensScroll();
}
function leeLensScroll() {
  const L = leeLens, s = lee.trace.model?.states[lee.trace.step]; if (!L.on || !s || !L.kit) return;
  try {
    const doc = L.view.state.doc, line = doc.line(Math.max(1, Math.min(s.line, doc.lines)));
    L.view.dispatch({effects: L.kit.EditorView.scrollIntoView(line.from, {y: 'nearest', yMargin: 24})});
  } catch (e) { /* the editor is gone */ }
}
//: Take every strip, line mark, bar and plot off the cell. The text and the undo history stay as they were.
function leeLensHide() {
  const L = leeLens, id = L.id;
  if (id) { $('#trbar-' + id)?.remove(); $('#trtop-' + id)?.remove(); }
  const v = L.view; L.on = false; L.id = null; L.view = null; L.pin = {};
  leeLensPoke(v);
}
//: The cell's text changed: the values no longer describe it.
function leeLensEdited() {
  const id = leeLens.id; leeLens.on = false;
  queueMicrotask(() => leeTraceInvalidate(id));
}
//: A one-line note where the bar was.
function leeLensCleared(id, text) {
  $('#trcleared-' + id)?.remove(); if (!text) return;
  const n = Object.assign(document.createElement('div'), {id: 'trcleared-' + id, className: 'lee-trcleared', textContent: text}); n.setAttribute('role', 'status');
  ($('#out-' + id) || $('#cm-' + id))?.before(n);
}
