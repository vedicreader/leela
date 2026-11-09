/* Scrub a number: hold Alt and drag a number in a Python cell, or put the caret on it and press Alt+Up or Alt+Down.
 * The text changes at once. A cell that is safe to run over and over (`scrub_ok`, nb/scrub.py) re-runs at most every
 * 150 ms; the output it had before stays beside the new one as a ghost until the next ordinary run. */
const leeScrubPx = 4, leeScrubGap = 150, leeScrubLimit = 1000, leeScrubIdle = 700;
const leeScrubS = {drag: null, key: null, mouse: null, hint: null};

//: Every number in `text` that a drag may change: not in a string or comment, not part of a name, not `1e5`, `0x1f`, `1_000` or `2j`.
function leeScrubScan(text) {
  const out = [], n = text.length;
  for (let i = 0; i < n;) {
    const c = text[i];
    if (c === '#') { while (i < n && text[i] !== '\n') i++; continue; }
    if (c === '"' || c === "'") {
      const q = text.startsWith(c.repeat(3), i) ? c.repeat(3) : c;
      for (i += q.length; i < n && !text.startsWith(q, i); i++) if (text[i] === '\\') i++; else if (q.length === 1 && text[i] === '\n') break;
      i += q.length; continue;
    }
    if (/[A-Za-z_]/.test(c)) { while (i < n && /\w/.test(text[i])) i++; continue; }
    if (!/\d/.test(c) && !(c === '.' && /\d/.test(text[i + 1] || ''))) { i++; continue; }
    const m = /\d+\.?\d*|\.\d+/y; m.lastIndex = i;
    const [tok] = m.exec(text), end = i + tok.length;
    if (/[\w.]/.test(text[end] || '')) { i = end; while (i < n && /[\w.]/.test(text[i])) i++; continue; }
    let j = i - 1; while (text[j] === ' ' || text[j] === '\t') j--;
    let from = i, signed = false;
    if (text[j] === '-') {
      let k = j - 1; while (text[k] === ' ' || text[k] === '\t') k--;
      if (k < 0 || /[\n=(,\[{:*\/+\-<>%&|^~!@;]/.test(text[k])) { from = j; signed = true; }
    }
    out.push({from, to: end, text: text.slice(from, end), signed}); i = end;
  }
  return out;
}
//: The number in `text` that `pos` is in or touches, or null.
const leeScrubFind = (text, pos) => leeScrubScan(text).find(r => r.from <= pos && pos <= r.to) || null;

//: What one step of a drag is worth: 1 for an integer, a tenth of the last decimal for a float, both raised as the number grows.
function leeScrubUnit(v, floaty, d, fine) {
  const mag = v ? Math.floor(Math.log10(Math.abs(v))) : null;
  const u = floaty ? Math.max(10 ** -(d + 1), mag === null ? 0 : 10 ** (mag - 3)) : Math.max(1, mag === null ? 0 : 10 ** (mag - 2));
  return fine ? (floaty ? u / 10 : Math.max(1, u / 10)) : u;
}
//: `text` moved by `n` steps. `fine` takes a tenth of a step; a number whose minus is not its own stops at 0.
function leeScrubStep(text, n, fine = 0, signed = true) {
  const floaty = text.includes('.'), d = floaty ? text.length - text.indexOf('.') - 1 : 0, v = parseFloat(text);
  const u = leeScrubUnit(v, floaty, d, fine), next = v + n * u, dec = Math.min(8, Math.max(d, Math.round(-Math.log10(u))));
  const s = (signed ? next : Math.max(0, next)).toFixed(dec);
  return Number(s) === 0 ? s.replace('-', '') : s;
}

/* Runs `run(value)` for the newest pushed value, never two at once and never two starts less than `gap` ms apart; values
 * pushed meanwhile are dropped but the last. A run that returns 'stop' ends the gate. `end()` resolves once the last value ran. */
function leeScrubGate(run, gap = leeScrubGap) {
  let has = false, pending, busy = false, last = -Infinity, dead = false, timer = 0;
  const pump = async () => {
    if (busy || !has || dead) return;
    const wait = last + gap - Date.now();
    if (wait > 0) { clearTimeout(timer); timer = setTimeout(pump, wait); return; }
    const v = pending; has = false; busy = true; last = Date.now();
    try { if (await run(v) === 'stop') dead = true; } catch (e) { dead = true; }
    busy = false; pump();
  };
  return {
    push(v) { pending = v; has = true; pump(); },
    stop() { dead = true; clearTimeout(timer); },
    get dead() { return dead; },
    end: () => new Promise(res => { const t = setInterval(() => { if (!busy && (!has || dead)) { clearInterval(t); res(); } }, 10); }),
  };
}

const leeScrubTx = view => view.state.update({}).constructor;
//: Puts `text` over `from`..`to`. `silent` keeps it out of undo, which the ticks of a drag are; the end of it is the one undo step.
function leeScrubPut(view, from, to, text, silent) {
  const T = leeScrubTx(view);
  view.dispatch({changes: {from, to, insert: text}, annotations: [T.userEvent.of('scrub'), ...(silent ? [T.addToHistory.of(false)] : [])]});
}

const leeScrubOn = () => typeof lee !== 'undefined' && lee.kind === 'notebook' && !lee.present && nbLang() === 'python';
//: The code cell the event is in, its editor, and the number under the pointer, or null.
function leeScrubUnder(e) {
  if (!leeScrubOn()) return null;
  const cell = e.target.closest?.('.lee-cell.code'), view = cell && lee.editors.get(cell.dataset.id); if (!view) return null;
  const pos = view.posAtCoords({x: e.clientX, y: e.clientY}, false); if (pos == null) return null;
  const lit = leeScrubFind(view.state.doc.toString(), pos); if (!lit) return null;
  const a = view.coordsAtPos(lit.from), b = view.coordsAtPos(lit.to, -1);
  if (!a || !b || e.clientY < a.top || e.clientY > a.bottom || e.clientX < a.left - 3 || e.clientX > Math.max(a.left, b.left) + 3) return null;
  return {cell, id: cell.dataset.id, view, lit};
}
function leeScrubHint(view, lit) {
  let h = leeScrubS.hint;
  if (!lit) { h?.remove(); leeScrubS.hint = null; document.body.classList.remove('lee-scrub-armed'); return; }
  const a = view.coordsAtPos(lit.from), b = view.coordsAtPos(lit.to, -1); if (!a || !b) return;
  if (!h) { h = leeScrubS.hint = document.createElement('div'); h.className = 'lee-scrub-hint'; document.body.append(h); }
  Object.assign(h.style, {left: a.left + 'px', top: a.bottom - 2 + 'px', width: Math.max(6, b.left - a.left) + 'px'});
  document.body.classList.add('lee-scrub-armed');
}

//: The ghost: the cell's outputs from before the scrub, drawn dimmed after the live ones. Pictures overlay them; text goes beneath.
const leeScrubDrawable = o => !(o.data && (o.data[WIDGET_MIME] != null || o.data[RUPAKA_MIME] != null || o.data[PLOTLY_MIME] != null));
const leeScrubSig = outs => JSON.stringify((outs || []).map(o => o.output_type === 'stream' ? [o.name, o.text] : [o.output_type, o.data, o.ename, o.evalue]));
function leeScrubGhost(c, before) {
  const box = $('#out-' + c.id); if (!box) return;
  let g = $('#ghost-' + c.id);
  if (leeScrubSig(before) === leeScrubSig(c.outputs)) { g?.remove(); return; }
  if (!g) { g = document.createElement('div'); g.id = 'ghost-' + c.id; box.after(g); }
  g.className = 'lee-scrub-ghost'; g.setAttribute('aria-hidden', 'true'); g.textContent = '';
  const inner = g.appendChild(document.createElement('div')); inner.className = 'lee-scrub-ghost-in';
  (before || []).filter(leeScrubDrawable).forEach((o, i) => inner.append(outputEl(o, null, i)));
  const media = !!inner.querySelector('img, svg, iframe, .lee-out-rich'), boxH = box.offsetHeight;
  g.classList.toggle('overlay', media);
  inner.style.top = media ? -boxH + 'px' : '';
}
//: Forget the ghost and the note of cell `id`: an ordinary run has come.
function leeScrubClear(id) { $('#ghost-' + id)?.remove(); $('#note-' + id)?.remove(); }
function leeScrubNote(id, text) {
  let n = $('#note-' + id);
  if (!text) return n?.remove();
  if (!n) { n = document.createElement('div'); n.id = 'note-' + id; n.className = 'lee-scrub-note'; n.setAttribute('role', 'status'); $('#out-' + id)?.before(n); }
  n.textContent = text;
}

/* One gesture on one cell: a drag, or a burst of arrow presses. It owns the gate, the ghost's baseline and the
 * autosave hold, and checks once whether the cell may re-run. */
function leeScrubOpen(view, id) {
  const c = lee.cells.find(x => x.id === id), s = {view, id, before: JSON.parse(JSON.stringify(c?.outputs || [])), ok: false, ran: false};
  lee.scrubbing = true; leeScrubClear(id);
  s.gate = leeScrubGate(v => leeScrubRun(s));
  s.check = post('/nb/scrub/check', {source: view.state.doc.toString()}).then(r => {
    s.ok = !!r.ok; if (!r.ok) leeScrubNote(id, `Not re-running while you scrub: ${r.reason}. Run the cell yourself.`);
    if (s.ok && s.want) s.gate.push(1);
  }).catch(e => leeScrubNote(id, `Not re-running while you scrub: ${e.message || e}`));
  return s;
}
//: A new text is in the editor: run it when the cell may.
function leeScrubChanged(s) { s.want = true; if (s.ok) s.gate.push(1); }
async function leeScrubRun(s) {
  const i = lee.cells.findIndex(x => x.id === s.id), c = lee.cells[i];
  if (!c || c.running) return;
  let slow = false;
  //: An interrupt that lands while the kernel is still starting is lost, so it is sent again until the run ends.
  const stop = async () => { slow = true; try { if ((await post('/nb/interrupt', {path: lee.tabKey || '', id: s.id})).forced) kernelRestarted(); } catch (e) {} };
  let again = 0; const timer = setTimeout(() => { stop(); again = setInterval(stop, leeScrubLimit); }, leeScrubLimit);
  try { await runCell(i, false, {save: false, scrub: true}); } finally { clearTimeout(timer); clearInterval(again); }
  if (slow) { leeScrubNote(s.id, 'Too slow to scrub: the run took more than 1 second and was stopped. Run the cell yourself.'); return 'stop'; }
  s.ran = true; leeScrubGhost(lee.cells.find(x => x.id === s.id) || c, s.before);
}
async function leeScrubClose(s) {
  await s.check; await s.gate.end();
  if (leeScrubS.drag?.s === s) leeScrubS.drag = null; if (leeScrubS.key?.s === s) leeScrubS.key = null;
  lee.scrubbing = false;
  if (autoSaveEnabled()) scheduleAutoSave();
}

function leeScrubDragStart(e, t) {
  e.preventDefault(); e.stopImmediatePropagation();
  const s = leeScrubOpen(t.view, t.id), text = t.view.state.doc.toString();
  selectCell(lee.cells.findIndex(x => x.id === t.id));
  leeScrubS.drag = {s, lit: t.lit, orig: text, base: t.lit.text, cur: t.lit.text, x0: e.clientX, fine: e.shiftKey};
  document.body.classList.add('lee-scrubbing');
}
function leeScrubDragMove(e) {
  const d = leeScrubS.drag; if (!d) return;
  if (e.shiftKey !== d.fine) { d.fine = e.shiftKey; d.base = d.cur; d.x0 = e.clientX; }
  const text = leeScrubStep(d.base, Math.round((e.clientX - d.x0) / leeScrubPx), d.fine, d.lit.signed);
  if (text === d.cur) return;
  leeScrubPut(d.s.view, d.lit.from, d.lit.from + d.cur.length, text, true);
  d.cur = text; leeScrubHint(d.s.view, {from: d.lit.from, to: d.lit.from + text.length});
  leeScrubChanged(d.s);
}
//: The drag is over. `keep` false is Escape: the text goes back and nothing is undoable.
function leeScrubDragEnd(keep) {
  const d = leeScrubS.drag; if (!d) return;
  document.body.classList.remove('lee-scrubbing'); leeScrubHint(null, null);
  const {view} = d.s, lit = d.lit;
  if (d.cur !== d.lit.text) {
    leeScrubPut(view, lit.from, lit.from + d.cur.length, lit.text, true);
    if (keep) leeScrubPut(view, lit.from, lit.to, d.cur, false);
    else d.s.gate.stop();
  }
  const s = d.s; leeScrubS.drag = null;
  if (keep && d.cur !== lit.text) LeeCM.focus(view);
  return leeScrubClose(s);
}

//: Alt+Up or Alt+Down on a number moves it one step, Shift for a tenth of one.
function leeScrubKey(e) {
  if (!e.altKey || e.ctrlKey || e.metaKey || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') || !leeScrubOn()) return;
  const cell = e.target.closest?.('.lee-cell.code'), view = cell && lee.editors.get(cell.dataset.id);
  if (!view || !view.hasFocus || !view.state.selection.main.empty) return;
  const lit = leeScrubFind(view.state.doc.toString(), view.state.selection.main.head); if (!lit) return;
  e.preventDefault(); e.stopImmediatePropagation();
  let k = leeScrubS.key;
  if (!k || k.s.id !== cell.dataset.id) k = leeScrubS.key = {s: leeScrubOpen(view, cell.dataset.id), timer: 0};
  clearTimeout(k.timer); k.timer = setTimeout(() => leeScrubClose(k.s), leeScrubIdle);
  const text = leeScrubStep(lit.text, e.key === 'ArrowUp' ? 1 : -1, e.shiftKey, lit.signed); if (text === lit.text) return;
  const head = view.state.selection.main.head;
  leeScrubPut(view, lit.from, lit.to, text, false);
  view.dispatch({selection: {anchor: Math.min(head + text.length - lit.text.length, lit.from + text.length)}});
  leeScrubChanged(k.s);
}

function leeScrubInstall() {
  const hover = (m, alt) => {
    if (leeScrubS.drag) return;
    const t = alt && leeScrubUnder(m); leeScrubHint(t?.view, t?.lit);
  };
  window.addEventListener('pointermove', e => {
    leeScrubS.mouse = {target: e.target, clientX: e.clientX, clientY: e.clientY};
    if (leeScrubS.drag) leeScrubDragMove(e); else hover(e, e.altKey);
  }, true);
  window.addEventListener('pointerdown', e => {
    if (e.button !== 0 || !e.altKey || leeScrubS.drag) return;
    const t = leeScrubUnder(e); if (t) leeScrubDragStart(e, t);
  }, true);
  // The compatibility mouse events follow a cancelled pointerdown only in some engines, so the editor's own listener is shut out too.
  window.addEventListener('mousedown', e => { if (leeScrubS.drag) { e.preventDefault(); e.stopImmediatePropagation(); } }, true);
  window.addEventListener('pointerup', e => { if (leeScrubS.drag) leeScrubDragEnd(true); }, true);
  window.addEventListener('pointercancel', () => leeScrubDragEnd(false), true);
  window.addEventListener('keydown', e => {
    if (e.key === 'Escape' && leeScrubS.drag) { e.preventDefault(); e.stopImmediatePropagation(); leeScrubDragEnd(false); return; }
    if (e.key === 'Alt' && leeScrubS.mouse) hover(leeScrubS.mouse, true);
    leeScrubKey(e);
  }, true);
  window.addEventListener('keyup', e => { if (e.key === 'Alt' && !leeScrubS.drag) leeScrubHint(null, null); }, true);
  window.addEventListener('blur', () => { if (!leeScrubS.drag) leeScrubHint(null, null); });
}
if (typeof document !== 'undefined' && typeof window.addEventListener === 'function') leeScrubInstall();
