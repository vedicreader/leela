"The presentation guide: found from both indexes, true to the one mode, honest about what the room can see, and silent on what is not built."

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
GUIDE = ROOT/'docs'/'present.md'
LATER = '## Not in this version'

def _guide():
    assert GUIDE.is_file(), 'docs/present.md is missing'
    return GUIDE.read_text()

def test_the_guide_is_linked_from_the_readme_and_the_docs_index():
    _guide()
    assert '(docs/present.md)' in (ROOT/'README.md').read_text()
    assert '(present.md)' in (ROOT/'docs'/'README.md').read_text()

def test_the_guide_states_one_mode_and_drops_the_reveal_options():
    g = _guide()
    assert 'Leela has one presentation mode.' in g and 'writes no file' in g
    assert 'Esc never ends the presentation.' in g
    assert 'Leela ignores `rise.theme` and every other reveal.js option except `rise.start_slideshow_at`.' in g
    for line in g.splitlines():
        if re.search(r'(?i)reveal\.js', line): assert 'ignores' in line, line
    for old in ('Present to a room', 'vertical navigation', '/present/notes', 'BroadcastChannel', 'notes page'): assert old not in g, old

def test_the_guide_states_the_limits_and_the_notes_warning():
    g = _guide()
    assert '## What the room never sees' in g and '## What the room can still see' in g
    for limit in ('plain text', 'stream text', 'code source', 'state path', '`why`', '`alt` text', 'stderr'): assert limit in g, limit
    assert 'Speaker notes are not on the audience page. They are visible to the room when you share the presenter screen.' in g
    assert not re.search(r'(?i)all (the )?answers are hidden|answers are always hidden|never sees an answer', g)
    assert '\u2014' not in g, 'no em dashes'

def test_the_guide_does_not_offer_what_is_not_built():
    g = _guide()
    assert LATER in g
    body, later = g.split(LATER, 1)
    later = later.split('\n## ', 1)[0]
    for item in ('Ask the room', '.talk.json', 'recap', 'run log', 'agent-drafted', 'native audience window', 'blank keys other than B'):
        assert item in later, item
        assert item not in body, f'{item!r} is offered outside {LATER!r}'
