// A later tab must not take the answers asked for an earlier one.
let fileExtrasVersion = 0;

/* An image, in the same chrome as a PDF. Fit is the default because an image opened from a vault
   or a file tree is being identified rather than inspected. The dimensions are shown either way,
   since "is this the 2x asset" is the usual question. */
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

function mountMedia(host, st) {
  const name = (st.path || '').split('/').pop() || st.kind;
  const raw = '/file/raw/' + encodeURIComponent(name) + '?path=' + encodeURIComponent(st.path);
  const tag = st.kind === 'audio' ? 'audio' : 'video';
  host.innerHTML =
    `<div class="lee-doc"><div class="lee-doc-head"><span>${esc(compactPath(st.path))}</span>` +
    `<span class="lee-spacer"></span><a class="lee-btn" href="${esc(raw)}" target="_blank" rel="noopener noreferrer">open externally</a>` +
    `<a class="lee-btn" href="${esc(raw)}&download=true" download>download</a></div>` +
    `<div class="lee-doc-body lee-media-body"><${tag} class="lee-media" controls src="${esc(raw)}">` +
    `${esc(name)} could not be played by this browser.</${tag}></div></div>`;
}

/* The setting names the three views `source`, `preview` and `split`; the buttons and the stage's
   CSS have always said `edit`, `rendered` and `split`, so the names meet here and nowhere else.
   Adopted once a page: `origins` still says `default` until the settings are read again, so a
   second adoption would put the old key back over a view chosen since. */
const MD_VIEWS = {source: 'edit', preview: 'rendered', split: 'split'};
const MD_PREFS = {edit: 'source', rendered: 'preview', split: 'split'};
let mdAdopted = false;
async function adoptMdView() {
  if (mdAdopted) return;
  mdAdopted = true;
  await prefAdopt('workbench', 'markdownView', 'lee-md-view', v => MD_PREFS[v] || 'split');
}

const lspAnswers = new Map();
function paintCrumbSymbols(d) {
  const el = $('#editorcrumbs'); if (!el) return;
  const names = (d.symbols || []).slice(0, 40).map(s => `<button data-line="${(s.range?.start?.line || 0) + 1}">${esc(s.name)}</button>`).join('');
  el.insertAdjacentHTML('beforeend', `<i>›</i><span class="lee-breadcrumb-symbols">${names}</span>`);
  el.onclick = e => { const b = e.target.closest('[data-line]'); if (b) jumpToLine(b.dataset.line); };
}
// The server answers a mount's two questions slowly or not at all, so they are asked once the tab has
// painted and is still the one on screen, and a clean file's answer is kept for its disk version.
function lspExtras(v, st, crumbMode, mine, dirty) {
  if (!servedLang(st.lang) || !st.path) return;
  const asks = [];
  if (lee.editorPrefs.inlayHints) asks.push(['/lsp/inlay-hints', d => LeeCM.setInlayHints?.(v, d.hints || [])]);
  if (['symbols', 'pathAndSymbols'].includes(crumbMode)) asks.push(['/lsp/symbols', paintCrumbSymbols]);
  if (!asks.length) return;
  const live = () => mine === fileExtrasVersion && lee.editors.get('file') === v;
  requestAnimationFrame(() => setTimeout(() => {
    if (!live()) return;
    const text = LeeCM.getDoc(v);
    for (const [url, paint] of asks) {
      const key = `${url} ${st.path} ${st.disk_version}`, known = !dirty && lspAnswers.get(key);
      if (known) { paint(known); continue; }
      api(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({path: st.path, text})})
        .then(d => {
          if (!live()) return;
          if (!dirty && st.disk_version && (d.hints || d.symbols || []).length) {
            lspAnswers.set(key, d); if (lspAnswers.size > 60) lspAnswers.delete(lspAnswers.keys().next().value);
          }
          paint(d);
        }).catch(() => {});
    }
  }, 300));
}

async function mountFile(host, st) {
  const isProject = st.path?.endsWith('/pyproject.toml') || st.title === 'pyproject.toml';
  const crumbMode=lee.workbenchPrefs.breadcrumbs||'pathAndSymbols',crumb=crumbMode==='off'?'':`<nav class="lee-breadcrumbs" id="editorcrumbs" aria-label="File and symbol path"><span>${esc(compactPath(st.path||st.title||''))}</span></nav>`;
  // Markdown gets a rendered pane beside the editor. The editor stays mounted in every view and is
  // only hidden by CSS, so saving, autosave, blame, the change gutter and jump-to-line all keep
  // reaching `lee.editors.get('file')`.
  const isMd = (st.lang || '') === 'markdown';
  if (isMd) await adoptMdView();
  const view = isMd ? (MD_VIEWS[prefGet('workbench', 'markdownView', 'source')] || 'split') : '';
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
  // Nothing in the editor depends on these two answers, and awaiting them held an empty box on
  // screen for as long as they took: `/editor/packages` starts an interpreter to read version
  // metadata, and `/git/file` is four git subprocesses. Together they were 80 to 200ms of blank
  // pyproject. The file is mounted from the text `/tab/state` already carried, and each answer is
  // applied when it lands, to the editor it was asked for.
  let git = {ranges: []}, packages = null;
  lee.fileGit = git;
  const key = st.path || st.title;
  const v = createEditor($('#filecm'), {
    // A cached value is authoritative only after a real user edit, or a stale empty entry blanks
    // a freshly loaded file.
    doc: lee.dirtyBuffers.has(key) ? lee.buffers.get(key) : (st.text || ''),
    lang: st.lang || 'python', readOnly: !!st.read_only, lineNums: true, lintPath: st.path || '', tableKeys: true,
    completeUrl: '/complete', changedLines: git.ranges || [], breakpoints: lee.breakpoints.get(st.path)||[],
    onBreakpoint: st.lang==='python' ? lines=>{rememberBreakpoints(st.path,lines);if(lee.directDebug)post('/debug/breakpoints',{path:st.path,breakpoints:lines}).catch(e=>status(e.message||String(e),'err'));} : null,
    onChangeClick: line => showChangePopup(st.path, line),
    onDefinition: name => findDefinition(name), onSelection: () => {
      clearTimeout(selectionHelpTimer); selectionHelpTimer = setTimeout(showSelectionHelp, 120);
    },
    onChange: txt => {
      rememberBuffer(key, {path: key, kind: 'text', text: txt}); markDirty();
      // The preview follows the buffer, not the file. `renderMarkdown` is debounced and drops
      // superseded renders, so this is safe on every keystroke.
      if (isMd) renderMarkdown($('#mdpreview'), txt);
    },
  });
  lee.editors.set('file', v);
  if (isMd) {
    // The rendered pane carries the same change marks as the gutter, placed by block rather than
    // by line. Only this first render is annotated. See `paintMarkdownFileChanges`.
    renderMarkdown($('#mdpreview'), LeeCM.getDoc(v), false,
                   el => paintMarkdownFileChanges(el, git.ranges || []));
    $('#mdview').onclick = e => {
      const b = e.target.closest('[data-md-view]'); if (!b) return;
      const next = b.dataset.mdView;
      prefSet('workbench', 'markdownView', MD_PREFS[next] || 'split');
      $('.lee-md-stage').dataset.view = next;
      $$('#mdview .lee-seg').forEach(x => x.classList.toggle('active', x === b));
      // The editor was display:none a moment ago, so CodeMirror has stale measurements and draws
      // the cursor in the wrong place until it re-measures.
      if (next !== 'rendered') requestAnimationFrame(() => LeeCM.focus(v));
    };
  }
  const mine = ++fileExtrasVersion;
  lspExtras(v, st, crumbMode, mine, lee.dirtyBuffers.has(key));
  if (packages) paintPackageVersions(v, packages);
  if (st.path) {
    api('/git/file?path=' + encodeURIComponent(st.path)).then(d => {
      if (mine !== fileExtrasVersion || !d) return;
      lee.fileGit = d;
      LeeCM.setChangedLines(v, d.ranges || []);
      if (isMd) paintMarkdownFileChanges($('#mdpreview'), d.ranges || []);
    }).catch(() => {});
    if (isProject && lee.workbenchPrefs.dependencyHints !== false)
      api('/editor/packages?path=' + encodeURIComponent(st.path))
        .then(d => { if (mine === fileExtrasVersion && d) paintPackageVersions(v, d); }).catch(() => {});
  }
  closeChangePopup(); armChangeGutter($('#filecm'));
  $('#filecm').addEventListener('focusin', () => { lee.activeEditor='primary'; setScope('editor'); });
}

/* What the second pane can hold. A notebook goes in as a reading copy: its cells are what a person
   compares across a merge, and the editors, the kernel and the selection all belong to one notebook
   at a time. The live surfaces are bound to the pane they were opened in and are not offered. */
const SPLIT_KINDS = {text: 'editable', notebook: 'reading copy', pdf: 'view', image: 'view'};

function secondaryNotebook(host, st) {
  "The cells of a notebook, to read beside something else. No editors, no outputs, no execution."
  const cells = (st.cells || []).map((c, i) =>
    `<article class="lee-split-cell ${esc(c.cell_type)}"><header>${i + 1} · ${esc(c.cell_type)}` +
    `${c.execution_count != null ? ` · [${esc(String(c.execution_count))}]` : ''}</header>` +
    `<pre>${esc(String(c.source || ''))}</pre></article>`).join('');
  host.querySelector('.lee-split-body').innerHTML =
    cells || '<div class="lee-dim">this notebook has no cells</div>';
}

function splitStage(direction) {
  "The second pane, shown beside the editor with its editor destroyed and its side page dropped."
  const stage=$('#editorstage'),host=$('#editor2'); if (!stage || !host) return null;
  if (lee.editors.get('secondary')) { LeeCM.destroy(lee.editors.get('secondary')); lee.editors.delete('secondary'); }
  lee.sidePage = null;
  stage.classList.add('split',`split-${direction}`); stage.classList.remove(`split-${direction==='vertical'?'horizontal':'vertical'}`);
  host.hidden=false; setSplitSize(localStorage.getItem(SPLIT_SIZE)); return host;
}

async function mountSecondary(path, direction = 'vertical') {
  const stage=$('#editorstage'),host=$('#editor2'); if (!stage || !host) return;
  const st=await api('/tab/state?path='+encodeURIComponent(path));
  if (!SPLIT_KINDS[st.kind]) return status(`a ${st.kind || 'blank'} tab cannot be opened beside another; text, notebooks, PDFs and images can`,'err');
  if (st.kind !== 'text') {
    splitStage(direction);
    host.innerHTML=`<div class="lee-split-head"><span>${esc(compactPath(st.path||path))}</span>` +
      `<span class="lee-dim">${esc(SPLIT_KINDS[st.kind])}</span>` +
      `<button class="lee-btn" onclick="leeCloseSplit()">close</button></div>` +
      `<div class="lee-split-body" id="filecm2"></div>`;
    if (st.kind === 'notebook') secondaryNotebook(host, st);
    else if (st.kind === 'pdf') mountPdf($('.lee-split-body', host), st);
    else mountImage($('.lee-split-body', host), st);
    recordDiskVersion(st.path || path, st.disk_version || '');
    lee.secondaryPath = path; lee.activeEditor = 'primary';
    localStorage.setItem('lee-editor-split', JSON.stringify({path, direction}));
    return;
  }
  splitStage(direction); host.innerHTML=`<div class="lee-split-head"><span>${esc(compactPath(st.path))}</span><button class="lee-btn" onclick="leeCloseSplit()">close</button></div><div class="lee-cm" id="filecm2"></div>`;
  const key=st.path,view=createEditor($('#filecm2'),{doc:lee.dirtyBuffers.has(key)?lee.buffers.get(key):(st.text||''),lang:st.lang||'python',readOnly:!!st.read_only,lineNums:true,lintPath:st.path||'',completeUrl:'/complete',tableKeys:true,
    onDefinition:name=>findDefinition(name),onChange:txt=>{rememberBuffer(key,{path:key,kind:'text',text:txt});lee.editVersion+=1;const tab=$$('.lee-tab').find(x=>x.title===key);tab?.classList.add('dirty');setTabSaveState(tab,'pending');scheduleAutoSave();}});
  recordDiskVersion(st.path || path, st.disk_version || '');
  lee.editors.set('secondary',view);lee.secondaryPath=path;$('#filecm2').addEventListener('focusin',()=>{lee.activeEditor='secondary';setScope('editor');});localStorage.setItem('lee-editor-split',JSON.stringify({path,direction}));LeeCM.focus(view);
}
function mountPage(url, title = '', direction = 'vertical') {
  "The local Leela page `url` in the second pane, in a frame with `pane=1`. False when `url` is not local or there is no second pane."
  const src = leePaneURL(url), host = src && splitStage(direction === 'horizontal' ? 'horizontal' : 'vertical');
  if (!host) return false;
  const head = document.createElement('div'), trail = document.createElement('span'), own = document.createElement('a'),
    x = document.createElement('button'), frame = document.createElement('iframe');
  head.className = 'lee-split-head'; trail.className = 'lee-split-trail'; own.className = 'lee-split-own';
  own.textContent = 'Open in a tab'; own.target = '_blank'; own.rel = 'noopener'; own.title = 'Open this page in a new tab';
  x.className = 'lee-btn'; x.type = 'button'; x.textContent = 'close'; x.onclick = leeCloseSplit;
  frame.src = src; head.append(trail, own, x); host.replaceChildren(head, frame);
  const page = lee.sidePage = {frame, url: leeOwnURL(url), title: String(title || ''), trail: [], direction: direction === 'horizontal' ? 'horizontal' : 'vertical',
    at(u, t) { page.url = leeOwnURL(u); if (t) page.title = t; paintSidePage(page); },
    open(u) { const p = leePaneURL(u); if (!p) return; try { frame.contentWindow.location.replace(p); } catch (_) { frame.src = p; } },
    link: openExternal,
    key: k => document.body.dispatchEvent(new KeyboardEvent('keydown', {...k, bubbles: true, cancelable: true})),   // the keymap on `window` decides
    close: leeCloseSplit};
  lee.secondaryPath = ''; lee.activeEditor = 'primary';
  paintSidePage(page);
  return true;
}
function paintSidePage(page) {
  "The trail, the title and the Open in a tab link of the side page, as text, and the page kept for a reload."
  const head = page.frame.previousElementSibling, trail = $('.lee-split-trail', head), b = document.createElement('strong');
  trail.replaceChildren();
  for (const [label, href] of page.trail) {
    const a = document.createElement('a'); a.textContent = label; a.href = href;
    a.onclick = e => { e.preventDefault(); page.trail = []; page.open(href); };
    trail.append(a, ' › ');
  }
  b.textContent = page.title || 'Side page'; trail.append(b);
  page.frame.title = b.textContent; $('.lee-split-own', head).href = leeOwnURL(page.url);
  localStorage.setItem('lee-editor-split', JSON.stringify({page: page.url, title: page.title, direction: page.direction}));
}
function leeCloseSplit(){const stage=$('#editorstage'),host=$('#editor2'),v=lee.editors.get('secondary');if(v)LeeCM.destroy(v);lee.editors.delete('secondary');lee.sidePage=null;lee.secondaryPath='';lee.activeEditor='primary';stage?.classList.remove('split','split-vertical','split-horizontal');if(host){host.hidden=true;host.innerHTML='';}localStorage.removeItem('lee-editor-split');}
window.leeCloseSplit=leeCloseSplit;
function leeSplit(direction='vertical') {
  // Any open tab the second pane can hold, not only the text ones: two notebooks beside each other
  // is what a person merging them is looking for.
  const rows=$$('.lee-tab').filter(t=>SPLIT_KINDS[t.dataset.kind]&&t.title!==lee.path)
    .map(t=>({path:t.title,kind:t.dataset.kind,label:$('.lee-tab-name',t)?.textContent||t.title}));
  if (!rows.length) return status('open another file before splitting','err');
  const m=modal(`<div class="lee-mhead">Split editor<span class="sub">${direction==='vertical'?'side by side':'top and bottom'}</span></div><div class="lee-modallist">${rows.map((r,i)=>`<button class="lee-mrow" data-i="${i}"><strong>${esc(r.label)}</strong><span class="sub">${esc(r.kind)} · ${esc(compactPath(r.path))}</span></button>`).join('')}</div>`);
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
  return cells.flatMap((c, i) => c.cell_type === 'markdown' ? String(c.source || '').split('\n').flatMap((line, n) => {
    const m = /^(#{1,6})\s+(.+?)\s*$/.exec(line);
    return m ? [{i, level: m[1].length, text: m[2].replace(/[*_`]/g, ''), folds: n === 0 && headingLevel(c) > 0}] : [];
  }) : []);
}
function notebookToc(cells) {
  const headings = notebookHeadings(cells);
  const toc = document.createElement('details'); toc.className = 'lee-nb-toc';
  toc.innerHTML = `<summary>contents <span>${headings.length || 'no'} sections</span></summary><nav></nav>`;
  const nav = toc.querySelector('nav');
  if (!headings.length) nav.innerHTML = '<div class="lee-dim">Add Markdown headings to build the outline.</div>';
  else headings.forEach(h => {
    const row = document.createElement('div'); row.className = 'lee-toc-row'; row.style.setProperty('--level', h.level);
    // Only a cell's first line is a heading that folds; a later one in the same cell is a place to go.
    row.innerHTML = `<button class="lee-toc-jump">${esc(h.text)}</button>` + (h.folds
      ? `<button class="lee-toc-fold" data-i="${h.i}" title="collapse or expand this section">${headingFolded(cells[h.i]) ? '+' : '−'}</button>` : '');
    row.querySelector('.lee-toc-jump').onclick = () => { toc.open = false; focusCell(h.i); };
    const fold = row.querySelector('.lee-toc-fold'); if (fold) fold.onclick = () => toggleHeading(h.i);
    nav.appendChild(row);
  });
  return toc;
}
function observeNotebookCells(host, cells) {
  // Cell shells preserve the notebook's geometry, and CodeMirror is only created near the
  // viewport, so a 150-cell notebook paints immediately instead of constructing 150 editors in
  // one uninterruptible task.
  //
  // Built when the pane stops, not while it moves. Constructing one editor costs a whole frame in
  // the engine the packaged app runs, and scrolling a 155-cell notebook end to end crosses about
  // eighty of them: 103ms frames against 17 idle. Waiting for the scroll to settle builds the same
  // editors and holds 60fps throughout.
  lee.cellObserver?.disconnect();
  clearTimeout(lee.cellMountTimer);
  const owed = lee.cellsOwed = new Set();
  const drain = () => {
    lee.cellMountTimer = 0;
    for (const i of owed) ensureCellMounted(i);
    owed.clear();
  };
  lee.cellObserver = new IntersectionObserver(entries => {
    for (const e of entries) if (e.isIntersecting) {
      owed.add(+e.target.dataset.i); lee.cellObserver?.unobserve(e.target);
    }
    if (!owed.size) return;
    clearTimeout(lee.cellMountTimer);
    lee.cellMountTimer = setTimeout(drain, 120);
  }, {root: host, rootMargin: '700px 0px'});
  $$('.lee-cell', host).forEach((el, i) => {
    if (i === lee.sel || cells[i]?.running) ensureCellMounted(i);
    else lee.cellObserver.observe(el);
  });
}

/* Coming back to a notebook built every cell of it again, and laying a hundred of those out is what
   a switch costs: 319KB of elements for a 100-cell notebook, about 160ms of layout in the window
   Leela ships and 10 to 30 in Chrome. The shells are kept per file on the way out and reattached on
   the way back, so only the editors near the viewport are built again.

   Kept only for a file that was clean, and taken only when the file has not moved under it: a shell
   carries the cell's summary line and its outputs, and both are answers about a particular version. */
const nbShells = new Map();
const NB_SHELLS = 4;

function keepNotebookShells(host, key, version) {
  if (!host || !key || !version || !$('.lee-cell', host)) return;
  const frag = document.createDocumentFragment();
  while (host.firstChild) frag.appendChild(host.firstChild);
  // The views are already destroyed. What they left behind is not a shell, so it goes.
  frag.querySelectorAll('.lee-cm').forEach(cm => { cm.innerHTML = ''; });
  nbShells.delete(key);
  nbShells.set(key, {frag, version, ids: [...frag.querySelectorAll('.lee-cell')].map(el => el.dataset.id).join()});
  for (const stale of [...nbShells.keys()].slice(0, nbShells.size - NB_SHELLS)) nbShells.delete(stale);
}

function takeNotebookShells(host, st) {
  const key = st.path || st.title, held = key && nbShells.get(key);
  if (!held || held.version !== `${st.disk_version}@${st.version}` || held.ids !== st.cells.map(c => c.id).join()) return false;
  nbShells.delete(key);          // moving a fragment empties it, so it is good for one mount
  host.appendChild(held.frag);
  return true;
}

function mountNotebook(host, st) {
  lee.cellObserver?.disconnect();
  for (const [key, view] of [...lee.editors.entries()]) {
    if (key === 'exec' || key === 'file') continue;
    LeeCM.destroy(view); lee.editors.delete(key);
  }
  host.innerHTML = '';
  lee.headingHidden = hiddenIds(st.cells);
  if (!takeNotebookShells(host, st)) {
    host.appendChild(notebookToc(st.cells));
    st.cells.forEach((c, i) => host.appendChild(cellEl(c, i)));
  }
  paintHeadings(st.cells);
  for (const c of st.cells) if (isExercise(c)) renderExercise(c);
  selectCell(Math.min(lee.sel, st.cells.length - 1));
  observeNotebookCells(host, st.cells);
  lee.notebookGit = {};       // marks belong to the notebook that was open, not the next one
  paintNotebookGitMarks();
  queueNotebookOverview();    // a notebook outside a repository still gets its viewport thumb
}

function patchNotebook(host, before, cells, op = '') {
  // Keep unchanged cell DOM and CodeMirror views alive. Moving those nodes is free and, unlike
  // rebuilding the notebook, cannot flash blank or reset the viewport.
  lee.cellObserver?.disconnect();
  const oldCells = new Map(before.map(c => [c.id, c]));
  const oldEls = new Map($$('.lee-cell', host).map(el => [el.dataset.id, el]));
  const ids = new Set(cells.map(c => c.id));
  lee.headingHidden = hiddenIds(cells);
  for (const [id, el] of oldEls) if (!ids.has(id)) {
    const view = lee.editors.get(id); if (view) LeeCM.destroy(view);
    lee.editors.delete(id); el.remove();
  }
  const toc = notebookToc(cells), oldToc = $('.lee-nb-toc', host);
  if (oldToc) oldToc.replaceWith(toc); else host.prepend(toc);
  cells.forEach((c, i) => {
    const old = oldCells.get(c.id);
    let el = oldEls.get(c.id);
    // Against what the editor holds now: `before` shares its cell objects with code that rewrites them.
    const ed = lee.editors.get(c.id), held = ed ? LeeCM.getDoc(ed) : old?.source;
    const changed = !old || held !== c.source || old.cell_type !== c.cell_type;
    if (!el || changed) {
      const view = lee.editors.get(c.id); if (view) LeeCM.destroy(view);
      lee.editors.delete(c.id);
      const key = `${lee.tabKey}:${c.id}`;
      lee.buffers.set(key, c.source); lee.dirtyBuffers.add(key);
      const fresh = cellEl(c, i);
      if (el) el.replaceWith(fresh);
      el = fresh;
    } else {
      el.dataset.i = i;
      el.className = 'lee-cell ' + c.cell_type + (lee.collapsedCells.has(c.id) ? ' collapsed' : '') + (lee.headingHidden.has(c.id) ? ' heading-hidden' : '');
      const buttons = $('.lee-cellbtns', el); if (buttons) buttons.innerHTML = cellButtons(i);
      const summary = $('.lee-cell-summary', el);
      if (summary) summary.textContent = String(c.source || '').trim().split('\n')[0] || 'empty cell';
      paintCellMeta(el, c, i);   // an insert above renumbers every cell after it
      const gutter = $('#g-' + c.id); if (gutter) gutter.textContent = gutterFor(c);
      const context = $('.lee-cell-context', el); if (context) paintCellContext(context, c);
      const slide = $('.lee-cell-slide', el); if (slide) paintCellSlide(slide, c);
      setCellState(c, cellState(c)); setCellTime(c, c.execution_ms, c.running);
      if (op === 'clear' || op === 'clear_cell') renderOutputs(c);
    }
    host.appendChild(el); // appending an existing node reorders it without remounting
    if (c.extra?.lesson) { paintLessonCell(el, c); renderLessonReveal(c); }
    paintGuideButton(el, c);
    if (isExercise(c)) renderExercise(c, el);
  });
  paintHeadings(cells);
  paintSel();
  observeNotebookCells(host, cells);
  // `className` is rewritten above for every reused cell, so the marks are reapplied from what
  // was last read rather than refetched. Only the DOM moved.
  repaintNotebookGitMarks();
  queueNotebookOverview();
}

function ensureCellMounted(i) {
  const c = lee.cells[i];
  if (!c || lee.editors.has(c.id)) return lee.editors.get(c?.id);
  mountCell(c, i);
  return lee.editors.get(c.id);
}

// A prompt cell's gutter is its own mark, so the three kinds are told apart without reading them.
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
  refreshCellMeta(c);           // the run count and the outputs it left are in the tooltip
  queueNotebookOverview();      // a failure is one of the two things the stripe reports
}
//: The kernel is a new one: a presentation clears what it showed from the old one.
const kernelRestarted = () => dispatchEvent(new CustomEvent('lee-kernel-restart'));
function markPreviousRuns() {
  for (const c of lee.cells) {
    if (c.cell_type !== 'code' || c.execution_count == null) continue;
    c.fresh = false; setCellState(c, 'previous'); setCellTime(c, c.execution_ms, false);
  }
  kernelRestarted();
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

