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
      `<span>${t.missing.map(esc).join(', ')}</span><code>set them in Workflows → Environment</code><button data-dep-env>environment</button></div>` : '');
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
    `<button data-dep-top="terminal">terminal</button><button data-dep-top="env">environment</button>` +
    `<button data-dep-top="reset" ${d.running ? 'disabled' : ''}>reset</button>` +
    `<button data-dep-top="edit">edit steps</button>` +
    `${t.script ? '<button data-dep-top="open">open deploy.py</button>' : ''}</div>` +
    `${d.failed ? `<div class="lee-wf-note"><strong>${esc(d.failed)} failed</strong><span>Its output is in the deploy terminal. The stages are idempotent — fix and continue.</span></div>` : ''}` +
    blameRow(d.blame) +
    `<div class="lee-rel-steps">${d.steps.map(s => relStepRow(s, d)).join('')}</div>`;
  host.querySelectorAll('[data-dep-view]').forEach(b => b.onclick = () => { depUI.view = b.dataset.depView; renderDeployPanel(); });
  host.querySelectorAll('[data-dep-top]').forEach(b => b.onclick = () => deployTop(b.dataset.depTop, d));
  host.querySelector('[data-dep-env]')?.addEventListener('click', openProjectEnv);
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
  if (op === 'env') return openProjectEnv();
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
    if (!await confirmRerun(d, 'deploy')) return;
    if (d.done) await deployOp('reset');
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

