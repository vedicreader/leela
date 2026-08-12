"""Integrative feature-block fixtures.

Keeps Playwright/browser evidence and agent turns cheap: kernel I/O is faked, and when a
block needs a model reply it seeds Rishi's `CachedChat` oneshot cache instead of calling a
live backend.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from leela.kernels import ExecOutcome, KernelPool
from leela.workspace import Workspace

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _isolate_vault(monkeypatch, tmp_path_factory):
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path_factory.mktemp('vault') / 'vault.db'))
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')


class _FakeKernel:
    alive = True
    base = 'http://127.0.0.1:9'
    pid = 1
    boot_error = None
    token = None
    kernel_kind = 'ipykernel'

    async def api(self, path, params=None, timeout=15):
        return {'groups': []} if str(path).endswith('/api/rows') else None

    async def execute(self, code, **kw):
        return ExecOutcome(ok=True, execution_count=1, outputs=[])

    async def complete(self, code, pos): return {'from': 0, 'matches': []}
    async def inspect_obj(self, code, pos, detail=0): return ''
    async def names(self, scope='live', profile='full'): return []
    async def interrupt(self): pass
    async def restart(self): pass
    async def shutdown(self): pass


@pytest.fixture
def ws(tmp_path, monkeypatch):
    "A disposable workspace whose kernels never leave the test process."
    async def _get(self, key, **kw):
        return self.kernels.setdefault(key, _FakeKernel())
    monkeypatch.setattr(KernelPool, 'get', _get)
    monkeypatch.setattr(KernelPool, 'peek', lambda self, key: self.kernels.get(key))
    monkeypatch.setattr(KernelPool, 'close_all', lambda self: asyncio.sleep(0))
    (tmp_path / 'readme.md').write_text('# block fixture\n')
    return Workspace(roots=[tmp_path], port=8000)


def seed_oneshot(cache_dir, prompt, answer, model='scripted/model', sp='', think=None, max_tokens=None):
    """Record a `CachedChat.oneshot` reply so block tests never need a live model.

    Uses the same keying as Rishi's RecordCache: a miss would raise unless RISHI_RECORD_CHAT
    is set, so tests that only need a canned reply seed the cache ahead of time.
    """
    from rishi import CachedChat
    chat = CachedChat(model=model, path=cache_dir, record=True, sp=sp)
    key = chat._key('oneshot', prompt, sp, think, max_tokens, hist=False)
    chat.rec.cache[key] = ('ok', answer)
    return key


def cached_chat(cache_dir, model='scripted/model', sp='', tools=None):
    "A CachedChat that only replays; misses fail closed."
    from rishi import CachedChat
    return CachedChat(model=model, path=cache_dir, record=False, sp=sp, tools=tools)
