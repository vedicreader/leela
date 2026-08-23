"Server-owned turns: an event feed a browser replays from, and the thread that fills it."

import asyncio, threading, time, uuid
from collections import deque

from ... import errstr
from .turns import edit_diffs, tool_schemas, turn_media

TERMINAL_CANCEL = ('cancelled', 'detached', 'terminated')

class Feed:
    "One thread's events, numbered so a browser that missed some can ask for exactly those."
    def __init__(self, thread='', maxlen=2000):
        self.thread, self.rows, self.seq = thread, deque(maxlen=maxlen), 0
        self.closed, self.settled_seq, self.cv = False, 0, threading.Condition()
        self._waiters = set()

    def emit(self, event, data=None):
        with self.cv:
            if self.closed:return None
            self.seq += 1
            if event == 'user': self.settled_seq = 0
            row = {'seq': self.seq, 'event': event, 'data': {'thread': self.thread, **dict(data or {})}}
            self.rows.append(row); self.cv.notify_all(); self._wake()
            return row

    def since(self, seq=0):
        with self.cv:
            if self.rows and seq < self.rows[0]['seq'] - 1:
                return [{'seq': self.seq, 'event': 'resync', 'data': {
                    'thread': self.thread, 'oldest': self.rows[0]['seq'], 'latest': self.seq}}]
            return [row for row in self.rows if row['seq'] > seq]

    def wait(self, seq=0, timeout=15):
        with self.cv:
            rows = self.since(seq)
            if rows or self.closed:return rows
            self.cv.wait(timeout)
            return self.since(seq)

    async def anext(self, seq=0, timeout=15):
        "The same wait, parked on the caller's event loop rather than on the shared worker pool."
        rows = self.since(seq)
        if rows or self.closed: return rows
        loop, ev = asyncio.get_running_loop(), asyncio.Event()
        key = (loop, ev)
        with self.cv:
            rows = self.since(seq)
            if rows or self.closed: return rows
            self._waiters.add(key)
        try:
            try: await asyncio.wait_for(ev.wait(), timeout)
            except asyncio.TimeoutError: pass
            return self.since(seq)
        finally:
            with self.cv: self._waiters.discard(key)

    def _wake(self):
        "Called holding `cv`. A loop that has gone away loses its waiter rather than raising."
        for key in list(self._waiters):
            loop, ev = key
            try: loop.call_soon_threadsafe(ev.set)
            except RuntimeError: self._waiters.discard(key)

    def for_run(self, run_id):
        "Ordered events needed to reconstruct one browser turn after restart."
        keep = {'chunk', 'activity', 'approval', 'compaction', 'run', 'steer', 'error'}
        with self.cv:
            return [{'seq': row['seq'], 'event': row['event'], 'data': dict(row['data'])}
                    for row in self.rows if row['event'] in keep and row['data'].get('run') == run_id]

    def settle(self):
        with self.cv: self.settled_seq = self.seq; self.cv.notify_all(); self._wake()

    def finished(self, seq):
        with self.cv:
            return bool(self.settled_seq and seq >= self.settled_seq)

    def close(self):
        with self.cv: self.closed = True; self.cv.notify_all(); self._wake()


class TurnError(Exception):
    "A refusal a browser can act on: a code to branch on, a message to show, and what it was about."
    def __init__(self, code, message, thread='', run=''):
        self.code, self.message, self.thread, self.run = code, message, thread, run
        super().__init__(message)

    def dict(self):
        out = {'ok': False, 'code': self.code, 'message': self.message, 'thread': self.thread}
        if self.run:out['run'] = self.run
        return out


class Thread:
    "One live conversation and every mutable object that belongs only to it."
    def __init__(self, workspace, ai=None, approvals=None, feed=None):
        from .ai import Assistant, Interventions, WRITE_TOOLS
        self.workspace = workspace
        self.approvals = approvals or Interventions(tools=WRITE_TOOLS, mode=workspace.approvals_mode)
        self.ai = ai or Assistant(workspace, model=workspace.model, surface='agent',
            local_multimodal=workspace.local_multimodal, on_compact=workspace._compacted,
            history_name='agent', approvals=self.approvals)
        if hasattr(self.ai, 'set_model'): workspace.sync_agent_routing(self.ai)
        if hasattr(self.ai, 'host'): self.approvals.host = self.ai.host
        self.id = getattr(self.ai, 'session_id', '') or f'thread_{uuid.uuid4().hex[:12]}'
        self._stop_approvals = self.approvals.listen()
        self.feed = feed or Feed(self.id)
        self.runner = TurnRunner(workspace, self.feed, ai=self.ai, approvals=self.approvals, thread=self)
        self.created = self.touched = time.time(); self.title = ''; self.unread = 0
        self.opener = ''
        self.muted, self.mute_problem = False, ''
    @property
    def state(self):
        if self.approvals.pending is not None:return 'waiting'
        if self.ai.busy:return 'working'
        run = self.ai.run()
        return 'failed' if run is not None and run.terminal and run.state == 'failed' else 'idle'
    def touch(self): self.touched = time.time(); return self
    def finished_turn(self):
        "One more turn a person has not seen, unless they were watching this conversation."
        if self.workspace.threads.active_id != self.id: self.unread += 1
        return self.unread
    def read(self): self.unread = 0; return self
    def mute(self, muted=True):
        "Persisted, so it survives a restart. A failure to write is reported, not swallowed."
        self.muted = bool(muted)
        try: self.ai.set_muted(self.muted, self.id); self.mute_problem = ''
        except Exception as e: self.mute_problem = errstr(e)
        return self
    def meta(self):
        "The sidecar row, given the name `sessions()` derives while nothing has been summarised yet."
        ai = self.ai
        meta = ai.session_meta(self.id) if hasattr(ai, 'session_meta') else {}
        if meta.get('title') or not hasattr(ai, 'sessions'): return meta
        row = next((r for r in ai.sessions() if r.get('id') == self.id), {})
        return {**meta, 'title': row.get('title', '')}
    def name(self, meta=None):
        """What to call this conversation: a name a person chose, else a summarised or derived one,
        else the first thing they said. A card is named the moment a turn starts, rather than
        waiting for the summariser, the sidecar, or the turn to reach the log."""
        meta = self.meta() if meta is None else meta
        chosen = self.title.strip() if self.title else ''
        return chosen or str(meta.get('title', '')).strip() or ' '.join(self.opener.split())[:60]
    def dict(self):
        meta = self.meta()
        return {'id': self.id, 'title': self.name(meta), 'state': self.state,
                'created': self.created, 'touched': self.touched, 'unread': self.unread,
                'muted': bool(meta.get('muted', self.muted)), 'problem': self.mute_problem}
    def close(self):
        "Close every part, and report what refused rather than skipping the rest."
        problems = []
        for step in (self._stop_approvals, lambda: self.runner.close(cancel=False), self.ai.close):
            try: step()
            except Exception as e: problems.append(errstr(e))
        return problems


class Threads:
    "At most six live conversations, with working and waiting ones protected from eviction."
    def __init__(self, workspace, limit=6):
        self.workspace, self.limit, self._rows, self.active_id = workspace, limit, {}, ''
        self._lock = threading.RLock()
        if workspace._ai is not None or workspace._turn_runner is not None:
            runner = workspace._turn_runner
            thread = Thread(workspace, ai=workspace._ai, feed=getattr(runner, 'feed', None))
            if runner is not None: thread.runner = runner
            self._rows[thread.id], self.active_id = thread, thread.id
    def _activate(self, thread):
        self.active_id = thread.id; thread.read()
        self.workspace._ai, self.workspace._turn_runner = thread.ai, thread.runner
        return thread.touch()
    @property
    def active(self):
        with self._lock:
            if self.active_id:return self._rows[self.active_id].touch()
        return self.new()
    def rows(self):
        with self._lock:return list(self._rows.values())
    def dicts(self):
        "The conversations something has been said in: the empty one a person was handed is not one."
        # `title` is chosen, summarised, or derived from the log's first prompt, so any past counts.
        rows = sorted(self.rows(), key=lambda row: row.touched, reverse=True)
        return [d for d in (row.dict() for row in rows)
                if d['title'] or d['unread'] or d['state'] != 'idle']
    def attention(self):
        "What the badge and the switcher need: how many are working, how many want a person."
        rows = self.rows()
        return {'working': sum(1 for r in rows if r.state == 'working'),
                'waiting': self.waiting(), 'unread': sum(r.unread for r in rows),
                'threads': len(rows), 'active': self.active_id}
    def mute(self, thread_id, muted=True): return self.require(thread_id).mute(muted)
    def waiting(self):
        "Every conversation holding a checkpoint. What the attention bar and the badge read."
        return [row.id for row in self.rows() if row.state == 'waiting']
    def get(self, thread_id):
        with self._lock:return self._rows.get(str(thread_id))
    def require(self, thread_id):
        thread = self.get(thread_id)
        if thread is None: raise TurnError('thread_not_found', 'that conversation is not live', str(thread_id))
        return thread.touch()
    def _room(self):
        if len(self._rows) < self.limit:return
        idle = [row for row in self._rows.values() if row.state in ('idle', 'failed') and row.id != self.active_id]
        if not idle: raise TurnError('no_evictable_thread', 'all six conversations are working or waiting', self.active_id)
        victim = min(idle, key=lambda row: row.touched)
        self._rows.pop(victim.id); victim.close()
    def new(self, ai=None):
        with self._lock:
            self._room(); thread = Thread(self.workspace, ai=ai)
            self._rows[thread.id] = thread
            return self._activate(thread)
    def switch(self, thread_id):
        with self._lock:return self._activate(self.require(thread_id))
    def resume(self, session):
        from .ai import Assistant, Interventions, WRITE_TOOLS
        with self._lock:
            if session in self._rows:return self._activate(self._rows[session])
            self._room()
            approvals = Interventions(tools=WRITE_TOOLS, mode=self.workspace.approvals_mode)
            source = self._rows.get(self.active_id)
            ai = Assistant(self.workspace, model=self.workspace.model, surface='agent',
                local_multimodal=self.workspace.local_multimodal, on_compact=self.workspace._compacted,
                history_name='agent', approvals=approvals)
            if source is not None:
                self.workspace.fresh_history(source.ai); ai.history = list(source.ai.history)
            ai.refresh_history()          # another live thread may have written this session
            # resuming rebuilds context from the log, so keep a copy of it before anything can
            try: self.workspace.guard_history(f'before resuming {session}')
            except Exception: pass
            ai.resume_session(session)
            ai.mark_surface()   # continued here, so the history filter counts it as Leela's now
            thread = Thread(self.workspace, ai=ai, approvals=ai.approvals, feed=Feed(ai.session_id))
            self._rows[thread.id] = thread
            return self._activate(thread)
    def title(self, thread_id, text):
        with self._lock:
            thread = self.require(thread_id); thread.title = str(text or '').strip()
            if hasattr(thread.ai, 'set_title'): thread.ai.set_title(thread.title, thread.id)
            return thread
    def close(self, thread_id):
        with self._lock:
            thread = self.require(thread_id)
            if thread.state in ('working', 'waiting'): raise TurnError('thread_busy', 'stop or answer this conversation before closing it', thread.id)
            self._rows.pop(thread.id)
            replacement = self._rows.get(next(iter(self._rows), '')) if self.active_id == thread.id else None
            if replacement is not None:self._activate(replacement)
            elif self.active_id == thread.id:
                self.active_id = ''; self.workspace._ai = self.workspace._turn_runner = None
        thread.close(); return thread.id
    def shutdown(self):
        with self._lock:
            rows = list(self._rows.values()); self._rows.clear(); self.active_id = ''
            self.workspace._ai = self.workspace._turn_runner = None
        # shutting down is the one path that has to finish: one conversation that cannot close is
        # not a reason to leave the rest open, so problems are returned rather than raised
        problems = []
        for thread in rows:
            try: problems += [f'{thread.id}: {p}' for p in (thread.close() or [])]
            except Exception as e: problems.append(f'{thread.id}: {errstr(e)}')
        return problems


class TurnRunner:
    "One thread's turns, each on its own daemon thread, so closing a tab is not a cancel."
    def __init__(self, workspace, feed=None, ai=None, approvals=None, thread=None):
        self.workspace, self.ai, self.thread = workspace, ai, thread
        self.approvals = approvals or getattr(workspace, 'approvals', None)
        self.feed = feed or Feed()
        self._pending, self._lock = {}, threading.RLock()
        self.start_timeout = 30

    def _watch(self, ai, run_id):
        activity, approval, execution, compact = {}, '', '', ai.compactor.count
        while True:
            run = ai.run(run_id)
            if run is None or run.terminal:return
            if ai.compactor.count != compact:
                compact = ai.compactor.count
                self.feed.emit('compaction', {'count': compact, 'strategy': ai.compactor.strategy,
                    'note': ai.compactor.note, 'text': ai.compactor.last, 'run': run_id})
            state = {**self.approvals.state(), 'runs': ai.runs(active=True), 'run': run_id}
            version = repr(state)
            if version != execution:
                execution = version; self.feed.emit('execution', state)
            pending = self.approvals.pending
            if pending is not None and pending.id != approval:
                approval = pending.id
                self.feed.emit('approval', {**pending.dict(), 'schemas': tool_schemas(ai), 'run': run_id})
            for row in ai.activity.rows(mark=ai.activity._mark):
                version = (row.get('done'), row.get('detail'), row.get('ok'))
                if activity.get(row.get('id')) != version:
                    activity[row.get('id')] = version
                    self.feed.emit('activity', {**row, 'run': run_id})
            if run.terminal:return
            time.sleep(.1)

    def _done(self, ai, run_id, ok=None):
        "The turn's closing payload. A part that cannot be read becomes a problem, not a lost event."
        out = {'ok': False if ok is False else True, 'run': run_id, 'note': '', 'problems': [],
               'usage': {}, 'usage_label': '', 'session_usage': {}, 'session_usage_label': '',
               'model': '', 'turn_id': '', 'branch_id': '', 'media': [], 'edits': [],
               'capabilities': {}, 'activity': []}
        reads = (
            ('ok', lambda: ai.ready if ok is None else ok), ('note', lambda: ai.note),
            ('usage', lambda: ai.turn_use.dict()), ('usage_label', lambda: repr(ai.turn_use)),
            ('session_usage', lambda: ai.use.dict()), ('session_usage_label', lambda: repr(ai.use)),
            ('model', lambda: ai.model.name), ('turn_id', lambda: ai.current_turn_id),
            ('branch_id', lambda: ai.current_branch_id), ('problems', lambda: list(ai.problems)),
            ('media', lambda: turn_media(ai)), ('edits', lambda: edit_diffs(ai)),
            ('capabilities', lambda: ai.turn_capabilities(ai.current_turn_id)),
            ('activity', lambda: ai.activity.rows(mark=ai.activity._mark)))
        for key, read in reads:
            try:
                value = read()
                if key == 'problems': out[key].extend(value)
                else: out[key] = value
            except Exception as e: out['problems'].append(errstr(e))
        return out

    def _settled(self, ai, run_id, title=False):
        if title:
            try:
                meta = ai.summarize_session()
                self.feed.emit('title', {'title': meta.get('title', ''), 'title_turns': meta.get('title_turns', 0),
                    'muted': meta.get('muted', False), 'run': run_id})
            except Exception as e: self.feed.emit('title', {'problem': errstr(e), 'run': run_id})
        try: state = {**self.approvals.state(), 'runs': ai.runs(active=True), 'run': run_id}
        except Exception as e: state = {'runs': [], 'run': run_id, 'problems': [errstr(e)]}
        self.feed.emit('state', state); self.feed.settle()
        if self.thread is not None: self.thread.finished_turn()

    def _work(self, prompt, attachments, reasoning, context, context_path, grounding, ready):
        ai, run_id = self.ai or self.workspace.ai, ''
        def registered(run):
            nonlocal run_id
            run_id = run.id; threading.current_thread().name = f'leela-turn-{run_id}'
            ready['run'] = run_id; ready['event'].set(); ready['gate'].wait()
            if not ready['accepted']: ai.cancel(run_id); return
            threading.Thread(target=self._watch, args=(ai, run_id), daemon=True,
                name=f'leela-feed-{run_id}').start()
        try:
            stream = self.workspace.ask_stream(prompt, attachments=attachments, reasoning=reasoning,
                context=context, context_path=context_path, grounding=grounding,
                on_registered=registered, ai=ai)
            for chunk in stream:
                if not ready['accepted']: return
                if chunk is not None:self.feed.emit('chunk', {'text': chunk, 'run': run_id})
            if not ready['accepted']: return
            run = ai.run(run_id)
            # a turn that finished is told by `done`; `run` is how one that was stopped says so
            if run is not None and run.state in TERMINAL_CANCEL:self.feed.emit('run', run.dict())
            self.feed.emit('done', self._done(ai, run_id))
            try: self.workspace.save_timeline(ai.session_id, ai.current_turn_id, self.feed.for_run(run_id))
            except Exception as e: self.feed.emit('state', {'run': run_id, 'problems': [errstr(e)]})
            self._settled(ai, run_id, title=True)
        except Exception as e:
            if not ready['accepted']:
                ready['error'] = e; ready['event'].set()
            else:
                self.feed.emit('error', {'message': errstr(e), 'run': run_id})
                self.feed.emit('done', self._done(ai, run_id, ok=False))
                try: self.workspace.save_timeline(ai.session_id, ai.current_turn_id, self.feed.for_run(run_id))
                except Exception as e: self.feed.emit('state', {'run': run_id, 'problems': [errstr(e)]})
                self._settled(ai, run_id)
        finally:
            with self._lock:self._pending.pop(ready['id'], None)

    def start(self, prompt, attachments=(), reasoning=None, context='', context_path='', grounding=None):
        ai = self.ai or self.workspace.ai
        thread = ai.session_id
        self.feed.thread = thread
        ident = uuid.uuid4().hex[:8]
        ready = {'id': ident, 'event': threading.Event(), 'gate': threading.Event(),
            'accepted': False, 'run': '', 'error': None}
        worker = threading.Thread(target=self._work,
            args=(prompt, tuple(attachments), reasoning, context, context_path, grounding, ready), daemon=True,
            name=f'leela-turn-pending-{ident}')
        with self._lock:
            if self._pending or ai.busy:
                raise TurnError('thread_busy', 'the assistant is already working; use steering or stop it first', thread)
            self._pending[ident] = ready
        worker.start()
        ready['event'].wait(self.start_timeout)
        run_id = ready['run']
        if ready['error'] is not None:
            ready['gate'].set()
            if isinstance(ready['error'], TurnError): raise ready['error']
            raise TurnError('turn_conflict', errstr(ready['error']), thread)
        if not run_id:
            ready['gate'].set(); raise TurnError('turn_conflict', 'the turn did not start', thread)
        with self._lock:
            if ready['error'] is not None:
                ready['gate'].set(); raise ready['error']
            if self.thread is not None and not self.thread.opener: self.thread.opener = prompt
            user = self.feed.emit('user', {'text': prompt, 'run': run_id})
            if user is None:
                ready['gate'].set(); raise TurnError('thread_closed', 'the thread is closed', thread, run_id)
            ready['accepted'] = True; ready['gate'].set()
        return {'ok': True, 'thread': thread, 'run': run_id, 'seq': user['seq']}

    def close(self, cancel=True):
        with self._lock:
            for ready in self._pending.values():
                ready['error'] = TurnError('thread_closed', 'the thread is closed', self.feed.thread)
                ready['event'].set(); ready['gate'].set()
        ai = self.ai or self.workspace._ai
        if cancel and ai is not None:
            for row in ai.runs(active=True):
                try: ai.cancel(row['id'])
                except Exception: pass
        self.feed.close()
