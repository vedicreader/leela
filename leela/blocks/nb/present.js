/* The open notebook presented as slides. Cells group the way RISE groups them, from `metadata.slideshow.slide_type`, into one line.
   The server builds the presenter copy and the room copy; `slides.js` draws them; each move goes to the server, which sends it to the audience windows. */
const PRESENT_NOT_NOTEBOOK = 'only a notebook can be presented as slides';
const PRESENT_NOTHING = 'this notebook has nothing to present: every cell is empty or skipped';
const PRESENT_KINDS = new Set(['markdown', 'code', 'raw', 'prompt']);
//: A start the server refused because the notebook is too large to send.
const PRESENT_LARGE = /characters of (output|source)|larger than 32 MB|at most 2,000 cells/;
const PRESENT_GONE = /^This presentation (has ended|link is not valid)\.$/;
const PRESENT_HINT = 'Move the audience window to the projector. In that window, press F for full screen.';
const PRESENT_ENDED = 'This presentation has ended.', PRESENT_RESTARTED = 'Leela restarted, so the presentation stopped.';
const PRESENT_AWAY = 'Leela is not reachable, so the presentation is closed on this screen. Reload this page to try again.';
//: This tab's presenter record lives in `sessionStorage` under the presentation id, so another IDE tab never gets the key by itself.
const PRESENT_REC = 'lee-present:';
//: Laser points go at most once in this many ms, one at a time behind the other posts; the dot fades as `stage.js` fades it; Esc this soon after full screen ends is the browser's.
const PRESENT_POINT_MS = 33, PRESENT_FADE = 1500, PRESENT_FULL_MS = 400;
//: What Space or Enter presses by itself when it has focus.
const PRESENT_PRESSES = 'button, summary, [role="button"], input[type="checkbox"], input[type="radio"], input[type="button"], input[type="submit"], input[type="reset"]';
const presentClamp = v => Math.round(Math.min(1, Math.max(0, v))*1e4)/1e4;

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
const presentIndex = at => ({slide: +String(at.slide).slice(1) - 1, step: at.step});
//: Place `at` moved onto `line`: a slide past the end is the last one, a step past the groups is the last group.
function presentNear(line, at) {
  const slide = Math.max(0, Math.min(line.length - 1, at.slide | 0));
  return {slide, step: Math.max(0, Math.min(line[slide].groups, at.step | 0))};
}
//: Whether code cell `id` no longer matches the stored deck: gone from the open notebook, or edited since the start. Task 7 disables Run for it.
const presentStale = (p, id) => { const c = (lee.cells || []).find(x => x.id === id); return !c || !Object.hasOwn(p.src, id) || mdSource(c) !== p.src[id]; };
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
    if (e.message === PRESENT_ENDED) { closePresentation(); presentGone(p); }
    else if (PRESENT_GONE.test(e.message || '')) { closePresentation(); presentForget(p.id); status(PRESENT_ENDED, 'err'); }
    else presentSay('Moves are not reaching the audience window.');
  });
}
//: Post the place; the server's reply is the place a reload of this tab promises.
const presentGo = p => presentPost(p, '/present/at', presentAtBody(p)).then(r => { if (r?.at && lee.present === p) { p.acked = presentIndex(r.at); presentKeep(p); } });

function presentRecs() {
  try { return Object.keys(sessionStorage).filter(n => n.startsWith(PRESENT_REC)).map(n => ({...JSON.parse(sessionStorage.getItem(n)), id: n.slice(PRESENT_REC.length)})); }
  catch { return []; }
}
//: Keep `p`'s key, boot, notebook and last acknowledged place for a reload of this tab; the history entry keeps the same without the key, for a tab whose storage was cleared.
function presentKeep(p) {
  const rec = JSON.stringify({key: p.key, boot: p.boot, path: p.path, at: p.acked}); if (rec === p.kept) return;
  p.kept = rec;
  try { for (const r of presentRecs()) if (r.id !== p.id) sessionStorage.removeItem(PRESENT_REC + r.id); sessionStorage.setItem(PRESENT_REC + p.id, rec); } catch {}
  try { history.replaceState({...history.state, leePresent: {id: p.id, path: p.path, at: p.acked}}, ''); } catch {}
}
function presentForget(id) {
  try { sessionStorage.removeItem(PRESENT_REC + id); } catch {}
  try { if (history.state?.leePresent?.id === id) { const {leePresent, ...s} = history.state; history.replaceState(s, ''); } } catch {}
}
//: A presenter POST that tells a refusal from a network failure: `{ok, status, body, boot}`. A network failure throws.
async function presentAsk(url, body) {
  const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  return {ok: r.ok, status: r.status, body: await r.json().catch(() => ({})), boot: r.headers.get('X-Leela-Boot') || ''};
}
//: The live presentation `{id, boot, holder}` from the first event of `/present/events`; null when the server does not answer in 5 s.
const presentLive = () => new Promise(ok => {
  const es = new EventSource('/present/events'), t = setTimeout(() => { es.close(); ok(null); }, 5000);
  es.addEventListener('presentation', e => { clearTimeout(t); es.close(); try { ok(JSON.parse(e.data)); } catch { ok(null); } });
});

//: At page load. A reload of this tab brings its presenter screen back from the server's state; a tab that copied the record asks first; a tab that lost its key says so.
async function presentResume() {
  const rec = presentRecs()[0], mark = history.state?.leePresent;
  if (!rec) return mark?.id && presentLost(mark);
  if (performance.getEntriesByType?.('navigation')[0]?.type === 'reload') return presentRecover(rec);
  if ((await presentLive())?.id !== rec.id) return presentForget(rec.id);
  const take = await confirmDialog('Present from this tab?', 'This presentation is open in another tab. Take over to control it from this tab. The other tab stops presenting.', 'Take over');
  take ? presentRecover(rec) : presentForget(rec.id);
}
async function presentRecover(rec) {
  const ticket = lee.presentTicket = (lee.presentTicket || 0) + 1;
  let r; try { r = await presentAsk('/present/resume', {k: rec.key}); } catch { return status(PRESENT_AWAY, 'err'); }
  if (ticket !== lee.presentTicket || lee.present) return;
  if (r.ok) return presentOpen(r.body, false, rec.path);
  presentForget(rec.id);
  if (r.status === 410) presentAgain(rec, !!r.boot && r.boot !== rec.boot);
}
//: The server holds no presentation for `p`: ask once with its key; only a confirmed 410 offers Start again, never a network failure.
async function presentGone(p) {
  const m = {id: p.id, key: p.key, boot: p.boot, path: p.path, at: p.acked};
  let r; try { r = await presentAsk('/present/resume', {k: m.key}); } catch { return status(PRESENT_AWAY, 'err'); }
  if (r.ok) return lee.present || presentOpen(r.body, false, m.path);
  presentForget(m.id);
  if (r.status === 410) return presentAgain(m, !!r.boot && r.boot !== m.boot);
  status('Another presentation started.', 'err');
}
async function presentAgain(m, restarted) {
  status(restarted ? PRESENT_RESTARTED : PRESENT_ENDED, 'err');
  const why = restarted ? 'The presentation stopped when Leela restarted.' : 'The server no longer holds this presentation.';
  if (await confirmDialog(restarted ? 'Leela restarted' : 'The presentation has ended',
    `${why} Start again to present from slide ${(m.at?.slide || 0) + 1}. The audience window must open again.`, 'Start again')) presentRestart(m);
}
async function presentLost(mark) {
  if ((await presentLive())?.id !== mark.id) return presentForget(mark.id);
  const go = await confirmDialog('This tab lost its presenter key', 'The presentation is still running, but this tab can no longer control it. ' +
    `Start again to present from slide ${(mark.at?.slide || 0) + 1} in this tab. This ends the running presentation, and the audience window must open again.`, 'Start again');
  presentForget(mark.id);
  if (go) presentRestart(mark);
}
//: A new presentation of notebook `m.path`, from the live cells, at its last acknowledged place.
async function presentRestart(m) {
  if (m.path && m.path !== (lee.path || lee.tabKey)) try { await leeOpenFile(m.path); } catch (e) { return status(String(e.message || e), 'err'); }
  presentNotebook(m.at || '');
}
//: What `/present/events` says on each connect and for each new holder: another id or another holder closes this presenter screen at once.
function presentCheck(p, d) {
  if (lee.present !== p || d.id === p.id && (!d.holder || d.holder === p.holder)) return;
  closePresentation();
  if (d.id === p.id) { presentForget(p.id); return status('The presentation moved to another tab.', 'err'); }
  if (d.id) { presentForget(p.id); return status('Another presentation started.', 'err'); }
  presentGone(p);
}
//: Post the body `make()` gives, `[url, body]` or null, for `slot`: one post of a slot in the chain at a time, and only the newest of those that wait; `then` gets the reply.
function presentLatest(p, slot, make, then) {
  const s = (p.slots ||= {})[slot] ||= {busy: false, next: null};
  s.next = {make, then};
  if (!s.busy) presentDrain(p, s);
}
function presentDrain(p, s) {
  const m = s.next; if (!m) return;
  s.next = null;
  const b = m.make(); if (!b) return presentDrain(p, s);
  s.busy = true;
  presentPost(p, ...b).then(r => { s.busy = false; m.then?.(r); presentDrain(p, s); });
}
//: Post the newest outputs of run `gen` of code cell `id`; a run from before the last kernel restart sends nothing. `seq` counts the posts of one run.
function presentOut(p, id, gen, outputs, done) {
  const q = p.outq[id] ||= {gen: 0, seq: 0};
  if (gen <= p.floor || gen < q.gen) return;
  presentLatest(p, 'out:' + id, () => {
    if (gen <= p.floor || gen < q.gen) return null;
    if (gen !== q.gen) { q.gen = gen; q.seq = 0; }
    return ['/present/out', {cell: id, gen, seq: ++q.seq, outputs, done}];
  }, r => { if (r?.msg && lee.present === p && gen > p.floor) presentShown(p, id, r, done, gen); });
}
//: The room copy the server made of a run's outputs, drawn on the presenter screen too; a finished run that failed opens the private error panel.
function presentShown(p, id, r, done, gen) {
  if (!slidesNewer(r.msg, p.outs[id])) return;
  p.outs[id] = r.msg; presentBox(p, id);
  if (done && r.error) presentErr(p, {cell: id, gen, ...r.error});
  else if (done && p.err?.cell === id) presentErr(p, null);
}
function presentBox(p, id) {
  const f = slidesOut(p.canvas, id, p.outs[id]?.html || '', p.ak);
  if (f && !f.fits) presentSay(`Slide ${p.at.slide + 1} has more than fits. Split it or trim it.`);
}
//: The private error panel for error `e` of a run, `{cell, gen, ename, evalue, traceback}`, or closed for null.
function presentErr(p, e) {
  const box = $('.lee-present-err', p.root); p.err = e; if (!box) return;
  if (!e && box.contains(document.activeElement)) p.root.focus({preventScroll: true});
  box.hidden = !e; if (!e) return;
  $('[data-err-sum]', box).textContent = `${e.ename}: ${e.evalue}`;
  $('[data-err-tb]', box).textContent = (e.traceback || []).join('\n');
}
//: Show error: the server sends the error to the room only while run `gen` is the last run of the cell.
function presentShowError(p) {
  const e = p.err; if (!e) return;
  presentPost(p, '/present/show-error', {cell: e.cell, gen: e.gen}).then(r => {
    if (lee.present !== p || !r) return;
    if (p.err === e) presentErr(p, null);
    if (r.stale) return presentSay('A newer run of this cell replaced that error.');
    if (slidesNewer(r.msg, p.outs[e.cell])) { p.outs[e.cell] = r.msg; presentBox(p, e.cell); }
    presentSay('The room can see the error.');
  });
}
//: The kernel restarted, died or was stopped by force: every code cell of the deck empty on both screens, no private error, and each older run stale.
function presentReset(p) {
  if (lee.present !== p) return;
  p.floor = p.gen = Math.max(p.gen, p.floor) + 1;
  for (const id of Object.keys(p.src)) p.outs[id] = {cell: id, gen: p.floor, seq: 0, html: ''};
  presentErr(p, null); p.draw();
  presentPost(p, '/present/clear', {gen: p.floor});
}
//: A run that ended with no count and no error: kunda settles the runs of a kernel that died that way.
const presentDied = c => !!c && c.execution_count == null && !(c.outputs || []).some(o => o.output_type === 'error');
//: Run the live text of code cell `id` with no save; its outputs stream to the room as it runs.
async function presentRun(p, id) {
  const i = lee.cells.findIndex(c => c.id === id);
  if (p.runs[id] || i < 0 || presentStale(p, id)) return presentStrip(p);
  const gen = p.gen = Math.max(p.gen, p.floor) + 1, run = p.runs[id] = {gen};
  if (p.err?.cell === id) presentErr(p, null);
  presentStrip(p);
  presentOut(p, id, gen, [], false);
  const r = await runCell(i, false, {save: false});
  if (p.runs[id] === run) delete p.runs[id];
  if (lee.present !== p) return;
  const c = lee.cells.find(x => x.id === id);
  if (r.ok && presentDied(c)) presentReset(p);
  else {
    presentOut(p, id, gen, c?.outputs || [], true);
    if (!r.ok && !(c?.outputs || []).some(o => o.output_type === 'error')) presentSay(presentError(r.error));
  }
  presentStrip(p);
}
//: A run the server still holds after a reload of this page: its final outputs from `/nb/run/state`, posted as the same run.
async function presentFollow(p, id, o) {
  const run = p.runs[id] = {gen: o.gen};
  p.outq[id] = {gen: o.gen, seq: o.seq};
  presentStrip(p);
  let s = null; try { s = await settleRun(p.path, id); } catch {}
  if (p.runs[id] === run) delete p.runs[id];
  if (lee.present !== p) return;
  if (s?.cell) presentOut(p, id, o.gen, s.cell.outputs || [], true);
  presentStrip(p);
}
//: Stop code cell `id` by the exact-cell path; a run that this page did not start, after a reload, goes to the same route.
async function presentStop(p, id) {
  const i = lee.cells.findIndex(c => c.id === id);
  try {
    if (lee.cells[i]?.running) return await stopCell(i);
    if ((await post('/nb/interrupt', {path: p.path, id})).forced) kernelRestarted();
  } catch (e) { presentSay(String(e.message || e)); }
}
//: Run and Stop for each code cell of the slide: Stop shows while the cell runs, and Run is off while it runs or no longer matches the deck.
function presentStrip(p) {
  const s = p.deck.slides[p.at.slide] || {}, code = (s.blocks || []).filter(b => b.kind === 'code'), n = code.length > 1;
  const btn = (text, title, fn) => Object.assign(document.createElement('button'), {type: 'button', textContent: text, title, onclick: fn});
  $('[data-runs]', p.root).replaceChildren(...code.flatMap((b, j) => {
    const id = b.cell, on = !!p.runs[id], stale = presentStale(p, id), tag = n ? ` ${j + 1}` : '';
    const run = btn('Run' + tag, stale ? 'Run is off: this cell changed or left the notebook after the presentation started.' : 'Run this code cell', () => presentRun(p, id));
    const stop = btn('Stop' + tag, 'Stop this code cell', () => presentStop(p, id));
    run.dataset.run = stop.dataset.stop = id; run.disabled = on || stale; stop.hidden = !on;
    return [run, stop];
  }));
  if (document.activeElement === document.body && lee.present === p) p.root.focus({preventScroll: true});
}

//: The `demo` move of mirror snapshot `s` of demo `slug`: the stage fields only; null when it is over the 65536 units of a stage message.
function presentDemoMove(slug, s) {
  const m = {t: 'demo', slug, state: s.state, gates: s.gates, pick: s.pick};
  return JSON.stringify({v: 1, ...m}).length > 65536 ? null : m;
}
const presentGate = (inner, id) => [...inner.querySelectorAll('.rk-gate .q[id]')].find(q => q.id.endsWith(`-${id}-q`))?.closest('.rk-gate');
//: Presenter demo `d` mirrored to the room: the server's state first after a reload, one watch for the mount, a first snapshot, then each change.
function presentMirror(p, d) {
  try { d.mirror = abhyasaStage.mirror(d.inner); } catch { return; }
  presentHydrate(p, d);
  d.unwatch = d.mirror.watch(() => presentDemo(p, d));
  presentDemo(p, d);
}
/* The server's demo state on the presenter copy, which stays writable: its inputs, and each done gate settled with the pick. The mirror does not
   count a gate settled this way, so `d.kept` holds it as done while it stays closed. */
function presentHydrate(p, d) {
  d.kept = {gates: {}, pick: {}, answers: {}};
  const s = p.held.demo[d.slug], a = p.held.answers[d.slug]?.gates || {}; if (!s) return;
  try {
    const now = Rupaka.state(d.inner), keys = Object.keys(now).filter(k => Object.hasOwn(s.state, k) && JSON.stringify(now[k]) !== JSON.stringify(s.state[k]));
    if (keys.length) Rupaka.set(d.inner, Object.fromEntries(keys.map(k => [k, s.state[k]])));
    for (const [id, v] of Object.entries(s.gates)) {
      const os = Rupaka.options(d.inner, id) || [], i = s.pick?.[id], pick = Array.isArray(i) ? i.map(x => os[x]) : os[i];
      if (v === 'done' && Rupaka.settle(d.inner, id, pick ?? null)) Object.assign(d.kept, {gates: {...d.kept.gates, [id]: 'done'}, pick: i == null ? d.kept.pick : {...d.kept.pick, [id]: i},
                                                                             answers: a[id] ? {...d.kept.answers, [id]: a[id]} : d.kept.answers});
    }
  } catch {}
}
//: The mirror's snapshot of `d`, with each kept gate that is still closed.
function presentSnap(d) {
  const s = d.mirror.snapshot(), k = d.kept;
  for (const id of Object.keys(k.gates)) {
    const go = presentGate(d.inner, id)?.querySelector('button.go');
    if (go?.hidden && !s.gates[id]) { s.gates[id] = 'done'; if (k.pick[id] != null) s.pick[id] = k.pick[id]; }
    else { delete k.gates[id]; delete k.pick[id]; delete k.answers[id]; }
  }
  return s;
}
//: A changed snapshot of demo `d` as a `demo` move; its answers follow in a move of their own, after the server has the snapshot of the settled gate.
function presentDemo(p, d) {
  if (lee.present !== p || !d.mirror) return;
  const m = presentDemoMove(d.slug, presentSnap(d));
  if (!m || !abhyasaStage.valid({v: 1, ...m})) return presentSay('The demo is too large for the room screen.');
  const was = p.held.demo[d.slug], key = x => JSON.stringify([x.state, x.gates, x.pick || {}]);
  if (was && key(was) === key(m)) return p.slots?.['demo:' + d.slug]?.busy || presentAnswers(p, d);
  p.held.demo[d.slug] = m;
  const a = p.held.answers[d.slug], g = a && Object.fromEntries(Object.entries(a.gates).filter(([id]) => m.gates[id] === 'done'));
  if (a) { if (Object.keys(g).length) p.held.answers[d.slug] = {...a, gates: g}; else delete p.held.answers[d.slug]; }
  presentLatest(p, 'demo:' + d.slug, () => ['/present/move', m], () => presentAnswers(p, d));
}
//: The answers of the settled gates of demo `d` for the room, once the server holds those gates as done; never from `rk-predict` itself.
function presentAnswers(p, d) {
  if (lee.present !== p || !d.mirror || !p.canvas.contains(d.host)) return;
  const done = p.held.demo[d.slug]?.gates || {}, got = {...d.kept.answers, ...d.mirror.answers()};
  const gates = Object.fromEntries(Object.entries(got).filter(([id]) => done[id] === 'done'));
  if (!Object.keys(gates).length || JSON.stringify(p.held.answers[d.slug]?.gates) === JSON.stringify(gates)) return;
  const m = {t: 'answers', slide: `s${p.at.slide + 1}`, slug: d.slug, gates};
  if (!abhyasaStage.valid({v: 1, ...m})) return;
  p.held.answers[d.slug] = m;
  presentPost(p, '/present/move', m);
}
function presentEnd(p) { presentForget(p.id); lee.presentWait = presentPost(p, '/present/end', {}, true); closePresentation(); }

async function presentNotebook(start = '') {
  if (lee.kind !== 'notebook') return status(PRESENT_NOT_NOTEBOOK, 'err');
  const cells = lee.cells, line = presentLine(presentSlides(cells, mdSource));
  if (!line.length) return status(PRESENT_NOTHING, 'err');
  closePresentation();
  const ticket = lee.presentTicket = (lee.presentTicket || 0) + 1, name = lee.path || lee.tabKey;
  const at = typeof start === 'object' ? presentNear(line, start) : (start || riseConfig(lee.rise).start) === 'selected' ? presentPlace(line, lee.sel) : {slide: 0, step: 0};
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
  presentOpen(r, true, name);
}

const PRESENT_HTML = '<div class="lee-present-main"><div class="lee-stage"><div class="lee-slide"></div></div>' +
  '<aside class="lee-present-notes" id="lee-present-notes" aria-label="Speaker notes" hidden><div class="lee-present-notes-head"><h2>Speaker notes</h2>' +
  '<button type="button" data-close title="Close the notes (Esc)">Close</button></div>' +
  '<p class="lee-present-warn">The room can see these notes when you share this screen.</p>' +
  '<div data-notes-body></div><p data-upcoming></p><p data-clock></p></aside>' +
  '<div class="lee-present-err" role="alert" hidden><p data-err-sum></p><p class="lee-present-warn">The room cannot see this error.</p>' +
  '<details><summary>Traceback</summary><pre data-err-tb></pre></details><div class="lee-present-err-acts">' +
  '<button type="button" data-show-error title="Show this error on the room screen">Show error</button><button type="button" data-err-close title="Close (Esc)">Close</button></div></div>' +
  '<div class="lee-present-msg" role="status" hidden></div></div>' +
  '<div class="lee-present-strip" role="toolbar" aria-label="Presentation controls">' +
  '<span class="lee-present-group"><button type="button" data-prev title="Previous (Left arrow)">Previous</button><button type="button" data-next title="Next (Right arrow or Space)">Next</button>' +
  '<span data-where></span><span data-runs></span></span>' +
  '<span class="lee-present-group"><button type="button" data-audience title="Open a window to show on the projector">Audience window</button><span data-conn role="status">Audience window: not connected</span></span>' +
  '<span class="lee-present-group lee-present-tools"><button type="button" data-notes title="Notes (N)" aria-controls="lee-present-notes" aria-expanded="false">Notes</button>' +
  '<button type="button" data-smaller title="Smaller text" aria-label="Smaller text">A−</button><span data-size title="Body text size on the 1280 by 720 slide"></span>' +
  '<button type="button" data-bigger title="Larger text" aria-label="Larger text">A+</button>' +
  '<button type="button" data-full title="Full screen (F)">Full screen</button></span><span class="lee-gap"></span>' +
  '<button type="button" data-end title="End the presentation">End</button></div>';

/* The presenter screen for presentation `r` of notebook `path`, as the server holds it: place, blank, size, look, clock and the stored deck.
   A `fresh` start then posts this page's text size and theme; a resumed one posts nothing until the presenter acts. */
function presentOpen(r, fresh, path) {
  const root = Object.assign(document.createElement('div'), {className: 'lee-present', tabIndex: -1, innerHTML: PRESENT_HTML});
  root.setAttribute('role', 'dialog'); root.setAttribute('aria-label', 'Presentation');
  const q = s => $(s, root), canvas = q('.lee-slide'), notes = q('.lee-present-notes'), strip = q('.lee-present-strip'), end = q('[data-end]'), notesBtn = q('[data-notes]');
  const dot = canvas.appendChild(Object.assign(document.createElement('div'), {className: 'stage-dot'}));
  dot.setAttribute('aria-hidden', 'true');
  canvas.appendChild(Object.assign(document.createElement('div'), {className: 'stage-blank', textContent: String(r.presenter?.title || '').replace(/\.ipynb$/i, '')}));
  const at = presentIndex(r.at), ide = presentTheme();
  const live = r.live || {}, outs = Object.values(live.outs || {});
  const p = lee.present = {root, canvas, key: r.key, ak: r.ak, id: r.id, boot: r.boot, holder: r.holder, path, src: r.src || {}, audience: r.audience, deck: r.presenter,
                           line: r.presenter.slides.map(s => ({groups: s.groups || 0})), at, acked: at, text: fresh ? presentStored() : r.at.size/10,
                           blank: !fresh && !!r.at.blank, outs: Object.fromEntries(outs.map(o => [o.cell, {cell: o.cell, gen: o.gen, seq: o.seq, html: o.html}])),
                           gen: Math.max(0, ...outs.map(o => o.gen)), floor: 0, runs: {}, outq: {}, err: null, held: {demo: {...live.demo}, answers: {...live.answers}},
                           demos: new Map(), slugs: new Set(r.presenter.slides.flatMap(s => (s.blocks || []).flatMap(b => (b.demo || []).map(x => x.id)))), chain: Promise.resolve(), started: Date.now() - (r.elapsed || 0)*1000, win: null,
                           ide, look: fresh ? ide : r.look?.theme || '', laser: false, pt: null, frame: 0, busy: false, lit: false, sent: 0, dotT: 0, left: -Infinity, inert: []};
  canvas.classList.toggle('blank', p.blank);
  // the presenter's own demo, with its answers, is the source of the room copy: one mirror for each mount, once rupaka has drawn it
  const demo = spec => {
    const e = rupakaDraw(spec), d = {host: e.host, inner: e.inner, slug: spec.id, mirror: null, kept: {gates: {}, pick: {}, answers: {}}};
    // a demo that a run's output shows is not in the deck, so the server takes no move for it; both windows draw it from the room copy
    e.done.then(() => { if (!e.ok) return; slidesRk(e.host.shadowRoot); if (lee.present === p && p.slugs.has(d.slug)) presentMirror(p, d); });
    return d;
  };
  const mount = (spec, id) => (p.demos.get(id) || p.demos.set(id, demo(spec)).get(id)).host;
  const stuck = d => { const a = presentMove(p.line, p.at, d); return a.slide === p.at.slide && a.step === p.at.step; };
  p.draw = () => {
    const s = p.deck.slides[p.at.slide] || {}, {fits} = slidesDraw(canvas, p.deck, p.at.slide, p.at.step, {key: p.ak, size: Math.round(p.text*10), mount, math: renderMath, outs: slidesHtml(p.outs)});
    for (const d of p.demos.values()) presentAnswers(p, d);
    const g = p.line[p.at.slide]?.groups || 0;
    q('[data-where]').textContent = `${p.at.slide + 1} / ${p.deck.slides.length}` + (g ? ` · step ${p.at.step + 1} / ${g + 1}` : '');
    q('[data-prev]').disabled = stuck(-1); q('[data-next]').disabled = stuck(1);
    if (document.activeElement?.disabled && root.contains(document.activeElement)) root.focus({preventScroll: true});
    q('[data-size]').textContent = `Text ${Math.round(28*p.text*(+canvas.style.getPropertyValue('--slide-fit') || 1))} px`;
    q('[data-notes-body]').replaceChildren(slidesSafe(s.notes || '', p.ak));
    q('[data-upcoming]').textContent = s.next ? `Next: ${s.next}` : 'This is the last slide.';
    presentStrip(p);
    if (!fits) presentSay(`Slide ${p.at.slide + 1} has more than fits. Split it or trim it.`);
  };
  const go = d => {
    const a = presentMove(p.line, p.at, d); if (a.slide === p.at.slide && a.step === p.at.step) return;
    if (a.slide !== p.at.slide) p.held.answers = {};
    p.at = a; p.draw(); presentGo(p);
  };
  const resize = d => {
    p.text = presentStep(p.text, d);
    try { localStorage.setItem(presentKey(), String(p.text)); } catch {}
    p.draw(); presentSay(`text ${Math.round(p.text*100)}%`); presentGo(p);
  };
  const full = () => document.fullscreenElement ? document.exitFullscreen().catch(() => {})
    : root.requestFullscreen ? root.requestFullscreen().catch(() => presentSay('Use View › Enter Full Screen to fill the screen.')) : presentSay('Use View › Enter Full Screen to fill the screen.');
  const setNotes = open => {
    const inside = notes.contains(document.activeElement);
    notes.hidden = !open; root.classList.toggle('lee-notes-open', open); notesBtn.setAttribute('aria-expanded', String(open));
    if (!open && inside) notesBtn.focus({preventScroll: true});
  };
  const toggleNotes = () => setNotes(notes.hidden);
  // the newest point waits here; at most one is in the post chain, so slow replies queue nothing behind them
  const send = () => {
    p.frame = 0;
    if (lee.present !== p || !p.laser || p.blank || !p.pt || p.busy) return;
    if (performance.now() - p.sent < PRESENT_POINT_MS) return void (p.frame = requestAnimationFrame(send));
    const [x, y] = p.pt; p.pt = null; p.busy = p.lit = true; p.sent = performance.now();
    presentPost(p, '/present/move', {t: 'point', x, y}).finally(() => { p.busy = false; if (p.pt) p.frame ||= requestAnimationFrame(send); });
  };
  const point = e => {
    if (!p.laser || p.blank) return;
    const b = canvas.getBoundingClientRect(); if (!b.width || !b.height) return;
    const [x, y] = p.pt = [presentClamp((e.clientX - b.left)/b.width), presentClamp((e.clientY - b.top)/b.height)];
    dot.style.left = x*100 + '%'; dot.style.top = y*100 + '%'; dot.classList.add('on');
    clearTimeout(p.dotT); p.dotT = setTimeout(() => dot.classList.remove('on'), PRESENT_FADE);
    p.frame ||= requestAnimationFrame(send);
  };
  // the dot off on both screens; the laser stays on for the next move
  const dark = () => {
    cancelAnimationFrame(p.frame); p.frame = 0; p.pt = null; clearTimeout(p.dotT); dot.classList.remove('on');
    if (p.lit) { p.lit = false; presentPost(p, '/present/move', {t: 'point', off: true}); }
  };
  const laser = (on = !p.laser) => { if (!on) dark(); p.laser = on; root.classList.toggle('lee-laser', on); };
  const blank = () => { p.blank = !p.blank; canvas.classList.toggle('blank', p.blank); if (p.blank) dark(); presentGo(p); };
  const esc = () => {
    if ($('.lee-modal')) return false;
    if (document.fullscreenElement) return false;
    if (performance.now() - p.left < PRESENT_FULL_MS) return true;
    if (p.err) return presentErr(p, null), true;
    if (!notes.hidden) return setNotes(false), true;
    if (p.laser) return laser(false), true;
    const a = document.activeElement;
    if (a !== root && root.contains(a) && (a.closest('.lee-rupaka') || isTextEntry(a))) root.focus({preventScroll: true});
    return true;
  };
  p.keys = {ArrowRight: () => go(1), ArrowDown: () => go(1), Space: () => go(1), PageDown: () => go(1),
            ArrowLeft: () => go(-1), ArrowUp: () => go(-1), 'Shift+Space': () => go(-1), PageUp: () => go(-1),
            KeyN: toggleNotes, KeyF: full, KeyX: () => laser(), KeyB: blank, Escape: esc};
  // the rules of `abhyasaStage.presenter`, which the IDE page does not load: a key is its `e.code`; no Alt, AltGraph, Cmd or Ctrl key, no held key,
  // no key in a field or a demo but Esc; Space or Enter presses a focused button and nothing else; a function that gives false lets the key go on
  p.onKey = e => {
    if (lee.present !== p || e.metaKey || e.ctrlKey || e.altKey || e.getModifierState?.('AltGraph') || e.isComposing || e.key === 'Process') return;
    const a = document.activeElement, t = keyTarget(e);
    if (a && a !== document.body && !root.contains(a)) return;
    if (e.code !== 'Escape' && (isTextEntry(t) || a?.closest('.lee-rupaka'))) return;
    if ((e.code === 'Space' || e.code === 'Enter') && t?.matches?.(PRESENT_PRESSES)) { if (e.repeat) e.preventDefault(); return; }
    const name = (e.shiftKey ? 'Shift+' : '') + e.code, fn = Object.hasOwn(p.keys, name) && p.keys[name]; if (!fn) return;
    if (!e.repeat && fn(e) === false) return;
    e.preventDefault(); e.stopPropagation();
  };
  p.onFull = () => { if (!document.fullscreenElement) p.left = performance.now(); };
  p.onFocus = e => { if (lee.present === p && !root.contains(e.target) && !e.target.closest?.('.lee-modal')) root.focus({preventScroll: true}); };
  p.onBlur = () => dark();
  canvas.addEventListener('pointermove', point); canvas.addEventListener('pointerleave', dark); canvas.addEventListener('pointercancel', dark);
  p.onOutput = e => { const run = lee.present === p && p.runs[e.detail.id]; if (run) presentOut(p, e.detail.id, run.gen, e.detail.outputs || [], false); };
  p.onRestart = () => presentReset(p);
  q('[data-show-error]').onclick = () => presentShowError(p); q('[data-err-close]').onclick = () => presentErr(p, null);
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
  // one stream; the browser connects it again by itself, and a closed one opens again with a growing wait; each connect starts with the live id
  const listen = () => {
    const s = p.events = new EventSource('/present/events'), on = (t, f) => s.addEventListener(t, e => { if (p.events === s) f(JSON.parse(e.data)); });
    on('presentation', d => { p.wait = 0; presentCheck(p, d); }); on('presenter', d => presentCheck(p, d));
    on('audience', d => { if (d.id === p.id) q('[data-conn]').textContent = d.n ? 'Audience window: connected' : 'Audience window: not connected'; });
    on('presentation-ended', d => {
      if (d.id !== p.id || lee.present !== p) return;
      presentForget(p.id); closePresentation(); status(d.reason === 'replaced' ? 'Another presentation started.' : PRESENT_ENDED, 'err');
    });
    s.onerror = () => {
      if (p.events !== s || s.readyState !== EventSource.CLOSED || lee.present !== p || p.again) return;
      p.again = setTimeout(() => { p.again = 0; if (lee.present === p && p.events === s) listen(); }, p.wait = Math.min(15000, (p.wait || 500)*2));
    };
  };
  listen();
  // the IDE theme changing during the show is a look move; the look the server holds at a resume is kept until then
  p.watch = new MutationObserver(() => { const t = presentTheme(); if (t && t !== p.ide) presentPost(p, '/present/move', {t: 'look', theme: p.ide = p.look = t}); });
  p.watch.observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme', 'data-mode', 'data-density']});
  p.clock = setInterval(() => {
    const s = Math.floor((Date.now() - p.started)/1000);
    q('[data-clock]').textContent = `Time: ${Math.floor(s/60)}:${String(s % 60).padStart(2, '0')}`;
  }, 1000);
  document.addEventListener('keydown', p.onKey, true); addEventListener('lee-cell-output', p.onOutput); addEventListener('lee-kernel-restart', p.onRestart);
  clearTimeout(lee.autoSaveTimer);
  document.addEventListener('fullscreenchange', p.onFull); document.addEventListener('focusin', p.onFocus, true); addEventListener('blur', p.onBlur);
  document.documentElement.classList.add('talk');
  closeInlinePopover(); document.body.appendChild(root); slidesScale(q('.lee-stage'));
  // the page under the presentation takes no focus and no key; a dialog opened later still can
  p.inert = [...document.body.children].filter(el => el !== root && !el.inert && !el.matches('.lee-modal'));
  for (const el of p.inert) el.inert = true;
  root.focus({preventScroll: true});
  const m = root.appendChild(Object.assign(document.createElement('div'), {className: 'lee-slide lee-measure'}));
  const long = p.deck.slides.map((s, i) => slidesDraw(m, p.deck, i, s.groups, {key: p.ak, size: Math.round(p.text*10)}).fits ? 0 : i + 1).filter(Boolean);
  m.remove();
  p.draw(); wake();
  if (long.length) presentSay(long.length === 1 ? `Slide ${long[0]} has more than fits. Split it or trim it.` : `Slides ${long.join(', ')} have more than fits. Split them or trim them.`);
  if (fresh) { presentGo(p); if (p.look) presentPost(p, '/present/move', {t: 'look', theme: p.look}); }
  const failed = outs.filter(o => o.error && o.html === o.room).sort((a, b) => b.gen - a.gen)[0];
  if (failed) presentErr(p, {cell: failed.cell, gen: failed.gen, ...failed.error});
  for (const o of outs) if (!o.done) presentFollow(p, o.cell, o);
  presentKeep(p);
  root.dataset.ready = '';
}

function closePresentation() {
  const p = lee.present; if (!p) return;
  lee.present = null;
  document.removeEventListener('keydown', p.onKey, true); removeEventListener('lee-cell-output', p.onOutput); removeEventListener('lee-kernel-restart', p.onRestart);
  for (const d of p.demos.values()) d.unwatch?.();
  document.removeEventListener('fullscreenchange', p.onFull); document.removeEventListener('focusin', p.onFocus, true); removeEventListener('blur', p.onBlur);
  cancelAnimationFrame(p.frame); clearTimeout(p.dotT);
  for (const el of p.inert || []) el.inert = false;
  p.events?.close(); clearTimeout(p.again); p.watch?.disconnect(); clearTimeout(p.idle); clearTimeout(p.endT); clearInterval(p.clock);
  document.documentElement.classList.remove('talk');
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  $$('[data-markdown]', p.root).forEach(el => {
    clearTimeout(el._leeMarkdownTimer); if (el._leeCodeFrame) cancelAnimationFrame(el._leeCodeFrame);
    for (const v of el._leeCodeViews || []) try { LeeCM.destroy(v); } catch {}
  });
  $$('iframe', p.root).forEach(f => f.remove());
  p.root.remove();
  if (lee.kind === 'notebook' && lee.cells.length) focusCell(lee.sel);
  if ($('.lee-tab.active.dirty')) scheduleAutoSave();
}
