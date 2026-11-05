"Report every thread's stack when the process stays busy."

import sys, threading, time, traceback
from collections import deque
from datetime import datetime
from fastcore.all import Path

from .. import leela_cfg

__all__ = ['cpu_report', 'watch_cpu']

#: A top frame in one of these is parked, not burning: such threads go last in a report.
_PARKED = {'threading.py', 'selectors.py', 'queue.py', 'socket.py', 'ssl.py', 'subprocess.py'}

def _mem():
    # `ru_maxrss` is bytes on macOS, KiB on Linux; `resource` does not exist on Windows. Current RSS needs psutil, which may be absent.
    try: import resource; peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024)
    except Exception: peak = None
    try: import psutil; rss = psutil.Process().memory_info().rss
    except Exception: rss = None
    return rss, peak

def cpu_report(samples, every):
    "The report text: time, CPU% samples, memory, and every thread's stack, busiest-looking first."
    names, me = {t.ident: t.name for t in threading.enumerate()}, threading.get_ident()
    frames = sorted(((i, f) for i, f in sys._current_frames().items() if i != me), key=lambda o: Path(o[1].f_code.co_filename).name in _PARKED)
    rss, peak = _mem()
    out = [f'time {datetime.now().isoformat(timespec="seconds")}\n',
           f'cpu% every {every}s: ' + ' '.join(f'{p:.0f}' for p in samples) + '\n',
           f'rss {rss} bytes, peak {peak} bytes\n']
    for ident, frame in frames: out += [f'\n--- {names.get(ident, "?")} ({ident})\n', *traceback.format_stack(frame)]
    return ''.join(out)

def _save(folder, text, keep):
    folder.mkdir(parents=True, exist_ok=True)
    (folder/f'cpu-{datetime.now():%Y%m%d-%H%M%S}.txt').write_text(text)
    for p in sorted(folder.glob('cpu-*.txt'))[:-keep]: p.unlink(missing_ok=True)

def _enabled(settings):
    try:
        from ..blocks.settings.settings import Settings
        return bool(((settings or Settings()).effective().get('diagnostics') or {}).get('cpu_watchdog', True))
    except Exception: return True

def watch_cpu(every=5, threshold=80, sustain=30, cooldown=600, keep=20, folder=None, settings=None,
              clock=time.monotonic, cpu=time.process_time, wait=None):  # `wait(every)` is True to stop; tests drive all three
    "Start a daemon thread that writes `cpu_report` when CPU% stays over `threshold` for `sustain` s. Returns a stop function, or None when `diagnostics.cpu_watchdog` is off."
    if not _enabled(settings): return None
    stop, folder, n = threading.Event(), Path(folder or Path(leela_cfg)/'watchdog'), max(1, round(sustain/every))
    def loop():
        window, last, t0, c0 = deque(maxlen=n), None, clock(), cpu()
        while not (wait or stop.wait)(every):
            try:
                t, c = clock(), cpu()
                window.append(100*(c-c0)/max(t-t0, 1e-9)); t0, c0 = t, c
                if len(window) < n or min(window) <= threshold or (last is not None and t-last < cooldown): continue
                last = t; _save(folder, cpu_report(list(window), every), keep); window.clear()
            except Exception: pass
    threading.Thread(target=loop, daemon=True, name='leela-cpu-watchdog').start()
    return stop.set
