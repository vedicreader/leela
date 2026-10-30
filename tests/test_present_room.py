import base64, html, io, json, re, subprocess
from html.parser import HTMLParser
from importlib.resources import files
import pytest
from PIL import Image
from rupaka.spec import demo, gate, is_, readout, slider, validate
from leela.blocks.fs.fs import Sandbox
from leela.blocks.nb.show import ROOM_LONG, clean_out, clip_msg, decks, demo_fences, room_spec, slide_html

KEY = 'ab' * 8
IMG = re.compile(r'<img\b[^>]*>')
SRC = re.compile(r'src="([^"]*)"')
OURS = re.compile(r'^/present/img/([0-9a-f]{64})\?k=' + KEY + '$')

def _img(fmt='PNG', size=(4, 3), colour=(200, 30, 30)):
    b = io.BytesIO(); Image.new('RGB', size, colour).save(b, fmt); return b.getvalue()

def _spec(slug='d1', answer=is_('two')):
    return demo(slug, title='Weights', state={'x': 2}, blocks=[slider('x', label='x', min=0, max=4, step=1),
        gate('g1', 'Which one?', ['one', 'two'], answer, why='because'), readout('x is {x}')])

def _fence(spec, ch='`', n=3, info='rupaka'): return f'{ch*n}{info}\n{json.dumps(spec)}\n{ch*n}'

def _gates(x):
    if isinstance(x, list):
        for v in x: yield from _gates(v)
    elif isinstance(x, dict):
        if x.get('type') == 'gate': yield x
        for v in x.values(): yield from _gates(v)

def _srcs(s): return [m for t in IMG.findall(s) for m in SRC.findall(t)]

def _cell(id, kind, source, outputs=()): return dict(id=id, cell_type=kind, source=source, outputs=list(outputs))

class _Tags(HTMLParser):
    "Fails on an end tag that closes no open element; `stack` is what stays open."
    VOID = set('area base br col embed hr img input link meta source track wbr'.split())
    def __init__(self): super().__init__(convert_charrefs=True); self.stack, self.text = [], []
    def handle_starttag(self, tag, a):
        if tag not in self.VOID: self.stack.append(tag)
    def handle_endtag(self, tag): assert self.stack and self.stack.pop() == tag, tag
    def handle_data(self, d): self.text.append(d)

def _balanced(s):
    p = _Tags(); p.feed(s); p.close(); return not p.stack

def test_room_spec_hides_the_gate_answer_and_keeps_the_rest():
    s = _spec(); r = room_spec(s)
    assert not list(validate(s)) and [g.get('answer') for g in _gates(s)] == [{'is': 'two'}]
    assert [g for g in _gates(r)] == [{k: v for k, v in g.items() if k != 'answer'} for g in _gates(s)]
    assert r['state'] == s['state'] and r['blocks'][0] == s['blocks'][0] and r['blocks'][2] == s['blocks'][2]
    p = room_spec(_spec(answer='x'))
    assert '"answer"' not in json.dumps(p) and p['state'] == {'x': 2}   # limit: a state-path answer can still be read from the state

FENCES = dict(back=_fence(_spec()), tilde=_fence(_spec(), '~'), longer=_fence({**_spec(), 'title': 'a ``` b'}, n=5),
              quote='> ' + _fence(_spec()).replace('\n', '\n> '), listed='- item\n\n  ' + _fence(_spec()).replace('\n', '\n  '),
              crlf=_fence(_spec()).replace('\n', '\r\n'), unclosed='```rupaka\n' + json.dumps(_spec()), info=_fence(_spec(), info='rupaka demo'))

@pytest.mark.parametrize('k', FENCES)
def test_demo_fences_find_every_fence_the_page_mounts(k):
    out, specs = slide_html('Before\n\n' + FENCES[k] + ('' if k == 'unclosed' else '\n\nAfter'), '', KEY, {}, room=False)
    assert specs == [{**_spec(), 'title': 'a ``` b'} if k == 'longer' else _spec()] and 'Before' in out and (k == 'unclosed' or 'After' in out)

def test_slide_html_puts_room_demos_in_place_and_drops_bad_fences():
    md = '\n\n'.join(['Before', _fence(_spec('d1')), 'Middle', '```rupaka\n{not json\n```', '```rupaka\n{"id": "bad", "blocks": [{"type": "nope"}]}\n```',
                      _fence(_spec('d2'), '~'), '````markdown\n' + _fence(_spec('d3')) + '\n````', 'After'])
    room, rs = slide_html(md, '', KEY, {})
    pres, ps = slide_html(md, '', KEY, {}, room=False)
    assert [s['id'] for s in rs] == ['d1', 'd2'] == [s['id'] for s in ps] and rs == [room_spec(s) for s in ps] and ps == [_spec('d1'), _spec('d2')]
    assert room.index('Before') < room.index('"d1"') < room.index('Middle') < room.index('"d2"') < room.index('After')
    assert 'not json' not in room and '"bad"' not in room and room.count('language-rupaka') == 2 and demo_fences(room)[1] == []   # a room spec is not a valid spec
    assert 'language-markdown' in room and 'd3' in room   # a fence shown as code stays code, as the IDE shows it
    assert 'answer' not in room[:room.index('language-markdown')] and pres[:pres.index('language-markdown')].count('"answer"') == 2

def test_room_markup_drops_comments_ids_titles_and_paths(tmp_path):
    md = '<!-- ANSWER-HINT -->\n\n<span id="x" data-id="y" title="HOVER-HINT">q</span> [rel](../a.md) [web](https://example.org/p) [top](#top) [abs](/etc/passwd)\n\n```{=html}\n<b>RAW</b>\n```'
    s, _ = slide_html(md, str(tmp_path), KEY, {}, Sandbox([tmp_path]))
    assert 'ANSWER-HINT' not in s and 'HOVER-HINT' not in s and 'data-id' not in s and 'id=' not in s
    assert 'a.md' not in s and '/etc/passwd' not in s and 'href="https://example.org/p"' in s and 'href="#top"' in s
    assert '<b>' not in s and 'language-html' in s and 'RAW' in s and '<span>q</span>' in s

def test_every_image_goes_into_the_store_or_is_dropped(tmp_path):
    root, out = tmp_path/'root', tmp_path/'out'; root.mkdir(); out.mkdir()
    png, gif = _img(), _img('GIF')
    (root/'a.png').write_bytes(png); (root/'sub').mkdir(); (root/'sub'/'b.gif').write_bytes(gif)
    (out/'c.png').write_bytes(_img(colour=(1, 2, 3))); (root/'fake.png').write_bytes(b'<svg onload="x()"></svg>')
    (root/'link.png').symlink_to(out/'c.png')
    data = 'data:image/png;base64,' + base64.b64encode(_img(colour=(9, 9, 9))).decode()
    md = ' '.join(f'![{n}]({s})' for n, s in [('A', 'a.png'), ('B', 'sub/b.gif'), ('C', '../out/c.png'), ('D', str(out/'c.png')), ('E', 'fake.png'),
        ('F', 'https://evil.example/x.png'), ('G', '//evil.example/y.png'), ('H', '/file/raw?path=/etc/x.png'), ('I', data), ('J', 'link.png'), ('K', 'a.png?v=1#x')])
    imgs = {}
    s, _ = slide_html(md, str(root), KEY, imgs, Sandbox([root]))
    kept = [OURS.match(x).group(1) for x in _srcs(s)]
    assert all(OURS.match(x) for x in _srcs(s)) and len(kept) == 4 and set(kept) == set(imgs) and len(imgs) == 3
    assert sorted(t for t, _ in imgs.values()) == ['image/gif', 'image/png', 'image/png'] and png in [b for _, b in imgs.values()]
    assert 'evil.example' not in s and str(tmp_path) not in s and 'file/raw' not in s and 'data:' not in s
    none = {}; s2, _ = slide_html(md, str(root), KEY, none)   # no workspace: no local file is read
    assert len(none) == 1 and len(_srcs(s2)) == 1

def test_clean_out_keeps_text_and_images_only():
    png, jpg, webp = _img(), _img('JPEG'), _img('WEBP')
    outs = [{'output_type': 'stream', 'name': 'stdout', 'text': 'tick 0 \x1b[32mgreen\x1b[0m <b>&\n'},
            {'output_type': 'display_data', 'data': {'text/html': '<b onclick="x()">ok</b><script>alert(1)</script><img src="https://evil.example/a.png">'
                '<img src="//evil.example/b.png"><iframe src="/x"></iframe><style>p{color:red}</style><svg><foreignObject><b>svgx</b></foreignObject></svg>'
                '<a href="jav&#x09;ascript:alert(1)">j1</a><a href="JaVaScRiPt:alert(1)">j2</a><a href="data:text/html,hi">j3</a><img src="data:image/svg+xml;base64,PHN2Zz4=">'
                '<img src="x" onerror="alert(1)"><p style="x" class="lee-ui">styled</p>'}},
            {'output_type': 'display_data', 'data': {'image/png': base64.b64encode(png).decode(), 'text/plain': '<Figure>'}, 'metadata': {'image/png': {'width': 2}}},
            {'output_type': 'execute_result', 'data': {'image/jpeg': base64.b64encode(jpg).decode(), 'text/plain': 'j'}},
            {'output_type': 'display_data', 'data': {'image/webp': base64.b64encode(webp).decode()}},
            {'output_type': 'display_data', 'data': {'image/svg+xml': '<svg onload="x()"/>', 'text/plain': 'SVG-FALLBACK'}},
            {'output_type': 'display_data', 'data': {'application/vnd.jupyter.widget-view+json': {'model_id': 'm'}, 'text/plain': 'WIDGET-FALLBACK'}},
            {'output_type': 'display_data', 'data': {'application/javascript': 'window.hit = 1', 'text/plain': 'JS-FALLBACK'}},
            {'output_type': 'display_data', 'data': {'application/vnd.plotly.v1+json': {'data': []}, 'text/plain': 'PLOT-FALLBACK'}},
            {'output_type': 'display_data', 'data': {'image/png': base64.b64encode(b'GIF89a not a png').decode(), 'text/plain': 'BAD-PNG'}},
            {'output_type': 'execute_result', 'data': {'text/markdown': '**md**\n\n' + _fence(_spec('m1')), 'text/plain': 'x'}},
            {'output_type': 'error', 'ename': 'ZeroDivisionError', 'evalue': 'division by zero', 'traceback': ['\x1b[31mZeroDivisionError\x1b[0m', 'line 2']}]
    imgs = {}
    room, err = clean_out(outs, KEY, imgs)
    assert 'tick 0 green &lt;b&gt;&amp;' in room and '<b>ok</b>' in room and 'styled' in room and 'ZeroDivisionError' not in room and '\x1b' not in room
    assert 'script' not in room and 'onclick' not in room and 'onerror' not in room and 'onload' not in room and 'evil.example' not in room
    assert 'iframe' not in room and '<style' not in room and 'style=' not in room and '<svg' not in room.lower() and 'svg+xml' not in room and 'svgx' not in room
    assert 'javascript' not in room.lower() and 'data:' not in room
    assert 'lee-ui' not in room and 'j1' in room and 'href' not in room
    assert 'SVG-FALLBACK' in room and 'WIDGET-FALLBACK' in room and 'JS-FALLBACK' in room and 'PLOT-FALLBACK' in room and 'window.hit' not in room
    assert 'BAD-PNG' in room and 'Figure' not in room and '<strong>md</strong>' in room and room.count('language-rupaka') == 1 and '"answer"' not in room
    assert sorted(t for t, _ in imgs.values()) == ['image/jpeg', 'image/png', 'image/webp'] and all(OURS.match(x) for x in _srcs(room)) and len(_srcs(room)) == 3
    assert 'width="2"' in room
    assert err == {'ename': 'ZeroDivisionError', 'evalue': 'division by zero', 'traceback': ['ZeroDivisionError', 'line 2']}
    assert clean_out(outs[:1], KEY, {})[1] is None
    pres, _ = clean_out(outs[-2:], KEY, {}, room=False)
    assert '"answer"' in pres

def test_a_rupaka_output_mounts_the_room_demo_never_its_html_page():
    out = {'output_type': 'display_data', 'data': {'application/vnd.rupaka+json': _spec('o1'), 'text/html': '<p>HTML-PAGE-FALLBACK</p>' + json.dumps(_spec('o1'))}}
    room, _ = clean_out([out], KEY, {})
    pres, _ = clean_out([out], KEY, {}, room=False)
    assert 'HTML-PAGE-FALLBACK' not in room and room.count('language-rupaka') == 1 and '"o1"' in room and '"answer"' not in room
    assert '"answer"' in pres
    s = json.loads(html.unescape(re.search(r'<code class="language-rupaka">(.*?)</code>', room, re.S).group(1)))
    assert s == room_spec(_spec('o1'))
    bad, _ = clean_out([{'output_type': 'display_data', 'data': {'application/vnd.rupaka+json': '{"id": "x", "blocks": []}', 'text/html': 'FALLBACK'}}], KEY, {})
    assert 'language-rupaka' not in bad and 'FALLBACK' not in bad and '"x"' not in bad

def test_image_count_and_bytes_are_bounded_separately(monkeypatch):
    import leela.blocks.nb.show as show
    many = [{'output_type': 'display_data', 'data': {'image/png': base64.b64encode(_img(colour=(i, 0, 0))).decode()}} for i in range(show.IMG_MOST + 5)]
    imgs = {}; room, _ = clean_out(many, KEY, imgs)
    assert len(imgs) == show.IMG_MOST == len(_srcs(room))
    one = _img(size=(64, 64)); monkeypatch.setattr(show, 'IMG_TOTAL', len(one) * 2 + 1)
    five = [{'output_type': 'display_data', 'data': {'image/png': base64.b64encode(_img(size=(64, 64), colour=(i, 1, 1))).decode()}} for i in range(5)]
    imgs = {}; room, _ = clean_out(five[:1] * 2 + five, KEY, imgs)
    assert sum(len(b) for _, b in imgs.values()) <= show.IMG_TOTAL and 1 <= len(imgs) < 5 and len(_srcs(room)) >= 2
    monkeypatch.setattr(show, 'IMG_BYTES', len(one) - 1)
    assert clean_out([{'output_type': 'display_data', 'data': {'image/png': base64.b64encode(one).decode()}}], KEY, (imgs := {}))[0] == '' and not imgs
    monkeypatch.undo()
    big = _img(size=(1, 1)); i = big.index(b'IHDR'); big = big[:i + 4] + (100000).to_bytes(4, 'big') * 2 + big[i + 12:]
    assert clean_out([{'output_type': 'display_data', 'data': {'image/png': base64.b64encode(big).decode()}}], KEY, (imgs := {}))[0] == '' and not imgs

def _decks(tmp_path):
    (tmp_path/'pic.png').write_bytes(_img()); (tmp_path/'notes.png').write_bytes(_img(colour=(5, 5, 5)))
    cells = [_cell('m0', 'markdown', '# Intro\n\nScores become weights. ![p](pic.png)\n\n' + _fence(_spec('d1')) + '\n\n<!-- ANSWER-HINT -->'),
             _cell('n1', 'markdown', 'SPEAKER-SECRET ![n](notes.png) ' + _fence(_spec('dn'))),
             _cell('skip2', 'markdown', 'SKIPPED-SECRET'),
             _cell('c3', 'code', 'print(1)', [{'output_type': 'stream', 'name': 'stdout', 'text': '1\n'},
                 {'output_type': 'display_data', 'data': {'application/vnd.rupaka+json': _spec('o1'), 'text/html': 'HTML-PAGE-FALLBACK'}},
                 {'output_type': 'error', 'ename': 'ValueError', 'evalue': 'TRACE-SECRET', 'traceback': ['TRACE-SECRET']}]),
             _cell('m4', 'markdown', '## Second\ntext')]
    line = [dict(items=[dict(i=0, frag=-1), dict(i=3, frag=0)], notes=[1], groups=1), dict(items=[dict(i=4, frag=-1)], notes=[], groups=0)]
    return decks(line, cells, str(tmp_path), KEY, 'a', dict(theme='cursor:light:tight', mono='Menlo'), Sandbox([tmp_path])), cells, line

def test_room_copy_has_no_notes_answers_or_paths(tmp_path):
    (p, r, imgs), cells, _ = _decks(tmp_path)
    ps, rs = json.dumps(p), json.dumps(r)
    for secret in ('SPEAKER-SECRET', 'TRACE-SECRET'): assert secret in ps and secret not in rs
    for secret in ('SKIPPED-SECRET', 'HTML-PAGE-FALLBACK', 'ANSWER-HINT', str(tmp_path), '"dn"', 'n1', 'skip2'): assert secret not in rs
    assert 'answer' not in rs and '"answer"' in ps
    assert [s['id'] for s in r['slides']] == ['s1', 's2'] == [s['id'] for s in p['slides']] and r['title'] == 'a' and r['look'] == p['look']
    assert set(r['slides'][0]) == {'id', 'groups', 'blocks'} and {'notes', 'next'} <= set(p['slides'][0])
    assert [(b['cell'], b['frag'], b['kind']) for b in r['slides'][0]['blocks']] == [('m0', -1, 'markdown'), ('c3', 0, 'code')]
    b0, c3 = r['slides'][0]['blocks']
    assert 'Scores become weights.' in b0['html'] and b0['demo'] == [room_spec(_spec('d1'))] and p['slides'][0]['blocks'][0]['demo'] == [_spec('d1')]
    assert 'print' in c3['html'] and '1' in c3['out'] and c3['demo'] == [room_spec(_spec('o1'))] and 'error' not in c3
    assert p['slides'][0]['blocks'][1]['error']['evalue'] == 'TRACE-SECRET' and p['slides'][0]['next'] == 'Second' and p['slides'][1]['next'] == ''
    srcs = _srcs(rs.replace('\\"', '"'))
    assert srcs and all(OURS.match(x) for x in srcs) and {OURS.match(x).group(1) for x in srcs} == set(imgs) and len(imgs) == 1
    assert 'notes.png' not in ps and len(_srcs(p['slides'][0]['notes'])) == 0   # notes images never enter the store the room can read

def test_a_gate_answer_never_reaches_the_room_before_reveal(tmp_path):
    (p, r, _), _, _ = _decks(tmp_path)
    rs = json.dumps(r)
    assert not list(_gates(r)) or all('answer' not in g for g in _gates(r))
    for b in r['slides'][0]['blocks']:
        assert '"answer"' not in b['html'] + b.get('out', '') and all('answer' not in g for g in _gates(b['demo']))
    assert [g['options'] for g in _gates(r['slides'][0]['blocks'][0]['demo'])] == [['one', 'two']]
    assert [g['answer'] for g in _gates(p['slides'][0]['blocks'][0]['demo'])] == [{'is': 'two'}]
    assert 'because' in rs and 'Which one?' in rs

def test_notes_and_items_must_be_disjoint(tmp_path):
    cells = [_cell('a', 'markdown', 'x'), _cell('b', 'markdown', 'y')]
    for line in ([dict(items=[dict(i=0, frag=-1)], notes=[0], groups=0)], [dict(items=[dict(i=0, frag=-1)], notes=[]), dict(items=[dict(i=1, frag=-1)], notes=[0])],
                 [dict(items=[dict(i=5, frag=-1)], notes=[])]):
        with pytest.raises(ValueError): decks(line, cells, str(tmp_path), KEY, 't', {})

STAGE = files('abhyasa.core')/'stage.js'
CELLOUT = ("abhyasaStage.add('cellout', {cell: v => typeof v === 'string' && v.length <= 64, gen: v => Number.isInteger(v) && v >= 0,"
           " seq: v => Number.isInteger(v) && v >= 0, html: v => typeof v === 'string'});")

def _node(msgs):
    js = STAGE.read_text() + CELLOUT + f'\nprocess.stdout.write(JSON.stringify({json.dumps(msgs)}.map(m => Object.assign({{v: 1}}, m)).map(m => [abhyasaStage.valid(m), JSON.stringify(m).length])));'
    return json.loads(subprocess.run(['node', '-'], input=js, capture_output=True, text=True, check=True).stdout)

def _msg(h): return dict(t='cellout', cell='c3', gen=1, seq=2, html=h)

def test_clip_counts_the_whole_message():
    big = {'escapes': '<pre>' + html.escape('"\\<\n\x01' * 30_000) + '</pre>',
           'emoji': '<p>' + '😀é' * 40_000 + '</p>',
           'images': '<p>lead</p>' + ''.join(f'<img src="/present/img/{i:064x}?k={KEY}" alt="i">' for i in range(2000)),
           'nested': '<p>lead</p><div><ul>' + '<li><b>a &amp; b &lt; c</b> <i>x</i></li>' * 4000 + '</ul></div><p>tail</p>',
           'blocks': ''.join(f'<p>block {i} {"y" * 50}</p>' for i in range(3000)),
           'surrogates': '<p>' + 'a\ud800b\udc00' * 30_000 + '</p>'}
    got = {k: clip_msg(_msg(h)) for k, h in big.items()}
    for k, m in got.items():
        assert m['html'].endswith(ROOM_LONG) and _balanced(m['html']), k
        assert {x: m[x] for x in ('t', 'cell', 'gen', 'seq')} == {x: _msg('')[x] for x in ('t', 'cell', 'gen', 'seq')}
    res = dict(zip(got, _node(list(got.values()))))
    for k, (ok, n) in res.items(): assert ok and 60_000 < n <= 65536, (k, n)
    assert got['escapes']['html'].startswith('<pre>' + html.escape('"\\<\n\x01' * 100, quote=False)) and got['emoji']['html'].startswith('<p>' + '😀é' * 1000)
    assert got['images']['html'].startswith('<p>lead</p><img') and got['images']['html'].count('<img') > 500
    assert got['nested']['html'].startswith('<p>lead</p><div><ul><li><b>a &amp; b &lt; c</b>') and '</ul></div>' in got['nested']['html'] and 'tail' not in got['nested']['html']
    assert got['blocks']['html'].startswith('<p>block 0 ') and re.fullmatch(r'(<p>block \d+ y*</p>)+(<p>[^<]*</p>)?' + re.escape(ROOM_LONG), got['blocks']['html'])
    assert '\ud800' not in got['surrogates']['html'] and 'a\ufffdb' in got['surrogates']['html']
    small = _msg('<p>small</p>')
    assert clip_msg(small) == small and _node([small]) == [[True, len(json.dumps({'v': 1, **small}, separators=(',', ':')))]]
    edge = _msg('<p>' + 'x' * (65536 - len(json.dumps({'v': 1, **_msg('<p></p>')}, separators=(',', ':')))) + '</p>')
    assert clip_msg(edge) == edge and _node([edge]) == [[True, 65536]]
    over = _msg(edge['html'].replace('<p>', '<p>x'))
    assert clip_msg(over)['html'].endswith(ROOM_LONG) and _node([clip_msg(over)])[0][0]
    with pytest.raises(ValueError): clip_msg(dict(_msg('<p>x</p>' * 10), cell='c' * 65500))

def test_an_output_the_room_cannot_show_says_so():
    "An output with no type the room shows vanished from the slide; it now says so, in both copies."
    from leela.blocks.nb.show import NOT_SHOWN
    outs = [{'output_type': 'display_data', 'data': {'application/vnd.jupyter.widget-view+json': {'model_id': 'm'}}},
            {'output_type': 'display_data', 'data': {'image/svg+xml': '<svg/>'}}]
    for room in (True, False): assert clean_out(outs, KEY, {}, room=room)[0] == NOT_SHOWN * 2
    assert NOT_SHOWN == '<p class="nb-none">This output type is not shown in presentations.</p>'
    assert clean_out([{'output_type': 'display_data', 'data': {'image/svg+xml': '<svg/>', 'text/plain': 'fallback'}}], KEY, {})[0] == '<pre>fallback</pre>'
