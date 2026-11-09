"""Every hosted page of the demo seed answers with no error, and none links to the desktop app."""
import re
from urllib.parse import urldefrag, urljoin, urlsplit

import pytest
from starlette.routing import Mount
from starlette.testclient import TestClient

from leela.app import ide_app
from leela.blocks.learn import host
from ramabana.core import ModelSpec
from tests.fakemodel import install
from tools.seed_learn_demo import seed

GRADE = r'{"correct": false, "grade": 2, "feedback": "Look again.", "first_error": "", "misconception": ""}'

LINK = re.compile(r'''(?:href|src|data-url|hx-get)=["']([^"']+)["']''')
SKIP = re.compile(r'^(?:/learn/abh/events|/events|/voice/|/speech/|/settings|/keys/float|/rupaka/|/activity|.*/predict$)')


@pytest.fixture
def crawl(ws, monkeypatch):
    from abhyasa.learner import temp_learning
    lr = temp_learning()
    monkeypatch.setattr(host, 'learn_store', lambda ws, vault=None, write=False: ('test', lr))
    monkeypatch.setattr(host, 'HOSTS', ('testserver',))
    jid = seed(lr, say=lambda *a: None)
    be = install(ws, [], spec=ModelSpec('grade-hosted', 'remote', 'scripted/model', ctx=8000))
    be.supports_deadline = True
    be._oneshot = lambda prompt, sp, max_tokens, deadline=None: GRADE
    ws.ai._be = ws.ai._be_or_none = lambda job='turn': be
    app = ide_app(ws)
    with TestClient(app) as cl:
        assert cl.post('/learn/abh/open').json()['ok']
        yield cl, lr, jid
    for h in app.router.routes:
        if isinstance(h, Mount) and isinstance(h.app, host.Hosted): h.app.stop()


def walk(cl, start, limit=120):
    "Fetch each local page and file that `start` reaches: `{path: (status, text)}`."
    seen, todo = {}, list(start)
    while todo and len(seen) < limit:
        u = todo.pop(0)
        if u in seen or SKIP.match(u): continue
        r = cl.get(u)
        seen[u] = (r.status_code, r.text if 'html' in r.headers.get('content-type', '') else '')
        for m in LINK.findall(seen[u][1]):
            m = urldefrag(urljoin(u, m))[0]
            p = urlsplit(m)
            if p.scheme or p.netloc or not m.startswith('/') or m in seen or m in todo: continue
            todo.append(m)
    return seen


def test_demo_seed_pages_have_no_error_and_no_desktop_link(crawl):
    cl, lr, jid = crawl
    pages = walk(cl, ['/', f'/w/{jid}', *(f'/w/{jid}/{i}' for i in range(3)), '/keys', '/keys/panel?path=/', '/library', '/you'])
    bad = {u: s for u, (s, _) in pages.items() if s >= 400}
    assert not bad, bad
    assert len(pages) > 15, sorted(pages)
    assert [u for u, (_, t) in pages.items() if 'abhyasa://' in t] == []


def test_demo_figure_is_a_real_png_and_the_source_text_links_no_picture(crawl):
    cl, lr, jid = crawl
    r = cl.get(f'/w/{jid}/1/img')
    assert r.status_code == 200 and r.content[:8] == b'\x89PNG\r\n\x1a\n' and len(r.content) > 40
    texts = [s['read']['text'] for s in lr.journey(jid).steps]
    assert not any('](images/' in t for t in texts)
    docs = [t for u, (_, t) in walk(cl, ['/library/sources', f'/w/{jid}/1']).items() if u.startswith('/v/store/') and '/img' not in u]
    assert docs and not any('images/fig2' in t and 'src=' in t and '/img?' not in t for t in docs)


def test_keys_panel_of_a_hosted_app_has_no_mac_link(crawl):
    cl, lr, jid = crawl
    r = cl.get('/keys/panel?path=/')
    assert r.status_code == 200 and 'abhyasa://' not in r.text and 'kf-mac' not in r.text


def test_missing_walk_in_a_tab_is_a_short_box_with_a_home_link(crawl):
    cl, lr, jid = crawl
    r = cl.get('/w/nope/0', headers={'HX-Request': 'true'})
    assert r.status_code == 200 and 'This walk is not here.' in r.text and 'Go Home' in r.text and 'canonical' not in r.text and '<html' not in r.text
    assert cl.get('/w/nope/0').status_code == 404


def test_empty_answer_spends_no_try(crawl):
    cl, lr, jid = crawl
    i, st = next((i, s) for i, s in enumerate(lr.journey(jid).steps) if not s.get('done') and s['check'].get('kind') not in ('demo', 'order', 'notebook'))
    lr.update(st['slug'], core='A fact.')
    lr.walk_slug(jid, st['slug'], note_none=True, check={**st['check'], 'q': 'What does softmax give?'})
    assert cl.get(f'/w/{jid}/{i}/check', headers={'HX-Request': 'true'}).status_code == 200
    n = len(lr.attempts())
    for a in ('', '   \n'):
        r = cl.post(f'/w/{jid}/{i}/answer', data={'answer': a}, headers={'HX-Request': 'true'})
        assert r.status_code == 400 and r.text == 'Type an answer first.', (r.status_code, r.text[:200])
    assert len(lr.attempts()) == n
    assert cl.post(f'/w/{jid}/{i}/answer', data={'answer': 'weights'}, headers={'HX-Request': 'true'}).status_code == 200
    assert len(lr.attempts()) == n + 1
