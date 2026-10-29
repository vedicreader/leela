/* The open notebook presented as slides. Cells group the way RISE groups them, from `metadata.slideshow.slide_type`, into one line.
   The server builds the presenter copy and the room copy; `slides.js` draws them; each move goes to the server, which sends it to the audience windows. */
const PRESENT_NOT_NOTEBOOK = 'only a notebook can be presented as slides';
const PRESENT_NOTHING = 'this notebook has nothing to present: every cell is empty or skipped';
const PRESENT_KINDS = new Set(['markdown', 'code', 'raw', 'prompt']);
//: A start the server refused because the notebook is too large to send.
const PRESENT_LARGE = /characters of (output|source)|larger than 32 MB|at most 2,000 cells/;
const PRESENT_GONE = /^This presentation (has ended|link is not valid)\.$/;
const PRESENT_HINT = 'Move the audience window to the projector. In that window, press F for full screen.';

//: The text scale after one press of A- (`d = -1`) or A+ (`d = 1`): tenths, from half to two and a half.
const presentStep = (s, d) => Math.min(2.5, Math.max(.5, Math.round((s + d/10)*10)/10));
const presentKey = (what = 'text') => `lee-present-${what}:${lee.path || lee.tabKey}`;
function presentStored() {
  try { const s = +localStorage.getItem(presentKey()); return s >= .5 && s <= 2.5 ? s : 1; } catch { return 1; }
}

//: Whether markdown text has an H2 line outside a backtick or tilde fence.
function presentH2(s) {
  let fence = '';
  for (const l of s.split(/\r?\n/)) {
    const m = /^ {0,3}(`{3,}|~{3,})(.*)$/.exec(l);
    if (fence) { if (m && m[1][0] === fence[0] && m[1].length >= fence.length && !m[2].trim()) fence = ''; }
    else if (m && !(m[1][0] === '`' && m[2].includes('`'))) fence = m[1];
    else if (/^ {0,3}##(?:[ \t]|$)/.test(l)) return true;
  }
  return false;
}

/* `[[slide, ...subslides], ...]`, each slide `{items: [{i, frag}], notes: [i]}` with `i` an index
   into `cells`. `src` reads a cell's text, so unsaved edits are what gets presented. With no `slide`
   or `subslide` cell, a markdown cell with an H2 line opens a slide; with no H2 either, each cell does. */
function presentSlides(cells, src = c => String(c.source || '')) {
  const kind = c => c.extra?.slideshow?.slide_type, ok = c => c.approval == null;
  // only a slide boundary makes unmarked cells continue a slide; a skip or notes mark alone does not
  const typed = cells.some(c => ok(c) && (kind(c) === 'slide' || kind(c) === 'subslide'));
  const heads = typed ? [] : cells.map(c => ok(c) && c.cell_type === 'markdown' && presentH2(src(c))), byH2 = heads.some(Boolean);
  const deck = []; let stack = null, slide = null;
  const open = sub => { slide = {items: [], notes: [], frag: -1}; if (!sub || !stack) deck.push(stack = []); stack.push(slide); };
  cells.forEach((c, i) => {
    if (!ok(c)) return;
    const k = kind(c), t = byH2 && (!k || k === '-') ? (heads[i] ? 'slide' : '-') : k || (typed ? '-' : 'slide');
    if (t === 'skip') return;
    const empty = !src(c).trim() && !(c.outputs || []).length && !c.reply;
    if (t === 'slide' || t === 'subslide') open(t === 'subslide');
    else if (!slide) open(false);
    if (empty) return;
    if (t === 'notes') return void slide.notes.push(i);
    if (t === 'fragment') slide.frag++;
    slide.items.push({i, frag: slide.frag});
  });
  return deck.map(s => s.filter(x => x.items.length || x.notes.length)).filter(s => s.length);
}

//: Where cell `i` is shown, or the nearest visible cell above it: `{h, v, f}` for `Reveal.slide`.
function presentAt(deck, i) {
  for (let j = i; j >= 0; j--)
    for (const [h, stack] of deck.entries()) for (const [v, s] of stack.entries()) {
      const it = s.items.find(x => x.i === j); if (it) return {h, v, f: it.frag};
    }
  return {h: 0, v: 0, f: -1};
}

//: The most fragment groups a slide shows: stage `go.beat` is one plus the groups shown, at most 50.
const PRESENT_GROUPS = 49;
/* The deck as one line `[{items: [{i, frag}], notes: [i], groups, warn}]`: subslides in order, a notes-only
   slide's notes on the next slide with items (on the last one at the end), groups past the 49th in the 49th. */
function presentLine(deck) {
  const line = []; let held = [];
  for (const s of deck.flat()) {
    if (!s.items.length) { held.push(...s.notes); continue; }
    const top = s.items.reduce((m, x) => Math.max(m, x.frag), -1);
    line.push({items: s.items.map(({i, frag}) => ({i, frag: Math.min(frag, PRESENT_GROUPS - 1)})), notes: [...held, ...s.notes],
               groups: Math.min(top + 1, PRESENT_GROUPS), warn: top >= PRESENT_GROUPS});
    held = [];
  }
  if (line.length) line.at(-1).notes.push(...held);
  return line;
}
//: `{slide, step}` where cell `i` shows, or the nearest visible cell above it; a fragment's own group is not yet shown.
function presentPlace(line, i) {
  const at = new Map(line.flatMap((s, slide) => s.items.map(x => [x.i, {slide, step: Math.max(0, x.frag)}])));
  for (let j = i; j >= 0; j--) if (at.has(j)) return at.get(j);
  return {slide: 0, step: 0};
}
//: One fragment group forward (`d = 1`) or back (`d = -1`), else the next slide at its start or the previous one in full.
function presentMove(line, {slide, step}, d) {
  const s = line[slide]; if (!s) return {slide: 0, step: 0};
  if (d > 0) return step < s.groups ? {slide, step: step + 1} : slide + 1 < line.length ? {slide: slide + 1, step: 0} : {slide, step};
  if (d < 0) return step > 0 ? {slide, step: step - 1} : slide > 0 ? {slide: slide - 1, step: line[slide - 1].groups} : {slide, step};
  return {slide, step};
}


//: The RISE setting that still counts: where the presentation starts. reveal.js and its options left with the one mode.
function riseConfig(rise) {
  const r = rise && typeof rise === 'object' && !Array.isArray(rise) ? rise : {};
  return {start: r.start_slideshow_at === 'beginning' ? 'beginning' : 'selected'};
}
const presentError = m => { try { return JSON.parse(m).error || m; } catch { return m; } };
const presentRefused = e => PRESENT_LARGE.test(e.message || '') ? `${e.message} Clear large outputs, then try again.` : `slides could not start: ${e.message || e}`;
const presentAtBody = p => ({slide: `s${p.at.slide + 1}`, step: p.at.step, blank: p.blank, size: Math.round(p.text*10)});
const presentTheme = () => lee.theme ? `${lee.theme.family}:${lee.theme.mode}:${lee.theme.density}` : '';

function presentSay(text) {
  const m = lee.present && $('.lee-present-msg', lee.present.root); if (!m) return;
  m.textContent = text; m.hidden = !text;
  clearTimeout(m._leeTimer); if (text) m._leeTimer = setTimeout(() => { m.hidden = true; }, 6000);
}
//: Post to the server in order with this presenter's other posts; a refused key closes the presenter screen.
function presentPost(p, url, body = {}, always = false) {
  return p.chain = p.chain.then(() => (always || lee.present === p) && post(url, {...body, k: p.key})).catch(e => {
    if (lee.present !== p) return;
    if (PRESENT_GONE.test(e.message || '')) { closePresentation(); status('This presentation has ended.', 'err'); }
    else presentSay('Moves are not reaching the audience window.');
  });
}
//: The cell's live outputs in place of the server's copy, on the presenter screen only.
function presentOuts(p, id, outs) {
  const box = $(`.lee-slide .lee-block[data-cell="${CSS.escape(id)}"] .lee-out`, p.root); if (!box) return;
  $$('[data-markdown]', box).forEach(el => { for (const v of el._leeCodeViews || []) try { LeeCM.destroy(v); } catch {} });
  box.replaceChildren(...(outs || []).map(outputEl));
}
async function presentRun(p, id) {
  const i = lee.cells.findIndex(c => c.id === id), button = () => $(`[data-run="${CSS.escape(id)}"]`, p.root);
  if (i < 0) return presentSay('This cell is no longer in the notebook.');
  if (button()) button().disabled = true;
  p.outs[id] = lee.cells[i].outputs || []; presentSay('Running…');
  const r = await runCell(i, false);
  if (lee.present !== p) return;
  const c = lee.cells.find(x => x.id === id), err = (c?.outputs || []).find(o => o.output_type === 'error');
  if (c) presentOuts(p, id, p.outs[id] = c.outputs || []);
  if (button()) button().disabled = false;
  presentSay(err ? `${err.ename}: ${err.evalue}` : r.ok ? '' : presentError(r.error));
}
function presentEnd(p) { lee.presentWait = presentPost(p, '/present/end', {}, true); closePresentation(); }

async function presentNotebook(start = '') {
  if (lee.kind !== 'notebook') return status(PRESENT_NOT_NOTEBOOK, 'err');
  const cells = lee.cells, line = presentLine(presentSlides(cells, mdSource));
  if (!line.length) return status(PRESENT_NOTHING, 'err');
  closePresentation();
  const ticket = lee.presentTicket = (lee.presentTicket || 0) + 1, name = lee.path || lee.tabKey;
  const at = (start || riseConfig(lee.rise).start) === 'selected' ? presentPlace(line, lee.sel) : {slide: 0, step: 0};
  status('Preparing slides…');
  const body = {path: name, title: String(name).split('/').pop(), start: at, line: line.map(({items, notes, groups}) => ({items, notes, groups})),
    cells: cells.map(c => ({id: c.id, cell_type: PRESENT_KINDS.has(c.cell_type) ? c.cell_type : 'raw', source: mdSource(c), outputs: c.outputs || []}))};
  // the server keeps the start whose body it reads last and refuses a start an end overtakes, so one start at a time, after the last end
  const sent = (lee.presentWait || Promise.resolve()).then(() => ticket === lee.presentTicket ? post('/present/start', body) : null);
  lee.presentWait = sent.catch(() => {});
  let r;
  try { r = await sent; } catch (e) { if (ticket === lee.presentTicket) status(presentRefused(e), 'err'); return; }
  if (!r || ticket !== lee.presentTicket || lee.present) return;
  status('');
  presentOpen(r, line, at);
}

const PRESENT_HTML = '<div class="lee-present-main"><div class="lee-stage"><div class="lee-slide"></div></div>' +
  '<aside class="lee-present-notes" id="lee-present-notes" aria-label="Speaker notes" hidden><div class="lee-present-notes-head"><h2>Speaker notes</h2>' +
  '<button type="button" data-close title="Close the notes (Esc)">Close</button></div>' +
  '<p class="lee-present-warn">The room can see these notes when you share this screen.</p>' +
  '<div data-notes-body></div><p data-upcoming></p><p data-clock></p></aside><div class="lee-present-msg" role="status" hidden></div></div>' +
  '<div class="lee-present-strip" role="toolbar" aria-label="Presentation controls">' +
  '<span class="lee-present-group"><button type="button" data-prev title="Previous (Left arrow)">Previous</button><button type="button" data-next title="Next (Right arrow or Space)">Next</button>' +
  '<span data-where></span><span data-runs></span></span>' +
  '<span class="lee-present-group"><button type="button" data-audience title="Open a window to show on the projector">Audience window</button><span data-conn role="status">Audience window: not connected</span></span>' +
  '<span class="lee-present-group lee-present-tools"><button type="button" data-notes title="Notes (N)" aria-controls="lee-present-notes" aria-expanded="false">Notes</button>' +
  '<button type="button" data-smaller title="Smaller text" aria-label="Smaller text">A−</button><span data-size title="Body text size on the 1280 by 720 slide"></span>' +
  '<button type="button" data-bigger title="Larger text" aria-label="Larger text">A+</button>' +
  '<button type="button" data-full title="Full screen (F)">Full screen</button></span><span class="lee-gap"></span>' +
  '<button type="button" data-end title="End the presentation">End</button></div>';

//: The presenter screen for the started presentation `r`, at place `at` of `line`.
function presentOpen(r, line, at) {
  const root = Object.assign(document.createElement('div'), {className: 'lee-present', tabIndex: -1, innerHTML: PRESENT_HTML});
  root.setAttribute('role', 'dialog'); root.setAttribute('aria-label', 'Presentation');
  const q = s => $(s, root), canvas = q('.lee-slide'), notes = q('.lee-present-notes'), strip = q('.lee-present-strip'), end = q('[data-end]'), notesBtn = q('[data-notes]');
  const p = lee.present = {root, key: r.key, ak: r.ak, id: r.id, audience: r.audience, deck: r.presenter, line, at, text: presentStored(), blank: false,
                           outs: {}, demos: new Map(), chain: Promise.resolve(), started: Date.now(), win: null, look: presentTheme()};
  const demo = spec => { const e = rupakaDraw(spec); e.done.then(() => slidesRk(e.host.shadowRoot)); return e.host; };
  const mount = (spec, id) => p.demos.get(id) || p.demos.set(id, demo(spec)).get(id);
  const stuck = d => { const a = presentMove(p.line, p.at, d); return a.slide === p.at.slide && a.step === p.at.step; };
  const run = b => { const e = Object.assign(document.createElement('button'), {type: 'button', title: 'Run this code cell', onclick: () => presentRun(p, b.cell)}); e.dataset.run = b.cell; return e; };
  p.draw = () => {
    const s = p.deck.slides[p.at.slide] || {}, {fits} = slidesDraw(canvas, p.deck, p.at.slide, p.at.step, {key: p.ak, size: Math.round(p.text*10), mount, math: renderMath});
    for (const [id, outs] of Object.entries(p.outs)) presentOuts(p, id, outs);
    const g = p.line[p.at.slide]?.groups || 0;
    q('[data-where]').textContent = `${p.at.slide + 1} / ${p.deck.slides.length}` + (g ? ` · step ${p.at.step + 1} / ${g + 1}` : '');
    q('[data-prev]').disabled = stuck(-1); q('[data-next]').disabled = stuck(1);
    if (document.activeElement?.disabled && root.contains(document.activeElement)) root.focus({preventScroll: true});
    q('[data-size]').textContent = `Text ${Math.round(28*p.text*(+canvas.style.getPropertyValue('--slide-fit') || 1))} px`;
    q('[data-notes-body]').replaceChildren(slidesSafe(s.notes || '', p.ak));
    q('[data-upcoming]').textContent = s.next ? `Next: ${s.next}` : 'This is the last slide.';
    const code = (s.blocks || []).filter(b => b.kind === 'code');
    q('[data-runs]').replaceChildren(...code.map((b, n) => Object.assign(run(b), {textContent: code.length > 1 ? `Run ${n + 1}` : 'Run'})));
    if (!fits) presentSay(`Slide ${p.at.slide + 1} has more than fits. Split it or trim it.`);
  };
  const go = d => {
    const a = presentMove(p.line, p.at, d); if (a.slide === p.at.slide && a.step === p.at.step) return;
    p.at = a; p.draw(); presentPost(p, '/present/at', presentAtBody(p));
  };
  const resize = d => {
    p.text = presentStep(p.text, d);
    try { localStorage.setItem(presentKey(), String(p.text)); } catch {}
    p.draw(); presentSay(`text ${Math.round(p.text*100)}%`); presentPost(p, '/present/at', presentAtBody(p));
  };
  const full = () => document.fullscreenElement ? document.exitFullscreen().catch(() => {})
    : root.requestFullscreen ? root.requestFullscreen().catch(() => presentSay('Use View › Enter Full Screen to fill the screen.')) : presentSay('Use View › Enter Full Screen to fill the screen.');
  const setNotes = open => {
    const inside = notes.contains(document.activeElement);
    notes.hidden = !open; root.classList.toggle('lee-notes-open', open); notesBtn.setAttribute('aria-expanded', String(open));
    if (!open && inside) notesBtn.focus({preventScroll: true});
  };
  const toggleNotes = () => setNotes(notes.hidden);
  p.keys = {ArrowRight: () => go(1), ArrowDown: () => go(1), Space: () => go(1), PageDown: () => go(1),
            ArrowLeft: () => go(-1), ArrowUp: () => go(-1), 'Shift+Space': () => go(-1), PageUp: () => go(-1),
            KeyN: toggleNotes, KeyF: full, Escape: () => setNotes(false)};
  // the rules of `abhyasaStage.presenter`, which the IDE page does not load: no held, Alt, Cmd or Ctrl key, no key in a text box or a demo but Esc
  p.onKey = e => {
    if (lee.present !== p || e.repeat || e.metaKey || e.ctrlKey || e.altKey || e.isComposing || $('.lee-modal')) return;
    const a = document.activeElement;
    if (a && (a.matches('textarea, input, select, [contenteditable]:not([contenteditable="false"])') || a.isContentEditable)) return;
    if (e.key !== 'Escape' && a?.closest('.lee-rupaka')) return;
    if ((e.code === 'Space' || e.code === 'Enter') && a?.matches('button') && (strip.contains(a) || notes.contains(a))) return;
    const fn = p.keys[(e.shiftKey ? 'Shift+' : '') + e.code]; if (!fn) return;
    e.preventDefault(); e.stopPropagation(); fn();
  };
  p.onOutput = e => { if (lee.present === p && e.detail.id in p.outs) presentOuts(p, e.detail.id, p.outs[e.detail.id] = e.detail.outputs || []); };
  q('[data-prev]').onclick = () => go(-1); q('[data-next]').onclick = () => go(1);
  q('[data-smaller]').onclick = () => resize(-1); q('[data-bigger]').onclick = () => resize(1);
  notesBtn.onclick = toggleNotes; q('[data-close]').onclick = () => setNotes(false); q('[data-full]').onclick = full;
  q('[data-audience]').onclick = () => {
    const url = location.origin + p.audience;
    if (inDesktopShell()) { openExternal(url); return presentSay(PRESENT_HINT); }
    const w = p.win && !p.win.closed ? p.win : window.open('', 'leela-audience', 'popup,width=1280,height=720');
    if (!w) return presentSay('The browser blocked the window. Click again.');
    let mine = false; try { mine = w.location.pathname === '/present/audience' && w.sessionStorage.getItem('lee-present-k') === p.ak; } catch {}
    if (!mine) w.location.href = url;
    p.win = w; w.focus(); presentSay(PRESENT_HINT);
  };
  end.onclick = () => {
    if (end.dataset.armed) return presentEnd(p);
    end.dataset.armed = '1'; end.textContent = 'End now?';
    clearTimeout(p.endT); p.endT = setTimeout(() => { delete end.dataset.armed; end.textContent = 'End'; }, 3000);
  };
  const wake = () => {
    root.classList.remove('lee-idle'); clearTimeout(p.idle);
    p.idle = setTimeout(() => { if (!strip.contains(document.activeElement)) root.classList.add('lee-idle'); }, 3000);
  };
  root.addEventListener('pointermove', e => { if (innerHeight - e.clientY <= Math.max(80, strip.offsetHeight + 24)) wake(); });
  strip.addEventListener('focusin', wake); strip.addEventListener('pointerdown', wake);
  root.addEventListener('lee-markdown-rendered', e => $$('.lee-reply-actions', e.target).forEach(x => x.remove()));
  p.events = new EventSource('/present/events');
  p.events.addEventListener('audience', e => {
    const d = JSON.parse(e.data); if (d.id === p.id) q('[data-conn]').textContent = d.n ? 'Audience window: connected' : 'Audience window: not connected';
  });
  p.events.addEventListener('presentation-ended', e => {
    const d = JSON.parse(e.data); if (d.id !== p.id || lee.present !== p) return;
    closePresentation(); status(d.reason === 'replaced' ? 'Another presentation started.' : 'This presentation has ended.', 'err');
  });
  p.watch = new MutationObserver(() => { const t = presentTheme(); if (t && t !== p.look) presentPost(p, '/present/move', {t: 'look', theme: p.look = t}); });
  p.watch.observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme', 'data-mode', 'data-density']});
  p.clock = setInterval(() => {
    const s = Math.floor((Date.now() - p.started)/1000);
    q('[data-clock]').textContent = `Time: ${Math.floor(s/60)}:${String(s % 60).padStart(2, '0')}`;
  }, 1000);
  document.addEventListener('keydown', p.onKey, true); addEventListener('lee-cell-output', p.onOutput);
  document.documentElement.classList.add('talk');
  closeInlinePopover(); document.body.appendChild(root); slidesScale(q('.lee-stage')); root.focus({preventScroll: true});
  const m = root.appendChild(Object.assign(document.createElement('div'), {className: 'lee-slide lee-measure'}));
  const long = p.deck.slides.map((s, i) => slidesDraw(m, p.deck, i, s.groups, {key: p.ak, size: Math.round(p.text*10)}).fits ? 0 : i + 1).filter(Boolean);
  m.remove();
  p.draw(); wake();
  if (long.length) presentSay(long.length === 1 ? `Slide ${long[0]} has more than fits. Split it or trim it.` : `Slides ${long.join(', ')} have more than fits. Split them or trim them.`);
  presentPost(p, '/present/at', presentAtBody(p));
  if (p.look) presentPost(p, '/present/move', {t: 'look', theme: p.look});
  root.dataset.ready = '';
}

function closePresentation() {
  const p = lee.present; if (!p) return;
  lee.present = null;
  document.removeEventListener('keydown', p.onKey, true); removeEventListener('lee-cell-output', p.onOutput);
  p.events?.close(); p.watch?.disconnect(); clearTimeout(p.idle); clearTimeout(p.endT); clearInterval(p.clock);
  document.documentElement.classList.remove('talk');
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  $$('[data-markdown]', p.root).forEach(el => {
    clearTimeout(el._leeMarkdownTimer); if (el._leeCodeFrame) cancelAnimationFrame(el._leeCodeFrame);
    for (const v of el._leeCodeViews || []) try { LeeCM.destroy(v); } catch {}
  });
  $$('iframe', p.root).forEach(f => f.remove());
  p.root.remove();
  if (lee.kind === 'notebook' && lee.cells.length) focusCell(lee.sel);
}
