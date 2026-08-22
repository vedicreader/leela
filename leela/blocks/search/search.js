async function quickOpen(searchMode) {
  const d = await api('/fs/find');
  let hits = d.hits, sel = 0;
  const m = modal(
    `<input class="lee-input" id="qo" placeholder="${searchMode ? 'search files…' : 'open file…'}" autofocus>
     <div class="lee-modallist" id="qolist"></div>`,
    (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, hits.length - 1); paint(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); paint(); }
      else if (e.key === 'Enter') { e.preventDefault(); go(); }
    });
  const list = m.querySelector('#qolist'), input = m.querySelector('#qo');
  const paint = () => {
    list.innerHTML = hits.slice(0, 300).map((h, i) =>
      `<div class="lee-mrow${i === sel ? ' sel' : ''}" data-i="${i}">${esc(h.name)}<span class="sub">${esc(h.path)}</span></div>`).join('');
    list.querySelector('.sel')?.scrollIntoView({block: 'nearest'});
  };
  const go = () => { const h = hits[sel]; if (h) { m.remove(); leeOpenFile(h.path); } };
  list.addEventListener('click', e => { const r = e.target.closest('.lee-mrow'); if (r) { sel = +r.dataset.i; go(); } });
  // Each search walks the whole tree. Debounced and sequenced like the folder picker.
  let seq = 0, timer = null;
  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const mine = ++seq, q = input.value.trim();
      const found = (await api('/fs/find?q=' + encodeURIComponent(q))).hits;
      if (mine !== seq) return;
      hits = found; sel = 0; paint();
    }, 120);
  });
  paint(); setTimeout(() => input.focus(), 0);
}

// The modes, in the order Tab walks them. `all` leads and is the default: it ranks every backend
// together, so it is the one that answers without you having to know which store the thing you
// half-remember is in. A rail rather than a row because each one carries a count, and a count is
// the thing that tells you where to look next when the mode you picked came back empty.
const SEARCH_MODES = [
  ['all', 'all', 'rank ripgrep, symbols, FTS and semantic results together'],
  ['rg', 'rg', 'ripgrep: literal search over current files, fastest'],
  ['context', 'context', 'Kosha composed retrieval across repository code and installed packages'],
  ['repo', 'repo', 'Kosha repository code store'],
  ['env', 'packages', 'Kosha installed-package environment store'],
  ['symbols', 'symbols', 'Kosha symbols: repository and indexed packages'],
  ['ann', 'ANN', 'Kosha embedding ANN'],
];

async function codeSearch() {
  let hits = [], sel = 0, backend = '', previewView = null, searchSeq = 0;
  let mode = localStorage.getItem('lee-search-mode') || 'all';
  if (!SEARCH_MODES.some(([id]) => id === mode)) mode = 'all';
  const counts = {};
  const m = modal(
    `<div class="lee-searchbar"><input class="lee-input" id="cs" placeholder="search code, symbols and meaning…" autofocus>
     <button class="lee-btn" id="kosharefresh" type="button">sync</button></div>` +
    // Where and what, beside which backend. A workspace holds several checkouts, so "this
    // project" is the useful default and "everything open" is the deliberate widening.
    `<div class="lee-searchfilters">
       <label>in<select id="csscope">
         <option value="project">this project</option>
         <option value="workspace">every open folder</option></select></label>
       <label>files<input class="lee-input" id="csexts" placeholder="py, ts — blank for all"
              aria-label="restrict to file extensions"></label>
       <span class="lee-dim" id="csscopenote"></span></div>` +
    `<div class="lee-kosha-status" id="koshastatus"><span>Opening Kosha…</span></div>
     <div class="lee-code-search-body">
       <nav class="lee-searchrail" id="csrail" aria-label="search mode">${SEARCH_MODES.map(([id, label, tip]) =>
         `<button class="lee-searchrail-mode" data-mode="${id}" title="${esc(tip)}">` +
         `<span>${esc(label)}</span><b data-count-for="${id}"></b></button>`).join('')}
         <span class="lee-dim lee-searchrail-hint">tab / shift+tab</span></nav>
       <div class="lee-modallist" id="cslist"><div class="lee-dim">type to search repository + environment context</div></div>
       <aside class="lee-search-preview"><header><div><strong id="cspreviewtitle">Code preview</strong>` +
       `<span id="cspreviewmeta">Select a result</span></div>` +
       `<div class="lee-search-actions"><button class="lee-btn" id="cspkg" hidden>Package API</button>` +
       `<button class="lee-btn go" id="csopen" disabled>Open file</button></div></header>` +
       `<div id="cspreview"><div class="lee-search-preview-empty">Matches open here with syntax highlighting.</div></div>` +
       `<div class="lee-search-relations" id="csrelations"></div></aside></div>`,
    (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, hits.length - 1); paint(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); paint(); }
      else if (e.key === 'Enter') { e.preventDefault(); go(); }
      // Tab walks the modes rather than the focus. The dialog traps Tab anyway, so the only
      // thing given up is a focus order over four controls, and what is bought is trying the
      // same query against another backend without leaving the keyboard.
      else if (e.key === 'Tab') { e.preventDefault(); cycleMode(e.shiftKey ? -1 : 1); }
    }, () => {
      if (previewView) LeeCM.destroy(previewView);
      // Closing the dialog must stop the search too, or four backends go on working for a
      // question whose answer has nowhere left to be drawn.
      if (liveStream) { try { liveStream.close(); } catch {} liveStream = null; }
    });
  m.classList.add('lee-code-search-modal');
  const list = $('#cslist', m), input = $('#cs', m), preview = $('#cspreview', m), open = $('#csopen', m);
  const pkgBtn = $('#cspkg', m);
  const scopeEl = $('#csscope', m), extsEl = $('#csexts', m);
  // Remembered, because a person who works in Python does not want to retype `py` every time
  // they open this box -- and the scope they chose is a statement about how they work.
  scopeEl.value = localStorage.getItem('lee-search-scope') || 'project';
  extsEl.value = localStorage.getItem('lee-search-exts') || '';
  const paintRail = () => {
    $$('.lee-searchrail-mode', m).forEach(b =>
      b.classList.toggle('active', b.dataset.mode === mode));
    // A count only means something once that mode has actually run. Blank is "not asked yet",
    // which is a different thing from nought and must not look like it.
    SEARCH_MODES.forEach(([id]) => {
      const el = $(`[data-count-for="${id}"]`, m); if (!el) return;
      el.textContent = counts[id] == null ? '' : counts[id];
      el.classList.toggle('zero', counts[id] === 0);
    });
  };
  const setMode = next => {
    if (!next || next === mode) return;
    mode = next; localStorage.setItem('lee-search-mode', mode);
    paintRail();
    if (input.value.trim()) search(); else paint();
    input.focus();
  };
  const cycleMode = step => {
    const at = SEARCH_MODES.findIndex(([id]) => id === mode);
    const next = SEARCH_MODES[(at + step + SEARCH_MODES.length) % SEARCH_MODES.length];
    setMode(next[0]);
  };
  const showPreview = () => {
    if (previewView) { LeeCM.destroy(previewView); previewView = null; }
    const h = hits[sel];
    if (!h) {
      preview.innerHTML = '<div class="lee-search-preview-empty">No result selected.</div>';
      open.disabled = true; pkgBtn.hidden = true; return;
    }
    const filename = h.path.split('/').pop() || h.package || 'indexed source';
    $('#cspreviewtitle', m).textContent = h.symbol || filename;
    $('#cspreviewmeta', m).textContent = `${h.package ? h.package + ' · ' : ''}${filename}:${h.line} · ${(h.sources || [h.kind]).join(' + ')}`;
    // A package is a file like any other once the path is one this project can open; its API
    // listing is the second question, so it gets its own button.
    const environment = h.kind.startsWith('env-');
    open.disabled = !h.path && !(environment && h.package);
    open.textContent = h.path ? 'Open file' : environment && h.package ? 'Package API' : 'Indexed package';
    pkgBtn.hidden = !(environment && h.package && h.path);
    preview.innerHTML = '<div class="lee-search-preview-editor"></div>';
    previewView = mountCodeSurface($('.lee-search-preview-editor', preview), h.text || '(no indexed preview)',
                                   codeLang('', h.path), false);
    const relations = $('#csrelations', m), callers = h.callers || [];
    relations.innerHTML = callers.length ? `<span>called by</span>` + callers.map(name =>
      `<button data-symbol="${esc(name)}">${esc(name.split('.').pop())}</button>`).join('') : '';
    // Following a caller is a graph question, so it switches to the mode that answers one.
    $$('[data-symbol]', relations).forEach(button => button.onclick = () => {
      input.value = button.dataset.symbol;
      if (mode === 'context') search(); else setMode('context');
    });
  };
  const paint = () => {
    if (!hits.length) {
      list.innerHTML = `<div class="lee-dim">${backend ? 'no matches · ' + esc(backend) : 'type to search'}</div>`;
      showPreview(); return;
    }
    list.innerHTML = hits.map((h, i) => {
      const f = h.path.split('/').pop() || h.package || 'environment';
      const foundBy = (h.sources || [h.kind]).join(' + ');
      return `<button class="lee-search-result${i === sel ? ' sel' : ''}" data-i="${i}">` +
        `<span class="lee-search-result-kind">${esc(h.kind.startsWith('env-') ? 'PKG' : h.kind === 'file' ? 'FILE' : h.symbol ? 'SYM' : 'TXT')}</span>` +
        `<span><strong>${esc(h.symbol || h.text.split('\n')[0].slice(0, 90))}</strong>` +
        `<small>${esc(h.package ? h.package + ' · ' : '')}${esc(f)}:${h.line}</small></span>` +
        `<em>${esc(foundBy)}</em></button>`;
    }).join('');
    $('.lee-search-result.sel', list)?.scrollIntoView({block: 'nearest'}); showPreview();
  };
  /* A name Kosha knows the file for opens it; one it does not still answers the other question. */
  const packageApi = async h => {
    const d = await api('/code/package-api?package=' + encodeURIComponent(h.package));
    const box = modal(`<div class="lee-mhead">${esc(h.package)}<span class="sub">public API from Kosha</span></div>` +
      `<div class="lee-package-api"></div>`);
    const body = $('.lee-package-api', box), symbols = d.symbols || [];
    body.innerHTML = symbols.length ? symbols.map((row, i) => `<button data-api="${i}">` +
      `<strong>${esc(row.mod_name || '')}</strong><span>${esc(row.docstring || '')}</span>` +
      `<small>${esc(row.path ? compactPath(row.path) + ':' + row.line : 'no indexed file')}</small></button>`).join('') :
      '<div class="lee-dim">No exported API metadata found.</div>';
    $$('[data-api]', body).forEach(el => el.onclick = () => {
      const row = symbols[+el.dataset.api]; box.remove();
      if (row.path) { m.remove(); return openLocation({path: row.path, line: row.line || 1}); }
      input.value = row.mod_name || ''; search();
    });
  };
  const go = async () => {
    const h = hits[sel]; if (!h) return;
    if (h.path) { m.remove(); return openLocation(h); }
    if (!h.package) return status('package source is indexed read-only', 'info');
    await packageApi(h);
  };
  // One click opens at the line, because that is what the box is *for*. It used to select on the
  // first click and need a second one on the same row to go anywhere, so the obvious gesture
  // landed in a preview pane and looked like the result was not clickable. The preview is still
  // reachable without committing: arrow keys move the selection and paint it.
  list.onclick = e => {
    const row = e.target.closest('[data-i]'); if (!row) return;
    sel = +row.dataset.i; paint(); go();
  };
  open.onclick = go;
  pkgBtn.onclick = () => { const h = hits[sel]; if (h?.package) packageApi(h); };
  // `all` streamed: one section per backend, in the server's best-first leg order, each filling
  // in as that backend reports. Slots are stable on purpose -- rg answers in tens of milliseconds
  // and the embedding leg in seconds, and a list that re-ranked on every arrival would reshuffle
  // under the cursor precisely while someone was reading it. A hit a later leg finds again is not
  // shown twice; it adds its name to the row the first leg already produced, which is the same
  // merge the batch answer does.
  const streamAll = (q, seq) => new Promise(resolve => {
    const slots = new Map(), seen = new Map();
    let notes = [];
    const es = new EventSource('/search/stream?q=' + encodeURIComponent(q) +
                               '&scope=' + encodeURIComponent(scopeEl.value) +
                               '&exts=' + encodeURIComponent(extsEl.value.trim()));
    // Held so the next keystroke can close it. A stream left open keeps four backends working on
    // a question nobody is asking any more, and the server only notices when it next tries to
    // write -- which for the slow legs is seconds away.
    liveStream = es;
    const stop = () => { try { es.close(); } catch {} if (liveStream === es) liveStream = null; resolve(); };
    const recount = () => {
      hits = [];
      for (const leg of slots.keys()) hits.push(...slots.get(leg));
      counts.all = hits.length; paintRail();
    };
    es.addEventListener('start', e => {
      const d = JSON.parse(e.data);
      for (const leg of d.legs || []) slots.set(leg, []);      // fixes the order once
      const where = (d.searched || []).map(p => p.split('/').pop()).join(', ');
      $('#csscopenote', m).textContent = where ? `searched ${where}` : '';
    });
    es.addEventListener('leg', e => {
      if (seq !== searchSeq) return stop();
      const d = JSON.parse(e.data);
      if (d.note) notes.push(d.note);
      const kept = [];
      for (const h of d.hits || []) {
        const key = `${h.path}:${h.line}:${h.package || ''}`;
        const already = seen.get(key);
        if (already) { already.sources = [...new Set([...(already.sources || []), d.leg])]; continue; }
        seen.set(key, h); kept.push(h);
      }
      slots.set(d.leg, kept);
      recount();
      backend = `all · ${[...slots.keys()].filter(k => slots.get(k).length).join(' + ') || 'searching'}`;
      // The selection is an index into a list that just grew at the end, so it still points at
      // the row it pointed at. Only an empty list needs resetting.
      if (sel >= hits.length) sel = Math.max(0, hits.length - 1);
      paint();
    });
    es.addEventListener('done', e => {
      if (notes.length) backend += ' · ' + notes.slice(0, 2).join('; ');
      paint(); stop();
    });
    es.onerror = () => { backend = backend || 'search stream failed'; paint(); stop(); };
  });

  let timer, liveStream = null;
  const search = () => {
    clearTimeout(timer); const seq = ++searchSeq;
    if (liveStream) { try { liveStream.close(); } catch {} liveStream = null; }
    timer = setTimeout(async () => {
      const q = input.value.trim();
      if (!q) { hits = []; backend = ''; paint(); return; }
      if (mode === 'all') {
        hits = []; sel = 0; backend = 'all · searching';
        list.innerHTML = `<div class="lee-search-progress"><span></span>every backend, fastest first…</div>`;
        return streamAll(q, seq);
      }
      list.innerHTML = `<div class="lee-search-progress"><span></span>searching ${esc(mode === 'context' ? 'Kosha repo + environment context' : mode === 'all' ? 'rg, symbols, FTS and ANN' : mode)}…</div>`;
      try {
        const d = await api('/search?q=' + encodeURIComponent(q) + '&mode=' + mode +
                            '&scope=' + encodeURIComponent(scopeEl.value) +
                            '&exts=' + encodeURIComponent(extsEl.value.trim()));
        if (seq !== searchSeq) return;
        hits = d.hits || []; backend = d.backend + (d.note ? ' · ' + d.note : ''); sel = 0;
        // Which folders were actually walked, because "no matches" and "no matches *here*" are
        // different answers and only one of them means the thing is not in your code.
        const where = (d.searched || []).map(p => p.split('/').pop()).join(', ');
        $('#csscopenote', m).textContent = where ? `searched ${where}` : '';
        counts[mode] = hits.length; paintRail();
        paint(); status(`search: ${d.backend}${d.note ? ' — ' + d.note : ''}`);
      } catch (e) {
        if (seq !== searchSeq) return;
        hits = []; backend = e.message || String(e); paint(); status(backend, 'err');
      }
    }, mode === 'rg' ? 120 : mode === 'all' || mode === 'context' ? 360 : 280);
  };
  input.addEventListener('input', search);
  scopeEl.addEventListener('change', () => {
    localStorage.setItem('lee-search-scope', scopeEl.value);
    if (input.value.trim()) search();
  });
  extsEl.addEventListener('input', () => {
    localStorage.setItem('lee-search-exts', extsEl.value.trim());
    if (input.value.trim()) search();
  });
  api('/code/status').then(d => {
    const el = $('#koshastatus', m); if (!el) return;
    el.innerHTML = d.ok ? `<span class="ok">Kosha connected</span><span>${Number(d.files || 0).toLocaleString()} files</span>` +
      `<span>${Number(d.packages || 0).toLocaleString()} packages</span><span>${Number(d.graph_nodes || 0).toLocaleString()} graph nodes</span>` +
      `${d.stale_files ? `<span class="warn">${d.stale_files} stale files</span>` : ''}` : `<span class="warn">${esc(d.note || 'Kosha unavailable')}</span>`;
  }).catch(() => {});
  $('#kosharefresh', m).onclick = async () => {
    const button = $('#kosharefresh', m); button.disabled = true; button.textContent = 'syncing…';
    try { await post('/code/sync'); button.textContent = 'synced'; status('Kosha code, notebooks and graph synced', 'ok'); if (input.value.trim()) search(); }
    catch (e) { button.textContent = 'retry sync'; status(e.message || String(e), 'err'); }
    finally { button.disabled = false; }
  };
  $('#csrail', m).onclick = e => {
    const b = e.target.closest('[data-mode]'); if (!b) return;
    e.preventDefault(); setMode(b.dataset.mode);
  };
  paintRail();
  setTimeout(() => input.focus(), 0);
}

function cursorWord() {
  const v = curEditor(); return v ? LeeCM.wordAtCursor(v) : '';
}
async function findDefinition(name = cursorWord()) {
  if (!name) return status('put the cursor on a symbol first', 'err');
  status(`finding ${name}…`);
  const d = await api('/code/definition?name=' + encodeURIComponent(name) + '&path=' + encodeURIComponent(lee.path || ''));
  if (!(d.hits || []).length) return status(`no definition found for ${name}`, 'err');
  if (d.hits.length === 1) return openLocation(d.hits[0]);
  hitList(d.hits, `${d.backend} — ${d.note}`, `definitions of ${name}`, openLocation);
}
async function findUsages(name = cursorWord()) {
  if (!name) return status('put the cursor on a symbol first', 'err');
  const d = await api('/code/usages?name=' + encodeURIComponent(name));
  hitList(d.hits || [], `${d.backend} — ${d.note}`, `usages of ${name}`, openLocation);
}
/* The dotted chain the cursor ends, so `fastcore.test` reaches the server whole: nothing declares
   a module, and the last name alone found whichever package had a `def test`. Leftwards only --
   on `fastcore` the answer is the package. */
function dottedAtCursor(view) {
  const word = LeeCM.wordAtCursor(view); if (!word) return '';
  const line = view.state.doc.lineAt(LeeCM.cursor(view)), text = line.text;
  let i = LeeCM.cursor(view) - line.from;
  while (i > 0 && /\w/.test(text[i - 1])) i--;
  let j = i;
  while (j > 1 && text[j - 1] === '.' && /\w/.test(text[j - 2])) {
    j--; while (j > 0 && /\w/.test(text[j - 1])) j--;
  }
  return text.slice(j, i) + word;
}
/* Where the cursor is, in the coordinates a symbol lookup can use. A notebook cursor is a cell
   and a line inside it: the file line is a line of JSON and matches no declaration. */
function editorPlace(view = curEditor()) {
  const path = lee.path || '';
  if (!view) return {path, line: 0, cellIndex: -1, dotted: ''};
  const line = view.state.doc.lineAt(LeeCM.cursor(view)).number;
  const cellIndex = lee.kind === 'notebook'
    ? lee.cells.findIndex(c => lee.editors.get(c.id) === view) : -1;
  return {path, line, cellIndex, dotted: dottedAtCursor(view)};
}
/* One key, both directions. On a usage it goes to the declaration; standing on the declaration it
   lists who uses it, because that is the only question left to ask there. The server decides which,
   since it is the side that knows where the declaration is. */
async function gotoDeclaration(name = cursorWord(), place = editorPlace()) {
  if (!name) return status('put the cursor on a symbol first', 'err');
  status(`finding ${name}…`);
  let d;
  // a failed lookup has to say so: `finding…` is busy, and a busy toast never leaves by itself
  try {
    d = await api('/code/jump?name=' + encodeURIComponent(name) +
      '&path=' + encodeURIComponent(place.path) + '&line=' + place.line + '&cell_index=' + place.cellIndex +
      '&dotted=' + encodeURIComponent(place.dotted || ''));
  } catch (e) { return status(String(e.message || e), 'err'); }
  const hits = d.hits || [];
  if (!hits.length) return status(`nothing found for ${name}`, 'err');
  if (d.kind === 'definition' && hits.length === 1) return openLocation(hits[0]);
  const label = d.kind === 'usages' ? 'usages' : 'definitions';
  hitList(hits, `${d.backend} — ${d.note}`, `${label} of ${name}`, openLocation);
  // `finding…` is a busy toast, and a busy toast waits to be clicked. The list is the answer, so
  // the toast has to stop saying it is still looking.
  status(`${hits.length} ${label} of ${name}`, 'ok');
}
/* The mouse saying what mod+b says. CodeMirror owns the click, so this listens in the capture
   phase and takes the event there: letting it through would move the caret and select a word.

   Either modifier counts. Platform detection is not reliable enough to make it the gate: in a
   webview that reported no platform, ctrl+click both looked up the symbol and, being a right-click
   on macOS, opened the cell menu on top of the result. So the paired `contextmenu` is claimed too. */
function bindModClick() {
  document.addEventListener('contextmenu', e => {
    if (e.shiftKey || !(e.metaKey || e.ctrlKey) || !e.target?.closest?.('.cm-content')) return;
    e.preventDefault(); e.stopPropagation();
  }, true);
  document.addEventListener('mousedown', e => {
    if (e.button !== 0 || e.altKey || e.shiftKey || !(e.metaKey || e.ctrlKey)) return;
    if (!e.target?.closest?.('.cm-content')) return;
    const view = [...lee.editors.values()].find(v => v?.contentDOM?.contains(e.target));
    const pos = view ? view.posAtCoords({x: e.clientX, y: e.clientY}) : null;
    if (pos == null) return;
    e.preventDefault(); e.stopPropagation();
    LeeCM.setCursor(view, pos);
    const word = LeeCM.wordAtCursor(view);
    if (!word) return status('nothing to look up there', 'err');
    gotoDeclaration(word, editorPlace(view));
  }, true);
}
window.gotoDeclaration = gotoDeclaration; window.bindModClick = bindModClick;
window.dottedAtCursor = dottedAtCursor;

async function renameSymbol() {
  const name=cursorWord(),view=curEditor();
  if(!name||!view||!lee.path||curLang()!=='python')return status('put the cursor on a Python symbol first','err');
  const next=await inputDialog('rename symbol','New name',name,'valid Python identifier');
  if(!next||next===name)return;
  const pos=LeeCM.cursor(view),line=view.state.doc.lineAt(pos),character=pos-line.from;
  try{
    const preview=await post('/lsp/rename',{path:lee.path,text:LeeCM.getDoc(view),line:line.number-1,character,newName:next});
    if(!preview.files?.length)return status('Pyright found no rename edits','err');
    const summary=preview.files.map(f=>`${f.path.split('/').pop()} · ${f.edits} edit${f.edits===1?'':'s'}`).join('\n');
    if(!await confirmDialog('Rename across workspace',`${name} → ${next}\n\n${summary}`,'rename'))return;
    await post('/lsp/rename',{path:lee.path,text:LeeCM.getDoc(view),line:line.number-1,character,newName:next,apply:true});
    await post('/tab/reload',{path:lee.path});await mountTab();refreshFileTree(undefined,false);status(`renamed ${name} to ${next}`,'ok');
  }catch(e){status(e.message||String(e),'err');}
}

async function syncCodeIndex() {
  status('syncing Kosha index, notebooks and call graph…');
  const d = await post('/code/sync'); status(d.note || 'Kosha index synced', d.ok ? 'ok' : 'err');
}

async function leeSymbols() {
  const host = $('#symbols'), label = $('#symbolfile'); if (!host) return;
  const path = lee.path, name = compactPath(path || ''); if (label) label.textContent = name ? '· ' + name : '';
  // Notebooks are included: their defs and classes are real structure, and the server reads
  // them out of the cells rather than out of the JSON. The outline is of the file on disk, so
  // a def typed and not yet saved appears once autosave has run.
  if (!lee.path || (lee.kind !== 'text' && lee.kind !== 'notebook')) {
    host.innerHTML = '<div class="lee-dim">Open a source file or notebook to see its symbols.</div>'; return;
  }
  host.innerHTML = '<div class="lee-symbol-loading">Reading structure…</div>';
  try {
    const d = await api('/outline?path=' + encodeURIComponent(path));
    if (path !== lee.path) return;
    const rows = d.symbols || [];
    host.innerHTML = rows.length ? rows.map((s, i) => {
      const depth = Math.max(0, Math.floor(Number(s.score || 0) / 4));
      const kind = /^class\s/.test(s.text || '') ? 'class' : 'function';
      // A notebook symbol is addressed by cell, and the JSON line it also carries would be a
      // meaningless number to show: the row says which cell and where in it instead.
      const cellLine = Number(s.cell_line || 0), cellIndex = Number(s.cell_index ?? -1);
      const where = cellLine > 0 ? `${cellIndex + 1}:${cellLine}` : String(Number(s.line || 1));
      return `<button class="lee-symbol-row" role="treeitem" style="--depth:${depth}" ` +
        `data-line="${Number(s.line || 1)}" data-column="${Number(s.column || 0)}" data-cell="${esc(s.cell || '')}" ` +
        `data-cell-index="${cellIndex}" data-cell-line="${cellLine}">` +
        `<span class="lee-symbol-kind">${kind === 'class' ? 'C' : 'ƒ'}</span>` +
        `<span>${esc(s.symbol)}</span><small>${esc(where)}</small></button>`;
    }).join('') : '<div class="lee-dim">No functions or classes in this file.</div>';
    $$('.lee-symbol-row', host).forEach(row => row.onclick = () => {
      openLocation({path: path, line: +row.dataset.line, column: +row.dataset.column, cell: row.dataset.cell,
                    cell_index: +row.dataset.cellIndex, cell_line: +row.dataset.cellLine});
      if (matchMedia('(max-width: 1100px)').matches) leePane('left', false);
    });
  } catch (e) { if (path === lee.path) host.innerHTML = `<div class="lee-err">${esc(e.message || e)}</div>`; }
}
window.leeSymbols = leeSymbols;

