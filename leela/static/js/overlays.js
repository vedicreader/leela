function modalViewport() {
  const v = window.visualViewport;
  return {left: v?.offsetLeft || 0, top: v?.offsetTop || 0, width: v?.width || innerWidth, height: v?.height || innerHeight};
}
function fitModal(m) {
  const box = $('.lee-modalbox', m), v = modalViewport(), gap = 8; if (!box) return;
  box.style.maxWidth = Math.max(0, v.width - gap * 2) + 'px';
  // Below where the box starts, not the whole viewport: a box 5vh down with a full-height cap ran off the bottom.
  const top = m.classList.contains('lee-modal-moved') ? gap : Math.max(gap, box.getBoundingClientRect().top - v.top);
  box.style.maxHeight = Math.max(0, v.height - top - gap) + 'px';
  if (!m.classList.contains('lee-modal-moved')) return;
  const r = box.getBoundingClientRect();
  box.style.left = Math.max(v.left, Math.min(r.left, v.left + v.width - Math.min(r.width, v.width) - gap)) + 'px';
  box.style.top = Math.max(v.top, Math.min(r.top, v.top + v.height - Math.min(r.height, v.height) - gap)) + 'px';
}
function modal(inner, onKey, onClose, options = {}) {
  const previousFocus = document.activeElement;
  const m = document.createElement('div');
  m.className = `lee-modal${options.className ? ' ' + options.className : ''}`;
  m.innerHTML = `<div class="lee-modalbox lee-modal-resizable" role="dialog" aria-modal="true" tabindex="-1">` +
                `<div class="lee-modal-grip" aria-hidden="true"></div>${inner}` +
                `<button class="lee-modal-expand" type="button" aria-label="expand dialog" title="expand dialog">↗</button>` +
                `<button class="lee-modal-close" type="button" aria-label="close dialog">×</button></div>`;
  const box = m.querySelector('.lee-modalbox');
  const heading = box.querySelector('.lee-mhead');
  if (heading) box.setAttribute('aria-label', heading.textContent.trim());
  const storageKey = options.storageKey ? `lee-modal-size:${options.storageKey}` : '';
  const viewport = modalViewport();
  if (storageKey) {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || 'null');
      if (saved?.width) box.style.width = Math.min(saved.width, viewport.width - 16) + 'px';
      if (saved?.height) box.style.height = Math.min(saved.height, viewport.height - 16) + 'px';
      if (Number.isFinite(saved?.left) && Number.isFinite(saved?.top)) {
        m.classList.add('lee-modal-moved');
        box.style.left = Math.max(viewport.left, Math.min(saved.left, viewport.left + viewport.width - 80)) + 'px';
        box.style.top = Math.max(viewport.top, Math.min(saved.top, viewport.top + viewport.height - 48)) + 'px';
      }
    } catch (_) {}
  }
  // Result rows are true keyboard targets, not divs that only a mouse can activate.
  const prepareRows = root => $$('.lee-mrow', root).forEach(row => {
    row.tabIndex = row.dataset.off ? -1 : 0; row.setAttribute('role', 'option');
    row.setAttribute('aria-selected', String(row.classList.contains('sel')));
    const list = row.closest('.lee-modallist'); if (list && !list.hasAttribute('role')) list.setAttribute('role', 'listbox');
  });
  prepareRows(m);
  const observer = new MutationObserver(records => records.forEach(r => r.addedNodes.forEach(n => {
    if (n instanceof Element) { if (n.matches('.lee-mrow')) prepareRows(n.parentElement); else prepareRows(n); }
  })));
  observer.observe(box, {childList: true, subtree: true});
  let closed = false;
  const onViewport = () => fitModal(m);
  const nativeRemove = m.remove.bind(m);
  const focusables = () => $$('button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [href], [tabindex]:not([tabindex="-1"])', box)
    .filter(el => !el.hidden && el.getClientRects().length);
  const requestClose = async () => {
    if (m.beforeClose && !await m.beforeClose()) return false;
    m.remove(); return true;
  };
  m.requestClose = requestClose;
  const key = (e) => {
    // Nested dialogs form a stack, and only the top one owns keys, or one Escape closes every
    // layer at once.
    if ($$('.lee-modal').at(-1) !== m) return;
    // The dialog's own keys come first. A dialog that means something by Tab says so by preventing
    // the default; the trap below then never sees it. Handling Tab here first made that branch
    // unreachable, and a dialog that bound it looked like it had no binding at all.
    if (onKey) onKey(e, m);
    if (e.defaultPrevented) return;
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); requestClose(); return; }
    if (e.key === 'Tab') {
      const items = focusables(); if (!items.length) { e.preventDefault(); box.focus(); return; }
      const at = items.indexOf(document.activeElement);
      if (e.shiftKey && at <= 0) { e.preventDefault(); items.at(-1).focus(); }
      else if (!e.shiftKey && (at < 0 || at === items.length - 1)) { e.preventDefault(); items[0].focus(); }
      return;
    }
    const rows = $$('.lee-mrow:not([data-off])', m), at = rows.indexOf(document.activeElement);
    if (rows.length && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      e.preventDefault(); e.stopPropagation();
      const step = e.key === 'ArrowDown' ? 1 : -1;
      const next = rows[(Math.max(0, at) + step + rows.length) % rows.length];
      rows.forEach(r => { const selected = r === next; r.classList.toggle('sel', selected); r.setAttribute('aria-selected', String(selected)); });
      next.focus(); next.scrollIntoView({block: 'nearest'});
    } else if (at >= 0 && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault(); e.stopPropagation(); rows[at].click();
    }
  };
  m.remove = () => {
    if (closed) return;
    closed = true; observer.disconnect(); document.removeEventListener('keydown', key, true);
    window.removeEventListener('resize', onViewport); window.visualViewport?.removeEventListener('resize', onViewport); nativeRemove();
    if (!$$('.lee-modal').length) { document.body.style.overflow = document.body.dataset.leeModalOverflow || ''; delete document.body.dataset.leeModalOverflow; }
    if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus({preventScroll: true});
    if (onClose) onClose();
  };
  const dragHandle = heading || m.querySelector('.lee-modal-grip');
  let drag = null;
  dragHandle.addEventListener('pointerdown', e => {
    if (e.button !== 0 || e.target.closest('button, input, textarea, select, a') || m.classList.contains('lee-modal-expanded')) return;
    const r = box.getBoundingClientRect();
    m.classList.add('lee-modal-moved', 'lee-modal-dragging');
    box.style.left = r.left + 'px'; box.style.top = r.top + 'px';
    drag = {x: e.clientX, y: e.clientY, left: r.left, top: r.top, dx: 0, dy: 0};
    dragHandle.setPointerCapture(e.pointerId); e.preventDefault();
  });
  dragHandle.addEventListener('pointermove', e => {
    if (!drag) return;
    const r = box.getBoundingClientRect(), v = modalViewport(), width = r.width, height = r.height;
    const maxX = v.left + Math.max(0, v.width - width) - drag.left;
    const maxY = v.top + Math.max(0, v.height - height) - drag.top;
    drag.dx = Math.max(v.left - drag.left, Math.min(e.clientX - drag.x, maxX));
    drag.dy = Math.max(v.top - drag.top, Math.min(e.clientY - drag.y, maxY));
    box.style.transform = `translate3d(${drag.dx}px, ${drag.dy}px, 0)`;
    e.preventDefault();
  });
  const endDrag = e => {
    if (!drag) return;
    const v = modalViewport();
    box.style.left = Math.max(v.left, drag.left + drag.dx) + 'px'; box.style.top = Math.max(v.top, drag.top + drag.dy) + 'px';
    box.style.transform = ''; drag = null; m.classList.remove('lee-modal-dragging');
    try { dragHandle.releasePointerCapture(e.pointerId); } catch (_) {}
  };
  dragHandle.addEventListener('pointerup', endDrag); dragHandle.addEventListener('pointercancel', endDrag);
  const toggleExpanded = () => {
    const expanding = !m.classList.contains('lee-modal-expanded');
    if (expanding) {
      box._leeRestorePosition = m.classList.contains('lee-modal-moved')
        ? {left: box.style.left, top: box.style.top} : null;
      m.classList.remove('lee-modal-moved'); box.style.left = box.style.top = box.style.transform = '';
      m.classList.add('lee-modal-expanded');
    } else {
      m.classList.remove('lee-modal-expanded');
      if (box._leeRestorePosition) {
        m.classList.add('lee-modal-moved'); box.style.left = box._leeRestorePosition.left; box.style.top = box._leeRestorePosition.top;
      }
    }
    const expanded = m.classList.contains('lee-modal-expanded');
    m.querySelector('.lee-modal-expand').textContent = expanded ? '↙' : '↗';
    m.querySelector('.lee-modal-expand').setAttribute('aria-label', expanded ? 'restore dialog' : 'expand dialog');
  };
  m.querySelector('.lee-modal-expand').onclick = toggleExpanded;
  heading?.addEventListener('dblclick', e => { if (!e.target.closest('button, input, select')) toggleExpanded(); });
  if (storageKey && 'ResizeObserver' in window) {
    const sizeObserver = new ResizeObserver(() => {
      if (m.classList.contains('lee-modal-expanded')) return;
      const r = box.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) localStorage.setItem(storageKey, JSON.stringify({width: Math.round(r.width), height: Math.round(r.height), left: Math.round(r.left), top: Math.round(r.top)}));
    });
    sizeObserver.observe(box);
    const oldRemove = m.remove;
    m.remove = () => { sizeObserver.disconnect(); oldRemove(); };
  }
  m.querySelector('.lee-modal-close').onclick = requestClose;
  m.addEventListener('mousedown', e => { if (e.target === m) requestClose(); });
  document.addEventListener('keydown', key, true);
  window.addEventListener('resize', onViewport); window.visualViewport?.addEventListener('resize', onViewport);
  if (!$$('.lee-modal').length) { document.body.dataset.leeModalOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden'; }
  document.body.appendChild(m);
  requestAnimationFrame(() => {
    fitModal(m);
    const target = box.querySelector('[autofocus]') || box.querySelector('.lee-mrow.sel:not([data-off])') ||
                   box.querySelector('.lee-mrow:not([data-off])') || box.querySelector('input, textarea, select') ||
                   box.querySelector('button:not(.lee-modal-close):not([disabled])') || box;
    target.focus({preventScroll: true});
    if (target.classList.contains('lee-mrow')) target.scrollIntoView({block: 'nearest'});
  });
  return m;
}

function inputDialog(title, label, value = '', placeholder = '') {
  return new Promise(resolve => {
    let settled = false;
    const done = value => { if (settled) return; settled = true; m.remove(); resolve(value); };
    const m = modal(
      `<form class="lee-dialogform"><div class="lee-mhead">${esc(title)}</div>` +
      `<label class="lee-fieldlabel">${esc(label)}<input class="lee-input" id="dialoginput" ` +
      `placeholder="${esc(placeholder)}" autocomplete="off"></label>` +
      `<div class="lee-mfoot"><button class="lee-btn go" type="submit">confirm</button>` +
      `<button class="lee-btn" type="button" id="dialogcancel">cancel</button></div></form>`,
      null, () => { if (!settled) { settled = true; resolve(null); } });
    const input = m.querySelector('#dialoginput'); input.value = value;
    m.querySelector('form').onsubmit = e => { e.preventDefault(); done(input.value.trim()); };
    m.querySelector('#dialogcancel').onclick = () => done(null);
    setTimeout(() => { input.focus(); input.select(); }, 0);
  });
}

function textDialog(title, label, value = '') {
  return new Promise(resolve => {
    let settled = false;
    const done = value => { if (settled) return; settled = true; m.remove(); resolve(value); };
    const m = modal(
      `<form class="lee-dialogform"><div class="lee-mhead">${esc(title)}</div>` +
      `<label class="lee-fieldlabel">${esc(label)}<textarea class="lee-keyedit" id="dialogtext" rows="12" spellcheck="false"></textarea></label>` +
      `<div class="lee-mfoot"><button class="lee-btn go" type="submit">retry</button>` +
      `<button class="lee-btn" type="button" id="dialogcancel">cancel</button></div></form>`,
      null, () => { if (!settled) { settled = true; resolve(null); } });
    const input = m.querySelector('#dialogtext'); input.value = value;
    m.querySelector('form').onsubmit = e => { e.preventDefault(); done(input.value.trim()); };
    m.querySelector('#dialogcancel').onclick = () => done(null);
    setTimeout(() => { input.focus(); input.select(); }, 0);
  });
}

/* `alt` offers a second way to say yes. It resolves `'alt'`, and cancel stays falsy so every
   caller that asked a yes/no question is unchanged. */
function confirmDialog(title, detail, action = 'confirm', alt = '') {
  return new Promise(resolve => {
    let settled = false;
    const done = value => { if (settled) return; settled = true; m.remove(); resolve(value); };
    const second = alt ? `<button class="lee-btn" id="dialogalt">${esc(alt)}</button>` : '';
    const m = modal(`<div class="lee-mhead">${esc(title)}</div><div class="lee-dialogcopy">${esc(detail)}</div>` +
      `<div class="lee-mfoot"><button class="lee-btn warn" id="dialogyes">${esc(action)}</button>${second}` +
      `<button class="lee-btn" id="dialogno" autofocus>cancel</button></div>`, null,
      () => { if (!settled) { settled = true; resolve(false); } });
    m.querySelector('#dialogyes').onclick = () => done(true);
    m.querySelector('#dialogalt')?.addEventListener('click', () => done('alt'));
    m.querySelector('#dialogno').onclick = () => done(false);
  });
}

/* One menu renderer for every contextual surface. Labels and effective chords come from
 * `leela.blocks.keys.menus` and `leela.core.keys`. The browser positions rows and dispatches. */
function closeMenu() {
  $('.lee-ctxmenu')?.remove();
  if (lee.menuAnchor?.hasAttribute('aria-haspopup')) lee.menuAnchor.setAttribute('aria-expanded', 'false');
  lee.menuAnchor = null;
}
function openMenu(surface, x, y) {
  closeMenu();
  lee.menuSurface = surface;   // an action can act on what was right-clicked, not on the focus
  const rows = lee.menus?.[surface] || [];
  if (!rows.length) return;
  const menu = document.createElement('div');
  menu.className = 'lee-ctxmenu'; menu.setAttribute('role', 'menu'); menu.tabIndex = -1;
  menu.innerHTML = rows.map(r => r.separator ? '<div class="lee-menusep" role="separator"></div>' :
    `<button class="lee-menuitem ${esc(r.kind)}" role="${r.check ? 'menuitemcheckbox' : 'menuitem'}"` +
    `${r.check ? ` aria-checked="${!!lee.menuChecks?.[r.action]?.()}"` : ''}${lee.menuOff?.[r.action]?.() ? ' disabled' : ''} data-action="${esc(r.action)}">` +
    `<span>${esc(sentence(r.label))}</span>${r.chord && r.chord !== '–' ? `<kbd>${esc(displayChord(r.chord))}</kbd>` : ''}</button>`).join('');
  document.body.appendChild(menu);
  const rect = menu.getBoundingClientRect();
  menu.style.left = Math.max(4, Math.min(x, innerWidth - rect.width - 4)) + 'px';
  menu.style.top = Math.max(4, Math.min(y, innerHeight - rect.height - 4)) + 'px';
  menu.onclick = e => {
    const item = e.target.closest('.lee-menuitem'); if (!item || item.disabled) return;
    if (item.getAttribute('role') !== 'menuitemcheckbox') { closeMenu(); return leeAct(item.dataset.action); }
    const sync = () => item.setAttribute('aria-checked', String(!!lee.menuChecks?.[item.dataset.action]?.()));
    Promise.resolve(leeAct(item.dataset.action)).then(sync, sync); sync();
  };
  menu.onkeydown = e => {
    const items = $$('.lee-menuitem:not(:disabled)', menu), at = items.indexOf(document.activeElement);
    if (e.key === 'Escape') { e.preventDefault(); const back = lee.menuAnchor; closeMenu(); back?.focus(); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); items[(at + 1 + items.length) % items.length]?.focus(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); items[(at - 1 + items.length) % items.length]?.focus(); }
    else if (e.key === 'Home') { e.preventDefault(); items[0]?.focus(); }
    else if (e.key === 'End') { e.preventDefault(); items.at(-1)?.focus(); }
  };
  menu.focus();
}
function leeMenuAt(surface, anchor) {
  const r = anchor.getBoundingClientRect(); openMenu(surface, r.right - 4, r.bottom + 3);
  if (!$('.lee-ctxmenu')) return;
  lee.menuAnchor = anchor; if (anchor.hasAttribute('aria-haspopup')) anchor.setAttribute('aria-expanded', 'true');
}
window.leeMenuAt = leeMenuAt;

function openChromeMenu(anchor, rows) {
  closeMenu();
  const menu = document.createElement('div'); menu.className = 'lee-ctxmenu'; menu.setAttribute('role', 'menu');
  menu.innerHTML = rows.map((r, i) => r.separator ? '<div class="lee-menusep" role="separator"></div>' :
    `<button class="lee-menuitem${r.warn ? ' warn' : ''}" role="menuitem" data-i="${i}" ${r.disabled ? 'disabled' : ''}>` +
    `<span>${esc(sentence(r.label))}</span>${r.detail ? `<small title="${esc(r.detail)}">${esc(r.detail)}</small>` : ''}</button>`).join('');
  document.body.appendChild(menu);
  const a = anchor.getBoundingClientRect(), rect = menu.getBoundingClientRect();
  menu.style.left = Math.max(4, Math.min(a.left, innerWidth - rect.width - 4)) + 'px';
  menu.style.top = Math.max(4, Math.min(a.bottom + 3, innerHeight - rect.height - 4)) + 'px';
  menu.onclick = e => { const b = e.target.closest('[data-i]'); if (!b || b.disabled) return; closeMenu(); rows[+b.dataset.i].run?.(); };
  menu.tabIndex = -1; menu.focus();
}

// Choosing a folder is choosing a project: source control, releases, deploys and the branch pill
// all follow it. Selecting the folder in the tree is not choosing it; this route is.
async function activateRoot(path) {
  try { await post('/workspace/activate', {path}); }
  catch (e) { return status(e.message || String(e), 'err'); }
  leeLeft('files');
  const node = $$('.lee-root').find(n => n.dataset.path === path);
  if (node) { selectTreeNode(node); await loadTreeDir(node); node.scrollIntoView({block: 'nearest'}); }
  gitUI.repo = '';                  // the panels follow the workspace again, not a pinned repo
  refreshProjectPills();
  projectChanged();
  status(`project · ${path.split('/').pop() || path}`);
}
window.leeActivateRoot = activateRoot;

async function leeWorkspaceMenu(anchor) {
  const d = await api('/workspace/info');
  const sites = d.workspaces || [];
  const home = p => lee.home && (p === lee.home || String(p).startsWith(lee.home + '/')) ? '~' + String(p).slice(lee.home.length) : p;
  const rows = sites.map(site => ({label: site.name, detail: home(site.root), run: () => {
    if (site.url && site.url !== location.href) location.href = site.url;
  }}));
  if (sites.length && (d.roots || []).length) rows.push({separator: true});
  rows.push(...(d.roots || []).map(root => ({label: sites.length ? `Folder: ${root.name}` : root.name,
    detail: home(root.path), run: () => activateRoot(root.path)})));
  if (rows.length) rows.push({separator: true});
  rows.push({label: 'Add folder…', detail: 'to this workspace', run: addRoot});
  openChromeMenu(anchor, rows);
}
window.leeWorkspaceMenu = leeWorkspaceMenu;

/* The branch pill's own popup is `branchbar.js`. It is a searchable list rather than a menu, so it
   does not fit `openChromeMenu`. */

async function operationHistory() {
  const d = await api('/history/operations');
  const m = modal(`<div class="lee-mhead">workspace history<span class="sub">saved file checkpoints · newest first</span></div>` +
    // An empty `data-history` still matches `[data-history]`, so the attribute is omitted rather
    // than blanked. A spent operation must not be clickable at all.
    `<div class="lee-modallist">${(d.operations || []).map(op => `<button class="lee-mrow" data-op="${esc(op.id)}"${op.reversible ? ' data-history="undo"' : op.redoable ? ' data-history="redo"' : ' data-off="1"'}>` +
      `<strong>${esc(op.label)}</strong><span class="sub">${op.redoable ? 'undone · redo available · ' : ''}${new Date(op.at * 1000).toLocaleString()} · ${esc((op.paths || []).join(', '))}</span></button>`).join('') || '<div class="lee-dim">No saved operations yet.</div>'}</div>` +
    `<div class="lee-mfoot"><span class="lee-dim">Undo and redo refuse files changed after the checkpoint.</span></div>`);
  $$('[data-history]', m).forEach(row => row.onclick = async () => {
    const redo = row.dataset.history === 'redo', verb = redo ? 'Redo' : 'Undo';
    if (!await confirmDialog(`${verb} workspace operation`, `${verb} ${row.textContent.trim()}?`, verb.toLowerCase())) return;
    try { const r = await post('/history/' + (redo ? 'redo' : 'undo'), {id: row.dataset.op}); m.remove();
      await afterHistory(r.operation, `workspace operation ${redo ? 'redone' : 'undone'}`, !redo);
    } catch (e) { status(e.message || String(e), 'err'); }
  });
}

function leeToolsMenu(anchor) {
  openChromeMenu(anchor, [
    {label: 'Command palette', detail: displayChord('mod+shift+p'), run: () => leeAct('palette')},
    {label: 'Recent files', detail: displayChord('mod+e'), run: () => leeAct('recent_tabs')},
    {separator: true},
    {label: 'The vault…', detail: 'browse, search, and put things in', run: () => leeVaultWorkbench()},
    {label: 'Research workspace…', run: () => leeAct('research')},
    {label: 'Read webpage…', run: () => leeAct('read_url')},
    {label: 'Browse a page…', detail: displayChord('alt+shift+o'), run: () => leeAct('browse_url')},
    {label: 'Pages open in the browser…', run: () => leeAct('browse_tabs')},
    {label: 'Kernel and interpreter…', run: () => leeAct('pick_kernel')},
    {label: 'Working directory…', run: leeCwd},
    {label: 'nbdev prepare…', detail: 'uv + settings.ini', run: leeNbdevPrepare},
    {label: 'fastship…', detail: 'releases for a package that is not nbdev', run: leeFastship},
    {label: 'Models and updates…', detail: 'set one up, or pull a newer backend', run: () => leeSetupModal()},
    {separator: true},
    {label: 'Settings…', detail: displayChord(shownChord(lee.keys.find(k => k.action === 'settings')) || 'mod+,'), run: editorSettings},
    {label: 'Workspace history…', detail: 'conflict-safe undo', run: operationHistory},
    {label: 'Inline completions…', detail: 'what you asked, and what you kept', run: () => showCompletions()},
    {label: 'Keybindings…', run: () => leeAct('edit_keys')},
    {label: 'Terminal', run: () => leeAct('terminal')},
  ]);
}
window.leeToolsMenu = leeToolsMenu;

function leeEditorMenu(anchor) {
  const rows = [
    {label: 'Run selection', detail: displayChord(shownChord(lee.keys.find(k => k.action === 'run_selection')) || ''), run: () => leeAct('run_selection')},
    {label: 'Run all cells', detail: displayChord(shownChord(lee.keys.find(k => k.action === 'run_all')) || ''), run: () => leeAct('run_all')},
    {label: 'Restart and run all', run: () => leeAct('restart_run_all')},
    {separator: true},
    {label: 'Save', detail: displayChord(shownChord(lee.keys.find(k => k.action === 'save')) || ''), run: () => leeAct('save')},
    {label: 'Show unsaved changes', run: () => leeAct('show_diff')},
    {label: 'Rename symbol…', run: () => leeAct('rename_symbol')},
    {label: 'Replace in workspace…', run: () => leeAct('replace_workspace')},
    {separator: true},
    {label: 'Insert cell below', run: () => leeAct('cell_below')},
    {label: 'Change cell type', run: () => leeAct('cell_type')},
    {label: 'Clear all outputs', run: () => leeAct('clear_all_outputs')},
    {separator: true},
    {label: 'All commands…', detail: displayChord(shownChord(lee.keys.find(k => k.action === 'palette')) || ''), run: () => leeAct('palette')},
  ];
  openChromeMenu(anchor, rows);
}
window.leeEditorMenu = leeEditorMenu;

function leeDebugMenu(anchor) {
  openChromeMenu(anchor, [
    {label:'Debug current Python file',detail:'debugpy',disabled:lee.kind!=='text'||curLang()!=='python',run:()=>startDirectDebug({name:lee.path?.split('/').pop()||'Python',program:lee.path,debug:true})},
    {label:'Run or debug configuration…',run:()=>leeAct('run_app')},
    {label:'Edit configurations…',run:editRuns},
    {separator:true},
    {label:'Continue',disabled:!lee.debugState,run:()=>leeDebugControl('continue')},
    {label:'Step over',disabled:!lee.debugState,run:()=>leeDebugControl('next')},
    {label:'Step into',disabled:!lee.debugState,run:()=>leeDebugControl('stepIn')},
    {label:'Step out',disabled:!lee.debugState,run:()=>leeDebugControl('stepOut')},
    {label:'Stop debugger',warn:true,disabled:!lee.debugCell&&!lee.directDebug,run:leeDebugStop},
    {separator:true},
    {label:'Interrupt kernel',warn:true,run:()=>leeAct('interrupt')},
    {label:'Restart kernel',warn:true,run:()=>leeAct('restart')},
  ]);
}
window.leeDebugMenu = leeDebugMenu;

document.addEventListener('pointerdown', e => { if (!e.target.closest('.lee-ctxmenu, .lee-more, [aria-haspopup="menu"]')) closeMenu(); }, true);
window.addEventListener('blur', closeMenu);
window.addEventListener('resize', () => { closeMenu(); layoutTabs(); });
window.addEventListener('scroll', e => { if (!e.target.closest?.('.lee-ctxmenu, #agentlog')) closeMenu(); }, true);

function showHelp() {
  const scopes = Object.entries(lee.help).sort(([a], [b]) =>
    a === lee.scope ? -1 : b === lee.scope ? 1 : a === 'global' ? -1 : b === 'global' ? 1 : 0);
  const body = scopes.map(([scope, rows]) =>
    `<section class="lee-help-scope${scope === lee.scope ? ' active' : ''}"><h4>${esc(scope)}` +
    `${scope === lee.scope ? '<span>current</span>' : ''}</h4>` +
    (scope === 'present' ? '<p class="lee-dim lee-help-note">These keys work only during a presentation. They cannot be rebound. Laser and blank have no button.</p>' : '') +
    (scope === 'editor' ? '<p class="lee-dim lee-help-note">In a notebook, a single letter works only when you do not edit a cell. Press Escape to stop editing. Press D two times to delete a cell. Hold ' + esc(displayChord('alt')) + ' and drag a number in a code cell to scrub it. ' + esc(displayChord('alt+up')) + ' or ' + esc(displayChord('alt+down')) + ' on a number moves it one step. "Nudge the number" and "scrub the number" are in the command palette.</p>' : '') + rows.map(([k, l]) =>
      `<div class="lee-krow"><kbd>${esc(displayChord(k))}</kbd><span>${esc(l)}</span></div>`).join('') + '</section>').join('');
  const m = modal(
    `<div class="lee-mhead">keys<span class="sub">${esc(lee.keyPath || '')}</span></div>` +
    (lee.keyNotes || []).map(n => `<div class="lee-err">${esc(n)}</div>`).join('') +
    `<div class="lee-dim">Every key outside the present section can be rebound. Each of those keys also has a button.</div>` +
    `<div class="lee-help">${body}</div>` +
    `<div class="lee-mfoot"><button class="lee-btn" id="gokeys">edit keybindings</button></div>`);
  m.querySelector('#gokeys').onclick = () => { m.remove(); editKeys(); };
}

