import pytest
from abhyasa.contract import _GOOD, read_handoff
from abhyasa.learner import temp_learning
from abhyasa.models import Fake
from abhyasa.path import nb_spec
from leela.blocks.learn.learn import find_step
from leela.blocks.nb.lesson import step_lesson
from rupaka.spec import gallery


def generated_lesson(monkeypatch, valid=True, reply=None):
    monkeypatch.setattr('rupaka.check.can_check', lambda: False)
    lr = temp_learning()
    lr.put('Projectile range', 'The range depends on the angle.', 'physics', visual=True, ways=['demo', 'code'])
    j = lr.put_journey(dict(id='generated', title='Throw a ball', goal='Predict the range', mode='walk',
                            steps=[dict(slug='projectile-range', check=dict(kind='notebook', way='code', depth=4))]))
    model = Fake({'Return JSON: {"task"': {**_GOOD, 'data': []},
                  'You design one interactive demo': reply if reply is not None else gallery()['throw-angle'] if valid else dict(blocks='not blocks')})
    spec = nb_spec(lr, model, j, 0)
    assert spec is not None
    calls = len(model.calls)
    assert nb_spec(lr, model, lr.journey(j.id), 0) == spec
    assert len(model.calls) == calls
    v = find_step(lr, read_handoff('walk=generated&step=0'))
    nb = step_lesson(v.name, dict(walk=j.id, step=0, slug='projectile-range'), v.nb, demo=v.demo)
    return nb, model, lr, spec


@pytest.mark.parametrize('valid', [True, False])
def test_generated_notebook_demo(monkeypatch, valid):
    nb, model, lr, spec = generated_lesson(monkeypatch, valid)
    if valid:
        assert '```rupaka' in nb[2].source
        assert 'No demo yet' not in nb[2].source
        demo = lr.demo(spec.demo).spec
        assert any(b['type'] == 'gate' for b in demo['blocks'])
        assert len(model.calls) == 2
    else:
        assert nb[2].source == 'No demo yet. Ask the tutor to add one.'
        assert not spec.demo
        assert len(model.calls) == 4


def test_malformed_demo_keeps_notebook(monkeypatch):
    nb, model, lr, spec = generated_lesson(monkeypatch, reply='[1]')
    assert not spec.demo
    assert nb[2].source == 'No demo yet. Ask the tutor to add one.'
    assert len(model.calls) == 2
