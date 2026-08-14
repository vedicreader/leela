"""Which folders the app opens when nobody tells it — the whole of a double-click.

A command line answers "which project" every time. A desktop app is launched by double-click,
by a Dock drop, or by Finder's "Open With", and has to work all three out for itself. These
tests are about that: what is remembered, what is offered, and -- the one with teeth -- what is
*not* opened when there is nothing to go on.
"""

from __future__ import annotations

import json
import os
import sys

import pytest
from starlette.testclient import TestClient

import leela_app
from leela.app import ide_app
from leela.core import projects
from leela.workspace import Workspace

@pytest.fixture(autouse=True)
def session_file(tmp_path, monkeypatch):
    "Point the remembered session at a scratch file; it is real state in a real config dir."
    monkeypatch.setattr(projects, 'SESSION', tmp_path/'desktop.json')
    return tmp_path/'desktop.json'

@pytest.fixture
def dirs(tmp_path):
    made = []
    for name in ('alpha', 'beta', 'gamma'):
        (tmp_path/name).mkdir()
        made.append(str(tmp_path/name))
    return made

def test_nothing_remembered_reads_as_nothing_rather_than_failing(session_file):
    assert projects.session() == {'folders': [], 'recent': []}
    assert projects.last_folders() == [] and projects.recent_folders() == []

def test_a_corrupt_session_file_does_not_stop_the_app_opening(session_file):
    "Half a write survives a crash; refusing to launch over it would not be an improvement."
    session_file.write_text('{"folders": [')
    assert projects.last_folders() == []

def test_the_folders_a_launch_opened_are_what_the_next_one_reopens(dirs):
    projects.remember(dirs[:2])
    assert projects.last_folders() == dirs[:2]

def test_opening_another_folder_adds_to_the_set_rather_than_replacing_it(dirs):
    """Under `--app` each folder is its own `Workspace`.

    Each recording itself would leave the session naming whichever one wrote last.
    """
    projects.remember([dirs[0]])
    projects.note_folder(dirs[1])
    assert projects.last_folders() == dirs[:2]

def test_closing_a_folder_stops_it_reopening_but_does_not_forget_it(dirs):
    projects.remember(dirs[:2])
    projects.drop_folder(dirs[0])
    assert projects.last_folders() == [dirs[1]]
    assert dirs[0] in projects.recent_folders(), 'closing a project is not forgetting it'

def test_recent_projects_come_back_most_recently_opened_first(dirs):
    for d in dirs: projects.note_folder(d)
    assert projects.recent_folders()[:3] == list(reversed(dirs))

def test_the_recent_list_is_bounded(tmp_path):
    for i in range(projects.MAX_RECENT + 8):
        d = tmp_path/f'p{i}'; d.mkdir()
        projects.note_folder(str(d))
    assert len(projects.recent_folders()) == projects.MAX_RECENT

def test_a_folder_that_has_gone_is_dropped_rather_than_offered(dirs, tmp_path):
    "Projects get deleted, renamed and unmounted between launches."
    projects.remember(dirs[:2])
    os.rmdir(dirs[0])
    assert projects.last_folders() == [dirs[1]]
    assert dirs[0] not in projects.recent_folders()

def test_forgetting_a_project_removes_it_from_the_welcome_screen(dirs):
    for d in dirs: projects.note_folder(d)
    projects.forget_recent(dirs[1])
    assert dirs[1] not in projects.recent_folders()

def test_the_same_folder_is_only_listed_once(dirs):
    projects.note_folder(dirs[0])
    projects.note_folder(dirs[0] + '/')
    projects.note_folder(dirs[0])
    assert projects.recent_folders().count(dirs[0]) == 1

def test_a_launch_with_no_arguments_reopens_the_last_session(dirs, monkeypatch):
    projects.remember(dirs[:2])
    seen = {}
    monkeypatch.setattr(leela_app, 'serve', lambda args, background=False: seen.setdefault('args', args))
    monkeypatch.setattr(leela_app, 'free_port', lambda preferred=5001: 5199)
    monkeypatch.setattr('leela.desktop.shell_ready', lambda *a: (True, 'gtk'))
    monkeypatch.setattr('leela.desktop.start_cdp', lambda *a, **k: None)
    monkeypatch.setattr('leela.desktop.run_shell', lambda urls, **kw: seen.update(urls=urls, **kw))
    monkeypatch.setattr(leela_app.sys, 'argv', ['leela_app.py'])
    leela_app.run()
    assert seen['args'][-2:] == dirs[:2]

def test_a_folder_given_by_the_desktop_wins_over_the_remembered_session(dirs, monkeypatch):
    "Opening a project with Leela means that project, not the one from yesterday."
    projects.remember([dirs[0]])
    seen = {}
    monkeypatch.setattr(leela_app, 'serve', lambda args, background=False: seen.setdefault('args', args))
    monkeypatch.setattr(leela_app, 'free_port', lambda preferred=5001: 5199)
    monkeypatch.setattr('leela.desktop.shell_ready', lambda *a: (True, 'gtk'))
    monkeypatch.setattr('leela.desktop.start_cdp', lambda *a, **k: None)
    monkeypatch.setattr('leela.desktop.run_shell', lambda urls, **kw: seen.update(urls=urls, **kw))
    monkeypatch.setattr(leela_app.sys, 'argv', ['leela_app.py', dirs[2]])
    leela_app.run()
    assert seen['args'][-1:] == [dirs[2]]
    assert projects.last_folders() == [dirs[2]]

def test_every_workspace_gets_its_own_window(dirs, monkeypatch):
    """`--app` gives each folder an isolated workspace behind a host-dispatching hub.

    One window on the bare loopback host would show the first folder and strand the rest.
    """
    seen = {}
    monkeypatch.setattr(leela_app, 'serve', lambda args, background=False: None)
    monkeypatch.setattr(leela_app, 'free_port', lambda preferred=5001: 5199)
    monkeypatch.setattr('leela.desktop.shell_ready', lambda *a: (True, 'gtk'))
    monkeypatch.setattr('leela.desktop.start_cdp', lambda *a, **k: None)
    monkeypatch.setattr('leela.desktop.run_shell', lambda urls, **kw: seen.update(urls=urls, **kw))
    monkeypatch.setattr(leela_app.sys, 'argv', ['leela_app.py', *dirs[:2]])
    leela_app.run()
    assert seen['urls'] == ['http://alpha.localhost:5199/', 'http://beta.localhost:5199/']
    assert seen['titles'] == ['leela — alpha', 'leela — beta']

def test_with_nothing_to_open_there_is_still_one_window(monkeypatch):
    seen = {}
    monkeypatch.setattr(leela_app, 'serve', lambda args, background=False: None)
    monkeypatch.setattr(leela_app, 'free_port', lambda preferred=5001: 5199)
    monkeypatch.setattr('leela.desktop.shell_ready', lambda *a: (True, 'gtk'))
    monkeypatch.setattr('leela.desktop.start_cdp', lambda *a, **k: None)
    monkeypatch.setattr('leela.desktop.run_shell', lambda urls, **kw: seen.update(urls=urls, **kw))
    monkeypatch.setattr(leela_app.sys, 'argv', ['leela_app.py'])
    leela_app.run()
    assert seen['urls'] == ['http://127.0.0.1:5199/'] and seen['titles'] == ['leela']

def test_a_frozen_app_with_no_folder_opens_on_nothing_rather_than_on_your_home_directory():
    """The bad guess this replaces had teeth.

    `leela` from a shell means "here", and the shell already chose where here is. A
    double-clicked application has no such answer, and the old fallback -- the home directory
    -- handed Kosha every file the user owns to index and the watcher every one to follow.
    """
    import inspect

    from leela import app as appmod
    src = inspect.getsource(appmod.serve_ide)
    assert 'Path.home()' not in src, 'the home-directory fallback is back'
    assert "not getattr(sys, 'frozen', False)" in src

def test_a_workspace_with_no_folders_still_serves(tmp_path, monkeypatch):
    "Opening on nothing has to be a usable screen, not a broken one."
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'v.db'))
    ws = Workspace(roots=[], port=8000)
    with TestClient(ide_app(ws)) as c:
        page = c.get('/')
        assert page.status_code == 200
        assert 'Open a folder' in page.text, 'the welcome screen must offer a way in'
        assert 'leerecent' in page.text
        assert c.get('/fs/recent').json()['ok']

def test_the_welcome_screen_offers_the_projects_you_have_opened_before(tmp_path, dirs, monkeypatch):
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'v.db'))
    for d in dirs: projects.note_folder(d)
    ws = Workspace(roots=[dirs[0]], port=8000)
    with TestClient(ide_app(ws)) as c:
        d = c.get('/fs/recent').json()
    listed = {r['name']: r['open'] for r in d['recent']}
    assert listed == {'alpha': True, 'beta': False, 'gamma': False}
    assert d['home'] == str(__import__('pathlib').Path.home())

def test_opening_a_folder_in_the_app_is_remembered_for_next_launch(tmp_path, dirs, monkeypatch):
    "The set that reopens has to follow the workspace, not the arguments it started with."
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'v.db'))
    ws = Workspace(roots=[dirs[0]], port=8000)
    with TestClient(ide_app(ws)) as c:
        c.get('/fs/add_root?path=' + dirs[1])
        assert projects.last_folders() == [dirs[1]]
        c.post('/fs/remove-root', json={'path': dirs[1]})
    assert projects.last_folders() == []
    assert dirs[1] in projects.recent_folders()

def test_a_folder_handed_to_a_running_app_is_added_to_it(tmp_path, dirs, monkeypatch):
    """The Dock-drop path: macOS delivers the folder to the process already running.

    It goes through the HTTP route because the server owns the `Workspace` on another thread
    and another event loop.
    """
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'v.db'))
    import threading

    import uvicorn
    ws = Workspace(roots=[dirs[0]], port=8000)
    server = uvicorn.Server(uvicorn.Config(ide_app(ws), host='127.0.0.1', port=5207,
                                           log_level='error'))
    threading.Thread(target=server.run, daemon=True).start()
    from leela.desktop import wait_for_http
    assert wait_for_http('http://127.0.0.1:5207/', timeout=30)
    try:
        leela_app.open_folder(5207, dirs[1])
        assert str(dirs[1]) in [str(r) for r in ws.fs.roots]
        assert dirs[1] in projects.last_folders()
    finally: server.should_exit = True

@pytest.mark.skipif(sys.platform == 'darwin', reason='macOS really does register the handler')
def test_the_open_folder_handler_is_a_no_op_where_there_is_nothing_to_register():
    "Windows and Linux get their folders through argv; asking for a handler must not raise."
    from leela.desktop import watch_open_events
    assert watch_open_events(lambda p: None) is None
