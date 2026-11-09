from leela.blocks.learn.walk import walk_fragment


def state(current=1, steps=None):
    if steps is None: steps = [
        dict(i=0, name='First', statement='Start here.', status='open', quote=None, check=None),
        dict(i=1, name='Second', statement='Continue here.', status='open', quote=dict(text='A verbatim source.', url='https://example.com/source', title='Source'), check=dict(question='What follows?', kind='short')),
        dict(i=2, name='Third', statement='Finish here.', status='open', quote=None, check=None),
    ]
    return dict(status='ok', revision='one', data=dict(title='Walk', current=current, steps=steps, gauge=dict(first=dict(state='new'), second=dict(state='known'))))


def test_walk_fragment_renders_walk_contract():
    page = str(walk_fragment(state(), 'walk-1'))
    assert '<blockquote>A verbatim source.</blockquote>' in page
    assert '<a href="https://example.com/source"' in page
    assert '<form' in page and 'action="/learn/walk/walk-1/1/answer"' in page and 'data-walk-answer="1"' in page
    assert 'name="attempt_id"' in page and 'name="revision" value="one"' in page
    assert 'data-walk-back="0"' in page and 'data-walk-next="2"' in page
    assert 'first' in page and 'new' in page and 'second' in page and 'known' in page
    first = str(walk_fragment(state(current=0), 'walk-1'))
    assert 'data-walk-back' not in first and 'data-walk-next="1"' in first
    last = str(walk_fragment(state(current=2), 'walk-1'))
    assert 'data-walk-back="1"' in last and 'data-walk-next' not in last


def test_walk_fragment_rejects_unsafe_links_and_renders_empty_errors():
    steps = [dict(i=0, name='Unsafe', statement='', status='open', quote=dict(text='No link.', url='javascript:alert(1)', title='Unsafe'), check=None)]
    unsafe = str(walk_fragment(state(current=0, steps=steps), 'walk-1'))
    assert 'javascript:alert(1)' not in unsafe and '<span>Unsafe</span>' in unsafe
    malformed = str(walk_fragment(state(current=0, steps=[{**steps[0], 'quote': dict(text='No link.', url='http://[bad', title='Bad')}]), 'walk-1'))
    assert '<span>Bad</span>' in malformed
    empty = str(walk_fragment(state(steps=[]), 'walk-1'))
    assert 'This walk has no steps yet.' in empty
    error = str(walk_fragment(dict(status='error', error='not_found', data=dict(message='Missing walk', steps=state()['data']['steps'], current=1)), 'walk-1'))
    assert 'Missing walk' in error and 'First' in error and 'Second' in error and 'role="status"' in error
    locked = str(walk_fragment(dict(status='error', error='vault_locked', data=dict(message='Vault is busy')), 'walk-1'))
    assert 'Vault is busy' in locked and 'no steps yet' not in locked
