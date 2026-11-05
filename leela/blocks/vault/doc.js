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
    `<span data-level-slot>${vaultLevelChip(d.level || {level: 'open'}, d.writable)}</span>${vaultTypeChip(doc.meta || {})}<span class="lee-spacer"></span>` +
    (d.paged ? `<button class="lee-btn" data-vault-act="reread" title="r">re-read</button>` +
      `<button class="lee-btn" data-vault-act="history" title="h">history</button>` +
      `<button class="lee-btn" data-vault-act="proofread" title="p">proofread</button>` +
      `<button class="lee-btn" data-vault-act="review">review</button>` +
      `<button class="lee-btn" data-vault-act="sent" title="m: what a hosted model receives">as sent</button>` +
      `<button class="lee-btn" data-vault-act="find" title="/: find in this document">find</button>` +
      `<button class="lee-btn" data-vault-act="fields" title="the fields read out of it, each with its page">fields</button>` +
      (doc.meta?.book ? `<button class="lee-btn" data-vault-act="chapters" title="its chapters and verse numbers, and the problems to check">chapters</button>`
                      : `<button class="lee-btn" data-vault-act="book" title="read every page by a model as a book of verses">read as a book</button>`) : '') +
    `<button class="lee-btn" data-vault-sent-log title="what of it went to a hosted model, and when">sent</button>` +
    (VAULT_PAGED.test(src) ? `<button class="lee-btn" data-vault-reread>${d.paged ? 'read the file again' : 'read it page by page'}</button>` : '') +
    (src.startsWith('/') ? `<button class="lee-btn" data-vault-file>open file</button>` : '') + `</header>`;
}

function vaultTypeChip(m) {
  const dt = m.doctype || m.doctype_proposed;
  return dt ? `<span class="lee-vault-type${m.doctype ? '' : ' proposed'}" title="${m.doctype ? 'type' : 'proposed type: decide it under Review > Types'}">` +
    `${esc(dt.replace(/_/g, ' '))}</span>` : '';
}

function wireVaultHead(host, st, d) {
  const src = String(d.doc?.source || '');
  const rr = $('[data-vault-reread]', host); if (rr) rr.onclick = () => leeVaultReadSheet(src, {vault: st.vault || '', shelf: st.shelf || ''});
  const of = $('[data-vault-file]', host); if (of) of.onclick = () => leeOpenVaultFile(st.doc, st.shelf || '', st.vault || '');
  const sl = $('[data-vault-sent-log]', host); if (sl) sl.onclick = () => leeVaultSends({doc: st.doc, shelf: st.shelf || '', vault: st.vault || ''});
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
    `<article class="lee-vault-pagetext" data-pagetext></article><aside class="lee-vault-fields" data-fields hidden></aside>` +
    `<aside class="lee-vault-fields lee-vault-chapters" data-chapters hidden></aside></div></div>`;
  const view = $('.lee-vault-docview', host), img = $('[data-pageimg]', host), text = $('[data-pagetext]', host);
  let at = -1, seq = 0;
  const show = async i => { const tok = ++seq;
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
      if (st.sent) {
        const s = await api(`/vault/page?${q}&page=${p.page}&view=sent`);
        if (tok !== seq) return;
        text.innerHTML = `<div class="lee-vault-pagehead lee-vault-senthead ${esc(s.how)}">as sent to a hosted model · page ${pageNo(p.page)} · ` +
          `${esc(s.how)} · ${esc(s.level)}${Object.keys(s.kinds || {}).length ? ' · ' + esc(Object.keys(s.kinds).join(', ')) : ''}` +
          `<small>a page image cannot be masked: a re-read or a proofread withholds a Personal page from a hosted model</small></div>` +
          `<pre class="lee-vault-sent" data-sent>${esc(s.text || '')}</pre>`;
        return;
      }
      const r = await api(`/vault/page?${q}&page=${p.page}`);
      if (tok !== seq) return;
      text.innerHTML = `<div class="lee-vault-pagehead">page ${pageNo(p.page)} · ${esc(r.route)}${r.model ? ' · ' + esc(r.model) : ''}` +
        ` · <button class="lee-vault-vchip" data-vault-act="history" title="h: versions of this page">v${r.version}</button>` +
        `${r.flags.length ? ` · <span class="warn">${esc(r.flags.join(', '))}</span>` : ''}</div>`;
      if (r.blocks?.length) text.insertAdjacentHTML('beforeend', vaultBlocks(r.blocks));
      else {
        // rendered on the server: a jump marks a block only once the text is on the page
        const a = document.createElement('div'); text.appendChild(a);
        await new Promise(res => { a.addEventListener('lee-markdown-rendered', res, {once: true}); setTimeout(res, 3000);
                                   renderMarkdown(a, r.text || '*no text on this page*'); });
      }
    } catch (e) { text.textContent = e.message || String(e); }
  };
  const cur = () => pages[at]?.page ?? 0;
  const go = async (page, hl) => { await show(Math.max(0, pages.findIndex(p => p.page === page))); vaultMark(text, hl); };
  const acts = {
    reread: () => vaultPageSheet('reparse', st, {pages: String(pageNo(cur())), done: () => mountVault(host, {...st, at: cur()})}),
    proofread: () => vaultPageSheet('proof', st, {pages: ''}),
    history: () => vaultHistory(st, q, cur(), () => mountVault(host, {...st, at: cur()})),
    review: () => leeVaultReview(st.doc, st.shelf || '', st.vault || ''),
    find: () => leeVaultFindIn(st),
    ask: () => leeVaultFindIn(st, cur()),
    fields: () => { $('[data-chapters]', host).hidden = true; vaultFields(st, $('[data-fields]', host), go); },
    chapters: () => { $('[data-fields]', host).hidden = true; vaultChapters(st, $('[data-chapters]', host), go); },
    book: () => vaultPageSheet('book', st, {done: () => { lee.vaultChapters = st.doc; mountVault(host, {...st, at: cur()}); }}),
    sent: () => { st.sent = !st.sent; view.classList.toggle('sent', !!st.sent); $$('[data-vault-act="sent"]', host).forEach(b => b.classList.toggle('active', !!st.sent)); show(at); },
  };
  view.addEventListener('click', e => { const b = e.target.closest('[data-vault-act]'); if (b && acts[b.dataset.vaultAct]) acts[b.dataset.vaultAct](); });
  const visible = () => $$('.lee-vault-thumb', host).filter(b => !b.hidden).map(b => pages.findIndex(p => p.page === +b.dataset.page));
  view.__vault = {
    ...acts,
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
  if (st.sent) { view.classList.add('sent'); $$('[data-vault-act="sent"]', host).forEach(b => b.classList.add('active')); }
  const jump = lee.vaultJump?.doc === st.doc ? lee.vaultJump : null;
  lee.vaultJump = null;
  await go(jump?.page ?? st.at, jump);
  if (lee.vaultChapters === st.doc && d.doc?.meta?.book) { lee.vaultChapters = null; acts.chapters(); }
  view.focus({preventScroll: true});
}

function leeVaultPage(n) { $('.lee-vault-docview')?.__vault?.step(n); }
function leeVaultFlag(n) { $('.lee-vault-docview')?.__vault?.flag(n); }
function leeVaultDoc(act) {
  const v = $('.lee-vault-docview');
  if (!v?.__vault) return status('open a read vault document first', 'err');
  v.__vault[act]?.();
}
window.leeVaultPage = leeVaultPage; window.leeVaultFlag = leeVaultFlag; window.leeVaultDoc = leeVaultDoc;

/* Versions of one page: pick any two and see what changed between them. */
async function vaultHistory(st, q, page, done = null) {
  let rows;
  try { rows = (await api(`/vault/pages?${q}&history=1`)).pages.filter(p => p.page === page); }
  catch (e) { return status(e.message || String(e), 'err'); }
  if (!rows.length) return status('this page has no versions yet', 'err');
  const when = t => t ? new Date(t * 1000).toLocaleString() : '';
  const opt = (sel) => rows.map(r => `<option value="${r.version}"${r.version === sel ? ' selected' : ''}>v${r.version} · ${esc(r.route)}` +
    `${r.model ? ' · ' + esc(r.model) : ''} · ${esc(when(r.at))}</option>`).join('');
  const last = rows.at(-1).version, prev = rows.length > 1 ? rows.at(-2).version : last;
  const m = modal(`<div class="lee-mhead">Page ${pageNo(page)} versions<span class="sub">${rows.length} version${rows.length === 1 ? '' : 's'}</span></div>` +
    `<div class="lee-vault-history" data-vault-history><div class="lee-vault-histpick">` +
    `<select class="lee-input" data-a aria-label="from version">${opt(prev)}</select><span>→</span>` +
    `<select class="lee-input" data-b aria-label="to version">${opt(last)}</select><span class="lee-spacer"></span>` +
    `<button class="lee-btn" data-restore title="file the from version again as the newest; no version is lost">restore the from version</button></div>` +
    `<div class="lee-diff" data-diff></div></div>`, null, null, {storageKey: 'vault-history'});
  const paint = async () => {
    const a = $('[data-a]', m).value, b = $('[data-b]', m).value, out = $('[data-diff]', m);
    try {
      const d = await api(`/vault/page/diff?${q}&page=${page}&a=${a}&b=${b}`);
      out.innerHTML = d.rows.length ? diffHtml(d.rows) : '<div class="lee-dim">these two versions read the same</div>';
    } catch (e) { out.textContent = e.message || String(e); }
  };
  m.addEventListener('change', paint);
  $('[data-restore]', m).onclick = async () => {
    const v = +$('[data-a]', m).value;
    if (v === last) return status(`v${v} is already the newest`, 'err');
    const r = await vaultCall('/vault/page/revert', {doc: st.doc, shelf: st.shelf || '', vault: st.vault || '', page, version: v});
    if (!r.ok) return status(r.error, 'err');
    m.remove(); status(`page ${pageNo(page)}: v${v} restored as v${r.version}`, 'ok'); done?.();
  };
  await paint();
  return m;
}

/* The Re-read and Proofread sheets: which pages, which models, and the send line above the button. */
async function vaultPageSheet(kind, st, {pages = '', done = null} = {}) {
  const proof = kind === 'proof', isBook = kind === 'book', base = {doc: st.doc, shelf: st.shelf || '', vault: st.vault || ''};
  const est = proof ? await vaultCall('/vault/proofread', {...base, estimate: true}) : {};
  const mem = est.remembered || {};
  const pick = i => `<label>${proof ? `reader ${i + 1}` : 'model'}<select class="lee-input" name="model${i}" aria-label="${proof ? 'proofreader' : 'the model that reads the pages again'}">` +
    `<option value="">${proof && i ? 'none' : 'choose a model'}</option></select></label>`;
  const title = proof ? 'Proofread' : isBook ? 'Read as a book of verses' : 'Re-read pages', goLabel = proof ? 'Proofread' : isBook ? 'Read as a book' : 'Read again';
  const m = modal(`<div class="lee-mhead"><span>${title}</span><span class="sub">${esc(st.title || st.doc)}</span></div>` +
    `<form class="lee-vault-sheet" data-vault-pagesheet="${kind}">` +
    `<label>pages<input class="lee-input" name="pages" autocomplete="off" value="${esc(pages)}" placeholder="all, or 3-9"></label>` +
    pick(0) + (proof ? pick(1) + `<label>agree<input class="lee-input" name="agree" type="number" min="1" max="2" value="${esc(mem.agree || 2)}"></label>`
      : `<label>preset<select class="lee-input" name="preset">${isBook ? '' : '<option value="">as first read</option>'}` +
        (isBook ? VAULT_VERSES : ['generic', 'sanskrit', 'tamil', 'tables']).map(p => `<option>${p}</option>`).join('') + `</select></label>` +
        (isBook ? `<label>verses per chapter<input class="lee-input" name="counts" autocomplete="off" placeholder="optional, like 47,72,43"></label>` : '') +
        `<label>hint<input class="lee-input" name="hint" autocomplete="off" placeholder="what the pages are, for the model"></label>`) +
    `<div class="lee-vault-sendline" data-send role="status">choose a model to see where the pages go</div>` +
    `<label class="lee-vault-allow" data-allow hidden><input type="checkbox" name="allow"> allow once: send the Personal pages, this run only</label>` +
    `<div class="lee-vault-sheetfoot"><span class="lee-spacer"></span><button class="lee-btn go" type="submit" data-go>${goLabel}</button></div>` +
    `<div class="lee-vault-jobs" data-job></div></form>`, null, null, {storageKey: 'vault-pages'});
  const f = $('[data-vault-pagesheet]', m), sels = $$('select[name^="model"]', f);
  const models = (await vaultModels()).filter(seesImages);
  sels.forEach((sel, i) => {
    for (const r of models) {
      const o = document.createElement('option');
      o.value = r.value; o.textContent = `${r.label} · ${r.local ? 'on this Mac' : 'hosted: ' + (r.provider || 'remote')}`;
      sel.appendChild(o);
    }
    const want = (mem.readers || [])[i];
    if (want && ![...sel.options].some(o => o.value === want)) sel.add(new Option(want, want));
    if (want) sel.value = want;
    attachModelPicker(sel);
  });
  let last = {};
  const names = () => sels.map(s => s.value).filter(Boolean).join(',');
  const fields = () => ({...base, pages: f.elements.pages.value, allow: f.elements.allow.checked,
    ...(proof ? {readers: names(), agree: +f.elements.agree.value || 2}
              : {model: names(), preset: f.elements.preset.value, hint: f.elements.hint.value, ...(isBook ? {counts: f.elements.counts.value} : {})})});
  const check = async () => {
    const line = $('[data-send]', m), go = $('[data-go]', m);
    if (!names()) { last = {}; line.className = 'lee-vault-sendline'; line.textContent = 'choose a model to see where the pages go'; return; }
    const d = await vaultCall('/vault/send-check', {...base, pages: f.elements.pages.value, model: names(), allow: f.elements.allow.checked});
    last = d.ok ? d : {check_ok: false, kind: d.kind, why: d.error};
    const blocked = last.check_ok === false;
    line.textContent = last.why || '';
    line.className = 'lee-vault-sendline' + (blocked ? ' blocked' : '');
    line.dataset.kind = last.kind || '';
    $('[data-allow]', m).hidden = last.kind !== 'pii_blocked' && !f.elements.allow.checked;
    go.textContent = last.kind === 'model_unavailable' ? 'pick another model'
      : blocked ? `${goLabel}, skipping withheld pages` : goLabel;
  };
  f.addEventListener('change', check);
  f.elements.pages.addEventListener('input', () => { clearTimeout(f.__t); f.__t = setTimeout(check, 300); });
  f.addEventListener('submit', async e => {
    e.preventDefault();
    if (!names()) return status('choose a model', 'err');
    const r = await vaultCall(proof ? '/vault/proofread' : isBook ? '/vault/book' : '/vault/reparse', {...fields(), partial: last.check_ok === false});
    const jobs = $('[data-job]', m);
    if (r.html) {
      jobs.insertAdjacentHTML('afterbegin', r.html);
      htmx.process(jobs);
      const id = (r.html.match(/id="job-([^"]+)"/) || [])[1];
      if (id) vaultFollow(id, m, kind, j => {
        m.remove();
        if (proof) return leeVaultReview(st.doc, st.shelf || '', st.vault || '');
        status(j.result?.blocked?.length ? `${j.result.blocked.length} page(s) not sent`
          : isBook ? `${j.result.chapters} chapter(s), ${j.result.verses} verses · ${j.result.problems} problem(s) to check` : 'read again: a new version of each page',
          j.result?.blocked?.length ? 'err' : 'ok');
        done?.(j);
      });
      return;
    }
    jobs.insertAdjacentHTML('afterbegin', `<div class="lee-job error" data-kind="${esc(r.kind || '')}">` +
      `<span class="lee-job-error">${esc(r.error || 'it did not start')}</span></div>`);
  });
  if (names()) check();
  setTimeout(() => (names() ? $('[data-go]', m) : sels[0])?.focus(), 0);
  return m;
}
window.vaultPageSheet = vaultPageSheet;

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
  // The fs sandbox refuses paths outside an open folder. The server asks before it adds one, so there is one question.
  if (!d.inside_workspace) {
    try { await post('/fs/add-root', {path: d.parent}); await refreshFileTree(d.parent); }
    catch (e) { return status(e.message || String(e), e.body?.declined ? '' : 'err'); }
  }
  return leeOpenFile(d.path);
}
window.leeOpenVaultFile = leeOpenVaultFile;

/* Mark the block a citation or a field came from: the one holding its quote, else the one locate named. A masked quote finds nothing, so the index stands. */
function vaultMark(text, hl) {
  if (!hl || (!hl.quote && hl.block == null)) return null;
  const norm = t => String(t || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const blocks = $$('.lee-vault-block, p, li, td', text), want = norm(hl.quote).slice(0, 40);
  const b = (want && blocks.find(x => norm(x.textContent).includes(want))) || (hl.block != null ? $$('.lee-vault-block', text)[hl.block] || blocks[hl.block] : null);
  $$('.lee-vault-marked', text).forEach(x => x.classList.remove('lee-vault-marked', 'active'));
  b?.classList.add('lee-vault-marked', 'active');
  b?.scrollIntoView({block: 'center'});
  return b;
}

/* The Fields drawer: each field with its page, quote and warnings; a click opens its page. */
async function vaultFields(st, box, go) {
  box.hidden = !box.hidden;
  if (box.hidden) return;
  const base = {doc: st.doc, shelf: st.shelf || '', vault: st.vault || ''};
  box.innerHTML = '<div class="lee-dim">reading the fields…</div>';
  let d;
  try { d = await api('/vault/fields?' + new URLSearchParams(base)); }
  catch (e) { box.textContent = e.message || String(e); return; }
  const shown = v => v == null || v === '' || (Array.isArray(v) && !v.length) ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v);
  box.innerHTML = `<div class="lee-vault-fieldshead"><strong>Fields</strong>` +
    `<small>${d.extracted ? `${esc(d.schema || '')}${d.model ? ' · ' + esc(d.model) : ''}` : 'nothing extracted yet'}</small></div>` +
    (d.fields || []).map((f, i) => `<button class="lee-vault-field${f.errors.length ? ' warn' : ''}${shown(f.value) === '—' ? ' empty' : ''}" data-field="${i}"` +
      `${f.page == null ? ' disabled' : ''}><strong>${esc(f.field.replace(/_/g, ' '))}</strong><span>${esc(shown(f.value))}</span>` +
      `${f.page == null ? '' : `<small>p. ${pageNo(f.page)}</small>`}${f.quote ? `<q>${esc(f.quote)}</q>` : ''}` +
      f.errors.map(w => `<span class="warn" data-field-warn>⚠ ${esc(w)}</span>`).join('') +
      `${f.stale ? '<span class="lee-dim">page read again since</span>' : ''}</button>`).join('') +
    `<form class="lee-vault-fieldsform" data-extract><select class="lee-input" name="model" id="vaultextractmodel" aria-label="the model that reads the fields">` +
    `<option value="">the conversation model</option></select><div class="lee-vault-sendline" data-send role="status"></div>` +
    `<button class="lee-btn go" type="submit">${d.extracted ? 're-extract' : 'extract'}</button><div class="lee-vault-jobs" data-job></div></form>`;
  $$('[data-field]', box).forEach(b => b.onclick = () => {
    const f = d.fields[+b.dataset.field];
    if (f.page != null) go(f.page, {quote: f.quote || shown(f.value), block: f.block});
  });
  const form = $('[data-extract]', box), sel = form.elements.model;
  for (const r of await vaultModels()) sel.add(new Option(`${r.label} · ${r.local ? 'on this Mac' : 'hosted: ' + (r.provider || 'remote')}`, r.value));
  attachModelPicker(sel);
  const check = async () => {
    const c = await vaultCall('/vault/send-check', {refs: st.doc, shelf: base.shelf, vault: base.vault, model: sel.value});
    const line = $('[data-send]', form);
    line.textContent = c.ok ? c.why : c.error;
    line.className = 'lee-vault-sendline' + (c.ok && c.check_ok ? '' : ' blocked');
  };
  sel.addEventListener('change', check);
  check();
  form.onsubmit = async e => {
    e.preventDefault();
    const r = await vaultCall('/vault/extract', {...base, model: sel.value}), jobs = $('[data-job]', form);
    if (!r.html) return jobs.insertAdjacentHTML('afterbegin', `<div class="lee-job error" data-kind="${esc(r.kind || '')}"><span class="lee-job-error">${esc(r.error || 'it did not start')}</span></div>`);
    jobs.insertAdjacentHTML('afterbegin', r.html); htmx.process(jobs);
    const id = (r.html.match(/id="job-([^"]+)"/) || [])[1];
    if (id) vaultFollow(id, box, 'extract', () => { box.hidden = true; vaultFields(st, box, go); });
  };
}

async function leeOpenVaultDoc(doc, shelf = '', vault = '', title = '', jump = null) {
  lee.vaultJump = jump ? {doc, ...jump} : null;
  await htmx.ajax('POST', '/vault/open?' + new URLSearchParams({doc, shelf, vault, title}),
    {target: '#tabbar', swap: 'outerHTML'});
  return mountTab();
}
window.leeOpenVaultDoc = leeOpenVaultDoc;

/* The Chapters drawer: each chapter's verse numbers, a click opens the verse's page on its block; the problems are checked under Review > Verses. */
async function vaultChapters(st, box, go) {
  box.hidden = !box.hidden;
  if (box.hidden) return;
  const base = {doc: st.doc, shelf: st.shelf || '', vault: st.vault || ''};
  box.innerHTML = '<div class="lee-dim">gathering the verses…</div>';
  let b;
  try { b = await api('/vault/book?' + new URLSearchParams(base)); }
  catch (e) { box.textContent = e.message || String(e); return; }
  const open = b.probs.filter(p => p.state === 'open').length;
  box.innerHTML = `<div class="lee-vault-fieldshead"><strong>Chapters</strong><small>${b.chapters.length} · ${b.verses} verses · ${esc(b.preset)}</small></div>` +
    `<div class="lee-vault-bookbar"><button class="lee-btn${open ? ' warn' : ''}" data-book-probs>${open} problem${open === 1 ? '' : 's'} to check</button>` +
    `<button class="lee-btn" data-book-md>BOOK.md</button><button class="lee-btn" data-book-save>save beside the file</button></div>` +
    (b.changed.length ? `<div class="lee-dim" data-book-changed>pages ${b.changed.map(pageNo).join(', ')} read again since: the chapters follow the pages as they read now</div>` : '') +
    b.chapters.map((c, i) => `<section class="lee-vault-chapter" data-chapter="${i}"><strong>${esc(c.heading || `Chapter ${i + 1}`)}</strong>` +
      `<div class="lee-vault-verses">${c.verses.map((v, k) => `<button class="lee-vault-verse" data-verse="${i}.${k}" title="p. ${pageNo(v.page)} · ${esc(v.text.split('\n')[0])}">${esc(v.n)}</button>`).join('')}</div>` +
      (c.colophon ? `<small>${esc(c.colophon)}</small>` : '') + `</section>`).join('');
  $$('[data-verse]', box).forEach(el => el.onclick = () => {
    const [i, k] = el.dataset.verse.split('.').map(Number), v = b.chapters[i].verses[k];
    $$('.lee-vault-verse.active', box).forEach(x => x.classList.remove('active')); el.classList.add('active');
    go(v.page, {block: v.block, quote: v.block == null ? v.text.split('\n')[0] : ''});
  });
  $('[data-book-probs]', box).onclick = () => leeVaultReview(st.doc, st.shelf || '', st.vault || '', 'book');
  $('[data-book-md]', box).onclick = async () => {
    const r = await fetch('/vault/book.md?' + new URLSearchParams(base)), md = await r.text();
    if (!r.ok) return status(md, 'err');
    modal(`<div class="lee-mhead">BOOK.md<span class="sub">${esc(b.title)}</span></div><pre class="lee-vault-sent lee-review-md" data-book-preview>${esc(md)}</pre>`, null, null, {storageKey: 'vault-bookmd'});
  };
  $('[data-book-save]', box).onclick = async () => {
    const r = await vaultCall('/vault/book.md', base);
    status(r.ok ? `wrote ${r.path}` : r.error, r.ok ? 'ok' : 'err');
  };
}
