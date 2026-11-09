function leeModeBoot() {
  const sh = $('#shell'); if (!sh) return;
  lee.mode = sh.dataset.mode || 'code';
  try { lee.modeLayouts = JSON.parse(sh.dataset.layouts || '{}'); } catch (_) { lee.modeLayouts = {}; }
  if (lee.mode !== 'code' || sh.dataset.kept) leeModeLayout(lee.modeLayouts[lee.mode]);
}
leeModeBoot();
const leeModeDock = () => { const s = $('#shell'); return {files: !s.classList.contains('no-left'), exec: !s.classList.contains('no-bottom'), exec_handle: !s.hasAttribute('data-nohandle'), agent: !s.classList.contains('no-right'), main: {learn: 'learn', create: 'story'}[lee.mode] || 'editor'}; };
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
  if (l.agent && !narrow && lee.mode !== 'code') leeRight('agent');
}
/* The mode follows a tab only when a person moves to it: a click or a key in the last moment. A mode switch or a restore mounts tabs too, and must not undo itself. */
let personAt = 0;
for (const t of ['click', 'keydown']) document.addEventListener(t, e => { if (e.isTrusted) personAt = Date.now(); }, true);
const leeModeAgent = mode => { lee.agentMode = mode; lee.agentLearnMode = mode === 'learn'; paintAgentLearn?.(); refreshAgentThreads?.().catch(() => {}); };
async function leeModeSet(mode, follow = false) {
  if (!mode || mode === lee.mode) return true;
  const was = lee.mode, keep = leeModeDock();
  lee.modeBusy = true;
  try {
    await post('/workspace/layout', {mode: was, layout: keep}).catch(() => {});
    const r = await fetch('/workspace/mode', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({mode, thread: lee.agentThread || undefined})});
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      status(d.message || 'The mode could not change.', 'err');
      if (follow) { await htmx.ajax('GET', '/tab/bar', {target: '#tabbar', swap: 'outerHTML'}); await post('/workspace/mode', {mode: was}).catch(() => {}); await mountTab(); }
      leeModePaint(); return false;
    }
    lee.modeLayouts[was] = keep; lee.mode = mode;
    leeModePaint(); leeModeLayout(lee.modeLayouts[mode] = d.layout); leeModeAgent(d.mode || mode);
    if (!follow) {
      if (mode === 'learn') await leeLearnOpen(d.focus?.path || '/');
      else if (mode === 'create') await leeCreateOpen();
      else { await htmx.ajax('GET', '/tab/bar', {target: '#tabbar', swap: 'outerHTML'}); await mountTab(); }
    }
    return true;
  } finally { lee.modeBusy = false; }
}
document.addEventListener('htmx:responseError', e => { const x = e.detail.xhr; if (x.status === 409 && /\/tab\/select/.test(e.detail.pathInfo?.requestPath || '')) { try { status(JSON.parse(x.responseText).message || 'The mode could not change.', 'err'); } catch (_) {} } });
const leeModeFollow = kind => { if (!lee.modeBusy && kind && Date.now() - personAt < 2500) leeModeSet({learn: 'learn', story: 'create'}[kind] || 'code', true); };
let keepTimer;
function leeModeKeep() {
  clearTimeout(keepTimer);
  keepTimer = setTimeout(() => { const l = lee.modeLayouts[lee.mode] = leeModeDock(); post('/workspace/layout', {mode: lee.mode, layout: l}).catch(() => {}); }, 400);
}
Object.assign(window, {leeModeBoot, leeModeSet, leeModeLayout, leeModeFollow, leeModeKeep, leeModeDock});
