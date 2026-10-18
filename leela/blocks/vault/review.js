/* ---- the Review queue: proofreading changes and personal information, decided from the keyboard ---- */

/* An accept files a new version of its page, which would make every other change on that page stale.
   So `a` stages a change, and a page's staged changes are applied together when the cursor leaves the
   page, on `A`, or from the apply bar. */

async function leeVaultReview(doc = '', shelf = '', vault = '') {
  await leeVaultWorkbench('review');
  if (doc) await htmx.ajax('GET', '/vault/view/review?' + new URLSearchParams({doc, shelf, vault}), {target: '#vaultwbbody', swap: 'innerHTML'});
  mountReviews();
  $('.lee-vault-review')?.focus({preventScroll: true});
}
window.leeVaultReview = leeVaultReview;

function mountReviews() { $$('.lee-vault-review:not([data-mounted])').forEach(mountReview); }
document.addEventListener('htmx:afterSettle', mountReviews);

const reviewQ = (st, extra = {}) => new URLSearchParams({doc: st.doc, vault: st.vault, ...(st.doc ? {shelf: st.shelf} : {}), ...extra});
const rowKey = r => `${r.doc}|${r.page}`;
const rowQ = (st, r) => new URLSearchParams({doc: r.doc, shelf: r.shelf || '', vault: st.vault});

async function mountReview(host) {
  host.dataset.mounted = '1';
  host.__review = {vault: host.dataset.vault || '', doc: host.dataset.doc || '', shelf: host.dataset.shelf || '',
                   mode: 'proof', doubts: false, at: 0, rows: [], undo: [], staged: new Map(), counts: {}, types: [], labels: []};
  host.addEventListener('click', e => reviewClick(host, e));
  host.addEventListener('mousedown', e => { if (!e.target.closest('input, button, select, a')) setTimeout(() => host.focus({preventScroll: true}), 0); });
  await reviewLoad(host);
}

async function reviewLoad(host) {
  const st = host.__review, tok = st.loads = (st.loads || 0) + 1;
  try {
    const [c, f, t] = await Promise.all([api('/vault/changes?' + reviewQ(st)), api('/vault/pii/findings?' + reviewQ(st, {state: 'found'})),
                                         api('/vault/types?' + new URLSearchParams({vault: st.vault}))]);
    if (tok !== st.loads) return;     // a later load is on its way, and it is the one that counts
    st.changes = c.changes || []; st.findings = f.findings || [];
    st.types = (t.types || []).filter(r => !st.doc || r.doc === st.doc); st.labels = t.labels || [];
  } catch (e) { host.innerHTML = `<div class="lee-err">${esc(e.message || e)}</div>`; return; }
  reviewPaint(host);
}

function reviewPaint(host) {
  const st = host.__review, proof = st.mode === 'proof', types = st.mode === 'types';
  st.rows = proof ? st.changes.filter(r => !st.doubts || r.state === 'doubt') : types ? st.types : st.findings;
  if (st.want) { const k = st.rows.findIndex(r => r.id === st.want); if (k >= 0) st.at = k; st.want = null; }
  st.at = Math.max(0, Math.min(st.at, st.rows.length - 1));
  const n = {proof: st.changes.length, pii: st.findings.length, types: st.types.length, doubt: st.changes.filter(r => r.state === 'doubt').length,
             stale: st.changes.filter(r => r.stale).length};
  const chip = (mode, label, k) => `<button class="lee-wb-subtab${st.mode === mode ? ' active' : ''}" data-review-mode="${mode}">${label} <span data-count="${mode}">${k}</span></button>`;
  let html = `<div class="lee-review-head">${chip('proof', 'Proofreading', n.proof)}${chip('pii', 'Personal info', n.pii)}${chip('types', 'Types', n.types)}` +
    (proof ? `<label class="lee-review-doubts"><input type="checkbox" data-review-doubts${st.doubts ? ' checked' : ''}> doubts only (d) · ${n.doubt}</label>` +
             (n.stale ? `<span class="lee-dim">${n.stale} stale</span>` : '') : '') +
    `<span class="lee-spacer"></span>` +
    (st.doc && proof ? `<button class="lee-btn" data-review-export>PROOFREAD.md</button><button class="lee-btn" data-review-save>save beside the file</button>` : '') +
    (st.doc && !proof ? `<button class="lee-btn" data-review-scan title="find personal information in pages read before findings were kept">scan again</button>` : '') +
    (st.doc ? `<button class="lee-btn" data-review-all>every document</button>` : '') + `</div>` +
    `<div class="lee-review-staged" data-staged ${st.staged.size ? '' : 'hidden'}>${st.staged.size} staged to accept · ` +
    `<button class="lee-btn go" data-review-apply>apply</button></div>`;
  if (!st.rows.length) html += `<div class="lee-wb-empty"><strong>${proof ? 'No changes to decide' : types ? 'No types to decide' : 'No personal information to decide'}</strong>` +
    `<span>${proof ? 'Proofread a document from its view (p) to file changes here.' : types ? 'A type the words cannot settle is proposed here; type untyped documents from Library.' : 'Findings are filed as pages are read.'}</span></div>`;
  if (types) {
    st.rows.forEach((r, i) => {
      html += `<div class="lee-review-row lee-review-type${i === st.at ? ' active' : ''}" data-i="${i}" data-id="${esc(r.doc)}">` +
        `<div class="lee-review-doc">${esc(r.title || r.doc)}</div><div class="lee-review-change">` +
        `<span class="lee-vault-type proposed" data-proposed>${esc(String(r.proposed).replace(/_/g, ' '))}</span>` +
        `${r.doctype ? `<small>now ${esc(r.doctype)}</small>` : ''}<small>${esc(r.by || '')}${r.score != null ? ' · ' + Number(r.score).toFixed(2) : ''}</small></div></div>`;
    });
    host.innerHTML = html;
    $('.lee-review-row.active', host)?.scrollIntoView({block: 'nearest'});
    return;
  }
  let lastDoc = null, lastPage = null;
  st.rows.forEach((r, i) => {
    if (r.doc !== lastDoc) { html += `<div class="lee-review-doc">${esc(r.title || r.doc)}</div>`; lastDoc = r.doc; lastPage = null; }
    if (r.page !== lastPage) { html += `<div class="lee-review-page">page ${pageNo(r.page)}</div>`; lastPage = r.page; }
    const q = rowQ(st, r);
    const img = proof && r.box ? `/vault/page/crop?${q}&page=${r.page}&box=${r.box.join(',')}` : `/vault/page/img?${q}&page=${r.page}&w=360`;
    const staged = st.staged.has(r.id);
    html += `<div class="lee-review-row${i === st.at ? ' active' : ''}${r.stale ? ' stale' : ''}${staged ? ' staged' : ''}" data-i="${i}" data-id="${esc(r.id)}" data-state="${esc(r.state)}">` +
      `<img class="lee-review-img" loading="lazy" alt="" src="${img}">` +
      (proof ? `<div class="lee-review-change"><del>${esc(r.before || '∅')}</del> → <ins data-after>${esc(staged && st.staged.get(r.id).after != null ? st.staged.get(r.id).after : r.after || '∅')}</ins>` +
               `<small>${esc((r.by || []).join(', '))} · ${esc(staged ? 'staged' : r.state)}</small>` +
               (r.stale ? `<span class="lee-review-stalewhy">page re-read since</span><button class="lee-btn" data-review-reproof="${i}">proofread this page again</button>` : '') + `</div>`
             : `<div class="lee-review-change"><code>${esc(r.preview || 'gone from the page')}</code><small>${esc(r.kind)} · ${esc(r.state)}</small></div>`) +
      `</div>`;
  });
  host.innerHTML = html;
  $('.lee-review-row.active', host)?.scrollIntoView({block: 'nearest'});
}

async function reviewClick(host, e) {
  const st = host.__review, t = e.target;
  if (t.closest('[data-review-mode]')) { await reviewCommit(host); st.mode = t.closest('[data-review-mode]').dataset.reviewMode; st.at = 0; return reviewPaint(host); }
  if (t.matches('[data-review-doubts]')) return leeReview('doubts', 0, host);
  if (t.closest('[data-review-apply]')) return reviewCommit(host);
  if (t.closest('[data-review-all]')) { await reviewCommit(host); st.doc = st.shelf = ''; return reviewLoad(host); }
  if (t.closest('[data-review-export]')) {
    const r = await fetch('/vault/proof.md?' + reviewQ(st));
    const md = await r.text();
    if (!r.ok) return status(md, 'err');
    return modal(`<div class="lee-mhead">PROOFREAD.md<span class="sub">${esc(st.doc)}</span></div><pre class="lee-vault-sent lee-review-md">${esc(md)}</pre>`,
                 null, null, {storageKey: 'vault-proofmd'});
  }
  if (t.closest('[data-review-save]')) {
    const r = await vaultCall('/vault/proof.md', {doc: st.doc, shelf: st.shelf, vault: st.vault});
    return status(r.ok ? `wrote ${r.path}` : r.error, r.ok ? 'ok' : 'err');
  }
  if (t.closest('[data-review-scan]')) {
    const r = await vaultCall('/vault/pii/scan', {doc: st.doc, shelf: st.shelf, vault: st.vault});
    if (!r.ok) return status(r.error, 'err');
    return reviewLoad(host);
  }
  if (t.closest('[data-review-reproof]')) return reviewReproof(host, st.rows[+t.closest('[data-review-reproof]').dataset.reviewReproof]);
  const row = t.closest('.lee-review-row');
  if (row) return reviewMove(host, +row.dataset.i);
}

async function reviewMove(host, i) {
  const st = host.__review, from = st.rows[st.at], to = st.rows[i];
  if (!to) return;
  st.at = i; st.want = to.id;
  if (from && rowKey(from) !== rowKey(to) && [...st.staged.values()].some(s => rowKey(s.row) === rowKey(from))) return reviewCommit(host, rowKey(from));
  $$('.lee-review-row', host).forEach(r => r.classList.toggle('active', +r.dataset.i === i));
  $('.lee-review-row.active', host)?.scrollIntoView({block: 'nearest'});
}

/* Apply the staged accepts, one call per document so each page gets one new version. */
async function reviewCommit(host, key = null) {
  const st = host.__review;
  const groups = new Map();
  for (const [id, s] of st.staged) if (!key || rowKey(s.row) === key) {
    if (!groups.has(s.row.doc)) groups.set(s.row.doc, []);
    groups.get(s.row.doc).push(s);
  }
  if (!groups.size) return;
  for (const [doc, ss] of groups) {
    const edits = Object.fromEntries(ss.filter(s => s.after != null).map(s => [s.row.id, s.after]));
    const r = await vaultCall('/vault/changes/accept', {doc, shelf: ss[0].row.shelf || '', vault: st.vault, ids: ss.map(s => s.row.id).join(','),
                                                       ...(Object.keys(edits).length ? {edits: JSON.stringify(edits)} : {})});
    ss.forEach(s => st.staged.delete(s.row.id));
    st.undo = st.undo.filter(u => !(u.t === 'stage' && ss.some(s => s.row.id === u.id)));
    if (r.ok) { st.undo.push({t: 'accept', doc, shelf: ss[0].row.shelf || '', ids: ss.map(s => s.row.id)}); status(`accepted ${r.accepted} change${r.accepted === 1 ? '' : 's'}`, 'ok'); }
    else status(r.kind === 'stale' ? 'the page was read again: proofread it again' : r.error, 'err');
  }
  await reviewLoad(host);
}

async function reviewReproof(host, r) {
  if (!r) return;
  const st = host.__review, base = {doc: r.doc, shelf: r.shelf || '', vault: st.vault};
  const est = await vaultCall('/vault/proofread', {...base, estimate: true});
  const readers = est.remembered?.readers || [];
  if (!readers.length) return vaultPageSheet('proof', {...base, title: r.title}, {pages: String(pageNo(r.page))});
  const go = await vaultCall('/vault/proofread', {...base, readers: readers.join(','), pages: String(pageNo(r.page)), agree: est.remembered.agree || 2});
  if (!go.html) return vaultPageSheet('proof', {...base, title: r.title}, {pages: String(pageNo(r.page))});
  status(`proofreading page ${pageNo(r.page)} again with ${readers.join(', ')}`);
  const id = (go.html.match(/id="job-([^"]+)"/) || [])[1];
  vaultFollow(id, host, 'proof', () => reviewLoad(host));
}

async function reviewDecide(host, url, rows, undo) {
  const st = host.__review, r0 = rows[0];
  const r = await vaultCall(url, {doc: r0.doc, shelf: r0.shelf || '', vault: st.vault, ids: rows.map(r => r.id).join(',')});
  if (!r.ok) { status(r.kind === 'stale' ? 'gone or changed since: the queue is reloaded' : r.error, 'err'); return reviewLoad(host); }
  if (undo) st.undo.push({...undo, doc: r0.doc, shelf: r0.shelf || '', ids: rows.map(r => r.id)});
  await reviewLoad(host);
}

function reviewEdit(host) {
  const st = host.__review, r = st.rows[st.at], el = $('.lee-review-row.active [data-after]', host);
  if (!r || !el || st.mode !== 'proof') return;
  if (r.stale) return status('the page was read again since: proofread it again', 'err');
  const inp = document.createElement('input');
  inp.className = 'lee-input lee-review-edit'; inp.value = st.staged.get(r.id)?.after ?? r.after ?? '';
  el.replaceWith(inp); inp.focus(); inp.select();
  inp.onkeydown = e => {
    e.stopPropagation();
    if (e.key === 'Escape') { e.preventDefault(); reviewPaint(host); host.focus(); }
    if (e.key !== 'Enter') return;
    e.preventDefault();
    st.staged.set(r.id, {row: r, after: inp.value});
    st.undo.push({t: 'stage', id: r.id});
    reviewPaint(host); host.focus();
  };
}

/* Keys queue behind each other: a second key acts on the queue the first one left. */
function leeReview(act, n = 1, el = null) {
  const host = el || document.activeElement?.closest?.('.lee-vault-review') || $('.lee-vault-review');
  if (!host?.__review) return status('open the Review tab first', 'err');
  return host.__chain = (host.__chain || Promise.resolve()).then(() => reviewAct(host, act, n)).catch(e => status(e.message || String(e), 'err'));
}

async function reviewAct(host, act, n) {
  const st = host.__review, r = st.rows[st.at], proof = st.mode === 'proof';
  const onPage = rows => rows.filter(x => r && rowKey(x) === rowKey(r));
  if (act === 'step') return reviewMove(host, Math.max(0, Math.min(st.rows.length - 1, st.at + n)));
  if (act === 'doubts') { if (!proof) return; await reviewCommit(host); st.doubts = !st.doubts; st.at = 0; return reviewPaint(host); }
  if (act === 'undo') {
    const u = st.undo.pop();
    if (!u) return status('nothing to undo', 'err');
    if (u.t === 'stage') { st.staged.delete(u.id); return reviewPaint(host); }
    if (u.t === 'type') {
      const res = await vaultCall('/vault/types/undo', {doc: u.doc, shelf: u.shelf, vault: st.vault, was: JSON.stringify(u.was)});
      status(res.ok ? 'undone' : res.error, res.ok ? 'ok' : 'err');
      return reviewLoad(host);
    }
    const url = u.t === 'pii' ? '/vault/pii/findings/undo' : '/vault/changes/undo';
    const res = await vaultCall(url, {doc: u.doc, shelf: u.shelf, vault: st.vault, ids: u.ids.join(',')});
    status(res.ok ? 'undone' : res.error, res.ok ? 'ok' : 'err');
    return reviewLoad(host);
  }
  if (act === 'edit' && st.mode === 'types') return reviewRetype(host);
  if (act === 'edit') return reviewEdit(host);
  if (!r) return status('nothing to decide', 'err');
  if (st.mode === 'types') {
    if (act === 'accept') return reviewType(host, 'accept', r);
    if (act === 'reject') return reviewType(host, 'reject', r);
    return status('types are decided one document at a time', 'err');
  }
  if (!proof) {
    if (act === 'accept') return reviewDecide(host, '/vault/pii/findings/accept', [r], {t: 'pii'});
    if (act === 'reject') return reviewDecide(host, '/vault/pii/findings/reject', [r], {t: 'pii'});
    if (act === 'page') return reviewDecide(host, '/vault/pii/findings/accept', onPage(st.rows), {t: 'pii'});
    return;
  }
  if (act === 'reject') {
    if (st.staged.has(r.id)) { st.staged.delete(r.id); }
    return reviewDecide(host, '/vault/changes/reject', [r], {t: 'reject'});
  }
  if (r.stale && act === 'accept') return status('the page was read again since: proofread it again', 'err');
  if (act === 'accept') {
    if (!st.staged.has(r.id)) { st.staged.set(r.id, {row: r, after: null}); st.undo.push({t: 'stage', id: r.id}); }
    reviewPaint(host);
    return st.at < st.rows.length - 1 ? reviewMove(host, st.at + 1) : reviewCommit(host);
  }
  if (act === 'page') {
    onPage(st.rows).filter(x => x.state === 'proposed' && !x.stale && !st.staged.has(x.id)).forEach(x => st.staged.set(x.id, {row: x, after: null}));
    return reviewCommit(host, rowKey(r));
  }
  if (act === 'doc') {
    const all = st.changes.filter(x => x.doc === r.doc && x.state === 'proposed' && !x.stale);
    if (!all.length) return status('nothing proposed in this document', 'err');
    if (!await confirmDialog('accept the document', `Accept all ${all.length} proposed change${all.length === 1 ? '' : 's'} in ${r.title || r.doc}?`, 'accept')) return;
    all.forEach(x => { if (!st.staged.has(x.id)) st.staged.set(x.id, {row: x, after: null}); });
    return reviewCommit(host);
  }
}
window.leeReview = leeReview;

/* A type is a meta field, not a page: an accept or a reject is undone by putting back what the route said was there. */
async function reviewType(host, verdict, r, doctype = '') {
  const st = host.__review;
  const res = await vaultCall(`/vault/types/${verdict}`, {doc: r.doc, shelf: r.shelf || '', vault: st.vault, ...(doctype ? {doctype} : {})});
  if (!res.ok) { status(res.kind === 'stale' ? 'decided elsewhere since: the queue is reloaded' : res.error, 'err'); return reviewLoad(host); }
  st.undo.push({t: 'type', doc: r.doc, shelf: r.shelf || '', was: res.was});
  status(verdict === 'accept' ? `typed ${res.doctype}` : 'proposal dropped', 'ok');
  return reviewLoad(host);
}

function reviewRetype(host) {
  const st = host.__review, r = st.rows[st.at], el = $('.lee-review-row.active [data-proposed]', host);
  if (!r || !el) return;
  const sel = document.createElement('select');
  sel.className = 'lee-input lee-review-edit'; sel.setAttribute('aria-label', 'another type');
  sel.innerHTML = st.labels.map(l => `<option value="${esc(l)}"${l === r.proposed ? ' selected' : ''}>${esc(l.replace(/_/g, ' '))}</option>`).join('');
  el.replaceWith(sel); sel.focus();
  sel.onkeydown = e => {
    e.stopPropagation();
    if (e.key === 'Escape') { e.preventDefault(); reviewPaint(host); host.focus(); }
    if (e.key === 'Enter') { e.preventDefault(); host.focus(); reviewType(host, 'accept', r, sel.value); }
  };
}
