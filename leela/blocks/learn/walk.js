registerTabMount('learn_walk', async (host, st) => {
  if (!document.getElementById('lee-walk-css')) {
    const link = document.createElement('link'); link.id = 'lee-walk-css'; link.rel = 'stylesheet'; link.href = '/learn/walk.css'; document.head.append(link);
  }
  const url = '/learn/walk/' + encodeURIComponent(st.walk) + '?vault=' + encodeURIComponent(st.vault);
  let generation = 0;
  async function show(address, options) {
    const n = ++generation;
    try {
      const html = await (await fetch(address, options)).text();
      if (n !== generation || lee.kind !== 'learn_walk' || lee.tabKey !== st.title) return;
      host.innerHTML = html;
    } catch (e) { if (lee.kind === 'learn_walk') host.textContent = 'Could not load this walk.'; }
  }
  host.onclick = e => {
    const source = e.target.closest('[data-walk-source]');
    if (source) { e.preventDefault(); openExternal(source.href); return; }
    const step = e.target.closest('[data-walk-step]');
    if (step) show(url + '&i=' + encodeURIComponent(step.dataset.walkStep));
  };
  host.onsubmit = e => {
    const form = e.target.closest('[data-walk-answer]'); if (!form) return;
    e.preventDefault(); show(form.action + '?vault=' + encodeURIComponent(st.vault), {method: 'POST', body: new FormData(form)});
  };
  await show(url);
});
