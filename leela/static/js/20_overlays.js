/* ------------------------------------------------------------------ overlays */
function modalViewport() {
  const v = window.visualViewport;
  return {left: v?.offsetLeft || 0, top: v?.offsetTop || 0, width: v?.width || innerWidth, height: v?.height || innerHeight};
}
function fitModal(m) {
  const box = $('.lee-modalbox', m), v = modalViewport(), gap = 8; if (!box) return;
  box.style.maxWidth = Math.max(0, v.width - gap * 2) + 'px';
  box.style.maxHeight = Math.max(0, v.height - gap * 2) + 'px';
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
    // Nested dialogs (for example “change cwd” from the kernel picker) form a stack.
    // Only the top one owns keys; otherwise one Escape closes every layer at once.
    if ($$('.lee-modal').at(-1) !== m) return;
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); requestClose(); return; }
    if (e.key === 'Tab') {
      const items = focusables(); if (!items.length) { e.preventDefault(); box.focus(); return; }
      const at = items.indexOf(document.activeElement);
      if (e.shiftKey && at <= 0) { e.preventDefault(); items.at(-1).focus(); }
      else if (!e.shiftKey && (at < 0 || at === items.length - 1)) { e.preventDefault(); items[0].focus(); }
      return;
    }
    if (onKey) onKey(e, m);
    if (e.defaultPrevented) return;
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

/* `alt` offers a second way to say yes, for a choice with two shapes rather than one. It resolves
   `'alt'`, and cancel stays falsy so every caller that only asked a yes/no question is unchanged. */
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

/* One menu renderer for every contextual surface. Labels and effective chords came from
 * leela.blocks.keys.menus + leela.core.keys; the browser only positions rows and dispatches their action. */
function closeMenu() { $('.lee-ctxmenu')?.remove(); }
function openMenu(surface, x, y) {
  closeMenu();
  lee.menuSurface = surface;   // an action can act on what was right-clicked, not on the focus
  const rows = lee.menus?.[surface] || [];
  if (!rows.length) return;
  const menu = document.createElement('div');
  menu.className = 'lee-ctxmenu'; menu.setAttribute('role', 'menu'); menu.tabIndex = -1;
  menu.innerHTML = rows.map(r => r.separator ? '<div class="lee-menusep" role="separator"></div>' :
    `<button class="lee-menuitem ${esc(r.kind)}" role="menuitem" data-action="${esc(r.action)}">` +
    `<span>${esc(r.label)}</span>${r.chord && r.chord !== '—' ? `<kbd>${esc(displayChord(r.chord))}</kbd>` : ''}</button>`).join('');
  document.body.appendChild(menu);
  const rect = menu.getBoundingClientRect();
  menu.style.left = Math.max(4, Math.min(x, innerWidth - rect.width - 4)) + 'px';
  menu.style.top = Math.max(4, Math.min(y, innerHeight - rect.height - 4)) + 'px';
  menu.onclick = e => { const item = e.target.closest('.lee-menuitem'); if (!item) return; closeMenu(); leeAct(item.dataset.action); };
  menu.onkeydown = e => {
    const items = $$('.lee-menuitem', menu), at = items.indexOf(document.activeElement);
    if (e.key === 'Escape') { e.preventDefault(); closeMenu(); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); items[(at + 1 + items.length) % items.length]?.focus(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); items[(at - 1 + items.length) % items.length]?.focus(); }
    else if (e.key === 'Home') { e.preventDefault(); items[0]?.focus(); }
    else if (e.key === 'End') { e.preventDefault(); items.at(-1)?.focus(); }
  };
  menu.focus();
}
function leeMenuAt(surface, anchor) {
  const r = anchor.getBoundingClientRect(); openMenu(surface, r.right - 4, r.bottom + 3);
}
window.leeMenuAt = leeMenuAt;

function openChromeMenu(anchor, rows) {
  closeMenu();
  const menu = document.createElement('div'); menu.className = 'lee-ctxmenu'; menu.setAttribute('role', 'menu');
  menu.innerHTML = rows.map((r, i) => r.separator ? '<div class="lee-menusep" role="separator"></div>' :
    `<button class="lee-menuitem${r.warn ? ' warn' : ''}" role="menuitem" data-i="${i}" ${r.disabled ? 'disabled' : ''}>` +
    `<span>${esc(r.label)}</span>${r.detail ? `<small>${esc(r.detail)}</small>` : ''}</button>`).join('');
  document.body.appendChild(menu);
  const a = anchor.getBoundingClientRect(), rect = menu.getBoundingClientRect();
  menu.style.left = Math.max(4, Math.min(a.left, innerWidth - rect.width - 4)) + 'px';
  menu.style.top = Math.max(4, Math.min(a.bottom + 3, innerHeight - rect.height - 4)) + 'px';
  menu.onclick = e => { const b = e.target.closest('[data-i]'); if (!b || b.disabled) return; closeMenu(); rows[+b.dataset.i].run?.(); };
  menu.tabIndex = -1; menu.focus();
}

// Choosing a folder is choosing a project: source control, releases, deploys and the branch
// pill all follow it. Selecting the folder in the tree without saying so left every one of
// them describing whichever folder had been opened first.
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
  const rows = sites.map(site => ({label: site.name, detail: site.root, run: () => {
    if (site.url && site.url !== location.href) location.href = site.url;
  }}));
  if (sites.length && (d.roots || []).length) rows.push({separator: true});
  rows.push(...(d.roots || []).map(root => ({label: sites.length ? `Folder: ${root.name}` : root.name,
    detail: root.path, run: () => activateRoot(root.path)})));
  if (rows.length) rows.push({separator: true});
  rows.push({label: 'Add folder…', detail: 'to this workspace', run: addRoot});
  openChromeMenu(anchor, rows);
}
window.leeWorkspaceMenu = leeWorkspaceMenu;

/* The branch pill's own popup is `28_branchbar.js`: it is a searchable list of branches and
   actions rather than a menu, so it does not fit `openChromeMenu`. */

async function operationHistory() {
  const d = await api('/history/operations');
  const m = modal(`<div class="lee-mhead">workspace history<span class="sub">saved file checkpoints · newest first</span></div>` +
    // An empty `data-history` still matches `[data-history]`, so the attribute is omitted
    // rather than blanked: a spent operation must not be clickable at all.
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
    {separator: true},
    {label: 'Settings…', detail: displayChord(lee.keys.find(k => k.action === 'settings')?.key || 'mod+,'), run: editorSettings},
    {label: 'Workspace history…', detail: 'conflict-safe undo', run: operationHistory},
    {label: 'Keybindings…', run: () => leeAct('edit_keys')},
    {label: 'Terminal', run: () => leeAct('terminal')},
  ]);
}
window.leeToolsMenu = leeToolsMenu;

function leeEditorMenu(anchor) {
  const rows = [
    {label: 'Run selection', detail: displayChord(lee.keys.find(k => k.action === 'run_selection')?.key || ''), run: () => leeAct('run_selection')},
    {label: 'Run all cells', detail: displayChord(lee.keys.find(k => k.action === 'run_all')?.key || ''), run: () => leeAct('run_all')},
    {label: 'Restart and run all', run: () => leeAct('restart_run_all')},
    {separator: true},
    {label: 'Save', detail: displayChord(lee.keys.find(k => k.action === 'save')?.key || ''), run: () => leeAct('save')},
    {label: 'Show unsaved changes', run: () => leeAct('show_diff')},
    {label: 'Rename symbol…', run: () => leeAct('rename_symbol')},
    {label: 'Replace in workspace…', run: () => leeAct('replace_workspace')},
    {separator: true},
    {label: 'Insert cell below', run: () => leeAct('cell_below')},
    {label: 'Change cell type', run: () => leeAct('cell_type')},
    {label: 'Clear all outputs', run: () => leeAct('clear_all_outputs')},
    {separator: true},
    {label: 'All commands…', detail: displayChord(lee.keys.find(k => k.action === 'palette')?.key || ''), run: () => leeAct('palette')},
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

document.addEventListener('pointerdown', e => { if (!e.target.closest('.lee-ctxmenu, .lee-more')) closeMenu(); }, true);
window.addEventListener('blur', closeMenu);
window.addEventListener('resize', () => { closeMenu(); layoutTabs(); });
window.addEventListener('scroll', closeMenu, true);

function showHelp() {
  const scopes = Object.entries(lee.help).sort(([a], [b]) =>
    a === lee.scope ? -1 : b === lee.scope ? 1 : a === 'global' ? -1 : b === 'global' ? 1 : 0);
  const body = scopes.map(([scope, rows]) =>
    `<section class="lee-help-scope${scope === lee.scope ? ' active' : ''}"><h4>${esc(scope)}` +
    `${scope === lee.scope ? '<span>current</span>' : ''}</h4>` + rows.map(([k, l]) =>
      `<div class="lee-krow"><kbd>${esc(displayChord(k))}</kbd><span>${esc(l)}</span></div>`).join('') + '</section>').join('');
  const m = modal(
    `<div class="lee-mhead">keys<span class="sub">${esc(lee.keyPath || '')}</span></div>` +
    (lee.keyNotes || []).map(n => `<div class="lee-err">${esc(n)}</div>`).join('') +
    `<div class="lee-dim">every one of these can be rebound, and every one of them also has a ` +
    `button — nothing here is reachable only by a chord.</div>` +
    `<div class="lee-help">${body}</div>` +
    `<div class="lee-mfoot"><button class="lee-btn" id="gokeys">edit keybindings</button></div>`);
  m.querySelector('#gokeys').onclick = () => { m.remove(); editKeys(); };
}

async function quickOpen(searchMode) {
  const d = await api('/fs/find');
  let hits = d.hits, sel = 0;
  const m = modal(
    `<input class="lee-input" id="qo" placeholder="${searchMode ? 'search files…' : 'open file…'}" autofocus>
     <div class="lee-modallist" id="qolist"></div>`,
    (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, hits.length - 1); paint(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); paint(); }
      else if (e.key === 'Enter') { e.preventDefault(); go(); }
    });
  const list = m.querySelector('#qolist'), input = m.querySelector('#qo');
  const paint = () => {
    list.innerHTML = hits.slice(0, 300).map((h, i) =>
      `<div class="lee-mrow${i === sel ? ' sel' : ''}" data-i="${i}">${esc(h.name)}<span class="sub">${esc(h.path)}</span></div>`).join('');
    list.querySelector('.sel')?.scrollIntoView({block: 'nearest'});
  };
  const go = () => { const h = hits[sel]; if (h) { m.remove(); leeOpenFile(h.path); } };
  list.addEventListener('click', e => { const r = e.target.closest('.lee-mrow'); if (r) { sel = +r.dataset.i; go(); } });
  // Each search walks the whole tree. Debounced and sequenced like the folder picker.
  let seq = 0, timer = null;
  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const mine = ++seq, q = input.value.trim();
      const found = (await api('/fs/find?q=' + encodeURIComponent(q))).hits;
      if (mine !== seq) return;
      hits = found; sel = 0; paint();
    }, 120);
  });
  paint(); setTimeout(() => input.focus(), 0);
}

// The modes, in the order Tab walks them. `all` leads and is the default: it ranks every backend
// together, so it is the one that answers without you having to know which store the thing you
// half-remember is in. A rail rather than a row because each one carries a count, and a count is
// the thing that tells you where to look next when the mode you picked came back empty.
const SEARCH_MODES = [
  ['all', 'all', 'rank ripgrep, symbols, FTS and semantic results together'],
  ['rg', 'rg', 'ripgrep: literal search over current files, fastest'],
  ['context', 'context', 'Kosha composed retrieval across repository code and installed packages'],
  ['repo', 'repo', 'Kosha repository code store'],
  ['env', 'packages', 'Kosha installed-package environment store'],
  ['symbols', 'symbols', 'Kosha symbols: repository and indexed packages'],
  ['ann', 'ANN', 'Kosha embedding ANN'],
];

async function codeSearch() {
  let hits = [], sel = 0, backend = '', previewView = null, searchSeq = 0;
  let mode = localStorage.getItem('lee-search-mode') || 'all';
  if (!SEARCH_MODES.some(([id]) => id === mode)) mode = 'all';
  const counts = {};
  const m = modal(
    `<div class="lee-searchbar"><input class="lee-input" id="cs" placeholder="search code, symbols and meaning…" autofocus>
     <button class="lee-btn" id="kosharefresh" type="button">sync</button></div>` +
    // Where and what, beside which backend. A workspace holds several checkouts, so "this
    // project" is the useful default and "everything open" is the deliberate widening.
    `<div class="lee-searchfilters">
       <label>in<select id="csscope">
         <option value="project">this project</option>
         <option value="workspace">every open folder</option></select></label>
       <label>files<input class="lee-input" id="csexts" placeholder="py, ts — blank for all"
              aria-label="restrict to file extensions"></label>
       <span class="lee-dim" id="csscopenote"></span></div>` +
    `<div class="lee-kosha-status" id="koshastatus"><span>Opening Kosha…</span></div>
     <div class="lee-code-search-body">
       <nav class="lee-searchrail" id="csrail" aria-label="search mode">${SEARCH_MODES.map(([id, label, tip]) =>
         `<button class="lee-searchrail-mode" data-mode="${id}" title="${esc(tip)}">` +
         `<span>${esc(label)}</span><b data-count-for="${id}"></b></button>`).join('')}
         <span class="lee-dim lee-searchrail-hint">tab / shift+tab</span></nav>
       <div class="lee-modallist" id="cslist"><div class="lee-dim">type to search repository + environment context</div></div>
       <aside class="lee-search-preview"><header><div><strong id="cspreviewtitle">Code preview</strong>` +
       `<span id="cspreviewmeta">Select a result</span></div><button class="lee-btn go" id="csopen" disabled>Open file</button></header>` +
       `<div id="cspreview"><div class="lee-search-preview-empty">Matches open here with syntax highlighting.</div></div>` +
       `<div class="lee-search-relations" id="csrelations"></div></aside></div>`,
    (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, hits.length - 1); paint(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); paint(); }
      else if (e.key === 'Enter') { e.preventDefault(); go(); }
      // Tab walks the modes rather than the focus. The dialog traps Tab anyway, so the only
      // thing given up is a focus order over four controls, and what is bought is trying the
      // same query against another backend without leaving the keyboard.
      else if (e.key === 'Tab') { e.preventDefault(); cycleMode(e.shiftKey ? -1 : 1); }
    }, () => {
      if (previewView) LeeCM.destroy(previewView);
      // Closing the dialog must stop the search too, or four backends go on working for a
      // question whose answer has nowhere left to be drawn.
      if (liveStream) { try { liveStream.close(); } catch {} liveStream = null; }
    });
  m.classList.add('lee-code-search-modal');
  const list = $('#cslist', m), input = $('#cs', m), preview = $('#cspreview', m), open = $('#csopen', m);
  const scopeEl = $('#csscope', m), extsEl = $('#csexts', m);
  // Remembered, because a person who works in Python does not want to retype `py` every time
  // they open this box -- and the scope they chose is a statement about how they work.
  scopeEl.value = localStorage.getItem('lee-search-scope') || 'project';
  extsEl.value = localStorage.getItem('lee-search-exts') || '';
  const paintRail = () => {
    $$('.lee-searchrail-mode', m).forEach(b =>
      b.classList.toggle('active', b.dataset.mode === mode));
    // A count only means something once that mode has actually run. Blank is "not asked yet",
    // which is a different thing from nought and must not look like it.
    SEARCH_MODES.forEach(([id]) => {
      const el = $(`[data-count-for="${id}"]`, m); if (!el) return;
      el.textContent = counts[id] == null ? '' : counts[id];
      el.classList.toggle('zero', counts[id] === 0);
    });
  };
  const setMode = next => {
    if (!next || next === mode) return;
    mode = next; localStorage.setItem('lee-search-mode', mode);
    paintRail();
    if (input.value.trim()) search(); else paint();
    input.focus();
  };
  const cycleMode = step => {
    const at = SEARCH_MODES.findIndex(([id]) => id === mode);
    const next = SEARCH_MODES[(at + step + SEARCH_MODES.length) % SEARCH_MODES.length];
    setMode(next[0]);
  };
  const showPreview = () => {
    if (previewView) { LeeCM.destroy(previewView); previewView = null; }
    const h = hits[sel];
    if (!h) {
      preview.innerHTML = '<div class="lee-search-preview-empty">No result selected.</div>';
      open.disabled = true; return;
    }
    const filename = h.path.split('/').pop() || h.package || 'indexed source';
    $('#cspreviewtitle', m).textContent = h.symbol || filename;
    $('#cspreviewmeta', m).textContent = `${h.package ? h.package + ' · ' : ''}${filename}:${h.line} · ${(h.sources || [h.kind]).join(' + ')}`;
    const environment = h.kind.startsWith('env-');
    open.disabled = environment && !h.package;
    open.textContent = environment ? (h.package ? 'Package API' : 'Indexed package') : 'Open file';
    preview.innerHTML = '<div class="lee-search-preview-editor"></div>';
    previewView = mountCodeSurface($('.lee-search-preview-editor', preview), h.text || '(no indexed preview)',
                                   codeLang('', h.path), false);
    const relations = $('#csrelations', m), callers = h.callers || [];
    relations.innerHTML = callers.length ? `<span>called by</span>` + callers.map(name =>
      `<button data-symbol="${esc(name)}">${esc(name.split('.').pop())}</button>`).join('') : '';
    // Following a caller is a graph question, so it switches to the mode that answers one.
    $$('[data-symbol]', relations).forEach(button => button.onclick = () => {
      input.value = button.dataset.symbol;
      if (mode === 'context') search(); else setMode('context');
    });
  };
  const paint = () => {
    if (!hits.length) {
      list.innerHTML = `<div class="lee-dim">${backend ? 'no matches · ' + esc(backend) : 'type to search'}</div>`;
      showPreview(); return;
    }
    list.innerHTML = hits.map((h, i) => {
      const f = h.path.split('/').pop() || h.package || 'environment';
      const foundBy = (h.sources || [h.kind]).join(' + ');
      return `<button class="lee-search-result${i === sel ? ' sel' : ''}" data-i="${i}">` +
        `<span class="lee-search-result-kind">${esc(h.kind.startsWith('env-') ? 'PKG' : h.kind === 'file' ? 'FILE' : h.symbol ? 'SYM' : 'TXT')}</span>` +
        `<span><strong>${esc(h.symbol || h.text.split('\n')[0].slice(0, 90))}</strong>` +
        `<small>${esc(h.package ? h.package + ' · ' : '')}${esc(f)}:${h.line}</small></span>` +
        `<em>${esc(foundBy)}</em></button>`;
    }).join('');
    $('.lee-search-result.sel', list)?.scrollIntoView({block: 'nearest'}); showPreview();
  };
  const go = async () => {
    const h = hits[sel]; if (!h) return;
    if (h.kind.startsWith('env-')) {
      if (!h.package) return status('package source is indexed read-only', 'info');
      const d = await api('/code/package-api?package=' + encodeURIComponent(h.package));
      const box = modal(`<div class="lee-mhead">${esc(h.package)}<span class="sub">public API from Kosha</span></div>` +
        `<div class="lee-package-api"></div>`);
      const body = $('.lee-package-api', box), symbols = d.symbols || [];
      body.innerHTML = symbols.length ? symbols.map(row => `<button data-name="${esc(row.mod_name || '')}">` +
        `<strong>${esc(row.mod_name || '')}</strong><span>${esc(row.docstring || '')}</span></button>`).join('') :
        '<div class="lee-dim">No exported API metadata found.</div>';
      $$('[data-name]', body).forEach(row => row.onclick = () => { box.remove(); input.value = row.dataset.name; search(); });
      return;
    }
    m.remove(); openLocation(h);
  };
  // One click opens at the line, because that is what the box is *for*. It used to select on the
  // first click and need a second one on the same row to go anywhere, so the obvious gesture
  // landed in a preview pane and looked like the result was not clickable. The preview is still
  // reachable without committing: arrow keys move the selection and paint it.
  list.onclick = e => {
    const row = e.target.closest('[data-i]'); if (!row) return;
    sel = +row.dataset.i; paint(); go();
  };
  open.onclick = go;
  // `all` streamed: one section per backend, in the server's best-first leg order, each filling
  // in as that backend reports. Slots are stable on purpose -- rg answers in tens of milliseconds
  // and the embedding leg in seconds, and a list that re-ranked on every arrival would reshuffle
  // under the cursor precisely while someone was reading it. A hit a later leg finds again is not
  // shown twice; it adds its name to the row the first leg already produced, which is the same
  // merge the batch answer does.
  const streamAll = (q, seq) => new Promise(resolve => {
    const slots = new Map(), seen = new Map();
    let notes = [];
    const es = new EventSource('/search/stream?q=' + encodeURIComponent(q) +
                               '&scope=' + encodeURIComponent(scopeEl.value) +
                               '&exts=' + encodeURIComponent(extsEl.value.trim()));
    // Held so the next keystroke can close it. A stream left open keeps four backends working on
    // a question nobody is asking any more, and the server only notices when it next tries to
    // write -- which for the slow legs is seconds away.
    liveStream = es;
    const stop = () => { try { es.close(); } catch {} if (liveStream === es) liveStream = null; resolve(); };
    const recount = () => {
      hits = [];
      for (const leg of slots.keys()) hits.push(...slots.get(leg));
      counts.all = hits.length; paintRail();
    };
    es.addEventListener('start', e => {
      const d = JSON.parse(e.data);
      for (const leg of d.legs || []) slots.set(leg, []);      // fixes the order once
      const where = (d.searched || []).map(p => p.split('/').pop()).join(', ');
      $('#csscopenote', m).textContent = where ? `searched ${where}` : '';
    });
    es.addEventListener('leg', e => {
      if (seq !== searchSeq) return stop();
      const d = JSON.parse(e.data);
      if (d.note) notes.push(d.note);
      const kept = [];
      for (const h of d.hits || []) {
        const key = `${h.path}:${h.line}:${h.package || ''}`;
        const already = seen.get(key);
        if (already) { already.sources = [...new Set([...(already.sources || []), d.leg])]; continue; }
        seen.set(key, h); kept.push(h);
      }
      slots.set(d.leg, kept);
      recount();
      backend = `all · ${[...slots.keys()].filter(k => slots.get(k).length).join(' + ') || 'searching'}`;
      // The selection is an index into a list that just grew at the end, so it still points at
      // the row it pointed at. Only an empty list needs resetting.
      if (sel >= hits.length) sel = Math.max(0, hits.length - 1);
      paint();
    });
    es.addEventListener('done', e => {
      if (notes.length) backend += ' · ' + notes.slice(0, 2).join('; ');
      paint(); stop();
    });
    es.onerror = () => { backend = backend || 'search stream failed'; paint(); stop(); };
  });

  let timer, liveStream = null;
  const search = () => {
    clearTimeout(timer); const seq = ++searchSeq;
    if (liveStream) { try { liveStream.close(); } catch {} liveStream = null; }
    timer = setTimeout(async () => {
      const q = input.value.trim();
      if (!q) { hits = []; backend = ''; paint(); return; }
      if (mode === 'all') {
        hits = []; sel = 0; backend = 'all · searching';
        list.innerHTML = `<div class="lee-search-progress"><span></span>every backend, fastest first…</div>`;
        return streamAll(q, seq);
      }
      list.innerHTML = `<div class="lee-search-progress"><span></span>searching ${esc(mode === 'context' ? 'Kosha repo + environment context' : mode === 'all' ? 'rg, symbols, FTS and ANN' : mode)}…</div>`;
      try {
        const d = await api('/search?q=' + encodeURIComponent(q) + '&mode=' + mode +
                            '&scope=' + encodeURIComponent(scopeEl.value) +
                            '&exts=' + encodeURIComponent(extsEl.value.trim()));
        if (seq !== searchSeq) return;
        hits = d.hits || []; backend = d.backend + (d.note ? ' · ' + d.note : ''); sel = 0;
        // Which folders were actually walked, because "no matches" and "no matches *here*" are
        // different answers and only one of them means the thing is not in your code.
        const where = (d.searched || []).map(p => p.split('/').pop()).join(', ');
        $('#csscopenote', m).textContent = where ? `searched ${where}` : '';
        counts[mode] = hits.length; paintRail();
        paint(); status(`search: ${d.backend}${d.note ? ' — ' + d.note : ''}`);
      } catch (e) {
        if (seq !== searchSeq) return;
        hits = []; backend = e.message || String(e); paint(); status(backend, 'err');
      }
    }, mode === 'rg' ? 120 : mode === 'all' || mode === 'context' ? 360 : 280);
  };
  input.addEventListener('input', search);
  scopeEl.addEventListener('change', () => {
    localStorage.setItem('lee-search-scope', scopeEl.value);
    if (input.value.trim()) search();
  });
  extsEl.addEventListener('input', () => {
    localStorage.setItem('lee-search-exts', extsEl.value.trim());
    if (input.value.trim()) search();
  });
  api('/code/status').then(d => {
    const el = $('#koshastatus', m); if (!el) return;
    el.innerHTML = d.ok ? `<span class="ok">Kosha connected</span><span>${Number(d.files || 0).toLocaleString()} files</span>` +
      `<span>${Number(d.packages || 0).toLocaleString()} packages</span><span>${Number(d.graph_nodes || 0).toLocaleString()} graph nodes</span>` +
      `${d.stale_files ? `<span class="warn">${d.stale_files} stale files</span>` : ''}` : `<span class="warn">${esc(d.note || 'Kosha unavailable')}</span>`;
  }).catch(() => {});
  $('#kosharefresh', m).onclick = async () => {
    const button = $('#kosharefresh', m); button.disabled = true; button.textContent = 'syncing…';
    try { await post('/code/sync'); button.textContent = 'synced'; status('Kosha code, notebooks and graph synced', 'ok'); if (input.value.trim()) search(); }
    catch (e) { button.textContent = 'retry sync'; status(e.message || String(e), 'err'); }
    finally { button.disabled = false; }
  };
  $('#csrail', m).onclick = e => {
    const b = e.target.closest('[data-mode]'); if (!b) return;
    e.preventDefault(); setMode(b.dataset.mode);
  };
  paintRail();
  setTimeout(() => input.focus(), 0);
}

function cursorWord() {
  const v = curEditor(); return v ? LeeCM.wordAtCursor(v) : '';
}
async function findDefinition(name = cursorWord()) {
  if (!name) return status('put the cursor on a symbol first', 'err');
  status(`finding ${name}…`);
  const d = await api('/code/definition?name=' + encodeURIComponent(name) + '&path=' + encodeURIComponent(lee.path || ''));
  if (!(d.hits || []).length) return status(`no definition found for ${name}`, 'err');
  if (d.hits.length === 1) return openLocation(d.hits[0]);
  hitList(d.hits, `${d.backend} — ${d.note}`, `definitions of ${name}`, openLocation);
}
async function findUsages(name = cursorWord()) {
  if (!name) return status('put the cursor on a symbol first', 'err');
  const d = await api('/code/usages?name=' + encodeURIComponent(name));
  hitList(d.hits || [], `${d.backend} — ${d.note}`, `usages of ${name}`, openLocation);
}
/* Where the cursor is, in the coordinates a symbol lookup can use. A notebook cursor is a cell
   and a line inside it: the file line is a line of JSON and matches no declaration. */
function editorPlace(view = curEditor()) {
  const path = lee.path || '';
  if (!view) return {path, line: 0, cellIndex: -1};
  const line = view.state.doc.lineAt(LeeCM.cursor(view)).number;
  const cellIndex = lee.kind === 'notebook'
    ? lee.cells.findIndex(c => lee.editors.get(c.id) === view) : -1;
  return {path, line, cellIndex};
}
/* One key, both directions. On a usage it goes to the declaration; standing on the declaration it
   lists who uses it, because that is the only question left to ask there. The server decides which,
   since it is the side that knows where the declaration is. */
async function gotoDeclaration(name = cursorWord(), place = editorPlace()) {
  if (!name) return status('put the cursor on a symbol first', 'err');
  status(`finding ${name}…`);
  let d;
  // a failed lookup has to say so: `finding…` is busy, and a busy toast never leaves by itself
  try {
    d = await api('/code/jump?name=' + encodeURIComponent(name) +
      '&path=' + encodeURIComponent(place.path) + '&line=' + place.line + '&cell_index=' + place.cellIndex);
  } catch (e) { return status(String(e.message || e), 'err'); }
  const hits = d.hits || [];
  if (!hits.length) return status(`nothing found for ${name}`, 'err');
  if (d.kind === 'definition' && hits.length === 1) return openLocation(hits[0]);
  const label = d.kind === 'usages' ? 'usages' : 'definitions';
  hitList(hits, `${d.backend} — ${d.note}`, `${label} of ${name}`, openLocation);
  // `finding…` is a busy toast, and a busy toast waits to be clicked. The list is the answer, so
  // the toast has to stop saying it is still looking.
  status(`${hits.length} ${label} of ${name}`, 'ok');
}
/* The mouse saying what mod+b says. CodeMirror owns the click, so this listens in the capture
   phase and takes the event there: letting it through would move the caret and select a word.

   Either modifier counts. Platform detection is not reliable enough to make it the gate: in a
   webview that reported no platform, ctrl+click both looked up the symbol and, being a right-click
   on macOS, opened the cell menu on top of the result. So the paired `contextmenu` is claimed too. */
function bindModClick() {
  document.addEventListener('contextmenu', e => {
    if (e.shiftKey || !(e.metaKey || e.ctrlKey) || !e.target?.closest?.('.cm-content')) return;
    e.preventDefault(); e.stopPropagation();
  }, true);
  document.addEventListener('mousedown', e => {
    if (e.button !== 0 || e.altKey || e.shiftKey || !(e.metaKey || e.ctrlKey)) return;
    if (!e.target?.closest?.('.cm-content')) return;
    const view = [...lee.editors.values()].find(v => v?.contentDOM?.contains(e.target));
    const pos = view ? view.posAtCoords({x: e.clientX, y: e.clientY}) : null;
    if (pos == null) return;
    e.preventDefault(); e.stopPropagation();
    LeeCM.setCursor(view, pos);
    const word = LeeCM.wordAtCursor(view);
    if (!word) return status('nothing to look up there', 'err');
    gotoDeclaration(word, editorPlace(view));
  }, true);
}
/* Cmd+F in a notebook. CodeMirror's own panel searches the one cell it belongs to, which is never
   the question being asked: a notebook is one document to the person reading it. This walks every
   cell's live text, selects each match where it lives, and says which one of how many. */
const nbCellText = i => {
  const c = lee.cells[i]; if (!c) return '';
  const v = lee.editors.get(c.id);
  return v ? LeeCM.getDoc(v) : String(c.source || '');
};
function nbFindMatches(q) {
  const out = [], needle = String(q || '').toLowerCase();
  if (!needle) return out;
  for (let i = 0; i < lee.cells.length; i++) {
    const text = nbCellText(i).toLowerCase();
    for (let at = text.indexOf(needle); at >= 0; at = text.indexOf(needle, at + needle.length))
      out.push({cell: i, from: at, to: at + needle.length});
  }
  return out;
}
function nbFindPaint() {
  const bar = $('#nbfind'); if (!bar) return;
  const q = $('#nbfindq', bar).value, hits = nbFindMatches(q), at = lee.nbFind?.at ?? -1;
  lee.nbFind = {q, hits, at: at < hits.length ? at : -1};
  $('#nbfindcount', bar).textContent = !q ? '' : !hits.length ? 'no matches'
    : `${(lee.nbFind.at < 0 ? 0 : lee.nbFind.at) + 1} of ${hits.length}`;
  bar.classList.toggle('empty', !!q && !hits.length);
}
function nbFindStep(direction) {
  const bar = $('#nbfind'), state = lee.nbFind;
  if (!bar || !state?.hits.length) return;
  const n = state.hits.length;
  state.at = ((state.at + direction) % n + n) % n;
  const hit = state.hits[state.at];
  focusCell(hit.cell);
  const view = ensureCellMounted(hit.cell);
  if (view) LeeCM.setSelection(view, hit.from, hit.to);
  $('#nbfindcount', bar).textContent = `${state.at + 1} of ${n}`;
  // `focusCell` and `setSelection` both take the focus, and each does it a frame apart. The
  // query is where the typing belongs, so it is claimed back after both have had their turn.
  requestAnimationFrame(() => requestAnimationFrame(() => $('#nbfindq', bar)?.focus()));
}
function nbFindClose() {
  const bar = $('#nbfind'); if (bar) bar.hidden = true;
  lee.nbFind = null;
  const v = curEditor(); if (v) LeeCM.focus(v);
}
function nbFind() {
  if (lee.kind !== 'notebook') return status('open a notebook to search across its cells', 'err');
  let bar = $('#nbfind');
  if (!bar) {
    bar = document.createElement('div');
    bar.id = 'nbfind'; bar.className = 'lee-find-bar'; bar.setAttribute('role', 'search');
    bar.innerHTML = '<input class="lee-input" id="nbfindq" spellcheck="false" ' +
      'placeholder="find in every cell" aria-label="find in every cell">' +
      '<span class="lee-find-count" id="nbfindcount" aria-live="polite"></span>' +
      '<button type="button" data-find="prev" title="previous match (shift+enter)">↑</button>' +
      '<button type="button" data-find="next" title="next match (enter)">↓</button>' +
      '<button type="button" data-find="close" title="close (esc)">✕</button>';
    document.body.appendChild(bar);
    bar.addEventListener('click', e => {
      const b = e.target.closest('[data-find]'); if (!b) return;
      if (b.dataset.find === 'close') return nbFindClose();
      nbFindStep(b.dataset.find === 'next' ? 1 : -1);
    });
    const input = $('#nbfindq', bar);
    input.addEventListener('input', nbFindPaint);
    input.addEventListener('keydown', e => {
      if (e.key === 'Escape') { e.preventDefault(); return nbFindClose(); }
      if (e.key !== 'Enter') return;
      e.preventDefault();
      if (!lee.nbFind?.hits.length) nbFindPaint();
      nbFindStep(e.shiftKey ? -1 : 1);
    });
  }
  bar.hidden = false;
  const input = $('#nbfindq', bar), view = curEditor(), held = view ? LeeCM.selection(view) : null;
  if (held && held.from !== held.to && !held.text.includes('\n')) input.value = held.text;
  lee.nbFind = null;
  nbFindPaint();
  input.focus(); input.select();
}
window.gotoDeclaration = gotoDeclaration; window.nbFind = nbFind; window.bindModClick = bindModClick;

async function renameSymbol() {
  const name=cursorWord(),view=curEditor();
  if(!name||!view||!lee.path||curLang()!=='python')return status('put the cursor on a Python symbol first','err');
  const next=await inputDialog('rename symbol','New name',name,'valid Python identifier');
  if(!next||next===name)return;
  const pos=LeeCM.cursor(view),line=view.state.doc.lineAt(pos),character=pos-line.from;
  try{
    const preview=await post('/lsp/rename',{path:lee.path,text:LeeCM.getDoc(view),line:line.number-1,character,newName:next});
    if(!preview.files?.length)return status('Pyright found no rename edits','err');
    const summary=preview.files.map(f=>`${f.path.split('/').pop()} · ${f.edits} edit${f.edits===1?'':'s'}`).join('\n');
    if(!await confirmDialog('Rename across workspace',`${name} → ${next}\n\n${summary}`,'rename'))return;
    await post('/lsp/rename',{path:lee.path,text:LeeCM.getDoc(view),line:line.number-1,character,newName:next,apply:true});
    await post('/tab/reload',{path:lee.path});await mountTab();refreshFileTree(undefined,false);status(`renamed ${name} to ${next}`,'ok');
  }catch(e){status(e.message||String(e),'err');}
}

async function syncCodeIndex() {
  status('syncing Kosha index, notebooks and call graph…');
  const d = await post('/code/sync'); status(d.note || 'Kosha index synced', d.ok ? 'ok' : 'err');
}

async function leeSymbols() {
  const host = $('#symbols'), label = $('#symbolfile'); if (!host) return;
  const path = lee.path, name = compactPath(path || ''); if (label) label.textContent = name ? '· ' + name : '';
  // Notebooks are included: their defs and classes are real structure, and the server reads
  // them out of the cells rather than out of the JSON. The outline is of the file on disk, so
  // a def typed and not yet saved appears once autosave has run.
  if (!lee.path || (lee.kind !== 'text' && lee.kind !== 'notebook')) {
    host.innerHTML = '<div class="lee-dim">Open a source file or notebook to see its symbols.</div>'; return;
  }
  host.innerHTML = '<div class="lee-symbol-loading">Reading structure…</div>';
  try {
    const d = await api('/outline?path=' + encodeURIComponent(path));
    if (path !== lee.path) return;
    const rows = d.symbols || [];
    host.innerHTML = rows.length ? rows.map((s, i) => {
      const depth = Math.max(0, Math.floor(Number(s.score || 0) / 4));
      const kind = /^class\s/.test(s.text || '') ? 'class' : 'function';
      // A notebook symbol is addressed by cell, and the JSON line it also carries would be a
      // meaningless number to show: the row says which cell and where in it instead.
      const cellLine = Number(s.cell_line || 0), cellIndex = Number(s.cell_index ?? -1);
      const where = cellLine > 0 ? `${cellIndex + 1}:${cellLine}` : String(Number(s.line || 1));
      return `<button class="lee-symbol-row" role="treeitem" style="--depth:${depth}" ` +
        `data-line="${Number(s.line || 1)}" data-column="${Number(s.column || 0)}" data-cell="${esc(s.cell || '')}" ` +
        `data-cell-index="${cellIndex}" data-cell-line="${cellLine}">` +
        `<span class="lee-symbol-kind">${kind === 'class' ? 'C' : 'ƒ'}</span>` +
        `<span>${esc(s.symbol)}</span><small>${esc(where)}</small></button>`;
    }).join('') : '<div class="lee-dim">No functions or classes in this file.</div>';
    $$('.lee-symbol-row', host).forEach(row => row.onclick = () => {
      openLocation({path: path, line: +row.dataset.line, column: +row.dataset.column, cell: row.dataset.cell,
                    cell_index: +row.dataset.cellIndex, cell_line: +row.dataset.cellLine});
      if (matchMedia('(max-width: 1100px)').matches) leePane('left', false);
    });
  } catch (e) { if (path === lee.path) host.innerHTML = `<div class="lee-err">${esc(e.message || e)}</div>`; }
}
window.leeSymbols = leeSymbols;

