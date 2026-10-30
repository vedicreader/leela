import re
from fastcore.basics import AttrDict
from leela.blocks.nb.exercise import exercise_cells
import leela.blocks.nb.lesson as lesson_mod
from leela.blocks.nb.lesson import check_anchors, fence, guide_context
from leela.blocks.nb.nb import Cell, src_hash

ID = re.compile(r'\A[A-Za-z0-9:_-]{1,40}\Z')
META = dict(v=1, name='Diffusion noise', walk=dict(walk='ddpm-ab12', step=2, section='Forward process', concept='forward-process'))
DDPM = r'q(\mathbf{x}_t\mid\mathbf{x}_0)=\mathcal{N}(\mathbf{x}_t;\sqrt{\bar\alpha_t}\mathbf{x}_0,(1-\bar\alpha_t)\mathbf{I})'
DEMO = dict(id='noise', state=dict(t=500, flag=False), blocks=[dict(type='stack', blocks=[
    dict(type='slider', bind='t', label='Step t', min=0, max=1000, step=10),
    dict(type='toggle', bind='flag', label='Show noise'),
    dict(type='slider', bind='bad id!', min=0, max=1),
    dict(type='readout', text='alpha bar = {abar}', label='Share left'),
    dict(type='row', blocks=[dict(type='gate', id='g1', prompt='Does it fall?', options=['yes', 'no'], answer={'is': 'yes'})])])])

def md(src): return Cell(source=src, cell_type='markdown')
def by_id(c): return {a['id']: a for a in c['anchors']}

def test_the_tokenizer_moved_to_the_page():
    assert not hasattr(lesson_mod, 'tex_tokens'), 'the page splits a formula (abhyasaTex.texParts); the server only receives its parts'

def test_markdown_cell_gives_passage_formulas_and_figures():
    src = f'Noise is added in one jump.\n\n$$ {DDPM} $$\n\nHere $\\bar\\alpha_t$ is the share left.\n\n![A noisy cat](cat.png)\n\n```python\nprice = "$5"; cost = "$7"\n```'
    page = [dict(id='f1', text=DDPM, parts=[r'\bar\alpha_t', r'\mathbf{x}_0']), dict(id='f2', text=r'\bar\alpha_t', parts=[]), dict(id='img1', text='A noisy cat')]
    c = guide_context(META, md(src), path='/w/diffusion.ipynb', anchors=page)
    a = by_id(c)
    assert list(a) == ['passage', 'f1', 'f2', 'img1'] and all(ID.match(i) for i in a)
    assert c['page'] == '/w/diffusion.ipynb' and c['title'] == 'Diffusion noise'
    assert (c['step'], c['concept'], c['slug']) == ('Step 2: Forward process', 'forward-process', 'forward-process')
    assert a['passage']['kind'] == 'passage' and a['passage']['text'] == src
    assert (a['f1']['kind'], a['f1']['text'], a['f1']['tokens']) == ('formula', DDPM, [r'\bar\alpha_t', r'\mathbf{x}_0'])
    assert a['f2']['text'] == r'\bar\alpha_t' and 'tokens' not in a['f2'], 'a formula the page sent no parts for has no tokens'
    assert (a['img1']['kind'], a['img1']['text']) == ('figure', 'A noisy cat') and 'labels' not in a['img1']
    assert 'demo' not in c

def test_formula_and_figure_anchors_come_only_from_the_page_list():
    src = 'Price `$5 and $7`, cost \\$3, code `![x](y.png)`.\n\n$a$ then $$b$$\n\n```\n$c$ ![z](q.png)\n```'
    page = [dict(id='f1', text='a', parts=['a']), dict(id='f2', text='b', parts=[])]
    assert list(by_id(guide_context(META, md(src), anchors=page))) == ['passage', 'f1', 'f2']
    assert list(by_id(guide_context(META, md(src)))) == ['passage'], 'with no list the server counts nothing'
    assert list(by_id(guide_context(META, md(src), anchors=[dict(id='img1', text='x')]))) == ['passage', 'img1']

def test_check_anchors_refuses_a_bad_list():
    assert check_anchors(None) == []
    ok = [dict(id='f1', text='a', parts=['a']), dict(id='img2', text='')]
    assert check_anchors(ok) == ok
    for bad in ('f1', {'id': 'f1'}, [1], [dict(text='a')], [dict(id='passage', text='a')], [dict(id='f0', text='a')], [dict(id='f1', text=1)],
                [dict(id='f1', text='a', parts='a')], [dict(id='f1', text='a', parts=[1])], [dict(id='img1', text='a', parts=['a'])],
                [dict(id='f1', text='a'), dict(id='f1', text='b')], [dict(id='f1', text='a' * 5000)], [dict(id='f1', text='a', parts=['a'] * 300)],
                [dict(id=f'f{i}', text='a') for i in range(1, 300)]):
        with pytest.raises(ValueError): check_anchors(bad)

def test_a_cell_with_no_walk_files_under_the_lesson_name():
    c = guide_context(dict(v=1, name='Half of eight'), md('Text.'))
    assert (c['step'], c['concept'], c['slug'], c['page']) == ('', '', 'half-of-eight', '')

def test_demo_comes_from_the_rupaka_spec_and_opens_with_the_lock_in():
    cell = md(f'Move the slider.\n\n{fence(DEMO)}')
    c = guide_context(META, cell)
    a = by_id(c)
    assert all(ID.match(i) for i in a)
    assert 'rupaka' not in a['passage']['text'] and a['passage']['text'] == 'Move the slider.'
    assert (a['demo']['kind'], a['in:t']['kind'], a['in:t']['text'], a['out1']['kind'], a['out1']['text']) == ('demo', 'input', 'Step t', 'readout', 'Share left: alpha bar = {abar}')
    d = c['demo']
    assert d['slug'] == 'noise' and d['open'] is False and d['readouts'] == ['Share left: alpha bar = {abar}']
    assert d['inputs'] == {'t': dict(value=500, min=0, max=1000, step=10, label='Step t'), 'flag': dict(value=False, label='Show noise')}
    key = f'{cell.id}:{src_hash(cell.source)}:noise:g1'
    assert guide_context(META, cell, filed={key})['demo']['open'] is True
    assert guide_context(META, cell, filed={'other:key'})['demo']['open'] is False

def test_a_demo_with_no_gate_is_open():
    spec = dict(id='free', state=dict(n=1), blocks=[dict(type='slider', bind='n', min=0, max=9)])
    assert guide_context(META, md(fence(spec)))['demo']['open'] is True

def test_exercise_task_and_check_are_check_anchors():
    task, code = exercise_cells(dict(task='Double a number.', fname='double', stub='def double(x):\n    pass', uses=[],
        tests=[dict(say='Two doubles to four', test='assert double(2) == 4', shown=False), dict(say='Zero stays zero', test='assert double(0) == 0', shown=True)]))
    t = by_id(guide_context(META, task))
    assert list(t) == ['check'] and t['check']['kind'] == 'check' and t['check']['text'].startswith('Double a number.')
    k = by_id(guide_context(META, code))['check']
    assert k['kind'] == 'check' and 'double' in k['text'] and 'Two doubles to four' in k['text'] and 'assert' not in k['text']

def test_other_cells_give_no_anchor_but_the_page():
    c = guide_context(META, Cell(source='print(1)'))
    assert c['anchors'] == [] and c['title'] == 'Diffusion noise'
import sys, threading, types
import abhyasa, pytest
from leela.blocks.nb.nb import Notebook
from test_lesson_predict import DEMO as GATE_DEMO, lesson, post as predict, serve, shelf

EXPLAINED = dict(tier='tutor', steps=[dict(n=1, say='It is the share left.', strokes=[])], sources=[dict(n=1, title='DDPM', url='', label='your vault', quoted=False)],
                 sure=0.9, failed=False, dropped=0, end="In the tutor's own words. No source found.", ms=3)

@pytest.fixture
def guide(monkeypatch):
    "A stand-in for `abhyasa.guide`, which abhyasa 0.0.14 adds: `calls` holds what `explain` was given."
    import abhyasa.llm
    calls = AttrDict(thread=None)
    def explain(ask, ctx, said, sources=(), search=None, fetch=None, web=None, note=None, lr=None):
        calls.update(ask=ask, ctx=mod.clean_context(ctx), said=said, sources=list(sources), web=web, lr=lr, thread=threading.current_thread())
        note('The tutor looks in your vault.')
        return AttrDict(EXPLAINED)
    mod = types.ModuleType('abhyasa.guide')
    mod.explain, mod.clean_context, mod.norm_tex = explain, (lambda raw: AttrDict(raw, cleaned=True)), (lambda s: 'n:' + s.strip())
    monkeypatch.setitem(sys.modules, 'abhyasa.guide', mod)
    monkeypatch.setattr(abhyasa, 'guide', mod, raising=False)
    monkeypatch.setattr(abhyasa.llm, 'route_ask', lambda model=None: 'the ask')
    return calls

def ask_guide(r, i=1, said="I don't get alpha bar", **kw):
    cell = r.nb[i] if isinstance(i, int) else None
    return r.c.post('/nb/guide', json=dict(path=str(r.p), cell_id=cell.id if cell else i, said=said, **kw))

def test_guide_route_builds_the_context_and_returns_the_board(serve, guide):
    r = serve(lesson(f'Alpha bar is the share left.\n\n$\\bar\\alpha_t$'))
    res = ask_guide(r, anchors=[dict(id='f1', text=r'\bar\alpha_t', parts=[])])
    assert res.status_code == 200, res.text
    d = res.json()
    assert d['steps'] == EXPLAINED['steps'] and d['tier'] == 'tutor' and d['notes'] == ['The tutor looks in your vault.']
    assert guide.said == "I don't get alpha bar" and guide.thread is not threading.main_thread()
    assert [a['id'] for a in guide.ctx.anchors] == ['passage', 'f1'] and guide.ctx.page == str(r.p) and guide.ctx.title == 'Halves'
    assert guide.ask.dflt == 'the ask'
    assert isinstance(guide.lr, type(shelf(r))) and len(guide.sources) == 1 and guide.web is None

def test_guide_route_opens_the_demo_after_the_lock_in(serve, guide):
    r = serve(lesson())
    first = ask_guide(r)
    assert first.status_code == 200 and guide.ctx['demo']['open'] is False and first.json()['demo_open'] is False
    assert predict(r, picked=4, why='half').json()['logged']
    second = ask_guide(r)
    assert second.status_code == 200 and guide.ctx['demo']['open'] is True and second.json()['demo_open'] is True

def test_guide_route_takes_formulas_and_figures_from_the_page_list_through_norm_tex(serve, guide):
    r = serve(lesson('Price `$5 and $7`, cost \\$3.\n\n$a_t$ and $b$ ![x](y.png)'))
    page = [dict(id='f1', text='a_t', parts=[' \\bar\\alpha_t ', 'a_t']), dict(id='f2', text='b', parts=[]), dict(id='img1', text='x')]
    assert ask_guide(r, anchors=page).status_code == 200
    a = {x['id']: x for x in guide.ctx.anchors}
    assert list(a) == ['passage', 'f1', 'f2', 'img1'] and a['f1']['tokens'] == ['n:\\bar\\alpha_t', 'n:a_t'] and 'tokens' not in a['f2']
    assert (a['f1']['kind'], a['f1']['text'], a['img1']['kind'], a['img1']['text']) == ('formula', 'a_t', 'figure', 'x')
    assert ask_guide(r).status_code == 200 and [x['id'] for x in guide.ctx.anchors] == ['passage']
    for bad in ('f1', [['a']], [dict(id='f1', text='a', parts='a_t')], [dict(id='f1', text='a', parts=[1])], [dict(id='f1')], [dict(id='x', text='a')]):
        res = ask_guide(r, anchors=bad)
        assert res.status_code == 400 and 'anchors' in res.json()['error'], bad

def test_guide_route_needs_the_norm_tex_of_abhyasa_0014(serve, guide, monkeypatch):
    monkeypatch.delattr(sys.modules['abhyasa.guide'], 'norm_tex')
    res = ask_guide(serve(lesson()))
    assert res.status_code == 400 and '0.0.14' in res.json()['error']

def test_vault_sources_find_a_paper_and_never_an_attempt(serve):
    "The guide's sources are `VaultSource(lr)`: a paper on the `papers` shelf is quoted, and what the learner answered on the `learning` shelf never is."
    from abhyasa.ground import VaultSource
    r = serve(lesson())
    r.ws.memory._store('papers').add('Alpha bar is the cumulative product of one minus beta in the diffusion forward process.', title='DDPM paper', source='https://arxiv.org/abs/2006.11239', kind='paper')
    lr = shelf(r)
    lr.v.add('Alpha bar attempt: the learner guessed the share left.', title='attempt alpha', source='attempt:1', kind='attempt')
    hits = VaultSource(lr).search('alpha bar diffusion', 4)
    assert [(h.src, h.title) for h in hits] == [('vault:papers', 'DDPM paper')]

def test_guide_route_names_the_abhyasa_it_needs_when_the_guide_is_missing(serve, monkeypatch):
    monkeypatch.setitem(sys.modules, 'abhyasa.guide', None)
    res = ask_guide(serve(lesson()))
    assert res.status_code == 400 and '0.0.14' in res.json()['error'] and 'abhyasa' in res.json()['error']

def test_guide_route_refuses_what_it_cannot_explain(serve, guide):
    r = serve(lesson())
    assert ask_guide(r, i='missing').status_code == 400
    assert ask_guide(r, said='  ').status_code == 400
    assert r.c.post('/nb/guide', json=[1]).status_code == 400
    plain = serve(Notebook([Cell(source='Text.', cell_type='markdown')]))
    assert ask_guide(plain, i=0).status_code == 400 and guide.thread is None

def test_guide_route_reports_a_failed_explain(serve, guide, monkeypatch):
    def boom(*a, **k): raise RuntimeError('The guide task got no answer from the model.')
    monkeypatch.setattr(sys.modules['abhyasa.guide'], 'explain', boom)
    res = ask_guide(serve(lesson()))
    assert res.status_code == 400 and 'no answer' in res.json()['error']

def test_guide_entry_asks_one_line_and_shows_the_steps_and_sources():
    "The page offers 'I don't get…' on lesson cells, seeds the line with the selection, posts it, and shows the say lines and the sources as plain text."
    import json, shutil, subprocess
    from pathlib import Path
    node = shutil.which('node')
    if not node: pytest.skip('node is not installed')
    harness = r'''const vm = require('vm'), fs = require('fs');
const el = tag => ({tag, children: [], dataset: {}, classList: {contains: () => false}, appendChild(c) { this.children.push(c); return c; }, remove() { this.gone = true; },
  after(n) { this.next = n; }});
const main = el('div'), out = el('div'), cell = el('div'), posts = [], dialogs = [], loads = [], plays = [], sets = [], target = el('span'), demoHost = {shadowRoot: {children: [{rupaka: {}}]}};
cell.guideEls = [{dataset: {guideId: 'f1', tex: ' a_t b ', parts: JSON.stringify([['a_t', 'g-1001-0'], ['b', 'g-1001-1']])}}, {dataset: {guideId: 'img1'}, alt: '', closest: () => ({querySelector: () => ({textContent: ' A cat '})})}, {dataset: {guideId: 'img2'}, alt: 'inline', closest: () => null}, {dataset: {guideId: 'f2'}}, {dataset: {guideId: 'demo'}}];
const ctx = {said: [], reply: null, selection: '', typed: null, CSS: {escape: s => s}, lee: {path: '/n.ipynb', nbQueue: Promise.resolve(), sel: 1,
  cells: [{id: 'a', cell_type: 'markdown', extra: {lesson: {role: 'prediction'}}}, {id: 'b', cell_type: 'markdown', extra: {}},
          {id: 'c', cell_type: 'code', extra: {exercise: {tests: []}}}, {id: 'd', cell_type: 'code', extra: {}}]}};
ctx.document = {createElement: el, addEventListener() {}, head: {appendChild(n) { loads.push(n); if (n.src) setTimeout(() => n.onerror()); return n; }}};
ctx.window = ctx; ctx.Rupaka = {set: (inner, s) => sets.push([inner, s])};
ctx.getSelection = () => ctx.selection;
ctx.$ = (sel, root) => sel === '.lee-cellmain' ? main : sel === '#out-b' ? out : sel.startsWith('.lee-cell[') ? cell : sel === '[data-guide-id="demo"]' ? demoHost : sel.startsWith('[data-guide-id=') ? target : null;
ctx.$$ = (sel, root) => sel === '[data-guide-id]' ? root.guideEls : [];
ctx.status = (t, k) => ctx.said.push([k, t]);
ctx.isExercise = c => c?.cell_type === 'code' && !!c.extra?.exercise?.tests;
ctx.inputDialog = async (...a) => { dialogs.push(a); return ctx.typed; };
ctx.post = async (url, body) => { posts.push([url, body]); if (ctx.reply instanceof Error) throw ctx.reply; return ctx.reply; };
vm.createContext(ctx); vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
(async () => { const r = {};
  const painted = c => { main.children = []; ctx.paintGuideButton(el('div'), c); return main.children.map(b => b.textContent); };
  r.buttons = ['a', 'b', 'c', 'd'].map(id => painted(ctx.lee.cells.find(c => c.id === id)));
  ctx.lee.cells.forEach(c => { c.extra = {}; }); r.plain = painted(ctx.lee.cells[1]);
  ctx.lee.cells[0].extra = {lesson: {role: 'card'}};
  ctx.selection = '  alpha bar \n'; ctx.typed = "I don't get alpha bar"; ctx.reply = {ok: true, steps: [{say: 'It is the share left.'}, {say: 'It falls with t.'}],
    sources: [{n: 1, title: 'DDPM', label: 'your vault'}], end: "In the tutor's own words.", notes: ['The tutor looks in your vault.']};
  await ctx.lessonGuide('b'); r.dialog = dialogs[0].slice(2, 3); r.post = posts[0]; r.out = out.next.textContent; r.said = ctx.said; r.loaded = loads.map(n => n.src || n.href);
  out.next = undefined; plays.length = 0; ctx.abhyasaBoard = {play: async (b, o) => { plays.push([b, o]); }};
  await ctx.lessonGuide('b'); const [board, opts] = plays[0], host = opts.host;
  r.played = [plays.length, board.steps.length, Object.keys(host).sort(), host.assets, out.next === undefined, host.resolve('f1') === target, host.resolve('demo') === demoHost];
  host.demo({t: 1}); r.closed = sets.length; ctx.reply = Object.assign({}, ctx.reply, {demo_open: true});
  await ctx.lessonGuide('b'); plays.at(-1)[1].host.demo({t: 2}); r.open = sets.map(s => s[1]);
  out.next = undefined; ctx.abhyasaBoard = {play: async () => { throw new Error('rough.js'); }}; await ctx.lessonGuide('b'); r.broke = out.next.textContent.split('\n')[0];
  ctx.abhyasaBoard = undefined; ctx.reply.demo_open = false;
  ctx.said = []; ctx.typed = null; posts.length = 0; await ctx.lessonGuide('b'); r.cancel = posts.length;
  ctx.typed = 'why?'; ctx.reply = Object.assign(new Error('x'), {body: {ok: false, error: 'The screen guide needs abhyasa 0.0.14 or newer.'}}); await ctx.lessonGuide('b'); r.failed = ctx.said.at(-1);
  ctx.said = []; ctx.lee.sel = 3; await ctx.lessonGuideSelected('alpha'); r.notCell = ctx.said;
  ctx.lee.sel = 1; ctx.typed = null; dialogs.length = 0; await ctx.lessonGuideSelected('beta'); r.picked = dialogs[0].slice(2, 3);
  console.log(JSON.stringify(r)); })();'''
    r = subprocess.run([node, '-e', harness, str(Path(__file__).parents[1]/'leela/blocks/nb/lesson.js')], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    assert got['buttons'] == [[], ["I don't get…"], ["I don't get…"], []], 'a markdown or exercise cell, never a prediction, a card or a plain code cell'
    assert got['plain'] == [], 'a notebook with no lesson cell is not a lesson'
    assert got['dialog'] == ["I don't get alpha bar"] and got['post'] == ['/nb/guide', dict(path='/n.ipynb', cell_id='b', said="I don't get alpha bar", anchors=[dict(id='f1', text='a_t b', parts=['a_t', 'b']), dict(id='img1', text='A cat'), dict(id='img2', text='inline'), dict(id='f2', text='', parts=[])])]
    assert any('lee-board.js' in s for s in got['loaded']) and any('lee-board.css' in s for s in got['loaded'])
    assert got['played'] == [1, 2, ['assets', 'demo', 'resolve'], '/leestatic/board/', True, True, True], 'the board is drawn, not the text, with no speak hook'
    assert got['closed'] == 0 and got['open'] == [{'t': 2}], 'the demo moves only when every gate is filed'
    assert got['broke'] == 'It is the share left.', 'a board that fails to draw leaves the plain text'
    assert got['out'].splitlines() == ['It is the share left.', 'It falls with t.', 'Source 1: your vault, DDPM', "In the tutor's own words."]
    assert got['cancel'] == 0 and got['failed'] == ['err', 'The screen guide needs abhyasa 0.0.14 or newer.']
    assert got['notCell'] == [['err', 'Pick a lesson cell first.']] and got['picked'] == ["I don't get beta"]
