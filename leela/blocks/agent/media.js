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
async function sendAgent() {
  if (lee.agentBusy) return status('the model is already working', 'err');
  if (lee.agentView && lee.agentView !== 'live') restoreAgentLive();
  const el = $('#agentprompt'); if (!el || !el.value.trim()) return;
  const q = el.value.trim(); el.value = ''; el.style.height = '64px'; closeAgentSuggest();
  if (q.startsWith('/')) {
    try { lee.agentVocabulary ||= await api('/agent/commands'); } catch (_) {}
    const head = q.slice(1).split(/\s/, 1)[0];
    if ((lee.agentVocabulary?.commands || []).some(c => c.name === head)) return sendAgentCommand(q);
  }
  const attachments = [...lee.agentAttachments.keys(), ...lee.agentSelections.map(s => s.ref),
                       ...lee.vaultRefs.values()];
  lee.agentAttachments.clear(); lee.agentSelections = []; lee.vaultRefs.clear(); paintAgentAttachments();
  lee.agentBusy = true; setAgentStatus('working'); updateAgentRunstrip(); refreshAgentBudget();
  const log = $('#agentlog'); $('.lee-agent-welcome', log)?.remove();
  log.appendChild(userMessage(q)); log.scrollTop = log.scrollHeight;
  status('model is working…');

  const progress = agentProgress(log);
  const acts = document.createElement('div');
  acts.className = 'lee-agent-steps';
  const out = document.createElement('div');
  out.className = 'lee-reply lee-agent-reply';
  log.appendChild(acts); log.appendChild(out); log.scrollTop = log.scrollHeight;
  const body = out, seen = new Map(); let raw = '', finished = false;

  const reasoning = $('#agentreasoning')?.value || 'auto';
  const es = new EventSource('/agent/stream?prompt=' + encodeURIComponent(q) +
    '&attachments=' + encodeURIComponent(JSON.stringify(attachments)) +
    '&reasoning=' + encodeURIComponent(reasoning));

  es.addEventListener('activity', ev => {
    const a = JSON.parse(ev.data);
    let row = seen.get(a.id);
    if (!row) {
      row = document.createElement('details'); acts.appendChild(row); seen.set(a.id, row);
      row.animate([{opacity: 0, transform: 'translateY(4px)'}, {opacity: 1, transform: 'translateY(0)'}],
                  {duration: 220, easing: 'cubic-bezier(.16,1,.3,1)'});
    }
    renderAgentStep(row, a); refreshAgentBudget();
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
  });

  es.addEventListener('chunk', ev => {
    raw += JSON.parse(ev.data).text || '';
    progress.phase('Writing response');
    renderMarkdown(body, raw);
    log.scrollTop = log.scrollHeight;
  });

  es.addEventListener('approval', ev => { progress.phase('Waiting for your approval'); showApproval(JSON.parse(ev.data)); });
  es.addEventListener('execution', ev => updateAgentRunstrip(JSON.parse(ev.data)));
  es.addEventListener('run', ev => {
    const run = JSON.parse(ev.data); lee.agentRuns = (lee.agentRuns || []).filter(r => r.id !== run.id);
    lee.agentBusy = false; setAgentStatus('ready'); progress.finish(run.state !== 'detached'); updateAgentRunstrip({runs: lee.agentRuns});
    status(run.state === 'detached' ? 'provider detached; no further output will be used' : run.state, 'ok'); es.close();
  });
  es.addEventListener('compaction', ev => {
    const d = JSON.parse(ev.data), note = document.createElement('details'); note.className = 'lee-compaction-event';
    note.innerHTML = `<summary>Context compacted automatically · ${esc(d.strategy)} · ${esc(d.note)}</summary><pre>${esc(d.text || '')}</pre>`;
    acts.appendChild(note); progress.phase('Context compacted; continuing from checkpoint');
  });

  es.addEventListener('error', ev => {
    try { raw += JSON.parse(ev.data).error || ''; renderMarkdown(body, raw); } catch (_) {}
  });

  es.addEventListener('done', async ev => {
    finished = true; lee.agentBusy = false; lee.agentRuns = []; setAgentStatus('ready'); es.close(); progress.finish(true); updateAgentRunstrip({runs: []}); refreshAgentBudget();
    const d = JSON.parse(ev.data);
    addResponseRevision(out, d.turn_id, raw, d.capabilities || {});
    drawTurnMedia(out, d.media);
    const usage = usageMeta(d.usage, d.usage_label, d.model); if (usage) out.after(usage);
    for (const e of (d.edits || []))
      agentLog(`<div class="lee-runline"><span class="sub">✎ ${esc(e.path.split('/').pop())} ${esc(e.label)}</span></div>` +
               `<div class="lee-diff inline">${diffHtml(e.rows)}</div>`);
    const tail = d.usage_label ? `${d.note || 'done'} · ${d.usage_label}` : (d.note || 'done');
    showProblems(d.problems);
    if ((d.problems || []).length) status(d.problems[d.problems.length - 1], 'err');
    else status(d.ok ? tail : (d.note || 'assistant unavailable'), d.ok ? 'ok' : 'err');
    await reloadAfterEdits(d.edits || []);
  });

  // A dropped connection must clear both the functional busy lock and its visual state.
  es.onerror = () => {
    if (finished) return;
    lee.agentBusy = false; lee.agentRuns = []; setAgentStatus('ready'); progress.finish(false); updateAgentRunstrip({runs: []});
    status('the model stream ended before it returned a result', 'err'); es.close();
  };
}

