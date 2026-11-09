/* Create mode: the story tab draws one rupaka scene in place (a shadow root, no frame). The page and the agent write the same story.json, so the tab polls its revision. */
const createState = {slug: '', rev: '', inner: null, timer: 0, pending: 0, sending: false, latest: null};
const createSay = (host, text, bad = true) => { const p = $('.lee-create-say', host); if (p) { p.textContent = text || ''; p.classList.toggle('err', !!text && bad); } };
async function createSend(host) {
  if (createState.sending || !createState.latest) return;
  const state = createState.latest, slug = createState.slug; createState.latest = null; createState.sending = true;
  try {
    const r = await fetch('/create/state', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({slug, state})}), d = await r.json().catch(() => ({}));
    if (r.ok) { createState.rev = d.rev; createSay(host, ''); } else createSay(host, d.error || 'The scene could not be saved.');
  } catch (_) { createSay(host, 'The scene could not be saved. Check that Leela is running.'); }
  finally { createState.sending = false; if (createState.latest) createSend(host); else createState.pending = 0; }
}
function createSave(host, state) { createState.latest = state; createState.pending = 1; clearTimeout(createState.saveTimer); createState.saveTimer = setTimeout(() => createSend(host), 120); }
async function createLoad(host, stage, first) {
  const r = await fetch(`/create/scene?slug=${encodeURIComponent(createState.slug)}${first ? '' : '&have=' + encodeURIComponent(createState.rev)}`), d = await r.json().catch(() => ({}));
  if (!r.ok || !d.ok) { createSay(host, d.error || 'The scene could not be read.'); return false; }
  if (d.same) return true;
  if (first) {
    const e = rupakaDraw(d.spec, null, null, null, {askable: false, save: s => createSave(host, s)});
    await e.done;
    if (!e.ok) { createSay(host, `The scene could not be drawn: ${e.err?.message || e.err}`); return false; }
    stage.replaceChildren(e.host); createState.inner = e.inner;
  } else if (!createState.pending && !createState.sending && createState.inner) window.Rupaka.set(createState.inner, d.state);
  createState.rev = d.rev;
  return true;
}
async function mountStory(host, st) {
  clearInterval(createState.timer);
  Object.assign(createState, {slug: st.project || '', rev: '', inner: null, pending: 0, latest: null});
  await htmx.ajax('GET', '/create/page?slug=' + encodeURIComponent(createState.slug), {target: host, swap: 'innerHTML'});
  const stage = $('.lee-create-stage', host);
  if (!stage) return;
  host.onclick = e => {
    const b = e.target.closest?.('[data-create]');
    if (b?.dataset.create === 'new') leeCreateNew();
    if (b?.dataset.create === 'export') Object.assign(document.createElement('a'), {href: `/create/export?slug=${encodeURIComponent(createState.slug)}`, download: `${createState.slug}.html`}).click();
  };
  if (!await createLoad(host, stage, true)) return;
  createState.timer = setInterval(() => {
    if (!stage.isConnected) return clearInterval(createState.timer);
    if (!document.hidden) createLoad(host, stage, false).catch(() => {});
  }, 1500);
}
registerTabMount('story', mountStory);
const leeCreateOpen = () => htmx.ajax('POST', '/create/tab/open', {target: '#tabbar', swap: 'outerHTML'}).then(() => mountTab());
async function leeCreateNew() {
  if (lee.mode !== 'create' && !await leeModeSet('create')) return;
  await htmx.ajax('POST', '/create/new', {target: '#tabbar', swap: 'outerHTML'});
  await mountTab();
}
Object.assign(window, {leeCreateOpen, leeCreateNew});
