const REL_MARK = {passed: '✓', failed: '✗', running: '•', skipped: '⤼', pending: '·', needs_notes: '✎'};
// The server rewrote the path to the checkout in this workspace, so "open" arrives in the
// repository rather than in a copy under .venv that the next sync overwrites.
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
      // `setCursor` deliberately does not scroll, so the move is dispatched with the scroll asked
      // for.
      view.dispatch({selection: {anchor: at.from}, scrollIntoView: true});
      LeeCM.focus?.(view);
    }, 350);
  });
}
function openProjectEnv() {
  leeLeft('workflows'); wfUI.view = 'env'; wfUI.env = null; return leeWorkflows();
}
// A finished pipeline refuses to start again server-side, because its end publishes or ships.
async function confirmRerun(d, what) {
  return !d.done || confirmDialog(`run ${what} again`,
    `Every step already ran. Forget that and run the whole ${what} again from the top?`, 'run again');
}
function relStepRow(s, d) {
  const busy = d.running && s.status !== 'running';
  return `<article class="lee-rel-step state-${s.status}" data-step="${esc(s.id)}">` +
    `<b>${REL_MARK[s.status] || '·'}</b>` +
    `<div><strong>${esc(s.label)}</strong><code>${esc(s.cmd)}</code>` +
    `<small>${esc(s.doc || '')}${s.code !== null && s.code !== undefined ? ` · exit ${s.code}` : ''}</small>` +
    `${s.status === 'needs_notes' ? '<i class="warn">needs release notes</i>' : ''}` +
    `${s.missing.length ? `<i class="warn">needs ${s.missing.map(esc).join(', ')}</i>` : ''}</div>` +
    `<span class="lee-rel-actions">` +
    `${s.status === 'running' ? '<button data-rel="stop">stop</button>' :
      `<button data-rel="step" ${busy ? 'disabled' : ''} title="run only this step">run</button>` +
      `${s.status === 'failed' ? `<button data-rel="start" ${busy ? 'disabled' : ''} title="retry, then continue">retry</button><button data-rel="skip" title="mark done without running">skip</button>` : ''}` +
      `${s.status === 'needs_notes' ? `<button data-rel-notes title="write the release notes">notes</button><button data-rel="skip" title="mark done without running">skip</button>` : ''}`}` +
    `</span></article>`;
}
// A release step that has no notes does not run. The box asks for them, and Save runs the step.
function relNotesBox(d) {
  const n = d.notes;
  if (!n || relUI.noteHide === n.version) return '';
  return `<form class="lee-rel-notes"><label for="relnotes"><strong>Release notes for ${esc(n.version)}</strong>` +
    `<span>Write what changed in this version. The notes go in CHANGELOG.md and on the GitHub release.</span></label>` +
    `<textarea id="relnotes" rows="6" spellcheck="false" placeholder="- Fix the login error">${esc(relUI.draft || '')}</textarea>` +
    `${relUI.noteErr ? `<p class="lee-rel-err">${esc(relUI.noteErr)}</p>` : ''}` +
    `<div class="lee-rel-notes-foot"><button type="submit" ${relUI.noteBusy ? 'disabled' : ''}>Save and release</button>` +
    `<button type="button" data-notes-cancel>Cancel</button></div></form>`;
}
async function saveNotes() {
  const text = (relUI.draft || '').trim();
  if (!text) { relUI.noteErr = 'Write the release notes first.'; return renderReleasesPanel(); }
  relUI.noteBusy = true; relUI.noteErr = ''; renderReleasesPanel();
  try {
    relUI.data = await post('/releases/action', {op: 'notes', repo: projectRepo(), text});
    relUI.draft = ''; relUI.noteHide = '';
    await openReleaseTerm(relUI.data.root, 'release');
  } catch (e) { relUI.noteErr = e.message || String(e); }
  relUI.noteBusy = false;
  renderReleasesPanel();
}
function wireNotes(host, d) {
  const form = host.querySelector('.lee-rel-notes'), ta = form?.querySelector('textarea');
  if (form) {
    ta.oninput = () => { relUI.draft = ta.value; };
    form.querySelector('[data-notes-cancel]').onclick = () => { relUI.noteHide = d.notes.version; relUI.noteErr = ''; renderReleasesPanel(); };
    form.onsubmit = e => { e.preventDefault(); saveNotes(); };
    if (relUI.noteFocus !== d.notes.version) { relUI.noteFocus = d.notes.version; ta.focus(); }
  }
  host.querySelectorAll('[data-rel-notes]').forEach(b => b.onclick = () => { relUI.noteHide = ''; relUI.noteFocus = ''; renderReleasesPanel(); });
}
function renderReleasesPanel() {
  const host = $('#releasespanel'); if (!host) return;
  const d = relUI.data;
  if (!d) { host.innerHTML = '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading the pipeline</small></div>'; return; }
  const done = d.steps.filter(s => s.status === 'passed').length;
  host.innerHTML =
    `<header class="lee-sc-branch"><div><strong>${esc(d.root.split('/').pop())}</strong>` +
    `<span>${d.flow || (d.nbdev ? 'nbdev' : 'plain')} project${d.app ? ' + desktop app' : ''} · ${done}/${d.steps.length} done${d.configured ? ' · .leela/release.json' : ' · default pipeline'}</span></div></header>` +
    `<div class="lee-sc-actions">` +
    `${d.running ? '<button data-rel-top="stop" class="warn">stop</button>' : `<button data-rel-top="start">${d.failed || d.notes ? 'continue' : 'run release'}</button>`}` +
    `<button data-rel-top="terminal">terminal</button><button data-rel-top="env">environment</button><button data-rel-top="reset" ${d.running ? 'disabled' : ''}>reset</button>` +
    `<button data-rel-top="edit">edit steps</button>${d.configured ? '<button data-rel-top="defaults">defaults</button>' : ''}</div>` +
    `${d.failed ? `<div class="lee-wf-note"><strong>${esc(d.failed)} failed</strong><span>Its output is in the release terminal. Fix and retry, or skip it deliberately.</span></div>` : ''}` +
    blameRow(d.blame) + relNotesBox(d) +
    `<div class="lee-rel-steps">${d.steps.map(s => relStepRow(s, d)).join('')}</div>` +
    `${d.needs.length ? `<div class="lee-rel-needs"><strong>needs</strong>${d.needs.map(k => `<i>${esc(k)}</i>`).join('')}<button data-rel-top="env">environment…</button></div>` : ''}`;
  wireReleasesPanel(host, d);
  wireBlame(host);
  wireNotes(host, d);
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
  // Steps finish on their own and start the next one, so the panel keeps asking while something
  // is running.
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
  if (op === 'env') return openProjectEnv();
  if (op === 'defaults') return releaseOp('reset_plan');
  if (op === 'start') {
    const missing = d.steps.flatMap(s => s.missing);
    if (missing.length && !await confirmDialog('run release',
        `These steps are missing ${[...new Set(missing)].join(', ')}. Run anyway?`, 'run')) return;
    if (!await confirmRerun(d, 'release')) return;
    if (d.done) await releaseOp('reset');
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

// The non-nbdev half of the same front end: the fastship commands that are not release steps.
async function fastshipOp(op, extra = {}) {
  status(`fastship ${op}…`, 'busy');
  try {
    const r = await post('/project/fastship/action', {op, repo: projectRepo(), ...extra});
    status(`fastship ${op} · ${PathName(r.root)}`, 'ok');
    refreshFileTree(undefined, false).catch(() => {});
    if (relUI.data) leeReleases();
    return r;
  } catch (e) { status(String(e.message || e), 'err'); return null; }
}
async function leeFastship() {
  let d;
  try { d = await api('/project/fastship' + projectQuery()); }
  catch (e) { return status(String(e.message || e), 'err'); }
  const flow = `${d.flow || 'plain'} project`;
  const note = d.flow === 'nbdev'
    ? '<div class="lee-wf-note"><strong>This is an nbdev project</strong><span>nbdev prepare is its front end, and the release pipeline runs nbdev\'s commands. fastship still scaffolds a new package.</span></div>'
    : !d.installed ? `<div class="lee-wf-note"><strong>fastship is not installed here</strong><span>${esc(d.why)}</span><code>uv add --dev fastship</code></div>` : '';
  const rows = (d.ops || []).map(o => `<article class="lee-rel-step" data-fs="${esc(o.op)}">` +
    `<b>·</b><div><strong>${esc(o.op)}</strong><code>${esc(o.cmd)}</code><small>${esc(o.doc)}</small></div>` +
    `<span class="lee-rel-actions"><button data-fs-run ${d.flow === 'nbdev' || !d.installed ? 'disabled' : ''}>run</button></span></article>`).join('');
  const m = modal(`<div class="lee-mhead">fastship<span class="sub">${esc(PathName(d.root))} · ${esc(flow)}` +
    `${d.changelog ? ' · CHANGELOG.md' : ' · no CHANGELOG.md yet'}${d.app ? ' · packages a desktop app' : ''}</span></div>` +
    note + `<div class="lee-rel-steps">${rows}</div>` +
    `<div class="lee-mfoot"><button class="lee-btn" id="fsrelease">release pipeline…</button>` +
    `<button class="lee-btn go" id="fsnew">new package…</button></div>`);
  m.querySelectorAll('[data-fs]').forEach(row => row.querySelector('[data-fs-run]')?.addEventListener('click', async () => {
    m.remove();
    await fastshipOp(row.dataset.fs);
  }));
  m.querySelector('#fsrelease').onclick = () => { m.remove(); leeLeft('releases'); leeReleases(); };
  m.querySelector('#fsnew').onclick = async () => {
    const name = await inputDialog('new fastship package', 'package name', '', 'my-package');
    if (!name) return;
    m.remove();
    const r = await fastshipOp('new', {name});
    if (r) status(`fastship new · ${PathName(r.root)} · release.yml written`, 'ok');
  };
}
window.leeFastship = leeFastship;
