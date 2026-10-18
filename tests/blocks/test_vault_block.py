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


# ── privacy: what of the vault reaches a model ─────────────────────────────

import pytest
from fastcore.all import AttrDict
from leela.blocks.memory.memory import PrivacyBlocked

HOSTED, LOCAL = AttrDict(local=False, name='claude-opus'), AttrDict(local=True, name='gemma-local')
CONTACT = '# Contact\n\nWrite to jane.doe@example.com about the lease.\n'
PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 32

@pytest.fixture
def pws(tmp_path, monkeypatch):
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'vault.db'))
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    (tmp_path/'proj').mkdir()
    return Workspace(roots=[str(tmp_path/'proj')])

def _filed(ws, name, text, level=None):
    "A file in the project, filed in the workspace vault, at `level` when given: `(path, shelf, doc_id)`."
    p = ws.fs.roots[0]/name
    if isinstance(text, str): p.write_text(text); ws.memory.clip([str(p)])
    else: p.write_bytes(text); ws.memory._open().add('a scanned card, no text layer', 'card', source=str(p))
    shelf, doc = ws.memory.by_source(p)
    if level: ws.memory._shelf(shelf).set_level(doc, level)
    return p, shelf, doc

def _vref(shelf, doc): return {'kind': 'vault', 'vault': '', 'shelf': shelf, 'doc': doc, 'title': 'contact'}

def test_a_personal_vault_attachment_is_masked_for_a_hosted_model_and_whole_for_a_local_one(pws):
    "Leak 1: `_vault_context` read `shelf_text` ungated, so `vault_pii` never applied to an @-attachment."
    _, shelf, doc = _filed(pws, 'contact.md', CONTACT)
    hosted, _ = pws._attachment_context([_vref(shelf, doc)], HOSTED)
    assert 'jane.doe@example.com' not in hosted and 'lease' in hosted
    assert 'jane.doe@example.com' in pws._attachment_context([_vref(shelf, doc)], LOCAL)[0]
    assert 'jane.doe@example.com' not in pws._attachment_context([_vref(shelf, doc)])[0], 'no spec is a hosted model'

def test_a_local_only_vault_attachment_is_withheld_from_a_hosted_model_whatever_the_policy(pws):
    _, shelf, doc = _filed(pws, 'contact.md', CONTACT, level='local')
    for policy in ('off', 'redact'):
        pws.vault_pii = policy
        with pytest.raises(PrivacyBlocked) as e: pws._attachment_context([_vref(shelf, doc)], HOSTED)
        assert e.value.kind == 'local_only' and e.value.refs == [doc]
        assert 'claude-opus' in str(e.value) and 'Nothing was sent' in str(e.value)
    assert 'jane.doe' in pws._attachment_context([_vref(shelf, doc)], LOCAL)[0]

def test_refuse_withholds_a_personal_attachment_as_pii_blocked(pws):
    _, shelf, doc = _filed(pws, 'contact.md', CONTACT)
    pws.vault_pii = 'refuse'
    with pytest.raises(PrivacyBlocked) as e: pws._attachment_context([_vref(shelf, doc)], HOSTED)
    assert e.value.kind == 'pii_blocked'

def test_a_file_attached_by_path_takes_its_vault_documents_level(pws):
    "Leak 2: an attachment by path sent raw bytes, so a filed document's level was skipped."
    p, _, _ = _filed(pws, 'contact.md', CONTACT)
    text, _ = pws._attachment_context([str(p)], HOSTED)
    assert '<attached-file' in text and 'jane.doe@example.com' not in text
    img, _, _ = _filed(pws, 'card.png', PNG, level='local')
    with pytest.raises(PrivacyBlocked) as e: pws._attachment_context([str(img)], HOSTED)
    assert e.value.kind == 'local_only'
    assert pws._attachment_context([str(img)], LOCAL)[1], 'a local model still sees the picture'
    (other := pws.fs.roots[0]/'notes.md').write_text('mail me at bob@example.com\n')
    assert 'bob@example.com' in pws._attachment_context([str(other)], HOSTED)[0], 'a file no vault filed goes as it is'

def test_a_personal_picture_cannot_be_masked_so_a_hosted_model_does_not_get_it(pws):
    img, _, _ = _filed(pws, 'card.png', PNG, level='personal')
    with pytest.raises(PrivacyBlocked) as e: pws._attachment_context([str(img)], HOSTED)
    assert e.value.kind == 'pii_blocked'

def test_a_selection_and_the_open_document_are_screened_by_their_path(pws):
    p, _, _ = _filed(pws, 'contact.md', CONTACT, level='local')
    sel = {'kind': 'selection', 'path': str(p), 'from': 1, 'to': 3, 'text': CONTACT}
    with pytest.raises(PrivacyBlocked): pws._attachment_context([sel], HOSTED)
    with pytest.raises(PrivacyBlocked): pws._grounding([], CONTACT, AttrDict(model=HOSTED), str(p))
    assert 'jane.doe' in pws._grounding([], CONTACT, AttrDict(model=LOCAL), str(p))[0]

def test_a_turn_with_a_withheld_attachment_answers_with_its_kind_and_never_starts(pws):
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from ramabana.core import ModelSpec
    from tests.fakemodel import Step, install
    _, shelf, doc = _filed(pws, 'contact.md', CONTACT, level='local')
    be = install(pws, [Step(text='I read it')], token_delay=0,
                 spec=ModelSpec('hosted-scripted', 'remote', 'scripted/model', ctx=8000))
    assert not pws.ai.model.local
    with TestClient(ide_app(pws)) as c:
        r = c.post('/agent/turn', json={'prompt': 'summarise', 'attachments': [_vref(shelf, doc)]})
    assert r.status_code == 400
    assert r.json()['ok'] is False and r.json()['kind'] == 'local_only' and r.json()['refs'] == [doc]
    assert be.steps and be.steps[0].text == 'I read it', 'the model was never asked'

def _host(ws, local=False):
    from leela.blocks.agent.ai import WorkspaceHost
    h = WorkspaceHost(ws)
    h.model_local = lambda: (local, 'gemma-local' if local else 'claude-opus')
    return h

def test_the_read_guard_withholds_masks_or_passes_a_vault_source(pws):
    "The file tools read a vault source on disk with no mark check; shalya's read guard is Leela's now."
    from shalya.core import Refusal, guard_read
    p, _, _ = _filed(pws, 'contact.md', CONTACT)
    h = _host(pws)
    masked = guard_read(h, p, lambda: CONTACT, 'view_file')
    assert isinstance(masked, str) and 'jane.doe' not in masked and 'lease' in masked
    assert guard_read(_host(pws, local=True), p, lambda: CONTACT, 'view_file') is None
    secret, _, _ = _filed(pws, 'secret.md', '# Plan\n\nnothing identifying\n', level='local')
    r = guard_read(h, secret, lambda: 'x', 'view_file')
    assert isinstance(r, Refusal) and r.kind == 'local_only' and 'claude-opus' in r.why
    assert isinstance(guard_read(h, 'secret.md', lambda: 'x', 'view_file'), Refusal), 'a relative path is the project\'s'
    img, _, _ = _filed(pws, 'card.png', PNG, level='personal')
    assert isinstance(guard_read(h, img, lambda: b'', 'view_file', 'image'), Refusal), 'a picture cannot be masked'
    (plain := pws.fs.roots[0]/'plain.md').write_text('bob@example.com')
    assert guard_read(h, plain, lambda: 'bob@example.com', 'view_file') is None

def test_view_file_on_a_local_only_source_sends_the_refusal(pws):
    from shalya.tools import file_tools
    secret, _, _ = _filed(pws, 'secret.md', '# Plan\n\nthe launch date\n', level='local')
    view = next(t for t in file_tools(_host(pws)) if t.__name__ == 'view_file')
    out = view(str(secret))
    assert 'launch date' not in out and 'local_only' in out

def test_a_command_naming_a_local_only_source_is_not_run_for_a_hosted_model(pws):
    secret, _, _ = _filed(pws, 'secret.md', '# Plan\n\nthe launch date\n', level='local')
    with pytest.raises(PrivacyBlocked) as e: _host(pws).run_cmd('cat secret.md')
    assert e.value.kind == 'local_only' and 'not run' in str(e.value)
    with pytest.raises(PrivacyBlocked): _host(pws)._exec_gate(f'open({str(secret)!r}).read()')
    code, out = _host(pws, local=True).run_cmd('cat secret.md')
    assert code == 0 and 'launch date' in out
    assert _host(pws).run_cmd('echo unrelated')[1].strip() == 'unrelated'

def test_vault_privacy_defaults_to_redact_and_a_stored_choice_is_kept(pws):
    assert pws.vault_pii == 'redact'
    pws.restore_settings({}); assert pws.vault_pii == 'redact'
    pws.restore_settings({'vault_pii': 'off'}); assert pws.vault_pii == 'off'
    assert _host(pws)._pii == 'off', 'a stored off is kept for a hosted model'
    pws.restore_settings({'vault_pii': 'bogus'}); assert pws.vault_pii == 'redact'
    assert _host(pws)._pii == 'redact' and _host(pws, local=True)._pii == 'off', 'a local model reads the vault whole'

def test_posting_no_policy_is_refused_rather_than_read_as_a_default(pws):
    from starlette.testclient import TestClient
    from leela.app import ide_app
    with TestClient(ide_app(pws)) as c:
        assert c.post('/agent/vault-pii', json={}).status_code == 400
        assert c.post('/agent/vault-pii', json={'pii': 'off'}).json()['pii'] == 'off'
