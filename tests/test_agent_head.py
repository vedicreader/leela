"The agent pane's head and composer: four head buttons, every other action in the ⋯ menu and the keymap."
import re
from html.parser import HTMLParser
from pathlib import Path
from starlette.testclient import TestClient

from leela.app import ide_app
from leela.blocks.keys.menus import web_menus
from leela.core.keys import lookup
from leela.workspace import Workspace

ROOT = Path(__file__).parents[1]
ACTIONS_JS = (ROOT/'leela'/'static'/'js'/'actions.js').read_text()
VOID = {'input', 'br', 'img', 'hr', 'meta', 'link'}

class Head(HTMLParser):
    "The attributes of the agent head and of every button inside it."
    def __init__(s): super().__init__(); s.depth, s.buttons, s.head = 0, [], {}
    def handle_starttag(s, tag, attrs):
        a = dict(attrs)
        if s.depth:
            if tag not in VOID: s.depth += 1
            if tag == 'button': s.buttons.append(a)
        elif tag == 'div' and 'lee-agent-head' in (a.get('class') or '').split(): s.depth, s.head = 1, a
    def handle_endtag(s, tag):
        if s.depth and tag not in VOID: s.depth -= 1

def page(tmp_path, **kw):
    ws = Workspace(roots=[tmp_path])
    for k, v in kw.items(): setattr(ws, k, v)
    with TestClient(ide_app(ws)) as c: return c.get('/').text

#: what each former head button called, and the keymap action that now reaches it
FORMER = {'leeAgentThreadsToggle': 'agent_threads', 'leeAgentNew': 'agent_new', 'leeAgentWarmToggle': 'agent_warm',
          "leeAgentOptinToggle('research')": 'agent_research', "leeAgentOptinToggle('exhash')": 'agent_exhash',
          "leeAgentOptinToggle('browser')": 'agent_browser', 'leeAgentFullToggle': 'agent_full', 'leeAgentHistory': 'agent_history',
          'leeAgentCalm': 'agent_calm', 'leeAgentAssess': 'agent_assess', 'leeAgentCapture': 'agent_round',
          'leeAgentAccept': 'agent_accept', 'leeMemoryNotes': 'memory_notes', 'leeAgentState': 'agent_state',
          'leeAgentExpand': 'agent_expand'}
ORDER = ['agent_new', 'agent_threads', 'agent_history', 'agent_assess', 'agent_round', 'agent_accept', None,
         'agent_calm', 'agent_expand', None, 'agent_research', 'agent_exhash', 'agent_browser', 'memory_notes', None,
         'agent_warm', 'agent_full', 'agent_state']
TOGGLES = {'agent_history', 'agent_calm', 'agent_expand', 'agent_research', 'agent_exhash', 'agent_browser', 'agent_warm', 'agent_full'}

def test_the_head_keeps_four_buttons_and_hands_the_rest_to_the_menu(tmp_path):
    html = page(tmp_path, agent_optin=('research',), agent_profile='full')
    p = Head(); p.feed(html)
    shown = [b for b in p.buttons if 'hidden' not in b]
    assert [b.get('id') for b in shown] == ['agentthreads', 'agentnew', 'agentmore', 'agentexpand'], shown
    more = shown[2]
    assert more.get('aria-haspopup') == 'menu' and more.get('aria-expanded') == 'false' and more.get('aria-label'), more
    assert p.head.get('data-optin-default') == 'research' and p.head.get('data-profile') == 'full', p.head
    for gone in ('agentstate', 'agentmemory', 'agentwarm', 'agentfull', 'agentcalm', 'agenthistory', 'agentassess',
                 'agentcapture', 'agentaccept', 'agentoptin-research'):
        assert f'id="{gone}"' not in html, gone

def test_every_former_head_action_is_in_the_menu_or_the_keymap_and_has_a_handler():
    rows = web_menus()['agent_head']
    assert [r.get('action') for r in rows] == ORDER
    assert {r['action'] for r in rows if r.get('check')} == TOGGLES
    for handler, action in FORMER.items():
        key = lookup(action)
        assert key.label, f'{action} has no label for the palette'
        if action not in ('agent_new', 'agent_threads', 'agent_expand', 'memory_notes'): assert not key.keys, f'{action} took a chord'
        line = re.search(rf'^\s+{action}:(.*)$', ACTIONS_JS, re.M)
        assert line and handler in line[1], f'ACTIONS.{action} does not run {handler}'
    assert lookup('agent_menu').label and re.search(r'^\s+agent_menu:.*leeAgentMenu', ACTIONS_JS, re.M)

def test_the_composer_chip_holds_the_four_selects_and_the_attach_button_is_an_icon(tmp_path):
    html = page(tmp_path)
    chip = re.search(r'<details[^>]*id="agentchip"[^>]*>.*?</details>', html, re.S)
    assert chip, 'no composer chip'
    for sel in ('agentmodel', 'agentcontrol', 'agentreasoning', 'agenttoolbudget'): assert f'id="{sel}"' in chip[0], sel
    assert re.search(r'data-mode="(autopilot|guided|directed|edits)"', chip[0])
    attach = re.search(r'<button[^>]*id="agentattach"[^>]*>(.*?)</button>', html, re.S)
    assert attach and 'aria-label="attach image"' in attach[0] and 'leeAgentAttach()' in attach[0]
    assert 'attach image' not in attach[1], 'the button should carry an icon, not its words'
