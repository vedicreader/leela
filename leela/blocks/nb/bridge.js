//: The notebook and the agent, in both directions: tell the server which cell the person is on, ask the agent about it, hand a word to Learn, and come back to Code.
const EXPLAIN_CELL = 'Explain what this cell does and, if it failed, why';
let reportedCell = '', reportTimer = 0;
const agentIdle = () => !(lee.agentBusy || lee.agentSending) || (status('The agent is working. Try again when it finishes.', 'err'), false);
const cellIdNow = () => lee.kind !== 'learn' && lee.cells?.length ? lee.cells[lee.sel]?.id || '' : '';
//: The id of the cell the agent turn anchors on; `sendAgent` sends it with the prompt.
window.leeCellId = cellIdNow;
async function leeReportCell(id = cellIdNow()) {
  const key = `${lee.tabKey}:${id}`;
  if (!id || key === reportedCell) return;
  reportedCell = key;
  try { await post('/nb/cell', {cell: id}); } catch (_) { reportedCell = ''; }
}
function leeReportSoon() {
  clearTimeout(reportTimer); reportTimer = setTimeout(() => leeReportCell(), 350);
}
document.addEventListener('focusin', e => { if (e.target.closest?.('#editor .lee-cell')) leeReportSoon(); });
document.addEventListener('click', e => { if (e.target.closest?.('#editor .lee-cell')) leeReportSoon(); });
//: A cell that ends in an error is the one the person will ask about, focused or not.
addEventListener('lee-cell-output', e => {
  const {id, outputs} = e.detail || {};
  if (outputs?.some(o => o.output_type === 'error') && lee.cells?.[lee.sel]?.id === id) leeReportCell(id);
});
//: Switch the workspace mode: the mode switch's `leeModeSet` when the page has it, else the route and the dock layout it answers with.
async function leeSwitchMode(mode) {
  if (window.leeModeSet) return window.leeModeSet(mode);
  try {
    const d = await post('/workspace/mode', {mode, ...(lee.agentThread ? {thread: lee.agentThread} : {})});
    for (const [k, pane] of [['files', 'left'], ['exec', 'bottom'], ['agent', 'right']]) if (k in (d.layout || {})) leePane(pane, !!d.layout[k], false);
    lee.agentLearnMode = mode === 'learn'; refreshAgentThreads?.().catch(() => {});
    await refreshTabStrip(); await mountTab();
    return true;
  } catch (e) {
    status(e.body?.code === 'thread_busy' ? 'The agent is working. Try again when it finishes.' : e.body?.message || e.message || String(e), 'err');
    return false;
  }
}
async function leeExplainCell(id) {
  const i = id ? lee.cells.findIndex(c => c.id === id) : lee.sel, c = lee.cells?.[i];
  if (lee.kind === 'learn' || !c) return status('Open a notebook and pick a cell first.', 'err');
  if (!agentIdle()) return;
  if ($('#agentprompt')?.value.trim()) { leeAct('focus_agent'); return status('Send or clear your message to the agent first.', 'err'); }
  if (lee.agentLearnMode && !await leeSwitchMode('code')) return;
  selectCell(i); await leeReportCell(c.id);
  leeAct('focus_agent');
  const prompt = $('#agentprompt'); if (!prompt) return;
  prompt.value = EXPLAIN_CELL;
  return sendAgent();
}
const selectedWords = () => {
  const v = typeof curEditor === 'function' ? curEditor() : null, s = v?.state.selection.main;
  const t = s && !s.empty ? v.state.doc.sliceString(s.from, s.to) : String(getSelection?.() ?? '');
  return t.replace(/\s+/g, ' ').trim().slice(0, 200);
};
const errorLine = c => { const o = [...(c?.outputs || [])].reverse().find(o => o.output_type === 'error'); return o ? `${o.ename}: ${o.evalue}`.slice(0, 200) : ''; };
//: Learn about `text`, the selection, or the error of the cell in hand: Learn mode on, the agent pane focused, 'Teach me about …' typed and not sent.
async function leeLearnAbout(text) {
  const about = String(text || '').replace(/\s+/g, ' ').trim().slice(0, 200) || selectedWords() || errorLine(lee.cells?.[lee.sel]);
  if (!about) return status('Select some text, or run a cell that fails, first.', 'err');
  if (!agentIdle()) return;
  const draft = $('#agentprompt')?.value.trim() || '';
  if (!await leeSwitchMode('learn')) return;
  leeAct('focus_agent');
  const prompt = $('#agentprompt'); if (!prompt) return;
  const line = `Teach me about ${about}`;
  prompt.value = draft ? `${prompt.value.replace(/\s+$/, '')}\n${line}` : line;
  prompt.focus(); prompt.setSelectionRange(prompt.value.length, prompt.value.length);
  if (draft) status('Added a line to your message. Nothing was sent.', 'ok');
}
//: The two links of a failing cell's traceback.
function errorActions(o, c) {
  const d = document.createElement('div'), b = (text, title, run) => Object.assign(document.createElement('button'), {type: 'button', className: 'lee-btn', textContent: text, title, onclick: e => { e.stopPropagation(); run(); }});
  d.className = 'lee-out-actions'; d.style.cssText = 'display:flex;gap:8px;margin-top:6px;font-family:var(--lee-sans,inherit)';
  const ex = b('Explain', 'Ask the agent what this cell did and why it failed', () => leeExplainCell(c.id)), lr = b('Learn about this', 'Switch to Learn and ask to be taught this error', () => leeLearnAbout(`${o.ename}: ${o.evalue}`));
  ex.dataset.explain = ''; lr.dataset.learnAbout = '';
  d.append(ex, lr); return d;
}
//: Return to Code (journey c): the Learn tab's Open in Leela links and buttons open the lesson in Leela's own editor, in Code mode, on the notebook.
async function leeOpenInCode(el) {
  const f = el.closest('form'), a = f ? null : el.closest('a[href]');
  if (!f && !a) return false;
  const u = new URL(f ? f.action : a.href, location.origin);
  const own = /^\/learn(\/|$)/.test(u.pathname);
  if (!f && own) u.searchParams.set('go', '1');
  const at = (own ? '' : '/learn/abh') + u.pathname + u.search;
  if (!await leeSwitchMode('code')) return true;
  try {
    const r = await fetch(at, f ? {method: 'POST', body: new FormData(f)} : {});
    if (!r.ok) throw new Error('Leela could not open the lesson.');
    await refreshTabStrip(); await mountTab();
  } catch (e) {
    status(e.message || 'Leela could not open the lesson.', 'err'); await leeSwitchMode('learn');
  }
  return true;
}
Object.assign(window, {leeReportCell, leeSwitchMode, leeExplainCell, leeLearnAbout, leeOpenInCode, errorActions});
