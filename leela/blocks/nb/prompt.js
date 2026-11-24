/* What the agent did to the notebook during a prompt, put on the page without a remount. Goes through `lee.nbQueue` so it
   cannot interleave with a structural edit, and only while the tab it asked from is still the one mounted. Text typed
   into a cell since the server last confirmed it stays; a cell still running here keeps its run state and outputs.
   Resolves to the number of cells that changed, or null when nothing was applied. */
function adoptAgentCells(key, mounted, r, askedId) {
  const run = lee.nbQueue.then(() => {
    const here = lee.tabKey === key && lee.mountedAt === mounted && mounted === mountTabVersion;
    if (!r?.cells || !here || (r.version ?? Infinity) < (lee.nbVersions.get(key) ?? 0)) return null;
    const host = $('#editor'), before = lee.cells.slice(), old = new Map(before.map(c => [c.id, c]));
    const typed = id => { const v = lee.editors.get(id); return v ? LeeCM.getDoc(v) : old.get(id)?.source; };
    let clash = 0;
    const cells = r.cells.map(s => {
      const c = {...s}, was = old.get(c.id), base = lee.nbSeen.get(seenKey(key, c.id)), now = typed(c.id);
      if (now !== undefined && base !== undefined && now !== base) { if (c.source !== base && c.source !== now) clash++; c.source = now; }
      if (c.id === askedId) c.running = false;
      else if (was?.running) Object.assign(c, {running: true, outputs: was.outputs, execution_count: was.execution_count, execution_ms: was.execution_ms, fresh: was.fresh});
      else c.running = false;
      return c;
    });
    const sig = c => JSON.stringify([c.id, c.cell_type, c.source, c.id === askedId ? null : [c.outputs, c.execution_count]]);
    const changed = cells.filter((c, i) => !before[i] || sig(c) !== sig(before[i])).length + Math.max(0, before.length - cells.length);
    if (r.version != null) lee.nbVersions.set(key, r.version);
    noteSeen(key, r.cells);
    if (!changed) return 0;
    const selectedId = lee.cells[lee.sel]?.id, scrollTop = host?.scrollTop || 0;
    lee.cells = foldsSince(key, cells, r.version ?? 0);
    const same = cells.findIndex(c => c.id === selectedId); if (same >= 0) lee.sel = same;
    else lee.sel = Math.min(lee.sel, cells.length - 1);
    patchNotebook(host, before, cells, 'agent');
    if (host) host.scrollTop = scrollTop;
    if (clash) status('the agent and you both changed a cell · your text is kept until you save', 'err');
    markDirty();
    return changed;
  });
  lee.nbQueue = run.catch(() => {});
  return run;
}

/* After an error or Stop no `done` arrives, but cells the agent already added sit in the server's copy, and a save
   would write cells nobody saw. The held copy is read back and adopted the same way. */
async function resyncAgentCells(key, mounted, askedId) {
  try { const st = await api('/tab/state?path=' + encodeURIComponent(key)); if (st?.cells) await adoptAgentCells(key, mounted, st, askedId); }
  catch (_) {}
}

/* A prompt cell answers into the cell, so the reply saves with the notebook. Cells the agent changed arrive with the
   answer and are patched in; the tab is not re-mounted, since `/tab/state` would drop an answer not yet saved. */
async function askCell(i, src, el) {
  const c = lee.cells[i], runKey = lee.tabKey, cellId = c.id, mounted = lee.mountedAt;
  let synced = false;
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
    synced = true;
    const moved = await adoptAgentCells(runKey, mounted, r, cellId);
    const at = cur();
    if (!at) { leeVars(); return; }
    Object.assign(at, r.cell, {running: false});
    renderOutputs(at);
    for (const e of (r.edits || []))
      agentLog(`<div class="lee-runline"><span class="sub">✎ ${esc(e.path.split('/').pop())} ${esc(e.label)}</span></div>` +
               `<div class="lee-diff inline">${diffHtml(e.rows)}</div>`);
    // An edit to this notebook that reached the page is shown; one that did not went to disk around the tab.
    const here = !moved && (r.edits || []).some(e => e.path === lee.path);
    showProblems(r.problems);
    status((r.problems || []).length ? r.problems[r.problems.length - 1]
           : here ? 'this notebook also changed on disk. Your text stays until you save'
                  : moved ? `answered · ${moved} cell${moved === 1 ? '' : 's'} changed` : (r.note || 'answered'),
           r.ok && !here && !(r.problems || []).length ? 'ok' : 'err');
    markDirty();
    leeVars();
  } catch (e) {
    if (e?.name === 'AbortError') { const n = lee.cells.indexOf(cur()); status(n < 0 ? 'prompt cell stopped' : `prompt cell ${n + 1} stopped`, 'ok'); }
    else status(String(e.message || e), 'err');
  }
  finally {
    lee.promptRuns?.delete(cellId);
    if (!synced) await resyncAgentCells(runKey, mounted, cellId);
    if (clock) clearInterval(clock);
    const at = cur() || c;
    if (at.execution_ms == null) at.execution_ms = performance.now() - began;
    if (cur()) setCellTime(at, at.execution_ms, false);
    if (notice) notice.hidden = true;
  }
  if (cur()) $('#g-' + cellId).textContent = '✦';
  el?.classList.remove('running');
}
