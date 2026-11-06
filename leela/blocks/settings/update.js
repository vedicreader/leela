/* The update notice. `/update` decides; it offers nothing outside the packaged Mac app. */
function updateBar(text, buttons) {
  let el = $('#leeupdate');
  if (!el) {
    el = document.createElement('div'); el.id = 'leeupdate'; el.className = 'lee-offer'; el.setAttribute('role', 'status');
    document.body.append(el);
  }
  el.hidden = false; el.title = text;
  el.innerHTML = `<span>${esc(text)}</span>` + buttons.map(([label], i) => `<button class="lee-btn${i ? '' : ' go'}" data-update="${i}">${esc(label)}</button>`).join('');
  buttons.forEach(([, fn], i) => { el.querySelector(`[data-update="${i}"]`).onclick = fn; });
  return el;
}
/* "Not now" holds for this offer only: a later version, or a new package set, asks again. */
const updateKey = d => `${d.kind || 'app'}:${d.latest}`;
let updateShown = null;
const updateLater = ['Not now', () => { $('#leeupdate').hidden = true; sessionStorage.setItem('lee-update-later', updateKey(updateShown || {})); }];
const updateText = d => ({lock: 'A new set of Leela packages is ready. Kernels stop when Leela restarts to use it.',
  'app-needed': `The newest Leela packages need Leela app ${d.latest}. Get it from the release page.`,
  download: `Leela ${d.latest} is available. You have ${d.current}. Get it from the release page.`})[d.kind] || `Leela ${d.latest} is available. You have ${d.current}.`;
function oldExtrasOffer(o) {
  if (!o || sessionStorage.getItem('lee-old-extras-later')) return;
  updateBar(`The old Leela app left ${o.mb} MB of packages in ${o.path}. This Leela does not use them.`,
    [['Remove them', async () => { const r = await post('/update/old-extras', {}).catch(() => ({})); $('#leeupdate').hidden = true; if (!r.ok) status('Leela could not remove the old packages', 'err'); }],
     ['Not now', () => { $('#leeupdate').hidden = true; sessionStorage.setItem('lee-old-extras-later', '1'); }]]);
}
async function leeUpdateNotice() {
  const d = await api('/update');
  if (!d.notice || sessionStorage.getItem('lee-update-later') === updateKey(d)) return oldExtrasOffer(d.old_extras);
  updateShown = d;
  const notes = [d.kind === 'lock' ? 'Details' : 'Release notes', () => openExternal(d.url)];
  updateBar(updateText(d), d.install ? [['Update', () => leeUpdateRun(d)], notes, updateLater] : [notes, updateLater]);
}
async function leeUpdateRun(d) {
  let s = await post('/update/install', {});
  const notes = ['Release notes', () => openExternal(d.url)];
  while (s.state === 'running') {
    updateBar(`Updating Leela: ${s.line || '…'}`, []);
    await new Promise(r => setTimeout(r, 1000));
    s = await api('/update/status').catch(e => ({state: 'error', line: String(e.message || e)}));
  }
  if (s.state === 'done') return updateBar(d.kind === 'lock' ? 'The new packages are installed. Restart to update; running kernels stop.' : `Leela ${d.latest} is installed. Restart now to use it.`,
    [[d.kind === 'lock' ? 'Restart to update' : 'Restart Leela', () => post('/update/restart', {}).catch(e => status(String(e.message || e), 'err'))]]);
  if (d.kind === 'lock') return updateBar(`The update did not install. Leela still runs the current version.${s.line ? ' ' + s.line : ''}`, [notes, updateLater]);
  if (s.state === 'same') return updateBar('Homebrew does not have the new version yet. Try again later, or get it from the release page.', [notes, updateLater]);
  if (s.state === 'unavailable') return updateBar('This Leela was not installed with Homebrew. Get the new version from the release page.', [notes, updateLater]);
  updateBar(`The update did not finish: ${s.line || s.state}`, [notes, updateLater]);
}
window.leeUpdateNotice = leeUpdateNotice;
