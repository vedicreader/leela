"""Shared fixtures for browser screenshot scripts."""

from __future__ import annotations
import asyncio
from unittest.mock import AsyncMock

from leela.kernels import ExecOutcome, KernelPool
from tests.fakemodel import Step

NB = '''{
 "cells": [
  {"cell_type": "markdown", "id": "m1", "metadata": {},
   "source": ["## Approvals\\n\\nAsk where write approval is handled."]},
  {"cell_type": "code", "id": "c1", "metadata": {}, "outputs": [], "execution_count": null,
   "source": ["# open while the agent streams"]}
 ],
 "metadata": {"kernelspec": {"name": "python3", "language": "python", "display_name": "Python 3"}},
 "nbformat": 4, "nbformat_minor": 5
}'''

STEPS = [
    Step(tool=('search_code', {'query': 'approval'})),
    Step(text='Approvals queue through the web HITL path; a refusal returns to the model.'),
]


def fake_kernels():
    "Stub KernelPool so screenshot scripts never launch a real ipykernel."
    async def _get(self, key, **kw):
        k = self.kernels.get(key)
        if k is None:
            k = type('K', (), {})()
            k.alive = True; k.base = 'http://127.0.0.1:9'; k.pid = 1
            k.boot_error = None; k.token = None; k.kernel_kind = 'ipykernel'
            k.api = AsyncMock(return_value={'groups': []})
            k.execute = AsyncMock(return_value=ExecOutcome(ok=True, execution_count=1, outputs=[]))
            k.complete = AsyncMock(return_value={'from': 0, 'matches': []})
            k.inspect_obj = AsyncMock(return_value='')
            k.names = AsyncMock(return_value=[])
            k.interrupt = AsyncMock(); k.restart = AsyncMock(); k.shutdown = AsyncMock()
            self.kernels[key] = k
        return k
    KernelPool.get = _get
    KernelPool.peek = lambda self, key: self.kernels.get(key)
    KernelPool.close_all = lambda self: asyncio.sleep(0)
