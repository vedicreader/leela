/* Putting things in the document, and connecting them to data. The slash menu inserts, the palette
 * lists what the component host publishes, and the wiring panel is where a port meets an expression. */

function cvPdf(b) {
  const box = document.createElement('div'); box.className = 'cv-frame cv-pdfbox';
  const raw = (b.attrs || {}).src || '';
  //: A relative src is a file beside the canvas, which only this server will serve.
  const src = /^(https?:|\/)/.test(raw) ? raw : `/canvas/file?path=${encodeURIComponent(raw)}`;
  box.innerHTML = `<iframe src="${cvEsc(src)}#view=FitH&toolbar=0" style="height:${(b.props || {}).height || 560}px"></iframe>` +
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
  {name: 'Text', icon: '¶', hint: 'a plain paragraph', group: '1_Basic', alias: ['paragraph', 'p'],
   make: () => ({kind: 'text', body: ''})},
  {name: 'Heading', icon: 'H', hint: 'a section title', group: '1_Basic', alias: ['h2', 'title'],
   make: () => ({kind: 'text', body: '## '})},
  {name: 'Bulleted list', icon: '•', hint: 'one point per line', group: '1_Basic', alias: ['ul', 'list'],
   make: () => ({kind: 'text', body: '- '})},
  {name: 'Note', icon: '❞', hint: 'an aside, in markdown', group: '1_Basic', alias: ['callout', 'aside'],
   make: () => ({kind: 'note', body: 'Note.'})},
  {name: 'Code', icon: '{}', hint: 'python, sharing the document namespace', group: '2_Live', alias: ['py', 'cell'],
   make: () => ({kind: 'code', body: ''})},
  {name: 'Live sentence', icon: '≈', hint: 'prose bound to an expression', group: '2_Live', alias: ['data', 'bind'],
   make: () => ({kind: 'data', binds: {text: 'f"..."'}, body: ''})},
  {name: 'Ask', icon: '✦', hint: 'a question that stays in the document', group: '2_Live', alias: ['ai', 'question'],
   make: () => ({kind: 'ask', body: ''})},
  {name: 'Component', icon: '▦', hint: 'a brick from a package', group: '3_Embed', alias: ['brick', 'widget'],
   palette: true},
  {name: 'Sketch', icon: '✧', hint: 'a component written here, in the document', group: '3_Embed', alias: ['sim', 'js'],
   make: () => ({kind: 'sim', props: {height: '160'}, body: SKETCH_STARTER})},
  {name: 'YouTube', icon: '▷', hint: 'paste a link', group: '3_Embed', alias: ['video'], ask: 'video URL or id',
   make: v => ({kind: 'video', attrs: {src: v}, body: ''})},
  {name: 'PDF', icon: '⤓', hint: 'a file beside this one, or a URL', group: '3_Embed', alias: ['file'],
   ask: 'pdf path or URL', make: v => ({kind: 'pdf', attrs: {src: v}, body: ''})},
  {name: 'Check yourself', icon: '✓', hint: 'questions from this document', group: '4_Learn', alias: ['quiz', 'test'],
   make: () => ({kind: 'quiz', body: '1. ?'})}];

const SKETCH_STARTER = `const draw = () => {
  root.innerHTML = '<div class="row"><label>n</label><input type=range min=0 max=100 id=n></div><b id=out></b>';
  const n = document.getElementById('n');
  n.value = props.n ?? 40;
  const show = () => { document.getElementById('out').textContent = n.value; emit('n', +n.value); };
  n.oninput = show; show();
};`;

//: The `/` stays in the paragraph while the menu is up and the query is what follows it, so the
//: person sees what they are searching for. Both go when something is chosen or the menu closes.
function cvSlash(id, el) {
  const r = el.getBoundingClientRect();
  cvSlashAt(id, r.left, r.bottom + 6, el);
}

function cvSlashAt(id, x, y, el) {
  const was = cvBrick(id)?.body ?? '';
  const undo = async () => { if (el) el.textContent = was; await cvOp({op: 'replace', id, body: was}, true); };
  cvOpenMenu(SLASH, x, y, it => cvSlashPick(it, id, el, undo), {width: 300, empty: 'no block by that name'});
  if (el) cvPop.onQuery = q => { el.textContent = q === null ? '' : '/' + q; cvCaretEnd(el); };
}

async function cvSlashPick(it, id, el, undo) {
  if (el) el.textContent = '';
  await cvOp({op: 'replace', id, body: ''}, false);
  try {
    if (it.palette) return await cvPalette(id, undo);
    let v = null;
    if (it.ask) { v = prompt(it.ask); if (!v) return await undo(); }
    const spec = it.make(v);
    const fresh = await cvOp({op: 'insert', after: id, ...spec});
    await cvOp({op: 'remove', id});
    cvLandOn(fresh);
  } catch (e) { cvStatus(String(e), 'bad'); await undo(); }
}

//: A block you just asked for should have the cursor in it.
function cvLandOn(r) {
  if (!r?.ok) return;
  const el = $$(`.cv-prose[data-id="${r.brick.id}"]`) || $$(`.cv-brick[data-id="${r.brick.id}"] textarea`);
  if (!el) return;
  el.focus(); cvCaretEnd(el);
}

function cvCaretEnd(el) {
  if (el.tagName === 'TEXTAREA') { el.selectionStart = el.selectionEnd = el.value.length; return; }
  const r = document.createRange(); r.selectNodeContents(el); r.collapse(false);
  const s = getSelection(); s.removeAllRanges(); s.addRange(r);
}

/* === the palette: what the component host publishes === */

async function cvPalette(after, undo) {
  if (!cv.palette) cv.palette = await (await fetch('/canvas/palette')).json();
  const groups = cv.palette.groups || {};
  const order = Object.keys(groups);
  const items = (cv.palette.bricks || []).map(b => ({
    name: b.title, icon: '▦', hint: `${b.doc || b.src}`, alias: [b.name, b.src, ...b.ports.map(p => p.name)],
    group: `${order.indexOf(b.group) + 1}_${b.group}`, b}));
  if (!items.length) { cvStatus('no component host: start one and set BRICK_HOST', 'bad'); return undo && undo(); }
  const anchor = brickEl(after)?.getBoundingClientRect() || {left: 200, bottom: 200};
  cvOpenMenu(items, anchor.left, anchor.bottom + 6, async it => {
    const r = await cvOp({op: 'insert', after, kind: 'brick', attrs: {src: it.b.src}, props: {height: String(it.b.height)}});
    if (!r.ok) return void (undo && await undo());
    try { await cvFill(r.brick.id, it.b); }
    catch (e) { cvStatus(String(e), 'bad'); }
    await cvOp({op: 'remove', id: after});                  // the brick is in either way; the `/` line is not
  }, {width: 320, empty: 'no component by that name'});
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
