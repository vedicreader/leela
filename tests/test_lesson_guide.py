import re
from fastcore.basics import AttrDict
from leela.blocks.nb.exercise import exercise_cells
import leela.blocks.nb.lesson as lesson_mod
from leela.blocks.nb.lesson import check_anchors, check_demo, fence, guide_context
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

PAGE_DEMO = dict(anchors=[dict(id='demo', kind='demo', text='Noise. Does it fall?'), dict(id='in:t', kind='input', text='Step t = 500'), dict(id='out:1', kind='readout', text='alpha bar = 0.5')],
                 demo=dict(slug='noise', inputs={'t': dict(value=500, label='Step t', min=0, max=1000, step=10)}, readouts=['alpha bar = 0.5'], open=True))

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

def test_the_demo_ids_come_from_the_page_and_the_server_only_opens_the_gate():
    cell = md(f'Move the slider.\n\n{fence(DEMO)}')
    c = guide_context(META, cell)
    a = by_id(c)
    assert 'rupaka' not in a['passage']['text'] and a['passage']['text'] == 'Move the slider.'
    assert list(a) == ['passage', 'demo'] and a['demo']['kind'] == 'demo', 'with no demo from the page the server numbers no input and no readout'
    assert c['demo'] == dict(slug='noise', inputs={}, readouts=[], open=False)
    c = guide_context(META, cell, demo=check_demo(PAGE_DEMO))
    a = by_id(c)
    assert list(a) == ['passage', 'demo', 'in:t', 'out:1'] and a['demo']['text'] == 'Noise. Does it fall?' and all(ID.match(i) for i in a)
    assert c['demo'] == dict(slug='noise', inputs=PAGE_DEMO['demo']['inputs'], readouts=['alpha bar = 0.5'], open=False), "the page's open is not the gate"
    key = f'{cell.id}:{src_hash(cell.source)}:noise:g1'
    assert guide_context(META, cell, filed={key}, demo=PAGE_DEMO)['demo']['open'] is True
    assert guide_context(META, cell, filed={'other:key'}, demo=PAGE_DEMO)['demo']['open'] is False
    assert 'demo' not in guide_context(META, md('Text.'), demo=PAGE_DEMO), 'a cell with no rupaka spec has no demo'
    hidden = dict(PAGE_DEMO, demo=dict(PAGE_DEMO['demo'], inputs=PAGE_DEMO['demo']['inputs'] | {'secret': dict(value=1, min=0, max=9)}))
    assert list(guide_context(META, cell, demo=check_demo(hidden))['demo']['inputs']) == ['t'], 'an input the page gave no anchor cannot be set by the tutor'

def test_check_demo_keeps_the_agreed_ids_and_refuses_a_bad_shape():
    assert check_demo(None) is None and check_demo(PAGE_DEMO) == PAGE_DEMO
    odd = dict(PAGE_DEMO, anchors=PAGE_DEMO['anchors'] + [dict(id=i, kind='readout', text='x') for i in ('out1', 'out:0', 'f1', 'in:' + 'a' * 38, 'in:a b')] + [dict(id='in:t', kind='input', text='again')])
    assert [a['id'] for a in check_demo(odd)['anchors']] == ['demo', 'in:t', 'out:1'], 'an id outside the grammar is dropped, and a bind two blocks share is kept once'
    long = check_demo(dict(anchors=[dict(id='in:t', kind='input', text='a' * 5000)], demo={}))
    assert len(long['anchors'][0]['text']) == 4000, 'a long state value is cut, not refused'
    for bad in ('x', dict(anchors='x', demo={}), dict(anchors=[], demo='x'), dict(anchors=[dict(id='in:t', kind='input')], demo={}),
                dict(anchors=[dict(id='out:1', kind='input', text='a')], demo={}), dict(anchors=[], demo=dict(inputs=[])),
                dict(anchors=[], demo=dict(readouts=[1])), dict(anchors=[dict(id=f'out:{i}', kind='readout', text='a') for i in range(1, 100)], demo={})):
        with pytest.raises(ValueError): check_demo(bad)

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
import json, sys, threading, types
import abhyasa, pytest
from leela.blocks.nb.nb import Notebook
from test_lesson_predict import DEMO as GATE_DEMO, lesson, post as predict, serve, shelf

EXPLAINED = dict(tier='tutor', steps=[dict(n=1, say='It is the share left.', strokes=[]), dict(n=2, say='It falls with t.', strokes=[])], sources=[dict(n=1, title='DDPM', url='', label='your vault', quoted=False)],
                 sure=0.9, failed=False, dropped=0, end="In the tutor's own words. No source found.", ms=3)

@pytest.fixture
def guide(monkeypatch):
    "A stand-in for `abhyasa.guide`: `calls` holds what `explain` was given. With the keywords of abhyasa 0.0.15 it sends a state event, a saved page and each step."
    import abhyasa.llm
    calls = AttrDict(thread=None)
    def explain(ask, ctx, said, sources=(), search=None, fetch=None, web=None, note=None, lr=None, **kw):
        calls.update(ask=ask, ctx=mod.clean_context(ctx), said=said, sources=list(sources), web=web, lr=lr, thread=threading.current_thread(), kw=kw)
        if note: note('The tutor looks in your vault.')
        if on_state := kw.get('on_state'): on_state(dict(wait='The tutor reads this page.', state='reading')); on_state(dict(saved=dict(title='A page', url='https://x.org')))
        if on_step := kw.get('on_step'):
            for k, s in enumerate(EXPLAINED['steps'], 1): on_step(s, k)
        return AttrDict(EXPLAINED)
    mod = types.ModuleType('abhyasa.guide')
    mod.explain, mod.clean_context, mod.norm_tex, mod.stream_board = explain, (lambda raw: AttrDict(raw, cleaned=True)), (lambda s: 'n:' + s.strip()), None
    monkeypatch.setitem(sys.modules, 'abhyasa.guide', mod)
    monkeypatch.setattr(abhyasa, 'guide', mod, raising=False)
    monkeypatch.setattr(abhyasa.llm, 'route_ask', lambda model=None: 'the ask')
    return calls

def ask_guide(r, i=1, said="I don't get alpha bar", **kw):
    cell = r.nb[i] if isinstance(i, int) else None
    return r.c.post('/nb/guide', json=dict(path=str(r.p), cell_id=cell.id if cell else i, said=said, **kw))

def events(res):
    "The `(event, data)` pairs of a server-sent event reply."
    out = []
    for frame in res.text.split('\n\n'):
        lines = dict(l.split(': ', 1) for l in frame.splitlines() if ': ' in l)
        if 'data' in lines: out.append((lines.get('event', 'message'), json.loads(lines['data'])))
    return out

def test_guide_stream_sends_each_step_before_the_board_and_frees_the_lock(serve, guide):
    r = serve(lesson())
    res = r.c.post('/nb/guide/stream', json=dict(path=str(r.p), cell_id=r.nb[1].id, said="I don't get alpha bar"))
    assert res.status_code == 200 and res.headers['content-type'].startswith('text/event-stream'), res.text
    ev = events(res)
    assert [e for e, _ in ev] == ['wait', 'step', 'step', 'board'], 'the saved page is not sent: Leela has no undo route for it'
    assert ev[0][1] == dict(wait='The tutor reads this page.', state='reading')
    assert [(d['k'], d['step']['say'], d['tier'], d['demo_open']) for e, d in ev if e == 'step'] == [(1, 'It is the share left.', 'tutor', False), (2, 'It falls with t.', 'tutor', False)]
    assert ev[-1][1]['steps'] == EXPLAINED['steps'] and ev[-1][1]['demo_open'] is False
    assert guide.thread is not threading.main_thread() and guide.kw['stop'].is_set() and guide.ctx['demo']['open'] is False
    assert ask_guide(r).status_code == 200, 'the lesson lock is free once the model call ends'
    res = r.c.post('/nb/guide/stream', json=dict(path=str(r.p), cell_id=r.nb[1].id, said='why?', demo=PAGE_DEMO))
    assert res.status_code == 200 and [a['id'] for a in guide.ctx.anchors][-3:] == ['demo', 'in:t', 'out:1'] and guide.ctx['demo']['inputs'] == PAGE_DEMO['demo']['inputs']

def test_guide_stream_reports_a_failed_explain_as_an_event_and_refuses_before_the_stream(serve, guide, monkeypatch):
    r = serve(lesson())
    def boom(*a, **k): raise RuntimeError('The guide task got no answer from the model.')
    monkeypatch.setattr(sys.modules['abhyasa.guide'], 'explain', boom)
    stream = lambda **kw: r.c.post('/nb/guide/stream', json=dict(path=str(r.p), cell_id=r.nb[1].id, said='why?') | kw)
    ev = events(stream())
    assert [e for e, _ in ev] == ['error'] and 'no answer' in ev[0][1]['error']
    assert stream().status_code == 200, 'a failed model call frees the lesson lock'
    def gone(*a, **k): raise ImportError('cannot import name VaultSource', name='abhyasa.ground')
    monkeypatch.setattr(sys.modules['abhyasa.guide'], 'explain', gone)
    assert [d['error'] for e, d in events(stream())] == [lesson_mod.GUIDE_STREAM_NEEDS], 'a missing part of abhyasa names the version the guide needs'
    for bad in (dict(said=' '), dict(cell_id='missing'), dict(anchors='f1'), dict(demo='x')):
        res = stream(**bad)
        assert res.status_code == 400 and res.json()['error'], bad
    monkeypatch.delattr(sys.modules['abhyasa.guide'], 'stream_board')
    res = stream()
    assert res.status_code == 400 and '0.0.15' in res.json()['error'], 'abhyasa 0.0.14 cannot stream a board'

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
  after(n) { this.next = n; }, append(...n) { this.children.push(...n); }});
const main = el('div'), out = el('div'), cell = el('div'), posts = [], dialogs = [], loads = [], plays = [], sets = [], target = el('span'), demoHost = {shadowRoot: {children: [{rupaka: {}}]}};
cell.guideEls = [{dataset: {guideId: 'f1', tex: ' a_t b ', parts: JSON.stringify([['a_t', 'g-1001-0'], ['b', 'g-1001-1']])}}, {dataset: {guideId: 'img1'}, alt: '', closest: () => ({querySelector: () => ({textContent: ' A cat '})})}, {dataset: {guideId: 'img2'}, alt: 'inline', closest: () => null}, {dataset: {guideId: 'f2'}}, {dataset: {guideId: 'demo'}}];
const ctx = {said: [], reply: null, selection: '', typed: null, CSS: {escape: s => s}, lee: {path: '/n.ipynb', nbQueue: Promise.resolve(), sel: 1,
  cells: [{id: 'a', cell_type: 'markdown', extra: {lesson: {role: 'prediction'}}}, {id: 'b', cell_type: 'markdown', extra: {}},
          {id: 'c', cell_type: 'code', extra: {exercise: {tests: []}}}, {id: 'd', cell_type: 'code', extra: {}}]}};
ctx.document = {createElement: el, addEventListener() {}, head: {appendChild(n) { loads.push(n); if (n.src) setTimeout(() => n.onerror()); return n; }}};
ctx.window = ctx; ctx.Rupaka = {set: (inner, s) => sets.push([inner, s])};
ctx.getSelection = () => ctx.selection;
ctx.$ = (sel, root) => sel === '.lee-rupaka' ? ctx.rupakaHost : sel === '.lee-cellmain' ? main : sel === '#out-b' ? out : sel.startsWith('.lee-cell[') ? cell : sel === '[data-guide-id="demo"]' ? demoHost : sel.startsWith('[data-guide-id=') ? target : null;
ctx.$$ = (sel, root) => sel === '[data-guide-id]' ? root.guideEls : [];
ctx.status = (t, k) => ctx.said.push([k, t]);
ctx.isExercise = c => c?.cell_type === 'code' && !!c.extra?.exercise?.tests;
ctx.inputDialog = async (...a) => { dialogs.push(a); return ctx.typed; };
ctx.AbortController = AbortController; ctx.delivered = [];
ctx.postEvents = async (url, body, onEvent, signal) => { posts.push([url, body]); if (ctx.reply instanceof Error) throw ctx.reply;
  for (const [e, d] of ctx.stream || [['board', ctx.reply]]) {
    if (ctx.gate && body.said === 'first') await ctx.gate;
    if (signal.aborted && !(ctx.buffered && body.said === 'first')) throw Object.assign(new Error('aborted'), {name: 'AbortError'});
    ctx.delivered.push(e); onEvent(e, d); await new Promise(r => setTimeout(r, 5)); } };
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
  r.played = [plays.length, board.steps.length, Object.keys(host).sort(), host.assets, out.next === undefined, host.resolve('f1') === target, host.resolve('demo') === demoHost]; r.voiceAt = opts.voiceAt;
  host.demo({t: 1}); r.closed = sets.length; ctx.reply = Object.assign({}, ctx.reply, {demo_open: true});
  await ctx.lessonGuide('b'); plays.at(-1)[1].host.demo({t: 2}); r.open = sets.map(s => s[1]);
  out.next = undefined; ctx.abhyasaBoard = {play: async () => { throw new Error('rough.js'); }}; await ctx.lessonGuide('b'); r.broke = out.next.textContent.split('\n')[0];
  ctx.abhyasaBoard = undefined; ctx.reply.demo_open = false;
  ctx.said = []; ctx.typed = null; posts.length = 0; await ctx.lessonGuide('b'); r.cancel = posts.length;
  ctx.typed = 'why?'; ctx.reply = Object.assign(new Error('x'), {body: {ok: false, error: 'The screen guide needs abhyasa 0.0.14 or newer.'}}); await ctx.lessonGuide('b'); r.failed = ctx.said.at(-1);
  ctx.said = []; ctx.lee.sel = 3; await ctx.lessonGuideSelected('alpha'); r.notCell = ctx.said;
  ctx.lee.sel = 1; ctx.typed = null; dialogs.length = 0; await ctx.lessonGuideSelected('beta'); r.picked = dialogs[0].slice(2, 3);
  const S1 = {n: 1, say: 'one', strokes: []}, S2 = {n: 2, say: 'two', strokes: []}, whole = {tier: 'tutor', steps: [S1, S2], sources: [], end: 'End.'};
  const mk = () => { const b = {log: [], st: null, ok: true,
    play: async (bd, o) => { b.log.push(['play', bd.steps.length, !!bd.streaming, ctx.delivered.length]); b.st = {streaming: !!bd.streaming}; b.host = o.host; },
    add: s => { b.log.push(['add', s.say]); return true; },
    finish: d => { b.log.push(['finish', d.steps.length, d.end]); if (b.ok) b.st.streaming = false; return b.ok; },
    get state() { return b.st; }}; return b; };
  const run = async (stream, set) => { const b = ctx.abhyasaBoard = mk(); set?.(b); ctx.stream = stream; ctx.delivered = []; ctx.reply = null; ctx.typed = 'why?'; out.next = undefined; ctx.said = []; await ctx.lessonGuide('b'); return b; };
  const steps = [['wait', {wait: 'The tutor reads this page.'}], ['step', {step: S1, k: 1, tier: 'tutor', demo_open: true}], ['step', {step: S2, k: 2, tier: 'tutor', demo_open: true}]];
  let b = await run([...steps, ['board', whole]]); r.streamed = b.log; r.streamUrl = posts.at(-1)[0]; r.waitSaid = ctx.said[1];
  b.host.demo({t: 3}); r.streamDemo = sets.at(-1)[1];
  b = await run([...steps, ['board', whole]], b => { b.ok = false; }); r.refused = b.log;
  b = await run([steps[1], steps[2], ['board', whole]], b => { const play = b.play; b.play = async (...a) => { await play(...a); b.st = null; }; }); r.stopped = [b.log, out.next === undefined];
  b = await run(steps); r.ended = b.log;
  b = await run([steps[1], ['error', {error: 'The tutor could not answer.'}]]); r.errored = [b.log, ctx.said.at(-1)];
  ctx.abhyasaBoard = b = mk(); ctx.delivered = []; let open; ctx.gate = new Promise(o => { open = o; }); ctx.stream = [steps[1], ['board', whole]];
  ctx.typed = 'first'; const p1 = ctx.lessonGuide('b'); await new Promise(r => setTimeout(r, 20));
  ctx.typed = 'second'; await ctx.lessonGuide('b'); open(); await p1; ctx.gate = null;
  r.superseded = b.log.map(x => x.slice(0, 3));
  ctx.abhyasaBoard = b = mk(); ctx.delivered = []; ctx.gate = new Promise(o => { open = o; }); ctx.buffered = true; ctx.said = [];
  ctx.typed = 'first'; const p3 = ctx.lessonGuide('b'); await new Promise(r => setTimeout(r, 20));
  ctx.typed = 'second'; await ctx.lessonGuide('b'); open(); await p3; ctx.gate = null; ctx.buffered = false;
  r.buffered = [b.log.map(x => x.slice(0, 3)), ctx.said.at(-1)];
  const inner = {rupaka: {spec: {}}}; ctx.rupakaHost = {shadowRoot: {children: [{}, inner]}};
  b = await run([['board', whole]], b => { b.demoAnchors = h => ({anchors: [{id: 'in:t', kind: 'input', text: h === inner ? 'inner' : 'host'}], demo: {inputs: {}, readouts: []}}); });
  r.pageDemo = posts.at(-1)[1].demo; ctx.rupakaHost = undefined;
  const S1b = {n: 1, say: 'one', strokes: [{op: 'circle', at: 'f1'}]};
  b = await run([steps[1], ['step', {step: S1b, k: 1, tier: 'tutor'}], steps[2]], b => { b.add = s => { b.log.push(['add', s.say, s.strokes.length]); return true; }; const f = b.finish; b.finish = d => { b.log.push(['finished', d.steps.map(x => x.strokes.length)]); return f(d); }; });
  r.grown = b.log;
  b = await run([['show', {show: {title: 'Halves', href: 'http://127.0.0.1:5126/c/halves?show=alpha'}}]], b => { b.stop = () => b.log.push(['stop']); });
  r.show = [b.log, out.next.textContent, out.next.children.map(c => c.href || c), ctx.said.at(-1)];
  b = await run([['show', {show: {title: 'Halves', href: null}}]], b => { b.stop = () => {}; }); r.showOff = [out.next.textContent, out.next.children];
  console.log(JSON.stringify(r)); })();'''
    r = subprocess.run([node, '-e', harness, str(Path(__file__).parents[1]/'leela/blocks/nb/lesson.js')], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    assert got['buttons'] == [[], ["I don't get…"], ["I don't get…"], []], 'a markdown or exercise cell, never a prediction, a card or a plain code cell'
    assert got['plain'] == [], 'a notebook with no lesson cell is not a lesson'
    assert got['dialog'] == ["I don't get alpha bar"] and got['post'] == ['/nb/guide/stream', dict(path='/n.ipynb', cell_id='b', said="I don't get alpha bar", anchors=[dict(id='f1', text='a_t b', parts=['a_t', 'b']), dict(id='img1', text='A cat'), dict(id='img2', text='inline'), dict(id='f2', text='', parts=[])])]
    assert any('lee-board.js' in s for s in got['loaded']) and any('lee-board.css' in s for s in got['loaded'])
    assert got['played'] == [1, 2, ['assets', 'demo', 'resolve'], '/leestatic/board/', True, True, True], 'the board is drawn, not the text, with no speak hook'
    assert got['voiceAt'] == dict(model='Browser voice', where='on this computer'), 'the strip names the voice that speaks'
    assert got['closed'] == 0 and got['open'] == [{'t': 2}], 'the demo moves only when every gate is filed'
    assert got['broke'] == 'It is the share left.', 'a board that fails to draw leaves the plain text'
    assert got['out'].splitlines() == ['It is the share left.', 'It falls with t.', 'Source 1: your vault, DDPM', "In the tutor's own words."]
    assert got['cancel'] == 0 and got['failed'] == ['err', 'The screen guide needs abhyasa 0.0.14 or newer.']
    assert got['notCell'] == [['err', 'Pick a lesson cell first.']] and got['picked'] == ["I don't get beta"]
    assert got['streamUrl'] == '/nb/guide/stream' and got['waitSaid'] == ['ok', 'The tutor reads this page.']
    assert got['streamed'] == [['play', 1, True, 2], ['add', 'two'], ['finish', 2, 'End.']], 'step 1 draws after two events, before the board event, and the board event finishes it'
    assert got['streamDemo'] == {'t': 3}, 'a step says whether the demo is open, so a streamed board can move it'
    assert got['refused'][-1] == ['play', 2, False, 4], 'a board that does not begin with the steps shown plays whole'
    assert got['stopped'] == [[['play', 1, True, 1]], True], 'a board the learner stopped takes no later step, no finish and no text'
    assert got['ended'] == [['play', 1, True, 2], ['add', 'two'], ['finish', 2, '']], 'a stream with steps and no board ends the board with no end line'
    assert got['errored'] == [[['play', 1, True, 1], ['finish', 1, '']], ['err', 'The tutor could not answer.']], 'an error after a step ends the board and says why'
    assert got['superseded'] == [['play', 1, True], ['finish', 2, 'End.']], 'a newer question aborts the older one, whose events go nowhere'
    assert got['pageDemo'] == dict(anchors=[dict(id='in:t', kind='input', text='inner')], demo=dict(inputs={}, readouts=[])), 'the page sends the demo ids that board.js gives the rupaka element'
    assert 'demo' not in got['post'][1], 'a cell with no rupaka demo sends no demo'
    assert got['buffered'] == [[['play', 1, True], ['finish', 2, 'End.']], ['ok', '']], 'frames of the older question that come after its abort draw nothing'
    assert got['grown'] == [['play', 1, True, 1], ['add', 'one', 1], ['add', 'two', 0], ['finished', [1, 0]], ['finish', 2, '']], 'a step that comes again with its `n` grows in place, and the end keeps the grown step once'
    assert got['show'] == [[['stop']], 'Show: Halves. ', ['http://127.0.0.1:5126/c/halves?show=alpha'], ['ok', '']], '"show me" hands off to the demo in abhyasa, with no board'
    assert got['showOff'] == ['Show: Halves. ', ['Start abhyasa to see the demo of this idea.']]

def test_code_anchors_come_from_the_page_for_any_cell():
    "abhyasa main's board copies values from code and its output (code1 to code4) into its panel."
    page = [dict(id='code1', text='def double(x): return 2 * x'), dict(id='code2', text='4'), dict(id='f1', text='a', parts=['a'])]
    assert check_anchors(page) == page
    for bad in ([dict(id='code5', text='x')], [dict(id='code0', text='x')], [dict(id='code1', text='x', parts=['x'])]):
        with pytest.raises(ValueError): check_anchors(bad)
    a = by_id(guide_context(META, Cell(source='print(1)'), anchors=page))
    assert list(a) == ['code1', 'code2'] and a['code1'] == dict(id='code1', kind='code', text='def double(x): return 2 * x')
    assert list(by_id(guide_context(META, md('Text.'), anchors=page))) == ['passage', 'f1', 'code1', 'code2']
    task, code = exercise_cells(dict(task='Double a number.', fname='double', stub='def double(x):\n    pass', uses=[],
        tests=[dict(say='Two doubles to four', test='assert double(2) == 4', shown=True)]))
    assert list(by_id(guide_context(META, code, anchors=page[:2]))) == ['check', 'code1', 'code2']

@pytest.mark.parametrize('running', [True, False])
def test_show_me_hands_off_to_the_demo_in_abhyasa_and_asks_no_model(serve, guide, monkeypatch, running):
    "abhyasa main answers \"show me …\" with Show, never a board; in Leela that is a link to the idea's demo in abhyasa."
    import abhyasa.demo
    from leela.blocks.learn import learn
    monkeypatch.setattr(abhyasa.demo, 'show_reply', lambda said, thread=(): said.removeprefix('show me ').strip() if said.startswith('show me') else None, raising=False)
    monkeypatch.setattr(learn, 'abhyasa_address', lambda: dict(url='http://127.0.0.1:5126', vault='v', pid=1) if running else {})
    r = serve(lesson())
    res = r.c.post('/nb/guide/stream', json=dict(path=str(r.p), cell_id=r.nb[1].id, said='show me alpha bar'))
    href = 'http://127.0.0.1:5126/c/halves?show=alpha%20bar' if running else None
    assert events(res) == [('show', dict(show=dict(title='Halves', href=href)))] and 'ask' not in guide, 'Show asks no model'
    assert ask_guide(r, said='show me alpha bar').json() == dict(ok=True, show=dict(title='Halves', href=href))
    assert [e for e, _ in events(r.c.post('/nb/guide/stream', json=dict(path=str(r.p), cell_id=r.nb[1].id, said="I don't get alpha bar")))][-1] == 'board'
