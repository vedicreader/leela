/* Scrub a number: hold Alt and drag a number in a Python cell, or put the caret on it and press Alt+Up or Alt+Down, or run
 * "nudge the number" or "scrub the number" from the palette. The text changes at once. A cell that passes the server's scrub check
 * (nb/scrub.py) re-runs lightly at most every 150 ms, and the output before stays beside the new one as a ghost until an ordinary run. */
const leeScrubPx = 4, leeScrubGap = 150, leeScrubIdle = 700, leeScrubMax = 1e6, leeScrubGrow = 100;
//: When false a scrub only changes the number and never re-runs the cell.
const leeScrubLive = true;
const leeScrubS = {drag: null, mouse: null, hint: null, warm: '', off: new Set()};
const leeScrubStartCh = /[\p{L}_]/u, leeScrubWordCh = /[\p{L}\p{N}\p{M}_]/u;
const leeScrubKw = new Set('return yield await assert not and or in is if elif while else lambda del raise from import as with for'.split(' '));
const leeScrubNum = /(?:\d[\d_]*(?:\.[\d_]*)?|\.\d[\d_]*)(?:[eE][+-]?[\d_]+)?[jJ]?|0[xXoObB]\w*/y;

//: Whether the minus just before position `j` is a sign and not a subtraction: nothing, an operator or a keyword comes before it.
function leeScrubUnary(text, j) {
  let k = j - 1; while (k >= 0 && /\s/.test(text[k])) k--;
  if (k < 0 || /[=(,\[{:*\/+\-<>%&|^~!@;]/.test(text[k])) return true;
  let w = k; while (w >= 0 && leeScrubWordCh.test(text[w])) w--;
  return w < k && leeScrubKw.has(text.slice(w + 1, k + 1));
}
//: Every number in `text` that a drag may change: plain decimals, not in a string or comment, not part of a name, no exponent, hex, `_` or `j`.
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
    if (leeScrubStartCh.test(c)) { while (i < n && leeScrubWordCh.test(text[i])) i++; continue; }
    if (!/\d/.test(c) && !(c === '.' && /\d/.test(text[i + 1] || ''))) { i++; continue; }
    leeScrubNum.lastIndex = i;
    const tok = leeScrubNum.exec(text)[0], end = i + tok.length, plain = /^(?:\d+\.?\d*|\.\d+)$/.test(tok) && !/^0\d+$/.test(tok);
    if (!plain || /[\p{L}\p{N}_.]/u.test(text[end] || '')) { i = end; while (i < n && /[\p{L}\p{N}_.]/u.test(text[i])) i++; continue; }
    const from = text[i - 1] === '-' && leeScrubUnary(text, i - 1) ? i - 1 : i;
    out.push({from, to: end, text: text.slice(from, end), signed: from < i}); i = end;
  }
  return out;
}
//: The number in `text` that `pos` is in or touches, or null.
const leeScrubFind = (text, pos) => leeScrubScan(text).find(r => r.from <= pos && pos <= r.to) || null;

/* `text` moved by `n` steps, in exact decimal arithmetic. A step is 1 for an integer (10 from 1000, 100 from 100000), a tenth of the
 * last decimal for a float, and grows with the number past 1000. `fine` takes a tenth of a step. A number whose minus is not its own stops at 0. */
function leeScrubStep(text, n, fine = 0, signed = true) {
  const m = /^(-?)(\d*)(\.?)(\d*)$/.exec(text); if (!m || !(m[2] || m[4])) return text;
  const neg = m[1] === '-', floaty = !!m[3], d = m[4].length, digits = (m[2] || '0') + m[4], big = BigInt(digits);
  const mag = big === 0n ? null : digits.replace(/^0+/, '').length - 1 - d;
  let e = floaty ? Math.max(-(d + 1), mag === null ? -Infinity : mag - 3) : Math.max(0, mag === null ? -Infinity : mag - 2);
  if (fine) e = floaty ? e - 1 : Math.max(0, e - 1);
  const dec = Math.max(d, -e, 0);
  let v = (neg ? -big : big) * 10n ** BigInt(dec - d) + BigInt(n) * 10n ** BigInt(e + dec);
  if (!signed && v < 0n) v = 0n;
  let s = (v < 0n ? -v : v).toString().padStart(dec + 1, '0');
  if (dec) s = s.slice(0, -dec) + '.' + s.slice(-dec);
  return (v < 0n ? '-' : '') + s;
}
//: How far a number may be dragged from `text`: a million, or a hundred times its size.
const leeScrubWindow = text => Math.min(leeScrubMax, leeScrubGrow * Math.max(1, Math.abs(parseFloat(text)) || 0));

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
const leeScrubDoc = view => view.state.doc.toString();
const leeScrubEditable = view => view.contentDOM.contentEditable !== 'false' && !view.state.readOnly;
const leeScrubOn = () => typeof lee !== 'undefined' && lee.kind === 'notebook' && !lee.present && nbLang() === 'python';
//: The editor of the selected code cell, or null.
function leeScrubView() {
  const c = leeScrubOn() && lee.cells[lee.sel], v = c && c.cell_type === 'code' && lee.editors.get(c.id);
  return v && leeScrubEditable(v) ? v : null;
}
//: The code cell the event is in, its editor, and the number under the pointer, or null.
function leeScrubUnder(e) {
  if (!leeScrubOn()) return null;
  const cell = e.target.closest?.('.lee-cell.code'), view = cell && lee.editors.get(cell.dataset.id);
  if (!view || !leeScrubEditable(view)) return null;
  const pos = view.posAtCoords({x: e.clientX, y: e.clientY}, false); if (pos == null) return null;
  const lit = leeScrubFind(leeScrubDoc(view), pos); if (!lit) return null;
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

//: The ghost: the last good output, drawn dimmed after the live ones. Pictures overlay them; text goes beneath.
const leeScrubDrawable = o => !(o.data && (o.data[WIDGET_MIME] != null || o.data[RUPAKA_MIME] != null || o.data[PLOTLY_MIME] != null));
const leeScrubSig = outs => JSON.stringify((outs || []).map(o => o.output_type === 'stream' ? [o.name, o.text] : [o.output_type, o.data, o.ename, o.evalue]));
const leeScrubBad = outs => (outs || []).some(o => o.output_type === 'error');
function leeScrubGhost(c, before) {
  const box = $('#out-' + c.id); if (!box) return;
  let g = $('#ghost-' + c.id);
  if (leeScrubSig(before) === leeScrubSig(c.outputs)) { g?.remove(); return; }
  if (!g) { g = document.createElement('div'); g.id = 'ghost-' + c.id; box.after(g); }
  g.className = 'lee-scrub-ghost'; g.setAttribute('aria-hidden', 'true'); g.textContent = '';
  const inner = g.appendChild(document.createElement('div')); inner.className = 'lee-scrub-ghost-in';
  (before || []).filter(leeScrubDrawable).forEach((o, i) => inner.append(outputEl(o, null, i)));
  const media = !!inner.querySelector('img, svg, iframe, .lee-out-rich');
  g.classList.toggle('overlay', media);
  inner.style.top = media ? -box.offsetHeight + 'px' : '';
}
//: Forget the ghost and the note of cell `id`: an ordinary run has come.
function leeScrubClear(id) { $('#ghost-' + id)?.remove(); $('#note-' + id)?.remove(); leeScrubS.off.delete(id); }
function leeScrubNote(id, text) {
  let n = $('#note-' + id);
  if (!text) return n?.remove();
  if (!n) { n = document.createElement('div'); n.id = 'note-' + id; n.className = 'lee-scrub-note'; n.setAttribute('role', 'status'); $('#out-' + id)?.before(n); }
  n.textContent = text;
}

/* One gesture on one cell: a drag, a burst of nudges, or a typed value. It owns the gate and the ghost's baseline, and holds autosave while open. */
function leeScrubOpen(view, id) {
  let s = lee.scrubbing.get(id); if (s) return s;
  const c = lee.cells.find(x => x.id === id);
  s = {view, id, good: JSON.parse(JSON.stringify(c?.outputs || [])), ran: false, last: null, ok: true};
  s.gate = leeScrubGate(() => leeScrubRun(s));
  lee.scrubbing.set(id, s); leeScrubClear(id);
  return s;
}
//: A new text is in the editor: run it when the cell may.
const leeScrubChanged = s => { if (leeScrubLive && !leeScrubS.off.has(s.id)) s.gate.push(1); };
async function leeScrubRun(s) {
  const c = lee.cells.find(x => x.id === s.id); if (!c) return 'stop';
  if (c.running) { setTimeout(() => s.gate.push(1), 250); return; }
  const src = leeScrubDoc(s.view);
  let r; try { r = await post('/nb/scrub/run', {path: lee.tabKey || '', id: s.id, source: src, seq: nextSeq(), ...seenRow(lee.tabKey, s.id), first: !s.ran}); }
  catch (e) { leeScrubNote(s.id, `Not re-running while you scrub: ${e.message || e}`); return 'stop'; }
  if (r.busy) { setTimeout(() => s.gate.push(1), 250); return; }
  s.last = src;
  if (r.refused) { s.ok = false; leeScrubNote(s.id, `Not re-running while you scrub: ${r.refused}. Run the cell yourself.`); return; }
  if (r.stuck) { leeScrubS.off.add(s.id); leeScrubNote(s.id, 'The cell does not stop. Scrubbing is off for this cell.'); return 'stop'; }
  if (r.slow) { leeScrubNote(s.id, 'Too slow to scrub: the run took too long and was stopped. Run the cell yourself.'); return 'stop'; }
  s.ok = true; s.ran = true; leeScrubNote(s.id, '');
  c.outputs = r.outputs || []; renderOutputs(c); cellOutputEvent(s.id, c.outputs);
  leeScrubGhost(c, s.good);
  if (!leeScrubBad(c.outputs)) s.good = JSON.parse(JSON.stringify(c.outputs));
}
//: The gesture is over: one last run when the text moved on from what last ran, then autosave is free again.
async function leeScrubClose(s) {
  if (s.closing) return; s.closing = true;
  if (s.ran && !s.gate.dead && !leeScrubS.off.has(s.id) && s.last !== leeScrubDoc(s.view)) s.gate.push(1);
  await s.gate.end();
  const c = lee.cells.find(x => x.id === s.id);
  if (c && s.ran && s.ok && !leeScrubBad(c.outputs)) setCellState(c, 'done', 'ran while scrubbing; the output follows the text');
  lee.scrubbing.delete(s.id);
  if (!lee.scrubbing.size && autoSaveEnabled()) scheduleAutoSave();
}

/* A literal being changed: `set` puts a new text over it without an undo step; `end(true)` makes the one undo step from the original
 * text to the last one, `end(false)` puts the original back. */
function leeScrubGrab(view, id, lit) {
  const s = leeScrubOpen(view, id);
  return {s, view, lit, cur: lit.text,
    set(text) {
      if (text === this.cur) return;
      leeScrubPut(view, lit.from, lit.from + this.cur.length, text, true); this.cur = text; leeScrubChanged(s);
    },
    end(keep) {
      if (this.cur !== lit.text) {
        leeScrubPut(view, lit.from, lit.from + this.cur.length, lit.text, true);
        if (keep) leeScrubPut(view, lit.from, lit.to, this.cur, false);
      }
      if (keep && this.cur !== lit.text) LeeCM.focus(view);
      return leeScrubClose(s);
    }};
}

function leeScrubDragStart(e, t) {
  e.preventDefault(); e.stopImmediatePropagation();
  selectCell(lee.cells.findIndex(x => x.id === t.id));
  leeScrubS.drag = {g: leeScrubGrab(t.view, t.id, t.lit), base: t.lit.text, x0: e.clientX, fine: e.shiftKey, lim: leeScrubWindow(t.lit.text)};
  document.body.classList.add('lee-scrubbing');
}
function leeScrubDragMove(e) {
  const d = leeScrubS.drag; if (!d) return;
  if (!e.buttons) return leeScrubDragEnd(true);
  if (e.shiftKey !== d.fine) { d.fine = e.shiftKey; d.base = d.g.cur; d.x0 = e.clientX; }
  const text = leeScrubStep(d.base, Math.round((e.clientX - d.x0) / leeScrubPx), d.fine, d.g.lit.signed);
  if (Math.abs(parseFloat(text)) > d.lim) return;
  d.g.set(text); leeScrubHint(d.g.view, {from: d.g.lit.from, to: d.g.lit.from + d.g.cur.length});
}
//: `keep` false is Escape or a cancelled pointer: the text goes back and nothing is undoable.
function leeScrubDragEnd(keep) {
  const d = leeScrubS.drag; if (!d) return;
  leeScrubS.drag = null; document.body.classList.remove('lee-scrubbing'); leeScrubHint(null, null);
  const done = d.g.end(keep);
  if (!keep) done.then(() => leeScrubClear(d.g.s.id));
  return done;
}

/* One step up or down on the number at the caret. Nudges within 700 ms of each other are one gesture. */
function leeScrubNudge(dir, fine = false) {
  const view = leeScrubView(); if (!view) return false;
  const head = view.state.selection.main.head, lit = leeScrubFind(leeScrubDoc(view), head);
  if (!lit || !view.state.selection.main.empty) { status('put the caret on a number in a code cell', 'err'); return false; }
  const id = lee.cells[lee.sel].id, s = leeScrubOpen(view, id);
  clearTimeout(s.idle); s.idle = setTimeout(() => leeScrubClose(s), leeScrubIdle);
  const text = leeScrubStep(lit.text, dir, fine, lit.signed); if (text === lit.text) return true;
  leeScrubPut(view, lit.from, lit.to, text, false);
  view.dispatch({selection: {anchor: Math.min(head + text.length - lit.text.length, lit.from + text.length)}});
  leeScrubChanged(s); return true;
}
function leeScrubKey(e) {
  if (!e.altKey || e.ctrlKey || e.metaKey || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') || !e.target.closest?.('.lee-cell.code .cm-content')) return;
  const view = leeScrubView(); if (!view || !view.hasFocus || !view.state.selection.main.empty || !leeScrubFind(leeScrubDoc(view), view.state.selection.main.head)) return;
  e.preventDefault(); e.stopImmediatePropagation();
  leeScrubNudge(e.key === 'ArrowUp' ? 1 : -1, e.shiftKey);
}

//: "Scrub the number under the caret" from the palette: a box takes the new value, typed or spoken, and the cell follows it.
function leeScrubValue() {
  const view = leeScrubView(); if (!view) return status('put the caret in a code cell', 'err');
  const lit = leeScrubFind(leeScrubDoc(view), view.state.selection.main.head);
  if (!lit) return status('put the caret on a number in a code cell', 'err');
  const g = leeScrubGrab(view, lee.cells[lee.sel].id, lit);
  const m = modal(`<div class="lee-mhead">scrub the number<span class="sub">type or say the new value</span></div>` +
    `<input class="lee-input" id="scrubvalue" inputmode="decimal" aria-label="new value" value="${esc(lit.text)}">`);
  const box = $('#scrubvalue', m); let ended = false;
  const finish = keep => { if (ended) return; ended = true; m.remove(); g.end(keep); };
  box.oninput = () => { if (/^-?(\d+\.?\d*|\.\d+)$/.test(box.value.trim()) && (lit.signed || !box.value.trim().startsWith('-'))) g.set(box.value.trim()); };
  box.onkeydown = e => { if (e.key === 'Enter' || e.key === 'Escape') e.preventDefault(); if (e.key === 'Enter') finish(true); else if (e.key === 'Escape') finish(false); e.stopPropagation(); };
  new MutationObserver((_, o) => { if (!m.isConnected) { o.disconnect(); finish(true); } }).observe(document.body, {childList: true});
  box.focus(); box.select();
}

//: Alt held with the pointer over a number: the kernel starts now, so the first tick does not wait for it.
function leeScrubWarm() {
  if (!leeScrubLive || leeScrubS.warm === lee.tabKey) return;
  leeScrubS.warm = lee.tabKey; post('/nb/scrub/warm', {path: lee.tabKey || ''}).catch(() => { leeScrubS.warm = ''; });
}

function leeScrubInstall() {
  lee.scrubbing = new Map();
  const hover = (m, alt) => {
    if (leeScrubS.drag) return;
    const t = alt && leeScrubUnder(m); leeScrubHint(t?.view, t?.lit); if (t) leeScrubWarm();
  };
  window.addEventListener('pointermove', e => {
    leeScrubS.mouse = {target: e.target, clientX: e.clientX, clientY: e.clientY};
    if (leeScrubS.drag) leeScrubDragMove(e); else hover(e, e.altKey);
  }, true);
  window.addEventListener('pointerdown', e => {
    if (e.button !== 0 || !e.altKey || leeScrubS.drag) return;
    const t = leeScrubUnder(e); if (t) leeScrubDragStart(e, t);
  }, true);
  window.addEventListener('mousedown', e => { if (leeScrubS.drag) { e.preventDefault(); e.stopImmediatePropagation(); } }, true);
  window.addEventListener('pointerup', () => leeScrubDragEnd(true), true);
  window.addEventListener('pointercancel', () => leeScrubDragEnd(false), true);
  window.addEventListener('blur', () => { leeScrubDragEnd(true); leeScrubHint(null, null); });
  window.addEventListener('keydown', e => {
    if (e.key === 'Escape' && leeScrubS.drag) { e.preventDefault(); e.stopImmediatePropagation(); leeScrubDragEnd(false); return; }
    if (e.key === 'Alt' && leeScrubS.mouse) hover(leeScrubS.mouse, true);
    leeScrubKey(e);
  }, true);
  window.addEventListener('keyup', e => { if (e.key === 'Alt' && !leeScrubS.drag) leeScrubHint(null, null); }, true);
}
if (typeof document !== 'undefined' && typeof window.addEventListener === 'function') leeScrubInstall();
