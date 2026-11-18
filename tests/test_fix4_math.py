from fastcore.basics import AttrDict
from fasthtml.common import to_xml
from leela.blocks.learn.ui import StepPage


def test_learn_passage_renders_stored_latex():
    v = AttrDict(kind='step', i=0, name='First law', nb=None,
        j=AttrDict(id='w', title='Thermodynamics', steps=[{}]),
        step=dict(read=dict(src='web', text=r'Internal energy ((\Delta U)) changes.', title='First law', url='https://example.org/t')))
    q = AttrDict(walk='w', v='', topic='', cell=None)
    h = to_xml(StepPage(v, q))
    assert 'class="math' in h and '((' not in h
