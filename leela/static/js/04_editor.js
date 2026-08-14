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
  if (!st.kind) { host.replaceChildren($('#leeempty')?.content.cloneNode(true) ?? ''); return; }
  if (st.kind === 'error') { host.innerHTML = `<div class="lee-err">${esc(st.error)}</div>`; return; }
  if (st.kind === 'vault') await mountVault(host, st);
  else if (st.kind === 'web') mountWeb(host, st);
  else if (st.kind === 'pdf') mountPdf(host, st);
  else if (st.kind === 'image') mountImage(host, st);
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
        }
      } else {
        jumpToLine(loc.line);
        if (loc.debug && lee.editors.get('file')) {
          LeeCM.setDebugLine(lee.editors.get('file'), loc.line);
          paintDebugInlineValues(lee.editors.get('file'), loc.line, lee.debugState?.variables);
        }
      }
    });
  }
  restoreTabLocation(st, hadPendingLocation);
  refreshKernelPill();
  if ($('#left')?.classList.contains('left-symbols')) leeSymbols();
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

/* An image, in the same chrome as a PDF. Fit is the default because an image opened from a
   vault or a file tree is being *identified*, not inspected; actual size is one click away and
   the dimensions are shown either way, since "is this the 2x asset" is the usual question. */
function mountImage(host, st) {
  const name = (st.path || '').split('/').pop() || 'image';
  const raw = '/file/raw/' + encodeURIComponent(name) + '?path=' + encodeURIComponent(st.path);
  host.innerHTML =
    `<div class="lee-doc">` +
    `<div class="lee-doc-head"><span>${esc(compactPath(st.path))}</span>` +
    `<span class="lee-dim" data-image-size></span><span class="lee-spacer"></span>` +
    `<button class="lee-btn" data-image-fit>actual size</button>` +
    `<a class="lee-btn" href="${esc(raw)}" target="_blank" rel="noopener noreferrer">open externally</a>` +
    `<a class="lee-btn" href="${esc(raw)}&download=true" download>download</a></div>` +
    `<div class="lee-doc-body lee-image-body fit">` +
    `<img class="lee-image" alt="${esc(st.title || name)}" src="${esc(raw)}"></div></div>`;
  const img = $('.lee-image', host), body = $('.lee-image-body', host), button = $('[data-image-fit]', host);
  img.onload = () => { $('[data-image-size]', host).textContent = `${img.naturalWidth}×${img.naturalHeight}`; };
  img.onerror = () => { body.innerHTML = `<div class="lee-err">${esc(name)} could not be displayed</div>`; };
  button.onclick = () => {
    const fit = body.classList.toggle('fit');
    button.textContent = fit ? 'actual size' : 'fit to window';
  };
}

async function mountFile(host, st) {
  const isProject = st.path?.endsWith('/pyproject.toml') || st.title === 'pyproject.toml';
  const crumbMode=lee.workbenchPrefs.breadcrumbs||'pathAndSymbols',crumb=crumbMode==='off'?'':`<nav class="lee-breadcrumbs" id="editorcrumbs" aria-label="File and symbol path"><span>${esc(compactPath(st.path||st.title||''))}</span></nav>`;
  // Markdown gets a rendered pane beside the editor. The editor stays mounted in every view and
  // is merely hidden by CSS when only the rendering is showing -- everything that reaches for
  // `lee.editors.get('file')` (saving, autosave, blame, the change gutter, jump-to-line) keeps
  // working, and "rendered" is a way of *looking* at the file rather than a different kind of tab.
  const isMd = (st.lang || '') === 'markdown';
  const view = isMd ? (localStorage.getItem('lee-md-view') || 'split') : '';
  host.innerHTML = crumb + (isProject ? '<div class="lee-package-summary" id="packagebar" hidden></div>' : '') +
    (isMd ? `<div class="lee-doc-head lee-md-bar"><div class="lee-segbar" id="mdview" aria-label="markdown view">` +
            ['edit', 'split', 'rendered'].map(v =>
              `<button class="lee-seg${v === view ? ' active' : ''}" data-md-view="${v}">${v}</button>`).join('') +
            `</div><span class="lee-spacer"></span>` +
            `<span class="lee-dim">the change gutter and blame stay on the source</span></div>` : '') +
    // `data-md-base` is this file's folder: a figure written `![](img/a.png)` is relative to the
    // document, not to the page the renderer drops it into.
    (isMd ? `<div class="lee-md-stage" data-view="${view}" data-md-base="${esc((st.path || '').slice(0, (st.path || '').lastIndexOf('/')))}">` +
            `<div class="lee-cm" id="filecm"></div>` +
            `<div class="lee-md-preview" id="mdpreview" data-markdown=""></div></div>`
          : '<div class="lee-cm" id="filecm"></div>');
  let git = {ranges: []}, packages = null;
  if (st.path) {
    const requests = [api('/git/file?path=' + encodeURIComponent(st.path)).catch(() => git)];
    if (isProject && lee.workbenchPrefs.dependencyHints !== false) requests.push(api('/editor/packages?path=' + encodeURIComponent(st.path)).catch(() => null));
    [git, packages] = await Promise.all(requests);
  }
  lee.fileGit = git;
  const key = st.path || st.title;
  const v = createEditor($('#filecm'), {
    // A cached value is authoritative only after an actual user edit. This guard prevents
    // stale/programmatic empty entries from blanking a freshly loaded file or run result.
    doc: lee.dirtyBuffers.has(key) ? lee.buffers.get(key) : (st.text || ''),
    lang: st.lang || 'python', lineNums: true, lintPath: st.path || '',
    completeUrl: '/complete', changedLines: git.ranges || [], breakpoints: lee.breakpoints.get(st.path)||[],
    onBreakpoint: st.lang==='python' ? lines=>{rememberBreakpoints(st.path,lines);if(lee.directDebug)post('/debug/breakpoints',{path:st.path,breakpoints:lines}).catch(e=>status(e.message||String(e),'err'));} : null,
    onChangeClick: line => showChangePopup(st.path, line),
    onDefinition: name => findDefinition(name), onSelection: () => {
      clearTimeout(selectionHelpTimer); selectionHelpTimer = setTimeout(showSelectionHelp, 120);
    },
    onChange: txt => {
      rememberBuffer(key, {path: key, kind: 'text', text: txt}); markDirty();
      // The preview follows the buffer, not the file: `renderMarkdown` is already debounced and
      // drops superseded renders, so this is safe to call on every keystroke.
      if (isMd) renderMarkdown($('#mdpreview'), txt);
    },
  });
  lee.editors.set('file', v);
  if (isMd) {
    // The rendered pane carries the same change marks as the gutter beside it, placed by block
    // rather than by line. Only this first render is annotated; see `paintMarkdownFileChanges`.
    renderMarkdown($('#mdpreview'), LeeCM.getDoc(v), false,
                   el => paintMarkdownFileChanges(el, git.ranges || []));
    $('#mdview').onclick = e => {
      const b = e.target.closest('[data-md-view]'); if (!b) return;
      const next = b.dataset.mdView;
      localStorage.setItem('lee-md-view', next);
      $('.lee-md-stage').dataset.view = next;
      $$('#mdview .lee-seg').forEach(x => x.classList.toggle('active', x === b));
      // The editor was display:none a moment ago, so CodeMirror has stale measurements and will
      // draw the cursor in the wrong place until it re-measures.
      if (next !== 'rendered') requestAnimationFrame(() => LeeCM.focus(v));
    };
  }
  if(st.lang==='python'&&st.path&&lee.editorPrefs.inlayHints)api('/lsp/inlay-hints',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:st.path,text:LeeCM.getDoc(v)})}).then(d=>LeeCM.setInlayHints?.(v,d.hints||[])).catch(()=>{});
  if(st.lang==='python'&&st.path&&['symbols','pathAndSymbols'].includes(crumbMode))api('/lsp/symbols',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:st.path,text:LeeCM.getDoc(v)})}).then(d=>{const el=$('#editorcrumbs');if(el){const names=(d.symbols||[]).slice(0,40).map(s=>`<button data-line="${(s.range?.start?.line||0)+1}">${esc(s.name)}</button>`).join('');el.insertAdjacentHTML('beforeend',`<i>›</i><span class="lee-breadcrumb-symbols">${names}</span>`);el.onclick=e=>{const b=e.target.closest('[data-line]');if(b)jumpToLine(b.dataset.line);};}}).catch(()=>{});
  if (packages) paintPackageVersions(v, packages);
  closeChangePopup(); armChangeGutter($('#filecm'));
  $('#filecm').addEventListener('focusin', () => { lee.activeEditor='primary'; setScope('editor'); });
}

async function mountSecondary(path, direction = 'vertical') {
  const stage=$('#editorstage'),host=$('#editor2'); if (!stage || !host) return;
  const st=await api('/tab/state?path='+encodeURIComponent(path));
  if (st.kind!=='text') return status('split view currently opens text files; notebooks stay in the primary editor','err');
  if (lee.editors.get('secondary')) { LeeCM.destroy(lee.editors.get('secondary')); lee.editors.delete('secondary'); }
  stage.classList.add('split',`split-${direction}`); stage.classList.remove(`split-${direction==='vertical'?'horizontal':'vertical'}`);
  host.hidden=false; host.innerHTML=`<div class="lee-split-head"><span>${esc(compactPath(st.path))}</span><button class="lee-btn" onclick="leeCloseSplit()">close</button></div><div class="lee-cm" id="filecm2"></div>`;
  const key=st.path,view=createEditor($('#filecm2'),{doc:lee.dirtyBuffers.has(key)?lee.buffers.get(key):(st.text||''),lang:st.lang||'python',lineNums:true,lintPath:st.path||'',completeUrl:'/complete',
    onDefinition:name=>findDefinition(name),onChange:txt=>{rememberBuffer(key,{path:key,kind:'text',text:txt});lee.editVersion+=1;const tab=$$('.lee-tab').find(x=>x.title===key);tab?.classList.add('dirty');setTabSaveState(tab,'pending');scheduleAutoSave();}});
  lee.editors.set('secondary',view);lee.secondaryPath=path;$('#filecm2').addEventListener('focusin',()=>{lee.activeEditor='secondary';setScope('editor');});localStorage.setItem('lee-editor-split',JSON.stringify({path,direction}));LeeCM.focus(view);
}
function leeCloseSplit(){const stage=$('#editorstage'),host=$('#editor2'),v=lee.editors.get('secondary');if(v)LeeCM.destroy(v);lee.editors.delete('secondary');lee.secondaryPath='';lee.activeEditor='primary';stage?.classList.remove('split','split-vertical','split-horizontal');if(host){host.hidden=true;host.innerHTML='';}localStorage.removeItem('lee-editor-split');}
window.leeCloseSplit=leeCloseSplit;
function leeSplit(direction='vertical') {
  const rows=$$('.lee-tab').filter(t=>t.dataset.kind==='text'&&t.title!==lee.path).map(t=>({path:t.title,label:$('.lee-tab-name',t)?.textContent||t.title}));
  if (!rows.length) return status('open another text file before splitting','err');
  const m=modal(`<div class="lee-mhead">Split editor<span class="sub">${direction==='vertical'?'side by side':'top and bottom'}</span></div><div class="lee-modallist">${rows.map((r,i)=>`<button class="lee-mrow" data-i="${i}"><strong>${esc(r.label)}</strong><span class="sub">${esc(compactPath(r.path))}</span></button>`).join('')}</div>`);
  $$('.lee-mrow',m).forEach(b=>b.onclick=()=>{const r=rows[+b.dataset.i];m.remove();mountSecondary(r.path,direction);});
}
window.leeSplit=leeSplit;

function paintPackageVersions(view, data) {
  LeeCM.setPackageVersions(view, data.packages || []);
  const bar = $('#packagebar'), s = data.summary || {};
  if (!bar) return;
  const env = String(s.python || '').replace(/\\/g, '/').split('/').slice(-2).join('/');
  bar.innerHTML = `<strong>environment</strong><span>${esc(env || 'python')}</span>` +
    `<span>${s.installed || 0}/${s.total || 0} installed</span>` +
    (s.mismatch ? `<span class="warn">${s.mismatch} version mismatch${s.mismatch === 1 ? '' : 'es'}</span>` : '') +
    (s.missing ? `<span class="err">${s.missing} missing</span>` : '<span class="ok">requirements satisfied</span>');
  bar.hidden = false;
}

async function refreshPackageVersions() {
  if (!lee.path?.endsWith('/pyproject.toml') || !lee.editors.get('file')) return;
  try { paintPackageVersions(lee.editors.get('file'), await api('/editor/packages?path=' + encodeURIComponent(lee.path))); }
  catch (_) {}
}

window.addEventListener('lee-package-open', e => {
  $('.lee-package-popover')?.remove();
  const item = e.detail?.item || {}, anchor = e.detail?.anchor;
  const p = document.createElement('aside'); p.className = 'lee-package-popover';
  const state = item.installed == null ? 'missing from this environment'
    : item.compatible === false ? 'installed version does not satisfy the declaration'
    : 'installed in this environment';
  p.innerHTML = `<div class="lee-inline-head"><strong>${esc(item.name || 'package')}</strong>` +
    `<button class="lee-icon" aria-label="close">×</button></div>` +
    `<dl><dt>declared</dt><dd>${esc(item.required || 'any version')}</dd>` +
    `<dt>installed</dt><dd>${esc(item.installed || 'not installed')}</dd>` +
    (item.marker ? `<dt>marker</dt><dd>${esc(item.marker)}</dd>` : '') +
    `<dt>runtime</dt><dd title="${esc(item.python || '')}">${esc(String(item.python || '').split('/').slice(-2).join('/'))}</dd></dl>` +
    `<p class="${item.installed == null || item.compatible === false ? 'warn' : 'ok'}">${esc(state)}</p>`;
  document.body.appendChild(p);
  const a = anchor?.getBoundingClientRect() || {left: innerWidth / 2, bottom: innerHeight / 2};
  const r = p.getBoundingClientRect(); p.style.left = Math.max(8, Math.min(a.left, innerWidth-r.width-8)) + 'px';
  p.style.top = Math.min(innerHeight-r.height-8, a.bottom+6) + 'px';
  p.querySelector('[aria-label="close"]').onclick = () => p.remove();
});
document.addEventListener('pointerdown', e => {
  if ($('.lee-package-popover') && !e.target.closest('.lee-package-popover, .cm-lee-package'))
    $('.lee-package-popover')?.remove();
}, true);

function notebookHeadings(cells) {
  return cells.flatMap((c, i) => c.cell_type === 'markdown' ? String(c.source || '').split('\n').flatMap(line => {
    const m = /^(#{1,6})\s+(.+?)\s*$/.exec(line); return m ? [{i, level: m[1].length, text: m[2].replace(/[*_`]/g, '')}] : [];
  }) : []);
}
function notebookToc(cells) {
  const headings = notebookHeadings(cells);
  const toc = document.createElement('details'); toc.className = 'lee-nb-toc';
  toc.innerHTML = `<summary>contents <span>${headings.length || 'no'} sections</span></summary><nav></nav>`;
  const nav = toc.querySelector('nav');
  if (!headings.length) nav.innerHTML = '<div class="lee-dim">Add Markdown headings to build the outline.</div>';
  else headings.forEach((h, at) => {
    const next = headings.slice(at + 1).find(x => x.level <= h.level);
    const row = document.createElement('div'); row.className = 'lee-toc-row'; row.style.setProperty('--level', h.level);
    row.innerHTML = `<button class="lee-toc-jump">${esc(h.text)}</button>` +
      `<button class="lee-toc-fold" title="collapse or expand this section">${lee.collapsedCells.has(cells[h.i].id) ? '+' : '−'}</button>`;
    row.querySelector('.lee-toc-jump').onclick = () => { toc.open = false; focusCell(h.i); };
    row.querySelector('.lee-toc-fold').onclick = () => {
      const end = next ? next.i : cells.length;
      for (let i = h.i; i < end; i++) setCellCollapsed(i, !lee.collapsedCells.has(cells[h.i].id));
      row.querySelector('.lee-toc-fold').textContent = lee.collapsedCells.has(cells[h.i].id) ? '+' : '−';
    };
    nav.appendChild(row);
  });
  return toc;
}
function observeNotebookCells(host, cells) {
  // Cell shells preserve the notebook's geometry; CodeMirror is only created near the
  // viewport. A 150-cell notebook therefore paints immediately instead of constructing
  // 150 editors in one uninterruptible task.
  lee.cellObserver?.disconnect();
  lee.cellObserver = new IntersectionObserver(entries => {
    for (const e of entries) if (e.isIntersecting) {
      const i = +e.target.dataset.i; ensureCellMounted(i); lee.cellObserver?.unobserve(e.target);
    }
  }, {root: host, rootMargin: '700px 0px'});
  $$('.lee-cell', host).forEach((el, i) => {
    if (i === lee.sel || cells[i]?.running) ensureCellMounted(i);
    else lee.cellObserver.observe(el);
  });
}

function mountNotebook(host, st) {
  lee.cellObserver?.disconnect();
  for (const [key, view] of [...lee.editors.entries()]) {
    if (key === 'exec' || key === 'file') continue;
    LeeCM.destroy(view); lee.editors.delete(key);
  }
  host.innerHTML = '';
  host.appendChild(notebookToc(st.cells));
  st.cells.forEach((c, i) => host.appendChild(cellEl(c, i)));
  selectCell(Math.min(lee.sel, st.cells.length - 1));
  observeNotebookCells(host, st.cells);
  lee.notebookGit = {};       // marks belong to the notebook that was open, not the next one
  paintNotebookGitMarks();
  queueNotebookOverview();    // a notebook outside a repository still gets its viewport thumb
}

function patchNotebook(host, before, cells, op = '') {
  // Keep unchanged cell DOM and CodeMirror views alive. Moving those nodes is effectively
  // free and, unlike rebuilding the notebook, cannot flash blank or reset the viewport.
  lee.cellObserver?.disconnect();
  const oldCells = new Map(before.map(c => [c.id, c]));
  const oldEls = new Map($$('.lee-cell', host).map(el => [el.dataset.id, el]));
  const ids = new Set(cells.map(c => c.id));
  for (const [id, el] of oldEls) if (!ids.has(id)) {
    const view = lee.editors.get(id); if (view) LeeCM.destroy(view);
    lee.editors.delete(id); el.remove();
  }
  const toc = notebookToc(cells), oldToc = $('.lee-nb-toc', host);
  if (oldToc) oldToc.replaceWith(toc); else host.prepend(toc);
  cells.forEach((c, i) => {
    const old = oldCells.get(c.id);
    let el = oldEls.get(c.id);
    const changed = !old || old.source !== c.source || old.cell_type !== c.cell_type;
    if (!el || changed) {
      const view = lee.editors.get(c.id); if (view) LeeCM.destroy(view);
      lee.editors.delete(c.id);
      const key = `${lee.path || 'scratch'}:${c.id}`;
      lee.buffers.set(key, c.source); lee.dirtyBuffers.add(key);
      const fresh = cellEl(c, i);
      if (el) el.replaceWith(fresh);
      el = fresh;
    } else {
      el.dataset.i = i;
      el.className = 'lee-cell ' + c.cell_type + (lee.collapsedCells.has(c.id) ? ' collapsed' : '');
      const buttons = $('.lee-cellbtns', el); if (buttons) buttons.innerHTML = cellButtons(i);
      const summary = $('.lee-cell-summary', el);
      if (summary) summary.textContent = String(c.source || '').trim().split('\n')[0] || 'empty cell';
      const gutter = $('#g-' + c.id); if (gutter) gutter.textContent = gutterFor(c);
      const context = $('.lee-cell-context', el); if (context) paintCellContext(context, c);
      setCellState(c, cellState(c)); setCellTime(c, c.execution_ms, c.running);
      if (op === 'clear' || op === 'clear_cell') renderOutputs(c);
    }
    host.appendChild(el); // appending an existing node reorders it without remounting
  });
  paintSel();
  observeNotebookCells(host, cells);
  // `className` is rewritten above for every reused cell, so the marks are reapplied from
  // what was last read rather than refetched -- the disk has not moved, only the DOM.
  repaintNotebookGitMarks();
  queueNotebookOverview();
}

function ensureCellMounted(i) {
  const c = lee.cells[i];
  if (!c || lee.editors.has(c.id)) return lee.editors.get(c?.id);
  mountCell(c, i);
  return lee.editors.get(c.id);
}

// A prompt cell's gutter is its own mark, so the three kinds are told apart at a glance
// without reading any of them.
const gutterFor = (c) => c.cell_type === 'code' ? '[' + (c.execution_count ?? ' ') + ']'
                       : c.cell_type === 'prompt' ? '✦' : 'md';
const cellState = (c) => c.running ? 'running' : c.cell_type === 'code' && c.execution_count != null
  ? (!c.fresh ? 'previous' : (c.outputs || []).some(o => o.output_type === 'error') ? 'error' : 'done') : 'idle';
const stateSvg = (state) => state === 'done'
  ? '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3.5 8.2 2.8 2.8 6.2-6.2"/></svg>'
  : state === 'error'
    ? '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4.5 4.5 7 7m0-7-7 7"/></svg>'
    : state === 'previous'
      ? '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="5"/><path d="M8 5v3l2 1.5"/></svg>'
      : state === 'running' ? '<span class="lee-cell-spinner" aria-hidden="true"></span>' : '';
function setCellState(c, state, label = '') {
  const badge = $('#state-' + c.id); if (!badge) return;
  badge.className = 'lee-cell-state ' + state;
  badge.innerHTML = stateSvg(state);
  badge.title = label || ({done: 'ran successfully in the current kernel', error: 'run failed in the current kernel',
    previous: 'saved output from a previous kernel; run this cell to restore its variables', running: 'running'}[state] || 'not run');
  badge.setAttribute('aria-label', badge.title);
  queueNotebookOverview();      // a failure is one of the two things the stripe reports
}
function markPreviousRuns() {
  for (const c of lee.cells) {
    if (c.cell_type !== 'code' || c.execution_count == null) continue;
    c.fresh = false; setCellState(c, 'previous'); setCellTime(c, c.execution_ms, false);
  }
}
function formatCellTime(ms) {
  if (ms == null || !Number.isFinite(Number(ms))) return '';
  ms = Number(ms);
  if (ms < 1000) return `${Math.max(1, Math.round(ms))}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)}s`;
  const seconds = Math.floor(ms / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}
function setCellTime(c, ms, running = false) {
  const el = $('#time-' + c.id); if (!el) return;
  el.textContent = formatCellTime(ms);
  el.hidden = !el.textContent;
  el.classList.toggle('running', running);
  const previous = !running && c.cell_type === 'code' && c.execution_count != null && !c.fresh;
  el.classList.toggle('previous', previous);
  el.title = running ? 'current execution time' : previous ? 'duration of the saved run; its variables are not in this kernel' : 'last execution time';
}

/* The per-cell controls, from the same table the toolbar comes from. They act on the cell
 * they are drawn in rather than on the selected one -- clicking ▶ on the third cell has
 * to run the third cell, whatever the cursor was doing. */
const contextLabel = mode => ({keep: 'keep context', discard: 'discard first', auto: 'context auto'}[mode] || 'context auto');
function paintCellContext(button, c) {
  const mode = c.context_mode || 'auto';
  button.dataset.mode = mode; button.textContent = contextLabel(mode);
  button.title = mode === 'keep' ? 'keep this cell if notebook context is compacted'
    : mode === 'discard' ? 'discard this cell first if notebook context is compacted'
    : 'automatically choose if notebook context is compacted';
}
async function cycleCellContext(i) {
  const c = lee.cells[i]; if (!c) return;
  const modes = ['auto', 'keep', 'discard'], mode = modes[(modes.indexOf(c.context_mode || 'auto') + 1) % modes.length];
  const r = await nbEdit({op: 'context', i, mode});
  Object.assign(c, r.cells[i]);
  const button = $(`.lee-cell[data-i="${i}"] .lee-cell-context`); if (button) paintCellContext(button, c);
  status(`cell ${i + 1}: ${contextLabel(mode)}`, 'ok');
}
window.leeCellContext = cycleCellContext;

function cellButtons(i) {
  const normal = (lee.bars.cell || []).map(b =>
    `<button class="lee-cbtn ${esc(b.kind)}" title="${esc(b.title)}" ` +
    `onclick="leeCellAct(${i}, '${esc(b.action)}')">${esc(b.label)}</button>`).join('');
  const debug = lee.cells[i]?.cell_type === 'code'
    ? `<button class="lee-cbtn" title="debug this cell (ipykernel)" onclick="leeDebugCell(${i})">◆</button>` : '';
  const more = `<button class="lee-cbtn" title="more cell actions" aria-label="more cell actions" ` +
    `onclick="leeCellMenu(${i}, this, event)">⋯</button>`;
  return debug + normal + more;
}
function leeCellAct(i, action) { selectCell(i); setScope('editor'); leeAct(action); }
function leeCellMenu(i, button, event) {
  event?.preventDefault(); event?.stopPropagation(); selectCell(i); setScope('editor');
  const r = button.getBoundingClientRect(); openMenu('cell', r.right - 4, r.bottom + 3);
}
window.leeCellAct = leeCellAct; window.leeCellMenu = leeCellMenu;

function cellEl(c, i) {
  const d = document.createElement('div');
  d.className = 'lee-cell ' + c.cell_type + (lee.collapsedCells.has(c.id) ? ' collapsed' : '');
  d.dataset.i = i; d.dataset.id = c.id;
  d.style.setProperty('--lee-cell-lines', Math.min(20, Math.max(2, String(c.source || '').split('\n').length)));
  const state = cellState(c);
  d.innerHTML =
    `<div class="lee-gutter" draggable="true" title="drag to move cell">` +
    `<button class="lee-cell-fold" title="collapse cell" aria-label="collapse cell">${lee.collapsedCells.has(c.id) ? '+' : '−'}</button>` +
    `<div class="lee-execution-count" id="g-${c.id}">${gutterFor(c)}</div></div>` +
    `<div class="lee-cellmain"><div class="lee-cell-chrome">` +
    `<span class="lee-cell-summary">${esc(String(c.source || '').trim().split('\n')[0] || 'empty cell')}</span>` +
    `<span class="lee-cell-state ${state}" id="state-${c.id}" ` +
    `title="${state === 'done' ? 'ran successfully in the current kernel' : state === 'error' ? 'run failed in the current kernel' : state === 'previous' ? 'saved output from a previous kernel; run to restore variables' : 'not run'}">${stateSvg(state)}</span>` +
    `<time class="lee-cell-time" id="time-${c.id}" title="last execution time" ` +
    `${c.execution_ms == null ? 'hidden' : ''}>${esc(formatCellTime(c.execution_ms))}</time>` +
    `<button class="lee-cell-context" data-mode="${esc(c.context_mode || 'auto')}" ` +
    `onclick="event.stopPropagation();leeCellContext(${i})">${esc(contextLabel(c.context_mode || 'auto'))}</button>` +
    `<div class="lee-model-running" id="model-${c.id}" role="status" aria-live="polite" hidden>` +
    `<span class="lee-running-dot" aria-hidden="true">●</span>` +
    `<span class="lee-running-copy">Model is running</span>` +
    `<span class="lee-running-time"> · starting</span></div>` +
    `<div class="lee-cellbtns">${cellButtons(i)}</div></div>` +
    `<div class="lee-cm" id="cm-${c.id}"></div><div id="out-${c.id}"></div></div>`;
  d.addEventListener('mousedown', e => { selectCell(+d.dataset.i, e.shiftKey); setScope('editor'); });
  d.querySelector('.lee-cell-fold').onclick = e => { e.stopPropagation(); setCellCollapsed(+d.dataset.i); };
  const gutter = d.querySelector('.lee-gutter');
  gutter.addEventListener('dragstart', e => {
    if (!lee.cellSelection.has(+d.dataset.i)) selectCell(+d.dataset.i);
    e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/lee-cell', d.dataset.i);
    e.dataTransfer.setData('text/lee-cells', JSON.stringify([...lee.cellSelection].sort((a,b) => a-b)));
    d.classList.add('dragging');
  });
  gutter.addEventListener('dragend', () => {
    d.classList.remove('dragging'); $$('.lee-cell.drag-target').forEach(x => x.classList.remove('drag-target'));
  });
  d.addEventListener('dragover', e => {
    if (!e.dataTransfer.types.includes('text/lee-cell')) return;
    e.preventDefault(); e.dataTransfer.dropEffect = 'move'; d.classList.add('drag-target');
  });
  d.addEventListener('dragleave', () => d.classList.remove('drag-target'));
  d.addEventListener('drop', e => {
    const from = Number(e.dataTransfer.getData('text/lee-cell'));
    if (!Number.isInteger(from)) return;
    let indices = [from]; try { indices = JSON.parse(e.dataTransfer.getData('text/lee-cells') || `[${from}]`); } catch (_) {}
    e.preventDefault(); d.classList.remove('drag-target');
    if (indices.length > 1) moveCellsTo(indices, +d.dataset.i); else moveCellTo(from, +d.dataset.i);
  });
  return d;
}

function setCellCollapsed(i, value = null) {
  const c = lee.cells[i]; if (!c) return;
  const collapsed = value === null ? !lee.collapsedCells.has(c.id) : value;
  if (collapsed) lee.collapsedCells.add(c.id); else lee.collapsedCells.delete(c.id);
  const el = $(`.lee-cell[data-i="${i}"]`); el?.classList.toggle('collapsed', collapsed);
  const button = el?.querySelector('.lee-cell-fold'); if (button) button.textContent = collapsed ? '+' : '−';
}

function cellClipboardPayload(i) {
  const cell = lee.cells[i]; if (!cell || lee.kind !== 'notebook') return null;
  const view = lee.editors.get(cell.id);
  const payload = JSON.parse(JSON.stringify(cell));
  if (view) payload.source = LeeCM.getDoc(view);
  payload.running = false; payload.fresh = false;
  return payload;
}
function selectedCellIndices(fallback = lee.sel) {
  return [...(lee.cellSelection.size ? lee.cellSelection : new Set([fallback]))].filter(i => i >= 0 && i < lee.cells.length).sort((a,b) => a-b);
}
function copyCell(i) {
  const indices = selectedCellIndices(i), cells = indices.map(cellClipboardPayload).filter(Boolean);
  if (!cells.length) return status('select notebook cells to copy', 'err');
  lee.cellClipboard = {cells, cell: cells[0], from: lee.path || lee.tabKey || 'scratch'};
  status(`${cells.length} cell${cells.length === 1 ? '' : 's'} copied — open another notebook and paste`, 'ok');
}
async function cutCell(i) {
  const indices = selectedCellIndices(i), cells = indices.map(cellClipboardPayload).filter(Boolean);
  if (!cells.length) return status('select notebook cells to cut', 'err');
  lee.cellClipboard = {cells, cell: cells[0], from: lee.path || lee.tabKey || 'scratch'};
  await nbEdit({op: 'delete_many', i: indices[0], indices});
  focusCell(Math.min(indices[0], lee.cells.length - 1));
  status(`${cells.length} cell${cells.length === 1 ? '' : 's'} cut`, 'ok');
}
async function pasteCell(i) {
  if (lee.kind !== 'notebook') return status('cells can only be pasted into a notebook', 'err');
  const cells = lee.cellClipboard?.cells || (lee.cellClipboard?.cell ? [lee.cellClipboard.cell] : []);
  if (!cells.length) return status('copy or cut cells first', 'err');
  const at = Math.max(0, Math.min(i, lee.cells.length));
  await nbEdit({op: 'paste_many', i: at, cells});
  focusCell(at); lee.cellSelection = new Set(cells.map((_, n) => at + n)); paintSel();
  status(`${cells.length} cell${cells.length === 1 ? '' : 's'} pasted from ${compactPath(lee.cellClipboard.from)}`, 'ok');
}

async function moveCellsTo(indices, to) {
  indices = [...new Set(indices)].sort((a,b) => a-b);
  const r = await nbEdit({op: 'move_many', i: indices[0], indices, target: to});
  const at = r.index ?? to; focusCell(at); lee.cellSelection = new Set(indices.map((_, n) => at + n));
  paintSel(); status(`${indices.length} cells moved`, 'ok');
}

async function moveCellTo(from, to) {
  const last = lee.cells.length - 1;
  to = Math.max(0, Math.min(to, last));
  if (from === to || from < 0 || from > last) return focusCell(from);
  await nbEdit({op: 'move', i: from, d: to - from});
  focusCell(to); status(`cell moved to ${to + 1}`, 'ok');
}

function mountCell(c, i) {
  if (lee.editors.has(c.id)) return;
  const key = `${lee.path || 'scratch'}:${c.id}`;
  // Only a docChanged transaction marks a buffer authoritative. A stale empty cache must
  // never replace the non-empty source returned by /tab/state after running a cell.
  const source = lee.dirtyBuffers.has(key) ? lee.buffers.get(key) : c.source;
  c.source = source;
  const v = createEditor($('#cm-' + c.id), {
    doc: source, lang: c.cell_type === 'code' ? 'python' : c.cell_type === 'markdown' ? 'markdown' : '',
    placeholder: c.cell_type === 'prompt' ? `ask the inline model — ${displayChord('mod+enter')} answers in place` : '',
    completeUrl: c.cell_type === 'code' ? '/complete' : null,
    onDefinition: c.cell_type === 'code' ? name => findDefinition(name) : null,
    breakpoints: lee.breakpoints.get(c.id) || [],
    // Line numbers relative to this cell, which is the only place they are drawn. A cell
    // mounted after the marks arrived would otherwise stay unmarked until the next save.
    changedLines: (lee.notebookGit?.lines || {})[c.id] || [],
    onBreakpoint: c.cell_type === 'code' ? lines => rememberBreakpoints(c.id, lines) : null,
    settings: {overviewMode:'off'},
    onSelection: () => { clearTimeout(selectionHelpTimer); selectionHelpTimer = setTimeout(showSelectionHelp, 120); },
    onChange: (txt) => {
      const at = lee.cells.findIndex(cell => cell.id === c.id); if (at < 0) return;
      lee.cells[at].source = txt;
      rememberBuffer(key, {path: lee.path, kind: 'notebook', i: at, id: c.id, text: txt});
      if (cellState(lee.cells[at]) !== 'idle') setCellState(lee.cells[at], 'stale', 'code changed since the last run');
      markDirty();
    },
  });
  lee.editors.set(c.id, v);
  $('#cm-' + c.id).addEventListener('focusin', () => {
    const at = lee.cells.findIndex(cell => cell.id === c.id);
    if (at >= 0) { lee.activeEditor='primary'; lee.sel = at; setScope('editor'); paintSel(); }
  });
  renderOutputs(c);
  if (c.running) {
    const el = $(`.lee-cell[data-i="${i}"]`); el?.classList.add('running');
    setCellState(c, 'running', 'still running in the background');
    setCellTime(c, 0, true);
    if (c.cell_type === 'prompt') {
      const notice = $('#model-' + c.id);
      if (notice) { notice.hidden = false; notice.querySelector('.lee-running-time').textContent = ' · in background'; }
    }
  }
}

function renderOutputs(c) {
  const box = $('#out-' + c.id); if (!box) return;
  $$('[data-markdown]', box).forEach(el => {
    if (el._leeCodeFrame) cancelAnimationFrame(el._leeCodeFrame);
    for (const v of (el._leeCodeViews || [])) try { LeeCM.destroy(v); } catch {}
  });
  box.innerHTML = '';
  // A prompt cell's "output" is the answer, and it is stored in the cell rather than in
  // an nbformat output -- so it renders from its own fields.
  if (c.cell_type === 'prompt') {
    if ((c.calls || []).length) {
      const steps = document.createElement('div'); steps.className = 'lee-agent-steps lee-cell-agent-steps';
      for (const activity of c.calls) {
        const row = document.createElement('details'); renderAgentStep(row, activity); steps.appendChild(row);
      }
      box.appendChild(steps);
    }
    if (c.reply) {
      const reply = document.createElement('div');
      reply.className = 'lee-reply'; box.appendChild(reply);
      renderMarkdown(reply, c.reply);
      const usage = usageMeta(c.usage, '', c.usage?.model); if (usage) box.appendChild(usage);
    }
    return;
  }
  for (const o of (c.outputs || [])) box.appendChild(outputEl(o));
}

const stripAnsi = (s) => String(s).replace(/\x1b\[[0-9;]*m/g, '');
const MAX_OUTPUT_CHARS = 60000;
function outputText(el, value) {
  const text = String(value || '');
  if (text.length <= MAX_OUTPUT_CHARS) { el.textContent = text; return; }
  el.textContent = text.slice(0, MAX_OUTPUT_CHARS);
  const folded = document.createElement('button');
  folded.className = 'lee-output-fold';
  folded.textContent = `show ${(text.length - MAX_OUTPUT_CHARS).toLocaleString()} more characters`;
  folded.title = 'Large outputs are folded to keep the notebook responsive';
  folded.onclick = () => { el.textContent = text; };
  el.appendChild(folded);
}

function closeInlinePopover() { $('.lee-inline-popover')?.remove(); }
function valueLensMeta(item) {
  return [item.type && item.type !== 'result' ? item.type : '', item.shape ? `shape ${item.shape}` : '',
          item.dtype ? `dtype ${item.dtype}` : ''].filter(Boolean).join(' · ') || 'runtime value';
}
function openValueLens(item, anchor, label = '') {
  if (!item) return;
  closeInlinePopover();
  const p = document.createElement('aside');
  p.className = 'lee-inline-popover lee-value-lens'; p.setAttribute('role', 'dialog');
  p.setAttribute('aria-label', `${label || item.name || 'result'} runtime value`);
  p.innerHTML = `<div class="lee-inline-head"><strong>${esc(label || item.path || item.name || 'result')}</strong>` +
    `<span>${esc(valueLensMeta(item))}</span><button class="lee-icon" aria-label="close">×</button></div>` +
    `<div class="lee-value-tree"></div><div class="lee-inline-actions">` +
    `<button class="lee-btn" data-copy>copy value</button>` +
    (item.accessor?.length && item.accessor[0] !== '_' ? `<button class="lee-btn" data-variables>variables</button>` : '') + `</div>`;
  const tree = $('.lee-value-tree', p);
  const row = (value, depth = 0) => {
    const shell = document.createElement('div'); shell.className = 'lee-value-node';
    const button = document.createElement('button'); button.className = 'lee-value-row';
    button.style.setProperty('--depth', depth);
    button.innerHTML = `<span class="lee-value-caret">${value.is_container ? '›' : ''}</span>` +
      `<strong>${esc(value.name || 'result')}</strong><small>${esc(value.type || '')}</small>` +
      `<span>${esc(value.value || '')}</span>`;
    shell.appendChild(button);
    if (value.is_container && value.accessor?.length) {
      const kids = document.createElement('div'); kids.className = 'lee-value-kids'; kids.hidden = true; shell.appendChild(kids);
      let open = false, loaded = false;
      button.onclick = async () => {
        open = !open; button.classList.toggle('open', open); kids.hidden = !open;
        if (!open || loaded) return;
        kids.innerHTML = '<div class="lee-value-loading">reading children…</div>';
        try {
          const acc = encodeURIComponent(JSON.stringify(value.accessor));
          const values = await api(`/vars/expand?accessor=${acc}&scope=${lee.execScope}`);
          kids.innerHTML = ''; values.forEach(child => kids.appendChild(row(child, depth + 1)));
          if (!values.length) kids.innerHTML = '<div class="lee-value-loading">no children</div>';
          loaded = true;
        } catch (e) { kids.innerHTML = `<div class="lee-value-error">${esc(e.message || e)}</div>`; }
      };
    }
    return shell;
  };
  tree.appendChild(row(item)); document.body.appendChild(p);
  const a = anchor?.getBoundingClientRect() || {left: innerWidth / 2, right: innerWidth / 2, top: innerHeight / 2, bottom: innerHeight / 2};
  const r = p.getBoundingClientRect(), below = a.bottom + 6;
  p.style.left = Math.max(8, Math.min(a.right - r.width, innerWidth - r.width - 8)) + 'px';
  p.style.top = (below + r.height < innerHeight - 8 ? below : Math.max(8, a.top - r.height - 6)) + 'px';
  $('[aria-label="close"]', p).onclick = closeInlinePopover;
  $('[data-copy]', p).onclick = () => { navigator.clipboard?.writeText(item.value || ''); status('value copied', 'ok'); };
  const show = $('[data-variables]', p);
  if (show) show.onclick = async () => {
    closeInlinePopover(); leePane('right', true); leeRight('vars'); await leeVars(); setScope('vars');
    const found = $$('#vars .lee-vrow').find(r => r.dataset.name === item.name);
    if (found) { selectVar(found); found.scrollIntoView({block: 'nearest'}); }
  };
}
window.openValueLens = openValueLens;
window.addEventListener('lee-inline-open', e => openValueLens(e.detail?.item, e.detail?.anchor));
document.addEventListener('pointerdown', e => {
  if ($('.lee-inline-popover') && !e.target.closest('.lee-inline-popover, .cm-lee-inline-value')) closeInlinePopover();
}, true);
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeInlinePopover(); }, true);

function outputTone(o) {
  if (o.output_type === 'error') return 'error';
  if (o.output_type === 'stream' && o.name === 'stderr')
    return /\b(?:warning|warns?|deprecated|deprecation)\b/i.test(String(o.text || '')) ? 'warning' : 'log';
  if (o.output_type === 'execute_result' || o.output_type === 'display_data') return 'result';
  return 'output';
}
function outputEl(o) {
  const d = document.createElement('div');
  const tone = outputTone(o);
  d.className = `lee-out ${tone}`;
  if (o.output_type === 'stream') { outputText(d, o.text); return d; }
  if (o.output_type === 'error') {
    outputText(d, stripAnsi((o.traceback || []).join('\n')) || `${o.ename}: ${o.evalue}`);
    return d;
  }
  const data = o.data || {};
  if (data['image/png']) {
    const i = document.createElement('img');
    i.src = 'data:image/png;base64,' + data['image/png'];
    d.appendChild(i); return d;
  }
  if (data['text/markdown']) {
    d.classList.add('lee-md-output'); renderMarkdown(d, data['text/markdown']); return d;
  }
  if (data['text/html'] || data['image/svg+xml']) {
    // Rich reprs get their own shadow root. pandas ships a <style> block with every
    // DataFrame and `scoped` has been dead for years, so without this an output could
    // restyle the IDE around it. Very large HTML stays unparsed until requested: parsing
    // a multi-megabyte table on the main thread is enough to trigger Chrome's hang dialog.
    const rich = data['text/html'] || data['image/svg+xml'];
    const show = () => { d.textContent = ''; d.attachShadow({mode: 'open'}).innerHTML = rich; };
    if (rich.length > MAX_OUTPUT_CHARS) {
      const folded = document.createElement('button'); folded.className = 'lee-output-fold';
      folded.textContent = `render large rich output (${Math.round(rich.length / 1024).toLocaleString()}kb)`;
      folded.onclick = show; d.appendChild(folded);
    } else show();
    return d;
  }
  outputText(d, data['text/plain'] || '');
  return d;
}

function paintSel() {
  $$('.lee-cell').forEach(el => {
    const i = +el.dataset.i, selected = lee.cellSelection.has(i) || (!lee.cellSelection.size && i === lee.sel);
    el.classList.toggle('sel', selected); el.setAttribute('aria-selected', String(selected));
  });
}
function selectCell(i, extend = false) {
  if (!lee.cells.length) return;
  lee.sel = Math.max(0, Math.min(i, lee.cells.length - 1));
  if (extend) {
    const lo = Math.min(lee.cellAnchor, lee.sel), hi = Math.max(lee.cellAnchor, lee.sel);
    lee.cellSelection = new Set(Array.from({length: hi - lo + 1}, (_, n) => lo + n));
  } else { lee.cellAnchor = lee.sel; lee.cellSelection = new Set([lee.sel]); }
  paintSel();
}
function focusCell(i) {
  selectCell(i);
  const c = lee.cells[lee.sel]; if (!c) return;
  const cell = $(`.lee-cell[data-i="${lee.sel}"]`);
  // CodeMirror focuses its own scroller but cannot reveal itself inside the notebook's
  // outer scroller. Run-and-advance therefore used to move the caret below the viewport.
  cell?.scrollIntoView({block: 'nearest', inline: 'nearest'});
  const v = ensureCellMounted(lee.sel);
  if (v) requestAnimationFrame(() => LeeCM.focus(v));
}
function focusCellPage(direction) {
  if (!lee.cells.length) return;
  const host = $('#editor'), current = $(`.lee-cell[data-i="${lee.sel}"]`);
  if (!host || !current) return focusCell(lee.sel + direction);
  const target = current.getBoundingClientRect().top + direction * Math.max(180, host.clientHeight * .78);
  const cells = $$('.lee-cell', host);
  const candidates = cells.filter(el => direction < 0 ? +el.dataset.i < lee.sel : +el.dataset.i > lee.sel);
  if (!candidates.length) return focusCell(direction < 0 ? 0 : lee.cells.length - 1);
  const next = candidates.reduce((best, el) =>
    Math.abs(el.getBoundingClientRect().top - target) < Math.abs(best.getBoundingClientRect().top - target) ? el : best);
  focusCell(+next.dataset.i);
}
function autoSaveEnabled() { return (lee.filePrefs.autoSave || 'afterDelay') !== 'off'; }
function normalizeSavedText(text) {
  const prefs=lee.filePrefs||{}; let out=String(text??'');
  if(prefs.trimTrailingWhitespace)out=out.split('\n').map(line=>line.replace(/[ \t]+$/,'')).join('\n');
  if(prefs.trimFinalNewlines)out=out.replace(/\n+$/,'');
  if(prefs.insertFinalNewline && out && !out.endsWith('\n'))out+='\n';
  return out;
}
function setTabSaveState(tab, state, detail = '') {
  if (!tab) return;
  const dot = $('.lee-save-state', tab); if (!dot) return;
  const labels = {
    pending: lee.path ? 'Changes queued for autosave' : 'Unsaved — choose a filename to save',
    saving: 'Saving changes…', saved: 'Saved on disk', error: 'Autosave failed',
  };
  dot.className = `lee-save-state ${state}`;
  dot.title = detail || labels[state] || state;
  dot.setAttribute('aria-label', dot.title);
  tab.dataset.saveState = state;
}
function scheduleAutoSave() {
  clearTimeout(lee.autoSaveTimer);
  if ((lee.filePrefs.autoSave || 'afterDelay') !== 'afterDelay' || !lee.path || lee.heldSaveConflicts.has(lee.path)) return;
  const version = lee.editVersion;
  lee.autoSaveTimer = setTimeout(async () => {
    if (lee.saving || version !== lee.editVersion) return scheduleAutoSave();
    lee.saving = true;
    setTabSaveState($('.lee-tab.active'), 'saving');
    try { await saveTab(true, version); }
    finally { lee.saving = false; if (version !== lee.editVersion) scheduleAutoSave(); }
  }, Math.max(100, Number(lee.filePrefs.autoSaveDelay) || 900));
}
document.addEventListener('focusout',e=>{if(lee.filePrefs.autoSave==='onFocusChange'&&!lee.heldSaveConflicts.has(lee.path)&&e.target.closest?.('.cm-editor')&&$('.lee-tab.active.dirty'))saveTab(true);});
window.addEventListener('blur',()=>{if(lee.filePrefs.autoSave==='onWindowChange'&&!lee.heldSaveConflicts.has(lee.path)&&$('.lee-tab.active.dirty'))saveTab(true);});
function markDirty() {
  lee.editVersion += 1;
  const t = $('.lee-tab.active');
  if (t) { t.classList.add('dirty'); setTabSaveState(t, 'pending'); }
  scheduleAutoSave();
}
/* Put a position in the middle of the view rather than merely inside it.

   `scrollIntoView` moves the *minimum* distance, so a match below the fold arrives on the last
   visible line with nothing under it -- and a search result is something you are about to read
   around, not just look at. Written against `scrollDOM` rather than CodeMirror's own centring
   effect: the vendored bundle is committed and rebuilding it needs node.

   A notebook scrolls its column of cells, not the cell's own editor, so the element that can
   actually move is the one that gets scrolled. */
function centreOnPos(v, pos) {
  const coords = v.coordsAtPos(pos); if (!coords) return;
  const own = v.scrollDOM, host = own.scrollHeight - own.clientHeight > 4 ? own : $('#editor');
  if (!host) return;
  const box = host.getBoundingClientRect();
  host.scrollTop += (coords.top + coords.bottom) / 2 - (box.top + box.height / 2);
}

function jumpToLine(line) {
  const v = lee.kind === 'notebook' ? lee.editors.get(lee.cells[lee.sel]?.id) : lee.editors.get('file');
  if (!v) return;
  const n = Math.max(1, Math.min(Number(line) || 1, v.state.doc.lines));
  const pos = v.state.doc.line(n).from;
  v.dispatch({selection: {anchor: pos}, scrollIntoView: true}); v.focus();
  // After the layout `scrollIntoView` just caused, or the measurement is of the old position.
  requestAnimationFrame(() => centreOnPos(v, pos));
}
function openLocation(hit) {
  // A hit in a notebook reports two coordinates: `line` in the .ipynb JSON, which is what
  // ripgrep and blame speak, and the cell plus the line inside it, which is the only pair an
  // editor can open. Prefer the second when the server placed the hit; a notebook hit it could
  // not place keeps the file line, and lands nowhere, rather than opening a cell chosen at random.
  const name = hit.path.split('/').pop();
  const inCell = Number(hit.cell_line) > 0;
  if (!inCell && /\.ipynb$/i.test(hit.path)) {
    // Nowhere to scroll to: the JSON line is not a line of any cell's editor, and jumping to
    // it inside whichever cell happens to be selected would look like an answer.
    leeOpenFile(hit.path);
    return status(`${name} — line ${hit.line} of the notebook file is in no cell`, 'info');
  }
  const line = inCell ? Number(hit.cell_line) : hit.line;
  lee.pendingLocation = {path: hit.path, line,
                         cellId: hit.cell || '',
                         cellIndex: Number.isFinite(hit.cell_index) ? Number(hit.cell_index) : -1};
  leeOpenFile(hit.path);
  status(`${name}${inCell ? ` · cell ${Number(hit.cell_index) + 1}` : ''}:${line}`);
}

async function stopCell(i) {
  const c = lee.cells[i];
  if (!c?.running) return status(`cell ${i + 1} is not running`, 'err');
  status(`stopping cell ${i + 1}…`);
  const r = await post('/nb/interrupt', {path: lee.tabKey || '', id: c.id});
  status(r.forced ? 'cell stopped · kernel restarted because interrupt was ignored' : 'cell stopped',
         r.forced ? 'err' : 'ok');
}

async function runCell(i, advance) {
  const c = lee.cells[i]; if (!c) return;
  if (c.running) return status(`cell ${i + 1} is already running`, 'err');
  const runPath = lee.path, cellId = c.id;
  const v = ensureCellMounted(i);
  const src = v ? LeeCM.getDoc(v) : c.source;
  const el = $(`.lee-cell[data-i="${i}"]`);
  if (c.cell_type === 'markdown') {
    // Rendering must not make the source editor disappear permanently. Keep both visible:
    // the preview is evidence of Run, and the source remains one click away to edit.
    const out = $('#out-' + c.id);
    if (out) {
      out.innerHTML = '<div class="lee-md"></div>';
      renderMarkdown(out.querySelector('.lee-md'), src, true);
    }
  } else if (c.cell_type === 'prompt') {
    c.running = true;
    try { await askCell(i, src, el); }
    finally { c.running = false; }
  } else {
    // PyCharm/Jupyter users expect code run from a file-backed notebook to be visible to
    // code that reads that notebook during the cell (indexers, nbdev, papermill). Flush
    // the complete browser document before execution; otherwise a newly created .ipynb
    // can still be zero-byte on disk while its in-memory cell is already running.
    if (lee.path && $('.lee-tab.active.dirty') && !await saveTab(true)) {
      return status('save the notebook before running this cell', 'err');
    }
    const began = performance.now();
    c.running = true;
    el?.classList.add('running');
    setCellState(c, 'running');
    setCellTime(c, 0, true);
    const cellClock = setInterval(() => setCellTime(c, performance.now() - began, true), 100);
    $('#g-' + c.id).textContent = '[*]';
    status(`running cell ${i + 1}…`);
    try {
      let r = null;
      await postEvents('/nb/run/stream', {i, id: cellId, path: runPath || lee.tabKey || '', source: src}, (event, data) => {
        const stillHere = lee.path === runPath && lee.cells[i]?.id === cellId;
        if (!stillHere) return;
        if (event === 'output') {
          lee.cells[i].outputs = data.outputs || [];
          renderOutputs(lee.cells[i]);
        } else if (event === 'error') throw new Error(data.text || 'cell execution failed');
        else if (event === 'done') r = data;
      });
      if (!r) throw new Error('cell execution ended without a result');
      const stillHere = lee.path === runPath && lee.cells[i]?.id === cellId;
      if (!stillHere) { leeVars(); return; }
      // Preserve the mounted cell object and its source/editor relationship. Replacing it
      // wholesale made stale buffer state able to win on a later remount and show blanks.
      Object.assign(c, r.cell);
      renderOutputs(r.cell);
      LeeCM.setInlineValues(v, r.inline || []);
      if (r.result) requestAnimationFrame(() => openValueLens(r.result, $('#out-' + c.id) || el, 'expression result'));
      $('#g-' + c.id).textContent = '[' + (r.cell.execution_count ?? ' ') + ']';
      const elapsed = Number(c.execution_ms ?? (performance.now() - began));
      const duration = formatCellTime(elapsed);
      setCellTime(c, elapsed, false);
      setCellState(c, r.ok ? 'done' : 'error', r.ok ? `ran successfully in ${duration}` : `failed after ${duration}`);
      status(r.ok ? `cell ${i + 1} ran in ${duration}` : `cell ${i + 1} failed after ${duration}`,
             r.ok ? 'ok' : 'err');
    } catch (e) {
      const elapsed = performance.now() - began;
      c.execution_ms = elapsed; setCellTime(c, elapsed, false);
      setCellState(c, 'error', `run failed after ${formatCellTime(elapsed)}`);
      status(String(e.message || e), 'err');
    } finally { clearInterval(cellClock); }
    c.running = false;
    el?.classList.remove('running');
    leeVars();
  }
  if (advance === 'insert') { await nbEdit({op: 'insert', i: i + 1}); focusCell(i + 1); }
  else if (advance) { if (i + 1 < lee.cells.length) focusCell(i + 1); else { await nbEdit({op: 'insert', i: i + 1}); focusCell(i + 1); } }
}

function paintDebugInlineValues(view, lineNo, variables) {
  if (!view || !lineNo || lee.debugPrefs.showInlineValues === false) return;
  const line = view.state.doc.line(Math.min(lineNo, view.state.doc.lines));
  const names = new Set((line.text.match(/[_A-Za-z]\w*/g) || []));
  const values = (variables || []).filter(v => names.has(v.name)).map(v => ({
    line: line.number, name: v.name, value: v.value || '', type: v.type || '',
    shape: null, dtype: null, is_grid: false, accessor: ['debug', Number(v.variablesReference) || 0],
  }));
  LeeCM.setInlineValues(view, values);
}

async function revealDebugFrame(state) {
  const frame = (state.frames || []).find(f => f.id === state.frame_id) || state.frames?.[0];
  if (!frame) return;
  // Exactly one source line is current. Clear the old marker before moving, including
  // when step-in changes files.
  for (const [key, view] of lee.editors) if (key !== 'exec') { LeeCM.setDebugLine(view, 0); LeeCM.setInlineValues(view, []); }
  if (frame.open_path) {
    $('#debugsource')?.remove();
    if (lee.path !== frame.open_path) {
      lee.pendingLocation = {path: frame.open_path, line: frame.line, debug: true,
                             cellId: frame.cell_id || ''};
      leeOpenFile(frame.open_path);
      return;
    }
    if (frame.cell_id && lee.kind === 'notebook') {
      const i = lee.cells.findIndex(c => c.id === frame.cell_id);
      if (i >= 0) {
        selectCell(i); const view = ensureCellMounted(i);
        LeeCM.setDebugLine(view, frame.line); paintDebugInlineValues(view, frame.line, state.variables); jumpToLine(frame.line);
      }
    } else {
      const view = lee.editors.get('file');
      if (view) { LeeCM.setDebugLine(view, frame.line); paintDebugInlineValues(view, frame.line, state.variables); jumpToLine(frame.line); }
    }
    return;
  }
  // Library frames are outside the workspace sandbox. Ask by frame id (never by an
  // arbitrary browser path) and show a read-only source view so step-in remains useful.
  if(lee.directDebug)return;
  const src = await api(`/nb/debug/source?frame_id=${frame.id}`);
  let pane = $('#debugsource');
  if (!pane) {
    pane = document.createElement('aside'); pane.id = 'debugsource'; pane.className = 'lee-debug-source-pane';
    pane.innerHTML = `<div class="lee-mhead">debug source <span class="sub"></span>` +
                     `<button class="lee-icon" aria-label="close">×</button></div>` +
                     `<div class="lee-debug-source-editor"></div>`;
    pane.querySelector('[aria-label="close"]').onclick = () => pane.remove();
    document.body.appendChild(pane);
  }
  pane.querySelector('.lee-mhead .sub').textContent = src.path || src.name || 'external frame';
  const host = pane.querySelector('.lee-debug-source-editor'); host.innerHTML = '';
  if (host._leeView) LeeCM.destroy(host._leeView);
  host._leeView = createEditor(host, {doc: src.content || '', lang: 'python', readOnly: true, lineNums: true});
  LeeCM.setDebugLine(host._leeView, src.line); const pos = host._leeView.state.doc.line(Math.min(src.line, host._leeView.state.doc.lines)).from;
  host._leeView.dispatch({selection: {anchor: pos}, scrollIntoView: true});
}

async function debugEvaluate(expression){return post(lee.directDebug?'/debug/evaluate':'/nb/debug/evaluate',lee.directDebug?{expression,frame_id:lee.debugState?.frame_id}:{code:expression,frame_id:lee.debugState?.frame_id});}
async function paintDebugWatches(panel=$('#debugger')){const host=$('.lee-debug-watches',panel);if(!host)return;host.innerHTML=lee.debugWatches.map((expression,i)=>`<div class="lee-debug-watch" data-i="${i}"><strong>${esc(expression)}</strong><span>evaluating…</span><button aria-label="remove">×</button></div>`).join('')||'<div class="lee-dim">no watch expressions</div>';
  $$('.lee-debug-watch',host).forEach(async row=>{row.querySelector('button').onclick=()=>{lee.debugWatches.splice(+row.dataset.i,1);localStorage.setItem('lee-debug-watches',JSON.stringify(lee.debugWatches));paintDebugWatches(panel);};try{const r=await debugEvaluate($('strong',row).textContent);$('span',row).textContent=r.result??r.value??'';}catch(e){$('span',row).textContent=e.message||String(e);}});}

function paintDebugger(state) {
  lee.debugState = state;
  let panel = $('#debugger');
  if (!panel) {
    panel = document.createElement('aside'); panel.id = 'debugger'; panel.className = 'lee-debugger';
    document.body.appendChild(panel);
  }
  const frames = state.frames || [], vars = state.variables || [];
  panel.innerHTML = `<div class="lee-debug-head"><strong>Paused at line ${esc(frames[0]?.line || '?')}</strong>` +
    `<span>${esc(frames[0]?.name || '')}</span><div class="lee-debug-controls">` +
    `<button title="continue" onclick="leeDebugControl('continue')">▶</button>` +
    `<button title="step over" onclick="leeDebugControl('next')">↷</button>` +
    `<button title="step into" onclick="leeDebugControl('stepIn')">↓</button>` +
    `<button title="step out" onclick="leeDebugControl('stepOut')">↑</button>` +
    `<button title="stop" onclick="leeDebugStop()">■</button></div></div>` +
    `<div class="lee-debug-body"><section><h4>call stack</h4>${frames.map(f =>
      `<button class="lee-debug-frame ${f.id === state.frame_id ? 'active' : ''}" onclick="leeDebugFrame(${f.id})">` +
      `${esc(f.name)} <span>line ${esc(f.line)}</span></button>`).join('')}</section>` +
    `<section><h4>locals <span class="lee-dim">expand in Variables</span></h4>${vars.map(v => `<div class="lee-debug-var"><strong>${esc(v.name)}</strong>` +
      `<span>${esc(v.value)}</span><small>${esc(v.type || '')}</small></div>`).join('') || '<div class="lee-dim">no locals</div>'}` +
    `<h4>watch</h4><form class="lee-debug-watch-form"><input class="lee-input" placeholder="expression"><button class="lee-btn">add</button></form><div class="lee-debug-watches"></div>` +
    `<h4>debug console</h4><form class="lee-debug-console-form"><input class="lee-input" placeholder="evaluate in selected frame"><button class="lee-btn">run</button></form><div class="lee-debug-console-out"></div></section></div>`;
  $('.lee-debug-watch-form',panel).onsubmit=e=>{e.preventDefault();const input=$('input',e.currentTarget),expression=input.value.trim();if(expression&&!lee.debugWatches.includes(expression)){lee.debugWatches.push(expression);localStorage.setItem('lee-debug-watches',JSON.stringify(lee.debugWatches));input.value='';paintDebugWatches(panel);}};
  $('.lee-debug-console-form',panel).onsubmit=async e=>{e.preventDefault();const input=$('input',e.currentTarget),expression=input.value.trim();if(!expression)return;try{const r=await debugEvaluate(expression);$('.lee-debug-console-out',panel).textContent=`${expression} → ${r.result??r.value??''}`;}catch(error){$('.lee-debug-console-out',panel).textContent=error.message||String(error);}};
  paintDebugWatches(panel);
  revealDebugFrame(state).catch(e => status(String(e.message || e), 'err'));
  leeScope('live'); leeRight('vars'); leeVars();
}

async function leeDebugFrame(frameId) {
  try {
    const state = await api(`${lee.directDebug?'/debug/state':'/nb/debug/state'}?frame_id=${frameId}`);
    paintDebugger(state);
  } catch (e) { status(String(e.message || e), 'err'); }
}
window.leeDebugFrame = leeDebugFrame;

async function leeDebugControl(command) {
  try {
    await post(lee.directDebug?'/debug/control':'/nb/debug/control', {command, thread_id: lee.debugThread});
    $('#debugger')?.classList.add('running'); status(`debugger: ${command}`);
  } catch (e) { status(String(e.message || e), 'err'); }
}
window.leeDebugControl = leeDebugControl;

async function leeDebugStop() {
  try { await post(lee.directDebug?'/debug/stop':'/nb/debug/stop', {}); } catch (_) {}
  lee.debugThread = null; lee.debugCell = null; lee.debugState = null; lee.directDebug=false;
  $('#debugger')?.remove(); $('#debugsource')?.remove();
  for (const [key, view] of lee.editors) if (key !== 'exec') { LeeCM.setDebugLine(view, 0); LeeCM.setInlineValues(view, []); }
  leeScope('live'); leeVars(); status('debugger stopped', 'ok');
}
window.leeDebugStop = leeDebugStop;

async function debugCell(i) {
  const c = lee.cells[i]; if (!c || c.cell_type !== 'code') return;
  if (lee.debugCell != null) return status('a debugger session is already active', 'err');
  const view = ensureCellMounted(i), source = LeeCM.getDoc(view);
  let breakpoints = lee.breakpoints.get(c.id) || [];
  if (!breakpoints.length) {
    breakpoints = [LeeCM.lineOf(view)]; rememberBreakpoints(c.id, breakpoints);
    LeeCM.setBreakpoints(view, breakpoints);
  }
  lee.debugCell = i; c.running = true; setCellState(c, 'running');
  status(`starting ipykernel debugger for cell ${i + 1}…`);
  let done = null;
  try {
    await postEvents('/nb/debug/stream', {i, id: c.id, path: lee.path || lee.tabKey || '', source, breakpoints}, (event, data) => {
      if (event === 'ready') {
        rememberBreakpoints(c.id, data.breakpoints || breakpoints);
        LeeCM.setBreakpoints(view, data.breakpoints || breakpoints);
      } else if (event === 'stopped') {
        lee.debugThread = data.thread_id; $('#debugger')?.classList.remove('running');
        paintDebugger(data); status(`paused at line ${data.frames?.[0]?.line || '?'}`, 'ok');
      } else if (event === 'continued') {
        lee.debugThread = null; lee.debugState = null; $('#debugger')?.classList.add('running');
        for (const [key, editor] of lee.editors) if (key !== 'exec') { LeeCM.setDebugLine(editor, 0); LeeCM.setInlineValues(editor, []); }
        leeVars();
      } else if (event === 'done') done = data;
      else if (event === 'error') throw new Error(data.text || 'debugger failed');
    });
    if (done?.cell) {
      Object.assign(c, done.cell); renderOutputs(c);
      $('#g-' + c.id).textContent = '[' + (c.execution_count ?? ' ') + ']';
      setCellState(c, done.ok ? 'done' : 'error');
    }
    status(done?.ok ? 'debug session finished' : (done?.error || 'debug session failed'), done?.ok ? 'ok' : 'err');
  } catch (e) { setCellState(c, 'error'); status(String(e.message || e), 'err'); }
  finally {
    c.running = false; lee.debugThread = null; lee.debugCell = null; lee.debugState = null;
    $('#debugger')?.remove(); $('#debugsource')?.remove();
    for (const [key, view] of lee.editors) if (key !== 'exec') { LeeCM.setDebugLine(view, 0); LeeCM.setInlineValues(view, []); }
    leeScope('live'); leeVars();
  }
}
window.leeDebugCell = debugCell;

/* Running a prompt cell. The answer lands in the cell rather than in the pane below,
 * which is the point of the cell type: it saves with the notebook and reads in order.
 *
 * The tab is deliberately *not* re-mounted afterwards even though the assistant's tools
 * may have edited files -- /tab/state reloads the notebook from disk, which would throw
 * away the answer that has not been saved yet. Files it changed are reported instead. */
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

