/* A Word, PowerPoint or Excel file, read-only. On macOS the tab shows Quick Look's own preview in a
   frame that runs no script. The simple view is the server's cleaned HTML, with the sheet buttons and
   the row pager. Nothing here writes the file. */
const officeQ = (path, more = '') => '?path=' + encodeURIComponent(path) + more;
const OFFICE_VIEW = 'lee-office-view';   // 'simple' once a person picks the simple view
async function mountOffice(host, st) {
  host.innerHTML =
    `<div class="lee-doc lee-office"><div class="lee-doc-head"><span>${esc(compactPath(st.path))}</span>` +
    `<span class="lee-dim">read-only</span><span class="lee-spacer"></span>` +
    `<button class="lee-btn" data-office-view hidden></button>` +
    `<button class="lee-btn" data-office-open>open in default app</button>` +
    `<button class="lee-btn" data-office-copy>copy as text</button></div>` +
    `<div class="lee-doc-body lee-office-body"><div class="lee-dim">Loading…</div></div></div>`;
  const body = $('.lee-office-body', host), path = st.path, view = $('[data-office-view]', host);
  $('[data-office-open]', host).onclick = () => post('/office/open' + officeQ(path))
    .then(() => status('opened in the default app', 'ok')).catch(e => status(String(e.message || e), 'err'));
  $('[data-office-copy]', host).onclick = async () => {
    try { await navigator.clipboard.writeText((await api('/office/text' + officeQ(path))).text); status('document text copied', 'ok'); }
    catch (e) { status(String(e.message || e), 'err'); }
  };
  const show = async faithful => {
    view.hidden = true; body.className = 'lee-doc-body lee-office-body'; body.innerHTML = '<div class="lee-dim">Loading…</div>';
    let ql = null;
    if (faithful) {
      try { ql = await api('/office/quicklook' + officeQ(path)); }
      catch (e) {
        if (e.body?.kind === 'no-quicklook') return officeSimple(body, path);
        status(`${String(e.message || e)}. The simple view is shown.`, 'err');
      }
    }
    if (ql) officeQuickLook(body, ql); else await officeSimple(body, path);
    view.textContent = ql ? 'simple view' : 'Quick Look view'; view.hidden = false;
    view.onclick = () => { localStorage.setItem(OFFICE_VIEW, ql ? 'simple' : 'quicklook'); show(!ql); };
  };
  await show(localStorage.getItem(OFFICE_VIEW) !== 'simple');
}
//: Quick Look's pages in a frame with no script and no links; a workbook gets one button for each sheet.
function officeQuickLook(body, ql) {
  body.className = 'lee-doc-body lee-office-ql';
  const src = pg => `/office/ql/${encodeURIComponent(ql.token)}/${encodeURIComponent(pg.src)}`;
  const note = document.createElement('div'), frame = document.createElement('iframe');
  note.className = 'lee-dim lee-office-clip';
  note.textContent = 'Quick Look shows only the first 4096 rows of a sheet. The simple view shows all rows.';
  frame.className = 'lee-office-frame'; frame.setAttribute('sandbox', 'allow-same-origin'); frame.title = 'Quick Look preview';
  const pick = i => {
    frame.src = src(ql.pages[i]); note.hidden = !ql.pages[i].clipped;
    for (const [j, x] of $$('[data-sheet-tab]', body).entries()) x.setAttribute('aria-selected', String(j === i));
  };
  body.replaceChildren();
  if (ql.pages.length > 1) {
    const bar = document.createElement('div');
    bar.className = 'lee-sheet-tabs'; bar.setAttribute('role', 'tablist');
    ql.pages.forEach((pg, i) => {
      const b = document.createElement('button');
      b.className = 'lee-btn'; b.setAttribute('role', 'tab'); b.dataset.sheetTab = i;
      b.textContent = pg.name || `Sheet ${i + 1}`; b.onclick = () => pick(i);
      bar.append(b);
    });
    body.append(bar);
  }
  // Quick Look draws slides at their size in points; scale them to the tab's width, never above it.
  const fit = () => {
    const d = frame.contentDocument, s = d?.querySelector('div.slide');
    if (s) d.body.style.zoom = String(Math.min(1, (frame.clientWidth - 32) / (s.offsetWidth + 16)));
  };
  frame.onload = fit; new ResizeObserver(fit).observe(frame);
  body.append(note, frame); pick(0);
}
async function officeSimple(body, path) {
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
