const D = window.PATA, B = new Map(D.blocks.map(b => [b.id, b]));
const $ = s => document.querySelector(s), el = (t, c) => { const n = document.createElement(t); if (c) n.className = c; return n; };
const esc = s => String(s ?? '').replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
const S = { view: 'canvas', sel: null, basket: [], spec: null };

/* The context rules, mirroring `pata.context.resolve`. Scope membership is computed in Python and
 * shipped in `D.prompts[id].members`, so only pins, mutes and the budget are decided here. */
const WRAP = 60;
function basket(pid, spec) {
  const P = D.prompts[pid], mute = new Set(spec.mutes), seen = new Set([pid]), out = [];
  const take = (id, why, pin) => {
    const b = B.get(id);
    if (!b || seen.has(id) || mute.has(id) || b.kind === 'edge' || !b.chars) return;
    seen.add(id);
    out.push({ ref: id, kind: b.kind, label: b.label, chars: b.chars, why, pinned: !!pin || b.mode === 'keep' });
  };
  if (spec.goal !== false && D.goal) take(D.goal, 'goal', true);
  for (const r of spec.pins) if (!mute.has(r)) take(r, 'pin', true);
  for (const id of (P.members[spec.scope] || [])) take(id, spec.scope, false);
  return fit(out, spec.budget);
}
function fit(items, budget) {
  if (!budget) return items;
  let total = items.reduce((n, i) => n + i.chars + WRAP, 0);
  if (total <= budget) return items;
  const order = items.map((it, i) => i).filter(i => !items[i].pinned)
    .sort((a, b) => (items[a].why === 'discard' ? 0 : 1) - (items[b].why === 'discard' ? 0 : 1) || a - b);
  const drop = new Set();
  for (const i of order) { if (total <= budget) break; total -= items[i].chars + WRAP; drop.add(i); }
  return items.map((it, i) => drop.has(i) ? { ...it, dropped: true } : it);
}

const specOf = pid => JSON.parse(JSON.stringify({ scope: 'page', pins: [], mutes: [], budget: null, ...D.prompts[pid].spec }));

function select(id) {
  S.sel = id;
  const b = B.get(id);
  S.spec = (b && b.kind === 'prompt') ? specOf(id) : null;
  recompute();
}
function recompute() {
  S.basket = S.spec ? basket(S.sel, S.spec) : [];
  paintBasket(); mark(); outline();
}
const inCtx = () => new Set(S.basket.filter(i => !i.dropped).map(i => i.ref));
const cutSet = () => new Set(S.basket.filter(i => i.dropped).map(i => i.ref));

function mark() {
  const on = inCtx(), cut = cutSet();
  document.querySelectorAll('.blk').forEach(n => {
    const id = n.dataset.id;
    n.classList.toggle('sel', id === S.sel);
    n.classList.toggle('inctx', on.has(id));
    n.classList.toggle('cut', cut.has(id));
  });
  $('#app').querySelectorAll('#wires line').forEach(l => {
    l.setAttribute('stroke-opacity', (on.has(l.dataset.src) && on.has(l.dataset.dst)) ? '.85' : '.22');
    l.setAttribute('stroke', (on.has(l.dataset.src) && on.has(l.dataset.dst)) ? '#d2a8ff' : '#30363d');
  });
}

function body(b) {
  const p = b.props, n = el('div', 'bd');
  const add = h => { const d = el('div'); d.innerHTML = h; n.appendChild(d); };
  if (b.kind === 'goal') {
    add(`<div class="stmt">${esc(p.source)}</div>`);
    const bits = ['measure', 'baseline', 'target', 'by'].filter(k => p[k]).map(k => `<b>${k}</b> ${esc(p[k])}`);
    if (bits.length) add(`<div style="margin-top:7px;color:var(--fg2);font-size:12px">${bits.join(' &nbsp;·&nbsp; ')}</div>`);
  } else if (b.kind === 'code') {
    add(`<pre>${esc(p.source)}</pre>`);
    for (const o of (p.outputs || [])) {
      const t = o.output_type === 'error' ? `${o.ename}: ${o.evalue}` : (o.text || (o.data || {})['text/plain'] || '');
      if (t) add(`<div class="out${o.output_type === 'error' ? ' err' : ''}">${esc(t)}</div>`);
    }
  } else if (b.kind === 'prompt') {
    add(`<div class="ask">${esc(p.source)}</div>`);
    if (p.reply) add(`<div class="reply">${esc(p.reply)}</div>`);
  } else if (b.kind === 'source') {
    const w = p.url || p.path || '';
    add(`<div><a href="${esc(w)}">${esc(p.title || w)}</a></div>`);
    if (p.text) add(`<div style="margin-top:6px;color:var(--fg2)">${esc(p.text)}</div>`);
  } else if (b.kind === 'task') {
    add(`<div>${esc(p.source)}</div>`);
  } else if (b.kind === 'data') {
    add(`<pre>${esc(p.name || p.path || '')}</pre>`);
    if (p.preview) add(`<div class="out">${esc(p.preview)}</div>`);
  } else add(`<div>${esc(p.source || p.title || '')}</div>`);
  return n;
}

function card(b) {
  const n = el('div', 'blk');
  n.dataset.id = b.id; n.dataset.k = b.kind;
  const hd = el('div', 'hd');
  hd.innerHTML = `<span class="k">${b.kind}</span><span>${b.id}</span><span class="sp"></span>` +
    (b.props.status ? `<span class="chip ${b.props.status}">${b.props.status}</span>` : '') +
    (b.props.owner ? `<span class="chip">${esc(b.props.owner)}</span>` : '') +
    (b.mode !== 'auto' ? `<span class="chip ${b.mode}">${b.mode}</span>` : '') +
    (b.stale ? '<span class="chip stale">stale</span>' : '') +
    (b.props.execution_count ? `<span class="chip">[${b.props.execution_count}]</span>` : '') +
    `<span class="chip">${b.chars}c</span>`;
  n.append(hd, body(b));
  n.addEventListener('mousedown', e => { if (!e.target.closest('a')) select(b.id); });
  return n;
}

function paintPage() {
  const v = $('#view'); v.innerHTML = '<div id="page"></div>';
  const p = $('#page');
  let frame = null;
  for (const b of D.blocks) {
    if (b.kind === 'edge') continue;
    if (b.kind === 'frame') { const h = el('div', 'fr'); h.textContent = b.props.title; h.style.position = 'static'; p.appendChild(h); frame = b.id; continue; }
    p.appendChild(card(b));
  }
}

function paintCanvas() {
  const v = $('#view');
  v.innerHTML = '<div id="canvas"><svg id="wires"></svg></div>';
  const c = $('#canvas'), svg = $('#wires');
  let mx = 0, my = 0;
  for (const f of D.frames) {
    const n = el('div', 'fr');
    Object.assign(n.style, { left: f.x + 'px', top: f.y + 'px', width: f.w + 'px', height: f.h + 'px' });
    n.dataset.frame = f.id;
    n.innerHTML = `<span>${esc(f.title)}</span>`;
    c.appendChild(n);
    mx = Math.max(mx, f.x + f.w); my = Math.max(my, f.y + f.h);
  }
  for (const b of D.blocks) {
    if (b.kind === 'edge' || b.kind === 'frame' || b.x == null) continue;
    const n = card(b);
    Object.assign(n.style, { left: b.x + 'px', top: b.y + 'px', width: (b.w || 280) + 'px' });
    c.appendChild(n);
    drag(n, b);
    mx = Math.max(mx, b.x + (b.w || 280)); my = Math.max(my, b.y + 300);
  }
  fitFrames(); 
  c.style.width = (mx + 80) + 'px'; c.style.height = (my + 80) + 'px';
  for (const e of D.edges) {
    const l = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    l.dataset.src = e.src; l.dataset.dst = e.dst;
    l.setAttribute('stroke', '#30363d'); l.setAttribute('stroke-width', '1.5');
    if (e.rel === 'blocks') l.setAttribute('stroke-dasharray', '4 3');
    svg.appendChild(l);
  }
  wires();
}

/* Heights are content-driven, so the frame rectangles Python estimated are advisory. Refit them
 * to what the page actually laid out, or a block spills into the frame below it. */
function fitFrames() {
  const c = $('#canvas'); if (!c) return;
  const box = {};
  for (const b of D.blocks) {
    if (!b.frame || b.x == null) continue;
    const n = c.querySelector(`.blk[data-id="${b.id}"]`); if (!n) continue;
    const r = box[b.frame] || (box[b.frame] = { x1: 1e9, y1: 1e9, x2: -1e9, y2: -1e9 });
    r.x1 = Math.min(r.x1, n.offsetLeft); r.y1 = Math.min(r.y1, n.offsetTop);
    r.x2 = Math.max(r.x2, n.offsetLeft + n.offsetWidth); r.y2 = Math.max(r.y2, n.offsetTop + n.offsetHeight);
  }
  c.querySelectorAll('.fr[data-frame]').forEach(n => {
    const r = box[n.dataset.frame]; if (!r) return;
    Object.assign(n.style, { left: (r.x1 - 22) + 'px', top: (r.y1 - 34) + 'px',
      width: (r.x2 - r.x1 + 44) + 'px', height: (r.y2 - r.y1 + 56) + 'px' });
  });
}

function wires() {
  const c = $('#canvas'); if (!c) return;
  const box = id => { const n = c.querySelector(`.blk[data-id="${id}"]`); return n && { x: n.offsetLeft, y: n.offsetTop, w: n.offsetWidth, h: n.offsetHeight }; };
  for (const l of $('#wires').children) {
    const a = box(l.dataset.src), b = box(l.dataset.dst);
    if (!a || !b) { l.setAttribute('stroke-opacity', '0'); continue; }
    l.setAttribute('x1', a.x + a.w / 2); l.setAttribute('y1', a.y + a.h / 2);
    l.setAttribute('x2', b.x + b.w / 2); l.setAttribute('y2', b.y + b.h / 2);
  }
}

function drag(n, b) {
  n.addEventListener('mousedown', e => {
    if (e.target.closest('a')) return;
    const sx = e.clientX, sy = e.clientY, ox = b.x, oy = b.y;
    n.classList.add('drag');
    const move = ev => { b.x = ox + ev.clientX - sx; b.y = oy + ev.clientY - sy; n.style.left = b.x + 'px'; n.style.top = b.y + 'px'; wires(); };
    const up = () => { n.classList.remove('drag'); fitFrames(); document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up); };
    document.addEventListener('mousemove', move); document.addEventListener('mouseup', up);
  });
}

function outline() {
  const a = $('#outline'); a.innerHTML = '';
  const on = inCtx();
  for (const b of D.blocks) {
    if (b.kind === 'edge') continue;
    const r = el('div', 'row' + (b.kind === 'frame' ? ' frame' : ' kid') + (b.id === S.sel ? ' sel' : '') + (on.has(b.id) ? ' inctx' : ''));
    r.textContent = b.kind === 'frame' ? b.props.title : (b.label || b.kind);
    r.onclick = () => { select(b.id); const n = document.querySelector(`.blk[data-id="${b.id}"]`); if (n) n.scrollIntoView({ block: 'center', behavior: 'smooth' }); };
    a.appendChild(r);
  }
}

function paintBasket() {
  const p = $('#basket');
  if (!S.spec) {
    p.innerHTML = '<h4>context</h4><div class="empty">Select a prompt block to see exactly what the model will be given.</div>';
    $('#app main').classList.add('nobasket');
    return;
  }
  $('#app main').classList.remove('nobasket');
  const kept = S.basket.filter(i => !i.dropped);
  const total = kept.reduce((n, i) => n + i.chars + WRAP, 0);
  const budget = S.spec.budget || 0;
  const pct = budget ? Math.min(100, total / budget * 100) : 0;
  p.innerHTML = `<h4>context for ${S.sel}</h4><div class="pad">
    <div class="ctl"><label>scope</label><select id="scope">${D.scopes.map(s => `<option ${s === S.spec.scope ? 'selected' : ''}>${s}</option>`).join('')}</select></div>
    <div class="ctl"><label>budget</label><input id="budget" type="number" step="500" value="${budget}"></div>
    <div class="meter ${budget && total > budget ? 'over' : ''}"><i style="width:${pct}%"></i></div>
    <div class="tot">${kept.length} blocks &nbsp; ${total.toLocaleString()} chars${budget ? ' / ' + budget.toLocaleString() : ''} &nbsp; ${S.basket.length - kept.length} cut</div>
    </div><h4>in the basket</h4><div class="pad" id="items"></div>
    <h4>what the model reads</h4><pre id="raw"></pre>
    <div class="hint">Click a row to mute it. Click the pin to keep it whatever the budget says.</div>`;
  const box = $('#items');
  for (const it of S.basket) {
    const r = el('div', 'item ' + (it.dropped ? 'off' : 'on'));
    r.innerHTML = `<span class="pin">${it.pinned ? '*' : ''}</span><span class="nm">${esc(it.label)}</span>` +
      `<span class="why">${it.why}</span><span class="n">${it.chars}</span>`;
    r.querySelector('.pin').onclick = e => { e.stopPropagation(); togglePin(it.ref); };
    r.onclick = () => { S.spec.mutes.push(it.ref); recompute(); };
    box.appendChild(r);
  }
  for (const m of S.spec.mutes) {
    const b = B.get(m); if (!b) continue;
    const r = el('div', 'item off');
    r.innerHTML = `<span class="pin"></span><span class="nm" style="text-decoration:line-through">${esc(b.label)}</span><span class="why">muted</span><span class="n">${b.chars}</span>`;
    r.onclick = () => { S.spec.mutes = S.spec.mutes.filter(x => x !== m); recompute(); };
    box.appendChild(r);
  }
  $('#raw').textContent = kept.map(i => `<cell id="${i.ref}" type="${i.kind}" compact="${i.pinned ? 'keep' : 'auto'}" why="${i.why}">\n${(B.get(i.ref).text || '').slice(0, 240)}\n</cell>`).join('\n');
  $('#scope').onchange = e => { S.spec.scope = e.target.value; recompute(); };
  $('#budget').onchange = e => { S.spec.budget = Number(e.target.value) || null; recompute(); };
}
function togglePin(ref) {
  const i = S.spec.pins.indexOf(ref);
  if (i >= 0) S.spec.pins.splice(i, 1); else S.spec.pins.push(ref);
  recompute();
}

function setView(v) {
  S.view = v;
  document.querySelectorAll('[data-view]').forEach(b => b.setAttribute('aria-pressed', b.dataset.view === v));
  (v === 'page' ? paintPage : paintCanvas)();
  mark();
}
$('#toggle').addEventListener('click', e => { const b = e.target.closest('[data-view]'); if (b) setView(b.dataset.view); });
setView('canvas');
select(D.firstPrompt);
