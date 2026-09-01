/* ---- the vault: a document as a tab, and the workbench that browses them all ---- */

/* The workbench is server-rendered and swaps its own body, so mounting it is one fetch and
   htmx owns everything after that. The tab holds only which view was last open. */
async function mountVaultWorkbench(host, st) {
  host.innerHTML = '<div class="lee-git-loading"><span></span><span></span><span></span><small>opening the vault</small></div>';
  try {
    await htmx.ajax('GET', '/vault/workbench?view=' + encodeURIComponent(st.view || 'browse'),
                    {target: host, swap: 'innerHTML'});
  } catch (e) { host.innerHTML = `<div class="lee-err">${esc(e.message || e)}</div>`; }
}
window.mountVaultWorkbench = mountVaultWorkbench;

async function leeVaultWorkbench(view = 'browse') {
  await htmx.ajax('POST', '/vault/workbench/open?view=' + encodeURIComponent(view),
                  {target: '#tabbar', swap: 'outerHTML'});
  return mountTab();
}
window.leeVaultWorkbench = leeVaultWorkbench;

/* Filtering is client-side because the rows are already here: a shelf of two hundred documents
   is one payload, and a keystroke that costs a request is a keystroke you feel. */
function leeVaultFilter(input) {
  const want = input.value.trim().toLowerCase(), wrap = input.closest('.lee-wb-main');
  let shown = 0;
  $$('.lee-vault-docrow', wrap).forEach(row => {
    const hit = !want || row.textContent.toLowerCase().includes(want);
    row.hidden = !hit; if (hit) shown++;
  });
  const count = $('.lee-wb-count', wrap);
  if (count) count.textContent = `${shown} shown`;
}
window.leeVaultFilter = leeVaultFilter;

/* ---- attaching a vault document to the next question ---- */

function attachVaultRef({vault = '', shelf = '', doc = '', title = ''}) {
  if (!doc) return null;
  lee.vaultRefs.set(`${vault}|${shelf}|${doc}`, {kind: 'vault', vault, shelf, doc, title: title || doc});
  return title || doc;
}
window.attachVaultRef = attachVaultRef;

function leeVaultAsk(btn) {
  const name = attachVaultRef(btn.dataset);
  if (!name) return;
  paintAgentAttachments();
  leeRight('agent');
  $('#agentprompt')?.focus();
  status(`${name} is attached to the next question`, 'ok');
}
window.leeVaultAsk = leeVaultAsk;

/* Every hit on the find view at once: "what do all of these say about X" is one question,
   and attaching them one at a time is the same question typed six times. */
function leeVaultAskAll(btn) {
  const rows = $$('.lee-wb-hit .lee-vault-ask', btn.closest('.lee-wb-find'));
  rows.forEach(b => attachVaultRef(b.dataset));
  paintAgentAttachments();
  leeRight('agent');
  status(`${rows.length} section${rows.length === 1 ? '' : 's'} attached`, 'ok');
}
window.leeVaultAskAll = leeVaultAskAll;


function vaultSectionRows(sections, active) {
  if (!sections.length) return '<div class="lee-dim">No section structure was extracted.</div>';
  return sections.map(s => `<button class="lee-vault-section${s.node_id === active ? ' active' : ''}" ` +
    `data-node="${esc(s.node_id)}" style="padding-left:${6 + s.depth * 10}px">` +
    `<strong>${esc(s.title)}</strong>${s.page ? `<small>p. ${s.page}</small>` : ''}</button>`).join('');
}

function vaultPrivacy(d) {
  const p = d.privacy || {};
  const kinds = Object.entries(p.kinds || {}).map(([k, n]) => `${k}×${n}`).join(', ');
  const cleared = p.override === 'clear', forced = p.override === 'force';
  // Nothing found and nothing said about it: the scan is the whole story, and the only override
  // left is the one arithmetic cannot reach.
  if (!p.has_pii && !p.detected && !forced) {
    return `<div class="lee-vault-privacy"><strong>No pattern found</strong>` +
      `<span class="lee-pii clear" title="${esc(d.covers || '')}">no pattern found</span>` +
      `<button data-vault-pii="1">mark personal</button></div>`;
  }
  // `detected` stays true under an override, so an overridden document says so rather than
  // claiming the scan found nothing.
  const head = cleared ? 'Marked not personal' : forced ? 'Marked personal' : 'Personal information found';
  return `<div class="lee-vault-privacy${cleared ? '' : ' sensitive'}">` +
    `<strong>${head}</strong>` +
    `<span class="lee-pii ${cleared ? 'clear' : 'found'}" title="${esc(d.covers || '')}">${esc(kinds || 'no kinds')}</span>` +
    (d.evidence?.length ? `<div class="lee-vault-evidence">${d.evidence.slice(0, 40).map(e =>
      `<span title="${esc(e.kind)}, page ${e.page}"><mark>${esc(e.value)}</mark><small>p. ${e.page}</small></span>`).join('')}</div>` : '') +
    (forced ? `<button data-vault-pii="0">restore detection</button>`
            : `<button data-vault-notpii="${cleared ? '0' : '1'}">${cleared ? 'restore detection' : 'mark not personal'}</button>`) +
    `</div>`;
}

async function mountVault(host, st) {
  host.innerHTML = '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading the vault</small></div>';
  const q = new URLSearchParams({doc: st.doc, shelf: st.shelf || '', vault: st.vault || ''});
  let d;
  try { d = await api('/vault/doc?' + q); }
  catch (e) { host.innerHTML = `<div class="lee-err">${esc(e.message || e)}</div>`; return; }

  const doc = d.doc || {}, sections = d.sections || [];
  const src = String(doc.source || '');
  const mdBase = /^(https?:|memory:|pointer:)/.test(src) || !src ? '' : src.slice(0, src.lastIndexOf('/'));
  host.innerHTML = `<div class="lee-vault-reader">` +
    `<aside class="lee-vault-toc"><div class="lee-phead"><span class="lee-ptitle">${esc(doc.title || st.title)}</span>` +
    `<span class="lee-keyscope">${esc(doc.kind || 'document')} · ${esc(st.shelf || 'store')}</span></div>` +
    `<div class="lee-vault-sections">${vaultSectionRows(sections, '')}</div></aside>` +
    // `data-md-base` is the folder the document was clipped from, so figures written relative
    // to it resolve. A document that was never a file has no base and keeps its links as written.
    `<div class="lee-vault-body"${mdBase ? ` data-md-base="${esc(mdBase)}"` : ''}>${vaultPrivacy(d)}` +
    `<article class="lee-vault-text" data-markdown=""></article></div></div>`;

  const body = $('.lee-vault-text', host);
  const show = async node => {
    $$('.lee-vault-section', host).forEach(b => b.classList.toggle('active', b.dataset.node === node));
    try {
      const s = await api('/vault/section?' + new URLSearchParams({node, shelf: st.shelf || '', vault: st.vault || ''}));
      renderMarkdown(body, s.section?.text || '');
    } catch (e) { body.textContent = e.message || String(e); }
  };
  $$('.lee-vault-section', host).forEach(b => b.onclick = () => show(b.dataset.node));
  if (sections.length) show(sections[0].node_id);
  // A document with nothing found has no override button, so this is optional -- assuming it was
  // there threw on null and took the rest of the mount, including the first section, with it.
  const notpii = $('[data-vault-notpii]', host);
  if (notpii) notpii.onclick = async e => {
    try {
      await post('/vault/not-pii', {doc: st.doc, shelf: st.shelf || '', vault: st.vault || '',
                                    clear: e.target.dataset.vaultNotpii === '1'});
      mountVault(host, st);
    } catch (err) { status(err.message || String(err), 'err'); }
  };
  const forcepii = $('[data-vault-pii]', host);
  if (forcepii) forcepii.onclick = async e => {
    try {
      await post('/vault/pii/mark', {doc: st.doc, shelf: st.shelf || '', vault: st.vault || '',
                                     force: e.target.dataset.vaultPii === '1'});
      mountVault(host, st);
    } catch (err) { status(err.message || String(err), 'err'); }
  };
}
window.mountVault = mountVault;

/* The document in the vault is a copy; this opens the thing it was copied from. Editing happens
   there, because a file on disk is something leela already knows how to edit, and writing back
   into the vault would mean deciding what becomes of its nodes, embeddings and content address. */
async function leeOpenVaultFile(doc, shelf = '', vault = '') {
  let d;
  try { d = await api('/vault/source?' + new URLSearchParams({doc, shelf, vault})); }
  catch (e) { return status(e.message || String(e), 'err'); }
  if (d.kind === 'url') return status('this was clipped from the web, not from a file', 'err');
  if (d.kind !== 'file') return status('this document was never a file', 'err');
  if (!d.exists) return status(`${d.path} is no longer there`, 'err');
  // The fs sandbox refuses paths outside an open folder, and that refusal is the thing every
  // other path in leela is checked against. So ask rather than reach around it.
  if (!d.inside_workspace) {
    if (!await confirmDialog('open folder', `${d.parent} is not open in this workspace.\n\nAdd it as a folder?`, 'add'))
      return;
    try { await post('/fs/add-root', {path: d.parent}); await refreshFileTree(d.parent); }
    catch (e) { return status(e.message || String(e), 'err'); }
  }
  return leeOpenFile(d.path);
}
window.leeOpenVaultFile = leeOpenVaultFile;

async function leeOpenVaultDoc(doc, shelf = '', vault = '', title = '') {
  await htmx.ajax('POST', '/vault/open?' + new URLSearchParams({doc, shelf, vault, title}),
    {target: '#tabbar', swap: 'outerHTML'});
  return mountTab();
}
window.leeOpenVaultDoc = leeOpenVaultDoc;
