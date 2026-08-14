/* Opening a project when there is no command line to type one on.
 *
 * A packaged Leela is double-clicked. Nothing tells it which folder you meant, so the ways in
 * are: the folders it had open last time (the server restores those before the page loads),
 * the recent list on the welcome screen, and the picker. In the native shell the picker is the
 * platform's own folder chooser, because a web page cannot produce a directory path however
 * hard it tries -- a file input hands over contents, never a location.
 */

// True inside the desktop shell. `window.pywebview` is injected by the native window, and its
// `api` object is `leela.desktop.ShellApi`.
const inShell = () => Boolean(window.pywebview?.api?.pick_folder);

/* The platform folder chooser, or null when there is none or the user cancelled.
   pywebview injects `window.pywebview` asynchronously, so a click arriving in the first
   moments after load waits briefly rather than falling back to typing a path. */
async function nativeFolder(waitMs = 1500) {
  const deadline = Date.now() + waitMs;
  while (!inShell() && Date.now() < deadline) await new Promise(r => setTimeout(r, 50));
  if (!inShell()) return null;
  try { return await window.pywebview.api.pick_folder(); }
  catch (e) { status(`folder chooser: ${e.message || e}`, 'err'); return null; }
}

// Open a folder as a workspace root, from wherever it was chosen.
async function openFolder(path) {
  if (!path) return;
  status(`opening ${path.split('/').pop()}…`);
  await htmx.ajax('POST', '/fs/add_root?path=' + encodeURIComponent(path),
                  {target: 'body', swap: 'outerHTML'});
}
window.leeOpenFolder = openFolder;

/* The welcome screen's recent list. Only drawn when there is something to draw and no tab is
   open, so it never competes with the editor -- but when Leela opens on nothing, it is the
   first thing there is. */
async function paintRecent() {
  const host = $('#leerecent');
  if (!host) return;
  let d;
  try { d = await api('/fs/recent'); } catch (_) { return; }
  lee.home = d.home || '';
  const rows = (d.recent || []).filter(r => !r.open);
  if (!rows.length) { host.hidden = true; return; }
  host.hidden = false;
  host.innerHTML =
    `<h3>Recent projects</h3><ul class="lee-recentlist">` +
    rows.map(r =>
      `<li><button class="lee-recent" data-path="${esc(r.path)}">` +
      `<span class="lee-recent-name">${esc(r.name)}</span>` +
      `<span class="lee-recent-path lee-dim">${esc(shortHome(r.path))}</span></button>` +
      `<button class="lee-recent-x" data-forget="${esc(r.path)}" title="forget this project"` +
      ` aria-label="forget ${esc(r.name)}">×</button></li>`).join('') +
    `</ul>`;
  host.querySelectorAll('.lee-recent').forEach(b =>
    b.onclick = () => openFolder(b.dataset.path));
  host.querySelectorAll('[data-forget]').forEach(b => b.onclick = async () => {
    await post('/fs/forget-recent', {path: b.dataset.forget});
    paintRecent();
  });
}
window.leePaintRecent = paintRecent;

const shortHome = p => {
  const home = (lee.home || '');
  return home && p.startsWith(home) ? '~' + p.slice(home.length) : p;
};
