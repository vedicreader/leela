registerTabMount('learn_walk', async (host, st) => {
  if (!document.getElementById('lee-walk-css')) {
    const link = document.createElement('link'); link.id = 'lee-walk-css'; link.rel = 'stylesheet'; link.href = '/learn/walk.css'; document.head.append(link);
  }
  const url = '/learn/walk/' + encodeURIComponent(st.walk) + '?vault=' + encodeURIComponent(st.vault);
  let generation = 0;
  function busy(on, text) {
    host.setAttribute('aria-busy', on); const status = host.querySelector('.lee-walk-busy');
    if (status) status.textContent = text || ''; host.querySelectorAll('[data-walk-answer] :is(button, textarea), [data-walk-back], [data-walk-next], [data-walk-step]').forEach(x => x.disabled = on);
  }
  function failure(text, focus) {
    busy(false, text); if (focus && host.contains(focus)) focus.focus();
  }
  async function show(address, options, form) {
    const n = ++generation, focus = document.activeElement, inside = host.contains(focus); busy(true, options ? 'Checking answer…' : 'Loading step…');
    try {
      const response = await fetch(address, options); if (!response.ok) throw Error('request failed');
      const html = await response.text();
      if (n !== generation || lee.kind !== 'learn_walk' || lee.tabKey !== st.title) return;
      if (html.includes('data-walk-notice-error') && !html.includes('data-walk-step')) { failure('Could not update this walk.', focus); return; }
      host.innerHTML = html;
      const retry = host.querySelector('[data-walk-answer]');
      if (form && host.querySelector('[data-walk-notice-error]') && retry) {
        retry.elements.attempt_id.value = form.elements.attempt_id.value;
        retry.elements.answer.value = form.elements.answer.value;
        retry.elements.answer.focus();
      } else if (inside) host.querySelector('[data-walk-next], [data-walk-back], .lee-walk-content h3')?.focus();
      busy(false);
    } catch (e) { if (n === generation && lee.kind === 'learn_walk') failure('Could not load this walk.', focus); }
  }
  host.onclick = e => {
    const source = e.target.closest('[data-walk-source]');
    if (source) { e.preventDefault(); openExternal(source.href); return; }
    const step = e.target.closest('[data-walk-step], [data-walk-back], [data-walk-next]');
    if (step) show(url + '&i=' + encodeURIComponent(step.dataset.walkStep || step.dataset.walkBack || step.dataset.walkNext));
  };
  host.onsubmit = e => {
    const form = e.target.closest('[data-walk-answer]'); if (!form) return;
    e.preventDefault(); if (form.querySelector('button').disabled) return;
    show(form.action + '?vault=' + encodeURIComponent(st.vault), {method: 'POST', body: new FormData(form)}, form);
  };
  await show(url);
});
