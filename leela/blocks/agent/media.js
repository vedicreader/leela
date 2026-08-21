/* A generated picture arrives as a data URL on the `done` event. The tool result the model
 * sees is a path, and a browser cannot draw a filename, so the bytes come separately. */
function drawTurnMedia(out, media) {
  for (const m of (media || [])) {
    const fig = document.createElement('figure');
    fig.className = 'lee-agent-media';
    fig.innerHTML = (m.mime || '').startsWith('video/')
      ? `<video controls src="${m.url}"></video>`
      : `<img src="${m.url}" alt="generated image">`;
    out.after(fig);
  }
}

function reduceAgentTimeline(events) {
  const parts = [], actions = new Map(); let prose = null;
  const seal = () => { prose = null; };
  for (const event of events || []) {
    const type = event.event || event.type, data = event.data || event;
    if (type === 'chunk') {
      if (!prose) { prose = {kind: 'prose', text: ''}; parts.push(prose); }
      prose.text += data.text || ''; continue;
    }
    if (type !== 'activity') { seal(); parts.push({kind: type, data}); continue; }
    const id = data.action_id || data.id;
    /* An update to a call already on screen is not a new position in the timeline, so only a
       call seen for the first time closes the open prose. A row with no id has no identity to
       update, so it can only ever be new -- and it is still work a person did. */
    let part = id ? actions.get(id) : null;
    if (!part) {
      seal();
      part = {kind: 'activity', id: id || '', parent: data.parent_action_id || '', data, children: []};
      if (id) actions.set(id, part);
      parts.push(part);
    }
    else part.data = data;
    if (!id) continue;
    if (part.parent && actions.has(part.parent)) {
      const parent = actions.get(part.parent), at = parts.indexOf(part);
      if (at >= 0) parts.splice(at, 1);
      if (!parent.children.includes(part)) parent.children.push(part);
    }
    for (const child of [...parts]) if (child.kind === 'activity' && child.parent === id) {
      parts.splice(parts.indexOf(child), 1); if (!part.children.includes(child)) part.children.push(child);
    }
  }
  return parts;
}

function agentTimeline(root) {
  const actions = new Map(); let prose = null;
  const seal = () => { prose = null; };
  const activity = a => {
    const id = a.action_id || a.id; if (!id) return null;
    let held = actions.get(id), row = held?.row;
    if (!row) {
      seal();
      row = document.createElement('details'); held = {row, parent: a.parent_action_id || '', children: null};
      actions.set(id, held); root.appendChild(row);
    }
    held.parent = a.parent_action_id || held.parent;
    const children = held.children; if (children) children.remove();
    renderAgentStep(row, a); if (children) { row.appendChild(children); held.children = children; }
    if (held.parent && actions.has(held.parent)) {
      const parent = actions.get(held.parent);
      parent.children ||= (() => { const box = document.createElement('div'); box.className = 'lee-agent-children'; parent.row.appendChild(box); return box; })();
      parent.children.appendChild(row);
    }
    for (const child of actions.values()) if (child.parent === id && child.row.parentElement === root) {
      held.children ||= (() => { const box = document.createElement('div'); box.className = 'lee-agent-children'; row.appendChild(box); return box; })();
      held.children.appendChild(child.row);
    }
    return row;
  };
  return {root, actions, seal, activity, chunk(text) {
    if (!prose) { prose = document.createElement('div'); prose.className = 'lee-reply lee-agent-reply lee-timeline-prose'; prose._text = ''; root.appendChild(prose); }
    prose._text += text || ''; renderMarkdown(prose, prose._text); return prose;
  }, append(node) { seal(); if (node) root.appendChild(node); return node; }};
}

function setAgentStatus(state, title) {
  const el = $('#agentstatus'); if (!el) return;
  el.classList.remove('working', 'ready', 'idle'); el.classList.add(state);
  el.title = title || (state === 'working' ? 'agent is working' : state === 'ready' ? 'agent ready' : 'agent idle');
  const dot = $('.lee-agent-status-dot', el); if (dot) dot.setAttribute('aria-label', el.title);
  const text = state === 'working' ? 'working' : state === 'ready' ? 'ready' : 'idle';
  [...el.childNodes].find(n => n.nodeType === Node.TEXT_NODE)?.replaceWith(document.createTextNode(text));
}

// The assistant's tools edit files on disk, so a turn can change what is on screen.
// Activity, answer chunks, and final diffs stream independently; each tool row is updated
// in place so pending work never remains on screen after that step has finished.
async function sendAgent(force = false) {
  if (lee.agentBusy) return force ? leeForceSteer() : leeQueueSteer();
  if (lee.agentView && lee.agentView !== 'live') restoreAgentLive();
  const el = $('#agentprompt'); if (!el || !el.value.trim()) return;
  const q = el.value.trim(); closeAgentSuggest();
  if (q.startsWith('/')) {
    try { lee.agentVocabulary ||= await api('/agent/commands'); } catch (_) {}
    const head = q.slice(1).split(/\s/, 1)[0];
    if ((lee.agentVocabulary?.commands || []).some(c => c.name === head)) return sendAgentCommand(q);
  }
  const attachments = [...lee.agentAttachments.keys(), ...lee.agentSelections.map(s => s.ref),
                       ...lee.vaultRefs.values()];
  const reasoning = $('#agentreasoning')?.value || 'auto';
  let accepted;
  try { accepted = await post('/agent/turn', {prompt: q, attachments, reasoning, thread: lee.agentThread || ''}); }
  catch (e) { el.value = q; return status(e.message || String(e), 'err'); }
  el.value = ''; el.style.height = '64px';
  lee.agentAttachments.clear(); lee.agentSelections = []; lee.vaultRefs.clear(); paintAgentAttachments();
  lee.agentBusy = true; setAgentStatus('working'); updateAgentRunstrip(); refreshAgentBudget();
  const log = $('#agentlog'); $('.lee-agent-welcome', log)?.remove();
  log.appendChild(userMessage(q)); log.scrollTop = log.scrollHeight;
  status('model is working…');
  agentListen(accepted.thread || lee.agentThread, accepted.seq);
}

/* One conversation's feed, painted into the live pane. `sendAgent` calls this for the turn it
   just started; a thread switch calls it for a turn already running, replaying from the feed's
   last settled point so only the turn in flight is drawn again. */
function agentListen(thread, since) {
  const log = $('#agentlog'); if (!log) return;
  $('.lee-agent-welcome', log)?.remove();
  const progress = agentProgress(log);
  const timelineRoot = document.createElement('div'); timelineRoot.className = 'lee-agent-timeline';
  log.appendChild(timelineRoot); log.scrollTop = log.scrollHeight;
  const timeline = agentTimeline(timelineRoot), seen = timeline.actions;
  let raw = '', runDone = false, lastSeq = since, body = null;
  if (lee.agentStream) { lee.agentStream._leeStopped = true; lee.agentStream.close(); }
  const generation = ++lee.agentStreamGen; let es, reconnecting = false;
  const reconnect = ms => { if (reconnecting || generation !== lee.agentStreamGen) return; reconnecting = true; setTimeout(() => { reconnecting = false; if (generation === lee.agentStreamGen) connect(); }, ms); };
  const connect = () => {
    es = new EventSource('/agent/stream?since=' + lastSeq + '&follow=1' +
      (thread ? '&thread=' + encodeURIComponent(thread) : '')); lee.agentStream = es;
    /* EventSource fires `error` for a dropped socket as well as for a frame the server named
       `error`, and the dropped one carries no data. Parsing it would throw before the handler. */
    const dedupe = fn => ev => {
      if (typeof ev.data !== 'string') return;
      let d; try { d = JSON.parse(ev.data); } catch (_) { return; }
      if (d.seq <= lastSeq) return;
      lastSeq = d.seq; fn(d, ev);
    };

  es.addEventListener('activity', dedupe(a => {
    const fresh = !seen.has(a.action_id || a.id), row = timeline.activity(a);
    if (fresh && row) row.animate([{opacity: 0, transform: 'translateY(4px)'}, {opacity: 1, transform: 'translateY(0)'}],
      {duration: 220, easing: 'cubic-bezier(.16,1,.3,1)'});
    refreshAgentBudget();
    const lifecycle = approvalCards.get(a.action_id || a.id);
    if (lifecycle && a.done) {
      lifecycle.classList.remove('running', 'proposed'); lifecycle.classList.add(a.ok ? 'complete' : 'failed');
      const actions = $('.lee-approval-actions', lifecycle);
      if (actions && !lifecycle.querySelector('.lee-checkpoint-result'))
        actions.before(checkpointResult(a.detail, a.ok, a.secs));
      const checkpointState = $('.lee-checkpoint-title small', lifecycle);
      if (checkpointState) checkpointState.textContent = a.ok ? 'Completed' : 'Tool failed';
      const actionState = $('.lee-approval-actions > span', lifecycle);
      if (actionState) actionState.innerHTML = a.ok
        ? (lifecycle.dataset.retryable === 'true'
            ? '<strong>Completed</strong><small>You can rerun this read-only tool without changing the conversation.</small>'
            : '<strong>Completed</strong><small>To run it again, ask the agent so you can review a new checkpoint.</small>')
        : '<strong>Failed</strong><small>The output above explains what the tool returned.</small>';
      updateAgentRunstrip();
    }
    if (a.done && a.ok && a.kind === 'edit' && a.args?.path) scheduleAgentFileReload(a.args.path);
    progress.phase(a.done ? 'Reviewing tool results' : (a.summary || `Running ${a.tool}`));
    log.scrollTop = log.scrollHeight;
  }));

  /* A turn already in flight when this pane attached: its prompt is in the feed, not on screen.
     `sendAgent` replays from its own user event, so it never arrives twice. */
  es.addEventListener('user', dedupe(d => {
    log.insertBefore(userMessage(d.text || ''), timelineRoot); log.scrollTop = log.scrollHeight;
  }));

  es.addEventListener('chunk', dedupe(d => {
    raw += d.text || ''; body = timeline.chunk(d.text || '');
    progress.phase('Writing response');
    log.scrollTop = log.scrollHeight;
  }));

  es.addEventListener('approval', dedupe(d => { timeline.seal(); progress.phase('Waiting for your approval'); showApproval(d, timelineRoot); }));
  es.addEventListener('execution', dedupe(d => updateAgentRunstrip(d)));
  es.addEventListener('state', dedupe(d => updateAgentRunstrip(d)));
  es.addEventListener('steer', dedupe(d => {
    timeline.seal(); if ('queued_steer' in d) setQueuedSteer(d.queued_steer || '', d.text || '');
  }));
  es.addEventListener('title', dedupe(d => { if (d.title) lee.agentTitle = titleText(d.title); }));
  /* Only a stopped run is announced here. `done` still follows and owns the end of the turn, so
     this says what happened to the run and touches nothing `done` will set. */
  es.addEventListener('run', dedupe(run => {
    timeline.seal(); lee.agentRuns = (lee.agentRuns || []).filter(r => r.id !== run.id);
    updateAgentRunstrip({runs: lee.agentRuns});
    status(run.state === 'detached' ? 'provider detached; no further output will be used' : run.state, 'ok');
  }));
  es.addEventListener('compaction', dedupe(d => {
    timeline.seal(); const note = document.createElement('details'); note.className = 'lee-compaction-event';
    note.innerHTML = `<summary>Context compacted automatically · ${esc(d.strategy)} · ${esc(d.note)}</summary><pre>${esc(d.text || '')}</pre>`;
    timelineRoot.appendChild(note); progress.phase('Context compacted; continuing from checkpoint');
  }));

  es.addEventListener('error', dedupe((d, ev) => {
    ev.stopImmediatePropagation(); raw += d.message || ''; body = timeline.chunk(d.message || '');
  }));
  /* The feed no longer holds what this tab missed, so the turns come from history instead --
     `/agent/transcript` carries executed cells, never the conversation. Nothing on screen is
     cleared until the replacement is in hand. */
  es.addEventListener('resync', dedupe(async d => {
    es.close();
    try {
      const history = await api('/agent/history' + (thread ? '?thread=' + encodeURIComponent(thread) : '')),
            sessions = history.sessions || [];
      const group = sessions.find(s => s.id === thread) || sessions.find(s => s.id === history.current);
      const turns = await sessionTurns(group?.id);
      if (!turns.length) throw new Error('no recorded turns for this conversation');
      log.innerHTML = ''; renderTurns(log, turns, 'Recovered conversation');
      log.scrollTop = log.scrollHeight; lastSeq = d.latest; reconnect(0);
    } catch (e) {
      status('conversation replay failed; retrying without clearing the transcript', 'err');
      reconnect(1000);
    }
  }));

  es.addEventListener('done', dedupe(async d => {
    timeline.seal(); runDone = true; lee.agentBusy = false; lee.agentRuns = []; setAgentStatus('ready'); progress.finish(true); updateAgentRunstrip({runs: []}); refreshAgentBudget();
    // a turn that ended on a call has no prose block, and its pictures are still its own
    const closing = body || timelineRoot;
    addResponseRevision(closing, d.turn_id, raw, d.capabilities || {}); drawTurnMedia(closing, d.media);
    const usage = usageMeta(d.usage, d.usage_label, d.model); if (usage) timelineRoot.appendChild(usage);
    for (const e of (d.edits || []))
      agentLog(`<div class="lee-runline"><span class="sub">✎ ${esc(e.path.split('/').pop())} ${esc(e.label)}</span></div>` +
               `<div class="lee-diff inline">${diffHtml(e.rows)}</div>`);
    const tail = d.usage_label ? `${d.note || 'done'} · ${d.usage_label}` : (d.note || 'done');
    showProblems(d.problems);
    if ((d.problems || []).length) status(d.problems[d.problems.length - 1], 'err');
    else status(d.ok ? tail : (d.note || 'assistant unavailable'), d.ok ? 'ok' : 'err');
    await reloadAfterEdits(d.edits || []);
  }));

  es.onerror = () => {
    if (es._leeStopped || generation !== lee.agentStreamGen) return;
    es.close(); status(runDone ? 'connection lost; restoring conversation updates…' : 'connection lost; replaying the running turn…', 'busy'); reconnect(500);
  };
  };
  connect();
}

