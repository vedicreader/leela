/* CodeMirror measures its width once and caches it, and nothing was telling it when that width
   changed. Toggling a pane, unpinning one so it auto-closes, opening a split, switching the
   markdown view or resizing the window all move the editor's right edge without a keystroke, so
   the cached measurement outlived the layout.

   Visible as a vertical band cutting through the text: the overview stripe is pinned to the
   *editor's* right edge, so it stays where the edge used to be while the text runs on past it.
   Intermittent only because it takes a resize that happens to miss a re-measure.

   `requestMeasure` is plain EditorView API, so no new `LeeCM` export and no vendored rebuild. */
/* An editor skipped by the sweep above still holds the width the pane used to have, which is the
   band cutting through the text this whole observer exists to prevent. It is measured the moment it
   is scrolled to instead, so the cost is paid for the editors a person actually looks at. */
function measureWhenSeen(views) {
  if (!views.length || !('IntersectionObserver' in window)) return;
  const io = new IntersectionObserver(entries => {
    for (const e of entries) if (e.isIntersecting) {
      io.unobserve(e.target);
      try { e.target._leeMeasure?.requestMeasure(); } catch (_) { /* torn down while off screen */ }
    }
  }, {rootMargin: '200px 0px'});
  for (const v of views) { try { v.dom._leeMeasure = v; io.observe(v.dom); } catch (_) {} }
}

function observeEditorWidth() {
  if (!('ResizeObserver' in window)) return;
  let frame = 0;
  const remeasure = () => {
    cancelAnimationFrame(frame);
    // Coalesced: a drag on the splitter fires this per frame, and each measure is a layout read.
    //
    // Spread, because a notebook that has been scrolled through holds 156 editors and measuring all
    // of them lands in one frame: 128ms in the engine the packaged app runs, which is what opening
    // the agent pane felt like. A slice per frame costs the same total and blocks nothing.
    const views = [...lee.editors.values(), lee.gitMergeView?.a, lee.gitMergeView?.b].filter(Boolean);
    /* A measure is only worth paying for on an editor somebody can see. A notebook scrolled end to
       end holds a view per cell and re-measured every one of them on every splitter drag; the ones
       off screen are marked instead and measured when they scroll back in, which is what
       `observeNotebookCells` already does for building them. */
    const tall = window.innerHeight || 900;
    const onScreen = v => {
      try { const r = v.dom.getBoundingClientRect(); return r.bottom > -tall && r.top < tall * 2; }
      catch (_) { return false; }
    };
    const later = [];
    const slice = () => {
      for (const v of views.splice(0, 12)) {
        try { onScreen(v) ? v.requestMeasure() : later.push(v); } catch (_) { /* torn down */ }
      }
      if (views.length) frame = requestAnimationFrame(slice);
      else measureWhenSeen(later.splice(0));
    };
    frame = requestAnimationFrame(slice);
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
  bootStep('mode', leeModeBoot);
  bootStep('click bindings', bindModClick);
  bootStep('exec strip', mountExec);
  bootStep('agent composer', initAgentComposer);
  // The agent pane is client-owned, so a reload starts it blank; the turns are on disk.
  bootStep('agent pane', rehydrateAgentLive);
  // `/?cell=N`: a hand-off from abhyasa (`/learn`) opens the notebook at that cell; the address drops it, so a reload keeps the place.
  const handCell = new URLSearchParams(location.search).get('cell');
  if (handCell !== null && /^\d{1,5}$/.test(handCell)) { lee.pendingLocation = {cellIndex: +handCell, line: 1}; history.replaceState(null, '', location.pathname); }
  await bootStep('editor', mountTab);
  bootStep('tab strip', layoutTabs);
  bootStep('header layout', () => new ResizeObserver(layoutTabs).observe($('#header')));
  bootStep('editor width', observeEditorWidth);
  bootStep('project runtime', checkProjectRuntime);
  bootStep('variables', leeVars);
  bootStep('lesson reviews', refreshLessonDue);
  setInterval(whenVisible(refreshLessonDue), 600000);
  setInterval(whenVisible(leeVars), 2500);   // the kernel's own inspector is the source of truth
  setInterval(watchOpenFile, 10000);   // a backstop: /fs/events is what actually reports a write
  bootStep('approvals', approvalLoop);                       // catches Rishi approvals raised outside an agent SSE stream
  bootStep('theme', () => applyTheme(readTheme()));   // also rewrites a pre-family value into `family:mode`
  // after the theme, so a theme set at boot is not a look move; a reload of the presenting tab comes back from the server's state
  bootStep('presentation', presentResume);
  // The first paint is server-rendered, so the welcome screen is already on the page when
  // Leela opens on no folder; only its recent list needs filling in.
  if ($('#leerecent')) bootStep('recent folders', paintRecent);
  // Beside it, and only in a packaged app with nothing set up: `/agent/setup` decides, not this.
  if ($('#leesetup')) bootStep('setup pane', leeSetupPane);
  // A network check, so it waits until the page is at work; it fails silent.
  setTimeout(() => leeUpdateNotice().catch(() => {}), 5000);
  setInterval(() => leeUpdateNotice().catch(() => {}), 3600e3);
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
  /* 286kb, fetched on the first terminal action with the person waiting on it. Fetching it while
     nothing is waiting spends the same time where nobody is watching. `requestIdleCallback` again:
     WebKit, which is the packaged app, has never shipped it. */
  const warmTerm = () => loadTermBundle().catch(() => {});
  typeof requestIdleCallback === 'function' ? requestIdleCallback(warmTerm, {timeout: 8000})
                                            : setTimeout(warmTerm, 3000);
  bootStep('project pills', refreshProjectPills);
  setInterval(whenVisible(refreshKernelPill), 5000);
  // The pills change only when a root or the cwd does, and every one of those already calls
  // `refreshProjectPills`. Polling them was 24 requests a minute saying nothing.
  bootStep('run log', runLogLoop);
  bootStep('file watcher', watchFiles);
  bootStep('file tree marks', () => { paintTreeGit(); });
  status('ready', 'ok');
}

// A window nobody is looking at asks for nothing.
const whenVisible = fn => () => { if (!document.hidden) fn(); };

document.addEventListener('DOMContentLoaded', boot);

document.addEventListener('htmx:beforeRequest', e => {
  if (/^\/tab\/(select|close)\b/.test(e.detail.pathInfo?.requestPath || '')) dropTabReads();
});

// The pills describe the folder the active tab is in, so a switch inside one folder has nothing new to say.
let pillsFolder = null;
function refreshPillsForTab() {
  const folder = ($('.lee-tab.active')?.title || '').replace(/\/[^/]*$/, '');
  if (folder === pillsFolder) return;
  pillsFolder = folder; refreshProjectPills();
}

document.addEventListener('htmx:afterSwap', (e) => {
  const id = e.target.id || '';
  // A tab change swaps only the tab bar; re-mount the editor for whatever is now active.
  if (id === 'tabbar') { mountTab().then(leeVars); refreshPillsForTab(); requestAnimationFrame(layoutTabs); }
  // Adding a folder rebuilds the whole shell, so everything the client owns is remounted.
  else if (id === 'shell') { paintTreeGit(); lee.editors.clear(); loadAgentModels(); initSplits(); leeModeBoot(); mountExec(); initAgentComposer(); rehydrateAgentLive(); mountTab().then(leeVars); refreshProjectPills(); refreshLessonDue(); requestAnimationFrame(layoutTabs); }
});
