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
  // After the layout `scrollIntoView` just caused, or the measurement is of the old position.
  requestAnimationFrame(() => centreOnPos(v, pos));
}
function openLocation(hit) {
  // A hit in a notebook reports two coordinates: `line` in the .ipynb JSON, which is what ripgrep
  // and blame speak, and the cell plus the line inside it, which is the only pair an editor can
  // open. Prefer the second when the server placed the hit. A hit it could not place keeps the
  // file line rather than opening a cell chosen at random.
  const name = hit.path.split('/').pop();
  const inCell = Number(hit.cell_line) > 0;
  if (!inCell && /\.ipynb$/i.test(hit.path)) {
    // Nowhere to scroll to: the JSON line is not a line of any cell's editor, and jumping to it
    // inside whichever cell is selected would look like an answer.
    leeOpenFile(hit.path);
    return status(`${name} — line ${hit.line} of the notebook file is in no cell`, 'info');
  }
  const line = inCell ? Number(hit.cell_line) : hit.line;
  lee.pendingLocation = {path: hit.path, line, column: Number(hit.column || 0), symbol: hit.symbol || '',
                         cellId: hit.cell || '',
                         cellIndex: Number.isFinite(hit.cell_index) ? Number(hit.cell_index) : -1};
  leeOpenFile(hit.path);
  status(`${name}${inCell ? ` · cell ${Number(hit.cell_index) + 1}` : ''}:${line}`);
}

async function stopCell(i) {
  const c = lee.cells[i];
  if (!c?.running) return status(`cell ${i + 1} is not running`, 'err');
  status(`stopping cell ${i + 1}…`);
  // A prompt cell is a turn of the inline agent rather than anything in a kernel. The server
  // stops the agent; this ends the reply stream that is holding the cell open here.
  lee.promptRuns?.get(c.id)?.abort();
  const r = await post('/nb/interrupt', {path: lee.tabKey || '', id: c.id});
  status(r.forced ? 'cell stopped · kernel restarted because interrupt was ignored' : 'cell stopped',
         r.forced ? 'err' : 'ok');
}

/* Resolves to `{ok, error}`. The slide deck runs cells with the status line hidden under it, so it
   reads the outcome here and follows the outputs through `lee-cell-output`. */
const cellOutputEvent = (id, outputs) => dispatchEvent(new CustomEvent('lee-cell-output', {detail: {id, outputs}}));
async function runCell(i, advance) {
  const c = lee.cells[i]; if (!c) return {ok: false, error: 'that cell is no longer in the notebook'};
  if (c.running) {
    status(`cell ${i + 1} is already running`, 'err');
    return {ok: false, error: `cell ${i + 1} is already running`};
  }
  const runPath = lee.path, cellId = c.id;
  let res = {ok: true, error: ''};
  const v = ensureCellMounted(i);
  const src = v ? LeeCM.getDoc(v) : c.source;
  const el = $(`.lee-cell[data-i="${i}"]`);
  if (c.cell_type === 'markdown') showRenderedMarkdown(c, true);
  else if (c.cell_type === 'prompt') {
    c.running = true;
    try { await askCell(i, src, el); }
    finally { c.running = false; }
  } else {
    // Code run from a file-backed notebook has to be visible to code that reads that notebook
    // during the cell, such as indexers, nbdev and papermill. Flush the whole browser document
    // first, or a newly created .ipynb is still zero-byte on disk while its cell runs.
    // `saveTab` has already said why, in the status line or the conflict dialog. Repeating a
    // generic `save the notebook` over the top of it hid the only diagnosable part.
    if (lee.path && $('.lee-tab.active.dirty') && !await saveTab(true)) return {ok: false, error: 'the notebook could not be saved first'};
    const began = performance.now();
    c.running = true;
    el?.classList.add('running');
    setCellState(c, 'running');
    setCellTime(c, 0, true);
    const cellClock = setInterval(() => setCellTime(c, performance.now() - began, true), 100);
    $('#g-' + c.id).textContent = '[*]';
    status(`running cell ${i + 1}…`);
    try {
      let r = null;
      await postEvents('/nb/run/stream', {i, id: cellId, path: runPath || lee.tabKey || '', source: src}, (event, data) => {
        const stillHere = lee.path === runPath && lee.cells[i]?.id === cellId;
        if (!stillHere) return;
        if (event === 'output') {
          lee.cells[i].outputs = data.outputs || [];
          renderOutputs(lee.cells[i]); cellOutputEvent(cellId, lee.cells[i].outputs);
        } else if (event === 'error') throw new Error(data.text || 'cell execution failed');
        else if (event === 'done') r = data;
      });
      if (!r) throw new Error('cell execution ended without a result');
      const stillHere = lee.path === runPath && lee.cells[i]?.id === cellId;
      if (!stillHere) {
        c.running = false; el?.classList.remove('running'); leeVars();
        return {ok: false, error: 'the notebook changed while the cell ran'};
      }
      // Preserve the mounted cell object and its editor relationship.
      Object.assign(c, r.cell);
      renderOutputs(r.cell); cellOutputEvent(cellId, c.outputs || []);
      LeeCM.setInlineValues(v, r.inline || []);
      if (r.result) requestAnimationFrame(() => openValueLens(r.result, $('#out-' + c.id) || el, 'expression result'));
      $('#g-' + c.id).textContent = '[' + (r.cell.execution_count ?? ' ') + ']';
      const elapsed = Number(c.execution_ms ?? (performance.now() - began));
      const duration = formatCellTime(elapsed);
      setCellTime(c, elapsed, false);
      setCellState(c, r.ok ? 'done' : 'error', r.ok ? `ran successfully in ${duration}` : `failed after ${duration}`);
      status(r.ok ? `cell ${i + 1} ran in ${duration}` : `cell ${i + 1} failed after ${duration}`,
             r.ok ? 'ok' : 'err');
      res = {ok: !!r.ok, error: r.ok ? '' : `cell ${i + 1} failed after ${duration}`};
    } catch (e) {
      const elapsed = performance.now() - began;
      c.execution_ms = elapsed; setCellTime(c, elapsed, false);
      setCellState(c, 'error', `run failed after ${formatCellTime(elapsed)}`);
      status(String(e.message || e), 'err');
      res = {ok: false, error: String(e.message || e)};
    } finally { clearInterval(cellClock); }
    c.running = false;
    el?.classList.remove('running');
    // A run rewrites the outputs, which is a change to the document, and only typing used to
    // schedule a save. Saved here rather than marked dirty: marking it left the notebook to the
    // autosave delay, and the next run flushed it on the way in, so every cell wrote the whole file
    // twice. Once a run has saved it, the next run finds nothing to flush.
    if (lee.path === runPath && autoSaveEnabled()) saveTab(true).catch(() => {});
    leeVars();
  }
  if (advance === 'insert') { await nbEdit({op: 'insert', i: i + 1}); focusCell(i + 1); }
  else if (advance) { if (i + 1 < lee.cells.length) focusCell(i + 1); else { await nbEdit({op: 'insert', i: i + 1}); focusCell(i + 1); } }
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
        selectCell(i); const view = ensureCellMounted(i);
        LeeCM.setDebugLine(view, frame.line); paintDebugInlineValues(view, frame.line, state.variables); jumpToLine(frame.line);
      }
    } else {
      const view = lee.editors.get('file');
      if (view) { LeeCM.setDebugLine(view, frame.line); paintDebugInlineValues(view, frame.line, state.variables); jumpToLine(frame.line); }
    }
    return;
  }
  // Library frames are outside the workspace sandbox. Ask by frame id, never by a browser path,
  // and show a read-only source view so step-in stays useful.
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
  const view = ensureCellMounted(i), source = LeeCM.getDoc(view);
  let breakpoints = lee.breakpoints.get(c.id) || [];
  if (!breakpoints.length) {
    breakpoints = [LeeCM.lineOf(view)]; rememberBreakpoints(c.id, breakpoints);
    LeeCM.setBreakpoints(view, breakpoints);
  }
  lee.debugCell = i; c.running = true; setCellState(c, 'running');
  status(`starting ipykernel debugger for cell ${i + 1}…`);
  let done = null;
  try {
    await postEvents('/nb/debug/stream', {i, id: c.id, path: lee.path || lee.tabKey || '', source, breakpoints}, (event, data) => {
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
    });
    if (done?.cell) {
      Object.assign(c, done.cell); renderOutputs(c);
      $('#g-' + c.id).textContent = '[' + (c.execution_count ?? ' ') + ']';
      setCellState(c, done.ok ? 'done' : 'error');
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

