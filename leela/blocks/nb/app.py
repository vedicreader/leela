"The notebook as routes: cells, runs, saves, and the notebook debugger."

from __future__ import annotations

import asyncio, base64, json, queue, sys, threading

from fasthtml.common import StreamingResponse
from fastcore.all import first
from starlette.routing import WebSocketRoute

from ... import errstr
from pathlib import Path

from ...core.text import did_you_mean
from ...core.session import MAX_BODY
from ...core.web import NOT_OBJECT, fail, json_obj, off_loop, sse
from ..fs.fs import NotText, decoded
from ..agent.turns import activity_changes, edit_diffs, tool_schemas
from ..debug.debug import notebook_state_ui, paused_kernel
from .scrub import scrub_names, scrub_why
from .scrubrun import FIRST as SCRUB_FIRST, LIMIT as SCRUB_LIMIT, outputs_of, parse_snapshot, snapshot_code, worker_for
from ..tabs.app import disk_version as _disk_version
from .nb import Cell, Notebook, OutFeed, RunningCellError, capped, cell_extras, inline_values, restore_exercise, run_watched, src_hash, take_seq
from .lesson import GUIDE_NEEDS, GUIDE_STREAM_NEEDS, EnvGone, check_anchors, check_demo, filed_picks, guide_board, lock, prediction_filing, record_card, record_prediction
from .exercise import JUDGE, Refused, check_cell, exercise_meta, public_verdict
from . import presentation

__all__ = ['CAPS', 'CommRelay', 'connect']

CAPS = ('fs', 'journal', 'inline_ai', 'tab', 'pending_approval', 'docs', 'debug', 'running', 'memory', 'vaults')
#: Seconds between SSE comments on a silent run stream, well inside the page's own silence limit.
KEEPALIVE = 15

#: Seconds between two output messages on a run stream. The page draws each one, and a cell can print thousands of lines a second.
FLUSH = .075
CONFLICT = 'save_conflict'

def conflict(msg, cells=()):
    "Every save conflict's answer: the page offers keep, merge, overwrite and load, with the other side of each cell that clashed."
    return fail(msg, 409, kind=CONFLICT, cells=[{'id': c.id, 'source': c.source, 'cell_type': c.cell_type} for c in cells])

def _labels(nb, cells):
    at = {c.id: j for j, c in enumerate(nb.cells)}
    return ', '.join(f'cell {at[c.id] + 1}' if c.id in at else 'a deleted cell' for c in cells)

#: Messages one page's widget socket holds while it falls behind; past it the page reloads widget state instead.
COMM_BACKLOG = 2000
#: Seconds between checks of which kernel a notebook's widget socket follows: a run starts one, a picker switches it.
COMM_WATCH = .2

class CommRelay:
    "One page's widget socket: the kernel it follows, what waits to go to the page, and the page's own message ids."
    def __init__(self): self.q, self.alias, self.k, self.dropped = asyncio.Queue(), {}, False, 0
    def put(self, m):
        if self.q.qsize() >= COMM_BACKLOG:
            # Kernel messages go; what says the kernel's state, or answers a page's question, stays.
            kept = [x for x in (self.q.get_nowait() for _ in range(self.q.qsize())) if 'header' not in x]
            for x in [*kept, {'type': 'resync'}]: self.q.put_nowait(x)
            if 'header' in m: return
        self.q.put_nowait(m)
    def follow(self, k):
        "Follow `k`, telling the page: `waiting` with no kernel, `unsupported` without comms, else `ready`."
        if k is self.k: return self.resync()
        if self.k is not False and self.k is not None:
            self.close()
            self.put({'type': 'kernel_gone'})
        self.k = k
        if k is None: return self.put({'type': 'waiting'})
        if not getattr(k, 'comms', False): return self.put({'type': 'unsupported'})
        self.dropped = k.feed.dropped
        k.subscribe(self.put)
        self.put({'type': 'ready', 'kernel': f'{id(k):x}'})
    def resync(self):
        "Kunda drops the oldest messages for a slow subscriber; the page then reloads every widget's state."
        if not getattr(self.k, 'comms', False) or self.k.feed.dropped == self.dropped: return
        self.dropped = self.k.feed.dropped
        self.put({'type': 'resync'})
    def close(self):
        if (off := getattr(self.k, 'unsubscribe', None)): off(self.put)
    def send(self, d):
        "Relay one comm message from the page, remembering the kernel's msg_id for it as the page's."
        if not getattr(self.k, 'comms', False): raise RuntimeError('no kernel relays widget messages for this notebook')
        mid = self.k.comm_send(d['comm_id'], d.get('data'), [base64.b64decode(b) for b in d.get('buffers') or ()],
                               d.get('msg_type') or 'comm_msg', d.get('target_name'), d.get('metadata'))
        self.alias[mid] = d.get('id') or mid
        if len(self.alias) > COMM_BACKLOG: del self.alias[next(iter(self.alias))]
    def frame(self, m):
        "`m` as JSON for the page: buffers in base64, and a reply to the page's own message under the page's id."
        if 'header' not in m: return json.dumps(m)
        ph = m.get('parent_header') or {}
        if (mine := self.alias.get(ph.get('msg_id'))): ph = {**ph, 'msg_id': mine}
        return json.dumps({**m, 'parent_header': ph, 'buffers': [base64.b64encode(b).decode() for b in m.get('buffers') or ()]}, default=str)

def connect(app, ctx):
    rt = app.route
    ws, store, dbgstate = ctx.session, ctx.docs, ctx.debug
    docs, run_locks = store.docs, store.run_locks
    buffers, buffer_bases, doc_versions = store.buffers, store.bases, store.versions
    running_cells = ctx.running.cells
    lesson_lock = asyncio.Lock()
    def run_owner(d): return store.owner(d.get('path'))
    def by_id(nb, d):
        "Turn `id`, `ids` and `target_id` ('' for the end) into the positions they name now; a message when one has gone."
        at = {c.id: j for j, c in enumerate(nb.cells)}
        if d.get('id'):
            if d['id'] not in at: return 'that cell is no longer in the notebook'
            d['i'] = at[d['id']]
        if (t := d.get('target_id')) is not None:
            if t and t not in at: return 'the cell to move before is no longer in the notebook'
            d['target'] = at[t] if t else len(nb.cells)
        if d.get('ids') is not None and d.get('op') != 'heading':
            if not all(x in at for x in d['ids']): return 'a selected cell is no longer in the notebook'
            d['indices'] = [at[x] for x in d['ids']]
    def took(nb, d, cid, i, tab):
        "Put a run's `source` on its cell; the conflict answer when another window changed that cell since this page saw it."
        if 'source' not in d: return None
        row = {'id': cid, 'i': i, 'source': d['source'], 'seq': d.get('seq'), **{k: d[k] for k in ('base', 'page') if k in d}}
        if not (clash := nb.take_sources([row], store.seqs_for(tab))): return None
        held = first(c for c in nb.cells if c.id == clash[0])
        return conflict('another window changed this cell: ' + _labels(nb, [held] if held else []) + '. Review it before running.', [held] if held else [])
    def note_origin(tab, cell): ws.origins.cell(cell, (tab.path or tab.title) if tab else '')
    def place(nb, c): return next((j for j, x in enumerate(nb.cells) if x is c), -1)
    def dbg(method=None): return paused_kernel(dbgstate, method)
    def debug_ui(state): return notebook_state_ui(dbgstate, ctx.fs, state)
    comm_relays = {}    # notebook key -> the `CommRelay` of every page holding a widget socket on it
    async def runtime_for(tab=None):
        "The tab's runtime, started if need be. Its widget sockets follow it before any cell runs, so no `comm_open` goes unheard."
        k = await ws.runtime(tab)
        for r in comm_relays.get(store.key(tab), ()): r.follow(k if getattr(k, 'alive', False) else None)
        return k
    async def explain(k, err, scope='live'):
        "A kernel error with a `did you mean` appended, when a near-miss name exists."
        if not (err and 'is not defined' in err): return err
        return did_you_mean(err, await k.names(scope)) if k else err

    @rt('/nb/run')
    async def nb_run(req):
        "Run one cell against its submitting tab's kernel and return its outputs."
        d = await req.json()
        owner_tab, nb, run_lock = run_owner(d)
        i = int(d.get('i', 0))
        if nb is None: return fail('no notebook open')
        if not (0 <= i < len(nb)) or (d.get('id') and nb[i].id != d['id']):
            return fail('that cell is no longer at this position', 409)
        c = nb[i]
        if (no := took(nb, d, c.id, i, owner_tab)): return no
        async with run_lock:
            if place(nb, c) < 0: return fail('that cell is no longer in the notebook', 409)
            try: k = await runtime_for(owner_tab)
            except EnvGone as e: return fail(str(e), 409)
            owner_tab.running += 1
            try: c, lost = await run_watched(nb, c, k)
            finally: owner_tab.running = max(0, owner_tab.running - 1)
            if c.cell_type == 'code': lock(c, d.get('prediction', ''), d.get('confidence'))
        file_after_run(owner_tab)
        note_origin(owner_tab, c)
        if owner_tab: owner_tab.dirty = True
        rows, result = await cell_extras(k, c)
        return {'ok': not c.has_error, 'lost': lost, 'reason': getattr(c, '_reason', None), 'i': place(nb, c), 'id': c.id, 'cell': c.dict(), 'result': result,
                'inline': inline_values(c.source, (rows or {}).get('groups', []), c.outputs, result)}
    def file_after_run(tab):
        "When the kernel of a lesson goes idle, file the run result beside it, off the loop. Filed once for each content; the learn block's sweep tries again after a failure."
        from .lesson import file_result_in, note_unfiled, result_sig
        if not (tab and tab.path and (sig := result_sig(tab.path))): return
        async def go():
            try: await off_loop(file_result_in, ctx, tab.path)
            except Exception as e:
                if note_unfiled(tab.path, sig, e): print(f'  run result not filed: {errstr(e)}')
        asyncio.ensure_future(go())
    @rt('/nb/run/stream')
    async def nb_run_stream(req):
        "Run a cell while streaming its evolving Jupyter outputs as SSE."
        d = await req.json()
        owner_tab, nb, run_lock = run_owner(d)
        i = int(d.get('i', 0))
        if nb is None: return fail('no notebook open')
        if not (0 <= i < len(nb)) or (d.get('id') and nb[i].id != d['id']):
            return fail('that cell is no longer at this position', 409)
        c = nb[i]
        if (no := took(nb, d, c.id, i, owner_tab)): return no
        # The notebook about to run is one stat; its tree is a walk, and that is once per root. `save: false` (a presentation) writes neither.
        if d.get('save') is not False:
            if ws.initialize_notebook(getattr(owner_tab, 'path', None), nb):
                doc_versions[owner_tab.path] = _disk_version(owner_tab.path)
            await off_loop(ws.initialize_empty_notebooks, ws.cwd_for(owner_tab))
        await run_lock.acquire()
        try: k = await runtime_for(owner_tab)
        except BaseException as e:
            run_lock.release()
            if isinstance(e, EnvGone): return fail(str(e), 409)
            raise
        if place(nb, c) < 0:
            run_lock.release()
            return fail('that cell is no longer in the notebook', 409)
        wake, feed = asyncio.Event(), OutFeed(c)
        def emitted(_i, _output): wake.set()
        async def run():
            _, lost = await run_watched(nb, c, k, on_output=emitted)
            if c.cell_type == 'code': lock(c, d.get('prediction', ''), d.get('confidence'))
            file_after_run(owner_tab)
            note_origin(owner_tab, c)
            if owner_tab: owner_tab.dirty = True
            rows, result = await cell_extras(k, c)
            return {'ok': not c.has_error, 'lost': lost, 'reason': getattr(c, '_reason', None), 'i': place(nb, c), 'id': c.id, 'cell': c.dict(), 'result': result,
                    'inline': inline_values(c.source, (rows or {}).get('groups', []), c.outputs, result)}
        # The run outlives its stream: a page that lost the stream asks `/nb/run/state` for the outcome.
        run_key = ((owner_tab.path or owner_tab.title) if owner_tab else '', c.id)
        def finished(_):
            if owner_tab: owner_tab.running = max(0, owner_tab.running - 1)
            if running_cells.get(run_key, (None,))[1:] == (task,): running_cells.pop(run_key, None)
            run_lock.release()
            wake.set()
        if owner_tab: owner_tab.running += 1
        task = asyncio.create_task(run())
        task.add_done_callback(finished)
        running_cells[run_key] = (k, task)
        async def events():
            # At most one message per `FLUSH`, each only what changed since the last; `done` carries the whole cell.
            loop, sent = asyncio.get_running_loop(), 0.
            try:
                while not task.done():
                    try: await asyncio.wait_for(wake.wait(), KEEPALIVE)
                    except TimeoutError:
                        yield ': keep-alive\n\n'
                        continue
                    await asyncio.sleep(max(0, sent + FLUSH - loop.time()))
                    wake.clear()
                    if task.done(): break
                    if (ops := feed.ops()):
                        sent = loop.time()
                        yield sse('output', {'i': place(nb, c), 'id': c.id, 'n': len(c.outputs), 'ops': ops})
                yield sse('done', await task)
            except Exception as e:
                yield sse('error', {'text': errstr(e)})
        return StreamingResponse(events(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
    def scrub_python(tab):
        "The interpreter of a tab's kernel, found without starting it."
        try: return str(ws.user_python(ws.cwd_for(tab)))
        except Exception: return sys.executable
    @rt('/nb/scrub/run')
    async def nb_scrub_run(req):
        "One tick of a live scrub: run a cell that passes the scrub check in the notebook's worker process, on a copy of the plain data it reads. The kernel is not run in, interrupted or restarted."
        d = await req.json()
        if not isinstance(d, dict) or not isinstance(d.get('source'), str): return fail('source must be text', 400)
        src = d['source']
        if (why := scrub_why(src)): return {'ok': False, 'refused': why}
        owner_tab, nb, run_lock = run_owner(d)
        c = first(x for x in (nb or []) if x.id == d.get('id'))
        if c is None or c.cell_type != 'code': return fail('that cell is no longer in the notebook', 409)
        if not (c.extra.get('scrub') or {}).get('live'): return {'ok': False, 'off': True}
        snap = {}
        if (names := scrub_names(src)):
            if run_lock.locked(): return {'ok': False, 'busy': True}
            async with run_lock:
                try: k = await runtime_for(owner_tab)
                except EnvGone as e: return fail(str(e), 409)
                r = await k.execute(snapshot_code(names), store_history=False, timeout=3)
            got = parse_snapshot(r.outputs)
            if got is None: return {'ok': False, 'refused': 'The kernel could not hand over the data this cell reads.'}
            if 'bad' in got: return {'ok': False, 'refused': f"This cell uses {got['bad']} from another cell, which is not plain data ({got['why']})."}
            snap = got['ok']
        w = worker_for(store.key(owner_tab), scrub_python(owner_tab))
        try: res = await w.run(src, snap, SCRUB_FIRST if d.get('first') else SCRUB_LIMIT)
        except Exception as e: return {'ok': False, 'died': True, 'note': errstr(e)}
        if 'refused' in res or 'slow' in res or 'memory' in res or 'died' in res: return {'ok': False, **res}
        return {'ok': not res.get('error'), 'outputs': outputs_of(res)}
    @rt('/nb/scrub/warm')
    async def nb_scrub_warm(req):
        "Start the notebook's scrub worker before a scrub needs it, so its first tick does not count the start."
        owner_tab, nb, _ = run_owner(await req.json())
        if nb is None: return fail('no notebook open')
        try: await worker_for(store.key(owner_tab), scrub_python(owner_tab)).start()
        except Exception as e: return fail(errstr(e))
        return {'ok': True}
    @rt('/nb/run/state')
    async def nb_run_state(req):
        "Whether one cell's run is still going, and the cell as the server holds it, for a page whose run stream ended early."
        d = await req.json()
        owner_tab, nb, _ = run_owner(d)
        c = first(x for x in (nb or []) if x.id == d.get('id'))
        if c is None: return {'ok': True, 'running': False, 'cell': None}
        item = running_cells.get(((owner_tab.path or owner_tab.title) if owner_tab else '', c.id))
        return {'ok': True, 'running': bool(item) and not item[1].done(), 'cell': c.dict()}
    @rt('/exercise/check')
    async def exercise_check(req):
        "Run an exercise's code cell and then its checks in the tab's kernel; the page gets the public verdict, never a hidden test."
        d = await req.json()
        owner_tab, nb, run_lock = run_owner(d)
        i = int(d.get('i', 0))
        if nb is None: return fail('no notebook open')
        if not (0 <= i < len(nb)) or (d.get('id') and nb[i].id != d['id']):
            return fail('that cell is no longer at this position', 409)
        c = nb[i]
        if not exercise_meta(c): return fail(JUDGE['not_exercise'], 400)
        if not take_seq(store.seqs_for(owner_tab), c.id, d.get('seq')): return fail(JUDGE['stale'], 409)
        if (no := took(nb, d, c.id, i, owner_tab)): return no
        try: verdict = await check_cell(nb, c, run_lock, lambda: runtime_for(owner_tab), ws.jobs)
        except (Refused, EnvGone) as e: return fail(str(e), 409)
        note_origin(owner_tab, c)
        if owner_tab: owner_tab.dirty = True
        if (now := first(x for x in nb if x.id == c.id)) is None: return fail('that cell is no longer in the notebook', 409)
        return {**public_verdict(verdict), 'cell': now.dict()}
    @rt('/nb/debug/stream')
    async def nb_debug_stream(req):
        "Debug one code cell through ipykernel's Jupyter Debug Protocol."
        d = await req.json()
        owner_tab, nb, run_lock = run_owner(d)
        i = int(d.get('i', 0))
        if nb is None or not (0 <= i < len(nb)):
            return fail(f'no cell {i}')
        if d.get('id') and nb[i].id != d['id']:
            return fail('that cell is no longer at this position', 409)
        c = nb[i]
        if c.cell_type != 'code': return fail('only code cells can be debugged')
        if (no := took(nb, d, c.id, i, owner_tab)): return no
        await run_lock.acquire()
        try: k = await runtime_for(owner_tab)
        except BaseException as e:
            run_lock.release()
            if isinstance(e, EnvGone): return fail(str(e), 409)
            raise
        if getattr(k, 'kernel_kind', None) != 'ipykernel' or not hasattr(k, 'debug_start'):
            run_lock.release()
            return fail('cell debugging requires an ipykernel runtime')
        if dbgstate.paused:
            run_lock.release()
            return fail('a debugger session is already active', 409)
        breakpoints = d.get('breakpoints') or []
        dbgstate.kernel, dbgstate.origin_path, dbgstate.cell_id = k, owner_tab.path, c.id
        async def events():
            q = asyncio.Queue()
            c.clear(); c.running = True
            if owner_tab: owner_tab.running += 1
            started = asyncio.get_running_loop().time()
            try:
                notebook_sources = [(cell.id, cell.source) for cell in nb.cells if cell.cell_type == 'code']
                verified = await k.debug_start(c.source, breakpoints, notebook_sources)
                yield sse('ready', {'i': place(nb, c), 'id': c.id, 'breakpoints': verified})
                def output(_out): q.put_nowait(('output', None))
                def debug(event): q.put_nowait(('debug', event))
                task = asyncio.create_task(k.execute(c.source, on_output=output, on_debug=debug))
                while not task.done() or not q.empty():
                    try: kind, value = await asyncio.wait_for(q.get(), .12)
                    except asyncio.TimeoutError: continue
                    if kind == 'output':
                        continue
                    if value.get('event') == 'stopped':
                        state = await k.debug_state((value.get('body') or {}).get('threadId'))
                        yield sse('stopped', debug_ui(state))
                    elif value.get('event') == 'continued':
                        yield sse('continued', value.get('body') or {})
                result = await task
                c.outputs, c.execution_count = capped(result.outputs), result.execution_count
                c.execution_ms = (asyncio.get_running_loop().time() - started) * 1000
                c.fresh, c.output_hash = True, src_hash(c.source)
                note_origin(owner_tab, c)
                if owner_tab: owner_tab.dirty = True
                yield sse('done', {'ok': result.ok, 'i': place(nb, c), 'id': c.id, 'cell': c.dict(),
                                    'error': result.error})
            except Exception as e:
                yield sse('error', {'text': errstr(e)})
            finally:
                c.running = False
                owner_tab.running = max(0, owner_tab.running - 1)
                try: await k.debug_stop()
                except Exception: pass
                if dbgstate.kernel is k: dbgstate.clear()
                run_lock.release()
        return StreamingResponse(events(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
    @rt('/nb/debug/state')
    async def nb_debug_state(frame_id: int = 0):
        if (k := dbg('debug_state')) is None: return fail('no ipykernel debugger is active')
        try:
            state = await k.debug_state(frame_id=frame_id or None)
            return debug_ui(state)
        except Exception as e: return fail(e)
    @rt('/nb/debug/source')
    async def nb_debug_source(frame_id: int):
        "Source for a stack frame outside the workspace, addressed by trusted frame id, never a client path."
        if (k := dbg()) is None: return fail('no ipykernel debugger is active')
        try:
            state = await k.debug_state(frame_id=frame_id)
            frame = first(f for f in state.get('frames', []) if f.get('id') == frame_id)
            if frame is None: return fail('debug frame is no longer available')
            source = frame.get('source') or {}
            reply = await k.debug_request('source', {'source': source,
                                                      'sourceReference': source.get('sourceReference', 0)})
            return {'content': reply.get('body', {}).get('content', ''), 'line': frame.get('line'),
                    'path': source.get('path', ''), 'name': frame.get('name', '')}
        except Exception as e: return fail(e)
    @rt('/nb/debug/variables')
    async def nb_debug_variables(reference: int):
        if (k := dbg('debug_variables')) is None: return fail('no ipykernel debugger is active')
        try: return {'variables': await k.debug_variables(reference)}
        except Exception as e: return fail(e)
    @rt('/nb/debug/evaluate')
    async def nb_debug_evaluate(req):
        d, k = await req.json(), dbg('debug_evaluate')
        if k is None: return fail('no ipykernel debugger is active')
        try:
            body = await k.debug_evaluate(d.get('code', ''), d.get('frame_id'))
            return {'ok': True, **body}
        except Exception as e: return fail(e)
    @rt('/nb/debug/control')
    async def nb_debug_control(req):
        d, k = await req.json(), dbg('debug_control')
        if k is None: return fail('no ipykernel debugger is active')
        try:
            await k.debug_control(d.get('command', ''), d.get('thread_id'))
            return {'ok': True, 'command': d.get('command')}
        except Exception as e: return fail(e)
    @rt('/nb/debug/stop')
    async def nb_debug_stop():
        if (k := dbg('debug_stop')) is None: return fail('no ipykernel debugger is active')
        try:
            await k.debug_stop()
            await k.interrupt()
            return {'ok': True}
        except Exception as e: return fail(e)
    @rt('/nb/ask')
    async def nb_ask(req):
        "Run a prompt cell: the assistant answers, with the notebook above it as context."
        d = await req.json()
        owner_tab, nb, _ = run_owner(d)
        if nb is None: return fail('no notebook open')
        if (gone := by_id(nb, d)): return fail(gone, 409)
        i = int(d.get('i', 0))
        if not (0 <= i < len(nb)): return fail(f'no cell {i}')
        asked = nb[i]
        if (no := took(nb, d, d.get('id'), i, owner_tab)): return no
        try: c = await off_loop(ws.ask_cell, nb, asked)
        except Exception as e: return fail(e)
        owner_tab.dirty = True
        a = ctx.inline_ai
        return {'ok': a.ready, 'i': place(nb, asked), 'id': asked.id, 'cell': c.dict(), 'note': a.note,
                'problems': a.problems,
                'cells': [x.dict() for x in nb.cells],
                'activity': a.activity.rows(mark=a.activity._mark),
                'edits': edit_diffs(a)}
    @rt('/nb/ask/stream')
    async def nb_ask_stream(req):
        "Stream a prompt cell into its own reply area as markdown arrives."
        d = await req.json()
        owner_tab, nb, _ = run_owner(d)
        if nb is None: return fail('no notebook open')
        if (gone := by_id(nb, d)): return fail(gone, 409)
        i = int(d.get('i', 0))
        if not (0 <= i < len(nb)): return fail(f'no cell {i}')
        if (no := took(nb, d, d.get('id'), i, owner_tab)): return no
        asked = nb[i]
        asked.running = True
        owner_tab.running += 1
        a = ctx.inline_ai
        mine = {'cell_id': asked.id}
        async def events():
            import queue as _q
            out, done = _q.Queue(), object()
            def pump():
                try:
                    for chunk in ws.ask_cell_stream(nb, asked): out.put(('chunk', chunk))
                except Exception as e: out.put(('error', errstr(e)))
                finally: out.put((done, None))
            task = asyncio.get_running_loop().run_in_executor(None, pump)
            approval_id, activity_versions = None, {}
            def changed_activity(): return activity_changes(a, activity_versions)
            try:
                while True:
                    try: kind, value = await off_loop(out.get, True, 0.25)
                    except _q.Empty: kind = value = None
                    pending = ctx.pending_approval
                    if pending is not None and pending.id != approval_id:
                        approval_id = pending.id
                        proposal = {**pending.dict(), 'schemas': tool_schemas(a), **mine}
                        yield sse('approval', proposal)
                    for row in changed_activity(): yield sse('activity', {**row, **mine})
                    if await req.is_disconnected():
                        a.cancel()
                        return
                    if kind is None: continue
                    if kind is done:
                        for row in changed_activity(): yield sse('activity', {**row, **mine})
                        break
                    yield sse(kind, {'text': value, 'id': asked.id, **mine})
                await task
                yield sse('done', {'ok': a.ready, 'i': place(nb, asked), 'id': asked.id, **mine, 'cell': asked.dict(), 'note': a.note,
                                    'usage': a.turn_use.dict(), 'usage_label': repr(a.turn_use),
                                    'problems': a.problems,
                                    'cells': [x.dict() for x in nb.cells],
                                    'activity': a.activity.rows(mark=a.activity._mark),
                                    'edits': edit_diffs(a)})
            finally:
                asked.running = False
                owner_tab.running = max(0, owner_tab.running - 1)
                owner_tab.dirty = True
        return StreamingResponse(events(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
    @rt('/nb/edit')
    async def nb_edit(req):
        "Structural edits: insert / delete / move / type / split / merge, to the notebook `path` names, else the active one."
        d = await req.json()
        tab, nb, _ = run_owner(d)
        if nb is None: return fail('that notebook is no longer open' if d.get('path') else 'no notebook open')
        clash = nb.take_sources(d.get('sources', []), store.seqs_for(tab))
        tab.dirty = tab.dirty or nb.dirty or bool(clash)
        if (gone := by_id(nb, d)): return fail(gone, 409)
        op, i = d.get('op'), int(d.get('i', 0))
        if op == 'insert': nb.insert(i, Cell(source=d.get('source', ''), cell_type=d.get('cell_type', 'code')))
        elif op == 'delete': nb.delete(i)
        elif op == 'delete_many': nb.delete_many(d.get('indices') or [i])
        elif op == 'move': i = nb.move(i, int(d.get('d', 1)))
        elif op == 'move_many': i = nb.move_many(d.get('indices') or [i], int(d.get('target', i)))
        elif op == 'type':
            nb.cycle_type(i) if d.get('cycle') else nb.set_type(i, d.get('cell_type', 'code'))
        elif op == 'split': nb.split(i, int(d.get('offset', 0)))
        elif op == 'split_symbols': nb.split_symbols(i)
        elif op == 'duplicate': nb.duplicate(i)
        elif op in ('paste', 'paste_many'):
            raws = d.get('cells') if op == 'paste_many' else [d.get('cell')]
            if not isinstance(raws, list) or not raws or not all(isinstance(raw, dict) for raw in raws):
                return fail('cell clipboard is empty')
            fields = Cell.__dataclass_fields__
            try: pasted = [Cell(**{name: raw[name] for name in fields if name in raw}) for raw in raws]
            except (TypeError, ValueError) as e: return fail(f'invalid cell clipboard: {e}')
            held = {c.id: c for c in nb.cells}
            for raw, n in zip(raws, pasted): restore_exercise(n, held.get(raw.get('id')))
            nb.paste_many(i, pasted)
        elif op == 'merge_above': nb.merge(i - 1) if i > 0 else None
        elif op == 'merge_below': nb.merge(i)
        elif op == 'clear_cell': nb.clear_cell(i)
        elif op in ('undo', 'redo'):
            try: at = getattr(nb, op)()
            except RunningCellError as e: return fail(str(e), 409)
            if at is None: return fail(f'no cell operation to {op}')
        elif op == 'merge': nb.merge(i)
        elif op == 'source':
            if (no := took(nb, {**d, 'source': d.get('source', '')}, nb[i].id, i, tab)): return no
        elif op == 'context':
            mode = str(d.get('mode') or 'auto')
            if mode not in ('auto', 'keep', 'discard'): return fail('context mode must be auto, keep or discard')
            nb._checkpoint(i)
            nb[i].context_mode = mode
            nb.dirty = True
        elif op == 'lesson_confidence':
            confidence = d.get('confidence')
            if nb[i].cell_type != 'markdown' or nb[i].extra.get('lesson', {}).get('role') != 'prediction':
                return fail('Confidence belongs to a prediction cell.')
            if confidence is not None and (type(confidence) is not int or confidence not in (10, 30, 50, 70, 90)):
                return fail('Confidence must be 10, 30, 50, 70, 90 or None.')
            nb._checkpoint(i)
            if confidence is None: nb[i].extra['lesson'].pop('confidence', None)
            else: nb[i].extra['lesson']['confidence'] = confidence
            nb.dirty = True
        elif op == 'scrub_live':
            if nb[i].cell_type != 'code': return fail('Live scrub belongs to a code cell.')
            nb._checkpoint(i)
            if d.get('on'): nb[i].extra['scrub'] = {'live': True}
            else: nb[i].extra.pop('scrub', None)
            nb.dirty = True
        elif op == 'slide':
            try: nb.set_slide(d.get('indices') or [i], str(d.get('type') or 'none'))
            except (TypeError, ValueError) as e: return fail(e)
        elif op == 'heading':
            # Ids are resolved here, so an edit that landed first cannot point the fold at another cell.
            if (ids := d.get('ids')) is not None: ids = set(ids); at = [j for j, c in enumerate(nb.cells) if c.id in ids]
            else: at = None if d.get('all') else d.get('indices') or [i]
            nb.set_collapsed(at, bool(d.get('collapsed', True)))
        elif op == 'clear': nb.clear_all()
        else: return fail(f'unknown op {op!r}')
        tab.dirty = tab.dirty or nb.dirty
        return {'ok': True, 'cells': [c.dict() for c in nb.cells], 'version': nb.version, 'clash': clash,
                'index': at if op in ('undo', 'redo') else i}
    def lesson_memory(nb, write=False):
        "The `Memory` of the vault that holds the walk of the lesson `nb`; `Refused` for `write` on a read-only one. It opens stores: call it off the loop."
        from ..learn.learn import walk_memory
        from .lesson import walk_meta
        return walk_memory(ctx, walk_meta(nb).get('walk'), write)
    def _vault_fail(e):
        from ..learn.learn import Refused
        if isinstance(e, Refused): return fail(str(e), 403)
        if isinstance(e, ImportError) and (getattr(e, 'name', '') or '').startswith('abhyasa'): return fail('Saving cards needs abhyasa. Install abhyasa, then try again.')
        return fail(f'The learning vault is locked or unreadable. {errstr(e)}')
    @rt('/lesson/save')
    async def lesson_save(req):
        d = await req.json()
        async with lesson_lock:
            tab, nb, run_lock = run_owner(d)
            if nb is None: return fail('Save the notebook first.')
            cell = first(c for c in nb.cells if c.id == d.get('cell_id') and c.cell_type == 'code')
            lesson = cell.extra.get('lesson') if cell else None
            if not lesson or lesson.get('for_count') != cell.execution_count or cell.stale or run_lock.locked():
                return fail('Run the cell after writing your guess, then save.')
            key = f'{cell.id}:{cell.execution_count}'
            if lesson.get('saved') == key:
                return dict(ok=True, saved=key, message=lesson.get('saved_message', 'Saved to your learning shelf.'))
            if not tab.path or not Path(tab.path).is_file() or tab.dirty or nb.dirty or doc_versions.get(tab.path) != _disk_version(tab.path):
                return fail('Save the notebook first.')
            if not nb.meta.get('lesson', {}).get('name'): return fail('This is not a lesson notebook.')
            async with run_lock:
                try: message = await off_loop(lambda: record_card(lesson_memory(nb, True), nb, cell, tab.path))
                except Exception as e: return _vault_fail(e)
                lesson.update(saved=key, saved_message=message)
                saved = await nb_save(req)
                if not isinstance(saved, dict) or not saved.get('ok'):
                    lesson.pop('saved', None); lesson.pop('saved_message', None)
                    return saved
                return dict(saved, saved=key, message=message)
    @rt('/lesson/predict', methods=['POST'])
    async def lesson_predict(req):
        if (d := await json_obj(req)) is None: return fail(NOT_OBJECT)
        async with lesson_lock:
            tab, nb, _ = run_owner(d)
            if nb is None: return fail('Return to the lesson notebook, then try.')
            if not isinstance(lesson := nb.meta.get('lesson'), dict) or not lesson.get('name'): return dict(ok=True, logged=False)
            cell = first(c for c in nb.cells if c.id == d.get('cell_id'))
            if cell is None: return fail('That cell is no longer in the notebook.')
            if d.get('src') != src_hash(cell.source): return fail('This demo changed. Run the cell again, then try.', 409)
            try: f = prediction_filing(nb, cell, tab.path, d.get('demo'), str(d.get('gate') or ''), d.get('picked'), d.get('why'), d.get('ans'), d.get('ok'))
            except ValueError as e: return fail(str(e))
            try: message = await off_loop(lambda: record_prediction(lesson_memory(nb, True), f))
            except Exception as e: return _vault_fail(e)
            return dict(ok=True, logged=True, message=message) if message else dict(ok=True, logged=False)
    @rt('/lesson/predictions', methods=['POST'])
    async def lesson_predictions(req):
        "The picks filed for the demos of one lesson cell at its source now. No `lesson_lock`: a guide stream holds it through a model call."
        if (d := await json_obj(req)) is None: return fail(NOT_OBJECT)
        _, nb, _ = run_owner(d)
        if nb is None: return fail('Return to the lesson notebook, then try.')
        if not isinstance(lesson := nb.meta.get('lesson'), dict) or not lesson.get('name'): return dict(ok=True, picks={})
        cell = first(c for c in nb.cells if c.id == d.get('cell_id'))
        if cell is None: return fail('That cell is no longer in the notebook.')
        if d.get('src') != src_hash(cell.source): return dict(ok=True, picks={})
        try: return dict(ok=True, picks=await off_loop(lambda: filed_picks(lesson_memory(nb), nb, cell)))
        except Exception as e: return _vault_fail(e)
    def guide_said(d):
        "`(said, anchors, demo)` of the guide request `d`, or its fail reply."
        said = str(d.get('said') or '').strip()
        if not said: return fail('Say what you do not get.')
        try: return said, check_anchors(d.get('anchors')), check_demo(d.get('demo'))
        except ValueError as e: return fail(str(e))
    def guide_cell(d):
        "`(tab, nb, cell)` of the guide request `d`, or its fail reply. Call it under `lesson_lock`."
        tab, nb, _ = run_owner(d)
        if nb is None: return fail('Return to the lesson notebook, then try.')
        if not isinstance(lesson := nb.meta.get('lesson'), dict) or not lesson.get('name'): return fail('This is not a lesson notebook.')
        cell = first(c for c in nb.cells if c.id == d.get('cell_id'))
        if cell is None: return fail('That cell is no longer in the notebook.')
        return tab, nb, cell
    def guide_show(nb, said):
        "The Show hand-off to abhyasa for a \"show me …\" on the lesson `nb`, or None; None too with no abhyasa guide, whose board then says what it needs."
        from ..learn.learn import show_link
        from .lesson import _slug
        m = nb.meta['lesson']
        try: return show_link(said, _slug(m['name'], m.get('walk') or {}), m['name'])
        except ImportError as e:
            if (e.name or '').startswith('abhyasa'): return None
            raise
    @rt('/nb/guide/stream', methods=['POST'])
    async def nb_guide_stream(req):
        "The screen guide's board as events: `wait` while it works, `step` for each step of a sure tutor board as soon as it is whole, then `board` or `error`; or one `show`, the hand-off to abhyasa, for a \"show me …\". The lesson lock is held until the model call ends, not while the page reads."
        if (d := await json_obj(req)) is None: return fail(NOT_OBJECT)
        try: from rupaka.board import stream_board  # noqa: F401   the stream of steps; abhyasa's `explain` calls it with abhyasa's quote check
        except ImportError: return fail(GUIDE_STREAM_NEEDS)
        if not isinstance(asked := guide_said(d), tuple): return asked
        said, anchors, demo = asked
        await lesson_lock.acquire()
        try: g = guide_cell(d)
        except BaseException: lesson_lock.release(); raise
        if not isinstance(g, tuple): lesson_lock.release(); return g
        tab, nb, cell = g
        if sh := guide_show(nb, said):
            lesson_lock.release()
            return StreamingResponse(iter([sse('show', dict(show=sh))]), media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
        q, stop = queue.Queue(), threading.Event()
        def state(e):
            if 'saved' not in e: q.put(('wait', e))   # a saved page needs an undo route, which Leela does not have
        def run():
            try: q.put(('board', guide_board(lesson_memory(nb), nb, cell, tab.path, said, None, anchors, demo, stop=stop, on_state=state,
                                             on_step=lambda s, k, o: q.put(('step', dict(step=s, k=k, tier='tutor', demo_open=o))))))
            except ImportError as e: q.put(('error', dict(error=GUIDE_STREAM_NEEDS if (e.name or '').startswith(('abhyasa', 'rupaka')) else errstr(e))))
            except Exception as e: q.put(('error', dict(error=errstr(e))))
        asyncio.ensure_future(off_loop(run)).add_done_callback(lambda _: lesson_lock.release())
        async def events():
            try:
                while True:
                    try: kind, m = await off_loop(q.get, True, .25)
                    except queue.Empty:
                        if await req.is_disconnected(): return
                        continue
                    yield sse(kind, m)
                    if kind in ('board', 'error'): return
            finally: stop.set()
        return StreamingResponse(events(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
    @rt('/nb/guide', methods=['POST'])
    async def nb_guide(req):
        "The screen guide's board for what the learner does not get in one cell of a lesson."
        if (d := await json_obj(req)) is None: return fail(NOT_OBJECT)
        if not isinstance(asked := guide_said(d), tuple): return asked
        said, anchors, demo = asked
        async with lesson_lock:
            if not isinstance(g := guide_cell(d), tuple): return g
            tab, nb, cell = g
            if sh := guide_show(nb, said): return dict(ok=True, show=sh)
            notes = []
            try: board = await off_loop(lambda: guide_board(lesson_memory(nb), nb, cell, tab.path, said, notes.append, anchors, demo))
            except ImportError as e:
                if (getattr(e, 'name', '') or '').startswith(('abhyasa', 'rupaka')): return fail(GUIDE_NEEDS)
                return fail(errstr(e))
            except Exception as e: return fail(errstr(e))
            return dict(board, notes=notes, ok=True)
    def _held_text(target):
        "The file's text for the journal, None when it is not there; `False` past `MAX_BODY`, which history does not copy, so it is never read."
        p = Path(target) if target else None
        if not (p and p.exists()): return None
        if p.stat().st_size > MAX_BODY: return False
        try: return decoded(p.read_bytes(), p)
        except NotText: raise NotText(p, write=True) from None
    @rt('/nb/save')
    async def nb_save(req):
        d=await req.json();path=str(d.get('path') or '')
        t=store.tab_for(d['tab']) if d.get('tab') else first(x for x in ws.tabs if x.path==path) if path else ctx.tab
        if t is None:return fail('that tab is no longer open' if d.get('tab') or path else 'nothing open')
        key, force = t.path or t.title, bool(d.get('force'))
        current_version = _disk_version(t.path)
        base_version = str(d.get('base_disk_version') or '')
        changed = ('the file changed on disk after this browser draft began; review it before overwriting. '
                   f'Draft base {base_version}, on disk {current_version}: ')
        nb = docs.get(key) if t.kind == 'notebook' else None
        if t.kind != 'notebook' and base_version and current_version != base_version and not force:
            mine = doc_versions.get(key) == current_version
            return conflict(changed + ('Leela wrote that version itself, so this draft began before its own last save.' if mine else 'another process wrote it.'))
        try:
            target = t.path or d.get('path')
            if t.kind == 'notebook':
                if nb is None:
                    try:nb=Notebook.load(t.path) if t.path else Notebook.blank()
                    except Exception:return fail('no notebook')
                    docs[key]=nb
                    doc_versions[key] = current_version
                rows = d.get('cells', [])
                if force: rows = [{k: v for k, v in r.items() if k != 'base'} for r in rows]
                if (clash := nb.take_sources(rows, store.seqs_for(t))):
                    t.dirty = True
                    held = {c.id: c for c in nb.cells}
                    gone = [Cell(id=i, source='') for i in clash if i not in held]
                    return conflict('another window changed these cells: ' + _labels(nb, [held[i] for i in clash if i in held] + gone)
                                    + '. Review them before overwriting.', [held[i] for i in clash if i in held] + gone)
                synced_at = doc_versions.get(key) or base_version
                if t.path and synced_at and current_version != synced_at and not force:
                    # Something else wrote the file: take its changes into this copy, which keeps its own.
                    try: clash = nb.take_disk(Notebook.load(t.path)) if current_version != 'missing' else None
                    except Exception: clash = None
                    if clash is None: return conflict(changed + 'another process wrote it.')
                    if clash: return conflict('the file changed on disk and so did these cells here: ' + _labels(nb, clash)
                                              + '. Review them before overwriting.', clash)
                    t.dirty = True
            before = _held_text(target)
            if t.kind == 'notebook': nb.save(t.path or d.get('path'), sandbox=ctx.fs)
            else:
                ctx.fs.write(t.path, text := d.get('text', ''))
                # A mirror stamped after this text has already landed: it stays held, and the tab dirty.
                if (newest := take_seq(store.seqs_for(t), '', d.get('seq'))): buffers.pop(key, None)
            t.dirty = t.kind != 'notebook' and not newest
            buffer_bases.pop(key, None)
            # what is cached now matches the file again, so this is the version it was read at
            doc_versions[key] = _disk_version(t.path)
            # A text save already knows what it wrote; a notebook is read back only when history keeps it.
            after = text if t.kind != 'notebook' else None if before is False else _held_text(target)
            operation = None if False in (before, after) else ctx.journal.record(f'Save {t.title}', [(target, before, after)], kind='save')
            return {'ok': True, 'path': t.path, 'disk_version': doc_versions[key],
                    'version': nb.version if t.kind == 'notebook' else None,
                    'operation_id': operation['id'] if operation else ''}
        except Exception as e:
            return fail(e)
    @rt('/nb/language')
    async def nb_language(req):
        "Read or set which language this notebook's cells are."
        from ...core.langs import LANGS, lang_named
        from ..runtime.kernels import kernelspec_for
        from ..runtime.runners import runner_for
        d = await req.json() if req.method == 'POST' else {}
        owner_tab, nb, _ = run_owner(d)
        if nb is None: return fail('no notebook open')
        want = str(d.get('lang') or '')
        if want:
            if not (l := lang_named(want)): return fail(f'Leela does not know the language {want!r}')
            nb.set_lang(l.id, display=l.label, kernel=kernelspec_for(l.id) or l.kernel)
            owner_tab.nb_lang = l.id
            # A notebook that has never been saved has nowhere to write a kernelspec. It keeps the
            # language in memory and carries it into the file the first save creates.
            if nb.path:
                try: nb.save(sandbox=ctx.fs)
                except Exception as e: return fail(e)
            await ws.pool.close(ws.kernel_key(owner_tab))
        return {'lang': nb.lang, 'path': owner_tab.path,
                'langs': [{'id': l.id, 'label': l.label, 'current': l.id == nb.lang,
                           'how': ('a Jupyter kernel is installed' if kernelspec_for(l.id)
                                   else 'Leela runs it' if runner_for(l.id)
                                   else f'needs `{l.install}`')} for l in LANGS.values()]}
    @rt('/nb/cell', methods=['POST'])
    async def nb_cell(req):
        "The page reports the cell the person is on; the agent's next turn in Code mode anchors on it."
        if (d := await json_obj(req)) is None: return fail(NOT_OBJECT)
        tab, cid = ws.tab, d.get('cell')
        nb = store.doc_for(tab) if tab is not None and tab.kind == 'notebook' else None
        if nb is None: return {'ok': False, 'cell': ''}
        if not isinstance(cid, str) or not any(c.id == cid for c in nb.cells): return fail('that cell is no longer in the notebook', 409)
        ws.note_cell(cid)
        return {'ok': True, 'cell': cid}
    @rt('/nb/interrupt')
    async def nb_interrupt(req):
        "Interrupt one exact running cell, force-restarting its managed kernel if needed."
        d = await req.json()
        cell_id = d.get('id') or ''
        item = running_cells.get((d.get('path') or '', cell_id))
        if item is None:
            tab, nb, _ = run_owner(d)
            c = first(x for x in (nb or []) if x.id == cell_id)
            if c is not None and c.is_prompt:
                # `cancel`, which is what the agent panel's own stop reaches: it refuses the calls
                # still to come and releases the one already waiting for an approval.
                ctx.inline_ai.cancel()
                c.running = False
                return {'ok': True, 'stopped': 'prompt', 'note': 'asked the inline agent to stop'}
            if c is not None and c.running and not (tab and tab.running):   # marked running, and no run counted on the tab: clear the mark, so the cell can run again
                c.running = False
                return {'ok': True, 'stopped': 'stale', 'note': 'cleared a running mark that had no run behind it'}
            return fail('that cell is not running')
        k, _task = item
        if not hasattr(k, 'stop'): return fail('this external runtime cannot be stopped safely')
        return await k.stop(timeout=2.0)
    async def nb_comm_ws(sock):
        "Relay one notebook kernel's widget traffic to a page and back. Several pages may hold one; none takes the run lock."
        await sock.accept()
        ref, r, asks = sock.query_params.get('path', ''), CommRelay(), set()
        key = store.key(store.tab_for(ref)) or ref
        comm_relays.setdefault(key, set()).add(r)
        def kernel():
            tab = store.tab_for(ref)
            k = ws.runtime_peek(tab) if tab is not None and tab.kind == 'notebook' else None
            return k if getattr(k, 'alive', False) else None
        async def watch():
            while True:
                r.follow(kernel())
                await asyncio.sleep(COMM_WATCH)
        async def pump():
            while True: await sock.send_text(r.frame(await r.q.get()))
        async def ask(d):
            try: r.put({'type': 'reply', 'id': d.get('id'), 'content': await r.k.comm_info(d.get('target_name'))})
            except Exception as e: r.put({'type': 'error', 'id': d.get('id'), 'error': errstr(e)})
        async def listen():
            while True:
                m = await sock.receive()
                if m['type'] == 'websocket.disconnect': return
                try: d = json.loads(m.get('text') or '{}')
                except ValueError: d = None
                if not isinstance(d, dict):
                    r.put({'type': 'error', 'id': None, 'error': 'a widget frame is a JSON object'})
                    continue
                if d.get('op') == 'info':
                    asks.add(t := asyncio.create_task(ask(d)))
                    t.add_done_callback(asks.discard)
                    continue
                try: r.send(d)
                except Exception as e: r.put({'type': 'error', 'id': d.get('id'), 'error': errstr(e)})
        tasks = [asyncio.create_task(f()) for f in (watch, pump, listen)]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in done: t.exception()      # a closed socket ends `pump`; that is how this ends, not a fault to log
        finally:
            r.close()
            comm_relays.get(key, set()).discard(r)
            for t in (*tasks, *asks): t.cancel()
            try: await sock.close()
            except Exception: pass
    app.routes.append(WebSocketRoute('/nb/comm/ws', nb_comm_ws))
    presentation.connect(app, ctx)
