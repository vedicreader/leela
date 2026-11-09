"The scrub worker: runs a cell on a copy of the data it reads, in its own process, under limits. The server kills it; it never gives up on its own."
import ast, base64, contextlib, importlib.util, io, json, os, socket, sys, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_MAX, RES_MAX, IMG_MAX, IMGS = 100_000, 10_000, 1_500_000, 4

def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + '.py'))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def limit(cap):
    "Memory, CPU and file-size limits where the system keeps them (macOS keeps only some; the server watches memory too)."
    try:
        import resource
        for r, v in ((getattr(resource, 'RLIMIT_AS', None), cap), (resource.RLIMIT_CPU, 600), (resource.RLIMIT_FSIZE, 1_000_000)):
            if r is None: continue
            try: resource.setrlimit(r, (v, v))
            except (ValueError, OSError): pass
    except ImportError: pass

def no_network():
    "Best effort: a cell that opens a socket gets an error. A cell that finds another way out is not stopped."
    def refuse(*a, **k): raise OSError('the network is off while scrubbing')
    for n in ('connect', 'connect_ex', 'sendto', 'bind'): setattr(socket.socket, n, refuse)
    for n in ('getaddrinfo', 'gethostbyname', 'create_connection'): setattr(socket, n, refuse)

def run(req, scrub, wire):
    src = req['source']
    if (why := scrub.scrub_why(src)): return {'refused': why}
    ns = {'__name__': '__main__'}
    ns.update({k: wire.decode(v) for k, v in req.get('snap', {}).items()})
    ns['display'] = lambda *a: [print(repr(x)) for x in a]
    out, err, res, error, images = io.StringIO(), io.StringIO(), None, None, []
    tree = ast.parse(src)
    last = ast.Expression(tree.body.pop().value) if tree.body and isinstance(tree.body[-1], ast.Expr) else None
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            exec(compile(tree, '<scrub>', 'exec'), ns)
            if last is not None and (v := eval(compile(ast.fix_missing_locations(last), '<scrub>', 'eval'), ns)) is not None: res = repr(v)[:RES_MAX]
    except BaseException as e:
        tb = traceback.format_exception(type(e), e, e.__traceback__)
        error = {'ename': type(e).__name__, 'evalue': str(e)[:2000], 'traceback': [''.join(tb[-4:])[:4000]]}
    plt = sys.modules.get('matplotlib.pyplot')
    if plt is not None:
        try:
            for num in plt.get_fignums()[:IMGS]:
                buf = io.BytesIO(); plt.figure(num).savefig(buf, format='png', dpi=80, bbox_inches='tight')
                if len(buf.getvalue()) <= IMG_MAX: images.append(base64.b64encode(buf.getvalue()).decode())
        except Exception: pass
        finally: plt.close('all')
    return {'stdout': out.getvalue()[:OUT_MAX], 'stderr': err.getvalue()[:OUT_MAX], 'result': res, 'images': images, 'error': error}

def main():
    proto = os.fdopen(os.dup(1), 'w')
    os.dup2(os.open(os.devnull, os.O_WRONLY), 1)
    scrub, wire = load('scrub'), load('scrubwire')
    limit(int(os.environ.get('LEELA_SCRUB_MEMORY', 1_500_000_000))); no_network()
    proto.write(json.dumps({'ready': True}) + '\n'); proto.flush()
    for line in sys.stdin:
        req = json.loads(line)
        try: res = run(req, scrub, wire)
        except BaseException as e: res = {'error': {'ename': type(e).__name__, 'evalue': str(e)[:500], 'traceback': []}}
        proto.write(json.dumps({'id': req.get('id'), **res}) + '\n'); proto.flush()

if __name__ == '__main__': main()
