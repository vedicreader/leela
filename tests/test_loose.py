import asyncio, os, stat, subprocess
import pytest
from fastcore.all import Path
from leela.blocks.agent.ai import WorkspaceHost
from leela.blocks.fs.fs import MAX_EDIT_BYTES, Sandbox, Unsafe, loose_refusal
from leela.blocks.fs.watch import Watcher
from leela.core.projects import loose_root
from leela.workspace import Workspace

def _loose_ws():
    (ws := Workspace()).add_root(loose_root(), loose=True)
    return ws

def _loose_fs():
    (sb := Sandbox()).add_root(loose_root(), loose=True)
    return sb

def test_an_admitted_file_is_written_in_place_and_never_moved_or_deleted(tmp_path):
    sb, f = _loose_fs(), tmp_path/'rc'
    for mode in (0o644, 0o755):
        f.write_text('a'); f.chmod(mode); sb.admit(f); sb.write(f, 'b')
        assert f.read_text() == 'b' and stat.S_IMODE(f.stat().st_mode) == mode, 'a save keeps the mode of the file it replaces'
    for op in (lambda: sb.rename(f, 'x'), lambda: sb.delete(f), lambda: sb.move(f, loose_root()), lambda: sb.copy(f, loose_root())):
        with pytest.raises(Unsafe): op()
    assert f.exists()
    (real := tmp_path/'real.toml').write_text('a'); (link := tmp_path/'link.toml').symlink_to(real)
    sb.admit(link); sb.write(link, 'new')
    assert link.is_symlink() and real.read_text() == 'new', 'the link survives a save and the target takes it'
    sb.revoke(f)
    with pytest.raises(Unsafe): sb.read(f)

def test_what_may_not_be_admitted(tmp_path):
    (ssh := tmp_path/'.ssh').mkdir(); (key := ssh/'id_ed25519').write_text('k')
    (big := tmp_path/'big.txt').write_text('x'); os.truncate(big, MAX_EDIT_BYTES + 1)
    sb = _loose_fs()
    for p in (tmp_path, key, big, tmp_path/'gone'):
        assert loose_refusal(p)
        with pytest.raises(Unsafe): sb.admit(p)
    with pytest.raises(Unsafe): Sandbox([tmp_path]).admit(tmp_path)

def test_a_loose_tab_admits_while_open_and_never_makes_home_the_project(tmp_path):
    home = tmp_path/'home'; home.mkdir(); subprocess.run(['git', 'init', '-q', str(home)], check=True)
    (rc := home/'.zshrc').write_text('x\n')
    ws = _loose_ws()
    ws.open(rc)
    assert ws.fs.covers(rc.resolve()) and ws.tab.path == str(rc.resolve())
    assert ws.cwd_for() == loose_root() and ws.project_repo == loose_root(), 'a git repo at home is not the project'
    ws.close()
    assert not ws.fs.admitted and not ws.fs.covers(rc.resolve())
    (other := tmp_path/'other.md').write_text('y')
    with pytest.raises(Unsafe): Workspace(roots=[home]).open(other)

def test_saved_loose_tabs_come_back_and_a_deleted_file_is_dropped(tmp_path):
    (a := tmp_path/'a.toml').write_text('a'); (b := tmp_path/'b.toml').write_text('b')
    ws = _loose_ws(); ws.open(a); ws.open(b)
    state = tmp_path/'loose.json'; ws.save(state)
    b.unlink()
    back = Workspace.load(path=state)
    assert [t.path for t in back.tabs] == [str(a.resolve())] and back.fs.covers(a.resolve())
    again = _loose_ws(); again._state_path = state
    assert again.reopen_saved_tabs() == 1 and [t.path for t in again.tabs] == [str(a.resolve())]

def test_the_agent_sees_loose_files_not_a_project(tmp_path):
    (rc := tmp_path/'.zshrc').write_text('x\n')
    ws = _loose_ws(); ws.open(rc)
    h = WorkspaceHost(ws)
    assert h.roots == [] and h.project == '' and h.loose_files == [str(rc.resolve())]
    prompt = ws.ai.system_prompt()
    assert f'Loose files: {rc.resolve()}' in prompt and str(loose_root()) not in prompt
    with pytest.raises(Unsafe): h.delete(rc)
    assert rc.exists()

def test_an_external_edit_to_a_loose_file_reaches_the_open_tab(tmp_path):
    (f := tmp_path/'rc').write_text('a')
    sb = _loose_fs(); f = sb.admit(f)
    async def run():
        w = Watcher(sb, step=50, poll=.05)
        q = w.subscribe()
        try:
            await asyncio.sleep(.3)
            while not q.empty(): q.get_nowait()
            (new := f.with_name('rc.new')).write_text('b'); os.replace(new, f)
            return await asyncio.wait_for(q.get(), 3)
        finally: w.close()
    paths, _ = asyncio.run(run())
    assert str(f) in paths, 'rename-over is an edit'

def _checkout(tmp_path):
    (proj := tmp_path/'proj').mkdir(); (proj/'.git').mkdir(); (a := proj/'a.md').write_text('a\n')
    return proj, a.resolve()

def test_a_link_out_of_a_folder_window_adds_no_folder(tmp_path, monkeypatch):
    "A definition, traceback or agent link in a folder window: the file is refused there, and no folder is added."
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.core import projects
    monkeypatch.setattr(projects, 'SESSION', tmp_path/'desktop.json')
    (mine := tmp_path/'mine').mkdir(); proj, a = _checkout(tmp_path)
    projects.note_folder(str(mine)); before = projects.session()
    ws = Workspace(roots=[mine])
    with TestClient(ide_app(ws)) as c: r = c.post('/tab/open', params={'path': str(a)})
    assert 'outside the open folders' in r.text and list(ws.fs.roots) == [mine.resolve()] and projects.session() == before

def test_the_agent_cannot_add_a_folder(tmp_path, monkeypatch):
    from shalya.tools import file_tools
    from leela.core import projects
    monkeypatch.setattr(projects, 'SESSION', tmp_path/'desktop.json')
    (mine := tmp_path/'mine').mkdir(); proj, a = _checkout(tmp_path)
    ws = Workspace(roots=[mine]); h = WorkspaceHost(ws)
    add = next(t for t in file_tools(h) if t.__name__ == 'add_root')
    assert 'could not open' in add(str(proj)) and list(ws.fs.roots) == [mine.resolve()] and projects.session()['folders'] == []

def test_a_loose_tab_offers_its_folder_until_not_now(tmp_path):
    from starlette.testclient import TestClient
    from leela.app import ide_app
    proj, a = _checkout(tmp_path)
    ws = _loose_ws()
    with TestClient(ide_app(ws)) as c:
        c.post('/tab/open', params={'path': str(a)})
        assert c.get('/tab/state').json()['offer'] == str(proj)
        assert c.post('/tab/offer/dismiss', params={'path': str(a)}).json()['ok']
        assert 'offer' not in c.get('/tab/state').json() and list(ws.fs.roots) == [loose_root()]
    ws.close(); ws.open(a)
    assert ws.offers == {str(a): str(proj)}, 'opened again, it offers again'
    ws.close()
    assert not ws.offers, 'closing the tab drops its offer'
