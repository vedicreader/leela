const MAC = /mac|iphone|ipad|ipod/i.test(navigator.userAgentData?.platform || navigator.platform || '');
const displayChord = s => String(s || '').replace(/\bmod\+/g, MAC ? '⌘' : 'ctrl+');
function paintKeyLabels(root = document) {
  $$('kbd', root).forEach(k => { if (k.textContent.includes('mod+')) k.textContent = displayChord(k.textContent); });
}

async function loadKeys() {
  const d = await api('/keys.json');
  lee.keys = d.keys; lee.help = d.help; lee.keyPath = d.path; lee.keyNotes = d.notes || [];
  lee.bars = d.bars || {}; lee.menus = d.menus || {};
  paintKeyLabels();
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
    `<div class="lee-krow${k.scope === scope ? ' contextual' : ''}"><kbd>${esc(displayChord(k.key))}</kbd>` +
    `<span>${esc(k.label)}</span></div>`).join('') : '<div class="lee-dim">no keys in this context</div>';
}

/* One application-level keyboard router owns every app command. CodeMirror owns editing commands
 * and xterm owns pty input, and neither gets a duplicate copy of this map. The capturing listener
 * resolves an accepted app command before an editor can consume it. An unaccepted event continues
 * untouched. */
const TERM_ESCAPES = new Set(['help', 'quit', 'palette', 'settings', 'toggle_left', 'toggle_right']);
const EDITING_SCOPES = new Set(['editor', 'exec', 'agent', 'term']);

function eventContext(e) {
  const path = e.composedPath ? e.composedPath() : [e.target];
  const inPath = selector => path.some(n => n instanceof Element && n.matches(selector));
  // Overlays own their keyboard while open, so commands behind a dialog never fire.
  if (inPath('.lee-modal, .lee-ctxmenu')) return 'overlay';
  if (inPath('#termwrap, .xterm')) return 'term';
  // A live page wants its own keyboard as much as a shell does, so the inline browser is routed
  // like the terminal. It has to come before `#editor`, which contains it.
  if (inPath('.lee-webview')) return 'web';
  if (inPath('#agentprompt, .lee-agent')) return 'agent';
  if (inPath('#execbox, .lee-exec')) return 'exec';
  // Before `#editor`, which holds the tab they are mounted in.
  if (inPath('.lee-vault-review')) return 'review';
  if (inPath('.lee-vault-docview')) return 'vault';
  if (inPath('#editor, .lee-cell, #filecm')) return 'editor';
  if (inPath('#vars, #varfilter, .lee-varspanel')) return 'vars';
  if (inPath('#filetree, .lee-files')) return 'files';
  return lee.scope || 'editor';
}

function isTextEntry(el) {
  if (!(el instanceof Element)) return false;
  if (el.isContentEditable) return true;
  if (el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') return true;
  return el.tagName === 'INPUT' &&
    !['checkbox', 'radio', 'button', 'submit', 'reset', 'range', 'color', 'file'].includes(el.type);
}

function chordMatches(c, e) {
  if (e.isComposing || e.key === 'Process' || e.repeat) return false;
  // macOS reports Caps Lock remapped to Hyper as all four modifiers. Other platforms and some
  // Karabiner or browser combinations expose only Ctrl+Alt+Shift, where the Meta bit is not
  // portable. Hyper accepts either shape. Ordinary `mod` stays strict.
  if (c.hyper) {
    // Safari and Chrome occasionally omit either the synthetic Shift or the Meta bit for named
    // keys, so require the stable Ctrl+Alt pair plus one of the two high modifiers.
    if (!e.ctrlKey || !e.altKey || !(e.shiftKey || e.metaKey)) return false;
  } else {
    const wantCtrl = !!c.ctrl || (!!c.mod && !MAC);
    const wantMeta = !!c.mod && MAC;
    if (wantCtrl !== e.ctrlKey || wantMeta !== e.metaKey || !!c.alt !== e.altKey || !!c.shift !== e.shiftKey)
      return false;
  }
  // Matched by physical code where there is one: Karabiner and Hyper can transform `event.key`,
  // while `event.code` stays Enter, KeyR, ArrowDown.
  if (c.code && (c.mod || c.ctrl || c.alt || c.hyper)) return c.code === e.code;
  return c.key.toLowerCase() === (e.key || '').toLowerCase();
}

const firesInTextEntry = c => c.mod || c.ctrl || c.alt || /^F([1-9]|1[0-2])$/.test(c.key);
function findBinding(e, scope) {
  if (scope === 'overlay') return null;
  // `term` and `web` hand the keyboard to something that is not Leela, keeping only the chords
  // that get you back out.
  // A canvas is a frame with its own keyboard, so it is routed like the terminal and the browser:
  // only the chords that get you back out are taken from it.
  const allowed = (scope === 'term' || scope === 'web' || scope === 'canvas')
    ? k => k.scope === scope || k.action.startsWith('focus_') || TERM_ESCAPES.has(k.action)
    : k => k.scope === scope || k.scope === 'global';
  const guard = !EDITING_SCOPES.has(scope) && isTextEntry(e.target);
  for (const k of lee.keys) {
    if (!allowed(k)) continue;
    const chord = k.chords.find(c => chordMatches(c, e));
    if (!chord || (guard && !firesInTextEntry(chord))) continue;
    // Copy and Cut become whole-cell operations only when a notebook cell has no text selection.
    if (['cell_copy', 'cell_cut'].includes(k.action)) {
      if (lee.kind !== 'notebook') continue;
      const inEditor = e.composedPath?.().some(n => n instanceof Element && n.matches('.cm-editor'));
      const selection = curEditor() ? LeeCM.selection(curEditor()) : null;
      if (inEditor && selection?.from !== selection?.to) continue;
    }
    if (['cell_first', 'cell_last', 'cell_page_up', 'cell_page_down'].includes(k.action)
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
  if (!match) return;
  const cmd = DEFER_IN_TEXT[match.binding.action], view = cmd && textEditorOf(e);
  if (view) {
    e.preventDefault(); e.stopPropagation();
    if (LeeCM[cmd](view)) return;          // the document had something to undo
    return void leeAct(match.binding.action);
  }
  e.preventDefault(); e.stopPropagation();
  leeAct(match.binding.action);
}, true);

