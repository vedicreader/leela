/* The detail a status line cannot hold. Git's refusal names the files it would overwrite, and a
   toast shows one clipped sentence of it. `/dev/log` keeps what a dev server prints.

   Kept in memory for this session, because a store that outlives the question would need
   retention rules. */
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

/* "See logs" has to end with you seeing the log. Sending the reader off to find it, through a dock
   showing something else and a filter they set an hour ago, loses the thing worth keeping. A
   failure opens the log it just wrote, on a filter that can show it. */
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

/* Said only in the status line, the detail is gone, because the toast clips to a sentence and times
   out. The whole message goes to the log. The error carries that it has been reported, so an outer
   catch around `gitDo` can call this without saying it twice. */
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
   Logs is visible, and a failed run opens the useful filter automatically. */
lee.runSeen = new Map(); lee.runFinished = new Set();
lee.runs = [];

/* What is running, next to the kernel it is not. A dev server is a process leela started and can
   end, and the only evidence one existed was output arriving, which is what a broken one does not
   do. */
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
    detail: runState(s), run: () => leeRunTerm(s.script || s.path, s.label, s.pid),
  }));
  // Where each running app is listening, as rows: a port is the thing you want back after a reload.
  const urls = runs.filter(s => s.running !== false).flatMap(s => (s.urls || []).map(url => ({url, s})));
  if (urls.length) rows.push({separator: true});
  for (const {url, s} of urls) rows.push({label: 'open ' + url, detail: s.label || s.path, run: () => window.open(url, '_blank')});
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

/* A reload closes the page, not the servers. The first poll after one puts each running server
   back on a terminal, so what is running is on screen rather than only in a pill's tooltip. */
function adoptRuns(servers) {
  if (lee.runsAdopted) return;
  lee.runsAdopted = true;
  for (const s of servers) {
    if (s.running === false || !s.pid || lee.terms.has('run:' + (s.script || s.path))) continue;
    leeRunTerm(s.script || s.path, s.label, s.pid).catch(() => {});
  }
}

async function pollRunLogs() {
  let servers = [];
  try { servers = (await api('/dev/list')).servers || []; } catch (_) { lee.runs = []; paintRunsPill(); return false; }
  lee.runs = servers.map(s => ({...s, path: s.path || s.script || ''}));
  paintRunsPill(); adoptRuns(servers);
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
    // `running`, not `alive`: the child keeps the inspector up after the command returns, so
    // liveness of the inspector says nothing about whether the command is still going.
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

