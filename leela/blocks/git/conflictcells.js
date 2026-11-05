// A conflicted notebook, answered cell by cell.
//
// The worktree file is JSON with conflict markers through it: not a notebook, and not text anybody
// can read a merge out of. Git keeps all three sides in the index as whole notebooks, so the server
// lines them up into rows and this draws them. A person answers about cells, and the only answers
// are the four the server takes.

//: The states that owe an answer. The rest are context and resolve themselves.
const NB_OWED = new Set(['both', 'added', 'deleted']);
const NB_OWED_SAYS = {both: 'both sides changed this cell', added: 'one side added this cell',
                      deleted: 'one side deleted this cell'};
const NB_CONTEXT_SAYS = {same: 'both sides agree', ours: 'only ours changed it',
                         theirs: 'only theirs changed it'};

function nbCellSource(cell) {
  const s = (cell || {}).source;
  return Array.isArray(s) ? s.join('') : String(s || '');
}

// The same read-only cell the split pane draws, so a merge and a side-by-side read look alike.
function nbMergeCell(cell, label) {
  if (!cell) return `<div class="lee-nbmerge-absent">${esc(label)} does not have this cell</div>`;
  const kind = String(cell.cell_type || 'code');
  return `<article class="lee-split-cell ${esc(kind)}"><header>${esc(label)} · ${esc(kind)}</header>` +
         `<pre>${esc(nbCellSource(cell))}</pre></article>`;
}

// What a row can be answered with. An added or deleted cell exists on one side only, so the
// question is whether to keep it, and `side` is the side that has it to keep.
function nbTakes(row) {
  if (row.state === 'both') return [['ours', 'take ours'], ['theirs', 'take theirs'], ['both', 'take both']];
  return [[row.side === 'theirs' ? 'theirs' : 'ours', 'keep'], ['drop', 'drop']];
}

function nbContextCell(row) {
  return nbMergeCell(row.state === 'theirs' ? row.theirs : (row.ours || row.theirs),
                     NB_CONTEXT_SAYS[row.state] || row.state);
}

function nbOwedRow(row) {
  const takes = nbTakes(row).map(([choice, label]) =>
    `<button class="lee-btn" data-key="${esc(row.key)}" data-choice="${choice}">${esc(label)}</button>`).join('');
  return `<section class="lee-nbmerge-row" data-row="${esc(row.key)}">` +
    `<header><strong>${esc(NB_OWED_SAYS[row.state] || row.state)}</strong>` +
    `<span class="lee-dim">${esc(row.id ? 'cell ' + row.id : row.key)}</span>` +
    `<span class="lee-spacer"></span>${takes}<span class="lee-nbmerge-chose" data-chose></span></header>` +
    `<div class="lee-nbmerge-sides">${nbMergeCell(row.ours, 'ours')}${nbMergeCell(row.theirs, 'theirs')}</div>` +
    `</section>`;
}

// Rows in document order, with each run of self-resolving ones folded into one count. Order is what
// says where a contested cell sits in the notebook, so the context is not moved out of the way.
function nbMergeBody(rows) {
  const out = [];
  let context = [];
  const flush = () => {
    if (!context.length) return;
    out.push(`<details class="lee-nbmerge-context"><summary>${context.length} settled cell` +
             `${context.length === 1 ? '' : 's'}, nothing to answer</summary>` +
             context.map(nbContextCell).join('') + '</details>');
    context = [];
  };
  for (const row of rows) {
    if (NB_OWED.has(row.state)) { flush(); out.push(nbOwedRow(row)); }
    else context.push(row);
  }
  flush();
  return out.join('') || '<div class="lee-dim">this notebook has no cells to merge</div>';
}

async function showNotebookConflict(path, d) {
  const rows = d.rows || [], owed = rows.filter(r => NB_OWED.has(r.state)), choices = {};
  const m = modal(
    `<div class="lee-mhead">merge ${esc(path)}` +
    `<span class="sub">cell by cell · ours is this branch, theirs is incoming</span></div>` +
    `<div class="lee-nbmerge"><div class="lee-nbmerge-rows">${nbMergeBody(rows)}</div>` +
    `<div class="lee-nbmerge-foot"><span class="lee-dim" data-nb-left></span>` +
    `<span class="lee-nbmerge-why" data-nb-why></span>` +
    `<button class="lee-btn go" data-nb-apply>apply &amp; stage</button></div></div>`,
    null, null, {className: 'lee-modal-nbmerge', storageKey: 'git-notebook-conflict'});

  const left = () => owed.filter(r => !choices[r.key]).length;
  const refresh = () => {
    const n = left();
    m.querySelector('[data-nb-left]').textContent = owed.length
      ? (n ? `${n} of ${owed.length} contested cell${owed.length === 1 ? '' : 's'} still undecided`
           : `all ${owed.length} contested cell${owed.length === 1 ? '' : 's'} decided`)
      : 'nothing here needs an answer';
    m.querySelector('[data-nb-apply]').disabled = n > 0;
    m.querySelectorAll('[data-row]').forEach(sec => {
      const pick = choices[sec.dataset.row] || '';
      sec.classList.toggle('decided', !!pick);
      sec.querySelector('[data-chose]').textContent = pick ? `taking ${pick}` : '';
      sec.querySelectorAll('[data-choice]').forEach(b => b.classList.toggle('on', b.dataset.choice === pick));
    });
  };
  m.querySelectorAll('[data-choice]').forEach(b => b.onclick = () => {
    const key = b.dataset.key;
    if (choices[key] === b.dataset.choice) delete choices[key];
    else choices[key] = b.dataset.choice;
    refresh();
  });
  m.querySelector('[data-nb-apply]').onclick = async () => {
    if (left()) return;
    const why = m.querySelector('[data-nb-why]');
    why.textContent = '';
    try { await post('/git/notebook/conflict/resolve', {path, choices}); }
    catch (e) {
      // The server checks the same thing again, over the rows it re-reads. Its sentence is the one
      // that is true about the file, so it is shown rather than translated.
      why.textContent = e.message || String(e);
      return status(`notebook merge refused · ${e.message || e}`, 'err');
    }
    m.remove();
    const info = await api(gitUrl('/git/info'));
    gitUI.snapshot = info; paintGitPill(info);
    noteGitSignature(info); gitChanged();
    afterConflictResolved(info, `${path} staged`);
  };
  refresh();
}
window.showNotebookConflict = showNotebookConflict;
