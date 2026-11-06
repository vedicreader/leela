const diffHtml = (rows) => rows.map(r =>
  `<div class="lee-drow ${r.kind}"><span class="lee-dnum">${r.line || ''}</span>` +
  (r.html ? `<span class="lee-dtext hl">${r.html}</span></div>` : `<span class="lee-dtext">${esc(r.text)}</span></div>`)).join('');

function diffModal(title, label, rows) {
  return modal(`<div class="lee-mhead">${esc(title)}<span class="sub">${esc(label)}</span></div>
                <div class="lee-diff">${diffHtml(rows)}</div>`);
}

/* Local history. Undo is one step back, and after an agent, a tool or another editor has been
   through the tree the question is what the file said an hour ago. Every version Leela saw is
   kept, and this is where one gets picked. */
async function leeLocalHistory(path = lee.path) {
  if (!path) return status('open a file to see its history', 'err');
  let d;
  try { d = await api('/history/file?path=' + encodeURIComponent(path)); }
  catch (e) { return status(String(e.message || e), 'err'); }
  const versions = d.versions || [], name = path.split('/').pop();
  const m = modal(`<div class="lee-mhead">local history<span class="sub">${esc(name)}</span></div>` +
    `<div class="lee-lh"><nav class="lee-lh-list" id="lhrows" aria-label="kept versions"></nav>` +
    `<div class="lee-lh-view" id="lhview"></div></div>`, null, null, {storageKey: 'localhistory'});
  const rows = $('#lhrows', m), view = $('#lhview', m);
  if (!versions.length) {
    view.innerHTML = '<div class="lee-dim">Nothing kept for this file yet. A save, an agent edit, ' +
      'or a write from outside Leela starts its history.</div>';
    return;
  }
  const when = at => new Date((at || 0) * 1000).toLocaleString();
  rows.innerHTML = versions.map((v, i) =>
    `<button type="button" class="lee-lh-row${i ? '' : ' active'}" data-version="${esc(v.id)}">` +
    `<strong>${esc(v.label)}</strong><span>${esc(when(v.at))} · ${Number(v.bytes || 0).toLocaleString()} bytes` +
    `</span></button>`).join('');
  const show = async id => {
    $$('[data-version]', m).forEach(b => b.classList.toggle('active', b.dataset.version === id));
    view.innerHTML = '<div class="lee-dim">reading…</div>';
    let held;
    try { held = await api('/history/version?id=' + encodeURIComponent(id)); }
    catch (e) { view.innerHTML = `<div class="lee-err">${esc(String(e.message || e))}</div>`; return; }
    view.innerHTML = `<header class="lee-lh-head"><span>${esc(held.label)} · ${esc(when(held.at))}</span>` +
      `<span class="lee-spacer"></span>` +
      `<button type="button" class="lee-btn go" data-restore="${esc(id)}">restore this version</button></header>` +
      ((held.rows || []).length ? `<div class="lee-diff">${diffHtml(held.rows)}</div>`
        : '<div class="lee-dim">identical to what is on disk now</div>');
  };
  m.addEventListener('click', async e => {
    const pick = e.target.closest('[data-version]');
    if (pick) return show(pick.dataset.version);
    const back = e.target.closest('[data-restore]');
    if (!back) return;
    back.disabled = true;
    try {
      const out = await post('/history/restore', {id: back.dataset.restore});
      m.remove();
      await post('/tab/reload', {path: out.path});
      await mountTab(out.path);
      status(`${out.path.split('/').pop()} restored · ${out.label || 'from local history'}`, 'ok');
    } catch (err) { back.disabled = false; status(String(err.message || err), 'err'); }
  });
  show(versions[0].id);
}
window.leeLocalHistory = leeLocalHistory;

// The dirty dot says that a tab changed. This says what changed, before a save or after something
// moved the file underneath.
function bufferBody() {
  return lee.kind === 'notebook'
    ? {cells: lee.cells.map((c, i) => ({i, id: c.id, seq: nextSeq(), source: lee.editors.has(c.id) ? LeeCM.getDoc(lee.editors.get(c.id)) : c.source}))}
    : {text: lee.editors.has('file') ? LeeCM.getDoc(lee.editors.get('file')) : ''};
}

async function showDiff() {
  if (!lee.kind) return status('nothing open', 'err');
  const d = await post('/diff', {path: lee.tabKey, ...bufferBody()});
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
      merges[i] = createMerge($(`[data-cell-merge="${i}"]`, m), {left: disk.cells?.[i]?.source || '', right: draft,
        lang: lee.cells[i]?.cell_type === 'markdown' ? 'markdown' : nbLang(), settings: lee.editorPrefs});
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
      if (added.length && !await nbEdit({op:'paste_many', i:lee.cells.length, cells:added})) return;
      m.remove(); await saveTab(false, null, true); status('merged notebook saved', 'ok');
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
  mergeView = createMerge($('.lee-merge-host', m), {left: disk.text || '', right: draft,
    lang: curLang(), settings: lee.editorPrefs});
  $('[data-cancel]', m).onclick = () => m.remove();
  $('[data-save-merge]', m).onclick = async () => {
    const result = LeeCM.mergeResult(mergeView), view = lee.editors.get('file');
    LeeCM.setDoc(view, result); rememberBuffer(lee.path, {path: lee.path, kind: 'text', text: result});
    m.remove(); await saveTab(false, null, true); status('merged file saved', 'ok');
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
  // A document the browser renders has no editor behind it, so `getDoc` would be called on
  // nothing. Reporting success is honest: the file on disk is what is being shown.
  if (['pdf', 'image', 'office', 'audio', 'video'].includes(lee.kind)) {
    if (!quiet) status(`${{pdf: 'a PDF', image: 'an image', office: 'an office file', audio: 'an audio file', video: 'a video'}[lee.kind]} is read-only here`);
    return true;
  }
  let saveTabEl = $('.lee-tab.active');
  setTabSaveState(saveTabEl, 'saving');
  try {
    if (lee.activeEditor==='secondary' && lee.editors.get('secondary') && lee.secondaryPath) {
      const path=lee.secondaryPath,base_disk_version=draftBaseFor(path);
      const d=await post('/nb/save',{path,text:normalizeSavedText(LeeCM.getDoc(lee.editors.get('secondary'))),seq:nextSeq(),base_disk_version,force});
      noteSelfWrite(path);
      // Without this the pane saved and learned nothing, so the next edit began from the same
      // stale base and was refused all over again.
      await rebaseDrafts(path, recordDiskVersion(path, d.disk_version || diskVersionFor(path)));
      lee.buffers.delete(path);lee.dirtyBuffers.delete(path);await clearDrafts(path);
      saveTabEl = $$('.lee-tab').find(x=>x.title===path); saveTabEl?.classList.remove('dirty');
      setTabSaveState(saveTabEl, 'saved');
      if(!quiet)status(`saved ${path.split('/').pop()}`,'ok');return true;
    }
    // The tab being saved, held: a switch while the save is out must not clear the next tab's state.
    const tabKey = lee.tabKey, kind = lee.kind, cellKey = tabKey + ':';
    const edits = () => lee.tabEdits.get(tabKey) || 0;
    let editAt = expectedVersion ?? lee.editVersion, tabAt = edits();
    const bufferKeys = kind === 'notebook'
      ? [...lee.bufferTimers.keys()].filter(k => k.startsWith(cellKey))
      : [lee.path || $('.lee-tab.active .lee-tab-name')?.textContent || ''];
    for (const k of bufferKeys) { clearTimeout(lee.bufferTimers.get(k)); lee.bufferTimers.delete(k); }
    let d;
    const documentKey = lee.path || $('.lee-tab.active .lee-tab-name')?.textContent || '';
    const base_disk_version = draftBaseFor(documentKey);
    if (kind === 'notebook') {
      const seq = nextSeq(), cells = lee.cells.map((c, i) => ({i, id: c.id, seq, source: lee.editors.has(c.id) ? LeeCM.getDoc(lee.editors.get(c.id)) : c.source}));
      await headingSynced(tabKey);
      d = await post('/nb/save', {tab: tabKey, cells, base_disk_version, force});
    } else {
      let text=normalizeSavedText(LeeCM.getDoc(lee.editors.get('file')));
      if(lee.filePrefs.formatOnSave){try{const formatted=await post('/editor/format',{path:lee.path,lang:curLang(),text});text=formatted.text;if(text!==LeeCM.getDoc(lee.editors.get('file')))LeeCM.setDoc(lee.editors.get('file'),text);editAt=expectedVersion??lee.editVersion;tabAt=edits();}catch(e){status(`format skipped: ${e.message||e}`,'err');}}
      d = await post('/nb/save', {tab: tabKey, text, seq: nextSeq(), base_disk_version, force});
    }
    const written = recordDiskVersion(documentKey, d.disk_version || diskVersionFor(documentKey));
    // A keystroke, fold or edit made while the save was out is not in what it wrote: the disk has its
    // snapshot, the tab stays dirty, and the newer draft is rebased on our own write so the next save
    // is not mistaken for an external conflict.
    if ((expectedVersion !== null && editAt !== lee.editVersion) || tabAt !== edits()) {
      await rebaseDrafts(documentKey, written);
      setTabSaveState(saveTabEl, 'pending', 'Changed while saving; not saved yet');
      return false;
    }
    const key = documentKey;
    if (kind === 'notebook') {
      for (const k of [...lee.buffers.keys()]) if (k.startsWith(cellKey)) {
        lee.buffers.delete(k); lee.dirtyBuffers.delete(k);
      }
    } else { lee.buffers.delete(key); lee.dirtyBuffers.delete(key); }
    await clearDrafts(documentKey);
    lee.heldSaveConflicts.delete(documentKey);
    saveTabEl?.classList.remove('dirty');
    setTabSaveState(saveTabEl, 'saved');
    if (!quiet) status('saved', 'ok');
    noteSelfWrite(documentKey, lee.path);
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

/* Every JSON config here is written by a program and read by a person, so most arrive as one long
   line. The same formatter as format-on-save, asked for on purpose, editing the buffer rather than
   the file so it stays undoable. */
async function leeFormatDoc() {
  const view = lee.editors.get(lee.scope === 'exec' ? 'exec' : 'file');
  if (!view) return status('open a file to format', 'err');
  const text = LeeCM.getDoc(view), lang = curLang();
  try {
    const d = await post('/editor/format', {path: lee.path, lang, text});
    if (d.text === text) return status(`${lang} already formatted`, 'ok');
    LeeCM.setDoc(view, d.text);
    status(`formatted ${lang}${lee.path ? ' · ' + lee.path.split('/').pop() : ''} · save to keep it`, 'ok');
  } catch (e) { status(String(e.message || e), 'err'); }
}
window.leeFormatDoc = leeFormatDoc;

async function saveAllTabs() {
  // The active editor is saved through the same version-checked path as ordinary autosave.
  // Inactive editors are mirrored to the server within 120ms, and pending mirrors are left to
  // arrive rather than cancelled, which would save the previous snapshot.
  if (!lee.kind) return status('nothing to save', 'err');
  if (!lee.path) return status('save the unnamed tab individually first', 'err');
  const activeDirty = !!$('.lee-tab.active.dirty');
  if (activeDirty && !await saveTab(true)) return;
  await new Promise(resolve => setTimeout(resolve, 140));
  await Promise.all([...lee.headingSync.values(), lee.nbQueue]);   // folds and edits still out are in what it writes
  try {
    const d = await post('/tabs/save-all'), saved = d.saved + (activeDirty ? 1 : 0);
    for (const tab of $$('.lee-tab')) {
      if (tab.classList.contains('dirty')) await clearDrafts(tab.title || $('.lee-tab-name', tab)?.textContent || '');
      tab.classList.remove('dirty'); setTabSaveState(tab, 'saved');
    }
    status(`saved ${saved} tab${saved === 1 ? '' : 's'}`, 'ok');
  } catch (e) { status(e.message || String(e), 'err'); }
}

