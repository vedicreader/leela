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

/* The WebKit in some macOS versions plays no Ogg or WebM, so a file that fails says so and offers the
   system's own player rather than a silent, empty control. */
function mountMedia(host, st) {
  const name = (st.path || '').split('/').pop() || st.kind;
  const raw = '/file/raw/' + encodeURIComponent(name) + '?path=' + encodeURIComponent(st.path);
  const tag = st.kind === 'audio' ? 'audio' : 'video';
  host.innerHTML =
    `<div class="lee-doc"><div class="lee-doc-head"><span>${esc(compactPath(st.path))}</span>` +
    `<span class="lee-spacer"></span><button class="lee-btn" data-media-open>open in default app</button>` +
    `<a class="lee-btn" href="${esc(raw)}&download=true" download>download</a></div>` +
    `<div class="lee-doc-body lee-media-body"><${tag} class="lee-media" controls preload="metadata" src="${esc(raw)}"></${tag}></div></div>`;
  const open = () => post('/media/open?path=' + encodeURIComponent(st.path))
    .then(() => status('opened in the default app', 'ok')).catch(e => status(String(e.message || e), 'err'));
  $('[data-media-open]', host).onclick = open;
  $('.lee-media', host).onerror = () => {
    const body = $('.lee-media-body', host);
    if (!body) return;   // the tab has moved on
    body.innerHTML = `<div class="lee-err" data-media-error>${esc(name)} cannot play here. ` +
      `Open it in the default app.<br><button class="lee-btn" data-media-open>open in default app</button></div>`;
    $('.lee-media-body [data-media-open]', host).onclick = open;
  };
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

//: A Markdown file keeps its view in its own key, so a tab comes back as it was left. `dflt` is for a file with none.
const mdViewOf = (path, dflt) => { try { const v = localStorage.getItem('lee-md-view:' + path); return ['edit', 'split', 'rendered'].includes(v) ? v : dflt; } catch (_) { return dflt; } };
const mdViewKeep = (path, v) => { try { localStorage.setItem('lee-md-view:' + path, v); } catch (_) {} };
function mdShell(path, view, ids, note = '') {
  "The view switch and the stage of a Markdown file: its editor and its rendered copy. `ids` names the three nodes, so two panes never share one."
  return `<div class="lee-doc-head lee-md-bar"><div class="lee-segbar" id="${ids.bar}" aria-label="markdown view">` +
    ['edit', 'split', 'rendered'].map(v => `<button class="lee-seg${v === view ? ' active' : ''}" data-md-view="${v}">${v}</button>`).join('') +
    `</div><span class="lee-spacer"></span>${note ? `<span class="lee-dim">${note}</span>` : ''}</div>` +
    // `data-md-base` is this file's folder: a figure written `![](img/a.png)` is relative to the document, not to the page.
    `<div class="lee-md-stage" data-view="${view}" data-md-base="${esc((path || '').slice(0, (path || '').lastIndexOf('/')))}">` +
    `<div class="lee-cm" id="${ids.cm}"></div><div class="lee-md-preview" id="${ids.preview}" data-markdown=""></div></div>`;
}
function mdWire(bar, view, path, onPick) {
  "Make the view switch in `bar` change its stage, remember the choice for `path`, and tell `onPick` the new view."
  bar.onclick = e => {
    const b = e.target.closest('[data-md-view]'); if (!b) return;
    const next = b.dataset.mdView;
    bar.parentElement.nextElementSibling.dataset.view = next;
    $$('.lee-seg', bar).forEach(x => x.classList.toggle('active', x === b));
    mdViewKeep(path, next); onPick?.(next);
    // The editor was display:none a moment ago, so CodeMirror has stale measurements and draws the cursor in the wrong place until it re-measures.
    if (next !== 'rendered') requestAnimationFrame(() => LeeCM.focus(view));
  };
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
  const view = isMd ? mdViewOf(st.path, MD_VIEWS[prefGet('workbench', 'markdownView', 'source')] || 'split') : '';
  host.innerHTML = crumb + (isProject ? '<div class="lee-package-summary" id="packagebar" hidden></div>' : '') +
    (isMd ? mdShell(st.path, view, {bar: 'mdview', cm: 'filecm', preview: 'mdpreview'}, 'the change gutter and blame stay on the source')
          : '<div class="lee-cm" id="filecm"></div>');
  if (st.note) host.insertAdjacentHTML('afterbegin', `<div class="lee-doc-head lee-readonly-note" role="note">${esc(st.note)}</div>`);
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
      if (isMd) renderMarkdown($('#mdpreview'), txt, false, el => rupakaFences(el, `file:${key}`));
    },
  });
  lee.editors.set('file', v);
  if (isMd) {
    // The rendered pane carries the same change marks as the gutter, placed by block rather than
    // by line. Only this first render is annotated. See `paintMarkdownFileChanges`.
    renderMarkdown($('#mdpreview'), LeeCM.getDoc(v), false,
                   el => { paintMarkdownFileChanges(el, git.ranges || []); rupakaFences(el, `file:${key}`); });
    mdWire($('#mdview'), v, st.path, next => prefSet('workbench', 'markdownView', MD_PREFS[next] || 'split'));
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

/* What the second pane can hold. A notebook goes in as a notebook to read and copy from: rendered
   Markdown, highlighted code, its outputs, and a copy action on each cell. It has no editor, no
   kernel and no run, so a read-only notebook shows the same; `swap panes` makes it the main one. */
const SPLIT_KINDS = {text: 'editable', notebook: 'notebook', pdf: 'view', image: 'view', office: 'view'};
const SIDE_CAP = 150;   //: cells drawn at first; a button draws the next ones

function sideClear() {
  "Drop the side pane's lazy editors and the observer that builds them."
  lee.sideObserver?.disconnect(); lee.sideObserver = null;
  for (const v of lee.sideViews || []) try { LeeCM.destroy(v); } catch (_) {}
  lee.sideViews = []; lee.sideNb = null;
}
const sidePayload = c => ({...JSON.parse(JSON.stringify(c)), running: false, fresh: false});
//: A cell's outputs as the text a person would paste.
const sideOutText = c => (c.outputs || []).map(o => o.output_type === 'stream' ? mimeText(o.text)
  : o.output_type === 'error' ? stripAnsi((o.traceback || []).join('\n')) || `${o.ename}: ${o.evalue}`
  : mimeText(o.data?.['text/plain']) ?? mimeText(o.data?.['text/markdown']) ?? '').filter(Boolean).join('\n');
function sideOutEl(o, i) {
  const data = o.data || {};
  // A widget needs its kernel, which this pane does not have: its text stands in.
  if (data[WIDGET_MIME] != null) o = {output_type: 'display_data', metadata: {}, data: {'text/plain': mimeText(data['text/plain']) || 'interactive output: open the notebook to use it'}};
  try { return outputEl(o, null, i); }
  catch (_) { return Object.assign(document.createElement('div'), {className: 'lee-out error', textContent: 'this output could not be drawn'}); }
}
async function sideCopy(text, what) {
  try { await navigator.clipboard.writeText(text); status(`${what} copied`, 'ok'); }
  catch (_) { status('clipboard access failed', 'err'); }
}
async function sideInsert(c) {
  if (lee.kind !== 'notebook') return status('open a notebook in the other pane to insert into it', 'err');
  if (lee.readOnly) return status(`${compactPath(lee.path)} is read-only`, 'err');
  const at = belowAt(lee.sel);
  if (!await nbEdit({op: 'paste_many', i: at, cells: [sidePayload(c)]})) return;
  focusCell(at); status(`cell inserted below cell ${at}`, 'ok');
}
async function cellToOther() {
  "Copy the selected cells of the main notebook to the end of the notebook in the side pane."
  const side = lee.sideNb;
  if (lee.kind !== 'notebook' || !side) return status('open two notebooks side by side first', 'err');
  if (side.path === lee.path) return status('both panes show the same notebook', 'err');
  if (side.read_only) return status(`${compactPath(side.path)} is read-only`, 'err');
  const cells = selectedCellIndices().map(cellClipboardPayload).filter(Boolean);
  if (!cells.length) return status('select a cell to copy', 'err');
  const seq = lee.sideSeq;
  let r;
  try { r = await post('/nb/edit', {op: 'paste_many', i: side.cells.length, cells, path: side.path, side: true}); }
  catch (e) { return status(String(e.message || e), 'err'); }
  if (seq !== lee.sideSeq) return;
  sideRender(side.body, {...side.st, cells: r.cells});
  if (!autoSaveEnabled()) return status(`${plural(cells.length, 'cell')} copied to ${compactPath(side.path)}; it is not saved yet`, 'ok');
  try { await post('/nb/save', {path: side.path}); status(`${plural(cells.length, 'cell')} copied to ${compactPath(side.path)} and saved`, 'ok'); }
  catch (e) { status(`copied, but not saved: ${e.message || e}`, 'err'); }
}
function sideCellEl(c, i, st) {
  const d = document.createElement('div'), md = c.cell_type === 'markdown', code = c.cell_type === 'code';
  d.className = 'lee-cell ' + c.cell_type; d.dataset.nbv = ''; d.dataset.i = i; d.dataset.id = c.id;
  d.style.setProperty('--lee-cell-lines', Math.min(20, Math.max(2, cellLines(c))));
  const b = (act, label, title) => `<button class="lee-cbtn" data-act="${act}" title="${esc(title)}">${label}</button>`;
  d.innerHTML = `<div class="lee-gutter"><div class="lee-execution-count">${esc(gutterFor(c))}</div></div>` +
    `<div class="lee-cellmain"><div class="lee-cell-chrome"><span class="lee-cell-meta"><span class="lee-cell-no">#${i + 1}</span>` +
    `<span class="lee-cell-size">${esc((code ? (LANG_TAGS[st.lang] || st.lang || 'py') : cellKind(c)) + ' · ' + plural(cellLines(c), 'line'))}</span></span>` +
    `<div class="lee-cellbtns">` + b('source', 'copy', 'copy the source of this cell') +
    (code && (c.outputs || []).length ? b('output', 'copy output', 'copy the output of this cell as text') : '') +
    b('cell', 'copy cell', 'copy this cell, then paste it in a notebook') +
    b('insert', 'insert', 'insert this cell below the selected cell of the notebook in the other pane') + `</div></div>` +
    (md ? '<div class="lee-md-cell lee-md"></div>' : '<div class="lee-cm"></div>') + '<div class="lee-nbv-out"></div></div>';
  return d;
}
function sideFill(d, c, st) {
  "Build what a cell scrolled into view shows: its editor or its Markdown, and its outputs."
  if (c.cell_type === 'markdown') {
    const el = $('.lee-md-cell', d); el.dataset.mdBase = (st.path || '').slice(0, (st.path || '').lastIndexOf('/'));
    renderMarkdown(el, c.source || '', true, mdPaint(c, false));
  } else lee.sideViews.push(createEditor($('.lee-cm', d), {doc: String(c.source || ''), lang: c.cell_type === 'code' ? (st.lang || 'python') : '',
    readOnly: true, lineNums: false, settings: {overviewMode: 'off'}}));
  const out = $('.lee-nbv-out', d); (c.outputs || []).forEach((o, i) => out.appendChild(sideOutEl(o, i)));
}
function sideRender(body, st) {
  "The cells of `st` in `body`: each as the notebook draws it, with copy actions."
  sideClear();
  const cells = st.cells || [];
  lee.sideNb = {path: st.path, read_only: !!st.read_only, cells, body, st};
  body.innerHTML = '';
  if (!cells.length) { body.innerHTML = '<div class="lee-dim">this notebook has no cells</div>'; return; }
  const io = lee.sideObserver = new IntersectionObserver(es => es.forEach(e => {
    if (!e.isIntersecting) return;
    io.unobserve(e.target); sideFill(e.target, cells[+e.target.dataset.i], st);
  }), {rootMargin: '700px 0px'});
  let drawn = 0;
  const more = () => {
    body.querySelector('[data-side-more]')?.remove();
    for (const end = Math.min(cells.length, drawn + SIDE_CAP); drawn < end; drawn++) { const d = sideCellEl(cells[drawn], drawn, st); body.appendChild(d); io.observe(d); }
    if (drawn < cells.length) body.insertAdjacentHTML('beforeend', `<button class="lee-btn" data-side-more>show ${Math.min(SIDE_CAP, cells.length - drawn)} more of ${cells.length - drawn} cells</button>`);
  };
  more();
  body.onclick = e => {
    if (e.target.closest('[data-side-more]')) return more();
    const b = e.target.closest('[data-act]'); if (!b) return;
    const c = cells[+b.closest('.lee-cell').dataset.i], act = b.dataset.act;
    if (act === 'source') sideCopy(String(c.source || ''), 'cell source');
    else if (act === 'output') sideCopy(sideOutText(c), 'output');
    else if (act === 'cell') { lee.cellClipboard = {cells: [sidePayload(c)], cell: sidePayload(c), from: st.path}; sideCopy(String(c.source || ''), 'cell'); }
    else if (act === 'insert') sideInsert(c);
  };
}

function splitStage(direction) {
  "The second pane, shown beside the editor with its editor destroyed and its side page dropped."
  const stage=$('#editorstage'),host=$('#editor2'); if (!stage || !host) return null;
  if (lee.editors.get('secondary')) { LeeCM.destroy(lee.editors.get('secondary')); lee.editors.delete('secondary'); }
  sideClear();
  lee.sidePage = null;
  stage.classList.add('split',`split-${direction}`); stage.classList.remove(`split-${direction==='vertical'?'horizontal':'vertical'}`);
  host.hidden=false; setSplitSize(localStorage.getItem(SPLIT_SIZE)); return host;
}

const sideHead = (path, ...bits) => `<div class="lee-split-head"><span>${esc(compactPath(path))}</span>${bits.join('')}<button class="lee-btn" onclick="leeCloseSplit()">close</button></div>`;

async function mountSecondary(path, direction = 'vertical') {
  const stage=$('#editorstage'),host=$('#editor2'); if (!stage || !host) return;
  const seq = lee.sideSeq = (lee.sideSeq || 0) + 1;   // a later mount or a close makes this one stale
  const st=await api('/tab/state?path='+encodeURIComponent(path));
  if (seq !== lee.sideSeq) return;
  if (st.kind === 'error') {
    splitStage(direction); lee.secondaryPath = ''; lee.activeEditor = 'primary';
    host.innerHTML = sideHead(path) + `<div class="lee-err">${esc(st.error)}</div>`;
    return;
  }
  if (!SPLIT_KINDS[st.kind]) {
    leeCloseSplit();
    return status(st.kind ? `a ${st.kind} tab cannot be opened beside another; text, notebooks, PDFs, images and office files can` : 'that file is not open any more', 'err');
  }
  if (st.kind !== 'text') {
    splitStage(direction);
    const nb = st.kind === 'notebook';
    host.innerHTML = sideHead(st.path||path, `<span class="lee-dim">${esc(SPLIT_KINDS[st.kind])}</span>`,
      nb && st.read_only ? '<span class="lee-dim" data-readonly>read only</span>' : '',
      nb ? '<button class="lee-btn" onclick="leeSwapSplit()" title="show this notebook in the main pane, and the main one here">swap panes</button>' : '') +
      `<div class="lee-split-body" id="filecm2"></div>`;
    if (nb) sideRender($('.lee-split-body', host), st);
    else if (st.kind === 'pdf') mountPdf($('.lee-split-body', host), st);
    else if (st.kind === 'office') mountOffice($('.lee-split-body', host), st);
    else mountImage($('.lee-split-body', host), st);
    recordDiskVersion(st.path || path, st.disk_version || '');
    lee.secondaryPath = path; lee.activeEditor = 'primary';
    localStorage.setItem('lee-editor-split', JSON.stringify({path, direction}));
    return;
  }
  const isMd = st.lang === 'markdown', key = st.path;
  splitStage(direction);
  host.innerHTML = sideHead(st.path, st.read_only ? '<span class="lee-dim" data-readonly>read only</span>' : '') +
    (isMd ? mdShell(key, mdViewOf(key, 'rendered'), {bar: 'mdview2', cm: 'filecm2', preview: 'mdpreview2'}) : '<div class="lee-cm" id="filecm2"></div>');
  const paint = txt => renderMarkdown($('#mdpreview2'), txt, false, el => rupakaFences(el, `file2:${key}`));
  const view=createEditor($('#filecm2'),{doc:lee.dirtyBuffers.has(key)?lee.buffers.get(key):(st.text||''),lang:st.lang||'python',readOnly:!!st.read_only,lineNums:true,lintPath:st.path||'',completeUrl:'/complete',tableKeys:true,
    onDefinition:name=>findDefinition(name),onChange:txt=>{rememberBuffer(key,{path:key,kind:'text',text:txt});lee.editVersion+=1;const tab=$$('.lee-tab').find(x=>x.title===key);tab?.classList.add('dirty');setTabSaveState(tab,'pending');scheduleAutoSave();if(isMd)paint(txt);}});
  if (isMd) { paint(LeeCM.getDoc(view)); mdWire($('#mdview2'), view, key); }
  recordDiskVersion(st.path || path, st.disk_version || '');
  lee.editors.set('secondary',view);lee.secondaryPath=path;$('#filecm2').addEventListener('focusin',()=>{lee.activeEditor='secondary';setScope('editor');});localStorage.setItem('lee-editor-split',JSON.stringify({path,direction}));LeeCM.focus(view);
}
async function leeOpenSide(path, direction = 'vertical') {
  "Show the file `path` beside the main one, opening it as a tab first when it is not one."
  if (!path) return status('select a file or open a tab first', 'err');
  if (path === lee.path) return status('that file is already open in the main pane', 'err');
  try {
    if (!$$('.lee-tab').some(t => t.title === path)) {
      const prev = lee.path;
      await leeOpenFile(path);
      if (prev) await leeOpenFile(prev);   // the file opens as a tab; the main pane stays where it was
    }
    await mountSecondary(path, direction);
  } catch (e) { status(String(e.message || e), 'err'); }
}
window.leeOpenSide = leeOpenSide;
async function leeSwapSplit() {
  "The side file becomes the main one, and the main one goes to the side."
  const side = lee.secondaryPath, main = lee.path, direction = $('#editorstage')?.classList.contains('split-horizontal') ? 'horizontal' : 'vertical';
  if (!side || !main) return;
  await leeOpenFile(side); await mountSecondary(main, direction);
}
window.leeSwapSplit = leeSwapSplit;
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
function leeCloseSplit(){const stage=$('#editorstage'),host=$('#editor2'),v=lee.editors.get('secondary');sideClear();lee.sideSeq=(lee.sideSeq||0)+1;if(v)LeeCM.destroy(v);lee.editors.delete('secondary');lee.sidePage=null;lee.secondaryPath='';lee.activeEditor='primary';stage?.classList.remove('split','split-vertical','split-horizontal');if(host){host.hidden=true;host.innerHTML='';}localStorage.removeItem('lee-editor-split');}
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
  nbShells.set(key, {frag, version, ids: [...frag.querySelectorAll('.lee-cell')].map(el => el.dataset.id).join(), cells: lee.cells});
  for (const stale of [...nbShells.keys()].slice(0, nbShells.size - NB_SHELLS)) nbShells.delete(stale);
}

//: `{key: version}` of each kept notebook, which `/tab/state` answers with `same` instead of its cells.
function heldNotebookVersions() {
  return Object.fromEntries([...nbShells].map(([key, held]) => [key, Number(held.version.split('@').pop())]));
}
function heldNotebookCells(key) { return nbShells.get(key)?.cells || []; }

function takeNotebookShells(host, st) {
  const key = st.path || st.title, held = key && nbShells.get(key);
  if (!held || held.version !== `${st.disk_version}@${st.version}` || held.ids !== st.cells.map(c => c.id).join()) return false;
  nbShells.delete(key);          // moving a fragment empties it, so it is good for one mount
  host.appendChild(held.frag);
  rupakaReviveIn(host);
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

