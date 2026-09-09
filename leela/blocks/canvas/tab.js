/* A canvas as an IDE tab: the page `/canvas` serves, in a frame of its own because it ships its
 * own stylesheet and globals. Same-origin, so the two still talk. */

function canvasFrame() { return $('#editor iframe.lee-canvasframe'); }
function canvasWindow() { const f = canvasFrame(); return f && f.contentWindow; }

/* A frame owns its keyboard, so no IDE chord reached the router. Modified chords are forwarded
 * and resolved in the `canvas` scope; bare keys stay in the document. */
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
  // The page's state is a `const`, not a window property, so ask what it drew.
  setTimeout(() => {
    if (canvasWindow()?.document?.querySelector('#cv-doc .cv-brick')) return;
    note.hidden = false;
    note.textContent = 'the canvas page did not load — open /canvas directly to see why';
  }, 8000);
  setScope('canvas');
}
window.mountCanvas = mountCanvas;

/* `saveTab` reaches for a CodeMirror document; a canvas has none. The page owns its own save,
   revision check included. */
async function saveCanvasTab(quiet) {
  const win = canvasWindow();
  if (!win || !win.cvSave) { status('the canvas is still loading', 'err'); return false; }
  try { await win.cvSave(); if (!quiet) status('saved ' + (lee.path.split('/').pop() || 'canvas'), 'ok'); return true; }
  catch (e) { status(String(e.message || e), 'err'); return false; }
}
window.saveCanvasTab = saveCanvasTab;

/* An ask from a canvas runs in the agent pane. Same agent, same tools; what the margin added was
   a thinner turn UI that rendered its approvals where the asker could not see them. */
async function canvasAskPane({question, brickId = '', selection = '', path = ''}) {
  const box = $('#agentprompt');
  if (!box || !question?.trim()) return false;
  const doc = path || lee.path || '';
  if (selection.trim()) {
    // A brick is a range of one document, so it needs no attachment kind of its own.
    lee.agentSelections.push({
      label: `${(doc.split('/').pop() || 'canvas')}${brickId ? ' · ' + brickId : ''}`,
      path: doc,
      ref: {kind: 'selection', path: doc, from: 1, to: 1, text: selection},
    });
  }
  const where = brickId ? `\n\n(asked from brick \`${brickId}\` of the open canvas)` : '';
  box.value = (box.value.trim() ? box.value.trim() + '\n\n' : '') + question.trim() + where;
  leePane('right', true); leeRight('agent');
  if (typeof paintAgentAttachments === 'function') paintAgentAttachments();
  await sendAgent();
  return true;
}
window.canvasAskPane = canvasAskPane;

/* Repaint from the store, not `fresh`: reopening builds a new `Open` and drops the namespace and
   the trust the person granted. */
function canvasRepaint() {
  const win = canvasWindow();
  if (win && typeof win.cvOpen === 'function' && win.cv?.path) win.cvOpen(win.cv.path);
}
window.canvasRepaint = canvasRepaint;
