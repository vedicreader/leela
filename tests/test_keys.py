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

def test_no_default_chord_lands_on_one_the_browser_will_not_deliver():
    reserved = {'ctrl+up', 'ctrl+down', 'ctrl+left', 'ctrl+right'}
    landed = [(k.action, c) for k in DEFAULTS for c in k.keys if c in reserved]
    assert not landed, f'these sit on a macOS-reserved chord: {landed}'
    chords = [(k.action, c) for k in DEFAULTS for c in k.keys]
    assert not [(a, c) for a, c in chords if c.startswith('ctrl+alt+')]
    assert not [(a, c) for a, c in chords if c.startswith('f')]


def test_a_hyper_chord_reaches_the_browser_as_all_four_modifiers():
    "The page matches a KeyboardEvent, which has no hyper key: it must see command, control, option and shift together."
    hypers = [c for r in web_keymap() for c in r['chords'] if c['hyper']]
    assert hypers, 'no default uses hyper, so this guards nothing'
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
    assert by['focus_files'].key == 'alt+shift+1'
    assert len(notes) == 3 and all(isinstance(n, str) and n for n in notes)

def test_a_rejected_override_does_not_leak_into_the_defaults(tmp_path):
    "The trial map is a copy: a refused entry must not still be sitting in the table it was tried."
    p = _keymap(tmp_path, {'focus_files': 'alt+shift+3'})
    apply_overrides(DEFAULTS, read_overrides(p, notes=[]), notes=[])
    assert lookup('focus_files').key == 'alt+shift+1'
    assert {k.action: k.key for k in DEFAULTS}['focus_files'] == 'alt+shift+1'


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
