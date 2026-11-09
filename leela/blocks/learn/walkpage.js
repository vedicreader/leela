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
