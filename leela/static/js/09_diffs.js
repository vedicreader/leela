/* ------------------------------------------------------------------ diffs */
const diffHtml = (rows) => rows.map(r =>
  `<div class="lee-drow ${r.kind}"><span class="lee-dnum">${r.line || ''}</span>` +
  `<span class="lee-dtext">${esc(r.text)}</span></div>`).join('');

function diffModal(title, label, rows) {
  return modal(`<div class="lee-mhead">${esc(title)}<span class="sub">${esc(label)}</span></div>
                <div class="lee-diff">${diffHtml(rows)}</div>`);
}

// The dirty dot says *that* a tab changed. This says what changed -- the question
// actually worth answering before a save, or after something moved the file underneath.
function bufferBody() {
  return lee.kind === 'notebook'
    ? {cells: lee.cells.map((c, i) => ({i, source: lee.editors.has(c.id) ? LeeCM.getDoc(lee.editors.get(c.id)) : c.source}))}
    : {text: lee.editors.has('file') ? LeeCM.getDoc(lee.editors.get('file')) : ''};
}

async function showDiff() {
  if (!lee.kind) return status('nothing open', 'err');
  const d = await post('/diff', bufferBody());
  if (!d.rows.length) return status('no unsaved changes', 'ok');
  status(`${d.label} unsaved`, 'ok');
  diffModal('unsaved changes — ' + d.title, d.label, d.rows);
}

async function openMergeConflict(conflictBox) {
  if (!lee.path) return status('save the document before merging it', 'err');
  const disk = await api('/tab/disk?path=' + encodeURIComponent(lee.path));
  if (lee.kind === 'notebook') {
    conflictBox?.remove(); const merges = [];
    const count = Math.max(lee.cells.length, (disk.cells || []).length);
    const m = modal(`<div class="lee-mhead">Resolve notebook conflict<span class="sub">cell-aware disk / draft merge</span></div>` +
      `<div class="lee-notebook-merge">${Array.from({length: count}, (_, i) => `<section><header>Cell ${i + 1} · ${esc(lee.cells[i]?.cell_type || disk.cells?.[i]?.cell_type || 'code')}</header><div data-cell-merge="${i}"></div></section>`).join('')}</div>` +
      `<div class="lee-mfoot"><span class="lee-dim">Disk is left; the result saved to the notebook is right.</span><span class="lee-spacer"></span><button class="lee-btn" data-cancel>cancel</button><button class="lee-btn go" data-save-merge>save merged notebook</button></div>`,
      null, () => merges.forEach(LeeCM.destroyMerge), {className:'lee-merge-modal', storageKey:'notebook-merge'});
    for (let i = 0; i < count; i++) {
      const view = lee.cells[i] && lee.editors.get(lee.cells[i].id);
      const draft = view ? LeeCM.getDoc(view) : (lee.cells[i]?.source || '');
      merges[i] = LeeCM.createMerge($(`[data-cell-merge="${i}"]`, m), {left: disk.cells?.[i]?.source || '', right: draft,
        lang: lee.cells[i]?.cell_type === 'markdown' ? 'markdown' : 'python', settings: lee.editorPrefs});
    }
    $('[data-cancel]', m).onclick = () => m.remove();
    $('[data-save-merge]', m).onclick = async () => {
      for (let i = 0; i < Math.min(lee.cells.length, merges.length); i++) {
        const source = LeeCM.mergeResult(merges[i]); lee.cells[i].source = source;
        const view = lee.editors.get(lee.cells[i].id); if (view) LeeCM.setDoc(view, source);
      }
      const added = merges.slice(lee.cells.length).map((merge, n) => ({
        source: LeeCM.mergeResult(merge), cell_type: disk.cells?.[lee.cells.length + n]?.cell_type || 'code',
        metadata: {}, outputs: [], execution_count: null})).filter(cell => cell.source);
      if (added.length) await nbEdit({op:'paste_many', i:lee.cells.length, cells:added});
      m.remove(); await saveTab(false, disk.disk_version, true); status('merged notebook saved', 'ok');
    };
    return;
  }
  const draft = LeeCM.getDoc(lee.editors.get('file'));
  conflictBox?.remove();
  let mergeView = null;
  const m = modal(`<div class="lee-mhead">Resolve file conflict<span class="sub">disk on the left · editable result on the right</span></div>` +
    `<div class="lee-merge-host"></div><div class="lee-mfoot"><span class="lee-dim">Use the arrows to accept disk changes into your result.</span>` +
    `<span class="lee-spacer"></span><button class="lee-btn" data-cancel>cancel</button><button class="lee-btn go" data-save-merge>save merged result</button></div>`,
    null, () => { if (mergeView) LeeCM.destroyMerge(mergeView); }, {className: 'lee-merge-modal', storageKey: 'merge'});
  mergeView = LeeCM.createMerge($('.lee-merge-host', m), {left: disk.text || '', right: draft,
    lang: curLang(), settings: lee.editorPrefs});
  $('[data-cancel]', m).onclick = () => m.remove();
  $('[data-save-merge]', m).onclick = async () => {
    const result = LeeCM.mergeResult(mergeView), view = lee.editors.get('file');
    LeeCM.setDoc(view, result); rememberBuffer(lee.path, {path: lee.path, kind: 'text', text: result});
    m.remove(); await saveTab(false, disk.disk_version, true); status('merged file saved', 'ok');
  };
}
function showSaveConflict(message) {
  if ($('.lee-save-conflict')) return;
  const box = modal(`<div class="lee-mhead">File changed on disk</div>` +
    `<div class="lee-dialogcopy">${esc(message)} Your browser draft is safe and has not been replaced.</div>` +
    `<div class="lee-mfoot"><button class="lee-btn go" data-keep>keep draft</button>` +
    `<button class="lee-btn" data-merge>merge changes</button>` +
    `<button class="lee-btn warn" data-overwrite>overwrite disk</button>` +
    `<button class="lee-btn" data-disk>load disk version</button></div>`);
  box.classList.add('lee-save-conflict');
  $('[data-keep]', box).onclick = () => {
    lee.heldSaveConflicts.add(lee.path); box.remove();
    setTabSaveState($('.lee-tab.active'), 'pending', 'Draft kept; press Save to review the disk conflict again');
    status('kept browser draft · automatic retries paused until you save or resolve it', 'ok');
  };
  $('[data-merge]', box).onclick = () => openMergeConflict(box);
  $('[data-overwrite]', box).onclick = async () => { lee.heldSaveConflicts.delete(lee.path); box.remove(); await saveTab(false, null, true); };
  $('[data-disk]', box).onclick = async () => { lee.heldSaveConflicts.delete(lee.path); box.remove(); await takeDiskVersion(lee.path); status('loaded disk version; browser draft discarded', 'ok'); };
}
async function saveTab(quiet = false, expectedVersion = null, force = false) {
  // A document the browser renders has no editor behind it, so there is nothing to write and
  // `getDoc` would be called on nothing. Reporting success is honest here: the file on disk is
  // exactly what is being shown.
  if (lee.kind === 'pdf' || lee.kind === 'image') {
    if (!quiet) status(`${lee.kind === 'pdf' ? 'a PDF' : 'an image'} is read-only here`);
    return true;
  }
  let saveTabEl = $('.lee-tab.active');
  setTabSaveState(saveTabEl, 'saving');
  try {
    if (lee.activeEditor==='secondary' && lee.editors.get('secondary') && lee.secondaryPath) {
      const path=lee.secondaryPath,base_disk_version=draftBaseFor(path);
      const d=await post('/nb/save',{path,text:normalizeSavedText(LeeCM.getDoc(lee.editors.get('secondary'))),base_disk_version,force});
      lee.buffers.delete(path);lee.dirtyBuffers.delete(path);await clearDrafts(path);
      saveTabEl = $$('.lee-tab').find(x=>x.title===path); saveTabEl?.classList.remove('dirty');
      setTabSaveState(saveTabEl, 'saved');
      if(!quiet)status(`saved ${path.split('/').pop()}`,'ok');return true;
    }
    const bufferKeys = lee.kind === 'notebook'
      ? [...lee.bufferTimers.keys()].filter(k => k.startsWith((lee.path || 'scratch') + ':'))
      : [lee.path || $('.lee-tab.active .lee-tab-name')?.textContent || ''];
    for (const k of bufferKeys) { clearTimeout(lee.bufferTimers.get(k)); lee.bufferTimers.delete(k); }
    let d;
    const documentKey = lee.path || $('.lee-tab.active .lee-tab-name')?.textContent || '';
    const base_disk_version = draftBaseFor(documentKey);
    if (lee.kind === 'notebook') {
      const cells = lee.cells.map((c, i) => ({i, source: lee.editors.has(c.id) ? LeeCM.getDoc(lee.editors.get(c.id)) : c.source}));
      d = await post('/nb/save', {cells, base_disk_version, force});
    } else {
      let text=normalizeSavedText(LeeCM.getDoc(lee.editors.get('file')));
      if(lee.filePrefs.formatOnSave){try{const formatted=await post('/editor/format',{path:lee.path,lang:curLang(),text});text=formatted.text;if(text!==LeeCM.getDoc(lee.editors.get('file')))LeeCM.setDoc(lee.editors.get('file'),text);}catch(e){status(`format skipped: ${e.message||e}`,'err');}}
      d = await post('/nb/save', {text, base_disk_version, force});
    }
    // An autosave request may finish after another keystroke. The disk has its snapshot,
    // but the newer browser buffer must remain authoritative and schedule the next save.
    if (expectedVersion !== null && expectedVersion !== lee.editVersion) {
      // This request wrote an older snapshot, but newer typing is still in the editor and
      // IndexedDB. Rebase that draft on our own disk write so the follow-up autosave is not
      // mistaken for an external conflict.
      lee.diskVersion = d.disk_version || lee.diskVersion; lee.seenDiskVersion = lee.diskVersion;
      await rebaseDrafts(documentKey, lee.diskVersion);
      setTabSaveState(saveTabEl, 'pending', 'Newer changes are queued for autosave');
      return false;
    }
    lee.diskVersion = d.disk_version || lee.diskVersion; lee.seenDiskVersion = lee.diskVersion;
    const key = documentKey;
    if (lee.kind === 'notebook') {
      for (const k of [...lee.buffers.keys()]) if (k.startsWith((lee.path || 'scratch') + ':')) {
        lee.buffers.delete(k); lee.dirtyBuffers.delete(k);
      }
    } else { lee.buffers.delete(key); lee.dirtyBuffers.delete(key); }
    await clearDrafts(documentKey);
    lee.heldSaveConflicts.delete(documentKey);
    saveTabEl?.classList.remove('dirty');
    setTabSaveState(saveTabEl, 'saved');
    if (!quiet) status('saved', 'ok');
    refreshProjectPills();
    refreshOpenGitMarks();      // a notebook's marks are per cell, a file's per line
    if (lee.path?.endsWith('/pyproject.toml')) refreshPackageVersions();
    return true;
  } catch (e) {
    const message = String(e.message || e);
    setTabSaveState(saveTabEl, 'error', `Autosave failed: ${message}`);
    if (message.includes('changed on disk after this browser draft began')) {
      const documentKey = lee.path || $('.lee-tab.active .lee-tab-name')?.textContent || '';
      if (!quiet || !lee.heldSaveConflicts.has(documentKey)) showSaveConflict(message);
    }
    else status(message, 'err');
    return false;
  }
}

async function saveAllTabs() {
  // The active editor is saved through the same version-checked path as ordinary autosave.
  // Inactive editors are mirrored to the server within 120ms; let pending mirrors land
  // rather than cancelling their timers and accidentally saving the previous snapshot.
  if (!lee.kind) return status('nothing to save', 'err');
  if (!lee.path) return status('save the unnamed tab individually first', 'err');
  const activeDirty = !!$('.lee-tab.active.dirty');
  if (activeDirty && !await saveTab(true)) return;
  await new Promise(resolve => setTimeout(resolve, 140));
  try {
    const d = await post('/tabs/save-all'), saved = d.saved + (activeDirty ? 1 : 0);
    for (const tab of $$('.lee-tab')) {
      if (tab.classList.contains('dirty')) await clearDrafts(tab.title || $('.lee-tab-name', tab)?.textContent || '');
      tab.classList.remove('dirty'); setTabSaveState(tab, 'saved');
    }
    status(`saved ${saved} tab${saved === 1 ? '' : 's'}`, 'ok');
  } catch (e) { status(e.message || String(e), 'err'); }
}

