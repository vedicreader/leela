/* ---------------------------------------------------------- running files */
/* The exec log is where anything run outside a notebook cell lands -- the exec box, a
 * selection, a whole file. One place to look for "what have I asked this kernel to do". */
function execLine(code, text, ok) {
  const log = $('#execlog'); if (!log) return;
  const line = document.createElement('div');
  line.className = 'lee-runline' + (ok ? '' : ' err');
  line.innerHTML = `<span class="code">${esc(code)}</span><span class="arrow">→</span>` +
                   `<span class="res">${esc((text || 'ok').trim())}</span>`;
  log.appendChild(line); log.scrollTop = log.scrollHeight;
}

/* Run the open .py as a script, in the tab's own kernel: `__main__`, an argv, and a
 * traceback that points at the file -- but with everything it defines left in the
 * namespace the variable panel is watching, which a subprocess could not do. */
async function runFile() {
  if (lee.kind !== 'text') return status('this is a notebook — run its cells, or “▶ all”', 'err');
  if (lee.path && $('.lee-tab.active.dirty') && !await saveTab(true))
    return status('save the file before running it', 'err');
  const v = lee.editors.get('file');
  const name = (lee.path || '').split('/').pop();
  status('running ' + name + '…');
  const r = await post('/run/file', {text: v ? LeeCM.getDoc(v) : null});
  execLine('▶ ' + r.label, r.text, r.ok);
  status(r.ok ? r.label + ' finished' : r.label + ' raised — see the exec log', r.ok ? 'ok' : 'err');
  leeVars();
}

/* Just the selected code. Read straight off the CodeMirror state rather than through
 * `LeeCM`: the bundle in static/ is committed and rebuilding it needs node, so the client
 * does not grow a dependency on a wrapper function that is not in the shipped build. */
async function runSelection() {
  const v = curEditor();
  if (!v) return status('put the cursor in some code first', 'err');
  const s = v.state.selection.main;
  const code = s.empty ? '' : v.state.doc.sliceString(s.from, s.to);
  if (!code.trim()) return status('select some code first', 'err');
  const r = await post('/run/code', {code});
  const head = code.trim().split('\n')[0].slice(0, 60);
  execLine(head + (code.trim().includes('\n') ? ' …' : ''), r.text, r.ok);
  status(r.ok ? 'ran the selection' : 'the selection raised — see the exec log', r.ok ? 'ok' : 'err');
  leeVars();
}

/* Execute a bounded notebook range in order. Range commands deliberately run code cells
 * only: “run above” must not unexpectedly send every prompt cell above it to a model. */
async function runRange(start, end, label) {
  if (lee.kind !== 'notebook') return runFile();
  start = Math.max(0, start); end = Math.min(end, lee.cells.length);
  for (let i = start; i < end; i++) {
    const c = lee.cells[i];
    if (c.cell_type !== 'code' || !(c.source || '').trim()) continue;
    status(`running cell ${i + 1}…`);
    await runCell(i, false);
    if ((lee.cells[i].outputs || []).some(o => o.output_type === 'error'))
      return status(`cell ${i + 1} raised — stopped there`, 'err');
  }
  status(`ran ${label}`, 'ok');
}

async function runAll() {
  return runRange(0, lee.cells.length, 'every cell');
}

async function restartRunAll() {
  if (lee.kind !== 'notebook') return runFile();
  status('restarting kernel…');
  await post('/kernel/restart');
  markPreviousRuns();
  await runAll();
}

