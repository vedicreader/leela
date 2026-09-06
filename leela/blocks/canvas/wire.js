/* Putting things in the document, and connecting them to data. The slash menu inserts, the palette
 * lists what the component host publishes, and the wiring panel is where a port meets an expression. */

function cvPdf(b) {
  const box = document.createElement('div'); box.className = 'cv-frame cv-pdfbox';
  const src = (b.attrs || {}).src || '';
  box.innerHTML = `<iframe src="${cvEsc(src)}#view=FitH" style="height:${(b.props || {}).height || 520}px"></iframe>` +
    `<div class="cv-cap">${cvEsc((b.body || src).trim())}</div>`;
  return box;
}

//: A facade, not the embed: nothing is fetched from YouTube until somebody asks for it, and the
//: document still reads the same offline.
function cvVideo(b) {
  const box = document.createElement('div'); box.className = 'cv-frame cv-videobox';
  const raw = (b.attrs || {}).src || '';
  const id = (raw.match(/(?:v=|youtu\.be\/|embed\/)([\w-]{6,})/) || [, raw])[1];
  const t = (b.attrs || {}).t ? `?start=${parseInt(b.attrs.t)}` : '';
  const h = (b.props || {}).height || 300;
  const face = document.createElement('button');
  face.className = 'cv-play'; face.style.height = h + 'px';
  face.innerHTML = `<span class="cv-tri">▶</span><span class="cv-vid">youtube · ${cvEsc(id)}</span>`;
  face.onclick = () => {
    const f = document.createElement('iframe');
    f.src = `https://www.youtube-nocookie.com/embed/${id}${t}`; f.allowFullscreen = true; f.style.height = h + 'px';
    face.replaceWith(f);
  };
  box.appendChild(face);
  if ((b.body || '').trim()) box.appendChild(Object.assign(document.createElement('div'),
    {className: 'cv-cap', textContent: b.body.trim()}));
  return box;
}

/* === the slash menu === */

const SLASH = [
  {key: 'code', label: 'Code cell', hint: 'python, shares the document namespace', make: () => ({kind: 'code', body: ''})},
  {key: 'ask', label: 'Ask', hint: 'a question that stays in the document', make: () => ({kind: 'ask', body: ''})},
  {key: 'note', label: 'Note', hint: 'an aside, in markdown', make: () => ({kind: 'note', body: 'Note.'})},
  {key: 'brick', label: 'Component…', hint: 'a brick from a package', palette: true},
  {key: 'sketch', label: 'Sketch', hint: 'a component written here, in the document',
   make: () => ({kind: 'sim', props: {height: '160'}, body: SKETCH_STARTER})},
  {key: 'video', label: 'YouTube', hint: 'paste a link', ask: 'video URL or id',
   make: v => ({kind: 'video', attrs: {src: v}, body: ''})},
  {key: 'pdf', label: 'PDF', hint: 'a path or a URL', ask: 'pdf path or URL',
   make: v => ({kind: 'pdf', attrs: {src: v}, body: ''})},
  {key: 'quiz', label: 'Check yourself', hint: 'questions from this document', make: () => ({kind: 'quiz', body: '1. ?'})}];

const SKETCH_STARTER = `const draw = () => {
  root.innerHTML = '<div class="row"><label>n</label><input type=range min=0 max=100 id=n></div><b id=out></b>';
  const n = document.getElementById('n');
  n.value = props.n ?? 40;
  const show = () => { document.getElementById('out').textContent = n.value; emit('n', +n.value); };
  n.oninput = show; show();
};`;

function cvMenu(items, x, y, pick) {
  const m = $$('#cv-menu');
  m.innerHTML = items.map((it, i) =>
    `<button data-i="${i}"><b>${cvEsc(it.label)}</b><span>${cvEsc(it.hint || '')}</span></button>`).join('');
  m.style.left = Math.min(x, innerWidth - 300) + 'px'; m.style.top = y + 'px'; m.hidden = false;
  m.onclick = ev => {
    const btn = ev.target.closest('button'); if (!btn) return;
    m.hidden = true; pick(items[+btn.dataset.i]);
  };
  setTimeout(() => document.addEventListener('click', () => { m.hidden = true; }, {once: true}), 0);
}

function cvSlash(id, el) {
  const r = el.getBoundingClientRect();
  cvMenu(SLASH, r.left, r.bottom + 6, async it => {
    el.textContent = ''; el.blur();
    await cvOp({op: 'replace', id, body: ''}, false);        // the `/` that opened this menu is not prose
    if (it.palette) return cvPalette(id);
    let v = null;
    if (it.ask) { v = prompt(it.ask); if (!v) return; }
    await cvOp({op: 'insert', after: id, ...it.make(v)});
    await cvOp({op: 'remove', id});
  });
}

/* === the palette: what the component host publishes === */

async function cvPalette(after) {
  if (!cv.palette) cv.palette = await (await fetch('/canvas/palette')).json();
  const items = (cv.palette.bricks || []).map(b => ({label: b.title, hint: `${b.src} · in ${b.ports.map(p => p.name).join(', ') || '—'}`, b}));
  if (!items.length) return cvStatus('no component host: start lego on 5001', 'bad');
  const anchor = brickEl(after)?.getBoundingClientRect() || {left: 200, bottom: 200};
  cvMenu(items, anchor.left, anchor.bottom + 6, async it => {
    const r = await cvOp({op: 'insert', after, kind: 'brick', attrs: {src: it.b.src}, props: {height: String(it.b.height)}});
    if (r.ok) { await cvFill(r.brick.id, it.b); await cvOp({op: 'remove', id: after}); }
  });
}

//: Taking the snippet the component's own package ships. This is the whole of "connect it to its
//: data source": the package knows how to fill its ports, and the document keeps the code it used.
async function cvFill(id, spec) {
  const name = spec.name || (cvBrick(id)?.attrs?.src || '').split(':').pop();
  const w = await (await fetch(`/canvas/wire/${name}`)).json();
  if (!w.ok) return cvStatus(w.error || 'no wiring for that brick', 'bad');
  if (w.wire) {
    const at = cv.canvas.bricks.findIndex(x => x.id === id);
    const code = await cvOp({op: 'insert', at, kind: 'code', body: w.wire});
    //: The import form first. Where the package is not installed beside this document, the same
    //: package's host answers instead, and the document keeps whichever one it ran.
    if (code.ok) {
      const r = await api('/canvas/run', {path: cv.path, id: code.brick.id, source: w.wire});
      const missing = (r.run?.outputs || []).some(o => /ModuleNotFoundError|ImportError/.test(o.ename || ''));
      if (missing && w.remote) await cvOp({op: 'replace', id: code.brick.id, body: w.remote}, false);
      await cvRun(code.brick.id);
    }
  }
  for (const [port, expr] of Object.entries(w.binds || {})) await cvOp({op: 'bind', id, port, expr}, false);
  const r = await api('/canvas/open?path=' + encodeURIComponent(cv.path));
  if (r.ok) { cv.ports = r.ports; cvSync(r.canvas); cvApplyPorts(cv.ports); }
  cvStatus(`wired ${name} from its package`, 'ok');
}

/* === the wiring panel === */

async function cvWire(id, port) {
  const b = cvBrick(id); if (!b) return;
  const panel = $$('#cv-wire');
  const src = (b.attrs || {}).src || 'sketch';
  const name = src.split(':').pop();
  let spec = null;
  if (b.kind === 'brick') {
    if (!cv.palette) cv.palette = await (await fetch('/canvas/palette')).json();
    spec = (cv.palette.bricks || []).find(x => x.name === name);
  }
  const ins = spec ? spec.ports : Object.keys(b.binds || {}).map(k => ({name: k, doc: ''}));
  const outs = spec ? spec.emits : [];
  const resolved = cv.ports[id] || {};
  panel.innerHTML = `
    <header><b>${cvEsc(spec?.title || name)}</b><code>${cvEsc(src)}</code>
      <button class="cv-x" onclick="cvWireClose()">✕</button></header>
    <div class="cv-wsec"><h4>draws from</h4>${ins.map(p => {
      const r = resolved[p.name] || {};
      const state = r.ok === true ? 'ok' : r.ok === false ? 'bad' : '';
      return `<label class="cv-wrow ${state}"><span title="${cvEsc(p.doc || '')}">${cvEsc(p.name)}</span>
        <input data-port="${cvEsc(p.name)}" value="${cvEsc((b.binds || {})[p.name] || '')}" placeholder="an expression">
        <em>${cvEsc(r.ok === false ? r.error : r.ok ? cvPeek(r.value) : 'unbound')}</em></label>`;
    }).join('')}
      <div class="cv-wnames">${cv.names.slice(0, 24).map(n => `<button data-name="${cvEsc(n)}">${cvEsc(n)}</button>`).join('')}</div>
    </div>
    ${outs.length ? `<div class="cv-wsec"><h4>hands back</h4>${outs.map(p =>
      `<label class="cv-wrow"><span title="${cvEsc(p.doc || '')}">${cvEsc(p.name)}</span>
       <input data-emit="${cvEsc(p.name)}" value="${cvEsc((b.attrs || {})['emit_' + p.name] || p.name)}" placeholder="a name">
       <em>clicking sets this name</em></label>`).join('')}</div>` : ''}
    <footer>
      ${spec ? '<button class="cv-fill">fill from its package</button>' : ''}
      <button class="cv-apply">apply</button>
    </footer>`;
  panel.hidden = false;
  panel.dataset.id = id;
  $all('.cv-wnames button', panel).forEach(x => x.onclick = () => {
    const first = $$('.cv-wrow input', panel); if (first) { first.value = x.dataset.name; first.focus(); }
  });
  const fill = $$('.cv-fill', panel); if (fill) fill.onclick = () => { cvWireClose(); cvFill(id, spec); };
  $$('.cv-apply', panel).onclick = async () => {
    for (const inp of $all('input[data-port]', panel)) await cvOp({op: 'bind', id, port: inp.dataset.port, expr: inp.value}, false);
    const attrs = {...(b.attrs || {})};
    for (const inp of $all('input[data-emit]', panel)) attrs['emit_' + inp.dataset.emit] = inp.value;
    await cvOp({op: 'replace', id, attrs}, false);
    const r = await api('/canvas/open?path=' + encodeURIComponent(cv.path));
    if (r.ok) { cv.ports = r.ports; cvSync(r.canvas); cvApplyPorts(cv.ports); }
    cvWireClose(); cvStatus('wired', 'ok');
  };
  if (port) $$(`input[data-port="${port}"]`, panel)?.focus();
}

function cvWireClose() { $$('#cv-wire').hidden = true; }
function cvPeek(v) {
  const s = JSON.stringify(v);
  return s === undefined ? String(v) : s.length > 46 ? s.slice(0, 45) + '…' : s;
}
