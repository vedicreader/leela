/* The change gutter popup: the mark thickens under the pointer, and clicking it shows what the
 * line used to say beside step, revert, copy and commit-only-this.
 *
 * The hunks come from `/git/file`, cut out of a three-context diff so each one is a patch Git can
 * place by its own context. The browser never assembles a patch of its own, because a hand-built
 * hunk with the wrong line numbers is applied silently in the wrong place.
 */
const fileHunks = () => lee.fileGit?.hunks || [];

function hunkAtLine(line) {
  const hunks = fileHunks();
  const inside = hunks.findIndex(h => line >= h.from && line <= h.to);
  if (inside >= 0) return inside;
  // Three context lines can merge two changes into one hunk, so a mark drawn from the exact
  // zero-context ranges can sit just outside the span of the hunk that carries it. The nearest
  // change is the right answer there.
  let best = -1, gap = Infinity;
  hunks.forEach((h, i) => {
    const d = Math.min(Math.abs(line - h.from), Math.abs(line - h.to));
    if (d < gap) { gap = d; best = i; }
  });
  return best;
}

/* Which words of the old line the new one no longer has. A plain LCS over words is enough at one
 * line's length. */
function tokenDiffHtml(before, after) {
  const a = String(before ?? '').match(/\w+|\s+|[^\w\s]/g) || [];
  const b = String(after ?? '').match(/\w+|\s+|[^\w\s]/g) || [];
  if (!a.length) return '';
  if (!b.length) return `<mark>${esc(before)}</mark>`;
  const n = a.length, m = b.length;
  const dp = Array.from({length: n + 1}, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
    dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  let out = '', run = '', i = 0, j = 0;
  const flush = () => { if (run) out += `<mark>${esc(run)}</mark>`; run = ''; };
  while (i < n) {
    if (j < m && a[i] === b[j]) { flush(); out += esc(a[i]); i++; j++; }
    else if (j < m && dp[i + 1][j] < dp[i][j + 1]) j++;
    else run += a[i++];
  }
  flush();
  return out;
}

function closeChangePopup() {
  const pop = $('.lee-change-pop');
  if (!pop) return;
  pop._leeOff?.(); pop.remove();
}

/* The mark widens only while the pointer is on it. 12px is the editor bundle's own click target
 * for a change mark, and the two numbers must agree. */
function armChangeGutter(host) {
  if (!host || host._leeGutterArmed) return;
  host._leeGutterArmed = true;
  let hot = null;
  const cool = () => { hot?.classList.remove('lee-change-hot'); hot = null; };
  host.addEventListener('mousemove', e => {
    const line = e.target.closest?.('.cm-lee-change');
    if (!line || e.clientX > line.getBoundingClientRect().left + 12) return cool();
    if (line === hot) return;
    cool(); hot = line; line.classList.add('lee-change-hot');
  });
  host.addEventListener('mouseleave', cool);
}

function changePopupBody(h) {
  if (!h.old) return '<div class="lee-change-new">These lines are new — there is no committed version of them.</div>';
  const old = h.old.replace(/\n$/, '').split('\n'), now = (h.new || '').replace(/\n$/, '').split('\n');
  return `<pre class="lee-change-old">${old.map((l, k) => tokenDiffHtml(l, now[k])).join('\n')}</pre>`;
}

function showChangePopup(path, line) {
  closeChangePopup();
  const hunks = fileHunks(), at = hunkAtLine(line);
  // An untracked file has no committed version, so the whole-file diff is the honest answer.
  if (at < 0) return showGitFileDiff(path, lee.fileGit?.diff || '', line);
  const h = hunks[at], name = String(path || '').split('/').pop();
  const pop = document.createElement('div');
  pop.className = 'lee-change-pop'; pop.setAttribute('role', 'dialog');
  pop.setAttribute('aria-label', `change ${at + 1} of ${hunks.length} in ${name}, line ${h.from}`);
  pop.innerHTML =
    `<div class="lee-change-tools">` +
    `<button class="lee-change-icon" data-act="prev" title="previous change" aria-label="previous change">↑</button>` +
    `<button class="lee-change-icon" data-act="next" title="next change" aria-label="next change">↓</button>` +
    `<button class="lee-change-icon" data-act="revert" title="revert this change" aria-label="revert this change">⟲</button>` +
    `<button class="lee-change-icon" data-act="diff" title="show this file's whole diff" aria-label="show diff">◫</button>` +
    `<button class="lee-change-icon" data-act="copy" title="copy the previous version" aria-label="copy the previous version">⧉</button>` +
    `<span class="lee-change-count">${at + 1} / ${hunks.length}</span>` +
    `<input class="lee-input lee-change-msg" placeholder="Commit this change" aria-label="commit message for this change">` +
    `<button class="lee-btn go" data-act="commit">commit</button></div>` + changePopupBody(h);
  document.body.appendChild(pop);
  const anchor = $(`#filecm .cm-lee-change[data-change-line="${h.from}"]`) ||
                 $(`#filecm .cm-lee-change[data-change-line="${line}"]`) || $('#filecm');
  const rect = anchor.getBoundingClientRect(), size = pop.getBoundingClientRect();
  pop.style.left = Math.max(4, Math.min(rect.left, innerWidth - size.width - 4)) + 'px';
  pop.style.top = Math.max(4, Math.min(rect.bottom + 4, innerHeight - size.height - 4)) + 'px';

  const away = e => { if (!pop.contains(e.target)) closeChangePopup(); };
  const key = e => { if (e.key === 'Escape') { e.stopPropagation(); closeChangePopup(); } };
  // Deferred by a tick: the click that opened this popup is still on its way up.
  setTimeout(() => document.addEventListener('mousedown', away), 0);
  document.addEventListener('keydown', key, true);
  pop._leeOff = () => {
    document.removeEventListener('mousedown', away);
    document.removeEventListener('keydown', key, true);
  };

  pop.addEventListener('click', e => {
    const act = e.target.closest('[data-act]')?.dataset.act;
    if (!act) return;
    if (act === 'prev' || act === 'next') {
      const next = hunks[(at + (act === 'next' ? 1 : hunks.length - 1)) % hunks.length];
      jumpToLine(next.from);
      // The line has to be laid out before it can be measured, and the editor only renders the
      // lines it has scrolled to.
      return requestAnimationFrame(() => showChangePopup(path, next.from));
    }
    if (act === 'diff') { closeChangePopup(); return showGitFileDiff(path, lee.fileGit?.diff || '', h.from); }
    if (act === 'copy') return copyChangeHunk(h);
    if (act === 'revert') return revertChangeHunk(path, h);
    if (act === 'commit') return commitChangeHunk(path, h, pop.querySelector('.lee-change-msg').value);
  });
  return pop;
}

async function copyChangeHunk(h) {
  try { await navigator.clipboard.writeText(h.old || h.new || ''); status('previous version copied', 'ok'); }
  catch (_) { status('clipboard access failed', 'err'); }
}

/* Git reads and writes the file on disk, and this editor may hold a newer version of it. Both
 * directions are silent data loss: the revert overwrites the unsaved edit, or the next autosave
 * writes the reverted lines back. So the file is saved first and the buffer reloaded after. */
async function refreshFileChanges(path, fromDisk = false) {
  const v = lee.editors.get('file');
  if (!v) return;
  if (fromDisk) {
    const st = await api('/tab/state?path=' + encodeURIComponent(path)).catch(() => null);
    if (typeof st?.text === 'string') {
      lee.dirtyBuffers.delete(path); lee.buffers.delete(path);
      if (st.text !== LeeCM.getDoc(v)) LeeCM.setDoc(v, st.text);
      $$('.lee-tab').find(x => x.title === path)?.classList.remove('dirty');
    }
  }
  const git = await api('/git/file?path=' + encodeURIComponent(path)).then(noteHl).catch(() => null);
  if (!git) return;
  lee.fileGit = git; LeeCM.setChangedLines(v, git.ranges || []);
}

async function revertChangeHunk(path, h) {
  if ($('.lee-tab.active.dirty') && !await saveTab(true)) return;
  const ok = await confirmDialog('Revert this change?',
    `Lines ${h.from}–${h.to} of ${String(path).split('/').pop()} go back to their committed ` +
    `version. Every other change in the file is left alone.`, 'revert');
  if (!ok) return;
  closeChangePopup();
  // Reverse against the working tree, not the index. This is an edit to the file.
  try { await gitDo('apply_patch', {patch: h.patch, staged: false, reverse: true}); }
  catch (_) { return; }
  await refreshFileChanges(path, true);
}

async function commitChangeHunk(path, h, message) {
  const text = String(message || '').trim();
  if (!text) return status('write a message to commit this change', 'err');
  if ($('.lee-tab.active.dirty') && !await saveTab(true)) return;
  /* Git can only commit what is in the index, so this stages the hunk and commits, and anything
   * already staged rides along. The choice is put to whoever is looking at it rather than
   * quietly widening the commit or quietly unstaging deliberate work. */
  const snapshot = gitUI.snapshot || await gitInfoOrNull();
  const staged = (snapshot?.changes || []).filter(c => c.staged && c.path !== path).map(c => c.path);
  if (staged.length) {
    const shown = staged.slice(0, 3).join(', ') + (staged.length > 3 ? `, and ${staged.length - 3} more` : '');
    const ok = await confirmDialog('Something else is already staged',
      `${shown} ${staged.length === 1 ? 'is' : 'are'} staged and would be committed together with ` +
      `this change. Unstage first to commit this change on its own.`, 'commit anyway');
    if (!ok) return;
  }
  closeChangePopup();
  try {
    await gitDo('apply_patch', {patch: h.patch, staged: true, reverse: false});
    await gitDo('commit', {message: text});
  } catch (_) { return; }
  await refreshFileChanges(path);
}

