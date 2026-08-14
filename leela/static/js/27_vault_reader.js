/* ---- vault reader: a document from the vault, as an editor tab ---- */

function vaultSectionRows(sections, active) {
  if (!sections.length) return '<div class="lee-dim">No section structure was extracted.</div>';
  return sections.map(s => `<button class="lee-vault-section${s.node_id === active ? ' active' : ''}" ` +
    `data-node="${esc(s.node_id)}" style="padding-left:${6 + s.depth * 10}px">` +
    `<strong>${esc(s.title)}</strong>${s.page ? `<small>p. ${s.page}</small>` : ''}</button>`).join('');
}

function vaultPrivacy(d) {
  const p = d.privacy || {};
  if (!p.has_pii && !p.detected) return `<div class="lee-pii clear" title="${esc(d.covers || '')}">no pattern found</div>`;
  const kinds = Object.entries(p.kinds || {}).map(([k, n]) => `${k}×${n}`).join(', ');
  const cleared = p.override === 'clear';
  // `detected` stays true under an override, so an overridden document says so rather than
  // claiming the scan found nothing.
  return `<div class="lee-vault-privacy${cleared ? '' : ' sensitive'}">` +
    `<strong>${cleared ? 'Marked not personal' : 'Personal information found'}</strong>` +
    `<span class="lee-pii ${cleared ? 'clear' : 'found'}" title="${esc(d.covers || '')}">${esc(kinds || 'no kinds')}</span>` +
    (d.evidence?.length ? `<div class="lee-vault-evidence">${d.evidence.slice(0, 40).map(e =>
      `<span title="${esc(e.kind)}, page ${e.page}"><mark>${esc(e.value)}</mark><small>p. ${e.page}</small></span>`).join('')}</div>` : '') +
    `<button data-vault-notpii="${cleared ? '0' : '1'}">${cleared ? 'restore detection' : 'mark not personal'}</button></div>`;
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
