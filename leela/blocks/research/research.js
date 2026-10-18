function researchDomain(url) {
  try { return new URL(url).hostname.replace(/^www\./, ''); } catch (_) { return 'source'; }
}
async function saveDoc(doc, kind) {
  doc = doc || lee.lastDoc; if (!doc) return status('nothing fetched yet', 'err');
  if (kind === 'notebook' && !doc.url) return status('a research digest can be saved as markdown; source pages can become notebooks', 'err');
  if (!doc.text && doc.url && kind !== 'notebook') {
    status('reading source before saving…');
    const fetched = await api('/research/read?url=' + encodeURIComponent(doc.url));
    if (!fetched.doc) return status(fetched.note, 'err');
    doc = fetched.doc;
  }
  const r = await post('/research/save', {kind: kind === 'notebook' ? 'notebook' : 'md',
                                          url: doc.url, title: doc.title, text: doc.text});
  status('saved ' + r.entry.path, 'ok');
  leeOpenFile(r.entry.path);
}
function researchWorkspace(mode = 'search', value = '') {
  let activeMode = mode, docs = [], activeDoc = null, digest = '', query = value;
  const m = modal(`<div class="lee-mhead lee-research-head"><span>Research</span>` +
    `<span class="sub">search, read, and keep sources with the project</span></div>` +
    `<form class="lee-research-command"><div class="lee-segbar" aria-label="research mode">` +
    `<button type="button" class="lee-seg" data-mode="search">Search</button>` +
    `<button type="button" class="lee-seg" data-mode="read">Read URL</button>` +
    `<button type="button" class="lee-seg" data-mode="research">Research</button>` +
    `<button type="button" class="lee-seg" data-mode="vault">Vault</button></div>` +
    `<input class="lee-input" id="researchquery" autocomplete="off">` +
    `<label class="lee-research-remember" title="Store fetched sources in durable memory"><input type="checkbox" id="researchremember" checked> remember</label>` +
    `<button class="lee-btn go" type="submit">Go</button></form>` +
    `<div class="lee-research-body"><aside class="lee-research-sources">` +
    `<div class="lee-research-section-label">Sources</div><div id="researchsources" class="lee-research-source-list">` +
    `<div class="lee-research-empty">Search the web or enter a URL to begin.</div></div></aside>` +
    `<main class="lee-research-reader"><div class="lee-research-reader-head"><div>` +
    `<strong id="researchtitle">Research workspace</strong><span id="researchmeta">Current sources stay visible while you read.</span></div>` +
    `<div class="lee-research-actions"><button class="lee-btn" data-new-thought>New note</button>` +
    `<button class="lee-btn" data-open disabled>Open webpage</button>` +
    `<button class="lee-btn" data-save disabled>Save Markdown</button><button class="lee-btn" data-notebook disabled>Make notebook</button>` +
    `<button class="lee-btn" data-memory-note disabled>Add to agent memory</button>` +
    `<button class="lee-btn" data-forget disabled>Forget</button><button class="lee-btn" data-ask disabled>Ask with sources</button></div></div>` +
    `<article id="researchreader" class="lee-research-content"><div class="lee-research-hero">` +
    `<span class="lee-research-mark">R</span><strong>Keep evidence close to the work.</strong>` +
    `<p>Read a source cleanly, save it into the project, or carry cited results into the assistant.</p></div></article></main></div>`);
  m.classList.add('lee-research-modal');
  const input = $('#researchquery', m), list = $('#researchsources', m), reader = $('#researchreader', m);
  const title = $('#researchtitle', m), meta = $('#researchmeta', m);
  /* Vault mode puts what you have already kept in the same column as what you are about to find.
     The sources list becomes the vault tree, and the reader stays the reader. */
  const showVault = async () => {
    list.innerHTML = '<div class="lee-research-empty">Reading the vault…</div>';
    // `elid`, because the vault panel can be open behind this modal with a fragment of its own,
    // and two elements sharing an id would send every folder toggle to whichever came first.
    try {
      await htmx.ajax('GET', '/vault/browse?elid=researchvault', {target: '#researchsources', swap: 'innerHTML'});
      list.insertAdjacentHTML('afterbegin', '<button class="lee-btn" data-open-vault>open in Vault</button>');
      $('[data-open-vault]', list).onclick = () => { m.remove(); leeVaultWorkbench('library'); };
    }
    catch (e) { list.innerHTML = `<div class="lee-research-error">${esc(e.message || e)}</div>`; }
  };
  const setMode = next => {
    activeMode = next;
    $$('[data-mode]', m).forEach(b => b.classList.toggle('active', b.dataset.mode === next));
    input.placeholder = next === 'read' ? 'https://example.com/article' :
      next === 'research' ? 'Research a question across several sources…' :
      next === 'vault' ? 'Search what you have already kept…' : 'Search the web…';
    m.classList.toggle('research-vault', next === 'vault');
    if (next === 'vault') showVault();
    input.focus();
  };
  const setBusy = text => {
    reader.innerHTML = `<div class="lee-research-loading"><span></span><span></span><span></span><p>${esc(text)}</p></div>`;
  };
  const setActions = doc => {
    $('[data-open]', m).disabled = !doc?.url;
    $('[data-save]', m).disabled = !doc;
    $('[data-notebook]', m).disabled = !doc?.url;
    $('[data-memory-note]', m).disabled = !doc?.text;
    $('[data-forget]', m).disabled = !doc?.memory_id;
    $('[data-ask]', m).disabled = !(docs.length || doc);
  };
  const showDoc = async doc => {
    activeDoc = doc; lee.lastDoc = doc;
    title.textContent = doc.title || doc.url || 'Source'; meta.textContent = doc.url || 'research digest';
    setActions(doc);
    if (!doc.text && doc.url) {
      setBusy('Reading and cleaning the source…');
      try {
        const remember = $('#researchremember', m)?.checked !== false;
        const result = await api('/research/read?url=' + encodeURIComponent(doc.url) + '&remember=' + remember);
        if (!result.doc) throw new Error(result.note || 'No readable content');
        Object.assign(doc, result.doc); activeDoc = doc; lee.lastDoc = doc; setActions(doc);
      } catch (e) { reader.innerHTML = `<div class="lee-research-error"><strong>Could not read this source</strong><p>${esc(e.message || e)}</p>` +
        `<button class="lee-btn" data-open-fallback>Open the original webpage</button></div>`;
        $('[data-open-fallback]', reader).onclick = () => openExternal(doc.url); return; }
    }
    reader.innerHTML = '';
    if ((doc.sections || []).length > 1) {
      const collection = document.createElement('div'); collection.className = 'lee-research-collection';
      doc.sections.forEach((section, i) => {
        const article = document.createElement('article'); article.className = 'lee-research-article';
        article.innerHTML = `<header><span>${String(i + 1).padStart(2, '0')}</span>` +
          `<strong>${esc(section.title || `Article ${i + 1}`)}</strong></header>`;
        const body = document.createElement('div'); body.className = 'lee-research-markdown';
        article.appendChild(body); collection.appendChild(article); renderMarkdown(body, section.text || '');
      });
      reader.appendChild(collection);
      meta.textContent = `${researchDomain(doc.url)} · ${doc.sections.length} articles · ` +
        `${doc.sections.reduce((n, x) => n + (x.text || '').length, 0).toLocaleString()} characters`;
    } else {
      const md = document.createElement('div'); md.className = 'lee-research-markdown'; reader.appendChild(md);
      renderMarkdown(md, doc.text || 'No readable content was returned.');
      meta.textContent = `${researchDomain(doc.url)} · ${(doc.text || '').length.toLocaleString()} characters`;
    }
  };
  const paintSources = () => {
    list.innerHTML = docs.length ? docs.map((doc, i) => `<button class="lee-research-source${doc === activeDoc ? ' active' : ''}" data-source="${i}">` +
      `<span class="lee-research-source-index">${String(i + 1).padStart(2, '0')}</span><span><strong>${esc(doc.title || doc.url)}</strong>` +
      `<small>${esc(researchDomain(doc.url))}</small></span></button>`).join('') :
      '<div class="lee-research-empty">No sources yet.</div>';
  };
  const run = async () => {
    query = input.value.trim();
    // The vault is searched where it is shown, and an empty box puts the tree back, the same
    // two-views-of-one-panel rule the vault panel follows.
    if (activeMode === 'vault')
      return htmx.ajax('GET', '/vault/browse?' + new URLSearchParams({q: query, elid: 'researchvault'}),
                       {target: '#researchsources', swap: 'innerHTML'});
    if (!query) return;
    setBusy(activeMode === 'research' ? 'Reading and comparing the strongest sources…' : activeMode === 'read' ? 'Fetching the page…' : 'Searching the web…');
    try {
      if (activeMode === 'read') {
        const remember = $('#researchremember', m)?.checked !== false;
        const result = await api('/research/read?url=' + encodeURIComponent(query) + '&remember=' + remember);
        if (!result.doc) throw new Error(result.note || 'No readable content');
        docs = [result.doc]; paintSources(); await showDoc(result.doc); paintSources();
      } else if (activeMode === 'research') {
        const remember = $('#researchremember', m)?.checked !== false;
        const result = await api('/research/dig?q=' + encodeURIComponent(query) + '&remember=' + remember);
        docs = result.docs || []; digest = result.digest || '';
        const brief = {title: query, url: '', text: digest, kind: 'research'};
        paintSources(); await showDoc(brief); status(result.note, docs.length ? 'ok' : 'err');
      } else {
        const result = await api('/research/search?q=' + encodeURIComponent(query));
        docs = result.docs || []; activeDoc = null; paintSources();
        title.textContent = `${docs.length} results`; meta.textContent = result.note || query; setActions(null);
        reader.innerHTML = docs.length ? '<div class="lee-research-empty">Choose a source to open it in the reader.</div>' :
          '<div class="lee-research-error"><strong>No sources found</strong><p>Try a more specific query or switch to Research.</p></div>';
        status(result.note, docs.length ? 'ok' : 'err');
      }
    } catch (e) { reader.innerHTML = `<div class="lee-research-error"><strong>Research stopped</strong><p>${esc(e.message || e)}</p></div>`; status(e.message || String(e), 'err'); }
  };
  m.querySelector('.lee-research-command').onsubmit = e => { e.preventDefault(); run(); };
  m.querySelector('.lee-segbar').onclick = e => { const b = e.target.closest('[data-mode]'); if (b) setMode(b.dataset.mode); };
  list.onclick = e => { const b = e.target.closest('[data-source]'); if (!b) return; const doc = docs[+b.dataset.source]; showDoc(doc).then(paintSources); };
  $('[data-new-thought]', m).onclick = () => {
    activeDoc = {title: 'Research notes', url: '', text: '', kind: 'note'}; lee.lastDoc = activeDoc;
    title.textContent = 'New research note'; meta.textContent = 'Your Markdown scratchpad · save to the project or agent memory';
    reader.innerHTML = `<section class="lee-research-note-editor"><label>Title<input class="lee-input" data-thought-title value="Research notes"></label>` +
      `<div class="lee-research-note-cm"></div></section>`;
    const noteEditor = createEditor($('.lee-research-note-cm', reader), {doc: '# Notes\n\n', lang: 'markdown', lineNums: true,
      placeholder: 'Write observations, decisions, open questions, and links…', onChange: text => {
        activeDoc.text = text; setActions(activeDoc);
      }});
    activeDoc.text = LeeCM.getDoc(noteEditor); setActions(activeDoc);
    $('[data-thought-title]', reader).oninput = e => { activeDoc.title = e.target.value || 'Research notes'; };
    $('[data-thought-title]', reader).focus();
  };
  $('[data-open]', m).onclick = () => openExternal(activeDoc?.url);
  $('[data-save]', m).onclick = () => activeDoc && saveDoc(activeDoc, 'markdown');
  $('[data-notebook]', m).onclick = () => activeDoc && saveDoc(activeDoc, 'notebook');
  $('[data-memory-note]', m).onclick = () => {
    if (!activeDoc?.text) return;
    const source = activeDoc.url ? `\n\nSource: ${activeDoc.url}` : '';
    const text = String(activeDoc.text || '').slice(0, 30_000) + source;
    m.remove(); leeNewMemoryNote({title: activeDoc.title || query || 'Research note', text});
    status('research added to a new memory note; edit and choose model routing before saving', 'ok');
  };
  $('[data-forget]', m).onclick = async () => {
    if (!activeDoc?.memory_id) return;
    if (!await confirmDialog('forget research source', `Remove ${activeDoc.title || activeDoc.url} from durable memory?`, 'forget')) return;
    await post('/memory/forget', {id: activeDoc.memory_id}); activeDoc.memory_id = '';
    setActions(activeDoc); lee.memoryLoaded = false; status('source removed from memory', 'ok');
  };
  $('[data-ask]', m).onclick = () => {
    const sources = docs.filter(d => d.url).map((d, i) => `[${i + 1}] ${d.title}: ${d.url}`).join('\n');
    const prompt = $('#agentprompt'); if (!prompt) return;
    prompt.value = `Research this question using these sources and cite them in the answer:\n\n${query || activeDoc?.title || ''}\n\n${sources}`;
    m.remove(); leePane('right', true); leeRight('agent'); prompt.focus(); status(`${docs.length} research sources added to the prompt`, 'ok');
  };
  setMode(mode); input.value = value;
  if (value) queueMicrotask(run);
  return m;
}
function webSearch() { return researchWorkspace('search'); }
function readUrl(url = '') { return researchWorkspace('read', url); }
function researchQ() { return researchWorkspace('research'); }


// Clip a file, a folder or the open tab into the workspace vault shelf.
function clipTarget() {
  // Which menu opened decides the target. A tab names its path in `title`, so an inactive tab
  // read straight after right-clicking it does not have to wait for the select.
  const s = lee.menuSurface;
  if (s === 'file' || s === 'folder') return treeSel()?.dataset.path || '';
  if (s === 'tab') return $(`.lee-tab[data-i="${lee.menuTab}"]`)?.title || '';
  return treeSel()?.dataset.path || lee.path || '';
}
window.clipTarget = clipTarget;
