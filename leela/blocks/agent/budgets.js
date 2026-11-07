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

async function paintAgentBudget() {
  const el = $('#agentbudgetstatus'); if (!el) return;
  try {
    const d = await api('/agent/status');
    el.textContent = `${d.tool_calls || 0} / ${d.tool_limit || '–'}`;
    el.title = `${d.tool_calls || 0} of ${d.tool_limit || 'unknown'} tool calls used this turn`;
  } catch (_) {}
}
/* This used to be called straight from the stream's `activity` handler, so a turn making a hundred
   tool calls asked the server a hundred times for a counter that reads "12 / 40". Leading edge, so
   the first call of a turn still paints at once; trailing, so the number on screen is the last one. */
const BUDGET_GAP = 1000;
let budgetTimer = 0, budgetAt = -Infinity;
function refreshAgentBudget() {
  const wait = BUDGET_GAP - (performance.now() - budgetAt);
  if (wait <= 0) { budgetAt = performance.now(); return paintAgentBudget(); }
  clearTimeout(budgetTimer);
  budgetTimer = setTimeout(() => { budgetAt = performance.now(); paintAgentBudget(); }, wait);
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

/* Three-valued, so the control is a select and the recovery is putting the old value back rather
   than flipping a box. The policy is the workspace's: the model is never asked to respect it. */
/* Workspace default for the per-chat opt-ins: which groups a new conversation gets unless its
   own toggles say otherwise. The pane's buttons are painted from it on the next load. */
async function leeAgentOptin(name, on) {
  const box = $(`#agent-optin-${name}`);
  const names = ['research', 'exhash'].filter(n => n === name ? on : $(`#agent-optin-${n}`)?.checked);
  try {
    const d = await post('/agent/optin', {optin: names});
    if (!d.ok && box) box.checked = !on;
    status(d.ok ? d.note : (d.error || 'opt-in setting failed'), d.ok ? 'ok' : 'err');
  } catch (e) { if (box) box.checked = !on; status(String(e.message || e), 'err'); }
}
window.leeAgentOptin = leeAgentOptin;
/* Workspace default for how a new conversation is briefed; the select goes back on a refusal. */
async function leeAgentProfile(profile) {
  const sel = $('#agent-profile');
  try {
    const d = await post('/agent/profile', {profile});
    if (d.ok && sel) sel.dataset.was = profile; else if (sel) sel.value = sel.dataset.was || 'auto';
    status(d.ok ? d.note : (d.error || 'profile setting failed'), d.ok ? 'ok' : 'err');
  } catch (e) { if (sel) sel.value = sel.dataset.was || 'auto'; status(String(e.message || e), 'err'); }
}
window.leeAgentProfile = leeAgentProfile;
async function leeVaultPii(policy) {
  const sel = $('#vault-pii'), was = sel ? sel.dataset.was || 'redact' : 'redact';
  try {
    const d = await post('/agent/vault-pii', {pii: policy});
    if (!d.ok && sel) sel.value = was; else if (sel) sel.dataset.was = policy;
    status(d.ok ? d.note : (d.error || 'vault privacy setting failed'), d.ok ? 'ok' : 'err');
  } catch (e) {
    if (sel) sel.value = was;
    status(String(e.message || e), 'err');
  }
}
window.leeVaultPii = leeVaultPii;

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

/* The sub-agent model, effort and tool channel come back as one dict from every route that sets
   them, a refusal included (`ok: false`, the setup message in `error`), so one painter serves all. */
function paintSubagentSettings(d) {
  if (!d) return;
  const effort = $('#subeffort'), tools = $('#subtools'), model = $('#jobmodels [data-job="subagent"]');
  if (effort) effort.value = d.effort || 'default';
  if (tools && d.tools) tools.value = d.tools;
  if (model && [...model.options].some(o => o.value === d.model)) { model.value = d.model; window.leeModelPickers?.(); }
}
async function leeSubagentSettings(change) {
  let d;
  try { d = await post('/agent/subagent-settings', change || {}); }
  catch (e) { d = {ok: false, error: String(e.message || e)}; }
  status(d.ok ? (d.note || '').split('\n')[0] || 'sub-agent settings saved' : (d.error || 'sub-agent setting failed'), d.ok ? 'ok' : 'err');
  // a refusal still carries what is in force; only a failed request does not
  paintSubagentSettings('effort' in d ? d : await api('/agent/subagent-settings').catch(() => null));
  return d;
}
async function leeToolMode(tools) {
  let d;
  try { d = await post('/agent/tool-mode', {tools}); } catch (e) { d = {ok: false, error: String(e.message || e)}; }
  status(d.ok ? (d.note || `tool calls ${d.tools}`) : (d.error || 'tool mode failed'), d.ok ? 'ok' : 'err');
  if (!d.ok) d = await api('/agent/tool-mode').catch(() => null);
  if (d && $('#toolmode')) $('#toolmode').value = d.tools;
}
async function loadAgentSettings() {
  paintSubagentSettings(await api('/agent/subagent-settings').catch(() => null));
  const t = await api('/agent/tool-mode').catch(() => null);
  if (t && $('#toolmode')) $('#toolmode').value = t.tools;
}
/* The palette's way to a setting: the agent pane, its settings open, the control focused. */
function leeOpenSetting(sel) {
  leePane('right', true); leeRight('agent'); setScope('agent');
  const d = $('details.lee-agent-settings'); if (d) d.open = true;
  const el = $(sel); if (!el) return;
  (el.hidden && el.previousElementSibling?.dataset.modelPick !== undefined ? el.previousElementSibling : el).focus();
}
window.leeSubagentSettings = leeSubagentSettings;
window.leeToolMode = leeToolMode;
window.leeLoadAgentSettings = loadAgentSettings;
window.leePaintSubagentSettings = paintSubagentSettings;
window.leeOpenSetting = leeOpenSetting;

/* Learning is ramabana's, in the agent's config folder: `/learned on|off` and the Review tab say the same thing. */
async function leeAgentLearning(enabled) {
  const box = $('#agent-learning');
  try {
    const d = await post('/agent/learning', {enabled: !!enabled});
    if (box) box.checked = d.ok ? !!d.enabled : !enabled;
    status(d.ok ? d.note : (d.error || 'learning setting failed'), d.ok ? 'ok' : 'err');
  } catch (e) {
    if (box) box.checked = !enabled;
    status(String(e.message || e), 'err');
  }
}
window.leeAgentLearning = leeAgentLearning;
function leeLearningShown(on) { const box = $('#agent-learning'); if (box && typeof on === 'boolean') box.checked = on; }
window.leeLearningShown = leeLearningShown;

function leeAgentExpand() { leeRight('agent'); leeExpandPane('right'); }
window.leeAgentExpand = leeAgentExpand;

function leeRight(which) {
  const right = $('#right'); if (!right) return;
  try { localStorage.setItem('lee-right-view', which); } catch (_) {}
  right.classList.toggle('right-agent', which === 'agent');
  right.classList.toggle('right-vars', which === 'vars');
  right.classList.toggle('right-memory', which === 'memory');
  right.classList.toggle('right-learn', which === 'learn');
  $$('.lee-righttab', right).forEach(b => {
    const active = b.dataset.right === which;
    b.classList.toggle('active', active); b.setAttribute('aria-selected', String(active));
  });
  if (which === 'agent') requestAnimationFrame(() => stickAgentLog());
  if (which === 'memory' && !lee.memoryLoaded) leeMemoryNotes();
  if (which === 'learn') paintLessonReview();
}
window.leeRight = leeRight;

// Every memory view is fetched asynchronously into one `#memorybody`, so a slow answer must not
// paint over the view you switched to. Each switch takes the next token, and a fetch that finds the
// token moved drops its result.
let memoryViewSeq = 0;
