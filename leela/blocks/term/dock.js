function leeDock(which) {
  const dock = $('#bottomdock'); if (!dock) return;
  leePane('bottom', true);
  const centre = $('.lee-centre');
  dock.classList.toggle('dock-exec', which === 'exec');
  dock.classList.toggle('dock-term', which === 'term');
  dock.classList.toggle('dock-logs', which === 'logs');
  if (which === 'logs') {
    $$('.lee-docktab').forEach(b => { if (b.dataset.dock === 'logs') b.classList.remove('has-error'); });
    renderLogs();
  }
  $$('.lee-docktab', dock).forEach(b => {
    const active = b.dataset.dock === which; b.classList.toggle('active', active);
    b.setAttribute('aria-selected', String(active));
  });
  if (which === 'term') requestAnimationFrame(() => lee.term?.refit());
}
window.leeDock = leeDock;
function switchTerm(id) {
  const t = lee.terms.get(id); if (!t) return;
  leeDock('term'); lee.activeTerm = id; lee.term = t.view;
  $$('.lee-term-session').forEach(x => x.hidden = x.dataset.term !== id);
  paintTermTabs(); $('#shell').classList.add('show-term'); setScope('term');
  requestAnimationFrame(() => { t.view.refit(); t.view.focus(); });
}
function cycleTerm(d) {
  const ids = [...lee.terms.keys()]; if (!ids.length) return;
  const at = Math.max(0, ids.indexOf(lee.activeTerm));
  switchTerm(ids[(at + d + ids.length) % ids.length]);
}
async function openTerm(kind = 'shell', forceNew = false) {
  await loadTermBundle();
  const d = await api('/term/info');
  if (!d.enabled) return status(d.why, 'err');
  if (kind === 'git' && !d.lazygit) return status(d.lazygit_why, 'err');
  const external = $('#termexternal');
  if (external) external.hidden = !(d.external || []).length;
  const live = (d.open || []).filter(t => t.alive).map(t => t.id).filter(Boolean);
  if (!forceNew) {
    const existing = [...lee.terms.entries()].find(([, t]) => t.kind === kind);
    if (existing) return switchTerm(existing[0]);
    // A session this page has never seen, still running from before a reload. Reattaching is
    // the point of letting a pty outlive its socket -- and it has to be *visible* to be
    // closable, or its process is orphaned where nobody can see it to stop it.
    const orphan = live.find(id => !lee.terms.has(id) && (kind === 'git' ? id === 'git'
                                                                        : id.startsWith('term-')));
    if (orphan) return adoptTerm(orphan, kind, d);
  }
  const id = nextTermId(kind, live);
  if (lee.terms.has(id)) return switchTerm(id);
  $('#shell').classList.add('show-term');
  const parent = $('#terms'); if (!parent) return status('no terminal pane', 'err');
  const host = document.createElement('div'); host.className = 'lee-term lee-term-session';
  host.dataset.term = id; parent.appendChild(host);
  const record = {id, kind, label: termLabel(kind, id), cwd: d.cwd, host, view: null};
  record.view = LeeTerm.create(host, {
    token: d.token, cwd: d.cwd, kind, id,
    onStatus: m => status(`${record.label}: ${m}`),
    onExit: () => { record.exited = true; paintTermTabs(); status(`${record.label} exited`); },
  });
  lee.terms.set(id, record); switchTerm(id);
}
// The pipeline's pty is opened by the pipeline, not by whoever attaches, so this
// terminal talks to `/release/ws` instead of `/term/ws`. Everything else -- the theme, the
// keyboard, the dock tab -- is the same component the shell uses. `cwd` carries the project
// root, which is the only thing that socket needs to know which pipeline is being watched.
async function openReleaseTerm(root = '', kind = 'release') {
  await loadTermBundle();
  const d = await api('/term/info');
  if (!d.enabled) return status(d.why, 'err');
  const id = kind, prior = lee.terms.get(id);
  if (prior && !prior.exited) return switchTerm(id);
  if (prior) { prior.view.dispose(); prior.host.remove(); lee.terms.delete(id); }
  $('#shell').classList.add('show-term');
  const parent = $('#terms'); if (!parent) return status('no terminal pane', 'err');
  const host = document.createElement('div'); host.className = 'lee-term lee-term-session';
  host.dataset.term = id; parent.appendChild(host);
  const record = {id, kind, label: termLabel(kind, id), cwd: root || d.cwd, host, view: null};
  record.view = LeeTerm.create(host, {
    token: d.token, cwd: root || d.cwd, kind, id,
    url: kind === 'drive' ? '/drive/ws' : '/pipeline/ws',
    onStatus: m => status(`${termLabel(kind, id)}: ${m}`),
    onExit: () => { record.exited = true; paintTermTabs(); },
  });
  lee.terms.set(id, record); switchTerm(id);
}
/* A run's own terminal. The Logs pane answers "what happened"; this answers "what is it doing",
   which for a dev server is the whole of the job -- colour, progress, a traceback as it lands, and
   a keyboard, so ctrl-c reaches the app. Same component as the shell, pointed at `/run/ws`, which
   hands back the pty the run is already on rather than starting anything. */
async function leeRunTerm(path, label = '') {
  if (!path) return;
  await loadTermBundle();
  const d = await api('/term/info');
  if (!d.enabled) return status(d.why, 'err');
  const id = 'run:' + path, prior = lee.terms.get(id);
  if (prior && !prior.exited) return switchTerm(id);
  if (prior) { prior.view.dispose(); prior.host.remove(); lee.terms.delete(id); }
  $('#shell').classList.add('show-term');
  const parent = $('#terms'); if (!parent) return status('no terminal pane', 'err');
  const host = document.createElement('div'); host.className = 'lee-term lee-term-session';
  host.dataset.term = id; parent.appendChild(host);
  const name = label || path.split('/').pop();
  const record = {id, kind: 'run', label: name, cwd: path, host, view: null};
  record.view = LeeTerm.create(host, {
    token: d.token, cwd: path, kind: 'run', id, url: '/run/ws',
    onStatus: m => status(`${name}: ${m}`),
    onExit: () => { record.exited = true; paintTermTabs(); },
  });
  lee.terms.set(id, record); switchTerm(id);
}
window.leeRunTerm = leeRunTerm;

// Reconnect to a pty that is already running, rather than starting one. Same component and the
// same id, so the server hands back the session it still has -- which is what makes the process
// inside it visible in a tab, and therefore closable.
function adoptTerm(id, kind, d) {
  $('#shell').classList.add('show-term');
  const parent = $('#terms'); if (!parent) return status('no terminal pane', 'err');
  const host = document.createElement('div'); host.className = 'lee-term lee-term-session';
  host.dataset.term = id; parent.appendChild(host);
  const record = {id, kind, label: termLabel(kind, id), cwd: d.cwd, host, view: null};
  record.view = LeeTerm.create(host, {
    token: d.token, cwd: d.cwd, kind, id,
    onStatus: m => status(`${record.label}: ${m}`),
    onExit: () => { record.exited = true; paintTermTabs(); status(`${record.label} exited`); },
  });
  lee.terms.set(id, record); switchTerm(id);
  status(`${record.label} was still running — reattached`);
}

// xterm.js cannot be attached to a terminal application that is already running: that program is
// itself an emulator with its own pty, and a browser pane has no way to adopt its window. What it
// can do is hand the project over, which is what this is -- and the button stays hidden unless
// the server found a terminal to hand it to, so it is never one that fails when pressed.
async function leeExternalTerm() {
  try {
    const d = await post('/term/external');
    status(`opened ${(d.argv || []).includes('-a') ? d.argv[d.argv.indexOf('-a') + 1] : (d.argv || [])[0] || 'terminal'}`, 'ok');
  } catch (e) { status(e.message || String(e), 'err'); }
}
window.leeExternalTerm = leeExternalTerm;

function leeNewTerm() { return openTerm('shell', true); }
window.leeNewTerm = leeNewTerm;

// The IDE follows the system's light/dark setting through a media query; the terminal
// reads its colours from CSS once, when it is created, so it has to be told.
try {
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    for (const t of lee.terms.values()) t.view.retheme();
  });
} catch (e) {}

function leeTermExpand() {
  const centre = $('.lee-centre'); if (!centre) return;
  leeDock('term');
  centre.classList.toggle('term-expanded');
  const expanded = centre.classList.contains('term-expanded');
  $('#termexpand').textContent = expanded ? 'restore' : 'expand';
  requestAnimationFrame(() => { lee.term?.refit(); lee.term?.focus(); });
}
window.leeTermExpand = leeTermExpand;

function closeTerm(id = lee.activeTerm) {
  const t = lee.terms.get(id); if (!t) return;
  t.view.dispose(); t.host.remove(); lee.terms.delete(id); post('/term/close?id=' + encodeURIComponent(id));
  const next = [...lee.terms.keys()].at(-1);
  lee.term = null; lee.activeTerm = '';
  if (next) switchTerm(next);
  else {
    paintTermTabs(); $('#shell').classList.remove('show-term'); leeDock('exec');
    $('.lee-centre')?.classList.remove('term-expanded'); setScope('editor');
  }
  // A shell or lazygit may have changed the working tree under us.
  refreshFileTree(undefined, false).catch(e => status(String(e.message || e), 'err'));
}

