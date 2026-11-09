function palette() {
  const picked = String(getSelection?.() ?? '').trim();
  const lessonCommands = [{name: "Lesson: I don't get…", scope: 'editor', run: () => lessonGuideSelected(picked)}];
  const agentCommands = [
    {name: 'Learn mode', scope: 'agent', run: () => leeAgentLearnToggle()},
    {name: 'Agent: autopilot mode', scope: 'agent', run: () => leeAgentControl('autopilot')},
    {name: 'Agent: guided mode', scope: 'agent', run: () => leeAgentControl('guided')},
    {name: 'Agent: directed mode', scope: 'agent', run: () => leeAgentControl('directed')},
    {name: 'Agent: pause after current call', scope: 'agent', run: pauseAgentAfterCurrent},
    {name: 'Agent: run until next write', scope: 'agent', run: () => post('/agent/run-policy', {policy: 'until_write'})},
    {name: 'Agent: run read-only calls', scope: 'agent', run: () => post('/agent/run-policy', {policy: 'reads'})},
    {name: 'Agent: edit starting state', scope: 'agent', run: leeAgentState},
    {name: 'Agent: steer after current call', scope: 'agent', run: () => $('#agentprompt')?.focus()},
    {name: 'Agent: sub-agents', scope: 'agent', run: () => leeSubagents()},
    {name: 'Agent: sub-agent model', scope: 'agent', run: () => leeOpenSetting('#jobmodels [data-job="subagent"]')},
    {name: 'Agent: sub-agent effort', scope: 'agent', run: () => leeOpenSetting('#subeffort')},
    {name: 'Agent: sub-agent tool calls native or text', scope: 'agent', run: () => leeOpenSetting('#subtools')},
    {name: 'Agent: tool calls native or text', scope: 'agent', run: () => leeOpenSetting('#toolmode')},
    {name: 'Agent: conversation branches', scope: 'agent', run: () => leeAgentBranches()},
    {name: 'Agent: shape what the model remembers', scope: 'agent', run: () => leeAgentShape()},
    {name: 'Inline completions: what was asked and taken', scope: 'global', run: () => showCompletions()},
  ];
  const cmds = lee.keys.filter(k => k.label).map(k => ({name: k.label, scope: k.scope, action: k.action, key: shownChord(k)})).concat(agentCommands, lessonCommands);
  let hits = cmds, sel = 0;
  const m = modal(`<input class="lee-input" id="cp" placeholder="command…" aria-label="Command palette" role="combobox" aria-controls="cplist" aria-expanded="true" autofocus>
                   <div class="lee-modallist" id="cplist" role="listbox" aria-label="Commands"></div>`,
    (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, hits.length - 1); paint(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); paint(); }
      else if (e.key === 'Enter') { e.preventDefault(); go(); }
    });
  const list = m.querySelector('#cplist'), input = m.querySelector('#cp');
  const paint = () => {
    list.innerHTML = hits.slice(0, 200).map((h, i) =>
      `<div class="lee-mrow${i === sel ? ' sel' : ''}" data-i="${i}">${esc(sentence(h.name))}${h.scope && h.scope !== 'global' ? `<span class="sub">${esc(h.scope)}</span>` : ''}` +
      `${h.key ? `<kbd>${esc(displayChord(h.key))}</kbd>` : ''}</div>`).join('');
    list.querySelector('.sel')?.scrollIntoView({block: 'nearest'});
  };
  const go = () => {
    const h = hits[sel]; if (!h) return;
    m.remove();
    h.run ? h.run() : leeAct(h.action);
  };
  list.addEventListener('click', e => { const r = e.target.closest('.lee-mrow'); if (r) { sel = +r.dataset.i; go(); } });
  // Files are ⌘P's: one row hands the query over rather than twenty crowding the commands.
  input.addEventListener('input', () => {
    const q = input.value.toLowerCase(), raw = input.value.trim();
    hits = cmds.filter(c => c.name.toLowerCase().includes(q) || (c.action || '').includes(q));
    if (raw) hits = hits.concat({name: `Go to file matching “${raw}”…`, scope: 'files', key: shownChord(lee.keys.find(k => k.action === 'quick_open')),
                                 run: () => quickOpen(false, raw)});
    sel = 0; paint();
  });
  paint(); setTimeout(() => input.focus(), 0);
}

