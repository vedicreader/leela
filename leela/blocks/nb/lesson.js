function learnDiff(guess, actual) {
  const lines = text => text.split(/\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]/)
    .map(line => line.split(/[\t-\r\x1c-\x20\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/).filter(Boolean).join(' ')).filter(Boolean);
  const g = lines(guess), a = lines(actual);
  return Array.from({length: Math.max(g.length, a.length)}, (_, i) => {
    const x = g[i] ?? null, y = a[i] ?? null;
    return {guess: x, actual: y, kind: x === null ? 'missing' : y === null ? 'extra' : x === y ? 'match' : 'mismatch'};
  });
}

function lessonActual(c) {
  const text = value => Array.isArray(value) ? value.join('') : String(value ?? '');
  const outputs = c.outputs || [], error = outputs.find(o => o.output_type === 'error');
  if (error) {
    const last = stripAnsi(text((error.traceback || []).join('\n'))).trim().split('\n').pop();
    return 'It raised ' + (last || `${error.ename}: ${error.evalue}`);
  }
  return stripAnsi(outputs.map(o => o.output_type === 'stream' ? text(o.text) : text(o.data?.['text/plain'])).filter(Boolean).join('\n'));
}
function lessonRevealText(c) {
  const lesson = c.extra.lesson, rows = learnDiff(String(lesson.prediction || ''), lessonActual(c));
  const different = rows.filter(r => r.kind !== 'match');
  if (!different.length) return 'Right. You saw that before running it.';
  const lines = rows.filter(r => r.kind === 'match').map(r => r.actual);
  for (const r of different) lines.push(r.kind === 'missing' ? `It printed ${r.actual}, which you did not expect.`
    : r.kind === 'extra' ? `You expected ${r.guess}, which did not appear.` : `You wrote ${r.guess}. It printed ${r.actual}.`);
  if (lesson.confidence >= 60) lines.push('You were sure, and it went another way. That is the part worth a look.');
  return lines.join('\n');
}
function lessonRevealActions(cell, el) {
  const lesson = cell.extra.lesson, key = `${cell.id}:${cell.execution_count}`;
  const row = document.createElement('div'); row.className = 'lee-reveal-save'; el.appendChild(row);
  if (lesson.saved === key) { row.textContent = lesson.saved_message || 'Saved to your learning shelf.'; return; }
  const button = document.createElement('button'); button.type = 'button'; button.className = 'lee-btn'; button.textContent = 'Save card';
  row.appendChild(button);
  button.onmousedown = e => { e.preventDefault(); e.stopPropagation(); };
  button.onclick = async () => {
    if (button.disabled) return;
    button.disabled = true;
    const path = lee.path, tabKey = lee.tabKey;
    try {
      await lee.nbQueue;
      if (lee.tabKey !== tabKey) throw new Error('Return to the lesson notebook, then save.');
      if ($('.lee-tab.active')?.classList.contains('dirty')) throw new Error('Save the notebook first.');
      const d = await post('/lesson/save', {path, cell_id: cell.id});
      lesson.saved = d.saved; lesson.saved_message = d.message;
      const current = lee.tabKey === tabKey && lee.cells.find(c => c.id === cell.id && c.execution_count === cell.execution_count);
      if (current) Object.assign(current.extra.lesson, {saved: d.saved, saved_message: d.message});
      row.textContent = d.message;
      if (d.disk_version) { recordDiskVersion(path, d.disk_version); await rebaseDrafts(path, d.disk_version); noteSelfWrite(path); }
    } catch (e) { status(String(e.message || e), 'err'); button.disabled = false; }
  };
}
function renderLessonReveal(c) {
  const cell = $(`.lee-cell[data-id="${CSS.escape(c.id)}"]`); if (!cell) return;
  $('.lee-reveal', cell)?.remove();
  if (c.cell_type !== 'code' || !c.extra?.lesson || c.extra.lesson.for_count !== c.execution_count
      || c.stale || $('#state-' + c.id)?.classList.contains('stale') || c.running || !c.outputs?.length) return;
  const el = document.createElement('div'); el.className = 'lee-reveal';
  el.textContent = lessonRevealText(c);
  $('#out-' + c.id, cell).after(el);
  lessonRevealActions(c, el);
}
function paintLessonCell(cell, c) {
  const role = c.cell_type === 'markdown' ? c.extra?.lesson?.role : '';
  cell.dataset.lessonRole = role || '';
  $('.lee-confidence', cell)?.remove();
  if (role !== 'prediction') return;
  const row = document.createElement('div'); row.className = 'lee-confidence';
  const label = document.createElement('span'); label.textContent = 'Sure?'; row.appendChild(label);
  for (const [value, name] of [[10, 'not'], [30, 'a little'], [50, 'half'], [70, 'fairly'], [90, 'very']]) {
    const button = document.createElement('button'); button.type = 'button'; button.textContent = name;
    button.setAttribute('aria-pressed', String(c.extra.lesson.confidence === value));
    button.onclick = async () => {
      const at = lee.cells.findIndex(x => x.id === c.id), current = lee.cells[at]; if (!current) return;
      const previous = current.extra.lesson.confidence, confidence = previous === value ? null : value;
      if (confidence === null) delete current.extra.lesson.confidence; else current.extra.lesson.confidence = confidence;
      for (const b of row.querySelectorAll('button')) { b.disabled = true; b.setAttribute('aria-pressed', String(b === button && confidence !== null)); }
      try { await nbEdit({op: 'lesson_confidence', i: at, confidence}); }
      catch (e) {
        if (previous == null) delete current.extra.lesson.confidence; else current.extra.lesson.confidence = previous;
        status(String(e.message || e), 'err');
      } finally {
        const now = lee.cells.find(x => x.id === c.id), host = $(`.lee-cell[data-id="${CSS.escape(c.id)}"]`);
        if (now && host) paintLessonCell(host, now);
      }
    };
    row.appendChild(button);
  }
  $('.lee-cellmain', cell).appendChild(row);
}
