/* Enough markdown for a document: headings, emphasis, code, lists, quotes, links, rules, tables.
 * Leela's own tabs render through mdhtml; a canvas frame is one page and carries this instead. */
const cvEsc = s => String(s ?? '').replace(/[&<>"']/g,
  c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

/* A URL a document may point at. `javascript:` in an href is script, and a data: SVG carries
 * script too. Only http, https, mailto, a relative path and an anchor get through. Quotes are
 * already entities by the time this runs, and a URL holding one is refused rather than repaired. */
const cvUrl = u => {
  const raw = String(u ?? '').trim();
  if (!raw || /[\s"'<>`]/.test(raw)) return '';
  const bare = raw.replace(/[\u0000-\u001f]/g, '');
  if (/^data:image\/(png|jpe?g|gif|webp);base64,[A-Za-z0-9+/=]+$/i.test(bare)) return bare;
  const scheme = bare.match(/^([a-z][a-z0-9+.-]*):/i);
  if (scheme) return /^(https?|mailto)$/i.test(scheme[1]) ? bare : '';
  return bare;                                      // relative, absolute-path or anchor
};

function cvInline(s) {
  return cvEsc(s)
    .replace(/`([^`]+)`/g, (_, c) => `<code>${c}</code>`)
    .replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (m, a, u) => {
      const src = cvUrl(u); return src ? `<img alt="${a}" src="${src}">` : cvEsc(m);
    })
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, txt, u) => {
      const href = cvUrl(u);
      return href ? `<a href="${href}" target="_blank" rel="noreferrer noopener">${txt}</a>` : cvEsc(m);
    })
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[\s(])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/(^|[\s(])_([^_\n]+)_/g, '$1<em>$2</em>')
    .replace(/ {2}\u0001/g, '<br>').replace(/\u0001/g, ' ');
}

function cvMd(src) {
  const lines = String(src ?? '').split('\n'), out = [];
  let list = null, para = [], quote = [], fence = null, code = [], lang = '';
  //: Two trailing spaces are markdown's hard break, and the only way a line break survives here.
  const flushPara = () => { if (para.length) { out.push(`<p>${cvInline(para.join('\u0001'))}</p>`); para = []; } };
  const flushList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  const flushQuote = () => { if (quote.length) { out.push(`<blockquote>${cvInline(quote.join(' '))}</blockquote>`); quote = []; } };
  const flush = () => { flushPara(); flushList(); flushQuote(); };
  for (const raw of lines) {
    const l = raw.replace(/\s+$/, '');
    let m;
    if (fence) {                                           // inside a fence: kept verbatim to the closing ticks
      if ((m = l.match(/^(`{3,})\s*$/)) && m[1].length >= fence.length) {
        out.push(cvPre(lang, code)); fence = null; code = []; lang = '';
      } else code.push(raw);
      continue;
    }
    if ((m = l.match(/^(`{3,})(.*)$/))) { flush(); fence = m[1]; lang = m[2].trim(); code = []; continue; }
    if (!l.trim()) { flush(); continue; }
    if ((m = l.match(/^(#{1,6})\s+(.*)$/))) { flush(); out.push(`<h${m[1].length}>${cvInline(m[2])}</h${m[1].length}>`); continue; }
    if (/^(-{3,}|\*{3,})$/.test(l.trim())) { flush(); out.push('<hr>'); continue; }
    if ((m = l.match(/^>\s?(.*)$/))) { flushPara(); flushList(); quote.push(m[1]); continue; }
    if ((m = l.match(/^\s*[-*+]\s+(.*)$/))) {
      flushPara(); flushQuote();
      if (list !== 'ul') { flushList(); out.push('<ul>'); list = 'ul'; }
      out.push(`<li>${cvInline(m[1])}</li>`); continue;
    }
    if ((m = l.match(/^\s*\d+[.)]\s+(.*)$/))) {
      flushPara(); flushQuote();
      if (list !== 'ol') { flushList(); out.push('<ol>'); list = 'ol'; }
      out.push(`<li>${cvInline(m[1])}</li>`); continue;
    }
    if (l.includes('|') && l.trim().startsWith('|')) { flushPara(); out.push(cvRow(l)); continue; }
    flushList(); flushQuote(); para.push(raw.replace(/\s+$/, m => m.length >= 2 ? '  ' : ''));
  }
  if (fence) out.push(cvPre(lang, code));
  flush();
  return out.join('\n').replace(/(<tr>[\s\S]*<\/tr>)/, '<table>$1</table>');
}

//: The info string rides on the class, so `cvHtmlToMd` can put it back on the fence.
const cvPre = (lang, code) =>
  `<pre><code${lang ? ` class="language-${cvEsc(lang)}"` : ''}>${cvEsc(code.join('\n'))}</code></pre>`;

function cvRow(l) {
  const cells = l.trim().replace(/^\||\|$/g, '').split('|');
  if (cells.every(c => /^\s*:?-+:?\s*$/.test(c))) return '';
  return '<tr>' + cells.map(c => `<td>${cvInline(c.trim())}</td>`).join('') + '</tr>';
}
/* One popover, used by the slash menu, the palette and the block menu. Items are grouped, filtered
 * as you type, and driven by the keyboard. Groups sort by `N_Name`, which is BlockSuite's trick for
 * keeping the order of a menu out of the order of the code that builds it. */
const cvPop = {el: null, items: [], shown: [], at: 0, pick: null, query: '', onQuery: null};

const cvFuzzy = (hay, q) => {          // every character of the query, in order
  hay = hay.toLowerCase(); let i = 0;
  for (const c of q) { i = hay.indexOf(c, i); if (i < 0) return false; i++; }
  return true;
};
const cvScore = (name, q) => {
  const n = name.toLowerCase();
  return n === q ? 100 : n.startsWith(q) ? 60 : n.includes(q) ? 30 : cvFuzzy(n, q) ? 10 : 0;
};
const cvGroupOf = it => (it.group || '9_More').split('_')[1] || 'More';

function cvOpenMenu(items, x, y, pick, {query = false, width = 300, empty = 'nothing here'} = {}) {
  cvCloseMenu();
  const el = document.createElement('div');
  el.className = 'cv-pop'; el.style.width = width + 'px'; el.setAttribute('role', 'listbox');
  document.body.appendChild(el);
  Object.assign(cvPop, {el, items, pick, query: '', at: 0, empty});
  cvPaintMenu();
  const box = el.getBoundingClientRect();
  el.style.left = Math.max(8, Math.min(x, innerWidth - box.width - 8)) + 'px';
  el.style.top = (y + box.height > innerHeight - 8 ? Math.max(8, y - box.height - 26) : y) + 'px';
  el.onmousedown = ev => ev.preventDefault();
  el.onclick = ev => {
    const b = ev.target.closest('.cv-item'); if (!b) return;
    cvChoose(cvPop.shown[+b.dataset.i]);
  };
  setTimeout(() => document.addEventListener('pointerdown', cvOutside, true), 0);
  return el;
}

function cvPaintMenu() {
  const {el, items, query} = cvPop;
  const q = query.toLowerCase();
  let shown = q ? items.filter(it => cvScore(it.name, q) || (it.alias || []).some(a => cvScore(a, q))) : items.slice();
  if (q) shown.sort((a, b) => cvScore(b.name, q) - cvScore(a.name, q));
  cvPop.shown = shown;
  cvPop.at = Math.min(cvPop.at, Math.max(0, shown.length - 1));
  if (!shown.length) { el.innerHTML = `<div class="none">${cvEsc(cvPop.empty)}</div>`; return; }
  let html = '', group = null;
  shown.forEach((it, i) => {
    const g = q ? null : cvGroupOf(it);
    if (g && g !== group) { html += `<div class="grp">${cvEsc(g)}</div>`; group = g; }
    html += `<button class="cv-item" role="option" data-i="${i}" aria-selected="${i === cvPop.at}">` +
      `<span class="cv-ico">${it.icon || '·'}</span><span class="txt">` +
      `<span class="nm">${cvEsc(it.name)}</span>` +
      (it.hint ? `<span class="hint">${cvEsc(it.hint)}</span>` : '') + '</span></button>';
  });
  el.innerHTML = html;
  el.querySelector('[aria-selected=true]')?.scrollIntoView({block: 'nearest'});
}

//: A pointer inside the menu is a choice, not a dismissal. Closing on every pointerdown would take
//: the item out from under the click that was picking it.
function cvOutside(ev) { if (!cvPop.el?.contains(ev.target)) cvCloseMenu(); }

function cvChoose(it) { const {pick} = cvPop; cvCloseMenu(); if (it && pick) pick(it); }
function cvMenuOpen() { return !!cvPop.el }
function cvCloseMenu() {
  document.removeEventListener('pointerdown', cvOutside, true);
  cvPop.el?.remove();
  cvPop.el = null; cvPop.onQuery?.(null); cvPop.onQuery = null;
}

//: The menu owns the keys while it is up, including the ones that edit its query, so the block
//: underneath never sees them.
function cvMenuKey(ev) {
  if (!cvPop.el || ev.cvSeen) return false;
  ev.cvSeen = true;                        // the block's handler and the document's both call this
  const k = ev.key;
  if (k === 'Escape') { ev.preventDefault(); cvCloseMenu(); return true; }
  if (k === 'ArrowDown' || k === 'ArrowUp') {
    ev.preventDefault();
    const n = cvPop.shown.length; if (!n) return true;
    cvPop.at = (cvPop.at + (k === 'ArrowDown' ? 1 : n - 1)) % n;
    cvPaintMenu(); return true;
  }
  if (k === 'Enter' || k === 'Tab') { ev.preventDefault(); cvChoose(cvPop.shown[cvPop.at]); return true; }
  if (k === 'Backspace') {
    if (!cvPop.query) { cvCloseMenu(); return false; }
    ev.preventDefault(); cvPop.query = cvPop.query.slice(0, -1); cvPop.at = 0; cvPaintMenu();
    cvPop.onQuery?.(cvPop.query); return true;
  }
  if (k.length === 1 && !ev.metaKey && !ev.ctrlKey) {
    if (k === ' ' && !cvPop.query) { cvCloseMenu(); return false; }
    ev.preventDefault(); cvPop.query += k; cvPop.at = 0; cvPaintMenu();
    cvPop.onQuery?.(cvPop.query);
    if (!cvPop.shown.length && cvPop.query.length > 12) cvCloseMenu();
    return true;
  }
  return false;
}
/* The canvas: one document made of bricks, drawn once and repainted a brick at a time.
 * `cv` is the whole client state, the way `lee` is in the IDE. */
const cv = {path: '', canvas: null, ports: {}, host: '', names: [], files: [], palette: null, focus: null,
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
  cvTrail(r.trail || []);
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
                     data: cvData}[b.kind] || cvProse)(b));
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
/* The left gutter: what a block offers when the pointer is on it. `+` inserts under it, the grip
 * drags it somewhere else, and clicking the grip opens what else can be done to it. Nothing is
 * drawn until the pointer arrives, so the document reads as a document. */

const KIND_LABEL = {code: 'code', ask: 'ask', brick: 'component', sim: 'sketch', pdf: 'pdf',
                    video: 'video', reply: 'answer', note: 'note', quiz: 'check', data: 'live', text: ''};

function cvGutter(b) {
  const g = document.createElement('div');
  g.className = 'cv-gutter';
  g.innerHTML = `<button class="cv-gadd" title="insert below" aria-label="insert below">+</button>` +
    `<button class="cv-ghandle" title="drag to move, click for actions" aria-label="block actions">` +
    `<span class="cv-grip"><i></i><i></i><i></i><i></i><i></i><i></i></span></button>`;
  const add = g.querySelector('.cv-gadd'), grip = g.querySelector('.cv-ghandle');
  add.onclick = ev => { ev.stopPropagation(); cvInsertUnder(b.id, add); };
  grip.onclick = ev => { ev.stopPropagation(); if (!cvDrag.moved) cvBlockMenu(b, grip); };
  grip.onpointerdown = ev => cvDragStart(ev, b, g);
  return g;
}

/* --- inserting --- */

async function cvInsertUnder(id, anchor) {
  const r = anchor.getBoundingClientRect();
  const fresh = await cvOp({op: 'insert', after: id, kind: 'text', body: ''});
  if (!fresh.ok) return;
  const el = $$(`.cv-prose[data-id="${fresh.brick.id}"]`);
  el?.focus();
  cvSlashAt(fresh.brick.id, r.left + 26, r.bottom + 4);
}

/* --- the block menu --- */

const BLOCK_ACTIONS = [
  {name: 'Run', icon: '▶', hint: 'run this cell', group: '1_This', when: b => b.kind === 'code',
   act: b => cvRun(b.id)},
  {name: 'Ask about this', icon: '✦', hint: 'the helper, anchored here', group: '1_This',
   act: b => cvTurn({id: b.id, question: prompt('ask about this block') || '', selection: ''})},
  {name: 'Ports and wiring', icon: '⌗', hint: 'what it draws from', group: '1_This',
   when: b => b.kind === 'brick' || b.kind === 'sim', act: b => cvWire(b.id)},
  {name: 'Show markdown', icon: '‹›', hint: 'the source of this paragraph', group: '1_This',
   when: b => b.kind === 'text', act: b => cvRawToggle(b)},
  {name: 'Duplicate', icon: '⧉', hint: 'a copy under it', group: '2_Move',
   act: b => cvOp({op: 'insert', after: b.id, kind: b.kind, body: b.body, attrs: b.attrs, binds: b.binds, props: b.props})},
  {name: 'Move up', icon: '↑', group: '2_Move', act: b => cvMove(b.id, -1)},
  {name: 'Move down', icon: '↓', group: '2_Move', act: b => cvMove(b.id, 1)},
  {name: 'Copy id', icon: '#', hint: 'to name it to the helper', group: '3_More',
   act: b => { navigator.clipboard?.writeText(b.id); cvStatus(`${b.id} copied`, 'ok'); }},
  {name: 'Delete', icon: '✕', hint: 'take it out', group: '3_More', act: b => cvOp({op: 'remove', id: b.id})}];

function cvBlockMenu(b, anchor) {
  const items = BLOCK_ACTIONS.filter(a => !a.when || a.when(b));
  cvPick(b.id);
  const r = anchor.getBoundingClientRect();
  const g = $$(`.cv-brick[data-id="${b.id}"] .cv-gutter`);
  g?.classList.add('stay');
  cvOpenMenu(items, r.right + 6, r.top, it => { g?.classList.remove('stay'); it.act(cvBrick(b.id) || b); },
             {width: 260, empty: 'nothing for this block'});
}

async function cvMove(id, by) {
  const at = cv.canvas.bricks.findIndex(x => x.id === id);
  const to = Math.max(0, Math.min(cv.canvas.bricks.length - 1, at + by));
  if (to === at) return;
  await cvOp({op: 'move', id, to});
  brickEl(id)?.scrollIntoView({block: 'nearest', behavior: 'smooth'});
}

/* --- dragging --- */

const cvDrag = {id: null, moved: false, over: null, after: false};

function cvDragStart(ev, b, gutter) {
  if (ev.button !== 0) return;
  cvDrag.id = b.id; cvDrag.moved = false;
  const el = brickEl(b.id);
  const move = e => {
    if (!cvDrag.moved && Math.abs(e.clientY - ev.clientY) < 4 && Math.abs(e.clientX - ev.clientX) < 4) return;
    if (!cvDrag.moved) { cvDrag.moved = true; el?.classList.add('dragging'); gutter.classList.add('stay'); }
    cvDragOver(e.clientY);
  };
  const up = async () => {
    document.removeEventListener('pointermove', move);
    document.removeEventListener('pointerup', up);
    el?.classList.remove('dragging'); gutter.classList.remove('stay');
    cvClearDrop();
    if (cvDrag.moved && cvDrag.over && cvDrag.over !== b.id) await cvDropOn(b.id, cvDrag.over, cvDrag.after);
    setTimeout(() => { cvDrag.moved = false; }, 0);
    cvDrag.id = cvDrag.over = null;
  };
  document.addEventListener('pointermove', move);
  document.addEventListener('pointerup', up);
}

function cvDragOver(y) {
  cvClearDrop();
  const els = $all('#cv-doc .cv-brick');
  const hit = els.find(e => { const r = e.getBoundingClientRect(); return y >= r.top && y <= r.bottom; })
           || els.filter(e => e.getBoundingClientRect().top < y).pop();
  if (!hit) return;
  const r = hit.getBoundingClientRect();
  cvDrag.over = hit.dataset.id;
  cvDrag.after = y > r.top + r.height / 2;
  hit.classList.add('dropping'); hit.classList.toggle('after', cvDrag.after);
}

function cvClearDrop() { $all('#cv-doc .dropping').forEach(e => e.classList.remove('dropping', 'after')); }

async function cvDropOn(id, overId, after) {
  const order = cv.canvas.bricks.map(b => b.id).filter(x => x !== id);
  const at = order.indexOf(overId) + (after ? 1 : 0);
  await cvOp({op: 'move', id, to: at});
  brickEl(id)?.classList.add('fresh');
  setTimeout(() => brickEl(id)?.classList.remove('fresh'), 1500);
}
/* The bar that follows a text selection: the three marks that matter, a link, and the helper.
 * "Ask AI" is the same turn the margin runs; what it adds is the span you had selected. */

const MARKS = [
  {key: 'b', label: 'B', title: 'bold (mod+b)', wrap: '**', style: 'font-weight:700'},
  {key: 'i', label: 'I', title: 'italic (mod+i)', wrap: '*', style: 'font-style:italic'},
  {key: 'e', label: '‹›', title: 'code (mod+e)', wrap: '`', style: 'font-family:var(--cv-mono)'}];

function cvFormatBar() {
  const sel = getSelection();
  const text = String(sel || '').trim();
  const host = sel?.anchorNode?.parentElement?.closest('.cv-brick.cv-text');
  if (!text || !host || !sel.rangeCount) return cvHideFormat();
  const r = sel.getRangeAt(0).getBoundingClientRect();
  if (!r.width && !r.height) return cvHideFormat();
  let bar = $$('#cv-format');
  if (!bar) {
    bar = document.createElement('div');
    bar.id = 'cv-format'; bar.className = 'cv-format';
    bar.innerHTML = MARKS.map(m => `<button class="cv-fbtn" data-mark="${m.key}" title="${m.title}" ` +
        `style="${m.style}">${m.label}</button>`).join('') +
      `<button class="cv-fbtn" data-mark="link" title="link">🔗</button>` +
      '<span class="cv-fsep"></span>' +
      '<button class="cv-fbtn ai" data-ask="1">✦ Ask AI</button>';
    document.body.appendChild(bar);
    bar.onmousedown = ev => ev.preventDefault();
    bar.onclick = ev => {
      const b = ev.target.closest('.cv-fbtn'); if (!b) return;
      if (b.dataset.ask) { cvHideFormat(); return cvInlineAsk(); }
      cvMark(b.dataset.mark);
    };
  }
  bar.style.left = Math.max(8, Math.min(r.left + r.width / 2 - bar.offsetWidth / 2, innerWidth - 260)) + 'px';
  bar.style.top = (r.top + scrollY - bar.offsetHeight - 8) + 'px';
  bar.hidden = false;
}

function cvHideFormat() { const b = $$('#cv-format'); if (b) b.hidden = true; }

//: Marks are applied to the markdown, not to the rendered HTML: the file is what is true, and
//: `document.execCommand('bold')` would put a `<b>` in that `cvHtmlToMd` has to guess about.
function cvMark(kind) {
  const sel = getSelection();
  const text = String(sel || '');
  const host = sel?.anchorNode?.parentElement?.closest('.cv-brick.cv-text');
  if (!text.trim() || !host) return;
  const b = cvBrick(host.dataset.id); if (!b) return;
  const nth = cvOccurrence($$('.cv-prose', host), sel, text);
  const now = kind === 'link' ? cvLink(text) : cvToggleWrap(text, MARKS.find(m => m.key === kind).wrap);
  if (now === null) return;
  cvHideFormat();
  cvOp({op: 'replace_selection', id: b.id, was: text, nth, text: now});
}

function cvToggleWrap(text, w) {
  return text.startsWith(w) && text.endsWith(w) && text.length > 2 * w.length
    ? text.slice(w.length, -w.length) : w + text + w;
}

function cvLink(text) {
  const href = prompt('link to', 'https://');
  return href ? `[${text}](${href})` : null;
}

document.addEventListener('selectionchange', () => {
  clearTimeout(cvFormatBar.t);
  cvFormatBar.t = setTimeout(cvFormatBar, 90);
});
document.addEventListener('scroll', cvHideFormat, true);
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
/* The helper: one thread in the margin, and the same turn reachable from anywhere in the document.
 * Inline asks and margin asks are the same call. What differs is the selection that travels with it. */

const cvTurnState = {id: null, abort: null};

async function cvTurn({id, question, selection, nth = 0, into}) {
  if (!question?.trim()) return;
  //: Embedded, the turn belongs to the pane: same agent, same tools, and it owns the approvals.
  //: The margin keeps its own thread only on the standalone page, where the stand-in answers.
  if (cv.embed) {
    try {
      if (typeof parent?.canvasAskPane === 'function') {
        const sent = await parent.canvasAskPane({question, brickId: id || '', selection: selection || '',
                                                 path: cv.path});
        if (sent) return cvStatus('asked in the agent pane', 'ok');
      }
    } catch (e) { cvStatus('could not reach the agent pane: ' + e, 'bad'); return; }
  }
  const turn = 'T' + Math.random().toString(36).slice(2, 8);
  cvTurnState.id = turn; cvTurnState.abort = new AbortController();
  const thread = into || $$('#cv-thread');
  const card = document.createElement('div'); card.className = 'cv-turn running';
  card.innerHTML = `<div class="cv-tq">${cvEsc(question)}</div>` +
    (selection ? `<div class="cv-tsel">“${cvEsc(selection.slice(0, 140))}”</div>` : '') +
    '<div class="cv-tsteps"></div><div class="cv-treply"></div>';
  thread.appendChild(card); card.scrollIntoView({block: 'nearest', behavior: 'smooth'});
  cvSteerBar(turn, true);
  const steps = $$('.cv-tsteps', card), reply = $$('.cv-treply', card);
  let raw = '';
  try {
    await cvEvents('/canvas/ask/stream', {path: cv.path, id, question, selection, nth, turn}, (ev, d) => {
      if (ev === 'step') {
        const row = document.createElement('div'); row.className = 'cv-tstep';
        row.innerHTML = `<code>${cvEsc(d.label)}</code><span>${cvEsc(d.detail || '')}</span>`;
        steps.appendChild(row);
      } else if (ev === 'chunk') { raw += d.text; reply.innerHTML = cvMd(raw); }
      else if (ev === 'op') cvTurnOp(d);
      else if (ev === 'error') { card.classList.add('failed'); reply.textContent = d.text; }
      else if (ev === 'done') {
        cv.ports = d.ports || cv.ports;
        cvSync(d.canvas); cvApplyPorts(cv.ports); cvTrail(d.trail || []);
        if (d.reply) reply.innerHTML = cvMd(d.reply);
      }
    }, cvTurnState.abort.signal);
  } catch (e) { card.classList.add('failed'); reply.textContent = String(e); }
  card.classList.remove('running');
  cvSteerBar(turn, false);
  cvTurnState.id = null;
}

function cvTurnOp(r) {
  if (!r.ok) return;
  if (r.removed) return brickEl(r.removed)?.remove();
  if (r.brick) {
    const node = cvRepaint(r.brick, r.at ?? 0);
    node.classList.add('fresh');
    setTimeout(() => node.classList.remove('fresh'), 1600);
    node.scrollIntoView({block: 'center', behavior: 'smooth'});
  }
}

async function cvEvents(url, body, on, signal) {
  const r = await fetch(url, {method: 'POST', headers: {'content-type': 'application/json'},
                              body: JSON.stringify(body), signal});
  const rd = r.body.getReader(), dec = new TextDecoder();
  let buf = '';
  for (;;) {
    const {value, done} = await rd.read(); if (done) break;
    buf += dec.decode(value, {stream: true});
    let i;
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const frame = buf.slice(0, i); buf = buf.slice(i + 2);
      const ev = (frame.match(/^event: (.*)$/m) || [, 'message'])[1];
      const data = (frame.match(/^data: (.*)$/m) || [, '{}'])[1];
      try { on(ev, JSON.parse(data)); } catch (e) { on('error', {text: String(e)}); }
    }
  }
}

/* === steering, while it runs === */

function cvSteerBar(turn, on) {
  const bar = $$('#cv-steer');
  bar.hidden = !on;
  if (!on) return;
  const inp = $$('#cv-steer input');
  inp.value = ''; inp.focus();
  inp.onkeydown = async ev => {
    if (ev.key !== 'Enter' || !inp.value.trim()) return;
    const text = inp.value; inp.value = '';
    await api('/canvas/steer', {path: cv.path, turn, text});
    cvStatus('steering sent', 'ok');
  };
}

/* === the trail === */

function cvTrail(trail) {
  const el = $$('#cv-trail');
  el.innerHTML = trail.length
    ? '<h4>trail</h4>' + trail.slice(-6).map(t =>
        `<div class="cv-trow"><span>${cvEsc(t.question.slice(0, 60))}</span>${t.brick ? `<code>${cvEsc(t.brick)}</code>` : ''}</div>`).join('')
    : '<h4>trail</h4><div class="cv-trow dim">nothing asked yet</div>';
}

/* === the inline ask === */

function cvInlineAsk() {
  const sel = getSelection();
  const text = String(sel).trim();
  const host = sel.anchorNode && sel.anchorNode.parentElement?.closest('.cv-brick');
  //: The same words can appear twice in one brick. Which one was selected is the count before it.
  const nth = cvOccurrence(host, sel, text);
  const id = host?.dataset.id || cv.focus || (cv.canvas?.bricks.at(-1)?.id ?? '');
  const box = $$('#cv-inline');
  const r = text && sel.rangeCount ? sel.getRangeAt(0).getBoundingClientRect() : (host?.getBoundingClientRect() || {left: 200, bottom: 200});
  box.style.left = Math.min(r.left, innerWidth - 460) + 'px';
  box.style.top = (r.bottom + scrollY + 8) + 'px';
  box.hidden = false;
  const inp = $$('#cv-inline input');
  inp.placeholder = text ? `ask about “${text.slice(0, 40)}”` : 'ask about this document';
  inp.value = ''; inp.focus();
  $$('#cv-inline .cv-isel').textContent = text ? text.slice(0, 90) : '';
  inp.onkeydown = async ev => {
    if (ev.key === 'Escape') { box.hidden = true; return; }
    if (ev.key !== 'Enter' || !inp.value.trim()) return;
    const question = inp.value; box.hidden = true;
    await cvTurn({id, question, selection: text, nth});
  };
}

function cvOccurrence(host, sel, text) {
  if (!host || !text || !sel.rangeCount) return 0;
  const before = document.createRange();
  before.selectNodeContents(host);
  before.setEnd(sel.getRangeAt(0).startContainer, sel.getRangeAt(0).startOffset);
  return before.toString().split(text).length - 1;
}

/* === keys === */

document.addEventListener('keydown', ev => {
  if (cvMenuKey(ev)) return;
  const mod = ev.metaKey || ev.ctrlKey, k = ev.key.toLowerCase();
  if (mod && k === 'k') { ev.preventDefault(); return cvInlineAsk(); }
  if (mod && k === 's') { ev.preventDefault(); return cvSave(); }
  if (mod && k === 'j') { ev.preventDefault(); return cvMargin(); }
  if (mod && ev.shiftKey && ev.key === 'Enter') { ev.preventDefault(); return cvRunAll(); }
  if (ev.key === 'Escape') { $$('#cv-inline').hidden = true; cvCloseMenu(); cvHideFormat(); cvWireClose(); cvPick(null); }
  if (!cv.picked || /INPUT|TEXTAREA/.test(document.activeElement?.tagName) ||
      document.activeElement?.isContentEditable) return;
  cvBlockKey(ev, k);
});

//: With a block picked and nothing focused, the keyboard drives blocks rather than characters.
function cvBlockKey(ev, k) {
  const at = cv.canvas.bricks.findIndex(b => b.id === cv.picked);
  const b = cv.canvas.bricks[at]; if (!b) return;
  const go = d => { ev.preventDefault(); const n = cv.canvas.bricks[at + d]; if (n) cvPick(n.id); };
  if (ev.key === 'ArrowDown' || k === 'j') return go(1);
  if (ev.key === 'ArrowUp' || k === 'k') return go(-1);
  if (ev.key === 'Backspace' || ev.key === 'Delete') { ev.preventDefault(); return void cvOp({op: 'remove', id: b.id}); }
  if (ev.key === 'Enter') {
    ev.preventDefault();
    if (b.kind === 'code') return void cvRun(b.id);
    const el = $$(`.cv-prose[data-id="${b.id}"]`); if (el) { el.focus(); cvCaretEnd(el); }
    return;
  }
  if (ev.altKey && (ev.key === 'ArrowUp' || ev.key === 'ArrowDown')) { ev.preventDefault(); cvMove(b.id, ev.key === 'ArrowUp' ? -1 : 1); }
}

function cvMargin(on) {
  const w = $$('.cv-wrap');
  const open = on ?? !w.classList.contains('margin-open');
  w.classList.toggle('margin-open', open);
  $$('#cv-toggle')?.classList.toggle('on', open);
  return open;
}

function cvTheme(next) {
  cv.theme = next || (cv.theme === 'dark' ? 'light' : 'dark');
  document.body.dataset.theme = cv.theme;
  localStorage.setItem('cv-theme', cv.theme);
  for (const f of $all('#cv-doc iframe')) {
    const u = new URL(f.src, location.href);
    if (u.searchParams.get('theme') !== cv.theme && !f.srcdoc) { u.searchParams.set('theme', cv.theme); f.src = u.toString(); }
  }
}

async function cvBoot() {
  const q = new URLSearchParams(location.search);
  //: Embedded, the tab strip names the document and owns switching, so the picker is not drawn.
  cv.embed = document.body.dataset.embed === '1';
  const sel = $$('#cv-file');
  if (!cv.embed) {
    const list = await (await fetch('/canvas/list')).json();
    cv.files = list.files || [];
    sel.innerHTML = cv.files.map(f => `<option value="${cvEsc(f)}">${cvEsc(f.split('/').pop().replace('.canvas.md', ''))}</option>`).join('');
    sel.onchange = () => cvOpen(sel.value);
  }
  const want = q.get('path') || cv.files[0];
  if (!want) return cvStatus('no canvases found', 'bad');
  if (!cv.embed) sel.value = want;
  await cvOpen(want, q.get('fresh'));
  $$('#cv-runall').onclick = cvRunAll;
  $$('#cv-save').onclick = cvSave;
  $$('#cv-trust-run').onclick = cvTrust;
  $$('#cv-theme').onclick = () => cvTheme();
  $$('#cv-toggle').onclick = () => cvMargin();
  //: Embedded, the theme comes on the URL; a store of the frame's own would disagree with it.
  cvTheme(q.get('theme') || localStorage.getItem('cv-theme') || 'light');
  cvMargin(true);
  $$('#cv-askform').onsubmit = async ev => {
    ev.preventDefault();
    const inp = $$('#cv-askform input'), question = inp.value; inp.value = '';
    await cvTurn({id: cv.focus || '', question, selection: ''});
  };
}
document.addEventListener('DOMContentLoaded', cvBoot);
