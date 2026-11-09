import asyncio, json

from leela.app import ide_app
from leela.blocks.fs.fs import Sandbox
from leela.blocks.fs.watch import Watcher


def _first(w, announce, typ):
    async def run():
        q = w.subscribe()
        try:
            assert await w.settled()
            await asyncio.to_thread(announce)
            while True:
                got = await asyncio.wait_for(q.get(), 5)
                if isinstance(got, typ): return got
        finally: w.close()
    return asyncio.run(run())


def test_a_path_tab_is_announced_as_before(tmp_path):
    w = Watcher(Sandbox([tmp_path]), step=50)
    assert _first(w, lambda: w.announce(tmp_path / 'a.py'), str) == str(tmp_path / 'a.py')


def test_a_tab_with_no_path_is_announced_to_every_subscriber(tmp_path):
    w = Watcher(Sandbox([tmp_path]), step=50)
    assert _first(w, lambda: w.announce_tab('learn_walk', '["vault", "walk"]'), dict) == dict(kind='learn_walk', ref='["vault", "walk"]')


def test_the_page_receives_the_tab_only_form_of_the_opened_event(ws):
    ws.fs_watch.poll = .05
    app, got = ide_app(ws), []
    async def run():
        sent = asyncio.Event()
        async def send(m):
            if m['type'] == 'http.response.body' and b'event: opened' in m.get('body', b''): got.append(m['body']); sent.set()
        scope = {'type': 'http', 'method': 'GET', 'path': '/fs/events', 'raw_path': b'/fs/events', 'query_string': b'',
                 'headers': [(b'host', b'127.0.0.1')], 'scheme': 'http', 'server': ('127.0.0.1', 80), 'client': ('127.0.0.1', 1),
                 'root_path': '', 'http_version': '1.1'}
        never, asked = asyncio.Event(), []
        async def receive():
            if not asked: asked.append(1); return {'type': 'http.request', 'body': b'', 'more_body': False}
            await never.wait()
        task = asyncio.create_task(app(scope, receive, send))
        try:
            await asyncio.sleep(.3)
            await asyncio.to_thread(ws.fs_watch.announce_tab, 'learn_walk', '["vault", "walk"]')
            await asyncio.wait_for(sent.wait(), 5)
        finally:
            task.cancel()
            ws.fs_watch.close()
    asyncio.run(run())
    assert json.loads(got[0].decode().split('data: ', 1)[1]) == dict(kind='learn_walk', ref='["vault", "walk"]')
