"The notebook as routes: cells, runs, saves, and the notebook debugger."

from __future__ import annotations

import asyncio

from fasthtml.common import StreamingResponse
from fastcore.all import first

from ... import errstr
from pathlib import Path

from ...core.text import did_you_mean
from ...core.web import fail, off_loop, sse
from ..agent.turns import activity_changes, edit_diffs, tool_schemas
from ..debug.debug import notebook_state_ui, paused_kernel
from ..tabs.app import disk_version as _disk_version
from .nb import Cell, Notebook, cell_extras, inline_values, src_hash

__all__ = ['CAPS', 'connect']

CAPS = ('fs', 'journal', 'inline_ai', 'tab', 'pending_approval', 'docs', 'debug', 'running')

def _rebase_notebook(tab, payload, docs):
    """Put a draft's source edits onto the notebook as it is on disk now.

    Returns the cells whose source moved on both sides, `[]` when the rebase is clean, or None when
    it cannot be attempted at all and the caller should refuse the save. Cells are matched by id,
    because an external write may have added or removed one and shifted every index after it.
    """
    key = tab.path or tab.title
    base = docs.get(key)
    if base is None or not tab.path: return None
    try: disk = Notebook.load(tab.path)
    except Exception: return None
    by_id = {c.id: c for c in disk.cells if c.id}
    clash, edits = [], []
    for c in payload.get('cells', []):
        i = c.get('i')
        if not isinstance(i, int) or not 0 <= i < len(base): return None
        was = base[i]
        now = by_id.get(was.id) if was.id else (disk[i] if i < len(disk) else None)
        if now is None: return None                      # the cell is gone: not ours to reconcile
        if now.source != was.source and now.source != c['source']:
            clash.append(f'cell {i + 1}')
        else: edits.append((now, c['source']))
    if clash: return clash
    for cell, source in edits: cell.source = source
    docs[key] = disk
    return []

def connect(app, ctx):
    rt = app.route
    ws, store, dbgstate = ctx.session, ctx.docs, ctx.debug
    docs, run_locks = store.docs, store.run_locks
    buffers, buffer_bases, doc_versions = store.buffers, store.bases, store.versions
    running_cells = ctx.running.cells
    def doc(): return store.current()
    def run_owner(d): return store.owner(d.get('path'))
    def note_origin(tab, cell): ws.origins.cell(cell, (tab.path or tab.title) if tab else '')
    def dbg(method=None): return paused_kernel(dbgstate, method)
    def debug_ui(state): return notebook_state_ui(dbgstate, ctx.fs, state)
    def previous_runs(): store.mark_all_stale()
    async def runtime_for(tab=None): return await ws.runtime(tab)
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
        nb[i].source = d.get('source', nb[i].source)
        async with run_lock:
            k = await runtime_for(owner_tab)
            owner_tab.running += 1
            try: c = await nb.run(i, k)
            finally: owner_tab.running = max(0, owner_tab.running - 1)
        note_origin(owner_tab, c)
        if owner_tab: owner_tab.dirty = True
        rows, result = await cell_extras(k, c)
        return {'ok': not c.has_error, 'i': i, 'cell': c.dict(), 'result': result,
                'inline': inline_values(c.source, (rows or {}).get('groups', []), c.outputs, result)}
    @rt('/nb/run/stream')
    async def nb_run_stream(req):
        "Run a cell while streaming its evolving Jupyter outputs as SSE."
        d = await req.json()
        owner_tab, nb, run_lock = run_owner(d)
        i = int(d.get('i', 0))
        if nb is None: return fail('no notebook open')
        if not (0 <= i < len(nb)) or (d.get('id') and nb[i].id != d['id']):
            return fail('that cell is no longer at this position', 409)
        nb[i].source = d.get('source', nb[i].source)
        # The notebook about to run is one stat; its tree is a walk, and that is once per root.
        if ws.initialize_notebook(getattr(owner_tab, 'path', None), nb):
            doc_versions[owner_tab.path] = _disk_version(owner_tab.path)
        await off_loop(ws.initialize_empty_notebooks, ws.cwd_for(owner_tab))
        await run_lock.acquire()
        try: k = await runtime_for(owner_tab)
        except BaseException:
            run_lock.release()
            raise
        async def events():
            q = asyncio.Queue()
            if owner_tab: owner_tab.running += 1
            def emitted(_i, _output): q.put_nowait([dict(x) for x in nb[i].outputs])
            task = asyncio.create_task(nb.run(i, k, on_output=emitted))
            # The end of the cell wakes this loop. It used to wait on the queue with a 120ms timeout
            # and re-check, so a cell that finished without printing anything -- an assignment, an
            # import, a definition, most cells in most notebooks -- paid that 120ms in full, every
            # run, on top of the two milliseconds it took to execute.
            task.add_done_callback(lambda _: q.put_nowait(None))
            run_key = ((owner_tab.path or owner_tab.title) if owner_tab else '', nb[i].id)
            running_cells[run_key] = (k, task)
            try:
                while True:
                    outputs = await q.get()
                    if outputs is None:
                        if q.empty(): break
                        continue
                    while not q.empty():
                        nxt = q.get_nowait()
                        if nxt is None: break
                        outputs = nxt
                    yield sse('output', {'i': i, 'outputs': outputs})
                c = await task
                note_origin(owner_tab, c)
                if owner_tab: owner_tab.dirty = True
                rows, result = await cell_extras(k, c)
                yield sse('done', {'ok': not c.has_error, 'i': i, 'cell': c.dict(), 'result': result,
                                    'inline': inline_values(c.source, (rows or {}).get('groups', []), c.outputs, result)})
            except Exception as e:
                yield sse('error', {'text': errstr(e)})
            finally:
                owner_tab.running = max(0, owner_tab.running - 1)
                if running_cells.get(run_key, (None,))[1:] == (task,): running_cells.pop(run_key, None)
                if not task.done(): task.cancel()
                run_lock.release()
        return StreamingResponse(events(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
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
        if nb[i].cell_type != 'code': return fail('only code cells can be debugged')
        nb[i].source = d.get('source', nb[i].source)
        await run_lock.acquire()
        try: k = await runtime_for(owner_tab)
        except BaseException:
            run_lock.release()
            raise
        if getattr(k, 'kernel_kind', None) != 'ipykernel' or not hasattr(k, 'debug_start'):
            run_lock.release()
            return fail('cell debugging currently requires a direct ipykernel runtime')
        if dbgstate.paused:
            run_lock.release()
            return fail('a debugger session is already active', 409)
        breakpoints = d.get('breakpoints') or []
        dbgstate.kernel, dbgstate.origin_path, dbgstate.cell_id = k, owner_tab.path, nb[i].id
        async def events():
            q, c = asyncio.Queue(), nb[i]
            c.clear(); c.running = True
            if owner_tab: owner_tab.running += 1
            started = asyncio.get_running_loop().time()
            try:
                notebook_sources = [(cell.id, cell.source) for cell in nb.cells if cell.cell_type == 'code']
                verified = await k.debug_start(c.source, breakpoints, notebook_sources)
                yield sse('ready', {'i': i, 'breakpoints': verified})
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
                c.outputs, c.execution_count = result.outputs, result.execution_count
                c.execution_ms = (asyncio.get_running_loop().time() - started) * 1000
                c.fresh, c.output_hash = True, src_hash(c.source)
                note_origin(owner_tab, c)
                if owner_tab: owner_tab.dirty = True
                yield sse('done', {'ok': result.ok, 'i': i, 'cell': c.dict(),
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
        nb, i = doc(), int(d.get('i', 0))
        if nb is None: return fail('no notebook open')
        if not (0 <= i < len(nb)): return fail(f'no cell {i}')
        nb[i].source = d.get('source', nb[i].source)
        try: c = await off_loop(ws.ask_cell, nb, i)
        except Exception as e: return fail(e)
        if ctx.tab: ctx.tab.dirty = True
        a = ctx.inline_ai
        return {'ok': a.ready, 'i': i, 'cell': c.dict(), 'note': a.note,
                'problems': a.problems,
                'cells': [x.dict() for x in nb.cells],
                'activity': a.activity.rows(mark=a.activity._mark),
                'edits': edit_diffs(a)}
    @rt('/nb/ask/stream')
    async def nb_ask_stream(req):
        "Stream a prompt cell into its own reply area as markdown arrives."
        d = await req.json()
        nb, i = doc(), int(d.get('i', 0))
        if nb is None: return fail('no notebook open')
        if not (0 <= i < len(nb)): return fail(f'no cell {i}')
        nb[i].source = d.get('source', nb[i].source)
        nb[i].running = True
        owner_tab = ctx.tab
        if owner_tab: owner_tab.running += 1
        a = ctx.inline_ai
        async def events():
            import queue as _q
            out, done = _q.Queue(), object()
            def pump():
                try:
                    for chunk in ws.ask_cell_stream(nb, i): out.put(('chunk', chunk))
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
                        proposal = {**pending.dict(), 'schemas': tool_schemas(a)}
                        yield sse('approval', proposal)
                    for row in changed_activity(): yield sse('activity', row)
                    if await req.is_disconnected():
                        a.cancel()
                        return
                    if kind is None: continue
                    if kind is done:
                        for row in changed_activity(): yield sse('activity', row)
                        break
                    yield sse(kind, {'text': value})
                await task
                c = nb[i]
                yield sse('done', {'ok': a.ready, 'i': i, 'cell': c.dict(), 'note': a.note,
                                    'usage': a.turn_use.dict(), 'usage_label': repr(a.turn_use),
                                    'problems': a.problems,
                                    'cells': [x.dict() for x in nb.cells],
                                    'activity': a.activity.rows(mark=a.activity._mark),
                                    'edits': edit_diffs(a)})
            finally:
                nb[i].running = False
                if owner_tab is not None:
                    owner_tab.running = max(0, owner_tab.running - 1)
                    owner_tab.dirty = True
        return StreamingResponse(events(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
    @rt('/nb/edit')
    async def nb_edit(req):
        "Structural edits: insert / delete / move / type / split / merge."
        d = await req.json()
        nb = doc()
        if nb is None: return fail('no notebook open')
        op, i = d.get('op'), int(d.get('i', 0))
        for src in d.get('sources', []):
            j = int(src.get('i', -1))
            if 0 <= j < len(nb): nb[j].source = src.get('source', nb[j].source)
        if op == 'insert': nb.insert(i, Cell(source=d.get('source', ''), cell_type=d.get('cell_type', 'code')))
        elif op == 'delete': nb.delete(i)
        elif op == 'delete_many': nb.delete_many(d.get('indices') or [i])
        elif op == 'move': nb.move(i, int(d.get('d', 1)))
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
            nb.paste_many(i, pasted)
        elif op == 'merge_above': nb.merge(i - 1) if i > 0 else None
        elif op == 'merge_below': nb.merge(i)
        elif op == 'clear_cell': nb.clear_cell(i)
        elif op == 'undo':
            if (at := nb.undo()) is None: return fail('no cell operation to undo')
        elif op == 'redo':
            if (at := nb.redo()) is None: return fail('no cell operation to redo')
        elif op == 'merge': nb.merge(i)
        elif op == 'source':
            nb[i].source = d.get('source', '')
            nb.dirty = True
        elif op == 'context':
            mode = str(d.get('mode') or 'auto')
            if mode not in ('auto', 'keep', 'discard'): return fail('context mode must be auto, keep or discard')
            nb._checkpoint(i)
            nb[i].context_mode = mode
            nb.dirty = True
        elif op == 'clear': nb.clear_all()
        else: return fail(f'unknown op {op!r}')
        if ctx.tab: ctx.tab.dirty = nb.dirty
        return {'ok': True, 'cells': [c.dict() for c in nb.cells],
                'index': at if op in ('undo', 'redo') else i}
    @rt('/nb/save')
    async def nb_save(req):
        d=await req.json();path=str(d.get('path') or '')
        t=(first(x for x in ws.tabs if x.path==path) if path else ctx.tab)
        if t is None:return fail('nothing open')
        current_version = _disk_version(t.path)
        base_version = str(d.get('base_disk_version') or '')
        rebased = ''
        if base_version and current_version != base_version and not d.get('force'):
            # A save writes cell sources and nothing else, and `nbdev_clean` rewrites outputs and
            # metadata and nothing else, so the two rarely touch the same thing. Take the file as it
            # is now and put the draft's edits back on top; only a source changed on both sides is a
            # conflict worth stopping for.
            clash = _rebase_notebook(t, d, docs) if t.kind == 'notebook' else None
            if clash is None:
                mine = doc_versions.get(t.path or t.title) == current_version
                whose = ('Leela wrote that version itself, so this draft began before its own last save'
                         if mine else 'another process wrote it')
                return fail('the file changed on disk after this browser draft began; review it before '
                            f'overwriting. Draft base {base_version}, on disk {current_version}: {whose}.', 409)
            if clash:
                return fail('the file changed on disk and so did these cells in the browser: '
                            + ', '.join(clash) + '. Review them before overwriting.', 409)
            rebased = current_version
        try:
            target = t.path or d.get('path')
            before = Path(target).read_text(encoding='utf-8', errors='replace') if target and Path(target).exists() else None
            if t.kind == 'notebook':
                nb=docs.get(t.path or t.title)
                if nb is None:
                    try:nb=Notebook.load(t.path) if t.path else Notebook.blank()
                    except Exception:return fail('no notebook')
                    docs[t.path or t.title]=nb
                for c in d.get('cells', []):
                    if 0 <= c['i'] < len(nb): nb[c['i']].source = c['source']
                nb.save(t.path or d.get('path'), sandbox=ctx.fs)
            else:
                ctx.fs.write(t.path, text := d.get('text', ''))
                buffers.pop(t.path or t.title, None)
            t.dirty = False
            buffer_bases.pop(t.path or t.title, None)
            # what is cached now matches the file again, so this is the version it was read at
            doc_versions[t.path or t.title] = _disk_version(t.path)
            # A text save already knows what it wrote. Reading it back would cost a second pass
            # over the file, which on a large notebook is long enough to feel.
            after = (text if t.kind != 'notebook' else
                     Path(target).read_text(encoding='utf-8', errors='replace')
                     if target and Path(target).exists() else None)
            operation = ctx.journal.record(f'Save {t.title}', [(target, before, after)], kind='save')
            return {'ok': True, 'path': t.path, 'disk_version': _disk_version(t.path),
                    'operation_id': operation['id'] if operation else ''}
        except Exception as e:
            return fail(e)
    @rt('/nb/language')
    async def nb_language(req):
        """Read or set which language this notebook's cells are.

        The notebook's kernelspec is the only record of it, so setting one writes the file. The
        runtime a tab already holds is for the old language, so it goes; the next run starts the
        one this notebook now names.
        """
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
    @rt('/nb/interrupt')
    async def nb_interrupt(req):
        "Interrupt one exact running cell, force-restarting its managed kernel if needed."
        d = await req.json()
        item = running_cells.get((d.get('path') or '', d.get('id') or ''))
        if item is None: return fail('that cell is not running')
        k, _task = item
        if not hasattr(k, 'stop'): return fail('this external runtime cannot be stopped safely')
        return await k.stop(timeout=2.0)
