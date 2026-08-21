/* ------------------------------------------------------------------ logs

   The detail a status line cannot hold. Git's refusals are the motivating case: the useful
   part of "cannot switch branch" is the list of files it would overwrite, and a toast shows
   one clipped sentence of it. Runs are the other: `/dev/log` has always kept what a dev
   server prints, and nothing in the browser read it.

   Kept in memory for this session on purpose. This answers "what just happened", and a store
   that outlives the question would need retention rules to go with it. */
const LOG_MAX = 500;
lee.logs = [];

function leeLog(source, title, detail = '', kind = '') {
  lee.logs.push({at: new Date(), source, title: String(title || ''), detail: String(detail || ''), kind});
  if (lee.logs.length > LOG_MAX) lee.logs.splice(0, lee.logs.length - LOG_MAX);
  const dock = $('#bottomdock');
  if (dock?.classList.contains('dock-logs')) renderLogs();
  else if (kind === 'err') $$('.lee-docktab').forEach(b => {
    if (b.dataset.dock === 'logs') b.classList.add('has-error');   // a failure you have not read
  });
}
window.leeLog = leeLog;

function renderLogs() {
  const el = $('#loglist'); if (!el) return;
  const want = lee.logFilter || '';
  if (want === 'history') {
    const rows = lee.gitHistory || [];
    el.innerHTML = rows.length ? rows.map(c =>
      `<article class="lee-logrow"><div class="lee-loghead"><time>${new Date(c.timestamp * 1000).toLocaleString()}</time>` +
      `<span class="lee-logsource">git</span><strong>${esc(c.short)} ${esc(c.subject)}</strong></div>` +
      `<pre class="lee-logdetail">${esc(c.author)}${c.decoration ? '\n' + c.decoration : ''}</pre></article>`).join('')
      : `<div class="lee-dim lee-logempty">no Git history for this repository</div>`;
  } else {
    const rows = lee.logs.filter(r => !want || r.source === want);
    el.innerHTML = rows.length ? rows.map(r =>
      `<article class="lee-logrow${r.kind ? ' ' + r.kind : ''}">` +
      `<div class="lee-loghead"><time>${r.at.toTimeString().slice(0, 8)}</time>` +
      `<span class="lee-logsource">${esc(r.source)}</span><strong>${esc(r.title)}</strong></div>` +
      (r.detail ? `<pre class="lee-logdetail">${esc(r.detail)}</pre>` : '') + `</article>`).join('')
      : `<div class="lee-dim lee-logempty">nothing logged${want ? ' for ' + esc(want) : ''} yet</div>`;
  }
  el.scrollTop = el.scrollHeight;
}

/* "See logs" has to end with you seeing the log.

   The reason a failure writes a detail line at all is that the toast cannot hold it -- so
   sending the reader off to find it, through a dock that is showing something else and a
   filter they set an hour ago for something unrelated, loses the very thing that was worth
   keeping. A failure now opens the log it just wrote, on a filter that can show it. */
function showLog(source = '') {
  if (lee.logFilter && lee.logFilter !== source) leeLogFilter('');
  leeDock('logs');
}
// The first line of git's refusal is usually the whole story ("would be overwritten by
// checkout"), and the files it names are the part that needs the pane.
function firstLine(text, max = 96) {
  const line = String(text || '').replace(/^\w*Error:\s*/, '').split('\n').find(x => x.trim()) || '';
  return line.length > max ? line.slice(0, max - 1) + '…' : line;
}

/* Said only in the status line, the detail is gone: the toast clips to a sentence and times out.
   The whole message goes to the log, which opens on a filter that can show it. The error carries
   that it has been reported, so an outer catch around `gitDo` may call this and not say it twice. */
function leeFail(source, what, e) {
  if (e && e.reported) return;
  if (e) e.reported = true;
  const detail = (e && e.message) || String(e || '');
  leeLog(source, `${what} failed`, detail, 'err');
  showLog(source);
  status(`${source} ${what} failed — ${firstLine(detail)}`, 'err');
}
window.leeFail = leeFail;

async function leeLogFilter(which) {
  lee.logFilter = which || '';
  $$('.lee-logfilter').forEach(b => b.classList.toggle('active', (b.dataset.logFilter || '') === lee.logFilter));
  if (lee.logFilter === 'history') {
    try { lee.gitHistory = (await api('/git/history?limit=100&repo=' + encodeURIComponent(gitUI.repo || ''))).commits || []; }
    catch (e) { lee.gitHistory = []; return leeFail('git', 'history', e); }
  }
  renderLogs();
}
function leeLogClear() { lee.logs = []; renderLogs(); }
async function leeLogCopy() {
  const want = lee.logFilter || '';
  const text = lee.logs.filter(r => !want || r.source === want)
    .map(r => `${r.at.toTimeString().slice(0, 8)} ${r.source} ${r.title}` + (r.detail ? '\n' + r.detail : '')).join('\n');
  try { await navigator.clipboard.writeText(text); status('log copied', 'ok'); }
  catch (e) { status('could not copy the log', 'err'); }
}
window.leeLogFilter = leeLogFilter; window.leeLogClear = leeLogClear; window.leeLogCopy = leeLogCopy;

/* Managed runs keep their output after exit. Polling creates the activity record whether or not
   Logs is visible; a failed run is a notification that opens the useful filter automatically. */
lee.runSeen = new Map(); lee.runFinished = new Set();
lee.runs = [];

/* What is running, next to the kernel it is not. A dev server has no window of its own -- it is a
   process leela started and can end, and until this there was nowhere that said so: the only
   evidence a run existed was output arriving, which is exactly what a broken one does not do. */
function paintRunsPill() {
  const pill = $('#runspill'); if (!pill) return;
  const runs = lee.runs || [];
  const live = runs.filter(s => s.running !== false);
  const dead = runs.filter(s => s.running === false && s.code);
  pill.className = 'lee-pill ' + (dead.length ? 'lee-pill-err' : live.length ? 'lee-pill-on' : 'lee-pill-off');
  pill.textContent = live.length === 1 ? '▶ ' + (live[0].label || 'run')
    : live.length ? `▶ ${live.length} runs`
    : dead.length ? `⚠ ${dead.length} stopped` : '○ runs';
  pill.title = runs.length ? runs.map(s => `${s.label}: ${runState(s)}`).join('\n')
                           : 'nothing running — click to start a script';
}
function runState(s) {
  if (s.running === false) return s.code ? `exited ${s.code}` : 'finished';
  return 'running' + (s.app_url ? ' · ' + s.app_url : s.pid ? ' · pid ' + s.pid : '');
}
async function leeRunsMenu(anchor) {
  await pollRunLogs();
  const runs = lee.runs || [];
  const rows = runs.map(s => ({
    label: (s.running === false ? '⚠ ' : '▶ ') + (s.label || s.path),
    detail: runState(s), run: () => leeRunTerm(s.script || s.path, s.label),
  }));
  if (rows.length) rows.push({separator: true});
  for (const s of runs.filter(s => s.running !== false)) rows.push({
    label: 'stop ' + (s.label || s.path), warn: true,
    run: async () => {
      try { await api('/dev/stop?path=' + encodeURIComponent(s.script || s.path)); }
      catch (e) { return status(String(e.message || e), 'err'); }
      status(`${s.label} stopped`, 'ok'); pollRunLogs();
    },
  });
  rows.push({label: rows.length ? 'run another script…' : 'run a script…', run: () => runApp()});
  openChromeMenu(anchor, rows);
}
window.leeRunsMenu = leeRunsMenu;

async function pollRunLogs() {
  let servers = [];
  try { servers = (await api('/dev/list')).servers || []; } catch (_) { lee.runs = []; paintRunsPill(); return false; }
  lee.runs = servers.map(s => ({...s, path: s.path || s.script || ''}));
  paintRunsPill();
  for (const srv of servers) {
    const path = srv.path || srv.script || '';
    if (!path) continue;
    let lines = [];
    try { lines = (await api('/dev/log?n=200&path=' + encodeURIComponent(path))).log || []; }
    catch (_) { continue; }
    const seen = lee.runSeen.get(path) || 0;
    if (lines.length < seen) { lee.runSeen.set(path, 0); lee.runFinished.delete(path); }
    const fresh = lines.slice(lee.runSeen.get(path) || 0);
    lee.runSeen.set(path, lines.length);
    if (fresh.length) leeLog('runs', srv.label || path.split('/').pop(), fresh.join('\n'));
    // `running`, not `alive`: the child keeps the inspector up after the command returns, so a run
    // that died on its first line reported itself healthy for as long as leela stayed open.
    const code = srv.code !== undefined && srv.code !== null ? srv.code : srv.returncode;
    if (!srv.running && code !== null && code !== undefined && !lee.runFinished.has(path)) {
      lee.runFinished.add(path);
      const failed = code !== 0;
      leeLog('runs', `${srv.label || path.split('/').pop()} ${failed ? 'failed' : 'finished'} · exit ${code}`, '', failed ? 'err' : 'ok');
      if (failed) { leeLogFilter('runs'); leeDock('logs'); status(`${srv.label || path.split('/').pop()} failed — exit ${code}`, 'err'); }
    }
  }
  return servers.length;
}

// A dev server's output has to arrive promptly. An empty list has nothing to say for 15s.
async function runLogLoop() {
  const busy = await pollRunLogs();
  setTimeout(runLogLoop, busy ? 2000 : 15000);
}

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

