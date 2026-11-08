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
  initEditorSplitter();
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

const SPLIT_SIZE = 'lee-editor-split-size';   //: the first pane's share in percent; its own key, as each side page rewrites `lee-editor-split`
//: The share of the first pane of the editor split, clamped to 20-80; `keep` saves it for the next split and the next session.
function setSplitSize(v, keep = false) {
  const stage = $('#editorstage'), bar = $('.lee-editor-splitter'); if (!stage || !bar) return;
  v = Math.round(Math.max(20, Math.min(80, Number(v) || 50)));
  stage.style.setProperty('--lee-split', v + '%'); bar.setAttribute('aria-valuenow', v);
  bar.setAttribute('aria-orientation', stage.classList.contains('split-horizontal') ? 'horizontal' : 'vertical');
  if (keep) localStorage.setItem(SPLIT_SIZE, v);
}
const splitSize = () => parseFloat($('#editorstage')?.style.getPropertyValue('--lee-split')) || 50;
function initEditorSplitter() {
  const stage = $('#editorstage'), bar = $('.lee-editor-splitter'); if (!stage || !bar) return;
  Object.assign(bar, {tabIndex: 0, title: 'Drag, or use the arrow keys, to resize the split'});
  bar.setAttribute('role', 'separator'); bar.setAttribute('aria-label', 'Resize the split'); bar.setAttribute('aria-valuemin', 20); bar.setAttribute('aria-valuemax', 80);
  const across = () => stage.classList.contains('split-horizontal');
  bar.onpointerdown = e => {
    e.preventDefault(); bar.classList.add('drag'); stage.classList.add('split-dragging'); bar.setPointerCapture(e.pointerId);
    const r = stage.getBoundingClientRect();
    bar.onpointermove = ev => setSplitSize(across() ? (ev.clientY - r.top) / r.height * 100 : (ev.clientX - r.left) / r.width * 100);
    // a cancelled drag (a system gesture, a context menu) ends as a finished one, or the frames stay deaf to the pointer
    bar.onpointerup = bar.onpointercancel = bar.onlostpointercapture = () => {
      bar.classList.remove('drag'); stage.classList.remove('split-dragging');
      bar.onpointermove = bar.onpointerup = bar.onpointercancel = bar.onlostpointercapture = null; setSplitSize(splitSize(), true);
    };
  };
  bar.onkeydown = e => {
    const step = (across() ? {ArrowUp: -5, ArrowDown: 5} : {ArrowLeft: -5, ArrowRight: 5})[e.key];
    if (!step) return;
    e.preventDefault(); e.stopPropagation(); setSplitSize(splitSize() + step, true);
  };
}

async function refreshKernelPill() {
  try {
    const d = await api('/kernel/info');
    const pill = $('#kpill'); if (!pill) return;
    pill.className = 'lee-pill ' + (d.api_error || d.boot_error || d.notice ? 'lee-pill-warn' : d.alive ? 'lee-pill-on' : 'lee-pill-err');
    pill.textContent = (d.api_error || d.notice ? '⚠ ' : d.alive ? '⏺ ' : '○ ') + (d.key || '').split('/').pop();
    pill.title = (d.base || 'no inspector') + (d.cwd ? ' · cwd ' + d.cwd : '') +
                 (d.boot_error ? ' · ' + d.boot_error : '') + (d.api_error ? ' · inspector: ' + d.api_error : '') +
                 (d.notice ? ' · ' + d.notice.message : '');
    if (d.evicted) status(`closed ${d.evicted.name} runtime to make room; its in-memory variables were cleared`);
    paintVenvNotice(d.no_venv);
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

/* A project with Python in it and nowhere to run it says so above the editor until it is answered.
   "Not now" holds for this window's session; the server, not the page, decides when it is answered. */
function paintVenvNotice(v) {
  let bar = $('#venvnotice');
  if (!v || lee.observer || sessionStorage.getItem('lee-venv-later:' + v.root)) return bar?.remove();
  if (bar?.dataset.root === v.root) return;
  bar?.remove();
  bar = document.createElement('div');
  Object.assign(bar, {id: 'venvnotice', className: 'lee-venv-notice', role: 'status'});
  bar.dataset.root = v.root;
  bar.innerHTML = `<span>No Python environment for ${esc(v.name)}.</span>` +
    `<button class="lee-btn go" data-venv="setup">Set up .venv</button>` +
    `<button class="lee-btn" data-venv="pick">Choose interpreter…</button>` +
    `<button class="lee-btn" data-venv="later">Not now</button>`;
  $('#editorstage')?.before(bar);
  bar.addEventListener('click', async e => {
    const act = e.target.closest('[data-venv]')?.dataset.venv;
    if (act === 'later') { sessionStorage.setItem('lee-venv-later:' + v.root, '1'); bar.remove(); }
    else if (act === 'pick') { if (await pickKernel()) refreshKernelPill(); }
    else if (act === 'setup') {
      bar.querySelectorAll('button').forEach(b => b.disabled = true);
      bar.classList.add('busy'); bar.firstChild.textContent = `Setting up .venv for ${v.name}…`;
      if (!await setUpVenv(v.root, v.name)) { bar.remove(); refreshKernelPill(); }
    }
  });
}

async function checkProjectRuntime() {
  if (lee.observer) return;
  let d;
  try { d = await api('/runtime/info'); } catch (_) { return; }
  /* A folder with no environment gets the notice above the editor, from `refreshKernelPill`, and
     never a venv it did not ask for. */
  if ((!d.needs_support && !d.needs_upgrade && !d.needs_inspector) || sessionStorage.getItem('lee-runtime-asked:' + d.root)) return;
  sessionStorage.setItem('lee-runtime-asked:' + d.root, '1');
  /* Two separate lacks, one dialog: the runtime cannot run notebook code without the launchers,
     and the variables panel cannot read the namespace without what dhrishti imports. A folder
     missing both should be asked once. */
  const pkgs = (d.inspector_packages || []).map(p => `<code>${esc(p)}</code>`).join(' and ');
  const wants = [d.needs_support ? '<code>ipykernel</code> and <code>ipymini</code> to run notebook code' : '',
                 d.needs_upgrade && !d.needs_support ? `<code>ipykernel</code> 7.4 or later (${esc(d.notice.message)})` : '',
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
      if (d.needs_support || d.needs_upgrade) await post('/runtime/support', {python: d.python});
      if (d.needs_inspector) await post('/runtime/inspector', {python: d.python});
      m.remove();
      status('project runtime ready', 'ok');
      refreshKernelPill(); if (window.leeVars) leeVars();
    }
    catch (e) { status(String(e.message || e), 'err'); m.querySelector('#runtimeenable').disabled = false; }
  };
  m.querySelector('#runtimelater').onclick = () => m.remove();
}

