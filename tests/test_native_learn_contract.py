import logging, sys, types
import abhyasa.learner
from types import SimpleNamespace

from leela.app import ide_app
from leela.blocks.learn.tools import contract_missing, learn_tools


def test_an_abhyasa_without_the_contract_keeps_learn_off_and_leela_starting(ws, monkeypatch, caplog):
    assert contract_missing() == []
    old = types.ModuleType('abhyasa.learner')
    old.__dict__.update({k: v for k, v in vars(abhyasa.learner).items() if k not in ('use_settings', '__name__')})
    monkeypatch.setitem(sys.modules, 'abhyasa.learner', old)
    assert contract_missing() == ['abhyasa.learner.use_settings']
    assert learn_tools(SimpleNamespace(ws=ws, learn_mode=True)) == []
    with caplog.at_level(logging.WARNING): assert ide_app(ws)
    said = [r for r in caplog.records if r.name == 'leela.blocks.learn.app' and r.levelno == logging.WARNING]
    assert len(said) == 1 and 'abhyasa.learner.use_settings' in said[0].getMessage()