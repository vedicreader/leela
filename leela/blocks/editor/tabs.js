/* ------------------------------------------------------------------ editor */
function updateToolbarForKind(kind) {
  const notebook = kind === 'notebook', text = kind === 'text';
  // `stop` interrupts the tab's kernel, and a document tab -- a PDF, an image, a vault entry,
  // a live web page -- does not have one, so it was offering to interrupt nothing.
  const visibility = {run_cell: notebook, run_advance: notebook, run_file: text,
                      run_selection: text, interrupt: notebook || text};
  for (const [action, shown] of Object.entries(visibility)) {
    const button = $(`#toolbar [data-action="${action}"]`); if (button) button.hidden = !shown;
  }
  refreshMarkdownCellActions();   // whether a reply can become a cell depends on this tab
}

let mountTabVersion=0;
function saveTabLocation() {
  const view = curEditor(), key = lee.path || lee.tabKey;
  if (!view || !key) return;
  // A Map keeps a re-set key at its *first* insertion point, so without the delete the tail
  // slice below persisted the eighty oldest files ever opened and dropped the recent ones.
  lee.locations.delete(key);
  lee.locations.set(key, {pos: LeeCM.cursor(view), scroll: view.scrollDOM.scrollTop,
    cell: lee.kind === 'notebook' ? lee.sel : -1});
  // Nothing else prunes this: a closed, renamed or deleted file leaves its entry behind, so
  // the cap is what keeps a long session (and sessionStorage) bounded.
  for (const stale of [...lee.locations.keys()].slice(0, lee.locations.size - 80)) lee.locations.delete(stale);
  try { sessionStorage.setItem('lee-tab-locations', JSON.stringify([...lee.locations])); } catch (_) {}
}
function restoreTabLocation(st, skip = false) {
  const key = st.path || st.title, loc = lee.locations.get(key);
  if (!loc || skip || lee.pendingLocation) return;
  requestAnimationFrame(() => {
    let view = lee.editors.get('file');
    if (st.kind === 'notebook' && loc.cell >= 0 && loc.cell < lee.cells.length) {
      selectCell(loc.cell); view = ensureCellMounted(loc.cell);
    }
    if (!view) return;
    LeeCM.setCursor(view, loc.pos); view.scrollDOM.scrollTop = loc.scroll || 0;
  });
}
async function mountTab(expectedPath = '') {
  saveTabLocation();
  const hadPendingLocation = Boolean(lee.pendingLocation);
  const mountVersion=++mountTabVersion;
  lee.activeGitTab = '';
  if (lee.gitMergeView) { LeeCM.destroyMerge(lee.gitMergeView); lee.gitMergeView = null; }
  syncGitDiffTabs();
  clearTimeout(lee.autoSaveTimer);
  lee.editVersion += 1; // invalidates an autosave response belonging to the previous tab
  const st=await api('/tab/state'+(expectedPath?'?path='+encodeURIComponent(expectedPath):''));
  if(mountVersion!==mountTabVersion)return;
  const recoveredDraft = await restoreDrafts(st);
  // Only the tab's own editors are torn down. The exec strip belongs to the app, not
  // to the tab, and destroying it here would silently leave the box unmounted.
  lee.cellObserver?.disconnect(); lee.cellObserver = null;
  lee.editors.forEach((v, k) => { if (k !== 'exec') { LeeCM.destroy(v); lee.editors.delete(k); } });
  // A screencast is a live encode in Chrome for as long as it is running, so leaving the tab
  // has to stop it. The page itself stays open; the tab reattaches to it on the way back.
  closeWebView();
  const host = $('#editor'); if (!host) return;
  lee.kind = st.kind; lee.path = st.path || ''; lee.tabKey = st.path || st.title || ''; lee.cells = st.cells || [];
  await loadSettings(st.lang || (st.kind === 'notebook' ? 'python' : ''));
  updateToolbarForKind(st.kind);
  rememberRecentTab(st);
  lee.diskVersion = st.disk_version || ''; lee.seenDiskVersion = lee.diskVersion;
  // Tab navigation always returns Run and Variables to that tab's private kernel.
  paintEnv('');
  // The empty state is authored once, in Python's `_empty_editor`, and shipped as a template.
  if (!st.kind) {
    host.replaceChildren($('#leeempty')?.content.cloneNode(true) ?? '');
    paintRecent();
    return;
  }
  if (st.kind === 'error') { host.innerHTML = `<div class="lee-err">${esc(st.error)}</div>`; return; }
  if (st.kind === 'vault') await mountVault(host, st);
  else if (st.kind === 'vaultwb') await mountVaultWorkbench(host, st);
  else if (st.kind === 'web') mountWeb(host, st);
  else if (st.kind === 'pdf') mountPdf(host, st);
  else if (st.kind === 'image') mountImage(host, st);
  else if (st.kind === 'audio' || st.kind === 'video') mountMedia(host, st);
  else if (st.kind === 'notebook') mountNotebook(host, st);
  else await mountFile(host, st);
  if (recoveredDraft) {
    const tab = $('.lee-tab.active'); tab?.classList.add('dirty'); setTabSaveState(tab, 'pending');
    status('restored an unsaved browser draft · autosave will persist it', 'ok');
    scheduleAutoSave();
  }
  if (lee.pendingLocation && (!lee.pendingLocation.path || lee.pendingLocation.path === st.path)) {
    const loc = lee.pendingLocation; lee.pendingLocation = null;
    requestAnimationFrame(() => {
      // A notebook is a column of editors, each with its own line 1, so a location in one has
      // to name the cell. `cellIndex` is the fallback for a notebook whose cells carry no ids
      // of their own (anything written before nbformat 4.5), and the debug decorations are only
      // for the debugger: a search result is somewhere to go, not the line being executed.
      if ((loc.cellId || loc.cellIndex >= 0) && lee.kind === 'notebook') {
        let i = loc.cellId ? lee.cells.findIndex(c => c.id === loc.cellId) : -1;
        if (i < 0 && loc.cellIndex >= 0 && loc.cellIndex < lee.cells.length) i = loc.cellIndex;
        if (i >= 0) {
          selectCell(i); const view = ensureCellMounted(i);
          if (loc.debug) {
            LeeCM.setDebugLine(view, loc.line);
            paintDebugInlineValues(view, loc.line, lee.debugState?.variables);
          }
          jumpToLine(loc.line);
          if (loc.column) { const at = view.state.doc.line(loc.line).from + loc.column; LeeCM.setSelection(view, at, at + String(loc.symbol || '').length); }
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
  try { const split=JSON.parse(localStorage.getItem('lee-editor-split')||'null'); if(split?.path&&split.path!==st.path) await mountSecondary(split.path,split.direction); }
  catch (_) { localStorage.removeItem('lee-editor-split'); }
  if (lee.pendingFocusPath === st.path) {
    lee.pendingFocusPath = '';
    requestAnimationFrame(() => {
      const view = st.kind === 'text' ? lee.editors.get('file') : lee.editors.get(lee.cells[lee.sel]?.id);
      if (view) { LeeCM.focus(view); setScope('editor'); }
    });
  }
}

function rememberBuffer(key, payload) {
  lee.buffers.set(key, payload.text); lee.dirtyBuffers.add(key); persistDraft(key, payload);
  clearTimeout(lee.bufferTimers.get(key));
  lee.bufferTimers.set(key, setTimeout(() => {
    lee.bufferTimers.delete(key);
    const documentKey = payload.path || payload.title || lee.tabKey || key;
    post('/tab/buffer', {...payload, base_disk_version: draftBaseFor(documentKey)})
      .catch(e => status(String(e.message || e), 'err'));
  }, 120));
}

// A PDF, in the viewer the browser already ships. Reimplementing one on a canvas would be a
// worse viewer and a large amount of code, and we are in a browser after all -- so the whole
// feature is an `<iframe>` pointed at the bytes, plus the two things an iframe cannot do for
// itself: open the file outside Leela, and say something useful if the viewer is disabled.
function mountPdf(host, st) {
  // The filename goes in the *path* as well as the query, because the browser's own viewer titles
  // itself from the last path segment -- so `/file/raw?path=…` opened every document called
  // "raw". The segment is decoration: the server still resolves the file from `path` alone, and
  // must, or a name in a URL would become a way to ask for a different file.
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

