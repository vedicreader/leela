import json
from pathlib import Path
import pytest
import abhyasa.settings, abhyasa.tutor
from abhyasa.prompts import PROMPTS, set_prompt
from leela.blocks.nb.lesson import CHARTER_TAIL, lesson_charter

DFLT = PROMPTS['tutor'].dflt

def save(cfg, text):
    cfg.mkdir(parents=True, exist_ok=True)
    (p := cfg/'settings.json').write_text(text)
    return p

def test_charter_reads_the_saved_tutor_prompt(abhyasa_cfg):
    assert lesson_charter() == DFLT + CHARTER_TAIL
    set_prompt('tutor', 'Ask one question at a time. Never give the answer.')
    assert lesson_charter() == 'Ask one question at a time. Never give the answer.' + CHARTER_TAIL
    set_prompt('tutor', '')
    assert lesson_charter() == DFLT + CHARTER_TAIL
    assert CHARTER_TAIL.startswith('\nHint ladder:\n') and 'add_exercise' in CHARTER_TAIL

@pytest.mark.parametrize('text', ['', ' \n\t ', None, 3, ['Ask.']])
def test_a_blank_or_non_text_saved_prompt_gives_the_default(abhyasa_cfg, text):
    save(abhyasa_cfg, json.dumps(dict(prompts=dict(tutor=text))))
    assert lesson_charter() == DFLT + CHARTER_TAIL

def test_malformed_settings_give_the_default(abhyasa_cfg):
    save(abhyasa_cfg, '{"prompts": {"tutor": "Saved text."')
    assert lesson_charter() == DFLT + CHARTER_TAIL

@pytest.mark.parametrize('meth', ['stat', 'read_text'])
def test_unreadable_settings_give_the_default(abhyasa_cfg, monkeypatch, meth):
    p = save(abhyasa_cfg, json.dumps(dict(prompts=dict(tutor='Saved text.'))))
    assert lesson_charter() == 'Saved text.' + CHARTER_TAIL
    real = getattr(Path, meth)
    def deny(self, *a, **kw):
        if self == p: raise PermissionError(13, 'Permission denied', str(self))
        return real(self, *a, **kw)
    monkeypatch.setattr(abhyasa.settings, '_cache', {})
    monkeypatch.setattr(Path, meth, deny)
    assert lesson_charter() == DFLT + CHARTER_TAIL
