const DICTATE_BOX = 'textarea, input:not([type]), input[type=text], input[type=search]';
async function leeDictate() {
  if (window.abhyasaDict) return abhyasaMic(window.abhyasaDict.btn);
  const act = document.activeElement, box = act?.matches?.(DICTATE_BOX) ? act : $('#agentprompt');
  if (!box) return status('Click a text box first, then run Dictate.', 'err');
  const post = u => fetch(u, {method: 'POST'}).then(r => r.json()).catch(() => ({ok: false, say: 'Leela could not reach the speech service.'}));
  const [ready, s] = await Promise.all([post('/speech/ready'), fetch('/learn/abh-surface?path=/dictate').then(r => r.json()).catch(() => ({files: []}))]);
  if (!ready.ok) return status(ready.say, 'err');
  if (!box.id) box.id = 'box-' + Math.random().toString(36).slice(2, 8);
  const b = Object.assign(document.createElement('button'), {type: 'button', id: 'mic-dictate', hidden: true, innerHTML: '<span class="say"></span>'});
  Object.assign(b.dataset, {into: box.id, concept: '', vad: s.files[0], start: '/speech/start', seg: '/speech/seg/', stop: '/speech/stop/', events: '/speech/events/'});
  document.body.append(b);
  let on = false;
  const watch = new MutationObserver(() => {
    if (b.title) { status(b.title, 'err'); b.title = ''; }
    const live = b.classList.contains('on') || b.classList.contains('busy');
    if (live && !on) status('Dictating. Run Dictate again to stop.', 'ok');
    if (!live && on) { watch.disconnect(); b.remove(); }
    on = live;
  });
  watch.observe(b, {attributes: true, attributeFilter: ['class', 'title']});
  abhyasaMic(b);
}
window.leeDictate = leeDictate;
