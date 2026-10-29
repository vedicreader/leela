"Raw HTML in a Markdown render: what reaches `innerHTML` is parsed and checked, never grepped."
import re
import pytest
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.workspace import Workspace

import fast5ever

#: The policy as the test states it, independent of the implementation's own lists.
TAGS = set('a abbr b blockquote br caption cite code col colgroup dd del details div dl dt em figcaption figure h1 h2 h3 h4 h5 h6 hr i img input ins kbd li mark ol p pre q s samp section small span strong sub summary sup table tbody td tfoot th thead tr u ul var'.split())
CLASS_OK = re.compile(r'^(language-|hl-|footnote-)')
CLASS_NAMES = {'footnotes', 'task-list', 'xref', 'math', 'inline', 'display'}
ID_OK = re.compile(r'^[A-Za-z][\w:.-]{0,80}$')
BAD_ATTRS = {'srcdoc', 'style', 'formaction', 'action'}
DATA_IMG = re.compile(r'^data:image/(png|jpeg|gif|webp|avif);base64,')

def fence(h): return f'```{{=html}}\n{h}\n```'

ATTACKS = {
    'img onerror': fence('<img src=x onerror=alert(1)>'),
    'svg onload': fence('<svg onload=alert(1)><circle r=1 /></svg>'),
    'a javascript': fence('<a href="javascript:alert(1)">x</a>'),
    'markdown javascript link': '[x](javascript:alert(1))',
    'vbscript': fence('<a href="vbscript:msgbox(1)">x</a>'),
    'data html href': fence('<a href="data:text/html,<script>alert(1)</script>">x</a>'),
    'data svg img': fence('<img src="data:image/svg+xml;base64,PHN2ZyBvbmxvYWQ9YWxlcnQoMSk+">'),
    'iframe': fence('<iframe src="https://example.com"></iframe>'),
    'video autoplay': fence('<video src=x autoplay onloadstart=alert(1)></video>'),
    'audio': fence('<audio src=x autoplay></audio>'),
    'object': fence('<object data="x.swf"></object>'),
    'embed': fence('<embed src="x.swf">'),
    'style element': fence('<style>body{display:none}</style><p style="color:red">x</p>'),
    'form action': fence('<form action="https://evil.example"><input name=a><button formaction="https://evil.example">go</button></form>'),
    'meta refresh': fence('<meta http-equiv="refresh" content="0;url=https://evil.example">'),
    'base href': fence('<base href="https://evil.example/">'),
    'link stylesheet': fence('<link rel="stylesheet" href="https://evil.example/a.css">'),
    'script': fence('<script>alert(1)</script>'),
    'iframe srcdoc': fence('<iframe srcdoc="<script>alert(1)</script>"></iframe>'),
    'mixed case scheme': fence('<a href="JaVaScRiPt:alert(1)">x</a>'),
    'entity tab scheme': fence('<a href="jav&#x09;ascript:alert(1)">x</a>'),
    'entity newline scheme': fence('<a href="java&#10;script:alert(1)">x</a>'),
    'nested script': fence('<scr<script>ipt>alert(1)</scr</script>ipt>'),
    'noscript mxss': fence('<noscript><p title="</noscript><img src=x onerror=alert(1)>">'),
    'data-markdown': fence('<div data-markdown="x" data-other="y">x</div>'),
    'id clobber': fence('<p id="1bad">a</p><p id="has space">b</p><p id="__proto__x&quot;">c</p>'),
    'ui class': fence('<div class="lee-modal lee-cell keep-out language-x">x</div>'),
    'textarea select': fence('<textarea>x</textarea><select><option>x</option></select>'),
    'math svg': fence('<math><mi xlink:href="javascript:alert(1)">x</mi></math>'),
    'attachment markdown link': '[x](attachment:a.png)',
    'attachment href': fence('<a href="attachment:a.png">x</a>'),
    'attachment upper href': fence('<a href="ATTACHMENT:a.png">x</a>'),
    'attachment entity tab href': fence('<a href="attach&#9;ment:a.png">x</a>'),
    'attachment space href': fence('<a href=" attachment:a.png">x</a>'),
    'attachment image link': '[![a](attachment:a.png)](attachment:a.png)',
}

def render(text, **kw):
    with TestClient(ide_app(Workspace(roots=[]))) as c:
        r = c.post('/markdown/render', json={'text': text, **kw})
    assert r.status_code == 200, r.text
    return r.json()['html']

def walk(nodes):
    for n in nodes:
        if isinstance(n, fast5ever.Element):
            yield n
            yield from walk(n.children)

def violations(html):
    "Every way the parsed `html` breaks the policy; empty when it is clean."
    out = []
    for e in walk(fast5ever.parse_fragment(html).children):
        if e.name not in TAGS: out.append(f'element <{e.name}>')
        for k, v in dict(e.attrs).items():
            v = str(v or '')
            if k.startswith('on') or k in BAD_ATTRS: out.append(f'attribute {k} on <{e.name}>')
            elif k.startswith('data-') and k != 'data-id': out.append(f'attribute {k}')
            elif k == 'class': out += [f'class {t}' for t in v.split() if not (CLASS_OK.match(t) or t in CLASS_NAMES)]
            elif k == 'id' and not ID_OK.match(v): out.append(f'id {v!r}')
            elif k in ('href', 'src'):
                u = re.sub(r'[\x00-\x20]+', '', v).lower()
                if re.match(r'^[a-z][a-z0-9+.-]*:', u):
                    ok = u.startswith(('http:', 'https:', 'mailto:')) or (e.name == 'img' and k == 'src' and (DATA_IMG.match(u) or u.startswith('attachment:')))
                    if not ok: out.append(f'{k} scheme {v!r}')
    return out

@pytest.mark.parametrize('name', ATTACKS)
@pytest.mark.parametrize('kw', [{'allow_raw': True}, {}], ids=['allow_raw', 'default'])
def test_no_attack_survives_the_render(name, kw):
    html = render(ATTACKS[name], **kw)
    assert not violations(html), (name, violations(html), html)

def test_obfuscated_schemes_are_dropped_not_decoded_into_links():
    html = render(ATTACKS['entity tab scheme'] + '\n\n' + ATTACKS['mixed case scheme'], allow_raw=True)
    assert not [e for e in walk(fast5ever.parse_fragment(html).children) if e.name == 'a' and 'href' in dict(e.attrs)], html

def _srcs(html): return [str(dict(e.attrs).get('src')) for e in walk(fast5ever.parse_fragment(html).children) if e.name == 'img']

@pytest.mark.parametrize('kw', [{'allow_raw': True}, {}], ids=['allow_raw', 'default'])
def test_a_notebook_attachment_keeps_its_image_src(kw):
    "nh3 dropped `attachment:`, so the client never saw the name it resolves from the cell's attachments."
    assert _srcs(render('![a](attachment:a.png)\n\ntext ![b](attachment:b.png)', **kw)) == ['attachment:a.png', 'attachment:b.png']

def test_a_raw_attachment_img_keeps_its_src_and_stored_text_drops_it():
    from leela.core.text import md_html
    assert _srcs(render(fence('<img src="attachment:a.png">'), allow_raw=True)) == ['attachment:a.png']
    assert 'attachment:' not in md_html('![a](attachment:a.png)'), 'stored text has no attachments to resolve'

def test_a_ui_class_is_dropped_and_a_code_class_kept():
    html = render(ATTACKS['ui class'], allow_raw=True)
    (div,) = [e for e in walk(fast5ever.parse_fragment(html).children) if e.name == 'div']
    assert str(dict(div.attrs).get('class') or '').split() == ['language-x']

DOC = '''# Title

<!-- a note to the reader -->

| left | centre | right |
|:-----|:------:|------:|
| a | b | c |

```{=html}
<details open><summary>More</summary><p>inside</p></details>
```

- [ ] open
- [x] done

A footnote[^1] with [web](http://example.com), [secure](https://example.com/a?b=1), [mail](mailto:a@example.com), [rel](docs/a.md) and [anchor](#title).

![remote](https://example.com/p.png) ![inline](data:image/png;base64,iVBORw0KGgo=)

```python
def f(x): return x + 1
```

```rupaka
{"schema": 1, "id": "x", "note": "a < b && c > d"}
```

[^1]: The note.
'''

def text_of(n):
    return ''.join(c.text if isinstance(c, fast5ever.Text) else text_of(c) for c in getattr(n, 'children', ()) if not isinstance(c, fast5ever.Comment)) if not isinstance(n, fast5ever.Text) else n.text

def shape(nodes):
    "Parsed nodes as plain tuples; the `rel` the sanitizer adds to links is the one difference ignored."
    out = []
    for n in nodes:
        if isinstance(n, fast5ever.Element):
            at = {k: str(v) for k, v in dict(n.attrs).items() if k != 'rel'}
            out.append((n.name, sorted(at.items()), shape(n.children)))
        elif isinstance(n, fast5ever.Comment): out.append(('#comment', n.content if hasattr(n, 'content') else str(n)))
        else: out.append(('#text', n.text))
    return out

@pytest.mark.parametrize('hl', [None, 'spans'])
def test_ordinary_markdown_renders_node_for_node_as_mdhtml_does(monkeypatch, hl):
    import leela.app
    from mdhtml import md2mdhtml, mdhtml2html
    monkeypatch.setattr(leela.app, 'MD_HIGHLIGHT', hl)
    sym = md2mdhtml(DOC, math='dollars', implicit_figures=True, bare_autolinks=True, frontmatter=False)
    want = str(mdhtml2html(sym, refs='ids', auto_ids=False, hl=hl))
    got = render(DOC, allow_raw=True)
    assert shape(fast5ever.parse_fragment(got).children) == shape(fast5ever.parse_fragment(want).children)
    kinds = {n[0] for n in shape(fast5ever.parse_fragment(got).children)}
    assert {'#comment', 'table', 'details', 'ul', 'pre', 'section'} <= kinds
    rk = [e for e in walk(fast5ever.parse_fragment(got).children) if 'language-rupaka' in str(dict(e.attrs).get('class') or '')]
    assert [text_of(e) for e in rk] == [text_of(e) for e in walk(fast5ever.parse_fragment(want).children) if 'language-rupaka' in str(dict(e.attrs).get('class') or '')]
    assert rk and '"note": "a < b && c > d"' in text_of(rk[0])

@pytest.mark.slow
def test_the_browser_runs_no_handler_and_follows_no_script_link_from_a_markdown_cell():
    pytest.importorskip('playwright.async_api')
    from test_web_slow import _run
    text = '<img src=x onerror="window.pwned=1">\n\n[x](javascript:window.pwned=2)\n\n```{=html}\n<img src=y onerror="window.pwned=3">\n```'
    async def go(pg):
        await pg.evaluate("""(t) => { const d = document.createElement('div'); d.id = 'md-attack'; document.body.appendChild(d);
          window.__done = new Promise(r => d.addEventListener('lee-markdown-rendered', r, {once: true})); renderMarkdown(d, t, true); }""", text)
        await pg.evaluate('() => window.__done')
        a = pg.locator('#md-attack a')
        if await a.count(): await a.first.click(no_wait_after=True)
        await pg.wait_for_timeout(300)
        return await pg.evaluate("() => ({pwned: window.pwned, onerror: document.querySelectorAll('#md-attack [onerror]').length, imgs: document.querySelectorAll('#md-attack img').length, hrefs: [...document.querySelectorAll('#md-attack a')].map(a => a.getAttribute('href'))})")
    got = _run(go)
    assert got['pwned'] is None and got['onerror'] == 0, got
    assert not [h for h in got['hrefs'] if (h or '').lower().startswith('javascript')], got
