/* Most callers pass no state, and a steer is not theirs to forget. Only a payload carrying
   `queued_steer` may change it, so the acknowledgement survives until the server says the steer
   was taken. */
//: The run states `Run.terminal` covers. A row in one of them is history, not work in progress.
const TERMINAL = new Set(['completed', 'cancelled', 'detached', 'terminated', 'failed']);

function updateAgentRunstrip(state = {}) {
  const strip = $('#agentrunstrip'); if (!strip) return;
  if ('queued_steer' in state) setQueuedSteer(state.queued_steer || '');
  if ('runs' in state) lee.agentRuns = state.runs || [];
  const runs = lee.agentRuns || [];
  const flattenRuns = rows => rows.flatMap(r => [r, ...flattenRuns(r.children || [])]);
  const flat = flattenRuns(runs);
  // A row that has ended is history. Counting them as work kept the strip up over a finished
  // delegation and left the composer in steer mode, so the next thing typed was offered to a run
  // that was already over instead of being sent as a turn.
  const active = flat.some(r => !TERMINAL.has(r.state));
  strip.hidden = !active && !lee.agentBusy && !state.waiting;
  updateAgentSendMode(active || lee.agentBusy ? 'steer' : 'send');
  const rootLabel = state.waiting ? `Waiting · ${state.waiting}`
    : lee.queuedSteer ? 'Steering queued · applies after the current tool call'
    : state.run_policy ? `Running automatically · ${runPolicyLabel(state.run_policy)}`
    : `${($('#agentcontrol')?.value || 'guided').toUpperCase()} · agent working`;
  // A fan-out's rows tell each other apart only by what each subagent was asked, and the buttons'
  // row leaves that a dozen characters. The rows take the width and the buttons go under them.
  strip.classList.toggle('fanned', flat.length > 1);
  $('.lee-agent-run-state', strip).innerHTML = flat.length ? flat.map(r => {
    // `ended`, where the run has one: a finished run's clock counted on, and read as still working.
    const done = TERMINAL.has(r.state);
    const until = r.ended || (done ? r.started : Date.now() / 1000);
    const elapsed = r.started ? Math.max(0, until - r.started) : 0;
    const clock = `${Math.floor(elapsed / 60)}:${String(Math.floor(elapsed % 60)).padStart(2, '0')}`;
    // the model repeats on every row of a fan-out; the question does not
    const who = r.kind === 'child' ? `subagent ${(r.model || '').split('/').pop()}`.trim() : (r.model || 'Agent');
    // The root's line says what the agent is doing, which is not what a delegate was asked. A child
    // with no question of its own borrowed it and read as the agent working.
    const what = r.question || (r.kind === 'child' ? 'delegated' : rootLabel);
    const label = r.state === 'cancelling' ? `Cancelling ${who}…` : `${what} · ${who}`;
    return `<span class="lee-agent-run${r.kind === 'child' ? ' child' : ''}"><span>${esc(label)}</span>` +
      `<time>${esc(clock)}</time>` +
      (r.kind === 'child' ? `<button type="button" data-open-subs>Open</button><button type="button" data-watch-run="${esc(r.id)}" data-title="${esc(r.question || r.id)}">Watch</button>` : '') +
      (done ? '' : `<button type="button" data-stop-run="${esc(r.id)}">Stop</button>`) + `</span>`;
  }).join('') : esc(rootLabel);
  $$('[data-open-subs]', strip).forEach(b => b.onclick = e => { e.stopPropagation(); leeSubagents(); });
  $$('[data-watch-run]', strip).forEach(b => b.onclick = e => { e.stopPropagation(); leeWatchRun(b.dataset.watchRun, b.dataset.title); });
  $$('[data-stop-run]', strip).forEach(btn => btn.onclick = async e => {
    e.stopPropagation();
    try { const d = await post(`/agent/runs/${encodeURIComponent(btn.dataset.stopRun)}/cancel${agentThreadQuery()}`, {}); updateAgentRunstrip({runs: (await api(`/agent/runs${agentThreadQuery()}`)).runs}); status(d.state, 'ok'); }
    catch (err) { status(err.message || String(err), 'err'); }
  });
}
// a run belongs to the conversation the pane shows; without it the server picks its own active one
const agentThreadQuery = () => lee.agentThread ? `?thread=${encodeURIComponent(lee.agentThread)}` : '';
async function pauseAgentAfterCurrent() {
  const d = await post('/agent/run-policy', {policy: 'pause'}); updateAgentRunstrip(d);
  status('agent will pause before the next call', 'ok');
}
function updateAgentSendMode(mode = 'send') {
  const button = $('#agentsend'); if (!button) return;
  const label = mode === 'force' ? 'Stop and send next' : mode === 'steer' ? 'Steer after this call' : 'Send';
  button.textContent = label; button.setAttribute('aria-label', label);
  button.title = mode === 'send' ? 'send this as a turn'
    : 'hand this to the model after the current call — shift-click to stop the run and send it now';
}
/* A steer belongs inside the turn's timeline rather than after it, among the chunks and tool rows
   it came between. */
const steerHost = log => lee.agentTimeline?.root?.isConnected ? lee.agentTimeline.root : log;
/* The local reply and the feed event carry the same steer, so the same text twice with nothing
   between it is one. Two identical steers a person really sent have a turn's work in between. */
const steerDrawn = (log, text) => steerHost(log).lastElementChild?.dataset?.steer === text;
function placeSteer(log, card, text) {
  card.dataset.steer = text;
  const live = lee.agentTimeline;
  // no live timeline: the turn's own body, so a steer is never a stray sibling between two turns
  if (live?.root?.isConnected) live.append(card);
  else (turnBody(currentAgentTurn()) || log).appendChild(card);
  log.scrollTop = log.scrollHeight;
  return card;
}
function setQueuedSteer(text, shown = '', cancel = false) {
  lee.queuedSteer = text || '';
  const log = $('#agentlog'), old = $('#agentqueuedsteer'); if (!log) return;
  if (!lee.queuedSteer) {
    if (cancel) { old?.remove(); return; }
    /* A steer that has been taken is no longer the queued one, and the id has to go with the state.
       It used to stay on the card, so the next steer found it here and returned without drawing,
       and a queued one after that was written into it: the agent acted on a message the transcript
       never showed. */
    if (old) { old.id = ''; old.classList.remove('queued'); $('[data-cancel-steer]', old)?.remove(); }
    if (old && old.dataset.steer === shown) return;
    /* Steering against a waiting approval answers it there and then, so it is never queued and
       nothing recorded what was said. The local reply and the feed event both arrive, and the
       same text twice with nothing between it is one steer. */
    if (shown && !steerDrawn(log, shown)) placeSteer(log, userMessage(shown), shown);
    return;
  }
  const card = old || userMessage(shown || lee.queuedSteer);
  card.id = 'agentqueuedsteer'; card.classList.add('queued');
  if (!old) placeSteer(log, card, shown || lee.queuedSteer);
  let button = $('[data-cancel-steer]', card);
  if (!button) { button = document.createElement('button'); button.type = 'button'; button.dataset.cancelSteer = '1'; button.textContent = 'Cancel'; card.appendChild(button); }
  button.onclick = async () => {
    try { await post('/agent/steer', {cancel: true}); } catch (e) { return status(e.message || String(e), 'err'); }
    setQueuedSteer('', '', true); updateAgentRunstrip();
  };
  log.scrollTop = log.scrollHeight;
}
async function leeQueueSteer() {
  const input = $('#agentprompt'), text = input?.value.trim();
  if (!text) return status('write what to steer towards first', 'err');
  try {
    const d = await post('/agent/steer', {text}); input.value = '';
    setQueuedSteer(d.queued_steer || '', text); updateAgentRunstrip(d);
    status(d.queued_steer ? 'steering queued after the current tool call' : 'steering sent to the agent', 'ok');
  } catch (e) { input.value = text; status(e.message || String(e), 'err'); }
}
async function leeForceSteer() {
  const input = $('#agentprompt'), text = input?.value.trim();
  if (!lee.agentBusy) return status('nothing is running to stop; send it as a turn instead', 'err');
  if (!text) return status('write what to send next first', 'err');
  updateAgentSendMode('force');
  try {
    const d = await post('/agent/steer', {text, force: true});
    lee.agentBusy = false; lee.agentRuns = []; input.value = text; setQueuedSteer('', '', true); updateAgentRunstrip({runs: []});
    status(d.run?.state === 'detached' ? 'provider detached; sending the saved draft' : 'run cancelled; sending the saved draft', 'ok');
    return sendAgent();
  } catch (e) { input.value = text; updateAgentSendMode('steer'); status(e.message || String(e), 'err'); }
}

async function pollApproval() {
  try {
    const r = await api('/agent/approval');
    if (r.pending) showApproval(r.pending);
  } catch (_) {}
}

/* An approval must not sit unseen while the model works. Idle, only a background job raises one.

   Two seconds while busy, not the 750ms this used to run at: the turn's own SSE feed carries an
   `approval` event and paints the checkpoint the moment it is raised, so this poll is the backstop
   for a run whose stream this tab is not attached to. At 750ms it was four requests a second of the
   process the window is drawing in, for something the stream had already said. */
const APPROVAL_GAP = {hidden: 5000, busy: 2000, idle: 5000};
async function approvalLoop() {
  if (lee.observer) return;
  if (!document.hidden) await pollApproval();
  // attention is about the conversations a person is *not* looking at, so it is polled even hidden
  try { await refreshAgentThreads(); } catch (_) {}
  setTimeout(approvalLoop, document.hidden ? APPROVAL_GAP.hidden
                         : lee.agentBusy ? APPROVAL_GAP.busy : APPROVAL_GAP.idle);
}

function readableDetail(value) {
  const text = String(value || '');
  try { return JSON.stringify(JSON.parse(text), null, 2); } catch { return text; }
}
/* `user_steering` is what the person said when they refused a call. Drawn as an ordinary step it
   read `user_steering(instruction='The user rejected this tool c…')`, the harness describing
   itself with the direction hidden behind a chevron. The full instruction stays in the panel. */
const STEER_TOOL = 'user_steering';
function steerSaid(args) {
  const raw = String((args || {}).instruction || '');
  const said = raw.split(/User direction:\s*/)[1];      // what was typed, when anything was
  return (said || '').trim() ||
    (/stopped this turn/i.test(raw) ? 'stopped the turn' : 'rejected that call');
}
function renderAgentStep(row, a) {
  const wasOpen = row.open;
  for (const v of (row._leeViews || [])) try { LeeCM.destroy(v); } catch {}
  row._leeViews = []; row.innerHTML = '';
  const deferredEditors = [];
  const steered = (a.tool || '') === STEER_TOOL;
  row.className = `lee-agent-step kind-${a.kind || 'tool'} ${a.done ? (a.ok ? 'done' : 'failed') : 'pending'}`
    + (steered ? ' lee-agent-steer-step' : '');
  const summary = document.createElement('summary');
  summary.innerHTML = `<span class="lee-agent-step-state" aria-hidden="true"></span>` +
    `<span class="lee-agent-step-copy">${steered ? `<strong>You</strong> ${esc(steerSaid(a.args))}`
      : esc(a.summary || a.tool || 'Working')}</span>` +
    // a delegation is the one step whose work happened somewhere this row cannot show
    ((a.kind || '') === 'delegate' ? `<button class="lee-agent-step-open" type="button" data-open-sub` +
      ` title="open this delegation: what its sub-agents did, and steer one that is still going">open</button>` : '') +
    `<span class="lee-agent-step-meta">${steered ? 'steered'
      : a.done && a.secs ? esc(Number(a.secs).toFixed(1) + 's') : esc(a.kind || '')}</span>` +
    `<span class="lee-agent-step-chevron" aria-hidden="true"></span>`;
  // inside a `summary`, a click is the disclosure's unless it is taken
  $('[data-open-sub]', summary)?.addEventListener('click', e => {
    e.preventDefault(); e.stopPropagation(); leeSubagents(a.action_id || a.id || '');
  });
  row.appendChild(summary);

  const args = a.args && typeof a.args === 'object' ? a.args : {};
  const code = typeof args.code === 'string' ? args.code : '';
  const rest = Object.entries(args).filter(([k, v]) => k !== 'code' && v != null && String(v) !== '');
  if (code || rest.length || a.detail) {
    const panel = document.createElement('div'); panel.className = 'lee-agent-step-detail';
    if (rest.length) {
      const dl = document.createElement('dl');
      for (const [key, value] of rest) {
        const dt = document.createElement('dt'), dd = document.createElement('dd');
        dt.textContent = key; dd.textContent = typeof value === 'string' ? value : JSON.stringify(value);
        dl.append(dt, dd);
      }
      panel.appendChild(dl);
    }
    if (code) {
      const block = document.createElement('div'); panel.appendChild(block);
      deferredEditors.push(() => row._leeViews.push(mountCodeSurface(block, code, 'python', true)));
    }
    if (a.detail) {
      const result = document.createElement('section'); result.className = 'lee-tool-result';
      const label = document.createElement('header'); label.textContent = 'result'; result.appendChild(label);
      const detail = readableDetail(a.detail);
      if (a.kind === 'view' || a.kind === 'skill') {
        const block = document.createElement('div'); result.appendChild(block);
        const path = args.path || (a.kind === 'skill' ? 'note.md' : '');
        deferredEditors.push(() => row._leeViews.push(mountCodeSurface(
          block, detail, codeLang('', path), /\.py$/i.test(path))));
      } else {
        const pre = document.createElement('pre'); pre.textContent = detail; result.appendChild(pre);
      }
      panel.appendChild(result);
    }
    row.appendChild(panel); row.open = wasOpen;
    let mounted = false;
    const mountDeferred = () => {
      if (mounted || !row.open) return;
      mounted = true; requestAnimationFrame(() => deferredEditors.forEach(fn => fn()));
    };
    row.ontoggle = mountDeferred;
    mountDeferred();
  } else { summary.classList.add('empty'); row.ontoggle = null; }
}

/* A delegated sub-agent's conversation is thrown away the moment it answers, so its recorded calls
   are the whole account of what it did. The runstrip shows one while it runs and forgets it, which
   left a failed delegation as one row of prose and nothing to look at. */
function subagentQuestions(args) {
  const raw = (args || {}).questions ?? (args || {}).question ?? '';
  try { const v = JSON.parse(raw); if (Array.isArray(v)) return v.map(String); } catch {}
  return [String(raw)].filter(Boolean);
}
function subagentRunRow(r) {
  const secs = r.started ? Math.max(0, Date.now() / 1000 - r.started) : 0;
  return `<div class="lee-subagent-run" data-run="${esc(r.id)}">` +
    `<strong>${esc(r.question || '(no question)')}</strong>` +
    `<span>${esc(r.state)} · ${esc((r.model || '').split('/').pop())} · ` +
    `${Math.floor(secs / 60)}:${String(Math.floor(secs % 60)).padStart(2, '0')}` +
    `${r.inbox ? ' · message queued' : ''}</span>` +
    `<button class="lee-btn" type="button" data-watch-run="${esc(r.id)}" data-title="${esc(r.question || r.id)}">Transcript</button>` +
    `<button class="lee-btn" type="button" data-steer-run>Message</button>` +
    `<button class="lee-btn warn" type="button" data-stop-run="${esc(r.id)}">Stop</button></div>`;
}
function paintSubagents(box, d) {
  const list = $('.lee-subagent-list', box);
  for (const row of $$('.lee-subagent-calls > details', list))
    for (const v of (row._leeViews || [])) try { LeeCM.destroy(v); } catch {}
  const cards = (d.delegations || []).map(x => {
    const calls = x.calls || [];
    // an empty list is not the same answer as "it did nothing", and the server says which
    const none = d.records_sub_calls
      ? 'This delegation recorded no tool calls.'
      : 'Nothing a sub-agent does is being recorded here, so this is not an account of what it did.';
    return `<section class="lee-subagent ${x.ok ? 'ok' : 'failed'}">` +
      `<header><strong>${esc(x.summary || x.tool)}</strong>` +
      `<span>${esc(x.done ? (x.ok ? `answered in ${Number(x.secs || 0).toFixed(1)}s` : 'failed') : 'still working')}` +
      ` · ${calls.length} recorded call${calls.length === 1 ? '' : 's'}</span></header>` +
      `<ol class="lee-subagent-questions">${subagentQuestions(x.args).map(q => `<li>${esc(q)}</li>`).join('')}</ol>` +
      `<div class="lee-subagent-calls" data-calls="${esc(x.id)}"></div>` +
      (calls.length ? '' : `<p class="lee-dim">${esc(none)}</p>`) +
      (x.detail ? `<details class="lee-subagent-answer"><summary>What it reported back</summary><pre>${esc(x.detail)}</pre></details>` : '') +
      `</section>`;
  }).join('');
  const runs = (d.runs || []).map(subagentRunRow).join('');
  list.innerHTML = (runs ? `<section class="lee-subagent running"><header><strong>Running now</strong>` +
      `<span>message one and it reads you on its next tool result</span></header>${runs}</section>` : '') +
    (cards || `<p class="lee-dim">No delegated questions in this conversation yet.</p>`);
  const drawCalls = (host, calls) => { for (const call of calls || []) {
    const row = document.createElement('details'); renderAgentStep(row, call); host.appendChild(row);
    // a nested delegation carries its own sub-agent's calls
    if (call.calls?.length) { const sub = document.createElement('div'); sub.className = 'lee-subagent-calls lee-subagent-nested'; row.appendChild(sub); drawCalls(sub, call.calls); }
  } };
  for (const x of d.delegations || []) {
    const host = $(`[data-calls="${CSS.escape(x.id)}"]`, list); if (host) drawCalls(host, x.calls);
  }
  $$('[data-stop-run]', list).forEach(b => b.onclick = async () => {
    try { await post(`/agent/runs/${encodeURIComponent(b.dataset.stopRun)}/cancel${agentThreadQuery()}`, {}); status('sub-agent stopping', 'ok'); }
    catch (e) { status(e.message || String(e), 'err'); }
  });
  $$('[data-steer-run]', list).forEach(b => b.onclick = async () => {
    const id = b.closest('.lee-subagent-run').dataset.run;
    const text = await textDialog('Message this sub-agent', 'It reads this on its next tool result', ''); if (!text) return;
    try { const d = await post(`/agent/runs/${encodeURIComponent(id)}/steer`, {text, thread: lee.agentThread || ''}); status(d.note || 'message sent', 'ok'); }
    catch (e) { status(e.message || String(e), 'err'); }
  });
  $$('[data-watch-run]', list).forEach(b => b.onclick = () => leeWatchRun(b.dataset.watchRun, b.dataset.title));
}
/* A run's transcript is a file the agent core appends to. The logs dock tails it under the `runs`
   filter, one poll a second, until the run ends; a background command's output arrives the same way. */
lee.watches = new Map();
async function leeWatchRun(runId, title = '') {
  if (!runId || lee.watches.has(runId)) { leeDock('logs'); leeLogFilter('runs'); return; }
  const w = {since: 0, title: title || runId}; lee.watches.set(runId, w);
  leeDock('logs'); leeLogFilter('runs'); leeLog('runs', `watching ${w.title}`, '', '');
  const stop = $('#logstop'); if (stop && runId.startsWith('cmd_')) { stop.hidden = false; stop.dataset.run = runId; }
  const tick = async () => {
    if (!lee.watches.has(runId)) return;
    if (!$('#bottomdock')?.classList.contains('dock-logs')) { w.timer = setTimeout(tick, 1000); return; }
    try {
      const d = await api(`/agent/runs/${encodeURIComponent(runId)}/log?since=${w.since}` + (lee.agentThread ? '&thread=' + encodeURIComponent(lee.agentThread) : ''));
      if (d.text) { w.since = d.since; leeLog('runs', w.title, d.text.replace(/\n$/, ''), ''); }
      if (d.done) { leeLog('runs', `${w.title} · ${d.state}`, '', ''); return leeWatchStop(runId); }
    } catch (e) { leeLog('runs', `${w.title} · ${e.message || e}`, '', 'err'); return leeWatchStop(runId); }
    w.timer = setTimeout(tick, 1000);
  };
  tick();
}
async function leeWatchStop(runId = '') {
  const stop = $('#logstop'), id = runId || stop?.dataset.run || '';
  if (!runId && id.startsWith('cmd_')) {
    try { const d = await post(`/agent/shell/${encodeURIComponent(id)}/stop` + (lee.agentThread ? '?thread=' + encodeURIComponent(lee.agentThread) : ''), {}); status(`${id} ${d.state}`, 'ok'); }
    catch (e) { status(e.message || String(e), 'err'); }
  }
  const w = lee.watches.get(id); if (w) { clearTimeout(w.timer); lee.watches.delete(id); }
  if (stop && stop.dataset.run === id) { stop.hidden = true; delete stop.dataset.run; }
}
window.leeWatchRun = leeWatchRun; window.leeWatchStop = leeWatchStop;
/* A delegation that finished while nobody was asking: painted when it lands, and carried into the
   next turn by the agent core itself. */
function backgroundCard(log, d) {
  const el = document.createElement('details'); el.className = `lee-agent-background ${esc(d.state || '')}`; el.open = true;
  el.innerHTML = `<summary><strong>Background result</strong><span>${esc(d.id || '')} · ${esc(d.state || '')}</span>` +
    `<i class="lee-agent-step-chevron" aria-hidden="true"></i></summary>` +
    `<p>${esc(d.question || '')}</p><pre>${esc(d.answer || '')}</pre>` +
    `<button class="lee-btn" type="button" data-watch-run="${esc(d.id || '')}">Transcript</button>`;
  $('[data-watch-run]', el).onclick = () => leeWatchRun(d.id, d.question || d.id);
  (log || $('#agentlog'))?.appendChild(el); stickAgentLog(log || $('#agentlog'));
}
async function leeApprovalRules() {
  const url = () => '/agent/approval/rules' + (lee.agentThread ? '?thread=' + encodeURIComponent(lee.agentThread) : '');
  let d; try { d = await api(url()); } catch (e) { return status(e.message || String(e), 'err'); }
  const box = modal(`<div class="lee-mhead">Approval rules<span class="sub">calls that run without asking · ${esc(d.path || 'this session only')}</span></div>` +
    `<div class="lee-rule-list"></div>`, null, null, {className: 'lee-rules-modal', storageKey: 'approvalrules'});
  const paint = rules => {
    $('.lee-rule-list', box).innerHTML = rules.length ? rules.map(([tool, pat, verdict]) =>
      `<div class="lee-rule ${esc(verdict)}"><code>${esc(tool)}</code><span>${esc(pat)}</span><em>${esc(verdict)}</em>` +
      `<button class="lee-btn warn" type="button" data-rule="${esc(JSON.stringify([tool, pat, verdict]))}">Remove</button></div>`).join('')
      : `<p class="lee-dim">No saved rules. Always allow on an approval card adds one.</p>`;
    $$('[data-rule]', box).forEach(b => b.onclick = async () => {
      try { paint((await post('/agent/approval/rules/delete', {rule: JSON.parse(b.dataset.rule), thread: lee.agentThread || ''})).rules || []); }
      catch (e) { status(e.message || String(e), 'err'); }
    });
  };
  paint(d.rules || []);
}
window.leeApprovalRules = leeApprovalRules;

async function leeSubagents(actionId = '') {
  const url = () => '/agent/subagents?action_id=' + encodeURIComponent(actionId) +
    (lee.agentThread ? '&thread=' + encodeURIComponent(lee.agentThread) : '');
  let first;
  try { first = await api(url()); } catch (e) { return status(e.message || String(e), 'err'); }
  let timer = 0;
  const box = modal(`<div class="lee-mhead">Sub-agents<span class="sub">what a delegated question actually did</span></div>` +
    `<div class="lee-subagent-list"></div>`, null, () => clearInterval(timer),
    {className: 'lee-subagent-modal', storageKey: 'subagents'});
  /* Repainted only when something actually moved. `paintSubagents` replaces the list wholesale, so
     a repaint on every tick closed every step a person had opened and dropped its CodeMirror views
     on the floor. A finished delegation never changes again, so polling stops with the last run. */
  const moved = d => JSON.stringify([d.runs, (d.delegations || []).map(x => [x.id, x.done, x.ok, x.calls.length,
    (x.calls || []).map(c => [c.id, c.done, c.ok])])]);
  let seen = moved(first);
  paintSubagents(box, first);
  const running = d => (d.runs || []).length || (d.delegations || []).some(x => !x.done);
  if (!running(first)) return;
  timer = setInterval(async () => {
    if (!box.isConnected) return clearInterval(timer);
    try {
      const d = await api(url()), now = moved(d);
      if (now !== seen) { seen = now; paintSubagents(box, d); }
      if (!running(d)) clearInterval(timer);
    } catch (_) {}
  }, 1200);
}
window.leeSubagents = leeSubagents;

// A turn gets an immediate, persistent status surface, in the agent log rather than only in the
// footer: long local inference must still look alive when the footer is out of sight.
function agentProgress(log) {
  const el = document.createElement('section');
  el.className = 'lee-agent-progress'; el.setAttribute('role', 'status'); el.setAttribute('aria-live', 'polite');
  el.innerHTML = `<div class="lee-agent-motion" aria-hidden="true"><i></i><i></i><i></i></div>` +
    `<div class="lee-agent-progress-copy"><strong>Model is working</strong>` +
    `<span class="lee-agent-phase">Preparing context</span></div>` +
    `<time class="lee-agent-elapsed">0:00</time>` +
    `<button class="lee-agent-stop" type="button">Stop</button>`;
  log.appendChild(el);
  const began = performance.now(), clock = setInterval(() => {
    // The pane rebuilds this log whole, and only `finish` clears the clock, so a strip that is
    // replaced rather than finished would be written to four times a second forever.
    if (!el.isConnected) return clearInterval(clock);
    const secs = Math.floor((performance.now() - began) / 1000);
    $('.lee-agent-elapsed', el).textContent = `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, '0')}`;
  }, 250);
  $('.lee-agent-stop', el).onclick = () => { $('.lee-agent-phase', el).textContent = 'Stopping after this step'; stopAgent(); };
  return {
    phase(text) { $('.lee-agent-phase', el).textContent = text; },
    finish(ok = true) {
      clearInterval(clock); el.classList.add(ok ? 'complete' : 'failed');
      $('.lee-agent-progress-copy strong', el).textContent = ok ? 'Response ready' : 'Model stopped';
      $('.lee-agent-phase', el).textContent = ok ? 'Finished' : 'The stream ended before completion';
      $('.lee-agent-stop', el).remove();
      setTimeout(() => el.remove(), 900);
    },
  };
}

// Slash commands and @ files are resolved inline, without sending a half-written token to the
// model. Selected files stay visible as removable chips until the turn starts.
const attachKey = r => typeof r === 'string' ? r : r?.kind === 'vault' ? `${r.vault || ''}|${r.shelf || ''}|${r.doc}`
  : `sel|${r?.path || ''}|${r?.from || ''}`;
function agentAttachList() {
  return [...lee.agentAttachments.keys(), ...lee.agentSelections.map(s => s.ref), ...lee.vaultRefs.values()];
}
window.agentAttachList = agentAttachList;
function markAgentBlocked(refs, why, kind) {
  lee.attachBlocked = new Map((refs || []).map(r => [attachKey(r), why]));
  const line = $('#agentsendline');
  if (line && why) { line.hidden = false; line.textContent = why; line.className = 'lee-vault-sendline lee-agent-sendline blocked'; line.dataset.kind = kind || ''; }
}
window.markAgentBlocked = markAgentBlocked;
/* The line above the prompt: where the attachments go for the turn model, from the route every send line uses. */
let agentSendSeq = 0;
async function checkAgentSend() {
  const line = $('#agentsendline'), atts = agentAttachList(), mine = ++agentSendSeq;
  if (!line) return;
  if (!atts.length) { line.hidden = true; lee.attachBlocked?.clear(); return; }
  const d = await vaultCall('/vault/send-check', {attach: JSON.stringify(atts)});
  if (mine !== agentSendSeq) return;
  line.hidden = false; line.dataset.kind = d.kind || '';
  line.textContent = d.ok ? d.why : d.error;
  line.className = 'lee-vault-sendline lee-agent-sendline' + (d.ok && d.check_ok ? '' : ' blocked');
  const was = [...(lee.attachBlocked?.keys() || [])].join();
  lee.attachBlocked = new Map((d.attachments || []).map(r => [attachKey(r), d.why]));
  if ([...lee.attachBlocked.keys()].join() !== was) paintAgentAttachments(false);
}
function paintAgentAttachments(check = true) {
  const host = $('#agentattachments'); if (!host) return;
  if (check) { clearTimeout(lee.__sendT); lee.__sendT = setTimeout(checkAgentSend, 150); }
  const bad = k => lee.attachBlocked?.get(k);
  const chip = (k, cls, title) => `<span class="lee-agent-attachment${cls}${bad(k) ? ' blocked' : ''}" title="${esc(bad(k) || title)}" data-attach-key="${esc(k)}">`;
  const active = lee.path ? `<span class="lee-agent-context" title="The assistant can see the active workspace and open files">` +
    `<span>active · ${esc(compactPath(lee.path))}</span></span>` : '';
  const states = lee.stateSuggestions.map(s => `<button type="button" class="lee-agent-state-suggestion" data-state-id="${esc(s.id)}" ` +
    `title="Preview and attach this remembered starting state">state · ${esc(s.title)}</button>`).join('');
  const sels = lee.agentSelections.map((s, i) =>
    `${chip(attachKey(s.ref), ' selection', s.path)}<span>${esc(s.label)}</span>` +
    `<button type="button" data-sel="${i}" aria-label="remove ${esc(s.label)}">remove</button></span>`).join('');
  const vaulted = [...lee.vaultRefs.entries()].map(([key, r]) =>
    `${chip(attachKey(r), ' vault', `${r.vault || 'vault'} · ${r.shelf || 'main'}`)}` +
    `<span>${esc(r.title)}</span>` +
    `<button type="button" data-vault-ref="${esc(key)}" aria-label="remove ${esc(r.title)}">remove</button></span>`).join('');
  host.innerHTML = active + sels + vaulted + [...lee.agentAttachments.entries()].map(([path, name]) =>
    `${chip(path, name.endsWith('/') ? ' folder' : '', path)}<span>${esc(name)}</span>` +
    `<button type="button" data-path="${esc(path)}" aria-label="remove ${esc(name)}">remove</button></span>`).join('') + states;
  $$('.lee-agent-state-suggestion', host).forEach(b => b.onclick = async () => {
    await post('/agent/state/load', {id: b.dataset.stateId, layer: 'task'});
    lee.stateSuggestions = []; paintAgentAttachments(); status('relevant state attached to this workspace', 'ok');
  });
  $$('[data-sel]', host).forEach(b => b.onclick = () => {
    lee.agentSelections.splice(+b.dataset.sel, 1); paintAgentAttachments();
  });
  $$('[data-vault-ref]', host).forEach(b => b.onclick = () => {
    lee.vaultRefs.delete(b.dataset.vaultRef); paintAgentAttachments();
  });
  $$('[data-path]', host).forEach(b => b.onclick = () => {
    const name = lee.agentAttachments.get(b.dataset.path);
    lee.agentAttachments.delete(b.dataset.path);
    // The token goes with the chip, or the prompt keeps naming something no longer attached.
    const input = $('#agentprompt');
    if (input && name) input.value = input.value.replace(new RegExp(`(^|\\s)@${name.replace(/[.*+?^${}()|[\]\\\/]/g, '\\$&')}\\s?`), '$1');
    paintAgentAttachments();
  });
}
function closeAgentSuggest() {
  const menu = $('#agentsuggest'); if (!menu) return;
  menu.hidden = true; menu.innerHTML = ''; lee.agentSuggest = []; lee.agentSuggestAt = 0;
}
function paintAgentSuggest() {
  const menu = $('#agentsuggest'); if (!menu) return;
  menu.hidden = !lee.agentSuggest.length;
  menu.innerHTML = lee.agentSuggest.map((x, i) =>
    `<button type="button" role="option" aria-selected="${i === lee.agentSuggestAt}" ` +
    `class="lee-agent-suggest-row${i === lee.agentSuggestAt ? ' active' : ''}" data-i="${i}">` +
    `<strong>${esc(x.label)}</strong><span>${esc(x.detail || '')}</span></button>`).join('');
  $$('button', menu).forEach(b => b.onclick = () => chooseAgentSuggest(+b.dataset.i));
}
function chooseAgentSuggest(i = lee.agentSuggestAt) {
  const item = lee.agentSuggest[i], input = $('#agentprompt'); if (!item || !input) return;
  // The caret is set on every branch: assigning `value` on a box that is not focused leaves it
  // at 0, so completing a command read as Home.
  if (item.kind === 'command') { input.value = `/${item.name} `; input.selectionStart = input.selectionEnd = input.value.length; }
  else if (item.kind === 'tool' || item.kind === 'skill') {
    const at = input.selectionStart, before = input.value.slice(0, at);
    const left = before.replace(/(^|\s)\/(?:[A-Za-z_][\w-]*)?$/, `$1/${item.name} `);
    input.value = left + input.value.slice(at); input.selectionStart = input.selectionEnd = left.length;
  } else if (item.kind === 'vault') {
    attachVaultRef(item);
    const at = input.selectionStart, before = input.value.slice(0, at);
    const left = before.replace(/(^|\s)@[^\s@]*$/, `$1@${item.name} `);
    input.value = left + input.value.slice(at); input.selectionStart = input.selectionEnd = left.length;
    paintAgentAttachments();
  } else {
    // The token stays. What you typed is the reference, and the chip is that reference resolved.
    lee.agentAttachments.set(item.path, item.name);
    const at = input.selectionStart, before = input.value.slice(0, at);
    const left = before.replace(/(^|\s)@[^\s@]*$/, `$1@${item.name} `);
    input.value = left + input.value.slice(at); input.selectionStart = input.selectionEnd = left.length;
    paintAgentAttachments();
  }
  closeAgentSuggest(); input.focus();
}
let agentSuggestSeq = 0, stateSuggestTimer = null, agentSuggestTimer = null;
async function suggestAgentState(text) {
  if (text.trim().length < 18 || text.trim().startsWith('/')) { lee.stateSuggestions = []; return paintAgentAttachments(); }
  try {
    const d = await api('/agent/state/suggest?q=' + encodeURIComponent(text.trim()));
    lee.stateSuggestions = (d.states || []).slice(0, 2); paintAgentAttachments();
  } catch (_) {}
}
async function updateAgentSuggest() {
  const input = $('#agentprompt'); if (!input) return;
  const before = input.value.slice(0, input.selectionStart);
  const slash = before.match(/(?:^|\s)\/([A-Za-z_][\w-]*)?$/), commandSlash = before.match(/^\s*\/([\w-]*)$/);
  const mention = before.match(/(?:^|\s)@([^\s@]*)$/); const seq = ++agentSuggestSeq;
  if (slash) {
    lee.agentVocabulary ||= await api('/agent/commands');
    if (seq !== agentSuggestSeq) return;
    const query = (slash[1] || '').toLowerCase(), vocab = lee.agentVocabulary;
    const commands = commandSlash ? (vocab.commands || []).map(c => ({kind: 'command', ...c})) : [];
    const tools = (vocab.tools || []).map(t => ({kind: 'tool', ...t}));
    const skills = (vocab.skills || []).map(s => ({kind: 'skill', ...s}));
    lee.agentSuggest = [...commands, ...tools, ...skills]
      .filter(x => x.name.toLowerCase().startsWith(query)).slice(0, 14)
      .map(x => ({...x, label: '/' + x.name, detail: `${x.kind} · ${x.help || ''}`}));
  } else if (mention) {
    // `@` means "in this project": with several checkouts open, the unscoped list is mostly files
    // from a project you are not in. `dirs` because attaching a folder says "read around here".
    // The vault answers the same `@`, because "this document" is one gesture whether the document
    // is open or filed a month ago. Both are capped short, or one source fills every visible row.
    const [f, v] = await Promise.all([
      api('/fs/find?dirs=1&scope=project&q=' + encodeURIComponent(mention[1]) + '&limit=7').catch(() => ({})),
      api('/vault/mentions?limit=5&q=' + encodeURIComponent(mention[1])).catch(() => ({}))]);
    if (seq !== agentSuggestSeq) return;
    const files = (f.hits || []).slice(0, 7).map(x => ({kind: x.kind === 'folder' ? 'folder' : 'file',
      path: x.path, name: x.name, label: '@' + x.name,
      detail: (x.kind === 'folder' ? 'folder · ' : '') + compactPath(x.path)}));
    const vaulted = (v.mentions || []).map(x => ({kind: 'vault', vault: x.vault, shelf: x.shelf,
      doc: x.doc, name: x.title, title: x.title, label: '@' + x.title, detail: 'vault · ' + x.detail}));
    lee.agentSuggest = [...files, ...vaulted];
  } else return closeAgentSuggest();
  lee.agentSuggestAt = 0; paintAgentSuggest();
}
/* The chip reads `model · mode`; `data-mode` tints it when a write can run without asking. */
function paintAgentChip() {
  const chip = $('#agentchip'), model = $('#agentmodel'), mode = $('#agentcontrol'); if (!chip || !model || !mode) return;
  $('#agentchipmodel', chip).textContent = (model.selectedOptions[0]?.text || model.value).split(' · ')[0];
  $('#agentchipmode', chip).textContent = mode.value; chip.dataset.mode = mode.value;
}
window.paintAgentChip = paintAgentChip;
/* Each conversation keeps its own control, so the select follows the one on screen. */
function showAgentControl(control) {
  const select = $('#agentcontrol'); if (!select || !control) return;
  select.value = control; paintAgentChip();
}
async function leeAgentControl(control) {
  try {
    const d = await post('/agent/control', {control});
    showAgentControl(d.control);
    status(`agent control: ${d.control}`, 'ok');
  } catch (e) { status(String(e.message || e), 'err'); }
}
window.leeAgentControl = leeAgentControl;

async function leeAgentAttach(path = '') {
  const value = String(path || '').trim();
  if (!value) {
    const picked = window.prompt('Workspace image path');
    if (!picked) return;
    return leeAgentAttach(picked);
  }
  try {
    const d = await post('/agent/attachment', {path: value});
    lee.agentAttachments.set(d.path, d.name || d.path.split('/').pop());
    paintAgentAttachments();
    status('image attached', 'ok');
  } catch (e) { status(String(e.message || e), 'err'); }
}
window.leeAgentAttach = leeAgentAttach;

async function attachPastedImage(blob) {
  const reader = new FileReader();
  reader.onload = async () => {
    try {
      const d = await post('/agent/attachment', {data_url: reader.result});
      lee.agentAttachments.set(d.path, d.name || d.path.split('/').pop());
      paintAgentAttachments();
      status('pasted image attached', 'ok');
    } catch (e) { status(String(e.message || e), 'err'); }
  };
  reader.readAsDataURL(blob);
}

function initAgentComposer() {
  // before the guard: a conversation with no turns paints nothing, so a paint is too late to bind
  bindAgentTurnFolds($('#agentlog'));
  const input = $('#agentprompt'); if (!input || input.dataset.composerReady) return;
  input.dataset.composerReady = '1';
  $('[data-agent-pause]')?.addEventListener('click', pauseAgentAfterCurrent);
  $('[data-agent-stop]')?.addEventListener('click', stopAgent);
  /* A one-line box with a placeholder telling you to write in it takes Enter, or it eats what you
     typed. It is not in a form and has no default action, so Enter does nothing unless it is bound
     here. */
  const notify = $('#agentnotify'), reasoning = $('#agentreasoning');
  if (reasoning) reasoning.onchange = () => prefSet('agent', 'reasoning', reasoning.value);
  // Both are settings, and settings arrive over the network: painted from the cache, then again.
  const paint = () => {
    if (notify) notify.checked = agentNotifyEnabled();
    if (reasoning) reasoning.value = prefGet('agent', 'reasoning', '') || 'auto';
  };
  paint(); agentPrefsReady().then(paint);
  const grow = () => {
    input.style.height = 'auto';
    input.style.height = Math.min(190, Math.max(64, input.scrollHeight)) + 'px';
  };
  input.addEventListener('paste', e => {
    const image = [...(e.clipboardData?.items || [])].find(item => item.type.startsWith('image/'));
    if (image) { e.preventDefault(); attachPastedImage(image.getAsFile()); return; }
    const text = e.clipboardData?.getData('text/plain')?.trim();
    if (text && /(?:^|\s)(?:~\/|\/|[A-Za-z]:[\\/]|\.\.?[\/])[^\s]+\.(?:png|jpe?g|gif|webp|bmp)(?:$|\s)/i.test(text)) {
      e.preventDefault(); leeAgentAttach(text);
    }
  });
  input.addEventListener('input', () => {
    grow();
    // Coalesced, because each call walks the project tree. `agentSuggestSeq` drops a stale answer
    // only after the work has been done.
    clearTimeout(agentSuggestTimer);
    agentSuggestTimer = setTimeout(
      () => updateAgentSuggest().catch(e => status(String(e.message || e), 'err')), 90);
    clearTimeout(stateSuggestTimer); stateSuggestTimer = setTimeout(() => suggestAgentState(input.value), 420);
  });
  grow();
  input.addEventListener('keydown', e => {
    if ($('#agentsuggest')?.hidden) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault(); const d = e.key === 'ArrowDown' ? 1 : -1;
      lee.agentSuggestAt = (lee.agentSuggestAt + d + lee.agentSuggest.length) % lee.agentSuggest.length;
      paintAgentSuggest();
    } else if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); e.stopPropagation(); chooseAgentSuggest(); }
    else if (e.key === 'Escape') { e.preventDefault(); closeAgentSuggest(); }
  });
}
async function sendAgentCommand(line) {
  // a command is a person's input and a reply, so it folds like every other exchange
  const log = $('#agentlog'); if (!log) return;
  const card = agentTurnCard({prompt: line, route: 'command'}), body = turnBody(card);
  body.appendChild(userMessage(line)); log.appendChild(card);
  try {
    const d = await post('/agent/command', {line, thread: lee.agentThread || ''});
    if (/^\/reload(?:\s|$)/.test(line)) lee.agentVocabulary = null;
    if ('enabled' in d) window.leeLearningShown?.(d.enabled);
    if (d.settings) window.leePaintSubagentSettings?.(d.settings);
    if (/^\/model\s+tools(?:\s|$)/.test(line)) window.leeLoadAgentSettings?.();
    const out = document.createElement('div'); out.className = 'lee-reply lee-agent-reply'; body.appendChild(out);
    renderMarkdown(out, d.text || ''); log.scrollTop = log.scrollHeight;
    status('command finished', 'ok');
  } catch (e) { status(String(e.message || e), 'err'); }
}

