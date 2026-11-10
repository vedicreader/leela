const tabMounts = new Map(), tabHandlers = new Map(); let tabHostOff = [];
function registerTabHandlers(kind, on) { tabHandlers.set(kind, on); }
function registerTabMount(kind, mount, on) { tabMounts.set(kind, mount); if (on) registerTabHandlers(kind, on); }
// A kind's listeners on `#editor` are its own: the last kind's come off, and each runs only while its kind is on screen.
function bindTabHandlers(kind, host) {
  tabHostOff.splice(0).forEach(off => off());
  for (const [type, fn] of Object.entries(tabHandlers.get(kind) || {})) {
    const h = e => lee.kind === kind && fn(e); host.addEventListener(type, h); tabHostOff.push(() => host.removeEventListener(type, h));
  }
}

function updateToolbarForKind(kind) {
  const notebook = kind === 'notebook', text = kind === 'text';
  // `stop` interrupts the tab's kernel, and a document tab does not have one.
  const visibility = {run_cell: notebook, run_advance: notebook, run_file: text,
                      run_selection: text, interrupt: notebook || text};
  for (const [action, shown] of Object.entries(visibility)) {
    const button = $(`#toolbar [data-action="${action}"]`); if (button) button.hidden = !shown;
  }
  refreshMarkdownCellActions();   // whether a reply can become a cell depends on this tab
}

/* A save Leela made is not a change somebody else made. `/tabs/save-all` writes from the buffers the
   server holds, so the browser kept the version it had before that write: the next save read as
   `another process wrote it`, and the poll that watches the open file called it an outside edit and
   reloaded the tab. What was written comes back with the new version of each file, and both the
   editor's token and any draft that descends from it are moved on to it. */
function takeSavedVersions(d) {
  refreshKernelPill();
  const versions = (d && d.versions) || {};
  for (const [key, version] of Object.entries(versions)) {
    recordDiskVersion(key, version);
    rebaseDrafts(key, version);
  }
}

/* Background tabs' dots: lit for each the server holds unsaved, cleared only for each a save-all wrote. Never
   cleared from the strip alone, which has not seen a mirror still in flight or a draft not yet posted. */
function setTabDirt(titles, dirty) {
  for (const tab of $$('.lee-tab:not(.active)')) if (titles.has(tab.title)) { tab.classList.toggle('dirty', dirty); setTabSaveState(tab, dirty ? 'pending' : 'saved'); }
}
async function syncTabDirt() {
  const bar = new DOMParser().parseFromString(await (await fetch('/tab/bar')).text(), 'text/html');
  setTabDirt(new Set($$('.lee-tab.dirty', bar).map(t => t.title)), true);
}
let mountTabVersion=0;
function saveTabLocation() {
  const view = curEditor(), key = lee.path || lee.tabKey;
  if (!view || !key) return;
  // A Map keeps a re-set key at its first insertion point, so the delete is what moves the key to
  // the end for the tail slice below.
  lee.locations.delete(key);
  // Two scrollers, and only the inner one was kept. A notebook scrolls in `#editor`, and each cell's
  // CodeMirror is its own scroller sitting at zero, so coming back to a tab landed at the top.
  lee.locations.set(key, {pos: LeeCM.cursor(view), scroll: view.scrollDOM.scrollTop,
    host: $('#editor')?.scrollTop || 0,
    cell: lee.kind === 'notebook' ? lee.sel : -1});
  // Nothing else prunes this: a closed, renamed or deleted file leaves its entry behind, so the
  // cap is what keeps a long session and sessionStorage bounded.
  for (const stale of [...lee.locations.keys()].slice(0, lee.locations.size - 80)) lee.locations.delete(stale);
  try { localStorage.setItem('lee-tab-locations', JSON.stringify([...lee.locations])); } catch (_) {}
}
function restoreTabLocation(st, skip = false) {
  const key = st.path || st.title, loc = lee.locations.get(key);
  if (!loc || skip || lee.pendingLocation) return;
  requestAnimationFrame(() => {
    let view = lee.editors.get('file');
    if (st.kind === 'notebook' && loc.cell >= 0 && loc.cell < lee.cells.length) {
      selectCell(loc.cell); view = ensureCellMounted(loc.cell);
    }
    // The cells of a long notebook mount as they are reached, so the height the offset was taken
    // against arrives a frame late. Setting it twice lands on the second one.
    const host = $('#editor');
    if (host && loc.host) {
      host.scrollTop = loc.host;
      requestAnimationFrame(() => { if (host.scrollTop !== loc.host) host.scrollTop = loc.host; });
    }
    if (!view) return;
    LeeCM.setCursor(view, loc.pos); view.scrollDOM.scrollTop = loc.scroll || 0;
  });
}
async function mountTab(expectedPath = '') {
  saveTabLocation();
  dropTabReads();
  const hadPendingLocation = Boolean(lee.pendingLocation);
  const mountVersion=++mountTabVersion;
  lee.activeGitTab = '';
  if (lee.gitMergeView) { LeeCM.destroyMerge(lee.gitMergeView); lee.gitMergeView = null; }
  syncGitDiffTabs();
  // A queued autosave belongs to the tab being left, and cancelling it was all this did, so typing
  // and switching inside the delay left that tab dirty with nothing left to save it. The server
  // holds a buffer for every tab, so it persists what is dirty, once the last mirror has landed.
  clearTimeout(lee.autoSaveTimer);
  // The strip just swapped in is the server's, which has not yet seen a fold or edit still out for the tab
  // being left. Those land first, then the strip says what the server holds and the save goes by that.
  const leaving = lee.tabKey;
  setTimeout(() => Promise.all([headingSynced(leaving), lee.nbQueue]).then(syncTabDirt)
    .then(() => autoSaveEnabled() && !lee.observer && ($('.lee-tab.dirty:not(.untitled)') || lee.bufferTimers.size) && post('/tabs/save-all')
      .then(d => { takeSavedVersions(d); setTabDirt(new Set(Object.keys(d.versions || {})), false); }))
    .catch(() => {}), 160);
  lee.editVersion += 1; // invalidates an autosave response belonging to the previous tab
  // A notebook this page still holds comes back without its cells when the server's copy is the same version.
  const have = JSON.stringify(heldNotebookVersions());
  const st=await api('/tab/state?'+new URLSearchParams({...(expectedPath?{path:expectedPath}:{}), have}));
  if(mountVersion!==mountTabVersion)return;
  window.leeModeFollow?.(st.kind);
  if (st.kind === 'notebook' && st.same) st.cells = heldNotebookCells(st.path || st.title);
  if (st.kind === 'notebook') noteSeen(st.path || st.title, st.cells);
  const recoveredDraft = await restoreDrafts(st);
  // `/tab/state` serves the cached copy and flags that the file has moved under it, which is what a
  // run of `nbdev-prepare` over an open notebook does. Nobody read the flag, so the tab showed the
  // version from before the run with nothing saying so.
  if (st.stale) noteStaleTab(st, recoveredDraft);
  // Only the tab's own editors are torn down. The exec strip belongs to the app, and destroying
  // it here would silently leave the box unmounted.
  lee.cellObserver?.disconnect(); lee.cellObserver = null;
  lee.editors.forEach((v, k) => { if (k !== 'exec') { LeeCM.destroy(v); lee.editors.delete(k); } });
  // The notebook being left keeps its shells, so coming back to it is a reattach rather than a
  // hundred elements built and laid out again. A dirty one is not kept: its summaries and outputs
  // describe a version that is not on disk.
  if (lee.kind === 'notebook' && !$('.lee-tab.active.dirty')) keepNotebookShells($('#editor'), lee.tabKey, lee.diskVersion && `${lee.diskVersion}@${lee.nbVersions.get(lee.tabKey)}`);
  // A screencast is a live encode in Chrome while it runs, so leaving the tab stops it. The page
  // stays open and the tab reattaches on the way back.
  closeWebView();
  const host = $('#editor'); if (!host) return;
  lee.kind = st.kind; lee.path = st.path || ''; lee.learnPage = ''; lee.tabKey = st.path || st.title || ''; lee.cells = st.cells || [];
  lee.rise = st.rise || {};
  lee.readOnly = !!st.read_only;
  bindTabHandlers(st.kind, host);
  window.leeFolderOffer?.(st);
  paintTitle();
  // A notebook's kernelspec, so cells highlight and lint as the language they are.
  lee.nbLang = st.kind === 'notebook' ? (st.lang || 'python') : '';
  execLang();
  await loadSettings(st.lang || (st.kind === 'notebook' ? 'python' : ''));
  updateToolbarForKind(st.kind);
  rememberRecentTab(st);
  lee.diskVersion = st.disk_version || ''; lee.seenDiskVersion = lee.diskVersion;
  recordDiskVersion(st.path || lee.path, lee.diskVersion);
  // Tab navigation always returns Run and Variables to that tab's private kernel.
  paintEnv('');
  // The empty state is authored once, in Python's `_empty_editor`, and shipped as a template.
  if (!st.kind) {
    host.replaceChildren($('#leeempty')?.content.cloneNode(true) ?? '');
    paintKeyLabels(host); paintRecent(); paintAgentAttachments();
    return;
  }
  if (st.kind === 'error') { host.innerHTML = `<div class="lee-err">${esc(st.error)}</div>`; return; }
  if (tabMounts.has(st.kind)) await tabMounts.get(st.kind)(host, st);
  else if (st.kind === 'vault') await mountVault(host, st);
  else if (st.kind === 'vaultwb') await mountVaultWorkbench(host, st);
  else if (st.kind === 'web') mountWeb(host, st);
  else if (st.kind === 'pdf') mountPdf(host, st);
  else if (st.kind === 'image') mountImage(host, st);
  else if (st.kind === 'office') await mountOffice(host, st);
  else if (st.kind === 'audio' || st.kind === 'video') mountMedia(host, st);
  else if (st.kind === 'notebook') { takeLate(st); mountNotebook(host, st); lee.mountedAt = mountVersion; }
  else await mountFile(host, st);
  if (recoveredDraft) {
    const tab = $('.lee-tab.active'); tab?.classList.add('dirty'); setTabSaveState(tab, 'pending');
    status('restored an unsaved browser draft · autosave will persist it', 'ok');
    scheduleAutoSave();
  }
  // Only the newest mount takes the place: a mount that started after this one (a disk reload at boot) draws the cells again and would lose it.
  if (lee.pendingLocation && mountVersion === mountTabVersion && (!lee.pendingLocation.path || lee.pendingLocation.path === st.path)) {
    const loc = lee.pendingLocation; lee.pendingLocation = null;
    requestAnimationFrame(() => {
      // A notebook is a column of editors, each with its own line 1, so a location has to name
      // the cell. `cellIndex` is the fallback for cells with no ids of their own, written before
      // nbformat 4.5. The debug decorations are only for the debugger, since a search result is
      // somewhere to go rather than the line being executed.
      if ((loc.cellId || loc.cellIndex >= 0) && lee.kind === 'notebook') {
        let i = loc.cellId ? lee.cells.findIndex(c => c.id === loc.cellId) : -1;
        if (i < 0 && loc.cellIndex >= 0 && loc.cellIndex < lee.cells.length) i = loc.cellIndex;
        if (i >= 0) {
          // `focusCell` scrolls `#editor` to the cell: `jumpToLine` below scrolls only a code cell, so a hand-off to a section heading stayed off screen.
          focusCell(i); const view = ensureCellMounted(i);
          // The outputs and late cells above it still grow, so the cell is shown again while they settle, until the learner scrolls, types or moves on.
          let moved = false; const off = () => { moved = true; };
          $('#editor')?.addEventListener('wheel', off, {once: true, passive: true}); addEventListener('keydown', off, {once: true});
          for (const ms of [150, 400, 900, 1800]) setTimeout(() => { if (!moved && lee.sel === i) revealCell($(`.lee-cell[data-i="${i}"]`)); }, ms);
          if (loc.debug && view) {
            LeeCM.setDebugLine(view, loc.line);
            paintDebugInlineValues(view, loc.line, lee.debugState?.variables);
          }
          jumpToLine(loc.line);
          if (loc.column && view) { const at = view.state.doc.line(loc.line).from + loc.column; LeeCM.setSelection(view, at, at + String(loc.symbol || '').length); }
        }
      } else {
        jumpToLine(loc.line);
        const view = lee.editors.get('file');
        if (view && loc.column) { const at = view.state.doc.line(loc.line).from + loc.column; LeeCM.setSelection(view, at, at + String(loc.symbol || '').length); }
        if (loc.debug && view) {
          LeeCM.setDebugLine(lee.editors.get('file'), loc.line);
          paintDebugInlineValues(lee.editors.get('file'), loc.line, lee.debugState?.variables);
        }
      }
    });
  }
  restoreTabLocation(st, hadPendingLocation);
  refreshKernelPill();
  if (lee.kind === 'text' || lee.kind === 'notebook') leeSymbols();
  paintAgentAttachments();
  const split = leeSavedSplit(localStorage.getItem('lee-editor-split'));
  if (split === false) leeCloseSplit();
  else if (split?.page) { if (!lee.sidePage?.frame?.isConnected && !mountPage(split.page, split.title, split.direction)) leeCloseSplit(); }
  else if (split?.path && split.path !== st.path) {
    try { await mountSecondary(split.path, split.direction); } catch (_) { localStorage.removeItem('lee-editor-split'); }
  }
  if (lee.pendingFocusPath === st.path) {
    lee.pendingFocusPath = '';
    requestAnimationFrame(() => {
      const view = st.kind === 'text' ? lee.editors.get('file') : lee.editors.get(lee.cells[lee.sel]?.id);
      if (view) { LeeCM.focus(view); setScope('editor'); }
    });
  }
}

//: What `/tab/state` said, with the newest edit response that landed while the tab was away and the folds not yet written.
function takeLate(st) {
  const key = st.path || st.title, late = lee.nbLate.get(key); lee.nbLate.delete(key);
  if (late && late.version > (st.version ?? 0)) Object.assign(st, {cells: late.cells, version: late.version});
  lee.cells = st.cells = foldsSince(key, st.cells, st.version);
  lee.nbVersions.set(key, st.version);
}
function rememberBuffer(key, payload) {
  payload = {...payload, seq: nextSeq(), ...(payload.kind === 'notebook' ? seenRow(payload.title || payload.path, payload.id) : {})};
  lee.buffers.set(key, payload.text); lee.dirtyBuffers.add(key); persistDraft(key, payload);
  clearTimeout(lee.bufferTimers.get(key));
  lee.bufferTimers.set(key, setTimeout(() => {
    lee.bufferTimers.delete(key);
    const documentKey = payload.path || payload.title || lee.tabKey || key;
    post('/tab/buffer', {...payload, base_disk_version: draftBaseFor(documentKey)})
      .catch(e => status(String(e.message || e), 'err'));
  }, 120));
}

// A PDF, in the viewer the browser already ships: an `<iframe>` pointed at the bytes, plus the two
// things an iframe cannot do for itself, which are opening the file outside Leela and saying
// something useful if the viewer is disabled.
function mountPdf(host, st) {
  // The filename goes in the path as well as the query, because the browser's own viewer titles
  // itself from the last path segment.
  // The segment is decoration: the server still resolves the file from `path` alone, and must, or
  // a name in a URL would become a way to ask for a different file.
  const name = (st.path || '').split('/').pop() || 'document.pdf';
  const raw = '/file/raw/' + encodeURIComponent(name) + '?path=' + encodeURIComponent(st.path);
  host.innerHTML =
    `<div class="lee-doc">` +
    `<div class="lee-doc-head"><span>${esc(compactPath(st.path))}</span><span class="lee-spacer"></span>` +
    `<a class="lee-btn" href="${esc(raw)}" target="_blank" rel="noopener noreferrer">open externally</a>` +
    `<a class="lee-btn" href="${esc(raw)}&download=true" download>download</a></div>` +
    `<div class="lee-doc-body"><iframe class="lee-pdf" title="${esc(st.title || 'PDF')}" src="${esc(raw)}"></iframe>` +
    `<noscript class="lee-dim">This view needs the browser's PDF viewer.</noscript></div></div>`;
}

function noteStaleTab(st, recoveredDraft) {
  const name = (st.path || st.title || 'this file').split('/').pop();
  // A recovered draft is the user's own unsaved work, so it is never dropped for a disk change.
  if (st.dirty || recoveredDraft) {
    status(`${name} changed on disk; your unsaved version is what you are looking at`, 'err');
    return;
  }
  status(`${name} changed on disk. Reloading…`, 'busy');
  takeDiskVersion(st.path).then(() => status(`${name} reloaded from disk`, 'ok'))
                          .catch(e => status(String(e.message || e), 'err'));
}
