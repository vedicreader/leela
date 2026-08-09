"""Research keeps Fossick's rich results and writes useful, confined documents."""

from types import SimpleNamespace

from leela.fs import Sandbox
from leela.research import Research, _url_slug


def test_arxiv_reader_uses_fossick_source_and_title(monkeypatch, tmp_path):
    fake = SimpleNamespace(read_arxiv=lambda *a, **k: {
        'title': 'A Better Runtime Boundary',
        'summary': 'Short abstract',
        'source': '# Introduction\n\nThe complete paper source.',
    })
    research = Research(Sandbox([tmp_path]))
    monkeypatch.setattr(research, '_fossick', lambda: fake)
    doc = research.read('https://arxiv.org/abs/2601.01234')
    assert doc.title == 'A Better Runtime Boundary'
    assert 'complete paper source' in doc.text
    assert doc.kind == 'paper'


def test_repeated_articles_remain_separate_documents(monkeypatch, tmp_path):
    class Match:
        def __init__(self, items): self.items = items
        @property
        def first(self): return self.items[0] if self.items else None
        def __iter__(self): return iter(self.items)
    class Heading:
        def __init__(self, text): self.text = text
        def get_all_text(self): return self.text
    class Article:
        def __init__(self, title, html): self.title, self.html = title, html
        def css(self, query): return Match([Heading(self.title)])
        def get(self): return self.html
    class Page:
        def __init__(self): self.articles = [Article('First story', '<p>first body</p>'), Article('Second story', '<p>second body</p>')]
        def css(self, query): return Match(self.articles if query == 'article' else [])
    page = Page()
    fake = SimpleNamespace(
        fetch=lambda *a, **k: page,
        to_md=lambda value, **kw: {'<p>first body</p>': 'first body ' * 20,
                                   '<p>second body</p>': 'second body ' * 20}.get(value, 'combined page text ' * 30),
    )
    research = Research(Sandbox([tmp_path]))
    monkeypatch.setattr(research, '_fossick', lambda: fake)
    doc = research.read('https://example.com/daily')
    assert [section['title'] for section in doc.sections] == ['First story', 'Second story']
    assert 'first body' in doc.sections[0]['text'] and 'second body' in doc.sections[1]['text']


def test_page_reader_keeps_all_semantic_blocks_not_only_the_first(monkeypatch, tmp_path):
    calls = []
    page = object()
    def to_md(got, sel=None, multi=False):
        assert got is page
        calls.append((sel, multi))
        if sel == 'article': return '# Complete article\n\n' + ('whole paragraph\n\n' * 120)
        if sel is None: return 'lead paragraph only'
        return ''
    fake = SimpleNamespace(fetch=lambda *a, **k: page, to_md=to_md)
    research = Research(Sandbox([tmp_path]))
    monkeypatch.setattr(research, '_fossick', lambda: fake)
    doc = research.read('https://example.com/story')
    assert len(doc.text) > 1000 and 'Complete article' in doc.text
    assert ('article', True) in calls
    assert 'via article' in research.note


def test_thin_static_pages_retry_with_rendering_and_independent_extract(monkeypatch, tmp_path):
    static, rendered = object(), object()
    fetches = []
    def fetch(url, **kw):
        fetches.append(kw)
        return rendered if kw.get('heavy') else static
    def to_md(page, sel=None, multi=False):
        return ('rendered article ' * 100) if page is rendered and sel == 'main' else 'lead'
    fake = SimpleNamespace(fetch=fetch, to_md=to_md, extract=lambda url: [])
    research = Research(Sandbox([tmp_path]))
    monkeypatch.setattr(research, '_fossick', lambda: fake)
    doc = research.read('https://example.com/app')
    assert len(doc.text) > 1000
    assert any(call.get('heavy') and call.get('network_idle') for call in fetches)
    assert 'rendered main' in research.note


def test_research_fetches_complete_sources_in_parallel(monkeypatch, tmp_path):
    hits = [
        {'title': 'First', 'href': 'https://one.example/article'},
        {'title': 'Second', 'href': 'https://two.example/article'},
    ]
    pages = {url: object() for url in [h['href'] for h in hits]}
    fake = SimpleNamespace(
        search=lambda *a, **k: hits,
        fetch_all=lambda urls, **kw: [pages[u] for u in urls],
        to_md=lambda page, sel=None, multi=False: ('full source text ' * 200) if sel == 'article' else 'lead',
    )
    research = Research(Sandbox([tmp_path]))
    monkeypatch.setattr(research, '_fossick', lambda: fake)
    docs, digest = research.dig('complete sources', n=2)
    assert len(docs) == 2 and all(len(doc.text) > 2000 for doc in docs)
    assert 'First' in digest and 'Second' in digest
    assert 'complete sources' in research.note


def test_url_notebooks_get_distinct_meaningful_default_names(monkeypatch, tmp_path):
    written = []
    def url2nb(url, nb_path):
        written.append((url, nb_path))
        open(nb_path, 'w').write('{}')
        return nb_path
    research = Research(Sandbox([tmp_path]))
    monkeypatch.setattr(research, '_fossick', lambda: SimpleNamespace(url2nb=url2nb))
    first = research.save_notebook('https://docs.python.org/3/library/asyncio.html')
    second = research.save_notebook('https://arxiv.org/abs/2601.01234')
    assert first.name != second.name
    assert first.name == 'docs-python-org-3-library-asyncio-html.ipynb'
    assert second.name == 'arxiv-org-abs-2601-01234.ipynb'
    assert all(str(tmp_path) in path for _, path in written)


def test_url_slug_has_a_safe_fallback():
    assert _url_slug('') == 'page'
    assert _url_slug('https://www.example.com/a useful/page') == 'example-com-a-useful-page'
