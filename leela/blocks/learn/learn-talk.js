if (!window.leeLearnTalk) {
  window.leeLearnTalk = true;
  const START = /^\/t\/([a-z0-9-]+)\/start$/;
  async function leePresent(id, back) {
    const abh = document.querySelector('.abh');
    if (!abh || abh.querySelector('.lee-present')) return;
    const r = await fetch(`/learn/abh/t/${id}/present?pane=1`).catch(() => null);
    const talk = r?.ok && /\/present$/.test(new URL(r.url).pathname) && new DOMParser().parseFromString(await r.text(), 'text/html').getElementById('talk');
    if (!talk) return status('The talk did not open. Try again.', 'err');
    await learnSurface(`/t/${id}/present`);
    const o = Object.assign(document.createElement('div'), {className: 'lee-present talk present', tabIndex: -1}), mine = {};
    o.append(document.adoptNode(talk)); abh.append(o); abh.scrollTop = 0; abh.classList.add('lee-presenting');
    htmx.process(o); renderMath(o);
    const stop = abhyasaTalkWindow(o), gone = new MutationObserver(() => o.isConnected || leave('', true));
    function leave(to, quiet) {
      gone.disconnect(); stop(); o.remove(); abh.classList.remove('lee-presenting');
      for (const k of ['abhyasaTalkLeave', 'abhyasaTalkEnded']) if (window[k] === mine[k]) delete window[k];
      if (!quiet && (to ||= back)) leeLearnNav(to);
    }
    window.abhyasaTalkLeave = mine.abhyasaTalkLeave = () => leave();
    window.abhyasaTalkEnded = mine.abhyasaTalkEnded = to => leave(to);
    gone.observe(abh, {childList: true});
    o.focus();
  }
  window.leeLearnPresent = leePresent;
  document.addEventListener('submit', async e => {
    const f = e.target, u = f.closest?.('.abh') && new URL(f.getAttribute('action') || '', location.origin), m = u && START.exec(u.pathname);
    if (!m) return;
    e.preventDefault(); e.stopImmediatePropagation();
    const r = await fetch(u.pathname, {method: 'POST', redirect: 'manual'}).catch(() => null);
    if (!r || !(r.ok || r.type === 'opaqueredirect')) return status('The talk did not start. Try again.', 'err');
    leePresent(m[1], `/t/${m[1]}`);
  }, true);
}
