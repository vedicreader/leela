/* Asking: the same agent-pane turn from anywhere in the document. What differs is the brick and
   the selection that travel with it. The turn itself is the pane's: approvals, steering, history. */

async function cvTurn({id, question, selection, nth = 0}) {
  if (!question?.trim()) return;
  try {
    if (typeof parent?.canvasAskPane !== 'function') return cvStatus('no agent pane to ask', 'bad');
    const sent = await parent.canvasAskPane({question, brickId: id || '', selection: selection || '',
                                             path: cv.path});
    return cvStatus(sent ? 'asked in the agent pane' : 'the agent pane refused it', sent ? 'ok' : 'bad');
  } catch (e) { cvStatus('could not reach the agent pane: ' + e, 'bad'); }
}

function cvInlineAsk(bid) {
  const sel = getSelection();
  const text = bid ? '' : String(sel).trim();
  const host = bid ? $$(`.cv-brick[data-id="${bid}"]`) : sel.anchorNode && sel.anchorNode.parentElement?.closest('.cv-brick');
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
  //: The theme comes on the URL; a store of the frame's own would disagree with the IDE's. Set before
  //: the document loads, so the IDE repainting it mid-load is not undone.
  cvTheme(q.get('theme') || 'light');
  if (!want) return cvStatus('no document named', 'bad');
  await cvOpen(want, q.get('fresh'));
  $$('#cv-runall').onclick = cvRunAll;
  $$('#cv-save').onclick = cvSave;
  $$('#cv-trust-run').onclick = cvTrust;
  $$('#cv-theme').onclick = () => cvTheme();
}
document.addEventListener('DOMContentLoaded', cvBoot);
