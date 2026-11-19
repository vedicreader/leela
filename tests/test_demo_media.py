"Decision 28: the media of a Rupaka demo come from `vault.assets()/demo-media/<sha256>.<ext>`, at `/leemedia/` on Leela's own origin, and each element Leela mounts a demo in names that route as its media base."
import shutil, subprocess
from pathlib import Path
import pytest
from test_lesson_run import lesson_client

ROOT, BASE = Path(__file__).parents[1], '/leemedia/'

@pytest.fixture
def media(lesson_client, monkeypatch, tmp_path):
    "The client, the vault's demo media store and the name of one sound in it."
    from rupaka.media import import_asset
    client, ws, _, _ = lesson_client
    monkeypatch.setattr(ws.memory, 'path', tmp_path/'learning.db')
    store = ws.memory._store('learning').assets('demo-media')
    (tmp_path/'tha.wav').write_bytes(b'RIFF tha sound')
    return client, store, import_asset(tmp_path/'tha.wav', store)[6:]

def test_the_media_route_serves_a_stored_file_with_its_type_nosniff_a_csp_and_ranges(media):
    from leela.core.web import MEDIA_URL
    from leela.blocks.learn.app import MEDIA_TYPES
    from rupaka.spec import MEDIA_EXTS
    client, store, name = media
    assert MEDIA_URL == BASE and set(MEDIA_TYPES) == {x for xs in MEDIA_EXTS.values() for x in xs}, 'each file type of rupaka has its media type'
    r = client.get(BASE + name)
    assert (r.status_code, r.content, r.headers['content-type']) == (200, b'RIFF tha sound', 'audio/wav')
    assert (r.headers['x-content-type-options'], r.headers['content-security-policy']) == ('nosniff', "default-src 'none'")
    part = client.get(BASE + name, headers={'Range': 'bytes=0-3'})
    assert (part.status_code, part.content) == (206, b'RIFF'), 'audio and video can seek'

def test_the_media_route_refuses_a_bad_name_a_path_escape_and_a_missing_file(media):
    client, store, name = media
    assert client.get(BASE + name).status_code == 200, 'the route serves the good name, so each 404 below is a refusal'
    (store.parent/name).write_bytes(b'not in the store')
    out = 'd' * 64 + '.wav'
    (store/out).symlink_to(store.parent/name)   # a name that passes, for a file outside the store
    for f in ('tha.wav', name[:-4] + '.exe'): (store/f).write_bytes(b'RIFF')   # files in the store whose names do not pass
    for bad in (name.upper(), name[:-4] + '.exe', 'tha.wav', out, f'..%2F{name}', f'%2E%2E%2F{name}', f'..%2F..%2Fassets%2F{name}', 'c' * 64 + '.wav'):
        r = client.get(BASE + bad)
        assert r.status_code == 404 and b'RIFF' not in r.content and b'not in the store' not in r.content, bad

MOUNTS = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const [core, cells, lesson, slides, base] = process.argv.slice(1);
const cut = (f, a, b) => { const s = fs.readFileSync(f, 'utf8'), i = s.indexOf(a), j = s.indexOf(b, i); assert.ok(i >= 0 && j > i, `${f}: ${a}`); return s.slice(i, j); };
class El {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.style = {}; this.parent = null; this.textContent = ''; }
  append(...n) { for (const c of n) { c.parent = this; this.children.push(c); } }
  prepend(...n) { this.append(...n); }
  after(c) { this.parent.append(c); }
  replaceChildren(...n) { this.children = []; this.append(...n); }
  attachShadow() { this.shadowRoot = new El('#shadow'); this.shadowRoot.host = this; return this.shadowRoot; }
  setAttribute() {}
  querySelectorAll() { return []; }
}
const seen = [], Rupaka = {mount(el, spec) { seen.push([spec.id, el.dataset.rkMedia, el.parent?.tag]); el.rupaka = {st: {gate: {}, log: []}, get: () => 1, on() {}}; },
  set() {}, state: () => ({}), options: () => [], settle: () => true};
const world = extra => { const c = {document: {createElement: t => new El(t), head: {appendChild() {}}, querySelector: () => null}, window: {Rupaka}, Rupaka, console, ...extra}; vm.createContext(c); return c; };
(async () => {
  const ide = world({$: () => null, fetch: async () => ({ok: true, text: async () => ''}), lessonActive: new Map()});
  vm.runInContext(cut(core, 'const RUPAKA_MIME', 'const katexLoad'), ide);
  vm.runInContext(cut(lesson, 'function lessonTransferMount', '//: The answer to a new case'), ide);
  vm.runInContext(cut(cells, 'function rupakaTrials', 'const mdPaint'), ide);
  const e = ide.rupakaDraw({id: 'drawn', blocks: []}); await e.done;
  assert.equal(e.err, null); assert.equal(e.inner.parent, e.host.shadowRoot, 'the demo mounts inside the shadow root');
  e.host.isConnected = true; delete e.inner.dataset.rkMedia; e.spec = {id: 'revived', blocks: []};
  e.inner.querySelectorAll = () => [{getContext: () => ({isContextLost: () => true})}];
  ide.rupakaRevive(e);
  ide.lessonTransferMount(e.host, {key: 'k'}, {id: 'new-case', blocks: []});
  const parent = new El('div'), inner = new El('div'); parent.append(inner); inner.rupaka = {st: {gate: {g: 'done'}}, on() {}};
  const entry = {src: 'h', options: {save() {}}}, record = {trials: [{n: 1, src: 'h', inputs: {}}]};
  ide.rupakaTrials(inner, {id: 'trial', blocks: []}, entry, () => ({extra: {rupaka: {trial: record}}})); entry.paint?.();
  const room = world({slidesRk() {}, slidesWhy() {}});
  vm.runInContext(cut(slides, 'function slidesMount', '//: Fit the 1280'), room);
  room.slidesMount({id: 'slide', blocks: []});
  const got = Object.fromEntries(seen.map(([id, m]) => [id, m]));
  assert.deepStrictEqual(got, {drawn: base, revived: base, 'new-case': base, trial: base, slide: base}, JSON.stringify(got));
  assert.ok(seen.filter(([id]) => id !== 'trial').every(([, , p]) => p !== undefined));
})().catch(e => { console.error(e); process.exitCode = 1; });
'''

def test_each_mount_of_a_demo_names_the_media_route_on_the_element_it_mounts_in():
    "rupaka reads `closest('[data-rk-media]')` from the mount element, which stops at a shadow root: the IDE draw, its revive, the new case, the trials copy and the room slide each carry it."
    node = shutil.which('node')
    if not node: pytest.skip('node is not installed')
    nb = ROOT/'leela'/'blocks'/'nb'
    for core, slides in ((ROOT/'leela/static/js/core.js', nb/'slides.js'), (ROOT/'leela/static/lee-core.js', ROOT/'leela/static/lee-slides.js')):
        r = subprocess.run([node, '-e', MOUNTS, str(core), str(nb/'cells.js' if core.name == 'core.js' else core), str(nb/'lesson.js' if core.name == 'core.js' else core), str(slides), BASE],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, (core.name, r.stderr)
