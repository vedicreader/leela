const MAC = /mac|iphone|ipad|ipod/i.test(navigator.userAgentData?.platform || navigator.platform || '');
//: A native window gets every chord; a browser tab never sees the ones Chrome keeps (`browser: false`).
const NATIVE = !!(window.pywebview || window.webkit?.messageHandlers);
//: Each chord as kavacha's `chord_glyph` writes it, from the server's table; a chord it lacks keeps the old spelling.
const displayChord = s => String(s || '').split(/(\s+)/).map(t =>
  /^\s*$/.test(t) || t === '/' ? t : lee.glyphs?.[MAC ? 'mac' : 'pc']?.[t] || t.replace(/\bmod\+/g, MAC ? '⌘' : 'ctrl+')).join('');
//: The chord to advertise for a row: its first, or in a browser tab its first one the tab receives.
const shownChord = k => { const cs = (k?.key || '').split(' ').filter(Boolean);
  return (NATIVE ? cs[0] : cs.find((c, i) => k.chords?.[i]?.browser !== false)) || ''; };
function paintKeyLabels(root = document) {
  $$('kbd', root).forEach(k => { if (k.textContent.includes('mod+')) k.textContent = displayChord(k.textContent); });
}

//: The server draws the footer once; its chords follow `lee.keys` from here.
function paintFooterKeys() {
  $$('.lee-fkey[data-action]').forEach(el => {
    const first = shownChord(lee.keys.find(k => k.action === el.dataset.action));
    el.style.display = first ? '' : 'none';
    const kbd = el.querySelector('kbd'); if (kbd && first) kbd.textContent = displayChord(first);
  });
}

//: `d` is a keymap the server pushed over `/fs/events`, so it is not fetched again.
async function loadKeys(d) {
  d ||= await api('/keys.json');
  lee.keys = d.keys; lee.help = d.help; lee.keyPath = d.path; lee.keyNotes = d.notes || [];
  lee.bars = d.bars || {}; lee.menus = d.menus || {}; lee.glyphs = d.glyphs || {}; lee.legacy = d.legacy || [];
  lee.menuChords = d.menuChords || [];
  paintFooterKeys(); paintKeyLabels();
  const prompt = $('#agentprompt'); if (prompt) prompt.placeholder = displayChord(prompt.placeholder);
  renderContextKeys(lee.scope);
  if (lee.keyNotes.length) status(lee.keyNotes[0] + ' — see the keys panel', 'err');
}

function renderContextKeys(scope = lee.scope) {
  const host = $('#keytoast'), tag = $('#keyscope');
  if (!host || !lee.keys.length) return;
  // A glanceable contextual cheat sheet, not the full keymap. Help-only commands stay in the
  // searchable help and settings surfaces rather than pushing the file tree off screen.
  const local = lee.keys.filter(k => k.scope === scope && k.label && k.key && ['footer','toast'].includes(k.show)).slice(0, 8);
  const global = lee.keys.filter(k => k.scope === 'global' && k.show === 'toast' && k.label && k.key).slice(0, 4);
  const rows = local.concat(global);
  if (tag) tag.textContent = scope && scope !== 'global' ? `· ${scope}` : '';
  host.innerHTML = rows.length ? rows.map(k =>
    `<div class="lee-krow${k.scope === scope ? ' contextual' : ''}"><kbd>${esc(displayChord(shownChord(k)))}</kbd>` +
    `<span>${esc(k.label)}</span></div>`).join('') : '<div class="lee-dim">no keys in this context</div>';
}

/* One application-level keyboard router owns every app command. CodeMirror owns editing commands
 * and xterm owns pty input, and neither gets a duplicate copy of this map. The capturing listener
 * resolves an accepted app command before an editor can consume it. An unaccepted event continues
 * untouched. */
const TERM_ESCAPES = new Set(['help', 'quit', 'palette', 'settings', 'toggle_left', 'toggle_right', 'leave_full_screen']);
const EDITING_SCOPES = new Set(['editor', 'exec', 'agent', 'term']);

function eventContext(e) {
  const path = e.composedPath ? e.composedPath() : [e.target];
  const inPath = selector => path.some(n => n instanceof Element && n.matches(selector));
  // Overlays own their keyboard while open, so commands behind a dialog never fire. A slide deck
  // owns it wherever focus has gone, since what is behind it cannot be seen.
  if (inPath('.lee-modal, .lee-ctxmenu') || lee.present) return 'overlay';
  if (inPath('#termwrap, .xterm')) return 'term';
  // A live page wants its own keyboard as much as a shell does, so the inline browser is routed
  // like the terminal. It has to come before `#editor`, which contains it.
  if (inPath('.lee-webview')) return 'web';
  if (inPath('#agentprompt, .lee-agent')) return 'agent';
  if (inPath('#execbox, .lee-exec')) return 'exec';
  // Before `#editor`, which holds the tab they are mounted in.
  if (inPath('.lee-vault-review')) return 'review';
  if (inPath('.lee-vault-docview')) return 'vault';
  // Before `.lee-cell`, which holds it: a widget's sliders and fields take arrows and letters, a rupaka demo's gate takes mod+enter.
  if (inPath('.lee-widget, .lee-rupaka')) return 'widget';
  if (inPath('#editor, .lee-cell, #filecm')) return 'editor';
  if (inPath('#vars, #varfilter, .lee-varspanel')) return 'vars';
  if (inPath('#filetree, .lee-files')) return 'files';
  return lee.scope || 'editor';
}

/* The window title ends with the kind of pane that has focus, so a tool outside the page (Sanketa)
 * can read it. The token comes from the same scope the key router uses; `title_scope` in Python
 * gives the same word for a tab before the page names the focused pane. */
function titleScope(scope, kind = lee.kind, path = lee.path) {
  if (scope === 'term') return 'terminal';
  if (scope && !['editor', 'global', 'widget'].includes(scope)) return scope;
  if (!kind) return 'files';
  if (scope === 'widget' || kind === 'notebook') return 'notebook';
  if (kind === 'vault' || kind === 'vaultwb') return 'vault';
  if (kind === 'web') return 'web';
  const ext = /\.([^./]+)$/.exec(path || '')?.[1]?.toLowerCase();
  return ext === 'py' ? 'py' : ext ? `editor:${ext}` : 'editor';
}
//: One part of the title: no control characters, never ` · ` inside, at most 60 characters. `title_part` in Python is the same.
function titlePart(s, most = 60) {
  s = String(s ?? '').replace(/[\u0000-\u001f\u007f]+/g, ' ');
  while (s.includes(' · ')) s = s.replaceAll(' · ', ' - ');
  return Array.from(s.trim()).slice(0, most).join('').trim();
}
//: `[prefix · ]Leela · <folder> · <scope>`, as `window_title` in Python builds it. `prefix` is the agent's attention marks.
const leelaTitle = (folder, token, prefix = '') => [prefix, 'Leela', titlePart(folder), token || 'files'].filter(Boolean).join(' · ');
//: The active folder's title name. The server puts it on the folder pill; `refreshProjectPills` keeps it current.
const titleFolder = () => lee.titleFolder ??= globalThis.document?.getElementById?.('workspacepill')?.dataset.folder || '';
//: An overlay keeps the scope it opened over. Native windows are told only when the string changes.
function paintTitle(scope) {
  if (scope && scope !== 'overlay') lee.titleScope = scope;
  clearTimeout(lee.titleTimer);
  lee.titleTimer = setTimeout(() => {
    const t = leelaTitle(titleFolder(), titleScope(lee.titleScope || lee.scope), lee.titlePrefix);
    if (t === lee.title) return;
    document.title = lee.title = t;
    window.pywebview?.api?.set_title?.(t, location.href)?.catch?.(() => {});
  }, 100);
}
document.addEventListener('focusin', e => paintTitle(eventContext(e)), true);
window.addEventListener('pywebviewready', () => { lee.title = ''; paintTitle(); });

//: The element a key went to. `e.target` is retargeted to the host of an open shadow root, such as a widget's.
const keyTarget = e => e.composedPath?.()[0] || e.target;
function isTextEntry(el) {
  if (!(el instanceof Element)) return false;
  if (el.isContentEditable) return true;
  if (el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') return true;
  return el.tagName === 'INPUT' &&
    !['checkbox', 'radio', 'button', 'submit', 'reset', 'range', 'color', 'file'].includes(el.type);
}

function chordMatches(c, e) {
  if (e.isComposing || e.key === 'Process' || e.repeat) return false;
  // AltGr arrives as Ctrl+Alt on Windows and Linux; in a text field it is a character, not a chord.
  if (!MAC && e.getModifierState?.('AltGraph') && isTextEntry(keyTarget(e))) return false;
  // Hyper is all four modifiers, the shape macOS reports. Ctrl+Alt+Shift alone is AeroSpace's.
  const wantCtrl = !!c.ctrl || !!c.hyper || (!!c.mod && !MAC);
  const wantMeta = (!!c.mod || !!c.hyper) && MAC;
  if (wantCtrl !== e.ctrlKey || wantMeta !== e.metaKey || !!(c.alt || c.hyper) !== e.altKey || !!(c.shift || c.hyper) !== e.shiftKey)
    return false;
  // Matched by physical code where there is one: Karabiner and Hyper can transform `event.key`,
  // while `event.code` stays Enter, KeyR, ArrowDown.
  if (c.code && (c.mod || c.ctrl || c.alt || c.hyper)) return c.code === e.code;
  return c.key.toLowerCase() === (e.key || '').toLowerCase();
}

//: Cell actions whose first chord is also a CodeMirror line command (copy, cut, toggle comment).
//: While a cell's editor has focus CodeMirror gets that chord; the cell action answers it in command
//: mode, and on its other chords everywhere.
const CELL_ON_CM_CHORD = new Set(['cell_copy', 'cell_cut', 'comment']);
//: CodeMirror commands the table binds. Editors made with `tableKeys` have no chord of their own for them.
const CM_EDIT = {copy_line_up: 'copyLineUp', copy_line_down: 'copyLineDown', delete_line: 'deleteLine',
  select_line: 'selectLine', select_next_occurrence: 'selectNextOccurrence',
  select_all_occurrences: 'selectSelectionMatches', add_cursor_above: 'addCursorAbove',
  add_cursor_below: 'addCursorBelow', matching_bracket: 'cursorMatchingBracket',
  select_parent_syntax: 'selectParentSyntax', block_comment: 'toggleBlockComment'};
const inCellEditor = e => (e.composedPath?.() || [e.target]).some(n => n instanceof Element && n.matches('.lee-cell .cm-editor'));
//: A letter or shifted letter in the editor scope is a notebook command-mode key, as RISE's slide chords and
//: Jupyter's `a`, `b`, `d d`: a cell in command mode takes it, and every editor, field, tab or button types or keeps it.
const typesHere = e => lee.kind !== 'notebook' || isTextEntry(keyTarget(e)) ||
  (e.composedPath?.() || [e.target]).some(n => n instanceof Element && n.matches('.cm-editor'));
const commandChord = (k, c) => k.scope === 'editor' && !(c.mod || c.ctrl || c.alt || c.hyper) && c.key.length === 1 && c.key !== ' ';
function commandMode(e) {
  if (typesHere(e)) return false;
  const t = keyTarget(e);
  return t === document.body || (t instanceof Element && !!t.closest('.lee-cell, #editor') && !t.closest('button, a, summary, select, .lee-tab'));
}
//: `d d`: the first press arms, a second within the window runs. Any other key disarms.
const TWICE_MS = 800;
function twiceReady(k, chord, e) {
  if (!chord.twice) return true;
  const armed = lee.twice?.action === k.action && e.timeStamp - lee.twice.at < TWICE_MS;
  lee.twice = armed ? null : {action: k.action, at: e.timeStamp};
  return armed;
}
const firesInTextEntry = c => c.mod || c.ctrl || c.alt || /^F([1-9]|1[0-2])$/.test(c.key);
//: Plain copy, cut and paste stay the browser's in a text field, and copy and cut also with text
//: selected. Not a selection touching a cell's editor, which keeps one after it blurs, or the file
//: tree, where shift-click marks rows and drags a text selection along.
const selTouches = (n, sel) => (n?.nodeType === 1 ? n : n?.parentElement)?.closest(sel);
function nativeClipboard(e) {
  if (!['KeyC', 'KeyX', 'KeyV'].includes(e.code) || e.altKey || e.shiftKey || e.metaKey !== MAC || e.ctrlKey === MAC) return false;
  if (isTextEntry(keyTarget(e))) return true;
  const s = getSelection(), own = '.lee-cell .cm-editor, #filetree, .lee-files';
  return e.code !== 'KeyV' && !!s && !s.isCollapsed && !!String(s).trim() &&
    !selTouches(s.anchorNode, own) && !selTouches(s.focusNode, own);
}
//: An old default chord nothing is bound to now: run its action once and say where it went. Never while typing.
function legacyBinding(e, scope) {
  if (scope === 'overlay' || isTextEntry(keyTarget(e)) || (scope === 'editor' && lee.kind === 'notebook' && typesHere(e))) return null;
  const allowed = new Set(lee.keys.filter(k => k.scope === scope || k.scope === 'global').map(k => k.action));
  return (lee.legacy || []).find(r => allowed.has(r.action) && chordMatches(r.chord, e)) || null;
}
//: A chord the Mac menu bar owns, pressed over an overlay. The page swallows it, so the row does not run behind the overlay.
const menuChordOver = (e, scope) => scope === 'overlay' && (lee.menuChords || []).some(c => chordMatches(c, e));
function findBinding(e, scope) {
  if (scope === 'overlay' || nativeClipboard(e)) return null;
  // `term` and `web` hand the keyboard to something that is not Leela, keeping only the chords
  // that get you back out.
  const allowed = (scope === 'term' || scope === 'web')
    ? k => k.scope === scope || k.action.startsWith('focus_') || TERM_ESCAPES.has(k.action)
    : k => k.scope === scope || k.scope === 'global';
  const guard = !EDITING_SCOPES.has(scope) && isTextEntry(keyTarget(e));
  for (const k of lee.keys) {
    if (!allowed(k)) continue;
    const chord = k.chords.find(c => chordMatches(c, e));
    if (!chord || (guard && !firesInTextEntry(chord))) continue;
    // A widget keeps every plain key, and its own undo; only chords that leave it reach Leela.
    if (scope === 'widget' && (!firesInTextEntry(chord) || k.scope !== 'global' || DEFER_IN_TEXT[k.action])) continue;
    if (['cell_copy', 'cell_cut'].includes(k.action) && lee.kind !== 'notebook') continue;
    if (CELL_ON_CM_CHORD.has(k.action) && chord === k.chords[0] && inCellEditor(e)) continue;
    if (MD_KEYS[k.action] && !MD_KEYS[k.action](e)) continue;
    if (commandChord(k, chord) && !commandMode(e)) continue;
    // With no tab open ⌘W is the window's: the page leaves it alone and the window closes.
    if (k.action === 'close_tab' && chord.mod && !$$('.lee-tab').length) continue;
    if (['cell_first', 'cell_last', 'cell_page_up', 'cell_page_down', 'cell_move_up', 'cell_move_down'].includes(k.action)
        && lee.kind !== 'notebook') continue;
    // The find pane searches the open document. A CodeMirror that is not one of the page's own
    // editors keeps its own panel, which searches the text on screen there.
    if (k.action === 'find_in_file') {
      const cm = (e.composedPath ? e.composedPath() : [e.target])
        .find(n => n instanceof Element && n.matches('.cm-editor'));
      if (cm && !cm.closest('#editor, #filecm, .lee-cell')) continue;
    }
    return {binding: k, chord};
  }
  return null;
}

//: Chords CodeMirror owns while the caret is in a document, and what to try there first. Its
//: command returns false with nothing left to undo, which is when the cell operation is what
//: `mod+z` must mean instead.
const DEFER_IN_TEXT = {notebook_undo: 'undo', notebook_redo: 'redo',
                       indent_more: 'indentMore', indent_less: 'indentLess',
                       indent_selection: 'indentSelection'};

function textEditorOf(e) {
  const path = e.composedPath ? e.composedPath() : [e.target];
  const el = path.find(n => n instanceof Element && n.matches('.cm-content'));
  if (!el) return null;
  const host = el.closest('.cm-editor');
  return [...lee.editors.values()].find(v => v.dom === host) || null;
}

window.addEventListener('keydown', e => {
  const scope = eventContext(e), match = findBinding(e, scope);
  // Kept on `lee` so the key editor and DevTools can tell "Chrome did not deliver it" from "the
  // router rejected it".
  lee.lastKeyEvent = {key: e.key, code: e.code, ctrl: e.ctrlKey, alt: e.altKey,
                      shift: e.shiftKey, meta: e.metaKey, scope,
                      action: match?.binding.action || '', trusted: e.isTrusted};
  if (!match) {
    if (!['Shift', 'Control', 'Alt', 'Meta'].includes(e.key)) lee.twice = null;
    if (menuChordOver(e, scope)) return void e.preventDefault();
    const old = legacyBinding(e, scope); if (!old) return;
    e.preventDefault(); e.stopPropagation();
    status(old.now ? `${old.old} is now ${old.now}` : `${old.old} has no key now. Use the command palette.`, 'ok');
    return void leeAct(old.action);
  }
  if (!twiceReady(match.binding, match.chord, e)) return void (e.preventDefault(), e.stopPropagation());
  if (!match.chord.twice) lee.twice = null;
  // Run on the editor under the caret; any other CodeMirror keeps its own chord for the command.
  if (CM_EDIT[match.binding.action]) {
    const v = textEditorOf(e); if (!v) return;
    e.preventDefault(); e.stopPropagation();
    return void LeeCM[CM_EDIT[match.binding.action]](v);
  }
  const cmd = DEFER_IN_TEXT[match.binding.action], view = cmd && textEditorOf(e);
  if (view) {
    e.preventDefault(); e.stopPropagation();
    if (LeeCM[cmd](view)) return;          // the document had something to undo
    return void leeAct(match.binding.action);
  }
  e.preventDefault(); e.stopPropagation();
  leeAct(match.binding.action);
}, true);

