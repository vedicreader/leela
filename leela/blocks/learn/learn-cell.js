(() => {
  const LV = window.leeLiveCell ||= {views: new Map(), n: 0};
  const SAFE = 'This code runs on your computer.';
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const dec = s => new TextDecoder().decode(Uint8Array.from(atob(s), c => c.charCodeAt(0)));
  const cells = () => [...document.querySelectorAll('.abh .lee-livecell')];
  const same = c => cells().filter(x => x.dataset.walk === c.dataset.walk && x.dataset.step === c.dataset.step);

  function editor(host, doc, onChange) {
    try {
      if (typeof createEditor === 'function' && window.LeeCM) {
        const v = createEditor(host, {doc, lang: 'python', settings: {overviewMode: 'off'}, onChange});
        return {get: () => LeeCM.getDoc(v), set: t => v.dispatch({changes: {from: 0, to: v.state.doc.length, insert: t}}), destroy: () => { try { LeeCM.destroy(v); } catch {} }, focus: () => { try { LeeCM.focus(v); } catch {} }};
      }
    } catch {}
    const ta = el('textarea', 'lv-ta'); ta.value = doc; ta.spellcheck = false; ta.rows = Math.min(14, doc.split('\n').length + 1);
    ta.setAttribute('aria-label', 'Code');
    ta.addEventListener('keydown', e => {
      if (e.key !== 'Tab' || e.shiftKey || e.metaKey || e.ctrlKey || e.altKey) return;
      e.preventDefault(); const s = ta.selectionStart; ta.setRangeText('    ', s, ta.selectionEnd, 'end');
    });
    ta.addEventListener('input', () => onChange?.(ta.value));
    host.append(ta);
    return {get: () => ta.value, set: t => { ta.value = t; }, destroy() {}, focus: () => ta.focus()};
  }

  const numbers = c => document.querySelector(`.live-numbers[data-for="${CSS.escape(c.dataset.id)}"]`);

  function show(c, r) {
    const out = c.querySelector('.lv-out'); out.replaceChildren(); out.classList.remove('lv-old');
    const add = (cls, text) => { const p = el('pre', 'lv-' + cls, text); out.append(p); return p; };
    if (r.stdout) add('stdout', r.stdout);
    if (r.result) add('result', r.result);
    for (const b64 of r.images || []) { const i = el('img', 'lv-img'); i.alt = 'A plot from the code'; i.src = 'data:image/png;base64,' + b64; out.append(i); }
    if (r.timed_out) add('err', 'The code stopped after 5 seconds. A loop may never end. Change the code and run it again.');
    else if (r.error) add('err', [r.error.name + ': ' + r.error.msg, ...(r.error.tb || [])].join('\n'));
    else if (r.ok && !out.children.length) add('none', 'Done. The code printed nothing.');
    const t = c.querySelector('.lv-watch'), rows = Object.entries(r.watch || {});
    t.hidden = !rows.length; t.replaceChildren();
    for (const [k, v] of rows) { const tr = el('tr'); tr.append(el('th', '', k), el('td', '', v)); t.append(tr); }
    if (r.ok) document.dispatchEvent(new CustomEvent('lee-live-ran', {detail: {id: c.dataset.id, watch: r.watch || {}}}));
    const num = document.querySelector(`.live-numbers[data-for="${CSS.escape(c.dataset.id)}"]`);
    if (num) { num.replaceChildren(); for (const [k, v] of rows) { const tr = el('tr'); tr.append(el('th', '', k), el('td', '', v)); num.append(tr); } num.nextElementSibling?.remove?.(); }
  }

  async function post(c, body) {
    const r = await fetch('/learn/cell/run', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({id: c.dataset.id, walk: c.dataset.walk, step: c.dataset.step, ...body})});
    const j = await r.json().catch(() => ({}));
    if (!r.ok) return {ok: false, error: {name: 'Error', msg: j.error || 'The code did not run. Try again.', tb: []}, stdout: '', result: '', images: [], watch: {}};
    return j;
  }

  async function run(c, extra = {}) {
    const v = LV.views.get(c); if (!v || c.dataset.busy) return;
    const state = c.querySelector('.lv-state'); c.dataset.busy = '1'; c.querySelector('.lv-run').disabled = true; c.querySelector('.lv-out').classList.remove('lv-old'); numbers(c)?.classList.remove('lv-old'); state.textContent = LV.ran ? 'Running…' : 'Starting the kernel… the first run can take 10 seconds.'; state.classList.add('lv-spin');
    try {
      const r = await post(c, {code: (v.head ? v.head + '\n' : '') + v.ed.get(), watch: (c.dataset.watch || '').split(',').filter(Boolean), ...extra});
      v.last = r; LV.ran = true; show(c, r); state.textContent = '';
    } catch { state.textContent = 'The code did not run. Try again.'; }
    finally { state.classList.remove('lv-spin'); delete c.dataset.busy; c.querySelector('.lv-run').disabled = false; }
  }

  // A name in the demo moved: put its new number in the one place the code sets it, and say that the output is old until a run.
  async function rewrite(c, name, value) {
    const v = LV.views.get(c); if (!v || c.dataset.busy) return false;
    const r = await fetch('/learn/cell/literal', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({code: v.ed.get(), name, value})}).then(x => x.json()).catch(() => null);
    if (!r?.ok) return false;
    v.ed.set(r.code); c.querySelector('.lv-out').classList.add('lv-old'); c.querySelector('.lv-state').textContent = r.said;
    numbers(c)?.classList.add('lv-old');
    return true;
  }
  LV.rewrite = rewrite;

  async function check(c) {
    const v = LV.views.get(c), say = c.querySelector('.lv-state');
    if (!v?.last || v.last.timed_out) { say.textContent = 'Run the code first.'; return; }
    const body = new URLSearchParams({aid: `${c.dataset.id}-${Date.now().toString(36)}`, out: v.last.stdout || '', watch: JSON.stringify(v.last.watch || {})});
    const r = await fetch('/learn/abh' + c.dataset.checkUrl, {method: 'POST', body}).then(x => x.json()).catch(() => null);
    if (!r?.ok) { say.textContent = 'The check did not run. Try again.'; return; }
    const g = Object.values(r.gauge || {})[0];
    say.textContent = r.say + (g ? ` Your level on this idea: ${g.state}.` : '');
    c.dataset.checked = r.correct ? 'yes' : 'no';
  }

  function reset(c, all) {
    for (const x of all ? same(c) : [c]) { const v = LV.views.get(x); if (!v) continue; v.ed.set(v.body); v.last = null; x.querySelector('.lv-out').replaceChildren(); x.querySelector('.lv-watch').hidden = true; x.querySelector('.lv-state').textContent = ''; delete x.dataset.checked; }
    post(c, {code: '', reset: true});
  }

  function mount(c) {
    if (LV.views.has(c) || !c.dataset.srcB64) return;
    const lines = dec(c.dataset.srcB64).split('\n'), ro = +c.dataset.ro || 0, head = lines.slice(0, ro).join('\n'), body = lines.slice(ro).join('\n');
    c.querySelector('pre')?.remove(); c.querySelector(':scope > .lbl')?.remove(); c.classList.add('lv-on');
    const top = el('div', 'lv-top'); top.append(el('span', 'lbl', 'Code'), el('span', 'lv-safe', SAFE));
    const host = el('div', 'lv-ed'), bar = el('div', 'lv-bar');
    const btn = (cls, text, f, title) => { const b = el('button', 'lee-btn ' + cls, text); b.type = 'button'; if (title) b.title = title; b.addEventListener('click', f); return b; };
    const runB = btn('lv-run', 'Run', () => run(c), 'Run (Ctrl or ⌘ + Enter)');
    bar.append(runB, el('kbd', 'lv-key', /Mac/.test(navigator.platform) ? '⌘↵' : 'Ctrl+↵'));
    if (c.dataset.checkUrl) bar.append(btn('lv-check', 'Check', () => check(c)));
    bar.append(btn('lv-reset', 'Reset', () => reset(c, false), 'Back to the first code'));
    if (same(c).length > 1) bar.append(btn('lv-reset-all', 'Reset all', () => reset(c, true), 'Every cell of this step, and its variables'));
    bar.append(el('span', 'lv-state'));
    const out = el('div', 'lv-out'); out.setAttribute('aria-live', 'polite');
    const watch = el('table', 'lv-watch'); watch.hidden = true;
    c.append(top, ...(head ? [el('pre', 'lv-ro', head)] : []), host, bar, out, watch);
    const ed = editor(host, body, () => {});
    LV.views.set(c, {ed, head, body, last: null});
  }

  function scan() {
    for (const [c, v] of LV.views) if (!c.isConnected) { v.ed.destroy(); LV.views.delete(c); }
    cells().forEach(mount);
  }
  LV.scan = scan;
  if (!LV.on) {
    LV.on = true; document.addEventListener('htmx:afterSettle', scan);
    // the chord is taken on the window, before Leela's keymap, and only inside a cell: no other key and no other place
    window.addEventListener('keydown', e => {
      const c = e.key === 'Enter' && (e.metaKey || e.ctrlKey) && e.target.closest?.('.abh .lee-livecell');
      if (c) { e.preventDefault(); e.stopImmediatePropagation(); run(c); }
    }, true);
  }
  scan();
})();
