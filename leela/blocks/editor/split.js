/* ------------------------------------------------------------------ splitters */
function initSplits() {
  const savedLeft = localStorage.getItem('lee-left-view');
  // Every panel is saved on switch, so every panel is restorable. Restoring only two of them
  // meant a reload silently moved you back to the file tree from the one you were working in.
  leeLeft(['git', 'symbols', 'workflows', 'releases', 'deploys', 'drive'].includes(savedLeft) ? savedLeft : 'files');
  // Read before the views: `leeDock` opens the bottom pane to show its tab and persists that,
  // which would erase a pane the last session had minimised.
  const closed = ['left', 'right', 'bottom'].filter(p => localStorage.getItem('lee-pane-' + p) === 'hidden');
  const savedRight = localStorage.getItem('lee-right-view');
  if (['agent', 'vars', 'memory'].includes(savedRight)) leeRight(savedRight);
  const savedDock = localStorage.getItem('lee-dock-view');
  if (['exec', 'term', 'logs'].includes(savedDock)) leeDock(savedDock);
  for (const pane of closed) leePane(pane, false);
  // The pin buttons are rendered pinned; a saved unpin has to reach them before the first click.
  for (const pane of ['left', 'right']) leeSyncPin(pane);
  if (matchMedia('(max-width: 1100px)').matches) {
    leePane('left', false); leePane('right', false);
  }
  $$('.lee-split').forEach(sp => {
    sp.onpointerdown = (e) => {
      e.preventDefault(); sp.classList.add('drag'); sp.setPointerCapture(e.pointerId);
      const side = sp.dataset.split;
      const move = (ev) => {
        const w = side === 'left' ? ev.clientX : window.innerWidth - ev.clientX;
        const v = Math.max(140, Math.min(window.innerWidth - 300, w));
        document.documentElement.style.setProperty(`--lee-${side}-w`, v + 'px');
        localStorage.setItem(`lee-${side}-w`, v + 'px');
      };
      const up = () => { sp.classList.remove('drag'); sp.onpointermove = null; sp.onpointerup = null; };
      sp.onpointermove = move; sp.onpointerup = up;
    };
  });
  const centreHeight = () => $('.lee-centre')?.clientHeight || window.innerHeight;
  // The dock may occupy most of the workspace; 360px made Agent and Terminal feel like
  // preview strips on large displays. The editor keeps its own 140px safety floor.
  const limit = () => Math.min(900, Math.max(110, centreHeight() - 240));
  const dockSplit = $('.lee-dock-split');
  if (dockSplit) dockSplit.onpointerdown = (e) => {
    e.preventDefault(); dockSplit.classList.add('drag'); dockSplit.setPointerCapture(e.pointerId);
    const bottom = $('#bottomdock')?.getBoundingClientRect().bottom || window.innerHeight;
    const move = (ev) => {
      const v = Math.max(110, Math.min(limit(), bottom - ev.clientY));
      document.documentElement.style.setProperty('--lee-dock-h', v + 'px');
      localStorage.setItem('lee-dock-h', v + 'px');
      localStorage.setItem('lee-agent-h', v + 'px'); // migrate the previous bottom-dock preference
      requestAnimationFrame(() => lee.term?.refit());
    };
    dockSplit.onpointermove = move;
    dockSplit.onpointerup = () => { dockSplit.classList.remove('drag'); dockSplit.onpointermove = null; };
  };
  ['left-w', 'right-w'].forEach(k => {
    const v = localStorage.getItem('lee-' + k);
    if (v) document.documentElement.style.setProperty('--lee-' + k, v);
  });
  // Legacy names remain readable so an upgrade preserves the user's lower-panel height.
  const legacyPanelFloors = [['exec-h', 80], ['agent-h', 110]];
  void legacyPanelFloors;
  for (const [k, floor] of [['dock-h', 110]]) {
    const raw = parseFloat(localStorage.getItem('lee-' + k) || localStorage.getItem('lee-agent-h'));
    if (!Number.isFinite(raw)) continue;
    const value = Math.max(floor, Math.min(limit(), raw));
    document.documentElement.style.setProperty('--lee-' + k, value + 'px');
    localStorage.setItem('lee-' + k, value + 'px');
  }
  // The retired boolean is read once and rewritten as the slot and mode it meant.
  if (localStorage.getItem('lee-agent-expanded') === '1' && !localStorage.getItem('lee-expand'))
    localStorage.setItem('lee-expand', 'right:wide');
  localStorage.removeItem('lee-agent-expanded');
  leeSyncExpand();
}

async function refreshKernelPill() {
  try {
    const d = await api('/kernel/info');
    const pill = $('#kpill'); if (!pill) return;
    pill.className = 'lee-pill ' + (d.api_error || d.boot_error ? 'lee-pill-warn' : d.alive ? 'lee-pill-on' : 'lee-pill-err');
    pill.textContent = (d.api_error ? '⚠ ' : d.alive ? '⏺ ' : '○ ') + (d.key || '').split('/').pop();
    pill.title = (d.base || 'no inspector') + (d.cwd ? ' · cwd ' + d.cwd : '') +
                 (d.boot_error ? ' · ' + d.boot_error : '') + (d.api_error ? ' · inspector: ' + d.api_error : '');
    if (d.evicted) status(`closed ${d.evicted.name} runtime to make room; its in-memory variables were cleared`);
    (d.tabs || []).forEach((state, i) => {
      const tab = $(`.lee-tab[data-i="${i}"]`); if (!tab) return;
      let run = tab.querySelector('.lee-tab-run');
      if (state.running && !run) { run = document.createElement('span'); run.className = 'lee-tab-run'; tab.prepend(run); }
      if (run) { run.hidden = !state.running; run.title = `${state.running} cell(s) running`; }
      const wasDirty = tab.classList.contains('dirty');
      tab.classList.toggle('dirty', !!state.dirty);
      if (state.dirty && !wasDirty) setTabSaveState(tab, 'pending');
      else if (!state.dirty && wasDirty && tab.dataset.saveState !== 'error') setTabSaveState(tab, 'saved');
    });
  } catch (e) {}
}

async function checkProjectRuntime() {
  let d;
  try { d = await api('/runtime/info'); } catch (_) { return; }
  if ((!d.needs_create && !d.needs_support) || sessionStorage.getItem('lee-runtime-asked:' + d.root)) return;
  sessionStorage.setItem('lee-runtime-asked:' + d.root, '1');
  /* A folder with no environment at all gets one, without being asked. Opening a project and
     landing on whatever `python3` happens to be on PATH is never what anyone wanted, and with uv
     the fix is one command that a deleted directory undoes. Only for a *missing* environment:
     installing packages into an environment you built yourself is your decision, so needs_support
     below still asks. Without uv it also still asks, because a half-built venv is worse than
     none. */
  if (d.needs_create && d.uv) {
    status('no project environment — creating .venv with uv…');
    try {
      const r = await post('/runtime/create');
      status(`project runtime ready: ${r.python}`, 'ok'); refreshKernelPill();
      return;
    } catch (e) { status(`could not create .venv — ${String(e.message || e)}`, 'err'); }
    /* fall through to the dialog, which offers choosing an interpreter instead */
  }
  if (d.needs_support) {
    const m = modal(`<div class="lee-mhead">enable project runtime<span class="sub">${esc(d.python)}</span></div>` +
      `<div class="lee-dialogcopy">Leela found this folder’s environment, but it needs ` +
      `<code>ipykernel</code> and <code>ipymini</code> to run notebook code. ` +
      `Leela installs them into this project environment with uv; the IDE remains separate.</div>` +
      `<div class="lee-mfoot"><button class="lee-btn go" id="runtimeenable">install kernel support</button>` +
      `<button class="lee-btn" id="runtimelater">not now</button></div>`);
    m.querySelector('#runtimeenable').onclick = async () => {
      m.querySelector('#runtimeenable').disabled = true; status('installing project kernel support…');
      try {
        const r = await post('/runtime/support', {python: d.python}); m.remove();
        status(`project runtime ready · ipykernel + ipymini`, 'ok');
        refreshKernelPill();
      }
      catch (e) { status(String(e.message || e), 'err'); m.querySelector('#runtimeenable').disabled = false; }
    };
    m.querySelector('#runtimelater').onclick = () => m.remove();
    return;
  }
  const m = modal(`<div class="lee-mhead">project runtime<span class="sub">${esc(d.root)}</span></div>` +
    `<div class="lee-dialogcopy">This folder has no <code>.venv</code>, <code>venv</code>, ` +
    `<code>env</code>, or <code>.env</code>. Leela stays in its own environment; your code ` +
    `runs in a project environment.</div><div class="lee-mfoot">` +
    `<button class="lee-btn go" id="runtimecreate">create .venv</button>` +
    `<button class="lee-btn" id="runtimepick">choose interpreter</button>` +
    `<button class="lee-btn" id="runtimelater">not now</button></div>`);
  m.querySelector('#runtimecreate').onclick = async () => {
    m.querySelector('#runtimecreate').disabled = true; status('creating .venv and installing ipykernel…');
    try {
      const r = await post('/runtime/create'); m.remove();
      status(`project runtime ready: ${r.python}`, 'ok'); refreshKernelPill();
    } catch (e) { status(String(e.message || e), 'err'); m.querySelector('#runtimecreate').disabled = false; }
  };
  m.querySelector('#runtimepick').onclick = () => { m.remove(); pickKernel(); };
  m.querySelector('#runtimelater').onclick = () => m.remove();
}

