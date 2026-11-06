"The keymap and the buttons and menus that name the same actions."

import json
from fastcore.all import first
from leela.core.keys import DEFAULTS, apply_overrides, keymap_json, lookup, read_overrides, web_keymap


def test_new_lesson_is_an_unbound_palette_command_in_the_file_menu():
    from leela.blocks.keys.menus import BAR
    key = lookup('new_lesson')
    assert key is not None
    assert (key.key, key.scope, key.label) == ('', 'global', 'new lesson notebook')
    row = first(web_keymap(), lambda k: k['action'] == 'new_lesson')
    assert row and row['label'] == key.label and row['chords'] == []
    actions = [r.action for title, rows in BAR if title == 'File' for r in rows]
    assert actions[actions.index('new_notebook') + 1] == 'new_lesson'

HELP_PRESENT = 'These keys work only during a presentation. They cannot be rebound. Laser and blank have no button.'
HELP_TOP = 'Every key outside the present section can be rebound. Each of those keys also has a button.'

def test_the_keys_help_says_the_presentation_keys_cannot_be_rebound():
    "The help said every key in it could be rebound; the `present` rows are display rows, not bindings."
    from pathlib import Path
    from leela.core.keys import help_rows
    js = (Path(__file__).parents[1]/'leela'/'static'/'js'/'overlays.js').read_text()
    body = js[js.index('function showHelp'):]; body = body[:body.index('\n}\n')]
    assert 'every one of these can be rebound' not in body and HELP_TOP in body
    assert "scope === 'present'" in body and HELP_PRESENT in body and 'present' in help_rows()

def test_no_default_chord_lands_on_one_the_browser_will_not_deliver():
    reserved = {'ctrl+up', 'ctrl+down', 'ctrl+left', 'ctrl+right'}
    landed = [(k.action, c) for k in DEFAULTS for c in k.keys if c in reserved]
    assert not landed, f'these sit on a macOS-reserved chord: {landed}'
    chords = [(k.action, c) for k in DEFAULTS for c in k.keys]
    assert not [(a, c) for a, c in chords if c.startswith('ctrl+alt+')]
    assert not [(a, c) for a, c in chords if c.startswith('f')]


def test_a_legacy_hyper_chord_reaches_the_browser_as_all_four_modifiers():
    "The page matches a KeyboardEvent, which has no hyper key: it must see command, control, option and shift together."
    from leela.core.keys import legacy_rows
    hypers = [r['chord'] for r in legacy_rows() if r['chord']['hyper']]
    assert hypers, 'no old chord uses hyper, so this guards nothing'
    assert all(c[x] for c in hypers for x in ('mod', 'ctrl', 'alt', 'shift')), hypers


def _keymap(tmp_path, d):
    p = tmp_path / 'keys.json'
    p.write_text(json.dumps(d))
    return p


def test_a_broken_entry_costs_that_entry_and_nothing_else(tmp_path):
    "One typo must not throw the file away, and must not be silent either."
    p = _keymap(tmp_path, {'run_cell': 'ctrl+y', 'nope': 'ctrl+q',
                           'save': 'ctrl+bogus+s', 'focus_files': 'alt+shift+3'})
    notes = []
    ks = apply_overrides(DEFAULTS, read_overrides(p, notes=notes), notes=notes)
    by = {k.action: k for k in ks}
    assert by['run_cell'].keys[0] == 'ctrl+y'
    assert by['save'].key == lookup('save').key
    assert by['focus_files'].key == 'mod+1 alt+shift+1'
    assert len(notes) == 3 and all(isinstance(n, str) and n for n in notes)

def test_a_rejected_override_does_not_leak_into_the_defaults(tmp_path):
    "The trial map is a copy: a refused entry must not still be sitting in the table it was tried."
    p = _keymap(tmp_path, {'focus_files': 'alt+shift+3'})
    apply_overrides(DEFAULTS, read_overrides(p, notes=[]), notes=[])
    assert lookup('focus_files').key == 'mod+1 alt+shift+1'
    assert {k.action: k.key for k in DEFAULTS}['focus_files'] == 'mod+1 alt+shift+1'


def test_two_actions_can_trade_chords(tmp_path):
    "Applied one at a time, each half of a swap collided with the chord the other was about to give up."
    p = _keymap(tmp_path, {'copy_line_down': 'mod+d', 'select_next_occurrence': 'mod+shift+d'})
    notes = []
    by = {k.action: k.key for k in apply_overrides(DEFAULTS, read_overrides(p, notes=notes), notes=notes)}
    assert (by['copy_line_down'], by['select_next_occurrence'], notes) == ('mod+d', 'mod+shift+d', [])


def test_every_editing_command_the_router_runs_is_a_row_in_the_table():
    "A command with no row has no chord in a cell, since the cell editor drops CodeMirror's own."
    import re
    from fastcore.all import Path
    import leela
    src = (Path(leela.__file__).parent/'blocks/keys/keymap.js').read_text()
    acts = re.findall(r'(\w+): \'\w+\'', re.search(r'const CM_EDIT = \{(.*?)\};', src, re.S)[1])
    assert len(acts) == 11 and all(lookup(a) for a in acts), acts
    assert lookup('copy_line_down').key == 'mod+shift+d' and lookup('select_next_occurrence').key == 'mod+d'


def _written(path, keys=None, keep=True):
    from leela.core.keys import write_keymap
    write_keymap(path, keys=keys, keep=keep)
    return json.loads(path.read_text())


def test_an_unbound_action_is_an_override_and_not_an_empty_one(tmp_path):
    "`\"\"` unbinds, so a falsy check would drop the one entry the file exists to carry."
    p = tmp_path/'keys.json'
    ks = apply_overrides(DEFAULTS, {'save': ''}, notes=[])
    assert _written(p, keys=ks)['keys'] == {'save': ''}
    back = apply_overrides(DEFAULTS, read_overrides(p, notes=[]), notes=[])
    assert not first(back.filter(lambda k: k.action == 'save')).bound
    assert _written(p, keys=DEFAULTS)['keys'] == {'save': ''}, 'and it survives a second write'


def test_a_keymap_written_before_a_default_moved_does_not_collide_after_it(tmp_path):
    """`add_root` moved from `o` to `O` and `open_folder` took `o`."""
    from dataclasses import replace
    from fastcore.all import L
    import leela.core.keys as K
    was = L([replace(k, key='o') if k.action == 'add_root' else k
             for k in DEFAULTS if k.action != 'open_folder'])
    p = tmp_path/'keys.json'
    p.write_text(json.dumps({'_help': keymap_json()['_help'],
                             'keys': {k.action: k.key for k in was}}))
    notes = []
    apply_overrides(DEFAULTS, read_overrides(p, notes=notes), notes=notes)
    assert [n for n in notes if 'add_root' in n], 'the old full dump is what collides'
    keep = K.DEFAULTS
    K.DEFAULTS = was
    try: K.write_keymap(p, keys=was)
    finally: K.DEFAULTS = keep
    assert json.loads(p.read_text())['keys'] == {}
    notes = []
    ks = apply_overrides(DEFAULTS, read_overrides(p, notes=notes), notes=notes)
    assert notes == []
    assert {k.action: k.key for k in ks}['add_root'] == 'O'


def test_an_unbound_footer_action_leaves_the_footer_and_the_page_still_renders(monkeypatch):
    "Unbinding `help` in keys.json made every page a 500: the footer read the first chord of an action with none."
    from fastcore.xml import to_xml
    import leela.app as A, leela.core.keys as K
    monkeypatch.setattr(K, 'KEYS', apply_overrides(DEFAULTS, {'help': ''}, notes=[]))
    html = to_xml(A._footer())
    assert 'command palette' in html and '<span>keys</span>' not in html


def _keymap_js(expr):
    "Evaluate `expr` in node with `keymap.js` loaded on a stub page; the title code needs no DOM."
    import shutil, subprocess, pytest
    from pathlib import Path
    if not shutil.which('node'): pytest.skip('node is not installed')
    stub = ("globalThis.lee = {scope: 'editor'}; globalThis.location = {href: 'http://x/'};"
            "const _on = {}; globalThis.window = globalThis; globalThis.addEventListener = (k, f) => _on[k] = f;"
            "globalThis.document = {title: 'leela — orgs', addEventListener() {}};"
            "const _timers = []; globalThis.setTimeout = f => _timers.push(f); globalThis.clearTimeout = () => _timers.splice(0);\n")
    src = stub + (Path(__file__).parents[1]/'leela'/'blocks'/'keys'/'keymap.js').read_text()
    out = subprocess.run(['node', '-'], input=src + f'\nprocess.stdout.write(JSON.stringify({expr}));\n', capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_the_title_names_the_focused_pane_with_one_token_per_scope():
    cases = [('editor', 'text', 'a/b.py', 'py'), ('editor', 'notebook', 'n.ipynb', 'notebook'),
             ('widget', 'notebook', 'n.ipynb', 'notebook'), ('editor', 'text', 'README.MD', 'editor:md'),
             ('editor', 'text', 'Makefile', 'editor'), ('term', 'text', 'a.py', 'terminal'),
             ('agent', 'text', 'a.py', 'agent'), ('exec', 'text', 'a.py', 'exec'), ('files', 'text', 'a.py', 'files'),
             ('vars', 'text', 'a.py', 'vars'), ('vault', '', '', 'vault'), ('review', '', '', 'review'),
             ('global', 'text', 'a.py', '')]
    got = _keymap_js(f'{json.dumps(cases)}.map(([s, k, p]) => titleScope(s, k, p))')
    assert got == [c[3] for c in cases]
    assert _keymap_js("[leelaTitle('leela — orgs', 'py'), leelaTitle('leela — orgs', 'agent', '2⚙ (!)'), leelaTitle('leela', '')]") == \
        ['leela — orgs · py', '2⚙ (!) · leela — orgs · agent', 'leela']


def test_the_title_is_painted_once_per_change_and_sent_to_the_native_window():
    got = _keymap_js("""(() => {
      const sent = []; window.pywebview = {api: {set_title: (t, u) => { sent.push([t, u]); return Promise.resolve(true); }}};
      const flush = () => _timers.splice(0).forEach(f => f());
      lee.kind = 'text'; lee.path = 'x.py';
      paintTitle('term'); paintTitle('editor'); flush();
      paintTitle('overlay'); flush();
      lee.titlePrefix = '1⚙'; paintTitle(); flush();
      delete window.pywebview; paintTitle('vault'); flush();
      return {sent, title: document.title};
    })()""")
    assert got['sent'] == [['leela — orgs · py', 'http://x/'], ['1⚙ · leela — orgs · py', 'http://x/']], \
        'debounced to the last scope, an overlay keeps the scope under it, and an unchanged title is not sent again'
    assert got['title'] == '1⚙ · leela — orgs · vault', 'a browser without pywebview still gets the title'

def test_option_s_checks_the_exercise_in_the_editor_and_nothing_else():
    "abhyasa 0.0.13 asks for Option+S on Check my work. On a Mac Option+S types ß, so the chord matches the physical key."
    from leela.core.keys import _signature
    assert [(k.scope, k.action) for k in DEFAULTS for c in k.keys if _signature(c) == (('alt',), 's')] == [('editor', 'check_exercise')]
    k = lookup('check_exercise')
    assert k.label == 'check my work' and first(web_keymap(), lambda r: r['action'] == 'check_exercise')['chords'][0]['code'] == 'KeyS'


# Keys v2 lint: /tmp plan "Leela key binding plan (agreed 6 Nov 2026)". It checks the defaults; keys.json is only checked by `_dupes`.
_MODS = {'mod', 'ctrl', 'alt'}
#: AeroSpace's chords in ~/.aerospace.toml on 6 Nov 2026, beside what kavacha reserves.
AEROSPACE = {*(f'hyper+{k}' for k in [*'123456789', 'tab', *'sqawhjklrftcd', 'space', *'`[]=-0', 'up', 'down', 'left', 'right']),
             *(f'ctrl+alt+shift+{k}' for k in [*'123456789', 'left', 'right']),
             *(f'ctrl+alt+{k}' for k in [*'123456789', *'hjkl', 'up', 'down', 'left', 'right']),
             'alt+shift+left', 'alt+shift+right', 'alt+shift+;', 'mod+ctrl+tab', 'mod+ctrl+`'}

def _chords(keys=DEFAULTS): return [(k, c) for k in keys for c in k.keys]

def test_one_modifier_chord_means_one_thing_everywhere():
    "⌥↩, ⇧⌘↩ and ⌘D meant different things in different panes."
    from collections import defaultdict
    from leela.core.keys import SAME_IDEA, _signature, parse_key
    by = defaultdict(set)
    for k, c in _chords():
        if parse_key(c)[0] & _MODS: by[_signature(c)].add(k.action)
    groups = [set(g) for g in SAME_IDEA]
    bad = {s: a for s, a in by.items() if len(a) > 1 and not any(a <= g for g in groups)}
    assert not bad, bad

def test_bare_keys_are_panel_keys_and_command_mode_letters():
    from leela.core.keys import parse_key
    bare = [(k.scope, k.action, c) for k, c in _chords() if not parse_key(c)[0] & _MODS]
    assert not [b for b in bare if b[0] in ('global', 'exec', 'agent', 'term') and parse_key(b[2])[1] not in ('enter', 'escape')], bare
    named = {'enter', 'escape', 'up', 'down', 'left', 'right', 'backspace', 'pageup', 'pagedown', 'space', 'tab'}
    cmd = [(a, c) for s, a, c in bare if s == 'editor' and parse_key(c)[1] not in named]
    assert all(len(parse_key(c)[1]) == 1 for _, c in cmd) and len(cmd) >= 12, cmd

def test_no_default_uses_hyper_a_reserved_chord_a_dead_key_or_an_f_key():
    from kavacha import RESERVED
    from leela.core.keys import _signature, EDITING_SCOPES, parse_key
    allowed = {('complete', 'ctrl+space')}
    taken = {parse_key(c) for c in RESERVED | AEROSPACE}
    assert not [(k.action, c) for k, c in _chords() if 'hyper' in c]
    assert not [(k.action, c) for k, c in _chords() if parse_key(c) in taken and (k.action, c) not in allowed]
    dead = {_signature(c) for c in ('alt+e', 'alt+i', 'alt+u', 'alt+n', 'alt+`')}
    assert not [(k.action, c) for k, c in _chords() if (k.scope in EDITING_SCOPES or k.scope == 'global') and _signature(c) in dead]

def test_a_chrome_reserved_chord_always_has_a_second_chord_a_browser_tab_gets():
    rows = [r for r in web_keymap() if r['chords'] and not r['chords'][0]['browser']]
    assert {r['action'] for r in rows} >= {'close_tab', 'new_file', 'new_notebook', 'agent_new', 'focus_files'}
    assert all(any(c['browser'] for c in r['chords']) for r in rows), [r['action'] for r in rows]

def test_every_bound_global_action_has_a_menu_row():
    from leela.blocks.keys.menus import BAR
    from leela.core.keys import NO_MENU
    rows = {r.action for _, rs in BAR for r in rs if getattr(r, 'action', '')}
    missing = [k.action for k in DEFAULTS if k.scope == 'global' and k.bound and k.action not in rows | NO_MENU]
    assert not missing, missing

def test_a_scoped_chord_shows_in_the_menu_only_when_no_other_scope_binds_it():
    from kavacha.window import menu_chord
    from leela.blocks.keys.menus import menu_lookup
    assert menu_chord('run_cell', menu_lookup) is None, '⌘↩ is three runs, so the menu cannot own it'
    assert menu_chord('copy_line_down', menu_lookup) is not None
    assert menu_chord('close_tab', menu_lookup) == ('w', 1 << 20)

def test_menu_bar_and_launcher_chords_are_unique():
    from kavacha import LAUNCHER_ROWS
    from kavacha.window import menu_json
    from leela.blocks.keys.menus import BAR, menu_lookup
    seen = {}
    for m in menu_json(BAR, menu_lookup) + menu_json([('launcher', LAUNCHER_ROWS)], menu_lookup):
        for r in m['items']:
            if 'key' not in r: continue
            what = r.get('action') or r.get('selector') or r.get('js')
            assert seen.setdefault((r['key'], r['mask']), what) == what, (r, seen[(r['key'], r['mask'])])
    assert seen[('W', 1 << 20)] == 'performClose:' and seen[('w', 1 << 20)] == 'close_tab'

def test_old_chords_never_shadow_a_new_default():
    from leela.core.keys import LEGACY, lookup, parse_key
    new = {parse_key(c) for _, c in _chords()}
    assert not [c for c in LEGACY if parse_key(c) in new]
    assert all(lookup(a) for a in LEGACY.values())

def test_an_old_generated_snapshot_moves_to_the_v2_defaults(tmp_path):
    "A full dump written before keys v2 froze the Hyper chords; its untouched defaults move, its edits stay."
    import leela.core.keys as K
    old = {k.action: k.key for k in DEFAULTS} | {a: o for a, (o, _) in K._V2_MIGRATIONS.items()}
    old['save'] = 'mod+shift+s'
    p = _keymap(tmp_path, {'_help': ['leela keymap: action -> chord', 'mod is Command'], 'keys': old})
    notes = []
    ks = apply_overrides(DEFAULTS, read_overrides(p, notes=notes), notes=notes)
    by = {k.action: k.key for k in ks}
    assert notes == [], notes
    assert by['toggle_scope'] == 'alt+t' and by['close_tab'] == 'mod+w alt+w' and by['save'] == 'mod+shift+s'
    assert by['new_file'] == 'mod+n mod+alt+shift+n' and by['tree_new_file'] == 'n'

def test_a_bare_key_on_new_file_moves_to_the_files_panel():
    from leela.core.keys import _tree_moved
    assert _tree_moved({'new_file': 'a'}) == {'tree_new_file': 'a'}
    assert _tree_moved({'new_file': 'mod+shift+m'}) == {'new_file': 'mod+shift+m'}

def test_the_page_gets_one_glyph_per_chord_from_kavacha():
    from leela.core.keys import glyphs
    row = first(web_keymap(), lambda r: r['action'] == 'toggle_left')
    assert row['display'] == ['⌥⇧B']
    assert first(web_keymap(), lambda r: r['action'] == 'cell_delete')['display'] == ['⌥⌘⌫', 'D D']
    g = glyphs()
    assert g['mac']['mod+shift+p'] == '⇧⌘P' and g['pc']['mod+shift+p'] == 'Ctrl+Shift+P' and g['mac']['alt+i'] == '⌥I'

def test_an_overlay_swallows_menu_chords_but_keeps_the_editing_ones():
    from leela.blocks.keys.menus import menu_chords
    got = {(c['key'], c['mod'], c['ctrl'], c['alt'], c['shift']) for c in menu_chords()}
    assert ('p', True, False, False, False) in got and ('w', True, False, False, False) in got
    assert ('W', True, False, False, True) in got
    assert not got & {('c', True, False, False, False), ('v', True, False, False, False), ('z', True, False, False, False)}

def test_open_is_the_mac_open_and_go_to_file_is_the_quick_open():
    """⌘O opened folders only and ⌘P was called "open file", so the owner reached for ⌘P to open a file from the Mac."""
    from kavacha.window import menu_json
    from leela.blocks.keys.menus import BAR, MENUS, menu_lookup
    from leela.core.keys import help_rows
    from leela.core.ui import BUTTONS
    assert (lookup('open_folder').key, lookup('open_folder').label) == ('mod+o', 'open…')
    assert (lookup('quick_open').key, lookup('quick_open').label) == ('mod+p', 'go to file…')
    assert lookup('tree_open_folder').key == 'o', 'the tree keeps its folder key'
    file = first(m for m in menu_json(BAR, menu_lookup) if m['title'] == 'File')['items']
    rows = {r.get('action'): r for r in file}
    assert (rows['open_folder']['title'], rows['open_folder']['key'], rows['open_folder']['mask']) == ('Open…', 'o', 1 << 20)
    assert (rows['quick_open']['title'], rows['quick_open']['key']) == ('Go to file…', 'p')
    acts = [r.get('action') for r in file]
    assert acts.index('open_folder') + 1 == acts.index('quick_open')
    assert [i.action for i in MENUS['files'][:2]] == ['open_folder', 'quick_open'], 'the files panel menu shows both'
    btns = {b.action: b.label for b in BUTTONS if b.bar in ('files', 'web_files')}
    assert (btns['open_folder'], btns['quick_open']) == ('open…', 'go to file…'), 'and its buttons'
    assert {('mod+o', 'open…'), ('mod+p', 'go to file…')} <= set(help_rows()['global'])
