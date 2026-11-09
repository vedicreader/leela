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
  // One state for the code, the picture and the numbers. The names that a cell watches are the keys of the demo: a run moves the demo,
  // and a move in the demo changes the one number that the code sets for that name. Nothing runs by itself.
  const names = () => new Set([...document.querySelectorAll('.abh .lee-livecell[data-watch]')].flatMap(c => c.dataset.watch.split(',').filter(Boolean)));
  const num = v => { const n = typeof v === 'string' && v.trim() === '' ? NaN : Number(v); return Number.isFinite(n) ? n : null };
  const known = new WeakMap();
  const bind = () => {
    for (const h of document.querySelectorAll('.abh [data-rupaka]')) {
      const s = h.rupaka; if (!s || known.has(h) || !names().size) continue;
      const seen = {}; known.set(h, seen);
      for (const n of names()) if (num(s.st?.[n]) != null) seen[n] = num(s.st[n]);
      let t = 0;
      s.on(() => {
        clearTimeout(t); t = setTimeout(() => {
          for (const n of names()) {
            const v = num(s.st?.[n]); if (v == null || !(n in seen) || v === seen[n]) continue;
            seen[n] = v;
            for (const c of document.querySelectorAll('.abh .lee-livecell[data-watch]')) if (c.dataset.watch.split(',').includes(n)) window.leeLiveCell?.rewrite?.(c, n, v);
          }
        }, 200);
      });
    }
  };
  document.addEventListener('lee-live-ran', e => {
    const st = {};
    for (const [k, v] of Object.entries(e.detail?.watch || {})) if (num(v) != null) st[k] = num(v);
    for (const h of document.querySelectorAll('.abh [data-rupaka]')) {
      const seen = known.get(h); if (!h.rupaka || !seen) continue;
      Object.assign(seen, Object.fromEntries(Object.entries(st).filter(([k]) => Object.hasOwn(h.rupaka.st || {}, k))));
      try { Rupaka.set(h, st); } catch {}
    }
  });
  document.addEventListener('htmx:afterSettle', bind);
  setInterval(bind, 1000); bind();
}
