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
