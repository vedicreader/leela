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
const updateHide = () => { const el = $('#leeupdate'); if (el) el.hidden = true; };
const updateLater = ['Not now', () => { updateHide(); sessionStorage.setItem('lee-update-later', updateKey(updateShown || {})); }];
const updateText = d => ({lock: `A new set of Leela packages is ready${d.changes ? ` (${d.changes})` : ''}. Kernels stop when Leela restarts to use it.`,
  'app-needed': `The newest Leela packages need Leela app ${d.latest}. Get it from the release page.`,
  download: `Leela ${d.latest} is available. You have ${d.current}. Get it from the release page.`})[d.kind] || `Leela ${d.latest} is available. You have ${d.current}.`;
const updateNotes = d => [d.kind === 'lock' ? 'Details' : 'Release notes', () => openExternal(d.url)];
const updateBusy = d => ['running', 'done'].includes(d.job?.state);
const updateRestart = (text, d = {}) => updateBar(text, [[d.kind === 'lock' ? 'Restart to update' : 'Restart Leela',
  () => post('/update/restart', {}).catch(e => status(String(e.message || e), 'err'))]]);
const updateInstalled = (d, line) => d.kind === 'lock' ? 'The new packages are installed. Restart to update; running kernels stop.' : `${line || `Leela ${d.latest} is installed.`} Restart now to use it.`;
function oldExtrasOffer(o) {
  if (!o || sessionStorage.getItem('lee-old-extras-later')) return;
  updateBar(`The old Leela app left ${o.mb} MB of packages in ${o.path}. This Leela does not use them.`,
    [['Remove them', async () => { const r = await post('/update/old-extras', {}).catch(() => ({})); updateHide(); if (!r.ok) status('Leela could not remove the old packages', 'err'); }],
     ['Not now', () => { updateHide(); sessionStorage.setItem('lee-old-extras-later', '1'); }]]);
}
/* A run in progress or already installed comes first, so a reload or a second window picks it up. */
function updateOffer(d) {
  updateShown = d;
  if (d.job?.state === 'running') return leeUpdateRun(d);
  if (d.job?.state === 'done') return updateRestart(updateInstalled(d, d.job.line), d);
  updateBar(updateText(d), d.install ? [['Update', () => leeUpdateRun(d)], updateNotes(d), updateLater] : [updateNotes(d), updateLater]);
}
async function leeUpdateNotice() {
  if ($('#leeupdate')?.hidden === false) return;
  const d = await api('/update');
  if (updateBusy(d)) return updateOffer(d);
  if (!d.notice || sessionStorage.getItem('lee-update-later') === updateKey(d)) return oldExtrasOffer(d.old_extras);
  updateOffer(d);
}
/* "Check for updates…": asks GitHub now, past the cache and past "Not now", and always answers. */
async function leeUpdateCheck() {
  if (updateRunning) return;
  updateBar('Checking for updates…', []);
  const d = await api('/update?fresh=1').catch(() => ({failed: true}));
  if (updateBusy(d) || d.outdated) return updateOffer(d);
  if (d.failed) return updateBar('Leela could not check for updates. Make sure that the network is on, then try again.',
    [['Try again', leeUpdateCheck], ['Close', updateHide]]);
  updateBar(`Leela is up to date (${d.current}).`, [['OK', updateHide]]);
}
/* One run per window: the bar, the dialog and a second click share it. */
let updateRunning = null;
function leeUpdateRun(d) { return updateRunning ||= updateRunOnce(d).finally(() => { updateRunning = null; }); }
async function updateRunOnce(d) {
  const err = e => ({state: 'error', line: String(e.message || e)});
  let s = d.job?.state === 'running' ? d.job : await post('/update/install', {}).catch(err);
  while (s.state === 'running') {
    updateBar(`Updating Leela: ${s.line || '…'}`, []);
    await new Promise(r => setTimeout(r, 1000));
    s = await api('/update/status').catch(err);
  }
  if (s.state === 'done') return updateRestart(updateInstalled(d, s.line), d);
  if (d.kind === 'lock') return updateBar(`The update did not install. Leela still runs the current version.${s.line ? ' ' + s.line : ''}`,
    [['Try again', () => leeUpdateRun(d)], updateNotes(d), updateLater]);
  if (s.state === 'same') return updateBar(s.line || 'Homebrew does not list the new Leela yet. Try again in a few minutes.',
    [['Try again', () => leeUpdateRun(d)], updateNotes(d), updateLater]);
  if (s.state === 'unavailable') return updateBar('This Leela was not installed with Homebrew. Get the new version from the release page.', [updateNotes(d), updateLater]);
  updateBar(`The update did not finish: ${s.line || s.state}`, [['Try again', () => leeUpdateRun(d)], updateNotes(d), updateLater]);
}
window.leeUpdateNotice = leeUpdateNotice;
window.leeUpdateCheck = leeUpdateCheck;
window.leeUpdateRun = leeUpdateRun;
