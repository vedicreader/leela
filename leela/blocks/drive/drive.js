// The alternative to the deploy script, kept as its own panel so the two can be compared: same
// runner, same terminal, same blame on a failure, six library calls instead of three subcommands.
// The snippet is on screen because a button you cannot read is not a diagnostic.
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
    `<button data-drv-top="values">environment</button></div>` +
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
  if (op === 'values') return openProjectEnv();
  if (op === 'stop') { if (await confirmDialog('stop', 'Stop the running call?', 'stop')) driveOp('stop'); return; }
  if (op === 'reset') { if (await confirmDialog('reset', 'Forget what ran? The calls are unchanged.', 'reset')) driveOp('reset'); return; }
  if (op === 'start') {
    const missing = [...new Set(d.steps.flatMap(s => s.missing))];
    if (missing.length && !await confirmDialog('run every call',
        `These are not set: ${missing.join(', ')}. Run anyway?`, 'run')) return;
    if (!await confirmRerun(d, 'run')) return;
    if (d.done) await driveOp('reset');
    return driveOp('start');
  }
}

