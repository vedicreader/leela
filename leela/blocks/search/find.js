/* --------------------------------------------------------------------- find */
/* One find pane for both shapes of document. CodeMirror's own panel searches the one cell it
   belongs to, which is never what is being asked of a notebook, and it offered no regex or
   replace where the cell bar did. This is the single mod+f: regex, case, whole word and
   replace, over a file or over every cell. */

const FIND_FLAGS = 'lee-find-flags';
const MAX_FIND_HITS = 5000;

const cellText = i => {
  const c = lee.cells[i]; if (!c) return '';
  const v = lee.editors.get(c.id);
  return v ? LeeCM.getDoc(v) : String(c.source || '');
};

function findFlags() {
  if (!lee.findFlags) {
    try { lee.findFlags = JSON.parse(localStorage.getItem(FIND_FLAGS)) || {}; }
    catch (_) { lee.findFlags = {}; }
  }
  return lee.findFlags;
}

function findRe(q) {
  const f = findFlags();
  let body = f.regex ? q : q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  if (f.word) body = `\\b(?:${body})\\b`;
  return new RegExp(body, 'g' + (f.case ? '' : 'i'));
}

/* `-1` is the open file; anything else is a cell index. Whichever the tab holds, the pane
   walks the live text rather than what was last saved. */
const findDocs = () => lee.kind === 'notebook' ? lee.cells.map((_, i) => i) : (curEditor() ? [-1] : []);
const findText = i => i < 0 ? (curEditor() ? LeeCM.getDoc(curEditor()) : '') : cellText(i);
const findView = i => i < 0 ? curEditor() : ensureCellMounted(i);

/* Null means the pattern itself is broken, which is a different thing to say than "no matches". */
function findMatches(q) {
  if (!q) return [];
  let re;
  try { re = findRe(q); } catch (_) { return null; }
  const out = [];
  for (const i of findDocs()) {
    const text = findText(i);
    re.lastIndex = 0;
    for (let m; (m = re.exec(text));) {
      out.push({doc: i, from: m.index, to: m.index + m[0].length});
      if (!m[0].length) re.lastIndex++;
      if (out.length >= MAX_FIND_HITS) return out;
    }
  }
  return out;
}

function findPaint() {
  const bar = $('#leefind'); if (!bar) return;
  const q = $('#leefindq', bar).value, hits = findMatches(q), at = lee.find?.at ?? -1;
  lee.find = {q, hits: hits || [], at: hits && at < hits.length ? at : -1, bad: hits === null};
  $('#leefindcount', bar).textContent = !q ? '' : hits === null ? 'bad pattern'
    : !hits.length ? 'no matches' : `${(lee.find.at < 0 ? 0 : lee.find.at) + 1} of ${hits.length}`;
  bar.classList.toggle('empty', !!q && !lee.find.hits.length);
  $$('[data-find-flag]', bar).forEach(b => b.classList.toggle('on', !!findFlags()[b.dataset.findFlag]));
}

function findStep(direction) {
  const bar = $('#leefind'), state = lee.find;
  if (!bar || !state?.hits.length) return;
  const n = state.hits.length;
  state.at = ((state.at + direction) % n + n) % n;
  const hit = state.hits[state.at];
  if (hit.doc >= 0) focusCell(hit.doc);
  const view = findView(hit.doc);
  if (view) LeeCM.setSelection(view, hit.from, hit.to);
  $('#leefindcount', bar).textContent = `${state.at + 1} of ${n}`;
  // `focusCell` and `setSelection` both take the focus, a frame apart. The query is where the
  // typing belongs, so it is claimed back after both have had their turn.
  requestAnimationFrame(() => requestAnimationFrame(() => $('#leefindq', bar)?.focus()));
}

function findReplaceOne() {
  const state = lee.find; if (!state?.hits.length) return findPaint();
  if (state.at < 0) return findStep(1);
  const hit = state.hits[state.at], view = findView(hit.doc);
  if (!view) return;
  const text = findText(hit.doc).slice(hit.from, hit.to);
  LeeCM.replaceRange(view, hit.from, hit.to, text.replace(findRe(state.q), $('#leefindr').value));
  const was = state.at;
  findPaint();
  lee.find.at = Math.min(was, lee.find.hits.length - 1) - 1;
  findStep(1);
}

function findReplaceAll() {
  const state = lee.find; if (!state?.hits.length) return findPaint();
  const to = $('#leefindr').value, done = new Set(state.hits.map(h => h.doc));
  let n = 0;
  for (const i of done) {
    const view = findView(i); if (!view) continue;
    const before = findText(i), after = before.replace(findRe(state.q), to);
    if (after === before) continue;
    n += state.hits.filter(h => h.doc === i).length;
    LeeCM.setDoc(view, after);
  }
  lee.find = null; findPaint();
  status(`replaced ${n} match${n === 1 ? '' : 'es'}`, 'ok');
}

function findClose() {
  const bar = $('#leefind'); if (bar) bar.hidden = true;
  lee.find = null;
  const v = curEditor(); if (v) LeeCM.focus(v);
}

function findMake() {
  const bar = document.createElement('div');
  bar.id = 'leefind'; bar.className = 'lee-find-bar'; bar.setAttribute('role', 'search');
  bar.innerHTML =
    `<input class="lee-input" id="leefindq" spellcheck="false" placeholder="find" aria-label="find">` +
    `<div class="lee-find-tools">` +
      `<button type="button" data-find-flag="regex" title="regular expression" aria-label="regular expression">.*</button>` +
      `<button type="button" data-find-flag="case" title="match case" aria-label="match case">Aa</button>` +
      `<button type="button" data-find-flag="word" title="whole word" aria-label="whole word">|ab|</button>` +
      `<span class="lee-find-count" id="leefindcount" aria-live="polite"></span>` +
      `<button type="button" data-find="prev" title="previous match (shift+enter)">&#8593;</button>` +
      `<button type="button" data-find="next" title="next match (enter)">&#8595;</button>` +
      `<button type="button" data-find="close" title="close (esc)">&#10005;</button>` +
    `</div>` +
    `<input class="lee-input" id="leefindr" spellcheck="false" placeholder="replace" aria-label="replace">` +
    `<div class="lee-find-tools">` +
      `<button type="button" class="lee-btn" data-find="one" title="replace this match">replace</button>` +
      `<button type="button" class="lee-btn" data-find="all" title="replace every match">all</button>` +
    `</div>`;
  document.body.appendChild(bar);
  bar.addEventListener('click', e => {
    const flag = e.target.closest('[data-find-flag]');
    if (flag) {
      const f = findFlags();
      f[flag.dataset.findFlag] = !f[flag.dataset.findFlag];
      try { localStorage.setItem(FIND_FLAGS, JSON.stringify(f)); } catch (_) {}
      lee.find = null; findPaint(); $('#leefindq', bar).focus();
      return;
    }
    const b = e.target.closest('[data-find]'); if (!b) return;
    if (b.dataset.find === 'close') return findClose();
    if (b.dataset.find === 'one') return findReplaceOne();
    if (b.dataset.find === 'all') return findReplaceAll();
    findStep(b.dataset.find === 'next' ? 1 : -1);
  });
  const step = e => {
    if (e.key === 'Escape') { e.preventDefault(); return findClose(); }
    if (e.key !== 'Enter') return;
    e.preventDefault();
    if (!lee.find?.hits.length) findPaint();
    findStep(e.shiftKey ? -1 : 1);
  };
  $('#leefindq', bar).addEventListener('input', findPaint);
  $('#leefindq', bar).addEventListener('keydown', step);
  $('#leefindr', bar).addEventListener('keydown', e => {
    if (e.key === 'Escape') { e.preventDefault(); return findClose(); }
    if (e.key === 'Enter') { e.preventDefault(); findReplaceOne(); }
  });
  return bar;
}

function leeFind() {
  if (!findDocs().length) return status('open a file to search it', 'err');
  const bar = $('#leefind') || findMake();
  bar.hidden = false;
  const input = $('#leefindq', bar), view = curEditor(), held = view ? LeeCM.selection(view) : null;
  if (held && held.from !== held.to && !held.text.includes('\n')) input.value = held.text;
  lee.find = null;
  findPaint();
  input.focus(); input.select();
}
