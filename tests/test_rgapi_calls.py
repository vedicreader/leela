"rgapi 0.2.3 swapped the first two arguments of fd, fda and fd_iter; Leela names them, so either order finds the files."
import asyncio
from pathlib import Path
import leela.blocks.fs.fs as fs

def _new_order(seen):
    "An fd_iter with 0.2.3's signature, (pattern, root), that walks `root`."
    def fd_iter(pattern=None, root='.', *a, **kw):
        seen.append(root)
        return iter(sorted(p for p in Path(root).rglob('*') if p.is_file()))
    return fd_iter

def test_the_walk_names_its_root(tmp_path, monkeypatch):
    (tmp_path/'a.py').write_text('x = 1\n')
    seen = []
    monkeypatch.setattr(fs, 'fd_iter', _new_order(seen))
    assert fs._walked([tmp_path], False, 100, None) == ([tmp_path/'a.py'], False)
    assert seen == [tmp_path], 'the folder went in as the pattern'

def test_hidden_files_name_root_and_pattern(tmp_path, monkeypatch):
    got = {}
    async def fda(pattern=None, root='.', *a, **kw):
        got.update(pattern=pattern, root=root)
        class Found(list): stop_reason = 'done'
        return Found()
    monkeypatch.setattr(fs, 'fda', fda)
    f = fs.Sandbox.__new__(fs.Sandbox)
    monkeypatch.setattr(fs.Sandbox, '_live', lambda self, ref=None: [tmp_path])
    monkeypatch.setattr(fs.Sandbox, 'walk_capped', lambda self, *a, **kw: ([], False))
    asyncio.run(f.hidden_files('x.*'))
    assert got == dict(pattern='x.*', root=[tmp_path])
