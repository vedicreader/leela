function leeModeBoot() {
  const sh = $('#shell'); if (!sh) return;
  lee.mode = sh.dataset.mode || 'code';
  try { lee.modeLayouts = JSON.parse(sh.dataset.layouts || '{}'); } catch (_) { lee.modeLayouts = {}; }
  if (lee.mode !== 'code') leeModeLayout(lee.modeLayouts[lee.mode]);
}
leeModeBoot();
const leeModeDock = () => { const s = $('#shell'); return {files: !s.classList.contains('no-left'), exec: !s.classList.contains('no-bottom'), exec_handle: !s.hasAttribute('data-nohandle'), agent: !s.classList.contains('no-right'), main: lee.mode === 'learn' ? 'learn' : 'editor'}; };
function leeModePaint() {
  $('#shell')?.setAttribute('data-mode', lee.mode);
  for (const b of $$('#modeswitch [data-mode]')) { const on = b.dataset.mode === lee.mode; b.classList.toggle('active', on); b.setAttribute('aria-pressed', String(on)); }
}
function leeModeLayout(l) {
  const s = $('#shell'), narrow = matchMedia('(max-width: 1100px)').matches;
  if (!s || !l) return;
  leePane('left', !!l.files && !narrow, false); leePane('bottom', !!l.exec, false);
  if (!l.agent || !narrow) leePane('right', !!l.agent, false);
  s.toggleAttribute('data-nohandle', l.exec_handle === false);
  if (l.agent && !narrow && lee.mode === 'learn') leeRight('agent');
}
async function leeModeSet(mode, follow = false) {
  if (!mode || mode === lee.mode) return true;
  const was = lee.mode, keep = leeModeDock();
  lee.modeBusy = true;
  try {
    await post('/workspace/layout', {mode: was, layout: keep}).catch(() => {});
    const r = await fetch('/workspace/mode', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({mode, thread: lee.agentThread || undefined})});
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { status(d.message || 'The mode could not change.', 'err'); if (!follow) { leeModePaint(); return false; } }
    lee.modeLayouts[was] = keep; lee.mode = mode;
    leeModePaint(); leeModeLayout(r.ok ? (lee.modeLayouts[mode] = d.layout) : lee.modeLayouts[mode]);
    if (!follow && r.ok) {
      if (mode === 'learn') await leeLearnOpen(d.focus?.path || '/');
      else { await htmx.ajax('GET', '/tab/bar', {target: '#tabbar', swap: 'outerHTML'}); await mountTab(); }
    }
    return true;
  } finally { lee.modeBusy = false; }
}
const leeModeFollow = kind => { if (!lee.modeBusy && kind) leeModeSet(kind === 'learn' ? 'learn' : 'code', true); };
let keepTimer;
function leeModeKeep() {
  clearTimeout(keepTimer);
  keepTimer = setTimeout(() => { const l = lee.modeLayouts[lee.mode] = leeModeDock(); post('/workspace/layout', {mode: lee.mode, layout: l}).catch(() => {}); }, 400);
}
Object.assign(window, {leeModeBoot, leeModeSet, leeModeLayout, leeModeFollow, leeModeKeep, leeModeDock});
