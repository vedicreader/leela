"The keymap and the buttons and menus that name the same actions."

import json
from fastcore.all import first
from leela.core.keys import DEFAULTS, apply_overrides, keymap_json, lookup, read_overrides, web_keymap


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
