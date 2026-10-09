"The vault block: what goes in, how it is browsed, and how a document reaches a turn."

from __future__ import annotations

from fasthtml.common import to_xml

from leela.blocks.memory.memory import Memory
from leela.blocks.vault.acquire import plan_tree
from leela.blocks.vault.jobs import every_seconds
from leela.blocks.vault.news import Feed, Feeds, feed_title, parse_feed
from leela.blocks.vault import ui
from leela.workspace import Workspace

RSS = '''<?xml version="1.0"?><rss version="2.0"><channel>
  <title>A blog</title>
  <item><title>First post</title><link>https://x.test/1</link>
        <pubDate>Tue, 05 Aug 2025 10:00:00 GMT</pubDate>
        <description>&lt;p&gt;Something&lt;/p&gt;&lt;p&gt;else&lt;/p&gt;</description></item>
  <item><title>Second</title><link>https://x.test/2</link></item>
</channel></rss>'''

ATOM = '''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
  <title>A journal</title>
  <entry><title>An entry</title><link rel="alternate" href="https://y.test/a"/>
         <updated>2025-08-05T10:00:00Z</updated><summary>Body text</summary></entry>
</feed>'''

# ── what a thing is, and where a folder of things would land ────────────────


def test_generated_paths_are_left_out_and_counted(tmp_path):
    (tmp_path/'docs').mkdir()
    (tmp_path/'docs'/'real.md').write_text('# a\n')
    for junk in ('node_modules', '__pycache__', '.venv'):
        (tmp_path/junk).mkdir()
        (tmp_path/junk/'x.md').write_text('# junk\n')
    plan = plan_tree(tmp_path)
    assert [x.relative for x in plan.files] == ['docs/real.md']
    assert len(plan.skipped) == 3


# ── cadence ─────────────────────────────────────────────────────────────────


def test_an_unreadable_cadence_is_the_default_rather_than_a_busy_loop():
    for junk in ('', None, 'soon', '1 fortnight', '-4h', '3x', '1h30m'):
        assert every_seconds(junk) == 3600
    assert every_seconds('0s') == 60, 'zero would poll continuously'


# ── feeds ───────────────────────────────────────────────────────────────────

def test_rss_and_atom_both_parse_to_the_same_shape():
    rss, atom = parse_feed(RSS), parse_feed(ATOM)
    assert [x.title for x in rss] == ['First post', 'Second']
    assert rss[0].link == 'https://x.test/1' and rss[0].published.startswith('2025-08-05')
    assert atom[0].title == 'An entry' and atom[0].link == 'https://y.test/a'
    assert feed_title(RSS) == 'A blog' and feed_title(ATOM) == 'A journal'


def test_a_feed_registry_round_trips_through_its_file(tmp_path):
    f = Feeds(tmp_path/'feeds.json')
    f.rows.append(Feed(url='https://x.test/feed', title='A blog', every='6h'))
    f.save()
    again = Feeds(tmp_path/'feeds.json')
    assert [r.url for r in again] == ['https://x.test/feed']
    assert again.rows[0].seconds == 21600 and again.rows[0].due
    again.mark(again.rows[0].id, 'ok', 3)
    assert not Feeds(tmp_path/'feeds.json').rows[0].due, 'a feed just read is not due again'


# ── the workbench ───────────────────────────────────────────────────────────


def test_every_view_renders_over_an_empty_vault(tmp_path):
    "A vault nobody has filled yet is the first thing anyone sees, so no view may need rows."
    m = Memory(shelf='main', path=tmp_path/'v.db', offline=True)
    for view in (ui.browse_view, ui.find_view, ui.topics_view):
        assert to_xml(view(m, 'workspace'))
    assert to_xml(ui.add_view(m, 'workspace', jobs=None, root=str(tmp_path)))
    assert to_xml(ui.news_view(m, 'workspace', feeds=Feeds(tmp_path/'f.json')))
    assert to_xml(ui.specs_view(m, 'workspace'))


# ── attaching a document to a turn ──────────────────────────────────────────

def test_a_vault_document_reaches_the_turn_as_grounded_text(tmp_path, monkeypatch):
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'vault.db'))
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    (src := tmp_path/'auth.md').write_text('# Auth spec\n\nTokens expire after 30 minutes.\n\n'
                                           '## Refresh\n\nA refresh token lasts 30 days.\n')
    ws = Workspace(roots=[str(tmp_path)])
    ws.memory.clip([str(src)], shelf='specs')
    doc = ws.memory.all_documents(shelves=['specs'])[0]
    ref = {'kind': 'vault', 'vault': '', 'shelf': 'specs', 'doc': doc['doc_id'], 'title': 'auth'}
    text, images = ws._attachment_context([ref])
    assert text.startswith('<attached-document') and text.endswith('</attached-document>')
    assert 'shelf="specs"' in text and 'Tokens expire after 30 minutes' in text
    assert images == []

def test_attaching_a_section_reads_that_section_rather_than_the_whole_document(tmp_path, monkeypatch):
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'vault.db'))
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    (src := tmp_path/'auth.md').write_text('# Auth spec\n\nTokens expire after 30 minutes.\n\n'
                                           '## Refresh\n\nA refresh token lasts 30 days.\n')
    ws = Workspace(roots=[str(tmp_path)])
    ws.memory.clip([str(src)], shelf='specs')
    doc = ws.memory.all_documents(shelves=['specs'])[0]
    node = next(s['node_id'] for s in ws.memory.sections(doc['doc_id'], 'specs')
                if 'refresh' in s['title'].lower())
    text, _ = ws._attachment_context([{'kind': 'vault', 'vault': '', 'shelf': 'specs',
                                       'doc': node, 'title': 'Refresh'}])
    assert 'lasts 30 days' in text
    assert 'expire after 30 minutes' not in text, 'the whole document came back, not the section'


def test_the_workbench_reopens_on_the_section_you_left_it_on(tmp_path, monkeypatch):
    """Reading a story opens a document tab."""
    from starlette.testclient import TestClient
    from leela.app import ide_app
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'vault.db'))
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    ws = Workspace(roots=[str(tmp_path)]); ws._state_path = tmp_path/'workspace.json'
    ws.open_vault_workbench()
    with TestClient(ide_app(ws)) as c:
        assert c.get('/vault/view/news').status_code == 200
        assert ws.tab.ref == 'news', 'the swap moved the tab, not just the page'
        assert c.get('/vault/workbench?view=specs').status_code == 200
        assert ws.tab.ref == 'specs', 'however the section was asked for'
