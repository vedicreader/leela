/* Reloading the open tab is what makes an AI edit visible without a refresh -- but only
 * when there is nothing of the user's to lose. Typing while the model thinks is normal,
 * and a buffer with unsaved edits is not something to overwrite silently just because
 * the model happened to reach the same file. So that case is offered, with the diff, and
 * the choice is the user's. */
function scheduleAgentFileReload(path) {
  if (path !== lee.path || $('.lee-tab.active')?.classList.contains('dirty')) return;
  clearTimeout(lee.agentReloadTimer);
  lee.agentReloadTimer = setTimeout(async () => {
    if (path !== lee.path || $('.lee-tab.active')?.classList.contains('dirty')) return;
    try { await takeDiskVersion(path); status(`${path.split('/').pop()} updated from the agent edit`, 'ok'); }
    catch (e) { status(String(e.message || e), 'err'); }
  }, 90);
}
async function watchOpenFile() {
  if (!lee.path || lee.watchingDisk || document.hidden) return;
  lee.watchingDisk = true;
  try {
    const d = await api('/tab/watch');
    if (!d || d.path !== lee.path || !lee.diskVersion) return;
    if (d.disk_version === lee.diskVersion) return;
    // Never advance the editor's base token while it is dirty. Doing so makes a missing
    // IndexedDB base fall back to the *new* disk version and silently turns an external
    // write into our own. The old token is exactly what makes the save endpoint detect it.
    // Never destroy typing that has not reached disk. The diff command remains available,
    // while a clean editor follows agent, terminal, git, and other external writes live.
    if ($('.lee-tab.active')?.classList.contains('dirty')) {
      if (d.disk_version !== lee.seenDiskVersion)
        status(`${lee.path.split('/').pop()} changed on disk — keeping your unsaved buffer`, 'err');
      lee.seenDiskVersion = d.disk_version;
      return;
    }
    await takeDiskVersion(lee.path);
    status(`${lee.path.split('/').pop()} updated from disk`, 'ok');
  } catch (_) {
    // Watching is convenience; a transient request failure should not interrupt editing.
  } finally { lee.watchingDisk = false; }
}

async function takeDiskVersion(path) {
  lee.heldSaveConflicts.delete(path);
  // Accepting disk is explicit. Remove any durable browser draft first so mountTab cannot
  // faithfully restore the very buffer the user chose to discard.
  await clearDrafts(path);
  // Clear both client and server document caches. The following mount therefore reads the
  // bytes the tool just wrote rather than replaying the notebook object from before the turn.
  for (const key of [...lee.buffers.keys()])
    if (key === path || key.startsWith(path + ':')) {
      lee.buffers.delete(key); lee.dirtyBuffers.delete(key);
    }
  await post('/tab/reload', {path});
  await mountTab();
}
async function reloadAfterEdits(edits) {
  const e = edits.find(x => x.path && x.path === lee.path);
  if (!e) return;
  if (!$('.lee-tab.active')?.classList.contains('dirty')) {
    await takeDiskVersion(e.path);
    return status(`${e.path.split('/').pop()} updated from the agent edit`, 'ok');
  }
  const m = diffModal(e.path.split('/').pop() + ' changed on disk', e.label, e.rows);
  const bar = document.createElement('div');
  bar.className = 'lee-mfoot';
  bar.innerHTML = '<button class="lee-btn" id="dtake">reload from disk</button>' +
                  '<button class="lee-btn" id="dkeep">keep my buffer</button>' +
                  '<span class="lee-dim">you have unsaved edits in this tab</span>';
  m.querySelector('.lee-modalbox').appendChild(bar);
  bar.querySelector('#dtake').onclick = async () => {
    m.remove(); await takeDiskVersion(e.path); status('loaded the agent edit from disk', 'ok');
  };
  bar.querySelector('#dkeep').onclick = () => { m.remove(); status('kept your buffer — ctrl+s overwrites', 'ok'); };
}

async function stopAgent() {
  const d = await post('/agent/stop', {});
  updateAgentRunstrip({runs: (await api('/agent/runs')).runs});
  status(d.ok ? d.state : d.error, d.ok ? 'ok' : 'err');
}

/* Failures with nowhere else to go: a compaction the engine refused, a completion that
 * came back empty, anything the native model layer printed instead of raising. They land
 * in the agent pane because that is where the turn they belong to is. */
function showProblems(ps) {
  for (const p of (ps || [])) {
    if (lee.shownProblems.has(p)) continue;
    lee.shownProblems.add(p);
    agentLog(`<div class="lee-runline err"><span class="res">⚠ ${esc(p)}</span></div>`);
  }
}

async function agentTools() {
  const d = await api('/agent/status');
  const rows = (d.calls || []).map(c => `${c.tool}(${c.args})`).join('\n');
  agentLog(`<div class="lee-runline"><span class="sub">${esc(d.note)} · ${d.ntools} tools` +
           `${d.busy ? ' · thinking now' : ''} · context ${Math.round(100 * (d.pct_full || 0))}% full` +
           `${d.compactions ? ' · ' + d.compactions + ' compaction(s)' : ''}</span></div>` +
           (rows ? `<div class="lee-runline"><span class="code">${esc(rows)}</span></div>` : ''));
  showProblems(d.problems);
}

