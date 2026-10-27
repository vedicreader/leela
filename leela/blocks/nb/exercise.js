const EXERCISE_MARKS = {pass: '✓', fail: '✗', error: '!', timeout: '…'};
const isExercise = c => c?.cell_type === 'code' && !!c.extra?.exercise?.tests;

function exEl(tag, cls, text) {
  const e = document.createElement(tag); e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function exerciseState(key) {
  const all = lee.exerciseResults ||= new Map();
  if (!all.has(key)) all.set(key, {});
  return all.get(key);
}

function exerciseGradeLine(c) {
  const g = c.extra?.exercise?.state?.grade;
  return g && c.graded_current ? `Grade ${g.score}/10. ${g.note}` : '';
}

function exerciseTutorMessage(c, r) {
  const rows = r.checks.map(k => `- ${k.say}: ${k.message}`);
  return [`I pressed Check on the exercise in cell ${lee.cells.indexOf(c) + 1} (id ${c.id}). ${r.summary}`, ...rows,
          'Please look at my code and give me one hint, not the answer.'].join('\n');
}

function renderExercise(c, root) {
  const host = $('.lee-exercise', root || $(`.lee-cell[data-id="${CSS.escape(c.id)}"]`)); if (!host) return;
  const st = exerciseState(`${lee.tabKey}:${c.id}`), r = st.result, fresh = !!r && r.source === c.source;
  const kept = host.contains?.(document.activeElement) ? document.activeElement.getAttribute('data-ex') : '';
  const check = exEl('button', 'lee-btn' + (st.busy ? ' busy' : ''), st.busy ? 'Checking…' : 'Check');
  check.type = 'button'; check.setAttribute('aria-label', 'Check my code'); check.setAttribute('data-ex', 'check');
  check.setAttribute('aria-busy', String(!!st.busy)); check.setAttribute('aria-disabled', String(!!st.busy || !!c.running));
  check.onclick = () => checkExercise(c.id);
  const ask = exEl('button', 'lee-btn', 'Ask the tutor');
  ask.type = 'button'; ask.setAttribute('aria-label', 'Ask the tutor about this result'); ask.setAttribute('data-ex', 'ask'); ask.disabled = !fresh;
  ask.onclick = () => askTutor(c.id);
  const bar = exEl('div', 'lee-ex-bar'); bar.appendChild(check); bar.appendChild(ask);
  host.replaceChildren(bar);
  if (st.error) host.appendChild(exEl('div', 'lee-ex-error', st.error));
  if (r) {
    const summary = exEl('div', 'lee-ex-summary', r.summary); summary.setAttribute('role', 'status'); host.appendChild(summary);
    if (r.source !== c.source) host.appendChild(exEl('div', 'lee-ex-note', 'Out of date: the code has changed since this check.'));
    const list = exEl('ul', 'lee-ex-list' + (fresh ? '' : ' stale'));
    for (const k of r.checks) {
      const row = exEl('li', 'lee-ex-row'); row.setAttribute('data-status', k.status);
      const mark = exEl('span', 'lee-ex-mark', EXERCISE_MARKS[k.status] || '?'); mark.setAttribute('aria-label', k.status);
      row.appendChild(mark); row.appendChild(exEl('span', 'lee-ex-say', k.say)); row.appendChild(exEl('span', 'lee-ex-msg', k.message));
      list.appendChild(row);
    }
    host.appendChild(list);
  }
  const grade = exerciseGradeLine(c);
  if (grade) host.appendChild(exEl('div', 'lee-ex-grade', grade));
  ({check, ask})[kept]?.focus();
}

async function checkExercise(cellId) {
  await lee.nbQueue;
  const runKey = lee.tabKey, st = exerciseState(`${runKey}:${cellId}`);
  const cur = () => lee.tabKey === runKey ? lee.cells.find(x => x.id === cellId) : null;
  const c = cur(); if (!c || st.busy) return;
  if (c.running) return status('this cell is already running', 'err');
  st.busy = true; c.running = true; st.error = '';
  renderExercise(c);
  try {
    if (lee.path && $('.lee-tab.active.dirty') && !await saveTab(true)) throw new Error('the notebook could not be saved first');
    const i = lee.cells.findIndex(x => x.id === cellId); if (!cur() || i < 0) throw new Error('the notebook changed before the check began');
    const v = ensureCellMounted(i), source = v ? LeeCM.getDoc(v) : lee.cells[i].source;
    const {cell, ...verdict} = await post('/exercise/check', {i, id: cellId, path: runKey, source, seq: nextSeq()});
    st.result = {...verdict, source};
    const at = cur();
    if (at && cell) {
      const view = lee.editors.get(cellId), typed = view ? LeeCM.getDoc(view) : source;
      Object.assign(at, cell);
      if (typed !== source) { at.source = typed; at.graded_current = false; }
      renderOutputs(at);
      $('#g-' + cellId).textContent = '[' + (cell.execution_count ?? ' ') + ']';
      setCellState(at, (at.outputs || []).some(o => o.output_type === 'error') ? 'error' : 'done');
      status(verdict.summary, verdict.passed === verdict.total ? 'ok' : 'info');
      if (lee.path && autoSaveEnabled()) saveTab(true).catch(() => {});
      leeVars();
    }
  } catch (e) { st.error = String(e.message || e); status(st.error, 'err'); }
  finally {
    st.busy = false;
    for (const x of [c, cur()]) if (x) x.running = false;
    const at = cur(); if (at) renderExercise(at);
  }
}

function askTutor(cellId) {
  const c = lee.cells.find(x => x.id === cellId), r = exerciseState(`${lee.tabKey}:${cellId}`).result;
  if (!c || !r || r.source !== c.source) return;
  if (lee.agentBusy) return status('The tutor is working. Ask again when it finishes.', 'err');
  leeAct('focus_agent');
  const prompt = $('#agentprompt');
  if (prompt.value.trim()) return status('Send or clear your message to the agent first.', 'err');
  prompt.value = exerciseTutorMessage(c, r);
  return sendAgent();
}
