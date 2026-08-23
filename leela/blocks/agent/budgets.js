/* How much work one turn may do. `auto` lets ramabana size it from the prompt; a number pins it.
   The fields are written back from the answer, so a refusal leaves the box showing what is
   actually in force rather than the rejected text. */
/* The highlighted range, queued as context for the next turn. Sent as text rather than as
   `path:from-to` for the agent to read, because the buffer may be unsaved and what you highlighted
   is what you meant. */
function leeAgentSelection() {
  const v = curEditor();
  if (!v) return status('put the cursor in some code first', 'err');
  const sel = v.state.selection.main;
  if (sel.empty) return status('select the code you want the agent to see', 'err');
  const doc = v.state.doc, from = doc.lineAt(sel.from).number, to = doc.lineAt(sel.to).number;
  const path = lee.path || 'untitled', name = path.split('/').pop() || 'untitled';
  lee.agentSelections.push({
    label: `${name}:${from}${to > from ? '–' + to : ''}`,
    path,
    ref: {kind: 'selection', path, from, to, text: doc.sliceString(sel.from, sel.to)},
  });
  leePane('right', true); leeRight('agent'); paintAgentAttachments();
  $('#agentprompt')?.focus();
  status(`selection queued for the agent · ${from}${to > from ? '–' + to : ''}`, 'ok');
}
window.leeAgentSelection = leeAgentSelection;

async function leeAgentBudget() {
  const tools = $('#toolbudget'), steps = $('#stepbudget');
  try {
    const d = await post('/agent/budget', {tools: tools?.value.trim(), steps: steps?.value.trim()});
    if (tools) tools.value = String(d.tools);
    if (steps) steps.value = String(d.steps);
    const quick = $('#agenttoolbudget'); if (quick) quick.value = String(d.tools);
    status(d.note, 'ok');
  } catch (e) {
    status(e.message || String(e), 'err');
    try { const d = await api('/agent/budget/state');
      if (tools) tools.value = String(d.tools); if (steps) steps.value = String(d.steps);
      const quick = $('#agenttoolbudget'); if (quick) quick.value = String(d.tools);
    } catch (_) { /* leave the boxes alone rather than blank them on a second failure */ }
  }
}
window.leeAgentBudget = leeAgentBudget;

async function leeAgentQuickBudget() {
  const quick = $('#agenttoolbudget'), tools = $('#toolbudget');
  if (tools) tools.value = quick?.value || 'auto';
  await leeAgentBudget();
}
window.leeAgentQuickBudget = leeAgentQuickBudget;

async function refreshAgentBudget() {
  const el = $('#agentbudgetstatus'); if (!el) return;
  try {
    const d = await api('/agent/status');
    el.textContent = `${d.tool_calls || 0} / ${d.tool_limit || '—'}`;
    el.title = `${d.tool_calls || 0} of ${d.tool_limit || 'unknown'} tool calls used this turn`;
  } catch (_) {}
}

async function leeLocalMultimodal(enabled) {
  const box = $('#localmultimodal');
  const d = await post('/agent/settings', {local_multimodal: !!enabled});
  if (!d.ok && box) box.checked = !enabled;
  status(d.ok ? d.note : (d.error || 'local multimodal setting failed'), d.ok ? 'ok' : 'err');
}
window.leeLocalMultimodal = leeLocalMultimodal;

async function leeWorkspaceRepoWrites(enabled) {
  const box = $('#workspace-repo-writes');
  try {
    const d = await post('/agent/workspace-repo-writes', {enabled: !!enabled});
    if (!d.ok && box) box.checked = !enabled;
    status(d.ok ? d.note : (d.error || 'workspace repository write setting failed'), d.ok ? 'ok' : 'err');
  } catch (e) {
    if (box) box.checked = !enabled;
    status(String(e.message || e), 'err');
  }
}
window.leeWorkspaceRepoWrites = leeWorkspaceRepoWrites;

async function leeAgentReadOutside(enabled) {
  const box = $('#agent-read-outside');
  try {
    const d = await post('/agent/read-outside', {enabled: !!enabled});
    if (!d.ok && box) box.checked = !enabled;
    status(d.ok ? d.note : (d.error || 'read-outside setting failed'), d.ok ? 'ok' : 'err');
  } catch (e) {
    if (box) box.checked = !enabled;
    status(String(e.message || e), 'err');
  }
}
window.leeAgentReadOutside = leeAgentReadOutside;

async function leeSubagentWrites(enabled) {
  const box = $('#subagent-writes');
  try {
    const d = await post('/agent/subagent-writes', {enabled: !!enabled});
    if (!d.ok && box) box.checked = !enabled;
    status(d.ok ? d.note : (d.error || 'sub-agent write setting failed'), d.ok ? 'ok' : 'err');
  } catch (e) {
    if (box) box.checked = !enabled;
    status(String(e.message || e), 'err');
  }
}
window.leeSubagentWrites = leeSubagentWrites;

function leeAgentExpand() { leeRight('agent'); leeExpandPane('right'); }
window.leeAgentExpand = leeAgentExpand;

function leeRight(which) {
  const right = $('#right'); if (!right) return;
  try { localStorage.setItem('lee-right-view', which); } catch (_) {}
  right.classList.toggle('right-agent', which === 'agent');
  right.classList.toggle('right-vars', which === 'vars');
  right.classList.toggle('right-memory', which === 'memory');
  $$('.lee-righttab', right).forEach(b => {
    const active = b.dataset.right === which;
    b.classList.toggle('active', active); b.setAttribute('aria-selected', String(active));
  });
  if (which === 'agent') requestAnimationFrame(() => { const log = $('#agentlog'); if (log) log.scrollTop = log.scrollHeight; });
  if (which === 'memory' && !lee.memoryLoaded) leeMemoryNotes();
}
window.leeRight = leeRight;

// Every memory view is fetched asynchronously into one `#memorybody`, so a slow answer must not
// paint over the view you switched to. Each switch takes the next token, and a fetch that finds the
// token moved drops its result.
let memoryViewSeq = 0;
