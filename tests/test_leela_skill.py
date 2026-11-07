"The `leela` skill: what Leela can do, built from the keymap, menus, panes, settings and toolset."

import re
import pytest
from fastcore.all import Path
from leela.workspace import Workspace
ROOT = Path(__file__).resolve().parents[1]
NAME = re.compile(r"""name:\s*(['"])(.*?)\1""")

@pytest.fixture
def ai(tmp_path): return Workspace(roots=[tmp_path]).ai

def _text(ai): return {t.__name__: t for t in ai.tools}['read_skill'](name='leela')

def test_the_briefing_lists_the_skill_and_read_skill_returns_it_whole(ai):
    from ramabana.agent import CATALOGUE_CHARS
    from leela.blocks.agent.skill import SKILL_DESC
    first = SKILL_DESC.split('. ')[0] + '.'
    assert len(first) <= CATALOGUE_CHARS, 'the catalogue clips the first sentence past this'
    assert f'- `leela`: {first}' in ai.system_prompt()
    t = _text(ai)
    assert t.startswith('<skill name="leela"') and '# What Leela can do' in t and 'truncated' not in t

def test_the_text_fits_under_the_skill_cap(ai):
    "`Skill.text` clips silently at `MAX_SKILL_CHARS`, before the tool spills anything to a file."
    from shalya.skills import MAX_SKILL_CHARS, find
    ai.tools
    assert len(find(ai.skills, 'leela')._text()) <= MAX_SKILL_CHARS

def _palette_names():
    js = (ROOT/'leela'/'blocks'/'keys'/'palette.js').read_text()
    body = js[js.index('function palette()'):js.index('const cmds')]
    return [m[2] for m in NAME.finditer(body)]

def test_every_menu_row_key_palette_command_pane_and_setting_is_named(ai):
    from leela.core import keys as K
    from leela.blocks.keys.menus import BAR, MENUS
    from leela.app import LEFT_PANES
    from leela.blocks.settings.settings import DEFAULT_SETTINGS
    t = _text(ai)
    rows = [r for _, rs in BAR for r in rs] + [r for rs in MENUS.values() for r in rs]
    want = [K.lookup(r.action).label if getattr(r, 'action', None) else getattr(r, 'title', '') for r in rows]
    want += [k.label for k in K.KEYS if k.label] + [l for _, l in K.PRESENT_KEYS] + [p for _, _, p in LEFT_PANES]
    want += [f'**{s}**: ' + ', '.join(d) for s, d in DEFAULT_SETTINGS.items()] + _palette_names()
    assert len(_palette_names()) > 10
    assert not [w for w in want if w and w not in t]

def test_the_palette_names_come_from_the_shipped_bundle():
    "The bundle ships, the module it is built from does not: both must list the same commands."
    from leela.blocks.agent.skill import _palette_extras
    assert _palette_extras() == _palette_names()

def test_every_tool_leela_can_offer_is_named_and_the_hidden_one_is_not(ai):
    from shalya.tools import tool_groups
    from leela.blocks.agent.ai import HIDDEN
    t = _text(ai)
    own = [f.__name__ for ts in (ai._news_toolset, ai._lesson_toolset, ai._session_toolset, ai._video_toolset) for f in ts]
    names = {*tool_groups(), *(f.__name__ for f in ai._plain), *own} - HIDDEN
    assert not [n for n in names if f'`{n}`' not in t]
    assert '`news_follow` (while a feed is followed)' in t and '`user_steering`' not in t

def test_every_slash_command_is_named(ai):
    from leela.blocks.agent.app import PAGE_COMMANDS
    t = _text(ai)
    assert not [n for n in {*ai.commands(), *PAGE_COMMANDS} if f'`/{n}`' not in t]
    media = (ROOT/'leela'/'blocks'/'agent'/'media.js').read_text()
    assert all(f'\\/{n}' in media for n in PAGE_COMMANDS), 'a page command the page no longer runs'

def test_each_guide_section_has_a_feature_row_and_each_action_is_real():
    from leela.core import keys as K
    from leela.blocks.agent.skill import FEATURES
    g = (ROOT/'docs'/'guide.md').read_text()
    heads = re.findall(r'^### (.+)$', g, re.M) + ['Watching something run', 'Opening a project without a command line']
    assert not set(heads) - {f[0] for f in FEATURES}
    assert not [a for _, where, _ in FEATURES for a in where if re.fullmatch(r'[a-z_]+', a) and K.lookup(a) is None]

def test_a_rebound_key_shows_the_users_chord(ai, tmp_path, monkeypatch):
    from leela.core import keys as K
    p = tmp_path/'keys.json'; p.write_text('{"keys": {"open_vault": "mod+alt+shift+9"}}')
    monkeypatch.setenv('LEELA_KEYMAP', str(p))
    K.reload()
    try: assert 'open the vault `mod+alt+shift+9`' in _text(ai)
    finally:
        monkeypatch.delenv('LEELA_KEYMAP')
        K.reload()
    assert 'open the vault `alt+v`' in _text(ai)

def test_reading_the_skill_never_rebuilds_the_toolset(ai):
    "A read mid-turn must not swap the tools under a backend briefed with the old ones."
    from leela.blocks.agent.skill import leela_skill
    ai.tools; ai._tools = None
    t = leela_skill(ai)
    assert ai._tools is None and '## Agent tools' in t and 'Offered now' not in t

def test_the_skill_survives_a_refresh_once_and_wins_over_a_project_skill_of_that_name(tmp_path):
    from shalya.skills import find
    d = tmp_path/'.agents'/'skills'/'leela'; d.mkdir(parents=True)
    (d/'SKILL.md').write_text('---\nname: leela\ndescription: a stale copy\n---\nold text\n')
    ai = Workspace(roots=[tmp_path]).ai
    assert find(ai.skills, 'leela').source == 'leela'
    ai.refresh()
    assert find(ai.skills, 'leela').source == 'leela'
    assert len([s for s in ai.registry.skills if s.name == 'leela']) == 1

@pytest.mark.xfail(strict=True, reason="ramabana's small profile lists no skills and offers no read_skill")
def test_the_small_profile_names_the_skill(tmp_path):
    ws = Workspace(roots=[tmp_path]); ws.agent_profile = 'small'
    ai = ws.ai
    assert ai.profile == 'small'
    assert '`leela`' in ai.system_prompt() and 'read_skill' in {t.__name__ for t in ai.tools}
