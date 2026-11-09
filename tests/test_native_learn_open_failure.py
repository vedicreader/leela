from starlette.testclient import TestClient

from leela.app import ide_app
from leela.blocks.learn import walk

SLOT = '#open-walk-error-job-1'


def _missing(ctx, vault): raise KeyError('Learning vault is not attached.')


def test_a_failed_open_leaves_the_tab_bar_alone_and_says_why_in_the_card(ws, monkeypatch):
    monkeypatch.setattr(walk, 'walk_memory', _missing)
    with TestClient(ide_app(ws)) as c:
        r = c.post('/learn/walk/open', data=dict(vault='gone', walk='w', slot=SLOT), headers={'HX-Request': 'true'})
        assert r.headers['hx-retarget'] == SLOT and r.headers['hx-reswap'] == 'innerHTML'
        assert 'not attached' in r.text and 'tabbar' not in r.text
        bad = c.post('/learn/walk/open', data=dict(vault='gone', walk='w', slot='#tabbar'), headers={'HX-Request': 'true'})
        assert 'hx-retarget' not in bad.headers and bad.headers['hx-reswap'] == 'none'
        monkeypatch.setattr(walk, 'walk_memory', lambda ctx, vault: object())
        monkeypatch.setattr(walk, 'learn_settings', lambda session: {})
        monkeypatch.setattr(walk, 'walk_state_for', lambda memory, jid, settings: walk.walk_failure('not_found', 'No such walk.', jid))
        gone = c.post('/learn/walk/open', data=dict(vault='v', walk='w', slot=SLOT), headers={'HX-Request': 'true'})
        assert gone.headers['hx-retarget'] == SLOT and 'No such walk.' in gone.text and 'tabbar' not in gone.text
    assert not [t for t in ws.tabs if t.kind == 'learn_walk']
