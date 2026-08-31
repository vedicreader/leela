// Whichever editor has the cursor: a cell, a whole file, or the exec box.
function curEditor() {
  if (lee.scope === 'exec') return lee.editors.get('exec');
  if (lee.activeEditor === 'secondary') return lee.editors.get('secondary');
  if (lee.kind === 'notebook') { const c = lee.cells[lee.sel]; return c && lee.editors.get(c.id); }
  return lee.editors.get('file');
}
function curLang() {
  if (lee.scope === 'exec') return 'python';
  if (lee.kind === 'notebook') return lee.cells[lee.sel]?.cell_type === 'markdown' ? 'markdown' : nbLang();
  return $('#editor')?.dataset.lang || 'python';
}

/* Indent from the palette, or from a chord the caret did not reach a document with. `curEditor`
   answers for a notebook cell and for a whole file alike, which is what these have to cover. */
function leeIndent(cmd) {
  const v = curEditor();
  if (!v) return status('put the cursor in some code first', 'err');
  LeeCM.focus(v);
  LeeCM[cmd](v);
}

function kernelComplete() {
  const v = curEditor();
  if (!v) return status('put the cursor in some code first', 'err');
  LeeCM.startCompletion(v);
}

/* Two completions, two different questions. alt+/ asks the kernel what names exist, which is
 * instant and right by construction. This asks the model what should come next, which costs a
 * forward pass, so it is never fired by typing and stays ghost text until tab accepts it. */
function closeSelectionHelp() { $('.lee-selection-tools')?.remove(); }
function selectionEditor() {
  if (!['editor', 'exec'].includes(lee.scope)) return null;
  return curEditor();
}
/* Place a floating panel beside `rect`, wholly inside the viewport.

   `offsetHeight`, not `getBoundingClientRect`: these panels animate in from a transform, and the
   rect is of the transformed box, which is short by a few pixels on the first frame. Callers place
   twice, once while the panel is a skeleton and again once it has its content, so appending is
   conditional and the second call only moves it. */
function positionFloating(el, rect) {
  if (!el.isConnected) document.body.appendChild(el);
  const w = el.offsetWidth, h = el.offsetHeight, below = innerHeight - rect.bottom - 15;
  const top = h <= below || below >= rect.top - 15 ? rect.bottom + 7 : rect.top - h - 7;
  el.style.left = Math.max(8, Math.min(rect.left, innerWidth - w - 8)) + 'px';
  el.style.top = Math.max(8, Math.min(top, innerHeight - h - 8)) + 'px';
}
function showSelectionHelp() {
  if ($('.lee-selection-reply') || document.activeElement?.closest?.('.lee-selection-tools')) return;
  const view = selectionEditor(); if (!view) return closeSelectionHelp();
  const selected = LeeCM.selection(view); if (!selected?.text.trim()) return closeSelectionHelp();
  const rect = LeeCM.selectionCoords(view); if (!rect) return closeSelectionHelp();
  closeSelectionHelp();
  const tools = document.createElement('aside'); tools.className = 'lee-selection-tools';
  tools.innerHTML = `<button type="button" data-summary>summarise</button>` +
    `<button type="button" data-ask>ask AI</button>`;
  positionFloating(tools, rect);
  $('[data-summary]', tools).onclick = () => runSelectionHelp(view, selected, rect, 'summary');
  $('[data-ask]', tools).onclick = () => {
    tools.classList.add('asking');
    tools.innerHTML = `<input class="lee-input" placeholder="e.g. make this clearer, fix it, explain briefly…">` +
      `<button type="button" data-send>send</button>`;
    const input = $('input', tools); input.focus();
    const send = () => { const instruction = input.value.trim(); if (instruction) runSelectionHelp(view, selected, rect, 'instruction', instruction); };
    $('[data-send]', tools).onclick = send;
    input.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); send(); } else if (e.key === 'Escape') closeSelectionHelp(); };
  };
}
/* What the model looked at before answering, named rather than counted: a rewrite that read the
   file around the selection is worth more trust than one that read nothing, and the reader is the
   one deciding whether to take it. */
function trailHtml(activity) {
  if (!Array.isArray(activity)) return '';   // an older server: say nothing rather than guess
  const used = activity.filter(a => a.tool).map(a => a.tool);
  // An empty trail is a fact about the answer, not a missing feature. Rendering nothing for it
  // leaves the reader unable to tell "it looked at nothing" from "the trail is broken".
  if (!used.length) return `<div class="lee-selection-trail lee-trail-none">` +
    `<span>answered without looking anything up</span></div>`;
  const counts = used.reduce((n, t) => ({...n, [t]: (n[t] || 0) + 1}), {});
  const named = Object.entries(counts).map(([t, n]) => esc(n > 1 ? `${t} x${n}` : t)).join(', ');
  return `<div class="lee-selection-trail"><span>looked at</span> ${named}</div>`;
}
/* One panel's judgement, reported as it happens.

   The outcome is a click, so only the browser ever learns it, and the `ask_id` the server minted is
   what ties the answer to what became of it. Every send is swallowed: `post` rejects on a non-2xx,
   and a recording failure must never be what stops a replace. */
function completionLog() {
  let queue = [], timer = null, done = false;
  const flush = () => {
    clearTimeout(timer); timer = null;
    const events = queue; queue = [];
    if (events.length) post('/ai/events', {events}).catch(() => {});
  };
  const add = (kind, row = {}) => {
    if (done) return;
    if (['replace', 'discard', 'stale', 'abandon'].includes(kind)) done = true;   // one panel, one verdict
    queue.push({kind, at: Date.now() / 1000, ...row});
    clearTimeout(timer); timer = setTimeout(flush, done ? 0 : 2500);
  };
  return {add, flush, settled: () => done};
}
async function runSelectionHelp(view, selected, rect, mode, instruction = '') {
  closeSelectionHelp();
  const log = completionLog();
  status(mode === 'summary' ? 'summarising selection with the local model…' : 'asking the inline model to rewrite the selection…');
  const panel = document.createElement('aside'); panel.className = 'lee-selection-reply loading';
  panel.innerHTML = `<header><strong>${mode === 'summary' ? 'Summarising selection' : 'Inline AI help'}</strong>` +
    `<span>working locally when available</span></header><div class="lee-selection-skeleton"><i></i><i></i><i></i></div>`;
  // The reader can scroll or resize while the model answers, so the anchor is asked for again
  // rather than reused. `selectionCoords` gives nothing once the selection is gone.
  const anchor = () => { try { return LeeCM.selectionCoords(view) || rect; } catch (_) { return rect; } };
  positionFloating(panel, anchor());
  try {
    // The path and the lines are what the read-only tools need to open anything around the
    // selection. Without them a model asked about `check` can only see the range it was given.
    const doc = LeeCM.getDoc(view), lineAt = i => doc.slice(0, i).split('\n').length;
    log.add('ask', {mode, instruction, lang: curLang(), path: lee.path || '',
                    chars: selected.text.length, text: selected.text});
    const result = await post('/complete/selection', {
      text: selected.text, mode, instruction, lang: curLang(), path: lee.path || '',
      line_from: lineAt(selected.from), line_to: lineAt(selected.to)});
    const ask_id = result.ask_id || '';
    log.add('reply', {ask_id, model: result.model, ms: result.ms, tools: result.tools,
                      reply: result.text});
    panel.classList.remove('loading'); panel.innerHTML = `<header><strong>${mode === 'summary' ? 'Summary' : 'Suggested replacement'}</strong>` +
      `<span title="the inline model, set beside 'prompt cells · inline AI' in the agent settings">` +
      `${esc(result.model || '')}${mode === 'summary' ? '' : ' · inline model'}</span></header>` +
      `<pre></pre>${trailHtml(result.activity)}<footer>` +
      `<button class="lee-btn" data-discard>discard</button><button class="lee-btn go" data-replace>replace selection</button></footer>`;
    $('pre', panel).textContent = result.text;
    panel._leeLog = log; panel._leeAsk = ask_id;
    $('[data-discard]', panel).onclick = () => { log.add('discard', {ask_id}); panel.remove(); };
    $('[data-replace]', panel).onclick = () => {
      // Not an accept: nothing was applied. Counting it as one would flatter the model.
      if (LeeCM.slice(view, selected.from, selected.to) !== selected.text) {
        log.add('stale', {ask_id});
        return status('selection changed while the model was answering; suggestion left open', 'err');
      }
      log.add('replace', {ask_id});
      LeeCM.replaceRange(view, selected.from, selected.to, result.text); panel.remove(); status('selection replaced', 'ok');
    };
    panel.onkeydown = e => {
      if (e.key === 'Escape') { log.add('abandon', {ask_id}); panel.remove(); }
      else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) $('[data-replace]', panel).click();
    };
    $('[data-replace]', panel).focus();
    positionFloating(panel, anchor());
    status(`${mode === 'summary' ? 'summary' : 'replacement'} ready from ${result.model || 'the inline model'} · review before replacing`, 'ok');
  } catch (e) {
    // Asked and got nothing is the signal a rejection rate would otherwise hide.
    log.add('error', {ask_id: '', mode, model: '', instruction});
    panel.classList.remove('loading'); panel.innerHTML = `<div class="lee-selection-error">${esc(e.message || e)}</div>` +
      `<footer><button class="lee-btn" data-discard>close</button></footer>`;
    $('[data-discard]', panel).onclick = () => panel.remove();
    positionFloating(panel, anchor());
  }
}
/* The panel's own `onkeydown` only fires while the focus is inside it, which the first click
   elsewhere ends. Escape closes it from anywhere, and defers to a modal above it. */
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape' || $$('.lee-modal').length) return;
  const panel = $('.lee-selection-reply'); if (!panel) return;
  abandonReply(panel); panel.remove(); e.stopPropagation();
}, true);

/* A panel closed without a verdict is still an answer nobody took, and leaving it unrecorded makes
   the accept rate a ratio over a denominator that quietly drops them. */
function abandonReply(panel) {
  const log = panel?._leeLog;
  if (log && !log.settled()) log.add('abandon', {ask_id: panel._leeAsk || ''});
}
addEventListener('pagehide', () => {
  const panel = $('.lee-selection-reply'); if (!panel?._leeLog || panel._leeLog.settled()) return;
  // `post` will not survive the unload; a beacon will.
  const body = JSON.stringify({events: [{kind: 'abandon', ask_id: panel._leeAsk || '',
                                         at: Date.now() / 1000}]});
  try { navigator.sendBeacon('/ai/events', new Blob([body], {type: 'application/json'})); } catch (_) {}
});
let selectionHelpTimer = null;
document.addEventListener('selectionchange', () => {
  clearTimeout(selectionHelpTimer); selectionHelpTimer = setTimeout(showSelectionHelp, 180);
});
document.addEventListener('pointerdown', e => {
  if ($('.lee-selection-tools') && !e.target.closest('.lee-selection-tools, .cm-editor')) closeSelectionHelp();
}, true);

async function aiComplete() {
  const v = curEditor();
  if (!v) return status('put the cursor in some code first', 'err');
  if (LeeCM.ghost(v)) { LeeCM.acceptGhost(v); return status('accepted', 'ok'); }
  const pos = LeeCM.cursor(v);
  status('checking Kosha graph, then asking the completion model…');
  const d = await post('/complete/ai', {code: LeeCM.getDoc(v), pos, lang: curLang(), cell: lee.sel});
  if (!d.text) return status(d.note || 'no suggestion', 'err');
  if (LeeCM.cursor(v) !== pos) return status('cursor moved while the model was thinking', 'err');
  LeeCM.focus(v);
  LeeCM.setGhost(v, d.text);
  const graph = d.graph_methods ? ` · ${d.graph_methods} Kosha graph method(s)` : '';
  status(`suggestion ready from ${d.model || 'the completion model'}${graph} · tab accepts · esc dismisses`, 'ok');
}

async function showDocs() {
  const v = curEditor();
  if (!v) return status('put the cursor on a name first', 'err');
  status('asking the kernel…');
  const d = await post('/inspect', {code: LeeCM.getDoc(v), pos: LeeCM.cursor(v)});
  if (!d.text) return status(d.note, 'err');
  status('');
  modal(`<div class="lee-mhead">docs<span class="sub">from the object the kernel actually has</span></div>
         <pre class="lee-docs">${esc(d.text)}</pre>`);
}

