/* ------------------------------------------------- workflows and the release pipeline */
// Both panels are about a project rather than a file, so they ask the same question the
// source-control panel does -- which repository -- and answer it the same way: empty means
// the one the active tab is in.
const wfUI = {data: null, runs: null, env: null, catalogue: null, docker: null, open: '', view: 'graph', preview: '', busy: ''};
const relUI = {data: null, busy: '', poll: 0};
function projectRepo() { return gitUI.repo || ''; }
function projectQuery(params = {}) {
  const q = new URLSearchParams(params);
  if (projectRepo()) q.set('repo', projectRepo());
  const query = q.toString();
  return query ? `?${query}` : '';
}
function wfStatusNote(st) {
  if (!st) return '';
  if (!st.gheasy) return `<div class="lee-wf-note"><strong>Local only</strong><span>${esc(st.why)}</span><code>pip install "leela[github]"</code></div>`;
  if (!st.repo) return '<div class="lee-wf-note"><strong>No GitHub remote</strong><span>Runs and secrets need one; the files below still read.</span></div>';
  if (!st.token) return `<div class="lee-wf-note"><strong>No GITHUB_TOKEN</strong><span>Set it in Environment below and the run history appears.</span></div>`;
  return '';
}
function wfJobBox(job, run) {
  const jr = (run?.jobs || []).find(j => j.name === job.name || j.name === job.id);
  const state = jr ? (jr.conclusion || jr.status || '') : '';
  return `<article class="lee-wf-job ${state ? 'state-' + esc(state) : ''}" data-job="${esc(job.id)}">` +
    `<header><strong>${esc(job.name)}</strong>${state ? `<i>${esc(state)}</i>` : ''}</header>` +
    `<small>${esc(job.runs_on || job.uses || '')}${job.environment ? ' · ' + esc(job.environment) : ''}</small>` +
    `${job.if ? `<code class="lee-wf-if">if ${esc(job.if)}</code>` : ''}` +
    `<ol class="lee-wf-steps">${job.steps.map(st => `<li title="${esc(st.uses || st.run)}">${esc(st.name)}</li>`).join('')}</ol></article>`;
}
function wfGraph(wf, run) {
  if (wf.error) return `<div class="lee-git-empty-state"><strong>${esc(wf.file)}</strong><span>${esc(wf.error)}</span></div>`;
  if (!wf.jobs.length) return `<div class="lee-git-empty-state"><strong>No jobs</strong><span>${esc(wf.file)} declares no jobs.</span></div>`;
  const byId = Object.fromEntries(wf.jobs.map(j => [j.id, j]));
  return `<div class="lee-wf-graph">${wf.levels.map((row, i) => `<div class="lee-wf-level">` +
    `${i ? '<span class="lee-wf-edge" aria-hidden="true"></span>' : ''}` +
    `<div class="lee-wf-row">${row.map(id => wfJobBox(byId[id], run)).join('')}</div></div>`).join('')}</div>`;
}
function wfRunRow(r) {
  const state = r.conclusion || r.status || '';
  return `<button class="lee-wf-run state-${esc(state)}" data-run="${r.id}" data-url="${esc(r.url)}">` +
    `<b>${state === 'success' ? '✓' : state === 'failure' ? '✗' : state === 'in_progress' ? '•' : '·'}</b>` +
    `<span><strong>${esc(r.title || r.name || r.file)}</strong><small>${esc(r.file)} · ${esc(r.branch)} · ${esc(r.event)}${r.actor ? ' · ' + esc(r.actor) : ''}</small></span>` +
    `<small>#${r.number || ''}</small></button>`;
}
function wfPickRows(cat) {
  if (!cat) return '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading the project</small></div>';
  const d = cat.detect || {};
  const tags = Object.entries(d).filter(([k, v]) => v === true).map(([k]) => `<i>${esc(k)}</i>`).join('');
  const rows = (cat.workflows || []).map(w => `<article class="lee-wf-pick${w.recommended ? ' recommended' : ''}${w.present ? ' present' : ''}" data-pick="${esc(w.id)}">` +
    `<div><strong>${esc(w.name)}</strong><small>${esc(w.doc)}</small>` +
    `${w.recommended ? `<i class="lee-wf-because">recommended · ${esc(w.why)}</i>` : ''}</div>` +
    `<span class="lee-wf-pickfile">${esc(w.file)}</span>` +
    `<button data-pick-preview>preview</button>` +
    `${w.present ? '<span class="lee-wf-has">already here</span>' : '<button data-pick-add>add</button>'}</article>`).join('');
  return `<div class="lee-wf-detect"><strong>detected</strong>${tags || '<i>nothing conclusive</i>'}` +
    `${d.build ? `<code>${esc(d.build)}</code>` : d.build_why ? `<small>${esc(d.build_why)}</small>` : ''}</div>` +
    `<div class="lee-wf-picks">${rows}</div>`;
}
function wfEnvRows(entries) {
  if (!entries?.length) return '<div class="lee-git-empty-state"><strong>Nothing declared</strong><span>Add <code>env_schema</code> to .gheasy/config.json, or a release step that needs a key.</span></div>';
  return entries.map(e => `<article class="lee-wf-env${e.set ? ' is-set' : ''}" data-env="${esc(e.key)}">` +
    `<div><strong>${esc(e.key)}</strong><small>${e.target}${e.declared ? '' : ' · from a release step'}</small></div>` +
    `<span class="lee-wf-envval">${e.secret ? (e.set ? '••••••••' : 'not set') : esc(e.value || 'not set')}</span>` +
    `<button data-env-set>${e.set ? 'change' : 'set'}</button>${e.set ? '<button data-env-unset aria-label="remove">×</button>' : ''}</article>`).join('');
}
function renderWorkflowsPanel() {
  const host = $('#workflowspanel'); if (!host) return;
  const d = wfUI.data;
  if (!d) { host.innerHTML = '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading workflows</small></div>'; return; }
  const st = d.status || {};
  const wf = d.workflows.find(w => w.file === wfUI.open) || d.workflows[0];
  if (wf) wfUI.open = wf.file;
  const tabs = d.workflows.map(w => `<button data-wf="${esc(w.file)}" class="${w.file === wfUI.open ? 'active' : ''}">${esc(w.name)}</button>`).join('');
  const runsFor = (wfUI.runs || []).filter(r => !wf || !r.file || r.file === wf.file);
  const body = wfUI.view === 'runs'
    ? `<div class="lee-wf-runs">${runsFor.length ? runsFor.map(wfRunRow).join('')
        : `<div class="lee-git-empty-state"><strong>No runs</strong><span>${st.token ? 'This workflow has not run yet.' : 'Connect a token to see run history.'}</span></div>`}</div>`
    : wfUI.view === 'add'
    ? wfPickRows(wfUI.catalogue)
    : wfUI.view === 'build'
    ? renderBuilder()
    : wfUI.view === 'yaml'
    ? `<pre class="lee-wf-yaml">${esc(wfUI.preview || 'Generate to preview the workflow gheasy would write from .gheasy/config.json.')}</pre>`
    : wf ? wfGraph(wf, wfUI.runJobs) : '<div class="lee-git-empty-state"><strong>No workflows</strong><span>This project has no .github/workflows yet.</span></div>';
  host.innerHTML = wfStatusNote(st) +
    `<header class="lee-sc-branch"><div><strong>${esc(st.repo || d.root.split('/').pop())}</strong><span>${d.workflows.length} workflow${d.workflows.length === 1 ? '' : 's'}${d.config ? ' · gheasy config' : ''}</span></div></header>` +
    `<nav class="lee-git-nav" aria-label="Workflow views">${[['graph', 'Jobs'], ['add', 'Add'], ['build', 'Build'], ['runs', 'Runs'], ['env', 'Environment']].map(([id, label]) =>
      `<button data-wf-view="${id}" class="${wfUI.view === id ? 'active' : ''}">${label}</button>`).join('')}</nav>` +
    (wfUI.view === 'add' || wfUI.view === 'build'
      ? `<main class="lee-wf-body">${body}</main>`
      : wfUI.view === 'env'
      ? `<div class="lee-sc-actions"><button data-wf-env="refresh">refresh</button>` +
        `${st.gh_cli && !st.gh_auth ? '<button data-wf-env="auth">gh auth login…</button>' : ''}` +
        `<button data-wf-env="push" ${st.gh_auth ? '' : 'title="pushing uses the GitHub CLI"'}>push declared to GitHub</button>` +
        `<button data-wf-env="add">add key…</button></div>` +
        `<div class="lee-wf-envs">${wfEnvRows(wfUI.env?.entries)}</div>`
      : `<div class="lee-wf-tabs">${tabs}</div>` +
        `<div class="lee-sc-actions">${wf?.dispatchable ? '<button data-wf-op="dispatch">run workflow</button>' : ''}` +
        `<button data-wf-op="open">open file</button><button data-wf-op="edit">edit in builder</button>` +
        `<button data-wf-op="generate">from gheasy config</button>` +
        `${d.config ? '<button data-wf-op="write">write gheasy.yml</button>' : ''}` +
        `<button data-wf-op="docker">Dockerfile…</button></div>` +
        `<main class="lee-wf-body">${body}</main>`);
  wireWorkflowsPanel(host, d, wf);
  if (wfUI.view === 'build') wireBuilder(host);
}
function wireWorkflowsPanel(host, d, wf) {
  host.querySelectorAll('[data-wf-view]').forEach(b => b.onclick = () => {
    wfUI.view = b.dataset.wfView; renderWorkflowsPanel();
    if (wfUI.view === 'runs' && !wfUI.runs) loadWorkflowRuns();
    if (wfUI.view === 'add' && !wfUI.catalogue) loadWorkflowCatalogue();
    if (wfUI.view === 'build' && !bldUI.vocab) loadBuilder(wfUI.open);
    if (wfUI.view === 'env' && !wfUI.env) loadWorkflowEnv();
  });
  host.querySelectorAll('[data-wf]').forEach(b => b.onclick = () => { wfUI.open = b.dataset.wf; wfUI.runJobs = null; renderWorkflowsPanel(); });
  host.querySelectorAll('[data-wf-op]').forEach(b => b.onclick = () => workflowOp(b.dataset.wfOp, wf));
  host.querySelector('[data-wf-op="edit"]')?.addEventListener('click', () => { wfUI.view = 'build'; loadBuilder(wf?.file); });
  host.querySelectorAll('.lee-wf-pick').forEach(row => {
    const id = row.dataset.pick;
    row.querySelector('[data-pick-preview]').onclick = () => pickWorkflow('preview', id);
    row.querySelector('[data-pick-add]')?.addEventListener('click', () => pickWorkflow('add', id));
  });
  host.querySelectorAll('[data-run]').forEach(b => b.onclick = async () => {
    try { wfUI.runJobs = {jobs: (await api('/workflows/jobs' + projectQuery({id: b.dataset.run}))).jobs};
          wfUI.view = 'graph'; renderWorkflowsPanel();
          status('run ' + b.dataset.run + ': job results are on the graph', 'ok'); }
    catch (e) { status(e.message || String(e), 'err'); }
  });
  host.querySelectorAll('[data-env]').forEach(row => {
    const key = row.dataset.env;
    row.querySelector('[data-env-set]').onclick = async () => {
      const entry = (wfUI.env?.entries || []).find(e => e.key === key) || {};
      const value = await inputDialog(`set ${key}`, entry.secret ? 'Value (stored in your keychain, never shown again)' : 'Value',
                                      entry.secret ? '' : (entry.value || ''), entry.secret ? 'paste the token' : 'value');
      if (value) envOp('set', {key, value, secret: !!entry.secret});
    };
    row.querySelector('[data-env-unset]')?.addEventListener('click', async () => {
      if (await confirmDialog('remove value', `Remove ${key} from the keychain and the env file?`, 'remove')) envOp('unset', {key});
    });
  });
  host.querySelectorAll('[data-wf-env]').forEach(b => b.onclick = async () => {
    const op = b.dataset.wfEnv;
    if (op === 'refresh') return loadWorkflowEnv(true);
    // Authenticating is a conversation with a browser and a one-time code in it, so the
    // button opens the real `gh auth login` rather than a form pretending to be one.
    if (op === 'auth') { await openTerm('gh-auth'); return status('finish the login in the terminal, then refresh', 'ok'); }
    if (op === 'push') {
      if (await confirmDialog('push to GitHub', 'Send every declared value to this repository as a secret or a variable?', 'push')) envOp('push', {});
      return;
    }
    const key = await inputDialog('add key', 'Environment key', '', 'GITHUB_TOKEN');
    if (!key) return;
    const value = await inputDialog(`set ${key}`, 'Value (stored in your keychain)', '', 'paste the value');
    if (value) envOp('set', {key, value, secret: true});
  });
}
async function leeWorkflows() {
  try { wfUI.data = await api('/workflows' + projectQuery()); }
  catch (e) { const host = $('#workflowspanel'); if (host) host.innerHTML = `<div class="lee-git-empty-state"><strong>No project</strong><span>${esc(e.message || e)}</span></div>`; return; }
  renderWorkflowsPanel();
  if (wfUI.view === 'runs' && !wfUI.runs) loadWorkflowRuns();
  if (wfUI.view === 'add' && !wfUI.catalogue) loadWorkflowCatalogue();
  if (wfUI.view === 'env' && !wfUI.env) loadWorkflowEnv();
}
window.leeWorkflows = leeWorkflows;
async function loadWorkflowCatalogue() {
  try { wfUI.catalogue = await api('/workflows/catalogue' + projectQuery()); }
  catch (e) { status(e.message || String(e), 'err'); return; }
  renderWorkflowsPanel();
}
async function pickWorkflow(op, id) {
  try {
    const d = await post('/workflows/action', {op: op === 'add' ? 'add' : 'preview', repo: projectRepo(), workflow: id});
    if (d.yaml) { wfUI.preview = d.yaml; wfUI.view = 'yaml'; }
    if (d.path) { status(`wrote ${d.path}`, 'ok'); wfUI.catalogue = null; loadWorkflowCatalogue(); }
    if (d.workflows) wfUI.data = {...wfUI.data, workflows: d.workflows, status: d.status};
    renderWorkflowsPanel();
  } catch (e) { status(e.message || String(e), 'err'); }
}
async function loadWorkflowRuns() {
  if (!wfUI.data?.status?.token) { wfUI.runs = []; return renderWorkflowsPanel(); }
  try { wfUI.runs = (await api('/workflows/runs' + projectQuery({limit: 20}))).runs; }
  catch (e) { wfUI.runs = []; status(e.message || String(e), 'err'); }
  renderWorkflowsPanel();
}
async function loadWorkflowEnv(remote = false) {
  try { wfUI.env = await api('/workflows/env' + projectQuery(remote ? {remote: true} : {})); }
  catch (e) { status(e.message || String(e), 'err'); return; }
  renderWorkflowsPanel();
}
async function envOp(op, extra) {
  try {
    const d = await post('/workflows/env/action', {op, repo: projectRepo(), ...extra});
    wfUI.env = {...(wfUI.env || {}), entries: d.entries};
    if (d.results) {
      const failed = d.results.filter(r => r.ok === false).length;
      status(`pushed ${d.results.filter(r => r.ok && !r.skipped).length} · skipped ${d.results.filter(r => r.skipped).length} · failed ${failed}`, failed ? 'err' : 'ok');
    } else status(`${extra.key} ${op === 'unset' ? 'removed' : 'saved'}`, 'ok');
    renderWorkflowsPanel();
  } catch (e) { status(e.message || String(e), 'err'); }
}
async function workflowOp(op, wf) {
  try {
    if (op === 'open') { if (wf) leeOpenFile(wf.path); return; }
    if (op === 'edit') return;                       // wired separately: it changes view, not state
    if (op === 'docker') {
      const d = await api('/workflows/docker' + projectQuery());
      if (d.why) return status(d.why, 'err');
      if (d.dockerfile) return status('this project already has a Dockerfile', 'ok');
      if (!await confirmDialog('write Dockerfile', `dockeasy detected:\n\n${d.base}\n\nWrite this Dockerfile?`, 'write')) return;
      op = 'dockerfile';
    }
    if (op === 'dispatch') {
      const ref = await inputDialog('run workflow', 'Branch or tag to run on', '', 'leave empty for the current branch');
      if (ref === null) return;
      const d = await post('/workflows/action', {op, repo: projectRepo(), workflow: wf.file, ref});
      wfUI.data = {...wfUI.data, workflows: d.workflows, status: d.status};
      status(`dispatched ${wf.file} on ${d.ref}`, 'ok');
      wfUI.view = 'runs'; setTimeout(loadWorkflowRuns, 1500);
      return renderWorkflowsPanel();
    }
    const d = await post('/workflows/action', {op, repo: projectRepo()});
    wfUI.data = {...wfUI.data, workflows: d.workflows, status: d.status};
    if (d.yaml) { wfUI.preview = d.yaml; wfUI.view = 'yaml'; }
    if (d.path) status(`wrote ${d.path}`, 'ok');
    renderWorkflowsPanel();
  } catch (e) { status(e.message || String(e), 'err'); }
}

// -- the workflow builder ---------------------------------------------------------------
// A form over gheasy's DSL. The vocabulary comes from the server as data, so a preset added
// in leela/wfbuild.py appears here without a line of frontend -- and the form is the list of
// decisions a workflow actually has, which is the part that is hard to learn from YAML.
const bldUI = {vocab: null, spec: null, yaml: '', file: '', stale: false, timer: 0};
function blankSpec() {
  return {name: 'ci', file: 'ci.yml', on: {push: 'main', pull_request: 'main', workflow_dispatch: true},
          jobs: [{preset: 'uv_test', needs: []}]};
}
function bldTrigger(t, on) {
  const v = on[t.id];
  const checked = t.kind === 'flag' ? !!v : (v !== undefined && v !== false && v !== '');
  const field = t.kind === 'flag' ? '' :
    `<input class="lee-input" data-trigger-value="${t.id}" value="${esc(checked ? String(v ?? t.default) : t.default)}" ` +
    `placeholder="${esc(t.kind === 'cron' ? 'minute hour day month weekday' : 'main, release')}" ${checked ? '' : 'disabled'}>`;
  return `<article class="lee-bld-trigger"><label><input type="checkbox" data-trigger="${t.id}" ${checked ? 'checked' : ''}>` +
    `<strong>${esc(t.label)}</strong></label><small>${esc(t.doc)}</small>${field}</article>`;
}
function bldOption(o, job, i) {
  const value = (job.options || {})[o.key] ?? o.default;
  const field = o.type === 'flag'
    ? `<input type="checkbox" data-opt="${o.key}" data-job="${i}" ${value ? 'checked' : ''}>`
    : o.type === 'lines'
    ? `<textarea class="lee-keyedit" rows="3" data-opt="${o.key}" data-job="${i}">${esc(value)}</textarea>`
    : `<input class="lee-input" data-opt="${o.key}" data-job="${i}" value="${esc(value)}">`;
  return `<label class="lee-bld-opt"><span>${esc(o.label)}</span>${field}${o.doc ? `<small>${esc(o.doc)}</small>` : ''}</label>`;
}
function bldJob(job, i, presets, spec) {
  const preset = presets.find(p => p.id === job.preset) || presets[0];
  const others = spec.jobs.map((j, n) => n === i ? null : (j.id || (presets.find(p => p.id === j.preset) || {}).job))
                         .filter(Boolean);
  const needs = (job.needs || []).join(', ');
  return `<article class="lee-bld-job" data-job="${i}">` +
    `<header><select data-preset="${i}">${presets.map(p => `<option value="${p.id}" ${p.id === job.preset ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select>` +
    `<button data-job-up="${i}" title="move earlier" ${i ? '' : 'disabled'}>↑</button>` +
    `<button data-job-del="${i}" title="remove" aria-label="remove job">×</button></header>` +
    `<small>${esc(preset.doc)}</small>` +
    (others.length ? `<label class="lee-bld-opt"><span>waits for</span>` +
      `<input class="lee-input" data-needs="${i}" value="${esc(needs)}" placeholder="${esc(others.join(', '))}"></label>` : '') +
    preset.options.map(o => bldOption(o, job, i)).join('') + `</article>`;
}
function renderBuilder() {
  const v = bldUI.vocab;
  if (!v) return '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading the presets</small></div>';
  const spec = bldUI.spec || (bldUI.spec = blankSpec());
  return `<div class="lee-bld">` +
    `<div class="lee-bld-head"><label class="lee-bld-opt"><span>file</span><input class="lee-input" id="bldfile" value="${esc(spec.file || 'ci.yml')}"></label>` +
    `<label class="lee-bld-opt"><span>name</span><input class="lee-input" id="bldname" value="${esc(spec.name || 'ci')}"></label></div>` +
    `${bldUI.stale ? '<div class="lee-wf-note"><strong>The file has been edited</strong><span>Writing replaces those edits with what this form says.</span></div>' : ''}` +
    `<section class="lee-bld-section"><header>when it runs</header>${v.triggers.map(t => bldTrigger(t, spec.on || {})).join('')}</section>` +
    `<section class="lee-bld-section"><header>what it does<button id="bldaddjob">add job</button></header>` +
    `${spec.jobs.map((j, i) => bldJob(j, i, v.presets, spec)).join('')}</section>` +
    `<div class="lee-sc-actions"><button id="bldwrite">write ${esc(spec.file || 'ci.yml')}</button><button id="bldyaml">show YAML</button></div>` +
    `${bldUI.yaml ? `<pre class="lee-wf-yaml">${esc(bldUI.yaml)}</pre>` : ''}</div>`;
}
function wireBuilder(host) {
  const spec = bldUI.spec;
  const touch = () => { renderWorkflowsPanel(); scheduleBuild(); };
  host.querySelector('#bldfile')?.addEventListener('change', e => { spec.file = e.target.value.trim(); touch(); });
  host.querySelector('#bldname')?.addEventListener('change', e => { spec.name = e.target.value.trim(); touch(); });
  host.querySelectorAll('[data-trigger]').forEach(b => b.onchange = () => {
    const id = b.dataset.trigger, t = bldUI.vocab.triggers.find(x => x.id === id);
    spec.on = spec.on || {};
    if (!b.checked) delete spec.on[id];
    else spec.on[id] = t.kind === 'flag' ? true : t.default;
    touch();
  });
  host.querySelectorAll('[data-trigger-value]').forEach(i => i.onchange = () => {
    spec.on[i.dataset.triggerValue] = i.value.trim(); touch();
  });
  host.querySelector('#bldaddjob')?.addEventListener('click', () => { spec.jobs.push({preset: 'run', needs: []}); touch(); });
  host.querySelectorAll('[data-preset]').forEach(sel => sel.onchange = () => {
    const i = Number(sel.dataset.preset);
    spec.jobs[i] = {preset: sel.value, needs: spec.jobs[i].needs || []};
    touch();
  });
  host.querySelectorAll('[data-job-del]').forEach(b => b.onclick = () => { spec.jobs.splice(Number(b.dataset.jobDel), 1); touch(); });
  host.querySelectorAll('[data-job-up]').forEach(b => b.onclick = () => {
    const i = Number(b.dataset.jobUp); if (!i) return;
    [spec.jobs[i - 1], spec.jobs[i]] = [spec.jobs[i], spec.jobs[i - 1]]; touch();
  });
  host.querySelectorAll('[data-needs]').forEach(i => i.onchange = () => {
    spec.jobs[Number(i.dataset.needs)].needs = i.value.split(',').map(x => x.trim()).filter(Boolean);
    touch();
  });
  host.querySelectorAll('[data-opt]').forEach(el => el.onchange = () => {
    const job = spec.jobs[Number(el.dataset.job)];
    job.options = job.options || {};
    job.options[el.dataset.opt] = el.type === 'checkbox' ? el.checked : el.value;
    scheduleBuild();
  });
  host.querySelector('#bldyaml')?.addEventListener('click', () => buildYaml(true));
  host.querySelector('#bldwrite')?.addEventListener('click', async () => {
    try {
      const d = await post('/workflows/action', {op: 'write_spec', repo: projectRepo(), spec: bldUI.spec, file: bldUI.spec.file});
      status(`wrote ${d.path}`, 'ok');
      wfUI.data = {...wfUI.data, workflows: d.workflows, status: d.status};
      wfUI.catalogue = null; bldUI.stale = false; wfUI.view = 'graph';
      wfUI.open = bldUI.spec.file;
      renderWorkflowsPanel();
    } catch (e) { status(e.message || String(e), 'err'); }
  });
}
function scheduleBuild() { clearTimeout(bldUI.timer); bldUI.timer = setTimeout(() => buildYaml(false), 350); }
async function buildYaml(show) {
  try {
    const d = await post('/workflows/action', {op: 'build', repo: projectRepo(), spec: bldUI.spec});
    if (show || bldUI.yaml) { bldUI.yaml = d.yaml; renderWorkflowsPanel(); }
    else bldUI.yaml = '';
  } catch (e) { status(e.message || String(e), 'err'); }
}
async function loadBuilder(file = '') {
  if (!bldUI.vocab) { try { bldUI.vocab = await api('/workflows/presets'); } catch (e) { return status(e.message || String(e), 'err'); } }
  if (file) {
    try {
      const d = await api('/workflows/spec' + projectQuery({file}));
      if (d.spec) { bldUI.spec = d.spec; bldUI.stale = !!d.stale; }
    } catch (e) {}
  }
  if (!bldUI.spec) bldUI.spec = blankSpec();
  renderWorkflowsPanel();
}

// -- the release pipeline ------------------------------------------------------------
const REL_MARK = {passed: '✓', failed: '✗', running: '•', skipped: '⤼', pending: '·'};
// A failed step's traceback belongs to *someone*, and in a stack you own that is the whole
// question. The server rewrote the path to the checkout in this workspace, so "open" lands
// in the repository rather than in a copy under .venv that the next sync overwrites.
function blameRow(b) {
  if (!b || !b.package) return '';
  const where = b.file ? `${b.package}/${b.file.split('/').slice(-1)[0]}:${b.line}` : b.package;
  return `<div class="lee-blame"><strong>${esc(b.package)}</strong>` +
    `<span>${esc(b.error || 'raised here')}</span>` +
    `<code>${esc(where)}${b.fn ? ' in ' + esc(b.fn) : ''}</code>` +
    `${b.checkout ? '<i>your checkout</i>' : '<i class="warn">installed copy</i>'}` +
    `${b.open ? `<button data-blame-open="${esc(b.open)}" data-blame-line="${b.line}">open</button>` : ''}</div>`;
}
function wireBlame(host) {
  host.querySelectorAll('[data-blame-open]').forEach(b => b.onclick = async () => {
    try { await leeOpenFile(b.dataset.blameOpen); } catch (e) { return status(e.message || String(e), 'err'); }
    // The line the traceback named, once the editor has actually mounted the file.
    const line = Number(b.dataset.blameLine) || 0;
    if (!line) return;
    setTimeout(() => {
      const view = lee.editors.get('file'); if (!view) return;
      const doc = view.state.doc, at = doc.line(Math.max(1, Math.min(line, doc.lines)));
      // `setCursor` deliberately does not scroll, so the move is dispatched with the
      // scroll asked for -- landing on a line you cannot see is not landing on it.
      view.dispatch({selection: {anchor: at.from}, scrollIntoView: true});
      LeeCM.focus?.(view);
    }, 350);
  });
}
function relStepRow(s, d) {
  const busy = d.running && s.status !== 'running';
  return `<article class="lee-rel-step state-${s.status}" data-step="${esc(s.id)}">` +
    `<b>${REL_MARK[s.status] || '·'}</b>` +
    `<div><strong>${esc(s.label)}</strong><code>${esc(s.cmd)}</code>` +
    `<small>${esc(s.doc || '')}${s.code !== null && s.code !== undefined ? ` · exit ${s.code}` : ''}</small>` +
    `${s.missing.length ? `<i class="warn">needs ${s.missing.map(esc).join(', ')}</i>` : ''}</div>` +
    `<span class="lee-rel-actions">` +
    `${s.status === 'running' ? '<button data-rel="stop">stop</button>' :
      `<button data-rel="step" ${busy ? 'disabled' : ''} title="run only this step">run</button>` +
      `${s.status === 'failed' ? `<button data-rel="start" ${busy ? 'disabled' : ''} title="retry, then continue">retry</button><button data-rel="skip" title="mark done without running">skip</button>` : ''}`}` +
    `</span></article>`;
}
function renderReleasesPanel() {
  const host = $('#releasespanel'); if (!host) return;
  const d = relUI.data;
  if (!d) { host.innerHTML = '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading the pipeline</small></div>'; return; }
  const done = d.steps.filter(s => s.status === 'passed').length;
  host.innerHTML =
    `<header class="lee-sc-branch"><div><strong>${esc(d.root.split('/').pop())}</strong>` +
    `<span>${d.nbdev ? 'nbdev project' : 'plain project'} · ${done}/${d.steps.length} done${d.configured ? ' · .leela/release.json' : ' · default pipeline'}</span></div></header>` +
    `<div class="lee-sc-actions">` +
    `${d.running ? '<button data-rel-top="stop" class="warn">stop</button>' : `<button data-rel-top="start">${d.failed ? 'continue' : 'run release'}</button>`}` +
    `<button data-rel-top="terminal">terminal</button><button data-rel-top="reset" ${d.running ? 'disabled' : ''}>reset</button>` +
    `<button data-rel-top="edit">edit steps</button>${d.configured ? '<button data-rel-top="defaults">defaults</button>' : ''}</div>` +
    `${d.failed ? `<div class="lee-wf-note"><strong>${esc(d.failed)} failed</strong><span>Its output is in the release terminal. Fix and retry, or skip it deliberately.</span></div>` : ''}` +
    blameRow(d.blame) +
    `<div class="lee-rel-steps">${d.steps.map(s => relStepRow(s, d)).join('')}</div>` +
    `${d.needs.length ? `<div class="lee-rel-needs"><strong>needs</strong>${d.needs.map(k => `<i>${esc(k)}</i>`).join('')}<button data-rel-top="env">environment…</button></div>` : ''}`;
  wireReleasesPanel(host, d);
  wireBlame(host);
  relPoll(d);
}
function wireReleasesPanel(host, d) {
  host.querySelectorAll('[data-rel-top]').forEach(b => b.onclick = () => releaseTop(b.dataset.relTop, d));
  host.querySelectorAll('.lee-rel-step').forEach(row => {
    const step = row.dataset.step;
    row.querySelectorAll('[data-rel]').forEach(b => b.onclick = () => releaseOp(b.dataset.rel, {step}));
  });
}
function relPoll(d) {
  clearTimeout(relUI.poll);
  // Steps finish on their own and start the next one, so the panel has to keep asking.
  // Only while something is running: an idle pipeline costs nothing.
  if (d.running) relUI.poll = setTimeout(() => leeReleases(), 1200);
}
async function leeReleases() {
  try { relUI.data = await api('/releases' + projectQuery()); }
  catch (e) { const host = $('#releasespanel'); if (host) host.innerHTML = `<div class="lee-git-empty-state"><strong>No project</strong><span>${esc(e.message || e)}</span></div>`; return; }
  renderReleasesPanel();
}
window.leeReleases = leeReleases;
async function releaseOp(op, extra = {}) {
  try {
    relUI.data = await post('/releases/action', {op, repo: projectRepo(), ...extra});
    if (op === 'start' || op === 'step') await openReleaseTerm(relUI.data.root, 'release');
    renderReleasesPanel();
  } catch (e) { status(e.message || String(e), 'err'); }
}
async function releaseTop(op, d) {
  if (op === 'terminal') return openReleaseTerm(d.root, 'release');
  if (op === 'env') { leeLeft('workflows'); wfUI.view = 'env'; wfUI.env = null; return leeWorkflows(); }
  if (op === 'defaults') return releaseOp('reset_plan');
  if (op === 'start') {
    const missing = d.steps.flatMap(s => s.missing);
    if (missing.length && !await confirmDialog('run release',
        `These steps are missing ${[...new Set(missing)].join(', ')}. Run anyway?`, 'run')) return;
    return releaseOp('start');
  }
  if (op === 'stop') { if (await confirmDialog('stop release', 'Stop the running step?', 'stop')) releaseOp('stop'); return; }
  if (op === 'reset') { if (await confirmDialog('reset', 'Forget what ran? The commands are unchanged.', 'reset')) releaseOp('reset'); return; }
  if (op === 'edit') {
    const text = await textDialog('release steps', 'One step per line: id | label | command',
                                  d.steps.map(s => `${s.id} | ${s.label} | ${s.cmd}`).join('\n'));
    if (text === null) return;
    const steps = text.split('\n').map(line => line.split('|').map(x => x.trim())).filter(p => p.length >= 3 && p[2])
      .map(([id, label, cmd]) => ({id, label, cmd}));
    releaseOp('save', {steps});
  }
}

// -- deploy ---------------------------------------------------------------------------
// The same pipeline as a release, with a target above it: a deploy that cannot say where it
// is going is the one nobody presses.
const depUI = {data: null, poll: 0, view: 'stages', infra: null, stack: null, zone: '', records: null};
function depTargetCard(t) {
  const files = [['deploy.py', t.script], ['setup.py', t.setup], ['Dockerfile', t.dockerfile],
                 ['docker-compose.yml', t.compose], ['Caddyfile', t.caddyfile]];
  return `<header class="lee-sc-branch"><div><strong>${esc(t.domain || t.app)}</strong>` +
    `<span>${esc(t.server || 'no server named')} · ${esc(t.user)}@:${esc(t.port)}</span></div></header>` +
    `<div class="lee-dep-files">${files.map(([n, has]) => `<i class="${has ? 'has' : ''}">${esc(n)}</i>`).join('')}</div>` +
    (t.missing.length ? `<div class="lee-wf-note"><strong>${t.missing.length} value${t.missing.length === 1 ? '' : 's'} not set</strong>` +
      `<span>${t.missing.map(esc).join(', ')}</span><code>set them in Workflows → Environment</code></div>` : '');
}

function depInfraRows() {
  const d = depUI.infra;
  if (!d) return '<div class="lee-git-loading"><span></span><span></span><span></span><small>asking Hetzner and Cloudflare</small></div>';
  const st = d.status || {};
  const half = (title, part, render) => `<section class="lee-inf-group"><header>${title}</header>` +
    (part.error ? `<div class="lee-wf-note"><span>${esc(part.error)}</span></div>`
                : (part.rows.length ? part.rows.map(render).join('')
                                    : '<div class="lee-dim lee-git-empty">none</div>')) + '</section>';
  return `<div class="lee-inf-status">${['vpseasy', 'cfeasy'].map(k => `<i class="${st[k] ? 'has' : ''}">${k}</i>`).join('')}` +
    `<i class="${st.hcloud_token ? 'has' : ''}">HCLOUD_TOKEN</i><i class="${st.cf_token ? 'has' : ''}">CLOUDFLARE_API_TOKEN</i></div>` +
    half('servers', d.servers || {rows: [], error: ''}, s =>
      `<article class="lee-inf-row" data-server="${esc(s.name)}"><div><strong>${esc(s.name)}</strong><small>${esc(s.ip || '')} · ${esc(s.status || '')}</small></div>` +
      `<button data-server-del title="delete this server">delete</button></article>`) +
    half('tunnels', d.tunnels || {rows: [], error: ''}, t =>
      `<article class="lee-inf-row" data-tunnel="${esc(t.id)}"><div><strong>${esc(t.name)}</strong><small>${esc(t.status || '')} · ${t.connections} connection${t.connections === 1 ? '' : 's'}</small></div>` +
      `<button data-tunnel-del title="delete this tunnel">delete</button></article>`) +
    half('zones', d.zones || {rows: [], error: ''}, z =>
      `<article class="lee-inf-row" data-zone="${esc(z.name)}"><div><strong>${esc(z.name)}</strong><small>${esc(z.status || '')}</small></div>` +
      `<button data-zone-dns>records</button></article>`) +
    (depUI.records ? `<section class="lee-inf-group"><header>${esc(depUI.zone)}</header>` +
      depUI.records.map(r => `<article class="lee-inf-row"><div><strong>${esc(r.name)}</strong>` +
        `<small>${esc(r.type)} · ${esc(r.content)}${r.proxied ? ' · proxied' : ''}</small></div>` +
        `${r.tunnel ? '<i class="lee-inf-tag">tunnel</i>' : ''}</article>`).join('') + '</section>' : '');
}
function depStackRows() {
  const d = depUI.stack;
  if (!d) return '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading the stack</small></div>';
  return `<div class="lee-inf-status"><i>${d.checkouts.length} checkouts open</i></div>` +
    `<div class="lee-pkgs">${d.packages.map(p => `<article class="lee-pkg${p.shadowed ? ' shadowed' : ''}">` +
      `<div><strong>${esc(p.name)}</strong><small>${p.installed ? esc(p.version || 'no version') + ' · ' + esc(p.source) : 'not installed'}</small>` +
      `${p.shadowed ? '<i class="warn">edits in your checkout are not what runs — reinstall it editable</i>' : ''}</div>` +
      `${p.checkout ? `<button data-pkg-open="${esc(p.checkout)}">open</button>` : ''}</article>`).join('')}</div>`;
}
async function loadInfra(force = false) {
  if (depUI.infra && !force) return renderDeployPanel();
  try { depUI.infra = await api('/infra'); } catch (e) { status(e.message || String(e), 'err'); return; }
  renderDeployPanel();
}
async function loadStack() {
  try { depUI.stack = await api('/stack' + projectQuery()); } catch (e) { status(e.message || String(e), 'err'); return; }
  renderDeployPanel();
}
async function infraOp(op, extra = {}) {
  try {
    depUI.infra = await post('/infra/action', {op, ...extra});
    status(`${op.replace('_', ' ')} done`, 'ok');
    renderDeployPanel();
  } catch (e) { status(e.message || String(e), 'err'); }
}
function wireInfra(host) {
  host.querySelectorAll('[data-server-del]').forEach(b => b.onclick = async () => {
    const name = b.closest('[data-server]').dataset.server;
    if (await confirmDialog('delete server', `Delete ${name}? The machine and everything on it goes.`, 'delete'))
      infraOp('delete_server', {name});
  });
  host.querySelectorAll('[data-tunnel-del]').forEach(b => b.onclick = async () => {
    const row = b.closest('[data-tunnel]');
    if (await confirmDialog('delete tunnel', `Delete this tunnel? Anything routed through it stops answering.`, 'delete'))
      infraOp('delete_tunnel', {id: row.dataset.tunnel});
  });
  host.querySelectorAll('[data-zone-dns]').forEach(b => b.onclick = async () => {
    const zone = b.closest('[data-zone]').dataset.zone;
    try { depUI.zone = zone; depUI.records = (await api('/infra/records?zone=' + encodeURIComponent(zone))).records; }
    catch (e) { return status(e.message || String(e), 'err'); }
    renderDeployPanel();
  });
  host.querySelectorAll('[data-pkg-open]').forEach(b => b.onclick = () => leeOpenFile(b.dataset.pkgOpen));
}
function renderDeployPanel() {
  const host = $('#deploypanel'); if (!host) return;
  const d = depUI.data;
  if (!d) { host.innerHTML = '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading the deploy plan</small></div>'; return; }
  const t = d.target;
  const nav = `<nav class="lee-git-nav" aria-label="Deploy views">${[['stages', 'Stages'], ['infra', 'Servers'], ['stack', 'Stack']].map(([id, label]) =>
    `<button data-dep-view="${id}" class="${depUI.view === id ? 'active' : ''}">${label}</button>`).join('')}</nav>`;
  if (depUI.view !== 'stages') {
    host.innerHTML = depTargetCard(t) + nav +
      `<main class="lee-wf-body">${depUI.view === 'infra' ? depInfraRows() : depStackRows()}</main>`;
    host.querySelectorAll('[data-dep-view]').forEach(b => b.onclick = () => { depUI.view = b.dataset.depView; renderDeployPanel(); });
    wireInfra(host);
    if (depUI.view === 'infra' && !depUI.infra) loadInfra();
    if (depUI.view === 'stack' && !depUI.stack) loadStack();
    return;
  }
  host.innerHTML = depTargetCard(t) + nav +
    `<div class="lee-sc-actions">` +
    `${t.script ? (d.running ? '<button data-dep-top="stop" class="warn">stop</button>'
                             : `<button data-dep-top="start">${d.failed ? 'continue' : 'deploy'}</button>`)
                : '<button data-dep-top="scaffold">write deploy.py…</button>'}` +
    `<button data-dep-top="terminal">terminal</button>` +
    `<button data-dep-top="reset" ${d.running ? 'disabled' : ''}>reset</button>` +
    `<button data-dep-top="edit">edit steps</button>` +
    `${t.script ? '<button data-dep-top="open">open deploy.py</button>' : ''}</div>` +
    `${d.failed ? `<div class="lee-wf-note"><strong>${esc(d.failed)} failed</strong><span>Its output is in the deploy terminal. The stages are idempotent — fix and continue.</span></div>` : ''}` +
    blameRow(d.blame) +
    `<div class="lee-rel-steps">${d.steps.map(s => relStepRow(s, d)).join('')}</div>`;
  host.querySelectorAll('[data-dep-view]').forEach(b => b.onclick = () => { depUI.view = b.dataset.depView; renderDeployPanel(); });
  host.querySelectorAll('[data-dep-top]').forEach(b => b.onclick = () => deployTop(b.dataset.depTop, d));
  wireBlame(host);
  host.querySelectorAll('.lee-rel-step').forEach(row => {
    const step = row.dataset.step;
    row.querySelectorAll('[data-rel]').forEach(b => b.onclick = () => deployOp(b.dataset.rel, {step}));
  });
  clearTimeout(depUI.poll);
  if (d.running) depUI.poll = setTimeout(() => leeDeploys(), 1200);
}
async function leeDeploys() {
  try { depUI.data = await api('/deploys' + projectQuery()); }
  catch (e) { const host = $('#deploypanel'); if (host) host.innerHTML = `<div class="lee-git-empty-state"><strong>No project</strong><span>${esc(e.message || e)}</span></div>`; return; }
  renderDeployPanel();
}
window.leeDeploys = leeDeploys;
async function deployOp(op, extra = {}) {
  try {
    depUI.data = await post('/deploys/action', {op, repo: projectRepo(), ...extra});
    if (op === 'start' || op === 'step') await openReleaseTerm(depUI.data.root, 'deploy');
    renderDeployPanel();
  } catch (e) { status(e.message || String(e), 'err'); }
}
async function deployTop(op, d) {
  const t = d.target;
  if (op === 'terminal') return openReleaseTerm(d.root, 'deploy');
  if (op === 'open') return leeOpenFile(d.root + '/deploy.py');
  if (op === 'reset') { if (await confirmDialog('reset', 'Forget what ran? The stages are unchanged.', 'reset')) deployOp('reset'); return; }
  if (op === 'stop') { if (await confirmDialog('stop deploy', 'Stop the running stage?', 'stop')) deployOp('stop'); return; }
  if (op === 'scaffold') {
    const domain = await inputDialog('write deploy.py', 'Domain this app answers on', t.domain || '', 'example.com');
    if (!domain) return;
    const sub = await inputDialog('write deploy.py', 'Subdomain, or empty for the apex', '', 'app');
    if (sub === null) return;
    const second = await inputDialog('write deploy.py', 'A second hostname on the same container, or empty',
                                     '', 'the apex, as lego serves it');
    if (second === null) return;
    const r = await post('/deploys/action', {op: 'scaffold', repo: projectRepo(), domain,
                                             subdomain: sub, second_host: second})
                    .catch(e => { status(e.message || String(e), 'err'); });
    if (!r) return;
    depUI.data = r.state;
    status(`wrote ${(r.written || []).map(p => p.split('/').pop()).join(', ')}`, 'ok');
    return renderDeployPanel();
  }
  if (op === 'start') {
    if (t.missing.length && !await confirmDialog('deploy',
        `These are not set: ${t.missing.join(', ')}. Deploy anyway?`, 'deploy')) return;
    return deployOp('start');
  }
  if (op === 'edit') {
    const text = await textDialog('deploy stages', 'One stage per line: id | label | command',
                                  d.steps.map(s => `${s.id} | ${s.label} | ${s.cmd}`).join('\n'));
    if (text === null) return;
    const steps = text.split('\n').map(l => l.split('|').map(x => x.trim())).filter(p => p.length >= 3 && p[2])
      .map(([id, label, cmd]) => ({id, label, cmd}));
    deployOp('save', {steps});
  }
}

// -- driving the packages one call at a time --------------------------------------------
// The alternative to the deploy script, kept as its own panel so the two can be compared:
// same runner, same terminal, same blame on a failure -- six library calls instead of three
// subcommands. The snippet is on screen because a button you cannot read is not a diagnostic.
const drvUI = {data: null, open: '', poll: 0};
function drvPart(s, d) {
  const m = s.meta || {}, busy = d.running && s.status !== 'running';
  const flow = [...(m.produces || []).map(f => `<i>writes ${esc(f)}</i>`),
                ...(m.writes || []).map(k => `<i class="writes">sets ${esc(k)}</i>`),
                ...(s.missing || []).map(k => `<i class="warn">needs ${esc(k)}</i>`)].join('');
  const open = drvUI.open === s.id;
  return `<article class="lee-drv-part state-${s.status}" data-part="${esc(s.id)}">` +
    `<b>${REL_MARK[s.status] || '·'}</b>` +
    `<div><strong><span class="lee-drv-pkg">${esc(m.package || '')}</span>${esc(m.title || s.label)}</strong>` +
    `<small>${esc(s.doc || '')}${s.code !== null && s.code !== undefined ? ` · exit ${s.code}` : ''}</small>` +
    `${flow ? `<div class="lee-drv-flow">${flow}</div>` : ''}` +
    `<details ${open ? 'open' : ''}><summary>${open ? 'hide' : 'show'} the call</summary>` +
    `<pre class="lee-drv-code">${esc(m.code || '')}</pre></details></div>` +
    `<span class="lee-drv-actions">` +
    `${s.status === 'running' ? '<button data-drv="stop">stop</button>'
                              : `<button data-drv="step" ${busy ? 'disabled' : ''}>run</button>`}` +
    `</span></article>`;
}
function renderDrivePanel() {
  const host = $('#drivepanel'); if (!host) return;
  const d = drvUI.data;
  if (!d) { host.innerHTML = '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading the parts</small></div>'; return; }
  const c = d.context || {};
  const done = d.steps.filter(s => s.status === 'passed').length;
  host.innerHTML =
    `<header class="lee-sc-branch"><div><strong>${esc(c.host || c.app || '')}</strong>` +
    `<span>${esc(d.packages.join(' · '))} · ${done}/${d.steps.length} run</span></div></header>` +
    `<div class="lee-drv-ctx"><b>values</b><i>app ${esc(c.app || '')}</i>` +
    `${c.domain ? `<i>domain ${esc(c.domain)}</i>` : '<i class="warn">DOMAIN not set</i>'}` +
    `${c.subdomain ? `<i>sub ${esc(c.subdomain)}</i>` : ''}<i>tunnel ${esc(c.tunnel || '')}</i></div>` +
    `<div class="lee-sc-actions">` +
    `${d.running ? '<button data-drv-top="stop" class="warn">stop</button>'
                 : '<button data-drv-top="start">run all</button>'}` +
    `<button data-drv-top="terminal">terminal</button>` +
    `<button data-drv-top="reset" ${d.running ? 'disabled' : ''}>reset</button>` +
    `<button data-drv-top="values">values…</button></div>` +
    blameRow(d.blame) +
    `<div class="lee-rel-steps">${d.steps.map(s => drvPart(s, d)).join('')}</div>`;
  host.querySelectorAll('[data-drv-top]').forEach(b => b.onclick = () => driveTop(b.dataset.drvTop, d));
  host.querySelectorAll('.lee-drv-part').forEach(row => {
    const step = row.dataset.part;
    row.querySelectorAll('[data-drv]').forEach(b => b.onclick = () => driveOp(b.dataset.drv, {step}));
    row.querySelector('details')?.addEventListener('toggle', e => { drvUI.open = e.target.open ? step : ''; });
  });
  wireBlame(host);
  clearTimeout(drvUI.poll);
  if (d.running) drvUI.poll = setTimeout(() => leeDrive(), 1200);
}
async function leeDrive() {
  try { drvUI.data = await api('/drive' + projectQuery()); }
  catch (e) { const host = $('#drivepanel'); if (host) host.innerHTML = `<div class="lee-git-empty-state"><strong>No project</strong><span>${esc(e.message || e)}</span></div>`; return; }
  renderDrivePanel();
}
window.leeDrive = leeDrive;
async function driveOp(op, extra = {}) {
  try {
    drvUI.data = await post('/drive/action', {op, repo: projectRepo(), ...extra});
    if (op === 'step' || op === 'start') await openReleaseTerm(drvUI.data.root, 'drive');
    renderDrivePanel();
  } catch (e) { status(e.message || String(e), 'err'); }
}
async function driveTop(op, d) {
  if (op === 'terminal') return openReleaseTerm(d.root, 'drive');
  if (op === 'values') { leeLeft('workflows'); wfUI.view = 'env'; wfUI.env = null; return leeWorkflows(); }
  if (op === 'stop') { if (await confirmDialog('stop', 'Stop the running call?', 'stop')) driveOp('stop'); return; }
  if (op === 'reset') { if (await confirmDialog('reset', 'Forget what ran? The calls are unchanged.', 'reset')) driveOp('reset'); return; }
  if (op === 'start') {
    const missing = [...new Set(d.steps.flatMap(s => s.missing))];
    if (missing.length && !await confirmDialog('run every call',
        `These are not set: ${missing.join(', ')}. Run anyway?`, 'run')) return;
    return driveOp('start');
  }
}

async function renderGitPanel(snapshot = null) {
  const host = $('#gitpanel'); if (!host) return;
  host.dataset.features = 'Staged changes · Changes · Branches · Stashes · Remotes & tags · All repos · staged changes · working tree · fetch · pull · push · stash · tag · stage all · unstage all · fetch all · pull all · push all · clone';
  if (gitUI.tab === 'repos') {
    host.innerHTML = gitScope() + gitNav() + `<main class="lee-git-view">${gitReposView()}</main>`;
    wireGitPanel(host, gitUI.snapshot);
    if (!gitUI.repos) loadGitRepos();
    return;
  }
  if (!snapshot && !gitUI.snapshot) host.innerHTML = '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading repository</small></div>';
  let d = snapshot || gitUI.snapshot;
  try { if (!d) d = await api(gitUrl('/git/info')); }
  catch (e) {
    // Still draw the nav: a workspace whose active folder is not a checkout can have five
    // other repositories in it, and Repos is how you reach them.
    host.innerHTML = gitScope() + gitNav() +
      `<main class="lee-git-view"><div class="lee-git-empty-state"><strong>No Git repository</strong><span>${esc(e.message || e)}</span></div></main>`;
    // `null`, not `{}`: switching to another view from here must re-read the repository
    // rather than render a snapshot-shaped object with no fields in it.
    wireGitPanel(host, null);
    return;
  }
  gitUI.snapshot = d; paintGitPill(d);
  const view = gitUI.tab === 'changes' ? gitChangesView(d) : gitUI.tab === 'review' ? gitReviewView(d) : gitUI.tab === 'branches' ? gitBranchesView(d) : gitUI.tab === 'history' ? gitHistoryView(d) : gitResourcesView(d);
  host.innerHTML = gitScope() + gitSummary(d) + gitNav() + `<main class="lee-git-view">${view}</main>`;
  wireGitPanel(host, d);
  if (gitUI.tab === 'history' && !gitUI.history.length) loadGitHistory();
  if (gitUI.tab === 'review' && !gitUI.review) loadGitReview();
  if (gitUI.tab === 'resources') loadGitResources();
}
async function loadGitReview() {
  if (!gitUI.reviewBase || !gitUI.reviewHead) return;
  const host = $('.lee-git-review-workspace');
  if (host) host.innerHTML = '<div class="lee-git-loading"><span></span><span></span><span></span><small>building review</small></div>';
  try {
    gitUI.review = await api(gitUrl('/git/review', {base: gitUI.reviewBase, head: gitUI.reviewHead, mode: gitUI.reviewMode}));
    gitUI.reviewFile = gitUI.review.files[0]?.path || ''; gitUI.reviewPatch = '';
    renderGitPanel(gitUI.snapshot);
  } catch (e) { status(e.message || String(e), 'err'); }
}
async function loadGitReviewFile(path, asTab = false) {
  if (!gitUI.review) return;
  gitUI.reviewFile = path;
  try {
    const d = await api(gitUrl('/git/review/file', {base: gitUI.review.base, head: gitUI.review.head, mode: gitUI.review.mode, path}));
    gitUI.reviewPatch = d.patch || '';
    if (asTab) return openGitDiffTab({...d, path, kind: 'review', baseLabel: gitUI.review.base, headLabel: gitUI.review.head, absolutePath: gitUI.snapshot.root + '/' + path, reviewKey: gitReviewKey({...gitUI.review, root: gitUI.snapshot.root}, path), allowWrite: !!d.can_apply && !path.toLowerCase().endsWith('.ipynb')});
    renderGitPanel(gitUI.snapshot);
  } catch (e) { status(e.message || String(e), 'err'); }
}
function moveGitReviewFile(delta) {
  const files = gitUI.review?.files || [], at = files.findIndex(f => f.path === gitUI.reviewFile);
  if (!files.length) return;
  loadGitReviewFile(files[(Math.max(0, at) + delta + files.length) % files.length].path);
}
async function loadGitHistory() {
  const rows = $('#githistoryrows');
  try {
    const ref = $('#githistoryref')?.value || '--all';
    const result = await api(gitUrl('/git/history', {limit: 150, query: gitUI.historyQuery, ref}));
    gitUI.history = result.commits || []; renderGitPanel(gitUI.snapshot);
  } catch (e) { if (rows) rows.innerHTML = `<div class="lee-err">${esc(e.message || e)}</div>`; }
}
async function loadGitResources() {
  try {
    const r = await api(gitUrl('/git/resources'));
    const worktrees = $('#gitworktrees');
    if (worktrees) worktrees.innerHTML = (r.worktrees || []).map(w => `<article class="lee-git-resource-row" data-worktree="${esc(w.path)}"><div><strong>${esc(w.branch || 'detached')}</strong><code>${esc(w.path)}</code></div>${w.path === gitUI.snapshot.root ? '<i>current</i>' : '<button data-remove-worktree class="warn">remove</button>'}</article>`).join('') || '<span class="lee-dim">No worktrees</span>';
    const submodules = $('#gitsubmodules');
    if (submodules) submodules.innerHTML = (r.submodules || []).map(s => `<article class="lee-git-resource-row"><div><strong>${esc(s.path)}</strong><code>${esc(s.oid)}</code></div><i>${s.state === ' ' ? 'clean' : s.state === '-' ? 'not initialized' : s.state === '+' ? 'different commit' : 'conflict'}</i></article>`).join('') || '<span class="lee-dim">No submodules</span>';
    worktrees?.querySelectorAll('[data-remove-worktree]').forEach(b => b.onclick = async () => {
      const path = b.closest('[data-worktree]').dataset.worktree;
      if (await confirmDialog('remove worktree', `Remove ${path}? Uncommitted work prevents removal.`, 'remove')) renderGitPanel(await gitDo('remove_worktree', {path}));
    });
  } catch (e) { status(e.message || String(e), 'err'); }
}
function wireGitPanel(host, d) {
  host.querySelectorAll('[data-git-tab]').forEach(b => b.onclick = () => { gitUI.tab = b.dataset.gitTab; if (gitUI.tab !== 'history') gitUI.history = []; renderGitPanel(d); });
  host.querySelector('#gitscopeclear')?.addEventListener('click', () => gitPinRepo(''));
  host.querySelectorAll('[data-repos-op]').forEach(b => b.onclick = () => gitReposDo(b.dataset.reposOp));
  host.querySelectorAll('.lee-git-repo-row').forEach(row => {
    const root = row.dataset.repo;
    row.querySelector('[data-repo-open]').onclick = () => gitPinRepo(root === gitUI.repo ? '' : root);
    row.querySelector('[data-repo-fetch]').onclick = () => gitReposDo('fetch', {paths: [root]});
    row.querySelector('[data-repo-remove]').onclick = async () => {
      if (!await confirmDialog('remove repository', `Stop listing ${gitRepoName(root)} here? The checkout is left alone.`, 'remove')) return;
      if (gitUI.repo === root) gitUI.repo = '';
      gitReposDo('remove', {path: root});
    };
  });
  const expect = host.querySelector('#gitrepoexpect');
  if (expect) expect.onchange = () => { gitUI.expect = expect.value.trim(); loadGitRepos(); };
  host.querySelector('#gitrepoadd')?.addEventListener('click', async () => {
    const path = await inputDialog('add repository', 'Path to a Git checkout', '', '/home/you/code/project');
    if (path) gitReposDo('add', {path});
  });
  host.querySelector('#gitrepoclone')?.addEventListener('click', async () => {
    const spec = await inputDialog('clone repositories', 'URLs or owner/name, one per line', '', 'AnswerDotAI/fastws');
    if (spec) gitReposDo('clone', {urls: spec.split(/[\s,]+/).filter(Boolean)});
  });
  const act = async (op, extra = {}) => renderGitPanel(await gitDo(op, extra));
  host.querySelectorAll('[data-operation]').forEach(b => b.onclick = async () => {
    if (b.dataset.operation === 'abort' && !await confirmDialog('abort Git operation', `Abort the active ${d.operation.active}?`, 'abort')) return;
    act('operation_' + b.dataset.operation);
  });
  host.querySelectorAll('[data-git-undo]').forEach(b => b.onclick = async () => {
    const point = (d.safepoints || [])[0];
    if (!await confirmDialog('undo Git operation',
        `Put this repository back where it was before ${point?.describe || 'the last operation'}?` +
        `\n\nHEAD returns to ${point?.head || 'the recorded commit'}` +
        `${point?.dirty ? ` and ${point.dirty} uncommitted file(s) are restored` : ''}.`, 'undo')) return;
    act('undo', {token: b.dataset.gitUndo});
  });
  host.querySelectorAll('[data-top]').forEach(b => b.onclick = () => b.dataset.top === 'publish' ? act('push', {publish: true}) : act(b.dataset.top));
  host.querySelector('#scstageall')?.addEventListener('click', e => { e.preventDefault(); act('stage', {paths: d.changes.filter(x => x.unstaged).map(x => x.path)}); });
  host.querySelector('#scunstageall')?.addEventListener('click', e => { e.preventDefault(); act('unstage', {paths: d.changes.filter(x => x.staged).map(x => x.path)}); });
  host.querySelector('#scstash')?.addEventListener('click', async () => { const message = await inputDialog('stash changes', 'Optional message', '', 'work in progress'); if (message !== null) act('stash', {message}); });
  host.querySelector('#sccommit')?.addEventListener('submit', e => { e.preventDefault(); const message = e.target.querySelector('textarea').value.trim(); if (message) act('commit', {message, amend: e.target.elements.amend.checked}); });
  host.querySelector('#screviewstaged')?.addEventListener('click', () => showStagedReview(d));
  host.querySelectorAll('[data-selected-action]').forEach(b => b.onclick = async () => {
    const action = b.dataset.selectedAction;
    if (action === 'clear') { gitUI.selectedChanges.clear(); return renderGitPanel(d); }
    const selected = [...gitUI.selectedChanges].map(key => { const [group, ...parts] = key.split(':'); return {group, path: parts.join(':')}; });
    if (action === 'changelist') {
      const name = await inputDialog('move to changelist', 'Local changelist name', '', 'Focused change');
      if (name !== null) { for (const x of selected) { if (name) gitUI.changeLists[x.path] = name; else delete gitUI.changeLists[x.path]; } saveGitWorkflowState(); renderGitPanel(d); }
      return;
    }
    const paths = selected.filter(x => action === 'stage' ? x.group === 'unstaged' : x.group === 'staged').map(x => x.path);
    if (!paths.length) return status(`select ${action === 'stage' ? 'unstaged' : 'staged'} files`, 'err');
    gitUI.selectedChanges.clear(); act(action, {paths});
  });
  host.querySelectorAll('.lee-git-change').forEach(row => {
    const path = row.dataset.path, staged = row.dataset.group === 'staged';
    row.querySelector('[data-select-change]').onchange = e => { const key = `${row.dataset.group}:${path}`; if (e.target.checked) gitUI.selectedChanges.add(key); else gitUI.selectedChanges.delete(key); renderGitPanel(d); };
    row.querySelector('.lee-git-file').onclick = async () => { const patch = await api(gitUrl('/git/diff', {path, staged})); openGitDiffTab({kind: 'changes-' + row.dataset.group, path, absolutePath: d.root + '/' + path, base: staged ? 'HEAD' : 'index', head: staged ? 'index' : 'worktree', baseLabel: staged ? 'HEAD' : 'index', headLabel: staged ? 'staged' : 'working tree', left: patch.left || '', right: patch.right || '', patch: patch.content || patch.text || '', rawPatch: patch.text || '', notebook: !!patch.notebook, group: row.dataset.group, allowWrite: row.dataset.group === 'unstaged' && !patch.notebook}); };
    row.querySelector('[data-open]').onclick = () => leeOpenFile(d.root + '/' + path);
    row.querySelector('[data-blame]')?.addEventListener('click', () => showGitBlame(d.root, path, null));
    row.querySelector('[data-resolve]')?.addEventListener('click', () => showGitConflict(path));
    row.querySelectorAll('[data-git]').forEach(b => b.onclick = async () => { const op = b.dataset.git; if (op === 'discard' && !await confirmDialog('discard changes', `Restore ${path} from the index? This cannot be undone.`, 'discard')) return; act(op, {paths: [path]}); });
  });
  host.querySelectorAll('[data-stash]').forEach(row => { const ref = row.dataset.stash; row.querySelector('[data-apply]').onclick = () => act('stash_apply', {ref}); row.querySelector('[data-pop]').onclick = () => act('stash_pop', {ref}); row.querySelector('[data-drop]').onclick = async () => { if (await confirmDialog('drop stash', `Delete ${ref}?`, 'drop')) act('stash_drop', {ref}); }; });
  const branchFilter = host.querySelector('#gitbranchfilter'); if (branchFilter) branchFilter.oninput = () => { gitUI.branchQuery = branchFilter.value; renderGitPanel(d); requestAnimationFrame(() => { const x = $('#gitbranchfilter'); x?.focus(); x?.setSelectionRange(x.value.length, x.value.length); }); };
  const branchScope = host.querySelector('#gitbranchscope'); if (branchScope) { branchScope.value = gitUI.branchScope; branchScope.onchange = () => { gitUI.branchScope = branchScope.value; renderGitPanel(d); }; }
  host.querySelector('#scbranch')?.addEventListener('click', async () => { const branch = await inputDialog('new branch', 'Branch name', '', 'feature/name'); if (branch) act('create', {branch}); });
  host.querySelectorAll('[data-branch]').forEach(row => { const branch = row.dataset.branch; row.querySelector('[data-switch]').onclick = () => act('checkout', {branch}); row.querySelector('[data-compare]')?.addEventListener('click', () => { gitUI.reviewBase = d.branch; gitUI.reviewHead = branch; gitUI.reviewMode = 'review'; gitUI.review = null; gitUI.tab = 'review'; renderGitPanel(d); }); row.querySelector('[data-more]')?.addEventListener('click', () => branchActions(branch, d, act)); });
  host.querySelector('#sctag')?.addEventListener('click', async () => { const name = await inputDialog('create tag', 'Tag name', '', 'v1.0.0'); if (!name) return; const message = await inputDialog('annotated tag', 'Optional annotation', '', ''); if (message !== null) act('tag', {name, message}); });
  host.querySelectorAll('[data-delete-tag]').forEach(b => b.onclick = async () => { const name = b.closest('[data-tag]').dataset.tag; if (await confirmDialog('delete tag', `Delete local tag ${name}?`, 'delete')) act('delete_tag', {name}); });
  host.querySelector('#gitreviewmode') && (host.querySelector('#gitreviewmode').value = gitUI.reviewMode);
  const swapReviewDirection = () => { const base = $('#gitreviewbase')?.value.trim() || gitUI.reviewBase; gitUI.reviewBase = $('#gitreviewhead')?.value.trim() || gitUI.reviewHead; gitUI.reviewHead = base; gitUI.review = null; loadGitReview(); };
  host.querySelector('#gitreviewcontrolswap')?.addEventListener('click', swapReviewDirection);
  host.querySelector('#gitreviewswap')?.addEventListener('click', swapReviewDirection);
  host.querySelector('#gitreviewsnapshot')?.addEventListener('click', () => { gitUI.reviewMode = 'snapshot'; gitUI.review = null; loadGitReview(); });
  host.querySelector('#gitreviewload')?.addEventListener('click', () => { gitUI.reviewBase = $('#gitreviewbase').value.trim(); gitUI.reviewHead = $('#gitreviewhead').value.trim(); gitUI.reviewMode = $('#gitreviewmode').value; gitUI.review = null; loadGitReview(); });
  host.querySelectorAll('[data-review-path]').forEach(b => b.onclick = () => loadGitReviewFile(b.dataset.reviewPath, true));
  host.querySelector('#gitreviewprev')?.addEventListener('click', () => moveGitReviewFile(-1));
  host.querySelector('#gitreviewnext')?.addEventListener('click', () => moveGitReviewFile(1));
  host.querySelector('#gitreviewmark')?.addEventListener('click', () => { const key = gitReviewKey({...gitUI.review, root: d.root}, gitUI.reviewFile); gitUI.reviewed[key] = !gitUI.reviewed[key]; saveGitWorkflowState(); renderGitPanel(d); });
  host.querySelector('#gitreviewnote')?.addEventListener('click', async () => { const key = gitReviewKey({...gitUI.review, root: d.root}, gitUI.reviewFile), note = await inputDialog('review note', `Note for ${gitUI.reviewFile}`, gitUI.reviewNotes[key] || '', 'Question, risk, or follow-up'); if (note !== null) { if (note.trim()) gitUI.reviewNotes[key] = note.trim(); else delete gitUI.reviewNotes[key]; saveGitWorkflowState(); renderGitPanel(d); } });
  host.querySelector('#gitreviewcopynotes')?.addEventListener('click', async () => { const prefix = `${d.root}\0${gitUI.review.base}\0${gitUI.review.head}\0${gitUI.review.mode}\0`, rows = Object.entries(gitUI.reviewNotes).filter(([key]) => key.startsWith(prefix)).map(([key, note]) => `- **${key.slice(prefix.length)}** — ${note}`); if (!rows.length) return status('this review has no notes', 'err'); const text = `# Review: ${gitUI.review.head} → ${gitUI.review.base}\n\n${rows.join('\n')}\n`; try { await navigator.clipboard.writeText(text); status(`copied ${rows.length} review note${rows.length === 1 ? '' : 's'}`, 'ok'); } catch (_) { status('clipboard access failed', 'err'); } });
  host.querySelector('#gitreviewapply')?.addEventListener('click', () => showReviewHunkApply(d));
  host.querySelector('#githistorygo')?.addEventListener('click', () => { gitUI.historyQuery = $('#githistoryfilter').value.trim(); gitUI.history = []; gitUI.selectedCommit = null; loadGitHistory(); });
  host.querySelector('#githistoryfilter')?.addEventListener('keydown', e => { if (e.key === 'Enter') { gitUI.historyQuery = e.target.value.trim(); gitUI.history = []; gitUI.selectedCommit = null; loadGitHistory(); } });
  host.querySelector('#githistoryref')?.addEventListener('change', () => { gitUI.history = []; gitUI.selectedCommit = null; loadGitHistory(); });
  host.querySelector('#gitreflog')?.addEventListener('click', showGitReflog);
  host.querySelectorAll('[data-history-commit]').forEach(b => b.onclick = () => loadGitCommitInspector(b.dataset.historyCommit));
  host.querySelectorAll('[data-commit]').forEach(b => b.onclick = () => showGitCommit(b.dataset.commit));
  host.querySelectorAll('[data-commit-file]').forEach(b => b.onclick = () => openGitCommitFile(gitUI.selectedCommit.oid, b.dataset.commitFile));
  host.querySelector('[data-close-commit]')?.addEventListener('click', () => { gitUI.selectedCommit = null; renderGitPanel(d); });
  host.querySelector('.lee-git-commit-inspector [data-cherry]')?.addEventListener('click', () => act('cherry_pick', {ref: gitUI.selectedCommit.oid}));
  host.querySelector('.lee-git-commit-inspector [data-revert]')?.addEventListener('click', async () => { if (await confirmDialog('revert commit', `Create a commit that reverses ${gitUI.selectedCommit.short}?`, 'revert')) act('revert', {ref: gitUI.selectedCommit.oid}); });
  host.querySelector('.lee-git-commit-inspector [data-reset]')?.addEventListener('click', async () => { const c = gitUI.selectedCommit, mode = await inputDialog('reset branch', 'Mode: soft keeps index; mixed keeps files; hard discards changes', 'mixed', 'soft, mixed, or hard'); if (!['soft','mixed','hard'].includes(mode)) return status('reset mode must be soft, mixed, or hard', 'err'); if (mode === 'hard' && !await confirmDialog('hard reset', `Discard tracked changes and reset to ${c.short}? This cannot be undone.`, 'reset')) return; act('reset', {ref: c.oid, mode}); });
  const rememberCompare = () => { gitUI.compareFrom = $('#gitcompareleft')?.value.trim() || ''; gitUI.compareTo = $('#gitcompareright')?.value.trim() || ''; };
  host.querySelector('#gitcompareleft')?.addEventListener('change', rememberCompare);
  host.querySelector('#gitcompareright')?.addEventListener('change', rememberCompare);
  host.querySelector('#gitcompareswap')?.addEventListener('click', () => { const left = $('#gitcompareleft'), right = $('#gitcompareright'), value = left.value; left.value = right.value; right.value = value; rememberCompare(); });
  host.querySelector('#gitcomparego')?.addEventListener('click', () => { rememberCompare(); showGitCompare(gitUI.compareFrom, gitUI.compareTo); });
  host.querySelector('[data-hosted-pr]')?.addEventListener('click', e => window.open(e.currentTarget.dataset.url, '_blank', 'noopener,noreferrer'));
  host.querySelector('#gitaddremote')?.addEventListener('click', async () => { const name = await inputDialog('add remote', 'Remote name', '', 'origin'); if (!name) return; const url = await inputDialog('add remote', 'Fetch URL', '', 'https://github.com/owner/repository.git'); if (url) act('add_remote', {name, url}); });
  host.querySelectorAll('[data-remote]').forEach(row => { const remote = row.dataset.remote; row.querySelector('[data-open-remote]')?.addEventListener('click', b => window.open(b.currentTarget.dataset.url, '_blank', 'noopener,noreferrer')); row.querySelector('[data-fetch-remote]').onclick = () => act('fetch', {remote}); row.querySelector('[data-edit-remote]').onclick = async () => { const url = await inputDialog('edit remote', `${remote} fetch URL`, row.querySelector('code').textContent, 'https://github.com/owner/repository.git'); if (url) act('set_remote', {name: remote, url}); }; row.querySelector('[data-remove-remote]').onclick = async () => { if (await confirmDialog('remove remote', `Remove ${remote}? Local commits and branches remain.`, 'remove')) act('remove_remote', {name: remote}); }; });
  host.querySelector('#gitaddworktree')?.addEventListener('click', async () => { const path = await inputDialog('add worktree', 'Directory path', '', '../project-feature'); if (!path) return; const branch = await inputDialog('add worktree', 'Existing branch, or a new branch name', '', 'feature/name'); if (branch) act('add_worktree', {path, branch, create: !(d.branches || []).some(b => !b.remote && b.name === branch)}); });
}
async function showStagedReview(d) {
  const files = (d.changes || []).filter(c => c.staged);
  if (!files.length) return status('stage changes before reviewing them', 'err');
  const m = modal(`<div class="lee-mhead">Review staged changes<span class="sub">${files.length} file${files.length === 1 ? '' : 's'} will be committed</span><span class="lee-spacer"></span><button class="lee-btn" data-prev>previous</button><button class="lee-btn" data-next>next</button></div><div class="lee-git-full-review"><aside></aside><main class="lee-git-patch"></main></div><div class="lee-mfoot"><span class="lee-dim">Only the index is shown. Unstaged edits are not part of the commit.</span></div>`);
  m.classList.add('lee-git-review-expanded');
  let at = 0;
  const paint = async next => {
    at = (next + files.length) % files.length;
    const active = files[at];
    m.querySelector('aside').innerHTML = files.map((f, i) => `<button data-index="${i}" class="${i === at ? 'active' : ''}"><b>${esc(f.index)}</b><span>${esc(f.path)}</span></button>`).join('');
    m.querySelectorAll('[data-index]').forEach(b => b.onclick = () => paint(+b.dataset.index));
    const detail = await api(gitUrl('/git/diff', {path: active.path, staged: true}));
    m.querySelector('main').innerHTML = gitPatchHtml(detail.content || detail.text || '');
  };
  m.querySelector('[data-prev]').onclick = () => paint(at - 1);
  m.querySelector('[data-next]').onclick = () => paint(at + 1);
  paint(0);
}
function showReviewHunkApply(d) {
  if (!gitUI.reviewPatch || !gitUI.review?.can_apply) return status('partial apply requires a clean current branch that is the review base', 'err');
  const parts = gitPatchParts(gitUI.reviewPatch);
  if (!parts.hunks.length) return status('this file has no text hunks to apply', 'err');
  const m = modal(`<div class="lee-mhead">Apply parts of ${esc(gitUI.reviewFile)}<span class="sub">from ${esc(gitUI.review.head)} into the current working tree</span></div><div class="lee-git-patch">${parts.hunks.map((h, i) => `<label class="lee-git-hunk"><input type="checkbox" data-hunk="${i}" checked><span>hunk ${i + 1}</span>${gitPatchHtml(h)}</label>`).join('')}</div><div class="lee-mfoot"><button class="lee-btn go" data-apply>apply selected hunks</button><span class="lee-dim">Changes remain uncommitted and can be reviewed before staging.</span></div>`);
  m.querySelector('[data-apply]').onclick = async () => {
    const selected = [...m.querySelectorAll('[data-hunk]:checked')].map(x => parts.hunks[+x.dataset.hunk]);
    if (!selected.length) return status('select at least one hunk', 'err');
    if (!await confirmDialog('apply branch hunks', `Apply ${selected.length} selected hunk${selected.length === 1 ? '' : 's'} from ${gitUI.review.head} to the working tree?`, 'apply')) return;
    try { const next = await gitDo('apply_patch', {patch: parts.header + selected.join(''), staged: false}); m.remove(); gitUI.review = null; gitUI.tab = 'changes'; renderGitPanel(next); }
    catch (e) { status(e.message || String(e), 'err'); }
  };
}
async function showMergePreview(branch, d, act) {
  try {
    const p = await api(gitUrl('/git/merge-preview', {incoming: branch}));
    const r = p.review, relation = {'fast-forward': 'Fast-forward available', 'already-merged': 'Already contained in current', 'identical': 'Branches are identical', 'diverged': 'Branches have diverged'}[p.relation] || p.relation;
    const conflict = p.conflict_likely ? `<div class="lee-git-merge-warning"><strong>Conflicts expected</strong><span>${p.conflicts.length ? p.conflicts.map(esc).join(' · ') : 'Git reports overlapping changes.'}</span></div>` : '<div class="lee-git-merge-ok"><strong>No conflicts found in merge rehearsal</strong><span>The working tree can still change before merge.</span></div>';
    // Untracked files are not dirt: git merges beside them and refuses only when the merge
    // would overwrite one, at which point it says so itself. Only tracked work blocks.
    const dirty = p.clean ? '' : `<div class="lee-git-merge-warning"><strong>Uncommitted changes to ${p.dirty.length} tracked file${p.dirty.length === 1 ? '' : 's'}</strong><span>${p.dirty.map(esc).join(' · ')}</span></div>`;
    const blocked = !p.clean ? `commit or stash ${p.dirty.length} changed file${p.dirty.length === 1 ? '' : 's'} first`
                  : p.relation === 'already-merged' ? `${p.current} already contains ${branch}`
                  : p.relation === 'identical' ? 'the two branches are identical' : '';
    const m = modal(`<div class="lee-mhead">Merge ${esc(branch)}<span class="sub">into ${esc(p.current)}</span></div><div class="lee-git-merge-preview"><header><strong>${esc(relation)}</strong><span>${r.head_only} commits · ${r.summary.files} files · +${r.summary.additions} −${r.summary.deletions}</span></header>${dirty}${conflict}<label>Strategy<select data-strategy><option value="merge">merge commit when needed</option><option value="squash">squash into working tree</option><option value="ff-only" ${p.relation === 'fast-forward' ? '' : 'disabled'}>fast-forward only</option></select></label><button class="lee-btn" data-review>review incoming files</button></div><div class="lee-mfoot"><button class="lee-btn go" data-merge>merge ${esc(branch)}</button><span class="lee-dim">${blocked ? esc(blocked) : 'Merge starts only after this preview.'}</span></div>`);
    m.querySelector('[data-review]').onclick = () => { m.remove(); gitUI.reviewBase = d.branch; gitUI.reviewHead = branch; gitUI.reviewMode = 'review'; gitUI.review = null; gitUI.tab = 'review'; renderGitPanel(d); };
    // Never a disabled button: one that cannot be pressed cannot say why, and "I clicked
    // merge and nothing happened" is the report that came back from exactly that.
    m.querySelector('[data-merge]').onclick = async () => {
      if (blocked) return status(`cannot merge — ${blocked}`, 'err');
      const strategy = m.querySelector('[data-strategy]').value;
      if (!await confirmDialog('merge branch', `Merge ${branch} into ${p.current} using ${strategy}?`, 'merge')) return;
      m.remove(); act('merge', {branch, strategy});
    };
  } catch (e) { status(e.message || String(e), 'err'); }
}
async function showRebasePreview(branch, d, act) {
  try {
    const p = await api(gitUrl('/git/rebase-preview', {onto: branch})), r = p.review;
    const warning = p.conflict_likely ? `<div class="lee-git-merge-warning"><strong>Conflicts may occur while replaying commits</strong><span>${p.conflicts.length ? p.conflicts.map(esc).join(' · ') : 'Git reports overlapping changes.'}</span></div>` : '<div class="lee-git-merge-ok"><strong>No conflicts found in the tree rehearsal</strong><span>Rebase replays commits individually, so this remains a forecast.</span></div>';
    const rbDirty = p.clean ? '' : `<div class="lee-git-merge-warning"><strong>Uncommitted changes to ${p.dirty.length} tracked file${p.dirty.length === 1 ? '' : 's'}</strong><span>${p.dirty.map(esc).join(' · ')}</span></div>`;
    const rbBlocked = !p.clean ? `commit or stash ${p.dirty.length} changed file${p.dirty.length === 1 ? '' : 's'} first`
                    : p.already_based ? `${p.current} already contains ${branch}`
                    : !p.commits.length ? 'there is nothing to replay' : '';
    const m = modal(`<div class="lee-mhead">Rebase ${esc(p.current)}<span class="sub">onto ${esc(branch)}</span></div><div class="lee-git-merge-preview"><header><strong>${p.already_based ? 'Branch already contains the target history' : `${p.commits.length} commit${p.commits.length === 1 ? '' : 's'} will be replayed`}</strong><span>${r.summary.files} proposed files · +${r.summary.additions} −${r.summary.deletions}</span></header>${rbDirty}${warning}<div class="lee-git-rebase-commits">${p.commits.slice(0, 12).map(c => `<span><code>${esc(c.short)}</code>${esc(c.subject)}</span>`).join('')}</div><button class="lee-btn" data-review>review branch changes</button></div><div class="lee-mfoot"><button class="lee-btn go" data-rebase>start rebase</button><span class="lee-dim">The operation banner will offer continue, skip, and abort if Git pauses.</span></div>`);
    m.querySelector('[data-review]').onclick = () => { m.remove(); gitUI.reviewBase = branch; gitUI.reviewHead = d.branch; gitUI.reviewMode = 'review'; gitUI.review = null; gitUI.tab = 'review'; renderGitPanel(d); };
    m.querySelector('[data-rebase]').onclick = async () => {
      if (rbBlocked) return status(`cannot rebase — ${rbBlocked}`, 'err');
      if (!await confirmDialog('rebase branch', `Replay ${p.commits.length} commit${p.commits.length === 1 ? '' : 's'} from ${p.current} onto ${branch}?`, 'rebase')) return;
      m.remove(); act('rebase', {branch});
    };
  } catch (e) { status(e.message || String(e), 'err'); }
}
async function branchActions(branch, d, act) {
  const m = modal(`<div class="lee-mhead">${esc(branch)}<span class="sub">branch actions</span></div><div class="lee-branch-actions">` +
    `<button class="lee-btn" data-op="merge">merge into ${esc(d.branch)}</button><button class="lee-btn" data-op="rebase">rebase current onto branch</button>` +
    `<button class="lee-btn" data-op="rename">rename</button><button class="lee-btn" data-op="upstream">set upstream</button><button class="lee-btn" data-op="compare">review selected into current</button>` +
    `<button class="lee-btn warn" data-op="delete">delete local branch</button></div>`);
  m.querySelectorAll('[data-op]').forEach(b => b.onclick = async () => {
    const op = b.dataset.op;
    if (op === 'delete') { if (!await confirmDialog('delete branch', `Delete local branch ${branch}?`, 'delete')) return; m.remove(); return act('delete', {branch}); }
    if (op === 'rename') { const name = await inputDialog('rename branch', 'New name', branch, 'feature/name'); if (name) { m.remove(); act('rename_branch', {branch, name}); } return; }
    if (op === 'upstream') { const upstream = await inputDialog('set upstream', 'Remote tracking branch', '', 'origin/' + branch); if (upstream) { m.remove(); act('set_upstream', {branch, upstream}); } return; }
    if (op === 'compare') { m.remove(); gitUI.reviewBase = d.branch; gitUI.reviewHead = branch; gitUI.reviewMode = 'review'; gitUI.review = null; gitUI.tab = 'review'; return renderGitPanel(d); }
    if (op === 'merge') { m.remove(); return showMergePreview(branch, d, act); }
    if (op === 'rebase') { m.remove(); return showRebasePreview(branch, d, act); }
    m.remove(); act(op, {branch});
  });
}
async function loadGitCommitInspector(ref) {
  try { gitUI.selectedCommit = await api(gitUrl('/git/commit/review', {ref})); renderGitPanel(gitUI.snapshot); }
  catch (e) { status(e.message || String(e), 'err'); }
}
async function openGitCommitFile(ref, path) {
  try {
    const d = await api(gitUrl('/git/commit/file', {ref, path}));
    const c = gitUI.selectedCommit;
    return openGitDiffTab({...d, path, kind: 'commit', baseLabel: c?.parents?.[0]?.slice(0, 8) || 'empty tree', headLabel: c?.short || ref.slice(0, 8), absolutePath: gitUI.snapshot.root + '/' + path});
  } catch (e) { status(e.message || String(e), 'err'); }
}
async function showGitCommit(ref) {
  try {
    const c = await api(gitUrl('/git/commit/review', {ref}));
    const files = c.files.map(f => `<button class="lee-git-commit-file" data-path="${esc(f.path)}"><b>${esc(f.status)}</b><span>${esc(f.path)}</span><small>${f.binary ? 'binary' : `+${f.additions} −${f.deletions}`}</small></button>`).join('');
    const m = modal(`<div class="lee-mhead">${esc(c.short)}<span class="sub">${esc(c.author)} · ${new Date(c.timestamp * 1000).toLocaleString()}</span></div><article class="lee-git-commit-sheet"><h3>${esc(c.message)}</h3><section><b>${c.summary.files} files</b><span>+${c.summary.additions}</span><span>−${c.summary.deletions}</span></section><div>${files}</div></article>`);
    m.querySelectorAll('[data-path]').forEach(b => b.onclick = () => { m.remove(); gitUI.selectedCommit = c; openGitCommitFile(c.oid, b.dataset.path); });
  } catch (e) { status(e.message || String(e), 'err'); }
}
async function showGitCompare(left, right) {
  if (!left || !right) return status('choose a base and target ref', 'err');
  gitUI.reviewBase = left; gitUI.reviewHead = right; gitUI.reviewMode = 'snapshot';
  gitUI.review = null; gitUI.reviewFile = ''; gitUI.reviewPatch = ''; gitUI.tab = 'review';
  await renderGitPanel(gitUI.snapshot);
}
async function showGitReflog() {
  try {
    const d = await api(gitUrl('/git/reflog', {limit: 150}));
    const m = modal(`<div class="lee-mhead">reflog<span class="sub">local recovery history · newest first</span></div><div class="lee-git-history">${(d.entries || []).map(x => `<button class="lee-git-commit-row" data-commit="${x.oid}"><span class="lee-git-graph">◆</span><span><strong>${esc(x.subject)}</strong><small>${esc(x.selector)} · ${esc(x.author)} · ${gitRelative(x.timestamp)} · ${esc(x.short)}</small></span></button>`).join('') || '<div class="lee-git-empty-state"><strong>No reflog entries</strong><span>This repository has no local movement history.</span></div>'}</div>`);
    m.querySelectorAll('[data-commit]').forEach(b => b.onclick = () => showGitCommit(b.dataset.commit));
  } catch (e) { status(e.message || String(e), 'err'); }
}
// Three-pane conflict resolution: ours, an editable result, and theirs.
//
// The conflicts are read from the markers Git already wrote into the working-tree file, not
// diffed back out of the three versions. Git's own account of what it could not decide is
// better than anything reconstructed from the sides afterwards -- it knows which lines it
// tried to merge and gave up on, and a re-diff only guesses at it.
//
// The result pane is that file, markers and all, and it is re-scanned after every change.
// That is what lets the buttons and hand-editing coexist without either being a mode:
// "which conflicts are left" is answered by looking at the text rather than by remembering
// what was clicked, so an edit that removes a marker block counts as resolving it.

const CONFLICT_OPEN = /^<{7}(?:\s|$)/, CONFLICT_MID = /^={7}(?:\s|$)/,
      CONFLICT_BASE = /^\|{7}(?:\s|$)/, CONFLICT_CLOSE = /^>{7}(?:\s|$)/;

function scanConflicts(text) {
  const lines = String(text ?? '').split('\n'), blocks = [];
  for (let i = 0; i < lines.length; i++) {
    if (!CONFLICT_OPEN.test(lines[i])) continue;
    const block = {start: i, end: -1, ours: [], theirs: [], base: []};
    let side = block.ours, j = i + 1;
    for (; j < lines.length; j++) {
      if (CONFLICT_BASE.test(lines[j])) { side = block.base; continue; }
      if (CONFLICT_MID.test(lines[j])) { side = block.theirs; continue; }
      if (CONFLICT_CLOSE.test(lines[j])) { block.end = j; break; }
      side.push(lines[j]);
    }
    // An opening marker with no close is a line of text that happens to look like one --
    // in a file *about* merge conflicts, say. Not a conflict, and not ours to rewrite.
    if (block.end < 0) continue;
    blocks.push(block); i = block.end;
  }
  return {lines, blocks};
}

// One whole side of a conflicted file, as it would read if every contested block went that
// way. `ranges` are the 1-based line spans of the contested parts, for marking them.
function conflictSide(scan, pick) {
  const out = [], ranges = [];
  let at = 0;
  for (const block of scan.blocks) {
    out.push(...scan.lines.slice(at, block.start));
    const from = out.length + 1;
    out.push(...(block[pick] || []));
    // A side that deleted these lines contributes none, so the marker goes on the seam.
    ranges.push(out.length >= from ? {from, to: out.length}
                                   : {from: Math.max(1, from - 1), to: Math.max(1, from - 1)});
    at = block.end + 1;
  }
  out.push(...scan.lines.slice(at));
  return {text: out.join('\n'), ranges};
}

function replaceConflict(scan, index, lines) {
  const block = scan.blocks[index];
  if (!block) return null;
  return [...scan.lines.slice(0, block.start), ...lines,
          ...scan.lines.slice(block.end + 1)].join('\n');
}

async function showGitConflict(path) {
  try {
    const d = await api(gitUrl('/git/conflict', {path}));
    const original = scanConflicts(d.worktree || '');
    if (!original.blocks.length && (d.ours || d.theirs)) {
      // Add/add or delete/modify: there are no marked lines to work through, so the choice
      // is which whole side to keep, and pretending otherwise would be a worse dialog.
      return showWholeSideConflict(path, d);
    }
    const lang = codeLang('', path);
    const pane = (key, label, note) =>
      `<section data-pane="${key}"${key === 'base' ? ' hidden' : ''}>` +
      `<header><strong>${label}</strong>${note ? `<small>${note}</small>` : ''}</header>` +
      `<div class="lee-merge3-editor" data-editor></div></section>`;
    const m = modal(
      `<div class="lee-mhead">resolve ${esc(path)}<span class="sub">ours · result · theirs</span></div>` +
      `<div class="lee-git-merge3">` +
      `<div class="lee-merge3-bar">` +
      `<span class="lee-merge3-count" data-count></span>` +
      `<button class="lee-btn" data-nav="prev" title="previous conflict">‹</button>` +
      `<button class="lee-btn" data-nav="next" title="next conflict">›</button>` +
      `<span class="lee-merge3-take">` +
      `<button class="lee-btn" data-take="ours">take ours</button>` +
      `<button class="lee-btn" data-take="theirs">take theirs</button>` +
      `<button class="lee-btn" data-take="both">both</button></span>` +
      `<button class="lee-btn" data-base-toggle>show base</button></div>` +
      `<div class="lee-merge3-panes">${pane('base', 'base', 'common ancestor')}` +
      `${pane('ours', 'ours', 'this branch')}` +
      `${pane('result', 'result', 'editable')}` +
      `${pane('theirs', 'theirs', 'incoming')}</div>` +
      `<div class="lee-merge3-foot"><span class="lee-dim" data-state></span>` +
      `<button class="lee-btn go" data-resolve>resolve &amp; stage</button></div></div>`,
      null, () => teardown(), {className: 'lee-modal-merge3', storageKey: 'git-conflict'});

    const views = {};
    const editorFor = key => m.querySelector(`[data-pane="${key}"] [data-editor]`);
    const teardown = () => Object.values(views).forEach(v => { try { LeeCM.destroy(v); } catch {} });
    let live = original, active = 0;

    const marks = (ranges, current) => ranges.map((r, i) =>
      ({...r, kind: i === current ? 'conflict-active' : 'conflict'}));

    for (const key of ['base', 'ours', 'theirs']) {
      const {text, ranges} = conflictSide(original, key);
      views[key] = LeeCM.create(editorFor(key), {
        doc: text, lang, readOnly: true, lineNums: true, settings: lee.editorPrefs});
      views[key]._ranges = ranges;
      LeeCM.setChangedLines(views[key], marks(ranges, 0));
    }
    // `onChange` runs inside CodeMirror's own update, where dispatching again is not allowed,
    // and `refresh` dispatches marks -- hence the deferral. `programmatic` is why a button's own
    // `setDoc` does not come back round here and refresh a second time from stale text.
    let programmatic = false;
    views.result = LeeCM.create(editorFor('result'), {
      doc: d.worktree || '', lang, lineNums: true, settings: lee.editorPrefs,
      onChange: text => { if (!programmatic) setTimeout(() => refresh(text, false), 0); }});

    // Which of the original blocks a remaining one is, matched on its contested text. Indices
    // cannot be used: resolving the second of three leaves two, and the sides still show three.
    // Two identical conflicts in one file align to the first of them, which is harmless.
    const originalIndex = block => original.blocks.findIndex(b =>
      b.ours.join('\n') === block.ours.join('\n') && b.theirs.join('\n') === block.theirs.join('\n'));

    // The side panes are read-only and CodeMirror only builds the lines it is showing, so
    // there is no element to scroll to for a conflict that is off screen. Proportional
    // scrolling gets there regardless, and lands close enough to read.
    const align = () => {
      const block = live.blocks[active];
      const index = block ? originalIndex(block) : -1;
      for (const key of ['base', 'ours', 'theirs']) {
        const view = views[key], range = index >= 0 ? view._ranges[index] : null;
        LeeCM.setChangedLines(view, marks(view._ranges, index));
        const scroller = view.dom.querySelector('.cm-scroller');
        if (!range || !scroller) continue;
        const total = Math.max(1, LeeCM.lineCount(view));
        scroller.scrollTop = Math.max(0, (range.from - 1) / total * scroller.scrollHeight
                                         - scroller.clientHeight / 3);
      }
    };

    const refresh = (text, move = true) => {
      live = scanConflicts(text ?? LeeCM.getDoc(views.result));
      const total = live.blocks.length;
      active = Math.max(0, Math.min(active, total - 1));
      const done = original.blocks.length - total;
      m.querySelector('[data-count]').textContent = total
        ? `conflict ${active + 1} of ${total}` : 'no conflicts left';
      m.querySelector('[data-state]').textContent = total
        ? `${done} of ${original.blocks.length} resolved`
        : `all ${original.blocks.length} resolved — staging marks this file merged`;
      m.querySelectorAll('[data-take],[data-nav]').forEach(b => b.disabled = !total);
      m.querySelector('[data-resolve]').classList.toggle('go', !total);
      LeeCM.setChangedLines(views.result, marks(
        live.blocks.map(b => ({from: b.start + 1, to: b.end + 1})), active));
      if (move) align();
    };

    const jumpTo = index => {
      const total = live.blocks.length;
      if (!total) return;
      active = (index + total) % total;
      const block = live.blocks[active];
      const at = live.lines.slice(0, block.start).reduce((n, l) => n + l.length + 1, 0);
      refresh(null, true);
      LeeCM.setSelection(views.result, at, at);
    };

    const take = which => {
      const block = live.blocks[active];
      if (!block) return;
      const lines = which === 'both' ? [...block.ours, ...block.theirs] : block[which];
      const next = replaceConflict(live, active, lines);
      if (next == null) return;
      programmatic = true;
      try { LeeCM.setDoc(views.result, next); } finally { programmatic = false; }
      refresh(next, true);
      if (live.blocks.length) jumpTo(Math.min(active, live.blocks.length - 1));
    };

    m.querySelectorAll('[data-take]').forEach(b => b.onclick = () => take(b.dataset.take));
    m.querySelector('[data-nav="prev"]').onclick = () => jumpTo(active - 1);
    m.querySelector('[data-nav="next"]').onclick = () => jumpTo(active + 1);
    m.querySelector('[data-base-toggle]').onclick = e => {
      const section = m.querySelector('[data-pane="base"]');
      section.hidden = !section.hidden;
      e.currentTarget.textContent = section.hidden ? 'show base' : 'hide base';
      if (!section.hidden) align();
    };
    m.querySelector('[data-resolve]').onclick = async () => {
      const content = LeeCM.getDoc(views.result);
      const left = scanConflicts(content).blocks.length;
      if (left && !await confirmDialog('stage an unresolved file',
          `${left} conflict marker block${left === 1 ? '' : 's'} are still in ${path}. Stage it ` +
          `anyway, markers and all?`, 'stage anyway')) return;
      const next = await gitDo('resolve_conflict', {path, choice: 'resolved', content});
      m.remove();
      renderGitPanel(next);
      status(next.outcome?.summary || `${path} staged as resolved`, 'ok');
    };
    refresh(d.worktree || '', true);
    jumpTo(0);
  } catch (e) { status(e.message || String(e), 'err'); }
}

// Add/add and delete/modify conflicts have no contested lines to work through -- one side has
// no file at all -- so the only question is which side to keep.
async function showWholeSideConflict(path, d) {
  const side = (label, text, choice) =>
    `<section><header><strong>${label}</strong>` +
    `<button class="lee-btn" data-choice="${choice}">use ${label}</button></header>` +
    `<pre>${esc(text || 'This side does not have this file.')}</pre></section>`;
  const m = modal(
    `<div class="lee-mhead">resolve ${esc(path)}<span class="sub">one side has no file to merge</span></div>` +
    `<div class="lee-git-conflict">${side('ours', d.ours, 'ours')}${side('theirs', d.theirs, 'theirs')}` +
    `<details><summary>common base</summary><pre>${esc(d.base || 'No common base content.')}</pre></details></div>`,
    null, null, {storageKey: 'git-conflict-side'});
  m.querySelectorAll('[data-choice]').forEach(b => b.onclick = async () => {
    const choice = b.dataset.choice;
    if (!await confirmDialog('resolve conflict', `Use ${choice} for ${path} and stage it as resolved?`, 'resolve')) return;
    m.remove();
    const next = await gitDo('resolve_conflict', {path, choice});
    renderGitPanel(next);
    status(next.outcome?.summary || `${path} staged as resolved`, 'ok');
  });
}

// Blame, reachable from wherever you are rather than only from a changed-file row. A text
// file blames the lines you have selected -- "who wrote these six" is the question, and the
// whole-file answer is one button away. A notebook blames its cells, because blaming its
// JSON tells you about `"source": [` and nothing about your code.
function blameRelative(root, path) {
  const p = String(path || '');
  if (!root) return p;
  return p.startsWith(root + '/') ? p.slice(root.length + 1) : p;
}
function blameSelectionRange() {
  const view = curEditor(); if (!view || lee.kind === 'notebook') return null;
  const sel = view.state.selection.main;
  if (sel.empty) return null;
  const doc = view.state.doc;
  return {start: doc.lineAt(sel.from).number, end: doc.lineAt(sel.to).number};
}
async function leeBlame() {
  if (!lee.path) return status('open a file to blame it', 'err');
  let root = gitUI.snapshot?.root;
  if (!root) { try { root = (await api(gitUrl('/git/info'))).root; } catch (e) { return status(e.message || String(e), 'err'); } }
  showGitBlame(root, blameRelative(root, lee.path), blameSelectionRange());
}
window.leeBlame = leeBlame;
function blameHue(oid, commits) {
  // Colour by commit so a cell made of three commits reads as three bands. Position in the
  // recency-sorted legend, not a hash: the newest change is the one being looked for.
  const i = commits.findIndex(c => c.oid === oid);
  return i < 0 ? 'var(--lee-fg4)' : `hsl(${(i * 47) % 360} 55% 55%)`;
}
function blameLineRows(lines, commits, showN) {
  return lines.map(l => `<button class="lee-blame-line${l.uncommitted ? ' uncommitted' : ''}" data-commit="${esc(l.oid)}" ` +
    `title="${esc(l.author)} · ${esc(l.summary || '')}">` +
    `<i style="background:${blameHue(l.oid, commits)}"></i>` +
    `<code>${l.uncommitted ? 'working' : esc(l.oid.slice(0, 8))}</code>` +
    `<span class="lee-blame-who">${esc(l.author || '')}</span>` +
    `<small>${l.timestamp ? gitRelative(l.timestamp) : ''}</small>` +
    `<em>${showN ? l.n : l.line}</em><pre>${esc(l.text)}</pre></button>`).join('');
}
function blameCells(d) {
  const commits = d.commits || [];
  const legend = commits.length ? `<div class="lee-blame-legend">${commits.map(c =>
    `<i style="border-color:${blameHue(c.oid, commits)}">${c.uncommitted ? 'working tree' : esc(c.oid.slice(0, 8))} · ${esc(c.author || '')}</i>`).join('')}</div>` : '';
  const cells = d.cells.map(c => {
    const t = c.touched || {};
    const made = c.commits.length;
    return `<details class="lee-blame-cell" data-cell="${c.index}">` +
      `<summary><b>${c.index}</b><span class="lee-blame-kind">${esc(c.kind)}</span>` +
      `<strong>${esc(t.author || 'never committed')}</strong>` +
      `<small>${t.timestamp ? gitRelative(t.timestamp) : ''}${made > 1 ? ` · ${made} commits` : ''}` +
      `${c.mapped ? '' : ' · lines not located'}</small>` +
      `<span class="lee-blame-bar">${c.commits.map(x =>
        `<i style="background:${blameHue(x.oid, commits)};flex:${x.lines}"></i>`).join('')}</span></summary>` +
      `<div class="lee-git-blame">${blameLineRows(c.lines, commits, true)}</div></details>`;
  }).join('');
  return legend + `<div class="lee-blame-cells">${cells}</div>`;
}
async function showGitBlame(root, path, range = null) {
  try {
    const params = range ? {path, start: range.start, end: range.end} : {path};
    const d = await api(gitUrl('/git/blame', params));
    const scope = d.notebook ? `${d.cells.length} cells`
                             : range ? `lines ${range.start}–${range.end}` : 'whole file';
    const commits = d.commits || [];
    const body = d.notebook ? blameCells(d)
      : `<div class="lee-git-blame">${blameLineRows((d.lines || []).map(x => ({...x, uncommitted: /^0+$/.test(x.oid)})), commits, false)}</div>`;
    const m = modal(`<div class="lee-mhead">${esc(path)}<span class="sub">who wrote this · ${esc(scope)}</span></div>` +
      `${d.error ? `<div class="lee-dialogcopy">${esc(d.error)}</div>` : ''}${body}` +
      `${range ? '<div class="lee-mfoot"><button class="lee-btn" id="blameall">blame the whole file</button></div>' : ''}`);
    m.querySelectorAll('[data-commit]').forEach(b => b.onclick = () => showGitCommit(b.dataset.commit));
    m.querySelector('#blameall')?.addEventListener('click', () => { m.remove(); showGitBlame(root, path, null); });
  } catch (e) { status(e.message || String(e), 'err'); }
}
function leeGit() { leeLeft('git'); }
function leeGitRefresh() { gitUI.snapshot = null; gitUI.history = []; renderGitPanel(); refreshProjectPills(); }
window.leeGit = leeGit; window.leeGitRefresh = leeGitRefresh;

async function leeNbdevPrepare() {
  status('nbdev prepare…', 'busy');
  try {
    const r = await post('/project/nbdev_prepare', {});
    status(`nbdev prepare · ${PathName(r.root)}${r.nbs_path ? ' · ' + r.nbs_path : ''}`, 'ok');
    refreshFileTree(undefined, false).catch(() => {});
  } catch (e) { status(String(e.message || e), 'err'); }
}
function PathName(path) { return String(path || '').split('/').pop() || path || ''; }
window.leeNbdevPrepare = leeNbdevPrepare;

