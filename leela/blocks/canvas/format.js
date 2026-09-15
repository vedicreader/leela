/* The bar that follows a text selection: the three marks that matter, a link, and the helper.
 * "Ask AI" is the same turn the margin runs; what it adds is the span you had selected. */

const MARKS = [
  {key: 'b', label: 'B', title: 'bold (mod+b)', wrap: '**', style: 'font-weight:700'},
  {key: 'i', label: 'I', title: 'italic (mod+i)', wrap: '*', style: 'font-style:italic'},
  {key: 'e', label: '‹›', title: 'code (mod+e)', wrap: '`', style: 'font-family:var(--cv-mono)'}];

function cvFormatBar() {
  const sel = getSelection();
  const text = String(sel || '').trim();
  const host = sel?.anchorNode?.parentElement?.closest('.cv-brick.cv-text');
  if (!text || !host || !sel.rangeCount) return cvHideFormat();
  const r = sel.getRangeAt(0).getBoundingClientRect();
  if (!r.width && !r.height) return cvHideFormat();
  let bar = $$('#cv-format');
  if (!bar) {
    bar = document.createElement('div');
    bar.id = 'cv-format'; bar.className = 'cv-format';
    bar.innerHTML = MARKS.map(m => `<button class="cv-fbtn" data-mark="${m.key}" title="${m.title}" ` +
        `style="${m.style}">${m.label}</button>`).join('') +
      `<button class="cv-fbtn" data-mark="link" title="link">🔗</button>` +
      '<span class="cv-fsep"></span>' +
      '<button class="cv-fbtn ai" data-ask="1">✦ Ask AI</button>';
    document.body.appendChild(bar);
    bar.onmousedown = ev => ev.preventDefault();
    bar.onclick = ev => {
      const b = ev.target.closest('.cv-fbtn'); if (!b) return;
      if (b.dataset.ask) { cvHideFormat(); return cvInlineAsk(); }
      cvMark(b.dataset.mark);
    };
  }
  bar.style.left = Math.max(8, Math.min(r.left + r.width / 2 - bar.offsetWidth / 2, innerWidth - 260)) + 'px';
  bar.style.top = (r.top + scrollY - bar.offsetHeight - 8) + 'px';
  bar.hidden = false;
}

function cvHideFormat() { const b = $$('#cv-format'); if (b) b.hidden = true; }

//: Marks are applied to the markdown, not to the rendered HTML: the file is what is true, and
//: `document.execCommand('bold')` would put a `<b>` in that `cvHtmlToMd` has to guess about.
function cvMark(kind) {
  const sel = getSelection();
  const text = String(sel || '');
  const host = sel?.anchorNode?.parentElement?.closest('.cv-brick.cv-text');
  if (!text.trim() || !host) return;
  const b = cvBrick(host.dataset.id); if (!b) return;
  const nth = cvOccurrence($$('.cv-prose', host), sel, text);
  const now = kind === 'link' ? cvLink(text) : cvToggleWrap(text, MARKS.find(m => m.key === kind).wrap);
  if (now === null) return;
  cvHideFormat();
  cvOp({op: 'replace_selection', id: b.id, was: text, nth, text: now});
}

function cvToggleWrap(text, w) {
  return text.startsWith(w) && text.endsWith(w) && text.length > 2 * w.length
    ? text.slice(w.length, -w.length) : w + text + w;
}

function cvLink(text) {
  const href = prompt('link to', 'https://');
  return href ? `[${text}](${href})` : null;
}

document.addEventListener('selectionchange', () => {
  clearTimeout(cvFormatBar.t);
  cvFormatBar.t = setTimeout(cvFormatBar, 90);
});
document.addEventListener('scroll', cvHideFormat, true);
