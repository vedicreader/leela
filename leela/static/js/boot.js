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

/* One step of boot, which costs itself and nothing after it when it fails.

   `boot` was a single sequence of awaits, so one throw anywhere in it took every step below with
   it: the branch and kernel pills kept the text the page was rendered with, the file watcher and
   the polls never started, and nothing said why. */
async function bootStep(name, fn) {
  try { return await fn(); }
  catch (e) { console.error('boot: ' + name, e); status(`${name} did not start: ${e.message || e}`, 'err'); }
}

/* ------------------------------------------------------------------ boot */
async function boot() {
  await bootStep('settings', () => Promise.all([loadKeys(), loadSettings()]));
  // Model discovery can probe CLIs and registries; it must not hold the editor's first paint.
  loadAgentModels().catch(e => status(String(e.message || e), 'err'));
  refreshAgentThreads().catch(e => status(String(e.message || e), 'err'));
  bootStep('panes', initSplits);
  bootStep('click bindings', bindModClick);
  bootStep('exec strip', mountExec);
  bootStep('agent composer', initAgentComposer);
  // The agent pane is client-owned, so a reload starts it blank; the turns are on disk.
  bootStep('agent pane', rehydrateAgentLive);
  await bootStep('editor', mountTab);
  bootStep('tab strip', layoutTabs);
  bootStep('header layout', () => new ResizeObserver(layoutTabs).observe($('#header')));
  bootStep('editor width', observeEditorWidth);
  bootStep('project runtime', checkProjectRuntime);
  bootStep('variables', leeVars);
  setInterval(whenVisible(leeVars), 2500);   // the kernel's own inspector is the source of truth
  setInterval(watchOpenFile, 10000);   // a backstop: /fs/events is what actually reports a write
  bootStep('approvals', approvalLoop);                       // catches Rishi approvals raised outside an agent SSE stream
  bootStep('theme', () => applyTheme(readTheme()));   // also rewrites a pre-family value into `family:mode`
  // The first paint is server-rendered, so the welcome screen is already on the page when
  // Leela opens on no folder; only its recent list needs filling in.
  if ($('#leerecent')) bootStep('recent folders', paintRecent);
  // Beside it, and only in a packaged app with nothing set up: `/agent/setup` decides, not this.
  if ($('#leesetup')) bootStep('setup pane', leeSetupPane);
  // The first paint is server-rendered without the preference, so it is only wrong when set.
  bootStep('file tree', paintHiddenBtn); if (treeHidden()) refreshFileTree(undefined, false).catch(() => {});
  /* The agent's log is one append-only file and grows without bound; reading it the first time
     costs seconds on a large one, and it is cached after that. Paying it here, once the page is
     interactive, means the first click on History does not. */
  // `typeof`, because a bare reference to a global that does not exist is a ReferenceError, not a
  // falsy value. WebKit has never shipped `requestIdleCallback`, so this line threw in the packaged
  // app and took every step below it: both pills, the polls, the run log and the file watcher.
  typeof requestIdleCallback === 'function' ? requestIdleCallback(warmAgentHistory, {timeout: 4000})
                                            : setTimeout(warmAgentHistory, 2000);
  bootStep('project pills', refreshProjectPills);
  setInterval(whenVisible(refreshKernelPill), 5000);
  // The pills change only when a root or the cwd does, and every one of those already calls
  // `refreshProjectPills`. Polling them was 24 requests a minute saying nothing.
  bootStep('run log', runLogLoop);
  bootStep('file watcher', watchFiles);
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
