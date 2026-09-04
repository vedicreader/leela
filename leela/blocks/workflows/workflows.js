// Both panels are about a project rather than a file, so they ask which repository, as the
// source-control panel does. Empty means the one the active tab is in.
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
  if (!st.gheasy) return `<div class="lee-wf-note"><strong>Local only</strong><span>${esc(st.why)}</span><code>pip install gheasy</code></div>`;
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
// Where `refresh`'s answer about what GitHub has is shown. Secret values are not readable by
// GitHub's design, so remote presence is all there is to show for one.
function wfRemoteMark(remote, key) {
  if (!remote) return '';
  const hit = (remote.secrets || []).find(s => s.name === key) || (remote.variables || []).find(v => v.name === key);
  if (!hit) return '<span class="lee-wf-remote missing" title="not on GitHub">·</span>';
  const when = String(hit.updated_at || '').slice(0, 10);
  return `<span class="lee-wf-remote" title="on GitHub${when ? ', updated ' + when : ''}">gh</span>`;
}
function wfRemoteExtra(remote, entries) {
  if (!remote) return '';
  const declared = new Set((entries || []).map(e => e.key));
  const extra = [...(remote.secrets || []), ...(remote.variables || [])].map(x => x.name).filter(n => !declared.has(n));
  return extra.length ? `<div class="lee-wf-remote-extra">on GitHub but not declared here: ${extra.map(esc).join(', ')}</div>` : '';
}
function wfEnvRows(entries, remote) {
  if (!entries?.length) return '<div class="lee-git-empty-state"><strong>Nothing declared</strong><span>Add <code>env_schema</code> to .gheasy/config.json, or a release step that needs a key.</span></div>';
  return entries.map(e => `<article class="lee-wf-env${e.set ? ' is-set' : ''}" data-env="${esc(e.key)}">` +
    `<div><strong>${esc(e.key)}</strong><small>${e.target}${e.declared ? '' : ' · from a release step'}</small></div>` +
    `<span class="lee-wf-envval">${e.secret ? (e.set ? '••••••••' : 'not set') : esc(e.value || 'not set')}</span>` +
    wfRemoteMark(remote, e.key) +
    `<button data-env-set>${e.set ? 'change' : 'set'}</button>${e.set ? '<button data-env-unset aria-label="remove">×</button>' : ''}</article>`).join('')
    + wfRemoteExtra(remote, entries);
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
        `<div class="lee-wf-envs">${wfEnvRows(wfUI.env?.entries, wfUI.env?.remote)}</div>`
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
    // Authenticating is a conversation with a browser and a one-time code, so the button opens
    // the real `gh auth login`.
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
    // A push changes what GitHub has, so a listing already on screen is now wrong.
    if (op === 'push' && wfUI.env.remote) return loadWorkflowEnv(true);
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

