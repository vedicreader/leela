async function startRun(r) {
  if (r.debug) return startDirectDebug(r);
  status(`starting ${r.name || (r.cmd || '').split('/').pop()}…`);
  let s;
  try { s = await withPython(() => post('/dev/start?name=' + encodeURIComponent(r.name || '') + '&path=' + encodeURIComponent(r.cmd))); }
  catch (e) { return status(String(e.message || e), 'err'); }
  if (!s.ok) return status(s.error || 'failed to start', 'err');
  agentLog(`<div class="lee-runline"><span class="sub">▶ ${esc(s.label)}: ${esc(s.cmd)}</span></div>` +
           `<div class="lee-runline"><span class="res">${esc((s.log || []).join('\n'))}</span></div>`);
  // A dev server's output is the thing you watch, so open the terminal it is on rather than
  // leaving it to be found under a dock tab and a filter.
  leeRunTerm(s.script || r.cmd, s.label, s.pid).catch(e => status(String(e.message || e), 'err'));
  if (s.base) {
    // Running is an explicit choice of runtime, so connect the variable panel rather than making
    // the user repeat that choice in "env…".
    await post('/envs/watch', {base: s.base});
    paintEnv(s.label);
  }
  status(`${s.label} running · app ${s.app_url || '?'} · ` +
         (s.base ? 'variables connected' : 'inspector pending'), 'ok');
  pollRunLogs(); leeVars();
}
window.startRun = startRun;

async function runApp() {
  const d = await api('/runs');
  const opts = (d.runs || []).concat(d.here ? [d.here] : []);
  if (!opts.length) {
    editRuns();
    return status('no run configurations yet. This is the file for them', 'err');
  }
  const start = startRun;
  if (opts.length === 1) return start(opts[0]);
  const m = modal(
    `<div class="lee-mhead">run<span class="sub">${esc(d.path || 'no project folder')}</span></div>` +
    `<div class="lee-modallist">${opts.map((r, i) =>
      `<div class="lee-mrow" data-i="${i}">${esc(r.name)}<span class="sub">${esc(r.cmd)}</span></div>`).join('')}</div>` +
    `<div class="lee-mfoot"><button class="lee-btn" id="editruns">edit configurations</button></div>`);
  m.addEventListener('click', (e) => {
    const r = e.target.closest('.lee-mrow'); if (!r) return;
    m.remove(); start(opts[+r.dataset.i]);
  });
  m.querySelector('#editruns').onclick = () => { m.remove(); editRuns(); };
}

// The menu bar reaches this from `evaluate_js`, which runs in global scope and cannot see a
// module-scope name. Same arguments the Debug chrome menu passes.
window.leeDebugFile = () => startDirectDebug(
  {name: lee.path?.split('/').pop() || 'Python', program: lee.path, debug: true});

async function startDirectDebug(run={}) {
  let capabilities;
  try{capabilities=await withPython(()=>api('/debug/capabilities'));}catch(e){return status(String(e.message||e),'err');}
  if(!capabilities.debugpy){
    const ok=await confirmDialog('Install debugpy',`Install debugpy into ${capabilities.python}?`,'install');
    if(!ok)return;
    status('installing debugpy…');await post('/debug/install',{python:capabilities.python});
  }
  const path=run.program||lee.path||'', lines=path?detailedBreakpoints(path):[];
  status(`starting debugger: ${run.name||path.split('/').pop()||'Python'}…`);
  const config={...lee.debugPrefs,...run,program:run.program||path,breakpoints:path?{[path]:lines}:{}};
  try{await withPython(()=>post('/debug/start',config));}catch(e){return status(String(e.message||e),'err');}
  lee.directDebug=true;
  status('debugger running','ok');
  postEvents('/debug/events',{},(event,data)=>{
    if(event==='stopped'){lee.debugThread=data.thread_id;paintDebugger(data);status(`paused at line ${data.frames?.[0]?.line||'?'}`,'ok');}
    else if(event==='continued'){$('#debugger')?.classList.add('running');}
    else if(event==='output'){const text=data.output||'';if(text)agentLog(`<div class="lee-runline"><span class="res">${esc(text)}</span></div>`);}
    else if(event==='error')status(data.message||'debugger failed','err');
    else if(event==='terminated'||event==='exited'){leeDebugStop();status('debug session finished','ok');}
  }).catch(e=>status(e.message||String(e),'err'));
}
window.leeStartDebug=startDirectDebug;

/* Which live namespace the variable panel shows. Every process that registered an inspector is
 * here: a notebook kernel, an app leela started, or something you launched yourself that called
 * `dhrishti.serving.serve()`. Nothing else has anything to read. */
function paintEnv(name) {
  lee.env = name || '';
  const t = $('#envtag'); if (!t) return;
  t.textContent = name ? '▶ ' + name : '';
  t.style.display = name ? '' : 'none';
  t.title = name ? 'Run and the variable panel are connected to this runtime' : '';
}

async function pickEnv() {
  const d = await api('/envs');
  const rows = [{name: 'the tab’s own kernel', base: null, kind: 'kernel', current: !d.watching}]
    .concat(d.envs || []);
  const m = modal(
    `<div class="lee-mhead">runtime<span class="sub">Run + variables · ${(d.envs || []).length} live env(s)</span></div>` +
    `<div class="lee-modallist">${rows.map((e, i) =>
      `<div class="lee-mrow${e.current ? ' sel' : ''}" data-i="${i}">${e.current ? '● ' : '○ '}` +
      `${esc(e.name)}<span class="sub">${esc(e.kind)}${e.pid ? ' · pid ' + e.pid : ''}</span></div>`).join('')}</div>` +
    `<div class="lee-dim">a process shows here only when it has an inspector in it. ` +
    `<code>${esc(d.hint)}</code> puts one in yours.</div>`);
  m.addEventListener('click', async (e) => {
    const r = e.target.closest('.lee-mrow'); if (!r) return;
    const pick = rows[+r.dataset.i];
    m.remove();
    await post('/envs/watch', {base: pick.base});
    paintEnv(pick.base ? pick.name : '');
    status(pick.base ? 'watching ' + pick.name : 'back on the tab’s kernel', 'ok');
    leeVars();
  });
}

/* The configurations themselves, editable in place for the same reason the keymap is. */
async function editRuns() {
  const d = await api('/runs/file');
  let data;
  try { data = JSON.parse(d.text); } catch (_) { data = {runs: []}; }
  let runs = Array.isArray(data) ? data : (data.runs || []);
  const m = modal(`<div class="lee-mhead">run configurations<span class="sub">${esc(d.path || 'open a folder first')}</span></div>` +
    `<div class="lee-runtime-workbench"><header><div><strong>Project runtime</strong><span>Commands, working directories, and environment sources</span></div>` +
    `<button class="lee-btn" data-add-run>Add configuration</button></header><div data-run-list></div>` +
    `<details class="lee-run-json"><summary>Advanced JSON</summary><textarea class="lee-keyedit" spellcheck="false"></textarea></details></div>` +
    `<div class="lee-mfoot"><span class="lee-dim">Secret values belong in an ignored .env.local file, not runs.json.</span><span class="lee-spacer"></span>` +
    `<button class="lee-btn" data-cancel>cancel</button><button class="lee-btn go" data-save>save configurations</button></div>`,
    null, null, {className: 'lee-runtime-modal', storageKey: 'runs'});
  const list = $('[data-run-list]', m), json = $('.lee-run-json textarea', m);
  const normal = r => ({name:r.name||'run',cmd:r.cmd||'',cwd:r.cwd||'',watch:r.watch||'',inspect:r.inspect!==false,
    env_file:r.env_file||'',env:{...(r.env||{})},debug:!!r.debug,request:r.request||'launch',program:r.program||'',module:r.module||'',
    args:Array.isArray(r.args)?r.args:[],justMyCode:r.justMyCode!==false,stopOnEntry:!!r.stopOnEntry,subProcess:r.subProcess!==false,
    host:r.host||'127.0.0.1',port:Number(r.port)||5678,django:!!r.django,jinja:!!r.jinja,gevent:!!r.gevent,pathMappings:r.pathMappings||[]});
  runs = runs.map(normal);
  const collect = () => $$('.lee-run-card', list).map(card => {
    const env = {}; $$('.lee-env-row', card).forEach(row => { const key = $('[data-env-key]', row).value.trim(); if (key) env[key] = $('[data-env-value]', row).value; });
    return {name:$('[data-run-name]',card).value.trim()||'run',cmd:$('[data-run-cmd]',card).value.trim(),cwd:$('[data-run-cwd]',card).value.trim(),
      watch:$('[data-run-watch]',card).value.trim(),env_file:$('[data-run-env-file]',card).value.trim(),inspect:$('[data-run-inspect]',card).checked,env,
      debug:$('[data-run-debug]',card).checked,request:$('[data-debug-request]',card).value,program:$('[data-debug-program]',card).value.trim(),
      module:$('[data-debug-module]',card).value.trim(),args:$('[data-debug-args]',card).value.trim().split(/\s+/).filter(Boolean),
      justMyCode:$('[data-debug-mycode]',card).checked,stopOnEntry:$('[data-debug-entry]',card).checked,subProcess:$('[data-debug-subprocess]',card).checked,
      host:$('[data-debug-host]',card).value.trim()||'127.0.0.1',port:Number($('[data-debug-port]',card).value)||5678,
      django:$('[data-debug-django]',card).checked,jinja:$('[data-debug-jinja]',card).checked,gevent:$('[data-debug-gevent]',card).checked,
      pathMappings:(()=>{try{return JSON.parse($('[data-debug-paths]',card).value||'[]');}catch(_){return [];}})()};
  });
  const envRow = (key = '', value = '') => `<div class="lee-env-row"><input class="lee-input" data-env-key placeholder="NAME" value="${esc(key)}">` +
    `<input class="lee-input" data-env-value placeholder="value" value="${esc(value)}"><button class="lee-icon" data-remove-env aria-label="remove variable">×</button></div>`;
  const paint = () => {
    list.innerHTML = runs.map((r, i) => `<section class="lee-run-card" data-i="${i}"><header><strong>${esc(r.name)}</strong>` +
      `<button class="lee-btn warn" data-remove-run>remove</button></header><div class="lee-run-fields">` +
      `<label>Name<input class="lee-input" data-run-name value="${esc(r.name)}"></label><label>Command<input class="lee-input" data-run-cmd value="${esc(r.cmd)}" placeholder="uv run python app.py"></label>` +
      `<label>Working directory<input class="lee-input" data-run-cwd value="${esc(r.cwd)}" placeholder="project root"></label><label>Watch module<input class="lee-input" data-run-watch value="${esc(r.watch)}" placeholder="infer from command"></label>` +
      `<label>Environment file<input class="lee-input" data-run-env-file value="${esc(r.env_file)}" placeholder=".env.local"></label><label class="lee-run-check"><input type="checkbox" data-run-inspect${r.inspect?' checked':''}> Attach live inspector</label></div>` +
      `<details class="lee-debug-config"${r.debug?' open':''}><summary><label class="lee-run-check"><input type="checkbox" data-run-debug${r.debug?' checked':''}> Debug with debugpy</label></summary><div class="lee-run-fields">` +
      `<label>Request<select class="lee-select" data-debug-request><option value="launch"${r.request==='launch'?' selected':''}>Launch</option><option value="attach"${r.request==='attach'?' selected':''}>Attach</option></select></label>` +
      `<label>Program<input class="lee-input" data-debug-program value="${esc(r.program)}" placeholder="active Python file"></label><label>Module<input class="lee-input" data-debug-module value="${esc(r.module)}" placeholder="pytest"></label>` +
      `<label>Arguments<input class="lee-input" data-debug-args value="${esc(r.args.join(' '))}" placeholder="-x tests"></label><label>Attach host<input class="lee-input" data-debug-host value="${esc(r.host)}"></label><label>Attach port<input class="lee-input" data-debug-port type="number" value="${r.port}"></label>` +
      `<label>Path mappings<input class="lee-input" data-debug-paths value="${esc(JSON.stringify(r.pathMappings||[]))}" placeholder='[{"localRoot":".","remoteRoot":"/app"}]'></label>` +
      `<label class="lee-run-check"><input type="checkbox" data-debug-mycode${r.justMyCode?' checked':''}> Just my code</label><label class="lee-run-check"><input type="checkbox" data-debug-entry${r.stopOnEntry?' checked':''}> Stop on entry</label><label class="lee-run-check"><input type="checkbox" data-debug-subprocess${r.subProcess?' checked':''}> Subprocesses</label>` +
      `<label class="lee-run-check"><input type="checkbox" data-debug-django${r.django?' checked':''}> Django</label><label class="lee-run-check"><input type="checkbox" data-debug-jinja${r.jinja?' checked':''}> Jinja templates</label><label class="lee-run-check"><input type="checkbox" data-debug-gevent${r.gevent?' checked':''}> gevent</label></div></details>` +
      `<div class="lee-env-head"><strong>Environment variables</strong><button class="lee-btn" data-add-env>Add variable</button></div><div data-env-list>${Object.entries(r.env).map(([k,v])=>envRow(k,v)).join('')}</div></section>`).join('') ||
      `<div class="lee-empty"><strong>No run configurations</strong><p>Add how this project starts, then attach its live namespace to Variables.</p></div>`;
    $$('.lee-run-card', list).forEach(card => {
      $('[data-remove-run]', card).onclick = () => { runs = collect(); runs.splice(+card.dataset.i, 1); paint(); };
      $('[data-add-env]', card).onclick = () => { $('[data-env-list]', card).insertAdjacentHTML('beforeend', envRow()); $('.lee-env-row:last-child [data-env-key]', card).focus(); };
      card.onclick = e => { const b = e.target.closest('[data-remove-env]'); if (b) b.closest('.lee-env-row').remove(); };
    });
  };
  paint();
  $('[data-add-run]', m).onclick = () => { runs = collect(); runs.push(normal({name: `run ${runs.length + 1}`})); paint(); $$('.lee-run-card', list).at(-1)?.scrollIntoView({block:'center'}); };
  $('.lee-run-json', m).ontoggle = e => { if (e.target.open) json.value = JSON.stringify({runs: collect()}, null, 2); };
  json.addEventListener('change', () => { try { runs = (JSON.parse(json.value).runs || []).map(normal); paint(); } catch (e) { status('invalid run configuration JSON: ' + e.message, 'err'); } });
  $('[data-cancel]', m).onclick = () => m.remove();
  $('[data-save]', m).onclick = async () => {
    try {
      runs = collect();
      const r = await post('/runs/save', {text: JSON.stringify({runs}, null, 2) + '\n'});
      status(r.note || `saved ${r.runs.length} configuration(s)`, r.note ? 'err' : 'ok'); m.remove();
    } catch (e) { status(String(e.message || e), 'err'); }
  };
}

