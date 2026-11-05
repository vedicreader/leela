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
const updateLater = ['Not now', () => { $('#leeupdate').hidden = true; sessionStorage.setItem('lee-update-later', '1'); }];
async function leeUpdateNotice() {
  if (sessionStorage.getItem('lee-update-later')) return;
  const d = await api('/update');
  if (!d.notice) return;
  const notes = ['Release notes', () => openExternal(d.url)];
  updateBar(`Leela ${d.latest} is available. You have ${d.current}.`, d.install ? [['Update', () => leeUpdateRun(d)], notes, updateLater] : [notes, updateLater]);
}
async function leeUpdateRun(d) {
  let s = await post('/update/install', {});
  const notes = ['Release notes', () => openExternal(d.url)];
  while (s.state === 'running') {
    updateBar(`Updating Leela: ${s.line || '…'}`, []);
    await new Promise(r => setTimeout(r, 1000));
    s = await api('/update/status').catch(e => ({state: 'error', line: String(e.message || e)}));
  }
  if (s.state === 'done') return updateBar(`Leela ${d.latest} is installed. Restart now to use it.`,
    [['Restart Leela', () => post('/update/restart', {}).catch(e => status(String(e.message || e), 'err'))]]);
  if (s.state === 'same') return updateBar('Homebrew does not have the new version yet. Try again later, or get it from the release page.', [notes, updateLater]);
  if (s.state === 'unavailable') return updateBar('This Leela was not installed with Homebrew. Get the new version from the release page.', [notes, updateLater]);
  updateBar(`The update did not finish: ${s.line || s.state}`, [notes, updateLater]);
}
window.leeUpdateNotice = leeUpdateNotice;
