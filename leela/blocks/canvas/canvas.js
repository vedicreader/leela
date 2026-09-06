/* The canvas: one document made of bricks, drawn once and repainted a brick at a time.
 * `cv` is the whole client state, the way `lee` is in the IDE. */
const cv = {path: '', canvas: null, ports: {}, host: '', names: [], files: [], palette: null, focus: null, dirty: false};
const $$ = (sel, root = document) => root.querySelector(sel);
const $all = (sel, root = document) => [...root.querySelectorAll(sel)];
const brickEl = id => $$(`.cv-brick[data-id="${id}"]`);
const cvBrick = id => (cv.canvas?.bricks || []).find(b => b.id === id);

async function api(path, body) {
  const r = await fetch(path, body ? {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify(body)}
                              : undefined);
  const j = await r.json();
  if (!j.ok && j.error) cvStatus(j.error, 'bad');
  return j;
}

function cvStatus(text, kind = '') {
  const el = $$('#cv-status'); if (!el) return;
  el.textContent = text; el.className = 'cv-status ' + kind;
  clearTimeout(cvStatus.t); cvStatus.t = setTimeout(() => { el.textContent = ''; }, 4000);
}

/* === opening === */

async function cvOpen(path, fresh) {
  const r = await api(`/canvas/open?path=${encodeURIComponent(path)}${fresh ? '&fresh=1' : ''}`);
  if (!r.ok) return;
  cv.path = path; cv.canvas = r.canvas; cv.ports = r.ports || {}; cv.host = r.host; cv.names = r.names || [];
  document.title = r.canvas.title;
  $$('#cv-title').textContent = r.canvas.title;
  $$('#cv-mode').textContent = r.canvas.meta.mode || 'make';
  cvRender();
  cvTrail(r.trail || []);
  cvStatus(`${r.canvas.bricks.length} bricks · ${cv.names.length} live names`, 'ok');
}

function cvRender() {
  const doc = $$('#cv-doc'); doc.innerHTML = '';
  cv.canvas.bricks.forEach((b, i) => doc.appendChild(cvPaint(b, i)));
  cvApplyPorts(cv.ports);
}

//: Redrawing the whole document would rebuild every iframe, and a frame that reloads forgets what
//: the person had selected in it. Only what actually changed is repainted.
function cvSync(canvas) {
  const was = new Map((cv.canvas?.bricks || []).map(b => [b.id, b]));
  const now = canvas.bricks;
  cv.canvas = canvas;
  for (const id of was.keys()) if (!now.some(b => b.id === id)) brickEl(id)?.remove();
  now.forEach((b, i) => {
    const before = was.get(b.id), el = brickEl(b.id);
    if (!before || !el) return void cvRepaint(b, i);
    if (cvSame(before, b)) { if (el.dataset.i !== String(i)) el.dataset.i = i; return; }
    if (cvFrameKind(b) && before.body === b.body && cvSame(before, b, true)) return;   // bindings alone: props, not a reload
    cvRepaint(b, i);
  });
  cvOrder(now);
}

const cvFrameKind = b => b.kind === 'brick' || b.kind === 'sim';
const cvSame = (a, b, ignoreBinds) => a.kind === b.kind && a.body === b.body &&
  JSON.stringify(a.attrs) === JSON.stringify(b.attrs) && JSON.stringify(a.props) === JSON.stringify(b.props) &&
  (ignoreBinds || JSON.stringify(a.binds) === JSON.stringify(b.binds));

function cvOrder(bricks) {
  const doc = $$('#cv-doc');
  bricks.forEach((b, i) => { const el = brickEl(b.id); if (el && doc.children[i] !== el) doc.insertBefore(el, doc.children[i] || null); });
}

function cvRepaint(brick, at) {
  const old = brickEl(brick.id), node = cvPaint(brick, at);
  if (old) old.replaceWith(node);
  else {
    const doc = $$('#cv-doc'), ref = doc.children[at];
    ref ? doc.insertBefore(node, ref) : doc.appendChild(node);
  }
  cvApplyPorts(cv.ports);
  return node;
}

/* === one brick === */

const KIND_LABEL = {code: 'code', ask: 'ask', brick: 'component', sim: 'sketch', pdf: 'pdf',
                    video: 'video', reply: 'answer', note: 'note', quiz: 'check', data: 'data', text: 'text'};

function cvPaint(b, i) {
  const wrap = document.createElement('section');
  wrap.className = `cv-brick cv-${b.kind}`; wrap.dataset.id = b.id; wrap.dataset.i = i;
  wrap.appendChild(cvRail(b));
  wrap.appendChild(({text: cvText, code: cvCode, ask: cvAsk, brick: cvComponent, sim: cvSim,
                     pdf: cvPdf, video: cvVideo, reply: cvProse, note: cvProse, quiz: cvQuiz,
                     data: cvData}[b.kind] || cvProse)(b));
  return wrap;
}

function cvRail(b) {
  const rail = document.createElement('div');
  rail.className = 'cv-rail';
  rail.innerHTML = `<span class="cv-kind">${KIND_LABEL[b.kind] || b.kind}</span>`;
  const btn = (label, title, fn) => {
    const x = document.createElement('button'); x.className = 'cv-rbtn'; x.textContent = label; x.title = title;
    x.onclick = fn; rail.appendChild(x); return x;
  };
  if (b.kind === 'code') btn('▶', 'run this cell (mod+enter)', () => cvRun(b.id));
  if (b.kind === 'ask') btn('▶', 'ask', () => cvAskRun(b.id));
  if (b.kind === 'brick' || b.kind === 'sim') btn('⚙', 'ports and wiring', () => cvWire(b.id));
  if (b.kind === 'text') btn('</>', 'show the markdown (mod+e)', () => cvRawToggle(b));
  btn('␡', 'remove this brick', () => cvOp({op: 'remove', id: b.id}));
  return rail;
}

/* Prose a person edits in place. It stays rendered while you work in it, and goes back to markdown
 * on the way out: selecting a sentence to ask about it must not change what the sentence looks like. */
function cvText(b) {
  const el = document.createElement('div');
  el.className = 'cv-prose'; el.contentEditable = 'true'; el.spellcheck = false;
  el.dataset.id = b.id;
  el.innerHTML = cvMd(b.body) || '<p><br></p>';
  el.onfocus = () => { cv.focus = b.id; };
  el.onblur = () => {
    const body = el.classList.contains('raw') ? el.innerText.trimEnd() : cvHtmlToMd(el);
    if (body !== b.body) { b.body = body; cvOp({op: 'replace', id: b.id, body}, false); }
  };
  el.onkeydown = ev => cvTextKeys(ev, b, el);
  return el;
}

function cvRawToggle(b) {
  const el = $$(`.cv-prose[data-id="${b.id}"]`); if (!el) return;
  const raw = el.classList.toggle('raw');
  if (raw) el.textContent = b.body;
  else { b.body = el.innerText.trimEnd(); el.innerHTML = cvMd(b.body) || '<p><br></p>'; }
  el.focus();
}

//: Rendered prose back to the markdown the file keeps. Only what `cvMd` can produce needs handling.
function cvHtmlToMd(root) {
  const inline = n => {
    if (n.nodeType === 3) return n.nodeValue;
    if (n.nodeType !== 1) return '';
    const kids = [...n.childNodes].map(inline).join('');
    return {CODE: `\`${kids}\``, STRONG: `**${kids}**`, B: `**${kids}**`, EM: `*${kids}*`, I: `*${kids}*`,
            A: `[${kids}](${n.getAttribute('href') || ''})`, BR: '\n'}[n.tagName] ?? kids;
  };
  const out = [];
  for (const n of root.childNodes) {
    if (n.nodeType === 3) { if (n.nodeValue.trim()) out.push(n.nodeValue.trim()); continue; }
    if (n.nodeType !== 1) continue;
    const t = n.tagName, body = inline(n).trim();
    if (/^H[1-6]$/.test(t)) out.push('#'.repeat(+t[1]) + ' ' + body);
    else if (t === 'UL') out.push([...n.children].map(li => '- ' + inline(li).trim()).join('\n'));
    else if (t === 'OL') out.push([...n.children].map((li, i) => `${i + 1}. ` + inline(li).trim()).join('\n'));
    else if (t === 'BLOCKQUOTE') out.push('> ' + body);
    else if (t === 'HR') out.push('---');
    else if (body) out.push(body);
  }
  return out.join('\n\n');
}

function cvTextKeys(ev, b, el) {
  if (ev.key === '/' && !el.textContent.trim()) { setTimeout(() => cvSlash(b.id, el), 0); return; }
  if (ev.key === 'e' && (ev.metaKey || ev.ctrlKey)) { ev.preventDefault(); cvRawToggle(b); return; }
  if (ev.key === 'Enter' && (ev.metaKey || ev.ctrlKey)) { ev.preventDefault(); el.blur(); return; }
  if (ev.key === 'Escape') el.blur();
}

function cvProse(b) {
  const el = document.createElement('div');
  el.className = 'cv-prose cv-said';
  el.innerHTML = cvMd(b.body);
  return el;
}

//: Prose bound to the namespace. The only brick that redraws itself with no iframe in it.
function cvData(b) {
  const el = document.createElement('div');
  el.className = 'cv-prose cv-live'; el.id = 'live-' + b.id;
  el.innerHTML = cvMd(cvLiveText(b));
  el.appendChild(cvPortStrip(b));
  return el;
}

function cvLiveText(b) {
  const r = (cv.ports[b.id] || {}).text;
  if (!r) return b.body || '_not bound_';
  return r.ok ? String(r.value) : `\`${r.error}\``;
}

function cvQuiz(b) {
  const el = document.createElement('div');
  el.className = 'cv-quizbox';
  const items = b.body.split('\n').filter(Boolean);
  el.innerHTML = '<b>Check yourself</b>' + items.map((q, i) =>
    `<label class="cv-q"><input type="checkbox"><span>${cvInline(q.replace(/^\d+[.)]\s*/, ''))}</span></label>`).join('');
  return el;
}

/* === code === */

function cvCode(b) {
  const box = document.createElement('div'); box.className = 'cv-codebox';
  const ta = document.createElement('textarea');
  ta.className = 'cv-src'; ta.value = b.body; ta.spellcheck = false; ta.rows = 1;
  const grow = () => { ta.style.height = 'auto'; ta.style.height = (ta.scrollHeight + 2) + 'px'; };
  ta.oninput = () => { b.body = ta.value; grow(); cv.dirty = true; };
  ta.onfocus = () => { cv.focus = b.id; };
  ta.onkeydown = ev => {
    if (ev.key === 'Enter' && (ev.metaKey || ev.ctrlKey)) { ev.preventDefault(); cvRun(b.id); }
    if (ev.key === 'Tab') { ev.preventDefault(); document.execCommand('insertText', false, '    '); }
  };
  box.appendChild(ta);
  const out = document.createElement('div'); out.className = 'cv-out'; out.id = 'out-' + b.id;
  box.appendChild(out);
  setTimeout(grow, 0);
  return box;
}

function cvOutputs(id, run) {
  const out = $$('#out-' + id); if (!out) return;
  out.innerHTML = '';
  for (const o of (run.outputs || [])) {
    const d = document.createElement('div');
    if (o.output_type === 'error') { d.className = 'cv-err'; d.textContent = `${o.ename}: ${o.evalue}\n` + (o.traceback || []).join('\n'); }
    else if (o.output_type === 'stream') { d.className = 'cv-stream ' + (o.name || ''); d.textContent = o.text; }
    else { d.className = 'cv-value'; d.textContent = (o.data || {})['text/plain'] ?? ''; }
    out.appendChild(d);
  }
  const meta = document.createElement('div'); meta.className = 'cv-runmeta';
  meta.textContent = `${run.ms.toFixed(0)}ms` + (run.defs?.length ? ` · defines ${run.defs.join(', ')}` : '');
  out.appendChild(meta);
  brickEl(id)?.classList.toggle('failed', !run.ok);
}

async function cvRun(id) {
  const b = cvBrick(id); if (!b) return;
  brickEl(id)?.classList.add('running');
  const r = await api('/canvas/run', {path: cv.path, id, source: b.body});
  brickEl(id)?.classList.remove('running');
  if (!r.ok) return;
  cvOutputs(id, r.run);
  cvSettle(r);
}

function cvSettle(r) {
  for (const [id, run] of Object.entries(r.runs || {})) if (id !== r.id) cvOutputs(id, run);
  if (r.ports) { cv.ports = {...cv.ports, ...r.ports}; cvApplyPorts(r.ports); }
  const changed = Object.keys(r.runs || {}).length, redrawn = Object.keys(r.ports || {}).length;
  if (changed + redrawn) cvStatus(`${changed} cell${changed === 1 ? '' : 's'} rerun, ${redrawn} brick${redrawn === 1 ? '' : 's'} redrawn`, 'ok');
}

async function cvRunAll() {
  for (const b of cv.canvas.bricks) if (b.kind === 'code') await cvRun(b.id);
  cvStatus('whole document run', 'ok');
}

/* === embedded components === */

function cvFrameSrc(b) {
  const src = (b.attrs || {}).src || '';
  if (src.startsWith('http')) return src;
  const name = src.split(':').pop();
  return `${cv.host}/bricks/f/${name}?frame=${b.id}`;
}

function cvComponent(b) {
  const box = document.createElement('div'); box.className = 'cv-frame';
  const f = document.createElement('iframe');
  f.src = cvFrameSrc(b); f.dataset.id = b.id; f.style.height = ((b.props || {}).height || 260) + 'px';
  f.setAttribute('scrolling', 'no');
  box.appendChild(f);
  box.appendChild(cvPortStrip(b));
  return box;
}

function cvSim(b) {
  const box = document.createElement('div'); box.className = 'cv-frame cv-sketch';
  const f = document.createElement('iframe');
  f.dataset.id = b.id; f.style.height = ((b.props || {}).height || 260) + 'px';
  f.srcdoc = cvSketchDoc(b);
  box.appendChild(f); box.appendChild(cvPortStrip(b));
  return box;
}

//: A sketch is a component written in the document itself. It gets the same two messages a packaged
//: brick gets, and nothing else: no parent DOM, no fetch to this origin.
function cvSketchDoc(b) {
  return `<!doctype html><meta charset="utf-8"><style>
  body{margin:0;font:14px/1.5 ui-sans-serif,system-ui,sans-serif;color:#1a1c22}
  input[type=range]{width:100%} .row{display:flex;gap:10px;align-items:center;margin:6px 0}
  </style><body><div id="root"></div><script>
  let props = ${JSON.stringify(cv.ports[b.id] ? Object.fromEntries(Object.entries(cv.ports[b.id]).map(([k, v]) => [k, v.value])) : {})};
  const emit = (port, value) => parent.postMessage({type:'brick:emit', port, value, id:${JSON.stringify(b.id)}}, '*');
  const root = document.getElementById('root');
  addEventListener('message', e => { if (e.data?.type === 'brick:props') { props = {...props, ...e.data.props}; draw(); } });
  const post = () => parent.postMessage({type:'brick:height', px: document.body.scrollHeight, id:${JSON.stringify(b.id)}}, '*');
  ${b.body}
  if (typeof draw === 'function') draw();
  new ResizeObserver(post).observe(document.body); post();
  <\/script>`;
}

function cvPortStrip(b) {
  const strip = document.createElement('div'); strip.className = 'cv-ports';
  const binds = b.binds || {};
  const keys = Object.keys(binds);
  strip.innerHTML = keys.length
    ? keys.map(k => `<button class="cv-port" data-port="${k}" data-id="${b.id}" title="${cvEsc(binds[k])}"><b>${k}</b><code>${cvEsc(cvClip(binds[k]))}</code></button>`).join('')
    : b.kind === 'sim'
      ? `<button class="cv-port empty" data-id="${b.id}">a sketch: it writes to the namespace when you move it</button>`
      : `<button class="cv-port empty" data-id="${b.id}">not wired: click to connect it to a data source</button>`;
  strip.onclick = ev => { const p = ev.target.closest('.cv-port'); if (p) cvWire(b.id, p.dataset.port); };
  return strip;
}

const cvClip = (s, n = 48) => String(s).length > n ? String(s).slice(0, n - 1) + '…' : String(s);

function cvApplyPorts(ports) {
  for (const [id, resolved] of Object.entries(ports || {})) {
    const live = $$('#live-' + id);
    if (live) {
      const b = cvBrick(id);
      const strip = live.querySelector('.cv-ports');
      live.innerHTML = cvMd(cvLiveText(b));
      if (strip) live.appendChild(strip);
    }
    const f = $$(`iframe[data-id="${id}"]`); if (!f?.contentWindow) continue;
    const props = {}, bad = [];
    for (const [port, r] of Object.entries(resolved)) r.ok ? (props[port] = r.value) : bad.push(`${port}: ${r.error}`);
    f.contentWindow.postMessage({type: 'brick:props', props, id}, '*');
    const el = brickEl(id);
    el?.classList.toggle('portbad', bad.length > 0);
    const strip = el && $$('.cv-ports', el);
    if (strip && bad.length) strip.dataset.error = bad.join(' · '); else if (strip) delete strip.dataset.error;
  }
}

window.addEventListener('message', async ev => {
  const d = ev.data || {}; if (!d.type?.startsWith('brick:')) return;
  const f = [...document.querySelectorAll('#cv-doc iframe')].find(x => x.contentWindow === ev.source);
  const id = d.id || f?.dataset.id; if (!id) return;
  if (d.type === 'brick:height' && f) f.style.height = Math.max(80, d.px) + 'px';
  //: A frame that has only just loaded missed the props sent when the document was drawn.
  if (d.type === 'brick:ready' && cv.ports[id]) cvApplyPorts({[id]: cv.ports[id]});
  if (d.type === 'brick:emit') {
    const b = cvBrick(id); if (!b) return;
    const name = (b.attrs || {})['emit_' + d.port] || (b.attrs || {}).emit || d.port;
    const r = await api('/canvas/emit', {path: cv.path, name, value: d.value});
    if (r.ok) { cvSettle(r); cvStatus(`${name} ← ${JSON.stringify(d.value).slice(0, 40)}`, 'ok'); cvNames(); }
  }
});

/* === ask bricks === */

function cvAsk(b) {
  const box = document.createElement('div'); box.className = 'cv-askbox';
  const ta = document.createElement('textarea');
  ta.className = 'cv-question'; ta.value = b.body; ta.rows = 1; ta.placeholder = 'ask the document…';
  const grow = () => { ta.style.height = 'auto'; ta.style.height = (ta.scrollHeight + 2) + 'px'; };
  ta.oninput = () => { b.body = ta.value; grow(); };
  ta.onkeydown = ev => { if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); cvAskRun(b.id); } };
  ta.onfocus = () => { cv.focus = b.id; };
  box.appendChild(ta);
  const steps = document.createElement('div'); steps.className = 'cv-steps'; steps.id = 'steps-' + b.id;
  box.appendChild(steps);
  setTimeout(grow, 0);
  return box;
}

async function cvAskRun(id, selection = '') {
  const b = cvBrick(id);
  const question = b ? b.body : selection;
  await cvTurn({id, question, selection, into: $$('#steps-' + id)});
}

/* === generic ops === */

async function cvOp(op, redraw = true) {
  const r = await api('/canvas/op', {path: cv.path, op});
  if (!r.ok) return r;
  cv.ports = r.ports || cv.ports;
  redraw ? cvSync(r.canvas) : (cv.canvas = r.canvas);       // `cvSync` needs the old document to diff against
  cv.dirty = true;
  return r;
}

async function cvSave() {
  for (const b of cv.canvas.bricks) if (b.kind === 'code' || b.kind === 'ask') await cvOp({op: 'replace', id: b.id, body: b.body}, false);
  const r = await api('/canvas/save', {path: cv.path});
  if (r.ok) { cv.dirty = false; cvStatus(`saved · ${r.bytes} bytes`, 'ok'); }
}

async function cvNames() {
  const r = await api(`/canvas/open?path=${encodeURIComponent(cv.path)}`);
  if (r.ok) cv.names = r.names || [];
}
