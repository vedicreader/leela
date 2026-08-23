/* Running a prompt cell. The answer arrives in the cell rather than the pane below, so it saves
 * with the notebook and reads in order.
 *
 * The tab is deliberately not re-mounted afterwards, even though the assistant's tools may have
 * edited files: `/tab/state` reloads the notebook from disk, which would throw away the answer
 * that has not been saved yet. Files it changed are reported instead. */
async function askCell(i, src, el) {
  const c = lee.cells[i], runPath = lee.path, cellId = c.id;
  const notice = $('#model-' + c.id);
  const began = performance.now();
  let clock = null;
  el?.classList.add('running');
  $('#g-' + c.id).textContent = '…';
  if (notice) {
    notice.hidden = false;
    const tick = () => {
      const elapsed = performance.now() - began;
      const seconds = Math.floor(elapsed / 1000);
      setCellTime(c, elapsed, true);
      const time = notice.querySelector('.lee-running-time');
      if (time) time.textContent = seconds < 2 ? ' · starting' : ` · ${seconds}s elapsed`;
    };
    tick();
    clock = setInterval(tick, 1000);
  }
  status('model running…');
  try {
    let r = null, raw = '';
    const out = $('#out-' + c.id), seen = new Map();
    if (out) out.innerHTML = '<div class="lee-agent-steps lee-cell-agent-steps"></div><div class="lee-reply"></div>';
    await postEvents('/nb/ask/stream', {i, source: src}, (event, data) => {
      if (event === 'chunk') {
        raw += data.text || '';
        const reply = $('#out-' + c.id + ' .lee-reply');
        renderMarkdown(reply, raw);
      } else if (event === 'activity') {
        const steps = $('#out-' + c.id + ' .lee-agent-steps');
        let row = seen.get(data.id);
        if (!row && steps) { row = document.createElement('details'); steps.appendChild(row); seen.set(data.id, row); }
        if (row) renderAgentStep(row, data);
      } else if (event === 'approval') showApproval(data);
      else if (event === 'error') throw new Error(data.text || 'model failed');
      else if (event === 'done') r = data;
    });
    if (!r) throw new Error('the model stream ended without a result');
    if (lee.path !== runPath || lee.cells[i]?.id !== cellId) { leeVars(); return; }
    Object.assign(c, r.cell);
    renderOutputs(c);
    for (const e of (r.edits || []))
      agentLog(`<div class="lee-runline"><span class="sub">✎ ${esc(e.path.split('/').pop())} ${esc(e.label)}</span></div>` +
               `<div class="lee-diff inline">${diffHtml(e.rows)}</div>`);
    const here = (r.edits || []).some(e => e.path === lee.path);
    showProblems(r.problems);
    status((r.problems || []).length ? r.problems[r.problems.length - 1]
           : here ? 'this notebook also changed on disk — your buffer wins until you save'
                  : (r.note || 'answered'),
           r.ok && !here && !(r.problems || []).length ? 'ok' : 'err');
    markDirty();
    leeVars();
  } catch (e) { status(String(e.message || e), 'err'); }
  finally {
    if (clock) clearInterval(clock);
    if (c.execution_ms == null) c.execution_ms = performance.now() - began;
    setCellTime(c, c.execution_ms, false);
    if (notice) notice.hidden = true;
  }
  $('#g-' + c.id).textContent = '✦';
  el?.classList.remove('running');
}

