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
  checkProjectRuntime();
  leeVars();
  setInterval(leeVars, 2500);          // the kernel's own inspector is the source of truth; poll it
  setInterval(watchOpenFile, 1000);    // agent, terminal and git writes appear without a page refresh
  pollApproval();
  setInterval(pollApproval, 750);       // catches Rishi approvals raised outside an agent SSE stream
  applyTheme(localStorage.getItem('lee-theme') || 'cursor');
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
