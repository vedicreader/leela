/* A canvas as an IDE tab. The page is the one `/canvas` already serves, in a frame of its own:
 * it ships its own stylesheet and declares its own globals, and inlining either would collide
 * with the IDE's. The frame is same-origin, so the two still talk. */

function canvasFrame() { return $('#editor iframe.lee-canvasframe'); }
function canvasWindow() { const f = canvasFrame(); return f && f.contentWindow; }

/* A frame owns its keyboard: an event inside one never reaches the parent's router, so every IDE
 * chord died while a canvas had focus. Modified chords are forwarded and resolved in the `canvas`
 * scope, which keeps only the ones that get you back out. Bare keys stay in the document. */
function forwardCanvasKeys(win) {
  win.document.addEventListener('keydown', e => {
    if (!(e.metaKey || e.ctrlKey || e.altKey)) return;
    const ev = new KeyboardEvent('keydown', {key: e.key, code: e.code, ctrlKey: e.ctrlKey,
      altKey: e.altKey, shiftKey: e.shiftKey, metaKey: e.metaKey, bubbles: false, cancelable: true});
    window.dispatchEvent(ev);
    if (ev.defaultPrevented) { e.preventDefault(); e.stopPropagation(); }
  }, true);
}

function mountCanvas(host, st) {
  const url = `/canvas?embed=1&path=${encodeURIComponent(st.path || '')}` +
              `&theme=${encodeURIComponent(lee.theme || 'light')}`;
  host.innerHTML = `<div class="lee-doc lee-canvasdoc">` +
    `<iframe class="lee-canvasframe" src="${esc(url)}" title="${esc(st.title || 'canvas')}"></iframe>` +
    `<div class="lee-canvasnote lee-dim" hidden></div></div>`;
  const frame = $('iframe', host), note = $('.lee-canvasnote', host);
  frame.addEventListener('load', () => {
    try { forwardCanvasKeys(frame.contentWindow); }
    catch (e) { note.hidden = false; note.textContent = 'the canvas loaded but its keyboard is its own: ' + e; }
  });
  // A frame that never loads leaves an empty pane and no reason for it. The page's own state is a
  // `const`, which is not a property of its window, so what is asked for is what it drew.
  setTimeout(() => {
    if (canvasWindow()?.document?.querySelector('#cv-doc .cv-brick')) return;
    note.hidden = false;
    note.textContent = 'the canvas page did not load — open /canvas directly to see why';
  }, 8000);
  setScope('canvas');
}
window.mountCanvas = mountCanvas;

/* `saveTab` reaches for a CodeMirror document, and a canvas has none. The page owns its own save,
   including the revision check that refuses a stale write, so the chord is handed to it. */
async function saveCanvasTab(quiet) {
  const win = canvasWindow();
  if (!win || !win.cvSave) { status('the canvas is still loading', 'err'); return false; }
  try { await win.cvSave(); if (!quiet) status('saved ' + (lee.path.split('/').pop() || 'canvas'), 'ok'); return true; }
  catch (e) { status(String(e.message || e), 'err'); return false; }
}
window.saveCanvasTab = saveCanvasTab;
