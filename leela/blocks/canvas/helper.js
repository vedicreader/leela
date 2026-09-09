/* The helper: one thread in the margin, and the same turn reachable from anywhere in the document.
 * Inline asks and margin asks are the same call. What differs is the selection that travels with it. */

/* The margin: where a question is asked, and where the answer comes back.

   The turn itself belongs to the agent pane. It drives the same agent through the same canvas
   tools, and it already owns approvals, steering and the history this used to redraw badly. */

async function cvTurn({id, question, selection, nth = 0}) {
  if (!question?.trim()) return;
  try {
    if (typeof parent?.canvasAskPane !== 'function') return cvStatus('no agent pane to ask', 'bad');
    const sent = await parent.canvasAskPane({question, brickId: id || '', selection: selection || '',
                                             path: cv.path});
    return cvStatus(sent ? 'asked in the agent pane' : 'the agent pane refused it', sent ? 'ok' : 'bad');
  } catch (e) { cvStatus('could not reach the agent pane: ' + e, 'bad'); }
}

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
  const want = q.get('path');
  if (!want) return cvStatus('no document named', 'bad');
  await cvOpen(want, q.get('fresh'));
  $$('#cv-runall').onclick = cvRunAll;
  $$('#cv-save').onclick = cvSave;
  $$('#cv-trust-run').onclick = cvTrust;
  $$('#cv-theme').onclick = () => cvTheme();
  $$('#cv-toggle').onclick = () => cvMargin();
  //: The theme comes on the URL; a store of the frame's own would disagree with the IDE's.
  cvTheme(q.get('theme') || 'light');
  cvMargin(true);
  $$('#cv-askform').onsubmit = async ev => {
    ev.preventDefault();
    const inp = $$('#cv-askform input'), question = inp.value; inp.value = '';
    await cvTurn({id: cv.focus || '', question, selection: ''});
  };
}
document.addEventListener('DOMContentLoaded', cvBoot);
