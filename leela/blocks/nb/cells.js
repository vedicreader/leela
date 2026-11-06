/* The banner says where a cell sits and how big it is. The gutter carries the execution count,
 * which is blank until the cell runs and renumbers on every rerun. */
//: The gutter tag. A code cell is tagged with the notebook's own language, not always Python.
const LANG_TAGS = {python: 'py', rust: 'rs', javascript: 'js', typescript: 'ts'};
const cellKind = (c) => c.cell_type === 'code' ? (LANG_TAGS[nbLang()] || nbLang())
  : ({markdown: 'md', prompt: 'prompt'}[c.cell_type] || c.cell_type);
const cellLines = (c) => String(c.source || '').split('\n').length;
const plural = (n, word, many = word + 's') => `${n} ${+n === 1 ? word : many}`;
function cellMetaTitle(c, i) {
  const src = String(c.source || '');
  const rows = [`cell ${i + 1} of ${lee.cells.length} · ${c.cell_type} · ${plural(cellLines(c), 'line')}, ${src.length} chars`];
  if (c.cell_type === 'code')
    rows.push([c.execution_count == null ? 'not run' : `run ${c.execution_count}`,
               formatCellTime(c.execution_ms), plural((c.outputs || []).length, 'output')].filter(Boolean).join(' · '));
  rows.push('click to copy the id');
  return rows.join('\n');
}
function paintCellMeta(el, c, i) {
  const meta = el && $('.lee-cell-meta', el); if (!meta) return;
  $('.lee-cell-no', meta).textContent = '#' + (i + 1);
  $('.lee-cell-size', meta).textContent = `${cellKind(c)} · ${plural(cellLines(c), 'line')}`;
  const id = $('.lee-cell-id', meta); if (id) id.textContent = c.id;
  meta.dataset.cellId = c.id; meta.title = cellMetaTitle(c, i);
}
function copyCellId(button) {
  navigator.clipboard?.writeText(button.dataset.cellId || '');
  status('cell id copied', 'ok');
}
function refreshCellMeta(c) {
  const el = $(`.lee-cell[data-id="${c.id}"]`);
  if (el) paintCellMeta(el, c, +el.dataset.i);
}
window.leeCopyCellId = copyCellId;

/* The per-cell controls, from the same table the toolbar comes from. They act on the cell they are
 * drawn in rather than on the selected one, so ▶ on the third cell runs the third cell. */
const contextLabel = mode => ({keep: 'keep context', discard: 'discard first', auto: 'context auto'}[mode] || 'context auto');
function paintCellContext(button, c) {
  const mode = c.context_mode || 'auto';
  button.dataset.mode = mode; button.textContent = contextLabel(mode);
  button.title = mode === 'keep' ? 'keep this cell if notebook context is compacted'
    : mode === 'discard' ? 'discard this cell first if notebook context is compacted'
    : 'automatically choose if notebook context is compacted';
}
async function cycleCellContext(i) {
  const c = lee.cells[i]; if (!c) return;
  const modes = ['auto', 'keep', 'discard'], mode = modes[(modes.indexOf(c.context_mode || 'auto') + 1) % modes.length];
  const r = await nbEdit({op: 'context', i, mode}); if (!r) return;
  Object.assign(c, r.cells?.find(x => x.id === c.id));
  const button = $(`.lee-cell[data-i="${i}"] .lee-cell-context`); if (button) paintCellContext(button, c);
  status(`cell ${i + 1}: ${contextLabel(mode)}`, 'ok');
}
window.leeCellContext = cycleCellContext;
//: RISE writes `-` for a cell that continues the slide above, which is what no type means too.
const SLIDE_TYPES = ['none', 'slide', 'subslide', 'fragment', 'skip', 'notes'];
const SLIDE_TAGS = {slide: 'slide', subslide: 'sub', fragment: 'frag', skip: 'skip', notes: 'notes'};
const slideType = c => { const t = c.extra?.slideshow?.slide_type; return SLIDE_TYPES.includes(t) ? t : 'none'; };
function paintCellSlide(button, c) {
  const t = slideType(c), cell = button.closest('.lee-cell');
  button.dataset.type = t; button.textContent = SLIDE_TAGS[t] || 'slide';
  button.title = t === 'none' ? 'continues the slide above; click to start a slide' : `slide type: ${t}; click for the next type`;
  if (cell) cell.dataset.slide = t;
}
async function setCellSlide(indices, type) {
  const r = await nbEdit({op: 'slide', i: indices[0], indices, type});
  if (r?.cells) status(`${indices.length === 1 ? `cell ${indices[0] + 1}` : plural(indices.length, 'cell')}: ${type === 'none' ? 'no slide type' : type}`, 'ok');
}
function cycleCellSlide(i) {
  const c = lee.cells[i]; if (!c) return;
  return setCellSlide([i], SLIDE_TYPES[(SLIDE_TYPES.indexOf(slideType(c)) + 1) % SLIDE_TYPES.length]);
}
window.leeCellSlide = button => cycleCellSlide(+button.closest('.lee-cell').dataset.i)?.catch(e => status(String(e.message || e), 'err'));

function cellButtons(i) {
  const normal = (lee.bars.cell || []).map(b =>
    `<button class="lee-cbtn ${esc(b.kind)}" title="${esc(b.title)}" ` +
    `onclick="leeCellAct(${i}, '${esc(b.action)}')">${esc(b.label)}</button>`).join('');
  const debug = lee.cells[i]?.cell_type === 'code'
    ? `<button class="lee-cbtn" title="debug this cell (ipykernel)" onclick="leeDebugCell(${i})">◆</button>` : '';
  const more = `<button class="lee-cbtn" title="more cell actions" aria-label="more cell actions" ` +
    `onclick="leeCellMenu(${i}, this, event)">⋯</button>`;
  return debug + normal + more;
}
function leeCellAct(i, action) { selectCell(i); setScope('editor'); leeAct(action); }
function leeCellMenu(i, button, event) {
  event?.preventDefault(); event?.stopPropagation(); selectCell(i); setScope('editor');
  const r = button.getBoundingClientRect(); openMenu('cell', r.right - 4, r.bottom + 3);
}
window.leeCellAct = leeCellAct; window.leeCellMenu = leeCellMenu;

function cellEl(c, i) {
  const d = document.createElement('div');
  d.className = 'lee-cell ' + c.cell_type + (lee.collapsedCells.has(c.id) ? ' collapsed' : '') + (lee.headingHidden.has(c.id) ? ' heading-hidden' : '');
  d.dataset.i = i; d.dataset.id = c.id;
  d.style.setProperty('--lee-cell-lines', Math.min(20, Math.max(2, String(c.source || '').split('\n').length)));
  const state = cellState(c);
  d.innerHTML =
    `<div class="lee-gutter" draggable="true" title="drag to move cell">` +
    `<button class="lee-cell-fold" title="collapse cell" aria-label="collapse cell">${lee.collapsedCells.has(c.id) ? '+' : '−'}</button>` +
    (c.cell_type === 'markdown' ? `<button class="lee-heading-caret" aria-label="collapse or expand this section"></button>` : '') +
    `<div class="lee-execution-count" id="g-${esc(c.id)}">${gutterFor(c)}</div></div>` +
    `<div class="lee-cellmain"><div class="lee-cell-chrome">` +
    `<button class="lee-cell-meta" data-cell-id="${esc(c.id)}" title="${esc(cellMetaTitle(c, i))}" ` +
    `onclick="event.stopPropagation();leeCopyCellId(this)">` +
    `<span class="lee-cell-no">#${i + 1}</span>` +
    `<span class="lee-cell-size">${esc(cellKind(c))} · ${esc(plural(cellLines(c), 'line'))}</span>` +
    `<span class="lee-cell-id">${esc(c.id)}</span></button>` +
    `<span class="lee-cell-summary">${esc(String(c.source || '').trim().split('\n')[0] || 'empty cell')}</span>` +
    `<span class="lee-cell-state ${state}" id="state-${esc(c.id)}" ` +
    `title="${state === 'done' ? 'ran successfully in the current kernel' : state === 'error' ? 'run failed in the current kernel' : state === 'previous' ? 'saved output from a previous kernel; run to restore variables' : 'not run'}">${stateSvg(state)}</span>` +
    `<time class="lee-cell-time" id="time-${esc(c.id)}" title="last execution time" ` +
    `${c.execution_ms == null ? 'hidden' : ''}>${esc(formatCellTime(c.execution_ms))}</time>` +
    `<button class="lee-cell-context" data-mode="${esc(c.context_mode || 'auto')}" ` +
    `onclick="event.stopPropagation();leeCellContext(${i})">${esc(contextLabel(c.context_mode || 'auto'))}</button>` +
    `<button class="lee-cell-slide" onclick="event.stopPropagation();leeCellSlide(this)"></button>` +
    `<div class="lee-model-running" id="model-${esc(c.id)}" role="status" aria-live="polite" hidden>` +
    `<span class="lee-running-dot" aria-hidden="true">●</span>` +
    `<span class="lee-running-copy">Model is running</span>` +
    `<span class="lee-running-time"> · starting</span></div>` +
    `<div class="lee-cellbtns">${cellButtons(i)}</div></div>` +
    `${c.cell_type === 'markdown' ? mdCellHost(c) + '<button class="lee-heading-badge" hidden></button>' : ''}<div class="lee-cm" id="cm-${esc(c.id)}"></div><div id="out-${esc(c.id)}"></div>` +
    `${isExercise(c) ? `<div class="lee-exercise" id="ex-${esc(c.id)}" data-guide-id="check"></div>` : ''}</div>`;
  paintCellSlide($('.lee-cell-slide', d), c);
  if (c.cell_type === 'markdown') {
    d.tabIndex = -1; paintMarkdownCell(d, c);
    d.querySelector('.lee-md-cell').addEventListener('dblclick', () => editMarkdownCell(+d.dataset.i));
    d.querySelector('.lee-heading-caret').onclick = e => { e.stopPropagation(); toggleHeading(+d.dataset.i); };
    d.querySelector('.lee-heading-badge').onclick = e => { e.stopPropagation(); setHeadings([+d.dataset.i], false); };
  }
  d.addEventListener('mousedown', e => { selectCell(+d.dataset.i, e.shiftKey); setScope('editor'); });
  d.querySelector('.lee-cell-fold').onclick = e => { e.stopPropagation(); setCellCollapsed(+d.dataset.i); };
  const gutter = d.querySelector('.lee-gutter');
  gutter.addEventListener('dragstart', e => {
    if (!lee.cellSelection.has(+d.dataset.i)) selectCell(+d.dataset.i);
    e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/lee-cell', d.dataset.i);
    e.dataTransfer.setData('text/lee-cells', JSON.stringify([...lee.cellSelection].sort((a,b) => a-b)));
    d.classList.add('dragging');
  });
  gutter.addEventListener('dragend', () => {
    d.classList.remove('dragging'); $$('.lee-cell.drag-target').forEach(x => x.classList.remove('drag-target'));
  });
  d.addEventListener('dragover', e => {
    if (!e.dataTransfer.types.includes('text/lee-cell')) return;
    e.preventDefault(); e.dataTransfer.dropEffect = 'move'; d.classList.add('drag-target');
  });
  d.addEventListener('dragleave', () => d.classList.remove('drag-target'));
  d.addEventListener('drop', e => {
    const from = Number(e.dataTransfer.getData('text/lee-cell'));
    if (!Number.isInteger(from)) return;
    let indices = [from]; try { indices = JSON.parse(e.dataTransfer.getData('text/lee-cells') || `[${from}]`); } catch (_) {}
    e.preventDefault(); d.classList.remove('drag-target');
    if (indices.length > 1) moveCellsTo(indices, +d.dataset.i); else moveCellTo(from, +d.dataset.i);
  });
  if (c.extra?.lesson) paintLessonCell(d, c);
  paintGuideButton(d, c);
  if (isExercise(c)) renderExercise(c, d);
  return d;
}

function setCellCollapsed(i, value = null) {
  const c = lee.cells[i]; if (!c) return;
  const collapsed = value === null ? !lee.collapsedCells.has(c.id) : value;
  if (collapsed) lee.collapsedCells.add(c.id); else lee.collapsedCells.delete(c.id);
  const el = $(`.lee-cell[data-i="${i}"]`); el?.classList.toggle('collapsed', collapsed);
  const button = el?.querySelector('.lee-cell-fold'); if (button) button.textContent = collapsed ? '+' : '−';
}

/* A heading cell is a markdown cell whose first line is a heading, and JupyterLab's
   `heading_collapsed` is its fold. What a fold hides is worked out from the headings every time
   and never stored. The same rules as `heading_level` and `section_end` in `nb.py`. */
const headingLevel = c => c?.cell_type === 'markdown' ? (/^(#{1,6})[ \t]+\S/.exec(String(c.source || ''))?.[1].length || 0) : 0;
const headingFolded = c => !!(headingLevel(c) && c.extra?.heading_collapsed);
function sectionEnd(cells, i) {
  const lv = headingLevel(cells[i]); let j = i + 1;
  while (j < cells.length && !(headingLevel(cells[j]) && headingLevel(cells[j]) <= lv)) j++;
  return j;
}
function hiddenCells(cells = lee.cells) {
  const out = new Set();
  for (let i = 0; i < cells.length;) {
    if (!headingFolded(cells[i])) { i++; continue; }
    const e = sectionEnd(cells, i);
    for (let j = i + 1; j < e; j++) out.add(j);
    i = e;
  }
  return out;
}
const hiddenIds = cells => new Set([...hiddenCells(cells)].map(i => cells[i].id));
function headingAncestors(i, cells = lee.cells) {
  let bound = headingLevel(cells[i]) || 7; const out = [];
  for (let j = i - 1; j >= 0; j--) { const lv = headingLevel(cells[j]); if (lv && lv < bound) { out.push(j); bound = lv; } }
  return out;
}
//: The next shown cell from `i` in direction `step`, or -1.
function visibleCell(i, step) {
  const hid = hiddenCells();
  for (let j = i + step; j >= 0 && j < lee.cells.length; j += step) if (!hid.has(j)) return j;
  return -1;
}
//: `i`, or the shown cell above it, which is the folded heading hiding it.
function shownAt(i) { const hid = hiddenCells(); while (i > 0 && hid.has(i)) i--; return i; }
//: Where a cell inserted below `i` goes: after a folded heading's section, not into it.
const belowAt = i => headingFolded(lee.cells[i]) ? sectionEnd(lee.cells, i) : i + 1;
function paintHeadings(cells = lee.cells) {
  const hid = hiddenCells(cells);
  lee.headingHidden = new Set([...hid].map(i => cells[i].id));
  $$('#editor .lee-cell').forEach(el => {
    const i = +el.dataset.i, c = cells[i]; if (!c) return;
    const folded = headingFolded(c);
    el.classList.toggle('heading-hidden', hid.has(i));
    el.classList.toggle('heading', !!headingLevel(c)); el.classList.toggle('heading-collapsed', folded);
    const caret = $('.lee-heading-caret', el);
    if (caret) { caret.textContent = folded ? '▸' : '▾'; caret.title = folded ? 'expand this section' : 'collapse this section'; }
    const badge = $('.lee-heading-badge', el); if (!badge) return;
    badge.hidden = !folded;
    if (folded) { badge.textContent = `${plural(sectionEnd(cells, i) - i - 1, 'cell')} hidden`; badge.title = 'expand this section'; }
  });
  $$('#editor .lee-toc-fold').forEach(b => { b.textContent = headingFolded(cells[+b.dataset.i]) ? '+' : '−'; });
  queueNotebookOverview();
}
/* Folds or unfolds heading cells, every one when `indices` is null. Painted here at once and
   written behind by cell id to this tab's notebook, chained per tab so its `nbEdit` and `saveTab` see
   the write land first. Not an undo step. `lee.headingFolds` keeps each fold, with the notebook version
   its write made once it lands, for `foldsSince`. */
function setHeadings(indices, collapsed) {
  const idx = (indices ?? lee.cells.map((_, i) => i)).filter(i => {
    const c = lee.cells[i]; return c && (collapsed ? headingLevel(c) && !c.extra?.heading_collapsed : c.extra?.heading_collapsed);
  });
  if (!idx.length) return;
  for (const i of idx) {
    const c = lee.cells[i]; c.extra = {...c.extra};
    if (collapsed) c.extra.heading_collapsed = true; else delete c.extra.heading_collapsed;
  }
  paintHeadings();
  const key = lee.tabKey, ids = idx.map(i => lee.cells[i].id), fold = {collapsed};
  const folds = lee.headingFolds.get(key) || lee.headingFolds.set(key, new Map()).get(key);
  for (const id of ids) folds.set(id, fold);
  lee.headingSync.set(key, headingSynced(key).then(() => post('/nb/edit', {op: 'heading', collapsed, ids, path: key}))
    .then(r => { fold.version = r.version; })
    .catch(e => { for (const id of ids) if (folds.get(id) === fold) folds.delete(id); status(String(e.message || e), 'err'); }));
  markDirty();
  if (collapsed && hiddenCells().has(lee.sel)) focusCell(shownAt(lee.sel));
}
//: Puts back on `cells`, tab `key`'s notebook at `version`, each fold it cannot hold yet; forgets the folds it holds.
function foldsSince(key, cells, version) {
  const folds = lee.headingFolds.get(key); if (!folds) return cells;
  for (const c of cells) {
    const f = folds.get(c.id); if (!f) continue;
    if (f.version && f.version <= version) { folds.delete(c.id); continue; }
    c.extra = {...c.extra};
    if (f.collapsed && headingLevel(c)) c.extra.heading_collapsed = true; else delete c.extra.heading_collapsed;
  }
  return cells;
}
//: A heading cell folds itself; any other cell folds the section it sits in.
function toggleHeading(i) {
  const h = headingLevel(lee.cells[i]) ? i : headingAncestors(i)[0];
  if (h == null) return status('this cell is under no heading', 'err');
  setHeadings([h], !headingFolded(lee.cells[h]));
}
function unfoldTo(i) {
  if (hiddenCells().has(i)) setHeadings(headingAncestors(i).filter(j => headingFolded(lee.cells[j])), false);
}

function cellClipboardPayload(i) {
  const cell = lee.cells[i]; if (!cell || lee.kind !== 'notebook') return null;
  const view = lee.editors.get(cell.id);
  const payload = JSON.parse(JSON.stringify(cell));
  if (view) payload.source = LeeCM.getDoc(view);
  payload.running = false; payload.fresh = false;
  return payload;
}
function selectedCellIndices(fallback = lee.sel) {
  return [...(lee.cellSelection.size ? lee.cellSelection : new Set([fallback]))].filter(i => i >= 0 && i < lee.cells.length).sort((a,b) => a-b);
}
function copyCell(i) {
  const indices = selectedCellIndices(i), cells = indices.map(cellClipboardPayload).filter(Boolean);
  if (!cells.length) return status('select notebook cells to copy', 'err');
  lee.cellClipboard = {cells, cell: cells[0], from: lee.path || lee.tabKey || 'scratch'};
  status(`${cells.length} cell${cells.length === 1 ? '' : 's'} copied — open another notebook and paste`, 'ok');
}
async function cutCell(i) {
  const indices = selectedCellIndices(i), cells = indices.map(cellClipboardPayload).filter(Boolean);
  if (!cells.length) return status('select notebook cells to cut', 'err');
  lee.cellClipboard = {cells, cell: cells[0], from: lee.path || lee.tabKey || 'scratch'};
  if (!await nbEdit({op: 'delete_many', i: indices[0], indices})) return;
  focusCell(shownAt(Math.min(indices[0], lee.cells.length - 1)));
  status(`${cells.length} cell${cells.length === 1 ? '' : 's'} cut`, 'ok');
}
async function pasteCell(i) {
  if (lee.kind !== 'notebook') return status('cells can only be pasted into a notebook', 'err');
  const cells = lee.cellClipboard?.cells || (lee.cellClipboard?.cell ? [lee.cellClipboard.cell] : []);
  if (!cells.length) return status('copy or cut cells first', 'err');
  const at = Math.max(0, Math.min(i, lee.cells.length));
  if (!await nbEdit({op: 'paste_many', i: at, cells})) return;
  focusCell(at); lee.cellSelection = new Set(cells.map((_, n) => at + n)); paintSel();
  status(`${cells.length} cell${cells.length === 1 ? '' : 's'} pasted from ${compactPath(lee.cellClipboard.from)}`, 'ok');
}

async function moveCellsTo(indices, to) {
  indices = [...new Set(indices)].sort((a,b) => a-b);
  const r = await nbEdit({op: 'move_many', i: indices[0], indices, target: to}); if (!r) return;
  const at = r.index ?? to; focusCell(at); lee.cellSelection = new Set(indices.map((_, n) => at + n));
  paintSel(); status(`${indices.length} cells moved`, 'ok');
}

async function moveCellTo(from, to) {
  const last = lee.cells.length - 1;
  to = Math.max(0, Math.min(to, last));
  if (from === to || from < 0 || from > last) return focusCell(from);
  // Dragged, a folded heading takes its section along. Stepped, the server moves it a block at a time.
  const end = headingFolded(lee.cells[from]) ? sectionEnd(lee.cells, from) : from + 1;
  if (end > from + 1 && Math.abs(to - from) > 1) {
    if (to > from && to < end) return focusCell(from);
    return moveCellsTo(Array.from({length: end - from}, (_, n) => from + n), to > from ? to + 1 : to);
  }
  const r = await nbEdit({op: 'move', i: from, d: to - from}); if (!r) return;
  const at = r.index ?? to; focusCell(at);
  status(at === from ? 'nothing to move past' : `cell moved to ${at + 1}`, at === from ? 'info' : 'ok');
}

function mountCell(c, i) {
  if (lee.editors.has(c.id)) return;
  const key = `${lee.tabKey}:${c.id}`;
  // Only a docChanged transaction marks a buffer authoritative. A stale empty cache must never
  // replace the non-empty source `/tab/state` returned after running a cell.
  const source = lee.dirtyBuffers.has(key) ? lee.buffers.get(key) : c.source;
  c.source = source;
  const v = createEditor($('#cm-' + c.id), {
    doc: source, lang: c.cell_type === 'code' ? nbLang() : c.cell_type === 'markdown' ? 'markdown' : '',
    placeholder: c.cell_type === 'prompt' ? `ask the inline model — ${displayChord('mod+enter')} answers in place`
      : c.cell_type === 'markdown' && c.extra?.lesson?.role === 'prediction' ? 'Your guess: what will the code below print?' : '',
    completeUrl: c.cell_type === 'code' ? '/complete' : null,
    lintPath: lee.path || 'scratch.ipynb',
    onDefinition: c.cell_type === 'code' ? name => findDefinition(name) : null,
    breakpoints: lee.breakpoints.get(c.id) || [],
    // Line numbers relative to this cell. A cell mounted after the marks arrived would otherwise
    // stay unmarked until the next save.
    changedLines: (lee.notebookGit?.lines || {})[c.id] || [],
    onBreakpoint: c.cell_type === 'code' ? lines => rememberBreakpoints(c.id, lines) : null,
    settings: {overviewMode:'off'}, tableKeys: true,
    onSelection: () => { clearTimeout(selectionHelpTimer); selectionHelpTimer = setTimeout(showSelectionHelp, 120); },
    onChange: (txt) => {
      const at = lee.cells.findIndex(cell => cell.id === c.id); if (at < 0) return;
      const level = headingLevel(lee.cells[at]);
      lee.cells[at].source = txt;
      rememberBuffer(key, {path: lee.path, title: lee.tabKey, kind: 'notebook', i: at, id: c.id, text: txt});
      if (cellState(lee.cells[at]) !== 'idle') setCellState(lee.cells[at], 'stale', 'code changed since the last run');
      if (lee.cells[at].extra?.lesson) renderLessonReveal(lee.cells[at]);
      if (isExercise(lee.cells[at])) { lee.cells[at].graded_current = false; renderExercise(lee.cells[at]); }
      if (headingLevel(lee.cells[at]) !== level) paintHeadings();
      markDirty();
    },
  });
  lee.editors.set(c.id, v);
  $('#cm-' + c.id).addEventListener('focusin', () => {
    const at = lee.cells.findIndex(cell => cell.id === c.id);
    if (at >= 0) { lee.activeEditor='primary'; lee.sel = at; setScope('editor'); paintSel(); }
  });
  renderOutputs(c);
  if (c.extra?.lesson) renderLessonReveal(c);
  if (c.running) {
    const el = $(`.lee-cell[data-i="${i}"]`); el?.classList.add('running');
    setCellState(c, 'running', 'still running in the background');
    setCellTime(c, 0, true);
    if (c.cell_type === 'prompt') {
      const notice = $('#model-' + c.id);
      if (notice) { notice.hidden = false; notice.querySelector('.lee-running-time').textContent = ' · in background'; }
    }
  }
}

/* A markdown cell is read rendered and edited on demand. Its editor stays mounted and hidden, so the
   buffer, undo and save are the ones every other cell has. `data-md-edit` marks the editing ones. */
const mdEditing = new Set();
const mdSource = c => { const v = lee.editors.get(c.id); return v ? LeeCM.getDoc(v) : String(c.source || ''); };
const nbBase = () => (lee.path || '').slice(0, (lee.path || '').lastIndexOf('/'));
const mdAttached = c => el => $$('img[src^="attachment:"]', el).forEach(img => {
  const a = c.attachments?.[img.getAttribute('src').slice(11)], t = a && Object.keys(a)[0];
  if (t) img.src = `data:${t};base64,${[].concat(a[t]).join('')}`;
});
//: What a notebook markdown surface runs after each render; `c` is null on a slide that keeps no cache.
const mdPaint = (c, cached = true) => (el, src) => { if (c) mdAttached(c)(el); const k = cached && c; rupakaFences(el, k ? `md:${c.id}` : null, k ? src : null, k ? lessonRestore(c.id, src) : null); };
const mdCellHost = c => `<div class="lee-md-cell lee-md" id="mdr-${esc(c.id)}" title="double-click to edit · ${esc(displayChord('enter'))}"></div>`;
const mdCellOf = i => $(`.lee-cell[data-i="${i}"]`);
function paintMarkdownCell(el, c, now = false) {
  const host = $('.lee-md-cell', el); if (!host) return;
  const src = mdSource(c);
  el.toggleAttribute('data-md-edit', mdEditing.has(c.id));
  host.classList.toggle('empty', !src.trim());
  host.dataset.mdBase = nbBase();
  if (now) { host.dataset.markdown = src; flushMarkdown(host, true, mdPaint(c)); } else renderMarkdown(host, src, true, mdPaint(c));
}
function editMarkdownCell(i) {
  const c = lee.cells[i], el = mdCellOf(i); if (c?.cell_type !== 'markdown' || !el) return;
  mdEditing.add(c.id); el.setAttribute('data-md-edit', '');
  const v = ensureCellMounted(i);
  requestAnimationFrame(() => { v.dispatch({selection: {anchor: v.state.doc.length}}); LeeCM.focus(v); v.requestMeasure(); });
}
function showRenderedMarkdown(c, refocus = false) {
  if (c?.cell_type !== 'markdown') return;
  const el = $(`.lee-cell[data-id="${c.id}"]`); if (!el) return;
  const hadFocus = el.contains(document.activeElement);
  mdEditing.delete(c.id); paintMarkdownCell(el, c, true);
  if (hadFocus || refocus) el.focus({preventScroll: true});
}
function leaveOtherMarkdownEdits(keep) {
  const stay = lee.cells[keep]?.id;
  for (const id of [...mdEditing]) if (id !== stay) showRenderedMarkdown(lee.cells.find(c => c.id === id));
}
// A cell with nothing in it starts in the editor, which is how a new markdown cell arrives.
function focusRenderedMarkdown(i) {
  const c = lee.cells[i]; if (c?.cell_type !== 'markdown') return false;
  if (!mdSource(c).trim() && !mdEditing.has(c.id)) editMarkdownCell(i);
  if (mdEditing.has(c.id)) return false;
  mdCellOf(i)?.focus({preventScroll: true}); return true;
}
const MD_KEYS = {
  cell_edit: e => { const el = e.target.closest?.('.lee-cell.markdown');
    return !!el && !el.hasAttribute('data-md-edit') && !isTextEntry(keyTarget(e)) && !keyTarget(e).closest?.('button, a, summary'); },
  // A markdown cell renders; a code cell's editor lets go, so the cell is in command mode.
  cell_render: e => { const el = e.target.closest?.('.lee-cell'), v = el && lee.editors.get(el.dataset.id);
    return !!el && (el.classList.contains('markdown') ? el.hasAttribute('data-md-edit') : !$('.lee-inline-popover')) &&
      inCellEditor(e) && !el.querySelector('.cm-panel') && !(v && LeeCM.holdsEscape(v)); },
};

function renderOutputs(c) {
  const box = $('#out-' + c.id); if (!box) return;
  $$('[data-markdown]', box).forEach(el => {
    if (el._leeCodeFrame) cancelAnimationFrame(el._leeCodeFrame);
    for (const v of (el._leeCodeViews || [])) try { LeeCM.destroy(v); } catch {}
  });
  widgetDetach(c);
  const rkPass = rupakaPass(`out:${c.id}`);
  box.innerHTML = '';
  // A prompt cell's "output" is the answer, stored in the cell rather than in an nbformat output,
  // so it renders from its own fields.
  if (c.cell_type === 'prompt') {
    if ((c.calls || []).length) {
      const steps = document.createElement('div'); steps.className = 'lee-agent-steps lee-cell-agent-steps';
      for (const activity of c.calls) {
        const row = document.createElement('details'); renderAgentStep(row, activity); steps.appendChild(row);
      }
      box.appendChild(steps);
    }
    if (c.reply) {
      const reply = document.createElement('div');
      reply.className = 'lee-reply'; box.appendChild(reply);
      renderMarkdown(reply, (c.calls || []).length ? stripWorkLog(c.reply) : c.reply);
      const usage = usageMeta(c.usage, '', c.usage?.model); if (usage) box.appendChild(usage);
    }
    // pictures and video the turn generated do arrive as nbformat outputs, and draw as any other
    (c.outputs || []).forEach((o, i) => box.appendChild(outputEl(o, c, i)));
    rupakaSweep(rkPass);
    return widgetSweep(c);
  }
  (c.outputs || []).forEach((o, i) => box.appendChild(outputEl(o, c, i)));
  rupakaSweep(rkPass);
  widgetSweep(c);
}

const stripAnsi = (s) => String(s).replace(/\x1b\[[0-9;]*m/g, '');
const MAX_OUTPUT_CHARS = 60000;
function outputText(el, value) {
  const text = String(value || '');
  if (text.length <= MAX_OUTPUT_CHARS) { el.textContent = text; return; }
  el.textContent = text.slice(0, MAX_OUTPUT_CHARS);
  const folded = document.createElement('button');
  folded.className = 'lee-output-fold';
  folded.textContent = `show ${(text.length - MAX_OUTPUT_CHARS).toLocaleString()} more characters`;
  folded.title = 'Large outputs are folded to keep the notebook responsive';
  folded.onclick = () => { el.textContent = text; };
  el.appendChild(folded);
}

function closeInlinePopover() { $('.lee-inline-popover')?.remove(); }
function valueLensMeta(item) {
  return [item.type && item.type !== 'result' ? item.type : '', item.shape ? `shape ${item.shape}` : '',
          item.dtype ? `dtype ${item.dtype}` : ''].filter(Boolean).join(' · ') || 'runtime value';
}
function openValueLens(item, anchor, label = '') {
  if (!item || lee.present) return;
  closeInlinePopover();
  const p = document.createElement('aside');
  p.className = 'lee-inline-popover lee-value-lens'; p.setAttribute('role', 'dialog');
  p.setAttribute('aria-label', `${label || item.name || 'result'} runtime value`);
  p.innerHTML = `<div class="lee-inline-head"><strong>${esc(label || item.path || item.name || 'result')}</strong>` +
    `<span>${esc(valueLensMeta(item))}</span><button class="lee-icon" aria-label="close">×</button></div>` +
    `<div class="lee-value-tree"></div><div class="lee-inline-actions">` +
    `<button class="lee-btn" data-copy>copy value</button>` +
    (item.accessor?.length && item.accessor[0] !== '_' ? `<button class="lee-btn" data-variables>variables</button>` : '') + `</div>`;
  const tree = $('.lee-value-tree', p);
  const row = (value, depth = 0) => {
    const shell = document.createElement('div'); shell.className = 'lee-value-node';
    const button = document.createElement('button'); button.className = 'lee-value-row';
    button.style.setProperty('--depth', depth);
    button.innerHTML = `<span class="lee-value-caret">${value.is_container ? '›' : ''}</span>` +
      `<strong>${esc(value.name || 'result')}</strong><small>${esc(value.type || '')}</small>` +
      `<span>${esc(value.value || '')}</span>`;
    shell.appendChild(button);
    if (value.is_container && value.accessor?.length) {
      const kids = document.createElement('div'); kids.className = 'lee-value-kids'; kids.hidden = true; shell.appendChild(kids);
      let open = false, loaded = false;
      button.onclick = async () => {
        open = !open; button.classList.toggle('open', open); kids.hidden = !open;
        if (!open || loaded) return;
        kids.innerHTML = '<div class="lee-value-loading">reading children…</div>';
        try {
          const acc = encodeURIComponent(JSON.stringify(value.accessor));
          const values = await api(`/vars/expand?accessor=${acc}&scope=${lee.execScope}`);
          kids.innerHTML = ''; values.forEach(child => kids.appendChild(row(child, depth + 1)));
          if (!values.length) kids.innerHTML = '<div class="lee-value-loading">no children</div>';
          loaded = true;
        } catch (e) { kids.innerHTML = `<div class="lee-value-error">${esc(e.message || e)}</div>`; }
      };
    }
    return shell;
  };
  tree.appendChild(row(item)); document.body.appendChild(p);
  const a = anchor?.getBoundingClientRect() || {left: innerWidth / 2, right: innerWidth / 2, top: innerHeight / 2, bottom: innerHeight / 2};
  const r = p.getBoundingClientRect(), below = a.bottom + 6;
  p.style.left = Math.max(8, Math.min(a.right - r.width, innerWidth - r.width - 8)) + 'px';
  p.style.top = (below + r.height < innerHeight - 8 ? below : Math.max(8, a.top - r.height - 6)) + 'px';
  $('[aria-label="close"]', p).onclick = closeInlinePopover;
  $('[data-copy]', p).onclick = () => { navigator.clipboard?.writeText(item.value || ''); status('value copied', 'ok'); };
  const show = $('[data-variables]', p);
  if (show) show.onclick = async () => {
    closeInlinePopover(); leePane('right', true); leeRight('vars'); await leeVars(); setScope('vars');
    const found = $$('#vars .lee-vrow').find(r => r.dataset.name === item.name);
    if (found) { selectVar(found); found.scrollIntoView({block: 'nearest'}); }
  };
}
window.openValueLens = openValueLens;
window.addEventListener('lee-inline-open', e => openValueLens(e.detail?.item, e.detail?.anchor));
document.addEventListener('pointerdown', e => {
  if ($('.lee-inline-popover') && !e.target.closest('.lee-inline-popover, .cm-lee-inline-value')) closeInlinePopover();
}, true);
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !lee.present) closeInlinePopover(); }, true);

function outputTone(o) {
  if (o.output_type === 'error') return 'error';
  if (o.output_type === 'stream' && o.name === 'stderr')
    return /\b(?:warning|warns?|deprecated|deprecation)\b/i.test(String(o.text || '')) ? 'warning' : 'log';
  if (o.output_type === 'execute_result' || o.output_type === 'display_data') return 'result';
  return 'output';
}
const PLOTLY_JS = 'https://cdn.plot.ly/plotly-4.1.1.min.js';
const PLOTLY_MIME = 'application/vnd.plotly.v1+json';
function sandboxFrame(d, srcdoc, height) {
  const f = document.createElement('iframe'); f.className = 'lee-out-frame';
  f.setAttribute('sandbox', 'allow-scripts'); f.srcdoc = srcdoc;
  f.style.cssText = `width:100%;height:${height}px;border:0;resize:vertical;overflow:auto;display:block`;
  d.classList.add('lee-out-media'); d.appendChild(f); return d;
}
function plotlyFrame(d, fig) {
  const json = JSON.stringify({data: fig.data || [], layout: fig.layout || {}, config: fig.config || {}}).replace(/</g, '\\u003c');
  const h = +(fig.layout && fig.layout.height) || 450;
  return sandboxFrame(d, `<!doctype html><meta charset="utf-8"><body style="margin:0"><div id="p" style="width:100%;height:100vh"></div>` +
    `<script src="${PLOTLY_JS}" onerror="document.getElementById('p').innerHTML=` +
    `'<p style=&quot;font:13px sans-serif;color:#888;padding:1em&quot;>plotly.js could not load, so this chart cannot be drawn offline</p>'"><\/script>` +
    `<script>const f = ${json}; if (window.Plotly) Plotly.newPlot('p', f.data, Object.assign({}, f.layout, {autosize: true, width: undefined, height: undefined}), Object.assign({responsive: true}, f.config));<\/script>`, h);
}
//: A rupaka output is drawn here, so the `text/html` fallback `rupaka.show` sends beside it never reaches a frame.
function rupakaEl(d, raw, pass, i) {
  const text = typeof raw === 'string' ? raw : JSON.stringify(raw);
  const fail = err => d.append(rupakaErr(err), Object.assign(document.createElement('pre'), {textContent: text}));
  let spec; try { spec = JSON.parse(text); } catch (err) { fail(err); return d; }
  d.classList.add('lee-out-media');
  const e = rupakaDraw(spec, pass && `${pass.owner}:${i}:${text.length}:${text}`, pass);
  if (e.err) fail(e.err); else d.append(e.host);
  if (!e.ok && !e.err) e.done.then(() => { if (e.err) { e.host.remove(); fail(e.err); } rupakaRendered(d); });
  return d;
}
//: Rich output markup that runs no script and sends no request to Leela: allowlisted HTML, SVG and MathML, no handlers, links only to other sites, images also as `data:`, and no Leela class names.
const RICH_TAGS = new Set(('a abbr address article aside b bdi bdo blockquote br caption center cite code col colgroup data dd del details dfn div dl dt em figcaption figure font footer h1 h2 h3 h4 h5 h6 header hr i img input ins kbd label legend li main mark meter nav ol p picture pre progress q rp rt ruby s samp section small source span strike strong style sub summary sup table tbody td tfoot th thead time tr tt u ul var wbr video audio ' +
  'svg g defs symbol use path rect circle ellipse line polyline polygon text tspan textpath title desc metadata clippath mask pattern marker image lineargradient radialgradient stop filter foreignobject switch ' +
  'feblend fecolormatrix fecomponenttransfer fecomposite feconvolvematrix fediffuselighting fedisplacementmap fedistantlight fedropshadow feflood fefunca fefuncb fefuncg fefuncr fegaussianblur femerge femergenode femorphology feoffset fepointlight fespecularlighting fespotlight fetile feturbulence ' +
  'math semantics annotation annotation-xml mrow mi mo mn ms mtext mspace msup msub msubsup munder mover munderover mfrac msqrt mroot mtable mtr mtd mlabeledtr mstyle mpadded mphantom menclose merror mfenced mmultiscripts mprescripts none').split(' '));
const RICH_ATTR_GONE = new Set('srcdoc srcset is formaction formtarget form name action attributename popover popovertarget popovertargetaction commandfor command interestfor autofocus accesskey ping background codebase longdesc lowsrc dynsrc'.split(' '));
const RICH_OURS = /^(lee-|cm-|xterm|rk|stage-)/;
const RICH_GONE = new Set('script iframe frame frameset object embed applet noscript noembed noframes template textarea select xmp button form base meta link set animate animatemotion animatetransform discard portal dialog slot'.split(' '));
const RICH_MEDIA = /^data:(image\/(png|jpe?g|gif|webp|avif|svg\+xml)|video\/(mp4|webm|ogg)|audio\/(mpeg|mp4|wav|ogg|webm));base64,/i;
//: Whether URL `v` on attribute `n` of `tag` may stay: `#…` inside the output, `data:` media where it is drawn, a link or an image on a site that is not this computer.
function richUrl(tag, n, v) {
  const u = v.replace(/[\x00-\x20\x7f-\x9f]+/g, '');
  if (u.startsWith('#')) return true;
  const media = n === 'src' && ['img', 'video', 'audio', 'source'].includes(tag) || n === 'href' && tag === 'image';
  if (/^data:/i.test(u)) return media && RICH_MEDIA.test(u);
  if (tag === 'a' && n === 'href') return /^mailto:/i.test(u) || richSite(u);
  return (tag === 'img' && n === 'src' || tag === 'image' && n === 'href') && richSite(u);
}
function richSite(u) {
  let url; try { url = new URL(u, location.href); } catch (_) { return false; }
  const h = url.hostname.replace(/^\[|\]$/g, '').toLowerCase();
  return /^https?:$/.test(url.protocol) && url.origin !== location.origin && !/^(localhost|127\.\d+\.\d+\.\d+|::1|0\.0\.0\.0)$|\.localhost$/.test(h);
}
//: CSS with no request in it: no `@import`, and no `url()` or `image-set()` but an in-output `#` reference or a `data:` image.
function richCss(css) {
  css = String(css).replace(/\\([0-9a-f]{1,6})\s?/gi, (_, h) => String.fromCodePoint(Math.min(parseInt(h, 16), 0x10ffff) || 0xfffd)).replace(/\\(.)/g, '$1');
  return css.replace(/@import[^;]*;?/gi, '').replace(/(-webkit-)?image-set\s*\(/gi, 'none(')
    .replace(/url\s*\(\s*(['"]?)([^)]*)\)/gi, (m, q, v) => /^#|^data:image\/(png|jpe?g|gif|webp|avif|svg\+xml);base64,/i.test(v.replace(/['"\s]/g, '')) ? m : 'none');
}
//: Clean the children of `root` in place.
function richWalk(root) {
  for (const el of [...root.children]) {
    const tag = el.localName.toLowerCase();
    if (RICH_GONE.has(tag)) { el.remove(); continue; }
    if (!RICH_TAGS.has(tag)) { richWalk(el); el.replaceWith(...el.childNodes); continue; }
    if (tag === 'input' && (el.getAttribute('type') || '').toLowerCase() !== 'checkbox') { el.remove(); continue; }
    for (const a of [...el.attributes]) {
      const n = a.localName.toLowerCase();
      if (n.startsWith('on') || RICH_ATTR_GONE.has(n) || (['href', 'src', 'poster', 'data', 'cite'].includes(n) && !richUrl(tag, n, a.value))) el.removeAttributeNode(a);
      else if (n === 'style') a.value = richCss(a.value);
      else if (n === 'class') a.value = a.value.split(/\s+/).filter(c => c && !RICH_OURS.test(c)).join(' ');
      else if (/url\s*\(/i.test(a.value) && !/^\s*url\s*\(\s*#[^)]*\)\s*$/i.test(a.value)) el.removeAttributeNode(a);
    }
    if (tag === 'style') el.textContent = richCss(el.textContent);
    if (tag === 'input') el.setAttribute('disabled', '');
    if (tag === 'a') { el.setAttribute('target', '_blank'); el.setAttribute('rel', 'noopener noreferrer'); }
    richWalk(el);
  }
}
//: `html` as a clean fragment. Parsed in a `<template>`, so nothing in it loads or runs before the walk.
function richHtml(html) {
  const t = document.createElement('template'); t.innerHTML = html;
  richWalk(t.content);
  return document.importNode(t.content, true);
}
//: `html` as clean markup for code that sets `innerHTML` on a `div`: parsed as that `div` parses it, in a document with no window, until it reads back the same; empty when it never does.
function richString(html) {
  const d = (richString.doc ||= document.implementation.createHTMLDocument('')).createElement('div');
  let s = String(html ?? '');
  for (let i = 0; i < 4; i++) { d.innerHTML = s; richWalk(d); if (d.innerHTML === s) return s; s = d.innerHTML; }
  return '';
}
//: A mime value as text: a saved notebook may keep it as a list of lines.
const mimeText = v => Array.isArray(v) ? v.join('') : typeof v === 'string' ? v : null;
function outputEl(o, c = null, i = 0) {
  const d = document.createElement('div');
  const tone = outputTone(o);
  d.className = `lee-out ${tone}`;
  if (o.output_type === 'stream') { outputText(d, o.text); return d; }
  if (o.output_type === 'error') {
    outputText(d, stripAnsi((o.traceback || []).join('\n')) || `${o.ename}: ${o.evalue}`);
    if (o.ename === 'ShellStopped') {
      const b = document.createElement('button');
      b.className = 'lee-btn'; b.dataset.restartKernel = ''; b.textContent = 'Restart kernel'; b.onclick = () => restartKernel();
      d.appendChild(b);
    }
    return d;
  }
  const data = o.data || {};
  if (data[WIDGET_MIME] != null) return widgetEl(o, c, i);
  if (data[RUPAKA_MIME] != null) return rupakaEl(d, data[RUPAKA_MIME], c?.id && rupaka.passes.get(`out:${c.id}`), i);
  if (data[PLOTLY_MIME] != null) return plotlyFrame(d, data[PLOTLY_MIME]);
  if (data['image/png']) {
    const i = document.createElement('img'), m = o.metadata?.['image/png'] || {};
    i.src = 'data:image/png;base64,' + mimeText(data['image/png']);
    // A retina figure's width and height are half its pixels.
    if (m.width) i.width = m.width;
    if (m.height) i.height = m.height;
    d.classList.add('lee-out-media'); d.appendChild(i); return d;
  }
  // Presence, not truthiness. Clearing a rich display is publishing an empty one of the same type:
  // fastprogress ends a progress bar with `HTML('')`, and testing the string sent that output down
  // to its `text/plain`, which for any rich object is the placeholder `<... object>` repr.
  const html = mimeText(data['text/html']), svgText = mimeText(data['image/svg+xml']), rich = html ?? svgText;
  if (html != null && /<script[\s/>]/i.test(html)) return sandboxFrame(d, html, 450);
  const svg = html == null && svgText != null;
  if (svg) d.classList.add('lee-out-media');
  if (rich != null) {
    // Rich reprs get their own shadow root: pandas ships a <style> block with every DataFrame and
    // `scoped` has been dead for years, so an output could restyle the IDE around it. Very large
    // HTML stays unparsed until requested, because parsing a multi-megabyte table on the main
    // thread triggers Chrome's hang dialog.
    // The shadow host sits inside `d`, which contains its paint: a `:host` or `position: fixed` rule cannot cover the IDE.
    const show = () => {
      d.textContent = ''; d.style.contain = 'paint';
      const r = d.appendChild(Object.assign(document.createElement('div'), {className: 'lee-out-rich'})).attachShadow({mode: 'open'});
      if (svg) r.append(Object.assign(document.createElement('style'), {textContent: 'svg{display:block;max-width:100%;height:auto}'}));
      r.append(richHtml(rich));
    };
    if (rich.length > MAX_OUTPUT_CHARS) {
      const folded = document.createElement('button'); folded.className = 'lee-output-fold';
      folded.textContent = `render large rich output (${Math.round(rich.length / 1024).toLocaleString()}kb)`;
      folded.onclick = show; d.appendChild(folded);
    } else show();
    return d;
  }
  // After the rich types, as Jupyter ranks them: a FastHTML object sends its markup as `text/html` and
  // again as a fenced `text/markdown` block, and the fence is source, not the thing to draw.
  if (data['text/markdown'] != null) {
    d.classList.add('lee-md-output'); d.dataset.mdBase = nbBase(); renderMarkdown(d, data['text/markdown'], false, el => rupakaFences(el, c?.id ? `outmd:${c.id}:${i}` : null)); return d;
  }
  outputText(d, data['text/plain'] || '');
  return d;
}

function paintSel() {
  $$('.lee-cell').forEach(el => {
    const i = +el.dataset.i, selected = lee.cellSelection.has(i) || (!lee.cellSelection.size && i === lee.sel);
    el.classList.toggle('sel', selected); el.setAttribute('aria-selected', String(selected));
  });
}
function selectCell(i, extend = false) {
  if (!lee.cells.length) return;
  lee.sel = Math.max(0, Math.min(i, lee.cells.length - 1));
  if (extend) {
    const lo = Math.min(lee.cellAnchor, lee.sel), hi = Math.max(lee.cellAnchor, lee.sel);
    lee.cellSelection = new Set(Array.from({length: hi - lo + 1}, (_, n) => lo + n));
  } else { lee.cellAnchor = lee.sel; lee.cellSelection = new Set([lee.sel]); }
  paintSel(); leaveOtherMarkdownEdits(lee.sel);
}
/* Bring a cell into view with room around it.

   `scrollIntoView({block: 'nearest'})` moves the minimum distance, so a cell arriving from below
   parks flush against the bottom edge with nothing under it, which is the whole of what a reader
   wants to see after running it. Moving the minimum is still right once the cell is comfortably
   on screen, or stepping to a neighbour would jump the page, so the margin is what decides. */
function revealCell(cell) {
  const host = $('#editor'); if (!host || !cell) return;
  const box = host.getBoundingClientRect(), r = cell.getBoundingClientRect();
  const margin = Math.min(120, Math.max(24, box.height * .18));
  const above = r.top - box.top - margin, below = r.bottom - box.bottom + margin;
  // A cell taller than the room left over can only be shown from its top.
  if (r.height > box.height - margin * 2 || above < 0) host.scrollTop += above;
  else if (below > 0) host.scrollTop += below;
}
function focusCell(i) {
  unfoldTo(Math.max(0, Math.min(i, lee.cells.length - 1)));
  selectCell(i);
  const c = lee.cells[lee.sel]; if (!c) return;
  // Mounted first: an unmounted cell is a shell whose height is a guess, and the reveal measures it.
  const v = ensureCellMounted(lee.sel), rendered = focusRenderedMarkdown(lee.sel);
  const reveal = () => revealCell($(`.lee-cell[data-i="${lee.sel}"]`));
  reveal();
  // CodeMirror focuses its own scroller and reveals the caret minimally, which spends the margin
  // again, so the reveal is repeated after it and after the layout mounting just caused.
  requestAnimationFrame(() => { if (v && !rendered) LeeCM.focus(v); reveal(); });
}
function focusCellPage(direction) {
  if (!lee.cells.length) return;
  const host = $('#editor'), current = $(`.lee-cell[data-i="${lee.sel}"]`);
  if (!host || !current) return focusCell(lee.sel + direction);
  const target = current.getBoundingClientRect().top + direction * Math.max(180, host.clientHeight * .78);
  const cells = $$('.lee-cell', host);
  const candidates = cells.filter(el => !el.classList.contains('heading-hidden') && (direction < 0 ? +el.dataset.i < lee.sel : +el.dataset.i > lee.sel));
  if (!candidates.length) return focusCell(direction < 0 ? 0 : shownAt(lee.cells.length - 1));
  const next = candidates.reduce((best, el) =>
    Math.abs(el.getBoundingClientRect().top - target) < Math.abs(best.getBoundingClientRect().top - target) ? el : best);
  focusCell(+next.dataset.i);
}
//: The autosave mode in effect: `off` while a presentation is open, which writes no file; the setting does not change.
const autoSaveMode = () => lee.present ? 'off' : lee.filePrefs.autoSave || 'afterDelay';
function autoSaveEnabled() { return autoSaveMode() !== 'off'; }
function normalizeSavedText(text) {
  const prefs=lee.filePrefs||{}; let out=String(text??'');
  if(prefs.trimTrailingWhitespace)out=out.split('\n').map(line=>line.replace(/[ \t]+$/,'')).join('\n');
  if(prefs.trimFinalNewlines)out=out.replace(/\n+$/,'');
  if(prefs.insertFinalNewline && out && !out.endsWith('\n'))out+='\n';
  return out;
}
function setTabSaveState(tab, state, detail = '') {
  if (!tab) return;
  const dot = $('.lee-save-state', tab); if (!dot) return;
  const labels = {
    pending: lee.path ? 'Changes queued for autosave' : 'Unsaved — choose a filename to save',
    saving: 'Saving changes…', saved: 'Saved on disk', error: 'Autosave failed',
  };
  dot.className = `lee-save-state ${state}`;
  dot.title = detail || labels[state] || state;
  dot.setAttribute('aria-label', dot.title);
  tab.dataset.saveState = state;
}
function scheduleAutoSave() {
  clearTimeout(lee.autoSaveTimer);
  if (autoSaveMode() !== 'afterDelay' || !lee.path || lee.heldSaveConflicts.has(lee.path)) return;
  const version = lee.editVersion;
  lee.autoSaveTimer = setTimeout(async () => {
    if (autoSaveMode() !== 'afterDelay') return;
    if (lee.saving || version !== lee.editVersion) return scheduleAutoSave();
    lee.saving = true;
    setTabSaveState($('.lee-tab.active'), 'saving');
    try { await saveTab(true, version); }
    finally { lee.saving = false; if (version !== lee.editVersion) scheduleAutoSave(); }
  }, Math.max(100, Number(lee.filePrefs.autoSaveDelay) || 900));
}
document.addEventListener('focusout',e=>{if(autoSaveMode()==='onFocusChange'&&!lee.heldSaveConflicts.has(lee.path)&&e.target.closest?.('.cm-editor')&&$('.lee-tab.active.dirty'))saveTab(true);});
window.addEventListener('blur',()=>{if(autoSaveMode()==='onWindowChange'&&!lee.heldSaveConflicts.has(lee.path)&&$('.lee-tab.active.dirty'))saveTab(true);});
function markDirty() {
  lee.editVersion += 1; lee.tabEdits.set(lee.tabKey, (lee.tabEdits.get(lee.tabKey) || 0) + 1);
  const t = $('.lee-tab.active');
  if (t) { t.classList.add('dirty'); setTabSaveState(t, 'pending'); }
  scheduleAutoSave();
}

/* A notebook's language is its kernelspec, so choosing one here writes the file and drops the
   runtime the old language was using. Unbound by default: a button and a palette entry, like every
   other action whose chord is not worth spending. */
async function pickNotebookLanguage() {
  if (lee.kind !== 'notebook') return status('open a notebook first', 'err');
  const o = await post('/nb/language', {path: lee.tabKey || ''});
  const rows = (o.langs || []).map(l =>
    `<div class="lee-mrow${l.current ? ' sel' : ''}" data-lang="${esc(l.id)}">` +
    `${l.current ? '● ' : '○ '}${esc(l.label)}<span class="sub">${esc(l.how)}</span></div>`).join('');
  const m = modal(
    `<div class="lee-mhead">notebook language<span class="sub">${esc(o.path || '')}</span></div>` +
    `<div class="lee-dim">this is written into the notebook, and closes the runtime it is using</div>` +
    `<div class="lee-modallist">${rows}</div>`);
  m.querySelectorAll('[data-lang]').forEach(el => el.onclick = async () => {
    m.remove();
    try {
      const d = await post('/nb/language', {path: lee.tabKey || '', lang: el.dataset.lang});
      status(`this notebook is ${d.lang} now`, 'ok');
      await mountTab(lee.tabKey);
    } catch (e) { status(String(e.message || e), 'err'); }
  });
}
