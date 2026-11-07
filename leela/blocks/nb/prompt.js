/* A prompt cell answers into the cell, so the reply saves with the notebook. The tab is not re-mounted afterwards:
 * `/tab/state` would reload from disk and drop an answer not yet saved. */
async function askCell(i, src, el) {
  const c = lee.cells[i], runKey = lee.tabKey, cellId = c.id;
  // The cell that was asked, wherever an insert, move or delete has put it; null once its tab is not shown.
  const cur = () => lee.tabKey === runKey ? lee.cells.find(x => x.id === cellId) : null;
  const notice = $('#model-' + cellId);
  const began = performance.now();
  let clock = null;
  el?.classList.add('running');
  $('#g-' + cellId).textContent = '…';
  if (notice) {
    notice.hidden = false;
    const tick = () => {
      const elapsed = performance.now() - began;
      const seconds = Math.floor(elapsed / 1000);
      const at = cur(); if (at) setCellTime(at, elapsed, true);
      const time = notice.querySelector('.lee-running-time');
      if (time) time.textContent = seconds < 2 ? ' · starting' : ` · ${seconds}s elapsed`;
    };
    tick();
    clock = setInterval(tick, 1000);
  }
  status('model running…');
  try {
    let r = null, raw = '';
    const seen = new Map();
    // An insert or move re-renders the cell, so its reply area is made again when it has gone.
    const area = (sel, fresh = false) => {
      const out = $('#out-' + cellId); if (!out) return null;
      if (fresh || !out.querySelector('.lee-reply')) seen.clear(), out.innerHTML = '<div class="lee-agent-steps lee-cell-agent-steps"></div><div class="lee-reply"></div>';
      return out.querySelector(sel);
    };
    area('.lee-reply', true);
    // Held so Stop can end the turn here as well as asking the agent to stop.
    lee.promptRuns = lee.promptRuns || new Map();
    const abort = new AbortController();
    lee.promptRuns.set(cellId, abort);
    await postEvents('/nb/ask/stream', {i, id: cellId, path: runKey, source: src, seq: nextSeq(), ...seenRow(runKey, cellId)}, (event, data) => {
      const shown = cur();
      if (event === 'chunk') {
        raw += data.text || '';
        const reply = shown && area('.lee-reply'); if (reply) renderMarkdown(reply, raw);
      } else if (event === 'activity') {
        const steps = shown && area('.lee-agent-steps');
        let row = seen.get(data.id);
        if (!row && steps) { row = document.createElement('details'); steps.appendChild(row); seen.set(data.id, row); }
        if (row) renderAgentStep(row, data);
      } else if (event === 'approval') showApproval(data);
      else if (event === 'error') throw new Error(data.text || 'model failed');
      else if (event === 'done') r = data;
    }, abort.signal);
    if (!r) throw new Error('the model stream ended without a result');
    const at = cur();
    if (!at) { leeVars(); return; }
    Object.assign(at, r.cell);
    renderOutputs(at);
    for (const e of (r.edits || []))
      agentLog(`<div class="lee-runline"><span class="sub">✎ ${esc(e.path.split('/').pop())} ${esc(e.label)}</span></div>` +
               `<div class="lee-diff inline">${diffHtml(e.rows)}</div>`);
    const here = (r.edits || []).some(e => e.path === lee.path);
    showProblems(r.problems);
    status((r.problems || []).length ? r.problems[r.problems.length - 1]
           : here ? 'this notebook also changed on disk. Your text stays until you save'
                  : (r.note || 'answered'),
           r.ok && !here && !(r.problems || []).length ? 'ok' : 'err');
    markDirty();
    leeVars();
  } catch (e) {
    if (e?.name === 'AbortError') { const n = lee.cells.indexOf(cur()); status(n < 0 ? 'prompt cell stopped' : `prompt cell ${n + 1} stopped`, 'ok'); }
    else status(String(e.message || e), 'err');
  }
  finally {
    lee.promptRuns?.delete(cellId);
    if (clock) clearInterval(clock);
    const at = cur() || c;
    if (at.execution_ms == null) at.execution_ms = performance.now() - began;
    if (cur()) setCellTime(at, at.execution_ms, false);
    if (notice) notice.hidden = true;
  }
  if (cur()) $('#g-' + cellId).textContent = '✦';
  el?.classList.remove('running');
}
