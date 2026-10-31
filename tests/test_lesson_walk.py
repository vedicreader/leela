"Walk lessons: the passage in the first cell, the walk in the meta, and the walk meta on each check filed from one."
from fastcore.basics import AttrDict, first
from abhyasa.store import Learning
from leela.blocks.memory.memory import Memory
from leela.blocks.nb.lesson import exercise_filing, lesson_charter, lesson_notebook, lesson_step, lock, prediction_filing, record_card, walk_meta
from leela.blocks.nb.nb import Notebook
from learn_data import JID, NB_JID, nb_walk, rig  # noqa: F401

STEP = dict(walk='attention-ab12', step=0, section='2 Background', text='Softmax maps scores to weights.\nThe sum is 1.', note='Watch the sum.')
WALK = {'walk': 'attention-ab12', 'step': 0, 'section': '2 Background', 'from': 'attention-ab12/0', 'app': 'leela'}

def test_walk_meta():
    assert walk_meta(lesson_notebook('Softmax', step=STEP)) == WALK
    assert walk_meta(lesson_notebook('Softmax', step={**STEP, 'section': ''})).keys() == {'walk', 'step', 'from', 'app'}
    assert walk_meta(lesson_notebook('Softmax')) == {}

def test_a_walk_lesson_keeps_the_cell_layout_and_quotes_the_passage():
    nb, plain = lesson_notebook('Softmax', step=STEP), lesson_notebook('Softmax')
    assert [c.cell_type for c in nb.cells] == [c.cell_type for c in plain.cells] and [c.source for c in nb.cells][1:] == [c.source for c in plain.cells][1:]
    assert nb[0].source.startswith(plain[0].source) and '> Softmax maps scores to weights.\n> The sum is 1.' in nb[0].source and 'Watch the sum.' in nb[0].source
    assert nb.meta['lesson'] == {'v': 1, 'name': 'Softmax', 'walk': dict(walk='attention-ab12', step=0, section='2 Background')}
    assert plain.meta['lesson'] == {'v': 1, 'name': 'Softmax'}

def test_a_source_line_shows_hostile_metadata_as_text():
    from abhyasa.sources import WEB
    from leela.blocks.nb.lesson import source_line
    from leela.core.text import md_html
    bad = '![leak](https://evil.example/pixel) <b>x</b> *y* [z](q)'
    p = AttrDict(label='your source', title=bad, place='<b>place</b>', date='', url='')
    h = md_html(source_line(p))
    assert '<img' not in h and '<b>' not in h and '<em>' not in h and '<a ' not in h and '![leak](https://evil.example/pixel)' in h and '&lt;b&gt;place&lt;/b&gt;' in h
    w = AttrDict(label=WEB, title='a] (b) <i>', place='site', date='', url='https://example.org/a b>c')
    h = md_html(source_line(w))
    assert '<i>' not in h and h.count('<a ') == 1 and 'href="https://example.org/a%20b%3Ec"' in h and 'a] (b) &lt;i&gt;' in h

def test_a_card_from_a_walk_lesson_carries_the_walk_meta(tmp_path):
    mem, nb = Memory(path=tmp_path/'vault.db', offline=True), lesson_notebook('Softmax', step=STEP)
    code = nb[3]; code.source, code.execution_count = 'print(1)', 1
    code.outputs = [{'output_type': 'stream', 'name': 'stdout', 'text': '1\n'}]
    lock(code, '1')
    record_card(mem, nb, code, str(tmp_path/'softmax.ipynb'))
    a = first(Learning(mem._store('learning')).attempts('softmax', limit=5))
    assert (a.kind, a.walk, a.step, a['from'], a.app, a.section) == ('predict', 'attention-ab12', 0, 'attention-ab12/0', 'leela', '2 Background')

def _kind(c):
    ex, ls, s = c.extra.get('exercise') or {}, c.extra.get('lesson') or {}, c.source
    if ex.get('role') == 'task': return 'task'
    if 'tests' in ex: return 'exercise'
    if ls.get('role') in ('prediction', 'card'): return ls['role']
    if c.cell_type == 'code': return 'setup' if 'EPISODES = Path(' in s else 'run' if 'Run it on all episodes.' in s else 'code'
    return 'header' if s.startswith('# ') else 'passage' if '> A caption is one line.' in s else 'demo' if '```rupaka' in s else 'markdown'

def test_a_step_with_nb_builds_the_lesson_from_the_step(rig, tmp_path_factory, monkeypatch, abhyasa_cfg):
    import abhyasa.demo  # adds Learning.put_demo
    from rupaka.spec import demo, gate, is_, slider
    c, ws, lr, j, root = rig
    monkeypatch.setenv('HOME', str(tmp_path_factory.mktemp('home')))   # a data path is checked against the home folder
    lr.put_demo(demo('cap-demo', title='Captions', state={'x': 1}, blocks=[slider('x', label='x', min=0, max=4, step=1),
                gate('g1', 'Which one?', ['one', 'two'], is_('two'), why='because')]), 'caption')
    nb_walk(lr, demo='cap-demo')
    assert c.post('/learn/open', data=dict(walk=NB_JID, step='0')).status_code == 200
    nb = Notebook.load(root/'lessons'/f'{NB_JID}-0.ipynb')
    assert [_kind(x) for x in nb.cells] == ['header', 'passage', 'demo', 'setup', 'task', 'exercise', 'prediction', 'run', 'card']
    head, passage, dm, setup, task, code, pred, run, card = nb.cells
    assert '**your source** · Comic notes · section 2' in passage.source and '> A caption names who acts.' in passage.source
    assert '**from the web** · example.org · ' in passage.source and '[Captions](<https://example.org/c>)' in passage.source
    assert "The tutor's note" in passage.source and 'Keep it short.' in passage.source and 'No demo yet' not in dm.source
    assert '"g1"' in dm.source and '"answer"' in dm.source, 'the demo keeps its gates'
    assert "EPISODES = Path('~/data/episodes.json').expanduser()" in setup.source and 'DEVICE' in setup.source and 'def save_result(' in setup.source
    assert code.extra['exercise']['requires'] == ['diffusers', 'torch'] and 'env' not in code.extra['exercise'], 'no environment before the yes'
    assert 'How many episodes have no place?' in pred.source and pred.extra['lesson']['for'] == run.id == card.extra['lesson']['for']
    assert not [x for x in nb.cells if x.source.strip() == 'pass'] and 'Runs on:' in head.source
    compile(setup.source, 'setup', 'exec'); compile(run.source, 'run', 'exec')
    assert nb.meta['lesson']['walk'] == dict(walk=NB_JID, step=0, section='2 Captions', concept='caption')
    with_nb, plain = lesson_step(ws.memory, nb), lesson_step(ws.memory, lesson_notebook('Softmax', step=dict(walk=JID, step=0)))
    assert 'add_exercise' not in lesson_charter(with_nb).split('This lesson is step')[1]
    assert 'Make the exercise for this step with add_exercise.' in lesson_charter(plain)

def test_a_bad_nb_is_refused_before_a_lesson_is_written(rig, tmp_path_factory, monkeypatch):
    c, ws, lr, j, root = rig
    monkeypatch.setenv('HOME', str(tmp_path_factory.mktemp('home')))
    nb_walk(lr)
    s = lr.journey(NB_JID).steps[0]; s['nb']['data'][0]['name'] = 'EPISODES\nimport os'
    lr.put_journey(dict(lr.journey(NB_JID), steps=[s]))
    r = c.post('/learn/open', data=dict(walk=NB_JID, step='0'))
    assert r.status_code == 400 and 'data:' in r.text and not (root/'lessons').exists()

def test_a_card_from_a_plain_lesson_has_no_walk_meta(tmp_path):
    mem, nb = Memory(path=tmp_path/'vault.db', offline=True), lesson_notebook('Softmax')
    code = nb[3]; code.source, code.execution_count = 'print(1)', 1
    code.outputs = [{'output_type': 'stream', 'name': 'stdout', 'text': '1\n'}]
    lock(code, '1')
    record_card(mem, nb, code, str(tmp_path/'softmax.ipynb'))
    a = first(Learning(mem._store('learning')).attempts('softmax', limit=5))
    assert not {'walk', 'step', 'from', 'app', 'section'} & set(a)

def test_the_filings_copy_the_walk_meta_when_made():
    from test_lesson_predict import DEMO
    from leela.blocks.nb.lesson import fence
    spec = dict(task='Double it.', fname='double', stub='def double(x): pass', tests=[dict(say='doubles 2', test='assert double(2) == 4', shown=True)])
    nb = lesson_notebook('Softmax', spec, step=STEP)
    code = next(c for c in nb.cells if 'tests' in c.extra.get('exercise', {}))
    code.extra['exercise']['state'] = dict(grade=dict(score=8, note='Clear.', hash=''))
    f = exercise_filing(nb, code, 'x.ipynb')
    nb.meta['lesson']['walk'] = dict(walk='other-0000', step=3, section='')
    assert f['walk'] == WALK
    nb[1].source = fence(DEMO)
    assert prediction_filing(nb, nb[1], 'x.ipynb', 'halves', 'g1', 4)['walk'] == {'walk': 'other-0000', 'step': 3, 'from': 'other-0000/3', 'app': 'leela'}
    plain = lesson_notebook('Plain'); plain[1].source = fence(DEMO)
    assert prediction_filing(plain, plain[1], 'x.ipynb', 'halves', 'g1', 4)['walk'] == {}

def test_the_step_page_and_the_setup_cell_name_the_data_that_is_not_on_this_computer(rig, tmp_path_factory, monkeypatch, capsys):
    "Each spec named home paths that did not exist, and neither the step page nor the setup cell said so."
    c, ws, lr, j, root = rig
    home = tmp_path_factory.mktemp('home')
    monkeypatch.setenv('HOME', str(home))
    nb_walk(lr)
    say = 'These data entries are not on this computer: EPISODES (~/data/episodes.json). Add the folder in abhyasa under Your data, or set the path in the setup cell of the lesson.'
    assert f'<p class="lee-learn-line">{say}</p>' in c.get(f'/learn?walk={NB_JID}&step=0').text
    assert c.post('/learn/open', data=dict(walk=NB_JID, step='0')).status_code == 200
    setup = next(x for x in Notebook.load(root/'lessons'/f'{NB_JID}-0.ipynb').cells if 'EPISODES = Path(' in x.source)
    run = lambda: exec(setup.source.split('RESULT =')[0], {}) or capsys.readouterr().out
    assert run() == f"These data entries are not on this computer: EPISODES ({home}/data/episodes.json). Add the folder in abhyasa under Your data, or set the path here.\n"
    (home/'data').mkdir(); (home/'data'/'episodes.json').write_text('[]')
    assert run() == '' and 'not on this computer' not in c.get(f'/learn?walk={NB_JID}&step=0').text
