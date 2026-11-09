(() => {
  if (window.leeAbhVault) return;
  window.leeAbhVault = 1;
  let es = null, at = 0;
  const jobs = () => {
    const abh = document.querySelector('.abh');
    if (es || !window.EventSource || !abh?.querySelector('[data-job]:not(#activity)')) return;
    const s = es = new EventSource('/learn/abh/events'), shut = () => { s.close(); if (es === s) es = null; };
    s.onmessage = e => {
      let d; try { d = JSON.parse(e.data); } catch { return; }
      for (const el of abh.querySelectorAll('[data-job]')) { const ks = el.dataset.job.split(' '); if (d.obj === '*' || ks.includes('*') || ks.includes(d.obj) || ks.includes(d.key)) htmx.trigger(el, 'job'); }
    };
    s.addEventListener('end', () => { shut(); if (Date.now() - at > 3000) { at = Date.now(); abh.querySelectorAll('[data-job]').forEach(el => htmx.trigger(el, 'job')); } });
    s.onerror = shut;
  };
  document.addEventListener('htmx:afterSettle', jobs); jobs();
  document.addEventListener('click', e => {
    const a = e.target.closest?.('.abh a[href^="/v/"]'), m = a && /^\/v\/([^/?#]+)\/([^/?#]+)/.exec(a.getAttribute('href'));
    if (!m || !window.leeOpenVaultDoc) return;
    e.preventDefault(); e.stopImmediatePropagation();
    window.leeOpenVaultDoc(decodeURIComponent(m[2]), m[1] === 'store' ? '' : m[1], 'learn', a.dataset.title || '');
  }, true);
})();
(() => {
  if (window.leeAbhKeep) return;
  window.leeAbhKeep = 1;
  let kept = null;
  const form = () => document.querySelector('.abh form[data-qid]');
  const note = () => { const f = form(); kept = !f ? null : {qid: f.dataset.qid, ans: f.querySelector('#ans')?.value || '', think: f.querySelector('#think')?.value || '', sure: f.querySelector('[name=confidence]:checked')?.value}; };
  const sync = () => { const f = form(), b = f?.querySelector('#send'), a = f?.querySelector('#ans'); if (b && a) b.disabled = !a.value.trim(); };
  const put = (el, v) => { if (el && v && !el.value) { el.value = v; el.setSelectionRange?.(v.length, v.length); } };
  const back = () => {
    const f = form();
    if (f && kept && kept.qid === f.dataset.qid) {
      put(f.querySelector('#ans'), kept.ans); put(f.querySelector('#think'), kept.think);
      if (kept.sure && !f.querySelector('[name=confidence]:checked')) { const r = f.querySelector(`[name=confidence][value="${kept.sure}"]`); if (r) r.checked = true; }
    }
    note(); sync();
  };
  const typed = e => { if (e.target.closest?.('.abh form[data-qid]')) { note(); sync(); } };
  document.addEventListener('input', typed, true); document.addEventListener('change', typed, true);
  document.addEventListener('htmx:beforeSwap', e => { if (e.detail.xhr.status < 300 && /\/(answer|giveup)$/.test(e.detail.requestConfig?.path || '')) kept = null; });
  document.addEventListener('htmx:afterSwap', back); document.addEventListener('htmx:afterSettle', back);
  document.addEventListener('htmx:beforeRequest', note);
  back();
})();
