function leeDock(which) {
  const dock = $('#bottomdock'); if (!dock) return;
  try { localStorage.setItem('lee-dock-view', which); } catch (_) {}
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
  // A shell is one process in one directory and cannot follow the project by itself, so there is
  // one per checkout, the way there is one kernel per project. Switching to a file in another repo
  // reaches that repo's shell; the one you were using stays exactly where you left it.
  const here = t => kind !== 'shell' || (t.project || '') === (d.project || '');
  if (!forceNew) {
    const existing = [...lee.terms.entries()].find(([, t]) => t.kind === kind && here(t));
    if (existing) return switchTerm(existing[0]);
    // A session this page has never seen, still running from before a reload. Reattaching is the
    // point of letting a pty outlive its socket, and it has to be visible to be closable, or its
    // process is orphaned where nobody can stop it.
    const orphan = (d.open || []).filter(t => t.alive && t.id && !lee.terms.has(t.id))
      .find(t => (kind === 'git' ? t.id === 'git' : String(t.id).startsWith('term-')) && here(t));
    if (orphan) return adoptTerm(orphan.id, kind, d, orphan.project);
  }
  const id = nextTermId(kind, live);
  if (lee.terms.has(id)) return switchTerm(id);
  $('#shell').classList.add('show-term');
  const parent = $('#terms'); if (!parent) return status('no terminal pane', 'err');
  const host = document.createElement('div'); host.className = 'lee-term lee-term-session';
  host.dataset.term = id; parent.appendChild(host);
  const record = {id, kind, label: termLabel(kind, id, kind === 'shell' ? d.project : ''),
                  cwd: d.cwd, project: d.project || '', host, view: null};
  record.view = LeeTerm.create(host, {
    token: d.token, cwd: d.cwd, kind, id,
    onStatus: m => status(`${record.label}: ${m}`),
    onExit: () => { record.exited = true; paintTermTabs(); status(`${record.label} exited`); },
  });
  lee.terms.set(id, record); switchTerm(id);
}
// The pipeline's pty is opened by the pipeline, not by whoever attaches, so this terminal talks to
// `/release/ws` instead of `/term/ws`. Everything else is the same component the shell uses. `cwd`
// carries the project root, the only thing that socket needs to know which pipeline is watched.
async function openReleaseTerm(root = '', kind = 'release') {
  await loadTermBundle();
  const d = await api('/term/info');
  if (!d.enabled) return status(d.why, 'err');
  /* Keyed by the root as well as the kind. The server already keeps one pipeline per package,
     but a single `release` record held the socket opened with whichever package came first, so
     moving to another package re-showed that one and closing it was the only way through. */
  const at = String(root || '').replace(/\/+$/, '');
  const id = at ? `${kind}:${at}` : kind, prior = lee.terms.get(id);
  if (prior && !prior.exited) return switchTerm(id);
  if (prior) { prior.view.dispose(); prior.host.remove(); lee.terms.delete(id); }
  $('#shell').classList.add('show-term');
  const parent = $('#terms'); if (!parent) return status('no terminal pane', 'err');
  const host = document.createElement('div'); host.className = 'lee-term lee-term-session';
  host.dataset.term = id; parent.appendChild(host);
  const label = termLabel(kind, id, at);
  const record = {id, kind, label, cwd: at || d.cwd, host, view: null};
  record.view = LeeTerm.create(host, {
    token: d.token, cwd: at || d.cwd, kind, id,
    url: kind === 'drive' ? '/drive/ws' : '/pipeline/ws',
    onStatus: m => status(`${label}: ${m}`),
    onExit: () => { record.exited = true; paintTermTabs(); },
  });
  lee.terms.set(id, record); switchTerm(id);
}
/* A run's own terminal. The Logs pane answers what happened, this answers what it is doing, which
   for a dev server is colour, progress, a traceback as it arrives, and a keyboard so ctrl-c reaches
   the app. Same component as the shell, pointed at `/run/ws`, which hands back the pty the run is
   already on rather than starting anything. */
async function leeRunTerm(path, label = '', pid = null, quiet = false) {
  if (!path) return;
  await loadTermBundle();
  const d = await api('/term/info');
  if (!d.enabled) return status(d.why, 'err');
  const id = 'run:' + path, prior = lee.terms.get(id);
  // Same path, another process: the view was attached to the run that ended, so Stop then Run
  // kept showing the first run's output. A new pid gets a new view.
  if (prior && !prior.exited && (!pid || prior.pid === pid)) return quiet ? undefined : switchTerm(id);
  if (prior) { prior.view.dispose(); prior.host.remove(); lee.terms.delete(id); }
  const parent = $('#terms'); if (!parent) return status('no terminal pane', 'err');
  // `quiet` is a reload adopting a run that is still up: the tab appears, hidden, and nothing
  // else moves. `switchTerm` refits it when it is chosen.
  const host = document.createElement('div'); host.className = 'lee-term lee-term-session';
  host.dataset.term = id; host.hidden = quiet; parent.appendChild(host);
  const name = label || path.split('/').pop();
  const record = {id, kind: 'run', label: name, cwd: path, pid, host, view: null};
  record.view = LeeTerm.create(host, {
    token: d.token, cwd: path, kind: 'run', id, url: '/run/ws',
    onStatus: m => status(`${name}: ${m}`),
    onExit: () => { record.exited = true; paintTermTabs(); },
  });
  lee.terms.set(id, record);
  if (quiet) { paintTermTabs(); return; }
  $('#shell').classList.add('show-term');
  switchTerm(id);
}
window.leeRunTerm = leeRunTerm;

// Reconnect to a pty that is already running rather than starting one. Same component and the same
// id, so the server hands back the session it still has, which makes the process inside it visible
// in a tab and therefore closable.
function adoptTerm(id, kind, d, project = '') {
  $('#shell').classList.add('show-term');
  const parent = $('#terms'); if (!parent) return status('no terminal pane', 'err');
  const host = document.createElement('div'); host.className = 'lee-term lee-term-session';
  host.dataset.term = id; parent.appendChild(host);
  const record = {id, kind, label: termLabel(kind, id, kind === 'shell' ? project : ''),
                  cwd: d.cwd, project: project || '', host, view: null};
  record.view = LeeTerm.create(host, {
    token: d.token, cwd: d.cwd, kind, id,
    onStatus: m => status(`${record.label}: ${m}`),
    onExit: () => { record.exited = true; paintTermTabs(); status(`${record.label} exited`); },
  });
  lee.terms.set(id, record); switchTerm(id);
  status(`${record.label} was still running. Leela connected to it again`);
}

// xterm.js cannot attach to a terminal application that is already running, because that program
// is itself an emulator with its own pty. What it can do is hand the project over. The button stays
// hidden unless the server found a terminal to hand it to.
async function leeExternalTerm() {
  try {
    const d = await post('/term/external');
    status(`opened ${(d.argv || []).includes('-a') ? d.argv[d.argv.indexOf('-a') + 1] : (d.argv || [])[0] || 'terminal'}`, 'ok');
  } catch (e) { status(e.message || String(e), 'err'); }
}
window.leeExternalTerm = leeExternalTerm;

function leeNewTerm() { return openTerm('shell', true); }
window.leeNewTerm = leeNewTerm;

// The IDE follows the system's light and dark setting through a media query. The terminal reads its
// colours from CSS once, when it is created, so it has to be told.
try {
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    for (const t of lee.terms.values()) t.view.retheme();
  });
} catch (e) {}

function leeTermExpand() {
  leeDock('term'); leeExpandPane('bottom');
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
    leeExpand(''); setScope('editor');
  }
  // A shell or lazygit may have changed the working tree under us.
  refreshFileTree(undefined, false).catch(e => status(String(e.message || e), 'err'));
}

