/* Reloading the open tab is what makes an AI edit visible without a refresh, but only when there is
 * nothing of the user's to lose. A buffer with unsaved edits is offered with the diff instead, and
 * the choice is the user's. */
/* Taking the disk version remounts the tab, which destroys the CodeMirror the caret is in: an agent
   edit or a build landing between two keystrokes took the keystrokes with it, and typing looked
   like it had stopped working. Only the two reloads nobody asked for wait for the caret to leave.
   An explicit reload, a tab switch, a refactor and a conflict resolution all go straight through
   `takeDiskVersion`, because in every one of those a person asked for exactly this. */
const editorHasFocus = () => !!document.activeElement?.closest?.('.cm-editor');
/* `key` is what stops these stacking up: the 10s poll and the `/fs/events` push both reach
   `watchOpenFile`, and without it a minute of typing over a busy tree queues a dozen reloads that
   all fire the moment the caret leaves, remounting the tab a dozen times. */
const waitingReloads = new Set();
function whenEditorIdle(fn, key = '', tries = 40) {
  if (!editorHasFocus()) { waitingReloads.delete(key); return fn(); }
  if (key && tries === 40 && waitingReloads.has(key)) return;
  if (key) waitingReloads.add(key);
  // 20s of unbroken typing and this gives up; `watchOpenFile`'s own poll comes round again.
  if (tries > 0) setTimeout(() => whenEditorIdle(fn, key, tries - 1), 500);
  else waitingReloads.delete(key);
}
/* Agent tools that change an open notebook in the server's copy, not on disk, so the tab remounts from that copy. */
const NOTEBOOK_TOOLS = new Set(['run_cell', 'check_exercise', 'grade_exercise', 'add_demo', 'add_exercise']);
function scheduleAgentFileReload(path) {
  // An open notebook's agent edit is in the server's copy of the tab, with the person's unsaved edits, so a dirty tab remounts too.
  const held = () => lee.kind === 'notebook', dirty = () => $('.lee-tab.active')?.classList.contains('dirty');
  if (path !== lee.path || (!held() && dirty())) return;
  clearTimeout(lee.agentReloadTimer);
  lee.agentReloadTimer = setTimeout(() => whenEditorIdle(async () => {
    if (path !== lee.path || (!held() && dirty())) return;
    try {
      if (held()) { await lee.nbQueue; await mountTab(path); }
      else await takeDiskVersion(path);
      status(`${path.split('/').pop()} updated from the agent edit`, 'ok');
    } catch (e) { status(String(e.message || e), 'err'); }
  }, 'agent:' + path), 90);
}
async function watchOpenFile() {
  if (!lee.path || lee.watchingDisk || document.hidden) return;
  lee.watchingDisk = true;
  try {
    const d = await api('/tab/watch?path=' + encodeURIComponent(lee.path));
    if (!d || d.path !== lee.path || !lee.diskVersion) return;
    if (d.disk_version === lee.diskVersion) return;
    // Never advance the editor's base token while it is dirty. Doing so makes a missing IndexedDB
    // base fall back to the new disk version and turns an external write into our own. The old
    // token is what makes the save endpoint detect it. The diff command stays available, and a
    // clean editor follows agent, terminal and git writes live.
    if ($('.lee-tab.active')?.classList.contains('dirty')) {
      if (d.disk_version !== lee.seenDiskVersion)
        status(`${lee.path.split('/').pop()} changed on disk. Leela keeps your unsaved text.`, 'err');
      lee.seenDiskVersion = d.disk_version;
      return;
    }
    /* Deferred while the caret is in the editor, and `seenDiskVersion` is deliberately not advanced
       on this path: it is what tells the save endpoint an outside write happened, and moving it
       here would make the deferred change read as our own when the caret finally leaves. */
    const path = lee.path;
    whenEditorIdle(async () => {
      if (path !== lee.path || $('.lee-tab.active')?.classList.contains('dirty')) return;
      try { await takeDiskVersion(path); status(`${path.split('/').pop()} updated from disk`, 'ok'); }
      catch (_) { /* the next poll tries again */ }
    }, 'watch:' + path);
  } catch (_) {
    // Watching is convenience; a transient request failure should not interrupt editing.
  } finally { lee.watchingDisk = false; }
}

/* Every tab holding one of `paths`, not only the one on screen. `/fs/events` and `/tab/watch` both
   report the active tab alone, so a file restored under a background tab had no way to be heard
   about: the copy from before sat in `lee.buffers` and in the server's document store until the
   next `/tabs/save-all` wrote it back over the file that had just been restored.

   The server decides what it dropped, and only those are cleared here: a tab with unsaved edits is
   held rather than silently discarded, and comes back in `held` for the caller to report. */
async function forgetDiskVersions(paths, force = false) {
  const want = [...new Set((paths || []).filter(Boolean))];
  if (!want.length) return {paths: [], held: []};
  const d = await post('/tab/reload', {paths: want, force});
  for (const path of d.paths || []) {
    lee.heldSaveConflicts.delete(path);
    // Remove any durable browser draft too, or `mountTab` restores the very buffer that was dropped.
    await clearDrafts(path);
    // A mirror still waiting to be posted would put the dropped text back on the copy just read.
    for (const key of new Set([...lee.buffers.keys(), ...lee.bufferTimers.keys()]))
      if (key === path || key.startsWith(path + ':')) {
        lee.buffers.delete(key); lee.dirtyBuffers.delete(key);
        clearTimeout(lee.bufferTimers.get(key)); lee.bufferTimers.delete(key);
      }
  }
  return d;
}
// Accepting disk for the tab on screen is explicit, so it takes what is there over unsaved edits.
async function takeDiskVersion(path) {
  await forgetDiskVersions([path], true);
  await mountTab(path);
}
/* What a rollback owes every tab holding a file it restored: the one on screen is remounted, and
   the rest read from disk when they are next shown. Returns the paths it would not touch. */
async function reloadRestored(paths) {
  const d = await forgetDiskVersions(paths);
  if ((d.paths || []).includes(lee.path)) await mountTab(lee.path);
  return d.held || [];
}
async function leeReloadFromDisk() {
  const name = (lee.path || '').split('/').pop();
  if (!lee.path) return status('this tab has no file on disk', 'err');
  if ($('.lee-tab.active')?.classList.contains('dirty') &&
      !await confirmDialog(`reload ${name}`, 'This drops the unsaved edits in this tab and loads what is on disk.', 'reload')) return;
  try { await takeDiskVersion(lee.path); status(`${name} reloaded from disk`, 'ok'); }
  catch (e) { status(String(e.message || e), 'err'); }
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
  bar.querySelector('#dkeep').onclick = () => { m.remove(); status(`kept your text. ${displayChord('mod+s')} writes it over the file`, 'ok'); };
}

async function stopAgent() {
  const d = await post('/agent/stop', {thread: lee.agentThread || ''});
  updateAgentRunstrip({runs: (await api(`/agent/runs${agentThreadQuery()}`)).runs});
  status(d.ok ? d.state : d.error, d.ok ? 'ok' : 'err');
}

/* Failures with nowhere else to go: a compaction the engine refused, a completion that came back
 * empty, anything the native model layer printed instead of raising. They appear in the agent pane
 * because that is where the turn they belong to is. */
function showProblems(ps, host = null) {
  for (const p of (ps || [])) {
    if (lee.shownProblems.has(p)) continue;
    lee.shownProblems.add(p);
    agentLog(`<div class="lee-runline err"><span class="res">⚠ ${esc(p)}</span></div>`, host);
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

