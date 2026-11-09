(() => {
  const abh = document.querySelector('.abh');
  if (!abh) return;
  const id = x => document.getElementById(x), STORE = 'lee-learn-keys';
  if (!abh.dataset.dontGet) {
    abh.dataset.dontGet = '1';
    abh.addEventListener('click', e => {
      const b = e.target.closest('button.rh-page');
      if (!b) return;
      e.preventDefault(); e.stopImmediatePropagation();
      window.leeLearnToAgent?.(`I don't get this idea: ${abh.querySelector('#concept-name')?.textContent || b.dataset.t}`, true);
    }, true);
  }
  const mark = kf => kf.querySelectorAll('.kf-do').forEach(b => {
    const d = b.dataset;
    if (['explain', 'dictate'].includes(d.act)) return b.closest('li').remove();
    if (!d.code) return;
    const sels = [].concat(window.abhyasaKeys?.[d.code] || []), mk = '⌥' + d.code.replace(/^(?:Key|Digit)/, '');
    b.disabled = ![...abh.querySelectorAll('button kbd, a kbd')].some(k => k.textContent.trim() === mk) && !sels.some(s => abh.querySelector(s));
  });
  const show = (kf, on) => { kf.querySelector('.kf-panel').hidden = !on; kf.querySelector('.kf-pill').setAttribute('aria-expanded', String(on)); if (on) mark(kf); };
  async function keys() {
    id('kf')?.remove();
    const main = abh.querySelector('main'); if (!main) return;
    const w = abh.querySelector('#rail li.now a')?.getAttribute('href') || [...main.querySelectorAll('[href^="/w/"], [hx-post^="/w/"], [hx-get^="/w/"]')].map(x => /^\/w\/[^/?]+/.exec(x.getAttribute('href') || x.getAttribute('hx-post') || x.getAttribute('hx-get'))?.[0])[0];
    const at = abh.querySelector('#concept-name') ? '/c/' + abh.querySelector('#concept-name').dataset.concept : w || '/';
    const html = await fetch('/learn/abh/keys/panel?path=' + encodeURIComponent(at)).then(r => r.ok ? r.text() : '').catch(() => '');
    if (!html || id('kf') || abh.querySelector('main') !== main) return;
    const t = document.createElement('template'); t.innerHTML = html;
    t.content.querySelectorAll('link, script').forEach(x => x.remove());
    const kf = t.content.querySelector('#kf'); if (!kf) return;
    abh.append(kf); mark(kf);
    let first = null; try { first = localStorage.getItem(STORE); if (first === null) localStorage.setItem(STORE, 'closed'); } catch {}
    show(kf, first === null && at === '/');
    kf.addEventListener('click', e => {
      const t = e.target.closest('button, a'); if (!t) return;
      if (t.id === 'kf-pill') show(kf, kf.querySelector('.kf-panel').hidden);
      else if (t.id === 'kf-close') show(kf, false);
      else if (t.id === 'kf-hide') { fetch('/learn/abh' + t.dataset.url, {method: 'POST', body: new URLSearchParams({on: '0'})}).finally(() => kf.remove()); }
      else if (t.classList.contains('kf-do')) {
        show(kf, false);
        if (t.dataset.act === 'search') return window.leeVaultWorkbench?.('find');
        main.dispatchEvent(new KeyboardEvent('keydown', {code: t.dataset.code, altKey: true, bubbles: true, cancelable: true}));
      }
    });
  }
  keys();
})();
