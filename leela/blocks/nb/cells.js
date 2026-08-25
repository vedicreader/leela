/* The banner says where a cell sits and how big it is. The gutter carries the execution count,
 * which is blank until the cell runs and renumbers on every rerun. */
const cellKind = (c) => ({code: 'py', markdown: 'md', prompt: 'prompt'}[c.cell_type] || c.cell_type);
const cellLines = (c) => String(c.source || '').split('\n').length;
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
function cellMetaTitle(c, i) {
  const src = String(c.source || '');
  const rows = [`cell ${i + 1} of ${lee.cells.length} · ${c.cell_type} · ${plural(cellLines(c), 'line')}, ${src.length} chars`];
  if (c.cell_type === 'code')
    rows.push([c.execution_count == null ? 'not run' : `run ${c.execution_count}`,
               formatCellTime(c.execution_ms), plural((c.outputs || []).length, 'output')].filter(Boolean).join(' · '));
  rows.push(`id ${c.id}`, 'click to copy the id');
  return rows.join('\n');
}
function paintCellMeta(el, c, i) {
  const meta = el && $('.lee-cell-meta', el); if (!meta) return;
  $('.lee-cell-no', meta).textContent = '#' + (i + 1);
  $('.lee-cell-size', meta).textContent = `${cellKind(c)} · ${plural(cellLines(c), 'line')}`;
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
  const r = await nbEdit({op: 'context', i, mode});
  Object.assign(c, r.cells[i]);
  const button = $(`.lee-cell[data-i="${i}"] .lee-cell-context`); if (button) paintCellContext(button, c);
  status(`cell ${i + 1}: ${contextLabel(mode)}`, 'ok');
}
window.leeCellContext = cycleCellContext;

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
  d.className = 'lee-cell ' + c.cell_type + (lee.collapsedCells.has(c.id) ? ' collapsed' : '');
  d.dataset.i = i; d.dataset.id = c.id;
  d.style.setProperty('--lee-cell-lines', Math.min(20, Math.max(2, String(c.source || '').split('\n').length)));
  const state = cellState(c);
  d.innerHTML =
    `<div class="lee-gutter" draggable="true" title="drag to move cell">` +
    `<button class="lee-cell-fold" title="collapse cell" aria-label="collapse cell">${lee.collapsedCells.has(c.id) ? '+' : '−'}</button>` +
    `<div class="lee-execution-count" id="g-${c.id}">${gutterFor(c)}</div></div>` +
    `<div class="lee-cellmain"><div class="lee-cell-chrome">` +
    `<button class="lee-cell-meta" data-cell-id="${esc(c.id)}" title="${esc(cellMetaTitle(c, i))}" ` +
    `onclick="event.stopPropagation();leeCopyCellId(this)">` +
    `<span class="lee-cell-no">#${i + 1}</span>` +
    `<span class="lee-cell-size">${esc(cellKind(c))} · ${esc(plural(cellLines(c), 'line'))}</span></button>` +
    `<span class="lee-cell-summary">${esc(String(c.source || '').trim().split('\n')[0] || 'empty cell')}</span>` +
    `<span class="lee-cell-state ${state}" id="state-${c.id}" ` +
    `title="${state === 'done' ? 'ran successfully in the current kernel' : state === 'error' ? 'run failed in the current kernel' : state === 'previous' ? 'saved output from a previous kernel; run to restore variables' : 'not run'}">${stateSvg(state)}</span>` +
    `<time class="lee-cell-time" id="time-${c.id}" title="last execution time" ` +
    `${c.execution_ms == null ? 'hidden' : ''}>${esc(formatCellTime(c.execution_ms))}</time>` +
    `<button class="lee-cell-context" data-mode="${esc(c.context_mode || 'auto')}" ` +
    `onclick="event.stopPropagation();leeCellContext(${i})">${esc(contextLabel(c.context_mode || 'auto'))}</button>` +
    `<div class="lee-model-running" id="model-${c.id}" role="status" aria-live="polite" hidden>` +
    `<span class="lee-running-dot" aria-hidden="true">●</span>` +
    `<span class="lee-running-copy">Model is running</span>` +
    `<span class="lee-running-time"> · starting</span></div>` +
    `<div class="lee-cellbtns">${cellButtons(i)}</div></div>` +
    `<div class="lee-cm" id="cm-${c.id}"></div><div id="out-${c.id}"></div></div>`;
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
  return d;
}

function setCellCollapsed(i, value = null) {
  const c = lee.cells[i]; if (!c) return;
  const collapsed = value === null ? !lee.collapsedCells.has(c.id) : value;
  if (collapsed) lee.collapsedCells.add(c.id); else lee.collapsedCells.delete(c.id);
  const el = $(`.lee-cell[data-i="${i}"]`); el?.classList.toggle('collapsed', collapsed);
  const button = el?.querySelector('.lee-cell-fold'); if (button) button.textContent = collapsed ? '+' : '−';
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
  await nbEdit({op: 'delete_many', i: indices[0], indices});
  focusCell(Math.min(indices[0], lee.cells.length - 1));
  status(`${cells.length} cell${cells.length === 1 ? '' : 's'} cut`, 'ok');
}
async function pasteCell(i) {
  if (lee.kind !== 'notebook') return status('cells can only be pasted into a notebook', 'err');
  const cells = lee.cellClipboard?.cells || (lee.cellClipboard?.cell ? [lee.cellClipboard.cell] : []);
  if (!cells.length) return status('copy or cut cells first', 'err');
  const at = Math.max(0, Math.min(i, lee.cells.length));
  await nbEdit({op: 'paste_many', i: at, cells});
  focusCell(at); lee.cellSelection = new Set(cells.map((_, n) => at + n)); paintSel();
  status(`${cells.length} cell${cells.length === 1 ? '' : 's'} pasted from ${compactPath(lee.cellClipboard.from)}`, 'ok');
}

async function moveCellsTo(indices, to) {
  indices = [...new Set(indices)].sort((a,b) => a-b);
  const r = await nbEdit({op: 'move_many', i: indices[0], indices, target: to});
  const at = r.index ?? to; focusCell(at); lee.cellSelection = new Set(indices.map((_, n) => at + n));
  paintSel(); status(`${indices.length} cells moved`, 'ok');
}

async function moveCellTo(from, to) {
  const last = lee.cells.length - 1;
  to = Math.max(0, Math.min(to, last));
  if (from === to || from < 0 || from > last) return focusCell(from);
  await nbEdit({op: 'move', i: from, d: to - from});
  focusCell(to); status(`cell moved to ${to + 1}`, 'ok');
}

function mountCell(c, i) {
  if (lee.editors.has(c.id)) return;
  const key = `${lee.path || 'scratch'}:${c.id}`;
  // Only a docChanged transaction marks a buffer authoritative. A stale empty cache must never
  // replace the non-empty source `/tab/state` returned after running a cell.
  const source = lee.dirtyBuffers.has(key) ? lee.buffers.get(key) : c.source;
  c.source = source;
  const v = createEditor($('#cm-' + c.id), {
    doc: source, lang: c.cell_type === 'code' ? 'python' : c.cell_type === 'markdown' ? 'markdown' : '',
    placeholder: c.cell_type === 'prompt' ? `ask the inline model — ${displayChord('mod+enter')} answers in place` : '',
    completeUrl: c.cell_type === 'code' ? '/complete' : null,
    onDefinition: c.cell_type === 'code' ? name => findDefinition(name) : null,
    breakpoints: lee.breakpoints.get(c.id) || [],
    // Line numbers relative to this cell. A cell mounted after the marks arrived would otherwise
    // stay unmarked until the next save.
    changedLines: (lee.notebookGit?.lines || {})[c.id] || [],
    onBreakpoint: c.cell_type === 'code' ? lines => rememberBreakpoints(c.id, lines) : null,
    settings: {overviewMode:'off'},
    onSelection: () => { clearTimeout(selectionHelpTimer); selectionHelpTimer = setTimeout(showSelectionHelp, 120); },
    onChange: (txt) => {
      const at = lee.cells.findIndex(cell => cell.id === c.id); if (at < 0) return;
      lee.cells[at].source = txt;
      rememberBuffer(key, {path: lee.path, kind: 'notebook', i: at, id: c.id, text: txt});
      if (cellState(lee.cells[at]) !== 'idle') setCellState(lee.cells[at], 'stale', 'code changed since the last run');
      markDirty();
    },
  });
  lee.editors.set(c.id, v);
  $('#cm-' + c.id).addEventListener('focusin', () => {
    const at = lee.cells.findIndex(cell => cell.id === c.id);
    if (at >= 0) { lee.activeEditor='primary'; lee.sel = at; setScope('editor'); paintSel(); }
  });
  renderOutputs(c);
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

function renderOutputs(c) {
  const box = $('#out-' + c.id); if (!box) return;
  $$('[data-markdown]', box).forEach(el => {
    if (el._leeCodeFrame) cancelAnimationFrame(el._leeCodeFrame);
    for (const v of (el._leeCodeViews || [])) try { LeeCM.destroy(v); } catch {}
  });
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
    for (const o of (c.outputs || [])) box.appendChild(outputEl(o));
    return;
  }
  for (const o of (c.outputs || [])) box.appendChild(outputEl(o));
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
  if (!item) return;
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
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeInlinePopover(); }, true);

function outputTone(o) {
  if (o.output_type === 'error') return 'error';
  if (o.output_type === 'stream' && o.name === 'stderr')
    return /\b(?:warning|warns?|deprecated|deprecation)\b/i.test(String(o.text || '')) ? 'warning' : 'log';
  if (o.output_type === 'execute_result' || o.output_type === 'display_data') return 'result';
  return 'output';
}
function outputEl(o) {
  const d = document.createElement('div');
  const tone = outputTone(o);
  d.className = `lee-out ${tone}`;
  if (o.output_type === 'stream') { outputText(d, o.text); return d; }
  if (o.output_type === 'error') {
    outputText(d, stripAnsi((o.traceback || []).join('\n')) || `${o.ename}: ${o.evalue}`);
    return d;
  }
  const data = o.data || {};
  if (data['image/png']) {
    const i = document.createElement('img');
    i.src = 'data:image/png;base64,' + data['image/png'];
    d.appendChild(i); return d;
  }
  if (data['text/markdown']) {
    d.classList.add('lee-md-output'); renderMarkdown(d, data['text/markdown']); return d;
  }
  if (data['text/html'] || data['image/svg+xml']) {
    // Rich reprs get their own shadow root: pandas ships a <style> block with every DataFrame and
    // `scoped` has been dead for years, so an output could restyle the IDE around it. Very large
    // HTML stays unparsed until requested, because parsing a multi-megabyte table on the main
    // thread triggers Chrome's hang dialog.
    const rich = data['text/html'] || data['image/svg+xml'];
    const show = () => { d.textContent = ''; d.attachShadow({mode: 'open'}).innerHTML = rich; };
    if (rich.length > MAX_OUTPUT_CHARS) {
      const folded = document.createElement('button'); folded.className = 'lee-output-fold';
      folded.textContent = `render large rich output (${Math.round(rich.length / 1024).toLocaleString()}kb)`;
      folded.onclick = show; d.appendChild(folded);
    } else show();
    return d;
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
  paintSel();
}
function focusCell(i) {
  selectCell(i);
  const c = lee.cells[lee.sel]; if (!c) return;
  const cell = $(`.lee-cell[data-i="${lee.sel}"]`);
  // CodeMirror focuses its own scroller but cannot reveal itself inside the notebook's outer
  // scroller, so the cell is scrolled into view here.
  cell?.scrollIntoView({block: 'nearest', inline: 'nearest'});
  const v = ensureCellMounted(lee.sel);
  if (v) requestAnimationFrame(() => LeeCM.focus(v));
}
function focusCellPage(direction) {
  if (!lee.cells.length) return;
  const host = $('#editor'), current = $(`.lee-cell[data-i="${lee.sel}"]`);
  if (!host || !current) return focusCell(lee.sel + direction);
  const target = current.getBoundingClientRect().top + direction * Math.max(180, host.clientHeight * .78);
  const cells = $$('.lee-cell', host);
  const candidates = cells.filter(el => direction < 0 ? +el.dataset.i < lee.sel : +el.dataset.i > lee.sel);
  if (!candidates.length) return focusCell(direction < 0 ? 0 : lee.cells.length - 1);
  const next = candidates.reduce((best, el) =>
    Math.abs(el.getBoundingClientRect().top - target) < Math.abs(best.getBoundingClientRect().top - target) ? el : best);
  focusCell(+next.dataset.i);
}
function autoSaveEnabled() { return (lee.filePrefs.autoSave || 'afterDelay') !== 'off'; }
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
  if ((lee.filePrefs.autoSave || 'afterDelay') !== 'afterDelay' || !lee.path || lee.heldSaveConflicts.has(lee.path)) return;
  const version = lee.editVersion;
  lee.autoSaveTimer = setTimeout(async () => {
    if (lee.saving || version !== lee.editVersion) return scheduleAutoSave();
    lee.saving = true;
    setTabSaveState($('.lee-tab.active'), 'saving');
    try { await saveTab(true, version); }
    finally { lee.saving = false; if (version !== lee.editVersion) scheduleAutoSave(); }
  }, Math.max(100, Number(lee.filePrefs.autoSaveDelay) || 900));
}
document.addEventListener('focusout',e=>{if(lee.filePrefs.autoSave==='onFocusChange'&&!lee.heldSaveConflicts.has(lee.path)&&e.target.closest?.('.cm-editor')&&$('.lee-tab.active.dirty'))saveTab(true);});
window.addEventListener('blur',()=>{if(lee.filePrefs.autoSave==='onWindowChange'&&!lee.heldSaveConflicts.has(lee.path)&&$('.lee-tab.active.dirty'))saveTab(true);});
function markDirty() {
  lee.editVersion += 1;
  const t = $('.lee-tab.active');
  if (t) { t.classList.add('dirty'); setTabSaveState(t, 'pending'); }
  scheduleAutoSave();
}
