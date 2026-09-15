/* One popover, used by the slash menu, the palette and the block menu. Items are grouped, filtered
 * as you type, and driven by the keyboard. Groups sort by `N_Name`, which is BlockSuite's trick for
 * keeping the order of a menu out of the order of the code that builds it. */
const cvPop = {el: null, items: [], shown: [], at: 0, pick: null, query: '', onQuery: null};

const cvFuzzy = (hay, q) => {          // every character of the query, in order
  hay = hay.toLowerCase(); let i = 0;
  for (const c of q) { i = hay.indexOf(c, i); if (i < 0) return false; i++; }
  return true;
};
const cvScore = (name, q) => {
  const n = name.toLowerCase();
  return n === q ? 100 : n.startsWith(q) ? 60 : n.includes(q) ? 30 : cvFuzzy(n, q) ? 10 : 0;
};
const cvGroupOf = it => (it.group || '9_More').split('_')[1] || 'More';

function cvOpenMenu(items, x, y, pick, {query = false, width = 300, empty = 'nothing here'} = {}) {
  cvCloseMenu();
  const el = document.createElement('div');
  el.className = 'cv-pop'; el.style.width = width + 'px'; el.setAttribute('role', 'listbox');
  document.body.appendChild(el);
  Object.assign(cvPop, {el, items, pick, query: '', at: 0, empty});
  cvPaintMenu();
  const box = el.getBoundingClientRect();
  el.style.left = Math.max(8, Math.min(x, innerWidth - box.width - 8)) + 'px';
  el.style.top = (y + box.height > innerHeight - 8 ? Math.max(8, y - box.height - 26) : y) + 'px';
  el.onmousedown = ev => ev.preventDefault();
  el.onclick = ev => {
    const b = ev.target.closest('.cv-item'); if (!b) return;
    cvChoose(cvPop.shown[+b.dataset.i]);
  };
  setTimeout(() => document.addEventListener('pointerdown', cvOutside, true), 0);
  return el;
}

function cvPaintMenu() {
  const {el, items, query} = cvPop;
  const q = query.toLowerCase();
  let shown = q ? items.filter(it => cvScore(it.name, q) || (it.alias || []).some(a => cvScore(a, q))) : items.slice();
  if (q) shown.sort((a, b) => cvScore(b.name, q) - cvScore(a.name, q));
  cvPop.shown = shown;
  cvPop.at = Math.min(cvPop.at, Math.max(0, shown.length - 1));
  if (!shown.length) { el.innerHTML = `<div class="none">${cvEsc(cvPop.empty)}</div>`; return; }
  let html = '', group = null;
  shown.forEach((it, i) => {
    const g = q ? null : cvGroupOf(it);
    if (g && g !== group) { html += `<div class="grp">${cvEsc(g)}</div>`; group = g; }
    html += `<button class="cv-item" role="option" data-i="${i}" aria-selected="${i === cvPop.at}">` +
      `<span class="cv-ico">${it.icon || '·'}</span><span class="txt">` +
      `<span class="nm">${cvEsc(it.name)}</span>` +
      (it.hint ? `<span class="hint">${cvEsc(it.hint)}</span>` : '') + '</span></button>';
  });
  el.innerHTML = html;
  el.querySelector('[aria-selected=true]')?.scrollIntoView({block: 'nearest'});
}

//: A pointer inside the menu is a choice, not a dismissal. Closing on every pointerdown would take
//: the item out from under the click that was picking it.
function cvOutside(ev) { if (!cvPop.el?.contains(ev.target)) cvCloseMenu(); }

function cvChoose(it) { const {pick} = cvPop; cvCloseMenu(); if (it && pick) pick(it); }
function cvMenuOpen() { return !!cvPop.el }
function cvCloseMenu() {
  document.removeEventListener('pointerdown', cvOutside, true);
  cvPop.el?.remove();
  cvPop.el = null; cvPop.onQuery?.(null); cvPop.onQuery = null;
}

//: The menu owns the keys while it is up, including the ones that edit its query, so the block
//: underneath never sees them.
function cvMenuKey(ev) {
  if (!cvPop.el || ev.cvSeen) return false;
  ev.cvSeen = true;                        // the block's handler and the document's both call this
  const k = ev.key;
  if (k === 'Escape') { ev.preventDefault(); cvCloseMenu(); return true; }
  if (k === 'ArrowDown' || k === 'ArrowUp') {
    ev.preventDefault();
    const n = cvPop.shown.length; if (!n) return true;
    cvPop.at = (cvPop.at + (k === 'ArrowDown' ? 1 : n - 1)) % n;
    cvPaintMenu(); return true;
  }
  if (k === 'Enter' || k === 'Tab') { ev.preventDefault(); cvChoose(cvPop.shown[cvPop.at]); return true; }
  if (k === 'Backspace') {
    if (!cvPop.query) { cvCloseMenu(); return false; }
    ev.preventDefault(); cvPop.query = cvPop.query.slice(0, -1); cvPop.at = 0; cvPaintMenu();
    cvPop.onQuery?.(cvPop.query); return true;
  }
  if (k.length === 1 && !ev.metaKey && !ev.ctrlKey) {
    if (k === ' ' && !cvPop.query) { cvCloseMenu(); return false; }
    ev.preventDefault(); cvPop.query += k; cvPop.at = 0; cvPaintMenu();
    cvPop.onQuery?.(cvPop.query);
    if (!cvPop.shown.length && cvPop.query.length > 12) cvCloseMenu();
    return true;
  }
  return false;
}
