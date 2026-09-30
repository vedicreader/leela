/* The canvas: one document made of bricks, drawn once and repainted a brick at a time.
 * `cv` is the whole client state, the way `lee` is in the IDE. */
const cv = {path: '', canvas: null, ports: {}, host: '', names: [], palette: null, focus: null,
            dirty: false, edited: new Set(), picked: null, theme: 'light'};
const $$ = (sel, root = document) => root.querySelector(sel);
const $all = (sel, root = document) => [...root.querySelectorAll(sel)];
const brickEl = id => $$(`.cv-brick[data-id="${id}"]`);
const cvBrick = id => (cv.canvas?.bricks || []).find(b => b.id === id);

//: The document is the record, never an element's closure. A `cvSync` keeps the element and hands
//: back a new brick object, so a write to the captured one is gone at the next flush.
function cvEdit(id, body) {
  const b = cvBrick(id);
  if (b) b.body = body;
  cv.edited.add(id); cv.dirty = true;
}

//: The server's copy is older than what someone is typing, so an edited body crosses the sync.
function cvKeepEdits(canvas) {
  for (const id of cv.edited) {
    const was = cvBrick(id), fresh = (canvas.bricks || []).find(b => b.id === id);
    if (was && fresh) fresh.body = was.body;
  }
  return canvas;
}

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
  cv.trusted = !!r.trusted; cv.rev = r.rev || 0;
  document.title = r.canvas.title;
  $$('#cv-mode').textContent = r.canvas.meta.mode || 'make';
  cvPick(null);
  cvRender();
  cvTrustBar();
  cvStatus(`${r.canvas.bricks.length} bricks · ${cv.trusted ? cv.names.length + ' live names' : 'not run'}`, 'ok');
}

//: A canvas is markdown, so it arrives from a clone, a download or a paste. Opening one draws it
//: and runs none of it; this is the one control that says its code may run.
function cvTrustBar() {
  const bar = $$('#cv-trust'); if (!bar) return;
  bar.hidden = cv.trusted;
  if (!cv.trusted) $$('#cv-trust-count').textContent =
    cv.canvas.bricks.filter(b => b.kind === 'code' || b.kind === 'data').length;
}

async function cvTrust() {
  const r = await api('/canvas/trust', {path: cv.path});
  if (!r.ok) return cvStatus(r.error || 'not trusted', 'bad');
  cv.trusted = true; cv.ports = {...cv.ports, ...(r.ports || {})};
  for (const [id, run] of Object.entries(r.runs || {})) cvOutputs(id, run);
  cvApplyPorts(cv.ports); cvTrustBar(); cvNames();
  cvStatus(`${Object.keys(r.runs || {}).length} cells run`, 'ok');
}

function cvRender() {
  const doc = $$('#cv-doc'); doc.innerHTML = '';
  cv.canvas.bricks.forEach((b, i) => doc.appendChild(cvPaint(b, i)));
  cvApplyPorts(cv.ports);
}

//: Redrawing the whole document would rebuild every iframe, and a frame that reloads forgets what
//: the person had selected in it. Only what actually changed is repainted, and what was painted is
//: read off the element rather than off the model: the model is mutated in place all over.
function cvSync(canvas) {
  const now = cvKeepEdits(canvas).bricks;
  cv.canvas = canvas;
  for (const el of $all('#cv-doc .cv-brick')) if (!now.some(b => b.id === el.dataset.id)) el.remove();
  now.forEach((b, i) => {
    const el = brickEl(b.id);
    if (!el) return void cvRepaint(b, i);
    if (cv.edited.has(b.id)) return;                      // being typed in: the server's copy is the older one
    const was = el.dataset.sig, sig = cvSig(b);
    if (was === sig) return;
    //: A binding that moved is new props and a new strip, not a reload of the frame.
    if (cvFrameKind(b) && cvSig(b, true) === cvSig({...b, binds: JSON.parse(was).binds}, true)) {
      el.dataset.sig = sig;
      $$('.cv-ports', el)?.replaceWith(cvPortStrip(b));
      return;
    }
    cvRepaint(b, i);
  });
  cvOrder(now);
}

const cvFrameKind = b => b.kind === 'brick' || b.kind === 'sim';
const cvSig = (b, noBinds) => JSON.stringify({kind: b.kind, body: b.body, attrs: b.attrs || {},
                                              props: b.props || {}, binds: noBinds ? 0 : (b.binds || {})});

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

function cvPaint(b, i) {
  const wrap = document.createElement('section');
  wrap.className = `cv-brick cv-${b.kind}`; wrap.dataset.id = b.id; wrap.dataset.i = i;
  wrap.dataset.kind = b.kind; wrap.dataset.sig = cvSig(b);
  wrap.appendChild(cvGutter(b));
  wrap.appendChild(({text: cvText, code: cvCode, ask: cvAsk, brick: cvComponent, sim: cvSim,
                     pdf: cvPdf, video: cvVideo, reply: cvProse, note: cvProse, quiz: cvQuiz,
                     data: cvData, snippet: cvSnippet}[b.kind] || cvProse)(b));
  wrap.onpointerdown = ev => { if (!ev.target.closest('.cv-gutter')) cvPick(null); };
  return wrap;
}

/* Prose a person edits in place. It stays rendered while you work in it, and goes back to markdown
 * on the way out: selecting a sentence to ask about it must not change what the sentence looks like. */
function cvText(b) {
  const el = document.createElement('div');
  el.className = 'cv-prose'; el.contentEditable = 'true'; el.spellcheck = false;
  el.dataset.id = b.id;
  el.dataset.placeholder = "Write, or press '/' for blocks";
  el.innerHTML = cvMd(b.body) || '';
  const blank = () => el.classList.toggle('blank', !el.textContent.trim());
  el.oninput = () => { blank(); cv.edited.add(b.id); cv.dirty = true; };
  el.onfocus = () => { cv.focus = b.id; blank(); };
  blank();
  //: Blur records; `cvFlush` writes. Blur used to post on its own, so a blur triggered by
  //: clicking Save raced the save itself and the file was written from whichever landed first.
  //: It also converted the rendered DOM back to markdown every time, which loses what `cvMd`
  //: cannot draw: a table came back as its text. Untouched prose is never converted now.
  el.onblur = () => {
    if (!cv.edited.has(b.id)) return;
    const body = el.classList.contains('raw') ? el.innerText.trimEnd() : cvHtmlToMd(el);
    if (body !== (cvBrick(b.id)?.body ?? b.body)) cvEdit(b.id, body);
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
    if (n.tagName === 'IMG') return `![${n.getAttribute('alt') || ''}](${n.getAttribute('src') || ''})`;
    return {CODE: `\`${kids}\``, STRONG: `**${kids}**`, B: `**${kids}**`, EM: `*${kids}*`, I: `*${kids}*`,
            A: `[${kids}](${n.getAttribute('href') || ''})`, BR: '  \n'}[n.tagName] ?? kids;
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
    else if (t === 'PRE') {
      const lang = (n.querySelector('code')?.className || '').replace('language-', '');
      out.push('```' + lang + '\n' + (n.textContent || '').replace(/\n$/, '') + '\n```');
    }
    else if (body) out.push(body);
  }
  return out.join('\n\n');
}

function cvTextKeys(ev, b, el) {
  if (cvMenuKey(ev)) return;
  const mod = ev.metaKey || ev.ctrlKey;
  if (ev.key === '/' && !el.textContent.trim()) { setTimeout(() => cvSlash(b.id, el), 0); return; }
  if (mod && 'bie'.includes(ev.key)) { ev.preventDefault(); return cvMark(ev.key); }
  if (mod && ev.key === 'Enter') { ev.preventDefault(); el.blur(); return; }
  //: Enter splits the block at the caret, the way every editor of this shape does. Shift+Enter is
  //: the line break inside one.
  if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); return cvSplit(b, el); }
  if (ev.key === 'Backspace' && !el.textContent.trim() && cv.canvas.bricks.length > 1) {
    ev.preventDefault(); cvFocusNear(b.id, -1); cvOp({op: 'remove', id: b.id});
    return;
  }
  if (ev.key === 'Escape') { el.blur(); cvPick(b.id); }
}

//: Split at the caret by cutting the rendered HTML in two and reading each half back as markdown.
//: The caret is a position in what is on the screen; the file wants two bodies.
async function cvSplit(b, el) {
  const sel = getSelection();
  if (!sel.rangeCount) return;
  const at = sel.getRangeAt(0);
  const cut = side => {
    const r = document.createRange();
    r.selectNodeContents(el);
    side === 'before' ? r.setEnd(at.startContainer, at.startOffset) : r.setStart(at.endContainer, at.endOffset);
    const box = document.createElement('div');
    box.appendChild(r.cloneContents());
    return cvHtmlToMd(box);
  };
  const head = cut('before'), tail = cut('after');
  el.blur();
  b.body = head;
  cv.edited.delete(b.id);
  await cvOp({op: 'replace', id: b.id, body: head}, false);
  cvLandOn(await cvOp({op: 'insert', after: b.id, kind: 'text', body: tail}));
}

function cvAtEnd(el) {
  const s = getSelection();
  if (!s.rangeCount || !s.isCollapsed) return false;
  const r = s.getRangeAt(0).cloneRange();
  r.selectNodeContents(el); r.setStart(s.getRangeAt(0).endContainer, s.getRangeAt(0).endOffset);
  return !r.toString().trim();
}

function cvFocusNear(id, by) {
  const at = cv.canvas.bricks.findIndex(b => b.id === id);
  const next = cv.canvas.bricks[at + by] || cv.canvas.bricks[at + (by > 0 ? -1 : 1)];
  if (!next) return;
  const el = $$(`.cv-prose[data-id="${next.id}"]`);
  if (el) { el.focus(); cvCaretEnd(el); } else cvPick(next.id);
}

//: A picked block is the keyboard's block when nothing is being typed into.
function cvPick(id) {
  $all('#cv-doc .picked').forEach(e => e.classList.remove('picked'));
  cv.picked = id || null;
  if (id) brickEl(id)?.classList.add('picked');
}

function cvProse(b) {
  const el = document.createElement('div');
  el.className = 'cv-prose cv-said';
  el.innerHTML = cvMd(b.body);
  return el;
}

//: Code a snippet cites. The document keeps no copy, so the source is read from its file each time it draws.
function cvSnippet(b) {
  const box = document.createElement('div'); box.className = 'cv-snipbox';
  const where = [b.attrs?.path, b.attrs?.symbol].filter(Boolean).join(' · ');
  box.innerHTML = ((b.body || '').trim() ? `<div class="cv-prose cv-said">${cvMd(b.body)}</div>` : '') +
    `<div class="cv-snip-where">${cvEsc(where)}</div><pre class="cv-snip"><code></code></pre>`;
  api(`/canvas/snip?path=${encodeURIComponent(cv.path)}&id=${encodeURIComponent(b.id)}`).then(r => {
    box.querySelector('code').textContent = r.ok ? (r.code || `${where} is not in that file any more`) : r.error;
  });
  return box;
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
  ta.oninput = () => { cvEdit(b.id, ta.value); grow(); };
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
  await cvFlush();
  const sources = Object.fromEntries(cv.canvas.bricks.filter(b => b.kind === 'code').map(b => [b.id, b.body]));
  const r = await api('/canvas/runall', {path: cv.path, sources});
  if (!r.ok) return;
  for (const [id, run] of Object.entries(r.runs)) cvOutputs(id, run);
  cv.ports = {...cv.ports, ...r.ports}; cvApplyPorts(r.ports);
  cvStatus(`${Object.keys(r.runs).length} cells run in dependency order`, 'ok');
}

/* === embedded components === */

function cvFrameSrc(b) {
  const src = (b.attrs || {}).src || '';
  if (src.startsWith('http')) return src;
  const name = src.split(':').pop();
  return `${cv.host}/bricks/f/${name}?frame=${b.id}&theme=${cv.theme}`;
}

/* A frame runs code the document did not write, so it is sandboxed. `allow-scripts` and nothing
 * else: no `allow-same-origin`, so the frame gets an opaque origin and cannot read this page's
 * DOM, cookies or storage, and cannot call this origin's routes with the session's credentials.
 * The two `postMessage` calls it needs work under that, because messages cross origins by design. */
const CV_SANDBOX = 'allow-scripts';

function cvFrame(b) {
  const f = document.createElement('iframe');
  f.setAttribute('sandbox', CV_SANDBOX);
  f.setAttribute('referrerpolicy', 'no-referrer');
  f.dataset.id = b.id;
  f.style.height = ((b.props || {}).height || 260) + 'px';
  return f;
}

function cvComponent(b) {
  const box = document.createElement('div'); box.className = 'cv-frame';
  const f = cvFrame(b);
  f.src = cvFrameSrc(b);
  f.setAttribute('scrolling', 'no');
  box.appendChild(f);
  box.appendChild(cvPortStrip(b));
  return box;
}

function cvSim(b) {
  const box = document.createElement('div'); box.className = 'cv-frame cv-sketch';
  const f = cvFrame(b);
  f.srcdoc = cvSketchDoc(b);
  box.appendChild(f); box.appendChild(cvPortStrip(b));
  return box;
}

//: A sketch is a component written in the document itself. It gets the same two messages a packaged
//: brick gets, and nothing else: no parent DOM, no fetch to this origin.
function cvSketchDoc(b) {
  return `<!doctype html><meta charset="utf-8"><style>
  body{margin:0;font:14px/1.5 ui-sans-serif,system-ui,sans-serif;color:${cv.theme === 'dark' ? '#e8eaf0' : '#1c1d21'};
       background:${cv.theme === 'dark' ? '#191b21' : '#fff'}}
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
  //: The window that sent it, never the id it claims. A sandboxed frame has an opaque origin, so
  //: `ev.origin` is "null" for all of them and identity is the frame element or nothing.
  const f = [...document.querySelectorAll('#cv-doc iframe')].find(x => x.contentWindow === ev.source);
  const id = f?.dataset.id; if (!id) return;
  if (d.type === 'brick:height' && f) f.style.height = Math.max(80, d.px) + 'px';
  //: A frame that has only just loaded missed the props sent when the document was drawn.
  if (d.type === 'brick:ready' && cv.ports[id]) cvApplyPorts({[id]: cv.ports[id]});
  if (d.type === 'brick:emit') {
    const b = cvBrick(id); if (!b) return;
    const name = (b.attrs || {})['emit_' + d.port] || (b.attrs || {}).emit || d.port;
    const r = await api('/canvas/emit', {path: cv.path, name, value: d.value, from: id});
    if (r.ok) { cvSettle(r); cvStatus(`${name} ← ${JSON.stringify(d.value).slice(0, 40)}`, 'ok'); cvNames(); }
  }
});

/* === ask bricks === */

function cvAsk(b) {
  const box = document.createElement('div'); box.className = 'cv-askbox';
  const ta = document.createElement('textarea');
  ta.className = 'cv-question'; ta.value = b.body; ta.rows = 1; ta.placeholder = 'ask the document…';
  const grow = () => { ta.style.height = 'auto'; ta.style.height = (ta.scrollHeight + 2) + 'px'; };
  ta.oninput = () => { cvEdit(b.id, ta.value); grow(); };
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

//: What is typed lives on the brick object until something sends it. Every path that takes the
//: document back from the server flushes first, or the reply overwrites the typing.
//: Every write goes through this chain, so a save cannot overtake a pending edit. Two callers
//: arriving together await the same tail rather than interleaving their requests.
let cvQueue = Promise.resolve();
function cvSerial(fn) {
  const next = cvQueue.then(fn, fn);
  cvQueue = next.catch(() => {});
  return next;
}

async function cvFlush() {
  if (document.activeElement?.blur) document.activeElement.blur();
  const dirty = [...cv.edited];
  cv.edited.clear();
  for (const id of dirty) {
    const b = cvBrick(id);
    if (b) {
      const r = await api('/canvas/op', {path: cv.path, op: {op: 'replace', id, body: b.body}});
      if (r?.rev != null) cv.rev = r.rev;
    }
  }
}

const SHAPE_KEEPING = new Set(['replace', 'bind', 'kind', 'replace_selection']);

function cvOp(op, redraw = true) { return cvSerial(() => cvOpNow(op, redraw)); }

async function cvOpNow(op, redraw = true) {
  if (op.op !== 'replace') await cvFlush();
  const r = await api('/canvas/op', {path: cv.path, op});
  if (!r.ok) return r;
  if (r.rev != null) cv.rev = r.rev;
  cv.ports = r.ports || cv.ports;
  if (redraw) cvSync(r.canvas);
  //: Without a redraw, only the brick that changed is taken. Replacing the whole document would
  //: leave the next `cvSync` diffing the new document against itself, and nothing would repaint.
  else if (r.brick && SHAPE_KEEPING.has(op.op)) Object.assign(cvBrick(r.brick.id) || {}, r.brick);
  else cv.canvas = cvKeepEdits(r.canvas);
  cv.dirty = true;
  return r;
}

function cvSave() { return cvSerial(cvSaveNow); }

async function cvSaveNow() {
  await cvFlush();
  for (const b of cv.canvas.bricks) {
    if (b.kind !== 'code' && b.kind !== 'ask') continue;
    const r = await api('/canvas/op', {path: cv.path, op: {op: 'replace', id: b.id, body: b.body}});
    if (r?.rev != null) cv.rev = r.rev;
  }
  //: `rev` is what the document was when this save was assembled. The server refuses an older one
  //: rather than overwriting somebody else's write.
  const r = await api('/canvas/save', {path: cv.path, rev: cv.rev});
  if (r.ok) { cv.dirty = false; cvStatus(`saved · ${r.bytes} bytes`, 'ok'); }
  else cvStatus(r.error || 'not saved', 'bad');
  return r;
}

async function cvNames() {
  const r = await api(`/canvas/open?path=${encodeURIComponent(cv.path)}`);
  if (r.ok) cv.names = r.names || [];
}
