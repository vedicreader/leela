"The routes. Nothing here imports the application it is mounted in."

from .bricks import find, manifest

__all__ = ['connect']

def connect(app, page=None):
    @app.get('/bricks/manifest.json')
    def demo_manifest(): return manifest()
    @app.get('/bricks/wire/{name}')
    def demo_wire(name: str): return {'ok': find(name) is not None, 'name': name}
