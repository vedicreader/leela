/* ------------------------------------------------------------------ agent */
function closeDismissableDisclosures(except = null) {
  $$('details.lee-dismissable[open]').forEach(details => { if (details !== except) details.open = false; });
}
document.addEventListener('pointerdown', e => {
  const inside = e.target.closest?.('details.lee-dismissable');
  closeDismissableDisclosures(inside);
}, true);
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape' || $$('.lee-modal').length) return;
  const open = $$('details.lee-dismissable[open]').at(-1);
  if (!open) return;
  e.preventDefault(); e.stopPropagation(); open.open = false;
  open.querySelector(':scope > summary')?.focus();
}, true);
window.addEventListener('blur', () => closeDismissableDisclosures());

// A model that draws or films says so in the picker itself; the rest of what it takes is the tooltip.
const modelMark = (m) => (m.gen_image ? ' · draws' : '') + (m.gen_video ? ' · films' : '');

// Cursor is the one runtime whose own tools act outside Leela's approvals, so the pane says so
// while such a model is chosen. The wording lives in the markup; this only decides when it shows.
let MODEL_RUNTIMES = {};
function markHarness(model) {
  const banner = $('#agentharnessbanner');
  if (banner) banner.hidden = MODEL_RUNTIMES[model] !== 'cursor';
}

/* The model list is long, and a native `<select>` hands its menu to the platform. WKWebView draws a
   list that long at the top of the screen rather than under the control, so in the packaged app the
   picker opened nowhere near the thing it belongs to. The select stays: it is the value, the id and
   the change event every other caller already reads, and this only draws a menu Leela can place
   itself. Every option comes from the select, so `loadAgentModels` keeps filling one list. */
const MODEL_MENU_MIN = 280, MODEL_MENU_ROOM = 220;
let modelMenu = null;

function modelLabel(select) {
  const o = select.options[select.selectedIndex];
  return o ? o.textContent : (select.value || 'choose a model');
}
function paintModelPickers(root = document) {
  for (const b of $$('[data-model-pick]', root)) {
    // The routed jobs have no id of their own -- they are `[data-job]` rows this file draws -- and
    // `'#' + ''` is not a selector but a SyntaxError, thrown before the sibling fallback below it
    // could answer. It took `loadAgentModels` down with it, and with it every error that reloading
    // the panel was supposed to report.
    // `attachModelPicker` inserts the button *before* the select it stands for, so the select is
    // what follows it. Looking the other way found the previous row's label and read `options` off
    // whatever that was.
    const id = b.dataset.modelPick;
    const select = (id && $('#' + id, root)) || b.nextElementSibling;
    if (select && select.options) b.textContent = modelLabel(select);
  }
}
function closeModelMenu(focus = false) {
  if (!modelMenu) return;
  const {el, button} = modelMenu;
  modelMenu = null;
  el.remove();
  button.setAttribute('aria-expanded', 'false');
  if (focus) button.focus();
}
function placeModelMenu(el, button) {
  const r = button.getBoundingClientRect(), width = Math.max(r.width, MODEL_MENU_MIN);
  el.style.width = `${Math.min(width, window.innerWidth - 16)}px`;
  const below = window.innerHeight - r.bottom;
  // Above when there is not room under it, and never off the edge: the fault being fixed here is a
  // menu that had nothing to do with where its control was.
  el.style.maxHeight = `${Math.max(160, Math.min(340, (below > MODEL_MENU_ROOM ? below : r.top) - 12))}px`;
  el.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - width - 8))}px`;
  if (below > MODEL_MENU_ROOM) { el.style.top = `${r.bottom + 4}px`; el.style.bottom = 'auto'; }
  else { el.style.bottom = `${window.innerHeight - r.top + 4}px`; el.style.top = 'auto'; }
}
function openModelMenu(select, button) {
  if (modelMenu?.button === button) return closeModelMenu(true);
  closeModelMenu();
  const el = document.createElement('div');
  el.className = 'lee-model-menu'; el.id = 'modelmenu';
  el.innerHTML = `<input class="lee-input lee-model-filter" data-model-filter placeholder="filter models…"` +
    ` autocomplete="off" spellcheck="false" aria-controls="modellist" aria-label="filter models">` +
    `<div class="lee-model-list" id="modellist" role="listbox" data-model-list></div>`;
  document.body.appendChild(el);
  button.setAttribute('aria-expanded', 'true');
  const list = $('[data-model-list]', el), filter = $('[data-model-filter]', el);
  let rows = [], active = 0;
  const paint = () => {
    const want = filter.value.trim().toLowerCase();
    rows = [...select.options].filter(o => !want ||
      `${o.textContent} ${o.value}`.toLowerCase().includes(want));
    if (!rows.length) { list.innerHTML = '<div class="lee-model-empty">no model matches</div>'; return; }
    active = Math.max(0, rows.findIndex(o => o.value === select.value));
    list.innerHTML = rows.map((o, i) =>
      `<button type="button" class="lee-model-row${o.value === select.value ? ' chosen' : ''}"` +
      ` role="option" id="modelrow${i}" aria-selected="${o.value === select.value}"` +
      ` data-value="${esc(o.value)}" title="${esc(o.title || '')}">${esc(o.textContent)}</button>`).join('');
    move(active);
  };
  const move = i => {
    if (!rows.length) return;
    active = (i + rows.length) % rows.length;
    const items = $$('.lee-model-row', list);
    items.forEach((x, n) => x.classList.toggle('active', n === active));
    items[active]?.scrollIntoView({block: 'nearest'});
    filter.setAttribute('aria-activedescendant', `modelrow${active}`);
  };
  const commit = value => {
    closeModelMenu(true);
    if (value === select.value) return;
    select.value = value;
    // The select's own `change` is what saves it, so one path answers for the picker and the
    // keyboard, and a refusal unwinds through `loadAgentModels` as it always did.
    select.dispatchEvent(new Event('change', {bubbles: true}));
    paintModelPickers();
  };
  list.onclick = e => { const row = e.target.closest('[data-value]'); if (row) commit(row.dataset.value); };
  filter.oninput = paint;
  filter.onkeydown = e => {
    if (e.key === 'ArrowDown') { e.preventDefault(); move(active + 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); move(active - 1); }
    else if (e.key === 'Home') { e.preventDefault(); move(0); }
    else if (e.key === 'End') { e.preventDefault(); move(rows.length - 1); }
    else if (e.key === 'Enter') { e.preventDefault(); if (rows[active]) commit(rows[active].value); }
    else if (e.key === 'Escape') { e.preventDefault(); closeModelMenu(true); }
    else if (e.key === 'Tab') closeModelMenu();
  };
  modelMenu = {el, button, select};
  paint();
  placeModelMenu(el, button);
  filter.focus();
}
function attachModelPicker(select) {
  if (!select || select.dataset.leePicked) return;
  select.dataset.leePicked = '1';
  const button = document.createElement('button');
  button.type = 'button';
  button.className = `${select.className} lee-model-pick`;
  button.dataset.modelPick = select.id || '';
  button.setAttribute('role', 'combobox');
  button.setAttribute('aria-haspopup', 'listbox');
  button.setAttribute('aria-expanded', 'false');
  button.setAttribute('aria-label', select.getAttribute('aria-label') || 'model');
  button.title = select.title || '';
  button.textContent = modelLabel(select);
  button.onclick = () => openModelMenu(select, button);
  button.onkeydown = e => {
    if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openModelMenu(select, button); }
  };
  select.hidden = true;                       // kept for its id, its value and its change event
  select.insertAdjacentElement('beforebegin', button);
  select.addEventListener('change', () => { button.textContent = modelLabel(select); });
  return button;
}
document.addEventListener('pointerdown', e => {
  if (modelMenu && !e.target.closest('.lee-model-menu, [data-model-pick]')) closeModelMenu();
}, true);
window.addEventListener('resize', () => closeModelMenu());
/* A menu placed against a rect is wrong the moment the thing under it moves, so it follows. Its own
   list scrolling is not that: closing on every scroll took the list away as soon as it was used. */
window.addEventListener('scroll', e => {
  if (!modelMenu) return;
  if (e.target instanceof Node && modelMenu.el.contains(e.target)) return;
  const r = modelMenu.button.getBoundingClientRect();
  if (r.bottom < 0 || r.top > window.innerHeight) return closeModelMenu();
  placeModelMenu(modelMenu.el, modelMenu.button);
}, true);
window.leeModelPickers = paintModelPickers;

async function loadAgentModels(legacy = $('#legacymodels')?.checked ?? true) {
  const selects = {agent: $('#agentmodel'), inline: $('#inlinemodel'), completion: $('#completionmodel')};
  if (!selects.agent || !selects.inline || !selects.completion) return;
  const previous = Object.fromEntries(Object.entries(selects).map(([k, s]) => [k, s.value]));
  const d = await api('/agent/models?legacy=' + (legacy ? 'true' : 'false'));
  for (const [target, select] of Object.entries(selects)) {
    select.innerHTML = '';
    for (const m of (d.models || [])) {
      const option = document.createElement('option');
      option.value = m.value; option.textContent = `${m.label} · ${m.provider}${modelMark(m)}`;
      option.title = [m.source, m.modalities].filter(Boolean).join(' · ');
      select.appendChild(option);
    }
    const wanted = d.selected?.[target] || previous[target];
    if ([...select.options].some(o => o.value === wanted)) select.value = wanted;
  }
  MODEL_RUNTIMES = Object.fromEntries((d.models || []).map(m => [m.value, m.runtime || '']));
  JOB_HELP = d.job_help || JOB_HELP;
  markHarness(selects.agent.value);
  paintJobModels(d);
  for (const select of Object.values(selects)) attachModelPicker(select);
  paintModelPickers();
  const notes = Object.values(d.auth || {}).map(x => x.note).filter(Boolean);
  if (notes.length) selects.agent.title = notes.join(' · ');
}

/* What each routed job spends its model on comes from the server, which is the same copy the
   server-rendered controls use. Two copies of this drifted apart the first time. */
let JOB_HELP = {};
const helpMark = job => JOB_HELP[job]
  ? `<span class="lee-hint" tabindex="0" role="note" aria-label="${esc(JOB_HELP[job])}" title="${esc(JOB_HELP[job])}">?</span>` : '';
function paintJobModels(d) {
  const host = $('#jobmodels'); if (!host) return;
  const jobs = Object.entries(d.jobs || {});
  host.hidden = !jobs.length;
  if (!jobs.length) return;
  const options = (d.models || []).map(m =>
    `<option value="${esc(m.value)}">${esc(m.label)} · ${esc(m.provider)}${esc(modelMark(m))}</option>`).join('');
  host.innerHTML = jobs.map(([job, current]) =>
    `<label><span class="lee-routing-name">${esc(job)}${helpMark(job)}</span>` +
    `<select class="lee-select" data-job="${esc(job)}">` +
    options + `</select></label>`).join('');
  for (const [job, current] of jobs) {
    const sel = host.querySelector(`[data-job="${job}"]`);
    if ([...sel.options].some(o => o.value === current)) sel.value = current;
    sel.onchange = () => leeAgentModel(job, sel.value);
    attachModelPicker(sel);
  }
}
window.leeLoadModels = loadAgentModels;

/* The on-device backends are not in the download, because they are most of what a download would
   weigh. This is the one place that says so and the one place that fetches them; the rows come
   from `/agent/runtimes`, so what is installable and what it needs stay rishi's to declare. */
let bkPoll = 0;
function backendRow(r) {
  const st = r.install || {}, running = st.state === 'running';
  const note = running ? `installing with ${esc(st.via || 'pip')}…`
    : st.state === 'error' ? `${esc(st.via || 'the installer')} failed — see below`
    : r.available ? 'ready' : esc(r.why || 'not installed');
  return `<div class="lee-setup-row" data-bk="${esc(r.value)}">` +
    `<span><strong>${esc(r.label || r.value)}</strong><br><small>${note}</small>` +
    `${(r.requirements || []).length ? `<br><code>${esc(r.requirements.join(' '))}</code>` : ''}` +
    `${st.state === 'error' && st.log ? `<br><small class="warn">${esc(String(st.log).split('\n').slice(-3).join(' '))}</small>` : ''}</span>` +
    `${r.available ? '<span class="lee-dim">installed</span>'
      : `<button class="lee-btn" data-bk-get ${running ? 'disabled' : ''}>${running ? '…' : 'install'}</button>`}` +
    `</div>`;
}
function renderBackends(m, rows) {
  const host = $('#backends', m); if (!host) return;
  const mine = rows.filter(r => r.installable);
  if (!mine.length) return void (host.innerHTML = '<div class="lee-dim">none on this platform</div>');
  host.innerHTML = mine.map(backendRow).join('');
  host.querySelectorAll('[data-bk]').forEach(row => row.querySelector('[data-bk-get]')?.addEventListener('click', async () => {
    const runtime = row.dataset.bk;
    const r = await post('/agent/runtimes/install', {runtime});
    if (!r.ok) return status(r.error || `could not install ${runtime}`, 'err');
    status(`installing ${runtime}… this downloads a lot and keeps going if you close this`, 'busy');
    pollBackends(m);
  }));
  // Only while something is running: an install takes minutes and the pane must not look stuck.
  clearTimeout(bkPoll);
  if (mine.some(r => (r.install || {}).state === 'running')) bkPoll = setTimeout(() => pollBackends(m), 2000);
}
async function pollBackends(m) {
  if (!m.isConnected) return clearTimeout(bkPoll);
  let d;
  try { d = await api('/agent/runtimes'); } catch (e) { return status(String(e.message || e), 'err'); }
  renderBackends(m, d.runtimes || []);
  const done = (d.runtimes || []).filter(r => r.installable && (r.install || {}).state === 'ok');
  if (done.length) { status(`${done.map(r => r.value).join(', ')} installed`, 'ok'); loadAgentModels(); }
}

async function leeAddModel() {
  const d = await api('/agent/models');
  const saved = (d.saved || []).map(x => `<div class="lee-setup-row"><span><strong>${esc(x.name)}</strong> · ${esc(x.runtime)}<br><small>${esc(x.model_id)}</small></span><button class="lee-btn warn" data-remove="${esc(x.name)}">remove</button></div>`).join('');
  const m = modal(`<div class="lee-mhead">Add model<span class="sub">saved in Leela · API keys stay in environment variables</span></div>
    <label>name<input class="lee-input" id="modelalias" placeholder="ornith-test"></label>
    <label>model ID or Hugging Face URL<input class="lee-input" id="modelid" placeholder="https://huggingface.co/litert-community/… or openai/model-id"></label>
    <label>runtime<select class="lee-select" id="modelruntime"></select></label>
    <label>context tokens<input class="lee-input" id="modelctx" type="number" value="128000" min="1024"></label>
    <details><summary>hosted API settings</summary><label>base URL<input class="lee-input" id="modelbase" placeholder="https://api.example.com/v1"></label><label>API key environment variable<input class="lee-input" id="modelkeyenv" placeholder="OPENAI_API_KEY"></label><label>FastLLM vendor<input class="lee-input" id="modelvendor" placeholder="openai"></label><label>FastLLM API transport<input class="lee-input" id="modelapi" placeholder="openai"></label></details>
    <button class="lee-btn go" id="modelsave">save model</button>
    <h4>on-device backends</h4><div class="lee-modallist" id="backends"></div>
    <h4>saved models</h4><div class="lee-modallist">${saved || '<div class="lee-dim">none yet</div>'}</div>`);
  /* The runtimes ramabana will accept, and which of them rishi can load here. The list, the
     label and the remedy all come from `d.runtimes`: kept here they drifted twice, offering MLX
     after it was dropped and telling you to pip install Cursor. Unavailable stays visible. */
  const rtsel = m.querySelector('#modelruntime');
  rtsel.innerHTML = (d.runtimes || [{value: 'remote', label: 'hosted API / FastLLM', available: true}]).map(r =>
    `<option value="${esc(r.value)}"${r.available ? '' : ' disabled'}>${esc(r.label || r.value)}` +
    `${r.available ? '' : ' — ' + esc(r.why || 'unavailable here')}</option>`).join('');
  const firstrt = rtsel.querySelector('option:not([disabled])');
  if (firstrt) rtsel.value = firstrt.value;
  renderBackends(m, d.runtimes || []);

  $('#modelsave', m).onclick = async () => {
    status('validating and saving model…');
    const r = await post('/agent/models/add', {name: $('#modelalias',m).value.trim(), model_id: $('#modelid',m).value.trim(), runtime: $('#modelruntime',m).value, ctx: Number($('#modelctx',m).value), base_url: $('#modelbase',m).value.trim(), api_key_env: $('#modelkeyenv',m).value.trim(), vendor_name: $('#modelvendor',m).value.trim(), api_name: $('#modelapi',m).value.trim()});
    if (!r.ok) return status(r.error || 'could not save model','err');
    m.remove(); await loadAgentModels(); status(`saved ${r.model.name} · ${r.model.runtime} · ${r.model.model_id}`,'ok');
  };
  $$('[data-remove]',m).forEach(b => b.onclick = async () => {
    const name=b.dataset.remove; const r=await post('/agent/models/remove',{name});
    if (!r.ok) return status(r.error || 'could not remove model','err');
    m.remove(); await loadAgentModels(); status(`removed ${name}`,'ok');
  });
  $('#modelalias',m)?.focus();
}
window.leeAddModel = leeAddModel;

const MODEL_SELECTS = {agent: '#agentmodel', inline: '#inlinemodel', completion: '#completionmodel'};
async function leeAgentModel(target, model) {
  // A harness job has no select of its own; it has the row `paintJobModels` drew for it.
  const select = $(MODEL_SELECTS[target] || `#jobmodels [data-job="${target}"]`);
  if (select) select.disabled = true;
  try {
    const d = await post('/agent/model', {target, model});
    if (d.ok && target === 'agent') markHarness(model);
    status(d.ok ? `${target} model saved: ${d.model}` : (d.error || 'model switch failed'), d.ok ? 'ok' : 'err');
    if (d.ok && target === 'completion') api('/complete/warm').catch(() => {});
    if (!d.ok) await loadAgentModels().catch(() => {});
  } catch (e) {
    // The message first: a refusal is the one sentence there is to act on, and putting the panel
    // back ahead of it meant a failure in the reload -- there was one -- threw the message away.
    status(e.message || String(e), 'err');
    await loadAgentModels().catch(() => {});
  }
  finally { if (select) select.disabled = false; }
}
window.leeAgentModel = leeAgentModel;

async function leeAgentCompaction() {
  try {
    const d = await post('/agent/compaction', {auto: !!$('#autocompact')?.checked,
                                               strategy: $('#compactstrategy')?.value || 'surgical'});
    status(d.note, 'ok');
  } catch (e) { status(e.message || String(e), 'err'); }
}
window.leeAgentCompaction = leeAgentCompaction;


/* Setting a model up, and afterwards where a new release shows up. A modal both times: the two
   panes do not fit the welcome screen's column and were cut off on the right. */
async function leeSetupPane() {
  const host = $('#leesetup'); if (!host) return;
  let d;
  try { d = await api('/agent/setup'); } catch (_) { return; }
  if (!d.ok || !d.frozen) { host.hidden = true; return; }
  host.hidden = false;
  host.innerHTML = `<button class="lee-btn${d.done ? '' : ' go'}" id="setupopen">` +
    `${d.done ? 'Models and updates' : 'Set up a model'}</button>`;
  $('#setupopen', host).onclick = () => leeSetupModal();
  if (!d.done && !d.dismissed) leeSetupModal(d);      // nothing can answer a prompt yet
}
function setupRow(a) {
  return `<div class="lee-setup-row"><span><strong>${esc(a.label)}</strong><br>` +
    `<small>${esc(a.blurb)}</small>` +
    `${a.detail ? `<br><small class="warn">${esc(a.detail)}</small>` : ''}</span>` +
    `<span class="${a.ready ? 'lee-dim' : 'warn'}">${a.ready ? 'ready' : 'not set up'}</span></div>`;
}
function offlineRow(o) {
  const st = o.install || {}, running = st.state === 'running';
  // The recommended one is named as such and offered first: it is the smallest, it runs on any Mac,
  // and the vault answers with it, so a bundle without it has no memory rather than a slower one.
  return `<div class="lee-setup-row" data-setup-get="${esc(o.value)}"><span><strong>${esc(o.label || o.value)}</strong>` +
    `${o.recommended ? ' <small class="lee-setup-pick">recommended</small>' : ''}` +
    ` <small>about ${o.mb} MB</small>` +
    `${st.state === 'error' ? `<br><small class="warn">${esc(String(st.log).split('\n').slice(-2).join(' '))}</small>` : ''}</span>` +
    `${o.available ? '<span class="lee-dim">installed</span>'
      : `<button class="lee-btn" ${running ? 'disabled' : ''}>${running ? `${esc(st.via || 'installing')}\u2026` : 'install'}</button>`}</div>`;
}
function toolRow(o) {
  const st = o.install || {}, running = st.state === 'running';
  return `<div class="lee-setup-row" data-setup-get="${esc(o.value)}"><span><strong>${esc(o.label)}</strong>` +
    ` <small>about ${o.mb} MB</small><br><small>${esc(o.blurb)}</small>` +
    `${st.state === 'error' ? `<br><small class="warn">${esc(String(st.log).split('\n').slice(-2).join(' '))}</small>` : ''}</span>` +
    `${o.available ? `<span class="lee-dim">${esc(o.found || 'installed')}</span>`
      : `<button class="lee-btn" ${running ? 'disabled' : ''}>${running ? `${esc(st.via || 'installing')}\u2026` : 'install'}</button>`}</div>`;
}

function updateRows(u) {
  if (!u) return '<div class="lee-dim">checking\u2026</div>';
  const app = u.leela || {};
  const head = app.outdated
    ? `<div class="lee-setup-row"><span><strong>Leela ${esc(app.latest)}</strong><br><small>you have ${esc(app.current)}</small></span>` +
      `<a class="lee-btn go" href="${esc(app.url)}" target="_blank" rel="noreferrer">get it</a></div>`
    : `<div class="lee-setup-row"><span><strong>Leela ${esc(app.current)}</strong><br><small>${app.latest ? 'up to date' : 'could not check'}</small></span></div>`;
  const rows = (u.outdated || []).map(r =>
    `<div class="lee-setup-row" data-setup-get="${esc(r.runtime)}"><span><strong>${esc(r.dist)}</strong><br>` +
    `<small>${esc(r.installed)} \u2192 ${esc(r.latest)}</small></span><button class="lee-btn">update</button></div>`).join('');
  return head + rows + (rows ? '' : (u.backends || []).length
    ? '<div class="lee-dim">backends are current</div>' : '');
}
function setupBody(d, u) {
  return `<div class="lee-setup-panes"><section class="lee-setup-pane${d.done ? '' : ' recommended'}"><h4>Accounts` +
    `<small>nothing to download</small></h4>${d.accounts.map(setupRow).join('')}</section>` +
    `<section class="lee-setup-pane"><h4>On device<small>large</small></h4>` +
    `${d.offline.length ? d.offline.map(offlineRow).join('') : '<div class="lee-dim">nothing for this machine</div>'}` +
    `</section></div>` +
    `${(d.tools || []).length ? `<h4>Tools</h4><div class="lee-setup-updates">${d.tools.map(toolRow).join('')}</div>` : ''}` +
    `<h4>Updates</h4><div class="lee-setup-updates">${updateRows(u)}</div>`;
}
/* The box `modal()` built owns the head, the foot and the close button, so only the middle is
   rewritten. Replacing the box's own markup threw all three away, and the styles with them. */
function renderSetup(box, d, u) {
  $('.lee-setup-body', box).innerHTML = setupBody(d, u);
  box.querySelectorAll('[data-setup-get]').forEach(row => row.querySelector('button')?.addEventListener('click', async () => {
    const runtime = row.dataset.setupGet;
    const r = await post('/agent/runtimes/install', {runtime});
    if (!r.ok) return status(r.error || `could not install ${runtime}`, 'err');
    status(`installing ${runtime}\u2026 it keeps going if you close this`, 'busy');
    pollSetup(box);
  }));
  clearTimeout(bkPoll);
  const busy = [...(d.offline || []), ...(d.tools || [])].some(o => (o.install || {}).state === 'running');
  if (busy) bkPoll = setTimeout(() => pollSetup(box), 2000);
}
async function leeSetupModal(known) {
  let d = known;
  if (!d) { try { d = await api('/agent/setup'); } catch (e) { return status(String(e.message || e), 'err'); } }
  const m = modal(`<div class="lee-mhead">${d.done ? 'Models and updates' : 'Set up a model'}` +
    `<span class="sub">${d.done ? 'what is installed here, and what is newer' : 'the agent has nothing to answer with yet'}</span></div>` +
    `<div class="lee-setup-body"></div>` +
    `<div class="lee-mfoot"><button class="lee-btn" id="setupreset">start over</button>` +
    `<span class="lee-spacer"></span><button class="lee-btn go" id="setupdone" autofocus>done</button></div>`,
    null, null, {className: 'lee-setup-modal', storageKey: 'agent-setup'});
  const box = $('.lee-modalbox', m);
  /* Setting a model up is a thing people get part way through and want to begin again: this puts
     the first-run prompt back rather than hiding it for good. */
  $('#setupreset', box).onclick = async () => {
    await post('/agent/setup/dismiss', {dismissed: false});
    m.remove();
    leeSetupPane();
    leeSetupModal();
  };
  $('#setupdone', box).onclick = async () => {
    await post('/agent/setup/dismiss', {dismissed: true});
    m.remove();
    leeSetupPane();
  };
  renderSetup(box, d, null);
  // The version check is a network call, so the modal opens first and fills this in.
  try { renderSetup(box, d, await api('/agent/updates')); } catch (_) { renderSetup(box, d, {leela: {}}); }
}
async function pollSetup(box) {
  if (!box.isConnected) return clearTimeout(bkPoll);
  try {
    const d = await api('/agent/setup');
    if (d.ok) renderSetup(box, d, await api('/agent/updates').catch(() => null));
  } catch (e) { status(String(e.message || e), 'err'); }
}
window.leeSetupPane = leeSetupPane;
window.leeSetupModal = leeSetupModal;
/* How much work one turn may do. `auto` lets ramabana size it from the prompt; a number pins it.
   The fields are written back from the answer, so a refusal leaves the box showing what is
   actually in force rather than the rejected text. */
/* The highlighted range, queued as context for the next turn. Sent as text rather than as
   `path:from-to` for the agent to read, because the buffer may be unsaved and what you highlighted
   is what you meant. */
function leeAgentSelection() {
  const v = curEditor();
  if (!v) return status('put the cursor in some code first', 'err');
  const sel = v.state.selection.main;
  if (sel.empty) return status('select the code you want the agent to see', 'err');
  const doc = v.state.doc, from = doc.lineAt(sel.from).number, to = doc.lineAt(sel.to).number;
  const path = lee.path || 'untitled', name = path.split('/').pop() || 'untitled';
  lee.agentSelections.push({
    label: `${name}:${from}${to > from ? '–' + to : ''}`,
    path,
    ref: {kind: 'selection', path, from, to, text: doc.sliceString(sel.from, sel.to)},
  });
  leePane('right', true); leeRight('agent'); paintAgentAttachments();
  $('#agentprompt')?.focus();
  status(`selection queued for the agent · ${from}${to > from ? '–' + to : ''}`, 'ok');
}
window.leeAgentSelection = leeAgentSelection;

async function leeAgentBudget() {
  const tools = $('#toolbudget'), steps = $('#stepbudget');
  try {
    const d = await post('/agent/budget', {tools: tools?.value.trim(), steps: steps?.value.trim()});
    if (tools) tools.value = String(d.tools);
    if (steps) steps.value = String(d.steps);
    const quick = $('#agenttoolbudget'); if (quick) quick.value = String(d.tools);
    status(d.note, 'ok');
  } catch (e) {
    status(e.message || String(e), 'err');
    try { const d = await api('/agent/budget/state');
      if (tools) tools.value = String(d.tools); if (steps) steps.value = String(d.steps);
      const quick = $('#agenttoolbudget'); if (quick) quick.value = String(d.tools);
    } catch (_) { /* leave the boxes alone rather than blank them on a second failure */ }
  }
}
window.leeAgentBudget = leeAgentBudget;

async function leeAgentQuickBudget() {
  const quick = $('#agenttoolbudget'), tools = $('#toolbudget');
  if (tools) tools.value = quick?.value || 'auto';
  await leeAgentBudget();
}
window.leeAgentQuickBudget = leeAgentQuickBudget;

async function paintAgentBudget() {
  const el = $('#agentbudgetstatus'); if (!el) return;
  try {
    const d = await api('/agent/status');
    el.textContent = `${d.tool_calls || 0} / ${d.tool_limit || '—'}`;
    el.title = `${d.tool_calls || 0} of ${d.tool_limit || 'unknown'} tool calls used this turn`;
  } catch (_) {}
}
/* This used to be called straight from the stream's `activity` handler, so a turn making a hundred
   tool calls asked the server a hundred times for a counter that reads "12 / 40". Leading edge, so
   the first call of a turn still paints at once; trailing, so the number on screen is the last one. */
const BUDGET_GAP = 1000;
let budgetTimer = 0, budgetAt = -Infinity;
function refreshAgentBudget() {
  const wait = BUDGET_GAP - (performance.now() - budgetAt);
  if (wait <= 0) { budgetAt = performance.now(); return paintAgentBudget(); }
  clearTimeout(budgetTimer);
  budgetTimer = setTimeout(() => { budgetAt = performance.now(); paintAgentBudget(); }, wait);
}

async function leeLocalMultimodal(enabled) {
  const box = $('#localmultimodal');
  const d = await post('/agent/settings', {local_multimodal: !!enabled});
  if (!d.ok && box) box.checked = !enabled;
  status(d.ok ? d.note : (d.error || 'local multimodal setting failed'), d.ok ? 'ok' : 'err');
}
window.leeLocalMultimodal = leeLocalMultimodal;

async function leeWorkspaceRepoWrites(enabled) {
  const box = $('#workspace-repo-writes');
  try {
    const d = await post('/agent/workspace-repo-writes', {enabled: !!enabled});
    if (!d.ok && box) box.checked = !enabled;
    status(d.ok ? d.note : (d.error || 'workspace repository write setting failed'), d.ok ? 'ok' : 'err');
  } catch (e) {
    if (box) box.checked = !enabled;
    status(String(e.message || e), 'err');
  }
}
window.leeWorkspaceRepoWrites = leeWorkspaceRepoWrites;

async function leeAgentReadOutside(enabled) {
  const box = $('#agent-read-outside');
  try {
    const d = await post('/agent/read-outside', {enabled: !!enabled});
    if (!d.ok && box) box.checked = !enabled;
    status(d.ok ? d.note : (d.error || 'read-outside setting failed'), d.ok ? 'ok' : 'err');
  } catch (e) {
    if (box) box.checked = !enabled;
    status(String(e.message || e), 'err');
  }
}
window.leeAgentReadOutside = leeAgentReadOutside;

/* Three-valued, so the control is a select and the recovery is putting the old value back rather
   than flipping a box. The policy is the workspace's: the model is never asked to respect it. */
/* Workspace default for the per-chat opt-ins: which groups a new conversation gets unless its
   own toggles say otherwise. The pane's buttons are painted from it on the next load. */
async function leeAgentOptin(name, on) {
  const box = $(`#agent-optin-${name}`);
  const names = ['research', 'exhash'].filter(n => n === name ? on : $(`#agent-optin-${n}`)?.checked);
  try {
    const d = await post('/agent/optin', {optin: names});
    if (!d.ok && box) box.checked = !on;
    status(d.ok ? d.note : (d.error || 'opt-in setting failed'), d.ok ? 'ok' : 'err');
  } catch (e) { if (box) box.checked = !on; status(String(e.message || e), 'err'); }
}
window.leeAgentOptin = leeAgentOptin;
/* Workspace default for how a new conversation is briefed; the select goes back on a refusal. */
async function leeAgentProfile(profile) {
  const sel = $('#agent-profile');
  try {
    const d = await post('/agent/profile', {profile});
    if (d.ok && sel) sel.dataset.was = profile; else if (sel) sel.value = sel.dataset.was || 'auto';
    status(d.ok ? d.note : (d.error || 'profile setting failed'), d.ok ? 'ok' : 'err');
  } catch (e) { if (sel) sel.value = sel.dataset.was || 'auto'; status(String(e.message || e), 'err'); }
}
window.leeAgentProfile = leeAgentProfile;
async function leeVaultPii(policy) {
  const sel = $('#vault-pii'), was = sel ? sel.dataset.was || 'redact' : 'redact';
  try {
    const d = await post('/agent/vault-pii', {pii: policy});
    if (!d.ok && sel) sel.value = was; else if (sel) sel.dataset.was = policy;
    status(d.ok ? d.note : (d.error || 'vault privacy setting failed'), d.ok ? 'ok' : 'err');
  } catch (e) {
    if (sel) sel.value = was;
    status(String(e.message || e), 'err');
  }
}
window.leeVaultPii = leeVaultPii;

async function leeSubagentWrites(enabled) {
  const box = $('#subagent-writes');
  try {
    const d = await post('/agent/subagent-writes', {enabled: !!enabled});
    if (!d.ok && box) box.checked = !enabled;
    status(d.ok ? d.note : (d.error || 'sub-agent write setting failed'), d.ok ? 'ok' : 'err');
  } catch (e) {
    if (box) box.checked = !enabled;
    status(String(e.message || e), 'err');
  }
}
window.leeSubagentWrites = leeSubagentWrites;

function leeAgentExpand() { leeRight('agent'); leeExpandPane('right'); }
window.leeAgentExpand = leeAgentExpand;

function leeRight(which) {
  const right = $('#right'); if (!right) return;
  try { localStorage.setItem('lee-right-view', which); } catch (_) {}
  right.classList.toggle('right-agent', which === 'agent');
  right.classList.toggle('right-vars', which === 'vars');
  right.classList.toggle('right-memory', which === 'memory');
  $$('.lee-righttab', right).forEach(b => {
    const active = b.dataset.right === which;
    b.classList.toggle('active', active); b.setAttribute('aria-selected', String(active));
  });
  if (which === 'agent') requestAnimationFrame(() => stickAgentLog());
  if (which === 'memory' && !lee.memoryLoaded) leeMemoryNotes();
}
window.leeRight = leeRight;

// Every memory view is fetched asynchronously into one `#memorybody`, so a slow answer must not
// paint over the view you switched to. Each switch takes the next token, and a fetch that finds the
// token moved drops its result.
let memoryViewSeq = 0;
function setMemoryView(view) {
  memoryViewSeq += 1;
  const panel = $('.lee-memory');
  if (panel) { panel.classList.remove('memory-view-notes', 'memory-view-sources', 'memory-view-topics', 'memory-view-vault'); panel.classList.add('memory-view-' + view); }
  $$('[data-memory-view]').forEach(button => button.classList.toggle('active', button.dataset.memoryView === view));
}
async function leeMemoryNotes() {
  const body = $('#memorybody'); if (!body) return;
  lee.memoryLoaded = 'loading'; leePane('right', true); leeRight('memory'); setMemoryView('notes');
  const seq = memoryViewSeq;
  body.innerHTML = '<div class="lee-memory-empty">Loading agent memory…</div>';
  try {
    const data = await api('/agent/memory'), selected = Object.fromEntries(
      Object.entries(data.selected || {}).map(([target, ids]) => [target, new Set(ids || [])]));
    if (seq !== memoryViewSeq) return;      // the vault (or another view) is on screen now
    lee.agentMemory = data; lee.memoryLoaded = 'notes';
    $('#memorystatus').textContent = `· ${data.notes.length} note${data.notes.length === 1 ? '' : 's'}`;
    if (!data.notes.length) {
      body.innerHTML = `<section class="lee-memory-notes-empty"><strong>Give the models durable context</strong>` +
        `<p>Store project conventions, decisions, preferences, and recurring instructions. You choose which model sees each note.</p>` +
        `<button class="lee-btn go" onclick="leeNewMemoryNote()">Create a memory note</button></section>`; return;
    }
    const labels = {agent: 'Agent', inline: 'Prompt', completion: 'Complete'};
    body.innerHTML = `<div class="lee-memory-notes-intro"><span>Model context</span><strong>Select exactly where each note is used.</strong></div>` +
      data.notes.map(note => `<article class="lee-memory-note-card" data-note-id="${esc(note.id)}"><button class="lee-memory-note-open" data-edit-note>` +
        `<strong>${esc(note.title || 'Untitled note')}</strong><span>${esc(String(note.text || '').replace(/\s+/g, ' ').slice(0, 180))}</span></button>` +
        `<div class="lee-memory-note-routes">${Object.entries(labels).map(([target, label]) => `<label title="Use in ${esc(data.targets[target])}">` +
          `<input type="checkbox" data-quick-target="${target}"${selected[target]?.has(String(note.id)) ? ' checked' : ''}><span>${label}</span></label>`).join('')}</div>` +
        `<button class="lee-memory-note-edit" data-edit-note aria-label="edit ${esc(note.title || 'memory note')}">edit</button></article>`).join('');
    $$('.lee-memory-note-card', body).forEach(card => {
      const note = data.notes.find(item => String(item.id) === card.dataset.noteId);
      $$('[data-edit-note]', card).forEach(button => button.onclick = () => leeAgentMemory(note.id));
      $$('[data-quick-target]', card).forEach(input => input.onchange = async () => {
        const target = input.dataset.quickTarget, id = String(note.id);
        input.checked ? selected[target].add(id) : selected[target].delete(id);
        try {
          const result = await post('/agent/memory/select', {target, ids: [...selected[target]]});
          status(`${data.targets[target]} memory updated · about ${result.tokens.toLocaleString()} tokens`, 'ok');
        } catch (e) { input.checked = !input.checked; status(e.message || String(e), 'err'); }
      });
    });
  } catch (e) { if (seq !== memoryViewSeq) return; lee.memoryLoaded = false; body.innerHTML = `<div class="lee-err">${esc(e.message || e)}</div>`; }
}
function leeNewMemoryNote(draft = {}) { leeAgentMemory('__new__', draft); }
window.leeMemoryNotes = leeMemoryNotes; window.leeNewMemoryNote = leeNewMemoryNote;

async function leeAgentMemory(focusId = '', draft = {}) {
  try {
    const data = await api('/agent/memory'), selected = Object.fromEntries(
      Object.entries(data.selected || {}).map(([target, ids]) => [target, new Set(ids || [])]));
    let active = focusId === '__new__' ? {id: '', title: draft.title || '', text: draft.text || ''} :
      (data.notes || []).find(note => String(note.id) === String(focusId)) || data.notes?.[0] || null;
    let saveNote = async () => false;
    const box = modal(`<div class="lee-mhead">Agent memory<span class="sub">durable notes with explicit model routing</span></div>` +
      `<div class="lee-memory-workbench"><aside class="lee-memory-note-list"><header><strong>Notes</strong>` +
      `<button class="lee-btn" data-new-note>New note</button></header><input class="lee-input" data-note-filter placeholder="Filter notes…">` +
      `<div data-note-list></div></aside><section class="lee-memory-note-editor"><div class="lee-memory-note-empty" data-note-empty>` +
      `<strong>No memory note selected</strong><span>Create a note for conventions, architectural decisions, preferences, or recurring context.</span>` +
      `<button class="lee-btn go" data-empty-new>Create first note</button></div><div data-note-form hidden>` +
      `<label class="lee-fieldlabel">Title<input class="lee-input" data-note-title placeholder="e.g. API compatibility rules"></label>` +
      `<div class="lee-memory-editor-head"><span>Memory note</span><small>Markdown · editable</small></div>` +
      `<div class="lee-memory-note-cm" data-note-text></div></div></section>` +
      `<aside class="lee-memory-routing"><header><strong>Use this note in</strong><span>${active?.id ? 'Changes apply to live model context immediately.' : 'Choose now; routing starts when you save.'}</span></header>` +
      `<div data-memory-targets></div><section class="lee-memory-routing-help"><strong>How routing works</strong>` +
      `<p><b>Agent</b> guides the long-running conversation and tools.</p><p><b>Prompt cells</b> guides notebook AI cells independently.</p>` +
      `<p><b>Completion</b> adds a bounded excerpt to one-shot code suggestions. Keep these notes short.</p></section>` +
      `<div class="lee-memory-budget" data-memory-budget></div></aside></div>` +
      `<div class="lee-mfoot"><button class="lee-btn warn" data-delete-note disabled>Delete note</button>` +
      `<span class="lee-spacer"></span><span class="lee-dim" data-note-status>Notes are durable; routing is saved with this workspace.</span>` +
      `<button class="lee-btn go" data-save-note disabled>Save note</button></div>`, e => {
        if ((e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === 's') {
          e.preventDefault(); e.stopPropagation(); saveNote();
        }
      }, null, {className: 'lee-agent-memory-modal', storageKey: 'agent-memory-v2'});
    const list = $('[data-note-list]', box), form = $('[data-note-form]', box), empty = $('[data-note-empty]', box);
    const title = $('[data-note-title]', box), textHost = $('[data-note-text]', box), targets = $('[data-memory-targets]', box);
    const stateView = createEditor(textHost, {doc: '', lang: 'markdown', lineNums: true, settings: {wordWrap: 'viewport'},
      placeholder: '# Context\n\nWrite only information that should influence a model…'});
    const noteText = {get value() { return LeeCM.getDoc(stateView); }, set value(value) { LeeCM.setDoc(stateView, String(value || '')); }};
    const labels = data.targets || {agent: 'Agent conversation', inline: 'Prompt cells', completion: 'Code completion'};
    let saveTimer = null, saving = null;
    const hasUnsavedChanges = () => !!active && (title.value !== (active.title || '') || noteText.value !== (active.text || ''));
    const mayLeaveNote = async () => !hasUnsavedChanges() || await confirmDialog(
      'discard unsaved note changes', 'Switch notes without saving the edits in the current note?', 'discard edits');
    const isSelected = (target, id) => selected[target]?.has(String(id));
    const selectionCount = id => Object.keys(labels).filter(target => isSelected(target, id)).length;
    const routeBadges = id => [['agent','A'],['inline','P'],['completion','C']]
      .map(([target, label]) => `<i class="${isSelected(target, id) ? 'active' : ''}" title="${esc(labels[target])}">${label}</i>`).join('');
    const paintList = (query = '') => {
      const q = query.trim().toLowerCase(), notes = (data.notes || []).filter(note =>
        !q || `${note.title} ${note.text}`.toLowerCase().includes(q));
      list.innerHTML = notes.map(note => `<button class="lee-memory-note-row${String(note.id) === String(active?.id) ? ' active' : ''}" data-note-id="${esc(note.id)}">` +
        `<span><strong>${esc(note.title || 'Untitled note')}</strong><small>${esc(String(note.text || '').replace(/\s+/g, ' ').slice(0, 110))}</small></span>` +
        `<b class="lee-memory-route-badges">${routeBadges(note.id)}</b></button>`).join('') ||
        '<div class="lee-memory-note-none">No matching notes.</div>';
      $$('[data-note-id]', list).forEach(row => row.onclick = async () => {
        const next = data.notes.find(note => String(note.id) === row.dataset.noteId);
        if (next === active || !await mayLeaveNote()) return; active = next; paint();
      });
    };
    const paintTargets = () => {
      targets.innerHTML = Object.entries(labels).map(([target, label]) => `<label class="lee-memory-target${active && isSelected(target, active.id) ? ' active' : ''}">` +
        `<input type="checkbox" data-memory-target="${target}"${active?.id && isSelected(target, active.id) ? ' checked' : ''}>` +
        `<span><strong>${esc(label)}</strong><small>${target === 'agent' ? 'conversation + tools' : target === 'inline' ? 'notebook prompt cells' : 'one-shot suggestions'}</small></span></label>`).join('');
      $$('[data-memory-target]', targets).forEach(input => input.onchange = async () => {
        const target = input.dataset.memoryTarget, id = String(active.id);
        if (!id) { $('[data-note-status]', box).textContent = 'Routing will activate when you save this note.'; paintBudget(); return; }
        input.checked ? selected[target].add(id) : selected[target].delete(id);
        try {
          const result = await post('/agent/memory/select', {target, ids: [...selected[target]]});
          $('[data-note-status]', box).textContent = `${labels[target]} updated · about ${result.tokens.toLocaleString()} context tokens`;
          paintList($('[data-note-filter]', box).value); paintTargets(); paintBudget();
        } catch (e) { input.checked = !input.checked; status(e.message || String(e), 'err'); }
      });
    };
    const paintBudget = () => {
      if (!active) { $('[data-memory-budget]', box).textContent = 'Select a note to route it.'; return; }
      const tokens = Math.max(1, Math.ceil(noteText.value.length / 4));
      $('[data-memory-budget]', box).innerHTML = active.id
        ? `<strong>~${tokens.toLocaleString()} tokens</strong><span>this note · active on ${selectionCount(active.id)} of 3 surfaces</span>`
        : `<strong>Unsaved note</strong><span>Save it before adding it to model context.</span>`;
    };
    const paint = () => {
      empty.hidden = !!active; form.hidden = !active;
      $('[data-save-note]', box).disabled = !active; $('[data-delete-note]', box).disabled = !active;
      if (active) { title.value = active.title || ''; noteText.value = active.text || ''; }
      paintList($('[data-note-filter]', box).value); paintTargets(); paintBudget();
    };
    const newNote = async () => { if (!await mayLeaveNote()) return; active = {id: '', title: '', text: ''}; paint(); title.focus(); };
    $('[data-new-note]', box).onclick = newNote; $('[data-empty-new]', box).onclick = newNote;
    $('[data-note-filter]', box).oninput = e => paintList(e.target.value);
    const button = $('[data-save-note]', box), noteStatus = $('[data-note-status]', box);
    saveNote = async () => {
      clearTimeout(saveTimer);
      if (!active || !hasUnsavedChanges()) return true;
      if (saving) return saving;
      const oldId = String(active.id || ''), nextTitle = title.value, nextText = noteText.value;
      const requestedTargets = $$('[data-memory-target]:checked', targets).map(input => input.dataset.memoryTarget);
      button.disabled = true; button.textContent = 'Saving…'; noteStatus.textContent = 'Saving changes…';
      saving = post('/agent/memory/save', {id: oldId, title: nextTitle, text: nextText, targets: requestedTargets}).then(result => {
        const id = String(result.id || oldId), previous = active;
        active = {...previous, id, title: nextTitle, text: nextText};
        const at = data.notes.findIndex(note => String(note.id) === oldId);
        if (at >= 0) data.notes[at] = active; else data.notes.push(active);
        for (const target of Object.keys(selected)) { selected[target].delete(oldId); if (requestedTargets.includes(target)) selected[target].add(id); }
        noteStatus.textContent = 'Saved'; button.textContent = 'Save note'; paintList($('[data-note-filter]', box).value); paintTargets(); paintBudget();
        lee.memoryLoaded = false; status(oldId ? 'memory note updated' : 'memory note created', 'ok'); return true;
      }).catch(e => {
        noteStatus.textContent = `Save failed · ${e.message || e}`; button.textContent = 'Retry save'; status(e.message || String(e), 'err'); return false;
      }).finally(() => { saving = null; button.disabled = !active; });
      return saving;
    };
    const markDirty = () => {
      noteStatus.textContent = 'Unsaved changes'; paintBudget(); clearTimeout(saveTimer);
      if (noteText.value.trim()) saveTimer = setTimeout(saveNote, 700);
    };
    title.oninput = markDirty;
    stateView.dom.addEventListener('input', markDirty);
    button.onclick = saveNote;
    box.beforeClose = async () => { clearTimeout(saveTimer); if (saving) await saving; return !hasUnsavedChanges() || await saveNote(); };
    $('[data-delete-note]', box).onclick = async () => {
      if (!active?.id || !await confirmDialog('delete memory note', `Delete “${active.title || 'Untitled note'}” from memory and every model route?`, 'delete')) return;
      await post('/agent/memory/delete', {id: active.id}); box.remove(); lee.memoryLoaded = false; status('memory note deleted', 'ok'); leeMemoryNotes();
    };
    paint();
  } catch (e) { status(e.message || String(e), 'err'); }
}
window.leeAgentMemory = leeAgentMemory;

function memoryRows(rows, kind = 'doc') {
  return rows.map((row, i) => {
    const title = row.breadcrumb || row.title || row.label || row.source || 'Untitled';
    const detail = row.source || row.summary || row.note || `${row.size || row.nchunks || 0} items`;
    const excerpt = (row.snippets || [])[0] || row.text || '';
    return `<button class="lee-memory-${kind}" data-i="${i}"><span class="lee-memory-index">${String(i + 1).padStart(2, '0')}</span>` +
      `<span class="lee-memory-copy"><strong>${esc(title)}</strong><small>${esc(detail)}</small>` +
      `${excerpt ? `<p>${esc(String(excerpt).replace(/\s+/g, ' ').slice(0, 220))}</p>` : ''}</span>` +
      `<span class="lee-memory-kind">${esc(row.kind || (kind === 'hit' ? 'section' : kind))}</span></button>`;
  }).join('');
}
async function leeMemoryHome() {
  const body = $('#memorybody'); if (!body) return;
  lee.memoryLoaded = 'loading'; leePane('right', true); leeRight('memory'); setMemoryView('sources');
  body.innerHTML = '<div class="lee-memory-empty">Opening durable memory…</div>';
  try {
    const d = await api('/memory/info'); lee.memoryLoaded = true; lee.memoryDocs = d.items || [];
    $('#memorystatus').textContent = `· ${d.documents} docs · ${d.nodes} sections`;
    body.innerHTML = lee.memoryDocs.length ? memoryRows(lee.memoryDocs) :
      '<div class="lee-memory-empty">Pages you read and research will be indexed here automatically.</div>';
    $$('.lee-memory-doc', body).forEach((row, i) => row.onclick = () => leeMemoryTree(lee.memoryDocs[i].id));
  } catch (e) { lee.memoryLoaded = false; body.innerHTML = `<div class="lee-err">${esc(e.message || e)}</div>`; }
}
async function leeMemoryPurge() {
  let docs = lee.memoryDocs;
  if (!docs) docs = (await api('/memory/info')).items || [];
  if (!docs.length) return status('memory is already empty', 'info');
  const m = modal(`<div class="lee-mhead">Purge memory<span class="sub">remove bad or irrelevant sources</span></div>` +
    `<div class="lee-memory-purge-list">${docs.map((doc, i) => `<label><input type="checkbox" value="${esc(doc.id)}">` +
      `<span><strong>${esc(doc.title)}</strong><small>${esc(doc.source || doc.kind || '')}</small></span></label>`).join('')}</div>` +
    `<div class="lee-mfoot"><button class="lee-btn warn" data-selected>purge selected</button>` +
    `<span class="lee-spacer"></span><button class="lee-btn warn" data-all>purge everything</button></div>`);
  $('[data-selected]', m).onclick = async () => {
    const ids = $$('input:checked', m).map(x => x.value);
    if (!ids.length) return status('select at least one source to purge', 'err');
    if (!await confirmDialog('purge selected memory', `Remove ${ids.length} document${ids.length === 1 ? '' : 's'} and all indexed sections?`, 'purge')) return;
    await post('/memory/purge', {ids}); m.remove(); lee.memoryLoaded = false; lee.memoryDocs = null; leeMemoryHome();
  };
  $('[data-all]', m).onclick = async () => {
    if (!await confirmDialog('purge all research memory', `Remove all ${docs.length} documents, trees, chunks and vectors?`, 'purge')) return;
    await post('/memory/purge', {ids: null}); m.remove(); lee.memoryLoaded = false; lee.memoryDocs = null; leeMemoryHome();
  };
}
async function leeMemorySearch() {
  const input = $('#memoryquery'), body = $('#memorybody'), q = input?.value.trim(); if (!q || !body) return;
  body.innerHTML = '<div class="lee-memory-empty">Searching remembered sections…</div>';
  try {
    const d = await api('/memory/search?q=' + encodeURIComponent(q)); lee.memoryHits = d.results || [];
    $('#memorystatus').textContent = `· ${d.note || ''}`;
    body.innerHTML = lee.memoryHits.length ? memoryRows(lee.memoryHits, 'hit') : '<div class="lee-memory-empty">Nothing remembered matches this query.</div>';
    $$('.lee-memory-hit', body).forEach((row, i) => row.onclick = () => leeMemoryRead(lee.memoryHits[i].node_id));
  } catch (e) { body.innerHTML = `<div class="lee-err">${esc(e.message || e)}</div>`; }
}
async function leeMemoryTree(doc) {
  const body = $('#memorybody'); if (!body) return;
  body.innerHTML = '<div class="lee-memory-empty">Reading document structure…</div>';
  const d = await api('/memory/toc?doc=' + encodeURIComponent(doc || ''));
  const flatten = (node, depth = 0, out = []) => {
    if (node) { out.push({...node, depth}); (node.children || []).forEach(child => flatten(child, depth + 1, out)); }
    return out;
  };
  const document = (d.documents || [])[0], rows = document ? flatten(document.tree) : [];
  body.innerHTML = `<div class="lee-memory-tree-actions"><button class="lee-btn lee-memory-back" onclick="leeMemoryHome()">Back to memory</button>` +
    `${document ? '<button class="lee-btn warn" data-forget>Forget document</button>' : ''}</div>` +
    `<div class="lee-memory-breadcrumb">${esc(document?.title || 'Document tree')}</div>` +
    (rows.length ? rows.map((row, i) => `<button class="lee-memory-hit lee-memory-tree" style="--depth:${row.depth}" data-node="${esc(row.id)}">` +
      `<span class="lee-memory-index">${String(i + 1).padStart(2, '0')}</span><span class="lee-memory-copy"><strong>${esc(row.title)}</strong>` +
      `<small>${esc(row.summary || `${row.nchunks || 0} chunks`)}</small></span><span class="lee-memory-kind">L${row.level}</span></button>`).join('') :
      '<div class="lee-memory-empty">No section tree is available.</div>');
  $$('[data-node]', body).forEach(row => row.onclick = () => leeMemoryRead(row.dataset.node));
  const forget = $('[data-forget]', body);
  if (forget) forget.onclick = async () => {
    if (!await confirmDialog('forget research document', `Remove ${document.title} and all of its remembered sections?`, 'forget')) return;
    await post('/memory/forget', {id: document.doc_id}); lee.memoryLoaded = false; leeMemoryHome();
  };
}
async function leeMemoryRead(node) {
  if (!node) return;
  const body = $('#memorybody'); body.innerHTML = '<div class="lee-memory-empty">Assembling the section…</div>';
  const d = await api('/memory/read?node=' + encodeURIComponent(node)), section = d.section || {};
  body.innerHTML = `<button class="lee-btn lee-memory-back" onclick="leeMemoryHome()">Back to memory</button>` +
    `<div class="lee-memory-breadcrumb">${esc(section.breadcrumb || section.title || node)}</div><article class="lee-memory-reader"></article>`;
  renderMarkdown($('.lee-memory-reader', body), section.text || 'No section text was retained.');
}
async function leeMemoryTopics() {
  const body = $('#memorybody'); if (!body) return;
  lee.memoryLoaded = 'loading'; leePane('right', true); leeRight('memory'); setMemoryView('topics'); body.innerHTML = '<div class="lee-memory-empty">Clustering remembered research…</div>';
  const d = await api('/memory/clusters'); lee.memoryTopics = d.clusters || [];
  $('#memorystatus').textContent = `· ${d.note || 'topics'}`;
  body.innerHTML = lee.memoryTopics.length ? memoryRows(lee.memoryTopics, 'topic') : `<div class="lee-memory-empty">${esc(d.note || 'Not enough remembered material to form topics.')}</div>`;
  $$('.lee-memory-topic', body).forEach((row, i) => row.onclick = () => {
    const topic = lee.memoryTopics[i], members = topic.members || [];
    body.innerHTML = `<button class="lee-btn lee-memory-back" onclick="leeMemoryTopics()">Back to topics</button>` +
      `<div class="lee-memory-breadcrumb">${esc(topic.label || 'Topic')} · ${topic.size || members.length} sections</div>` +
      (members.length ? memoryRows(members, 'hit') : '<div class="lee-memory-empty">No representative sections.</div>');
    $$('.lee-memory-hit', body).forEach((member, at) => member.onclick = () => leeMemoryRead(members[at].node_id));
  });
}
window.leeMemoryHome = leeMemoryHome; window.leeMemorySearch = leeMemorySearch; window.leeMemoryPurge = leeMemoryPurge;
window.leeMemoryTree = leeMemoryTree; window.leeMemoryRead = leeMemoryRead; window.leeMemoryTopics = leeMemoryTopics;

/* Following a feed is sticking to its bottom; it is not dragging a reader back down. Every paint in
   this pane used to write `scrollTop = scrollHeight` unconditionally, and to write it *before* the
   markdown render it had just asked for had landed, so the pane was measured short, jumped when the
   text arrived, and took the reader with it however far up they had scrolled to read.

   Stickiness is sampled from the reader's own scrolling: once they leave the bottom nothing the
   stream paints moves them, and scrolling back down opts in again. `force` is for the moves that
   are the reader's, not the stream's: taking the live pane back from History, and sending a turn. */
const BOTTOM_SLACK = 60;
const nearAgentBottom = log =>
  !log.clientHeight || log.scrollHeight - log.scrollTop - log.clientHeight <= BOTTOM_SLACK;
function stickAgentLog(log, force = false) {
  log = log || $('#agentlog'); if (!log) return;
  if (!log._leeStickBound) {
    log._leeStickBound = true; log._leeStick = true;
    log.addEventListener('scroll', () => { log._leeStick = nearAgentBottom(log); }, {passive: true});
  }
  if (force) log._leeStick = true;
  if (log._leeStick) log.scrollTop = log.scrollHeight;
}
/* A render lands a frame or more after the call that asked for it, so the pane is re-stuck when the
   content is actually there. `renderMarkdown` announces every one of its renders.

   Only the reply prose, not every render inside the pane: a checkpoint's proposal editor and the
   agent-state box re-render as a person types in them, and re-pinning the log to the bottom on
   every keystroke is the exact thing this change is here to stop. */
document.addEventListener('lee-markdown-rendered', e => {
  const log = $('#agentlog'), el = e.target;
  if (!log || !log.contains(el)) return;
  if (!el.closest('.lee-agent-turn') || el.closest('.lee-approval, .lee-proposal')) return;
  stickAgentLog(log);
});

/* The live pane is set aside as its own nodes, not as `innerHTML`. Serialising a long conversation
   and parsing it back paid for the whole log on every History toggle, and threw away every code
   surface the replies had mounted: the fragment keeps them alive and costs one pointer.
   `null` means "the live pane is whatever is on screen", which is the case until History takes it. */
function rememberAgentLive() {
  const log = $('#agentlog');
  if (!log || (lee.agentView && lee.agentView !== 'live')) return;
  const held = document.createDocumentFragment();
  held.append(...log.childNodes);
  lee.agentLive = held;
}
function restoreAgentLive() {
  const log = $('#agentlog'); if (!log) return;
  log.replaceChildren(lee.agentLive || document.createDocumentFragment());
  lee.agentLive = null; lee.agentView = 'live';
  $('#agenthistory')?.classList.remove('active');
  stickAgentLog(log, true);
}
function userMessage(text) {
  const raw = String(text || '').trim(), long = raw.length > 900 || raw.split('\n').length > 14;
  const card = document.createElement('section'); card.className = 'lee-user-message';
  const head = document.createElement('header');
  head.innerHTML = '<strong>You</strong><span>request</span>'; card.appendChild(head);
  if (!long) {
    const body = document.createElement('div'); body.className = 'lee-user-message-body';
    body.textContent = raw; card.appendChild(body); return card;
  }
  const lines = raw.split('\n');
  const preview = lines.slice(0, 6).join('\n').slice(0, 620).trimEnd();
  const body = document.createElement('div'); body.className = 'lee-user-message-body preview';
  body.textContent = preview + (preview.length < raw.length ? '\n…' : ''); card.appendChild(body);
  const more = document.createElement('details'); more.className = 'lee-user-message-more';
  more.innerHTML = `<summary>Show full request <span>${raw.length.toLocaleString()} characters · ${lines.length} lines</span>` +
    `<i class="lee-agent-step-chevron" aria-hidden="true"></i></summary><pre></pre>`;
  more.querySelector('pre').textContent = raw; card.appendChild(more);
  return card;
}
function usageMeta(usage, label = '', model = '') {
  if (!usage && !label) return null;
  const u = usage || {}, parts = [];
  if (Number(u.total)) parts.push(`${Number(u.total).toLocaleString()} tokens`);
  if (Number(u.input)) parts.push(`${Number(u.input).toLocaleString()} input`);
  if (Number(u.output)) parts.push(`${Number(u.output).toLocaleString()} output`);
  if (Number(u.cached)) parts.push(`${Number(u.cached).toLocaleString()} cached`);
  if (Number(u.reasoning)) parts.push(`${Number(u.reasoning).toLocaleString()} reasoning`);
  if (Number(u.cost)) parts.push(`$${Number(u.cost).toFixed(4)}`);
  if (!parts.length && label) parts.push(label);
  if (model || u.model) parts.push(String(model || u.model).split('/').pop());
  const el = document.createElement('footer'); el.className = 'lee-turn-usage';
  el.setAttribute('aria-label', 'Token usage and estimated cost for this turn');
  el.innerHTML = `<span class="lee-turn-usage-mark" aria-hidden="true">∑</span>` + parts.map((part, i) => `<span${i === parts.length - 1 ? ' class="model"' : ''}>${esc(part)}</span>`).join('');
  return el;
}

/* One turn is one card, so what has been read can be folded away. Everything a turn paints goes
   in its body: the live path used to append the prompt, the progress strip, the timeline and the
   closing diffs as flat siblings of the log, which is why `markTurnUndone` had to guess a turn's
   extent by walking to the next `.lee-user-message`. */
/* Scoped to whatever session was painted, which is not always the live thread: history view paints
   another conversation's turns while `lee.agentThread` still names the live one. */
const foldScope = () => $('#agentlog')?.dataset.foldScope || lee.agentThread || 'default';
const foldKey = () => `lee-agent-folded:${foldScope()}`;
const foldedTurns = () => { try { return new Set(JSON.parse(localStorage.getItem(foldKey()) || '[]')); } catch { return new Set(); } };
const saveFolded = set => { try { localStorage.setItem(foldKey(), JSON.stringify([...set].slice(-400))); } catch {} };

function agentTurnCard({prompt = '', model = '', route = '', turnId = ''} = {}) {
  const card = document.createElement('article'); card.className = 'lee-agent-turn';
  if (turnId) card.dataset.turn = turnId;
  const meta = [model, route].filter(Boolean).join(' · ');
  card.innerHTML = `<header class="lee-agent-turn-head"><button class="lee-agent-turn-fold" type="button"` +
    ` aria-expanded="true" title="fold this turn. Hold alt for every turn">` +
    `<i class="lee-agent-step-chevron" aria-hidden="true"></i></button>` +
    `<span class="lee-agent-turn-title"></span><span class="lee-agent-turn-meta">${esc(meta)}</span></header>` +
    `<div class="lee-agent-turn-body"></div>`;
  // textContent, not the template: a prompt is whatever was typed
  $('.lee-agent-turn-title', card).textContent = String(prompt).replace(/\s+/g, ' ').trim() || '(no prompt)';
  return card;
}
const turnBody = card => card && $('.lee-agent-turn-body', card);
/* A checkpoint the agent is blocked on must never sit behind a fold: its buttons and its ↵ / E / S
   keys are the only way the run continues, and a folded body cannot be focused or clicked. */
const turnAwaitingApproval = card => !!$('.lee-approval.proposed', card);
const unfoldForApproval = node => foldAgentTurn(node?.closest?.('.lee-agent-turn'), false);

function foldAgentTurn(card, folded) {
  if (!card || (folded && turnAwaitingApproval(card))) return;
  card.classList.toggle('folded', folded);
  $('.lee-agent-turn-fold', card)?.setAttribute('aria-expanded', String(!folded));
  turnBody(card)?.setAttribute('aria-hidden', String(folded));
  const id = card.dataset.turn; if (!id) return;
  const set = foldedTurns(); folded ? set.add(id) : set.delete(id); saveFolded(set);
}
const agentTurnCards = () => $$('.lee-agent-turn', $('#agentlog') || document);
function foldAgentTurns(folded) { for (const card of agentTurnCards()) foldAgentTurn(card, folded); }
/* What has been answered is not what is being read. A conversation of any length is mostly turns
   already dealt with, so every one before the newest is folded away: on a paint, and again when the
   next turn begins. A turn holding a checkpoint is never folded, because `foldAgentTurn` refuses. */
function foldOlderTurns(log, keep = 1) {
  const cards = $$('.lee-agent-turn', log || $('#agentlog') || document);
  cards.slice(0, Math.max(0, cards.length - keep)).forEach(card => foldAgentTurn(card, true));
}
/* Folding hides a turn from layout; it does not free it. Every turn of a session stays in the live
   pane holding its rendered replies and one CodeMirror view per code block in them, so a long day's
   conversation is hundreds of live views the pane carries through every paint. The pane keeps the
   last `LIVE_TURNS` and History holds the rest, which is where a conversation already lives.

   A turn holding a checkpoint is never dropped: its buttons are the only way that run continues. */
const LIVE_TURNS = 30;
function trimAgentLog(log, keep = LIVE_TURNS) {
  log = log || $('#agentlog');
  if (!log || (lee.agentView && lee.agentView !== 'live')) return 0;
  const cards = $$('.lee-agent-turn', log);
  let dropped = 0;
  for (const card of cards.slice(0, Math.max(0, cards.length - keep))) {
    if (turnAwaitingApproval(card)) continue;
    dropCodeSurfaces(card); card.remove(); dropped += 1;
  }
  if (!dropped) return 0;
  for (const [id, node] of approvalCards) if (!node.isConnected) approvalCards.delete(id);
  if (!$('.lee-agent-trimmed', log)) {
    const note = document.createElement('div'); note.className = 'lee-agent-trimmed';
    note.textContent = 'Earlier turns in this conversation are in History.';
    log.prepend(note);
  }
  return dropped;
}
/* The newest turn is the one being read, so it is never folded from storage: a turn folded before
   a resume would otherwise hide the answer a person came back for. */
function applyStoredFolds(log) {
  const cards = $$('.lee-agent-turn', log), stored = foldedTurns();
  cards.forEach((card, i) => { if (i < cards.length - 1 && stored.has(card.dataset.turn)) foldAgentTurn(card, true); });
}
/* `renderTurns` paints durable turns only, so on a resync the turn in flight is appended after it
   has already decided which card is newest. Re-applied once that card exists. */
const refoldAfter = log => applyStoredFolds(log);
/* One listener on the log, bound from `initAgentComposer` rather than from a paint: a conversation
   with no turns paints nothing, and the log element itself outlives every repaint. */
function bindAgentTurnFolds(log) {
  if (!log || log._leeFoldsBound) return;
  log._leeFoldsBound = true;
  log.addEventListener('click', e => {
    const button = e.target.closest?.('.lee-agent-turn-fold'); if (!button) return;
    const card = button.closest('.lee-agent-turn'), folded = !card.classList.contains('folded');
    if (e.altKey) foldAgentTurns(folded); else foldAgentTurn(card, folded);
  });
}
const latestAgentTurn = () => agentTurnCards().at(-1);
/* the turn being read: whichever card holds focus, or the newest, which is where focus is when it
   is in the composer. Only for what a person aimed at; anything the server sends goes to the
   newest, or a checkpoint would land in whichever old turn happened to hold focus */
const currentAgentTurn = () => document.activeElement?.closest?.('.lee-agent-turn') || latestAgentTurn();

function renderTurns(log, turns, heading, fold = true) {
  if (heading) log.insertAdjacentHTML('beforeend', `<div class="lee-vgroup">${esc(heading)}</div>`);
  for (const turn of (turns || [])) {
    const card = agentTurnCard({prompt: turn.prompt, model: turn.model, route: turn.plan?.route || 'direct',
                               turnId: turn.turn_id || ''});
    const item = turnBody(card);
    item.appendChild(userMessage(turn.prompt));
    let closing = null;
    if ((turn.timeline || []).length) {
      const root = document.createElement('div'); root.className = 'lee-agent-timeline'; item.appendChild(root);
      const paint = agentTimeline(root);
      const paintActivity = part => {
        paint.activity(part.data);
        for (const child of part.children || []) paintActivity(child);
      };
      for (const part of reduceAgentTimeline(turn.timeline)) {
        if (part.kind === 'prose') closing = paint.chunk(part.text);
        else if (part.kind === 'activity') paintActivity(part);
        // what the person said mid-turn, in the place they said it
        else if (part.kind === 'steer' && part.data?.text) paint.append(userMessage(part.data.text));
      }
      closing = closing || root;
    } else {
      if ((turn.activity || []).length) {
        const steps = document.createElement('div'); steps.className = 'lee-agent-steps';
        for (const activity of turn.activity) {
          const row = document.createElement('details'); renderAgentStep(row, activity); steps.appendChild(row);
        }
        item.appendChild(steps);
      }
      const reply = document.createElement('div'); reply.className = 'lee-reply'; item.appendChild(reply);
      renderMarkdown(reply, turn.reply || '');
      closing = reply;
    }
    /* The revision bar used to be added by the live `done` handler alone, so undo, restore and
       edit-what-the-agent-remembers vanished on every history toggle, resume, thread switch and
       resync. It is painted from the turn record here, and the server says whether the operations
       behind it can still be reached in this process. */
    addResponseRevision(closing, turn.turn_id, turn.reply || '', turn.capabilities || {});
    const usage = usageMeta(turn.usage, turn.usage_label, turn.model); if (usage) item.appendChild(usage);
    log.appendChild(card);
  }
  applyStoredFolds(log);
  if (fold) foldOlderTurns(log);
}
/* A summarised title arrives as `Title: Ramabana CLI ASCII`, quotes and all, and stored ones keep
   the prefix after the storage point is fixed, so every display cleans it. */
const titleText = t => String(t || '').replace(/\s+/g, ' ').trim()
  .replace(/^title\s*:\s*/i, '').replace(/^["'“”‘’]+|["'“”‘’]+$/g, '').trim();
const sessionTime = s => s.started ? new Date(s.started * 1000).toLocaleString() : s.id.replace(/^agent_/, '');
/* `/agent/history` lists conversations without their turns, since Leela and the CLI share one log.
   The turns of the one being opened come from here, and `count` is what the list knows about the
   rest. */
const sessionTurns = async id => {
  if (!id) return [];
  try { return (await api('/agent/history/session?id=' + encodeURIComponent(id))).turns || []; }
  catch (e) { status(String(e.message || e), 'err'); return []; }
};
/* The three preferences this pane keeps, each of which used to live only in `localStorage` and so
   came back at its default whenever the app was launched on a different port.

   settings.json answers with a default for every key, so `lee.prefs` cannot say whether a value was
   chosen, and `prefAdopt` reads that default as a choice and migrates nothing. `origins` names the
   layer each key came from, and only `default` means nobody has saved one. The control's own
   default is saved where it differs from settings', which is how the history filter stays on for
   someone who never asked for it off. */
const AGENT_PREFS = {notify: ['lee-agent-notify', v => v === 'on', false],
                     reasoning: ['lee-agent-reasoning', v => v, ''],
                     historyLeelaOnly: ['leeHistoryLeelaOnly', v => v !== '0', true]};
async function adoptAgentPrefs() {
  for (const [key, [legacy, parse, dflt]] of Object.entries(AGENT_PREFS)) {
    if ((lee.settingsMeta?.origins?.agent?.[key] || 'default') !== 'default') continue;
    const old = localStorage.getItem(legacy), value = old === null ? dflt : parse(old);
    if (value !== lee.prefs?.agent?.[key]) await prefSet('agent', key, value);
  }
}
let agentPrefsAdopted;
// Once per session, and not before `loadSettings` has said what is already saved.
const agentPrefsReady = () =>
  lee.settingsMeta ? (agentPrefsAdopted ||= adoptAgentPrefs()) : Promise.resolve();
/* Leela and the ramabana CLI append to one log, and only Leela marks the sessions it started, so
   anything unmarked reads as the CLI's, including Leela's history from before the mark. */
/* Checked unless it has been turned off: one log holds both, most of it is the CLI's, and the
   list a person opens is their own work. Asking the server means the CLI's are not grouped and
   shipped only to be filtered out here. */
const leelaOnly = () => prefGet('agent', 'historyLeelaOnly', true);
const shownSessions = groups => leelaOnly() ? groups.filter(s => s.app === 'leela') : groups;
async function historyGroups() {
  await agentPrefsReady();
  const d = await api('/agent/history' + (leelaOnly() ? '' : '?everything=1'));
  lee.agentHistoryHidden = d.hidden || 0;
  return d.sessions || [];
}
/* The inline panel's telemetry, in a surface of its own. It used to be appended to the bottom of a
   conversation in the agent's History view, which is a different feature's transcript: the only way
   to reach it was to open a conversation nobody wanted, and the two preferences that decide whether
   any of this is recorded lived there too. A `stale` is neither an accept nor a reject, so it is
   named rather than counted. */
const COMPLETION_VERDICT = {replace: 'accepted', discard: 'rejected', stale: 'selection moved',
                            abandon: 'abandoned', error: 'model failed', ask: 'still open',
                            reply: 'answered, no verdict'};
const COMPLETION_CODE = {kept: '', 'not kept': 'the code was not kept for this one',
                         withheld: 'turn on "keep the code" to read the selection and the suggestion'};
/* Two causes, one shape: nothing carried an id before the browser began minting them, and an ask
   can fall outside the window this list covers while its verdict stays inside it. */
const COMPLETION_ORPHAN = 'not joined to its ask: recorded before asks carried an id, or its ask is outside this window';
const percent = r => r === null || r === undefined ? '—' : Math.round(r * 100) + '%';
const completionWhen = at => at ? new Date(at * 1000).toLocaleString() : '';

function completionRow(r) {
  const row = document.createElement('details'); row.className = 'lee-completion-row';
  row.dataset.completion = r.kind || '';
  row.innerHTML = `<summary><strong></strong><span>${esc(r.model || 'unknown')}` +
    `${r.lang ? ' · ' + esc(r.lang) : ''}${r.ms ? ' · ' + esc(r.ms) + 'ms' : ''}` +
    `${r.at ? ' · ' + esc(completionWhen(r.at)) : ''}</span>` +
    `<em>${esc(COMPLETION_VERDICT[r.kind] || r.kind || '')}</em></summary>` +
    `<div class="lee-completion-detail"></div>`;
  // textContent throughout: an instruction and a suggestion are whatever the person and the model wrote
  $('summary strong', row).textContent = r.instruction || (r.orphan ? '(unlinked event)' : '(no instruction)');
  const detail = $('.lee-completion-detail', row);
  if (r.path) { const p = document.createElement('div'); p.className = 'lee-dim'; p.textContent = r.path; detail.appendChild(p); }
  const pair = (label, text) => {
    const box = document.createElement('div'); box.className = 'lee-completion-code';
    const h = document.createElement('h5'); h.textContent = label; box.appendChild(h);
    const pre = document.createElement('pre'); pre.textContent = text; box.appendChild(pre);
    detail.appendChild(box);
  };
  if (r.text) pair('selection', r.text);
  if (r.reply) pair('suggestion', r.reply);
  for (const note of [COMPLETION_CODE[r.code], r.orphan ? COMPLETION_ORPHAN : ''].filter(Boolean)) {
    const n = document.createElement('div'); n.className = 'lee-dim'; n.textContent = note; detail.appendChild(n);
  }
  return row;
}

async function showCompletions() {
  const m = modal(`<div class="lee-mhead">Inline completions<span class="sub">what you asked, what came back, and what you did with it</span></div>` +
    `<div class="lee-completions" id="completionsbody"><div class="lee-dim">reading the log…</div></div>`,
    null, null, {className: 'lee-completions-modal', storageKey: 'completions'});
  await paintCompletions(m);
  return m;
}

/* A paint in flight when a purge lands would repaint the selections the purge deleted, so each one
   takes a ticket and only the newest writes. */
let completionsPaint = 0;
async function paintCompletions(m) {
  const body = $('#completionsbody', m); if (!body) return;
  const mine = ++completionsPaint;
  let d;
  try { d = await api('/ai/completions?days=30'); }
  catch (e) {
    if (mine === completionsPaint) body.innerHTML = `<div class="lee-dim">completions unavailable: ${esc(e.message || e)}</div>`;
    return;
  }
  if (mine !== completionsPaint) return;
  const s = d.summary || {}, events = d.events || [];
  body.innerHTML = `<div class="lee-weight-group"><h4>What Leela keeps about your completions</h4><div class="lee-weight-row">` +
    `<label>keep<select class="lee-select" data-completion-pref="telemetry">` +
    ['on', 'off'].map(v => `<option value="${v}"${v === d.telemetry ? ' selected' : ''}>${v}</option>`).join('') +
    `</select></label>` +
    `<label class="lee-settings-toggle"><input type="checkbox" data-completion-pref="snippets"` +
    `${d.snippets ? ' checked' : ''}><span>keep the code</span></label>` +
    `<button class="lee-btn" data-completions-purge type="button">purge log</button></div>` +
    `<div class="lee-dim lee-weight-note">${esc(s.asks || 0)} asked · ${esc(s.answered || 0)} answered · ` +
    `${esc(s.replaced || 0)} accepted · ${esc(s.discarded || 0)} rejected · accepted ${percent(s.accept_rate)}` +
    `${d.telemetry === 'off' ? ' · recording is off, so nothing new is kept' : ''}` +
    `${d.snippets ? '' : ' · the code is not being kept, so rows show the question and the verdict only'}` +
    `<br>${esc(d.dir || '')}</div></div>` +
    `<div class="lee-weight-group"><h4>Accepted per model</h4><div class="lee-completion-models">` +
    ((s.models || []).map(x => `<div data-completion-model="${esc(x.model)}"><strong>${esc(x.model)}</strong>` +
      `<span>${esc(x.replaced || 0)} accepted · ${esc(x.discarded || 0)} rejected` +
      `${x.stale ? ' · ' + esc(x.stale) + ' stale' : ''}</span><em>${percent(x.accept_rate)}</em></div>`).join('') ||
      `<div class="lee-dim">nothing decided yet</div>`) + `</div></div>` +
    `<div class="lee-weight-group"><h4>Every ask</h4><div class="lee-completion-log"></div></div>`;
  const log = $('.lee-completion-log', body);
  if (!events.length) log.innerHTML = `<div class="lee-dim">nothing recorded yet</div>`;
  else events.forEach(r => log.appendChild(completionRow(r)));
  $$('[data-completion-pref]', body).forEach(el => el.onchange = async () => {
    const value = el.type === 'checkbox' ? el.checked : el.value;
    try {
      await post('/settings/save', {scope: 'user', section: 'completions',
                                    values: {[el.dataset.completionPref]: value}});
      await paintCompletions(m);   // `snippets` decides what the route will hand over at all
    } catch (e) { status(e.message || String(e), 'err'); }
  });
  $('[data-completions-purge]', body).onclick = async () => {
    if (!await confirmDialog('Purge the completion log',
        'Delete every recorded completion event? The conversations are not touched.', 'purge')) return;
    const out = await post('/ai/completions/purge', {});
    status(`removed ${out.removed} completion event file${out.removed === 1 ? '' : 's'}`, 'ok');
    // repainted from the server, never from anything held here: the point of a purge is that the
    // selections and suggestions are gone, and a cached copy on the page would outlive them
    await paintCompletions(m);
  };
}
window.showCompletions = showCompletions;

async function showHistorySession(group, groups) {
  const log = $('#agentlog'); if (!log) return; dropCodeSurfaces(log); log.innerHTML = ''; approvalCards.clear();
  log.dataset.foldScope = group?.id || '';   // these turns are that session's, whatever thread is live
  const index = document.createElement('nav'); index.className = 'lee-history-index';
  /* A conversation is known by what it was about, so its name is the whole option. The time
     identifies one that has no name yet, which is every conversation before its first turn
     finished. */
  const all = groups || [], shown = shownSessions(all);
  const hidden = (all.length - shown.length) || lee.agentHistoryHidden || 0;
  const options = shown.map(s =>
    `<option value="${esc(s.id)}"${s.id === group?.id ? ' selected' : ''}>` +
    `${esc(titleText(s.title) || sessionTime(s))}</option>`).join('');
  const turns = group ? await sessionTurns(group.id) : [];
  const resumable = !!group && !group.id.startsWith('legacy-') && turns.length > 0;
  index.innerHTML = `<div class="lee-history-heading"><strong>History</strong>` +
    `<span>one continuous model context per session</span></div>` +
    `<select class="lee-select lee-history-select" aria-label="agent history session">${options}</select>` +
    `<label class="lee-history-filter" title="Hide conversations this Leela did not start. History from before this filter existed is unmarked and hides with them.">` +
    `<input type="checkbox" class="lee-history-leelaonly"${leelaOnly() ? ' checked' : ''}> Leela only` +
    `${hidden ? ` <span class="lee-dim">(${hidden} hidden)</span>` : ''}</label>` +
    `<span class="lee-history-runs">${group?.code || 0} kernel run${group?.code === 1 ? '' : 's'}</span>` +
    (resumable ? `<button class="lee-btn go lee-history-resume" title="Continue this conversation">Resume</button>` : '');
  index.querySelector('select')?.addEventListener('change', e =>
    showHistorySession(all.find(s => s.id === e.target.value), all));
  index.querySelector('.lee-history-leelaonly')?.addEventListener('change', async e => {
    await prefSet('agent', 'historyLeelaOnly', e.target.checked);
    // The CLI's conversations are not in `all` when the box was checked, so this asks again.
    const groups = await historyGroups(), left = shownSessions(groups);
    showHistorySession(left.find(s => s.id === group?.id) || left[0], groups);
  });
  index.querySelector('.lee-history-resume')?.addEventListener('click', () => leeAgentResume(group));
  log.appendChild(index);
  if (!group) {
    return log.insertAdjacentHTML('beforeend', '<div class="lee-dim">(no sessions yet)</div>');
  }
  log.insertAdjacentHTML('beforeend', `<div class="lee-history-session-head">` +
    `<strong>${esc(titleText(group.title) || sessionTime(group))}</strong>` +
    `<span>${titleText(group.title) ? `${esc(sessionTime(group))} · ` : ''}` +
    `${group.context_continues ? 'context continued across these turns' : 'separate context'}</span></div>`);
  renderTurns(log, turns, 'conversation');
  if (group.code || group.id.startsWith('agent_')) {
    const transcript = await api('/agent/transcript?session=' + encodeURIComponent(group.id));
    if ((transcript.cells || []).length) {
      log.insertAdjacentHTML('beforeend', '<div class="lee-vgroup">code executed in this session</div>');
      renderSessionCells(log, transcript);
    }
  }
  log.scrollTop = 0;
}
/* The live pane is DOM only, so a reload, an htmx swap of the shell, or a switch to a conversation
   this tab has never shown leaves it blank while the turns are still on disk. They come from the
   server and replace what is on screen, because painting into what is already there duplicated a
   transcript on the way back to it. */
async function paintAgentThread(id) {
  const log = $('#agentlog'); if (!log) return null;
  const d = await api('/agent/thread/turns' + (id ? '?thread=' + encodeURIComponent(id) : ''));
  const welcome = $('.lee-agent-welcome', log);
  approvalCards.clear();
  log.dataset.foldScope = '';
  dropCodeSurfaces(log);
  if ((d.turns || []).length) { log.innerHTML = ''; renderTurns(log, d.turns, titleText(d.title) || 'conversation'); }
  else log.innerHTML = welcome ? welcome.outerHTML : '';
  renderWarmStart(log, d.warm);
  lee.agentView = 'live'; $('#agenthistory')?.classList.remove('active');
  trimAgentLog(log);   // a conversation of any length arrives here whole
  // Nothing to set aside: the live pane is what was just painted into the log.
  lee.agentLive = null; stickAgentLog(log, true);
  return d;
}
/* Conversations live in the agent's log, not in this process, so a fresh one holds none: opening
   the app after working in a browser showed an empty pane while the work sat on disk. An empty pane
   picks the newest conversation back up, which is what "where was I" means. */
async function rehydrateAgentLive() {
  if (lee.observer) return;
  const log = $('#agentlog');
  // a conversation a person chose is empty because it is new, not because the pane forgot it
  if (!log || lee.agentView === 'history' || lee.agentBusy || lee.agentHydrating || lee.agentPicks) return;
  lee.agentHydrating = true;
  try {
    const d = await paintAgentThread(lee.agentThread || '');
    if (!(d?.turns || []).length) await resumeLatestAgent();
  }
  catch (e) { /* an empty pane beats a boot that dies on a cold agent */ }
  finally { lee.agentHydrating = false; }
}
function paintResumed(d) {
  const log = $('#agentlog');
  if (log) {
    log.dataset.foldScope = ''; dropCodeSurfaces(log); log.innerHTML = '';
    renderTurns(log, d.turns || [], 'resumed conversation');
    stickAgentLog(log, true);
  }
  lee.agentView = 'live'; lee.agentLive = null; lee.agentThread = d.session || lee.agentThread;
  $('#agenthistory')?.classList.remove('active');
  loadAgentModels().catch(() => {});
}
/* A pick returns its `done`; until then `lee.agentPicked` is pending, so the boot resume can wait for
   the pane's own choice to land rather than switch the server back to the conversation it replaced. */
function pickAgentThread() {
  lee.agentPicks = (lee.agentPicks || 0) + 1; let done;
  const p = new Promise(r => done = r); lee.agentPicked = p;
  return () => { done(); if (lee.agentPicked === p) lee.agentPicked = null; };
}
async function agentPicksSettled() { while (lee.agentPicked) await lee.agentPicked; }
async function resumeLatestAgent() {
  if (lee.observer) return;
  // Nothing saved is the first run, not a failure, so this never speaks up about it.
  const picks = lee.agentPicks || 0;
  try {
    await agentPrefsReady();   // the saved filter, not the default, decides what boot may open
    if ((lee.agentPicks || 0) !== picks) return;
    /* Read under the same filter as the history list: a pane that hides the CLI's conversations
       cannot open one of them on boot. With the filter off, `latest` is the log's newest again. */
    const d = await post('/agent/resume', {session: 'latest', everything: !leelaOnly()});
    // the resume made its conversation the server's active one; a choice made meanwhile wins back
    const chosen = (lee.agentPicks || 0) !== picks;
    if (chosen) await agentPicksSettled();
    if (chosen || !(d.turns || []).length) {
      // nothing to paint: the server's active conversation goes back to the one this pane shows
      if (lee.agentThread && lee.agentThread !== d.session) await post('/agent/thread/switch', {thread: lee.agentThread});
      return loadAgentModels().catch(() => {});
    }
    paintResumed(d);
    status(`picked up ${titleText(d.title) || d.session}`, 'ok');
  } catch (_) {}
}
function warmAgentHistory() {
  // Nothing is painted from it: this is the read that makes the next one cheap.
  historyGroups().catch(() => {});
}
async function leeAgentHistory() {
  if (lee.agentView === 'history') return restoreAgentLive();
  rememberAgentLive(); lee.agentView = 'history'; $('#agenthistory')?.classList.add('active');
  /* `rememberAgentLive` moves the nodes out rather than copying them, so from here until the
     history is painted the only copy of the conversation is in `lee.agentLive`. A history read
     that fails must put it back, or the pane is left blank with the work in a variable. */
  try {
    const all = await historyGroups();
    await showHistorySession(shownSessions(all)[0], all);
    return;
  } catch (e) {
    restoreAgentLive();
    return status(`history unavailable: ${e.message || e}`, 'err');
  }
}
async function leeAgentResume(group) {
  if (!group) return;
  if (lee.agentBusy) return status('the model is already working', 'err');
  const picked = pickAgentThread();
  try {
    const d = await post('/agent/resume', {session: group.id});
    paintResumed(d);
    $('#agentprompt')?.focus();
    status(d.note || `resumed ${d.session}`, 'ok');
  } catch (e) { status(String(e.message || e), 'err'); }
  finally { picked(); }
}
function rememberAgentThread() {
  if (!lee.agentThread) return;
  lee.agentThreadDrafts.set(lee.agentThread, $('#agentprompt')?.value || '');
}
/* A conversation with nothing said in it has no name, and its id is a bare timestamp. Say what it
   is and when it started instead. */
function threadName(t) {
  const named = titleText(t.title); if (named) return named;
  const at = /(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})/.exec(t.id || '');
  return at ? `new conversation · ${at[4]}:${at[5]}` : 'new conversation';
}
function threadLabel(t) {
  return `${threadName(t)} · ${t.state}${t.unread ? ` · ${t.unread} new` : ''}${t.muted ? ' · muted' : ''}`;
}
/* One card per conversation, with its own controls, rather than a select plus four buttons that
   all acted on whichever one happened to be showing. */
function paintAgentThreads(d) {
  const rows = d.threads || [];
  // the pane's own choice outlives the server's `active`, which a resume elsewhere moves; only a gone one yields
  const gone = !lee.agentThread || (d.live && !d.live.includes(lee.agentThread));
  lee.agentThreadRows = rows; if (gone) lee.agentThread = d.active || '';
  const count = $('#agentthreadcount'); if (count) count.textContent = String(rows.length);
  const waiting = (d.attention?.waiting || []).length, unread = d.attention?.unread || 0;
  const toggle = $('#agentthreads');
  if (toggle) {
    toggle.classList.toggle('wants', !!waiting);
    toggle.classList.toggle('unread', !waiting && !!unread);
    toggle.title = waiting ? `${waiting} conversation(s) waiting for you`
      : unread ? `${unread} unread turn(s) elsewhere` : 'every live conversation';
  }
  const list = $('#agentthreadlist');
  if (list) {
    list.innerHTML = rows.map(t => {
      const live = t.id === d.active;
      return `<article class="lee-thread-card${live ? ' active' : ''}${t.state === 'waiting' ? ' wants' : ''}"` +
        ` role="option" aria-selected="${live}" tabindex="0" data-thread="${esc(t.id)}">` +
        `<header><strong>${esc(threadName(t))}</strong>${t.warm ? '<span class="lee-thread-warm" title="seeded from dhrona\'s rounds">·warm</span>' : ''}` +
        (t.optin || []).map(o => `<span class="lee-thread-warm" title="opted into ${esc(o)}">` + '·' + esc(o) + '</span>').join('') +
        (t.profile === 'small' ? '<span class="lee-thread-warm" title="small profile: 14 tools and one screen, for a local or small-window model">·small</span>' : '') +
        `<span class="lee-thread-state ${esc(t.state)}">${esc(t.state)}</span></header>` +
        `<footer><span>${t.unread ? `${t.unread} new` : (live ? 'on screen' : 'idle')}` +
        `${t.branch && t.branch !== 'main' ? ` · on ${esc(t.branch)}` : ''}` +
        `${t.muted ? ' · muted' : ''}</span><span class="lee-spacer"></span>` +
        `<button type="button" data-thread-rename title="rename">rename</button>` +
        `<button type="button" data-thread-mute title="${t.muted ? 'unmute' : 'silence notifications'}">${t.muted ? 'unmute' : 'mute'}</button>` +
        `<button type="button" data-thread-reshape title="edit this conversation as a notebook">edit</button>` +
        `<button type="button" data-thread-branches title="fork this conversation, or switch branch">branches</button>` +
        `<button type="button" data-thread-close class="warn" title="close">close</button></footer></article>`;
    }).join('') || '<div class="lee-dim">no live conversations</div>';
    list.insertAdjacentHTML('beforeend',
      `<footer class="lee-thread-list-foot"><label title="browser notification when a background ` +
      `conversation wants you"><input type="checkbox" id="agentnotify"${agentNotifyEnabled() ? ' checked' : ''}>` +
      `<span>notify me about background conversations</span></label></footer>`);
    $('#agentnotify', list).onchange = e => leeAgentNotifyToggle(e.target.checked);
    bindAgentThreadCards(list);
  }
  paintAgentWarmToggle();   // the preference arrives with the settings; the button shows it once they have
  paintAgentAcceptButton();
  paintAgentAttention(d.attention || {}, rows);
}
function bindAgentThreadCards(list) {
  if (list._leeThreadsBound) return;
  list._leeThreadsBound = true;
  const cardId = e => e.target.closest('[data-thread]')?.dataset.thread || '';
  list.addEventListener('click', e => {
    const id = cardId(e); if (!id) return;
    const button = e.target.closest('button');
    if (!button) return leeAgentThreadOpen(id);
    if (button.hasAttribute('data-thread-rename')) return leeAgentThreadRename(id);
    if (button.hasAttribute('data-thread-mute')) return leeAgentThreadMute(id);
    if (button.hasAttribute('data-thread-reshape')) return leeAgentReshape(id);
    if (button.hasAttribute('data-thread-branches')) return leeAgentBranches(id);
    if (button.hasAttribute('data-thread-close')) return leeAgentThreadClose(id);
  });
  list.addEventListener('keydown', e => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const id = cardId(e); if (!id || e.target.closest('button')) return;
    e.preventDefault(); leeAgentThreadOpen(id);
  });
}
function leeAgentThreadsToggle(show) {
  const list = $('#agentthreadlist'), toggle = $('#agentthreads'); if (!list) return;
  const open = show === undefined ? list.hidden : !!show;
  list.hidden = !open; toggle?.setAttribute('aria-expanded', String(open));
  if (open) refreshAgentThreads().catch(() => {});
}
/* The conversation as a notebook, edited with the editor a person already knows, then read back.
   Nothing is applied until they ask: saving the notebook changes no conversation by itself. */
async function leeAgentReshape(id = lee.agentThread) {
  if (!id) return status('open a conversation first', 'err');
  let made;
  try { made = await post('/agent/conversation/notebook', {thread: id, session: id}); }
  catch (e) { return status(e.message || String(e), 'err'); }
  lee.agentReshape = {thread: id, session: made.session, path: made.path, revision: made.revision};
  await leeOpenFile(made.path);
  status(`${made.parts} parts opened as a notebook · edit, save, then apply from the agent pane`, 'ok');
  paintAgentReshapeBar();
}
function paintAgentReshapeBar() {
  const bar = $('#agentattention'); const held = lee.agentReshape; if (!bar || !held) return;
  bar.hidden = false;
  bar.innerHTML = `<span>editing ${esc(held.session.replace(/^agent_/, 'conversation '))} as a notebook</span>` +
    `<button type="button" data-reshape-apply>apply edits</button>` +
    `<button type="button" data-reshape-cancel>discard edits</button>`;
  $('[data-reshape-apply]', bar).onclick = leeAgentReshapeApply;
  $('[data-reshape-cancel]', bar).onclick = () => { lee.agentReshape = null; bar.hidden = true; refreshAgentThreads(); };
}
async function leeAgentReshapeApply() {
  const held = lee.agentReshape; if (!held) return;
  // read the edits from disk, so an unsaved buffer cannot look like a deleted part
  try { await post('/tabs/save-all'); } catch (_) {}
  let out;
  try { out = await post('/agent/conversation/reshape', held); }
  catch (e) { return status(e.message || String(e), 'err'); }
  lee.agentReshape = null; $('#agentattention').hidden = true;
  await refreshAgentThreads();
  status(`reshaped · ${out.discarded.length} dropped, ${out.rewritten.length} rewritten · ${out.branch_id}`, 'ok');
}
/* Branches belong to a conversation, so the way in is that conversation's own card. Two lists in
   one dialog: where this conversation has already been cut, and where it can still be. A branch is
   a parent point and a manifest, recompiled on switch, so nothing here replays a turn. */
async function leeAgentBranches(id = lee.agentThread) {
  if (!id) return status('open a conversation first', 'err');
  let d;
  try { d = await api('/agent/branches?thread=' + encodeURIComponent(id)); }
  catch (e) { return status(e.message || String(e), 'err'); }
  const origin = b => b.branch_id === 'main' ? 'the conversation as recorded'
    : `${b.shaped ? 'shaped' : 'forked'} from turn ${esc(turnShort(b.parent_turn_id))} ${esc(b.stage || 'after')}` +
      `${b.parent_branch_id ? ` · off ${esc(b.parent_branch_id)}` : ''}`;
  const branches = (d.branches || []).map(b =>
    `<div class="lee-setup-row"><span><strong>${esc(b.branch_id)}</strong>` +
    `${b.branch_id === d.active ? ' · active' : ''}<br><small>${origin(b)}</small></span>` +
    (b.branch_id === d.active ? '<span class="lee-dim">on screen</span>'
      : `<button class="lee-btn" data-switch="${esc(b.branch_id)}">switch</button>`) + '</div>').join('');
  const points = (d.turns || []).filter(t => t.after).map(t =>
    `<div class="lee-setup-row"><span><strong>turn ${esc(turnShort(t.turn_id))}</strong><br>` +
    `<small>captured on ${esc(t.branch_id)}</small></span>` +
    `<button class="lee-btn" data-fork="${esc(t.turn_id)}">fork…</button></div>`).reverse().join('');
  const m = modal(`<div class="lee-mhead">Conversation branches<span class="sub">active · ${esc(d.active)}</span></div>` +
    `<h4>branches</h4><div class="lee-modallist">${branches}</div>` +
    `<h4>branch points</h4><div class="lee-modallist">${points ||
      '<div class="lee-dim">no turn of this conversation was captured in this session</div>'}</div>` +
    `<div class="lee-mfoot"><span class="lee-dim">a branch is a starting point, not a copy</span>` +
    `<span class="lee-spacer"></span><button class="lee-btn" data-shape>shape context…</button></div>`,
    null, null, {storageKey: 'agent-branches'});
  $('[data-shape]', m).onclick = () => { m.remove(); leeAgentShape(id); };
  $$('[data-switch]', m).forEach(b => b.onclick = async () => {
    if (await leeAgentBranchSwitch(b.dataset.switch, id)) { m.remove(); leeAgentBranches(id); }
  });
  $$('[data-fork]', m).forEach(b => b.onclick = () => { m.remove(); leeAgentForkTurn(b.dataset.fork, id); });
}
const turnShort = id => String(id || '').split(':').at(-1);
/* Switching moves what the model remembers, never what is on screen: the transcript is the record
   of what was said, and saying otherwise would hide a turn that really happened. */
async function leeAgentBranchSwitch(branchId, id = lee.agentThread) {
  try {
    const d = await post('/agent/branch/switch', {thread: id, branch_id: branchId});
    await refreshAgentThreads();
    status(`the next turn continues from ${d.active} · the transcript above is unchanged`, 'ok');
    return d;
  } catch (e) { status(e.message || String(e), 'err'); return null; }
}
/* A fork point is a part, not a message: a call and the results it produced move together, so
   picking one inside a tool exchange takes the whole exchange. */
async function leeAgentForkTurn(turnId, id = lee.agentThread) {
  if (!turnId) return status('no turn to branch from', 'err');
  let d;
  try { d = await api(`/agent/branch/parts?turn_id=${encodeURIComponent(turnId)}&stage=after` +
                      `&thread=${encodeURIComponent(id || '')}`); }
  catch (e) { return status(e.message || String(e), 'err'); }
  const kinds = {user: 'you', assistant: 'agent', calls: 'call', result: 'result'};
  const rows = (d.parts || []).map(p =>
    `<div class="lee-setup-row"><span><strong>${esc(kinds[p.kind] || p.kind)}</strong><br>` +
    `<small>${esc((p.preview || '').slice(0, 120) || 'no text')}</small></span>` +
    `<button class="lee-btn" data-part="${esc(p.part_id)}">keep to here</button></div>`).join('');
  const m = modal(`<div class="lee-mhead">Branch from turn ${esc(turnShort(turnId))}` +
    `<span class="sub">a new branch continuing from the point you pick · nothing is deleted</span></div>` +
    `<div class="lee-modallist"><div class="lee-setup-row"><span><strong>the whole turn</strong><br>` +
    `<small>everything said up to and including it</small></span>` +
    `<button class="lee-btn go" data-part="">branch here</button></div>${rows}</div>`,
    null, null, {storageKey: 'agent-fork'});
  $$('[data-part]', m).forEach(b => b.onclick = async () => {
    try {
      const out = await post('/agent/fork', {thread: id, turn_id: turnId, stage: 'after', part_id: b.dataset.part});
      m.remove(); await refreshAgentThreads();
      status(`branched to ${out.branch_id} · ${out.kept} part(s) kept, ${out.omitted} dropped`, 'ok');
    } catch (e) { status(e.message || String(e), 'err'); }
  });
}
/* What the model still carries, decided in one place rather than in a notebook. Nothing is
   written until apply, and apply is refused unless the branch is still at the revision the preview
   was taken at: a conversation that moved while a person was deciding is a different question. */
async function leeAgentShape(id = lee.agentThread) {
  if (!id) return status('open a conversation first', 'err');
  let d;
  try { d = await api('/agent/conversation/parts?thread=' + encodeURIComponent(id)); }
  catch (e) { return status(e.message || String(e), 'err'); }
  const parts = d.parts || [];
  if (!parts.length) return status('this conversation has no recorded turns to shape', 'err');
  const kinds = {user: 'you', assistant: 'agent', call: 'call', result: 'result'};
  const rows = parts.map(p =>
    `<div class="lee-setup-row lee-shape-row" data-part="${esc(p.part_id)}">` +
    `<span><strong>${esc(kinds[p.kind] || p.kind)}</strong>${p.tool ? ` · ${esc(p.tool)}` : ''}` +
    (p.editable ? `<textarea class="lee-input" data-text rows="2" spellcheck="true"` +
                  ` aria-label="what the model remembers here">${esc(p.text || '')}</textarea>`
                : `<br><small>${esc((p.text || '').slice(0, 160) || 'no text')}</small>`) + '</span>' +
    `<label title="uncheck to drop this part"><input type="checkbox" data-keep checked> keep</label></div>`).join('');
  const m = modal(`<div class="lee-mhead">Shape this conversation` +
    `<span class="sub">${esc(d.session)} · branch ${esc(d.branch_id)}</span></div>` +
    `<section class="lee-revision-explainer"><strong>You are choosing what the model still carries.</strong>` +
    `<span>Tools will not run again and files will not change. A call and its result go together. ` +
    `Apply writes a new branch, and the recorded conversation stays as it is.</span></section>` +
    `<div class="lee-modallist">${rows}</div>` +
    `<div class="lee-mfoot"><span class="lee-dim" data-summary>reading…</span><span class="lee-spacer"></span>` +
    `<button class="lee-btn" data-cancel>close</button>` +
    `<button class="lee-btn go" data-apply disabled>apply as a new branch</button></div>`,
    null, null, {className: 'lee-setup-modal', storageKey: 'agent-shape'});
  const manifest = () => Object.fromEntries($$('[data-part]', m)
    .filter(row => !$('[data-keep]', row).checked).map(row => [row.dataset.part, 'discard']));
  const rewrites = () => Object.fromEntries(parts.filter(p => p.editable).map(p =>
    [p.part_id, $(`[data-part="${CSS.escape(p.part_id)}"] [data-text]`, m)?.value])
    .filter(([pid, text]) => text !== undefined && text !== (parts.find(p => p.part_id === pid).text || '')));
  const summary = $('[data-summary]', m), apply = $('[data-apply]', m);
  let seen = null, timer = null;
  const preview = async () => {
    try {
      const pv = await post('/agent/history/preview',
                            {thread: id, session: d.session, manifest: manifest(), rewrites: rewrites()});
      seen = pv; apply.disabled = false;
      summary.textContent = `${pv.kept} kept · ${pv.omitted} dropped · ${pv.rewritten.length} rewritten` +
        ` · about ${pv.tokens} tokens` +
        (pv.adjusted.length ? ` · ${pv.adjusted.length} went with the call they belong to` : '');
    } catch (e) { seen = null; apply.disabled = true; summary.textContent = e.message || String(e); }
  };
  // Apply is only ever offered for a manifest the person has been shown the cost of.
  const schedule = () => { seen = null; apply.disabled = true; clearTimeout(timer); timer = setTimeout(preview, 250); };
  m.addEventListener('input', schedule); m.addEventListener('change', schedule);
  preview();
  $('[data-cancel]', m).onclick = () => m.remove();
  apply.onclick = async () => {
    if (!seen) return;
    try {
      const out = await post('/agent/history/apply',
                             {thread: id, session: d.session, branch_id: seen.branch_id, revision: seen.revision,
                              manifest: manifest(), rewrites: rewrites()});
      m.remove(); await refreshAgentThreads();
      status(`shaped into ${out.branch_id} · ${out.omitted} dropped, ${out.rewritten.length} rewritten`, 'ok');
    } catch (e) {
      /* A refusal here is nearly always the branch having moved, so the honest recovery is to
         re-read it and show what it costs now rather than to send the same revision again. */
      status(e.message || String(e), 'err'); preview();
    }
  };
}
async function leeAgentThreadOpen(id) {
  await leeAgentThreadSwitch(id);
  leeAgentThreadsToggle(false);
  $('#agentprompt')?.focus();
}
/* `status()` is footer-only and addressed to nothing. A checkpoint in another conversation needs
   naming and a way in. */
/* The `done` event is the only thing that clears `agentBusy`, and a stream that drops as the turn
   ends never delivers it -- `es.onerror` reconnects and leaves it standing. The pane then reads as
   working over a conversation the server has long since finished, and the composer stays in steer
   mode with no way back. This poll already carries the server's own view of the active
   conversation, so it is what settles the disagreement. The delay is for the other race: a send
   raises `agentBusy` before the run is registered, and a poll landing in that window would clear a
   turn that is about to start. */
const BUSY_SETTLE_MS = 6000;
function reconcileAgentBusy(attention) {
  const state = attention.active_state;
  if (!state || !lee.agentBusy) return;
  if (state === 'working' || state === 'waiting') return;
  if (Date.now() - (lee.agentBusyAt || 0) < BUSY_SETTLE_MS) return;
  lee.agentBusy = false; lee.agentRuns = [];
  setAgentStatus(state === 'failed' ? 'idle' : 'ready');
  updateAgentRunstrip({runs: []});
}
/* Nothing else polls: `refreshAgentThreads` runs on what a person does, and the stream that would
   say `done` is the thing missing when this goes wrong. So the check has to run on its own clock,
   and only while a turn is outstanding -- it stops itself as soon as one is not. */
function startAgentBusyWatch() {
  if (lee.agentBusyWatch) return;
  let asking = false;   // a reply slower than the interval must not stack a second request behind it
  lee.agentBusyWatch = setInterval(async () => {
    if (asking) return;
    const gen = lee.agentStreamGen;
    let d = null; asking = true;
    try { await agentPrefsReady(); d = await api('/agent/threads'); } catch (_) {} finally { asking = false; }
    // a switch or a new conversation that landed meanwhile owns `lee.agentThread`, and this `active` predates it
    if (d && gen === lee.agentStreamGen) { paintAgentThreads(d); notifyAgentAttention(d); }
    if (!lee.agentBusy && !d?.attention?.working) { clearInterval(lee.agentBusyWatch); lee.agentBusyWatch = null; }
  }, 5000);
}
function paintAgentAttention(attention, rows) {
  reconcileAgentBusy(attention);
  const bar = $('#agentattention'); if (!bar) return;
  const waiting = (attention.waiting || []).filter(id => id !== attention.active);
  const working = Math.max(0, (attention.working || 0) - (rows.some(t => t.id === attention.active && t.state === 'working') ? 1 : 0));
  document.title = agentDocumentTitle(attention);
  if (!waiting.length) { bar.hidden = true; bar.innerHTML = ''; return; }
  const named = waiting.map(id => {
    const row = rows.find(t => t.id === id);
    return `<button type="button" data-attention="${esc(id)}">${esc(row ? threadName(row) : id)}</button>`;
  }).join('');
  bar.hidden = false;
  bar.innerHTML = `<span>${waiting.length === 1 ? 'A conversation is' : `${waiting.length} conversations are`} waiting for you</span>${named}`;
  for (const button of $$('[data-attention]', bar)) button.onclick = () => leeAgentAttend(button.dataset.attention);
  return working;
}
function agentDocumentTitle(attention) {
  const base = lee.agentDocumentTitle ||= document.title.replace(/^[^·]*· /, '');
  const bits = [];
  if (attention.working) bits.push(`${attention.working}⚙`);
  if ((attention.waiting || []).length) bits.push('(!)');
  return bits.length ? `${bits.join(' ')} · ${base}` : base;
}
/* Switching to the conversation that asked, and then to the question it asked. The right pane with
   no idea what wanted you is half an answer. */
async function leeAgentAttend(id) {
  await leeAgentThreadSwitch(id);
  const card = $('.lee-approval-card') || $('[data-approval]');
  if (card) { card.scrollIntoView({block: 'center'}); (card.querySelector('button') || card).focus(); }
  else await pollApproval();
}
async function leeAgentThreadMute(id = lee.agentThread) {
  if (!id) return;
  const row = (lee.agentThreadRows || []).find(t => t.id === id);
  try {
    const d = await post('/agent/thread/mute', {thread: id, muted: !row?.muted});
    if (d.thread?.problem) status(`mute was not saved: ${d.thread.problem}`, 'err');
    await refreshAgentThreads();
  } catch (e) { status(String(e.message || e), 'err'); }
}
async function refreshAgentThreads() {
  await agentPrefsReady();   // the list paints the notify box, which is one of them
  const d = await api('/agent/threads'); paintAgentThreads(d); notifyAgentAttention(d); return d;
}
/* Off by default, and permission is asked for only when a person turns it on, because a prompt
   nobody invited is why browsers stopped honouring them. Every state is terminal: unsupported and
   denied disable delivery and say so once. */
function agentNotifyEnabled() { return prefGet('agent', 'notify', false) === true; }
async function leeAgentNotifyToggle(on) {
  const off = async (said, tone) => { await prefSet('agent', 'notify', false); return status(said, tone); };
  if (!on) return off('notifications off', 'ok');
  if (!('Notification' in window)) return off('this browser has no notifications', 'err');
  let state = Notification.permission;
  if (state === 'default') { try { state = await Notification.requestPermission(); } catch (_) { state = 'denied'; } }
  if (state !== 'granted') return off('notifications are blocked for this site', 'err');
  await prefSet('agent', 'notify', true); status('notifications on', 'ok');
}
/* One notification per thing that happened, keyed by what happened: replay, a reconnect and a
   second tab all deliver the same terminal event. */
function notifyAgentAttention(d) {
  const seen = lee.agentNotified ||= new Set();
  if (!agentNotifyEnabled() || !('Notification' in window) || Notification.permission !== 'granted') return;
  for (const row of (d.threads || [])) {
    if (row.id === d.active || row.muted) continue;
    const key = `${row.id}:${row.state}:${row.unread}`;
    if (seen.has(key)) continue;
    seen.add(key);
    if (!document.hidden) continue;
    const name = threadName(row);
    if (row.state === 'waiting') new Notification('Waiting for you', {body: name, tag: row.id});
    else if (row.unread) new Notification('Turn finished', {body: name, tag: row.id});
  }
}
window.leeAgentNotifyToggle = leeAgentNotifyToggle; window.agentNotifyEnabled = agentNotifyEnabled;
/* Warm starts are opt-in per new conversation: the toggle is a preference, read when `+` is
   pressed, so a person decides before the first prompt and sees the choice on the button. */
function agentWarmEnabled() { return prefGet('agent', 'warm', false) === true; }
function paintAgentWarmToggle() { $('#agentwarm')?.setAttribute('aria-pressed', String(agentWarmEnabled())); paintAgentOptins(); paintAgentFullToggle(); }
function leeAgentWarmToggle() {
  const on = !agentWarmEnabled(); prefSet('agent', 'warm', on); paintAgentWarmToggle();
  status(on ? 'the next new conversation starts warm' : 'new conversations start cold', 'ok');
}
/* Opt-in tool groups for the next new conversation. The buttons are painted from the workspace
   default on the server; a preference, once set, overrides it for this browser. */
/* The profile is ramabana's: `auto` is small for a local or small-window model. `full` here asks for
   everything on the next new conversation; the workspace default is the settings pane's select. */
function agentFullEnabled() { const p = prefGet('agent', 'full', null); return p === null ? $('#agentfull')?.getAttribute('aria-pressed') === 'true' : p === true; }
function paintAgentFullToggle() { $('#agentfull')?.setAttribute('aria-pressed', String(agentFullEnabled())); }
function leeAgentFullToggle() {
  const on = !agentFullEnabled(); prefSet('agent', 'full', on); paintAgentFullToggle();
  status(on ? 'the next new conversation is briefed in full' : 'new conversations take the workspace profile', 'ok');
}
window.leeAgentFullToggle = leeAgentFullToggle;
function agentOptinButtons() { return $$('[data-optin]').filter(b => b.id.startsWith('agentoptin-')); }
function agentOptins() { return agentOptinButtons().filter(b => b.getAttribute('aria-pressed') === 'true').map(b => b.dataset.optin); }
function paintAgentOptins() {
  for (const b of agentOptinButtons()) {
    const pref = prefGet('agent', 'optin:' + b.dataset.optin, null);
    if (pref !== null) b.setAttribute('aria-pressed', String(pref === true));
  }
}
function leeAgentOptinToggle(name) {
  const b = $(`#agentoptin-${name}`); if (!b) return;
  const on = b.getAttribute('aria-pressed') !== 'true';
  prefSet('agent', 'optin:' + name, on); b.setAttribute('aria-pressed', String(on));
  status(on ? `the next new conversation gets ${name}` : `new conversations go without ${name}`, 'ok');
}
window.leeAgentOptinToggle = leeAgentOptinToggle; window.agentOptins = agentOptins;
/* A warm start is one collapsed block above the first turn. Its body is the rounds as they were
   replayed: the user line, the assistant's words, and every tool call painted with the same step
   renderer a live call gets, so "seeing the instructions run" reads like the conversation does.
   The live `warm` event and a repaint from `/agent/thread/turns` both come here with the same JSON. */
function renderWarmStart(log, rep) {
  if (!log || !rep) return;
  $('.lee-agent-warm', log)?.remove();
  const used = rep.used || [], skipped = rep.skipped || [];
  const block = document.createElement('details'); block.className = 'lee-agent-warm';
  const names = used.map(r => r.name).join(', ');
  const title = used.length ? `Warm start · ${used.length} round${used.length === 1 ? '' : 's'} (${names})`
              : rep.problem ? 'Warm start · unavailable' : "Warm start · no rounds fit this session's tools";
  block.innerHTML = `<summary><span class="lee-agent-step-copy">${esc(title)}</span>` +
    `<span class="lee-agent-step-chevron" aria-hidden="true"></span></summary>`;
  if (rep.problem) block.insertAdjacentHTML('beforeend', `<div class="lee-dim">${esc(rep.problem)}</div>`);
  for (const r of used) {
    const sect = document.createElement('div'); sect.className = 'lee-agent-warm-round';
    sect.insertAdjacentHTML('beforeend', `<div class="lee-vgroup">${esc(r.name)} · rank ${esc(r.rank)}${r.model ? ' · ' + esc(r.model) : ''}</div>`);
    const results = new Map((r.messages || []).filter(m => m.role === 'tool').map(m => [m.tool_call_id, m.content]));
    for (const m of r.messages || []) {
      if (m.role === 'user') sect.appendChild(userMessage(m.content));
      else if (m.role === 'assistant') {
        if (m.content) { const reply = document.createElement('div'); reply.className = 'lee-reply'; renderMarkdown(reply, m.content); sect.appendChild(reply); }
        for (const tc of m.tool_calls || []) {
          const row = document.createElement('details');
          renderAgentStep(row, {tool: tc.name, args: tc.arguments, kind: 'tool', done: true, ok: true,
                                summary: `${tc.name} (replayed)`, detail: String(results.get(tc.id) ?? '')});
          sect.appendChild(row);
        }
      }
    }
    block.appendChild(sect);
  }
  if (skipped.length) {
    const ul = document.createElement('ul'); ul.className = 'lee-agent-warm-skipped';
    for (const s of skipped) ul.insertAdjacentHTML('beforeend', `<li><code>${esc(s.name)}</code> — ${esc(s.reason)}</li>`);
    block.insertAdjacentHTML('beforeend', '<div class="lee-vgroup">skipped</div>'); block.appendChild(ul);
  }
  const first = $('.lee-agent-turn', log);
  first ? log.insertBefore(block, first) : log.appendChild(block);
}
/* Assess, capture, accept: dhrona's loop from the pane. The assessment is a card at the end of
   the log; a capture opens the review notebook as a tab, and editing it there is the review. The
   accept button shows once something is here to accept: a capture this page made, or an open
   `.dhrona/*.ipynb` tab. */
const agentRoundSource = () => lee.agentRoundSource || (/\/\.dhrona\/[^/]+\.ipynb$/.test(lee.path || '') ? lee.path : '');
function paintAgentAcceptButton() { const b = $('#agentaccept'); if (b) b.hidden = !agentRoundSource(); }
async function leeAgentAssess() {
  try {
    const d = await post('/agent/thread/assess', {thread: lee.agentThread});
    const log = $('#agentlog'); if (!log) return;
    const card = document.createElement('details'); card.className = 'lee-agent-warm lee-agent-assess'; card.open = true;
    const rows = (d.findings || []).map(f => `<li><code>${esc(f.kind)}</code> ${esc(f.tool)} · turn ${f.turn + 1}, call ${f.index + 1} — ${esc(f.message)}</li>`).join('');
    card.innerHTML = `<summary><span class="lee-agent-step-copy">Assessment · score ${esc(d.score)} · ${esc(d.calls)} call${d.calls === 1 ? '' : 's'} over ${esc(d.turns)} turn${d.turns === 1 ? '' : 's'}</span>` +
      `<span class="lee-agent-step-chevron" aria-hidden="true"></span></summary>` +
      (rows ? `<ul class="lee-agent-warm-skipped">${rows}</ul>` : '<div class="lee-dim">no findings</div>');
    log.appendChild(card); stickAgentLog(log, true);
  } catch (e) { status(String(e.message || e), 'err'); }
}
async function leeAgentCapture() {
  const name = prompt('round name', lee.agentTitle || ''); if (name === null) return;
  try {
    const d = await post('/agent/thread/capture', {thread: lee.agentThread, name});
    lee.agentRoundSource = d.path; paintAgentAcceptButton(); await leeOpenFile(d.path);
    status(`review ${d.name}: remove poor routes, save, then accept`, 'ok');
  } catch (e) { status(String(e.message || e), 'err'); }
}
async function leeAgentAccept() {
  const source = agentRoundSource(); if (!source) { status('capture a round first, or open its review notebook', 'err'); return; }
  const reviewer = prompt('reviewer', lee.agentReviewer || ''); if (!reviewer) return;
  try {
    const d = await post('/agent/round/accept', {source, reviewer}); lee.agentReviewer = reviewer;
    status(`installed ${d.installed}`, 'ok');
  } catch (e) { status(String(e.message || e), 'err'); }
}
async function leeAgentNew() {
  rememberAgentThread(); const leftBusy = lee.agentBusy, picked = pickAgentThread();
  try {
    const d = await post('/agent/thread/new', {warm: agentWarmEnabled(), optin: agentOptins(), profile: agentFullEnabled() ? 'full' : ''}); lee.agentThread = d.active; lee.agentBusy = false; lee.agentTitle = '';
    // the turn left behind keeps running on the server; only this pane stops drawing it
    if (lee.agentStream) { lee.agentStream._leeStopped = true; lee.agentStream.close(); lee.agentStream = null; } ++lee.agentStreamGen;
    if (leftBusy) startAgentBusyWatch();
    approvalCards.clear(); const log = $('#agentlog'), input = $('#agentprompt');
    if (log) { dropCodeSurfaces(log); log.innerHTML = ''; lee.agentLive = null; lee.agentView = 'live'; } if (input) input.value = '';
    await refreshAgentThreads(); $('#agenthistory')?.classList.remove('active'); input?.focus(); status('new conversation started', 'ok');
    loadAgentModels().catch(() => {});
  } catch (e) { status(String(e.message || e), 'err'); }
  finally { picked(); }
}
/* A conversation with a turn in flight keeps producing while it is off screen. Switching to it
   paints its finished turns from the server first, then attaches to its feed from the last point
   it settled, so the running turn arrives once and nothing drawn is drawn twice. */
async function leeAgentThreadSwitch(id) {
  if (!id || id === lee.agentThread) return; rememberAgentThread(); const picked = pickAgentThread();
  try {
    const d = await post('/agent/thread/switch', {thread:id});
    if (lee.agentStream) { lee.agentStream._leeStopped = true; lee.agentStream.close(); lee.agentStream = null; } ++lee.agentStreamGen;
    const running = d.thread.state === 'working' || d.thread.state === 'waiting';
    lee.agentThread = d.active; lee.agentBusy = running; lee.agentTitle = titleText(d.thread.title);
    const input = $('#agentprompt'); if (input) input.value = lee.agentThreadDrafts.get(id) || '';
    const live = await paintAgentThread(d.active);
    await refreshAgentThreads(); updateAgentRunstrip(); loadAgentModels().catch(() => {});
    if (running) { setAgentStatus('working'); agentListen(d.active, live?.seq || 0); }
    else { setAgentStatus('ready'); await rehydrateAgentLive(); }
    input?.focus();
  } catch (e) { status(String(e.message || e), 'err'); await refreshAgentThreads(); }
  finally { picked(); }
}
async function leeAgentThreadRename(id = lee.agentThread) {
  if (!id) return;
  const row = (lee.agentThreadRows || []).find(t => t.id === id);
  const title = await textDialog('Rename conversation', 'Conversation title', row ? titleText(row.title) : '');
  if (title == null) return;
  try { const d = await post('/agent/thread/title', {thread: id, title});
        if (id === lee.agentThread) lee.agentTitle = titleText(d.thread.title);
        await refreshAgentThreads(); }
  catch (e) { status(String(e.message || e), 'err'); }
}
async function leeAgentThreadClose(id = lee.agentThread) {
  if (!id) return; const closing = id;
  try {
    const d = await post('/agent/thread/close', {thread:closing}); lee.agentThreadDrafts.delete(closing);
    paintAgentThreads(d); const log = $('#agentlog'); if (log) { dropCodeSurfaces(log); log.innerHTML = ''; } if (d.active) { const active = d.active; lee.agentThread = ''; await leeAgentThreadSwitch(active); }
  } catch (e) { status(String(e.message || e), 'err'); }
}
// The rehydrated banner survives `restoreAgentLive`, which round-trips the pane through innerHTML:
// an id in an onclick attribute outlives that, a bound listener does not.
window.leeAgentNew = leeAgentNew; window.leeAgentThreadsToggle = leeAgentThreadsToggle;
window.leeAgentThreadOpen = leeAgentThreadOpen; window.leeAgentReshape = leeAgentReshape; window.leeAgentAttend = leeAgentAttend;
window.leeAgentThreadMute = leeAgentThreadMute; window.leeAgentThreadSwitch = leeAgentThreadSwitch;
window.leeAgentThreadRename = leeAgentThreadRename; window.leeAgentThreadClose = leeAgentThreadClose;
window.refreshAgentThreads = refreshAgentThreads;
window.leeAgentResume = leeAgentResume;
window.leeAgentHistory = leeAgentHistory;
window.rehydrateAgentLive = rehydrateAgentLive; window.paintAgentThread = paintAgentThread;

async function leeAgentState() {
  try {
    const [draft, saved, template] = await Promise.all([api('/agent/state/draft'), api('/agent/states'), api('/agent/state/template')]);
    // Every workspace saves into one store, so this list has always held other projects' charters.
    // The row says which layer it was written for and which folders it was written in, because a
    // title and a date are not enough to reuse one deliberately.
    const stateRow = s => `<button class="lee-agent-state-row${s.mine ? ' mine' : ''}" data-id="${esc(s.id)}">` +
      `<strong>${esc(s.title)}</strong>` +
      `<span class="lee-state-origin">${s.layer ? `<em>${esc(s.layer)}</em>` : ''}` +
      `${s.where ? `<span>${esc(s.where)}</span>` : '<span class="lee-dim">no folder recorded</span>'}` +
      `${s.mine ? '<span class="lee-state-here">this project</span>' : ''}</span>` +
      `<span>${esc(new Date((s.added_at || 0) * 1000).toLocaleString())}</span></button>`;
    const rows = (saved.states || []).map(stateRow).join('');
    const box = modal(`<div class="lee-mhead">Agent state<span class="sub">remembered rules that stay visible and follow the code</span></div>` +
      `<section class="lee-agent-state-onboard${saved.active ? ' configured' : ''}"${saved.active ? ' hidden' : ''}><div><strong>Start with a worked template</strong>` +
      `<span>Describe what you want this agent to do. The configured summary model fills a complete charter using only tools that are actually installed.</span></div>` +
      `<input class="lee-input" id="agentstateintent" placeholder="e.g. Maintain this Python project; inspect before editing and run focused tests">` +
      `<button class="lee-btn go" data-bootstrap>Generate my charter</button><button class="lee-btn" data-template>Use blank template</button></section>` +
      `<div class="lee-agent-state-grid"><section><div class="lee-agent-state-controls"><label>Where this applies<select class="lee-select" id="agentstatelayer">` +
      `${['organization','project','task','preferences','branch','ephemeral'].map(x => `<option value="${x}"${x === 'task' ? ' selected' : ''}>${x}</option>`).join('')}</select></label>` +
      `<label class="lee-state-enabled" title="Silence this layer without deleting what it holds">` +
      `<input type="checkbox" id="agentstateenabled"><span>Enabled</span></label>` +
      `<button class="lee-btn" data-update>Refresh from code</button><button class="lee-btn" data-diagnose>Check state</button></div>` +
      `<label class="lee-fieldlabel">Title<input class="lee-input" id="agentstatetitle" value="Working state"></label>` +
      `<div class="lee-state-editor-head"><span>Markdown charter</span><button class="lee-btn" data-add-rule>Add rule</button>` +
      `<button class="lee-btn" data-add-check>Add verification</button><button class="lee-btn" data-add-tool>Add tool route</button>` +
      `<button class="lee-btn" data-preview-state>Preview</button></div><div class="lee-agent-state-editor" id="agentstatetext"></div>` +
      `<div class="lee-agent-state-help" data-state-help>Keep goal, constraints, progress, decisions, next steps, and critical context. ` +
      `This is an explicit briefing, not hidden chat history.</div></section>` +
      `<section class="lee-agent-state-reference"><nav class="lee-state-ref-tabs"><button class="active" data-ref="conversation">Conversation</button>` +
      `<button data-ref="tools">Tools</button><button data-ref="preview">Preview</button><button data-ref="saved">Saved</button></nav>` +
      `<div class="lee-state-ref-pane active" data-ref-pane="conversation"><pre class="lee-agent-conversation">${esc(draft.conversation || '(no completed turns)')}</pre></div>` +
      `<div class="lee-state-ref-pane" data-ref-pane="tools"><div class="lee-state-tool-list">${template.tools.map(t => `<button data-tool-name="${esc(t.name)}"><strong>${esc(t.name)}</strong><span>${esc(t.group)} · ${esc(t.description)}</span></button>`).join('')}</div></div>` +
      `<div class="lee-state-ref-pane lee-md" data-ref-pane="preview" id="agentstatepreview"></div>` +
      `<div class="lee-state-ref-pane" data-ref-pane="saved"><label class="lee-fieldlabel">Show<select class="lee-select" id="agentstatescope">` +
      `<option value="everywhere">every project on this machine</option><option value="project">this project only</option></select></label>` +
      `<div class="lee-agent-state-list">${rows || '<div class="lee-dim">No saved states yet.</div>'}</div></div></section></div>` +
      `<div class="lee-mfoot"><button class="lee-btn go" data-save>Save to memory + activate</button>` +
      `<button class="lee-btn" data-activate>Activate without saving</button>` +
      `<button class="lee-btn warn" data-clear>Clear this layer</button>` +
      `<span class="lee-dim">Drag the lower-right edge to resize · double-click the title to expand.</span></div>`,
      null, null, {className: 'lee-agent-state-modal', storageKey: 'agent-state'});
    const text = $('#agentstatetext', box), layer = $('#agentstatelayer', box);
    const stateView = createEditor(text, {doc: '', lang: 'markdown', lineNums: true, lintPath: '<agent-state>',
      placeholder: '# Agent charter\n\nDescribe how this agent should work…'});
    Object.defineProperty(text, 'value', {get: () => LeeCM.getDoc(stateView), set: value => LeeCM.setDoc(stateView, String(value || ''))});
    const insertStateMarkdown = value => {
      const at = LeeCM.cursor(stateView), prefix = at && !text.value.slice(0, at).endsWith('\n') ? '\n' : '';
      LeeCM.replaceRange(stateView, at, at, prefix + value); LeeCM.focus(stateView);
    };
    const showReference = name => {
      $$('.lee-state-ref-tabs button', box).forEach(b => b.classList.toggle('active', b.dataset.ref === name));
      $$('.lee-state-ref-pane', box).forEach(p => p.classList.toggle('active', p.dataset.refPane === name));
      if (name === 'preview') renderMarkdown($('#agentstatepreview', box), text.value, true);
    };
    $$('.lee-state-ref-tabs button', box).forEach(b => b.onclick = () => showReference(b.dataset.ref));
    $('[data-preview-state]', box).onclick = () => showReference('preview');
    $('[data-add-rule]', box).onclick = () => insertStateMarkdown('\n- [Write a clear, testable rule.]');
    $('[data-add-check]', box).onclick = () => insertStateMarkdown('\n- [Describe the evidence required before completion.]');
    $('[data-add-tool]', box).onclick = () => showReference('tools');
    $$('.lee-state-tool-list button', box).forEach(b => b.onclick = () => {
      const tool = template.tools.find(t => t.name === b.dataset.toolName);
      insertStateMarkdown(`\n- ${tool.name} → ${tool.description}`); showReference('preview');
    });
    const layers = {...(saved.layers || {})};
    const layerRow = () => layers[layer.value] || {text: '', enabled: true};
    const enabledBox = $('#agentstateenabled', box);
    // The badge names the state in force. Nothing in force is nothing to name.
    const anyActive = () => Object.values(layers).some(l => String(l.text || '').trim() && l.enabled !== false);
    const paintBadge = () => {
      const badge = $('#agentnames');
      if (badge && !anyActive()) { badge.textContent = ''; badge.title = ''; }
    };
    const loadLayer = () => {
      text.value = layerRow().text || (layer.value === 'task' ? draft.state : '');
      enabledBox.checked = layerRow().enabled !== false;
    };
    loadLayer(); layer.onchange = loadLayer;
    /* Off rather than gone, so a layer can be silenced for one piece of work and put back without
       being written again. It sends the layer's stored text and not the editor's: a draft nobody
       activated must not reach the briefing because a checkbox moved. */
    enabledBox.onchange = async () => {
      const row = layerRow(), on = enabledBox.checked;
      try {
        await post('/agent/state/activate', {text: row.text || '', layer: layer.value, enabled: on});
        layers[layer.value] = {...row, text: row.text || '', enabled: on};
        paintBadge(); status(`${layer.value} layer ${on ? 'enabled' : 'disabled'}`, 'ok');
      } catch (e) { enabledBox.checked = !on; status(e.message || String(e), 'err'); }
    };
    $('[data-template]', box).onclick = async () => {
      const d = await api('/agent/state/template'); text.value = d.template + '\n\n' + d.catalog;
      $('[data-state-help]', box).textContent = 'Template loaded. Replace bracketed prompts, then activate or save it.';
    };
    $('[data-bootstrap]', box).onclick = async () => {
      const button = $('[data-bootstrap]', box); button.disabled = true; button.textContent = 'Generating…';
      try {
        const d = await post('/agent/state/bootstrap', {intent: $('#agentstateintent', box).value});
        text.value = d.text; $('#agentstatetitle', box).value = ($('#agentstateintent', box).value || 'Workspace agent charter').slice(0, 80);
        $('[data-state-help]', box).textContent = `Drafted with ${d.model}. Read every rule, then save + activate.`;
      } catch (e) { $('[data-state-help]', box).textContent = e.message || String(e); }
      finally { button.disabled = false; button.textContent = 'Generate my charter'; }
    };
    $('[data-update]', box).onclick = async () => {
      const d = await post('/agent/state/update', {current: text.value, conversation: draft.conversation});
      const review = modal(`<div class="lee-mhead">Review proposed state update<span class="sub">nothing changes until you apply it</span></div>` +
        `<div class="lee-diff lee-state-update-diff">${diffHtml(d.diff.rows || [])}</div>` +
        `<div class="lee-mfoot"><button class="lee-btn go" data-accept>Apply to editor</button>` +
        `<button class="lee-btn" data-reject>Keep current state</button></div>`);
      $('[data-accept]', review).onclick = () => { text.value = d.text; review.remove(); $('[data-state-help]', box).textContent = 'Proposed update applied to the editor. Review before saving or activating.'; };
      $('[data-reject]', review).onclick = () => review.remove();
    };
    $('[data-diagnose]', box).onclick = async () => {
      const d = await post('/agent/state/diagnostics', {text: text.value});
      $('[data-state-help]', box).textContent = `${d.tokens} tokens` +
        (d.missing_paths.length ? ` · missing paths: ${d.missing_paths.join(', ')}` : ' · paths current') +
        (d.duplicate_headings.length ? ` · duplicate headings: ${d.duplicate_headings.join(', ')}` : '');
    };
    // The badge is what says which charter the agent is carrying, so it takes the state's own
    // heading rather than the word `active`.
    const stateLabel = () => (text.value.split('\n').find(l => l.startsWith('#') && l.replace(/^#+\s*/, '').trim())
      || '').replace(/^#+\s*/, '').trim().slice(0, 40) || 'state active';
    const markActive = () => {
      const badge = $('#agentnames'); if (badge) { badge.textContent = stateLabel(); badge.title = 'active starting state'; }
      $('.lee-agent-welcome', $('#agentlog'))?.remove();
    };
    // A save that fails leaves the state in the editor and the box open, with the reason on it.
    // Neither button said anything when the request was refused, so a person pressed a control that
    // did nothing: the packaged app cannot reach memory at all, and this is how that looked.
    const attempt = async (button, run) => {
      const el = $(`[data-${button}]`, box), label = el.textContent;
      el.disabled = true; el.textContent = 'Working…';
      try { await run(); box.remove(); }
      catch (e) {
        const why = e.message || String(e);
        $('[data-state-help]', box).textContent = why;
        status(why, 'err');
      }
      finally { el.disabled = false; el.textContent = label; }
    };
    $('[data-save]', box).onclick = () => attempt('save', async () => {
      const d = await post('/agent/state/save', {title: $('#agentstatetitle', box).value, text: text.value, layer: layer.value, activate: true});
      markActive(); status(d.saved?.skipped ? 'state already in memory and activated' : 'state saved to memory and activated', 'ok');
    });
    $('[data-activate]', box).onclick = () => attempt('activate', async () => {
      await post('/agent/state/activate', {text: text.value, layer: layer.value});
      markActive(); status('starting state activated without saving', 'ok');
    });
    /* Not through `attempt`, which closes the box on success: emptying a layer is a thing to watch
       happen, and the editor showing what it now holds is the whole of the confirmation. */
    $('[data-clear]', box).onclick = async () => {
      const el = $('[data-clear]', box), label = el.textContent;
      el.disabled = true; el.textContent = 'Working…';
      try {
        await post('/agent/state/activate', {text: '', layer: layer.value, enabled: true});
        layers[layer.value] = {text: '', enabled: true, source: 'user'};
        if (layer.value === 'task') draft.state = '';   // or leaving and returning refills it
        text.value = ''; enabledBox.checked = true; paintBadge();
        $('[data-state-help]', box).textContent = `The ${layer.value} layer is empty; nothing from it reaches the briefing.`;
        status(`${layer.value} layer cleared`, 'ok');
      } catch (e) {
        const why = e.message || String(e);
        $('[data-state-help]', box).textContent = why; status(why, 'err');
      }
      finally { el.disabled = false; el.textContent = label; }
    };
    const bindStateRows = () => $$('.lee-agent-state-row', box).forEach(row => row.onclick = async () => {
      const compared = await post('/agent/state/compare', {id: row.dataset.id, current: text.value});
      const review = modal(`<div class="lee-mhead">Compare state revision<span class="sub">choose how this revision enters ${esc(layer.value)}</span></div>` +
        `<div class="lee-diff lee-state-update-diff">${diffHtml(compared.diff.rows || [])}</div>` +
        `<div class="lee-mfoot"><button class="lee-btn go" data-replace>Replace + activate</button>` +
        `<button class="lee-btn" data-merge>Merge below current</button><button class="lee-btn" data-cancel>Cancel</button></div>`);
      $('[data-replace]', review).onclick = async () => {
        const d = await post('/agent/state/load', {id: row.dataset.id, layer: layer.value}); text.value = d.state;
        review.remove(); $$('.lee-agent-state-row', box).forEach(x => x.classList.toggle('active', x === row)); status('saved revision restored and active', 'ok');
      };
      $('[data-merge]', review).onclick = () => { text.value = text.value.trim() + '\n\n' + compared.state.trim(); review.remove(); status('revision merged into editor; review before activation', 'ok'); };
      $('[data-cancel]', review).onclick = () => review.remove();
    });
    bindStateRows();
    $('#agentstatescope', box).onchange = async e => {
      const list = $('.lee-agent-state-list', box);
      const d = await api('/agent/states?scope=' + encodeURIComponent(e.target.value));
      list.innerHTML = (d.states || []).map(stateRow).join('') ||
        `<div class="lee-dim">No states saved ${e.target.value === 'project' ? 'in this project' : 'yet'}.</div>`;
      bindStateRows();
    };
  } catch (e) { status(e.message || String(e), 'err'); }
}
window.leeAgentState = leeAgentState;

function renderSessionCells(log, d) {
  if (d.path) log.insertAdjacentHTML('beforeend', `<div class="lee-session-path">${esc(d.path)}</div>`);
  for (const [i, cell] of (d.cells || []).entries()) {
    if (cell.cell_type === 'markdown') {
      const md = document.createElement('div'); md.className = 'lee-session-markdown';
      renderMarkdown(md, cell.source); log.appendChild(md); continue;
    }
    const details = document.createElement('details'); details.className = 'lee-session-code';
    const first = (cell.source || '').split('\n').find(x => x.trim()) || '(empty code cell)';
    details.innerHTML = `<summary><span>run ${i + 1}</span><code>${esc(first)}</code>` +
      `<span class="lee-agent-step-chevron" aria-hidden="true"></span></summary><div class="lee-session-code-body"></div>`;
    let mounted = false;
    details.ontoggle = () => {
      if (!details.open || mounted) return; mounted = true;
      requestAnimationFrame(() => mountCodeSurface($('.lee-session-code-body', details), cell.source, 'python', true));
    };
    log.appendChild(details);
  }
}

function agentLog(html, host = null) {
  const log = $('#agentlog');
  if (host) { host.insertAdjacentHTML('beforeend', html); stickAgentLog(log); return; }
  // Never use `innerHTML +=`: it reparses every existing child and silently detaches every
  // checkpoint, fork, rollback, CodeMirror and disclosure handler already in the log.
  log.insertAdjacentHTML('beforeend', html);
  stickAgentLog(log);
}

/* A write pauses Rishi's tool loop until it is answered. The question stays in the agent pane
 * rather than a modal, so the rest of the IDE is usable while the model waits. The same event
 * serves agent-chat and notebook prompt-cell streams. */
// These are the log's own nodes. A detached one is held forever.
const approvalCards = new Map();
/* A checkpoint the run never answered keeps `proposed`, and a card holding one is never folded and
   never trimmed, so the turn it sits in cannot be collapsed for the rest of the session. `done`
   retires the ones its own stream raised: the run that asked is over, so nothing can answer them. */
function retireCheckpoints(ids) {
  for (const id of ids || []) {
    const card = approvalCards.get(id);
    if (!card?.classList.contains('proposed')) continue;
    card.classList.remove('proposed'); card.classList.add('refused');
    $$('button', card).forEach(b => b.disabled = true);
    const state = $('.lee-checkpoint-title small', card);
    if (state) state.textContent = 'The turn ended before this ran';
  }
}
function proposalArgs(card) {
  const schema = card._schema, args = {};
  for (const field of (schema?.fields || [])) {
    const input = card.querySelector(`[data-field="${CSS.escape(field.name)}"]`);
    if (!input) continue;
    if (field.kind === 'boolean') args[field.name] = input.checked;
    else {
      const raw = input._leeView ? LeeCM.getDoc(input._leeView) : input.value;
      if (!field.required && raw === '') continue;
      if (field.kind === 'integer') args[field.name] = Number.parseInt(raw, 10);
      else if (field.kind === 'number') args[field.name] = Number.parseFloat(raw);
      else if (field.kind === 'json') {
        try { args[field.name] = JSON.parse(raw); }
        catch (e) { throw new Error(`${field.name} must be JSON: ${e.message}`); }
      }
      else args[field.name] = raw;
      if (field.required && (args[field.name] === '' || Number.isNaN(args[field.name])))
        throw new Error(`${field.name} is required`);
    }
  }
  return args;
}
function proposalFields(schema, args) {
  return (schema?.fields || []).map(field => {
    const raw = args[field.name] ?? field.default ?? '', required = field.required ? ' required' : '';
    const value = typeof raw === 'object' && raw !== null ? JSON.stringify(raw, null, 2) : raw;
    if (field.kind === 'boolean')
      return `<label class="lee-proposal-check"><input type="checkbox" data-field="${esc(field.name)}"${value ? ' checked' : ''}>${esc(field.name)}</label>`;
    const type = field.kind === 'integer' || field.kind === 'number' ? 'number' : 'text';
    const control = field.multiline
      ? `<div class="lee-proposal-field-editor" data-field="${esc(field.name)}" data-value="${esc(value)}"${required}></div>`
      : `<input class="lee-input" type="${type}" data-field="${esc(field.name)}" value="${esc(value)}"${required}>`;
    return `<label><span>${esc(field.name)}${field.required ? ' *' : ''}</span>${control}</label>`;
  }).join('');
}
function mountProposalEditors(card) {
  $$('[data-field-editor], .lee-proposal-field-editor', card).forEach(host => {
    if (host._leeView) return;
    const field = host.dataset.field || '', tool = $('[data-tool]', card)?.value || '';
    const kind = (card._schema?.fields || []).find(f => f.name === field)?.kind;
    const lang = kind === 'json' ? 'json' : field === 'text' || field === 'source'
      ? codeLang('', proposalArgsSafe(card).path || '') : tool.includes('python') ? 'python' : 'text';
    host._leeView = createEditor(host, {doc: host.dataset.value || '', lang, lineNums: true});
  });
}
function proposalArgsSafe(card) { try { return proposalArgs(card); } catch (_) { return {}; } }
function groupedToolOptions(schemas, selected) {
  const groups = new Map();
  for (const schema of schemas) {
    if (!groups.has(schema.group)) groups.set(schema.group, []);
    groups.get(schema.group).push(schema);
  }
  return [...groups].map(([group, tools]) => `<optgroup label="${esc(group)}">` + tools.map(tool =>
    `<option value="${esc(tool.name)}"${tool.name === selected ? ' selected' : ''}>${esc(tool.name)} — ${esc(tool.description)}</option>`).join('') + '</optgroup>').join('');
}
function previewContent(preview) {
  if (!preview) return '<div class="lee-proposal-empty">No preview available.</div>';
  if (preview.kind === 'diff') return `<div class="lee-diff">${diffHtml(preview.rows || [])}</div>`;
  return `<pre class="lee-proposal-code">${esc(preview.text || '')}</pre>`;
}
async function refreshProposalPreview(card) {
  const host = $('[data-preview-body]', card), error = $('.lee-proposal-error', card);
  if (!host) return;
  try {
    const args = card._previewArgs || proposalArgs(card), tool = $('[data-tool]', card).value;
    card._previewArgs = null;
    host.innerHTML = '<div class="lee-proposal-loading"><i></i><i></i><i></i><span>Building dry-run preview</span></div>';
    const d = await post('/agent/tool-preview', {tool, args, thread: lee.agentThread || ''});
    host.innerHTML = (card._loopNote ? `<div class="lee-dim">${esc(card._loopNote)}</div>` : '') + previewContent(d.preview); error.textContent = '';
  } catch (e) { host.innerHTML = ''; error.textContent = e.message || String(e); }
}
function checkpointExplanation(tool, args = {}, schema = {}) {
  const target = args.path ? compactPath(args.path) : args.cwd ? compactPath(args.cwd) : '';
  if (tool === 'run_shell') return {
    title: 'Command approval',
    lead: `The agent wants to run a shell command${target ? ` in ${target}` : ''}. Nothing runs until you approve.`,
    detail: 'Commands can read files, use the network, start processes, and change data. Open “Edit call” to review or change the command.'};
  if (tool === 'run_python') return {
    title: 'Python approval', lead: 'The agent wants to execute Python in the live workspace. Nothing runs until you approve.',
    detail: 'This can change variables and process state. Open “Edit call” to review or change the code.'};
  if (schema.changes_state) return {
    title: 'Change approval', lead: `The agent wants to change ${target || 'the workspace'}. Nothing changes until you approve.`,
    detail: 'Review the preview, edit the call if needed, then choose how far the agent may continue.'};
  return {title: 'Tool approval', lead: `The agent wants to use ${tool}. Nothing runs until you approve.`,
    detail: 'This is a read-only call. You can review its inputs now and run it again later with different inputs.'};
}
function checkpointResult(detail, ok, secs) {
  const result = document.createElement('details'); result.className = 'lee-checkpoint-result';
  const summary = document.createElement('summary');
  summary.innerHTML = `<strong>${ok ? 'Completed' : 'Failed'}</strong><span>${Number(secs || 0).toFixed(1)}s · View output</span>`;
  const pre = document.createElement('pre'); pre.textContent = readableDetail(detail);
  result.append(summary, pre); return result;
}
function showApproval(a, destination = null) {
  if (lee.observer || !a?.id || approvalCards.has(a.id)) return;
  leePane('right', true); leeRight('agent');
  if (lee.agentView && lee.agentView !== 'live') restoreAgentLive();
  const log = $('#agentlog'); if (!log) return;
  /* `pollApproval` and a notebook prompt cell both call this with no destination, and a checkpoint
     that lands beside the turns instead of in the one it belongs to is a checkpoint nobody finds. */
  const host = destination || (lee.agentTimeline?.root?.isConnected ? lee.agentTimeline.root : null)
    || turnBody(latestAgentTurn()) || log;
  const schemas = a.schemas || [], byName = new Map(schemas.map(s => [s.name, s]));
  const card = document.createElement('section');
  card.className = 'lee-approval lee-proposal proposed'; card.dataset.id = a.id; card.dataset.tool = a.tool; card.tabIndex = -1;
  // the row this checkpoint replaces is in the turn it belongs to, not the last one anywhere in the log
  const pendingRow = [...$$('.lee-agent-step.pending', host.closest('.lee-agent-turn') || log)].at(-1);
  if (pendingRow) { pendingRow.hidden = true; card._activityRow = pendingRow; }
  card._schema = byName.get(a.tool) || {name: a.tool, fields: Object.keys(a.args || {}).map(name => ({name, kind: 'string'}))};
  // the repeat guard's line comes with the ask, not with a dry-run preview: kept, so an edit does not lose it
  card._loopNote = (String(a.preview || '').match(/^the same call .*? running -- allow it\?/) || [''])[0];
  const explanation = checkpointExplanation(a.tool, a.args, card._schema);
  card.innerHTML = `<header class="lee-approval-head"><span class="lee-proposal-mark" aria-hidden="true"></span>` +
    `<span class="lee-checkpoint-title"><strong>${esc(explanation.title)}</strong><small><b>${esc(a.control || 'guided')}</b> paused for your decision</small></span>` +
    `<kbd>↵ run&nbsp;&nbsp; ⇧↵ don’t run&nbsp;&nbsp; E edit&nbsp;&nbsp; S steer</kbd></header>` +
    `<div class="lee-checkpoint-intro"><strong>${esc(explanation.lead)}</strong><span>${esc(explanation.detail)}</span></div>` +
    `<div class="lee-approval-summary"><span>Agent’s reason</span>${esc(a.summary || '')}</div>` +
    `<nav class="lee-proposal-tabs"><button class="active" data-tab="preview">What will happen</button>` +
    `<button data-tab="call">Edit call</button><button data-tab="json">Raw JSON</button></nav>` +
    `<section class="lee-proposal-pane active" data-pane="preview"><div data-preview-body>` +
    `<pre class="lee-proposal-code">${esc(a.preview || '')}</pre></div></section>` +
    `<section class="lee-proposal-pane" data-pane="call"><div class="lee-proposal-fields">` +
    `<label><span>Tool</span><select class="lee-select" data-tool>${groupedToolOptions(schemas, a.tool)}</select></label>` +
    `<div data-schema-fields>${proposalFields(card._schema, a.args || {})}</div></div></section>` +
    `<section class="lee-proposal-pane" data-pane="json"><textarea class="lee-input lee-proposal-json" data-args spellcheck="false"></textarea></section>` +
    `<div class="lee-proposal-error" role="alert"></div>` +
    `<div class="lee-proposal-steer"><label><span>If you don’t run it, tell the agent what to do instead</span>` +
    `<input class="lee-input" data-note placeholder="Optional: use another approach, inspect a different file…"></label></div>` +
    `<footer class="lee-approval-actions"><button class="lee-btn warn" data-ok="0">Don’t run</button>` +
    `<span class="lee-spacer"></span><label class="lee-run-policy-label"><span>After this</span>` +
    `<select class="lee-select" data-run-policy title="how far the agent may continue without another pause">` +
    `<option value="once">Pause again</option><option value="count:3">Allow next 3 tools</option>` +
    `<option value="until_write">Allow reads, pause before changes</option><option value="reads">Allow read-only tools</option>` +
    `<option value="until_failure">Continue until a tool fails</option><option value="completion">Continue until finished</option>` +
    `<option value="approve_session">Trust changes for this session</option></select></label>` +
    `<button class="lee-btn" data-always title="run it, and save this command or path so it never asks again">Always allow</button>` +
    `<button class="lee-btn go" data-ok="1">Run this tool</button></footer>`;
  const raw = $('[data-args]', card); raw.value = JSON.stringify(a.args || {}, null, 2); mountProposalEditors(card);
  const switchTab = name => {
    $$('.lee-proposal-tabs button', card).forEach(b => b.classList.toggle('active', b.dataset.tab === name));
    $$('.lee-proposal-pane', card).forEach(p => p.classList.toggle('active', p.dataset.pane === name));
    if (name === 'json') { try { raw.value = JSON.stringify(proposalArgs(card), null, 2); } catch (_) {} }
    if (name === 'preview') refreshProposalPreview(card);
  };
  $$('.lee-proposal-tabs button', card).forEach(b => b.onclick = () => {
    if (b.dataset.tab === 'preview') { try { card._previewArgs = argsFromUI(); } catch (_) {} }
    switchTab(b.dataset.tab);
  });
  $('[data-tool]', card).onchange = e => {
    card._schema = byName.get(e.target.value) || {name: e.target.value, fields: []};
    $('[data-schema-fields]', card).innerHTML = proposalFields(card._schema, {});
    mountProposalEditors(card); switchTab('call');
  };
  const argsFromUI = () => {
    if ($('[data-pane="json"]', card).classList.contains('active')) {
      const parsed = JSON.parse(raw.value || '{}');
      if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error('arguments must be a JSON object');
      return parsed;
    }
    return proposalArgs(card);
  };
  const answer = async (ok, always = false) => {
    const buttons = $$('button', card), error = $('.lee-proposal-error', card);
    // Two different HITL decisions, not one form with a boolean. Approval executes the displayed
    // call, so it must parse and validate edits. Rejection executes no call, so malformed or
    // missing arguments must never trap the user.
    let args = null, tool = null, changed = false;
    if (ok) {
      try {
        args = argsFromUI(); tool = $('[data-tool]', card).value || a.tool;
        changed = tool !== a.tool || JSON.stringify(args) !== JSON.stringify(a.args || {});
        error.textContent = '';
      } catch (e) { switchTab('call'); error.textContent = e.message || String(e); return; }
    }
    buttons.forEach(b => b.disabled = true);
    try {
      const note = $('[data-note]', card).value || '';
      if (ok) {
        const spec = $('[data-run-policy]', card).value, [policy, count] = spec.split(':');
        if (!['once', 'approve_session'].includes(policy))
          await post('/agent/run-policy', {policy, count: Number(count || 1)});
      }
      const session = ok && $('[data-run-policy]', card).value === 'approve_session';
      if (always) await post('/agent/approval/always', {id: a.id, tool, args, thread: lee.agentThread || ''});
      else await post('/agent/approve', {id: a.id, ok, note, session, tool, args, thread: lee.agentThread || ''});
      card.classList.remove('proposed'); card.classList.add(ok ? 'running' : 'refused'); if (changed) card.classList.add('edited');
      const checkpointState = $('.lee-checkpoint-title small', card);
      if (checkpointState) checkpointState.textContent = ok
        ? (changed ? 'You edited the call · running now' : 'You approved it · running now')
        : 'You chose not to run it';
      const resolvedTool = ok ? tool : a.tool;
      card.dataset.tool = resolvedTool; card.dataset.resolvedTool = resolvedTool;
      card.dataset.retryable = String(!!byName.get(resolvedTool)?.retryable);
      $('.lee-approval-actions', card).innerHTML = `<span>${ok ? (changed ? 'Edited call is running' : 'Running approved tool') : (note ? 'Not run · your direction was sent to the agent' : 'Not run')}</span>` +
        (ok && card.dataset.retryable === 'true' ? `<button class="lee-btn" data-retry title="Run this read-only tool again without changing the conversation">Run again</button>` : '') +
        (ok && ['edit_file', 'create_file', 'replace_text', 'edit_cell'].includes(resolvedTool) ? `<button class="lee-btn warn" data-rollback disabled>Undo file change</button>` : '');
      $('[data-retry]', card)?.addEventListener('click', () => retryProposal(card, resolvedTool, args));
      const rollback = $('[data-rollback]', card);
      if (rollback) { setTimeout(() => rollback.disabled = false, 700); rollback.onclick = () => rollbackProposal(card, a.id); }
      status(ok ? `${changed ? 'edited and ran' : 'ran'} ${resolvedTool}` : `rejected ${a.tool}`, ok ? 'ok' : 'err');
    } catch (e) { buttons.forEach(b => b.disabled = false); error.textContent = String(e.message || e); }
  };
  $('[data-ok="1"]', card).onclick = () => answer(true);
  $('[data-ok="0"]', card).onclick = () => answer(false);
  $('[data-always]', card).onclick = () => answer(true, true);
  card.onkeydown = e => {
    if (e.target.matches('input, textarea, select') && e.key !== 'Escape' && !(e.key === 'Enter' && (e.metaKey || e.ctrlKey))) return;
    if (e.key === 'Enter' && e.shiftKey) { e.preventDefault(); answer(false); }
    else if (e.key === 'Enter') { e.preventDefault(); answer(true); }
    else if (/^[1-6]$/.test(e.key)) { e.preventDefault(); $('[data-run-policy]', card).selectedIndex = Number(e.key) - 1; }
    else if (e.key.toLowerCase() === 'e') { e.preventDefault(); switchTab('call'); card.querySelector('[data-field], [data-tool]')?.focus(); }
    else if (e.key.toLowerCase() === 's') { e.preventDefault(); $('[data-note]', card).focus(); }
    else if (e.key === 'Escape') switchTab('preview');
  };
  host.appendChild(card); approvalCards.set(a.id, card);
  unfoldForApproval(card);      // focus and the ↵ / E / S keys do nothing inside a folded turn
  card.focus(); log.scrollTop = log.scrollHeight;
  refreshProposalPreview(card); updateAgentRunstrip({waiting: a.tool});
  status(`${a.tool} is waiting at a checkpoint`, 'err');
}

function decodeResponseEntities(text) {
  const area = document.createElement('textarea'); let value = String(text || '');
  for (let i = 0; i < 3 && /&(?:#\d+|#x[\da-f]+|amp|lt|gt|quot|apos);/i.test(value); i++) {
    area.innerHTML = value; const decoded = area.value;
    if (decoded === value) break; value = decoded;
  }
  return value;
}
function editableResponse(raw) {
  const tools = '(?:run_shell|run_python|inspect_python|grep|search_code|similar_code|ls|view_file|create_file|edit_file|replace_text|view_cell|edit_cell|add_cell|web_search|read_url|research|delegate_[\\w-]+)';
  let text = decodeResponseEntities(raw)
    .replace(/\n?\s*<details>\s*<summary>result<\/summary>[\s\S]*?<\/details>\s*/gi, '\n');
  text = text.split('\n').filter(line =>
    !new RegExp(`^\\s*-\\s*[^\\w<]{0,6}\\s*<code>${tools}\\s*\\(`, 'i').test(line) &&
    !/^\s*(?:#{1,4}\s*)?what i did\s*$/i.test(line)).join('\n');
  return text.replace(/\n{3,}/g, '\n\n').trim();
}

function markTurnUndone(out, bar, files, revise) {
  /* `rollback_turn` restores files and does not touch model history, so the turn is marked rather
     than deleted. The agent still carries it.

     Scoped to the turn's card. This used to walk siblings until it hit a `.lee-user-message`, and
     the bar sits either inside the timeline or beside it depending on whether the turn ended on
     prose or on a tool call, so the marked range differed between two turns that were undone the
     same way. */
  const card = bar.closest('.lee-agent-turn');
  for (const node of (card ? $$('.lee-agent-turn-body > *', card) : [out])) {
    if (node !== bar) node.classList.add('lee-turn-undone');   // the bar carries the explanation
  }
  card?.classList.add('lee-turn-undone-card');
  const note = document.createElement('span');
  note.textContent = `${files} file${files === 1 ? '' : 's'} restored · the agent still remembers this turn`;
  bar.classList.add('lee-turn-undone-bar');
  bar.replaceChildren(note, ...(revise ? [revise] : []));
  return bar;
}

/* The pane is round-tripped through `innerHTML` by the history toggle, a rehydrate, a resume and
   every thread switch, and a bound listener does not survive that. The turn these controls act on
   is written into the DOM, and one delegated listener on the log dispatches them. */
/* A turn that ended on a tool call has no prose, and its files are still its own to restore, so
   the bar is not gated on there being an answer. Every button says why it is unavailable, and
   `known` distinguishes "this turn changed nothing" from "this process no longer holds a boundary
   for it", which is what a turn from before a restart or from past `MAX_CHECKPOINTS` looks like. */
/* An unavailable control is muted and states its reason on the row. `.lee-btn` has no disabled
   appearance in the stylesheet, so a dead button was pixel-identical to a live one down to the
   pointer cursor, and the only explanation was a `title` nobody hovers in the packaged app: the
   report was "I click edit and undo, nothing happens". The reason is carried here rather than in
   `lee-ide.css` so the bar explains itself wherever it is painted. */
const REVISION_MUTED = 'opacity:.4;cursor:default';
const REVISION_NOTE = 'flex:1 0 100%;order:9;margin-top:5px;color:var(--lee-fg4);font:9px/1.45 var(--lee-mono);white-space:normal';
function addResponseRevision(out, turnId, raw, capabilities = {}) {
  if (!turnId || !out) return;
  const bar = document.createElement('div'); bar.className = 'lee-response-revision';
  const files = capabilities.files || [], gone = capabilities.known === false;
  const unheld = 'this conversation was not run in this session, so there is no turn boundary to act on';
  const controls = [
    ['revise', 'lee-btn', 'Edit what agent remembers', !!capabilities.revisable,
     'Correct this answer and continue the next turn from your version',
     gone ? unheld : 'this turn failed before an assistant response entered model history'],
    ['unsay', 'lee-btn', 'Undo from conversation', !!capabilities.branchable,
     'Forget this turn: branch the conversation to just before it, keeping it in history',
     gone ? unheld : 'this turn has no captured boundary to branch at'],
    ['fork', 'lee-btn', 'Branch from here', !!capabilities.branchable,
     'Start a branch that continues from this turn, leaving this conversation as it is',
     gone ? unheld : 'this turn has no captured boundary to branch at'],
    ['undo', 'lee-btn warn', 'Restore files', !!capabilities.undoable,
     `Restore ${files.length} file${files.length === 1 ? '' : 's'} changed by this turn${gitWritesNote(capabilities.git)}`,
     gone ? unheld : 'this turn made no reversible file or git changes']];
  const off = controls.filter(c => !c[3]);
  bar.dataset.turn = turnId;
  bar.dataset.revisable = capabilities.revisable ? '1' : '';
  bar.dataset.undoable = capabilities.undoable ? '1' : '';
  bar.dataset.files = String(files.length);
  bar.innerHTML = `<span>turn ${esc(turnId.split(':').at(-1))}</span>` +
    controls.map(([key, cls, label, on, why, cant]) =>
      `<button class="${cls}" data-${key} title="${esc(on ? why : `Unavailable: ${cant}`)}"` +
      `${on ? '' : ` disabled style="${REVISION_MUTED}"`}>${esc(label)}</button>`).join('') +
    // one shared sentence when nothing is held for the turn, rather than the same one three times
    (off.length ? `<small data-unavailable style="${REVISION_NOTE}">${esc(gone ? `Unavailable: ${unheld}`
      : off.map(c => `${c[2]} is unavailable: ${c[5]}`).join(' · '))}</small>` : '');
  /* Last in the turn's body rather than straight after the answer. A turn that ended on prose has
     that prose inside `.lee-agent-timeline`, so `out.after` put the bar in there too -- inside the
     element `markTurnUndone` dims, which dimmed the bar's own explanation of why. The answer is
     marked instead, because a class survives the `innerHTML` round-trips this pane takes and a
     sibling relationship does not. */
  out.classList.add('lee-turn-answer'); out.dataset.answerFor = turnId;
  const body = out.closest('.lee-agent-turn-body');
  if (body) body.appendChild(bar); else out.after(bar);
  bindResponseRevisions(bar.closest('#agentlog') || $('#agentlog'));
}

/* What the reply said, recovered from the DOM rather than from a closure: `renderMarkdown` keeps
   the markdown it rendered, which is the one copy that survives an `innerHTML` round-trip. */
/* Paired by turn id rather than by position. One card can hold two answers: a feed left following
   after `done` paints a turn another tab or the CLI started into the card already on screen, and
   `.lee-turn-answer` alone then resolved both bars to the first one. */
const turnAnswer = bar => {
  const card = bar.closest('.lee-agent-turn') || document, id = bar.dataset.turn || '';
  return (id && $(`.lee-turn-answer[data-answer-for="${CSS.escape(id)}"]`, card))
    || $('.lee-turn-answer', card) || bar.previousElementSibling;
};
function turnReplyText(bar) {
  const reply = turnAnswer(bar);
  return reply?.dataset?.markdown ?? reply?.textContent ?? '';
}

function responseTurn(bar) {
  return {turnId: bar.dataset.turn || '', out: turnAnswer(bar),
          raw: turnReplyText(bar), files: Number(bar.dataset.files || 0),
          revisable: !!bar.dataset.revisable, undoable: !!bar.dataset.undoable};
}

async function unsayTurn(bar) {
  const {turnId, out, files, undoable, revisable} = responseTurn(bar);
  const short = turnId.split(':').at(-1);
  /* Undoing the conversation and restoring the files are separate promises. This one is only
     about what the model remembers, so it must never claim to have changed anything on disk. */
  const also = undoable && files
    ? await confirmDialog('Undo from conversation',
        `Branch this conversation to just before turn ${short}. Also restore ${files} file${files === 1 ? '' : 's'} it changed?`,
        'undo and restore files', 'undo conversation only')
    : await confirmDialog('Undo from conversation',
        `Branch this conversation to just before turn ${short}. The turn stays in history.`,
        'undo conversation');
  if (!also) return;
  try { await post('/agent/undo-turn', {thread: lee.agentThread, turn_id: turnId}); }
  catch (e) { return status(e.message || String(e), 'err'); }
  let restored = null;
  if (also === true) {
    try { restored = await post('/agent/rollback-turn', {turn_id: turnId, thread: lee.agentThread || ''}); }
    catch (e) { status(`undone from the conversation; these files were not restored: ${e.message || e}`, 'err'); }
  }
  markTurnUndone(out, bar, (restored?.paths || []).length, revisable ? $('[data-revise]', bar) : null);
  noteHeldRestores(await reloadRestored(restored?.paths || []));
  await refreshAgentThreads();
  status(restored ? `undone from the conversation · ${(restored.paths || []).length} file(s) restored`
                  : 'undone from the conversation; files left as they are', 'ok');
}

/* Naming what was left alone matters more here than anywhere else: a tab held back still holds the
   version from before the restore, and the person is the only one who can decide between the two. */
const noteHeldRestores = held => held.length && status(
  `${held.length} file${held.length === 1 ? '' : 's'} with unsaved edits ${held.length === 1 ? 'was' : 'were'} not reloaded: `
  + held.map(p => p.split('/').pop()).join(', '), 'err');

/* A turn's git writes carry gheasy undo tokens; the rollback applies them before the files. */
function gitWritesNote(git) {
  const n = (git || []).filter(g => g.undo).length;
  return n ? ` and undo ${n} git write${n === 1 ? '' : 's'}` : '';
}
function gitWritesList(git) {
  const rows = (git || []).filter(g => g.undo);
  return rows.length ? '\n\nGit writes undone, newest first:\n' + rows.slice().reverse().map(g =>
    `• ${g.tool}${g.summary ? ' · ' + g.summary : ''}${g.undoes ? ' · undoes ' + g.undoes : ''}`).join('\n') +
    '\n\nRefused, touching nothing, if HEAD moved since or the tree holds uncommitted changes outside this turn\'s files.' : '';
}
async function restoreTurnFiles(bar) {
  const {turnId, out, revisable} = responseTurn(bar);
  {
    try {
      const tx = await api('/agent/turn-transaction?turn_id=' + encodeURIComponent(turnId) +
        (lee.agentThread ? '&thread=' + encodeURIComponent(lee.agentThread) : ''));
      const files = tx.transaction.files || [], warning = (tx.transaction.irreversible || []).length
        ? `\n\nCannot undo external effects: ${tx.transaction.irreversible.join(', ')}` : '';
      if (!await confirmDialog('Restore files changed by this turn', `Restore ${files.length} file${files.length === 1 ? '' : 's'} changed by this turn${gitWritesNote(tx.transaction.git)}?${gitWritesList(tx.transaction.git)}${warning}`, 'restore files')) return;
      const d = await post('/agent/rollback-turn', {turn_id: turnId, thread: lee.agentThread || ''});
      // Marked before the files are reloaded, so a reload that raises still shows the turn undone.
      markTurnUndone(out, bar, (d.paths || []).length, revisable ? $('[data-revise]', bar) : null);
      noteHeldRestores(await reloadRestored(d.paths || []));
      status('turn changes rolled back', 'ok');
    } catch (e) { status(e.message || String(e), 'err'); }
  }
}

function reviseTurn(bar) {
  const {turnId, out, raw} = responseTurn(bar);
  {
    const original = editableResponse(raw);
    const box = modal(`<div class="lee-mhead">Shape the next turn<span class="sub">edit what the agent remembers, not the files it touched</span></div>` +
      `<section class="lee-revision-explainer"><strong>You are correcting the conversation.</strong>` +
      `<span>Tools will not run again and files will not change. The agent’s next reply will continue as if it gave your edited answer. The original stays in history.</span></section>` +
      `<div class="lee-revision-layout"><label class="lee-revision-editor"><span>Answer the agent should remember <b>Markdown</b></span>` +
      `<textarea class="lee-keyedit" data-revision spellcheck="true" aria-label="answer the agent should remember"></textarea></label>` +
      `<section class="lee-revision-preview"><header><span>How it will read</span><small>live preview</small></header>` +
      `<div class="lee-md" data-revision-preview></div></section></div>` +
      `<div class="lee-mfoot"><button class="lee-btn" data-cancel>Keep original</button><span class="lee-spacer"></span>` +
      `<span class="lee-dim">Creates a new conversation branch</span><button class="lee-btn go" data-apply>Use edited answer</button></div>`,
      null, null, {className: 'lee-response-editor-modal', storageKey: 'response-editor'});
    const editor = $('[data-revision]', box), preview = $('[data-revision-preview]', box);
    editor.value = original;
    let previewTimer = null;
    const paint = () => { clearTimeout(previewTimer); previewTimer = setTimeout(() => renderMarkdown(preview, editor.value), 90); };
    editor.addEventListener('input', paint); paint();
    $('[data-cancel]', box).onclick = () => box.remove();
    $('[data-apply]', box).onclick = async () => {
      const text = editor.value.trim();
      if (!text) return status('the remembered answer cannot be empty', 'err');
      const d = await post('/agent/revise', {turn_id: turnId, text});
      renderMarkdown(out, text); out.dataset.userRevised = '1';
      bar.innerHTML = `<span>Your edited answer now guides the next turn · ${esc(d.branch_id)}</span>`;
      box.remove(); status('edited answer is now the active conversation branch', 'ok');
    };
  }
}

/* One listener, on the log element itself. Its contents are replaced constantly and it is not, so
   a listener here outlives every repaint where a per-button binding does not. */
function bindResponseRevisions(log) {
  if (!log || log._leeRevisionsBound) return;
  log._leeRevisionsBound = true;
  log.addEventListener('click', e => {
    const button = e.target.closest?.('.lee-response-revision button'); if (!button) return;
    const bar = button.closest('.lee-response-revision');
    if (!bar?.dataset.turn || button.disabled) return;
    if (button.hasAttribute('data-unsay')) unsayTurn(bar);
    else if (button.hasAttribute('data-undo')) restoreTurnFiles(bar);
    else if (button.hasAttribute('data-revise')) reviseTurn(bar);
    else if (button.hasAttribute('data-fork')) leeAgentForkTurn(bar.dataset.turn, lee.agentThread);
  });
}

async function retryProposal(card, tool, args) {
  const copy = structuredClone(args), number = card.querySelectorAll('.lee-proposal-branch').length + 1;
  try {
    const d = await post('/agent/retry-tool', {tool, args: copy, thread: lee.agentThread || ''});
    const row = document.createElement('section'); row.className = 'lee-proposal-branch';
    row.innerHTML = `<header><strong>Rerun ${number}</strong><span>${esc(tool)} completed with the inputs shown below</span>` +
      `<button class="lee-btn" data-edit-retry>Edit inputs and run</button></header>` +
      `<details class="lee-checkpoint-result"><summary><strong>Result</strong><span>View output</span></summary><pre>${esc(d.result)}</pre></details>` +
      `<footer><span>This result is not in the conversation yet.</span><button class="lee-btn" data-use-result>Use in next message</button></footer>`;
    $('[data-edit-retry]', row).onclick = async () => {
      const text = await textDialog('Run tool with different inputs', 'Arguments as JSON', JSON.stringify(copy, null, 2)); if (!text) return;
      try { await retryProposal(card, tool, JSON.parse(text)); }
      catch (e) { status(e.message || String(e), 'err'); }
    };
    $('[data-use-result]', row).onclick = () => {
      const prompt = $('#agentprompt'); if (!prompt) return;
      const result = String(d.result || '').slice(0, 20_000);
      prompt.value = `Use this rerun of ${tool} to reconsider your previous answer. Explain what changed and what I should do next.\n\n<rerun-result tool="${tool}">\n${result}\n</rerun-result>`;
      prompt.dispatchEvent(new Event('input', {bubbles: true})); prompt.focus();
      row.scrollIntoView({block: 'nearest'}); status('rerun result added to your next message; review it before sending', 'ok');
    };
    card.appendChild(row); status(`rerun ${number} completed; previous conversation is unchanged`, 'ok');
  } catch (e) { status(e.message || String(e), 'err'); }
}
async function rollbackProposal(card, id) {
  try {
    const d = await post('/agent/rollback-tool', {id, thread: lee.agentThread || ''});
    card.classList.add('rolled-back'); $('[data-rollback]', card).disabled = true;
    status(`${d.path.split('/').pop()} rolled back`, 'ok');
    if (d.path === lee.path && !$('.lee-tab.active')?.classList.contains('dirty')) await takeDiskVersion(d.path);
  } catch (e) { status(e.message || String(e), 'err'); }
}
function runPolicyLabel(policy) {
  if (!policy) return '';
  const names = {once: 'next call', count: `next ${policy.remaining}`, until_write: 'until next write',
    reads: 'read-only calls', until_failure: 'until failure', completion: 'to completion'};
  return names[policy.kind] || policy.kind;
}
/* Most callers pass no state, and a steer is not theirs to forget. Only a payload carrying
   `queued_steer` may change it, so the acknowledgement survives until the server says the steer
   was taken. */
//: The run states `Run.terminal` covers. A row in one of them is history, not work in progress.
const TERMINAL = new Set(['completed', 'cancelled', 'detached', 'terminated', 'failed']);

function updateAgentRunstrip(state = {}) {
  const strip = $('#agentrunstrip'); if (!strip) return;
  if ('queued_steer' in state) setQueuedSteer(state.queued_steer || '');
  if ('runs' in state) lee.agentRuns = state.runs || [];
  const runs = lee.agentRuns || [];
  const flattenRuns = rows => rows.flatMap(r => [r, ...flattenRuns(r.children || [])]);
  const flat = flattenRuns(runs);
  // A row that has ended is history. Counting them as work kept the strip up over a finished
  // delegation and left the composer in steer mode, so the next thing typed was offered to a run
  // that was already over instead of being sent as a turn.
  const active = flat.some(r => !TERMINAL.has(r.state));
  strip.hidden = !active && !lee.agentBusy && !state.waiting;
  updateAgentSendMode(active || lee.agentBusy ? 'steer' : 'send');
  const rootLabel = state.waiting ? `Waiting · ${state.waiting}`
    : lee.queuedSteer ? 'Steering queued · applies after the current tool call'
    : state.run_policy ? `Running automatically · ${runPolicyLabel(state.run_policy)}`
    : `${($('#agentcontrol')?.value || 'guided').toUpperCase()} · agent working`;
  // A fan-out's rows tell each other apart only by what each subagent was asked, and the buttons'
  // row leaves that a dozen characters. The rows take the width and the buttons go under them.
  strip.classList.toggle('fanned', flat.length > 1);
  $('.lee-agent-run-state', strip).innerHTML = flat.length ? flat.map(r => {
    // `ended`, where the run has one: a finished run's clock counted on, and read as still working.
    const done = TERMINAL.has(r.state);
    const until = r.ended || (done ? r.started : Date.now() / 1000);
    const elapsed = r.started ? Math.max(0, until - r.started) : 0;
    const clock = `${Math.floor(elapsed / 60)}:${String(Math.floor(elapsed % 60)).padStart(2, '0')}`;
    // the model repeats on every row of a fan-out; the question does not
    const who = r.kind === 'child' ? `subagent ${(r.model || '').split('/').pop()}`.trim() : (r.model || 'Agent');
    // The root's line says what the agent is doing, which is not what a delegate was asked. A child
    // with no question of its own borrowed it and read as the agent working.
    const what = r.question || (r.kind === 'child' ? 'delegated' : rootLabel);
    const label = r.state === 'cancelling' ? `Cancelling ${who}…` : `${what} · ${who}`;
    return `<span class="lee-agent-run${r.kind === 'child' ? ' child' : ''}"><span>${esc(label)}</span>` +
      `<time>${esc(clock)}</time>` +
      (r.kind === 'child' ? `<button type="button" data-open-subs>Open</button><button type="button" data-watch-run="${esc(r.id)}" data-title="${esc(r.question || r.id)}">Watch</button>` : '') +
      (done ? '' : `<button type="button" data-stop-run="${esc(r.id)}">Stop</button>`) + `</span>`;
  }).join('') : esc(rootLabel);
  $$('[data-open-subs]', strip).forEach(b => b.onclick = e => { e.stopPropagation(); leeSubagents(); });
  $$('[data-watch-run]', strip).forEach(b => b.onclick = e => { e.stopPropagation(); leeWatchRun(b.dataset.watchRun, b.dataset.title); });
  $$('[data-stop-run]', strip).forEach(btn => btn.onclick = async e => {
    e.stopPropagation();
    try { const d = await post(`/agent/runs/${encodeURIComponent(btn.dataset.stopRun)}/cancel${agentThreadQuery()}`, {}); updateAgentRunstrip({runs: (await api(`/agent/runs${agentThreadQuery()}`)).runs}); status(d.state, 'ok'); }
    catch (err) { status(err.message || String(err), 'err'); }
  });
}
// a run belongs to the conversation the pane shows; without it the server picks its own active one
const agentThreadQuery = () => lee.agentThread ? `?thread=${encodeURIComponent(lee.agentThread)}` : '';
async function pauseAgentAfterCurrent() {
  const d = await post('/agent/run-policy', {policy: 'pause'}); updateAgentRunstrip(d);
  status('agent will pause before the next call', 'ok');
}
function updateAgentSendMode(mode = 'send') {
  const button = $('#agentsend'); if (!button) return;
  const label = mode === 'force' ? 'Stop and send next' : mode === 'steer' ? 'Steer after this call' : 'Send';
  button.textContent = label; button.setAttribute('aria-label', label);
  button.title = mode === 'send' ? 'send this as a turn'
    : 'hand this to the model after the current call — shift-click to stop the run and send it now';
}
/* A steer belongs inside the turn's timeline rather than after it, among the chunks and tool rows
   it came between. */
const steerHost = log => lee.agentTimeline?.root?.isConnected ? lee.agentTimeline.root : log;
/* The local reply and the feed event carry the same steer, so the same text twice with nothing
   between it is one. Two identical steers a person really sent have a turn's work in between. */
const steerDrawn = (log, text) => steerHost(log).lastElementChild?.dataset?.steer === text;
function placeSteer(log, card, text) {
  card.dataset.steer = text;
  const live = lee.agentTimeline;
  // no live timeline: the turn's own body, so a steer is never a stray sibling between two turns
  if (live?.root?.isConnected) live.append(card);
  else (turnBody(currentAgentTurn()) || log).appendChild(card);
  log.scrollTop = log.scrollHeight;
  return card;
}
function setQueuedSteer(text, shown = '', cancel = false) {
  lee.queuedSteer = text || '';
  const log = $('#agentlog'), old = $('#agentqueuedsteer'); if (!log) return;
  if (!lee.queuedSteer) {
    if (cancel) { old?.remove(); return; }
    /* A steer that has been taken is no longer the queued one, and the id has to go with the state.
       It used to stay on the card, so the next steer found it here and returned without drawing,
       and a queued one after that was written into it: the agent acted on a message the transcript
       never showed. */
    if (old) { old.id = ''; old.classList.remove('queued'); $('[data-cancel-steer]', old)?.remove(); }
    if (old && old.dataset.steer === shown) return;
    /* Steering against a waiting approval answers it there and then, so it is never queued and
       nothing recorded what was said. The local reply and the feed event both arrive, and the
       same text twice with nothing between it is one steer. */
    if (shown && !steerDrawn(log, shown)) placeSteer(log, userMessage(shown), shown);
    return;
  }
  const card = old || userMessage(shown || lee.queuedSteer);
  card.id = 'agentqueuedsteer'; card.classList.add('queued');
  if (!old) placeSteer(log, card, shown || lee.queuedSteer);
  let button = $('[data-cancel-steer]', card);
  if (!button) { button = document.createElement('button'); button.type = 'button'; button.dataset.cancelSteer = '1'; button.textContent = 'Cancel'; card.appendChild(button); }
  button.onclick = async () => {
    try { await post('/agent/steer', {cancel: true}); } catch (e) { return status(e.message || String(e), 'err'); }
    setQueuedSteer('', '', true); updateAgentRunstrip();
  };
  log.scrollTop = log.scrollHeight;
}
async function leeQueueSteer() {
  const input = $('#agentprompt'), text = input?.value.trim();
  if (!text) return status('write what to steer towards first', 'err');
  try {
    const d = await post('/agent/steer', {text}); input.value = '';
    setQueuedSteer(d.queued_steer || '', text); updateAgentRunstrip(d);
    status(d.queued_steer ? 'steering queued after the current tool call' : 'steering sent to the agent', 'ok');
  } catch (e) { input.value = text; status(e.message || String(e), 'err'); }
}
async function leeForceSteer() {
  const input = $('#agentprompt'), text = input?.value.trim();
  if (!lee.agentBusy) return status('nothing is running to stop; send it as a turn instead', 'err');
  if (!text) return status('write what to send next first', 'err');
  updateAgentSendMode('force');
  try {
    const d = await post('/agent/steer', {text, force: true});
    lee.agentBusy = false; lee.agentRuns = []; input.value = text; setQueuedSteer('', '', true); updateAgentRunstrip({runs: []});
    status(d.run?.state === 'detached' ? 'provider detached; sending the saved draft' : 'run cancelled; sending the saved draft', 'ok');
    return sendAgent();
  } catch (e) { input.value = text; updateAgentSendMode('steer'); status(e.message || String(e), 'err'); }
}

async function pollApproval() {
  try {
    const r = await api('/agent/approval');
    if (r.pending) showApproval(r.pending);
  } catch (_) {}
}

/* An approval must not sit unseen while the model works. Idle, only a background job raises one.

   Two seconds while busy, not the 750ms this used to run at: the turn's own SSE feed carries an
   `approval` event and paints the checkpoint the moment it is raised, so this poll is the backstop
   for a run whose stream this tab is not attached to. At 750ms it was four requests a second of the
   process the window is drawing in, for something the stream had already said. */
const APPROVAL_GAP = {hidden: 5000, busy: 2000, idle: 5000};
async function approvalLoop() {
  if (lee.observer) return;
  if (!document.hidden) await pollApproval();
  // attention is about the conversations a person is *not* looking at, so it is polled even hidden
  try { await refreshAgentThreads(); } catch (_) {}
  setTimeout(approvalLoop, document.hidden ? APPROVAL_GAP.hidden
                         : lee.agentBusy ? APPROVAL_GAP.busy : APPROVAL_GAP.idle);
}

function readableDetail(value) {
  const text = String(value || '');
  try { return JSON.stringify(JSON.parse(text), null, 2); } catch { return text; }
}
/* `user_steering` is what the person said when they refused a call. Drawn as an ordinary step it
   read `user_steering(instruction='The user rejected this tool c…')`, the harness describing
   itself with the direction hidden behind a chevron. The full instruction stays in the panel. */
const STEER_TOOL = 'user_steering';
function steerSaid(args) {
  const raw = String((args || {}).instruction || '');
  const said = raw.split(/User direction:\s*/)[1];      // what was typed, when anything was
  return (said || '').trim() ||
    (/stopped this turn/i.test(raw) ? 'stopped the turn' : 'rejected that call');
}
function renderAgentStep(row, a) {
  const wasOpen = row.open;
  for (const v of (row._leeViews || [])) try { LeeCM.destroy(v); } catch {}
  row._leeViews = []; row.innerHTML = '';
  const deferredEditors = [];
  const steered = (a.tool || '') === STEER_TOOL;
  row.className = `lee-agent-step kind-${a.kind || 'tool'} ${a.done ? (a.ok ? 'done' : 'failed') : 'pending'}`
    + (steered ? ' lee-agent-steer-step' : '');
  const summary = document.createElement('summary');
  summary.innerHTML = `<span class="lee-agent-step-state" aria-hidden="true"></span>` +
    `<span class="lee-agent-step-copy">${steered ? `<strong>You</strong> ${esc(steerSaid(a.args))}`
      : esc(a.summary || a.tool || 'Working')}</span>` +
    // a delegation is the one step whose work happened somewhere this row cannot show
    ((a.kind || '') === 'delegate' ? `<button class="lee-agent-step-open" type="button" data-open-sub` +
      ` title="open this delegation: what its sub-agents did, and steer one that is still going">open</button>` : '') +
    `<span class="lee-agent-step-meta">${steered ? 'steered'
      : a.done && a.secs ? esc(Number(a.secs).toFixed(1) + 's') : esc(a.kind || '')}</span>` +
    `<span class="lee-agent-step-chevron" aria-hidden="true"></span>`;
  // inside a `summary`, a click is the disclosure's unless it is taken
  $('[data-open-sub]', summary)?.addEventListener('click', e => {
    e.preventDefault(); e.stopPropagation(); leeSubagents(a.action_id || a.id || '');
  });
  row.appendChild(summary);

  const args = a.args && typeof a.args === 'object' ? a.args : {};
  const code = typeof args.code === 'string' ? args.code : '';
  const rest = Object.entries(args).filter(([k, v]) => k !== 'code' && v != null && String(v) !== '');
  if (code || rest.length || a.detail) {
    const panel = document.createElement('div'); panel.className = 'lee-agent-step-detail';
    if (rest.length) {
      const dl = document.createElement('dl');
      for (const [key, value] of rest) {
        const dt = document.createElement('dt'), dd = document.createElement('dd');
        dt.textContent = key; dd.textContent = typeof value === 'string' ? value : JSON.stringify(value);
        dl.append(dt, dd);
      }
      panel.appendChild(dl);
    }
    if (code) {
      const block = document.createElement('div'); panel.appendChild(block);
      deferredEditors.push(() => row._leeViews.push(mountCodeSurface(block, code, 'python', true)));
    }
    if (a.detail) {
      const result = document.createElement('section'); result.className = 'lee-tool-result';
      const label = document.createElement('header'); label.textContent = 'result'; result.appendChild(label);
      const detail = readableDetail(a.detail);
      if (a.kind === 'view' || a.kind === 'skill') {
        const block = document.createElement('div'); result.appendChild(block);
        const path = args.path || (a.kind === 'skill' ? 'note.md' : '');
        deferredEditors.push(() => row._leeViews.push(mountCodeSurface(
          block, detail, codeLang('', path), /\.py$/i.test(path))));
      } else {
        const pre = document.createElement('pre'); pre.textContent = detail; result.appendChild(pre);
      }
      panel.appendChild(result);
    }
    row.appendChild(panel); row.open = wasOpen;
    let mounted = false;
    const mountDeferred = () => {
      if (mounted || !row.open) return;
      mounted = true; requestAnimationFrame(() => deferredEditors.forEach(fn => fn()));
    };
    row.ontoggle = mountDeferred;
    mountDeferred();
  } else { summary.classList.add('empty'); row.ontoggle = null; }
}

/* A delegated sub-agent's conversation is thrown away the moment it answers, so its recorded calls
   are the whole account of what it did. The runstrip shows one while it runs and forgets it, which
   left a failed delegation as one row of prose and nothing to look at. */
function subagentQuestions(args) {
  const raw = (args || {}).questions ?? (args || {}).question ?? '';
  try { const v = JSON.parse(raw); if (Array.isArray(v)) return v.map(String); } catch {}
  return [String(raw)].filter(Boolean);
}
function subagentRunRow(r) {
  const secs = r.started ? Math.max(0, Date.now() / 1000 - r.started) : 0;
  return `<div class="lee-subagent-run" data-run="${esc(r.id)}">` +
    `<strong>${esc(r.question || '(no question)')}</strong>` +
    `<span>${esc(r.state)} · ${esc((r.model || '').split('/').pop())} · ` +
    `${Math.floor(secs / 60)}:${String(Math.floor(secs % 60)).padStart(2, '0')}` +
    `${r.inbox ? ' · message queued' : ''}</span>` +
    `<button class="lee-btn" type="button" data-watch-run="${esc(r.id)}" data-title="${esc(r.question || r.id)}">Transcript</button>` +
    `<button class="lee-btn" type="button" data-steer-run>Message</button>` +
    `<button class="lee-btn warn" type="button" data-stop-run="${esc(r.id)}">Stop</button></div>`;
}
function paintSubagents(box, d) {
  const list = $('.lee-subagent-list', box);
  for (const row of $$('.lee-subagent-calls > details', list))
    for (const v of (row._leeViews || [])) try { LeeCM.destroy(v); } catch {}
  const cards = (d.delegations || []).map(x => {
    const calls = x.calls || [];
    // an empty list is not the same answer as "it did nothing", and the server says which
    const none = d.records_sub_calls
      ? 'This delegation recorded no tool calls.'
      : 'Nothing a sub-agent does is being recorded here, so this is not an account of what it did.';
    return `<section class="lee-subagent ${x.ok ? 'ok' : 'failed'}">` +
      `<header><strong>${esc(x.summary || x.tool)}</strong>` +
      `<span>${esc(x.done ? (x.ok ? `answered in ${Number(x.secs || 0).toFixed(1)}s` : 'failed') : 'still working')}` +
      ` · ${calls.length} recorded call${calls.length === 1 ? '' : 's'}</span></header>` +
      `<ol class="lee-subagent-questions">${subagentQuestions(x.args).map(q => `<li>${esc(q)}</li>`).join('')}</ol>` +
      `<div class="lee-subagent-calls" data-calls="${esc(x.id)}"></div>` +
      (calls.length ? '' : `<p class="lee-dim">${esc(none)}</p>`) +
      (x.detail ? `<details class="lee-subagent-answer"><summary>What it reported back</summary><pre>${esc(x.detail)}</pre></details>` : '') +
      `</section>`;
  }).join('');
  const runs = (d.runs || []).map(subagentRunRow).join('');
  list.innerHTML = (runs ? `<section class="lee-subagent running"><header><strong>Running now</strong>` +
      `<span>message one and it reads you on its next tool result</span></header>${runs}</section>` : '') +
    (cards || `<p class="lee-dim">No delegated questions in this conversation yet.</p>`);
  const drawCalls = (host, calls) => { for (const call of calls || []) {
    const row = document.createElement('details'); renderAgentStep(row, call); host.appendChild(row);
    // a nested delegation carries its own sub-agent's calls
    if (call.calls?.length) { const sub = document.createElement('div'); sub.className = 'lee-subagent-calls lee-subagent-nested'; row.appendChild(sub); drawCalls(sub, call.calls); }
  } };
  for (const x of d.delegations || []) {
    const host = $(`[data-calls="${CSS.escape(x.id)}"]`, list); if (host) drawCalls(host, x.calls);
  }
  $$('[data-stop-run]', list).forEach(b => b.onclick = async () => {
    try { await post(`/agent/runs/${encodeURIComponent(b.dataset.stopRun)}/cancel${agentThreadQuery()}`, {}); status('sub-agent stopping', 'ok'); }
    catch (e) { status(e.message || String(e), 'err'); }
  });
  $$('[data-steer-run]', list).forEach(b => b.onclick = async () => {
    const id = b.closest('.lee-subagent-run').dataset.run;
    const text = await textDialog('Message this sub-agent', 'It reads this on its next tool result', ''); if (!text) return;
    try { const d = await post(`/agent/runs/${encodeURIComponent(id)}/steer`, {text, thread: lee.agentThread || ''}); status(d.note || 'message sent', 'ok'); }
    catch (e) { status(e.message || String(e), 'err'); }
  });
  $$('[data-watch-run]', list).forEach(b => b.onclick = () => leeWatchRun(b.dataset.watchRun, b.dataset.title));
}
/* A run's transcript is a file the agent core appends to. The logs dock tails it under the `runs`
   filter, one poll a second, until the run ends; a background command's output arrives the same way. */
lee.watches = new Map();
async function leeWatchRun(runId, title = '') {
  if (!runId || lee.watches.has(runId)) { leeDock('logs'); leeLogFilter('runs'); return; }
  const w = {since: 0, title: title || runId}; lee.watches.set(runId, w);
  leeDock('logs'); leeLogFilter('runs'); leeLog('runs', `watching ${w.title}`, '', '');
  const stop = $('#logstop'); if (stop && runId.startsWith('cmd_')) { stop.hidden = false; stop.dataset.run = runId; }
  const tick = async () => {
    if (!lee.watches.has(runId)) return;
    if (!$('#bottomdock')?.classList.contains('dock-logs')) { w.timer = setTimeout(tick, 1000); return; }
    try {
      const d = await api(`/agent/runs/${encodeURIComponent(runId)}/log?since=${w.since}` + (lee.agentThread ? '&thread=' + encodeURIComponent(lee.agentThread) : ''));
      if (d.text) { w.since = d.since; leeLog('runs', w.title, d.text.replace(/\n$/, ''), ''); }
      if (d.done) { leeLog('runs', `${w.title} · ${d.state}`, '', ''); return leeWatchStop(runId); }
    } catch (e) { leeLog('runs', `${w.title} · ${e.message || e}`, '', 'err'); return leeWatchStop(runId); }
    w.timer = setTimeout(tick, 1000);
  };
  tick();
}
async function leeWatchStop(runId = '') {
  const stop = $('#logstop'), id = runId || stop?.dataset.run || '';
  if (!runId && id.startsWith('cmd_')) {
    try { const d = await post(`/agent/shell/${encodeURIComponent(id)}/stop` + (lee.agentThread ? '?thread=' + encodeURIComponent(lee.agentThread) : ''), {}); status(`${id} ${d.state}`, 'ok'); }
    catch (e) { status(e.message || String(e), 'err'); }
  }
  const w = lee.watches.get(id); if (w) { clearTimeout(w.timer); lee.watches.delete(id); }
  if (stop && stop.dataset.run === id) { stop.hidden = true; delete stop.dataset.run; }
}
window.leeWatchRun = leeWatchRun; window.leeWatchStop = leeWatchStop;
/* A delegation that finished while nobody was asking: painted when it lands, and carried into the
   next turn by the agent core itself. */
function backgroundCard(log, d) {
  const el = document.createElement('details'); el.className = `lee-agent-background ${esc(d.state || '')}`; el.open = true;
  el.innerHTML = `<summary><strong>Background result</strong><span>${esc(d.id || '')} · ${esc(d.state || '')}</span>` +
    `<i class="lee-agent-step-chevron" aria-hidden="true"></i></summary>` +
    `<p>${esc(d.question || '')}</p><pre>${esc(d.answer || '')}</pre>` +
    `<button class="lee-btn" type="button" data-watch-run="${esc(d.id || '')}">Transcript</button>`;
  $('[data-watch-run]', el).onclick = () => leeWatchRun(d.id, d.question || d.id);
  (log || $('#agentlog'))?.appendChild(el); stickAgentLog(log || $('#agentlog'));
}
async function leeApprovalRules() {
  const url = () => '/agent/approval/rules' + (lee.agentThread ? '?thread=' + encodeURIComponent(lee.agentThread) : '');
  let d; try { d = await api(url()); } catch (e) { return status(e.message || String(e), 'err'); }
  const box = modal(`<div class="lee-mhead">Approval rules<span class="sub">calls that run without asking · ${esc(d.path || 'this session only')}</span></div>` +
    `<div class="lee-rule-list"></div>`, null, null, {className: 'lee-rules-modal', storageKey: 'approvalrules'});
  const paint = rules => {
    $('.lee-rule-list', box).innerHTML = rules.length ? rules.map(([tool, pat, verdict]) =>
      `<div class="lee-rule ${esc(verdict)}"><code>${esc(tool)}</code><span>${esc(pat)}</span><em>${esc(verdict)}</em>` +
      `<button class="lee-btn warn" type="button" data-rule="${esc(JSON.stringify([tool, pat, verdict]))}">Remove</button></div>`).join('')
      : `<p class="lee-dim">No saved rules. Always allow on an approval card adds one.</p>`;
    $$('[data-rule]', box).forEach(b => b.onclick = async () => {
      try { paint((await post('/agent/approval/rules/delete', {rule: JSON.parse(b.dataset.rule), thread: lee.agentThread || ''})).rules || []); }
      catch (e) { status(e.message || String(e), 'err'); }
    });
  };
  paint(d.rules || []);
}
window.leeApprovalRules = leeApprovalRules;

async function leeSubagents(actionId = '') {
  const url = () => '/agent/subagents?action_id=' + encodeURIComponent(actionId) +
    (lee.agentThread ? '&thread=' + encodeURIComponent(lee.agentThread) : '');
  let first;
  try { first = await api(url()); } catch (e) { return status(e.message || String(e), 'err'); }
  let timer = 0;
  const box = modal(`<div class="lee-mhead">Sub-agents<span class="sub">what a delegated question actually did</span></div>` +
    `<div class="lee-subagent-list"></div>`, null, () => clearInterval(timer),
    {className: 'lee-subagent-modal', storageKey: 'subagents'});
  /* Repainted only when something actually moved. `paintSubagents` replaces the list wholesale, so
     a repaint on every tick closed every step a person had opened and dropped its CodeMirror views
     on the floor. A finished delegation never changes again, so polling stops with the last run. */
  const moved = d => JSON.stringify([d.runs, (d.delegations || []).map(x => [x.id, x.done, x.ok, x.calls.length,
    (x.calls || []).map(c => [c.id, c.done, c.ok])])]);
  let seen = moved(first);
  paintSubagents(box, first);
  const running = d => (d.runs || []).length || (d.delegations || []).some(x => !x.done);
  if (!running(first)) return;
  timer = setInterval(async () => {
    if (!box.isConnected) return clearInterval(timer);
    try {
      const d = await api(url()), now = moved(d);
      if (now !== seen) { seen = now; paintSubagents(box, d); }
      if (!running(d)) clearInterval(timer);
    } catch (_) {}
  }, 1200);
}
window.leeSubagents = leeSubagents;

// A turn gets an immediate, persistent status surface, in the agent log rather than only in the
// footer: long local inference must still look alive when the footer is out of sight.
function agentProgress(log) {
  const el = document.createElement('section');
  el.className = 'lee-agent-progress'; el.setAttribute('role', 'status'); el.setAttribute('aria-live', 'polite');
  el.innerHTML = `<div class="lee-agent-motion" aria-hidden="true"><i></i><i></i><i></i></div>` +
    `<div class="lee-agent-progress-copy"><strong>Model is working</strong>` +
    `<span class="lee-agent-phase">Preparing context</span></div>` +
    `<time class="lee-agent-elapsed">0:00</time>` +
    `<button class="lee-agent-stop" type="button">Stop</button>`;
  log.appendChild(el);
  const began = performance.now(), clock = setInterval(() => {
    // The pane rebuilds this log whole, and only `finish` clears the clock, so a strip that is
    // replaced rather than finished would be written to four times a second forever.
    if (!el.isConnected) return clearInterval(clock);
    const secs = Math.floor((performance.now() - began) / 1000);
    $('.lee-agent-elapsed', el).textContent = `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, '0')}`;
  }, 250);
  $('.lee-agent-stop', el).onclick = () => { $('.lee-agent-phase', el).textContent = 'Stopping after this step'; stopAgent(); };
  return {
    phase(text) { $('.lee-agent-phase', el).textContent = text; },
    finish(ok = true) {
      clearInterval(clock); el.classList.add(ok ? 'complete' : 'failed');
      $('.lee-agent-progress-copy strong', el).textContent = ok ? 'Response ready' : 'Model stopped';
      $('.lee-agent-phase', el).textContent = ok ? 'Finished' : 'The stream ended before completion';
      $('.lee-agent-stop', el).remove();
      setTimeout(() => el.remove(), 900);
    },
  };
}

// Slash commands and @ files are resolved inline, without sending a half-written token to the
// model. Selected files stay visible as removable chips until the turn starts.
const attachKey = r => typeof r === 'string' ? r : r?.kind === 'vault' ? `${r.vault || ''}|${r.shelf || ''}|${r.doc}`
  : `sel|${r?.path || ''}|${r?.from || ''}`;
function agentAttachList() {
  return [...lee.agentAttachments.keys(), ...lee.agentSelections.map(s => s.ref), ...lee.vaultRefs.values()];
}
window.agentAttachList = agentAttachList;
function markAgentBlocked(refs, why, kind) {
  lee.attachBlocked = new Map((refs || []).map(r => [attachKey(r), why]));
  const line = $('#agentsendline');
  if (line && why) { line.hidden = false; line.textContent = why; line.className = 'lee-vault-sendline lee-agent-sendline blocked'; line.dataset.kind = kind || ''; }
}
window.markAgentBlocked = markAgentBlocked;
/* The line above the prompt: where the attachments go for the turn model, from the route every send line uses. */
let agentSendSeq = 0;
async function checkAgentSend() {
  const line = $('#agentsendline'), atts = agentAttachList(), mine = ++agentSendSeq;
  if (!line) return;
  if (!atts.length) { line.hidden = true; lee.attachBlocked?.clear(); return; }
  const d = await vaultCall('/vault/send-check', {attach: JSON.stringify(atts)});
  if (mine !== agentSendSeq) return;
  line.hidden = false; line.dataset.kind = d.kind || '';
  line.textContent = d.ok ? d.why : d.error;
  line.className = 'lee-vault-sendline lee-agent-sendline' + (d.ok && d.check_ok ? '' : ' blocked');
  const was = [...(lee.attachBlocked?.keys() || [])].join();
  lee.attachBlocked = new Map((d.attachments || []).map(r => [attachKey(r), d.why]));
  if ([...lee.attachBlocked.keys()].join() !== was) paintAgentAttachments(false);
}
function paintAgentAttachments(check = true) {
  const host = $('#agentattachments'); if (!host) return;
  if (check) { clearTimeout(lee.__sendT); lee.__sendT = setTimeout(checkAgentSend, 150); }
  const bad = k => lee.attachBlocked?.get(k);
  const chip = (k, cls, title) => `<span class="lee-agent-attachment${cls}${bad(k) ? ' blocked' : ''}" title="${esc(bad(k) || title)}" data-attach-key="${esc(k)}">`;
  const active = lee.path ? `<span class="lee-agent-context" title="The assistant can see the active workspace and open files">` +
    `<span>active · ${esc(compactPath(lee.path))}</span></span>` : '';
  const states = lee.stateSuggestions.map(s => `<button type="button" class="lee-agent-state-suggestion" data-state-id="${esc(s.id)}" ` +
    `title="Preview and attach this remembered starting state">state · ${esc(s.title)}</button>`).join('');
  const sels = lee.agentSelections.map((s, i) =>
    `${chip(attachKey(s.ref), ' selection', s.path)}<span>${esc(s.label)}</span>` +
    `<button type="button" data-sel="${i}" aria-label="remove ${esc(s.label)}">remove</button></span>`).join('');
  const vaulted = [...lee.vaultRefs.entries()].map(([key, r]) =>
    `${chip(attachKey(r), ' vault', `${r.vault || 'vault'} · ${r.shelf || 'main'}`)}` +
    `<span>${esc(r.title)}</span>` +
    `<button type="button" data-vault-ref="${esc(key)}" aria-label="remove ${esc(r.title)}">remove</button></span>`).join('');
  host.innerHTML = active + sels + vaulted + [...lee.agentAttachments.entries()].map(([path, name]) =>
    `${chip(path, name.endsWith('/') ? ' folder' : '', path)}<span>${esc(name)}</span>` +
    `<button type="button" data-path="${esc(path)}" aria-label="remove ${esc(name)}">remove</button></span>`).join('') + states;
  $$('.lee-agent-state-suggestion', host).forEach(b => b.onclick = async () => {
    await post('/agent/state/load', {id: b.dataset.stateId, layer: 'task'});
    lee.stateSuggestions = []; paintAgentAttachments(); status('relevant state attached to this workspace', 'ok');
  });
  $$('[data-sel]', host).forEach(b => b.onclick = () => {
    lee.agentSelections.splice(+b.dataset.sel, 1); paintAgentAttachments();
  });
  $$('[data-vault-ref]', host).forEach(b => b.onclick = () => {
    lee.vaultRefs.delete(b.dataset.vaultRef); paintAgentAttachments();
  });
  $$('[data-path]', host).forEach(b => b.onclick = () => {
    const name = lee.agentAttachments.get(b.dataset.path);
    lee.agentAttachments.delete(b.dataset.path);
    // The token goes with the chip, or the prompt keeps naming something no longer attached.
    const input = $('#agentprompt');
    if (input && name) input.value = input.value.replace(new RegExp(`(^|\\s)@${name.replace(/[.*+?^${}()|[\]\\\/]/g, '\\$&')}\\s?`), '$1');
    paintAgentAttachments();
  });
}
function closeAgentSuggest() {
  const menu = $('#agentsuggest'); if (!menu) return;
  menu.hidden = true; menu.innerHTML = ''; lee.agentSuggest = []; lee.agentSuggestAt = 0;
}
function paintAgentSuggest() {
  const menu = $('#agentsuggest'); if (!menu) return;
  menu.hidden = !lee.agentSuggest.length;
  menu.innerHTML = lee.agentSuggest.map((x, i) =>
    `<button type="button" role="option" aria-selected="${i === lee.agentSuggestAt}" ` +
    `class="lee-agent-suggest-row${i === lee.agentSuggestAt ? ' active' : ''}" data-i="${i}">` +
    `<strong>${esc(x.label)}</strong><span>${esc(x.detail || '')}</span></button>`).join('');
  $$('button', menu).forEach(b => b.onclick = () => chooseAgentSuggest(+b.dataset.i));
}
function chooseAgentSuggest(i = lee.agentSuggestAt) {
  const item = lee.agentSuggest[i], input = $('#agentprompt'); if (!item || !input) return;
  // The caret is set on every branch: assigning `value` on a box that is not focused leaves it
  // at 0, so completing a command read as Home.
  if (item.kind === 'command') { input.value = `/${item.name} `; input.selectionStart = input.selectionEnd = input.value.length; }
  else if (item.kind === 'tool' || item.kind === 'skill') {
    const at = input.selectionStart, before = input.value.slice(0, at);
    const left = before.replace(/(^|\s)\/(?:[A-Za-z_][\w-]*)?$/, `$1/${item.name} `);
    input.value = left + input.value.slice(at); input.selectionStart = input.selectionEnd = left.length;
  } else if (item.kind === 'vault') {
    attachVaultRef(item);
    const at = input.selectionStart, before = input.value.slice(0, at);
    const left = before.replace(/(^|\s)@[^\s@]*$/, `$1@${item.name} `);
    input.value = left + input.value.slice(at); input.selectionStart = input.selectionEnd = left.length;
    paintAgentAttachments();
  } else {
    // The token stays. What you typed is the reference, and the chip is that reference resolved.
    lee.agentAttachments.set(item.path, item.name);
    const at = input.selectionStart, before = input.value.slice(0, at);
    const left = before.replace(/(^|\s)@[^\s@]*$/, `$1@${item.name} `);
    input.value = left + input.value.slice(at); input.selectionStart = input.selectionEnd = left.length;
    paintAgentAttachments();
  }
  closeAgentSuggest(); input.focus();
}
let agentSuggestSeq = 0, stateSuggestTimer = null, agentSuggestTimer = null;
async function suggestAgentState(text) {
  if (text.trim().length < 18 || text.trim().startsWith('/')) { lee.stateSuggestions = []; return paintAgentAttachments(); }
  try {
    const d = await api('/agent/state/suggest?q=' + encodeURIComponent(text.trim()));
    lee.stateSuggestions = (d.states || []).slice(0, 2); paintAgentAttachments();
  } catch (_) {}
}
async function updateAgentSuggest() {
  const input = $('#agentprompt'); if (!input) return;
  const before = input.value.slice(0, input.selectionStart);
  const slash = before.match(/(?:^|\s)\/([A-Za-z_][\w-]*)?$/), commandSlash = before.match(/^\s*\/([\w-]*)$/);
  const mention = before.match(/(?:^|\s)@([^\s@]*)$/); const seq = ++agentSuggestSeq;
  if (slash) {
    lee.agentVocabulary ||= await api('/agent/commands');
    if (seq !== agentSuggestSeq) return;
    const query = (slash[1] || '').toLowerCase(), vocab = lee.agentVocabulary;
    const commands = commandSlash ? (vocab.commands || []).map(c => ({kind: 'command', ...c})) : [];
    const tools = (vocab.tools || []).map(t => ({kind: 'tool', ...t}));
    const skills = (vocab.skills || []).map(s => ({kind: 'skill', ...s}));
    lee.agentSuggest = [...commands, ...tools, ...skills]
      .filter(x => x.name.toLowerCase().startsWith(query)).slice(0, 14)
      .map(x => ({...x, label: '/' + x.name, detail: `${x.kind} · ${x.help || ''}`}));
  } else if (mention) {
    // `@` means "in this project": with several checkouts open, the unscoped list is mostly files
    // from a project you are not in. `dirs` because attaching a folder says "read around here".
    // The vault answers the same `@`, because "this document" is one gesture whether the document
    // is open or filed a month ago. Both are capped short, or one source fills every visible row.
    const [f, v] = await Promise.all([
      api('/fs/find?dirs=1&scope=project&q=' + encodeURIComponent(mention[1]) + '&limit=7').catch(() => ({})),
      api('/vault/mentions?limit=5&q=' + encodeURIComponent(mention[1])).catch(() => ({}))]);
    if (seq !== agentSuggestSeq) return;
    const files = (f.hits || []).slice(0, 7).map(x => ({kind: x.kind === 'folder' ? 'folder' : 'file',
      path: x.path, name: x.name, label: '@' + x.name,
      detail: (x.kind === 'folder' ? 'folder · ' : '') + compactPath(x.path)}));
    const vaulted = (v.mentions || []).map(x => ({kind: 'vault', vault: x.vault, shelf: x.shelf,
      doc: x.doc, name: x.title, title: x.title, label: '@' + x.title, detail: 'vault · ' + x.detail}));
    lee.agentSuggest = [...files, ...vaulted];
  } else return closeAgentSuggest();
  lee.agentSuggestAt = 0; paintAgentSuggest();
}
async function leeAgentControl(control) {
  try {
    const d = await post('/agent/control', {control});
    const select = $('#agentcontrol'); if (select) select.value = d.control;
    status(`agent control: ${d.control}`, 'ok');
  } catch (e) { status(String(e.message || e), 'err'); }
}
window.leeAgentControl = leeAgentControl;

async function leeAgentAttach(path = '') {
  const value = String(path || '').trim();
  if (!value) {
    const picked = window.prompt('Workspace image path');
    if (!picked) return;
    return leeAgentAttach(picked);
  }
  try {
    const d = await post('/agent/attachment', {path: value});
    lee.agentAttachments.set(d.path, d.name || d.path.split('/').pop());
    paintAgentAttachments();
    status('image attached', 'ok');
  } catch (e) { status(String(e.message || e), 'err'); }
}
window.leeAgentAttach = leeAgentAttach;

async function attachPastedImage(blob) {
  const reader = new FileReader();
  reader.onload = async () => {
    try {
      const d = await post('/agent/attachment', {data_url: reader.result});
      lee.agentAttachments.set(d.path, d.name || d.path.split('/').pop());
      paintAgentAttachments();
      status('pasted image attached', 'ok');
    } catch (e) { status(String(e.message || e), 'err'); }
  };
  reader.readAsDataURL(blob);
}

function initAgentComposer() {
  // before the guard: a conversation with no turns paints nothing, so a paint is too late to bind
  bindAgentTurnFolds($('#agentlog'));
  const input = $('#agentprompt'); if (!input || input.dataset.composerReady) return;
  input.dataset.composerReady = '1';
  $('[data-agent-pause]')?.addEventListener('click', pauseAgentAfterCurrent);
  $('[data-agent-stop]')?.addEventListener('click', stopAgent);
  /* A one-line box with a placeholder telling you to write in it takes Enter, or it eats what you
     typed. It is not in a form and has no default action, so Enter does nothing unless it is bound
     here. */
  const notify = $('#agentnotify'), reasoning = $('#agentreasoning');
  if (reasoning) reasoning.onchange = () => prefSet('agent', 'reasoning', reasoning.value);
  // Both are settings, and settings arrive over the network: painted from the cache, then again.
  const paint = () => {
    if (notify) notify.checked = agentNotifyEnabled();
    if (reasoning) reasoning.value = prefGet('agent', 'reasoning', '') || 'auto';
  };
  paint(); agentPrefsReady().then(paint);
  const grow = () => {
    input.style.height = 'auto';
    input.style.height = Math.min(190, Math.max(64, input.scrollHeight)) + 'px';
  };
  input.addEventListener('paste', e => {
    const image = [...(e.clipboardData?.items || [])].find(item => item.type.startsWith('image/'));
    if (image) { e.preventDefault(); attachPastedImage(image.getAsFile()); return; }
    const text = e.clipboardData?.getData('text/plain')?.trim();
    if (text && /(?:^|\s)(?:~\/|\/|[A-Za-z]:[\\/]|\.\.?[\/])[^\s]+\.(?:png|jpe?g|gif|webp|bmp)(?:$|\s)/i.test(text)) {
      e.preventDefault(); leeAgentAttach(text);
    }
  });
  input.addEventListener('input', () => {
    grow();
    // Coalesced, because each call walks the project tree. `agentSuggestSeq` drops a stale answer
    // only after the work has been done.
    clearTimeout(agentSuggestTimer);
    agentSuggestTimer = setTimeout(
      () => updateAgentSuggest().catch(e => status(String(e.message || e), 'err')), 90);
    clearTimeout(stateSuggestTimer); stateSuggestTimer = setTimeout(() => suggestAgentState(input.value), 420);
  });
  grow();
  input.addEventListener('keydown', e => {
    if ($('#agentsuggest')?.hidden) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault(); const d = e.key === 'ArrowDown' ? 1 : -1;
      lee.agentSuggestAt = (lee.agentSuggestAt + d + lee.agentSuggest.length) % lee.agentSuggest.length;
      paintAgentSuggest();
    } else if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); e.stopPropagation(); chooseAgentSuggest(); }
    else if (e.key === 'Escape') { e.preventDefault(); closeAgentSuggest(); }
  });
}
async function sendAgentCommand(line) {
  // a command is a person's input and a reply, so it folds like every other exchange
  const log = $('#agentlog'); if (!log) return;
  const card = agentTurnCard({prompt: line, route: 'command'}), body = turnBody(card);
  body.appendChild(userMessage(line)); log.appendChild(card);
  try {
    const d = await post('/agent/command', {line, thread: lee.agentThread || ''});
    if (/^\/reload(?:\s|$)/.test(line)) lee.agentVocabulary = null;
    const out = document.createElement('div'); out.className = 'lee-reply lee-agent-reply'; body.appendChild(out);
    renderMarkdown(out, d.text || ''); log.scrollTop = log.scrollHeight;
    status('command finished', 'ok');
  } catch (e) { status(String(e.message || e), 'err'); }
}

/* A generated picture arrives as a data URL on the `done` event. The tool result the model
 * sees is a path, and a browser cannot draw a filename, so the bytes come separately. */
function drawTurnMedia(out, media) {
  for (const m of (media || [])) {
    const fig = document.createElement('figure');
    fig.className = 'lee-agent-media';
    fig.innerHTML = (m.mime || '').startsWith('video/')
      ? `<video controls src="${m.url}"></video>`
      : `<img src="${m.url}" alt="generated image">`;
    out.after(fig);
  }
}

function reduceAgentTimeline(events) {
  const parts = [], actions = new Map(); let prose = null;
  const seal = () => { prose = null; };
  for (const event of events || []) {
    const type = event.event || event.type, data = event.data || event;
    if (type === 'chunk') {
      if (!prose) { prose = {kind: 'prose', text: ''}; parts.push(prose); }
      prose.text += data.text || ''; continue;
    }
    if (type !== 'activity') { seal(); parts.push({kind: type, data}); continue; }
    const id = data.action_id || data.id;
    /* An update to a call already on screen is not a new position in the timeline, so only a
       call seen for the first time closes the open prose. A row with no id has no identity to
       update, so it can only ever be new, and it is still work a person did. */
    let part = id ? actions.get(id) : null;
    if (!part) {
      seal();
      part = {kind: 'activity', id: id || '', parent: data.parent_action_id || '', data, children: []};
      if (id) actions.set(id, part);
      parts.push(part);
    }
    else part.data = data;
    if (!id) continue;
    if (part.parent && actions.has(part.parent)) {
      const parent = actions.get(part.parent), at = parts.indexOf(part);
      if (at >= 0) parts.splice(at, 1);
      if (!parent.children.includes(part)) parent.children.push(part);
    }
    for (const child of [...parts]) if (child.kind === 'activity' && child.parent === id) {
      parts.splice(parts.indexOf(child), 1); if (!part.children.includes(child)) part.children.push(child);
    }
  }
  return parts;
}

/* A reply is re-rendered from the top on every pass, so the gap between passes is paid over the
   whole reply, not over the words that arrived. 32ms is right for a preview following a person's
   typing and far too eager for this: at a hundred it is text arriving ten times a second, which
   reads as continuous, for a third of the renders. */
const AGENT_RENDER_GAP = 100;
/* A hundred is still too eager once the reply is long, because every pass costs the whole of it:
   a round trip that parses and highlights the document again, an `innerHTML` write, and a
   re-measure of every code surface in it. A 20,000-character answer at a fixed gap is six hundred
   passes over an average of ten thousand characters. The gap grows with the text, which brings
   that to about a hundred and fifty passes and the work down with them.

   `tail` is what keeps the pane live in between: the characters that have arrived since the last
   render, as plain text after the rendered prose. It costs a `textContent` write and no parse, so
   words still appear at the rate they arrive. `seal` renders the stretch properly and drops it,
   and every path that ends a stretch of prose goes through `seal`. */
const AGENT_RENDER_CEILING = 1200;
const agentRenderGap = n => Math.min(AGENT_RENDER_CEILING, AGENT_RENDER_GAP + Math.round(n / 20));

function agentTimeline(root) {
  const actions = new Map(); let prose = null, tail = null, rendered = 0;
  const dropTail = () => { if (tail) { tail.remove(); tail = null; } };
  const seal = () => {
    const el = prose; prose = null; rendered = 0; dropTail();
    if (el) flushMarkdown(el);
  };
  const activity = a => {
    const id = a.action_id || a.id; if (!id) return null;
    let held = actions.get(id), row = held?.row;
    if (!row) {
      seal();
      row = document.createElement('details'); held = {row, parent: a.parent_action_id || '', children: null};
      actions.set(id, held); root.appendChild(row);
    }
    held.parent = a.parent_action_id || held.parent;
    const children = held.children; if (children) children.remove();
    renderAgentStep(row, a); if (children) { row.appendChild(children); held.children = children; }
    if (held.parent && actions.has(held.parent)) {
      const parent = actions.get(held.parent);
      parent.children ||= (() => { const box = document.createElement('div'); box.className = 'lee-agent-children'; parent.row.appendChild(box); return box; })();
      parent.children.appendChild(row);
    }
    for (const child of actions.values()) if (child.parent === id && child.row.parentElement === root) {
      held.children ||= (() => { const box = document.createElement('div'); box.className = 'lee-agent-children'; row.appendChild(box); return box; })();
      held.children.appendChild(child.row);
    }
    return row;
  };
  /* The tail exists only while there is text the render has not reached, so a stretch the render
     has caught up with is one element, as it was before any of this. Nothing before the first
     render either: a short reply is parsed within the first gap and never shows its own markup. */
  const showTail = () => {
    const rest = prose && rendered ? prose._text.slice(rendered) : '';
    if (!rest) return dropTail();
    if (!tail) { tail = document.createElement('div'); tail.className = 'lee-agent-reply-tail'; }
    tail.textContent = rest;
    if (!tail.isConnected) prose.after(tail);
  };
  // `prose !== el` is a stretch that was sealed or replaced while its render was on the wire
  const painted = (el, sent) => { if (prose !== el) return; rendered = (sent || '').length; showTail(); };
  return {root, actions, seal, activity, chunk(text) {
    if (!prose) {
      prose = document.createElement('div'); prose.className = 'lee-reply lee-agent-reply lee-timeline-prose';
      prose._text = ''; rendered = 0; root.appendChild(prose);
    }
    prose._text += text || '';
    renderMarkdown(prose, prose._text, false, painted, agentRenderGap(prose._text.length));
    showTail();
    return prose;
  }, append(node) { seal(); if (node) root.appendChild(node); return node; }};
}

function setAgentStatus(state, title) {
  const el = $('#agentstatus'); if (!el) return;
  el.classList.remove('working', 'ready', 'idle'); el.classList.add(state);
  el.title = title || (state === 'working' ? 'agent is working' : state === 'ready' ? 'agent ready' : 'agent idle');
  const dot = $('.lee-agent-status-dot', el); if (dot) dot.setAttribute('aria-label', el.title);
  const text = state === 'working' ? 'working' : state === 'ready' ? 'ready' : 'idle';
  [...el.childNodes].find(n => n.nodeType === Node.TEXT_NODE)?.replaceWith(document.createTextNode(text));
}

// The assistant's tools edit files on disk, so a turn can change what is on screen. Activity,
// answer chunks and final diffs stream independently, and each tool row is updated in place so
// pending work never stays on screen after that step has finished.
async function sendAgent(force = false) {
  if (lee.agentBusy) return force ? leeForceSteer() : leeQueueSteer();
  if (lee.agentView && lee.agentView !== 'live') restoreAgentLive();
  const el = $('#agentprompt'); if (!el || !el.value.trim()) return;
  const q = el.value.trim(); closeAgentSuggest();
  if (q.startsWith('/')) {
    try { lee.agentVocabulary ||= await api('/agent/commands'); } catch (_) {}
    const head = q.slice(1).split(/\s/, 1)[0];
    if ((lee.agentVocabulary?.commands || []).some(c => c.name === head)) return sendAgentCommand(q);
  }
  const attachments = agentAttachList();
  const reasoning = $('#agentreasoning')?.value || 'auto';
  let accepted;
  try { accepted = await post('/agent/turn', {prompt: q, attachments, reasoning, thread: lee.agentThread || ''}); }
  catch (e) {
    el.value = q;
    // a withheld attachment: its chip turns red with the reason, and nothing was sent
    if (e.body?.attachments) { markAgentBlocked(e.body.attachments, e.body.line || e.message, e.body.kind); paintAgentAttachments(); }
    return status(e.message || String(e), 'err');
  }
  lee.attachBlocked?.clear();
  el.value = ''; el.style.height = '64px';
  lee.agentAttachments.clear(); lee.agentSelections = []; lee.vaultRefs.clear(); paintAgentAttachments();
  lee.agentBusy = true; lee.agentBusyAt = Date.now(); startAgentBusyWatch(); setAgentStatus('working'); updateAgentRunstrip(); refreshAgentBudget();
  const log = $('#agentlog'); $('.lee-agent-welcome', log)?.remove();
  const card = agentTurnCard({prompt: q, model: $('#agentmodel')?.value || ''});
  turnBody(card).appendChild(userMessage(q));
  log.appendChild(card);
  foldOlderTurns(log);            // what came before is answered; this is the one being read
  trimAgentLog(log);
  stickAgentLog(log, true);       // sending a turn is asking to watch it, wherever you had scrolled
  status('model is working…');
  agentListen(accepted.thread || lee.agentThread, accepted.seq, card);
}

/* One conversation's feed, painted into the live pane. `sendAgent` calls this for the turn it
   just started; a thread switch calls it for a turn already running, replaying from the feed's
   last settled point so only the turn in flight is drawn again. */
function agentListen(thread, since, card = null) {
  const log = $('#agentlog'); if (!log) return;
  $('.lee-agent-welcome', log)?.remove();
  /* A turn already in flight when this pane attached has no card yet: its prompt is in the feed,
     and the `user` event below fills the title in. */
  if (!card) { card = agentTurnCard({model: $('#agentmodel')?.value || ''}); log.appendChild(card); trimAgentLog(log); }
  let host = turnBody(card);
  let progress = agentProgress(host);
  let timelineRoot = document.createElement('div'); timelineRoot.className = 'lee-agent-timeline';
  host.appendChild(timelineRoot); stickAgentLog(log);
  let timeline = agentTimeline(timelineRoot), seen = timeline.actions;
  // A steer is drawn by the steer block, which is not in this scope. It belongs in the turn,
  // between the prose before it and the call after, so it needs the same painter.
  lee.agentTimeline = timeline;
  let raw = '', runDone = false, lastSeq = since, body = null;
  const checkpoints = new Set();
  if (lee.agentStream) { lee.agentStream._leeStopped = true; lee.agentStream.close(); }
  const generation = ++lee.agentStreamGen; let es, reconnecting = false;
  const reconnect = ms => { if (reconnecting || generation !== lee.agentStreamGen) return; reconnecting = true; setTimeout(() => { reconnecting = false; if (generation === lee.agentStreamGen) connect(); }, ms); };
  const connect = () => {
    es = new EventSource('/agent/stream?since=' + lastSeq + '&follow=1' +
      (thread ? '&thread=' + encodeURIComponent(thread) : '')); lee.agentStream = es;
    /* EventSource fires `error` for a dropped socket as well as for a frame the server named
       `error`, and the dropped one carries no data. Parsing it would throw. */
    /* One wake of the feed hands over every row that has arrived since the last, so a burst of
       chunks used to be a full paint each: `timeline.chunk` re-rendering the whole reply, a phase
       write and a scroll write per row, of which only the last was ever seen. The prose is
       gathered and painted once a frame instead. Every other event flushes it first, because
       `seal`, `done` and the rest are ordered against the text that came before them. */
    let pending = '', frame = 0;
    const flush = () => {
      frame = 0;
      const text = pending; pending = '';
      if (!text) return;
      body = timeline.chunk(text);
      progress.phase('Writing response');
      // `chunk` renders asynchronously, so this measures the pane as it was before the text landed.
      // The real one is the `lee-markdown-rendered` listener in `live.js`; this one is for the
      // height the progress strip and the timeline rows just took.
      stickAgentLog(log);
    };
    const dedupe = (fn, streaming = false) => ev => {
      if (typeof ev.data !== 'string') return;
      let d; try { d = JSON.parse(ev.data); } catch (_) { return; }
      if (d.seq <= lastSeq) return;
      if (!streaming) flush();
      lastSeq = d.seq; fn(d, ev);
    };

  es.addEventListener('activity', dedupe(a => {
    const fresh = !seen.has(a.action_id || a.id), row = timeline.activity(a);
    if (fresh && row) row.animate([{opacity: 0, transform: 'translateY(4px)'}, {opacity: 1, transform: 'translateY(0)'}],
      {duration: 220, easing: 'cubic-bezier(.16,1,.3,1)'});
    refreshAgentBudget();
    const lifecycle = approvalCards.get(a.action_id || a.id);
    if (lifecycle && a.done) {
      lifecycle.classList.remove('running', 'proposed'); lifecycle.classList.add(a.ok ? 'complete' : 'failed');
      const actions = $('.lee-approval-actions', lifecycle);
      if (actions && !lifecycle.querySelector('.lee-checkpoint-result'))
        actions.before(checkpointResult(a.detail, a.ok, a.secs));
      const checkpointState = $('.lee-checkpoint-title small', lifecycle);
      if (checkpointState) checkpointState.textContent = a.ok ? 'Completed' : 'Tool failed';
      const actionState = $('.lee-approval-actions > span', lifecycle);
      if (actionState) actionState.innerHTML = a.ok
        ? (lifecycle.dataset.retryable === 'true'
            ? '<strong>Completed</strong><small>You can rerun this read-only tool without changing the conversation.</small>'
            : '<strong>Completed</strong><small>To run it again, ask the agent so you can review a new checkpoint.</small>')
        : '<strong>Failed</strong><small>The output above explains what the tool returned.</small>';
      updateAgentRunstrip();
    }
    if (a.done && a.ok && a.kind === 'edit' && a.args?.path) scheduleAgentFileReload(a.args.path);
    progress.phase(a.done ? 'Reviewing tool results' : (a.summary || `Running ${a.tool}`));
    stickAgentLog(log);
  }));

  /* A turn already in flight when this pane attached: its prompt is in the feed, not on screen.
     `sendAgent` replays from its own user event, so it never arrives twice. */
  es.addEventListener('user', dedupe(d => {
    // `timelineRoot`'s parent, not the log: `insertBefore` throws when the reference is not a child,
    // and the throw was swallowed after `lastSeq` had already advanced, losing the prompt for good
    timelineRoot.parentElement.insertBefore(userMessage(d.text || ''), timelineRoot);
    const title = $('.lee-agent-turn-title', card);
    if (title && title.textContent === '(no prompt)') title.textContent = String(d.text || '').replace(/\s+/g, ' ').trim();
    stickAgentLog(log);
  }));

  es.addEventListener('chunk', dedupe(d => {
    raw += d.text || ''; pending += d.text || '';
    frame ||= requestAnimationFrame(flush);
  }, true));

  es.addEventListener('approval', dedupe(d => {
    checkpoints.add(d.id);
    timeline.seal(); progress.phase('Waiting for your approval'); showApproval(d, timelineRoot);
  }));
  es.addEventListener('execution', dedupe(d => updateAgentRunstrip(d)));
  es.addEventListener('state', dedupe(d => updateAgentRunstrip(d)));
  es.addEventListener('steer', dedupe(d => {
    timeline.seal(); if ('queued_steer' in d) setQueuedSteer(d.queued_steer || '', d.text || '');
  }));
  es.addEventListener('title', dedupe(d => { if (d.title) lee.agentTitle = titleText(d.title); }));
  // arrives during `_prepare`, before the first chunk: the seeds go above this first turn's card
  es.addEventListener('warm', dedupe(d => { renderWarmStart(log, d); stickAgentLog(log); }));
  es.addEventListener('watch', dedupe(d => leeWatchRun(d.target, d.target)));
  es.addEventListener('background', dedupe(d => { timeline.seal(); backgroundCard(log, d); }));
  /* Only a stopped run is announced here. `done` still follows and owns the end of the turn, so
     this says what happened to the run and touches nothing `done` will set. */
  es.addEventListener('run', dedupe(run => {
    timeline.seal(); lee.agentRuns = (lee.agentRuns || []).filter(r => r.id !== run.id);
    updateAgentRunstrip({runs: lee.agentRuns});
    status(run.state === 'detached' ? 'provider detached; no further output will be used' : run.state, 'ok');
  }));
  es.addEventListener('compaction', dedupe(d => {
    timeline.seal(); const note = document.createElement('details'); note.className = 'lee-compaction-event';
    note.innerHTML = `<summary>Context compacted automatically · ${esc(d.strategy)} · ${esc(d.note)}</summary><pre>${esc(d.text || '')}</pre>`;
    timelineRoot.appendChild(note); progress.phase('Context compacted; continuing from checkpoint');
  }));

  es.addEventListener('error', dedupe((d, ev) => {
    ev.stopImmediatePropagation(); raw += d.message || ''; body = timeline.chunk(d.message || '');
  }));
  /* The feed no longer holds what this tab missed, so the turns come from history:
     `/agent/transcript` carries executed cells, never the conversation. Nothing on screen is
     cleared until the replacement is in hand. */
  es.addEventListener('resync', dedupe(async d => {
    es.close();
    try {
      const history = await api('/agent/history' + (thread ? '?thread=' + encodeURIComponent(thread) : '')),
            sessions = history.sessions || [];
      const group = sessions.find(s => s.id === thread) || sessions.find(s => s.id === history.current);
      const turns = await sessionTurns(group?.id);
      if (!turns.length) throw new Error('no recorded turns for this conversation');
      dropCodeSurfaces(log); log.innerHTML = ''; approvalCards.clear(); log.dataset.foldScope = '';
      progress.finish(false);   // its 250ms clock is cleared by `finish` alone, and it is replaced below
      renderTurns(log, turns, 'Recovered conversation');
      /* `renderTurns` paints durable turns only, so a turn still in flight was painted nowhere and
         the rest of it streamed into a detached root. It gets a fresh card, and everything this
         listener paints into is re-pointed at it. */
      if (!runDone) {
        card = agentTurnCard({model: d.model || $('#agentmodel')?.value || ''});
        log.appendChild(card); host = turnBody(card);
        progress = agentProgress(host);
        timelineRoot = document.createElement('div'); timelineRoot.className = 'lee-agent-timeline';
        host.appendChild(timelineRoot);
        timeline = agentTimeline(timelineRoot); seen = timeline.actions; lee.agentTimeline = timeline;
        body = null; raw = '';
        refoldAfter(log);   // the last durable turn is no longer the newest, so it may fold again
      }
      // The transcript was replaced under the reader, so there is no scroll position left to keep.
      stickAgentLog(log, true); lastSeq = d.latest; reconnect(0);
    } catch (e) {
      status('conversation replay failed; retrying without clearing the transcript', 'err');
      reconnect(1000);
    }
  }));

  es.addEventListener('done', dedupe(async d => {
    timeline.seal(); retireCheckpoints(checkpoints); runDone = true; lee.agentBusy = false; lee.agentRuns = []; setAgentStatus('ready'); progress.finish(true); updateAgentRunstrip({runs: []}); refreshAgentBudget();
    // a turn that ended on a call has no prose block, and its pictures are still its own
    const closing = body || timelineRoot;
    addResponseRevision(closing, d.turn_id, raw, d.capabilities || {}); drawTurnMedia(closing, d.media);
    const usage = usageMeta(d.usage, d.usage_label, d.model); if (usage) timelineRoot.appendChild(usage);
    for (const e of (d.edits || []))
      // into the turn's body, not `agentLog`: what this turn wrote is part of this turn
      host.insertAdjacentHTML('beforeend',
        `<div class="lee-runline"><span class="sub">✎ ${esc(e.path.split('/').pop())} ${esc(e.label)}</span></div>` +
        `<div class="lee-diff inline">${diffHtml(e.rows)}</div>`);
    if (d.turn_id) card.dataset.turn = d.turn_id;
    stickAgentLog(log);
    const tail = d.usage_label ? `${d.note || 'done'} · ${d.usage_label}` : (d.note || 'done');
    showProblems(d.problems, host);   // a turn's problems belong to that turn
    if ((d.problems || []).length) status(d.problems[d.problems.length - 1], 'err');
    else status(d.ok ? tail : (d.note || 'assistant unavailable'), d.ok ? 'ok' : 'err');
    await reloadAfterEdits(d.edits || []);
  }));

  es.onerror = () => {
    if (es._leeStopped || generation !== lee.agentStreamGen) return;
    es.close(); status(runDone ? 'connection lost; restoring conversation updates…' : 'connection lost; replaying the running turn…', 'busy'); reconnect(500);
  };
  };
  connect();
}

/* Reloading the open tab is what makes an AI edit visible without a refresh, but only when there is
 * nothing of the user's to lose. A buffer with unsaved edits is offered with the diff instead, and
 * the choice is the user's. */
/* Taking the disk version remounts the tab, which destroys the CodeMirror the caret is in: an agent
   edit or a build landing between two keystrokes took the keystrokes with it, and typing looked
   like it had stopped working. Only the two reloads nobody asked for wait for the caret to leave.
   An explicit reload, a tab switch, a refactor and a conflict resolution all go straight through
   `takeDiskVersion`, because in every one of those a person asked for exactly this. */
const editorHasFocus = () => !!document.activeElement?.closest?.('.cm-editor');
/* `key` is what stops these stacking up: the 10s poll and the `/fs/events` push both reach
   `watchOpenFile`, and without it a minute of typing over a busy tree queues a dozen reloads that
   all fire the moment the caret leaves, remounting the tab a dozen times. */
const waitingReloads = new Set();
function whenEditorIdle(fn, key = '', tries = 40) {
  if (!editorHasFocus()) { waitingReloads.delete(key); return fn(); }
  if (key && tries === 40 && waitingReloads.has(key)) return;
  if (key) waitingReloads.add(key);
  // 20s of unbroken typing and this gives up; `watchOpenFile`'s own poll comes round again.
  if (tries > 0) setTimeout(() => whenEditorIdle(fn, key, tries - 1), 500);
  else waitingReloads.delete(key);
}
function scheduleAgentFileReload(path) {
  if (path !== lee.path || $('.lee-tab.active')?.classList.contains('dirty')) return;
  clearTimeout(lee.agentReloadTimer);
  lee.agentReloadTimer = setTimeout(() => whenEditorIdle(async () => {
    if (path !== lee.path || $('.lee-tab.active')?.classList.contains('dirty')) return;
    try { await takeDiskVersion(path); status(`${path.split('/').pop()} updated from the agent edit`, 'ok'); }
    catch (e) { status(String(e.message || e), 'err'); }
  }, 'agent:' + path), 90);
}
async function watchOpenFile() {
  if (!lee.path || lee.watchingDisk || document.hidden) return;
  lee.watchingDisk = true;
  try {
    const d = await api('/tab/watch');
    if (!d || d.path !== lee.path || !lee.diskVersion) return;
    if (d.disk_version === lee.diskVersion) return;
    // Never advance the editor's base token while it is dirty. Doing so makes a missing IndexedDB
    // base fall back to the new disk version and turns an external write into our own. The old
    // token is what makes the save endpoint detect it. The diff command stays available, and a
    // clean editor follows agent, terminal and git writes live.
    if ($('.lee-tab.active')?.classList.contains('dirty')) {
      if (d.disk_version !== lee.seenDiskVersion)
        status(`${lee.path.split('/').pop()} changed on disk — keeping your unsaved buffer`, 'err');
      lee.seenDiskVersion = d.disk_version;
      return;
    }
    /* Deferred while the caret is in the editor, and `seenDiskVersion` is deliberately not advanced
       on this path: it is what tells the save endpoint an outside write happened, and moving it
       here would make the deferred change read as our own when the caret finally leaves. */
    const path = lee.path;
    whenEditorIdle(async () => {
      if (path !== lee.path || $('.lee-tab.active')?.classList.contains('dirty')) return;
      try { await takeDiskVersion(path); status(`${path.split('/').pop()} updated from disk`, 'ok'); }
      catch (_) { /* the next poll tries again */ }
    }, 'watch:' + path);
  } catch (_) {
    // Watching is convenience; a transient request failure should not interrupt editing.
  } finally { lee.watchingDisk = false; }
}

/* Every tab holding one of `paths`, not only the one on screen. `/fs/events` and `/tab/watch` both
   report the active tab alone, so a file restored under a background tab had no way to be heard
   about: the copy from before sat in `lee.buffers` and in the server's document store until the
   next `/tabs/save-all` wrote it back over the file that had just been restored.

   The server decides what it dropped, and only those are cleared here: a tab with unsaved edits is
   held rather than silently discarded, and comes back in `held` for the caller to report. */
async function forgetDiskVersions(paths, force = false) {
  const want = [...new Set((paths || []).filter(Boolean))];
  if (!want.length) return {paths: [], held: []};
  const d = await post('/tab/reload', {paths: want, force});
  for (const path of d.paths || []) {
    lee.heldSaveConflicts.delete(path);
    // Remove any durable browser draft too, or `mountTab` restores the very buffer that was dropped.
    await clearDrafts(path);
    for (const key of [...lee.buffers.keys()])
      if (key === path || key.startsWith(path + ':')) {
        lee.buffers.delete(key); lee.dirtyBuffers.delete(key);
      }
  }
  return d;
}
// Accepting disk for the tab on screen is explicit, so it takes what is there over unsaved edits.
async function takeDiskVersion(path) {
  await forgetDiskVersions([path], true);
  await mountTab();
}
/* What a rollback owes every tab holding a file it restored: the one on screen is remounted, and
   the rest read from disk when they are next shown. Returns the paths it would not touch. */
async function reloadRestored(paths) {
  const d = await forgetDiskVersions(paths);
  if ((d.paths || []).includes(lee.path)) await mountTab();
  return d.held || [];
}
async function leeReloadFromDisk() {
  const name = (lee.path || '').split('/').pop();
  if (!lee.path) return status('this tab has no file on disk', 'err');
  if ($('.lee-tab.active')?.classList.contains('dirty') &&
      !await confirmDialog(`reload ${name}`, 'This drops the unsaved edits in this tab and loads what is on disk.', 'reload')) return;
  try { await takeDiskVersion(lee.path); status(`${name} reloaded from disk`, 'ok'); }
  catch (e) { status(String(e.message || e), 'err'); }
}
async function reloadAfterEdits(edits) {
  const e = edits.find(x => x.path && x.path === lee.path);
  if (!e) return;
  if (!$('.lee-tab.active')?.classList.contains('dirty')) {
    await takeDiskVersion(e.path);
    return status(`${e.path.split('/').pop()} updated from the agent edit`, 'ok');
  }
  const m = diffModal(e.path.split('/').pop() + ' changed on disk', e.label, e.rows);
  const bar = document.createElement('div');
  bar.className = 'lee-mfoot';
  bar.innerHTML = '<button class="lee-btn" id="dtake">reload from disk</button>' +
                  '<button class="lee-btn" id="dkeep">keep my buffer</button>' +
                  '<span class="lee-dim">you have unsaved edits in this tab</span>';
  m.querySelector('.lee-modalbox').appendChild(bar);
  bar.querySelector('#dtake').onclick = async () => {
    m.remove(); await takeDiskVersion(e.path); status('loaded the agent edit from disk', 'ok');
  };
  bar.querySelector('#dkeep').onclick = () => { m.remove(); status('kept your buffer — ctrl+s overwrites', 'ok'); };
}

async function stopAgent() {
  const d = await post('/agent/stop', {thread: lee.agentThread || ''});
  updateAgentRunstrip({runs: (await api(`/agent/runs${agentThreadQuery()}`)).runs});
  status(d.ok ? d.state : d.error, d.ok ? 'ok' : 'err');
}

/* Failures with nowhere else to go: a compaction the engine refused, a completion that came back
 * empty, anything the native model layer printed instead of raising. They appear in the agent pane
 * because that is where the turn they belong to is. */
function showProblems(ps, host = null) {
  for (const p of (ps || [])) {
    if (lee.shownProblems.has(p)) continue;
    lee.shownProblems.add(p);
    agentLog(`<div class="lee-runline err"><span class="res">⚠ ${esc(p)}</span></div>`, host);
  }
}

async function agentTools() {
  const d = await api('/agent/status');
  const rows = (d.calls || []).map(c => `${c.tool}(${c.args})`).join('\n');
  agentLog(`<div class="lee-runline"><span class="sub">${esc(d.note)} · ${d.ntools} tools` +
           `${d.busy ? ' · thinking now' : ''} · context ${Math.round(100 * (d.pct_full || 0))}% full` +
           `${d.compactions ? ' · ' + d.compactions + ' compaction(s)' : ''}</span></div>` +
           (rows ? `<div class="lee-runline"><span class="code">${esc(rows)}</span></div>` : ''));
  showProblems(d.problems);
}

