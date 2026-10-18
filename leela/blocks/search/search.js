async function quickOpen(searchMode) {
  let hits = [], sel = 0, seq = 0, timer = null, ctl = null, shown = null;
  const m = modal(
    `<input class="lee-input" id="qo" placeholder="${searchMode ? 'search files…' : 'open file…'}" autofocus>
     <label><input type="checkbox" id="qoall"> include .venv and dot folders</label>
     <div class="sub" id="qonote" hidden>hidden folders took over 10 seconds, so this list is incomplete</div>
     <div class="lee-modallist" id="qolist"></div>`,
    (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.max(0, Math.min(sel + 1, hits.length - 1)); paint(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); paint(); }
      else if (e.key === 'Enter') { e.preventDefault(); go(); }
    }, () => { clearTimeout(timer); ctl?.abort(); });
  const list = m.querySelector('#qolist'), input = m.querySelector('#qo'), all = m.querySelector('#qoall'), note = m.querySelector('#qonote');
  const paint = () => {
    list.innerHTML = hits.slice(0, 300).map((h, i) =>
      `<div class="lee-mrow${i === sel ? ' sel' : ''}" data-i="${i}">${esc(h.name)}<span class="sub">${h.hidden ? 'hidden · ' : ''}${esc(h.path)}</span></div>`).join('');
    list.querySelector('.sel')?.scrollIntoView({block: 'nearest'});
  };
  const go = () => { const h = hits[sel]; if (h) { m.remove(); leeOpenFile(h.path); } };
  list.addEventListener('click', e => { const r = e.target.closest('.lee-mrow'); if (r) { sel = +r.dataset.i; go(); } });
  // Hidden folders and environments take seconds to walk, so they follow the project's files and
  // only once typing pauses. Aborting a hidden batch stops its walk on the server; `seq` drops an
  // answer already on its way.
  const live = mine => mine === seq && m.isConnected;
  const stop = () => { seq++; ctl?.abort(); };
  const search = async () => {
    stop();
    const mine = seq, q = input.value.trim(), signal = (ctl = new AbortController()).signal;
    const find = extra => api('/fs/find?' + extra + 'q=' + encodeURIComponent(q), {signal});
    note.hidden = true;
    let found;
    if (q === shown) { hits = hits.filter(h => !h.hidden); sel = Math.min(sel, Math.max(0, hits.length - 1)); paint(); }
    else {
      try { found = (await find('')).hits; } catch (e) { if (live(mine)) status(e.message, 'err'); return; }
      if (!live(mine)) return;
      hits = found; shown = q; sel = 0; paint();
    }
    if (!all.checked || !q) return;
    await new Promise(r => setTimeout(r, 300));
    if (!live(mine)) return;
    try { found = await find('more=1&'); } catch (e) { if (live(mine)) status(e.message, 'err'); return; }
    if (!live(mine)) return;
    note.hidden = !found.partial;
    hits = hits.concat(found.hits.map(h => ({...h, hidden: true}))); paint();
  };
  input.addEventListener('input', () => { stop(); clearTimeout(timer); timer = setTimeout(search, 120); });
  all.addEventListener('change', () => { clearTimeout(timer); input.focus(); search(); });
  search(); setTimeout(() => input.focus(), 0);
}

// The modes, in the order Tab walks them. `all` leads and ranks every backend together. A rail
// rather than a row, because each mode carries a count.
const SEARCH_MODES = [
  ['all', 'all', 'rank ripgrep, symbols, FTS and semantic results together'],
  ['rg', 'rg', 'ripgrep: literal search over current files, fastest'],
  ['context', 'context', 'Kosha composed retrieval across repository code and installed packages'],
  ['repo', 'repo', 'Kosha repository code store'],
  ['env', 'packages', 'Kosha installed-package environment store'],
  ['symbols', 'symbols', 'Kosha symbols: repository and indexed packages'],
  ['ann', 'ANN', 'Kosha embedding ANN'],
];

/* What a search was asked, what it showed, and what was worth opening. Queued and posted in
   batches: a keystroke never waits on a write, and a failed write never fails a search. */
function searchSignals(session) {
  const queue = [];
  let queryId = '', askedAt = 0, timer = null, shown = new Map(), previewKey = '', previewAt = 0, opened = 0;
  let context = {};
  const key = h => `${h.path || ''}:${h.line || 0}:${h.package || ''}`;
  const flush = doc => {
    clearTimeout(timer); timer = null;
    const events = queue.splice(0, queue.length);
    if (!events.length && !doc) return;
    post('/search/events', {events, session: doc || null}).catch(() => {});
  };
  const push = (kind, row = {}) => {
    queue.push({session, query_id: queryId, kind, at: Date.now() / 1000, ...row});
    if (!timer) timer = setTimeout(() => flush(), 4000);
  };
  const closePreview = () => {
    if (!previewKey) return;
    const row = shown.get(previewKey);
    push('preview', {key: previewKey, rank: row?.rank ?? 0, dwell: Math.round(performance.now() - previewAt)});
    previewKey = '';
  };
  const doc = () => ({session, query_id: queryId, ...context, opened, shown_n: shown.size,
                      shown: [...shown.values()].sort((a, b) => a.rank - b.rank)});
  return {
    // A query typed over one that had already answered is the strongest negative signal there is.
    query(q, mode, scope, exts) {
      closePreview();
      if (queryId && shown.size) push('refine', {q});
      queryId = `${session}:${Date.now().toString(36)}`;
      askedAt = performance.now(); shown = new Map(); opened = 0;
      context = {q, mode, scope, exts};
      push('query', context);
    },
    leg(leg, ms, n) { push('leg', {leg, ms: Math.round(ms), n}); },
    impression(rows) {
      shown = new Map(rows.map((h, rank) => [key(h), {rank, path: h.path, line: h.line,
        symbol: h.symbol || '', package: h.package || '', sources: h.sources || [h.kind],
        previewed: false, opened: false}]));
      push('impression', {n: rows.length, ms: Math.round(performance.now() - askedAt)});
    },
    preview(hit, rank) {
      if (!hit) return;
      const k = key(hit); if (k === previewKey) return;
      closePreview();
      previewKey = k; previewAt = performance.now();
      const row = shown.get(k); if (row) row.previewed = true;
      if (!row) shown.set(k, {rank, path: hit.path, line: hit.line, symbol: hit.symbol || '',
        sources: hit.sources || [hit.kind], previewed: true, opened: false});
    },
    open(hit, rank) {
      if (!hit) return;
      closePreview(); opened += 1;
      const row = shown.get(key(hit)); if (row) row.opened = true;
      push('open', {key: key(hit), rank, path: hit.path, line: hit.line, symbol: hit.symbol || '',
        sources: hit.sources || [hit.kind], why: hit.why || null, score: hit.score || 0,
        ms: Math.round(performance.now() - askedAt), ...context});
    },
    mode(next) { push('mode', {mode: next}); },
    close() {
      closePreview();
      if (queryId && !opened) push('abandon', {n: shown.size});
      flush(queryId ? doc() : null);
    },
  };
}

/* Every slider in plain words: what the number buys, and what it is paying for. The settings keys
   are named for the scorer's own fields, which say nothing to somebody who has not read it. */
const WEIGHT_LABELS = {
  legFiles: ['a matching filename', 'a file whose name contains what you typed'],
  legSymbols: ['a matching name in the code', 'a function or class the code index knows'],
  legRg: ['the words, found in a file', 'a line containing exactly what you typed'],
  legFts: ['a keyword match', 'the search index found your words in a file'],
  legAnn: ['a match by meaning', 'code that does something similar, in different words'],
  legRank: ['being near the top of its own list', 'how much to respect the order each search came back in'],
  symbolExact: ['the name is exactly what you typed', 'searching `merge` and finding `def merge`'],
  symbolPart: ['the name contains what you typed', 'searching `merge` and finding `merge_dicts`'],
  queryInText: ['your words in the matching line', 'the line itself contains what you typed'],
  queryInFilename: ['your words in the filename', 'the file is called something like what you typed'],
  demoteNoise: ['pushing junk down', 'points taken off `node_modules`, `dist`, `build`, `vendor` and minified files'],
};

/* One hit's score from one set of weights, the arithmetic `Weights.score` does on the server. The
   panel re-ranks with it rather than asking again, so a slider moves the list as it is dragged. */
function weighHit(hit, weights, keys) {
  const why = hit.why; if (!why) return Number(hit.score || 0);
  let out = 0;
  for (const [name, field] of Object.entries(keys || {})) {
    if (field === why.leg) { out += Number(weights[name] || 0); continue; }
    if (field !== 'leg' && field in why) out += Number(weights[name] || 0) * Number(why[field] || 0);
  }
  return out;
}

/* What the dialog was last set to, kept where a moving port cannot lose it. The three legacy keys
   are adopted before anything is read, so the dialog opens on the same choices it closed on. Once
   a page: `origins` still says `default` until the settings are read again, so adopting on every
   open would put the old keys back over a choice made since. */
let searchAdopted = false;
async function adoptSearchPrefs() {
  if (searchAdopted) return;
  searchAdopted = true;
  await prefAdopt('search', 'lastMode', 'lee-search-mode');
  await prefAdopt('search', 'lastScope', 'lee-search-scope');
  await prefAdopt('search', 'lastExts', 'lee-search-exts');
}

async function codeSearch() {
  await adoptSearchPrefs();
  const session = crypto.randomUUID?.() || String(Math.random()).slice(2);
  const signals = searchSignals(session);
  let hits = [], sel = 0, backend = '', previewView = null, searchSeq = 0;
  // Two zones, one selection. Tab walks the rail and switches as it goes; Enter on the rail steps
  // into the results, and Enter in the results opens. Arrows are always the results.
  let zone = 'list', tuned = false, weights = {}, weightKeys = {}, weightDefaults = {};
  let mode = prefGet('search', 'lastMode', 'all');
  if (!SEARCH_MODES.some(([id]) => id === mode)) mode = 'all';
  const counts = {};
  const m = modal(
    `<div class="lee-searchbar"><input class="lee-input" id="cs" placeholder="search code, symbols and meaning…" autofocus
            role="combobox" aria-expanded="true" aria-controls="cslist" aria-autocomplete="list">
     <button class="lee-btn" id="cstune" type="button" aria-pressed="false">weights</button>
     <button class="lee-btn" id="cslog" type="button" aria-pressed="false">log</button>
     <button class="lee-btn" id="kosharefresh" type="button">sync</button></div>` +
    // A workspace holds several checkouts, so "this project" is the default and "everything
    // open" is the deliberate widening.
    `<div class="lee-searchfilters">
       <label>in<select id="csscope">
         <option value="project">this project</option>
         <option value="workspace">every open folder</option></select></label>
       <label>files<input class="lee-input" id="csexts" placeholder="py, ts — blank for all"
              aria-label="restrict to file extensions"></label>
       <span class="lee-dim" id="csscopenote"></span></div>` +
    `<div class="lee-search-weights" id="csweights" hidden></div>` +
    `<div class="lee-kosha-status" id="koshastatus"><span>Opening Kosha…</span></div>
     <div class="lee-code-search-body">
       <nav class="lee-searchrail" id="csrail" aria-label="search mode">${SEARCH_MODES.map(([id, label, tip]) =>
         `<button class="lee-searchrail-mode" data-mode="${id}" tabindex="-1" title="${esc(tip)}">` +
         `<span>${esc(label)}</span><b data-count-for="${id}"></b></button>`).join('')}
         <span class="lee-dim lee-searchrail-hint">tab / shift+tab</span></nav>
       <div class="lee-modallist" id="cslist" role="listbox" aria-label="search results"><div class="lee-dim">type to search repository + environment context</div></div>
       <aside class="lee-search-preview"><header><div><strong id="cspreviewtitle">Code preview</strong>` +
       `<span id="cspreviewmeta">Select a result</span></div>` +
       `<div class="lee-search-actions"><button class="lee-btn" id="cspkg" hidden>Package API</button>` +
       `<button class="lee-btn go" id="csopen" disabled>Open file</button></div></header>` +
       `<div id="cspreview"><div class="lee-search-preview-empty">Matches open here with syntax highlighting.</div></div>` +
       `<div class="lee-search-relations" id="csrelations"></div></aside></div>` +
       `<div class="lee-search-hints"><kbd>tab</kbd> changes the kind of search` +
       `<kbd>enter</kbd> goes into the results, then opens one<kbd>↑↓</kbd> moves` +
       `<span class="lee-dim lee-search-hint-click">click previews, clicking it again opens it</span>` +
       `<span class="lee-spacer"></span><span class="lee-dim" id="cssignals"></span></div>`,
    (e) => {
      // The panel owns its own keyboard: a slider needs its arrows, and Tab has to reach the next
      // control in it rather than the next search mode.
      if (e.target?.closest?.('.lee-search-weights')) return;
      if (e.key === 'ArrowDown') { e.preventDefault(); zone = 'list'; select(sel + 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); zone = 'list'; select(sel - 1); }
      else if (e.key === 'Enter') {
        e.preventDefault();
        if (zone === 'rail') { zone = 'list'; paintRail(); select(sel); input.focus(); }
        else go();
      }
      else if (e.key === 'Tab') { e.preventDefault(); cycleMode(e.shiftKey ? -1 : 1); }
    }, () => {
      if (previewView) LeeCM.destroy(previewView);
      clearTimeout(previewTimer);
      if (extsTimer) { clearTimeout(extsTimer); prefSet('search', 'lastExts', extsEl.value.trim()); }
      // Closing the dialog must stop the search, or four backends work on for nothing.
      if (liveStream) { try { liveStream.close(); } catch {} liveStream = null; }
      signals.close();
    });
  m.classList.add('lee-code-search-modal');
  const list = $('#cslist', m), input = $('#cs', m), preview = $('#cspreview', m), open = $('#csopen', m);
  const pkgBtn = $('#cspkg', m), panel = $('#csweights', m);
  const scopeEl = $('#csscope', m), extsEl = $('#csexts', m);
  // Remembered, so somebody who works in Python does not retype `py` every time.
  scopeEl.value = prefGet('search', 'lastScope', 'project');
  if (!scopeEl.value) scopeEl.value = 'project';
  extsEl.value = prefGet('search', 'lastExts', '');
  const paintRail = () => {
    $$('.lee-searchrail-mode', m).forEach(b => {
      b.classList.toggle('active', b.dataset.mode === mode);
      b.classList.toggle('cursor', zone === 'rail' && b.dataset.mode === mode);
      b.setAttribute('aria-pressed', String(b.dataset.mode === mode));
    });
    // A count means something only once that mode has run. Blank is "not asked yet", which must
    // not look like nought.
    SEARCH_MODES.forEach(([id]) => {
      const el = $(`[data-count-for="${id}"]`, m); if (!el) return;
      el.textContent = counts[id] == null ? '' : counts[id];
      el.classList.toggle('zero', counts[id] === 0);
    });
  };
  const setMode = (next, from = 'click') => {
    if (!next || next === mode) return;
    mode = next; prefSet('search', 'lastMode', mode);
    zone = from === 'tab' ? 'rail' : 'list';
    signals.mode(mode);
    paintRail();
    if (input.value.trim()) search(); else paint();
    input.focus();
  };
  // Tab switches as it walks: the mode you are on is the mode that answered, so there is never a
  // pending choice to lose track of. The searches it fires are debounced by `search`.
  const cycleMode = step => {
    const at = SEARCH_MODES.findIndex(([id]) => id === mode);
    setMode(SEARCH_MODES[(at + step + SEARCH_MODES.length) % SEARCH_MODES.length][0], 'tab');
  };
  const rowId = i => `cshit${i}`;
  const select = (next, withPreview = true) => {
    if (!hits.length) return;
    sel = Math.max(0, Math.min(next, hits.length - 1));
    $$('.lee-search-result', list).forEach((row, i) => {
      const on = i === sel;
      row.classList.toggle('sel', on); row.setAttribute('aria-selected', String(on));
      if (on) row.scrollIntoView({block: 'nearest'});
    });
    input.setAttribute('aria-activedescendant', rowId(sel));
    if (withPreview) showPreview();
  };
  let previewTimer = null;
  const showPreview = () => {
    // Debounced: a held arrow key would otherwise mount and tear down one editor per row.
    clearTimeout(previewTimer);
    previewTimer = setTimeout(paintPreview, 70);
  };
  const paintPreview = () => {
    if (previewView) { LeeCM.destroy(previewView); previewView = null; }
    const h = hits[sel];
    if (!h) {
      preview.innerHTML = '<div class="lee-search-preview-empty">No result selected.</div>';
      // The header named the last hit, which a mode with no matches of its own does not have.
      $('#cspreviewtitle', m).textContent = 'Code preview';
      $('#cspreviewmeta', m).textContent = 'Select a result';
      open.disabled = true; pkgBtn.hidden = true; return;
    }
    const filename = h.path.split('/').pop() || h.package || 'indexed source';
    $('#cspreviewtitle', m).textContent = h.symbol || filename;
    $('#cspreviewmeta', m).textContent = `${h.package ? h.package + ' · ' : ''}${filename}:${h.line} · ${(h.sources || [h.kind]).join(' + ')}`;
    // A package is a file like any other once the path is one this project can open. Its API
    // listing is the second question, so it gets its own button.
    const environment = h.kind.startsWith('env-');
    open.disabled = !h.path && !(environment && h.package) && h.kind !== 'vault';
    open.textContent = h.kind === 'vault' ? 'Open in vault' : h.path ? 'Open file' : environment && h.package ? 'Package API' : 'Indexed package';
    pkgBtn.hidden = !(environment && h.package && h.path);
    preview.innerHTML = '<div class="lee-search-preview-editor"></div>';
    previewView = mountCodeSurface($('.lee-search-preview-editor', preview), h.text || '(no indexed preview)',
                                   codeLang('', h.path), false);
    signals.preview(h, sel);
    const relations = $('#csrelations', m), callers = h.callers || [];
    relations.innerHTML = callers.length ? `<span>called by</span>` + callers.map(name =>
      `<button data-symbol="${esc(name)}">${esc(name.split('.').pop())}</button>`).join('') : '';
    // Following a caller is a graph question, so it switches to the mode that answers one.
    $$('[data-symbol]', relations).forEach(button => button.onclick = () => {
      input.value = button.dataset.symbol;
      if (mode === 'context') search(); else setMode('context');
    });
  };
  // Only once a weight has been moved: until then the streamed leg order is the order, and a list
  // that re-sorted under the cursor while it filled would be unreadable.
  const ranked = () => tuned ? [...hits].sort((a, b) =>
    weighHit(b, weights, weightKeys) - weighHit(a, weights, weightKeys) ||
    a.path.localeCompare(b.path) || a.line - b.line) : hits;
  const paint = () => {
    if (!hits.length) {
      list.innerHTML = `<div class="lee-dim">${backend ? 'no matches · ' + esc(backend) : 'type to search'}</div>`;
      input.removeAttribute('aria-activedescendant');
      showPreview(); return;
    }
    hits = ranked();
    list.innerHTML = hits.map((h, i) => {
      const f = h.path.split('/').pop() || h.package || 'environment';
      const foundBy = (h.sources || [h.kind]).join(' + ');
      return `<button class="lee-search-result${i === sel ? ' sel' : ''}" id="${rowId(i)}" role="option" ` +
        `tabindex="-1" aria-selected="${i === sel}" data-i="${i}">` +
        `<span class="lee-search-result-kind">${esc(h.kind === 'vault' ? 'VAULT' : h.kind.startsWith('env-') ? 'PKG' : h.kind === 'file' ? 'FILE' : h.symbol ? 'SYM' : 'TXT')}</span>` +
        `<span><strong>${esc(h.symbol || h.text.split('\n')[0].slice(0, 90))}</strong>` +
        `<small>${h.kind === 'vault' ? `vault · ${esc(h.shelf || 'main')}${h.page == null ? '' : ' · p. ' + (h.page + 1)}`
                                      : `${esc(h.package ? h.package + ' · ' : '')}${esc(f)}:${h.line}`}</small></span>` +
        `<em>${esc(foundBy)}</em></button>`;
    }).join('');
    select(sel);
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
    signals.open(h, sel);
    if (h.kind === 'vault') { m.remove(); return leeOpenVaultDoc(h.doc, h.shelf, h.vault, h.symbol, {page: h.page, quote: h.text.slice(0, 80)}); }
    if (h.path) { m.remove(); return openLocation(h); }
    if (!h.package) return status('package source is indexed read-only', 'info');
    await packageApi(h);
  };
  /* A click selects and previews. A click on the row already in the preview is what opens it, so a
     mouse can read a result before committing to it, exactly as the arrow keys can.

     Against `sel`, not against the last row the mouse hit. Those differ wherever the selection
     moved without the mouse: the first result is selected and previewed the moment the results
     land, so opening the row on screen took two clicks, and a row reached with the arrow keys was
     previewed and then ignored the click that meant open. */
  list.onclick = e => {
    const row = e.target.closest('[data-i]'); if (!row) return;
    const at = +row.dataset.i;
    zone = 'list';
    if (at === sel) return go();
    select(at, false); clearTimeout(previewTimer); paintPreview();
  };
  open.onclick = go;
  pkgBtn.onclick = () => { const h = hits[sel]; if (h?.package) packageApi(h); };
  // `all` streamed: one section per backend, in the server's best-first leg order. Slots are
  // stable because rg answers in tens of milliseconds and the embedding leg in seconds, and a
  // list that re-ranked on every arrival would reshuffle under the cursor while it was read. A
  // hit a later leg finds again adds its name to the existing row rather than a second one.
  const streamAll = (q, seq) => new Promise(resolve => {
    const slots = new Map(), seen = new Map();
    const started = performance.now();
    let notes = [];
    const es = new EventSource('/search/stream?q=' + encodeURIComponent(q) +
                               '&scope=' + encodeURIComponent(scopeEl.value) +
                               '&exts=' + encodeURIComponent(extsEl.value.trim()));
    // Held so the next keystroke can close it. A stream left open keeps four backends working,
    // and the server only notices when it next tries to write, seconds away for the slow legs.
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
      if (d.weights) setWeights(d.weights);
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
      signals.leg(d.leg, performance.now() - started, (d.hits || []).length);
      recount();
      backend = `all · ${[...slots.keys()].filter(k => slots.get(k).length).join(' + ') || 'searching'}`;
      // The list grew at the end, so the selection still points at its row.
      if (sel >= hits.length) sel = Math.max(0, hits.length - 1);
      paint();
    });
    // the vault answers after the code legs, in a section of its own at the end: at most five sections
    es.addEventListener('vault', e => {
      if (seq !== searchSeq) return stop();
      const d = JSON.parse(e.data);
      slots.set('vault', (d.hits || []).map(v => ({kind: 'vault', path: '', line: v.page == null ? 0 : v.page + 1, text: v.snippet || '',
        symbol: v.title || v.doc, doc: v.doc, shelf: v.shelf, vault: d.vault || '', page: v.page, sources: ['vault']})));
      recount(); paint();
    });
    es.addEventListener('done', e => {
      if (notes.length) backend += ' · ' + notes.slice(0, 2).join('; ');
      paint(); signals.impression(hits); stop();
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
      signals.query(q, mode, scopeEl.value, extsEl.value.trim());
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
        if (d.weights) setWeights(d.weights);
        // Which folders were walked, because "no matches" and "no matches here" are different
        // answers.
        const where = (d.searched || []).map(p => p.split('/').pop()).join(', ');
        $('#csscopenote', m).textContent = where ? `searched ${where}` : '';
        counts[mode] = hits.length; paintRail();
        paint(); signals.impression(hits); status(`search: ${d.backend}${d.note ? ' — ' + d.note : ''}`);
      } catch (e) {
        if (seq !== searchSeq) return;
        hits = []; backend = e.message || String(e); paint(); status(backend, 'err');
      }
    }, mode === 'rg' ? 120 : mode === 'all' || mode === 'context' ? 360 : 280);
  };
  input.addEventListener('input', search);
  scopeEl.addEventListener('change', () => {
    prefSet('search', 'lastScope', scopeEl.value);
    if (input.value.trim()) search();
  });
  // Settled, not per keystroke: this one is a POST and a file write, where the old key was neither.
  let extsTimer = 0;
  extsEl.addEventListener('input', () => {
    clearTimeout(extsTimer);
    extsTimer = setTimeout(() => prefSet('search', 'lastExts', extsEl.value.trim()), 400);
    if (input.value.trim()) search();
  });
  const setWeights = values => { weights = {...weights, ...values}; };
  /* Every weight `all` pays, with the list re-ranking as one is dragged. Ranking you cannot see
     is ranking you cannot tune, so each hit carries the features it scored on and the panel does
     the same arithmetic the server did. */
  let view = 'weights';
  const paintPanel = d => {
    held = d;
    weightKeys = d.keys || {}; weightDefaults = d.defaults || {}; setWeights(d.weights || {});
    const s = d.summary || {};
    const slider = name => {
      const [label, help] = WEIGHT_LABELS[name] || [name.replace(/([A-Z])/g, ' $1').toLowerCase(), ''];
      return `<label class="lee-weight" title="${esc(help)}"><span>${esc(label)}<small>${esc(help)}</small></span>` +
        `<input type="range" min="0" max="500" step="1" data-weight="${esc(name)}" value="${Number(weights[name] || 0)}" aria-label="${esc(label)}">` +
        `<input class="lee-input" type="number" min="0" max="500" data-weight-value="${esc(name)}" value="${Number(weights[name] || 0)}"></label>`;
    };
    const legs = Object.entries(s.legs || {}).map(([leg, row]) =>
      `${esc(leg)} ${row.won || 0}/${row.found || 0}`).join(' · ');
    panel.innerHTML =
      `<section data-panel="weights">` +
      `<p class="lee-weight-lead">Every result gets a score, and the highest score goes to the top. ` +
      `These are the points each thing is worth. Drag one and the list below re-sorts as you go.</p>` +
      `<div class="lee-weight-group"><h4>Points for how a result was found</h4><div class="lee-weight-grid">` +
      Object.keys(d.keys || {}).filter(k => k.startsWith('leg')).map(slider).join('') + `</div></div>` +
      `<div class="lee-weight-group"><h4>Points for how well it matches</h4><div class="lee-weight-grid">` +
      Object.keys(d.keys || {}).filter(k => !k.startsWith('leg')).map(slider).join('') + `</div></div>` +
      `<div class="lee-weight-actions"><button class="lee-btn" data-weights-reset type="button">defaults</button>` +
      `<span class="lee-spacer"></span><button class="lee-btn go" data-weights-save type="button">save weights</button></div></section>` +
      `<section data-panel="log"><div class="lee-weight-group"><h4>What Leela keeps about your searches</h4><div class="lee-weight-row">` +
      `<label>keep<select class="lee-select" data-signal="telemetry">` +
      ['off', 'local', 'vault'].map(v => `<option value="${v}"${v === d.telemetry ? ' selected' : ''}>${v}</option>`).join('') +
      `</select></label>` +
      `<label class="lee-settings-toggle"><input type="checkbox" data-signal="snippets"${d.snippets ? ' checked' : ''}><span>keep matched text</span></label>` +
      `<button class="lee-btn" data-signals-purge type="button">purge log</button></div>` +
      `<div class="lee-dim lee-weight-note">${esc(s.searches || 0)} searches · ${esc(s.opens || 0)} opened · ` +
      `MRR ${esc(s.mrr || 0)} · abandoned ${Math.round((s.abandon_rate || 0) * 100)}% · retyped ${Math.round((s.refine_rate || 0) * 100)}%` +
      `${legs ? ' · won/found ' + esc(legs) : ''}<br>${esc(d.dir || '')}${d.telemetry === 'vault' ? ' · vault ' + esc(d.vault || '') : ''}</div></div>` +
      // What was recorded, not just how much of it: a log you cannot read is a log you cannot
      // trust, and the rank a search was opened at is the number the weights are answering to.
      `<div class="lee-weight-group"><h4>Your recent searches</h4><div class="lee-search-log">` +
      ((s.recent || []).map(r => `<button data-recall="${esc(r.q)}" data-recall-mode="${esc(r.mode || 'all')}">` +
        `<strong>${esc(r.q)}</strong><span>${esc(r.mode || 'all')} · ${esc(r.n || 0)} shown` +
        `${r.ms ? ' · ' + esc(r.ms) + 'ms' : ''}${r.previewed ? ' · ' + esc(r.previewed) + ' previewed' : ''}</span>` +
        `<em>${r.opened.length ? 'opened #' + (r.opened[0].rank + 1) + ' ' + esc((r.opened[0].path || '').split('/').pop() || r.opened[0].symbol)
             : r.abandoned ? 'abandoned' : 'no open'}</em></button>`).join('') ||
        '<div class="lee-dim">nothing recorded yet</div>') + `</div></div>` +
      `<div class="lee-dim lee-weight-note">Click a row to run that search again. Leela keeps what you ` +
      `searched for, what it showed you, what you looked at and what you opened${d.telemetry === 'vault' ?
      ', and files one note per search in a vault of its own' : ''}. None of it leaves this machine.</div>` +
      `</div></section>`;
    $$('[data-panel]', panel).forEach(el => el.hidden = el.dataset.panel !== view);
    const retune = () => { tuned = true; paint(); };
    $$('[data-weight]', panel).forEach(el => el.oninput = () => {
      weights[el.dataset.weight] = Number(el.value);
      $(`[data-weight-value="${el.dataset.weight}"]`, panel).value = el.value;
      retune();
    });
    $$('[data-weight-value]', panel).forEach(el => el.oninput = () => {
      weights[el.dataset.weightValue] = Number(el.value);
      $(`[data-weight="${el.dataset.weightValue}"]`, panel).value = el.value;
      retune();
    });
    $('[data-weights-reset]', panel).onclick = () => {
      setWeights(weightDefaults);
      $$('[data-weight]', panel).forEach(el => el.value = weights[el.dataset.weight]);
      $$('[data-weight-value]', panel).forEach(el => el.value = weights[el.dataset.weightValue]);
      retune();
    };
    $('[data-weights-save]', panel).onclick = async () => {
      try {
        await post('/settings/save', {scope: 'user', section: 'search', values: weights});
        status('search weights saved', 'ok');
        if (input.value.trim()) { tuned = false; search(); }
      } catch (e) { status(e.message || String(e), 'err'); }
    };
    $$('[data-signal]', panel).forEach(el => el.onchange = async () => {
      const value = el.type === 'checkbox' ? el.checked : el.value;
      try { await post('/settings/save', {scope: 'user', section: 'search', values: {[el.dataset.signal]: value}}); }
      catch (e) { status(e.message || String(e), 'err'); }
    });
    // A recorded search is a search you can run again, which is what makes the log worth reading.
    $$('[data-recall]', panel).forEach(el => el.onclick = () => {
      input.value = el.dataset.recall;
      panel.hidden = true; $('#cstune', m).setAttribute('aria-pressed', 'false');
      if (el.dataset.recallMode !== mode) setMode(el.dataset.recallMode); else search();
      input.focus();
    });
    $('[data-signals-purge]', panel).onclick = async () => {
      if (!await confirmDialog('Purge the search log', 'Delete every recorded search event? The vault documents are not touched.', 'purge')) return;
      const out = await post('/search/signals/purge', {});
      status(`removed ${out.removed} search event file${out.removed === 1 ? '' : 's'}`, 'ok');
      loadPanel();
    };
  };
  let held = null;
  const loadPanel = async (force = false) => {
    if (held && !force) return paintPanel(held);
    try { paintPanel(await api('/search/signals')); }
    catch (e) { panel.innerHTML = `<div class="lee-err">${esc(e.message || e)}</div>`; }
  };
  // Two questions, one panel: what the ranking pays for, and what it has recorded so far. Each
  // button shows its own; pressing the one already showing puts the results back.
  const showPanel = next => {
    panel.hidden = !panel.hidden && view === next;
    view = next;
    ['cstune', 'cslog'].forEach(id =>
      $(`#${id}`, m).setAttribute('aria-pressed', String(!panel.hidden && view === (id === 'cstune' ? 'weights' : 'log'))));
    if (!panel.hidden) loadPanel(view === 'log'); else input.focus();
  };
  $('#cstune', m).onclick = () => showPanel('weights');
  $('#cslog', m).onclick = () => showPanel('log');
  api('/code/status').then(d => {
    const el = $('#koshastatus', m); if (!el) return;
    el.innerHTML = d.ok ? `<span class="ok">Kosha connected</span><span>${Number(d.files || 0).toLocaleString()} files</span>` +
      `<span>${Number(d.packages || 0).toLocaleString()} packages</span><span>${Number(d.graph_nodes || 0).toLocaleString()} graph nodes</span>` +
      `${d.stale_files ? `<span class="warn">${d.stale_files} stale files</span>` : ''}` : `<span class="warn">${esc(d.note || 'Kosha unavailable')}</span>`;
  }).catch(() => {});
  api('/search/signals?days=30').then(d => {
    weightKeys = d.keys || {}; weightDefaults = d.defaults || {}; setWeights(d.weights || {});
    const s = d.summary || {}, el = $('#cssignals', m);
    if (el && s.searches) el.textContent = `${s.searches} searches recorded · ${Math.round((s.open_rate || 0) * 100)}% opened`;
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
/* The dotted chain the cursor ends, so `fastcore.test` reaches the server whole: the last name
   alone found whichever package had a `def test`. Leftwards only, so on `fastcore` the answer is
   the package. */
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
/* One key, both directions. On a usage it goes to the declaration, on the declaration it lists
   who uses it. The server decides which, since it knows where the declaration is. */
async function gotoDeclaration(name = cursorWord(), place = editorPlace()) {
  if (!name) return status('put the cursor on a symbol first', 'err');
  status(`finding ${name}…`);
  let d;
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
  // `finding…` is a busy toast and waits to be clicked, so the answer has to replace it.
  status(`${hits.length} ${label} of ${name}`, 'ok');
}
/* The mouse saying what mod+b says. CodeMirror owns the click, so this takes the event in the
   capture phase: letting it through would move the caret and select a word.

   Either modifier counts, because platform detection is not reliable enough to gate it. In a
   webview that reported no platform, ctrl+click looked up the symbol and, being a right-click on
   macOS, opened the cell menu on top of the result. The paired `contextmenu` is claimed too. */
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
  // Notebooks are included, read out of the cells rather than the JSON. The outline is of the
  // file on disk, so a def typed and not yet saved appears once autosave has run.
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
      // A notebook symbol is addressed by cell. The JSON line it also carries would be a
      // meaningless number to show.
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

