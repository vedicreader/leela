/* A Word, PowerPoint or Excel file, read-only. The server sends the document as cleaned HTML; this
   file adds the head bar, the sheet buttons and the row pager. Nothing here writes the file. */
const officeQ = (path, more = '') => '?path=' + encodeURIComponent(path) + more;
async function mountOffice(host, st) {
  host.innerHTML =
    `<div class="lee-doc lee-office"><div class="lee-doc-head"><span>${esc(compactPath(st.path))}</span>` +
    `<span class="lee-dim">read-only</span><span class="lee-spacer"></span>` +
    `<button class="lee-btn" data-office-open>open in default app</button>` +
    `<button class="lee-btn" data-office-copy>copy as text</button></div>` +
    `<div class="lee-doc-body lee-office-body"><div class="lee-dim">Loading…</div></div></div>`;
  const body = $('.lee-office-body', host), path = st.path;
  $('[data-office-open]', host).onclick = () => post('/office/open' + officeQ(path))
    .then(() => status('opened in the default app', 'ok')).catch(e => status(String(e.message || e), 'err'));
  $('[data-office-copy]', host).onclick = async () => {
    try { await navigator.clipboard.writeText((await api('/office/text' + officeQ(path))).text); status('document text copied', 'ok'); }
    catch (e) { status(String(e.message || e), 'err'); }
  };
  try { body.innerHTML = (await api('/office/view' + officeQ(path))).html; }
  catch (e) { body.innerHTML = `<div class="lee-err">${esc(String(e.message || e))}</div>`; return; }
  // A link in a document never replaces the IDE page.
  for (const a of $$('a[href]', body)) { a.target = '_blank'; a.rel = 'noopener noreferrer'; }
  officeSheets(body, path);
}
function officeSheets(body, path) {
  const sheets = $$('.lee-sheet', body);
  if (!sheets.length) return;
  const bar = document.createElement('div');
  bar.className = 'lee-sheet-tabs'; bar.setAttribute('role', 'tablist');
  sheets.forEach((s, i) => {
    const b = document.createElement('button');
    b.className = 'lee-btn'; b.setAttribute('role', 'tab'); b.dataset.sheetTab = i;
    b.textContent = $('.lee-sheet-name', s)?.textContent || `Sheet ${i + 1}`;
    b.onclick = () => { sheets.forEach((x, j) => x.hidden = j !== i); $$('[data-sheet-tab]', bar).forEach((x, j) => x.setAttribute('aria-selected', String(j === i))); };
    bar.append(b);
  });
  body.prepend(bar);
  bar.firstChild.setAttribute('aria-selected', 'true');
  for (const more of $$('.lee-sheet-more', body)) {
    const b = document.createElement('button');
    b.className = 'lee-btn'; b.textContent = 'show more rows';
    b.onclick = async () => {
      const s = more.closest('.lee-sheet'); b.disabled = true;
      try {
        const d = await api('/office/rows' + officeQ(path, `&sheet=${s.dataset.sheet}&start=${more.dataset.next}`));
        $('.lee-sheet-table tbody', s).insertAdjacentHTML('beforeend', d.html);
        more.dataset.next = String(+more.dataset.next + d.count);
        $('span', more).textContent = `Showing the first ${more.dataset.next} rows.`;
        if (!d.more) more.remove(); else b.disabled = false;
      } catch (e) { b.disabled = false; status(String(e.message || e), 'err'); }
    };
    more.append(b);
  }
}
