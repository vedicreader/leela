registerTabMount('learn_walk', async (host, st) => {
  if (!document.getElementById('lee-abh-css')) {
    const link = document.createElement('link'); link.id = 'lee-abh-css'; link.rel = 'stylesheet'; link.href = '/learn/abh.css'; document.head.append(link);
  }
  const url = '/w/' + encodeURIComponent(st.walk) + '/0?pane=1';
  host.innerHTML = '<div class="abh" hx-get="' + url + '" hx-trigger="load" hx-select="main" hx-target="closest .abh" hx-swap="innerHTML" hx-boost="true" hx-push-url="false"></div>';
  const abh = host.firstElementChild;
  function pane(url) {
    const u = new URL(url, location.origin);
    if (u.origin !== location.origin || !/^\/(?:w|c|v)\//.test(u.pathname)) return null;
    u.searchParams.set('pane', '1'); return u.pathname + u.search + u.hash;
  }
  abh.addEventListener('htmx:configRequest', e => { e.detail.parameters.pane = '1'; });
  abh.addEventListener('htmx:beforeHistoryUpdate', e => e.preventDefault());
  abh.addEventListener('htmx:beforeRequest', e => { e.detail.requestConfig.path = pane(e.detail.requestConfig.path) || e.detail.requestConfig.path; });
  htmx.process(abh);
});
