"""The debugger: debugpy availability and one debug session over a kernel.

Domain only -- the debug routes are still closures in `leela/app.py`, sharing the run locks
and debugger state held by `leela/core/session.py`.
"""
