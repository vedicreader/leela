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
    if (!d.ok) await loadAgentModels();
  } catch (e) { await loadAgentModels(); status(e.message || String(e), 'err'); }
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
  return `<div class="lee-setup-row" data-setup-get="${esc(o.value)}"><span><strong>${esc(o.label || o.value)}</strong>` +
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
