"""The debugger: debugpy availability and one debug session over a kernel.

Domain only. The 10 debug routes are still closures in `leela/app.py`, sharing the run locks
and debugger state that `leela/core/session.py` exists to hold; when they move they land here
as `app.py` and the block joins the `BLOCKS` list.
"""
