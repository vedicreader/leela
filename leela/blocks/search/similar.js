function cursorLine() {
  if (lee.kind === 'notebook') {
    const c = lee.cells[lee.sel], v = c && lee.editors.get(c.id);
    return v ? LeeCM.lineOf(v) : 1;
  }
  const v = lee.editors.get('file');
  return v ? LeeCM.lineOf(v) : 1;
}

/* Where a hit is, said well enough to choose between two of them. A package hit is its dotted
   module, because `document.py` is offered by chonkie and by prompt_toolkit, and every package
   offers an `__init__.py`. A project hit is its basename until two hits share one, and then as
   many parent folders as it takes to tell them apart. */
function hitWhere(h, hits) {
  if (h.module) return h.module;
  const parts = String(h.path || '').split('/').filter(Boolean);
  const clash = hits.filter(o => o !== h && !o.module && String(o.path || '').split('/').pop() === parts.at(-1));
  if (!clash.length) return parts.at(-1) || h.path;
  const others = clash.map(o => String(o.path || '').split('/').filter(Boolean));
  for (let take = 2; take <= parts.length; take++) {
    const mine = parts.slice(-take).join('/');
    if (others.every(o => o.slice(-take).join('/') !== mine)) return mine;
  }
  return parts.join('/');
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
      `<span class="sub">${esc(hitWhere(h, hits))}:${h.line}` +
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

/* Start a run configuration in a process leela puts an inspector into. That is the difference
 * between this and the same command in a terminal: the inspector is inside it, so the variable
 * panel can watch the app's own module while it serves. A process started anywhere else has to opt
 * in with `dhrishti.serving.serve()`, and the picker says so.
 *
 * The picker and Run on an open file both come here, or there are two kinds of running script
 * again. */
