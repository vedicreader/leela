/* Opening a project when there is no command line to type one on.
 *
 * A packaged Leela is double-clicked. The ways in are the folders it had open last time, which the
 * server restores before the page loads, the recent list, and the picker. In the native shell the
 * picker is the platform's own, because a file input hands over contents, never a location.
 */

// `window.pywebview.api` is `leela.desktop.ShellApi`, injected by the native window.
const inShell = () => Boolean(window.pywebview?.api?.pick_folder);
const shortHome = p => lee.home && p.startsWith(lee.home) ? '~' + p.slice(lee.home.length) : p;

// pywebview injects its bridge asynchronously, so "is there a native chooser" cannot be answered
// by one synchronous look at load. The wait happens once: a browser tab never gets the bridge.
let shellSettled = null;
async function shellReady(waitMs = 1500) {
  if (inShell()) return (lee.inShell = true);
  return shellSettled ||= (async () => {
    for (const end = Date.now() + waitMs; !inShell() && Date.now() < end;)
      await new Promise(r => setTimeout(r, 50));
    return (lee.inShell = inShell());
  })();
}
window.leeShellReady = shellReady;
lee.inShell = inShell();
shellReady().catch(() => {});   // so `inDesktopShell` has an answer before anything asks

// The platform folder chooser, or null if there is none or it was cancelled.
async function nativeFolder() {
  if (!await shellReady()) return null;
  try { return await window.pywebview.api.pick_folder(); }
  catch (e) { return status(`folder chooser: ${e.message || e}`, 'err'), null; }
}

// A recent folder can have been renamed or deleted. htmx does not swap a 4xx and `htmx.ajax`
// resolves anyway, so the refusal has to be read off the event.
async function openFolder(path) {
  if (!path) return;
  const name = path.split('/').pop();
  status(`opening ${name}…`);
  let why = '';
  const note = e => { why = e.detail.xhr?.responseText || e.detail.error || 'no answer'; };
  document.body.addEventListener('htmx:responseError', note);
  document.body.addEventListener('htmx:sendError', note);
  try {
    await htmx.ajax('POST', '/fs/add_root?path=' + encodeURIComponent(path),
                    {target: 'body', swap: 'outerHTML'});
  } finally {
    document.body.removeEventListener('htmx:responseError', note);
    document.body.removeEventListener('htmx:sendError', note);
  }
  if (!why) return;
  // A No in the server's question is the person's answer, not a failure.
  if (jsonBody(why).declined) return status(jsonError(why));
  leeFail('project', `opening ${name}`, new Error(jsonError(why)));
}
// A refused route answers `{"ok": false, "error": …}`; anything else is shown as it came.
function jsonBody(text) { try { return JSON.parse(text) || {}; } catch (_) { return {}; } }
function jsonError(text) { return jsonBody(text).error || text; }
window.leeOpenFolder = openFolder;

/* A folder is a workspace, and a workspace is a window: `add_root` puts a second folder in the
 * window you are already in, and this gives it one of its own. The native shell builds the window,
 * because only the process running the GUI can; a browser gets a tab, being what it has. */
async function openFolderWindow(path) {
  path = path || await nativeFolder();
  if (!path) return;
  const name = path.split('/').pop();
  status(`opening ${name}…`);
  if (await shellReady()) {
    try { await window.pywebview.api.open_folder(path); }
    catch (e) { leeFail('project', `opening ${name}`, e); }
    return;
  }
  return hubOpen(path);
}
window.leeOpenFolderWindow = openFolderWindow;

// `/hub/open` sends a file where a Finder open sends it, and a folder to a window of its own.
async function hubOpen(path) {
  const name = path.split('/').pop();
  const r = await fetch('/hub/open?path=' + encodeURIComponent(path), {method: 'POST'});
  const d = await r.json().catch(() => ({ok: false, error: r.statusText}));
  if (!d.ok) return d.declined ? status(d.error) : leeFail('project', `opening ${name}`, new Error(d.error));
  if (new URL(d.url).host === location.host) { await refreshTabStrip(); return mountTab().catch(() => {}); }
  // In the app window a scripted `window.open` opens nothing and returns null; `openExternal`
  // knows that and asks the server to open a real browser instead.
  openExternal(d.url);
}

/* Open… as a Mac app has it: one chooser takes a file or a folder. An older native window
 * has the folder chooser only, and a browser tab has none, so it asks for the path. */
async function openAny() {
  if (!await shellReady()) {
    const path = await inputDialog('open', 'path of a file or a folder', '', '~/code/notes.md');
    return path && hubOpen(path);
  }
  const shell = window.pywebview.api;
  if (!shell.pick_path) return openFolderWindow();
  let path;
  try { path = await shell.pick_path(); } catch (e) { return status(`file chooser: ${e.message || e}`, 'err'); }
  if (!path) return;
  status(`opening ${path.split('/').pop()}…`);
  try { if (!await shell.open_path(path)) status(`Leela cannot open ${path} from here`, 'err'); }
  catch (e) { leeFail('project', `opening ${path.split('/').pop()}`, e); }
}

/* A file no open folder holds lands in the loose window. Its folder is offered once, and opened only on Open. */
function folderOffer(st) {
  let el = $('#leeoffer');
  if (!st?.offer || !st.path) { if (el) el.hidden = true; return; }
  if (!el) {
    el = document.createElement('div'); el.id = 'leeoffer'; el.className = 'lee-offer'; el.setAttribute('role', 'status');
    document.body.append(el);
  }
  const repo = st.offer, file = st.path, name = repo.split('/').pop();
  el.title = repo; el.hidden = false;
  el.innerHTML = `<span>This file is in ${esc(name)}. Open ${esc(name)} as a folder?</span>` +
    `<button class="lee-btn go" data-offer="open">Open</button><button class="lee-btn" data-offer="later">Not now</button>`;
  el.querySelector('[data-offer="open"]').onclick = async () => {
    el.hidden = true;
    const q = new URLSearchParams({path: repo, file, folder: '1'}); for (const a of st.also || []) q.append('also', a);
    const r = await fetch('/hub/open?' + q, {method: 'POST'});
    const d = await r.json().catch(() => ({ok: false, error: r.statusText}));
    if (!d.ok) return d.declined ? status(d.error) : leeFail('project', `opening ${name}`, new Error(d.error));
    await refreshTabStrip(); mountTab().catch(() => {});
    if (!await shellReady()) return openExternal(d.url);
    try { await window.pywebview.api.open_folder(repo); } catch (e) { leeFail('project', `opening ${name}`, e); }
  };
  el.querySelector('[data-offer="later"]').onclick = () => {
    el.hidden = true;
    post('/tab/offer/dismiss?path=' + encodeURIComponent(file), {}).catch(() => {});
  };
}
window.leeFolderOffer = folderOffer;

// The welcome screen's recent list: when Leela opens on nothing, this is the way back to work.
async function paintRecent() {
  const host = $('#leerecent'); if (!host) return;
  let d; try { d = await api('/fs/recent'); } catch (_) { return; }
  lee.home = d.home || '';
  const rows = (d.recent || []).filter(r => !r.open);
  host.hidden = !rows.length; if (!rows.length) return;
  host.innerHTML = `<h3>Recent projects</h3><ul class="lee-recentlist">` + rows.map(r =>
    `<li><button class="lee-recent" data-path="${esc(r.path)}">` +
    `<span class="lee-recent-name">${esc(r.name)}</span>` +
    `<span class="lee-recent-path lee-dim">${esc(shortHome(r.path))}</span></button>` +
    `<button class="lee-recent-x" data-forget="${esc(r.path)}" title="forget this project"` +
    ` aria-label="forget ${esc(r.name)}">×</button></li>`).join('') + `</ul>`;
  $$('.lee-recent', host).forEach(b => b.onclick = () => openFolder(b.dataset.path));
  $$('[data-forget]', host).forEach(b => b.onclick = async () => {
    await post('/fs/forget-recent', {path: b.dataset.forget});
    paintRecent();
  });
}
window.leePaintRecent = paintRecent;

// First-run "Learn something": switch the workspace to Learn mode, show its tab, then focus the Start box.
async function firstLearn() {
  try { await post('/workspace/mode', {mode: 'learn'}); }
  catch (e) { return status(e.message || 'Learn did not open', 'err'); }
  await refreshTabStrip(); await mountTab().catch(() => {});
  for (let i = 0; i < 100; i++) {
    const q = $('#start-q'); if (q) return q.focus();
    await new Promise(ok => setTimeout(ok, 100));
  }
}
window.leeFirstLearn = firstLearn;
