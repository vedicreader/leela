// `/exec` runs in whatever runtime the open tab runs in, so a Rust notebook makes this box Rust.
// The placeholder is built at mount and the bundle exposes no way to rewrite one, so a language
// change remounts rather than saying `python` over a box that runs something else.
function execLang() {
  const lang = lee.kind === 'notebook' ? nbLang() : 'python';
  if (lee.execLang === lang) return;
  lee.execLang = lang;
  const v = lee.editors.get('exec');
  if (!v) return;                     // not mounted yet; `mountExec` reads `lee.execLang` itself
  LeeCM.destroy(v);
  lee.editors.delete('exec');
  mountExec();
}

function mountExec() {
  const host = $('#execbox'); if (!host || lee.editors.has('exec')) return;
  const lang = lee.execLang || 'python';
  const v = createEditor(host, {
    doc: '', lang, placeholder: `${lang} · ${displayChord('mod+enter')} runs · ${displayChord('ctrl+shift+up')}/↓ history`,
    completeUrl: '/complete', onDefinition: name => findDefinition(name),
    onSelection: () => { clearTimeout(selectionHelpTimer); selectionHelpTimer = setTimeout(showSelectionHelp, 120); },
  });
  lee.editors.set('exec', v);
  leeScope(lee.execScope);
  if (host.dataset.wired) return;     // a remount replaces the editor, not the box around it
  host.dataset.wired = '1';
  host.addEventListener('focusin', () => setScope('exec'));
  // An empty box hands Tab back to the page, so a keyboard walk passes through it. With code in it, Tab indents and Escape then Tab leaves.
  host.addEventListener('keydown', e => {
    if (e.key === 'Tab' && !e.altKey && !e.ctrlKey && !e.metaKey && !LeeCM.getDoc(lee.editors.get('exec')).trim()) e.stopPropagation();
  }, true);
  api('/exec/history').then(d => { lee.hist = d.cells || []; lee.histIdx = lee.hist.length; }).catch(() => {});
}

function leeScope(s) {
  lee.execScope = s;
  const scopeButton = $('.lee-bar-exec .lee-btn:nth-child(2)');
  if (scopeButton) { scopeButton.textContent = 'live/agent'; scopeButton.title = 'switch owner and protected agent namespaces'; }
  $('#sc-live')?.classList.toggle('active', s === 'live');
  $('#sc-agent')?.classList.toggle('active', s === 'agent');
  const tag = $('#execscope');
  if (tag) tag.textContent = s === 'live'
    ? (lee.debugState?.paused ? '· evaluates in the paused debug frame' : '· runs in your kernel')
    : '· protected agent session';
  leeVars();
}
window.leeScope = leeScope;

async function runExec() {
  const v = lee.editors.get('exec'); if (!v) return;
  const code = LeeCM.getDoc(v).trim(); if (!code) return;
  if (lee.execBusy) return status('exec is already running', 'err');
  lee.execBusy = true; status('running exec…');
  const log = $('#execlog');
  try {
    const r = await withPython(() => post('/exec', {code, path: lee.tabKey || '', scope: lee.execScope, frame_id: lee.debugState?.frame_id}));
    const line = document.createElement('div');
    line.className = 'lee-runline' + (r.ok ? '' : ' err');
    line.innerHTML = `<span class="code">${esc(code)}</span><span class="arrow">→</span>` +
                     `<span class="res">${esc((r.text || 'ok').trim())}</span>`;
    log.appendChild(line); log.scrollTop = log.scrollHeight;
    if (r.result) requestAnimationFrame(() => openValueLens(r.result, line, code));
    lee.hist.push(code); lee.histIdx = lee.hist.length;
    LeeCM.setDoc(v, '');
    if (r.debug && lee.debugState) {
      try { lee.debugState = await api(`/nb/debug/state?frame_id=${lee.debugState.frame_id}`); }
      catch (_) {}
    }
    leeVars();
  } catch (e) { status(String(e.message || e), 'err'); }
  finally { lee.execBusy = false; }
}

function recall(d) {
  const v = lee.editors.get('exec'); if (!v || !lee.hist.length) return;
  lee.histIdx = Math.max(0, Math.min(lee.hist.length, lee.histIdx + d));
  LeeCM.setDoc(v, lee.histIdx >= lee.hist.length ? '' : lee.hist[lee.histIdx]);
  LeeCM.focus(v, true);
}
function leeExecClear() { const l = $('#execlog'); if (l) l.innerHTML = ''; }
window.leeExecClear = leeExecClear;

