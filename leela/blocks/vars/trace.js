/* The run trace: `Trace this run` runs the selected cell once with a line tracer on. The values then sit beside the code
 * (`nb/tracelens.js`), a step bar scrubs the one run, and this pane keeps the names and numbers of the current step. */
const leeTraceCss = `
.lee-varspanel.tracing > #vars, .lee-varspanel.tracing > .lee-filterbar { display: none; }
.lee-varspanel > #tracebox { display: none; }
.lee-varspanel.tracing > #tracebox { display: block; overflow: auto; flex: 1; min-height: 0; padding: 6px 8px; font: 11px/1.45 var(--lee-mono); color: var(--lee-fg); }
#tracebox .lee-trhead { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 6px; font-family: var(--lee-sans); }
#tracebox .lee-trnote { color: var(--lee-fg4); font-family: var(--lee-sans); font-size: 11px; }
#tracebox .lee-trslide { display: flex; gap: 8px; align-items: center; margin: 4px 0 6px; }
#tracebox .lee-trslide input { flex: 1; min-width: 0; }
#tracebox .lee-trvals { border: 1px solid var(--lee-border); border-radius: 4px; padding: 4px 6px; margin-bottom: 6px; background: var(--lee-bg1); }
#tracebox .lee-trval { display: flex; gap: 6px; align-items: center; white-space: nowrap; }
#tracebox .lee-trval button { font: inherit; font-weight: 600; min-width: 4ch; text-align: left; background: none; border: 0; padding: 0; color: var(--lee-fg); cursor: pointer; }
#tracebox .lee-trval button:hover, #tracebox .lee-trval button.on { color: var(--lee-accent); }
#tracebox .lee-trval span.v { overflow: hidden; text-overflow: ellipsis; max-width: 18ch; }
#tracebox .lee-trval svg { flex: none; }
#tracebox .lee-trerr { color: var(--lee-red); }
`;
function leeTraceStyle() {
  if (document.getElementById('lee-trace-css')) return;
  document.head.append(Object.assign(document.createElement('style'), {id: 'lee-trace-css', textContent: leeTraceCss}));
}
lee.trace = lee.trace || {model: null, id: null, step: 0, ok: null};

function leeTraceSpark(series, step, w = 70, h = 14) {
  const pts = (series?.points || []).filter(p => p.value != null);
  if (!series?.numeric || pts.length < 2) return '';
  const lo = Math.min(...pts.map(p => p.value)), hi = Math.max(...pts.map(p => p.value)), span = (hi - lo) || 1;
  const x = i => 1 + i * (w - 2) / (pts.length - 1), y = v => h - 2 - (v - lo) * (h - 4) / span;
  let at = -1; pts.forEach((p, i) => { if (p.step <= step) at = i; });
  const d = pts.map((p, i) => `${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ');
  const dot = at >= 0 ? `<circle cx="${x(at).toFixed(1)}" cy="${y(pts[at].value).toFixed(1)}" r="2" fill="var(--lee-accent)"/>` : '';
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-label="timeline of ${esc(series.name)}"><polyline points="${d}" fill="none" stroke="var(--lee-fg4)" stroke-width="1"/>${dot}</svg>`;
}

function leeTraceCell(x, curStep) {
  if (x.skip != null) return `<div class="lee-trit skip" title="${x.skip} passes not kept">⋯ ${x.skip}</div>`;
  const names = Object.keys(x.values || {});
  const body = names.map(n => {
    const was = x.was && n in x.was ? `<s title="previous run">${esc(x.was[n] ?? '–')}</s>` : '';
    return `<div title="${esc(n)} = ${esc(x.values[n])}">${was}<b>${esc(n)}</b>=${esc(x.values[n])}</div>`;
  }).join('');
  const cls = ['lee-trit', x.changed?.length ? 'chg' : '', x.step === curStep ? 'cur' : '', x.was && Object.keys(x.was).length ? 'diff' : ''].join(' ');
  return `<div class="${cls}" data-step="${x.step}">${body || '<span class="lee-trnote">·</span>'}</div>`;
}

function leeTraceDraw() {
  const box = $('#tracebox'), t = lee.trace, m = t.model; if (!box) return;
  if (m && t.tab !== lee.tabKey) { leeLensHide(); Object.assign(t, {model: null, id: null, plot: null}); }
  const head = `<div class="lee-trhead"><button class="lee-btn go" id="tracerun" onclick="leeTraceRun()">Trace this run</button>` +
    `<span class="lee-trnote" id="tracenote"></span></div>`;
  if (!t.model) { box.innerHTML = head + `<div class="lee-trnote">${t.why ? esc(t.why) : 'Select a code cell and press Trace this run. The values of each line then appear beside the code, one column for each pass.'}</div>`; return leeTraceNote(); }
  box.innerHTML = head +
    `<div class="lee-trslide"><span class="lee-trnote">step</span><input type="range" id="tracestep" min="0" max="${Math.max(0, t.model.states.length - 1)}" value="${t.step}" oninput="leeTraceScrub(+this.value)" aria-label="scrub the steps of this run"><span class="lee-trnote" id="tracepos"></span></div>` +
    `<div class="lee-trvals" id="tracevals"></div>`;
  leeTraceNote(); leeTraceValues();
}

//: The one line under the pane's button and in the step bar.
function leeTraceInfo() {
  const t = lee.trace, m = t.model; if (!m) return '';
  const bits = [`${m.table.steps} steps`];
  if (m.truncated) bits.push(`cut short: ${m.reason || 'limit reached'}`);
  if (m.has_prev) bits.push(m.table.diffs ? `${m.table.diffs} value${m.table.diffs === 1 ? '' : 's'} differ from the last run (old value struck through)` : 'same as the last run');
  if (t.ok === false) bits.push('the cell raised an error');
  return bits.join(' · ');
}
function leeTraceNote() {
  const n = $('#tracenote'); if (n) n.textContent = leeTraceInfo();
}

function leeTraceValues() {
  const t = lee.trace, m = t.model, s = m?.states[t.step], box = $('#tracevals'); if (!box || !s) return;
  const names = Object.keys(s.values);
  box.innerHTML = `<div class="lee-trnote">line ${s.line} · ${esc(s.event)}${s.depth > 1 ? ' · depth ' + s.depth : ''}${s.approx ? ' · approximate: passes were skipped' : ''}</div>` +
    (names.map(n => `<div class="lee-trval"><button type="button" class="${t.plot === n ? 'on' : ''}" data-name="${esc(n)}" title="plot ${esc(n)} above the code" onclick="leeTracePlot(this.dataset.name)">${esc(n)}</button><span class="v" title="${esc(s.values[n])}">${esc(s.values[n])}</span>${leeTraceSpark(m.series[n], s.step)}</div>`).join('') || '<div class="lee-trnote">no names yet</div>');
  const pos = $('#tracepos'); if (pos) pos.textContent = `${t.step + 1} / ${m.states.length}`;
}

function leeTraceScrub(i) {
  const t = lee.trace; if (!t.model) return;
  t.step = Math.max(0, Math.min(Math.round(i) || 0, t.model.states.length - 1));
  const sl = $('#tracestep'); if (sl) sl.value = t.step;
  leeTraceValues(); leeLensStep();
}
//: Jump to the pass whose step number is `step`.
function leeTraceJump(step) {
  const k = lee.trace.model && leeLensRows(lee.trace.model).idx.get(step);
  if (k != null) leeTraceScrub(k);
}
//: Plot one name's series above the code; the same name again hides it.
function leeTracePlot(name) {
  const t = lee.trace; if (!t.model) return;
  t.plot = t.plot === name ? null : name;
  leeTraceValues(); leeLensStep();
}
//: Remove the trace from the page: strips, bar, plot and the pane's numbers. Nothing in the cell changes.
function leeTraceClose(focus = true) {
  const t = lee.trace, id = t.id; leeLensHide(); leeLensCleared(id, '');
  Object.assign(t, {model: null, id: null, plot: null, why: ''}); leeTraceDraw();
  const v = id && lee.editors.get(id); if (v && focus) LeeCM.focus(v);
}
//: The cell was edited: its trace no longer describes it.
function leeTraceInvalidate(id) {
  const t = lee.trace; if (!t.model || t.id !== id) return;
  leeLensHide(); leeLensCleared(id, 'Trace cleared: the cell changed.');
  Object.assign(t, {model: null, id: null, plot: null, why: 'Trace cleared: the cell changed.'}); leeTraceDraw();
}

async function leeTraceRun() {
  const i = lee.sel, c = lee.cells?.[i];
  if (!c || c.cell_type !== 'code') return status('select a code cell to trace', 'err');
  if (c.running) return status(`cell ${i + 1} is already running`, 'err');
  await lee.nbQueue;
  const runKey = lee.tabKey, id = c.id, v = ensureCellMounted(i), src = v ? LeeCM.getDoc(v) : c.source;
  if (lee.path && $('.lee-tab.active.dirty') && !await saveTab(true)) return status('the notebook could not be saved first', 'err');
  const btn = $('#tracerun'); if (btn) btn.disabled = true;
  c.running = true; setCellState(c, 'running'); status(`tracing cell ${i + 1}…`);
  try {
    const r = await withPython(() => post('/vars/trace', {path: runKey, id, source: src, seq: nextSeq(), ...seenRow(runKey, id)}));
    const at = lee.tabKey === runKey ? lee.cells.find(x => x.id === id) : null;
    if (at) { Object.assign(at, r.cell); renderOutputs(at); cellOutputEvent(id, at.outputs || []); $('#g-' + id).textContent = '[' + (r.cell.execution_count ?? ' ') + ']'; setCellState(at, r.ok ? 'done' : 'error'); }
    leeTraceShow(r.trace, id, r.ok);
    status(r.ok ? `traced cell ${i + 1}: ${r.trace.table.steps} steps` : `cell ${i + 1} raised an error · its trace stops there`, r.ok ? 'ok' : 'err');
  } catch (e) { status(String(e.message || e), 'err'); setCellState(c, 'error'); }
  finally { c.running = false; if ($('#tracerun')) $('#tracerun').disabled = false; leeVars(); }
}

function leeTraceShow(model, id, ok = true) {
  leeLensHide();
  Object.assign(lee.trace, {model, id, ok, tab: lee.tabKey, plot: null, step: Math.max(0, (model?.states?.length || 1) - 1), why: ''});
  $('.lee-varspanel')?.classList.add('tracing'); $('#tracebtn')?.classList.add('active');
  leeTraceDraw();
  if (!leeLensShow()) { lee.trace.why = 'The values could not be drawn beside the code; the pane lists them.'; }
  $('#trbar-' + id)?.focus({preventScroll: true});
}

async function leeTraceToggle() {
  const panel = $('.lee-varspanel'); if (!panel) return;
  leeTraceStyle();
  if (!$('#tracebox')) panel.append(Object.assign(document.createElement('div'), {id: 'tracebox'}));
  const on = !panel.classList.contains('tracing');
  panel.classList.toggle('tracing', on); $('#tracebtn')?.classList.toggle('active', on);
  if (!on) return leeTraceClose(false);
  try { const s = await api('/vars/trace/support'); lee.trace.why = s.ok ? '' : `Tracing ${s.why}.`; lee.trace.can = !!s.ok; }
  catch (e) { lee.trace.why = String(e.message || e); lee.trace.can = false; }
  if (lee.trace.can && !lee.trace.model && lee.path && lee.cells?.[lee.sel]) {
    try { const d = await api(`/vars/trace/last?path=${encodeURIComponent(lee.tabKey)}&id=${encodeURIComponent(lee.cells[lee.sel].id)}`); if (d.trace && d.trace.source === LeeCM.getDoc(ensureCellMounted(lee.sel))) leeTraceShow(d.trace, lee.cells[lee.sel].id, true); } catch (e) {}
  }
  leeTraceDraw();
  if (!lee.trace.can) { const b = $('#tracerun'); if (b) { b.disabled = true; b.title = lee.trace.why; } }
}

function leeTraceInit() {
  const head = $('.lee-varspanel .lee-phead'); if (!head || $('#tracebtn')) return;
  head.insertBefore(Object.assign(document.createElement('button'), {id: 'tracebtn', className: 'lee-seg', textContent: 'trace', title: 'run the selected cell and see the values of each line, pass by pass', onclick: leeTraceToggle}), head.querySelector('.lee-spacer'));
}
window.leeTraceRun = leeTraceRun; window.leeTraceScrub = leeTraceScrub; window.leeTraceToggle = leeTraceToggle; window.leeTraceShow = leeTraceShow; window.leeTracePlot = leeTracePlot; window.leeTraceJump = leeTraceJump; window.leeTraceClose = leeTraceClose;
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', leeTraceInit); else leeTraceInit();
