function initSplits() {
  const savedLeft = localStorage.getItem('lee-left-view');
  // Every panel is saved on switch, so every panel is restorable.
  leeLeft(['git', 'symbols', 'workflows', 'releases', 'deploys', 'drive'].includes(savedLeft) ? savedLeft : 'files');
  // Read before the views: `leeDock` opens the bottom pane to show its tab and persists that,
  // which would erase a pane the last session had minimised.
  const closed = ['left', 'right', 'bottom'].filter(p => localStorage.getItem('lee-pane-' + p) === 'hidden');
  const savedRight = localStorage.getItem('lee-right-view');
  if (['agent', 'vars', 'memory', 'learn'].includes(savedRight)) leeRight(savedRight);
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
      // `localStorage` is synchronous and disk-backed, and a drag fires this at pointer rate. The
      // width a person let go at is the only one worth keeping, so it is written once, at the end.
      const move = (ev) => {
        const w = side === 'left' ? ev.clientX : window.innerWidth - ev.clientX;
        const v = Math.max(140, Math.min(window.innerWidth - 300, w));
        document.documentElement.style.setProperty(`--lee-${side}-w`, v + 'px');
      };
      const up = () => {
        sp.classList.remove('drag'); sp.onpointermove = null; sp.onpointerup = null;
        const now = getComputedStyle(document.documentElement).getPropertyValue(`--lee-${side}-w`).trim();
        if (now) localStorage.setItem(`lee-${side}-w`, now);
      };
      sp.onpointermove = move; sp.onpointerup = up;
    };
  });
  const centreHeight = () => $('.lee-centre')?.clientHeight || window.innerHeight;
  // The dock can occupy most of the workspace. The editor keeps its own 140px floor.
  const limit = () => Math.min(900, Math.max(110, centreHeight() - 240));
  const dockSplit = $('.lee-dock-split');
  if (dockSplit) dockSplit.onpointerdown = (e) => {
    e.preventDefault(); dockSplit.classList.add('drag'); dockSplit.setPointerCapture(e.pointerId);
    const bottom = $('#bottomdock')?.getBoundingClientRect().bottom || window.innerHeight;
    const move = (ev) => {
      const v = Math.max(110, Math.min(limit(), bottom - ev.clientY));
      document.documentElement.style.setProperty('--lee-dock-h', v + 'px');
      requestAnimationFrame(() => lee.term?.refit());
    };
    dockSplit.onpointermove = move;
    dockSplit.onpointerup = () => {
      dockSplit.classList.remove('drag'); dockSplit.onpointermove = null;
      const now = getComputedStyle(document.documentElement).getPropertyValue('--lee-dock-h').trim();
      if (!now) return;
      localStorage.setItem('lee-dock-h', now);
      localStorage.setItem('lee-agent-h', now);   // the previous name for this preference
    };
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
  if (lee.observer) return;
  let d;
  try { d = await api('/runtime/info'); } catch (_) { return; }
  if ((!d.needs_create && !d.needs_support && !d.needs_inspector) || sessionStorage.getItem('lee-runtime-asked:' + d.root)) return;
  sessionStorage.setItem('lee-runtime-asked:' + d.root, '1');
  /* A folder with no environment at all gets one, without being asked, because with uv the fix is
     one command that a deleted directory undoes. Only for a missing environment: installing
     packages into an environment you built yourself is your decision, so `needs_support` below
     still asks. Without uv it also still asks, because a half-built venv is worse than none. */
  if (d.needs_create && d.uv) {
    status('no project environment — creating .venv with uv…');
    try {
      const r = await post('/runtime/create');
      status(`project runtime ready: ${r.python}`, 'ok'); refreshKernelPill();
      return;
    } catch (e) { status(`could not create .venv — ${String(e.message || e)}`, 'err'); }
    /* fall through to the dialog, which offers choosing an interpreter instead */
  }
  if (d.needs_support || d.needs_inspector) {
    /* Two separate lacks, one dialog: the runtime cannot run notebook code without the launchers,
       and the variables panel cannot read the namespace without what dhrishti imports. A folder
       missing both should be asked once. */
    const pkgs = (d.inspector_packages || []).map(p => `<code>${esc(p)}</code>`).join(' and ');
    const wants = [d.needs_support ? '<code>ipykernel</code> and <code>ipymini</code> to run notebook code' : '',
                   d.needs_inspector ? `${pkgs} to read live variables` : ''].filter(Boolean);
    const m = modal(`<div class="lee-mhead">enable project runtime<span class="sub">${esc(d.python)}</span></div>` +
      `<div class="lee-dialogcopy">Leela found this folder’s environment, but it needs ` +
      `${wants.join(', and ')}. ` +
      `Leela installs them into this project environment with uv; the IDE remains separate.</div>` +
      `<div class="lee-mfoot"><button class="lee-btn go" id="runtimeenable">install kernel support</button>` +
      `<button class="lee-btn" id="runtimelater">not now</button></div>`);
    m.querySelector('#runtimeenable').onclick = async () => {
      m.querySelector('#runtimeenable').disabled = true; status('installing project kernel support…');
      try {
        if (d.needs_support) await post('/runtime/support', {python: d.python});
        if (d.needs_inspector) await post('/runtime/inspector', {python: d.python});
        m.remove();
        status('project runtime ready', 'ok');
        refreshKernelPill(); if (window.leeVars) leeVars();
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

