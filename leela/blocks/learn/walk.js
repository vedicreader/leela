registerTabMount('learn_walk', async (host, st) => {
  if (!document.getElementById('lee-abh-css')) {
    const link = document.createElement('link'); link.id = 'lee-abh-css'; link.rel = 'stylesheet'; link.href = '/learn/abh.css'; document.head.append(link);
  }
  const url = '/w/' + encodeURIComponent(st.walk) + '/0?pane=1';
  host.innerHTML = '<div class="abh" hx-boost="true" hx-push-url="false"><div hx-get="' + url + '" hx-trigger="load" hx-select="main" hx-target="closest .abh" hx-swap="innerHTML"></div></div>';
  const abh = host.firstElementChild;
  function pane(url) {
    const u = new URL(url, location.origin);
    if (u.origin !== location.origin || !/^\/(?:w|c|v)\//.test(u.pathname)) return null;
    u.searchParams.set('pane', '1'); return u.pathname + u.search + u.hash;
  }
  abh.addEventListener('click', e => {
    const a = e.target.closest('a[href]'), url = a && pane(a.href);
    if (!url || a.target) return;
    e.preventDefault(); e.stopImmediatePropagation(); htmx.ajax('GET', url, {target: abh, swap: 'innerHTML', select: 'main'});
  }, true);
  abh.addEventListener('htmx:configRequest', e => { e.detail.parameters.pane = '1'; });
  abh.addEventListener('htmx:afterSettle', () => { if (document.activeElement?.closest('.abh')) document.activeElement.blur(); });
  htmx.process(abh);
});
