/* CodeMirror measures its width once and caches it, and nothing was telling it when that width
   changed. Toggling a pane, unpinning one so it auto-closes, opening a split, switching the
   markdown view or resizing the window all move the editor's right edge without a keystroke, so
   the cached measurement outlived the layout.

   Visible as a vertical band cutting through the text: the overview stripe is pinned to the
   *editor's* right edge, so it stays where the edge used to be while the text runs on past it.
   Intermittent only because it takes a resize that happens to miss a re-measure.

   `requestMeasure` is plain EditorView API, so no new `LeeCM` export and no vendored rebuild. */
function observeEditorWidth() {
  if (!('ResizeObserver' in window)) return;
  let frame = 0;
  const remeasure = () => {
    cancelAnimationFrame(frame);
    // Coalesced: a drag on the splitter fires this per frame, and each measure is a layout read.
    frame = requestAnimationFrame(() => {
      for (const v of lee.editors.values()) { try { v.requestMeasure(); } catch (_) { /* torn down */ } }
      lee.gitMergeView?.a?.requestMeasure?.(); lee.gitMergeView?.b?.requestMeasure?.();
    });
  };
  const observer = new ResizeObserver(remeasure);
  for (const sel of ['#editor', '#shell', '#bottomdock']) { const el = $(sel); if (el) observer.observe(el); }
}

/* ------------------------------------------------------------------ boot */
async function boot() {
  await Promise.all([loadKeys(), loadSettings()]);
  // Model discovery can probe CLIs and registries; it must not hold the editor's first paint.
  loadAgentModels().catch(e => status(String(e.message || e), 'err'));
  refreshAgentThreads().catch(e => status(String(e.message || e), 'err'));
  initSplits();
  bindModClick();
  mountExec();
  initAgentComposer();
  // The agent pane is client-owned, so a reload starts it blank; the turns are on disk.
  rehydrateAgentLive();
  await mountTab();
  layoutTabs();
  new ResizeObserver(layoutTabs).observe($('#header'));
  observeEditorWidth();
  checkProjectRuntime();
  leeVars();
  setInterval(whenVisible(leeVars), 2500);   // the kernel's own inspector is the source of truth
  setInterval(watchOpenFile, 10000);   // a backstop: /fs/events is what actually reports a write
  approvalLoop();                       // catches Rishi approvals raised outside an agent SSE stream
  applyTheme(readTheme());   // also rewrites a pre-family value into `family:mode`
  // The first paint is server-rendered, so the welcome screen is already on the page when
  // Leela opens on no folder; only its recent list needs filling in.
  if ($('#leerecent')) paintRecent();
  // Beside it, and only in a packaged app with nothing set up: `/agent/setup` decides, not this.
  if ($('#leesetup')) leeSetupPane();
  // The first paint is server-rendered without the preference, so it is only wrong when set.
  paintHiddenBtn(); if (treeHidden()) refreshFileTree(undefined, false).catch(() => {});
  /* The agent's log is one append-only file and grows without bound; reading it the first time
     costs seconds on a large one, and it is cached after that. Paying it here, once the page is
     interactive, means the first click on History does not. */
  requestIdleCallback ? requestIdleCallback(warmAgentHistory, {timeout: 4000})
                      : setTimeout(warmAgentHistory, 2000);
  refreshProjectPills();
  setInterval(whenVisible(refreshKernelPill), 5000);
  // The pills change only when a root or the cwd does, and every one of those already calls
  // `refreshProjectPills`. Polling them was 24 requests a minute saying nothing.
  runLogLoop();
  watchFiles();
  status('ready', 'ok');
}

// A window nobody is looking at asks for nothing.
const whenVisible = fn => () => { if (!document.hidden) fn(); };

document.addEventListener('DOMContentLoaded', boot);

document.addEventListener('htmx:afterSwap', (e) => {
  const id = e.target.id || '';
  // A tab change swaps only the tab bar; re-mount the editor for whatever is now active.
  if (id === 'tabbar') { mountTab().then(leeVars); refreshProjectPills(); requestAnimationFrame(layoutTabs); }
  // Adding a folder rebuilds the whole shell, so everything the client owns is remounted.
  else if (id === 'shell') { lee.editors.clear(); loadAgentModels(); initSplits(); mountExec(); initAgentComposer(); rehydrateAgentLive(); mountTab().then(leeVars); refreshProjectPills(); requestAnimationFrame(layoutTabs); }
});
