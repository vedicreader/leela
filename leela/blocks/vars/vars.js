async function leeVars() {
  const box = $('#vars'); if (!box || document.hidden) return;
  // Polling is a refresh, not a queue: coalesce every request that arrives while one is in
  // flight, or a slow inspector stacks fetches and full-tree DOM rebuilds without bound.
  if (lee.varsBusy) { lee.varsPending = true; return; }
  lee.varsBusy = true;
  try { await refreshVars(box); }
  finally {
    lee.varsBusy = false;
    if (lee.varsPending) { lee.varsPending = false; queueMicrotask(leeVars); }
  }
}
window.leeVars = leeVars;

async function refreshVars(box) {
  const profile = $('#varprofile')?.value || 'minimal';
  const sort = $('#varsort')?.value || 'recent';
  let d;
  if (lee.debugState?.paused) {
    const frame = (lee.debugState.frames || []).find(f => f.id === lee.debugState.frame_id);
    d = {runtime: `debug:${lee.debugState.thread_id}:${lee.debugState.frame_id}`,
         groups: [{label: `paused locals · ${frame?.name || 'frame'} · line ${frame?.line || '?'}`,
                   nodes: (lee.debugState.variables || []).map(debugVar)}]};
  } else {
    try { d = await api(`/vars?profile=${profile}&sort=${sort}&scope=${lee.execScope}`); }
    catch (e) { box.innerHTML = `<div class="lee-err">${esc(e.message)}</div>`; return; }
    if (d.error) {
      // An install runs for minutes and the panel polls every 2.5 seconds; repainting would throw
      // away the disabled button and the progress line every poll.
      if (lee.varsInstalling) return;
      const pkgs = (d.packages || []).join(' and ');
      box.innerHTML = `<div class="lee-err"><strong>Dhrishti inspector unavailable</strong><span>${esc(d.error)}</span>` +
        (d.can_install ? `<button class="lee-btn go" data-install-inspector>Install ${esc(pkgs)} into this environment</button>` : '') +
        `<button class="lee-btn" data-repair-inspector>Restart kernel and repair</button></div>`;
      $('[data-repair-inspector]', box).onclick = async () => {
        if (!await confirmDialog('Restart kernel', 'Repairing the inspector restarts this kernel and clears its live variables.', 'restart and repair')) return;
        await post('/kernel/restart'); markPreviousRuns(); await leeVars(); refreshKernelPill();
      };
      const install = $('[data-install-inspector]', box);
      if (install) install.onclick = async () => {
        if (!await confirmDialog('Install into this environment',
            `Leela will install ${pkgs} into ${d.python}, then restart this kernel, which clears its live variables.`,
            'install and restart')) return;
        install.disabled = true; lee.varsInstalling = true;
        status(`installing ${pkgs} into ${d.python.split('/').slice(-3).join('/')}…`);
        try {
          await post('/runtime/inspector', {python: d.python});
          await post('/kernel/restart'); markPreviousRuns();
          status('inspector ready · live variables connected', 'ok');
        } catch (e) { status(String(e.message || e), 'err'); }
        finally { lee.varsInstalling = false; install.disabled = false; }
        await leeVars(); refreshKernelPill();
      };
      return;
    }
    if (d.python) paintEnv(String(d.python).split('/').slice(-3).join('/'));
    const envTag = $('#envtag');
    if (envTag && d.inspector) envTag.title = `${d.inspector} inspector · ${d.python || d.runtime}${d.cwd ? ' · cwd ' + d.cwd : ''}`;
  }

  // Every runtime gets its own view memory, so switching notebooks does not leak open rows and
  // the filter between them.
  const runtime = d.runtime || 'default';
  if (lee.varRuntime !== runtime) {
    if (lee.varRuntime) lee.varStates.set(lee.varRuntime, {
      open: new Set(lee.varOpen), prev: lee.varPrev, seen: lee.varSeen,
      scroll: box.scrollTop, filter: $('#varfilter')?.value || '', selected: selVar()?.dataset.name || '',
    });
    const saved = lee.varStates.get(runtime) || {};
    lee.varRuntime = runtime; lee.varOpen = new Set(saved.open || []);
    lee.varPrev = saved.prev || {}; lee.varSeen = !!saved.seen;
    if ($('#varfilter')) $('#varfilter').value = saved.filter || '';
    lee.varRestore = {scroll: saved.scroll || 0, selected: saved.selected || ''};
  }

  // Most polls are identical, and rebuilding the whole variable DOM every 2.5 seconds competes
  // with CodeMirror selection and streamed Markdown painting.
  const fingerprint = JSON.stringify(d.groups || []);
  if (!lee.varRestore && lee.varFingerprints.get(runtime) === fingerprint) return;
  lee.varFingerprints.set(runtime, fingerprint);

  // A changed poll must not cost the user their place: remember what is open, what is selected
  // and where the panel is scrolled, re-render, then put all three back.
  const scroll = lee.varRestore ? lee.varRestore.scroll : box.scrollTop;
  const selName = lee.varRestore ? lee.varRestore.selected : selVar()?.dataset.name;
  lee.varRestore = null;
  const cur = {};
  const html = (d.groups || []).map(g => {
    const rows = (g.nodes || []).map(n => { cur[n.name] = n.value; return varRow(n); }).join('');
    return g.label ? `<div class="lee-vgroup">${esc(g.label)}</div>${rows}` : rows;
  }).join('');
  box.innerHTML = html || '<div class="lee-dim">(no variables yet)</div>';
  lee.varPrev = cur; lee.varSeen = true;
  await Promise.all([...lee.varOpen].map(acc => fillKids(acc)));
  if (selName) $$(`#vars .lee-vrow`).find(r => r.dataset.name === selName)?.classList.add('sel');
  box.scrollTop = scroll;
  leeFilterVars();
}

function debugVar(v) {
  const ref = Number(v.variablesReference) || 0;
  return {name: v.name || '?', type: v.type || '', value: v.value || '', shape: null,
          accessor: ['debug', ref], is_container: ref > 0, is_grid: false, debug_reference: ref};
}

function varRow(n, depth = 0) {
  // new/edited is a statement about the namespace, so it is for top-level names only. Tagging a
  // DataFrame's own `shape` as "(new)" is noise, as is the first render, where everything is new.
  const tag = (depth || !lee.varSeen) ? ''
            : (!(n.name in lee.varPrev)) ? '<span class="lee-vnew"> (new)</span>'
            : (lee.varPrev[n.name] !== n.value ? '<span class="lee-vedit"> (edited)</span>' : '');
  const typ = n.shape ? `${n.type}: ${n.shape}` : n.type;
  const acc = encodeURIComponent(JSON.stringify(n.accessor));
  return `<div class="lee-vrow" data-name="${esc(n.name)}" data-acc="${acc}" data-container="${n.is_container ? 1 : 0}"
            data-grid="${n.is_grid ? 1 : 0}" onclick="leeVarClick(this)">` +
    `<span class="lee-vname">${esc(n.name)}</span> <span class="lee-vtype">{${esc(typ)}}</span> ` +
    `<span class="lee-vval">${esc(n.value)}</span>${n.is_grid ?
      ' <button class="lee-vgrid" title="open grid" onclick="event.stopPropagation(); selectVar(this.closest(\'.lee-vrow\')); openGrid()">▦</button>' : ''}${tag}</div>` +
    `<div class="lee-vkids" id="k-${acc}"></div>`;
}

async function fillKids(acc) {
  const box = document.getElementById('k-' + acc);
  if (!box) { lee.varOpen.delete(acc); return; }   // the variable is gone; stop tracking it
  try {
    const accessor = JSON.parse(decodeURIComponent(acc));
    const kids = accessor[0] === 'debug'
      ? (await api(`/nb/debug/variables?reference=${Number(accessor[1])}`)).variables.map(debugVar)
      : await api(`/vars/expand?accessor=${acc}&scope=${lee.execScope}`);
    box.innerHTML = kids.map(k => varRow(k, 1)).join('');
  } catch (e) { lee.varOpen.delete(acc); box.innerHTML = `<div class="lee-err">${esc(e.message)}</div>`; }
}

function selectVar(el) {
  $$('.lee-vrow').forEach(r => r.classList.remove('sel'));
  el?.classList.add('sel');
}
window.selectVar = selectVar;

async function leeVarClick(el) {
  selectVar(el);
  if (el.dataset.container !== '1') return;
  const acc = el.dataset.acc;
  const box = document.getElementById('k-' + acc);
  if (!box) return;
  if (lee.varOpen.has(acc)) { lee.varOpen.delete(acc); box.innerHTML = ''; return; }
  lee.varOpen.add(acc);
  await fillKids(acc);
}
window.leeVarClick = leeVarClick;

function leeFilterVars() {
  const raw = $('#varfilter')?.value || '', q = raw.toLowerCase();
  const expression = raw.trimStart().startsWith('=');
  $$('#vars .lee-vrow').forEach(r => {
    r.style.display = (expression || !q || (r.dataset.name || '').toLowerCase().includes(q)) ? '' : 'none';
  });
  $('#varfilter')?.classList.toggle('expression', expression);
}
async function leeEvalVarFilter(event) {
  if (event.key !== 'Enter') return;
  const input = event.currentTarget, raw = input.value.trim();
  if (!raw.startsWith('=')) return;
  event.preventDefault(); event.stopPropagation();
  const code = raw.slice(1).trim(); if (!code) return status('enter Python after =', 'err');
  input.disabled = true; status('evaluating variable expression…');
  try {
    const r = await post('/vars/eval', {code, scope: lee.execScope});
    if (!r.ok) return status(r.error || 'expression failed', 'err');
    if (r.stdout) status(r.stdout.trim(), 'info');
    if (!r.result) return status('expression returned no value', 'info');
    openValueLens(r.result, input, code); status('expression ready', 'ok');
  } catch (e) { status(e.message || String(e), 'err'); }
  finally { input.disabled = false; input.focus(); }
}
window.leeFilterVars = leeFilterVars; window.leeEvalVarFilter = leeEvalVarFilter;

function setProfile(p) { const s = $('#varprofile'); if (s) { s.value = p; leeVars(); } }
const selVar = () => $('.lee-vrow.sel');

async function editSelectedVar() {
  const r = selVar(); if (!r) return status('select a variable first');
  const expr = await inputDialog('set variable', `${r.dataset.name} =`, '', 'Python expression');
  if (expr == null) return;
  const res = await post('/vars/set', {accessor: decodeURIComponent(r.dataset.acc), expr});
  res.ok ? (status('set ' + r.dataset.name, 'ok'), leeVars()) : status(res.error, 'err');
}

async function openGrid() {
  const row = selVar();
  if (!row) return status('select a variable first', 'err');
  if (row.dataset.grid !== '1') return status(row.dataset.name + ' is not a table or array', 'err');
  let roff = 0, coff = 0, page = null;
  const m = modal(`<div class="lee-mhead">${esc(row.dataset.name)}<span class="sub">grid view</span></div>
    <div class="lee-gridwrap" id="gridbody"></div>
    <div class="lee-mfoot"><button class="lee-btn" id="gprevrow">↑ rows</button>
    <button class="lee-btn" id="gnextrow">↓ rows</button><button class="lee-btn" id="gprevcol">← columns</button>
    <button class="lee-btn" id="gnextcol">→ columns</button><span class="lee-dim" id="gridpos"></span></div>`);
  const draw = async () => {
    page = await api(`/vars/grid?accessor=${row.dataset.acc}&roff=${roff}&coff=${coff}&scope=${lee.execScope}`);
    if (!page) { m.remove(); return status('that value cannot be shown as a grid', 'err'); }
    const heads = page.headers.map(h => `<th>${esc(h)}</th>`).join('');
    const rows = page.cells.map((cells, i) => `<tr><th>${esc(page.index[i])}</th>` +
      cells.map(c => `<td>${esc(c)}</td>`).join('') + '</tr>').join('');
    m.querySelector('#gridbody').innerHTML = `<table class="lee-grid"><thead><tr><th></th>${heads}</tr></thead><tbody>${rows}</tbody></table>`;
    m.querySelector('#gridpos').textContent = `rows ${page.roff + 1}–${Math.min(page.roff + page.rows, page.nrows)} of ${page.nrows} · columns ${page.coff + 1}–${Math.min(page.coff + page.cols, page.ncols)} of ${page.ncols}`;
  };
  m.querySelector('#gprevrow').onclick = () => { roff = Math.max(0, roff - (page?.rows || 50)); draw(); };
  m.querySelector('#gnextrow').onclick = () => { roff = Math.min(Math.max(0, (page?.nrows || 1) - 1), roff + (page?.rows || 50)); draw(); };
  m.querySelector('#gprevcol').onclick = () => { coff = Math.max(0, coff - (page?.cols || 50)); draw(); };
  m.querySelector('#gnextcol').onclick = () => { coff = Math.min(Math.max(0, (page?.ncols || 1) - 1), coff + (page?.cols || 50)); draw(); };
  try { await draw(); } catch (e) { m.remove(); status(String(e.message || e), 'err'); }
}
async function liveHas(name) {
  try {
    const d = await api('/vars?profile=minimal&sort=name&scope=live');
    return (d.groups || []).some(g => (g.nodes || []).some(n => n.name === name));
  } catch (e) { return false; }
}

/* Promoting over a live name cannot be undone, so the refusal is the server's own sentence and the
 * replace is a second, deliberate answer to it. Only the pane can send one: the agent's tool is
 * refused outright. */
async function promoteVar(replace) {
  const r = selVar(); if (!r) return status('select a variable first');
  let res;
  try { res = await api('/vars/promote?accessor=' + r.dataset.acc + (replace ? '&replace=1' : '')); }
  catch (e) {
    const refusal = String(e.message || e);
    if (replace || !await liveHas(r.dataset.name)) return status(refusal, 'err');
    if (!await confirmDialog('replace a live variable', refusal, 'replace it')) return status(refusal, 'err');
    return promoteVar(true);
  }
  res.ok ? (status('promoted ' + r.dataset.name, 'ok'), leeVars()) : status(res.error, 'err');
}
function copyVar(what) {
  const r = selVar(); if (!r) return status('select a variable first');
  const txt = what === 'path' ? decodeURIComponent(r.dataset.acc) : r.querySelector('.lee-vval').textContent;
  navigator.clipboard?.writeText(txt);
  status('copied ' + what, 'ok');
}

