/* ---- the Vault tab: its home, the add box, and the Read sheet ---- */

async function mountVaultWorkbench(host, st) {
  host.innerHTML = '<div class="lee-git-loading"><span></span><span></span><span></span><small>opening the vault</small></div>';
  try {
    // a Find scoped from the document view arrives with its scope, in one load
    const scoped = (st.view || '') === 'find' && lee.vaultFindNext ? '&' + new URLSearchParams(lee.vaultFindNext) : '';
    lee.vaultFindNext = null;
    await htmx.ajax('GET', '/vault/workbench?view=' + encodeURIComponent(st.view || 'library') + scoped,
                    {target: host, swap: 'innerHTML'});
  } catch (e) { host.innerHTML = `<div class="lee-err">${esc(e.message || e)}</div>`; }
}
window.mountVaultWorkbench = mountVaultWorkbench;

async function leeVaultWorkbench(view = 'library') {
  await htmx.ajax('POST', '/vault/workbench/open?view=' + encodeURIComponent(view),
                  {target: '#tabbar', swap: 'outerHTML'});
  return mountTab();
}
window.leeVaultWorkbench = leeVaultWorkbench;

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

function leeVaultAskAll(btn) {
  const rows = $$('.lee-wb-hit .lee-vault-ask', btn.closest('.lee-wb-find'));
  rows.forEach(b => attachVaultRef(b.dataset));
  paintAgentAttachments();
  leeRight('agent');
  status(`${rows.length} section${rows.length === 1 ? '' : 's'} attached`, 'ok');
}
window.leeVaultAskAll = leeVaultAskAll;

/* A vault route answers `{ok: false, error, kind}` with an error status, and the screen needs the
   kind, so this reads the body whatever the status. A job card comes back as HTML. */
async function vaultCall(url, data) {
  const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data || {})});
  const ct = r.headers.get('content-type') || '';
  return ct.includes('json') ? r.json() : {ok: r.ok, html: await r.text()};
}
window.vaultCall = vaultCall;

const VAULT_PAGED = /\.(pdf|png|jpe?g|tiff?|webp)$/i;
const VAULT_LEVELS = [['open', 'Open'], ['personal', 'Personal'], ['local', 'Local only']];

function leeVaultAdd(form) {
  const src = form.elements.src.value.trim();
  if (!src) return;
  if (VAULT_PAGED.test(src) && !/^https?:/.test(src)) return leeVaultReadSheet(src);
  const into = $('#vaultwbjobs') ? '#vaultwbjobs' : null;
  if (/^https?:|^\d{4}\.\d{4,5}|^github\.com\//.test(src))
    return into ? htmx.ajax('POST', '/vault/acquire?' + new URLSearchParams({target: src}), {target: into, swap: 'afterbegin'}) : null;
  return into ? htmx.ajax('POST', '/clip?' + new URLSearchParams({target: src, kind: 'clip', origin: 'library'}),
                          {target: into, swap: 'afterbegin'}) : null;
}
window.leeVaultAdd = leeVaultAdd;

async function vaultModels() {
  try { return (await api('/agent/models')).models || []; } catch { return []; }
}
const seesImages = m => /\bimage\b/.test(String(m.modalities || '').split(/out:|→/)[0]);

/* The Read sheet. It estimates first, says where every page would go, and remembers what was
   chosen for the folder, so a second file from the same place is one Enter. */
async function leeVaultReadSheet(src, {vault = '', shelf = ''} = {}) {
  if (!src) return status('choose a PDF or a page image to read', 'err');
  const est = await vaultCall('/vault/read', {src, estimate: true, vault, shelf});
  if (!est.ok) return status(est.error || 'could not read that file', 'err');
  const mem = est.remembered || {}, name = src.split('/').pop();
  const opts = (xs, cur) => xs.map(([v, l]) => `<option value="${esc(v)}"${v === cur ? ' selected' : ''}>${esc(l)}</option>`).join('');
  const m = modal(`<div class="lee-mhead"><span>Read into the vault</span><span class="sub">${esc(name)}</span></div>` +
    `<form class="lee-vault-sheet" data-vault-sheet>` +
    `<div class="lee-vault-est" data-est></div>` +
    `<label>parse<select class="lee-input" name="parse">${opts(est.parses.map(p => [p, {auto: 'auto: keep a sound text layer', text: 'text layer only', ocr: 'OCR every page', llm: 'model reads every page'}[p] || p]), mem.parse || 'auto')}</select></label>` +
    `<label>preset<select class="lee-input" name="preset">${opts(est.presets.map(p => [p, p]), mem.preset || est.type.preset || 'generic')}</select></label>` +
    `<label>model<select class="lee-input" name="model" id="vaultreadmodel" aria-label="the model that reads page images">` +
    `<option value="">no model: nothing leaves this machine</option></select></label>` +
    `<label>hint<input class="lee-input" name="hint" autocomplete="off" value="${esc(mem.hint || '')}" placeholder="what the pages are, for the model"></label>` +
    `<label>pages<input class="lee-input" name="pages" autocomplete="off" placeholder="all, or 1-3,7"></label>` +
    `<label>privacy<select class="lee-input" name="level">${opts(VAULT_LEVELS, est.level)}</select></label>` +
    `<div class="lee-vault-sendline" data-send role="status"></div>` +
    `<label class="lee-vault-allow" data-allow hidden><input type="checkbox" name="allow"> allow once: send the Personal pages whole, this read only</label>` +
    `<div class="lee-vault-sheetfoot"><span class="lee-spacer"></span><button class="lee-btn go" type="submit" data-read>Read</button></div>` +
    `<div class="lee-vault-jobs" data-job></div></form>`, null, null, {storageKey: 'vault-read'});
  const f = $('[data-vault-sheet]', m), sel = $('#vaultreadmodel', m);
  const local = est.type.vision === 'local';
  const models = (await vaultModels()).filter(r => seesImages(r) && (!local || r.local));
  for (const r of models) {
    const o = document.createElement('option');
    o.value = r.value; o.textContent = `${r.label} · ${r.local ? 'on this Mac' : 'hosted: ' + (r.provider || 'remote')}`;
    sel.appendChild(o);
  }
  if ([...sel.options].some(o => o.value === mem.model)) sel.value = mem.model;
  attachModelPicker(sel);
  const pickedModel = () => sel.value;
  let last = est;
  const paint = d => {
    last = d;
    const need = d.need?.length || 0, kind = d.type?.doctype;
    $('[data-est]', m).innerHTML = `<strong>${d.pages} page${d.pages === 1 ? '' : 's'}</strong>` +
      ` · ${need ? `up to ${need} need${need === 1 ? 's' : ''} the model` : 'none needs a model'}` +
      (Object.keys(d.flags || {}).length ? ` · ${Object.keys(d.flags).length} flagged` : '') +
      (kind ? ` · looks like ${esc(kind.replace(/_/g, ' '))}` : '') +
      (d.type?.level === 'local' ? '<br><span class="warn">this kind of document is Local only: only models on this Mac are offered</span>' : '');
    const line = $('[data-send]', m), blocked = d.check_ok === false || d.ok === false;
    line.textContent = d.why || '';
    line.className = 'lee-vault-sendline' + (blocked ? ' blocked' : '');
    line.dataset.kind = d.kind || '';
    $('[data-allow]', m).hidden = d.kind !== 'pii_blocked' && !f.elements.allow.checked;
    $('[data-read]', m).textContent = d.kind === 'model_unavailable' ? 'pick another model'
      : blocked ? 'Read, keeping withheld pages as text' : 'Read';
  };
  const fields = () => ({src, vault, shelf, parse: f.elements.parse.value, preset: f.elements.preset.value,
    model: pickedModel(), hint: f.elements.hint.value, pages: f.elements.pages.value, level: f.elements.level.value,
    allow: f.elements.allow.checked});
  const check = async () => {
    const d = await vaultCall('/vault/send-check', fields());
    paint(d.ok ? d : {...last, check_ok: false, kind: d.kind, why: d.error});
  };
  paint(est);
  if (est.kind || pickedModel() !== '') check();
  f.addEventListener('change', check);
  f.addEventListener('submit', async e => {
    e.preventDefault();
    if (last.kind === 'model_unavailable') return $('[data-model-pick]', m)?.click();
    const r = await vaultCall('/vault/read', {...fields(), partial: last.check_ok === false});
    const jobs = $('[data-job]', m);
    if (r.html) {
      jobs.insertAdjacentHTML('afterbegin', r.html);
      htmx.process(jobs);
      const id = (r.html.match(/id="job-([^"]+)"/) || [])[1];
      if (id) vaultFollow(id, m);
      return;
    }
    jobs.insertAdjacentHTML('afterbegin', `<div class="lee-job error" data-kind="${esc(r.kind || '')}">` +
      `<span class="lee-job-error">${esc(r.error || 'the read did not start')}</span></div>`);
    if (r.kind === 'busy' && r.job) $(`#job-${CSS.escape(r.job)}`)?.scrollIntoView({block: 'nearest'});
  });
  if (mem.parse) setTimeout(() => $('[data-read]', m)?.focus(), 0);
  return m;
}
window.leeVaultReadSheet = leeVaultReadSheet;

/* The card polls itself; this waits on the same job to open what it read. */
async function vaultFollow(id, m, kind = 'read', done = null) {
  for (let i = 0; i < 1800 && m.isConnected; i++) {
    await new Promise(res => setTimeout(res, 700));
    let j;
    try { j = (await api(`/jobs?kind=${kind}&limit=20`)).jobs.find(x => x.id === id); } catch { continue; }
    if (!j || j.active) continue;
    if (j.status !== 'complete' || !j.result?.doc_id && kind === 'read') return;
    if (done) return done(j);
    m.remove();
    const r = j.result;
    status(r.blocked?.length ? `${r.blocked.length} page(s) kept their text layer: not sent` : 'read into the vault', r.blocked?.length ? 'err' : 'ok');
    return leeOpenVaultDoc(r.doc_id, r.shelf || '', r.vault || '', r.title || j.target.split('/').pop());
  }
}

/* Clipping a PDF or a scan is a read; anything else is clipped as text. Either way it lands in the Vault tab. */
async function leeClipToVault() {
  const target = clipTarget();
  if (!target) return status('select a file, a folder or a tab to clip', 'err');
  if (VAULT_PAGED.test(target)) return leeVaultReadSheet(target);
  await leeVaultWorkbench('library');
  const into = $('#vaultwbjobs');
  if (!into) return status('the Vault tab did not open', 'err');
  await htmx.ajax('POST', '/clip?' + new URLSearchParams({target, kind: 'clip', origin: 'menu'}), {target: into, swap: 'afterbegin'});
  into.closest('details')?.setAttribute('open', '');
  status(`clipping ${target.split('/').pop() || target} into the vault…`);
}
window.leeClipToVault = leeClipToVault;

function leeVaultRead() {
  const target = clipTarget();
  if (target && VAULT_PAGED.test(target)) return leeVaultReadSheet(target);
  return leeVaultWorkbench('library').then(() => $('[data-vault-add] input')?.focus());
}
window.leeVaultRead = leeVaultRead;

/* ---- Find: one box, a scope chip, hits to open and an answer that cites them ---- */

const findForm = el => el.closest('[data-vault-find]');
const findScope = f => {
  const scope = f.elements.scope?.value || 'vault';
  return {doc: scope === 'vault' ? '' : f.elements.doc.value, pages: scope === 'pages' ? f.elements.pages.value : '',
          shelf: f.elements.shelf.value, vault: f.elements.vault.value, model: f.elements.model?.value || ''};
};

function leeVaultScope(sel) {
  const f = findForm(sel); if (!f) return;
  f.elements.pages.hidden = sel.value !== 'pages';
  if (sel.value === 'pages') f.elements.pages.focus();
  vaultFindLine(f);
}
window.leeVaultScope = leeVaultScope;

/* Where an answer's sections may go, said before anything is asked, by the route every send line uses. */
async function vaultFindLine(f) {
  const line = $('[data-send]', f.closest('.lee-wb-find'));
  if (!line) return;
  const d = await vaultCall('/vault/send-check', {ask: true, ...findScope(f)});
  line.hidden = false;
  line.textContent = d.ok ? d.why : d.error;
  line.className = 'lee-vault-sendline' + (d.ok && d.check_ok !== false ? '' : ' blocked');
  line.dataset.kind = d.kind || '';
}

async function mountVaultFind(f) {
  f.dataset.mounted = '1';
  const sel = document.createElement('select');
  sel.name = 'model'; sel.className = 'lee-input'; sel.id = 'vaultaskmodel'; sel.setAttribute('aria-label', 'the model that answers');
  sel.add(new Option('the conversation model', ''));
  for (const r of await vaultModels()) sel.add(new Option(`${r.label} · ${r.local ? 'on this Mac' : 'hosted: ' + (r.provider || 'remote')}`, r.value));
  $('[data-find-ask]', f).before(sel);
  attachModelPicker(sel);
  sel.addEventListener('change', () => vaultFindLine(f));
  f.elements.pages.addEventListener('input', () => { clearTimeout(f.__t); f.__t = setTimeout(() => vaultFindLine(f), 300); });
  vaultFindLine(f);
}
const mountVaultFinds = () => $$('[data-vault-find]:not([data-mounted])').forEach(mountVaultFind);
document.addEventListener('htmx:afterSettle', mountVaultFinds);

async function leeVaultAskFind(btn) {
  const f = findForm(btn), q = f?.elements.q.value.trim();
  if (!q) return status('type a question to ask', 'err');
  const box = f.closest('.lee-wb-find'), out = $('[data-answer]', box), line = $('[data-send]', box), sc = findScope(f);
  out.hidden = false; out.className = 'lee-wb-answer asking'; out.dataset.kind = '';
  out.innerHTML = '<div class="lee-wb-answertext" data-answer-text>asking…</div><div class="lee-wb-cites" data-cites></div>';
  const text = $('[data-answer-text]', out), cites = $('[data-cites]', out);
  const fail = (msg, kind) => { out.className = 'lee-wb-answer failed'; out.dataset.kind = kind || ''; text.textContent = msg; };
  const said = (why, ok) => { line.hidden = false; line.textContent = why; line.className = 'lee-vault-sendline' + (ok === false ? ' blocked' : ''); };
  try {
    await postEvents('/vault/ask', {q, ...sc}, (ev, d) => {
      if (ev === 'send') said(d.why, d.check_ok);
      else if (ev === 'reset') text.textContent = '';
      else if (ev === 'chunk') text.textContent = d.text;
      else if (ev === 'error') fail(d.error, d.kind);
      else if (ev === 'answer') {
        out.className = 'lee-wb-answer' + (d.refused ? ' failed' : '');
        renderMarkdown(text, d.answer || '*no answer*');
        if (d.send?.why) said(d.send.why, d.send.ok);
        cites.innerHTML = (d.cited || []).map(c => `<button class="lee-wb-cite" data-cite="${c.n}">` +
          `<b>[${c.n}]</b> ${esc(c.title)}${c.page == null ? '' : ` · p. ${pageNo(c.page)}`}</button>`).join('');
        $$('[data-cite]', cites).forEach(b => b.onclick = () => {
          const c = d.cited.find(x => x.n === +b.dataset.cite);
          leeOpenVaultDoc(c.doc, c.shelf, sc.vault, c.title, {page: c.page, quote: c.quote});
        });
      }
    });
  } catch (e) {
    let body = {}; try { body = JSON.parse(e.message); } catch {}
    fail(body.error || e.message || String(e), body.kind);
  }
}
window.leeVaultAskFind = leeVaultAskFind;

/* Find scoped to the document in the view, or to its current page. */
async function leeVaultFindIn(st, page = null) {
  lee.vaultFindNext = {doc: st.doc, shelf: st.shelf || '', vault: st.vault || '', title: st.title || st.doc, scope: page == null ? 'doc' : 'pages',
                       ...(page == null ? {} : {pages: String(pageNo(page))})};
  await leeVaultWorkbench('find');
  $('[data-vault-find] [name=q]')?.focus();
  if (page != null) status(`ask about page ${pageNo(page)}: type the question, then ask`, 'ok');
}
window.leeVaultFindIn = leeVaultFindIn;

async function leeVaultGuessTypes(btn) {
  const d = await vaultCall('/vault/types/guess', {vault: btn.dataset.vault || ''});
  status(d.ok ? `${d.typed} typed, ${d.proposed} to decide under Review > Types` : d.error, d.ok ? 'ok' : 'err');
  if (d.ok) htmx.ajax('GET', '/vault/view/library?' + new URLSearchParams({vault: btn.dataset.vault || ''}), {target: '#vaultwbbody', swap: 'innerHTML'});
}
window.leeVaultGuessTypes = leeVaultGuessTypes;
