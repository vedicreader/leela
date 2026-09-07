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
