/* Most callers pass no state, and a steer is not theirs to forget. Only a payload carrying
   `queued_steer` may change it, so the acknowledgement survives until the server says the steer
   was taken. */
function updateAgentRunstrip(state = {}) {
  const strip = $('#agentrunstrip'); if (!strip) return;
  if ('queued_steer' in state) setQueuedSteer(state.queued_steer || '');
  if ('runs' in state) lee.agentRuns = state.runs || [];
  const runs = lee.agentRuns || [], active = runs.length > 0;
  strip.hidden = !active && !lee.agentBusy && !state.waiting;
  updateAgentSendMode(active || lee.agentBusy ? 'steer' : 'send');
  const rootLabel = state.waiting ? `Waiting · ${state.waiting}`
    : lee.queuedSteer ? 'Steering queued · applies after the current tool call'
    : state.run_policy ? `Running automatically · ${runPolicyLabel(state.run_policy)}`
    : `${($('#agentcontrol')?.value || 'guided').toUpperCase()} · agent working`;
  const flattenRuns = rows => rows.flatMap(r => [r, ...flattenRuns(r.children || [])]);
  const flat = flattenRuns(runs);
  // A fan-out's rows tell each other apart only by what each subagent was asked, and the buttons'
  // row leaves that a dozen characters. The rows take the width and the buttons go under them.
  strip.classList.toggle('fanned', flat.length > 1);
  $('.lee-agent-run-state', strip).innerHTML = flat.length ? flat.map(r => {
    const elapsed = r.started ? Math.max(0, Date.now() / 1000 - r.started) : 0;
    const clock = `${Math.floor(elapsed / 60)}:${String(Math.floor(elapsed % 60)).padStart(2, '0')}`;
    // the model repeats on every row of a fan-out; the question does not
    const who = r.kind === 'child' ? `subagent ${(r.model || '').split('/').pop()}`.trim() : (r.model || 'Agent');
    const label = r.state === 'cancelling' ? `Cancelling ${who}…` : `${r.question || rootLabel} · ${who}`;
    return `<span class="lee-agent-run"><span>${esc(label)}</span>` +
      `<time>${esc(clock)}</time><button type="button" data-stop-run="${esc(r.id)}">Stop</button></span>`;
  }).join('') : esc(rootLabel);
  $$('[data-stop-run]', strip).forEach(btn => btn.onclick = async e => {
    e.stopPropagation();
    try { const d = await post(`/agent/runs/${encodeURIComponent(btn.dataset.stopRun)}/cancel`, {}); updateAgentRunstrip({runs: (await api('/agent/runs')).runs}); status(d.state, 'ok'); }
    catch (err) { status(err.message || String(err), 'err'); }
  });
}
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
  if (live?.root?.isConnected) live.append(card); else log.appendChild(card);
  log.scrollTop = log.scrollHeight;
  return card;
}
function setQueuedSteer(text, shown = '', cancel = false) {
  lee.queuedSteer = text || '';
  const log = $('#agentlog'), old = $('#agentqueuedsteer'); if (!log) return;
  if (!lee.queuedSteer) {
    if (cancel) { old?.remove(); return; }
    if (old) { old.classList.remove('queued'); $('[data-cancel-steer]', old)?.remove(); return; }
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

// An approval must not sit unseen while the model works. Idle, only a background job raises one.
async function approvalLoop() {
  if (!document.hidden) await pollApproval();
  // attention is about the conversations a person is *not* looking at, so it is polled even hidden
  try { await refreshAgentThreads(); } catch (_) {}
  setTimeout(approvalLoop, document.hidden ? 5000 : lee.agentBusy ? 750 : 5000);
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
    `<span class="lee-agent-step-meta">${steered ? 'steered'
      : a.done && a.secs ? esc(Number(a.secs).toFixed(1) + 's') : esc(a.kind || '')}</span>` +
    `<span class="lee-agent-step-chevron" aria-hidden="true"></span>`;
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
function paintAgentAttachments() {
  const host = $('#agentattachments'); if (!host) return;
  const active = lee.path ? `<span class="lee-agent-context" title="The assistant can see the active workspace and open files">` +
    `<span>active · ${esc(compactPath(lee.path))}</span></span>` : '';
  const states = lee.stateSuggestions.map(s => `<button type="button" class="lee-agent-state-suggestion" data-state-id="${esc(s.id)}" ` +
    `title="Preview and attach this remembered starting state">state · ${esc(s.title)}</button>`).join('');
  const sels = lee.agentSelections.map((s, i) =>
    `<span class="lee-agent-attachment selection" title="${esc(s.path)}"><span>${esc(s.label)}</span>` +
    `<button type="button" data-sel="${i}" aria-label="remove ${esc(s.label)}">remove</button></span>`).join('');
  const vaulted = [...lee.vaultRefs.entries()].map(([key, r]) =>
    `<span class="lee-agent-attachment vault" title="${esc(r.vault || 'vault')} · ${esc(r.shelf || 'main')}">` +
    `<span>${esc(r.title)}</span>` +
    `<button type="button" data-vault-ref="${esc(key)}" aria-label="remove ${esc(r.title)}">remove</button></span>`).join('');
  host.innerHTML = active + sels + vaulted + [...lee.agentAttachments.entries()].map(([path, name]) =>
    `<span class="lee-agent-attachment${name.endsWith('/') ? ' folder' : ''}" title="${esc(path)}"><span>${esc(name)}</span>` +
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
  if (item.kind === 'command') input.value = `/${item.name} `;
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
async function leeAgentControl(control) {
  try {
    const d = await post('/agent/control', {control});
    const select = $('#agentcontrol'); if (select) select.value = d.control;
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
  const input = $('#agentprompt'); if (!input || input.dataset.composerReady) return;
  input.dataset.composerReady = '1';
  $('[data-agent-pause]')?.addEventListener('click', pauseAgentAfterCurrent);
  $('[data-agent-stop]')?.addEventListener('click', stopAgent);
  /* A one-line box with a placeholder telling you to write in it takes Enter, or it eats what you
     typed. It is not in a form and has no default action, so Enter does nothing unless it is bound
     here. */
  const notify = $('#agentnotify'); if (notify) notify.checked = agentNotifyEnabled();
  const reasoning = $('#agentreasoning');
  if (reasoning) {
    reasoning.value = localStorage.getItem('lee-agent-reasoning') || 'auto';
    reasoning.onchange = () => localStorage.setItem('lee-agent-reasoning', reasoning.value);
  }
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
  const log = $('#agentlog'); log?.appendChild(userMessage(line));
  try {
    const d = await post('/agent/command', {line, thread: lee.agentThread || ''});
    if (/^\/reload(?:\s|$)/.test(line)) lee.agentVocabulary = null;
    const out = document.createElement('div'); out.className = 'lee-reply lee-agent-reply'; log?.appendChild(out);
    renderMarkdown(out, d.text || ''); if (log) log.scrollTop = log.scrollHeight;
    status('command finished', 'ok');
  } catch (e) { status(String(e.message || e), 'err'); }
}

