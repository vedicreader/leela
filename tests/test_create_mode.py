"Create mode: it registers, it switches under the same busy rules as Learn, its tab opens a scene, the agent's two scene tools work, a page exports, and the mode survives a reload."
import json
import tempfile
from pathlib import Path

import pytest
from starlette.routing import Mount
from starlette.testclient import TestClient

from leela.app import ide_app
from leela.blocks.agent.threads import TurnError
from leela.blocks.create import scene
from leela.blocks.learn import host
from leela.blocks.modes.modes import get_mode, kind_mode, modes
from leela.workspace import Workspace
from tests.fakemodel import WIDE, install

pytest.importorskip('rupaka.spec')
if scene.contract_missing(): pytest.skip('rupaka has no layers block', allow_module_level=True)


@pytest.fixture(autouse=True)
def projects(monkeypatch):
    root = Path(tempfile.mkdtemp()).resolve()/'create'
    monkeypatch.setattr(scene, 'create_root', lambda: root)
    return root


@pytest.fixture
def home(): return Workspace(roots=[Path(tempfile.mkdtemp()).resolve()])


@pytest.fixture
def cl(home):
    install(home, [], spec=WIDE)
    app = ide_app(home)
    with TestClient(app) as c: yield c
    for h in app.router.routes:
        if isinstance(h, Mount) and isinstance(h.app, host.Hosted): h.app.stop()


@pytest.fixture
def thread(home, monkeypatch):
    install(home, [], spec=WIDE)
    t = home.threads.active
    monkeypatch.setattr(t.ai, 'refresh', lambda: t.ai._forget(files=False))
    return t


def tool(t, name): return next(f for f in t.ai._mode_toolsets['create'] if f.__name__ == name)


def test_create_registers_through_the_registry_alone():
    assert [m.id for m in modes()] == ['code', 'learn', 'create']
    m = get_mode('create')
    assert m.title == 'Create' and m.tab_kinds == ('story',) and m.palette == ('Mode: Create', 'Create: New scene')
    assert (m.layout['files'], m.layout['exec'], m.layout['exec_handle'], m.layout['agent']) == (False, False, False, True)
    assert kind_mode('story') == 'create' and kind_mode('learn') == 'learn' and kind_mode('notebook') == 'code' and kind_mode('pdf') == 'code'


def test_the_mode_switch_lists_create_and_the_mode_route_opens_a_scene_tab(home, cl):
    assert 'data-mode="create"' in cl.get('/').text
    assert [m['id'] for m in cl.get('/workspace/mode').json()['modes']] == ['code', 'learn', 'create']
    r = cl.post('/workspace/mode', json={'mode': 'create'}).json()
    assert r['ok'] and r['mode'] == 'create' and r['focus']['kind'] == 'story' and r['layout']['files'] is False
    assert home.mode == 'create' and home.threads.active.ai.mode == 'create'
    t = home.tab
    assert t.kind == 'story' and t.ref == r['focus']['path'] and (scene.create_root()/t.ref/'story.json').is_file()
    d = cl.get('/tab/state').json()
    assert d['kind'] == 'story' and d['project'] == t.ref
    assert cl.post('/workspace/mode', json={'mode': 'create'}).json()['ok'] and [x.kind for x in home.tabs].count('story') == 1


def test_a_busy_agent_blocks_the_create_switch_and_changes_nothing(home, cl):
    home.threads.active.runner._pending['q'] = {}
    try:
        r = cl.post('/workspace/mode', json={'mode': 'create'})
        assert r.status_code == 409 and r.json()['code'] == 'thread_busy' and r.json()['ok'] is False
    finally: home.threads.active.runner._pending.clear()
    assert home.mode == 'code' and not [t for t in home.tabs if t.kind == 'story'] and home.threads.active.ai.mode == 'code'


def test_selecting_a_code_tab_from_create_switches_back_and_keeps_the_scene_tab(home, cl):
    (home.fs.roots[0]/'a.py').write_text('x = 1\n')
    home.open(str(home.fs.roots[0]/'a.py'))
    cl.post('/workspace/mode', json={'mode': 'create'})
    cl.post('/tab/select?i=0')
    assert home.mode == 'code' and home.tab.kind == 'text' and [t.kind for t in home.tabs].count('story') == 1
    cl.post('/tab/select?i=1')
    assert home.mode == 'create' and home.tab.kind == 'story'


def test_one_agent_session_continues_across_modes_with_its_own_tools(thread):
    ai, history = thread.ai, thread.ai.history
    names = {f.__name__ for f in ai._mode_toolsets['create']}
    assert names == {'list_scene', 'set_scene_value'} and not names & {f.__name__ for f in ai.tools}
    thread.set_mode('create')
    assert thread.ai is ai and ai.history is history and names <= {f.__name__ for f in ai.tools}
    stale = tool(thread, 'list_scene')
    thread.set_mode('code')
    assert thread.ai is ai and ai.history is history and not names & {f.__name__ for f in ai.tools}
    r = stale()
    assert r['status'] == 'error' and r['error'] == 'mode_off' and r['data']['needs'] == 'create' and r['data']['mode'] == 'code'


def test_create_switch_is_refused_when_rupaka_is_too_old_and_nothing_changes(thread, monkeypatch):
    monkeypatch.setattr(get_mode('create'), 'contract_check', lambda: ['rupaka 0.0.16 (the layers block)'])
    with pytest.raises(TurnError) as e: thread.set_mode('create')
    assert e.value.code == 'contract_missing' and 'Create needs rupaka 0.0.16' in e.value.message and thread.ai.mode == 'code'
    assert thread.set_mode('code')['ok']


def test_list_scene_and_set_scene_value(home, thread):
    thread.set_mode('create'); home.set_mode('create')
    slug = home.tab.ref
    r = tool(thread, 'list_scene')()
    assert r['status'] == 'ok' and r['error'] is None and r['data']['project'] == slug
    vals = {v['name']: v for v in r['data']['values']}
    assert set(vals) == {'t', 'boat', 'sun'} and vals['t']['max'] == 100 and (vals['boat']['min'], vals['boat']['max']) == (14, 146) and vals['sun']['value'] == 58
    assert [m['label'] for m in r['data']['marks']] == ['Dawn', 'Morning', 'Afternoon', 'Dusk']
    r = tool(thread, 'set_scene_value')(name='boat', value=90)
    assert r['status'] == 'ok' and r['data'] | dict() == dict(project=slug, name='boat', value=90, previous=50)
    assert json.loads((scene.create_root()/slug/'story.json').read_text())['state']['boat'] == 90
    for name, value, err in (('boat', 500, 'invalid_value'), ('sky', 1, 'not_found'), ('t', True, 'invalid_value'), ('t', float('nan'), 'invalid_value')):
        r = tool(thread, 'set_scene_value')(name=name, value=value)
        assert (r['status'], r['error']) == ('error', err) and r['data']['message'], (name, value)
    assert json.loads((scene.create_root()/slug/'story.json').read_text())['state'] == dict(t=20, boat=90, sun=58)


def test_the_context_names_the_mode_and_the_values(home, thread):
    thread.set_mode('create'); home.set_mode('create')
    c = get_mode('create').context(thread.ai)
    assert c.startswith('Create mode.') and 'boat = 50 (14 to 146)' in c and 'sun = 58' in c and 'Dawn at 0' in c and 'set_scene_value' in c
    assert get_mode('code').context(thread.ai) == ''


def test_scene_and_state_routes(home, cl):
    cl.post('/workspace/mode', json={'mode': 'create'})
    slug = home.tab.ref
    d = cl.get(f'/create/scene?slug={slug}').json()
    assert d['ok'] and d['spec']['id'] == slug and d['state'] == dict(t=20, boat=50, sun=58)
    assert cl.get(f'/create/scene?slug={slug}&have={d["rev"]}').json() == dict(ok=True, same=True, rev=d['rev'])
    r = cl.post('/create/state', json=dict(slug=slug, state=dict(t=60, sun=20))).json()
    assert r['ok'] and r['rev'] != d['rev'] and cl.get(f'/create/scene?slug={slug}').json()['state'] == dict(t=60, boat=50, sun=20)
    for body, code in ((dict(slug=slug, state=dict(sun=99)), 400), (dict(slug=slug, state=dict(gone=1)), 404), (dict(slug=slug, state='x'), 400),
                       (dict(slug='nope', state={}), 404), (dict(slug='../x', state={}), 400)):
        assert cl.post('/create/state', json=body).status_code == code, body
    assert cl.post('/create/state', json=[1]).status_code == 400
    assert cl.get(f'/create/scene?slug=../x').status_code == 400 and cl.get('/create/scene?slug=nope').status_code == 404
    assert cl.get('/create/state').status_code == 405 and cl.get('/create/new').status_code == 405
    assert cl.get(f'/create/page?slug={slug}').text.count('data-create=') == 2


def test_a_broken_story_is_said_in_plain_words(home, cl):
    cl.post('/workspace/mode', json={'mode': 'create'})
    slug = home.tab.ref; p = scene.create_root()/slug/'story.json'
    p.write_text('{not json')
    assert cl.get(f'/create/scene?slug={slug}').json()['error'] == 'story.json is not valid JSON.'
    spec = scene.new_project('Other'); good = json.loads((scene.create_root()/spec/'story.json').read_text())
    good['blocks'][0]['blocks'][0]['art'] = 'dragon'
    p.write_text(json.dumps(good))
    assert 'is not one of' in cl.get(f'/create/scene?slug={slug}').json()['error']


def test_new_scene_makes_a_project_and_the_tab_moves_to_it(home, cl):
    cl.post('/workspace/mode', json={'mode': 'create'})
    first = home.tab.ref
    cl.post('/create/new', json={'name': 'River Trip'})
    assert home.tab.ref == 'river-trip' and first != 'river-trip' and [t.kind for t in home.tabs].count('story') == 1
    assert json.loads((scene.create_root()/'river-trip'/'story.json').read_text())['title'] == 'River Trip'
    cl.post('/create/new', json={'name': 'River Trip'})
    assert home.tab.ref == 'river-trip-2'


def test_export_is_one_standalone_page(home, cl):
    cl.post('/workspace/mode', json={'mode': 'create'})
    slug = home.tab.ref
    cl.post('/create/state', json=dict(slug=slug, state=dict(boat=77)))
    r = cl.get(f'/create/export?slug={slug}')
    assert r.status_code == 200 and r.headers['content-type'].startswith('text/html') and f'{slug}.html' in r.headers['content-disposition']
    html = r.text
    assert 'data-rupaka' in html and '"boat": 77' in html and 'Rupaka.block(\'layers\'' in html and 'Rupaka.block(\'timeline\'' in html
    assert 'src="http' not in html and "href=\"http" not in html and 'data:font/woff2' in html
    assert cl.get('/create/export?slug=nope').status_code == 404


def test_the_mode_and_the_scene_tab_survive_a_reload(tmp_path, home):
    home._state_path, home._owns_session = tmp_path/'ws.json', True
    home.set_mode('create')
    slug = home.tab.ref
    back = Workspace.load(tmp_path/'ws.json')
    assert back.mode == 'create' and back.tab is not None and back.tab.kind == 'story' and back.tab.ref == slug
    assert back.set_mode('code')['focus'] == dict(kind='', path='') and back.tab is None
    assert back.set_mode('create')['focus'] == dict(kind='story', path=slug) and [t.kind for t in back.tabs].count('story') == 1


def test_each_mode_keeps_its_own_layout_with_create(home, tmp_path):
    home._state_path = tmp_path/'ws.json'
    home.remember_layout('create', {'agent': False, 'bogus': 1})
    assert home.mode_layout('create')['agent'] is False and home.mode_layout('learn')['agent'] is True and home.mode_layout('create')['main'] == 'story'
