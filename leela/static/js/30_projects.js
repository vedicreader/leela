/* Opening a project when there is no command line to type one on.
 *
 * A packaged Leela is double-clicked. The ways in are the folders it had open last time (the
 * server restores those before the page loads), the recent list, and the picker -- which in the
 * native shell is the platform's own, because a web page cannot produce a directory path: a
 * file input hands over contents, never a location.
 */

// `window.pywebview.api` is `leela.desktop.ShellApi`, injected by the native window.
const inShell = () => Boolean(window.pywebview?.api?.pick_folder);
const shortHome = p => lee.home && p.startsWith(lee.home) ? '~' + p.slice(lee.home.length) : p;

// The platform folder chooser, or null if there is none or it was cancelled. pywebview injects
// its bridge asynchronously, so a click in the first moments after load waits for it.
async function nativeFolder(waitMs = 1500) {
  for (const end = Date.now() + waitMs; !inShell() && Date.now() < end;)
    await new Promise(r => setTimeout(r, 50));
  if (!inShell()) return null;
  try { return await window.pywebview.api.pick_folder(); }
  catch (e) { return status(`folder chooser: ${e.message || e}`, 'err'), null; }
}

async function openFolder(path) {
  if (!path) return;
  status(`opening ${path.split('/').pop()}…`);
  await htmx.ajax('POST', '/fs/add_root?path=' + encodeURIComponent(path),
                  {target: 'body', swap: 'outerHTML'});
}
window.leeOpenFolder = openFolder;

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
