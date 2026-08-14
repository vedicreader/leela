import asyncio

from leela.core.envs import EnvStore


def test_env_store_reads_async_dockeasy_ops(monkeypatch):
    async def get(*args, **kwargs): return 'value'
    async def put(*args, **kwargs): return None
    monkeypatch.setattr('leela.core.envs._dockeasy', lambda: (get, put, get, put))
    assert EnvStore().get('TOKEN') == 'value'
    assert EnvStore().set('TOKEN', 'next')['key'] == 'TOKEN'


def test_env_store_reads_async_ops_inside_an_event_loop(monkeypatch):
    async def get(*args, **kwargs): return 'value'
    monkeypatch.setattr('leela.core.envs._dockeasy', lambda: (get, get, get, get))
    async def read(): return EnvStore().get('TOKEN')
    assert asyncio.run(read()) == 'value'
