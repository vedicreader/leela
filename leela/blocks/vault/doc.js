/* ---- a vault document as a tab: page strip, page image and page text, or its sections ---- */

/* Pages are 0-based on the wire and 1-based on the screen. This is the one place that says so. */
const pageNo = i => i + 1;

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
  if (!p.has_pii && !p.detected && !forced) {
    return `<div class="lee-vault-privacy"><strong>No pattern found</strong>` +
      `<span class="lee-pii clear" title="${esc(d.covers || '')}">no pattern found</span>` +
      `<button data-vault-pii="1">mark personal</button></div>`;
  }
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

/* The level chip: what a hosted model may have of this document, and a person's way to change it. */
function vaultLevelChip(lv, writable) {
  const opts = VAULT_LEVELS.map(([v, l]) => `<option value="${v}"${v === lv.level ? ' selected' : ''}>${l}</option>`).join('');
  const why = [lv.override ? `marked ${lv.override}` : `detected ${lv.detected}`, lv.floor !== 'open' ? `floor ${lv.floor}` : '',
               lv.doctype ? `type ${lv.doctype}` : '', Object.keys(lv.kinds || {}).join(', ')].filter(Boolean).join(' · ');
  return `<span class="lee-vault-level ${esc(lv.level)}" title="${esc(why)}">` +
    `<select class="lee-input" data-vault-level aria-label="privacy level"${writable ? '' : ' disabled title="this vault is attached read-only"'}>${opts}</select>` +
    (lv.override ? `<button class="lee-btn" data-vault-level-reset title="let detection decide again">auto</button>` : '') + `</span>`;
}

function wireVaultLevel(host, st, repaint) {
  const set = async level => {
    const r = await vaultCall('/vault/privacy', {doc: st.doc, shelf: st.shelf || '', vault: st.vault || '', level});
    if (!r.ok) return status(r.error, 'err');
    status(`now ${VAULT_LEVELS.find(([v]) => v === r.privacy.level)?.[1] || r.privacy.level}`, 'ok');
    repaint(r.privacy);
  };
  const sel = $('[data-vault-level]', host);
  if (sel) sel.onchange = () => set(sel.value);
  const reset = $('[data-vault-level-reset]', host);
  if (reset) reset.onclick = () => set('');
}

async function mountVault(host, st) {
  host.innerHTML = '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading the vault</small></div>';
  const q = new URLSearchParams({doc: st.doc, shelf: st.shelf || '', vault: st.vault || ''});
  let d;
  try { d = await api('/vault/doc?' + q); }
  catch (e) { host.innerHTML = `<div class="lee-err">${esc(e.message || e)}</div>`; return; }
  return d.paged ? mountVaultPages(host, st, d, q) : mountVaultSections(host, st, d);
}
window.mountVault = mountVault;

function vaultHead(st, d) {
  const doc = d.doc || {}, src = String(doc.source || '');
  return `<header class="lee-vault-dochead"><span class="lee-ptitle">${esc(doc.title || st.title)}</span>` +
    `<span class="lee-keyscope">${esc(doc.kind || 'document')} · ${esc(st.shelf || 'store')}</span>` +
    `<span data-level-slot>${vaultLevelChip(d.level || {level: 'open'}, d.writable)}</span><span class="lee-spacer"></span>` +
    (VAULT_PAGED.test(src) ? `<button class="lee-btn" data-vault-reread>${d.paged ? 'read again' : 'read it page by page'}</button>` : '') +
    (src.startsWith('/') ? `<button class="lee-btn" data-vault-file>open file</button>` : '') + `</header>`;
}

function wireVaultHead(host, st, d) {
  const src = String(d.doc?.source || '');
  const rr = $('[data-vault-reread]', host); if (rr) rr.onclick = () => leeVaultReadSheet(src, {vault: st.vault || '', shelf: st.shelf || ''});
  const of = $('[data-vault-file]', host); if (of) of.onclick = () => leeOpenVaultFile(st.doc, st.shelf || '', st.vault || '');
  const repaint = lv => { $('[data-level-slot]', host).innerHTML = vaultLevelChip(lv, d.writable); wireVaultLevel(host, st, repaint); };
  wireVaultLevel(host, st, repaint);
}

function vaultBlocks(blocks) {
  return blocks.map((b, i) => {
    const body = b.rows?.length ? `<table>${b.rows.map(r => `<tr>${r.map(c => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</table>`
      : esc(b.text || '').replace(/\n/g, '<br>');
    return `<div class="lee-vault-block ${esc(b.kind || 'prose')}" data-block="${i}" tabindex="-1">` +
      (b.n != null ? `<small>${esc(b.n)}</small>` : '') + body + `</div>`;
  }).join('');
}

async function mountVaultPages(host, st, d, q) {
  let pages;
  try { pages = (await api('/vault/pages?' + q)).pages; }
  catch (e) { host.innerHTML = `<div class="lee-err">${esc(e.message || e)}</div>`; return; }
  const routes = [...new Set(pages.map(p => p.route))];
  const secs = (d.sections || []).filter(s => s.page);
  host.innerHTML = `<div class="lee-vault-docview" tabindex="0" data-doc="${esc(st.doc)}">${vaultHead(st, d)}` +
    `<div class="lee-vault-docbody"><aside class="lee-vault-strip">` +
    `<select class="lee-input" data-strip-filter aria-label="show pages"><option value="">every page</option>` +
    `<option value="flagged">flagged</option>${routes.map(r => `<option value="route:${esc(r)}">${esc(r)}</option>`).join('')}</select>` +
    (secs.length ? `<select class="lee-input" data-sections aria-label="sections"><option value="">sections…</option>` +
      secs.map(s => `<option value="${s.page - 1}">${esc(s.title)} · p. ${s.page}</option>`).join('') + `</select>` : '') +
    `<div class="lee-vault-thumbs">${pages.map(p => `<button class="lee-vault-thumb" data-page="${p.page}" data-route="${esc(p.route)}"` +
      ` data-flagged="${p.flags.length ? 1 : 0}" title="page ${pageNo(p.page)} · ${esc(p.route)}${p.flags.length ? ' · ' + esc(p.flags.join(', ')) : ''}">` +
      `<img loading="lazy" alt="" src="/vault/page/img?${q}&page=${p.page}&w=120">` +
      `<span class="lee-vault-pno">${pageNo(p.page)}</span><span class="lee-vault-route ${esc(p.route)}">${esc(p.route)}</span>` +
      `${p.flags.map(f => `<i class="lee-vault-flag" title="${esc(f)}"></i>`).join('')}</button>`).join('')}</div></aside>` +
    `<figure class="lee-vault-pageimg"><img data-pageimg alt=""><figcaption data-imgerr hidden></figcaption></figure>` +
    `<article class="lee-vault-pagetext" data-pagetext></article></div></div>`;
  const view = $('.lee-vault-docview', host), img = $('[data-pageimg]', host), text = $('[data-pagetext]', host);
  let at = -1;
  const show = async i => {
    if (i < 0 || i >= pages.length) return;
    at = i;
    const p = pages[i];
    view.dataset.page = String(p.page);
    $$('.lee-vault-thumb', host).forEach(b => b.classList.toggle('active', +b.dataset.page === p.page));
    $(`.lee-vault-thumb[data-page="${p.page}"]`, host)?.scrollIntoView({block: 'nearest'});
    const err = $('[data-imgerr]', host); err.hidden = true; img.hidden = false;
    img.src = `/vault/page/img?${q}&page=${p.page}&w=900`;
    img.onerror = async () => {
      let why = 'the page image did not render';
      try { why = (await (await fetch(img.src)).json()).error || why; } catch {}
      img.hidden = true; err.hidden = false; err.textContent = why;
    };
    try {
      const r = await api(`/vault/page?${q}&page=${p.page}`);
      if (at !== i) return;
      text.innerHTML = `<div class="lee-vault-pagehead">page ${pageNo(p.page)} · ${esc(r.route)}${r.model ? ' · ' + esc(r.model) : ''}` +
        ` · v${r.version}${r.flags.length ? ` · <span class="warn">${esc(r.flags.join(', '))}</span>` : ''}</div>`;
      if (r.blocks?.length) text.insertAdjacentHTML('beforeend', vaultBlocks(r.blocks));
      else { const a = document.createElement('div'); text.appendChild(a); renderMarkdown(a, r.text || '*no text on this page*'); }
    } catch (e) { text.textContent = e.message || String(e); }
  };
  const visible = () => $$('.lee-vault-thumb', host).filter(b => !b.hidden).map(b => pages.findIndex(p => p.page === +b.dataset.page));
  view.__vault = {
    step: n => { const v = visible(), k = v.indexOf(at); show(v[Math.max(0, Math.min(v.length - 1, (k < 0 ? 0 : k + n)))]); },
    flag: n => {
      const f = pages.map((p, i) => p.flags.length ? i : -1).filter(i => i >= 0);
      if (!f.length) return status('no page is flagged', 'ok');
      show(n > 0 ? (f.find(i => i > at) ?? f[0]) : (f.slice().reverse().find(i => i < at) ?? f.at(-1)));
    }};
  $$('.lee-vault-thumb', host).forEach(b => b.onclick = () => show(pages.findIndex(p => p.page === +b.dataset.page)));
  text.addEventListener('click', e => {
    const b = e.target.closest('.lee-vault-block'); if (!b) return;
    $$('.lee-vault-block.active', text).forEach(x => x.classList.remove('active')); b.classList.add('active');
  });
  $('[data-strip-filter]', host).onchange = e => {
    const v = e.target.value;
    $$('.lee-vault-thumb', host).forEach(b => b.hidden = v === 'flagged' ? b.dataset.flagged !== '1'
      : v.startsWith('route:') ? b.dataset.route !== v.slice(6) : false);
  };
  const sec = $('[data-sections]', host); if (sec) sec.onchange = () => sec.value && show(pages.findIndex(p => p.page === +sec.value));
  view.addEventListener('mousedown', e => { if (!e.target.closest('select, input, button, a')) setTimeout(() => view.focus({preventScroll: true}), 0); });
  wireVaultHead(host, st, d);
  await show(0);
  view.focus({preventScroll: true});
}

function leeVaultPage(n) { $('.lee-vault-docview')?.__vault?.step(n); }
function leeVaultFlag(n) { $('.lee-vault-docview')?.__vault?.flag(n); }
window.leeVaultPage = leeVaultPage; window.leeVaultFlag = leeVaultFlag;

function mountVaultSections(host, st, d) {
  const doc = d.doc || {}, sections = d.sections || [];
  const src = String(doc.source || '');
  const mdBase = /^(https?:|memory:|pointer:)/.test(src) || !src ? '' : src.slice(0, src.lastIndexOf('/'));
  host.innerHTML = `<div class="lee-vault-reader-wrap">${vaultHead(st, d)}<div class="lee-vault-reader">` +
    `<aside class="lee-vault-toc"><div class="lee-vault-sections">${vaultSectionRows(sections, '')}</div></aside>` +
    `<div class="lee-vault-body"${mdBase ? ` data-md-base="${esc(mdBase)}"` : ''}>${vaultPrivacy(d)}` +
    `<article class="lee-vault-text" data-markdown=""></article></div></div></div>`;
  wireVaultHead(host, st, d);
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

/* The document in the vault is a copy; this opens the thing it was copied from. */
async function leeOpenVaultFile(doc, shelf = '', vault = '') {
  let d;
  try { d = await api('/vault/source?' + new URLSearchParams({doc, shelf, vault})); }
  catch (e) { return status(e.message || String(e), 'err'); }
  if (d.kind === 'url') return status('this was clipped from the web, not from a file', 'err');
  if (d.kind !== 'file') return status('this document was never a file', 'err');
  if (!d.exists) return status(`${d.path} is no longer there`, 'err');
  // The fs sandbox refuses paths outside an open folder, and every other path is checked against that.
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
