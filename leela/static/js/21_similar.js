/* ---- similarity: what else in this codebase looks like the thing under the cursor ---- */
function cursorLine() {
  if (lee.kind === 'notebook') {
    const c = lee.cells[lee.sel], v = c && lee.editors.get(c.id);
    return v ? LeeCM.lineOf(v) : 1;
  }
  const v = lee.editors.get('file');
  return v ? LeeCM.lineOf(v) : 1;
}

function hitList(hits, note, title, onPick) {
  let sel = 0;
  const m = modal(
    `<div class="lee-mhead">${esc(title)}<span class="sub">${esc(note || '')}</span></div>
     <div class="lee-modallist" id="hl"></div>`,
    (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, hits.length - 1); paint(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); paint(); }
      else if (e.key === 'Enter') { e.preventDefault(); go(); }
    });
  const list = m.querySelector('#hl');
  const paint = () => {
    list.innerHTML = hits.length ? hits.map((h, i) =>
      `<div class="lee-mrow${i === sel ? ' sel' : ''}" data-i="${i}">` +
      `<span>${esc(h.symbol || h.text.slice(0, 60))}</span>` +
      `<span class="sub">${esc(h.path.split('/').pop())}:${h.line}` +
      `${h.score ? ' · d=' + h.score.toFixed(3) : ''}</span></div>`).join('')
      : '<div class="lee-dim">nothing found</div>';
    list.querySelector('.sel')?.scrollIntoView({block: 'nearest'});
  };
  const go = () => { const h = hits[sel]; if (h) { m.remove(); onPick(h); } };
  list.addEventListener('click', e => { const r = e.target.closest('.lee-mrow'); if (r) { sel = +r.dataset.i; go(); } });
  paint();
  return m;
}

const openHit = openLocation;

async function findSimilar() {
  if (!lee.path) return status('open a file first', 'err');
  status('finding similar code…');
  const d = await api(`/similar?path=${encodeURIComponent(lee.path)}&line=${cursorLine()}&mode=cluster`);
  status(`${d.hits.length} similar · ${d.backend} · ${d.note}`, d.hits.length ? 'ok' : null);
  hitList(d.hits, `${d.backend} — ${d.note}`, 'code like this', openHit);
}

async function codeMap() {
  status('clustering the codebase…');
  const d = await api('/clusters');
  if (!d.clusters.length) return status(d.note || 'no clusters', 'err');
  status(`${d.clusters.length} clusters · ${d.note}`, 'ok');
  // one row per cluster; picking one drills into its members
  const rows = d.clusters.map(c => ({
    symbol: `${c.label}  (${c.size})`, text: '', path: c.files[0] || '', line: 1,
    score: 0, _cluster: c,
  }));
  hitList(rows, d.note, 'code map — clusters by shape', (r) => {
    const c = r._cluster;
    hitList(c.members, `${c.size} members across ${c.files.length} files`, `cluster: ${c.label}`, openHit);
  });
}

/* Start a run configuration -- a command line, kept in the project -- in a process leela
 * puts an inspector into. That is the difference between this and the same command in a
 * terminal: the inspector is *inside* it, so the variable panel can watch the app's own
 * module while it serves. A process started anywhere else has to opt in with
 * `dhrishti.serving.serve()`; the picker says so, because everyone asks. */
async function runApp() {
  const d = await api('/runs');
  const opts = (d.runs || []).concat(d.here ? [d.here] : []);
  if (!opts.length) {
    editRuns();
    return status('no run configurations yet — here is the file', 'err');
  }
  const start = async (r) => {
    if(r.debug)return startDirectDebug(r);
    status(`starting ${r.name}…`);
    const s = await api('/dev/start?name=' + encodeURIComponent(r.name) +
                        '&path=' + encodeURIComponent(r.cmd));
    if (!s.ok) return status(s.error || 'failed to start', 'err');
    agentLog(`<div class="lee-runline"><span class="sub">▶ ${esc(s.label)} — ${esc(s.cmd)}</span></div>` +
             `<div class="lee-runline"><span class="res">${esc((s.log || []).join('\n'))}</span></div>`);
    // A dev server's output is the thing you watch, so open the terminal it is on rather than
    // leaving it to be found under a dock tab and a filter.
    leeRunTerm(s.script || r.cmd, s.label).catch(e => status(String(e.message || e), 'err'));
    if (s.base) {
      // Running from the picker is an explicit choice of runtime. Connect the variable
      // panel immediately instead of making the user repeat that choice in “env…”.
      await post('/envs/watch', {base: s.base});
      paintEnv(s.label);
    }
    status(`${s.label} running · app ${s.app_url || '?'} · ` +
           (s.base ? 'variables connected' : 'inspector pending'), 'ok');
    leeVars();
  };
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

async function startDirectDebug(run={}) {
  let capabilities=await api('/debug/capabilities');
  if(!capabilities.debugpy){
    const ok=await confirmDialog('Install debugpy',`Install debugpy into ${capabilities.python}?`,'install');
    if(!ok)return;
    status('installing debugpy…');await post('/debug/install',{python:capabilities.python});
  }
  const path=run.program||lee.path||'', lines=path?detailedBreakpoints(path):[];
  status(`starting debugger: ${run.name||path.split('/').pop()||'Python'}…`);
  const config={...lee.debugPrefs,...run,program:run.program||path,breakpoints:path?{[path]:lines}:{}};
  await post('/debug/start',config);lee.directDebug=true;
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

/* Which live namespace the variable panel shows. Every process that registered an
 * inspector is here -- a notebook kernel, an app leela started, or something you launched
 * yourself that called `dhrishti.serving.serve()`. Nothing else can be, because nothing else
 * has anything to read. */
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
    `<div class="lee-dim">a process only appears here if it has an inspector in it — ` +
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

/* The configurations themselves, editable in place for the same reason the keymap is:
 * telling someone to go and find a JSON file is not a feature. */
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

function palette() {
  const agentCommands = [
    {name: 'Agent: autopilot mode', scope: 'agent', run: () => leeAgentControl('autopilot')},
    {name: 'Agent: guided mode', scope: 'agent', run: () => leeAgentControl('guided')},
    {name: 'Agent: directed mode', scope: 'agent', run: () => leeAgentControl('directed')},
    {name: 'Agent: pause after current call', scope: 'agent', run: pauseAgentAfterCurrent},
    {name: 'Agent: run until next write', scope: 'agent', run: () => post('/agent/run-policy', {policy: 'until_write'})},
    {name: 'Agent: run read-only calls', scope: 'agent', run: () => post('/agent/run-policy', {policy: 'reads'})},
    {name: 'Agent: edit starting state', scope: 'agent', run: leeAgentState},
    {name: 'Agent: steer after current call', scope: 'agent', run: () => $('#agentsteer')?.focus()},
  ];
  const cmds = lee.keys.filter(k => k.label).map(k => ({name: k.label, scope: k.scope, action: k.action, key: k.key})).concat(agentCommands);
  let hits = cmds, sel = 0;
  const m = modal(`<input class="lee-input" id="cp" placeholder="command…" autofocus>
                   <div class="lee-modallist" id="cplist"></div>`,
    (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, hits.length - 1); paint(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); paint(); }
      else if (e.key === 'Enter') { e.preventDefault(); go(); }
    });
  const list = m.querySelector('#cplist'), input = m.querySelector('#cp');
  const paint = () => {
    list.innerHTML = hits.slice(0, 200).map((h, i) =>
      `<div class="lee-mrow${i === sel ? ' sel' : ''}" data-i="${i}">${esc(h.name)}<span class="sub">${esc(h.scope)} · ${esc(displayChord(h.key))}</span></div>`).join('');
    list.querySelector('.sel')?.scrollIntoView({block: 'nearest'});
  };
  const go = () => { const h = hits[sel]; if (h) { m.remove(); h.run ? h.run() : leeAct(h.action); } };
  list.addEventListener('click', e => { const r = e.target.closest('.lee-mrow'); if (r) { sel = +r.dataset.i; go(); } });
  input.addEventListener('input', () => {
    const q = input.value.toLowerCase();
    hits = cmds.filter(c => c.name.toLowerCase().includes(q) || (c.action || '').includes(q)); sel = 0; paint();
  });
  paint(); setTimeout(() => input.focus(), 0);
}

