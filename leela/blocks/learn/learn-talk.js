if (!window.leeLearnTalk) {
  window.leeLearnTalk = true;
  const VARS = ['--bg', '--fg', '--ink2', '--mute', '--line', '--rule', '--page', '--raised', '--sunken', '--acc', '--ok', '--no', '--bad', '--serif', '--head', '--mono'];
  const START = /^\/t\/([a-z0-9-]+)\/start$/;
  const dark = el => { const m = getComputedStyle(el).backgroundColor.match(/\d+/g) || [255, 255, 255]; return (+m[0] * 299 + +m[1] * 587 + +m[2] * 114) / 1000 < 128; };
  function leePresent(path, back) {
    if (document.querySelector('.lee-present')) return;
    const abh = document.querySelector('.abh'), f = Object.assign(document.createElement('iframe'), {className: 'lee-present', src: path, title: 'Talk'});
    const leave = to => { f.remove(); to ? leeLearnNav(to) : back && leeLearnNav(back); };
    f.addEventListener('load', () => {
      const w = f.contentWindow, d = f.contentDocument, cs = getComputedStyle(abh);
      VARS.forEach(v => d.documentElement.style.setProperty(v, cs.getPropertyValue(v)));
      d.documentElement.dataset.mode = dark(abh) ? 'dark' : 'light';
      w.abhyasaTalkLeave = () => leave();
      w.abhyasaTalkEnded = to => leave(to);
      w.focus();
    });
    document.body.append(f);
  }
  window.leeLearnPresent = leePresent;
  document.addEventListener('submit', async e => {
    const f = e.target, u = f.closest?.('.abh') && new URL(f.getAttribute('action') || '', location.origin), m = u && START.exec(u.pathname);
    if (!m) return;
    e.preventDefault(); e.stopImmediatePropagation();
    const r = await fetch(u.pathname, {method: 'POST', redirect: 'manual'}).catch(() => null);
    if (!r || !(r.ok || r.type === 'opaqueredirect')) return status('The talk did not start. Try again.', 'err');
    leePresent(`/t/${m[1]}/present`, `/t/${m[1]}`);
  }, true);
}
