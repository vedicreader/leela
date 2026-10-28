# Learn from abhyasa: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Leela opens a walk step or a topic from abhyasa at `/learn`, teaches code with real libraries in a lesson notebook (a tool environment, a closed-process check, kosha lookup in the side pane, the agent as tutor), and writes every check back to the shared learning store with the walk meta. On the way, Leela logs rupaka predictions, keeps its rupaka bundle and validator on one version, and reads the tutor prompt through `abhyasa.prompts`.

**Architecture:** The work lives in the existing `learn` block (`leela/blocks/learn/`), which today has one route, `/lesson/due`. It gets a domain module (`learn.py`: the handoff, the step lookup, `is_local`), the FT pieces (`ui.py`), the pane script (`pane.js`), and the tool module (`tools.py`: tool environments and library checks). Lesson notebooks stay in `leela/blocks/nb/lesson.py` and `exercise.py`; they get the walk meta, the prediction record, the charter function and the move to `abhyasa.check.run_isolated`. The handoff functions, the prompt registry and the closed runner come from abhyasa; Leela adds no copy of them, except `is_local` (three lines, with a reason) and, until abhyasa ships `python=`, the library runner.

**Tech Stack:** Python 3.13, FastHTML, Starlette `TestClient`, abhyasa (PyPI), rupaka (PyPI, vendored bundle), kosha (`koshas`), `uv`, pytest, Node for the small JS harnesses, Playwright bundled Chromium for one browser check.

**Spec:** `docs/plans/2026-10-28-learn-from-abhyasa-design.md`. Brief: `abhyasa-designs/leela-reuse.md`, section 6. abhyasa side: `abhyasa-walk/docs/superpowers/plans/2026-10-28-guided-walk.md`, Tasks 11 and 14.

## Survey

Entry points and call paths that this plan changes (main at `58af242`):

- New lesson: File menu `new_lesson` (`leela/blocks/keys/menus.py:84`, no key, `leela/core/keys.py:155`) to `POST /lesson/new` (`leela/blocks/tabs/app.py:82`) to `lesson_notebook` (`leela/blocks/nb/lesson.py:20`).
- Predict card save: `POST /lesson/save` (`leela/blocks/nb/app.py:531`) to `record_card` (`lesson.py:72`).
- Exercise: `POST /exercise/check` (`nb/app.py:249`) to `check_cell`; agent tools `add_exercise` (`leela/blocks/agent/ai.py:950`, uses `check_solution`), `check_exercise`, `grade_exercise`, and the filing path `record_exercise` (`ai.py:596`, `lesson.py:117`).
- Due cards: `GET /lesson/due` (`leela/blocks/learn/app.py`).
- Tutor charter: `LESSON_CHARTER` (`lesson.py:12`), read in `ai.py:1244`, `:1267` and `:1307` (`system_prompt` when `_lesson()` is true).
- Demos: `rupakaDraw` and `rupakaFences` (`leela/static/lee-core.js:613`, `:653`). `rk-predict` is sent with `composed: true` and has no listener.
- KaTeX: `loadKatex` (`lee-core.js:628`) loads `leela/vendor/katex/`.
- Split editor: the two tab-bar buttons (`leela/app.py:297-298`) call `leeSplit`, which calls `mountSecondary`; `leeCloseSplit` closes; the split is kept in `localStorage['lee-editor-split']` and mounted again at `lee-core.js:2006`. `SPLIT_KINDS` (`lee-core.js:2237`) lists what the split can hold. No key binds the split.
- Address file: `now_serving`, `served`, `serving` (`leela/core/projects.py:117-140`); the hub writes it at `leela/app.py:1396` and `:1466`.
- Guard: `LoopbackHostGuard` (`leela/hub.py:128`) refuses `Sec-Fetch-Site: cross-site` with 421.
- Code index: `Search._kosha`, `env_symbols` (`leela/blocks/search/search.py:202`, `:854`); `kosha.Kosha.env_context`.
- Jobs: `ws.jobs.register(kind, fn)`, `new`, `launch` (`leela/blocks/vault/jobs.py:125`).

Files that the ramabana agent edits now in Leela's main checkout: `leela/blocks/nb/lesson.py`, `leela/blocks/nb/exercise.py` and `tests/test_abhyasa_contract.py`. Each task below says whether it touches them, so the owner can put those tasks after the ramabana agent's work merges, or rebase.

## Global Constraints

- **Task 0 first.** Every other task needs the abhyasa release that carries the walk. Do not start a task before its "Needs abhyasa" line is true in the locked version.
- **Plan review.** Before you edit code for a task, send that task (its survey lines, routes, failure states and tests) to an independent teacher sub-agent for a missing-cases review, as `AGENTS.md` asks.
- **Code style.** `CLAUDE.md`: dense fastai style, one-line docstrings, no banner comments, rationale in `docs/`. Never hand-roll what abhyasa, rupaka, kosha, fastcore or shalya does.
- **No second copy without a reason.** A copy of an abhyasa function needs a one-line comment that gives the reason and names `leela-reuse.md`, and a test that pins the shared version.
- **Tests never reach the owner's data.** Use `Workspace(roots=[tmp_path])` and `Memory(path=tmp_path/'vault.db', offline=True)`. `tests/conftest.py` already patches `projects.SERVING` and `XDG_CONFIG_HOME`; Task 0 adds `ABHYASA_CONFIG`, because abhyasa's `cfg_dir()` ignores `XDG_CONFIG_HOME`. Never open the running Leela on ports 5010-5019 or its real workspace.
- **Processes.** Never kill a process by name. A test stops only the processes it started.
- **Browser checks.** Playwright's bundled Chromium (`p.chromium.launch(headless=True)`, no `executable_path`, no `channel`), or `$FASTCDP_CHROME` through fastcdp. Never `/Applications/Google Chrome.app`, port 9223 or `~/.cache/fastcdp/cdp-chrome`. One browser at a time, closed in a `finally`, audio muted, no window that takes the focus. Browser tests go in `*_slow.py` files.
- **Network.** Only the tool environment install (Task 8) uses the network, and only in a job. No test uses the network unless `LEELA_NET_TESTS=1` is set.
- **JS bundle.** A new block `.js` file goes into `LAYERS` in `tools/build_ide_js.py`; rebuild the bundle with that tool.
- **Routes.** Add each new route to `tests/routes.txt`.
- **Prose.** UI text, docs and commit messages are ASD-STE100 Simplified Technical English, US grade 9. No em dashes. Read the `write_docs` pyskill before docstrings and commit messages.
- **Commits.** One plain line for each task. No AI credit. No `Co-Authored-By` line.
- **Pass gate for each task.** The task's own tests, then `uv run pytest -q -x --ignore-glob='*_slow.py'`, then the task's slow tests when it has them.

## Review Focus

1. **A cross-site page drives `/learn`.** Another site links to, frames or posts to `/learn`. Expected: the GET writes nothing (no file, tab, attempt or job), the page cannot be framed, and a cross-site POST gets 421. Tests: `test_learn_shows_the_step_and_writes_nothing`, `test_guard_lets_only_a_learn_navigation_cross_site` (Task 4), `test_open_makes_one_lesson_and_reopens_it` (Task 5).
2. **A hostile or stale handoff query.** `walk=../x`, a negative or too-large step, no keys, an unknown walk, HTML in the stored passage. Expected: 400 with the reason, or the one line "This walk is not in your learning store.", never a traceback, and escaped text. Tests: `test_learn_refuses_bad_queries`, `test_learn_shows_the_step_and_writes_nothing` (Task 4).
3. **A forged or repeated prediction.** The page sends `ok: true` for a wrong pick, a gate that is not in the cell, or the same gate twice. Expected: the server computes `ok` from the notebook, refuses an unknown gate, and logs one attempt. Test: `test_predict_ok_is_server_side_and_once`, `test_predict_refuses_a_gate_that_is_not_in_the_cell` (Task 1).
4. **A pane message from the wrong place.** A message from another origin or another frame, or an off-app URL in `rh:at` or `rh:open`, or HTML in `rh:done`. Expected: ignored, the pane URL does not change, and the `rh:done` detail goes on as data only. Tests: `test_is_local_matches_abhyasa`, `test_pane_host_takes_only_its_own_frame` (Task 6).
5. **A package name or learner code that tries to get out.** A name that is an option, a URL or a path; more than 5 names; learner code that connects a socket, starts a process, writes outside its folder, prints a fake result line or hangs; asyncio that needs a socket pair. Expected: the names are refused before `uv` runs; the hostile code fails or stops within the 20 s total; the socket pair works and `connect` fails. Tests: `test_tool_names_refuse_options_urls_and_paths` (Task 8), `test_library_check_closed_and_asyncio_ok` (Task 10).

---

### Task 0: Pin abhyasa >= the next version once it is released

The next abhyasa release carries the walk (abhyasa plan Tasks 3, 7, 11 and 14). The walk branch has `__version__ = "0.0.11"`. Use the number that is released; the plan writes `0.0.11`.

**Needs abhyasa:** the release with `abhyasa.journey.LEELA_ROUTE`, `handoff`, `read_handoff`, `HANDOFF_CASES`, `walk_state`, `Learning.put_journey`; `abhyasa.prompts`; `abhyasa.check.run_isolated`.
**Touches the ramabana agent's files:** yes, `tests/test_abhyasa_contract.py`.

**Files:**
- Modify: `pyproject.toml` (`abhyasa>=0.0.11,<0.1`; add `rupaka==<the version that abhyasa 0.0.11 requires>`), `uv.lock`
- Modify: `tests/conftest.py` (`ABHYASA_CONFIG` under the test config home)
- Test: `tests/test_abhyasa_contract.py`

**Interfaces (consumed from abhyasa):**
- `abhyasa.journey.handoff(jid:str='', i:int|None=None, topic:str='') -> str`
- `abhyasa.journey.read_handoff(query:str) -> AttrDict(walk:str, step:int|None, topic:str)`; `ValueError` names the bad key
- `abhyasa.journey.HANDOFF_CASES: list[tuple[dict, str]]`, `LEELA_ROUTE = '/learn'`
- `abhyasa.journey.walk_state(j) -> AttrDict(steps, current, done, total, sections)`
- `abhyasa.prompts.prompt(name:str) -> str`, `register(name, label, note, dflt, check=None) -> str`, `set_prompt(name, text='') -> str`, `PROMPTS`
- `abhyasa.check.run_isolated(kind, fname, source, tests, *, total=10., setup=(), sandbox=True) -> dict`

- [ ] **Step 1: Write the failing tests**

```python
# tests/conftest.py, beside the XDG_CONFIG_HOME line at the top
_os.environ['ABHYASA_CONFIG'] = _os.path.join(TEST_CONFIG_HOME, 'abhyasa')   # abhyasa's cfg_dir() ignores XDG_CONFIG_HOME
```

```python
# tests/test_abhyasa_contract.py
def test_abhyasa_dependency_floor():
    deps = tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['dependencies']
    assert 'abhyasa>=0.0.11,<0.1' in deps
    assert any(re.fullmatch(r'rupaka==\d+\.\d+\.\d+', d) for d in deps)

def test_learn_handoff():
    from abhyasa.journey import LEELA_ROUTE, HANDOFF_CASES, handoff, read_handoff
    assert LEELA_ROUTE == '/learn'
    for kw, path in HANDOFF_CASES:
        assert handoff(**kw) == path
        q = read_handoff(path.split('?', 1)[1])
        assert (q.walk, q.step, q.topic) == (kw.get('jid', ''), kw.get('i'), kw.get('topic', ''))
    for bad in ('walk=../x', 'walk=a-1&step=-1', ''):
        with pytest.raises(ValueError): read_handoff(bad)

def test_prompts_contract():
    import abhyasa.tutor
    from abhyasa.prompts import PROMPTS, prompt
    assert 'tutor' in PROMPTS and prompt('tutor') == PROMPTS['tutor'].dflt   # ABHYASA_CONFIG is a temp folder: no saved text

def test_run_isolated_contract():
    from abhyasa.check import run_isolated
    ps = inspect.signature(run_isolated).parameters
    assert list(ps)[:4] == ['kind', 'fname', 'source', 'tests'] and {'total', 'setup', 'sandbox'} <= ps.keys()

def test_journey_contract():
    from abhyasa.journey import walk_state
    from abhyasa.store import Learning
    assert all(hasattr(Learning, n) for n in ('put_journey', 'journey', 'journeys'))
    assert walk_state(dict(steps=[dict(slug='a', status='done'), dict(slug='b')])).current == 1
```

In `test_pure_imports_in_isolated_python`, add `abhyasa.journey, abhyasa.prompts, abhyasa.check` to the import line.

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_abhyasa_contract.py -q`
Expected: FAIL. `test_abhyasa_dependency_floor` (the old floor), `ImportError: cannot import name 'HANDOFF_CASES' from 'abhyasa.journey'`, `ModuleNotFoundError: No module named 'abhyasa.prompts'`, `ModuleNotFoundError: No module named 'abhyasa.check'`.

- [ ] **Step 3: Implement**
  - Edit `pyproject.toml`. Run `uv lock --upgrade-package abhyasa --upgrade-package rupaka`, then `uv sync`.
  - Check that `uv.lock` names the released abhyasa and the exact rupaka. Do not edit `uv.lock` by hand.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_abhyasa_contract.py tests/test_lesson.py tests/test_exercise.py -q && uv run pytest -q -x --ignore-glob='*_slow.py'`
Expected: PASS. `test_rupaka_vendor_version` can still `xfail` here when rupaka moved; Task 2 makes it a real failure.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock tests/conftest.py tests/test_abhyasa_contract.py
git commit -m "Pin abhyasa 0.0.11 and rupaka, and test the handoff, prompts, runner and journey contracts"
```

---

### Task 1: Log rupaka predictions in a lesson

**Needs abhyasa:** `Learning.record(**meta)` and `abhyasa.model.update` (both in 0.0.9 already). No new API.
**Touches the ramabana agent's files:** yes, `leela/blocks/nb/lesson.py`.

**Files:**
- Modify: `leela/blocks/nb/lesson.py` (`demo_gate`, `record_prediction`)
- Modify: `leela/blocks/nb/app.py` (`POST /lesson/predict`)
- Modify: `leela/blocks/nb/lesson.js` (the `rk-predict` listener)
- Modify: `tests/routes.txt`
- Test: `tests/test_lesson_predict.py`, and one browser case in `tests/test_lesson_slow.py`

**Interfaces:**
- `demo_gate(cell, gate:str) -> dict|None`: the `gate` block with id `gate` in the `rupaka` fences of markdown `cell`, searched through nested `blocks`; None when there is none.
- `record_prediction(memory, nb, cell, path:str, gate:str, picked, why:str='') -> bool`: one attempt for key `f'{cell.id}:{src_hash(cell.source)}:{gate}'`; True when it logged, False when the key was already there. `ok = picked == g['answer']`, computed here. Fields: `concept=slugify(nb.meta['lesson']['name'])`, `question=g.get('prompt', gate)`, `answer=str(picked)`, `thinking=why`, `correct=ok`, `depth=3 if why.strip() else 2`, `kind='demo'`, `feedback=f'The answer is {g["answer"]}.'`, meta `notebook=path`, `card_key=key`, `gate=gate`, `demo=spec.get('id', '')`. The concept is updated with `update(c, depth, ok)` in the same `write_txn`, under `_open_lock`, as `record_card` does.
- `POST /lesson/predict` JSON `{path, cell_id, gate, picked, why}` returns `{ok: True, logged: bool}`; `fail(...)` 400 for an unknown cell or gate; `{ok: True, logged: False}` for a notebook with no `lesson` meta. It ignores `ok` and `ans` from the page.
- `lesson.js`: `document.addEventListener('rk-predict', e => ...)`. The cell is `e.composedPath().find(n => n.matches?.('.lee-cell[data-id]'))`. With no cell, or a notebook that is not a lesson, the listener does nothing. It posts with the existing `api` helper and shows the server's message in the status line.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_lesson_predict.py
import sys
import pytest
from starlette.testclient import TestClient
from abhyasa.store import Learning
from leela.app import ide_app
from leela.blocks.memory.memory import Memory
from leela.blocks.nb.lesson import fence, lesson_notebook
from leela.blocks.nb.nb import Cell, Notebook
from leela.workspace import Workspace

DEMO = {'id': 'halves', 'blocks': [{'type': 'stack', 'blocks': [
    {'type': 'gate', 'id': 'g1', 'prompt': 'What is half of 8?', 'options': [2, 4, 6], 'answer': 4}]}]}

def client(tmp_path, monkeypatch, nb):
    p = tmp_path/'lesson.ipynb'; nb.save(p)
    ws = Workspace(roots=[tmp_path], approvals='auto', python=sys.executable)
    monkeypatch.setattr(ws, 'memory', Memory(path=tmp_path/'vault.db', offline=True))
    ws.open(p)
    return ws, p

@pytest.fixture
def rig(tmp_path, monkeypatch):
    nb = lesson_notebook('Halves'); nb[1].source = fence(DEMO)
    ws, p = client(tmp_path, monkeypatch, nb)
    try:
        with TestClient(ide_app(ws)) as c:
            c.get('/tab/state')
            yield c, ws, p, nb
    finally: ws.shutdown_now()

def post(c, p, cell_id, gate='g1', **kw): return c.post('/lesson/predict', json=dict(path=str(p), cell_id=cell_id, gate=gate, **kw))

def test_predict_ok_is_server_side_and_once(rig):
    c, ws, p, nb = rig
    r = post(c, p, nb[1].id, picked=2, why='', ok=True, ans=2)            # the page says right; 2 is wrong
    assert r.status_code == 200 and r.json() == {'ok': True, 'logged': True}, r.text
    assert post(c, p, nb[1].id, picked=4, why='half').json()['logged'] is False   # "try again" logs nothing
    rows = Learning(ws.memory._store('learning')).attempts('halves', limit=10)
    assert len(rows) == 1
    a = rows[0]
    assert (a.kind, bool(a.correct), a.depth, a.answer, a.question) == ('demo', False, 2, '2', 'What is half of 8?')
    assert a.notebook == str(p) and a.card_key.endswith(':g1') and a.gate == 'g1' and a.demo == 'halves'

def test_predict_refuses_a_gate_that_is_not_in_the_cell(rig):
    c, ws, p, nb = rig
    r = post(c, p, nb[1].id, gate='nope', picked=4)
    assert r.status_code == 400 and 'no gate' in r.json()['error']
    assert post(c, p, 'missing', picked=4).status_code == 400
    assert post(c, p, nb[0].id, picked=4).status_code == 400              # a cell with no demo
    assert len(Learning(ws.memory._store('learning')).attempts('halves', limit=10)) == 0

def test_predict_in_a_plain_notebook_logs_nothing(tmp_path, monkeypatch):
    nb = Notebook([Cell(source=fence(DEMO), cell_type='markdown')])
    ws, p = client(tmp_path, monkeypatch, nb)
    try:
        with TestClient(ide_app(ws)) as c:
            c.get('/tab/state')
            assert post(c, p, nb[0].id, picked=4).json() == {'ok': True, 'logged': False}
    finally: ws.shutdown_now()
```

Browser case in `tests/test_lesson_slow.py`, with the server fixture that file already uses: open the lesson above, click option 4 and "Check" inside the demo's shadow root, and wait until `/lesson/predict` answers `logged: true`.

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_lesson_predict.py -q`
Expected: FAIL with status 404 on `/lesson/predict`.

- [ ] **Step 3: Implement**
  - `demo_gate`: parse each `rupaka` fence of the cell with `fenced_blocks` (already imported in `lesson.py`) and `json.loads`; skip a fence that does not parse.
  - The route takes `lesson_lock` and reads the notebook through `run_owner(d)`, as `/lesson/save` does; it runs `record_prediction` with `off_loop`; an `ImportError` or a locked vault gives the same messages as `/lesson/save`.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_lesson_predict.py tests/test_lesson_save.py -q && uv run pytest tests/test_lesson_slow.py -q -k predict`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add leela/blocks/nb tests/test_lesson_predict.py tests/test_lesson_slow.py tests/routes.txt
git commit -m "Log a rupaka gate in a lesson as one demo attempt, with the answer checked on the server"
```

---

### Task 2: One rupaka version for the bundle and the validator

**Needs abhyasa:** the rupaka pin from Task 0.
**Touches the ramabana agent's files:** yes, `tests/test_abhyasa_contract.py`.

**Files:**
- Modify: `leela/vendor/lee-rupaka.js`, `leela/vendor/lee-rupaka.css` (written again from the pinned wheel)
- Modify: `leela/vendor/README` (wheel name, URL, SHA-256)
- Test: `tests/test_abhyasa_contract.py` (`test_rupaka_vendor_version`), `tests/test_rupaka.py` (`test_the_vendored_rupaka_is_the_version_the_readme_pins`)

**Interfaces:** none new. The vendored `Rupaka.version`, the README wheel name, `rupaka.__version__` and the `rupaka==` pin are one value.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_abhyasa_contract.py: no xfail
def test_rupaka_vendor_version():
    import rupaka
    version = re.search(r"\bversion:\s*'([^']+)'", (ROOT/'leela'/'vendor'/'lee-rupaka.js').read_text()).group(1)
    assert version == rupaka.__version__, f'vendored rupaka {version}, installed {rupaka.__version__}: write the bundle again (leela/vendor/README)'
    deps = tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['dependencies']
    assert f'rupaka=={version}' in deps
```

```python
# tests/test_rupaka.py
def test_the_vendored_rupaka_is_the_version_the_readme_pins():
    "A stale or half-copied vendor file fails here, not in a user's notebook."
    import rupaka
    v, js = rupaka.__version__, (ROOT/'vendor'/'lee-rupaka.js').read_text()
    assert f"version: '{v}'" in js and 'R.mount' in js
    assert f'rupaka-{v}-py3-none-any.whl' in (ROOT/'vendor'/'README').read_text()
    assert '.rk' in (ROOT/'vendor'/'lee-rupaka.css').read_text()
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_abhyasa_contract.py::test_rupaka_vendor_version tests/test_rupaka.py -q`
Expected: FAIL with `vendored rupaka 0.0.1, installed <pinned>`. When the pin is still 0.0.1, the tests pass at once; the change is still needed, because the `xfail` is gone.

- [ ] **Step 3: Implement**
  - Follow `leela/vendor/README`: download the pinned wheel into a new empty folder, check its SHA-256 against PyPI, and write both bundles with the wheel's own `rupaka.render.bundle`, with `uv run --no-project --with <wheel> python -I`.
  - Update the README line: version, wheel name, URL, digest.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_abhyasa_contract.py tests/test_rupaka.py tests/test_rupaka_slow.py -q`
Expected: PASS. The Node mount cases in `test_rupaka.py` still pass with the new bundle.

- [ ] **Step 5: Commit**

```bash
git add leela/vendor tests/test_abhyasa_contract.py tests/test_rupaka.py
git commit -m "Vendor the pinned rupaka and fail when the bundle and the installed rupaka differ"
```

---

### Task 3: Read the tutor prompt through abhyasa.prompts

**Needs abhyasa:** `abhyasa.prompts.prompt`, `set_prompt`, `PROMPTS['tutor']` (registered by `abhyasa.tutor`).
**Touches the ramabana agent's files:** yes, `leela/blocks/nb/lesson.py`.

**Files:**
- Modify: `leela/blocks/nb/lesson.py` (`CHARTER_TAIL`, `lesson_charter`; remove `LESSON_CHARTER`)
- Modify: `leela/blocks/agent/ai.py` (`:1244`, `:1267`, `:1307`)
- Modify: each test that imports `LESSON_CHARTER` (`grep -rn LESSON_CHARTER tests`)
- Test: `tests/test_lesson_prompt.py`

**Interfaces:**
- `CHARTER_TAIL: str`: the Leela text after the tutor prompt (the hint ladder, the demo, method and exercise rules), as in today's `LESSON_CHARTER`.
- `lesson_charter(step:dict|None=None) -> str`: `prompt('tutor') + CHARTER_TAIL`, read at each call. `step` is added in Task 11; here it is unused.
- `ai.py`: the briefed test becomes `CHARTER_TAIL in prompt`, so a changed tutor prompt does not look like a missing charter; `system_prompt` adds `lesson_charter()`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_lesson_prompt.py
import abhyasa.tutor
from abhyasa.prompts import PROMPTS, set_prompt
from leela.blocks.nb.lesson import CHARTER_TAIL, lesson_charter

def test_charter_reads_the_saved_tutor_prompt():
    assert lesson_charter() == PROMPTS['tutor'].dflt + CHARTER_TAIL
    set_prompt('tutor', 'Ask one question at a time. Never give the answer.')
    try: assert lesson_charter() == 'Ask one question at a time. Never give the answer.' + CHARTER_TAIL
    finally: set_prompt('tutor', '')
    assert 'Hint ladder:' in CHARTER_TAIL and 'add_exercise' in CHARTER_TAIL
```

Add one case to `tests/test_lesson_agent.py`: with a saved tutor prompt, the agent's `system_prompt()` in a lesson tab holds that text and `CHARTER_TAIL`, and the briefed flag is true.

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_lesson_prompt.py -q`
Expected: FAIL with `ImportError: cannot import name 'CHARTER_TAIL'`.

- [ ] **Step 3: Implement.** Import `prompt` from `abhyasa.prompts` inside `lesson_charter` and `import abhyasa.tutor` once at module top, so the `tutor` prompt is registered.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_lesson_prompt.py tests/test_lesson_agent.py tests/test_exercise_agent.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add leela/blocks/nb/lesson.py leela/blocks/agent/ai.py tests
git commit -m "Read the tutor prompt from abhyasa at each briefing, so the owner's edits reach Leela"
```

---

### Task 4: The /learn route: show a walk step from a link

**Needs abhyasa:** `read_handoff`, `walk_state`, `Learning.journey`, `slugify`.
**Touches the ramabana agent's files:** no.

**Files:**
- Create: `leela/blocks/learn/learn.py` (`find_step`), `leela/blocks/learn/ui.py` (`StepPage`, `Line`)
- Modify: `leela/blocks/learn/app.py` (`GET /learn`)
- Modify: `leela/hub.py` (`learn_navigation`, used by `LoopbackHostGuard`)
- Modify: `tests/routes.txt`
- Test: `tests/test_learn_route.py`

**Interfaces:**
- `find_step(lr, q) -> AttrDict`: `q` is the `read_handoff` result. Returns `AttrDict(kind='step', j=journey, i=int, step=dict, name=str)`, `AttrDict(kind='done', j=journey)`, `AttrDict(kind='topic', name=str, concept=dict|None)` or `AttrDict(kind='missing')`. Raises `ValueError(f'step: this walk has no step {i}')` for a step out of range.
- `StepPage(v, q, pane:bool=False) -> FT`: the title, the section, the passage and the note as escaped text, the concept, and `Form(..., method='post', action='/learn/open')` with hidden `walk`, `step` and `topic` and the button "Open as a lesson".
- `GET /learn`: `read_handoff(req.url.query)`; `ValueError` gives 400 plain text; a store error gives 503 "The learning store is locked or cannot be read."; `missing` gives 200 "This walk is not in your learning store."; `done` gives 200 "This walk is done." Headers on every answer: `Content-Security-Policy: frame-ancestors 'self'`, `Referrer-Policy: no-referrer`. It writes nothing.
- `learn_navigation(scope, headers) -> bool`: True only for `GET` on `/learn` with `sec-fetch-mode: navigate` and `sec-fetch-dest: document`. `LoopbackHostGuard` sets `browser_ok = ... or learn_navigation(scope, headers)`. The Host check does not change.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_learn_route.py
import asyncio, sys
from unittest.mock import Mock
import pytest
from starlette.testclient import TestClient
from abhyasa.store import Learning
from leela.app import ide_app
from leela.blocks.memory.memory import Memory
from leela.workspace import Workspace

JID = 'attention-ab12'

def walk(lr):
    lr.put('Softmax'); lr.put('Attention')
    steps = [dict(slug='softmax', status='todo', read=dict(section='2 Background', text='Softmax maps scores to weights.'),
                  note='Watch the sum.', check=dict(kind='short', way='words')),
             dict(slug='attention', status='todo', read=dict(section='', text='<script>x()</script> Attention mixes values.'),
                  note='', check=dict(kind='short', way='words'), leela=True)]
    return lr.put_journey(dict(id=JID, title='Attention', goal='', steps=steps, mode='walk', tool=True))

@pytest.fixture
def rig(tmp_path, monkeypatch):
    ws = Workspace(roots=[tmp_path], approvals='auto', python=sys.executable)
    monkeypatch.setattr(ws, 'memory', Memory(path=tmp_path/'vault.db', offline=True))
    lr = Learning(ws.memory._store('learning')); j = walk(lr)
    try:
        with TestClient(ide_app(ws), base_url='http://127.0.0.1:5011') as c: yield c, ws, lr, j, tmp_path
    finally: ws.shutdown_now()

def test_learn_shows_the_step_and_writes_nothing(rig):
    c, ws, lr, j, root = rig
    before = (lr.journey(JID), sorted(root.rglob('*.ipynb')), len(ws.tabs))
    r = c.get(f'/learn?walk={JID}&step=0')
    assert r.status_code == 200 and 'Softmax maps scores to weights.' in r.text and 'Watch the sum.' in r.text
    assert "frame-ancestors 'self'" in r.headers['content-security-policy'] and r.headers['referrer-policy'] == 'no-referrer'
    assert 'action="/learn/open"' in r.text and 'method="post"' in r.text
    r = c.get(f'/learn?walk={JID}&step=1')
    assert '<script>x()' not in r.text and '&lt;script&gt;' in r.text                     # store text is text
    assert 'Softmax maps scores to weights.' in c.get(f'/learn?walk={JID}').text           # no step: the current step
    assert (lr.journey(JID), sorted(root.rglob('*.ipynb')), len(ws.tabs)) == before        # the GET wrote nothing

@pytest.mark.parametrize('q, code, text', [
    ('walk=../x', 400, 'walk'), ('walk=a-1&step=-1', 400, 'step'), ('', 400, 'nothing to open'),
    (f'walk={JID}&step=9', 400, 'no step 9'), ('walk=gone-0000', 200, 'This walk is not in your learning store.')])
def test_learn_refuses_bad_queries(rig, q, code, text):
    r = rig[0].get('/learn?' + q)
    assert r.status_code == code and text in r.text and 'Traceback' not in r.text

def test_learn_opens_a_topic(rig):
    c = rig[0]
    assert 'Softmax' in c.get('/learn?topic=Softmax').text
    assert 'Agents and tools' in c.get('/learn?topic=Agents+and+tools').text              # not on the shelf: the name

def guard(path, h, method='GET'):
    from leela.hub import LoopbackHostGuard
    seen, sent = [], []
    async def app(scope, receive, send): seen.append(scope['path'])
    async def send(m): sent.append(m)
    h = {'host': '127.0.0.1:5011', **h}
    asyncio.run(LoopbackHostGuard(app)({'type': 'http', 'method': method, 'path': path,
        'headers': [(k.encode(), v.encode()) for k, v in h.items()]}, Mock(), send))
    return 'passed' if seen else sent[0]['status']

NAV = {'sec-fetch-site': 'cross-site', 'sec-fetch-mode': 'navigate', 'sec-fetch-dest': 'document'}

def test_guard_lets_only_a_learn_navigation_cross_site():
    assert guard('/learn', NAV) == 'passed'
    assert guard('/learn', {**NAV, 'sec-fetch-mode': 'cors'}) == 421
    assert guard('/learn', {**NAV, 'sec-fetch-dest': 'iframe'}) == 421
    assert guard('/learn', NAV, 'POST') == 421 and guard('/learn/open', NAV, 'POST') == 421
    assert guard('/tab/state', NAV) == 421
    assert guard('/learn', {**NAV, 'host': 'evil.example'}) == 421                       # the Host check stays
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_learn_route.py -q`
Expected: FAIL with 404 on `/learn` and 421 for the cross-site navigation.

- [ ] **Step 3: Implement**
  - The route opens `Learning(memory._store('learning'))` under `_open_lock` in `off_loop`, as `due_cards` does, after `import abhyasa.journey`.
  - Text is FT children only (FastHTML escapes them). Never `NotStr` for store text.
  - The page links nothing outside Leela.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_learn_route.py tests/test_web.py tests/test_lesson_due.py -q && uv run pytest -q -x --ignore-glob='*_slow.py'`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add leela/blocks/learn leela/hub.py tests/test_learn_route.py tests/routes.txt
git commit -m "Add /learn: show a walk step or a topic from an abhyasa link, and write nothing"
```

---

### Task 5: Open the step as a lesson, and log the checks back

**Needs abhyasa:** `read_handoff`, `Learning.journey`, `Learning.record(**meta)`.
**Touches the ramabana agent's files:** yes, `leela/blocks/nb/lesson.py` (`lesson_notebook`, `walk_meta`, `record_card`, `exercise_filing`, `record_exercise`, `record_prediction`).

**Files:**
- Modify: `leela/blocks/nb/lesson.py`
- Modify: `leela/blocks/learn/learn.py` (`open_step`), `leela/blocks/learn/app.py` (`POST /learn/open`; `CAPS = ('memory', 'fs')`)
- Modify: `tests/routes.txt`
- Test: `tests/test_learn_route.py`, `tests/test_lesson_walk.py`

**Interfaces:**
- `lesson_notebook(name, exercise=None, step:dict|None=None) -> Notebook`: with `step = dict(walk, step, section, text, note)`, the first cell is the heading, the passage as a Markdown quote and the note; `meta['lesson']['walk'] = dict(walk=…, step=…, section=…)`. Cell positions do not change, so `lesson_notebook(name)` stays as today.
- `walk_meta(nb) -> dict`: `{}` with no walk; else `dict(walk=jid, step=i, section=s, app='leela', **{'from': f'{jid}/{i}'})`, with `section` only when it is not empty.
- `record_card`, `record_exercise` (through `exercise_filing`, which copies `walk_meta(nb)` under `walk`) and `record_prediction` pass `**walk_meta(nb)` to `lr.record`.
- `open_step(session, fs, lr, q) -> Path`: writes `lessons/<walk>-<step>.ipynb`, or `lessons/<slug>.ipynb` for a topic, with `fs._check` and `sandbox=fs`, as `/lesson/new` does; reopens a file whose meta names the same walk and step, and writes nothing then. Raises `ValueError('Open a folder in Leela, then open this link again.')` when `session.project_root` is None or the loose root; `ValueError` for a symbolic-link `lessons` folder.
- `POST /learn/open` (form `walk`, `step`, `topic`): `read_handoff` on the form; `open_step`; `session.open_external(path)`; 200 with the line "Opened in Leela."; `ValueError` gives 400 with its text. It never calls `put_journey`, `walk_step` or `journey_step`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_learn_route.py: add
from leela.blocks.nb.nb import Notebook

def test_open_makes_one_lesson_and_reopens_it(rig):
    c, ws, lr, j, root = rig
    before = lr.journey(JID)
    r = c.post('/learn/open', data=dict(walk=JID, step='0'))
    assert r.status_code == 200 and 'Opened in Leela.' in r.text, r.text
    p = root/'lessons'/f'{JID}-0.ipynb'
    nb = Notebook.load(p)
    assert nb.meta['lesson']['walk'] == dict(walk=JID, step=0, section='2 Background')
    assert 'Softmax maps scores to weights.' in nb[0].source and 'Watch the sum.' in nb[0].source
    assert ws.tab.path == str(p)
    t = p.stat().st_mtime_ns
    assert c.post('/learn/open', data=dict(walk=JID, step='0')).status_code == 200
    assert p.stat().st_mtime_ns == t and list((root/'lessons').glob('*.ipynb')) == [p]
    assert lr.journey(JID) == before                                                      # Leela never writes the journey

def test_open_refuses_a_bad_form_and_no_folder(rig, tmp_path, monkeypatch):
    assert rig[0].post('/learn/open', data=dict(walk='../x')).status_code == 400
    ws = Workspace(roots=[], approvals='auto', python=sys.executable)
    monkeypatch.setattr(ws, 'memory', Memory(path=tmp_path/'other.db', offline=True))
    walk(Learning(ws.memory._store('learning')))
    try:
        with TestClient(ide_app(ws), base_url='http://127.0.0.1:5011') as c:
            r = c.post('/learn/open', data=dict(walk=JID, step='0'))
            assert r.status_code == 400 and 'Open a folder in Leela' in r.text
    finally: ws.shutdown_now()
```

```python
# tests/test_lesson_walk.py
from fastcore.basics import first
from abhyasa.store import Learning
from leela.blocks.memory.memory import Memory
from leela.blocks.nb.lesson import lesson_notebook, lock, record_card, walk_meta

STEP = dict(walk='attention-ab12', step=0, section='2 Background', text='Softmax maps scores to weights.', note='Watch the sum.')

def test_walk_meta():
    assert walk_meta(lesson_notebook('Softmax', step=STEP)) == {
        'walk': 'attention-ab12', 'step': 0, 'section': '2 Background', 'from': 'attention-ab12/0', 'app': 'leela'}
    assert walk_meta(lesson_notebook('Softmax', step={**STEP, 'section': ''})).keys() == {'walk', 'step', 'from', 'app'}
    assert walk_meta(lesson_notebook('Softmax')) == {}

def test_a_card_from_a_walk_lesson_carries_the_walk_meta(tmp_path):
    mem, nb = Memory(path=tmp_path/'vault.db', offline=True), lesson_notebook('Softmax', step=STEP)
    code = nb[3]; code.source, code.execution_count = 'print(1)', 1
    code.outputs = [{'output_type': 'stream', 'name': 'stdout', 'text': '1\n'}]
    lock(code, '1')
    record_card(mem, nb, code, str(tmp_path/'softmax.ipynb'))
    a = first(Learning(mem._store('learning')).attempts('softmax', limit=5))
    assert (a.kind, a.walk, a.step, a['from'], a.app, a.section) == ('predict', 'attention-ab12', 0, 'attention-ab12/0', 'leela', '2 Background')
```

Add the same meta assertion to one exercise case in `tests/test_exercise_grade.py` (a lesson made with `step=STEP`, a graded full pass, the `code` attempt carries the walk meta) and to `test_predict_ok_is_server_side_and_once` with a walk lesson.

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_learn_route.py tests/test_lesson_walk.py -q`
Expected: FAIL with 404 on `/learn/open` and `ImportError: cannot import name 'walk_meta'`.

- [ ] **Step 3: Implement.** Keep `record_card` and `record_exercise` as they are apart from the meta. The `from` key is a Python keyword, so pass it in a dict.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_learn_route.py tests/test_lesson_walk.py tests/test_lesson_save.py tests/test_lesson_route.py tests/test_exercise_grade.py tests/test_lesson_predict.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add leela/blocks/nb/lesson.py leela/blocks/learn tests
git commit -m "Open a walk step as a lesson notebook and log its checks with the walk, step and app"
```

---

### Task 6: The split pane host

**Needs abhyasa:** none at run time. The test compares `is_local` with `abhyasa.core.pane.is_local` (walk release).
**Touches the ramabana agent's files:** no.

**Files:**
- Modify: `leela/blocks/learn/learn.py` (`is_local`, `pane_url`)
- Create: `leela/blocks/learn/pane.js` (`leePaneMessage`, `leePane`, the in-pane boot)
- Modify: `tools/build_ide_js.py` (`LAYERS`), and the built bundle
- Modify: `leela/static/lee-core.js` (`SPLIT_KINDS.page`, `mountPage`, the restore at `:2006`, `leeCloseSplit`)
- Modify: `leela/blocks/learn/ui.py` (`StepPage(pane=True)`: no chrome, `html.in-pane`)
- Test: `tests/test_learn_pane.py`

**Interfaces:**
- `is_local(url) -> bool`, `pane_url(url) -> str|None`: the same rules as `abhyasa/core/pane.py`. Comment: `# a copy of abhyasa.core.pane.is_local: abhyasa.core imports abhyasa's web UI (leela-reuse.md 5)`.
- `leePaneMessage(e, host) -> boolean`: takes `e` only when `e.origin === location.origin` and `e.source === host.frame.contentWindow`; `rh:at` with a local URL calls `host.at(url, title, trail)`; `rh:open` with a local URL calls `host.open(url)`; `rh:close` calls `host.close()`, or `host.back()` with `level: 1`; `rh:done` dispatches `new CustomEvent('abhyasa:rh-done', {detail: {slug: String(d.slug), outcome: String(d.outcome)}})` on `document`. Returns true when it acted.
- `leePane.open(url, title)`: calls `mountPage(pane_url(url), title)`. `leePane.close()`: `leeCloseSplit()`.
- `mountPage(url, title, direction='vertical')` in `lee-core.js`: the split head (title, "Own session ↗" to `url` without `pane=1` in a new tab, close), and an `iframe` with `src=url` and `title`; `localStorage['lee-editor-split'] = {page: url, title, direction}`. The restore at `:2006` mounts `split.page` with `mountPage` when `isLocal(split.page)`, else it removes the key.
- In a page with `html.in-pane`: send `{type: 'rh:at', url: location.pathname + location.search, title: document.title, trail}` to `parent` on load with `targetOrigin = location.origin`; Esc, when the focus is not in a text box, sends `{type: 'rh:close', level: 1}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_learn_pane.py
import json, shutil, subprocess
from pathlib import Path
import pytest
from leela.blocks.learn.learn import is_local, pane_url

PANE_JS = Path(__file__).parents[1]/'leela'/'blocks'/'learn'/'pane.js'
GOOD = ['/learn?walk=a-1&step=0', '/learn/lookup?q=Agent']
BAD = ['https://evil.example/x', '//evil.example', '/\\evil.example', 'javascript:alert(1)', 'w/g', '', None, '/learn\x00x']

def test_is_local_matches_abhyasa():
    from abhyasa.core.pane import is_local as theirs, pane_url as their_url
    for u in GOOD + BAD: assert is_local(u) == theirs(u) and pane_url(u) == their_url(u), u
    assert pane_url('/learn?walk=a-1') == '/learn?walk=a-1&pane=1' and pane_url('//evil.example') is None

HARNESS = r'''
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const events = [], st = {at: null, opened: [], closed: 0, back: 0};
global.location = {origin: 'http://127.0.0.1:5011'};
global.document = {dispatchEvent: e => events.push(e.detail), documentElement: {classList: {contains: () => false}}, addEventListener() {}};
global.CustomEvent = class { constructor(t, o) { this.type = t; this.detail = o.detail; } };
eval(src);
const frame = {contentWindow: {}};
const host = {frame, at: u => st.at = u, open: u => st.opened.push(u), close: () => st.closed++, back: () => st.back++};
const m = (data, origin = location.origin, source = frame.contentWindow) => leePaneMessage({data, origin, source}, host);
m({type: 'rh:at', url: '/learn?walk=a-1&step=0&pane=1', title: 'Softmax', trail: []});
m({type: 'rh:at', url: 'https://evil.example/'});
m({type: 'rh:open', url: '//evil.example'});
m({type: 'rh:close'}, 'http://evil.example');
m({type: 'rh:close'}, location.origin, {});
m({type: 'rh:done', slug: '<img src=x onerror=alert(1)>', outcome: 'passed'});
m({type: 'rh:close', level: 1});
console.log(JSON.stringify({st, events}));
'''

def test_pane_host_takes_only_its_own_frame():
    node = shutil.which('node')
    if not node: pytest.skip('node is not installed')
    r = subprocess.run([node, '-e', HARNESS, str(PANE_JS)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out['st'] == {'at': '/learn?walk=a-1&step=0&pane=1', 'opened': [], 'closed': 0, 'back': 1}
    assert out['events'] == [{'slug': '<img src=x onerror=alert(1)>', 'outcome': 'passed'}]   # data only, never HTML

def test_a_page_in_the_pane_has_no_chrome(rig):
    c = rig[0]
    t = c.get('/learn?walk=attention-ab12&step=0&pane=1').text
    assert 'in-pane' in t and 'id="tabbar"' not in t
```

Move `JID`, `walk` and the `rig` fixture of `tests/test_learn_route.py` into `tests/learn_data.py`, and import them in both files (`from learn_data import JID, rig, walk`).

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_learn_pane.py -q`
Expected: FAIL with `ImportError: cannot import name 'is_local'` and a missing `pane.js`.

- [ ] **Step 3: Implement.** `pane.js` defines functions only at the top level, with `function` declarations (the Node harness loads the file with `eval`, and a `const` would stay inside it); the in-pane boot runs from one `DOMContentLoaded` listener when `document.documentElement.classList.contains('in-pane')`. Add no key binding (Non-goals in the spec).

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run python tools/build_ide_js.py && uv run pytest tests/test_learn_pane.py tests/test_learn_route.py tests/blocks -q`
Expected: PASS, with the block-affinity test still green.

- [ ] **Step 5: Commit**

```bash
git add leela/blocks/learn leela/static tools/build_ide_js.py tests/test_learn_pane.py tests/learn_data.py tests/test_learn_route.py
git commit -m "Let the split editor hold a Leela page, with the pane messages and checks of abhyasa's pane"
```

---

### Task 7: kosha lookup in the side pane

**Needs abhyasa:** none.
**Touches the ramabana agent's files:** no.

**Files:**
- Modify: `leela/blocks/learn/learn.py` (`lookup`, `scratch_cell`)
- Modify: `leela/blocks/learn/app.py` (`GET /learn/lookup`, `POST /learn/scratch`; `CAPS` adds `search` and `tab`)
- Modify: `leela/blocks/learn/ui.py` (`LookupPage`)
- Modify: `tests/routes.txt`
- Test: `tests/test_learn_lookup.py`

**Interfaces:**
- `lookup(k, q:str, packages=(), limit:int=8) -> list[dict]`: `k` is a kosha handle (`kosha.Kosha` or `Search._kosha()`); calls `k.env_context(q, limit=limit, where=…)`, with a `package` filter when `packages` is given. Each row: `name`, `package`, `path`, `line`, `doc` (first line of `metadata.docstring`), `snippet` (at most 12 lines of `content`). Empty for an empty `q` or no handle.
- `scratch_cell(nb, snippet:str) -> Cell`: appends a code cell with `extra={'lesson': {'role': 'scratch'}}`; never changes an exercise cell.
- `GET /learn/lookup?q=…&tool=<key>`: a pane page; with `tool`, the handle is `Kosha(dir=tool_dir(key))` (Task 8; until then `tool` is ignored); with none, `ctx.search._kosha()`. kosha missing or not indexed gives one line, "No code index for this yet."
- `POST /learn/scratch` JSON `{path, snippet}`: `scratch_cell` on the open notebook, through the same owner and lock as the notebook routes; returns the cells.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_learn_lookup.py
from fastcore.basics import AttrDict
from leela.blocks.learn.learn import lookup, scratch_cell
from leela.blocks.nb.lesson import lesson_notebook

ROW = dict(content='def run_sync(self, prompt):\n    "Run the agent."\n' + 'x = 1\n' * 30, package='pydantic_ai',
           metadata=dict(name='run_sync', path='pydantic_ai/agent.py', lineno=40, docstring='Run the agent.\n\nMore.'))

class FakeKosha:
    def __init__(self): self.calls = []
    def env_context(self, q, **kw): self.calls.append((q, kw)); return [ROW]

def test_lookup_rows_and_package_filter():
    k = FakeKosha()
    rows = lookup(k, 'run sync', packages=['pydantic_ai'])
    assert rows == [dict(name='run_sync', package='pydantic_ai', path='pydantic_ai/agent.py', line=40,
                         doc='Run the agent.', snippet='\n'.join(ROW['content'].splitlines()[:12]))]
    assert 'pydantic_ai' in k.calls[0][1]['where']
    assert lookup(k, '') == [] and lookup(None, 'x') == []

SPEC = dict(task='Double it.', fname='double', stub='def double(x): pass',
            tests=[dict(say='doubles 2', test='assert double(2) == 4', shown=True)])

def test_scratch_never_touches_the_graded_cell():
    nb = lesson_notebook('Doubling', SPEC)
    graded = next(c for c in nb.cells if 'tests' in c.extra.get('exercise', {}))
    before, n = graded.source, len(nb.cells)
    c = scratch_cell(nb, 'from pydantic_ai import Agent')
    assert nb.cells[-1] is c and c.extra == {'lesson': {'role': 'scratch'}} and c.cell_type == 'code'
    assert graded.source == before and len(nb.cells) == n + 1
```

Add one route case to `tests/test_learn_route.py`: `GET /learn/lookup?q=x&pane=1` with no index gives 200 and "No code index for this yet."

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_learn_lookup.py -q`
Expected: FAIL with `ImportError: cannot import name 'lookup'`.

- [ ] **Step 3: Implement.** Use kosha's own row keys (`metadata.name`, `path`, `lineno`, `docstring`). Check the `where` form against `kosha.core.env_context` and `filt2wh`; quote package names with `?`-style values or `repr` only after they pass Task 8's name pattern.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_learn_lookup.py tests/test_learn_route.py tests/test_search*.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add leela/blocks/learn tests/test_learn_lookup.py tests/test_learn_route.py tests/routes.txt
git commit -m "Show kosha results for the lesson's library in the side pane, and copy a snippet to a scratch cell"
```

---

### Task 8: Tool environments

**Needs abhyasa:** none.
**Touches the ramabana agent's files:** no.

**Files:**
- Create: `leela/blocks/learn/tools.py`
- Modify: `leela/blocks/learn/app.py` (`POST /learn/tool`, `GET /learn/tool`; `CAPS` adds `jobs`)
- Modify: `leela/blocks/vault/clip.py` (`register_all` registers kind `tool_env`), or the learn block's `connect`, whichever `Jobs` reads first; check `workspace.py:236`
- Modify: `tests/routes.txt`
- Test: `tests/test_learn_tools.py`, `tests/test_learn_tools_slow.py` (real `uv`, only with `LEELA_NET_TESTS=1`)

**Interfaces:**
- `PKG = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}(\[[A-Za-z0-9._,-]{1,64}\])?((==|>=|<=|~=|<|>)[A-Za-z0-9.*+!-]{1,32})?')`, matched with `fullmatch`.
- `tool_names(names) -> list[str]`: sorted, unique; `ValueError` for no names, more than 5, or a name that does not match `PKG`.
- `tool_key(names, py=sys.version_info) -> str`: first 16 hex chars of `sha256(f'{py[0]}.{py[1]}\n' + '\n'.join(tool_names(names)))`.
- `tool_dir(key) -> Path`: `xdg_data_home()/'leela'/'tools'/key`.
- `tool_python(key) -> Path|None`: `tool_dir(key)/'.venv'/'bin'/'python'` when `ready` exists.
- `install_cmds(names, d:Path, uv:str, py=sys.version_info) -> list[list[str]]`: `[[uv, 'venv', str(d/'.venv'), '--python', f'{py[0]}.{py[1]}'], [uv, 'pip', 'install', '--python', str(d/'.venv'/'bin'/'python'), '--only-binary', ':all:', *tool_names(names)]]`.
- `make_tool_env(names, run=subprocess.run, uv=None) -> AttrDict(key, ok, python, error)`: removes a folder with no `ready`, runs `install_cmds` with `run(cmd, capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL)`, writes `ready` only when both succeed; on a failed install, `error` is "<name> has no wheel for this computer, so Leela cannot install it." when uv's stderr says no wheel, else uv's last stderr line.
- Job kind `tool_env`: `lambda job, report: make_tool_env(job.params['names'])`.
- `POST /learn/tool` JSON `{names}`: `tool_names`; returns `{ok, key, ready}` at once when ready, else starts the job and returns `{ok, key, job}`. `GET /learn/tool?key=…`: `{ok, ready, python}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_learn_tools.py
from pathlib import Path
from types import SimpleNamespace
import pytest
from leela.blocks.learn.tools import install_cmds, make_tool_env, tool_dir, tool_key, tool_names, tool_python

@pytest.fixture(autouse=True)
def data_home(tmp_path, monkeypatch): monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path/'data'))

@pytest.mark.parametrize('bad', [[], list('abcdef'), ['-e .'], ['--index-url=https://x'], ['https://x/p.whl'],
                                 ['../p'], ['/tmp/p'], ['p; rm -rf ~'], ['p @ file:///x'], ['git+https://x']])
def test_tool_names_refuse_options_urls_and_paths(bad):
    with pytest.raises(ValueError): tool_names(bad)

def test_names_key_and_commands():
    assert tool_names(['pydantic-ai-slim[openai]==1.0.2', 'httpx']) == ['httpx', 'pydantic-ai-slim[openai]==1.0.2']
    assert tool_key(['b', 'a'], (3, 13)) == tool_key(['a', 'b'], (3, 13)) != tool_key(['a', 'b'], (3, 12))
    d = tool_dir(tool_key(['httpx'], (3, 13)))
    assert install_cmds(['httpx'], d, '/u/uv', (3, 13)) == [
        ['/u/uv', 'venv', str(d/'.venv'), '--python', '3.13'],
        ['/u/uv', 'pip', 'install', '--python', str(d/'.venv'/'bin'/'python'), '--only-binary', ':all:', 'httpx']]

def fake(code_for):
    calls = []
    def run(cmd, **kw):
        calls.append(cmd)
        if cmd[1] == 'venv': (Path(cmd[2])/'bin').mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(returncode=code_for(cmd), stdout='', stderr='error: no wheel for sdist-only (no source builds allowed)')
    return run, calls

def test_ready_only_after_a_full_install():
    run, calls = fake(lambda c: 0)
    r = make_tool_env(['httpx'], run=run, uv='/u/uv')
    assert r.ok and tool_python(r.key) is not None and (tool_dir(r.key)/'ready').exists()
    assert all(isinstance(a, str) for c in calls for a in c)                                  # argv lists, no shell
    run, _ = fake(lambda c: 1 if c[1] == 'pip' else 0)
    r = make_tool_env(['sdist-only'], run=run, uv='/u/uv')
    assert not r.ok and 'has no wheel' in r.error and tool_python(r.key) is None
    run, _ = fake(lambda c: 0)
    assert make_tool_env(['sdist-only'], run=run, uv='/u/uv').ok                              # a half-made folder is made again
```

`tests/test_learn_tools_slow.py`: skip unless `LEELA_NET_TESTS=1` and `shutil.which('uv')`; make an environment for `six`, then run its Python with `-I -c 'import six'`.

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_learn_tools.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'leela.blocks.learn.tools'`.

- [ ] **Step 3: Implement.** `uv` is `shutil.which('uv')`, as `leela/blocks/runtime/app.py:113` finds it; with no `uv`, the error is "Leela needs uv to install packages for a lesson." Keep the owner's uv config (spec, decision 5).

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_learn_tools.py -q && LEELA_NET_TESTS=1 uv run pytest tests/test_learn_tools_slow.py -q`
Expected: PASS (the slow file skips without the variable).

- [ ] **Step 5: Commit**

```bash
git add leela/blocks/learn leela/blocks/vault/clip.py tests/test_learn_tools.py tests/test_learn_tools_slow.py tests/routes.txt
git commit -m "Make one cached tool environment for each set of packages, with uv and wheels only, in a job"
```

---

### Task 9: Check the reference solution with abhyasa's closed runner

**Needs abhyasa:** `abhyasa.check.run_isolated(kind='assert', ...)` and its report shape (`found`, `timeout`, `checks[i, status, got, error, hidden]`).
**Touches the ramabana agent's files:** yes, `leela/blocks/nb/exercise.py` (`check_solution`).

**Files:**
- Modify: `leela/blocks/nb/exercise.py` (`check_solution`)
- Test: `tests/test_exercise_check.py`, `tests/test_abhyasa_contract.py` (`check.HOSTILE` when abhyasa ships it)

**Interfaces:**
- `check_solution(spec, solution, timeout=10) -> dict(solution=report, stub=report)`: each report is `run_isolated('assert', spec['fname'], source, [t['test'] for t in spec['tests']], total=timeout, sandbox=True)`. The keys that `add_exercise` reads (`found`, `checks[].status`, `timeout`, `error`) keep their meaning. `HARNESS` stays for `run_checks` (the live kernel).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_exercise_check.py: add
from leela.blocks.nb.exercise import check_solution

SPEC = dict(task='Double it.', fname='double', stub='def double(x): pass',
            tests=[dict(say='doubles 2', test='assert double(2) == 4', shown=True)])

def test_check_solution_uses_the_closed_runner(monkeypatch):
    import abhyasa.check
    seen = []
    real = abhyasa.check.run_isolated
    monkeypatch.setattr(abhyasa.check, 'run_isolated', lambda *a, **kw: seen.append((a, kw)) or real(*a, **kw))
    r = check_solution(SPEC, 'def double(x): return 2 * x')
    assert r['solution']['found'] and [c['status'] for c in r['solution']['checks']] == ['pass']
    assert r['stub']['checks'][0]['status'] == 'fail'
    assert len(seen) == 2 and all(kw['sandbox'] for _, kw in seen)

@pytest.mark.parametrize('src', ['import socket; socket.create_connection(("1.1.1.1", 53))\ndef double(x): return 2 * x',
                                 'open("/tmp/leela-x", "w").write("x")\ndef double(x): return 2 * x',
                                 'while True: pass',
                                 'print(\'{"v": 1, "found": true, "checks": [{"i": 0, "status": "pass"}]}\')\ndef double(x): return x'])
def test_hostile_reference_solutions_do_not_pass(src):
    r = check_solution(SPEC, src, timeout=3)['solution']
    assert r.get('timeout') or r.get('error') or [c['status'] for c in r.get('checks', [])] != ['pass']
```

When abhyasa ships `check.HOSTILE`, the contract test runs it: each source through `check_solution`, each with its expected outcome.

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_exercise_check.py -q`
Expected: FAIL in `test_check_solution_uses_the_closed_runner` with `assert 0 == 2`.

- [ ] **Step 3: Implement.** Replace the `subprocess.run` loop with two `run_isolated` calls. Remove the code that only the old loop used. Keep `validate_exercise_spec` first.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_exercise_check.py tests/test_exercise.py tests/test_exercise_agent.py tests/test_exercise_route.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add leela/blocks/nb/exercise.py tests/test_exercise_check.py tests/test_abhyasa_contract.py
git commit -m "Check the reference solution in abhyasa's closed runner, in place of Leela's own subprocess"
```

---

### Task 10: Library code checks

**Needs abhyasa:** `run_isolated(..., python=None, unix=False)` (asked for in `leela-reuse.md` 6.4). Until it ships, Leela's runner below, with the reason comment.
**Touches the ramabana agent's files:** yes, `leela/blocks/nb/exercise.py` (an exercise with `env` uses `library_check`), and `tests/test_abhyasa_contract.py` (pins `python` and `unix` when they ship).

**Files:**
- Modify: `leela/blocks/learn/tools.py` (`library_check`)
- Modify: `leela/blocks/nb/exercise.py` (`validate_exercise_spec` keeps an optional `env` key; `check_solution` and the graded check pass it on)
- Modify: `leela/blocks/agent/ai.py` (`add_exercise` takes `packages: list|None = None`; it makes or finds the tool environment first)
- Test: `tests/test_learn_library_check_slow.py` (needs a real tool environment: `LEELA_NET_TESTS=1`), `tests/test_learn_tools.py`

**Interfaces:**
- `LIBRARY_TOTAL = 20.`
- `library_check(spec, source, key:str) -> dict`: `python = tool_python(key)`; `ValueError('The tool environment is not ready.')` when None; returns `run_isolated('assert', spec['fname'], source, tests, total=LIBRARY_TOTAL, sandbox=True, python=str(python), unix=True)`. When the locked abhyasa has no `python` parameter, it uses `_run_isolated_in(python, ...)`, a copy that calls the public `abhyasa.check.snippet` and `parse`, with the comment `# until abhyasa.check.run_isolated takes python= and unix= (leela-reuse.md 6.4)`.
- The `unix` switch: the audit hook allows `socket.socket` for `AF_UNIX` only (asyncio's socket pair); `connect`, `bind`, `getaddrinfo` and `sendto` stay refused; on macOS the `sandbox-exec` profile adds `(allow network* (local unix))` only when the pair fails without it.
- Exercise spec: `env: str` (a tool key) is optional; with it, the graded check is the closed `library_check`, and the learner's own runs stay in the live kernel.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_learn_tools.py: add
from leela.blocks.learn.tools import LIBRARY_TOTAL, library_check

def test_library_check_needs_a_ready_environment():
    assert LIBRARY_TOTAL == 20.
    with pytest.raises(ValueError, match='not ready'): library_check(dict(fname='f', tests=['assert f() == 1']), 'def f(): return 1', 'nokey')
```

```python
# tests/test_learn_library_check_slow.py
import os, shutil
import pytest
from leela.blocks.learn.tools import library_check, make_tool_env

pytestmark = pytest.mark.skipif(not (os.getenv('LEELA_NET_TESTS') == '1' and shutil.which('uv')), reason='needs uv and LEELA_NET_TESTS=1')
SPEC = dict(fname='f', tests=['assert f() == 1'])

@pytest.fixture(scope='module')
def key(tmp_path_factory):
    os.environ['XDG_DATA_HOME'] = str(tmp_path_factory.mktemp('data'))
    r = make_tool_env(['six']); assert r.ok, r.error
    return r.key

def test_library_check_closed_and_asyncio_ok(key):
    ok = library_check(SPEC, 'import six, asyncio\ndef f():\n    return asyncio.run(asyncio.sleep(0, result=1))', key)
    assert [c['status'] for c in ok['checks']] == ['pass']                                   # the socket pair works
    for bad in ['import socket\ns = socket.socket(socket.AF_UNIX)\ns.connect("/tmp/x")\ndef f(): return 1',
                'import socket\nsocket.create_connection(("1.1.1.1", 53))\ndef f(): return 1',
                'import subprocess\nsubprocess.run(["true"])\ndef f(): return 1',
                'import os\nopen(os.path.expanduser("~/leela-x"), "w")\ndef f(): return 1',
                'print(\'{"v": 1, "found": true, "checks": [{"i": 0, "status": "pass"}]}\')\nimport sys; sys.exit(0)']:
        r = library_check(SPEC, bad, key)
        assert r.get('error') or r.get('timeout') or [c['status'] for c in r.get('checks', [])] != ['pass'], bad
    r = library_check(SPEC, 'while True: pass', key)
    assert r.get('timeout')                                                                   # stops within the 20 s total
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_learn_tools.py -q && LEELA_NET_TESTS=1 uv run pytest tests/test_learn_library_check_slow.py -q`
Expected: FAIL with `ImportError: cannot import name 'library_check'`.

- [ ] **Step 3: Implement.** Model tests still pass `safe_test` and `validate_exercise`. The reference solution never leaves the server. The exercise prompt names the library and says that the code runs with no network and no API key (Task 11 registers that prompt).

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_learn_tools.py tests/test_exercise*.py -q && LEELA_NET_TESTS=1 uv run pytest tests/test_learn_library_check_slow.py -q`
Expected: PASS. Note the time of the slowest check in the commit body if it is above 10 s.

- [ ] **Step 5: Commit**

```bash
git add leela/blocks/learn/tools.py leela/blocks/nb/exercise.py leela/blocks/agent/ai.py tests
git commit -m "Run a graded library check in a closed process with the tool environment's Python and no network"
```

---

### Task 11: The agent as a tutor for tools

**Needs abhyasa:** `abhyasa.prompts.register`, `prompt`.
**Touches the ramabana agent's files:** yes, `leela/blocks/nb/lesson.py` (`lesson_charter(step=…)`, `LIBRARY_PROMPT`).

**Files:**
- Modify: `leela/blocks/nb/lesson.py` (`lesson_charter(step)`, `register('leela.library', …)`)
- Modify: `leela/blocks/agent/ai.py` (`system_prompt` passes the lesson's step; a lesson tool `look_up_code(q:str) -> str`)
- Test: `tests/test_lesson_prompt.py`, `tests/test_lesson_agent.py`

**Interfaces:**
- `LIBRARY_PROMPT = register('leela.library', 'Library lessons', 'What the tutor says about code that uses a library.', dflt)`. The default: the code runs with no network and no API key; use the library's offline test helpers (for PydanticAI: `pydantic_ai.models.test.TestModel` and `pydantic_ai.models.function.FunctionModel`); with no known helpers, set a task on the pure functions only.
- `lesson_charter(step:dict|None=None, packages=()) -> str`: `prompt('tutor') + CHARTER_TAIL`, then, with `step`, the passage, the note, the concept and the check kind; with `packages`, `prompt('leela.library')` and the package names.
- `look_up_code(q:str) -> str`: the rows of Task 7's `lookup` for the lesson's tool environment, as short text; available only when `_lesson()` is true.
- The charter keeps abhyasa's anti-goals (they are in `TUTOR_SP`): no answer, rubric or solution before the learner tries; one check for each idea; no score or timer.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_lesson_prompt.py: add
from leela.blocks.nb.lesson import lesson_charter

def test_charter_carries_the_step_and_the_library_prompt():
    step = dict(walk='a-1', step=0, section='', text='Agents call tools.', note='Look at run_sync.')
    t = lesson_charter(step, packages=['pydantic-ai-slim'])
    assert 'Agents call tools.' in t and 'Look at run_sync.' in t and 'pydantic-ai-slim' in t
    assert 'TestModel' in t and 'no network' in t
    set_prompt('leela.library', 'Use only pure functions.')
    try: assert 'Use only pure functions.' in lesson_charter(step, packages=['x']) and 'TestModel' not in lesson_charter(step, packages=['x'])
    finally: set_prompt('leela.library', '')
    assert 'Agents call tools.' not in lesson_charter()
```

Add one case to `tests/test_lesson_agent.py`: in a walk lesson tab, the agent's tool list holds `look_up_code`, and outside a lesson it does not.

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_lesson_prompt.py -q`
Expected: FAIL with `TypeError: lesson_charter() got an unexpected keyword argument 'packages'`.

- [ ] **Step 3: Implement.** The step comes from the lesson notebook meta (`lesson.walk`) and the store, read through `find_step`. Hints from the agent are not counted in this plan (spec, decision 7).

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_lesson_prompt.py tests/test_lesson_agent.py tests/test_exercise_agent.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add leela/blocks/nb/lesson.py leela/blocks/agent/ai.py tests
git commit -m "Brief the tutor with the walk step, the library prompt and a kosha lookup tool"
```

---

### Task 12: KaTeX stays local

Leela already loads KaTeX from `leela/vendor/katex/` (`loadKatex`), and it does not call mdhtml's `page()`, the only place that names the CDN. This task only adds a guard, so a later change cannot add a CDN load. Drop it if the owner wants no guard.

**Needs abhyasa:** none.
**Touches the ramabana agent's files:** no.

**Files:**
- Test: `tests/test_md_math.py`

**Interfaces:** none.

- [ ] **Step 1: Write the test**

```python
# tests/test_md_math.py: add
from pathlib import Path

def test_no_cdn_for_katex():
    root = Path(__file__).parents[1]/'leela'
    hits = [str(p) for p in root.rglob('*') if p.suffix in ('.py', '.js', '.html') and 'vendor' not in p.parts
            and 'cdn.jsdelivr.net' in p.read_text(errors='ignore')]
    assert hits == []
    assert (root/'vendor'/'katex'/'katex.min.js').is_file()
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/test_md_math.py -q`
Expected: PASS at once (a guard, not a fix). Make it fail one time by hand (add the CDN string to a scratch `.js` file under `leela/`), see the failure, and remove the file.

- [ ] **Step 3: Commit**

```bash
git add tests/test_md_math.py
git commit -m "Test that no Leela page loads KaTeX from a CDN"
```

---

## Order and sequencing

| task | needs abhyasa | ramabana agent's files |
|---|---|---|
| 0 Pin abhyasa | the walk release | `tests/test_abhyasa_contract.py` |
| 1 rupaka predictions | none new | `lesson.py` |
| 2 rupaka bundle and test | the rupaka pin | `tests/test_abhyasa_contract.py` |
| 3 prompts | `prompts` | `lesson.py` |
| 4 `/learn` page | `journey` handoff | none |
| 5 open as lesson, log back | `journey`, `record` | `lesson.py` |
| 6 split pane host | none (test only) | none |
| 7 kosha lookup | none | none |
| 8 tool environments | none | none |
| 9 `check_solution` to `run_isolated` | `check` | `exercise.py` |
| 10 library checks | `run_isolated(python=, unix=)` | `exercise.py`, `tests/test_abhyasa_contract.py` |
| 11 agent tutor | `prompts.register` | `lesson.py` |
| 12 KaTeX guard | none | none |

Tasks 4, 6, 7, 8 and 12 do not touch the ramabana agent's files, so they can go first after Task 0 when that agent's work is still open.
