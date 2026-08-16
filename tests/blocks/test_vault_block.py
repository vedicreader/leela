"The vault block: what goes in, how it is browsed, and how a document reaches a turn."

from __future__ import annotations

import json

import pytest
from fasthtml.common import to_xml

from leela.blocks.memory.memory import Memory
from leela.blocks.vault.acquire import ACTIONS, category_for, detect, plan_tree
from leela.blocks.vault.jobs import cadence, every_seconds
from leela.blocks.vault.news import Feed, Feeds, feed_title, item_markdown, parse_feed
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

@pytest.mark.parametrize('target,want', [
    ('https://example.com/a', 'grab'),
    ('2401.12345', 'arxiv'),
    ('https://arxiv.org/abs/2401.12345', 'arxiv'),
    ('https://github.com/owner/repo', 'github'),
    ('https://youtu.be/abc', 'youtube'),
    ('https://www.youtube.com/watch?v=abc', 'youtube'),
    ('just some words', 'note'),
    ('', 'note')])
def test_a_pasted_string_picks_its_own_reader(target, want):
    assert detect(target) == want

def test_a_path_that_exists_is_clipped_rather_than_fetched(tmp_path):
    p = tmp_path/'notes.md'
    p.write_text('# hi\n')
    assert detect(str(p)) == 'clip'
    assert detect(str(tmp_path/'nothing-here.md')) == 'note'

def test_every_offered_action_is_one_the_vault_can_actually_run():
    from leela.blocks.memory.memory import ACQUIRE
    assert {a for a, _ in ACTIONS} <= set(ACQUIRE)

def test_a_folder_becomes_one_shelf_per_top_folder(tmp_path):
    for rel in ('specs/auth.md', 'specs/billing.md', 'notes/kickoff.md', 'readme.md'):
        p = tmp_path/rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('# t\n\nbody\n')
    plan = plan_tree(tmp_path)
    assert plan.shelves == {'specs': 2, 'notes': 1, tmp_path.name.lower().replace('-', '_'): 1} or \
           set(plan.shelves) >= {'specs', 'notes'}
    assert plan.shelves['specs'] == 2
    assert {x.category for x in plan.files if x.shelf == 'specs'} == {'spec'}

def test_generated_paths_are_left_out_and_counted(tmp_path):
    (tmp_path/'docs').mkdir()
    (tmp_path/'docs'/'real.md').write_text('# a\n')
    for junk in ('node_modules', '__pycache__', '.venv'):
        (tmp_path/junk).mkdir()
        (tmp_path/junk/'x.md').write_text('# junk\n')
    plan = plan_tree(tmp_path)
    assert [x.relative for x in plan.files] == ['docs/real.md']
    assert len(plan.skipped) == 3

def test_a_plan_over_an_empty_folder_is_empty_rather_than_an_error(tmp_path):
    assert plan_tree(tmp_path).files == []

def test_a_file_is_categorised_from_its_path_not_its_contents():
    assert category_for('handbook/specs/auth.md') == 'spec'
    assert category_for('a/meeting notes/kickoff.md') == 'notes'
    assert category_for('a/b/c.md') == 'other'

# ── cadence ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('spec,secs', [('30m', 1800), ('6h', 21600), ('1d', 86400), ('2w', 1209600),
                                       ('3', 10800), ('90s', 90)])
def test_a_cadence_is_read_as_written(spec, secs):
    assert every_seconds(spec) == secs

def test_an_unreadable_cadence_is_the_default_rather_than_a_busy_loop():
    for junk in ('', None, 'soon', '1 fortnight', '-4h'):
        assert every_seconds(junk) == 3600
    assert every_seconds('0s') == 60, 'zero would poll continuously'

def test_a_cadence_says_itself_at_the_coarsest_unit_that_divides_it():
    assert cadence(86400) == 'every 1 day' and cadence(172800) == 'every 2 days'
    assert cadence(3600) == 'every 1 hour' and cadence(90) == 'every 90 seconds'

# ── feeds ───────────────────────────────────────────────────────────────────

def test_rss_and_atom_both_parse_to_the_same_shape():
    rss, atom = parse_feed(RSS), parse_feed(ATOM)
    assert [x.title for x in rss] == ['First post', 'Second']
    assert rss[0].link == 'https://x.test/1' and rss[0].published.startswith('2025-08-05')
    assert atom[0].title == 'An entry' and atom[0].link == 'https://y.test/a'
    assert feed_title(RSS) == 'A blog' and feed_title(ATOM) == 'A journal'

def test_a_block_boundary_is_a_space_and_a_tag_boundary_is_not():
    "`</p><p>` separates two sentences; `<b>x</b>.` must not become `x .`"
    assert parse_feed(RSS)[0].summary == 'Something else'

def test_an_item_with_no_link_is_not_an_item():
    assert parse_feed('<rss><channel><item><title>t</title></item></channel></rss>') == []

def test_junk_parses_to_nothing_rather_than_raising():
    assert parse_feed('not xml at all') == [] and feed_title('not xml') == ''

def test_an_item_becomes_a_document_that_says_where_it_came_from():
    md = item_markdown(parse_feed(RSS)[0], 'A blog')
    assert md.startswith('# First post') and 'A blog' in md and 'https://x.test/1' in md

def test_a_feed_registry_round_trips_through_its_file(tmp_path):
    f = Feeds(tmp_path/'feeds.json')
    f.rows.append(Feed(url='https://x.test/feed', title='A blog', every='6h'))
    f.save()
    again = Feeds(tmp_path/'feeds.json')
    assert [r.url for r in again] == ['https://x.test/feed']
    assert again.rows[0].seconds == 21600 and again.rows[0].due
    again.mark(again.rows[0].id, 'ok', 3)
    assert not Feeds(tmp_path/'feeds.json').rows[0].due, 'a feed just read is not due again'

def test_a_corrupt_feed_file_is_an_empty_registry_with_a_note(tmp_path):
    (p := tmp_path/'feeds.json').write_text('{not json')
    f = Feeds(p)
    assert list(f) == [] and 'could not read' in f.note

def test_a_feed_row_missing_its_url_is_dropped_rather_than_taking_the_file_with_it(tmp_path):
    (p := tmp_path/'feeds.json').write_text(json.dumps({'feeds': [{'title': 'no url'},
                                                                  {'url': 'https://ok.test'}]}))
    assert [r.url for r in Feeds(p)] == ['https://ok.test']

# ── the workbench ───────────────────────────────────────────────────────────

@pytest.fixture
def filled(tmp_path):
    "A vault with three documents on two shelves, and the `Memory` over it."
    for rel, body in (('specs/auth.md', '# Auth spec\n\nTokens expire after 30 minutes.\n\n'
                                        '## Refresh\n\nA refresh token lasts 30 days.\n'),
                      ('notes/kickoff.md', '# Kickoff\n\nWe agreed to ship the workbench.\n'),
                      ('readme.md', '# Handbook\n\nEverything written down.\n')):
        p = tmp_path/'src'/rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    m = Memory(shelf='main', path=tmp_path/'vault.db', offline=True)
    for shelf, rel in (('specs', 'specs/auth.md'), ('notes', 'notes/kickoff.md'), ('main', 'readme.md')):
        m.clip([str(tmp_path/'src'/rel)], shelf=shelf)
    return m

class _Vaults:
    "Enough of `Vaults` for the chrome, without a registry file."
    def dict(self): return {'active': 'workspace', 'vaults': [{'name': 'workspace', 'path': 'v.db',
                                                               'access': 'admin', 'agent': True,
                                                               'agent_writable': True, 'reserved': True,
                                                               'active': True}]}

def test_the_workbench_names_every_view_and_counts_what_is_in_the_vault(filled):
    html = to_xml(ui.workbench(filled, _Vaults()))
    for name, _ in ui.VIEWS: assert f'>{name}<' in html, f'{name} is not a tab'
    assert 'documents' in html and 'sections' in html and 'shelves' in html
    assert 'id="vaultwbbody"' in html

def test_browse_lists_the_shelves_and_the_documents_on_the_one_chosen(filled):
    every = to_xml(ui.browse_view(filled, 'workspace'))
    assert 'auth' in every and 'kickoff' in every and 'lee-wb-shelf' in every
    one = to_xml(ui.browse_view(filled, 'workspace', shelf='specs'))
    assert 'auth' in one and 'kickoff' not in one

def test_a_search_hit_offers_the_section_it_matched_rather_than_the_whole_document(filled):
    html = to_xml(ui.find_view(filled, 'workspace', q='refresh token'))
    assert 'lee-wb-hit' in html
    assert '<mark>' in html.lower(), 'the words searched for are not marked in the snippet'
    assert 'data-doc' in html and '#' in html, 'a hit attaches its section, not its document'

def test_an_empty_search_explains_itself_instead_of_listing_everything(filled):
    html = to_xml(ui.find_view(filled, 'workspace'))
    assert 'lee-wb-hit' not in html and 'search the whole vault' in html

def test_a_search_that_matches_nothing_says_so(tmp_path):
    "Not through a query: the offline hash encoder ranks everything, so nothing never matches nothing."
    m = Memory(shelf='main', path=tmp_path/'v.db', offline=True)
    html = to_xml(ui.find_view(m, 'workspace', q='zzzzznothingatall'))
    assert 'nothing matched' in html and 'zzzzznothingatall' in html

def test_the_import_plan_is_shown_before_anything_is_indexed(tmp_path):
    (tmp_path/'specs').mkdir()
    (tmp_path/'specs'/'a.md').write_text('# a\n')
    html = to_xml(ui.import_plan(plan_tree(tmp_path)))
    assert 'specs' in html and '1 files' in html
    assert 'hx-post="/clip"' in html and 'clip_tree' in html, 'the plan has to be the thing that runs'

def test_every_view_renders_over_an_empty_vault(tmp_path):
    "A vault nobody has filled yet is the first thing anyone sees, so no view may need rows."
    m = Memory(shelf='main', path=tmp_path/'v.db', offline=True)
    for view in (ui.browse_view, ui.find_view, ui.topics_view):
        assert to_xml(view(m, 'workspace'))
    assert to_xml(ui.add_view(m, 'workspace', jobs=None, root=str(tmp_path)))
    assert to_xml(ui.news_view(m, 'workspace', feeds=Feeds(tmp_path/'f.json')))
    assert to_xml(ui.specs_view(m, 'workspace'))

def test_the_specs_view_says_what_filing_a_specification_buys(filled):
    rows = [{'verb': 'GET', 'path': '/deployments', 'summary': 'list them', 'required': ['id'],
             'group': 'deploy'}]
    html = to_xml(ui.ops_table(rows, src='https://api.test/openapi.json'))
    assert 'GET' in html and '/deployments' in html
    assert 'clip_api_spec' in html, 'a read specification has to be fileable'

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

def test_a_document_with_nothing_readable_refuses_rather_than_attaching_an_empty_block(tmp_path, monkeypatch):
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'vault.db'))
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    ws = Workspace(roots=[str(tmp_path)])
    with pytest.raises(ValueError, match='nothing readable'):
        ws._attachment_context([{'kind': 'vault', 'vault': '', 'shelf': 'specs',
                                 'doc': 'no-such-document', 'title': 'ghost'}])

def test_the_workbench_is_one_tab_however_often_it_is_opened(tmp_path, monkeypatch):
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'vault.db'))
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    ws = Workspace(roots=[str(tmp_path)])
    ws.open_vault_workbench()
    ws.open_vault_workbench('find')
    assert [t.kind for t in ws.tabs] == ['vaultwb']
    assert ws.tab.ref == 'find', 'reopening it should move to the view asked for'
