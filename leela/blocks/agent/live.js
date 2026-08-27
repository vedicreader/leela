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

/* One turn is one card, so what has been read can be folded away. Everything a turn paints goes
   in its body: the live path used to append the prompt, the progress strip, the timeline and the
   closing diffs as flat siblings of the log, which is why `markTurnUndone` had to guess a turn's
   extent by walking to the next `.lee-user-message`. */
/* Scoped to whatever session was painted, which is not always the live thread: history view paints
   another conversation's turns while `lee.agentThread` still names the live one. */
const foldScope = () => $('#agentlog')?.dataset.foldScope || lee.agentThread || 'default';
const foldKey = () => `lee-agent-folded:${foldScope()}`;
const foldedTurns = () => { try { return new Set(JSON.parse(localStorage.getItem(foldKey()) || '[]')); } catch { return new Set(); } };
const saveFolded = set => { try { localStorage.setItem(foldKey(), JSON.stringify([...set].slice(-400))); } catch {} };

function agentTurnCard({prompt = '', model = '', route = '', turnId = ''} = {}) {
  const card = document.createElement('article'); card.className = 'lee-agent-turn';
  if (turnId) card.dataset.turn = turnId;
  const meta = [model, route].filter(Boolean).join(' · ');
  card.innerHTML = `<header class="lee-agent-turn-head"><button class="lee-agent-turn-fold" type="button"` +
    ` aria-expanded="true" title="fold this turn. Hold alt for every turn">` +
    `<i class="lee-agent-step-chevron" aria-hidden="true"></i></button>` +
    `<span class="lee-agent-turn-title"></span><span class="lee-agent-turn-meta">${esc(meta)}</span></header>` +
    `<div class="lee-agent-turn-body"></div>`;
  // textContent, not the template: a prompt is whatever was typed
  $('.lee-agent-turn-title', card).textContent = String(prompt).replace(/\s+/g, ' ').trim() || '(no prompt)';
  return card;
}
const turnBody = card => card && $('.lee-agent-turn-body', card);
/* A checkpoint the agent is blocked on must never sit behind a fold: its buttons and its ↵ / E / S
   keys are the only way the run continues, and a folded body cannot be focused or clicked. */
const turnAwaitingApproval = card => !!$('.lee-approval.proposed', card);
const unfoldForApproval = node => foldAgentTurn(node?.closest?.('.lee-agent-turn'), false);

function foldAgentTurn(card, folded) {
  if (!card || (folded && turnAwaitingApproval(card))) return;
  card.classList.toggle('folded', folded);
  $('.lee-agent-turn-fold', card)?.setAttribute('aria-expanded', String(!folded));
  turnBody(card)?.setAttribute('aria-hidden', String(folded));
  const id = card.dataset.turn; if (!id) return;
  const set = foldedTurns(); folded ? set.add(id) : set.delete(id); saveFolded(set);
}
const agentTurnCards = () => $$('.lee-agent-turn', $('#agentlog') || document);
function foldAgentTurns(folded) { for (const card of agentTurnCards()) foldAgentTurn(card, folded); }
/* What has been answered is not what is being read. A conversation of any length is mostly turns
   already dealt with, so every one before the newest is folded away: on a paint, and again when the
   next turn begins. A turn holding a checkpoint is never folded, because `foldAgentTurn` refuses. */
function foldOlderTurns(log, keep = 1) {
  const cards = $$('.lee-agent-turn', log || $('#agentlog') || document);
  cards.slice(0, Math.max(0, cards.length - keep)).forEach(card => foldAgentTurn(card, true));
}
/* The newest turn is the one being read, so it is never folded from storage: a turn folded before
   a resume would otherwise hide the answer a person came back for. */
function applyStoredFolds(log) {
  const cards = $$('.lee-agent-turn', log), stored = foldedTurns();
  cards.forEach((card, i) => { if (i < cards.length - 1 && stored.has(card.dataset.turn)) foldAgentTurn(card, true); });
}
/* `renderTurns` paints durable turns only, so on a resync the turn in flight is appended after it
   has already decided which card is newest. Re-applied once that card exists. */
const refoldAfter = log => applyStoredFolds(log);
/* One listener on the log, bound from `initAgentComposer` rather than from a paint: a conversation
   with no turns paints nothing, and the log element itself outlives every repaint. */
function bindAgentTurnFolds(log) {
  if (!log || log._leeFoldsBound) return;
  log._leeFoldsBound = true;
  log.addEventListener('click', e => {
    const button = e.target.closest?.('.lee-agent-turn-fold'); if (!button) return;
    const card = button.closest('.lee-agent-turn'), folded = !card.classList.contains('folded');
    if (e.altKey) foldAgentTurns(folded); else foldAgentTurn(card, folded);
  });
}
const latestAgentTurn = () => agentTurnCards().at(-1);
/* the turn being read: whichever card holds focus, or the newest, which is where focus is when it
   is in the composer. Only for what a person aimed at; anything the server sends goes to the
   newest, or a checkpoint would land in whichever old turn happened to hold focus */
const currentAgentTurn = () => document.activeElement?.closest?.('.lee-agent-turn') || latestAgentTurn();

function renderTurns(log, turns, heading, fold = true) {
  if (heading) log.insertAdjacentHTML('beforeend', `<div class="lee-vgroup">${esc(heading)}</div>`);
  for (const turn of (turns || [])) {
    const card = agentTurnCard({prompt: turn.prompt, model: turn.model, route: turn.plan?.route || 'direct',
                               turnId: turn.turn_id || ''});
    const item = turnBody(card);
    item.appendChild(userMessage(turn.prompt));
    let closing = null;
    if ((turn.timeline || []).length) {
      const root = document.createElement('div'); root.className = 'lee-agent-timeline'; item.appendChild(root);
      const paint = agentTimeline(root);
      const paintActivity = part => {
        paint.activity(part.data);
        for (const child of part.children || []) paintActivity(child);
      };
      for (const part of reduceAgentTimeline(turn.timeline)) {
        if (part.kind === 'prose') closing = paint.chunk(part.text);
        else if (part.kind === 'activity') paintActivity(part);
        // what the person said mid-turn, in the place they said it
        else if (part.kind === 'steer' && part.data?.text) paint.append(userMessage(part.data.text));
      }
      closing = closing || root;
    } else {
      if ((turn.activity || []).length) {
        const steps = document.createElement('div'); steps.className = 'lee-agent-steps';
        for (const activity of turn.activity) {
          const row = document.createElement('details'); renderAgentStep(row, activity); steps.appendChild(row);
        }
        item.appendChild(steps);
      }
      const reply = document.createElement('div'); reply.className = 'lee-reply'; item.appendChild(reply);
      renderMarkdown(reply, turn.reply || '');
      closing = reply;
    }
    /* The revision bar used to be added by the live `done` handler alone, so undo, restore and
       edit-what-the-agent-remembers vanished on every history toggle, resume, thread switch and
       resync. It is painted from the turn record here, and the server says whether the operations
       behind it can still be reached in this process. */
    addResponseRevision(closing, turn.turn_id, turn.reply || '', turn.capabilities || {});
    const usage = usageMeta(turn.usage, turn.usage_label, turn.model); if (usage) item.appendChild(usage);
    log.appendChild(card);
  }
  applyStoredFolds(log);
  if (fold) foldOlderTurns(log);
}
/* A summarised title arrives as `Title: Ramabana CLI ASCII`, quotes and all, and stored ones keep
   the prefix after the storage point is fixed, so every display cleans it. */
const titleText = t => String(t || '').replace(/\s+/g, ' ').trim()
  .replace(/^title\s*:\s*/i, '').replace(/^["'“”‘’]+|["'“”‘’]+$/g, '').trim();
const sessionTime = s => s.started ? new Date(s.started * 1000).toLocaleString() : s.id.replace(/^agent_/, '');
/* `/agent/history` lists conversations without their turns, since Leela and the CLI share one log.
   The turns of the one being opened come from here, and `count` is what the list knows about the
   rest. */
const sessionTurns = async id => {
  if (!id) return [];
  try { return (await api('/agent/history/session?id=' + encodeURIComponent(id))).turns || []; }
  catch (e) { status(String(e.message || e), 'err'); return []; }
};
/* Leela and the ramabana CLI append to one log, and only Leela marks the sessions it started, so
   anything unmarked reads as the CLI's, including Leela's history from before the mark. */
/* Checked unless it has been turned off: one log holds both, most of it is the CLI's, and the
   list a person opens is their own work. Asking the server means the CLI's are not grouped and
   shipped only to be filtered out here. */
const leelaOnly = () => localStorage.getItem('leeHistoryLeelaOnly') !== '0';
const shownSessions = groups => leelaOnly() ? groups.filter(s => s.app === 'leela') : groups;
async function historyGroups() {
  const d = await api('/agent/history' + (leelaOnly() ? '' : '?everything=1'));
  lee.agentHistoryHidden = d.hidden || 0;
  return d.sessions || [];
}
async function showHistorySession(group, groups) {
  const log = $('#agentlog'); if (!log) return; log.innerHTML = ''; approvalCards.clear();
  log.dataset.foldScope = group?.id || '';   // these turns are that session's, whatever thread is live
  const index = document.createElement('nav'); index.className = 'lee-history-index';
  /* A conversation is known by what it was about, so its name is the whole option. The time
     identifies one that has no name yet, which is every conversation before its first turn
     finished. */
  const all = groups || [], shown = shownSessions(all);
  const hidden = (all.length - shown.length) || lee.agentHistoryHidden || 0;
  const options = shown.map(s =>
    `<option value="${esc(s.id)}"${s.id === group?.id ? ' selected' : ''}>` +
    `${esc(titleText(s.title) || sessionTime(s))}</option>`).join('');
  const turns = group ? await sessionTurns(group.id) : [];
  const resumable = !!group && !group.id.startsWith('legacy-') && turns.length > 0;
  index.innerHTML = `<div class="lee-history-heading"><strong>History</strong>` +
    `<span>one continuous model context per session</span></div>` +
    `<select class="lee-select lee-history-select" aria-label="agent history session">${options}</select>` +
    `<label class="lee-history-filter" title="Hide conversations this Leela did not start. History from before this filter existed is unmarked and hides with them.">` +
    `<input type="checkbox" class="lee-history-leelaonly"${leelaOnly() ? ' checked' : ''}> Leela only` +
    `${hidden ? ` <span class="lee-dim">(${hidden} hidden)</span>` : ''}</label>` +
    `<span class="lee-history-runs">${group?.code || 0} kernel run${group?.code === 1 ? '' : 's'}</span>` +
    (resumable ? `<button class="lee-btn go lee-history-resume" title="Continue this conversation">Resume</button>` : '');
  index.querySelector('select')?.addEventListener('change', e =>
    showHistorySession(all.find(s => s.id === e.target.value), all));
  index.querySelector('.lee-history-leelaonly')?.addEventListener('change', async e => {
    localStorage.setItem('leeHistoryLeelaOnly', e.target.checked ? '1' : '0');
    // The CLI's conversations are not in `all` when the box was checked, so this asks again.
    const groups = await historyGroups(), left = shownSessions(groups);
    showHistorySession(left.find(s => s.id === group?.id) || left[0], groups);
  });
  index.querySelector('.lee-history-resume')?.addEventListener('click', () => leeAgentResume(group));
  log.appendChild(index);
  if (!group) { log.insertAdjacentHTML('beforeend', '<div class="lee-dim">(no sessions yet)</div>'); return; }
  log.insertAdjacentHTML('beforeend', `<div class="lee-history-session-head">` +
    `<strong>${esc(titleText(group.title) || sessionTime(group))}</strong>` +
    `<span>${titleText(group.title) ? `${esc(sessionTime(group))} · ` : ''}` +
    `${group.context_continues ? 'context continued across these turns' : 'separate context'}</span></div>`);
  renderTurns(log, turns, 'conversation');
  if (group.code || group.id.startsWith('agent_')) {
    const transcript = await api('/agent/transcript?session=' + encodeURIComponent(group.id));
    if ((transcript.cells || []).length) {
      log.insertAdjacentHTML('beforeend', '<div class="lee-vgroup">code executed in this session</div>');
      renderSessionCells(log, transcript);
    }
  }
  log.scrollTop = 0;
}
/* The live pane is DOM only, so a reload, an htmx swap of the shell, or a switch to a conversation
   this tab has never shown leaves it blank while the turns are still on disk. They come from the
   server and replace what is on screen, because painting into what is already there duplicated a
   transcript on the way back to it. */
async function paintAgentThread(id) {
  const log = $('#agentlog'); if (!log) return null;
  const d = await api('/agent/thread/turns' + (id ? '?thread=' + encodeURIComponent(id) : ''));
  const welcome = $('.lee-agent-welcome', log);
  approvalCards.clear();
  log.dataset.foldScope = '';
  if ((d.turns || []).length) { log.innerHTML = ''; renderTurns(log, d.turns, titleText(d.title) || 'conversation'); }
  else log.innerHTML = welcome ? welcome.outerHTML : '';
  lee.agentView = 'live'; $('#agenthistory')?.classList.remove('active');
  lee.agentLive = log.innerHTML; log.scrollTop = log.scrollHeight;
  return d;
}
/* Conversations live in the agent's log, not in this process, so a fresh one holds none: opening
   the app after working in a browser showed an empty pane while the work sat on disk. An empty pane
   picks the newest conversation back up, which is what "where was I" means. */
async function rehydrateAgentLive() {
  const log = $('#agentlog');
  if (!log || lee.agentView === 'history' || lee.agentBusy || lee.agentHydrating) return;
  lee.agentHydrating = true;
  try {
    const d = await paintAgentThread(lee.agentThread || '');
    if (!(d?.turns || []).length) await resumeLatestAgent();
  }
  catch (e) { /* an empty pane beats a boot that dies on a cold agent */ }
  finally { lee.agentHydrating = false; }
}
function paintResumed(d) {
  const log = $('#agentlog');
  if (log) {
    log.dataset.foldScope = ''; log.innerHTML = '';
    renderTurns(log, d.turns || [], 'resumed conversation');
    log.scrollTop = log.scrollHeight;
  }
  lee.agentView = 'live'; lee.agentLive = log?.innerHTML || '';
  $('#agenthistory')?.classList.remove('active');
}
async function resumeLatestAgent() {
  // Nothing saved is the first run, not a failure, so this never speaks up about it.
  try {
    const d = await post('/agent/resume', {session: 'latest'});
    if (!(d.turns || []).length) return;
    paintResumed(d);
    status(`picked up ${titleText(d.title) || d.session}`, 'ok');
  } catch (_) {}
}
function warmAgentHistory() {
  // Nothing is painted from it: this is the read that makes the next one cheap.
  historyGroups().catch(() => {});
}
async function leeAgentHistory() {
  if (lee.agentView === 'history') return restoreAgentLive();
  rememberAgentLive(); lee.agentView = 'history'; $('#agenthistory')?.classList.add('active');
  const all = await historyGroups();
  await showHistorySession(shownSessions(all)[0], all);
}
async function leeAgentResume(group) {
  if (!group) return;
  if (lee.agentBusy) return status('the model is already working', 'err');
  try {
    const d = await post('/agent/resume', {session: group.id});
    paintResumed(d);
    $('#agentprompt')?.focus();
    status(d.note || `resumed ${d.session}`, 'ok');
  } catch (e) { status(String(e.message || e), 'err'); }
}
function rememberAgentThread() {
  if (!lee.agentThread) return;
  lee.agentThreadDrafts.set(lee.agentThread, $('#agentprompt')?.value || '');
}
/* A conversation with nothing said in it has no name, and its id is a bare timestamp. Say what it
   is and when it started instead. */
function threadName(t) {
  const named = titleText(t.title); if (named) return named;
  const at = /(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})/.exec(t.id || '');
  return at ? `new conversation · ${at[4]}:${at[5]}` : 'new conversation';
}
function threadLabel(t) {
  return `${threadName(t)} · ${t.state}${t.unread ? ` · ${t.unread} new` : ''}${t.muted ? ' · muted' : ''}`;
}
/* One card per conversation, with its own controls, rather than a select plus four buttons that
   all acted on whichever one happened to be showing. */
function paintAgentThreads(d) {
  const rows = d.threads || [];
  lee.agentThreadRows = rows; lee.agentThread = d.active || lee.agentThread;
  const count = $('#agentthreadcount'); if (count) count.textContent = String(rows.length);
  const waiting = (d.attention?.waiting || []).length, unread = d.attention?.unread || 0;
  const toggle = $('#agentthreads');
  if (toggle) {
    toggle.classList.toggle('wants', !!waiting);
    toggle.classList.toggle('unread', !waiting && !!unread);
    toggle.title = waiting ? `${waiting} conversation(s) waiting for you`
      : unread ? `${unread} unread turn(s) elsewhere` : 'every live conversation';
  }
  const list = $('#agentthreadlist');
  if (list) {
    list.innerHTML = rows.map(t => {
      const live = t.id === d.active;
      return `<article class="lee-thread-card${live ? ' active' : ''}${t.state === 'waiting' ? ' wants' : ''}"` +
        ` role="option" aria-selected="${live}" tabindex="0" data-thread="${esc(t.id)}">` +
        `<header><strong>${esc(threadName(t))}</strong>` +
        `<span class="lee-thread-state ${esc(t.state)}">${esc(t.state)}</span></header>` +
        `<footer><span>${t.unread ? `${t.unread} new` : (live ? 'on screen' : 'idle')}` +
        `${t.muted ? ' · muted' : ''}</span><span class="lee-spacer"></span>` +
        `<button type="button" data-thread-rename title="rename">rename</button>` +
        `<button type="button" data-thread-mute title="${t.muted ? 'unmute' : 'silence notifications'}">${t.muted ? 'unmute' : 'mute'}</button>` +
        `<button type="button" data-thread-reshape title="edit this conversation as a notebook">edit</button>` +
        `<button type="button" data-thread-close class="warn" title="close">close</button></footer></article>`;
    }).join('') || '<div class="lee-dim">no live conversations</div>';
    list.insertAdjacentHTML('beforeend',
      `<footer class="lee-thread-list-foot"><label title="browser notification when a background ` +
      `conversation wants you"><input type="checkbox" id="agentnotify"${agentNotifyEnabled() ? ' checked' : ''}>` +
      `<span>notify me about background conversations</span></label></footer>`);
    $('#agentnotify', list).onchange = e => leeAgentNotifyToggle(e.target.checked);
    bindAgentThreadCards(list);
  }
  paintAgentAttention(d.attention || {}, rows);
}
function bindAgentThreadCards(list) {
  if (list._leeThreadsBound) return;
  list._leeThreadsBound = true;
  const cardId = e => e.target.closest('[data-thread]')?.dataset.thread || '';
  list.addEventListener('click', e => {
    const id = cardId(e); if (!id) return;
    const button = e.target.closest('button');
    if (!button) return leeAgentThreadOpen(id);
    if (button.hasAttribute('data-thread-rename')) return leeAgentThreadRename(id);
    if (button.hasAttribute('data-thread-mute')) return leeAgentThreadMute(id);
    if (button.hasAttribute('data-thread-reshape')) return leeAgentReshape(id);
    if (button.hasAttribute('data-thread-close')) return leeAgentThreadClose(id);
  });
  list.addEventListener('keydown', e => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const id = cardId(e); if (!id || e.target.closest('button')) return;
    e.preventDefault(); leeAgentThreadOpen(id);
  });
}
function leeAgentThreadsToggle(show) {
  const list = $('#agentthreadlist'), toggle = $('#agentthreads'); if (!list) return;
  const open = show === undefined ? list.hidden : !!show;
  list.hidden = !open; toggle?.setAttribute('aria-expanded', String(open));
  if (open) refreshAgentThreads().catch(() => {});
}
/* The conversation as a notebook, edited with the editor a person already knows, then read back.
   Nothing is applied until they ask: saving the notebook changes no conversation by itself. */
async function leeAgentReshape(id = lee.agentThread) {
  if (!id) return status('open a conversation first', 'err');
  let made;
  try { made = await post('/agent/conversation/notebook', {thread: id, session: id}); }
  catch (e) { return status(e.message || String(e), 'err'); }
  lee.agentReshape = {thread: id, session: made.session, path: made.path, revision: made.revision};
  await leeOpenFile(made.path);
  status(`${made.parts} parts opened as a notebook · edit, save, then apply from the agent pane`, 'ok');
  paintAgentReshapeBar();
}
function paintAgentReshapeBar() {
  const bar = $('#agentattention'); const held = lee.agentReshape; if (!bar || !held) return;
  bar.hidden = false;
  bar.innerHTML = `<span>editing ${esc(held.session.replace(/^agent_/, 'conversation '))} as a notebook</span>` +
    `<button type="button" data-reshape-apply>apply edits</button>` +
    `<button type="button" data-reshape-cancel>discard edits</button>`;
  $('[data-reshape-apply]', bar).onclick = leeAgentReshapeApply;
  $('[data-reshape-cancel]', bar).onclick = () => { lee.agentReshape = null; bar.hidden = true; refreshAgentThreads(); };
}
async function leeAgentReshapeApply() {
  const held = lee.agentReshape; if (!held) return;
  // read the edits from disk, so an unsaved buffer cannot look like a deleted part
  try { await post('/tabs/save-all'); } catch (_) {}
  let out;
  try { out = await post('/agent/conversation/reshape', held); }
  catch (e) { return status(e.message || String(e), 'err'); }
  lee.agentReshape = null; $('#agentattention').hidden = true;
  await refreshAgentThreads();
  status(`reshaped · ${out.discarded.length} dropped, ${out.rewritten.length} rewritten · ${out.branch_id}`, 'ok');
}
async function leeAgentThreadOpen(id) {
  await leeAgentThreadSwitch(id);
  leeAgentThreadsToggle(false);
  $('#agentprompt')?.focus();
}
/* `status()` is footer-only and addressed to nothing. A checkpoint in another conversation needs
   naming and a way in. */
function paintAgentAttention(attention, rows) {
  const bar = $('#agentattention'); if (!bar) return;
  const waiting = (attention.waiting || []).filter(id => id !== attention.active);
  const working = Math.max(0, (attention.working || 0) - (rows.some(t => t.id === attention.active && t.state === 'working') ? 1 : 0));
  document.title = agentDocumentTitle(attention);
  if (!waiting.length) { bar.hidden = true; bar.innerHTML = ''; return; }
  const named = waiting.map(id => {
    const row = rows.find(t => t.id === id);
    return `<button type="button" data-attention="${esc(id)}">${esc(row ? threadName(row) : id)}</button>`;
  }).join('');
  bar.hidden = false;
  bar.innerHTML = `<span>${waiting.length === 1 ? 'A conversation is' : `${waiting.length} conversations are`} waiting for you</span>${named}`;
  for (const button of $$('[data-attention]', bar)) button.onclick = () => leeAgentAttend(button.dataset.attention);
  return working;
}
function agentDocumentTitle(attention) {
  const base = lee.agentDocumentTitle ||= document.title.replace(/^[^·]*· /, '');
  const bits = [];
  if (attention.working) bits.push(`${attention.working}⚙`);
  if ((attention.waiting || []).length) bits.push('(!)');
  return bits.length ? `${bits.join(' ')} · ${base}` : base;
}
/* Switching to the conversation that asked, and then to the question it asked. The right pane with
   no idea what wanted you is half an answer. */
async function leeAgentAttend(id) {
  await leeAgentThreadSwitch(id);
  const card = $('.lee-approval-card') || $('[data-approval]');
  if (card) { card.scrollIntoView({block: 'center'}); (card.querySelector('button') || card).focus(); }
  else await pollApproval();
}
async function leeAgentThreadMute(id = lee.agentThread) {
  if (!id) return;
  const row = (lee.agentThreadRows || []).find(t => t.id === id);
  try {
    const d = await post('/agent/thread/mute', {thread: id, muted: !row?.muted});
    if (d.thread?.problem) status(`mute was not saved: ${d.thread.problem}`, 'err');
    await refreshAgentThreads();
  } catch (e) { status(String(e.message || e), 'err'); }
}
async function refreshAgentThreads() {
  const d = await api('/agent/threads'); paintAgentThreads(d); notifyAgentAttention(d); return d;
}
/* Off by default, and permission is asked for only when a person turns it on, because a prompt
   nobody invited is why browsers stopped honouring them. Every state is terminal: unsupported and
   denied disable delivery and say so once. */
function agentNotifyEnabled() { return localStorage.getItem('lee-agent-notify') === 'on'; }
async function leeAgentNotifyToggle(on) {
  if (!on) { localStorage.setItem('lee-agent-notify', 'off'); return status('notifications off', 'ok'); }
  if (!('Notification' in window)) { localStorage.setItem('lee-agent-notify', 'off'); return status('this browser has no notifications', 'err'); }
  let state = Notification.permission;
  if (state === 'default') { try { state = await Notification.requestPermission(); } catch (_) { state = 'denied'; } }
  if (state !== 'granted') { localStorage.setItem('lee-agent-notify', 'off'); return status('notifications are blocked for this site', 'err'); }
  localStorage.setItem('lee-agent-notify', 'on'); status('notifications on', 'ok');
}
/* One notification per thing that happened, keyed by what happened: replay, a reconnect and a
   second tab all deliver the same terminal event. */
function notifyAgentAttention(d) {
  const seen = lee.agentNotified ||= new Set();
  if (!agentNotifyEnabled() || !('Notification' in window) || Notification.permission !== 'granted') return;
  for (const row of (d.threads || [])) {
    if (row.id === d.active || row.muted) continue;
    const key = `${row.id}:${row.state}:${row.unread}`;
    if (seen.has(key)) continue;
    seen.add(key);
    if (!document.hidden) continue;
    const name = threadName(row);
    if (row.state === 'waiting') new Notification('Waiting for you', {body: name, tag: row.id});
    else if (row.unread) new Notification('Turn finished', {body: name, tag: row.id});
  }
}
window.leeAgentNotifyToggle = leeAgentNotifyToggle; window.agentNotifyEnabled = agentNotifyEnabled;
async function leeAgentNew() {
  rememberAgentThread();
  try {
    const d = await post('/agent/thread/new', {}); lee.agentThread = d.active; lee.agentBusy = false; lee.agentTitle = '';
    approvalCards.clear(); const log = $('#agentlog'), input = $('#agentprompt');
    if (log) { log.innerHTML = ''; lee.agentLive = ''; lee.agentView = 'live'; } if (input) input.value = '';
    await refreshAgentThreads(); $('#agenthistory')?.classList.remove('active'); input?.focus(); status('new conversation started', 'ok');
  } catch (e) { status(String(e.message || e), 'err'); }
}
/* A conversation with a turn in flight keeps producing while it is off screen. Switching to it
   paints its finished turns from the server first, then attaches to its feed from the last point
   it settled, so the running turn arrives once and nothing drawn is drawn twice. */
async function leeAgentThreadSwitch(id) {
  if (!id || id === lee.agentThread) return; rememberAgentThread();
  try {
    const d = await post('/agent/thread/switch', {thread:id});
    if (lee.agentStream) { lee.agentStream._leeStopped = true; lee.agentStream.close(); lee.agentStream = null; ++lee.agentStreamGen; }
    const running = d.thread.state === 'working' || d.thread.state === 'waiting';
    lee.agentThread = d.active; lee.agentBusy = running; lee.agentTitle = titleText(d.thread.title);
    const input = $('#agentprompt'); if (input) input.value = lee.agentThreadDrafts.get(id) || '';
    const live = await paintAgentThread(d.active);
    await refreshAgentThreads(); updateAgentRunstrip();
    if (running) { setAgentStatus('working'); agentListen(d.active, live?.seq || 0); }
    else { setAgentStatus('ready'); await rehydrateAgentLive(); }
    input?.focus();
  } catch (e) { status(String(e.message || e), 'err'); await refreshAgentThreads(); }
}
async function leeAgentThreadRename(id = lee.agentThread) {
  if (!id) return;
  const row = (lee.agentThreadRows || []).find(t => t.id === id);
  const title = await textDialog('Rename conversation', 'Conversation title', row ? titleText(row.title) : '');
  if (title == null) return;
  try { const d = await post('/agent/thread/title', {thread: id, title});
        if (id === lee.agentThread) lee.agentTitle = titleText(d.thread.title);
        await refreshAgentThreads(); }
  catch (e) { status(String(e.message || e), 'err'); }
}
async function leeAgentThreadClose(id = lee.agentThread) {
  if (!id) return; const closing = id;
  try {
    const d = await post('/agent/thread/close', {thread:closing}); lee.agentThreadDrafts.delete(closing);
    paintAgentThreads(d); const log = $('#agentlog'); if (log) log.innerHTML = ''; if (d.active) { const active = d.active; lee.agentThread = ''; await leeAgentThreadSwitch(active); }
  } catch (e) { status(String(e.message || e), 'err'); }
}
// The rehydrated banner survives `restoreAgentLive`, which round-trips the pane through innerHTML:
// an id in an onclick attribute outlives that, a bound listener does not.
window.leeAgentNew = leeAgentNew; window.leeAgentThreadsToggle = leeAgentThreadsToggle;
window.leeAgentThreadOpen = leeAgentThreadOpen; window.leeAgentReshape = leeAgentReshape; window.leeAgentAttend = leeAgentAttend;
window.leeAgentThreadMute = leeAgentThreadMute; window.leeAgentThreadSwitch = leeAgentThreadSwitch;
window.leeAgentThreadRename = leeAgentThreadRename; window.leeAgentThreadClose = leeAgentThreadClose;
window.refreshAgentThreads = refreshAgentThreads;
window.leeAgentResume = leeAgentResume;
window.leeAgentHistory = leeAgentHistory;
window.rehydrateAgentLive = rehydrateAgentLive; window.paintAgentThread = paintAgentThread;

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
    // The badge is what says which charter the agent is carrying, so it takes the state's own
    // heading rather than the word `active`.
    const stateLabel = () => (text.value.split('\n').find(l => l.startsWith('#') && l.replace(/^#+\s*/, '').trim())
      || '').replace(/^#+\s*/, '').trim().slice(0, 40) || 'state active';
    const markActive = () => {
      const badge = $('#agentnames'); if (badge) { badge.textContent = stateLabel(); badge.title = 'active starting state'; }
      $('.lee-agent-welcome', $('#agentlog'))?.remove();
    };
    // A save that fails leaves the state in the editor and the box open, with the reason on it.
    // Neither button said anything when the request was refused, so a person pressed a control that
    // did nothing: the packaged app cannot reach memory at all, and this is how that looked.
    const attempt = async (button, run) => {
      const el = $(`[data-${button}]`, box), label = el.textContent;
      el.disabled = true; el.textContent = 'Working…';
      try { await run(); box.remove(); }
      catch (e) {
        const why = e.message || String(e);
        $('[data-state-help]', box).textContent = why;
        status(why, 'err');
      }
      finally { el.disabled = false; el.textContent = label; }
    };
    $('[data-save]', box).onclick = () => attempt('save', async () => {
      const d = await post('/agent/state/save', {title: $('#agentstatetitle', box).value, text: text.value, layer: layer.value, activate: true});
      markActive(); status(d.saved?.skipped ? 'state already in memory and activated' : 'state saved to memory and activated', 'ok');
    });
    $('[data-activate]', box).onclick = () => attempt('activate', async () => {
      await post('/agent/state/activate', {text: text.value, layer: layer.value});
      markActive(); status('starting state activated without saving', 'ok');
    });
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

function agentLog(html, host = null) {
  const log = $('#agentlog');
  if (host) { host.insertAdjacentHTML('beforeend', html); log.scrollTop = log.scrollHeight; return; }
  // Never use `innerHTML +=`: it reparses every existing child and silently detaches every
  // checkpoint, fork, rollback, CodeMirror and disclosure handler already in the log.
  log.insertAdjacentHTML('beforeend', html);
  log.scrollTop = log.scrollHeight;
}

