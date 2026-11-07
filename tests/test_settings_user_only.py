"A repo's `.leela/settings.json` may not choose the shell or the agent's folder."

import json
from leela.blocks.settings.settings import Settings
from leela.blocks.term.term import shell_argv

def _repo(tmp_path, data):
    (tmp_path/'proj'/'.leela').mkdir(parents=True)
    (tmp_path/'proj'/'.leela'/'settings.json').write_text(json.dumps(data))
    return Settings(tmp_path/'proj', user_path=tmp_path/'user.json')

BAD = {'terminal': {'shell': '/bin/sh', 'shellArgs': ['-c', 'echo PWNED'], 'external': 'Evil'},
       'agent': {'configFolder': '/tmp/elsewhere', 'calm': True}, 'editor': {'fontSize': 20},
       'languages': {'python': {'terminal': {'shell': '/bin/sh'}, 'editor': {'tabSize': 2}}}}

def test_a_repo_cannot_set_the_shell_or_the_agent_folder(tmp_path):
    s = _repo(tmp_path, BAD)
    e, t = s.effective('python'), s.effective()['terminal']
    assert shell_argv(t.get('shell'), t.get('shellArgs'), t.get('loginShell'))[:2] != ['/bin/sh', '-c']
    assert e['terminal']['shell'] == '' and e['terminal']['external'] == '' and e['agent']['configFolder'] == ''
    assert e['editor']['fontSize'] == 20 and e['editor']['tabSize'] == 2 and e['agent']['calm'] is True, 'other repo settings still apply'
    d = s.describe()
    assert d['ignored'] == ['agent.configFolder', 'terminal.external', 'terminal.shell', 'terminal.shellArgs']
    assert d['origins']['terminal']['shell'] == 'default' and 'workspace' not in d['layers'].get('terminal', {}).get('shell', [])

def test_the_users_own_file_still_sets_them(tmp_path):
    s = _repo(tmp_path, BAD)
    s.save('user', 'terminal', {'shell': '/bin/zsh'})
    assert s.effective()['terminal']['shell'] == '/bin/zsh' and s.describe()['origins']['terminal']['shell'] == 'user'

def test_a_workspace_save_keeps_the_repo_file_and_writes_no_user_only_key(tmp_path):
    s = _repo(tmp_path, BAD)
    s.save('workspace', 'agent', {'configFolder': '/tmp/x', 'calm': False})
    on_disk = json.loads((tmp_path/'proj'/'.leela'/'settings.json').read_text())
    assert on_disk['agent'] == {'configFolder': '/tmp/elsewhere', 'calm': False}, 'the save neither drops nor sets it'
    assert on_disk['terminal'] == BAD['terminal']
