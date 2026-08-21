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

