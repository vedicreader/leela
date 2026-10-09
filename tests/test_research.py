"Research keeps Fossick's rich results and writes useful, confined documents."

from types import SimpleNamespace

from leela.blocks.fs.fs import Sandbox
from leela.blocks.research.research import Research, _url_slug


def test_url_slug_has_a_safe_fallback():
    assert _url_slug('') == 'page'
    assert _url_slug('https://www.example.com/a useful/page') == 'example-com-a-useful-page'


def test_a_reader_that_gives_up_falls_through_to_the_page_rather_than_returning_nothing(monkeypatch, tmp_path):
    "Leela used to return None here: an arxiv reader that raised ended the read."
    body = 'the abstract page as html ' * 50
    fake = SimpleNamespace(
        read_arxiv=lambda *a, **k: (_ for _ in ()).throw(RuntimeError('pdf server is down')),
        fetch=lambda url, **kw: SimpleNamespace(html_content=''),
        to_md=lambda page, sel=None, multi=False: body if sel is None else '')
    research = Research(Sandbox([tmp_path]))
    monkeypatch.setattr(research, '_fossick', lambda: fake)
    doc = research.read('https://arxiv.org/abs/2601.09999')
    assert doc is not None and 'abstract page' in doc.text and doc.kind == 'page'
