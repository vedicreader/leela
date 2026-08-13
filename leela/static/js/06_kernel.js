/* ---------------------------------------------------------- kernel picker */
/* Two questions, two lists: which interpreter's packages this tab can import, and which
 * launcher runs it. Both restart the kernel, so what that costs is on the screen while
 * the choice is being made rather than in a toast afterwards. */
async function pickKernel() {
  const o = await api('/kernel/options');
  const row = (cur, main, sub, attrs) =>
    `<div class="lee-mrow${cur ? ' sel' : ''}" ${attrs}>${cur ? '● ' : '○ '}${esc(main)}` +
    `<span class="sub">${esc(sub)}</span></div>`;
  const kinds = o.kinds.map(k => row(
    k.current, k.id,
    k.note || (k.id === 'ipymini' ? 'execs and completions run beside a busy cell'
                                  : 'the standard jupyter kernel'),
    `data-kind="${esc(k.id)}"${k.available ? '' : ' data-off="1"'}`)).join('');
  const pys = o.pythons.map(p => row(p.current, p.label, p.path, `data-py="${esc(p.path)}"`)).join('');
  const m = modal(
    `<div class="lee-mhead">kernel<span class="sub">${esc(o.key)} · ` +
    `${o.alive ? '⏺ running, pid ' + o.pid : '○ not started'} · ` +
    `${o.private ? 'private to this tab' : 'shared across this folder'}</span></div>` +
    (o.boot_error ? `<div class="lee-err">${esc(o.boot_error)}</div>` : '') +
    (o.api_error ? `<div class="lee-err">Inspector connection failed: ${esc(o.api_error)} <button class="lee-btn" data-kernel-reconnect>Restart kernel</button></div>` : '') +
    `<div class="lee-dim">choosing either of these restarts the kernel — its variables are lost</div>` +
    `<h4>launcher</h4><div class="lee-modallist">${kinds}</div>` +
    `<h4>interpreter</h4><div class="lee-modallist">${pys}</div>` +
    `<div class="lee-runtime-cwd"><span>working directory</span><code>${esc(o.cwd || '')}</code>` +
    `<button class="lee-btn" id="kernelcwd">change</button></div>` +
    `<div class="lee-mfoot"><button class="lee-btn" id="kernelattach">` +
    `${o.private ? 'attach to folder kernel' : 'give this tab its own kernel'}</button>` +
    `<span class="lee-dim">notebooks default to their own kernel; files share by folder</span></div>`);
  const reconnect = $('[data-kernel-reconnect]', m);
  if (reconnect) reconnect.onclick = async () => { await post('/kernel/restart'); m.remove(); status('kernel restarted', 'ok'); };
  m.querySelector('#kernelcwd').onclick = async () => {
    const cwd = await inputDialog('kernel working directory', 'folder inside an open project',
                                  o.cwd || '', '/path/to/project');
    if (!cwd || cwd === o.cwd) return;
    m.remove(); status('restarting kernel in ' + cwd + '…');
    const d = await post('/kernel/cwd', {cwd});
    markPreviousRuns(); paintEnv(''); status('kernel cwd: ' + d.cwd, 'ok'); refreshKernelPill(); leeVars();
  };
  m.querySelector('#kernelattach').onclick = async () => {
    const privateKernel = !o.private; m.remove(); status('changing kernel attachment…');
    const d = await post('/kernel/select', {private: privateKernel});
    markPreviousRuns(); paintEnv('');
    status(privateKernel ? 'this tab now has its own kernel' : 'attached to the folder kernel', 'ok');
    refreshKernelPill(); leeVars();
  };
  m.addEventListener('click', async (e) => {
    const r = e.target.closest('.lee-mrow'); if (!r) return;
    if (r.dataset.off) {
      if (!o.python) return status('choose a project interpreter before installing kernel support', 'err');
      m.remove(); status('installing ipykernel and ipymini with uv…');
      const support = await post('/runtime/support', {python: o.python});
      status(support.ok ? 'kernel support installed · ipykernel + ipymini' : support.error,
             support.ok ? 'ok' : 'err');
      return pickKernel();
    }
    m.remove();
    status('starting the new kernel…');
    const d = await post('/kernel/select',
                         r.dataset.kind ? {kind: r.dataset.kind} : {python: r.dataset.py});
    markPreviousRuns();
    // Picking a runtime also makes its namespace the live variable source. Do not leave
    // the panel visually (or server-side) pinned to the process watched before the switch.
    paintEnv('');
    status(`kernel: ${d.running_kind} · ${(d.python || 'leela’s own python').split('/').pop()} · variables connected`, 'ok');
    refreshKernelPill(); leeVars();
  });
}

