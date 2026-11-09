if (!window.leeLearnDemo) {
  window.leeLearnDemo = true;
  const said = d => {
    const st = d.state && typeof d.state === 'object' ? Object.entries(d.state).map(([k, v]) => `${k} = ${v}`).join(', ') : '';
    const where = document.querySelector('.abh main h1')?.textContent.trim();
    return `About the demo${where ? ` on "${where}"` : ''}${st ? ` (${st})` : ''}: ${d.text || ''}`.trim();
  };
  document.addEventListener('submit', e => {   // walk.js turns each form of the page into a navigation: the form of Ask about this stays the demo's own
    const f = e.target;
    if (!f.matches?.('.abh [data-rupaka] form')) return;
    e.stopImmediatePropagation(); f.onsubmit?.(e);
  }, true);
  document.addEventListener('rk-ask', async e => {
    if (!e.target.closest?.('.abh')) return;
    e.preventDefault();
    const text = said(e.detail || {});
    if (window.leeLearnToAgent) return leeLearnToAgent(text, true);
    if (window.lee?.agentBusy || window.lee?.agentSending) return status('The agent is working. Try again when it finishes.', 'err');
    leeAct('focus_agent');
    const box = $('#agentprompt'); if (!box) return;
    if (box.value.trim()) return status('Send or clear your message to the agent first.', 'err');
    box.value = text; sendAgent();
  });
}
