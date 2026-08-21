// Three-pane conflict resolution: ours, an editable result, and theirs.
//
// The conflicts are read from the markers Git already wrote into the working-tree file, not
// diffed back out of the three versions. Git's own account of what it could not decide is
// better than anything reconstructed from the sides afterwards -- it knows which lines it
// tried to merge and gave up on, and a re-diff only guesses at it.
//
// The result pane is that file, markers and all, and it is re-scanned after every change.
// That is what lets the buttons and hand-editing coexist without either being a mode:
// "which conflicts are left" is answered by looking at the text rather than by remembering
// what was clicked, so an edit that removes a marker block counts as resolving it.

const CONFLICT_OPEN = /^<{7}(?:\s|$)/, CONFLICT_MID = /^={7}(?:\s|$)/,
      CONFLICT_BASE = /^\|{7}(?:\s|$)/, CONFLICT_CLOSE = /^>{7}(?:\s|$)/;

function scanConflicts(text) {
  const lines = String(text ?? '').split('\n'), blocks = [];
  for (let i = 0; i < lines.length; i++) {
    if (!CONFLICT_OPEN.test(lines[i])) continue;
    const block = {start: i, end: -1, ours: [], theirs: [], base: []};
    let side = block.ours, j = i + 1;
    for (; j < lines.length; j++) {
      if (CONFLICT_BASE.test(lines[j])) { side = block.base; continue; }
      if (CONFLICT_MID.test(lines[j])) { side = block.theirs; continue; }
      if (CONFLICT_CLOSE.test(lines[j])) { block.end = j; break; }
      side.push(lines[j]);
    }
    // An opening marker with no close is a line of text that happens to look like one --
    // in a file *about* merge conflicts, say. Not a conflict, and not ours to rewrite.
    if (block.end < 0) continue;
    blocks.push(block); i = block.end;
  }
  return {lines, blocks};
}

// One whole side of a conflicted file, as it would read if every contested block went that
// way. `ranges` are the 1-based line spans of the contested parts, for marking them.
function conflictSide(scan, pick) {
  const out = [], ranges = [];
  let at = 0;
  for (const block of scan.blocks) {
    out.push(...scan.lines.slice(at, block.start));
    const from = out.length + 1;
    out.push(...(block[pick] || []));
    // A side that deleted these lines contributes none, so the marker goes on the seam.
    ranges.push(out.length >= from ? {from, to: out.length}
                                   : {from: Math.max(1, from - 1), to: Math.max(1, from - 1)});
    at = block.end + 1;
  }
  out.push(...scan.lines.slice(at));
  return {text: out.join('\n'), ranges};
}

function replaceConflict(scan, index, lines) {
  const block = scan.blocks[index];
  if (!block) return null;
  return [...scan.lines.slice(0, block.start), ...lines,
          ...scan.lines.slice(block.end + 1)].join('\n');
}

async function showGitConflict(path) {
  try {
    const d = await api(gitUrl('/git/conflict', {path}));
    const original = scanConflicts(d.worktree || '');
    if (!original.blocks.length && (d.ours || d.theirs)) {
      // Add/add or delete/modify: there are no marked lines to work through, so the choice
      // is which whole side to keep, and pretending otherwise would be a worse dialog.
      return showWholeSideConflict(path, d);
    }
    const lang = codeLang('', path);
    const pane = (key, label, note) =>
      `<section data-pane="${key}"${key === 'base' ? ' hidden' : ''}>` +
      `<header><strong>${label}</strong>${note ? `<small>${note}</small>` : ''}</header>` +
      `<div class="lee-merge3-editor" data-editor></div></section>`;
    const m = modal(
      `<div class="lee-mhead">resolve ${esc(path)}<span class="sub">ours · result · theirs</span></div>` +
      `<div class="lee-git-merge3">` +
      `<div class="lee-merge3-bar">` +
      `<span class="lee-merge3-count" data-count></span>` +
      `<button class="lee-btn" data-nav="prev" title="previous conflict">‹</button>` +
      `<button class="lee-btn" data-nav="next" title="next conflict">›</button>` +
      `<span class="lee-merge3-take">` +
      `<button class="lee-btn" data-take="ours">take ours</button>` +
      `<button class="lee-btn" data-take="theirs">take theirs</button>` +
      `<button class="lee-btn" data-take="both">both</button></span>` +
      `<button class="lee-btn" data-base-toggle>show base</button></div>` +
      `<div class="lee-merge3-panes">${pane('base', 'base', 'common ancestor')}` +
      `${pane('ours', 'ours', 'this branch')}` +
      `${pane('result', 'result', 'editable')}` +
      `${pane('theirs', 'theirs', 'incoming')}</div>` +
      `<div class="lee-merge3-foot"><span class="lee-dim" data-state></span>` +
      `<button class="lee-btn go" data-resolve>resolve &amp; stage</button></div></div>`,
      null, () => teardown(), {className: 'lee-modal-merge3', storageKey: 'git-conflict'});

    const views = {};
    const editorFor = key => m.querySelector(`[data-pane="${key}"] [data-editor]`);
    const teardown = () => Object.values(views).forEach(v => { try { LeeCM.destroy(v); } catch {} });
    let live = original, active = 0;

    const marks = (ranges, current) => ranges.map((r, i) =>
      ({...r, kind: i === current ? 'conflict-active' : 'conflict'}));

    for (const key of ['base', 'ours', 'theirs']) {
      const {text, ranges} = conflictSide(original, key);
      views[key] = LeeCM.create(editorFor(key), {
        doc: text, lang, readOnly: true, lineNums: true, settings: lee.editorPrefs});
      views[key]._ranges = ranges;
      LeeCM.setChangedLines(views[key], marks(ranges, 0));
    }
    // `onChange` runs inside CodeMirror's own update, where dispatching again is not allowed,
    // and `refresh` dispatches marks -- hence the deferral. `programmatic` is why a button's own
    // `setDoc` does not come back round here and refresh a second time from stale text.
    let programmatic = false;
    views.result = LeeCM.create(editorFor('result'), {
      doc: d.worktree || '', lang, lineNums: true, settings: lee.editorPrefs,
      onChange: text => { if (!programmatic) setTimeout(() => refresh(text, false), 0); }});

    // Which of the original blocks a remaining one is, matched on its contested text. Indices
    // cannot be used: resolving the second of three leaves two, and the sides still show three.
    // Two identical conflicts in one file align to the first of them, which is harmless.
    const originalIndex = block => original.blocks.findIndex(b =>
      b.ours.join('\n') === block.ours.join('\n') && b.theirs.join('\n') === block.theirs.join('\n'));

    // The side panes are read-only and CodeMirror only builds the lines it is showing, so
    // there is no element to scroll to for a conflict that is off screen. Proportional
    // scrolling gets there regardless, and lands close enough to read.
    const align = () => {
      const block = live.blocks[active];
      const index = block ? originalIndex(block) : -1;
      for (const key of ['base', 'ours', 'theirs']) {
        const view = views[key], range = index >= 0 ? view._ranges[index] : null;
        LeeCM.setChangedLines(view, marks(view._ranges, index));
        const scroller = view.dom.querySelector('.cm-scroller');
        if (!range || !scroller) continue;
        const total = Math.max(1, LeeCM.lineCount(view));
        scroller.scrollTop = Math.max(0, (range.from - 1) / total * scroller.scrollHeight
                                         - scroller.clientHeight / 3);
      }
    };

    const refresh = (text, move = true) => {
      live = scanConflicts(text ?? LeeCM.getDoc(views.result));
      const total = live.blocks.length;
      active = Math.max(0, Math.min(active, total - 1));
      const done = original.blocks.length - total;
      m.querySelector('[data-count]').textContent = total
        ? `conflict ${active + 1} of ${total}` : 'no conflicts left';
      m.querySelector('[data-state]').textContent = total
        ? `${done} of ${original.blocks.length} resolved`
        : `all ${original.blocks.length} resolved — staging marks this file merged`;
      m.querySelectorAll('[data-take],[data-nav]').forEach(b => b.disabled = !total);
      m.querySelector('[data-resolve]').classList.toggle('go', !total);
      LeeCM.setChangedLines(views.result, marks(
        live.blocks.map(b => ({from: b.start + 1, to: b.end + 1})), active));
      if (move) align();
    };

    const jumpTo = index => {
      const total = live.blocks.length;
      if (!total) return;
      active = (index + total) % total;
      const block = live.blocks[active];
      const at = live.lines.slice(0, block.start).reduce((n, l) => n + l.length + 1, 0);
      refresh(null, true);
      LeeCM.setSelection(views.result, at, at);
    };

    const take = which => {
      const block = live.blocks[active];
      if (!block) return;
      const lines = which === 'both' ? [...block.ours, ...block.theirs] : block[which];
      const next = replaceConflict(live, active, lines);
      if (next == null) return;
      programmatic = true;
      try { LeeCM.setDoc(views.result, next); } finally { programmatic = false; }
      refresh(next, true);
      if (live.blocks.length) jumpTo(Math.min(active, live.blocks.length - 1));
    };

    m.querySelectorAll('[data-take]').forEach(b => b.onclick = () => take(b.dataset.take));
    m.querySelector('[data-nav="prev"]').onclick = () => jumpTo(active - 1);
    m.querySelector('[data-nav="next"]').onclick = () => jumpTo(active + 1);
    m.querySelector('[data-base-toggle]').onclick = e => {
      const section = m.querySelector('[data-pane="base"]');
      section.hidden = !section.hidden;
      e.currentTarget.textContent = section.hidden ? 'show base' : 'hide base';
      if (!section.hidden) align();
    };
    m.querySelector('[data-resolve]').onclick = async () => {
      const content = LeeCM.getDoc(views.result);
      const left = scanConflicts(content).blocks.length;
      if (left && !await confirmDialog('stage an unresolved file',
          `${left} conflict marker block${left === 1 ? '' : 's'} are still in ${path}. Stage it ` +
          `anyway, markers and all?`, 'stage anyway')) return;
      const next = await gitDo('resolve_conflict', {path, choice: 'resolved', content});
      m.remove();
      afterConflictResolved(next, `${path} staged`);
    };
    refresh(d.worktree || '', true);
    jumpTo(0);
  } catch (e) { leeFail('git', 'resolve conflict', e); }
}

// Add/add and delete/modify conflicts have no contested lines to work through -- one side has
// no file at all -- so the only question is which side to keep.
async function showWholeSideConflict(path, d) {
  const side = (label, text, choice) =>
    `<section><header><strong>${label}</strong>` +
    `<button class="lee-btn" data-choice="${choice}">use ${label}</button></header>` +
    `<pre>${esc(text || 'This side does not have this file.')}</pre></section>`;
  const m = modal(
    `<div class="lee-mhead">resolve ${esc(path)}<span class="sub">one side has no file to merge</span></div>` +
    `<div class="lee-git-conflict">${side('ours', d.ours, 'ours')}${side('theirs', d.theirs, 'theirs')}` +
    `<details><summary>common base</summary><pre>${esc(d.base || 'No common base content.')}</pre></details></div>`,
    null, null, {storageKey: 'git-conflict-side'});
  m.querySelectorAll('[data-choice]').forEach(b => b.onclick = async () => {
    const choice = b.dataset.choice;
    if (!await confirmDialog('resolve conflict', `Use ${choice} for ${path} and stage it as resolved?`, 'resolve')) return;
    m.remove();
    afterConflictResolved(await gitDo('resolve_conflict', {path, choice}), `${path} staged`);
  });
}

