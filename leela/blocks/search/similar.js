/* ---- similarity: what else in this codebase looks like the thing under the cursor ---- */
function cursorLine() {
  if (lee.kind === 'notebook') {
    const c = lee.cells[lee.sel], v = c && lee.editors.get(c.id);
    return v ? LeeCM.lineOf(v) : 1;
  }
  const v = lee.editors.get('file');
  return v ? LeeCM.lineOf(v) : 1;
}

function hitList(hits, note, title, onPick) {
  let sel = 0;
  const m = modal(
    `<div class="lee-mhead">${esc(title)}<span class="sub">${esc(note || '')}</span></div>
     <div class="lee-modallist" id="hl"></div>`,
    (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, hits.length - 1); paint(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); paint(); }
      else if (e.key === 'Enter') { e.preventDefault(); go(); }
    });
  const list = m.querySelector('#hl');
  const paint = () => {
    list.innerHTML = hits.length ? hits.map((h, i) =>
      `<div class="lee-mrow${i === sel ? ' sel' : ''}" data-i="${i}">` +
      `<span>${esc(h.symbol || h.text.slice(0, 60))}</span>` +
      `<span class="sub">${esc(h.path.split('/').pop())}:${h.line}` +
      `${h.score ? ' · d=' + h.score.toFixed(3) : ''}</span></div>`).join('')
      : '<div class="lee-dim">nothing found</div>';
    list.querySelector('.sel')?.scrollIntoView({block: 'nearest'});
  };
  const go = () => { const h = hits[sel]; if (h) { m.remove(); onPick(h); } };
  list.addEventListener('click', e => { const r = e.target.closest('.lee-mrow'); if (r) { sel = +r.dataset.i; go(); } });
  paint();
  return m;
}

const openHit = openLocation;

async function findSimilar() {
  if (!lee.path) return status('open a file first', 'err');
  status('finding similar code…');
  const d = await api(`/similar?path=${encodeURIComponent(lee.path)}&line=${cursorLine()}&mode=cluster`);
  status(`${d.hits.length} similar · ${d.backend} · ${d.note}`, d.hits.length ? 'ok' : null);
  hitList(d.hits, `${d.backend} — ${d.note}`, 'code like this', openHit);
}

async function codeMap() {
  status('clustering the codebase…');
  const d = await api('/clusters');
  if (!d.clusters.length) return status(d.note || 'no clusters', 'err');
  status(`${d.clusters.length} clusters · ${d.note}`, 'ok');
  // one row per cluster; picking one drills into its members
  const rows = d.clusters.map(c => ({
    symbol: `${c.label}  (${c.size})`, text: '', path: c.files[0] || '', line: 1,
    score: 0, _cluster: c,
  }));
  hitList(rows, d.note, 'code map — clusters by shape', (r) => {
    const c = r._cluster;
    hitList(c.members, `${c.size} members across ${c.files.length} files`, `cluster: ${c.label}`, openHit);
  });
}

/* Start a run configuration -- a command line, kept in the project -- in a process leela
 * puts an inspector into. That is the difference between this and the same command in a
 * terminal: the inspector is *inside* it, so the variable panel can watch the app's own
 * module while it serves. A process started anywhere else has to opt in with
 * `dhrishti.serving.serve()`; the picker says so, because everyone asks. */
/* Starting one, wherever the request came from: the picker, or Run on an open file. Both have
   to land in the same place or there are two kinds of running script again, which is the thing
   that made this confusing. */
