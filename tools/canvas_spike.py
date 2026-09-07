"Boot the canvas block on its own: no kernels, no models, no workspace. `uv run python tools/canvas_spike.py`."

import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fasthtml.common import fast_app, serve
from leela.blocks.canvas.app import connect

app, _ = fast_app(default_hdrs=False, pico=False, live=False)
connect(app, ctx=None)

if __name__ == '__main__':
    serve('canvas_spike', 'app', port=int(os.getenv('PORT', 5002)), reload=False)
