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
const updateHide = () => { const el = $('#leeupdate'); if (el) el.hidden = true; };
/* Per version: a newer release that the hourly check finds shows the bar again. */
const updateLater = d => ['Not now', () => { updateHide(); sessionStorage.setItem('lee-update-later', d.latest || ''); }];
const updateNotes = d => ['Release notes', () => openExternal(d.url)];
const updateBusy = d => ['running', 'done'].includes(d.job?.state);
const updateRestart = text => updateBar(text, [['Restart Leela', () => post('/update/restart', {}).catch(e => status(String(e.message || e), 'err'))]]);
/* A run in progress or already installed comes first, so a reload or a second window picks it up. */
function updateOffer(d) {
  if (d.job?.state === 'running') return leeUpdateRun(d);
  if (d.job?.state === 'done') return updateRestart(`${d.job.line || 'The new Leela is installed.'} Restart now to use it.`);
  updateBar(`Leela ${d.latest} is available. You have ${d.current}.`,
    d.install ? [['Update', () => leeUpdateRun(d)], updateNotes(d), updateLater(d)] : [updateNotes(d), updateLater(d)]);
}
/* At start and then each hour (`boot.js`); a bar on screen or a run in progress is left alone. */
async function leeUpdateNotice() {
  if (updateRunning || $('#leeupdate')?.hidden === false) return;
  const d = await api('/update');
  if (updateBusy(d) || (d.notice && sessionStorage.getItem('lee-update-later') !== d.latest)) updateOffer(d);
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
  if (s.state === 'done') return updateRestart(`${s.line || `Leela ${d.latest} is installed.`} Restart now to use it.`);
  if (s.state === 'same') return updateBar(s.line || 'Homebrew does not list the new Leela yet. Try again in a few minutes.',
    [['Try again', () => leeUpdateRun(d)], updateNotes(d), updateLater(d)]);
  if (s.state === 'unavailable') return updateBar('This Leela was not installed with Homebrew. Get the new version from the release page.', [updateNotes(d), updateLater(d)]);
  updateBar(`The update did not finish: ${s.line || s.state}`, [['Try again', () => leeUpdateRun(d)], updateNotes(d), updateLater(d)]);
}
window.leeUpdateNotice = leeUpdateNotice;
window.leeUpdateCheck = leeUpdateCheck;
window.leeUpdateRun = leeUpdateRun;
