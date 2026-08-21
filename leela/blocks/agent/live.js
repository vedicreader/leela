function rememberAgentLive() {
  if (!lee.agentView || lee.agentView === 'live') lee.agentLive = $('#agentlog')?.innerHTML || '';
}
function restoreAgentLive() {
  const log = $('#agentlog'); if (!log) return;
  log.innerHTML = lee.agentLive || ''; lee.agentView = 'live';
  $('#agenthistory')?.classList.remove('active');
  log.scrollTop = log.scrollHeight;
}
function userMessage(text) {
  const raw = String(text || '').trim(), long = raw.length > 900 || raw.split('\n').length > 14;
  const card = document.createElement('section'); card.className = 'lee-user-message';
  const head = document.createElement('header');
  head.innerHTML = '<strong>You</strong><span>request</span>'; card.appendChild(head);
  if (!long) {
    const body = document.createElement('div'); body.className = 'lee-user-message-body';
    body.textContent = raw; card.appendChild(body); return card;
  }
  const lines = raw.split('\n');
  const preview = lines.slice(0, 6).join('\n').slice(0, 620).trimEnd();
  const body = document.createElement('div'); body.className = 'lee-user-message-body preview';
  body.textContent = preview + (preview.length < raw.length ? '\n…' : ''); card.appendChild(body);
  const more = document.createElement('details'); more.className = 'lee-user-message-more';
  more.innerHTML = `<summary>Show full request <span>${raw.length.toLocaleString()} characters · ${lines.length} lines</span>` +
    `<i class="lee-agent-step-chevron" aria-hidden="true"></i></summary><pre></pre>`;
  more.querySelector('pre').textContent = raw; card.appendChild(more);
  return card;
}
function usageMeta(usage, label = '', model = '') {
  if (!usage && !label) return null;
  const u = usage || {}, parts = [];
  if (Number(u.total)) parts.push(`${Number(u.total).toLocaleString()} tokens`);
  if (Number(u.input)) parts.push(`${Number(u.input).toLocaleString()} input`);
  if (Number(u.output)) parts.push(`${Number(u.output).toLocaleString()} output`);
  if (Number(u.cached)) parts.push(`${Number(u.cached).toLocaleString()} cached`);
  if (Number(u.reasoning)) parts.push(`${Number(u.reasoning).toLocaleString()} reasoning`);
  if (Number(u.cost)) parts.push(`$${Number(u.cost).toFixed(4)}`);
  if (!parts.length && label) parts.push(label);
  if (model || u.model) parts.push(String(model || u.model).split('/').pop());
  const el = document.createElement('footer'); el.className = 'lee-turn-usage';
  el.setAttribute('aria-label', 'Token usage and estimated cost for this turn');
  el.innerHTML = `<span class="lee-turn-usage-mark" aria-hidden="true">∑</span>` + parts.map((part, i) => `<span${i === parts.length - 1 ? ' class="model"' : ''}>${esc(part)}</span>`).join('');
  return el;
}

function renderTurns(log, turns, heading) {
  if (heading) log.insertAdjacentHTML('beforeend', `<div class="lee-vgroup">${esc(heading)}</div>`);
  for (const turn of (turns || [])) {
    const item = document.createElement('article'); item.className = 'lee-history-turn';
    item.innerHTML = `<div class="lee-history-meta"><span>${esc(turn.model)}</span>` +
      `<span>${esc(turn.plan?.route || 'direct')}</span></div>`;
    item.appendChild(userMessage(turn.prompt));
    if ((turn.activity || []).length) {
      const steps = document.createElement('div'); steps.className = 'lee-agent-steps';
      for (const activity of turn.activity) {
        const row = document.createElement('details'); renderAgentStep(row, activity); steps.appendChild(row);
      }
      item.appendChild(steps);
    }
    const reply = document.createElement('div'); reply.className = 'lee-reply'; item.appendChild(reply);
    renderMarkdown(reply, turn.reply || '');
    const usage = usageMeta(turn.usage, turn.usage_label, turn.model); if (usage) item.appendChild(usage);
    log.appendChild(item);
  }
}
const sessionTime = s => s.started ? new Date(s.started * 1000).toLocaleString() : s.id.replace(/^agent_/, '');
async function showHistorySession(group, groups) {
  const log = $('#agentlog'); if (!log) return; log.innerHTML = ''; approvalCards.clear();
  const index = document.createElement('nav'); index.className = 'lee-history-index';
  const options = (groups || []).map(s => {
    const models = (s.models || []).map(m => m.split('/').pop()).join(' + ') || 'execution';
    const label = `${sessionTime(s)} · ${models} · ${s.turns.length} turn${s.turns.length === 1 ? '' : 's'}`;
    return `<option value="${esc(s.id)}"${s.id === group?.id ? ' selected' : ''}>${esc(label)}</option>`;
  }).join('');
  const resumable = !!group && !group.id.startsWith('legacy-') && (group.turns || []).length > 0;
  index.innerHTML = `<div class="lee-history-heading"><strong>History</strong>` +
    `<span>one continuous model context per session</span></div>` +
    `<select class="lee-select lee-history-select" aria-label="agent history session">${options}</select>` +
    `<span class="lee-history-runs">${group?.code || 0} kernel run${group?.code === 1 ? '' : 's'}</span>` +
    (resumable ? `<button class="lee-btn go lee-history-resume" title="Continue this conversation">Resume</button>` : '');
  index.querySelector('select')?.addEventListener('change', e =>
    showHistorySession(groups.find(s => s.id === e.target.value), groups));
  index.querySelector('.lee-history-resume')?.addEventListener('click', () => leeAgentResume(group));
  log.appendChild(index);
  if (!group) { log.insertAdjacentHTML('beforeend', '<div class="lee-dim">(no sessions yet)</div>'); return; }
  log.insertAdjacentHTML('beforeend', `<div class="lee-history-session-head"><strong>${esc(sessionTime(group))}</strong>` +
    `<span>${group.context_continues ? 'context continued across these turns' : 'separate context'}</span></div>`);
  renderTurns(log, group.turns || [], 'conversation');
  if (group.code || group.id.startsWith('agent_')) {
    const transcript = await api('/agent/transcript?session=' + encodeURIComponent(group.id));
    if ((transcript.cells || []).length) {
      log.insertAdjacentHTML('beforeend', '<div class="lee-vgroup">code executed in this session</div>');
      renderSessionCells(log, transcript);
    }
  }
  log.scrollTop = 0;
}
/* The live pane is DOM only: a reload, or an htmx swap of the shell, leaves it blank while the
   turns are still on disk. Repaint them from `/agent/history` on mount. The current session is
   the honest case -- those turns really are in the model's context. On a fresh process the
   session id is new and empty, so the newest prior session is shown instead, marked as out of
   context with its own Resume: rendering it silently would claim a context the model lacks. */
async function rehydrateAgentLive() {
  const log = $('#agentlog');
  if (!log || lee.agentView === 'history' || lee.agentBusy || lee.agentHydrating) return;
  lee.agentHydrating = true;
  try {
    const d = await api('/agent/history'), groups = d.sessions || [];
    const live = groups.find(s => s.id === d.current), carried = !(live?.turns || []).length;
    const group = carried ? groups.find(s => (s.turns || []).length) : live;
    if (!group) return;
    const held = document.createElement('div');
    renderTurns(held, group.turns, carried ? `previous conversation · ${sessionTime(group)}` : 'earlier in this conversation');
    if (carried) held.insertAdjacentHTML('beforeend',
      `<div class="lee-history-carry"><span>Not in the model's context yet.</span>` +
      `<button class="lee-btn go" onclick="leeAgentResumeId('${esc(group.id)}')">Resume</button></div>`);
    $('.lee-agent-welcome', log)?.remove();
    log.prepend(...held.children);
    lee.agentLive = log.innerHTML;
    log.scrollTop = log.scrollHeight;
  } catch (e) { /* an empty pane beats a boot that dies on a cold agent */ }
  finally { lee.agentHydrating = false; }
}
async function leeAgentHistory() {
  if (lee.agentView === 'history') return restoreAgentLive();
  rememberAgentLive(); lee.agentView = 'history'; $('#agenthistory')?.classList.add('active');
  const d = await api('/agent/history');
  await showHistorySession((d.sessions || [])[0], d.sessions || []);
}
async function leeAgentResume(group) {
  if (!group) return;
  if (lee.agentBusy) return status('the model is already working', 'err');
  try {
    const d = await post('/agent/resume', {session: group.id}), log = $('#agentlog');
    if (log) { log.innerHTML = ''; renderTurns(log, d.turns || [], 'resumed conversation'); log.scrollTop = log.scrollHeight; }
    lee.agentView = 'live'; lee.agentLive = log?.innerHTML || '';
    $('#agenthistory')?.classList.remove('active'); $('#agentprompt')?.focus();
    status(d.note || `resumed ${d.session}`, 'ok');
  } catch (e) { status(String(e.message || e), 'err'); }
}
async function leeAgentNew() { if (lee.agentBusy) return status('the model is already working', 'err'); try { await post('/agent/new', {}); lee.agentView = 'live'; lee.agentLive = ''; approvalCards.clear(); const log = $('#agentlog'); if (log) log.innerHTML = ''; $('#agenthistory')?.classList.remove('active'); $('#agentprompt')?.focus(); status('new conversation started', 'ok'); } catch (e) { status(String(e.message || e), 'err'); } }
// The rehydrated banner survives `restoreAgentLive`, which round-trips the pane through
// innerHTML: an id in an onclick attribute outlives that, a bound listener does not.
const leeAgentResumeId = id => leeAgentResume({id});
window.leeAgentNew = leeAgentNew;
window.leeAgentResume = leeAgentResume;
window.leeAgentResumeId = leeAgentResumeId;
window.leeAgentHistory = leeAgentHistory;
window.rehydrateAgentLive = rehydrateAgentLive;

async function leeAgentState() {
  try {
    const [draft, saved, template] = await Promise.all([api('/agent/state/draft'), api('/agent/states'), api('/agent/state/template')]);
    const rows = (saved.states || []).map(s => `<button class="lee-agent-state-row" data-id="${esc(s.id)}">` +
      `<strong>${esc(s.title)}</strong><span>${esc(new Date((s.added_at || 0) * 1000).toLocaleString())}</span></button>`).join('');
    const box = modal(`<div class="lee-mhead">Agent state<span class="sub">remembered rules that stay visible and follow the code</span></div>` +
      `<section class="lee-agent-state-onboard${saved.active ? ' configured' : ''}"${saved.active ? ' hidden' : ''}><div><strong>Start with a worked template</strong>` +
      `<span>Describe what you want this agent to do. The configured summary model fills a complete charter using only tools that are actually installed.</span></div>` +
      `<input class="lee-input" id="agentstateintent" placeholder="e.g. Maintain this Python project; inspect before editing and run focused tests">` +
      `<button class="lee-btn go" data-bootstrap>Generate my charter</button><button class="lee-btn" data-template>Use blank template</button></section>` +
      `<div class="lee-agent-state-grid"><section><div class="lee-agent-state-controls"><label>Where this applies<select class="lee-select" id="agentstatelayer">` +
      `${['organization','project','task','preferences','branch','ephemeral'].map(x => `<option value="${x}"${x === 'task' ? ' selected' : ''}>${x}</option>`).join('')}</select></label>` +
      `<button class="lee-btn" data-update>Refresh from code</button><button class="lee-btn" data-diagnose>Check state</button></div>` +
      `<label class="lee-fieldlabel">Title<input class="lee-input" id="agentstatetitle" value="Working state"></label>` +
      `<div class="lee-state-editor-head"><span>Markdown charter</span><button class="lee-btn" data-add-rule>Add rule</button>` +
      `<button class="lee-btn" data-add-check>Add verification</button><button class="lee-btn" data-add-tool>Add tool route</button>` +
      `<button class="lee-btn" data-preview-state>Preview</button></div><div class="lee-agent-state-editor" id="agentstatetext"></div>` +
      `<div class="lee-agent-state-help" data-state-help>Keep goal, constraints, progress, decisions, next steps, and critical context. ` +
      `This is an explicit briefing, not hidden chat history.</div></section>` +
      `<section class="lee-agent-state-reference"><nav class="lee-state-ref-tabs"><button class="active" data-ref="conversation">Conversation</button>` +
      `<button data-ref="tools">Tools</button><button data-ref="preview">Preview</button><button data-ref="saved">Saved</button></nav>` +
      `<div class="lee-state-ref-pane active" data-ref-pane="conversation"><pre class="lee-agent-conversation">${esc(draft.conversation || '(no completed turns)')}</pre></div>` +
      `<div class="lee-state-ref-pane" data-ref-pane="tools"><div class="lee-state-tool-list">${template.tools.map(t => `<button data-tool-name="${esc(t.name)}"><strong>${esc(t.name)}</strong><span>${esc(t.group)} · ${esc(t.description)}</span></button>`).join('')}</div></div>` +
      `<div class="lee-state-ref-pane lee-md" data-ref-pane="preview" id="agentstatepreview"></div>` +
      `<div class="lee-state-ref-pane" data-ref-pane="saved"><div class="lee-agent-state-list">${rows || '<div class="lee-dim">No saved states yet.</div>'}</div></div></section></div>` +
      `<div class="lee-mfoot"><button class="lee-btn go" data-save>Save to memory + activate</button>` +
      `<button class="lee-btn" data-activate>Activate without saving</button>` +
      `<span class="lee-dim">Drag the lower-right edge to resize · double-click the title to expand.</span></div>`,
      null, null, {className: 'lee-agent-state-modal', storageKey: 'agent-state'});
    const text = $('#agentstatetext', box), layer = $('#agentstatelayer', box);
    const stateView = createEditor(text, {doc: '', lang: 'markdown', lineNums: true, lintPath: '<agent-state>',
      placeholder: '# Agent charter\n\nDescribe how this agent should work…'});
    Object.defineProperty(text, 'value', {get: () => LeeCM.getDoc(stateView), set: value => LeeCM.setDoc(stateView, String(value || ''))});
    const insertStateMarkdown = value => {
      const at = LeeCM.cursor(stateView), prefix = at && !text.value.slice(0, at).endsWith('\n') ? '\n' : '';
      LeeCM.replaceRange(stateView, at, at, prefix + value); LeeCM.focus(stateView);
    };
    const showReference = name => {
      $$('.lee-state-ref-tabs button', box).forEach(b => b.classList.toggle('active', b.dataset.ref === name));
      $$('.lee-state-ref-pane', box).forEach(p => p.classList.toggle('active', p.dataset.refPane === name));
      if (name === 'preview') renderMarkdown($('#agentstatepreview', box), text.value, true);
    };
    $$('.lee-state-ref-tabs button', box).forEach(b => b.onclick = () => showReference(b.dataset.ref));
    $('[data-preview-state]', box).onclick = () => showReference('preview');
    $('[data-add-rule]', box).onclick = () => insertStateMarkdown('\n- [Write a clear, testable rule.]');
    $('[data-add-check]', box).onclick = () => insertStateMarkdown('\n- [Describe the evidence required before completion.]');
    $('[data-add-tool]', box).onclick = () => showReference('tools');
    $$('.lee-state-tool-list button', box).forEach(b => b.onclick = () => {
      const tool = template.tools.find(t => t.name === b.dataset.toolName);
      insertStateMarkdown(`\n- ${tool.name} → ${tool.description}`); showReference('preview');
    });
    const loadLayer = () => { text.value = saved.layers?.[layer.value]?.text || (layer.value === 'task' ? draft.state : ''); };
    loadLayer(); layer.onchange = loadLayer;
    $('[data-template]', box).onclick = async () => {
      const d = await api('/agent/state/template'); text.value = d.template + '\n\n' + d.catalog;
      $('[data-state-help]', box).textContent = 'Template loaded. Replace bracketed prompts, then activate or save it.';
    };
    $('[data-bootstrap]', box).onclick = async () => {
      const button = $('[data-bootstrap]', box); button.disabled = true; button.textContent = 'Generating…';
      try {
        const d = await post('/agent/state/bootstrap', {intent: $('#agentstateintent', box).value});
        text.value = d.text; $('#agentstatetitle', box).value = ($('#agentstateintent', box).value || 'Workspace agent charter').slice(0, 80);
        $('[data-state-help]', box).textContent = `Drafted with ${d.model}. Read every rule, then save + activate.`;
      } catch (e) { $('[data-state-help]', box).textContent = e.message || String(e); }
      finally { button.disabled = false; button.textContent = 'Generate my charter'; }
    };
    $('[data-update]', box).onclick = async () => {
      const d = await post('/agent/state/update', {current: text.value, conversation: draft.conversation});
      const review = modal(`<div class="lee-mhead">Review proposed state update<span class="sub">nothing changes until you apply it</span></div>` +
        `<div class="lee-diff lee-state-update-diff">${diffHtml(d.diff.rows || [])}</div>` +
        `<div class="lee-mfoot"><button class="lee-btn go" data-accept>Apply to editor</button>` +
        `<button class="lee-btn" data-reject>Keep current state</button></div>`);
      $('[data-accept]', review).onclick = () => { text.value = d.text; review.remove(); $('[data-state-help]', box).textContent = 'Proposed update applied to the editor. Review before saving or activating.'; };
      $('[data-reject]', review).onclick = () => review.remove();
    };
    $('[data-diagnose]', box).onclick = async () => {
      const d = await post('/agent/state/diagnostics', {text: text.value});
      $('[data-state-help]', box).textContent = `${d.tokens} tokens` +
        (d.missing_paths.length ? ` · missing paths: ${d.missing_paths.join(', ')}` : ' · paths current') +
        (d.duplicate_headings.length ? ` · duplicate headings: ${d.duplicate_headings.join(', ')}` : '');
    };
    const markActive = () => {
      const badge = $('#agentnames'); if (badge) badge.textContent = 'state active';
      $('.lee-agent-welcome', $('#agentlog'))?.remove();
    };
    $('[data-save]', box).onclick = async () => {
      const d = await post('/agent/state/save', {title: $('#agentstatetitle', box).value, text: text.value, layer: layer.value, activate: true});
      markActive(); status(d.saved?.skipped ? 'state already in memory and activated' : 'state saved to memory and activated', 'ok'); box.remove();
    };
    $('[data-activate]', box).onclick = async () => {
      await post('/agent/state/activate', {text: text.value, layer: layer.value});
      markActive(); status('starting state activated without saving', 'ok'); box.remove();
    };
    $$('.lee-agent-state-row', box).forEach(row => row.onclick = async () => {
      const compared = await post('/agent/state/compare', {id: row.dataset.id, current: text.value});
      const review = modal(`<div class="lee-mhead">Compare state revision<span class="sub">choose how this revision enters ${esc(layer.value)}</span></div>` +
        `<div class="lee-diff lee-state-update-diff">${diffHtml(compared.diff.rows || [])}</div>` +
        `<div class="lee-mfoot"><button class="lee-btn go" data-replace>Replace + activate</button>` +
        `<button class="lee-btn" data-merge>Merge below current</button><button class="lee-btn" data-cancel>Cancel</button></div>`);
      $('[data-replace]', review).onclick = async () => {
        const d = await post('/agent/state/load', {id: row.dataset.id, layer: layer.value}); text.value = d.state;
        review.remove(); $$('.lee-agent-state-row', box).forEach(x => x.classList.toggle('active', x === row)); status('saved revision restored and active', 'ok');
      };
      $('[data-merge]', review).onclick = () => { text.value = text.value.trim() + '\n\n' + compared.state.trim(); review.remove(); status('revision merged into editor; review before activation', 'ok'); };
      $('[data-cancel]', review).onclick = () => review.remove();
    });
  } catch (e) { status(e.message || String(e), 'err'); }
}
window.leeAgentState = leeAgentState;

function renderSessionCells(log, d) {
  if (d.path) log.insertAdjacentHTML('beforeend', `<div class="lee-session-path">${esc(d.path)}</div>`);
  for (const [i, cell] of (d.cells || []).entries()) {
    if (cell.cell_type === 'markdown') {
      const md = document.createElement('div'); md.className = 'lee-session-markdown';
      renderMarkdown(md, cell.source); log.appendChild(md); continue;
    }
    const details = document.createElement('details'); details.className = 'lee-session-code';
    const first = (cell.source || '').split('\n').find(x => x.trim()) || '(empty code cell)';
    details.innerHTML = `<summary><span>run ${i + 1}</span><code>${esc(first)}</code>` +
      `<span class="lee-agent-step-chevron" aria-hidden="true"></span></summary><div class="lee-session-code-body"></div>`;
    let mounted = false;
    details.ontoggle = () => {
      if (!details.open || mounted) return; mounted = true;
      requestAnimationFrame(() => mountCodeSurface($('.lee-session-code-body', details), cell.source, 'python', true));
    };
    log.appendChild(details);
  }
}

function agentLog(html) {
  const log = $('#agentlog');
  // Never use `innerHTML +=`: it reparses every existing child and silently detaches all
  // checkpoint, fork, rollback, CodeMirror, and disclosure handlers already in the log.
  log.insertAdjacentHTML('beforeend', html);
  log.scrollTop = log.scrollHeight;
}

