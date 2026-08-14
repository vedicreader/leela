"""The three browser surfaces over the vault: the clip affordance, tidy review, the PII badge.

Fragments, not a browser: every one of these is server-rendered HTML with htmx attributes, so
rendering it and reading the attributes is the whole contract the client depends on.
"""

from fasthtml.common import to_xml

from leela.blocks.jobs.app import PII_COVERS, _tidy_list, _tidy_row, job_card, pii_badge, vault_panel
from leela.blocks.keys.menus import MENUS
from leela.blocks.memory.memory import Memory
from leela.core.keys import lookup


class _Job:
    "The one shape `job_card` reads, so a card can be rendered without running anything."

    def __init__(self, **kw): self.row = dict(id='j1', kind='clip', status='complete', target='/n.md',
        active=False, progress=1.0, current='', error='') | kw

    def dict(self): return self.row


class _Jobs:
    def all(self, limit=8): return []


def _mem(tmp_path, shelf='proj'): return Memory(shelf=shelf, path=tmp_path/'v.db', offline=True)


# -- the clip affordance ------------------------------------------------------------------

def test_clip_is_reachable_from_a_file_a_folder_and_a_tab():
    "The three places a person names the thing they want clipped, and one declared action."
    for surface in ('file', 'folder', 'tab'):
        assert 'clip_to_vault' in [i.action for i in MENUS[surface]], surface
    assert lookup('clip_to_vault').label == 'clip into the vault'
    assert not lookup('clip_to_vault').bound, 'menu-first: clipping is deliberate, not a chord'


# -- tidy review --------------------------------------------------------------------------

def test_a_tidy_row_offers_both_judgements_and_says_why_it_ranks():
    row = dict(doc_id='d1', title='CHANGELOG', score=2.5, length=-1.4, duplication=3.1)
    html = to_xml(_tidy_row(row, shelf='proj'))
    assert 'CHANGELOG' in html and '2.50' in html
    assert 'duplication +3.1' in html, 'the score carries the features that produced it'
    assert html.count('/vault/noisy') == 2 and 'value="true"' in html and 'value="false"' in html
    assert 'hx-target="closest .lee-tidy-row"' in html, 'a judged row replaces itself, not the list'


def test_the_tidy_list_is_asked_for_rather_than_rendered_with_the_panel(tmp_path):
    "Ranking reads every document, so the panel ships an empty target and a button."
    panel = to_xml(vault_panel(_mem(tmp_path), _Jobs()))
    assert 'hx-get="/vault/tidy/list"' in panel and 'id="vaulttidy"' in panel
    assert 'lee-tidy-row' not in panel, 'nothing is scored until review is pressed'


def test_an_empty_shelf_says_so_instead_of_rendering_no_rows(tmp_path):
    html = to_xml(_tidy_list(_mem(tmp_path)))
    assert 'id="vaulttidy"' in html and 'too small to have an opinion' in html


# -- the PII badge ------------------------------------------------------------------------

def test_the_badge_reports_what_was_found_and_never_that_there_is_none():
    "The wording is the point: coverage is titled names plus patterns, so 'none' would be a lie."
    found = to_xml(pii_badge(dict(doc_id='d1', has_pii=True, kinds={'email': 3, 'person': 1})))
    assert 'email×3' in found and 'person×1' in found and 'lee-pii found' in found
    clear = to_xml(pii_badge(dict(doc_id='d1', has_pii=False, kinds={})))
    assert 'no pattern found' in clear and 'nothing' not in clear.replace(PII_COVERS, '')
    assert PII_COVERS in found and PII_COVERS in clear


def test_a_tidy_row_fetches_its_badge_only_when_the_row_is_seen():
    "A PII scan reads the whole document, so twenty rows must not be twenty scans on open."
    html = to_xml(_tidy_row(dict(doc_id='d 1', title='Minute', score=1.0), shelf='proj'))
    assert 'hx-trigger="revealed"' in html and 'doc=d+1' in html and 'shelf=proj' in html


def test_a_clip_job_wears_its_pii_summary_rather_than_burying_it():
    card = to_xml(job_card(_Job(result=dict(files=['/a.md'], pii=dict(documents=['proj|d1'],
        kinds={'person': 2})))))
    assert 'pii in 1 document · person×2' in card
    clean = to_xml(job_card(_Job(result=dict(files=['/a.md'], pii=dict(documents=[], kinds={})))))
    assert 'no pattern found' in clean
