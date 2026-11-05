import threading, time
from leela.blocks.settings.settings import Settings
from leela.core.watchdog import watch_cpu

FAST = dict(every=.1, threshold=50, sustain=.5, cooldown=3600)

def spin_here(secs):
    end = time.monotonic() + secs
    while time.monotonic() < end: pass

def _run(tmp_path, *spins, gap=.6, **kw):
    stop = watch_cpu(folder=tmp_path, settings=Settings(user_path=tmp_path/'settings.json'), **FAST, **kw)
    try:
        for secs in spins:
            t = threading.Thread(target=spin_here, args=(secs,)); t.start(); t.join()
            time.sleep(gap)
    finally: stop()
    return sorted(tmp_path.glob('cpu-*.txt'))

def _busy(tmp_path, secs=30):
    "Spin from before the watchdog starts until it writes a report, so any report names the spin and a slow runner only takes longer."
    done = threading.Event()
    def spin_here():
        while not done.is_set(): pass
    t = threading.Thread(target=spin_here); t.start()
    stop = watch_cpu(folder=tmp_path, settings=Settings(user_path=tmp_path/'settings.json'), **{**FAST, 'threshold': 20})
    try:
        end = time.monotonic() + secs
        while time.monotonic() < end and not [p for p in tmp_path.glob('cpu-*.txt') if not p.name.startswith('cpu-2020')]: time.sleep(.05)
        time.sleep(.6)
    finally: stop(); done.set(); t.join()
    return sorted(tmp_path.glob('cpu-*.txt'))

def test_busy_thread_is_named_in_one_report(tmp_path):
    (rep,) = _busy(tmp_path)
    assert 'spin_here' in rep.read_text()

def test_idle_writes_nothing(tmp_path):
    assert _run(tmp_path, 0, gap=1.5) == []

def _scripted(tmp_path, busy, cooldown):
    "Drive the watchdog through `busy`, one CPU% for each tick of a fake clock, and return its reports. Runner speed does not matter."
    every, now, used, ticks, done = FAST['every'], [0.], [0.], iter(busy), threading.Event()
    def wait(_):
        try: pct = next(ticks)
        except StopIteration: done.set(); return True
        now[0] += every; used[0] += every*pct/100
        return False
    watch_cpu(folder=tmp_path, settings=Settings(user_path=tmp_path/'settings.json'), **{**FAST, 'cooldown': cooldown},
              clock=lambda: now[0], cpu=lambda: used[0], wait=wait)
    assert done.wait(30), 'the watchdog never took its last tick'
    return sorted(tmp_path.glob('cpu-*.txt'))

def test_cooldown_holds_across_windows(tmp_path):
    "Two busy windows 1.6 s apart, inside a cooldown of an hour: one report. Before, real spins on a slow runner sometimes made none."
    busy = [100]*5 + [0]*6 + [100]*5
    assert len(_scripted(tmp_path, busy, 3600)) == 1
    assert len(_scripted(tmp_path/'idle', [0]*16, 3600)) == 0, 'and the script is what made it'

def test_a_report_needs_the_whole_window_busy(tmp_path):
    assert len(_scripted(tmp_path, [100]*4 + [0] + [100]*4, 3600)) == 0

def test_keeps_newest_twenty(tmp_path):
    for i in range(25): (tmp_path/f'cpu-20200101-0000{i:02}.txt').write_text('')
    reps = _busy(tmp_path)
    assert len(reps) == 20
    assert not (tmp_path/'cpu-20200101-000005.txt').exists() and (tmp_path/'cpu-20200101-000006.txt').exists()

def test_setting_off_starts_nothing(tmp_path):
    s = Settings(user_path=tmp_path/'settings.json')
    s.save('user', 'diagnostics', {'cpu_watchdog': False})
    def n(): return sum(t.name == 'leela-cpu-watchdog' for t in threading.enumerate())
    before = n()
    assert watch_cpu(folder=tmp_path, settings=s, **FAST) is None and n() == before
