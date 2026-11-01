function learnDiff(guess, actual) {
  const lines = text => text.split(/\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]/)
    .map(line => line.split(/[\t-\r\x1c-\x20\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/).filter(Boolean).join(' ')).filter(Boolean);
  const g = lines(guess), a = lines(actual);
  return Array.from({length: Math.max(g.length, a.length)}, (_, i) => {
    const x = g[i] ?? null, y = a[i] ?? null;
    return {guess: x, actual: y, kind: x === null ? 'missing' : y === null ? 'extra' : x === y ? 'match' : 'mismatch'};
  });
}

function lessonActual(c) {
  const text = value => Array.isArray(value) ? value.join('') : String(value ?? '');
  const outputs = c.outputs || [], error = outputs.find(o => o.output_type === 'error');
  if (error) {
    const last = stripAnsi(text((error.traceback || []).join('\n'))).trim().split('\n').pop();
    return 'It raised ' + (last || `${error.ename}: ${error.evalue}`);
  }
  return stripAnsi(outputs.map(o => o.output_type === 'stream' ? text(o.text) : text(o.data?.['text/plain'])).filter(Boolean).join('\n'));
}
function lessonRevealText(c) {
  const lesson = c.extra.lesson, rows = learnDiff(String(lesson.prediction || ''), lessonActual(c));
  const different = rows.filter(r => r.kind !== 'match');
  if (!different.length) return 'Right. You saw that before running it.';
  const lines = rows.filter(r => r.kind === 'match').map(r => r.actual);
  for (const r of different) lines.push(r.kind === 'missing' ? `It printed ${r.actual}, which you did not expect.`
    : r.kind === 'extra' ? `You expected ${r.guess}, which did not appear.` : `You wrote ${r.guess}. It printed ${r.actual}.`);
  if (lesson.confidence >= 60) lines.push('You were sure, and it went another way. That is the part worth a look.');
  return lines.join('\n');
}
//: The line a failed lesson write shows: the server's own sentence when it sent one, else a line that says what to do.
const lessonSaid = (err, b = err?.body) => (b && typeof b === 'object' && (b.error || b.message)) || (typeof b === 'string' && b.trim() && !b.trim().startsWith('<') && b.trim().slice(0, 300)) || 'Leela did not save this. Try again.';
function lessonRevealActions(cell, el) {
  const lesson = cell.extra.lesson, key = `${cell.id}:${cell.execution_count}`;
  const row = document.createElement('div'); row.className = 'lee-reveal-save'; el.appendChild(row);
  if (lesson.saved === key) { row.textContent = lesson.saved_message || 'Saved to your learning shelf.'; return; }
  const button = document.createElement('button'); button.type = 'button'; button.className = 'lee-btn'; button.textContent = 'Save card';
  row.appendChild(button);
  button.onmousedown = e => { e.preventDefault(); e.stopPropagation(); };
  button.onclick = async () => {
    if (button.disabled) return;
    button.disabled = true;
    const path = lee.path, tabKey = lee.tabKey;
    try {
      await lee.nbQueue;
      const stop = lee.tabKey !== tabKey ? 'Return to the lesson notebook, then save.' : $('.lee-tab.active')?.classList.contains('dirty') ? 'Save the notebook first.' : '';
      if (stop) { status(stop, 'err'); button.disabled = false; return; }
      const d = await post('/lesson/save', {path, cell_id: cell.id});
      lesson.saved = d.saved; lesson.saved_message = d.message;
      const current = lee.tabKey === tabKey && lee.cells.find(c => c.id === cell.id && c.execution_count === cell.execution_count);
      if (current) Object.assign(current.extra.lesson, {saved: d.saved, saved_message: d.message});
      row.textContent = d.message;
      refreshLessonDue();
      if (d.disk_version) { recordDiskVersion(path, d.disk_version); await rebaseDrafts(path, d.disk_version); noteSelfWrite(path); }
    } catch (e) { status(lessonSaid(e), 'err'); button.disabled = false; }
  };
}
function renderLessonReveal(c) {
  const cell = $(`.lee-cell[data-id="${CSS.escape(c.id)}"]`); if (!cell) return;
  $('.lee-reveal', cell)?.remove();
  if (c.cell_type !== 'code' || !c.extra?.lesson || c.extra.lesson.for_count !== c.execution_count
      || c.stale || $('#state-' + c.id)?.classList.contains('stale') || c.running || !c.outputs?.length) return;
  const el = document.createElement('div'); el.className = 'lee-reveal';
  el.textContent = lessonRevealText(c);
  $('#out-' + c.id, cell).after(el);
  lessonRevealActions(c, el);
}
//: A gate locked in a notebook cell's demo goes to the server, which files it only in a lesson. The server checks a literal answer itself and files the page's `ans` and `ok` for a state-path answer. The gate reveals once the server answers ok. A failure opens the gate again with the server's message.
async function lessonPredict(e) {
  const at = e.composedPath(), host = at.find(n => n.classList?.contains('lee-rupaka')), cell = at.find(n => n.matches?.('.lee-cell[data-id]'));
  if (!cell || host?.leeSource == null) return;
  // rupaka 0.0.1 has no settle, and its gate reveals on lock-in.
  const held = typeof e.detail?.settle === 'function', settle = held ? e.detail.settle : () => {};
  if (held) e.preventDefault();
  try {
    const {demo, gate, picked, ans, ok, why} = e.detail, path = lee.path;
    const src = await srcHash(host.leeSource);
    await lee.nbQueue;
    const d = await post('/lesson/predict', {path, cell_id: cell.dataset.id, demo, gate, picked, ans, ok, why, src});
    settle(true);
    status(d.message || '', 'ok');   // an ok answer also clears the toast of a failed try
  } catch (err) {
    const said = lessonSaid(err);
    settle(false, said);
    status(said, 'err');
  }
}
// The Node harnesses load this file with no `document`.
globalThis.document?.addEventListener('rk-predict', lessonPredict);
//: "I don't get…" on a lesson cell: one line goes to the screen guide, and its steps and sources show as plain text in the cell's output area until the board is drawn.
const GUIDE_START = "I don't get ";
const lessonNotebook = () => lee.cells.some(c => c.extra?.lesson);
const guideCell = c => c.cell_type === 'markdown' ? !['prediction', 'card'].includes(c.extra?.lesson?.role) : isExercise(c);
const guideText = d => [...(d.steps || []).map(s => s.say), ...(d.sources || []).map(s => `Source ${s.n}: ${s.label}, ${s.title}`), d.end].filter(Boolean).join('\n');
const boardLoad = {p: null};
//: abhyasa's board, loaded on the first guide: `abhyasaBoard`, or null after one warning, and the next guide tries again.
function loadBoard() {
  if (window.abhyasaBoard) return Promise.resolve(window.abhyasaBoard);
  return boardLoad.p ||= (async () => {
    const meta = n => $(`meta[name="${n}"]`)?.content;
    document.head.appendChild(Object.assign(document.createElement('link'), {rel: 'stylesheet', href: meta('lee-board-css') || '/leestatic/lee-board.css'}));
    await new Promise((ok, no) => {
      const s = document.createElement('script');
      s.src = meta('lee-board-src') || '/leestatic/lee-board.js'; s.onload = ok;
      s.onerror = () => { s.remove(); no(new Error('board.js could not be loaded')); };
      document.head.appendChild(s);
    });
    return window.abhyasaBoard || Promise.reject(new Error('board.js defined no abhyasaBoard'));
  })().catch(e => { console.warn('Leela guide:', e); return null; }).finally(() => { boardLoad.p = null; });
}
//: Gives the parts of a lesson cell the ids `guide_context` names them by. The demo's inputs and readouts get theirs from abhyasa's `demoAnchors` when the guide asks.
function guideStamp(cell, c) {
  const tag = (e, id) => { if (e) e.dataset.guideId = id; }, md = $('.lee-md-cell', cell);
  if (!md) return;
  tag(md, c.extra?.exercise?.role === 'task' ? 'check' : 'passage');
  $$('img', md).forEach((img, n) => tag(img, `img${n + 1}`));
  tag($('.lee-rupaka', md), 'demo');
}
//: The code and the output in `cell`, as `code1` to `code4` in page order: the values that the board's panel copies. A markdown cell gives its code blocks; a code cell its code and its text outputs.
function guideCode(cell, c) {
  $$('[data-guide-id^="code"]', cell).forEach(e => delete e.dataset.guideId);
  $$(c?.cell_type === 'markdown' ? '.lee-md-cell pre, .lee-md-cell .cm-content' : '.cm-content, [id^="out-"] pre', cell).filter(e => e.textContent.trim()).slice(0, 4).forEach((e, n) => { e.dataset.guideId = `code${n + 1}`; });
}
//: The rupaka demo in `cell` as `{anchors, demo}` from the board's `demoAnchors`, which also stamps its ids; null with no demo or an older board.
const guideDemoAnchors = (cell, b) => { const inner = [...($('.lee-rupaka', cell)?.shadowRoot?.children || [])].find(n => n.rupaka); return inner && b?.demoAnchors ? b.demoAnchors(inner) : null; };
globalThis.document?.addEventListener('lee-markdown-rendered', e => {
  const cell = e.target.closest?.('.lee-cell[data-id]'), c = cell && lee.cells.find(x => x.id === cell.dataset.id);
  if (c && lessonNotebook() && guideCell(c)) guideStamp(cell, c);
});
//: The formulas, figures and code Leela drew in `cell`, in page order, as the one list the server takes them from: `{id, text, parts}` for each `f<n>`, `{id, text}` for each `img<n>` and `code<n>`. A figure on its own line has an empty `alt` and its text in the `figcaption`.
const guideAnchors = cell => $$('[data-guide-id]', cell).flatMap(e => { const id = e.dataset.guideId;
  return /^f\d+$/.test(id) ? [{id, text: (e.dataset.tex || '').trim(), parts: JSON.parse(e.dataset.parts || '[]').map(p => p[0])}] : /^img\d+$/.test(id) ? [{id, text: (e.alt || e.closest('figure')?.querySelector('figcaption')?.textContent || '').trim()}]
    : /^code[1-4]$/.test(id) ? [{id, text: e.textContent.trim().slice(0, 300)}] : []; });
const guideFind = (cell, id) => { const q = `[data-guide-id="${CSS.escape(id)}"]`; return $(q, cell) || $$('.lee-rupaka', cell).map(h => h.shadowRoot && $(q, h.shadowRoot)).find(Boolean) || null; };
const guideDemo = (cell, open) => set => { const inner = open && [...(guideFind(cell, 'demo')?.shadowRoot?.children || [])].find(n => n.rupaka); if (inner) Rupaka.set(inner, set); };
//: Draws the board in the cell it was asked from; false when the board is missing or fails, so the plain text stays.
//: Leela speaks with the browser's voice; the board's strip names it after the Voice button. The board calls only "on this Mac" local, and any other place "hosted", so off a Mac the strip names no place.
const GUIDE_VOICE = /Mac/.test(globalThis.navigator?.platform || '') ? {model: 'Browser voice', where: 'on this Mac'} : undefined;
//: "Show me …" to the guide: the hand-off to the demo of this idea in abhyasa, in place of a board.
function guideShowCard(sh, cell, id) {
  $('.lee-guide-out', cell)?.remove();
  const el = document.createElement('div'); el.className = 'lee-guide-out lee-guide-show'; el.textContent = `Show: ${sh.title}. `;
  if (sh.href) el.append(Object.assign(document.createElement('a'), {href: sh.href, target: '_blank', rel: 'noopener', textContent: 'Open in abhyasa ↗'}));
  else el.append('Start abhyasa to see the demo of this idea.');
  $('#out-' + id, cell).after(el);
}
//: Puts the board's side panel in the notebook area: under its tab bar, left of the side panes, and at most 45 % of its width (lee-ide.css).
function guideRoom() {
  const r = $('#editorstage')?.getBoundingClientRect();
  if (!r?.width) return;
  const s = document.documentElement.style;
  s.setProperty('--lee-panel-top', `${Math.round(r.top + 8)}px`);
  s.setProperty('--lee-panel-right', `${Math.round(innerWidth - r.right + 12)}px`);
  s.setProperty('--panel-w', `${Math.round(Math.min(440, r.width * .45))}px`);
}
globalThis.addEventListener?.('resize', () => { if (document.getElementById('board-panel')) guideRoom(); });
async function guidePlay(d, cell, board) {
  if (!board) return false;
  guideRoom();
  const assets = $('meta[name="lee-board-assets"]')?.content || '/leestatic/board/';
  try { await board.play(d, {host: {resolve: i => guideFind(cell, i), demo: guideDemo(cell, d.demo_open), assets}, voiceAt: GUIDE_VOICE}); return true; }
  catch (e) { console.warn('Leela guide:', e); return false; }
}
//: The board of the stream (`live`, the promise of its first play) gets the whole board: `finish` when its steps begin that board, else the whole board plays; a board the learner stopped stays stopped. With no board drawn, the plain text shows.
async function guideShow(d, id, cell, b, live, mine) {
  const drawn = live && await live, s = drawn && b.state;
  if (!mine() || (drawn && (!s || !s.streaming || b.finish(d)))) return;
  $('.lee-guide-out', cell)?.remove();
  if (await guidePlay(d, cell, b) || !mine()) return;
  const el = document.createElement('div'); el.className = 'lee-guide-out'; el.textContent = guideText(d);
  $('#out-' + id, cell).after(el);
}
const guideAsk = {n: 0, ctl: null};
globalThis.document?.addEventListener('board:stop', e => { if (e.detail?.by === 'learner') guideAsk.ctl?.abort(); });
//: Asks with events: the first step starts a streaming board and each next step is added to it, so step 1 draws before the model ends. A newer question aborts the older one, whose events then go nowhere.
async function lessonGuide(id, picked = String(globalThis.getSelection?.() ?? '').trim()) {
  const said = await inputDialog('screen guide', 'ask', GUIDE_START + picked.replace(/\s+/g, ' '));
  if (!said) return;
  const path = lee.path, tabKey = lee.tabKey, find = () => lee.tabKey === tabKey && $(`.lee-cell[data-id="${CSS.escape(id)}"]`);
  guideAsk.ctl?.abort();
  const n = ++guideAsk.n, ctl = guideAsk.ctl = new AbortController(), mine = () => n === guideAsk.n;
  let live = null, whole = false, failed = '', chain = Promise.resolve();
  const got = [];
  try {
    status('Asking the tutor…', 'ok');
    await lee.nbQueue;
    const asked = find();
    if (!asked) return status('', 'ok');
    guideCode(asked, lee.cells.find(x => x.id === id));
    const anchors = guideAnchors(asked), board = loadBoard(), demo = guideDemoAnchors(asked, await board);
    const on = async (ev, d) => {
      if (!mine()) return;
      if (ev === 'error') { failed = d.error; return; }
      if (ev === 'wait') return status(d.wait, 'ok');
      if (ev === 'step') { const k = (d.step.n || got.length + 1) - 1; if (k < got.length) got[k] = d.step; else got.push(d.step); }   // a step comes again as it grows
      const b = await board, cell = mine() && find();
      if (!cell) return;
      if (ev === 'show') { whole = true; b?.stop(); status('', 'ok'); return guideShowCard(d.show, cell, id); }
      if (ev === 'step') {
        if (!b) return;
        if (!live) { $('.lee-guide-out', cell)?.remove(); status('', 'ok'); live = guidePlay({steps: [d.step], tier: d.tier, sources: [], streaming: true, demo_open: d.demo_open}, cell, b); }
        else if (await live && mine() && b.state?.streaming) b.add(d.step);
      } else if (ev === 'board') { whole = true; status('', 'ok'); await guideShow(d, id, cell, b, live, mine); }
    };
    await postEvents('/nb/guide/stream', {path, cell_id: id, said, anchors, ...(demo && {demo})}, (ev, d) => { chain = chain.then(() => on(ev, d)).catch(e => console.warn('Leela guide:', e)); }, ctl.signal);
    await chain;
    const b = await board;
    if (!mine()) return;
    if (live && !whole && await live && mine() && b.state?.streaming) b.finish({steps: got, tier: 'tutor', sources: [], end: ''});
    status(failed, failed ? 'err' : 'ok');
  } catch (e) {
    if (e.name === 'AbortError') { if (mine()) status('', 'ok'); return; }
    status(lessonSaid(e, e.body ?? e.message), 'err');
  }
}
function lessonGuideSelected(picked) {
  const c = lee.cells[lee.sel];
  if (!lessonNotebook() || !c || !guideCell(c)) return status('Pick a lesson cell first.', 'err');
  return lessonGuide(c.id, picked);
}
function paintGuideButton(cell, c) {
  $('.lee-guide', cell)?.remove();
  if (!lessonNotebook() || !guideCell(c)) return;
  const button = document.createElement('button'); button.type = 'button'; button.className = 'lee-btn lee-guide'; button.textContent = GUIDE_START.trim() + '…';
  button.onmousedown = e => { e.preventDefault(); e.stopPropagation(); };
  button.onclick = () => lessonGuide(c.id);
  $('.lee-cellmain', cell).appendChild(button);
}
function paintLessonCell(cell, c) {
  const role = c.cell_type === 'markdown' ? c.extra?.lesson?.role : '';
  cell.dataset.lessonRole = role || '';
  $('.lee-confidence', cell)?.remove();
  if (role !== 'prediction') return;
  const row = document.createElement('div'); row.className = 'lee-confidence';
  const label = document.createElement('span'); label.textContent = 'Sure?'; row.appendChild(label);
  for (const [value, name] of [[10, 'not'], [30, 'a little'], [50, 'half'], [70, 'fairly'], [90, 'very']]) {
    const button = document.createElement('button'); button.type = 'button'; button.textContent = name;
    button.setAttribute('aria-pressed', String(c.extra.lesson.confidence === value));
    button.onclick = async () => {
      const at = lee.cells.findIndex(x => x.id === c.id), current = lee.cells[at]; if (!current) return;
      const previous = current.extra.lesson.confidence, confidence = previous === value ? null : value;
      if (confidence === null) delete current.extra.lesson.confidence; else current.extra.lesson.confidence = confidence;
      for (const b of row.querySelectorAll('button')) { b.disabled = true; b.setAttribute('aria-pressed', String(b === button && confidence !== null)); }
      try { await nbEdit({op: 'lesson_confidence', i: at, confidence}); }
      catch (e) {
        if (previous == null) delete current.extra.lesson.confidence; else current.extra.lesson.confidence = previous;
        status(lessonSaid(e), 'err');
      } finally {
        const now = lee.cells.find(x => x.id === c.id), host = $(`.lee-cell[data-id="${CSS.escape(c.id)}"]`);
        if (now && host) paintLessonCell(host, now);
      }
    };
    row.appendChild(button);
  }
  $('.lee-cellmain', cell).appendChild(row);
}
