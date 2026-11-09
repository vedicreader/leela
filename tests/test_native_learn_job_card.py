from types import SimpleNamespace

from fasthtml.common import Span, to_xml
from leela.blocks.vault import ui
from leela.blocks.vault.ui import job_card
from leela.blocks.learn.walk import walk_job_actions


def _card(**d):
    base = dict(id='learn-job', kind='learn_walk', active=False, status='complete', target='fractions', error='', params={}, cancellable=False, result={})
    return str(to_xml(job_card(SimpleNamespace(dict=lambda: base | d))))


def test_a_kind_with_no_registered_actions_draws_as_before(monkeypatch):
    monkeypatch.setattr(ui, 'JOB_ACTIONS', {})
    plain = _card(kind='other', result=dict(status='ok'))
    monkeypatch.setattr(ui, 'JOB_ACTIONS', {'learn_walk': lambda job, result: [Span('extra')]})
    assert _card(kind='other', result=dict(status='ok')) == plain and 'extra' not in plain
    assert 'extra' in _card()
    assert 'extra' not in _card(active=True, status='running', progress=.5, current='')


def test_learn_job_card_retains_open_action_and_failure_reason(monkeypatch):
    from abhyasa.agent_tools import failed, result
    monkeypatch.setattr(ui, 'JOB_ACTIONS', {'learn_walk': walk_job_actions})
    ok = result('ok', vault='learning', walk='fractions', data=dict(tab=dict(kind='learn', vault='learning', walk='fractions', path='/w/fractions/0')))
    card = _card(result=ok)
    assert 'Open walk' in card and '/learn/tab/open' in card and '/learn/walk' not in card
    assert 'name="path"' in card and 'value="/w/fractions/0"' in card and 'value="learning"' in card
    for error in ('model_refused', 'stopped'):
        card = _card(result=failed(error, 'No model answer.'))
        assert 'Open walk' not in card
        assert error in card and 'No model answer.' in card


def test_the_learn_block_registers_its_card_actions(ws):
    from leela.app import ide_app
    ide_app(ws)
    assert ui.JOB_ACTIONS['learn_walk'] is walk_job_actions
