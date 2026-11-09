const inLearnTab = () => lee.kind === 'learn';
async function leeLearnModeOn() {
  if (lee.agentLearnMode) return true;
  try {
    const rows = await api('/agent/threads'), d = await post('/agent/learn-mode', {on: true, thread: lee.agentThread || rows.active});
    if (!d.ok) { status(d.message || d.error || 'Learn mode could not turn on.', 'err'); return false; }
    lee.agentLearnMode = d.on; await refreshAgentThreads(); return true;
  } catch (e) {
    status(e.body?.code === 'thread_busy' ? 'The agent is working. Try again when it finishes.' : e.message || String(e), 'err'); return false;
  }
}
async function leeLearnToAgent(text, send) {
  if (!inLearnTab()) return status('Open a Learn tab first.', 'err');
  if (lee.agentBusy || lee.agentSending) return status('The agent is working. Try again when it finishes.', 'err');
  if ($('#agentprompt')?.value.trim()) { leeAct('focus_agent'); return status('Send or clear your message to the agent first.', 'err'); }
  if (!await leeLearnModeOn()) return;
  leeAct('focus_agent');
  const prompt = $('#agentprompt'); if (!prompt) return;
  prompt.value = text;
  if (send) return sendAgent();
  prompt.focus(); prompt.setSelectionRange(text.length, text.length);
}
const leeLearnAsk = () => leeLearnToAgent("I don't get this", true);
const leeLearnExplain = () => leeLearnToAgent('Explain this step', true);
const leeLearnChange = () => leeLearnToAgent('Change this walk: ', false);
addEventListener('keydown', e => {
  if (e.code !== 'KeyE' || !(e.metaKey && e.altKey && e.ctrlKey && e.shiftKey) || !inLearnTab()) return;
  e.preventDefault(); e.stopImmediatePropagation(); if (!e.repeat) leeLearnAsk();
}, true);
window.leeLearnToAgent = leeLearnToAgent; window.leeLearnAsk = leeLearnAsk; window.leeLearnChange = leeLearnChange; window.leeLearnExplain = leeLearnExplain;
