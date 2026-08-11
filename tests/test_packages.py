"""Whose code just raised, and which copy of it is running.

Both answers are about paths, so both are tested against made-up ones: a real environment
would make the interesting cases (a checkout shadowed by a wheel) impossible to arrange.
"""

from leela.packages import FAMILY, blame, checkout_for, frames, survey

TRACEBACK = '''
❯ python deploy.py deploy
Traceback (most recent call last):
  File "/work/kalpa/deploy.py", line 12, in deploy
    cf.setup_tunnel(domain, sub)
  File "/venv/lib/python3.12/site-packages/cfeasy/core.py", line 110, in setup_tunnel
    tid = first(t)['id'] if (t := exists(self.tunnels())) else self.create_tunnel(tname)['id']
  File "/venv/lib/python3.12/site-packages/cfeasy/core.py", line 57, in tunnels
    aid = account_id or self.account_id()
cloudflare.AuthenticationError: Authentication error [code: 10000]
'''


def make_checkout(root, name):
    (root/name/name).mkdir(parents=True)
    (root/name/name/'__init__.py').write_text('')
    (root/name/name/'core.py').write_text('x = 1\n')
    return root/name


def test_a_checkout_is_found_by_what_it_contains_not_by_its_name(tmp_path):
    "A repository can be called anything; `<root>/<name>/__init__.py` is what makes it the source."
    odd = tmp_path/'my-fork'
    (odd/'cfeasy').mkdir(parents=True)
    (odd/'cfeasy'/'__init__.py').write_text('')
    assert checkout_for('cfeasy', [odd]) == str(odd)
    assert checkout_for('vpseasy', [odd]) == ''


def test_the_deepest_frame_of_yours_is_the_one_to_open(tmp_path):
    """Your deploy calls cfeasy and both are yours -- the one that raised is the one to open.

    And when it raised in an installed copy while the same package is checked out here, the
    path is rewritten to the checkout, because that is the file an edit survives in.
    """
    checkout = make_checkout(tmp_path, 'cfeasy')
    b = blame(TRACEBACK, checkouts=[checkout])
    assert b['package'] == 'cfeasy' and b['line'] == 57 and b['fn'] == 'tunnels'
    assert b['error'].startswith('cloudflare.AuthenticationError')
    assert b['open'] == str(checkout/'cfeasy'/'core.py'), 'opened where a fix would land'
    assert b['checkout'] == str(checkout)


def test_without_a_checkout_it_still_names_the_package(tmp_path):
    b = blame(TRACEBACK, checkouts=[])
    assert b['package'] == 'cfeasy' and b['open'].endswith('site-packages/cfeasy/core.py')
    assert b['checkout'] == ''


def test_a_traceback_with_nothing_of_yours_in_it_blames_nobody():
    text = 'Traceback:\n  File "/usr/lib/python3.12/json/decoder.py", line 1, in decode\nValueError: bad'
    b = blame(text)
    assert b['package'] == '' and b['open'] == ''
    assert b['error'] == 'ValueError: bad', 'the exception is still worth reporting'


def test_frames_are_read_in_order():
    got = frames(TRACEBACK)
    assert [f['line'] for f in got] == [12, 110, 57]
    assert got[0]['fn'] == 'deploy'


def test_a_checkout_shadowed_by_an_installed_copy_is_the_row_worth_seeing(tmp_path, monkeypatch):
    """An edit in the checkout does nothing until the environment is reinstalled.

    Nothing else in the survey is as expensive to not know, so it is a flag of its own
    rather than something to infer from two paths.
    """
    import leela.packages as pkg
    checkout = make_checkout(tmp_path, 'cfeasy')
    monkeypatch.setattr(pkg, '_origin', lambda n: tmp_path/'venv'/'site-packages'/n if n == 'cfeasy' else None)
    rows = {r['name']: r for r in survey(['cfeasy', 'vpseasy'], [checkout])}
    assert rows['cfeasy']['shadowed'] and rows['cfeasy']['source'] == 'site-packages'
    assert rows['cfeasy']['checkout'] == str(checkout)
    assert not rows['vpseasy']['installed'] and not rows['vpseasy']['shadowed']


def test_a_package_run_from_its_checkout_is_not_shadowed(tmp_path, monkeypatch):
    import leela.packages as pkg
    checkout = make_checkout(tmp_path, 'cfeasy')
    monkeypatch.setattr(pkg, '_origin', lambda n: checkout/'cfeasy')
    row = survey(['cfeasy'], [checkout])[0]
    assert row['source'] == 'checkout' and row['editable'] and not row['shadowed']


def test_the_family_is_the_packages_this_workspace_is_about():
    for name in ('gheasy', 'dockeasy', 'vpseasy', 'cfeasy'):
        assert name in FAMILY


VENV_TRACEBACK = '''  File "<string>", line 4, in <module>
  File "/home/you/code/leela/.venv/lib/python3.12/site-packages/cfeasy/core.py", line 110, in setup_tunnel
    tid = first(t)['id']
  File "/home/you/code/leela/.venv/lib/python3.12/site-packages/cloudflare/_client.py", line 1431, in _validate_headers
    raise TypeError("Could not resolve authentication method.")
TypeError: Could not resolve authentication method.
'''


def test_a_venv_inside_a_package_directory_does_not_capture_every_traceback():
    """The bug this pins: a virtualenv at `~/code/leela/.venv` puts `leela` in the path of
    every installed package, so matching a family name anywhere in the path attributes the
    Cloudflare SDK's own error to Leela and points at the wrong repository.

    Inside `site-packages` the owner is the component straight after it, and nothing else.
    """
    b = blame(VENV_TRACEBACK)
    assert b['package'] == 'cfeasy', 'the deepest frame that is actually one of yours'
    assert b['line'] == 110 and b['fn'] == 'setup_tunnel'
    assert b['error'].startswith('TypeError')


def test_a_third_party_frame_is_nobody_of_yours():
    "cloudflare is not in the family, so a failure only in its code blames no package."
    only_theirs = '\n'.join(l for l in VENV_TRACEBACK.splitlines() if 'cfeasy' not in l)
    assert blame(only_theirs)['package'] == ''
