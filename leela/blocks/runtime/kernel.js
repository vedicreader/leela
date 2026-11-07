/* Two questions, two lists: which interpreter's packages this tab can import, and which launcher
 * runs it. Both restart the kernel, so what that costs is on screen while the choice is made.
 * Resolves true once an interpreter is chosen and its kernel is up, false when the picker closes without one. */
async function pickKernel() {
  let picked, picking = false;
  const chosen = new Promise(r => picked = r);
  const o = await api('/kernel/options');
  const models = await loadedModels();
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
    (o.notice ? `<div class="lee-err">${esc(o.notice.message)} <button class="lee-btn" data-kernel-upgrade>Upgrade ipykernel</button></div>` : '') +
    `<div class="lee-dim">choosing either of these restarts the kernel — its variables are lost</div>` +
    `<h4>launcher</h4><div class="lee-modallist">${kinds}</div>` +
    `<h4>interpreter</h4><div class="lee-modallist">${pys}</div>` +
    engineSection(models) +
    `<div class="lee-runtime-cwd"><span>working directory</span><code>${esc(o.cwd || '')}</code>` +
    `<button class="lee-btn" id="kernelcwd">change</button></div>` +
    `<label class="lee-check-setting"><input type="checkbox" id="kernel-auto-manage"${o.auto_manage ? ' checked' : ''}> leela manages the runtime limit</label>` +
    `<div class="lee-dim">at the limit, closes the longest-idle runtime instead of asking</div>` +
    `<div class="lee-mfoot"><button class="lee-btn" id="kernelattach">` +
    `${o.private ? 'attach to folder kernel' : 'give this tab its own kernel'}</button>` +
    `<span class="lee-dim">notebooks default to their own kernel; files share by folder</span></div>`,
    null, () => { if (!picking) picked(false); });
  const clearWeights = m.querySelector('#clearengines');
  if (clearWeights) clearWeights.onclick = () => clearEngines(m);
  const reconnect = $('[data-kernel-reconnect]', m);
  if (reconnect) reconnect.onclick = () => { m.remove(); restartKernel(); };
  const upgrade = $('[data-kernel-upgrade]', m);
  if (upgrade) upgrade.onclick = () => { m.remove(); upgradeIpykernel(o.python); };
  m.querySelector('#kernel-auto-manage').onchange = async (e) => {
    try { e.target.checked = await setKernelAutoManage(e.target.checked); }
    catch (err) { e.target.checked = !e.target.checked; status(String(err.message || err), 'err'); }
  };
  m.querySelector('#kernelcwd').onclick = async () => {
    const cwd = await inputDialog('kernel working directory', 'folder inside an open project',
                                  o.cwd || '', '/path/to/project');
    if (!cwd || cwd === o.cwd) return;
    m.remove(); status('restarting kernel in ' + cwd + '…');
    let d;
    try { d = await withPython(() => post('/kernel/cwd', {cwd})); }
    catch (e) { return status(String(e.message || e), 'err'); }
    markPreviousRuns(); paintEnv(''); status('kernel cwd: ' + d.cwd, 'ok'); refreshKernelPill(); leeVars();
  };
  m.querySelector('#kernelattach').onclick = async () => {
    const privateKernel = !o.private; m.remove(); status('changing kernel attachment…');
    let d;
    try { d = await withPython(() => post('/kernel/select', {private: privateKernel})); }
    catch (e) { return status(String(e.message || e), 'err'); }
    markPreviousRuns(); paintEnv('');
    status(privateKernel ? 'this tab now has its own kernel' : 'attached to the folder kernel', 'ok');
    refreshKernelPill(); leeVars();
  };
  m.addEventListener('click', async (e) => {
    const r = e.target.closest('.lee-mrow'); if (!r || r.dataset.engine) return;
    if (r.dataset.off) {
      if (!o.python) return status('choose a project interpreter before installing kernel support', 'err');
      m.remove(); status('installing ipykernel and ipymini with uv…');
      const support = await post('/runtime/support', {python: o.python});
      status(support.ok ? 'kernel support installed · ipykernel + ipymini' : support.error,
             support.ok ? 'ok' : 'err');
      return pickKernel();
    }
    picking = !r.dataset.kind; m.remove();
    status('starting the new kernel…');
    const pick = () => post('/kernel/select', r.dataset.kind ? {kind: r.dataset.kind} : {python: r.dataset.py});
    let d;
    try { d = await (r.dataset.kind ? withPython(pick) : pick()); }
    catch (e) { picked(false); return status(String(e.message || e), 'err'); }
    picked(true);
    markPreviousRuns();
    // Picking a runtime also makes its namespace the live variable source, so the panel must not
    // stay pinned, on screen or server-side, to the process watched before the switch.
    paintEnv('');
    status(`kernel: ${d.running_kind} · ${(d.python || 'leela’s own python').split('/').pop()} · variables connected`, 'ok');
    refreshKernelPill(); leeVars();
  });
  return chosen;
}

/* A project with no venv and no chosen interpreter runs no Python. The person answers once: set up
 * .venv, or choose an interpreter; then `go` runs again. Runs that ask together share one answer. */
let pythonAsked = null;
async function withPython(go) {
  try { return await go(); }
  catch (e) {
    if (e.body?.kind !== 'no_venv') throw e;
    if (!await (pythonAsked ||= askPython(e.body).finally(() => { pythonAsked = null; }))) throw e;
    return go();
  }
}
window.withPython = withPython;

async function setUpVenv(root, name) {
  status(`setting up .venv for ${name}…`);
  try {
    const r = await post('/runtime/create', {root});
    status(r.note || `the Python environment for ${name} is ready`, 'ok');
    refreshKernelPill(); return true;
  } catch (e) { status(String(e.message || e), 'err'); return false; }
}

function askPython(body) {
  const root = (body.refs || [])[0] || '', name = root.split('/').pop() || 'this project';
  return new Promise(resolve => {
    let settled = false;
    const done = v => { if (!settled) { settled = true; resolve(v); } };
    const m = modal(`<div class="lee-mhead">No Python environment for ${esc(name)}</div>` +
      `<div class="lee-dialogcopy">Leela runs no code in ${esc(name)} until it has a Python environment. ` +
      `Set up a <code>.venv</code> in the project, or choose an interpreter. Then the run starts.</div>` +
      `<div class="lee-mfoot"><button class="lee-btn go" id="pyvenv">Set up .venv</button>` +
      `<button class="lee-btn" id="pypick">Choose interpreter…</button>` +
      `<button class="lee-btn" id="pylater">Not now</button></div>`, null, () => done(false), {className: 'lee-python-ask'});
    m.querySelector('#pyvenv').onclick = async () => {
      m.querySelectorAll('button').forEach(b => b.disabled = true);
      if (!await setUpVenv(root, name)) return m.querySelectorAll('button').forEach(b => b.disabled = false);
      done(true); m.remove();
    };
    m.querySelector('#pypick').onclick = async () => { settled = true; m.remove(); resolve(await pickKernel()); };
    m.querySelector('#pylater').onclick = () => m.remove();
  });
}

//: Every Restart kernel button: the saved outputs turn historical, and the pill and the variables follow.
async function restartKernel() {
  status('restarting the kernel…');
  try { await post('/kernel/restart'); } catch (e) { return status(String(e.message || e), 'err'); }
  markPreviousRuns(); status('kernel restarted', 'ok'); refreshKernelPill(); if (window.leeVars) leeVars();
}

//: Install kernel support into `python` again, which asks for ipykernel 7.4 or later, then restart the kernel onto it.
async function upgradeIpykernel(python) {
  status('installing ipykernel 7.4 or later…');
  try { await post('/runtime/support', python ? {python} : {}); } catch (e) { return status(String(e.message || e), 'err'); }
  await restartKernel();
}

/* The weights the local models are loaded into, beside the kernels: one modal for what this machine
 * is holding open. The broker is the only thing that knows, and one that cannot answer must not keep
 * the kernel picker shut, since this is where a person comes when a runtime is misbehaving. */
async function loadedModels() {
  try { return (await api('/runtime/broker')).models || null; }
  catch (e) { console.warn('Leela could not read the model engine broker:', e); return null; }
}

function engineSection(models) {
  if (!models) return '';
  const idle = s => s >= 60 ? `idle ${Math.round(s / 60)}m` : `idle ${Math.max(0, Math.round(s))}s`;
  const rows = (models.engines || []).map(e =>
    `<div class="lee-mrow" data-engine="1" style="cursor: default">${esc(e.runtime + '/' + e.model)}` +
    `<span class="sub">${e.in_use ? 'in use' : idle(e.idle_for || 0)}</span></div>`).join('');
  return `<h4>loaded models</h4>` +
    (rows ? `<div class="lee-modallist">${rows}</div>` +
            `<div class="lee-dim">${models.live} of ${models.limit} loaded · ` +
            `weights outlive the chats built on them</div>` +
            `<div class="lee-mfoot"><button class="lee-btn" id="clearengines">clear weights</button></div>`
          : `<div class="lee-dim">no local model weights are loaded</div>`);
}

/* Releasing weights a session is answering on interrupts it, so the refusal is the server's own
 * sentence and the force is a second, deliberate answer to it. */
async function clearEngines(m) {
  let d;
  try { d = await post('/runtime/engines/clear', {}); }
  catch (e) {
    const refusal = String(e.message || e);
    const held = ((await loadedModels())?.engines || []).filter(x => x.in_use);
    if (!held.length) return status(refusal, 'err');   // not the one refusal a person can answer
    if (!await confirmDialog('a session is using a loaded model',
                             `${refusal} That session loses the model it is answering on.`,
                             'clear anyway')) return status(refusal, 'err');
    try { d = await post('/runtime/engines/clear', {force: true}); }
    catch (err) { return status(String(err.message || err), 'err'); }
  }
  const freed = (d.freed || []).map(e => `${e.runtime}/${e.model}`).join(', ');
  m.remove();
  status(freed ? `released ${freed}${d.live ? ` · ${d.live} still loaded` : ''}` : d.note, 'ok');
}

/* The kernel ceiling names the runtime it would close and waits for an answer. `settings > runtimes`
 * mutes this, and leela closes the longest-idle one itself. */
async function offerKernelRoom(body) {
  const c = body.candidate;
  if (!c) return false;                       // every runtime is busy, so there is nothing to offer
  const mins = Math.round((c.idle_for || 0) / 60);
  const idle = mins >= 1 ? `, idle ${mins} min` : '';
  if (!await confirmDialog('kernel limit reached',
      `${body.kernel_limit} runtimes are open, which is the limit. ` +
      `Close ${c.name}${idle} to make room?`, `close ${c.name}`)) return false;
  try { await post('/runtime/close', {key: c.key}); return true; }
  catch (e) { console.warn('Leela could not close that runtime:', e); return false; }
}

async function setKernelAutoManage(enabled) {
  const r = await post('/runtime/auto-manage', {enabled: !!enabled});
  return r.enabled;
}
