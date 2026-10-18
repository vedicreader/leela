function palette() {
  const agentCommands = [
    {name: 'Agent: autopilot mode', scope: 'agent', run: () => leeAgentControl('autopilot')},
    {name: 'Agent: guided mode', scope: 'agent', run: () => leeAgentControl('guided')},
    {name: 'Agent: directed mode', scope: 'agent', run: () => leeAgentControl('directed')},
    {name: 'Agent: pause after current call', scope: 'agent', run: pauseAgentAfterCurrent},
    {name: 'Agent: run until next write', scope: 'agent', run: () => post('/agent/run-policy', {policy: 'until_write'})},
    {name: 'Agent: run read-only calls', scope: 'agent', run: () => post('/agent/run-policy', {policy: 'reads'})},
    {name: 'Agent: edit starting state', scope: 'agent', run: leeAgentState},
    {name: 'Agent: steer after current call', scope: 'agent', run: () => $('#agentprompt')?.focus()},
    {name: 'Agent: sub-agents', scope: 'agent', run: () => leeSubagents()},
    {name: 'Agent: conversation branches', scope: 'agent', run: () => leeAgentBranches()},
    {name: 'Agent: shape what the model remembers', scope: 'agent', run: () => leeAgentShape()},
    {name: 'Inline completions: what was asked and taken', scope: 'global', run: () => showCompletions()},
  ];
  const cmds = lee.keys.filter(k => k.label).map(k => ({name: k.label, scope: k.scope, action: k.action, key: k.key})).concat(agentCommands);
  let hits = cmds, sel = 0, seq = 0, timer = null;
  const m = modal(`<input class="lee-input" id="cp" placeholder="command or file…" autofocus>
                   <div class="lee-modallist" id="cplist"></div>`,
    (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, hits.length - 1); paint(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); paint(); }
      else if (e.key === 'Enter') { e.preventDefault(); go(); }
    }, () => clearTimeout(timer));
  const list = m.querySelector('#cplist'), input = m.querySelector('#cp');
  const paint = () => {
    list.innerHTML = hits.slice(0, 200).map((h, i) =>
      `<div class="lee-mrow${i === sel ? ' sel' : ''}" data-i="${i}">${esc(h.name)}<span class="sub">${h.path ? 'file · ' + esc(h.path) : esc(h.scope) + ' · ' + esc(displayChord(h.key))}</span></div>`).join('');
    list.querySelector('.sel')?.scrollIntoView({block: 'nearest'});
  };
  const go = () => {
    const h = hits[sel]; if (!h) return;
    m.remove();
    if (h.path) leeOpenFile(h.path); else h.run ? h.run() : leeAct(h.action);
  };
  list.addEventListener('click', e => { const r = e.target.closest('.lee-mrow'); if (r) { sel = +r.dataset.i; go(); } });
  // Files arrive after the commands, so a late answer for an older query must not paint.
  input.addEventListener('input', () => {
    const q = input.value.toLowerCase(), mine = ++seq;
    hits = cmds.filter(c => c.name.toLowerCase().includes(q) || (c.action || '').includes(q)); sel = 0; paint();
    clearTimeout(timer);
    if (!q.trim()) return;
    timer = setTimeout(async () => {
      let files;
      try { files = (await api('/fs/find?limit=20&q=' + encodeURIComponent(q.trim()))).hits; } catch { return; }
      if (mine !== seq || !m.isConnected) return;
      hits = hits.concat(files.map(f => ({name: f.name, path: f.path}))); paint();
    }, 120);
  });
  paint(); setTimeout(() => input.focus(), 0);
}

