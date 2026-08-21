/* ------------------------------------------------------------------ keymap */
const MAC = /Mac|iPhone|iPad|iPod/.test(navigator.userAgentData?.platform || navigator.platform || '');
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
  // This panel is a glanceable contextual cheat sheet, not the full keymap. Commands
  // marked help-only stay in the searchable help/settings surfaces instead of pushing the
  // file tree and editor off screen when the editor scope has dozens of actions.
  const local = lee.keys.filter(k => k.scope === scope && k.label && k.key && ['footer','toast'].includes(k.show)).slice(0, 8);
  const global = lee.keys.filter(k => k.scope === 'global' && k.show === 'toast' && k.label && k.key).slice(0, 4);
  const rows = local.concat(global);
  if (tag) tag.textContent = scope && scope !== 'global' ? `· ${scope}` : '';
  host.innerHTML = rows.length ? rows.map(k =>
    `<div class="lee-krow${k.scope === scope ? ' contextual' : ''}"><kbd>${esc(displayChord(k.key))}</kbd>` +
    `<span>${esc(k.label)}</span></div>`).join('') : '<div class="lee-dim">no keys in this context</div>';
}

/* One application-level keyboard router owns every app command. CodeMirror owns editing
 * commands and xterm owns pty input, but neither gets a duplicate copy of this map. A
 * capturing listener is intentional: an accepted app command is resolved before an editor
 * can consume it; an unaccepted event is untouched and continues normally. */
const TERM_ESCAPES = new Set(['help', 'quit', 'palette', 'settings', 'toggle_left', 'toggle_right']);
const EDITING_SCOPES = new Set(['editor', 'exec', 'agent', 'term']);

function eventContext(e) {
  const path = e.composedPath ? e.composedPath() : [e.target];
  const inPath = selector => path.some(n => n instanceof Element && n.matches(selector));
  // Overlays own their keyboard while open. Their local handler receives the event after
  // this router leaves it alone; commands behind a dialog must never fire accidentally.
  if (inPath('.lee-modal, .lee-ctxmenu')) return 'overlay';
  if (inPath('#termwrap, .xterm')) return 'term';
  // A live page wants its own keyboard as much as a shell does -- Gmail's `j`, a site's `/`
  // search -- so the inline browser is routed exactly like the terminal, and for the same
  // reason. It has to come before `#editor`, which contains it.
  if (inPath('.lee-webview')) return 'web';
  if (inPath('#agentprompt, .lee-agent')) return 'agent';
  if (inPath('#execbox, .lee-exec')) return 'exec';
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
  // macOS reports Caps Lock remapped to Hyper as all four modifiers. Other platforms and
  // some Karabiner/browser combinations expose only Ctrl+Alt+Shift—the Command/Meta bit
  // is not portable there. Hyper explicitly accepts either shape; ordinary `mod` remains
  // strict, so regular shortcuts do not become ambiguous.
  if (c.hyper) {
    // Hyper remappers agree on Ctrl+Alt but Safari/Chrome occasionally omit either the
    // synthetic Shift or Meta bit for named keys. Require the stable pair plus one of the
    // two high modifiers; this accepts both browser shapes without colliding with normal
    // two-modifier shortcuts.
    if (!e.ctrlKey || !e.altKey || !(e.shiftKey || e.metaKey)) return false;
  } else {
    const wantCtrl = !!c.ctrl || (!!c.mod && !MAC);
    const wantMeta = !!c.mod && MAC;
    if (wantCtrl !== e.ctrlKey || wantMeta !== e.metaKey || !!c.alt !== e.altKey || !!c.shift !== e.shiftKey)
      return false;
  }
  // Every modified shortcut is matched by physical code when available. Karabiner/Hyper
  // can transform `event.key` (not just Option-printable characters), while `event.code`
  // remains Enter, KeyR, ArrowDown, and so on.
  if (c.code && (c.mod || c.ctrl || c.alt || c.hyper)) return c.code === e.code;
  return c.key.toLowerCase() === (e.key || '').toLowerCase();
}

const firesInTextEntry = c => c.mod || c.ctrl || c.alt || /^F([1-9]|1[0-2])$/.test(c.key);
function findBinding(e, scope) {
  if (scope === 'overlay') return null;
  // `term` and `web` both hand the keyboard to something that is not Leela, keeping only the
  // chords that get you back out again.
  const allowed = (scope === 'term' || scope === 'web')
    ? k => k.scope === scope || k.action.startsWith('focus_') || TERM_ESCAPES.has(k.action)
    : k => k.scope === scope || k.scope === 'global';
  const guard = !EDITING_SCOPES.has(scope) && isTextEntry(e.target);
  for (const k of lee.keys) {
    if (!allowed(k)) continue;
    const chord = k.chords.find(c => chordMatches(c, e));
    if (!chord || (guard && !firesInTextEntry(chord))) continue;
    // Standard Copy/Cut become whole-cell operations only when a notebook cell has no
    // text selection. Selected source keeps the browser/CodeMirror clipboard semantics.
    if (['cell_copy', 'cell_cut'].includes(k.action)) {
      if (lee.kind !== 'notebook') continue;
      const inEditor = e.composedPath?.().some(n => n instanceof Element && n.matches('.cm-editor'));
      const selection = curEditor() ? LeeCM.selection(curEditor()) : null;
      if (inEditor && selection?.from !== selection?.to) continue;
    }
    // Cmd+F only belongs to Leela when the document is a notebook, where one CodeMirror panel
    // would search one cell. Anywhere else the event is left alone and the editor's own panel opens.
    if (['cell_first', 'cell_last', 'cell_page_up', 'cell_page_down', 'find_in_file'].includes(k.action)
        && lee.kind !== 'notebook') continue;
    return {binding: k, chord};
  }
  return null;
}

window.addEventListener('keydown', e => {
  const scope = eventContext(e), match = findBinding(e, scope);
  // Kept on `lee` deliberately: the key editor and DevTools can distinguish "Chrome did
  // not deliver it" from "the router rejected it" using the last real event.
  lee.lastKeyEvent = {key: e.key, code: e.code, ctrl: e.ctrlKey, alt: e.altKey,
                      shift: e.shiftKey, meta: e.metaKey, scope,
                      action: match?.binding.action || '', trusted: e.isTrusted};
  if (!match) return;
  e.preventDefault(); e.stopPropagation();
  leeAct(match.binding.action);
}, true);

