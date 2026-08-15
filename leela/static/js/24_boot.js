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
  initSplits();
  mountExec();
  initAgentComposer();
  await mountTab();
  layoutTabs();
  new ResizeObserver(layoutTabs).observe($('#header'));
  observeEditorWidth();
  checkProjectRuntime();
  leeVars();
  setInterval(leeVars, 2500);          // the kernel's own inspector is the source of truth; poll it
  setInterval(watchOpenFile, 1000);    // agent, terminal and git writes appear without a page refresh
  pollApproval();
  setInterval(pollApproval, 750);       // catches Rishi approvals raised outside an agent SSE stream
  applyTheme(readTheme());   // also rewrites a pre-family value into `family:mode`
  // The first paint is server-rendered, so the welcome screen is already on the page when
  // Leela opens on no folder; only its recent list needs filling in.
  if ($('#leerecent')) paintRecent();
  // The first paint is server-rendered without the preference, so it is only wrong when set.
  paintHiddenBtn(); if (treeHidden()) refreshFileTree(undefined, false).catch(() => {});
  refreshProjectPills();
  setInterval(refreshKernelPill, 5000);
  setInterval(refreshProjectPills, 5000);
  setInterval(pollRunLogs, 2000);      // only does anything while the logs pane is open
  status('ready', 'ok');
}

document.addEventListener('DOMContentLoaded', boot);

document.addEventListener('htmx:afterSwap', (e) => {
  const id = e.target.id || '';
  // A tab change swaps only the tab bar; re-mount the editor for whatever is now active.
  if (id === 'tabbar') { mountTab().then(leeVars); refreshProjectPills(); requestAnimationFrame(layoutTabs); }
  // Adding a folder rebuilds the whole shell, so everything the client owns is remounted.
  else if (id === 'shell') { lee.editors.clear(); loadAgentModels(); initSplits(); mountExec(); initAgentComposer(); mountTab().then(leeVars); requestAnimationFrame(layoutTabs); }
});
