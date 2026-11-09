/* Put a position in the middle of the view rather than merely inside it.

   `scrollIntoView` moves the minimum distance, so a match below the fold arrives on the last
   visible line with nothing under it. Written against `scrollDOM` rather than CodeMirror's own
   centring effect, because the vendored bundle is committed and rebuilding it needs node.

   A notebook scrolls its column of cells, not the cell's own editor, so the element that can move
   is the one that gets scrolled. */
function centreOnPos(v, pos) {
  const coords = v.coordsAtPos(pos); if (!coords) return;
  const own = v.scrollDOM, host = own.scrollHeight - own.clientHeight > 4 ? own : $('#editor');
  if (!host) return;
  const box = host.getBoundingClientRect();
  host.scrollTop += (coords.top + coords.bottom) / 2 - (box.top + box.height / 2);
}

function jumpToLine(line) {
  const v = lee.kind === 'notebook' ? lee.editors.get(lee.cells[lee.sel]?.id) : lee.editors.get('file');
  if (!v) return;
  const n = Math.max(1, Math.min(Number(line) || 1, v.state.doc.lines));
  const pos = v.state.doc.line(n).from;
  v.dispatch({selection: {anchor: pos}, scrollIntoView: true}); v.focus();
  requestAnimationFrame(() => centreOnPos(v, pos));
}

async function openLocation(hit) {
  const name = hit.path.split('/').pop();
  const inCell = Number(hit.cell_line) > 0;
  try {
    if (!inCell && /\.ipynb$/i.test(hit.path)) {
      await leeOpenFile(hit.path);
      return status(`${name}: line ${hit.line} of the notebook file is in no cell`, 'info');
    }
    const line = inCell ? Number(hit.cell_line) : hit.line;
    lee.pendingLocation = {path: hit.path, line, column: Number(hit.column || 0), symbol: hit.symbol || '',
                           cellId: hit.cell || '',
                           cellIndex: Number.isFinite(hit.cell_index) ? Number(hit.cell_index) : -1};
    await leeOpenFile(hit.path);
    status(`${name}${inCell ? ` · cell ${Number(hit.cell_index) + 1}` : ''}:${line}`);
  } catch (e) { return status(e.message || String(e), 'err');}
}

async function stopCell(i) {
  const c = lee.cells[i];
  if (!c) return status(`cell ${i + 1} is not running`, 'err');
  // The page's flag can lag the run (an undo rebuilds the cells), so a cell the page thinks idle is still put to the server.
  const was = c.running;
  if (!was && c.cell_type === 'prompt') return status(`cell ${i + 1} is not running`, 'err');   // the server stops an agent turn for any prompt cell it is asked about
  if (was) { status(`stopping cell ${i + 1}…`); lee.promptRuns?.get(c.id)?.abort(); }
  let r;
  try { r = await post('/nb/interrupt', {path: lee.tabKey || '', id: c.id}); }
  catch (e) { if (was) throw e; return status(`cell ${i + 1} is not running`, 'err'); }
  status(r.forced ? 'cell stopped · kernel restarted because interrupt was ignored' : 'cell stopped',
         r.forced ? 'err' : 'ok');
  if (r.forced) kernelRestarted();
}

/* A run stream that ended without its result leaves the server knowing how the cell stands. Ask it,
   and keep asking, slower each time, while the cell is still running. */
async function settleRun(path, id) {
  for (let wait = 2000, misses = 0; ; wait = Math.min(wait * 2, 10000)) {
    const s = await post('/nb/run/state', {path, id}).catch(e => { if (++misses > 3) throw e; return {running: true}; });
    if (!s.running) {
      if (!s.cell) throw new Error('the cell is no longer in the notebook');
      const failed = (s.cell.outputs || []).some(o => o.output_type === 'error');
      if (s.cell.execution_count == null && !failed) throw new Error('the run stream ended, and the kernel kept no record of this cell');
      return {ok: !failed, cell: s.cell, inline: [], result: null};
    }
    await new Promise(res => setTimeout(res, wait));
  }
}

/* Resolves to `{ok, error}`. The slide deck runs cells with the status line hidden under it, so it
   reads the outcome here and follows the outputs through `lee-cell-output`. `save: false` runs the
   live text and writes no file: no save before or after, and no placeholder made valid. */
const cellOutputEvent = (id, outputs) => dispatchEvent(new CustomEvent('lee-cell-output', {detail: {id, outputs}}));
//: A run stream's `output` message on the outputs shown: `n` outputs, each op a stream's new text or a whole output.
function applyOutputOps(outputs, {n, ops}) {
  const outs = (outputs || []).slice(0, n);
  for (const [k, kind, v] of ops) outs[k] = kind === 'append' ? {...outs[k], text: (outs[k]?.text || '') + v} : v;
  return outs;
}
async function runCell(i, advance, {save = true} = {}) {
  // An edit still in flight (a confidence click) replaces the cells when it lands, and lands mid-save and refuses it.
  await lee.nbQueue;
  const c = lee.cells[i]; if (!c) return {ok: false, error: 'that cell is no longer in the notebook'};
  if (c.running) {
    status(`cell ${i + 1} is already running`, 'err');
    return {ok: false, error: `cell ${i + 1} is already running`};
  }
  const runKey = lee.tabKey, cellId = c.id;
  // The cell that runs, wherever an insert, move or delete above has put it since; null once its tab is not shown.
  const cur = () => lee.tabKey === runKey ? lee.cells.find(x => x.id === cellId) : null;
  let res = {ok: true, error: ''};
  const v = ensureCellMounted(i);
  const src = v ? LeeCM.getDoc(v) : c.source, seq = nextSeq();
  const el = $(`.lee-cell[data-i="${i}"]`);
  if (c.cell_type === 'markdown') showRenderedMarkdown(c, true);
  else if (c.cell_type === 'prompt') {
    c.running = true;
    try { await askCell(i, src, el); }
    finally { c.running = false; }
  } else {
    const p = lee.cells.find(x => x.cell_type === 'markdown' && x.extra?.lesson?.role === 'prediction' && x.extra.lesson.for === cellId);
    const pv = p && lee.editors.get(p.id), guess = p ? {prediction: pv ? LeeCM.getDoc(pv) : p.source, confidence: p.extra.lesson.confidence} : {};
    if (save && lee.path && $('.lee-tab.active.dirty') && !await saveTab(true)) return {ok: false, error: 'the notebook could not be saved first'};
    const began = performance.now();
    c.running = true;
    if (c.extra?.lesson) $('.lee-reveal', el)?.remove();
    el?.classList.add('running');
    setCellState(c, 'running');
    setCellTime(c, 0, true);
    const cellClock = setInterval(() => { if (cur()) setCellTime(c, performance.now() - began, true); }, 100);
    $('#g-' + c.id).textContent = '[*]';
    status(`running cell ${i + 1}…`);
    try {
      let r = null, failed = null;
      await widgetWatch(runKey, cellId);
      try {
        await withPython(() => postEvents('/nb/run/stream', {i, id: cellId, path: runKey, source: src, seq, ...seenRow(runKey, cellId), ...guess, ...(save ? {} : {save: false})}, (event, data) => {
          if (event === 'error') throw failed = new Error(data.text || 'cell execution failed');
          if (event === 'done') r = data;
          const at = cur();
          if (at && event === 'output') { at.outputs = data.ops ? applyOutputOps(at.outputs, data) : data.outputs || []; renderOutputs(at); cellOutputEvent(cellId, at.outputs); }
        }, null, 45000));
      } catch (e) { if (e === failed || e.unsent) throw e; }
      if (!r) r = await settleRun(runKey, cellId);
      const at = cur();
      if (!at) {
        c.running = false; el?.classList.remove('running'); leeVars();
        return {ok: false, error: 'the notebook changed while the cell ran'};
      }
      Object.assign(at, r.cell);
      renderOutputs(at); cellOutputEvent(cellId, at.outputs || []);
      const view = lee.editors.get(cellId); if (view) LeeCM.setInlineValues(view, r.inline || []);
      if (r.result) requestAnimationFrame(() => openValueLens(r.result, $('#out-' + cellId) || el, 'expression result'));
      $('#g-' + cellId).textContent = '[' + (r.cell.execution_count ?? ' ') + ']';
      const elapsed = Number(at.execution_ms ?? (performance.now() - began));
      const duration = formatCellTime(elapsed), n = lee.cells.indexOf(at) + 1;
      setCellTime(at, elapsed, false);
      setCellState(at, r.ok ? 'done' : 'error', r.ok ? `ran successfully in ${duration}` : `failed after ${duration}`);
      status(r.ok ? `cell ${n} ran in ${duration}${r.lost ? ' · some of its last outputs are lost' : ''}`
             : r.reason === 'shell_stopped' ? `cell ${n}: the kernel's shell stopped answering · restart the kernel` : `cell ${n} failed after ${duration}`,
             r.ok ? 'ok' : 'err');
      res = {ok: !!r.ok, error: r.ok ? '' : `cell ${n} failed after ${duration}`};
    } catch (e) {
      const elapsed = performance.now() - began, at = cur() || c;
      at.execution_ms = elapsed; setCellTime(at, elapsed, false);
      setCellState(at, 'error', `run failed after ${formatCellTime(elapsed)}`);
      status(String(e.message || e), 'err');
      res = {ok: false, error: String(e.message || e)};
    } finally { clearInterval(cellClock); }
    for (const x of [c, cur()]) if (x) x.running = false;
    if (cur()?.extra?.lesson) renderLessonReveal(cur());
    if (isExercise(cur())) renderExercise(cur());
    if (cur()) $(`#editor .lee-cell[data-id="${CSS.escape(cellId)}"]`)?.classList.remove('running');
    if (save && lee.path && cur() && autoSaveEnabled()) saveTab(true).catch(() => {});
    leeVars();
  }
  if (!advance || (i = cur() ? lee.cells.findIndex(x => x.id === cellId) : -1) < 0) return res;
  if (advance === 'insert') { const at = belowAt(i); if (await nbEdit({op: 'insert', i: at})) focusCell(at); }
  else if (advance) {
    const j = visibleCell(i, 1), at = lee.cells.length;
    if (j >= 0) focusCell(j); else if (await nbEdit({op: 'insert', i: at})) focusCell(at);
  }
  return res;
}

function paintDebugInlineValues(view, lineNo, variables) {
  if (!view || !lineNo || lee.debugPrefs.showInlineValues === false) return;
  const line = view.state.doc.line(Math.min(lineNo, view.state.doc.lines));
  const names = new Set((line.text.match(/[_A-Za-z]\w*/g) || []));
  const values = (variables || []).filter(v => names.has(v.name)).map(v => ({
    line: line.number, name: v.name, value: v.value || '', type: v.type || '',
    shape: null, dtype: null, is_grid: false, accessor: ['debug', Number(v.variablesReference) || 0],
  }));
  LeeCM.setInlineValues(view, values);
}

async function revealDebugFrame(state) {
  const frame = (state.frames || []).find(f => f.id === state.frame_id) || state.frames?.[0];
  if (!frame) return;
  // Exactly one source line is current. Clear the old marker before moving, including when
  // step-in changes files.
  for (const [key, view] of lee.editors) if (key !== 'exec') { LeeCM.setDebugLine(view, 0); LeeCM.setInlineValues(view, []); }
  if (frame.open_path) {
    $('#debugsource')?.remove();
    if (lee.path !== frame.open_path) {
      lee.pendingLocation = {path: frame.open_path, line: frame.line, debug: true,
                             cellId: frame.cell_id || ''};
      leeOpenFile(frame.open_path);
      return;
    }
    if (frame.cell_id && lee.kind === 'notebook') {
      const i = lee.cells.findIndex(c => c.id === frame.cell_id);
      if (i >= 0) {
        unfoldTo(i); selectCell(i); const view = ensureCellMounted(i);
        LeeCM.setDebugLine(view, frame.line); paintDebugInlineValues(view, frame.line, state.variables); jumpToLine(frame.line);
      }
    } else {
      const view = lee.editors.get('file');
      if (view) { LeeCM.setDebugLine(view, frame.line); paintDebugInlineValues(view, frame.line, state.variables); jumpToLine(frame.line); }
    }
    return;
  }
  if(lee.directDebug)return;
  const src = await api(`/nb/debug/source?frame_id=${frame.id}`);
  let pane = $('#debugsource');
  if (!pane) {
    pane = document.createElement('aside'); pane.id = 'debugsource'; pane.className = 'lee-debug-source-pane';
    pane.innerHTML = `<div class="lee-mhead">debug source <span class="sub"></span>` +
                     `<button class="lee-icon" aria-label="close">×</button></div>` +
                     `<div class="lee-debug-source-editor"></div>`;
    pane.querySelector('[aria-label="close"]').onclick = () => pane.remove();
    document.body.appendChild(pane);
  }
  pane.querySelector('.lee-mhead .sub').textContent = src.path || src.name || 'external frame';
  const host = pane.querySelector('.lee-debug-source-editor'); host.innerHTML = '';
  if (host._leeView) LeeCM.destroy(host._leeView);
  host._leeView = createEditor(host, {doc: src.content || '', lang: nbLang(), readOnly: true, lineNums: true});
  LeeCM.setDebugLine(host._leeView, src.line); const pos = host._leeView.state.doc.line(Math.min(src.line, host._leeView.state.doc.lines)).from;
  host._leeView.dispatch({selection: {anchor: pos}, scrollIntoView: true});
}

async function debugEvaluate(expression){return post(lee.directDebug?'/debug/evaluate':'/nb/debug/evaluate',lee.directDebug?{expression,frame_id:lee.debugState?.frame_id}:{code:expression,frame_id:lee.debugState?.frame_id});}
async function paintDebugWatches(panel=$('#debugger')){const host=$('.lee-debug-watches',panel);if(!host)return;host.innerHTML=lee.debugWatches.map((expression,i)=>`<div class="lee-debug-watch" data-i="${i}"><strong>${esc(expression)}</strong><span>evaluating…</span><button aria-label="remove">×</button></div>`).join('')||'<div class="lee-dim">no watch expressions</div>';
  $$('.lee-debug-watch',host).forEach(async row=>{row.querySelector('button').onclick=()=>{lee.debugWatches.splice(+row.dataset.i,1);localStorage.setItem('lee-debug-watches',JSON.stringify(lee.debugWatches));paintDebugWatches(panel);};try{const r=await debugEvaluate($('strong',row).textContent);$('span',row).textContent=r.result??r.value??'';}catch(e){$('span',row).textContent=e.message||String(e);}});}

function paintDebugger(state) {
  lee.debugState = state;
  let panel = $('#debugger');
  if (!panel) {
    panel = document.createElement('aside'); panel.id = 'debugger'; panel.className = 'lee-debugger';
    document.body.appendChild(panel);
  }
  const frames = state.frames || [], vars = state.variables || [];
  panel.innerHTML = `<div class="lee-debug-head"><strong>Paused at line ${esc(frames[0]?.line || '?')}</strong>` +
    `<span>${esc(frames[0]?.name || '')}</span><div class="lee-debug-controls">` +
    `<button title="continue" onclick="leeDebugControl('continue')">▶</button>` +
    `<button title="step over" onclick="leeDebugControl('next')">↷</button>` +
    `<button title="step into" onclick="leeDebugControl('stepIn')">↓</button>` +
    `<button title="step out" onclick="leeDebugControl('stepOut')">↑</button>` +
    `<button title="stop" onclick="leeDebugStop()">■</button></div></div>` +
    `<div class="lee-debug-body"><section><h4>call stack</h4>${frames.map(f =>
      `<button class="lee-debug-frame ${f.id === state.frame_id ? 'active' : ''}" onclick="leeDebugFrame(${f.id})">` +
      `${esc(f.name)} <span>line ${esc(f.line)}</span></button>`).join('')}</section>` +
    `<section><h4>locals <span class="lee-dim">expand in Variables</span></h4>${vars.map(v => `<div class="lee-debug-var"><strong>${esc(v.name)}</strong>` +
      `<span>${esc(v.value)}</span><small>${esc(v.type || '')}</small></div>`).join('') || '<div class="lee-dim">no locals</div>'}` +
    `<h4>watch</h4><form class="lee-debug-watch-form"><input class="lee-input" placeholder="expression"><button class="lee-btn">add</button></form><div class="lee-debug-watches"></div>` +
    `<h4>debug console</h4><form class="lee-debug-console-form"><input class="lee-input" placeholder="evaluate in selected frame"><button class="lee-btn">run</button></form><div class="lee-debug-console-out"></div></section></div>`;
  $('.lee-debug-watch-form',panel).onsubmit=e=>{e.preventDefault();const input=$('input',e.currentTarget),expression=input.value.trim();if(expression&&!lee.debugWatches.includes(expression)){lee.debugWatches.push(expression);localStorage.setItem('lee-debug-watches',JSON.stringify(lee.debugWatches));input.value='';paintDebugWatches(panel);}};
  $('.lee-debug-console-form',panel).onsubmit=async e=>{e.preventDefault();const input=$('input',e.currentTarget),expression=input.value.trim();if(!expression)return;try{const r=await debugEvaluate(expression);$('.lee-debug-console-out',panel).textContent=`${expression} → ${r.result??r.value??''}`;}catch(error){$('.lee-debug-console-out',panel).textContent=error.message||String(error);}};
  paintDebugWatches(panel);
  revealDebugFrame(state).catch(e => status(String(e.message || e), 'err'));
  leeScope('live'); leeRight('vars'); leeVars();
}

async function leeDebugFrame(frameId) {
  try {
    const state = await api(`${lee.directDebug?'/debug/state':'/nb/debug/state'}?frame_id=${frameId}`);
    paintDebugger(state);
  } catch (e) { status(String(e.message || e), 'err'); }
}
window.leeDebugFrame = leeDebugFrame;

async function leeDebugControl(command) {
  try {
    await post(lee.directDebug?'/debug/control':'/nb/debug/control', {command, thread_id: lee.debugThread});
    $('#debugger')?.classList.add('running'); status(`debugger: ${command}`);
  } catch (e) { status(String(e.message || e), 'err'); }
}
window.leeDebugControl = leeDebugControl;

async function leeDebugStop() {
  try { await post(lee.directDebug?'/debug/stop':'/nb/debug/stop', {}); } catch (_) {}
  lee.debugThread = null; lee.debugCell = null; lee.debugState = null; lee.directDebug=false;
  $('#debugger')?.remove(); $('#debugsource')?.remove();
  for (const [key, view] of lee.editors) if (key !== 'exec') { LeeCM.setDebugLine(view, 0); LeeCM.setInlineValues(view, []); }
  leeScope('live'); leeVars(); status('debugger stopped', 'ok');
}
window.leeDebugStop = leeDebugStop;

async function debugCell(i) {
  const c = lee.cells[i]; if (!c || c.cell_type !== 'code') return;
  if (lee.debugCell != null) return status('a debugger session is already active', 'err');
  const view = ensureCellMounted(i), source = LeeCM.getDoc(view), key = lee.tabKey;
  let breakpoints = lee.breakpoints.get(c.id) || [];
  if (!breakpoints.length) {
    breakpoints = [LeeCM.lineOf(view)]; rememberBreakpoints(c.id, breakpoints);
    LeeCM.setBreakpoints(view, breakpoints);
  }
  lee.debugCell = i; c.running = true; setCellState(c, 'running');
  status(`starting ipykernel debugger for cell ${i + 1}…`);
  let done = null;
  try {
    await withPython(() => postEvents('/nb/debug/stream', {i, id: c.id, path: key, source, seq: nextSeq(), ...seenRow(key, c.id), breakpoints}, (event, data) => {
      if (event === 'ready') {
        rememberBreakpoints(c.id, data.breakpoints || breakpoints);
        LeeCM.setBreakpoints(view, data.breakpoints || breakpoints);
      } else if (event === 'stopped') {
        lee.debugThread = data.thread_id; $('#debugger')?.classList.remove('running');
        paintDebugger(data); status(`paused at line ${data.frames?.[0]?.line || '?'}`, 'ok');
      } else if (event === 'continued') {
        lee.debugThread = null; lee.debugState = null; $('#debugger')?.classList.add('running');
        for (const [key, editor] of lee.editors) if (key !== 'exec') { LeeCM.setDebugLine(editor, 0); LeeCM.setInlineValues(editor, []); }
        leeVars();
      } else if (event === 'done') done = data;
      else if (event === 'error') throw new Error(data.text || 'debugger failed');
    }));
    const at = lee.tabKey === key && lee.cells.find(x => x.id === c.id);
    if (done?.cell && at) {
      Object.assign(at, done.cell); renderOutputs(at);
      $('#g-' + c.id).textContent = '[' + (at.execution_count ?? ' ') + ']';
      setCellState(at, done.ok ? 'done' : 'error');
    }
    status(done?.ok ? 'debug session finished' : (done?.error || 'debug session failed'), done?.ok ? 'ok' : 'err');
  } catch (e) { setCellState(c, 'error'); status(String(e.message || e), 'err'); }
  finally {
    c.running = false; lee.debugThread = null; lee.debugCell = null; lee.debugState = null;
    $('#debugger')?.remove(); $('#debugsource')?.remove();
    for (const [key, view] of lee.editors) if (key !== 'exec') { LeeCM.setDebugLine(view, 0); LeeCM.setInlineValues(view, []); }
    leeScope('live'); leeVars();
  }
}
window.leeDebugCell = debugCell;