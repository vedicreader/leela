# leela-bricks

Components a canvas document can embed. Ten of them, in four groups. None of them
computes anything: each draws what the document already worked out, and hands back what you
clicked.

A canvas document embeds one with a `brick` brick:

```markdown
```canvas brick id=b1 src=leela_bricks:viz.series emit_point=point
bind labels = list(cycle.index)
bind series = [{'name': 'days to clear', 'values': list(cycle.values)}]
prop height = 240
```
```

## Install

```sh
pip install -e extensions/bricks
```

Leela finds it through the `leela.bricks` entry point. Leela needs no other configuration, and
`LEELA_BRICK_HOST` serves only a library nobody installed. See
[docs/bricks.md](../../docs/bricks.md).

## What a brick declares

`Registry.brick(name, title, group, ports, emits, wire, height, doc)`. `ports` name what the component draws
from. `emits` name what a click writes back into the document's namespace. `wire` is the code
that fills the ports.

`wire` is optional and no brick here ships one, so `needs` is empty throughout. A library whose
components compute their own data does ship it, and `needs` then names the packages the snippet
imports, minus the standard library, read off the snippet rather than declared. A document
without those packages reads the ports over `data.remote_wire` instead. `docs/bricks.md` builds
one that way.

`src` is `LIB:name`, and `LIB` is this package's own module name. It is never a literal. A brick
therefore cannot claim a package it no longer lives in.

## Adding one to this library

Two edits, keyed by the same name. Nothing registers the pair: the name is the join.

`bricks.py` declares it. `ports` are what it reads, `emits` what a click writes back, `sample`
what it draws before anything is bound.

```python
brick('viz.gauge', 'Gauge', 'viz',
      doc='One number against its target.',
      ports=[Port('value', 'num', 'where it stands', sample=62),
             Port('target', 'num', 'where it should be', sample=80)],
      emits=[Port('gap', 'num', 'target minus value, when clicked')],
      height=140)
```

`bricks.js` draws it, into the element it is handed, with the ports already resolved.

```js
B['viz.gauge'] = (root, p, emit) => {
  const v = num(p.value), t = num(p.target) || 1;
  root.innerHTML = `<div class="bk-head"><b>${esc(p.label ?? 'Gauge')}</b><span>${v} of ${t}</span></div>`;
  const bar = el('div', 'bk-bar', '<i></i>');
  bar.firstChild.style.width = Math.min(100, v / t * 100).toFixed(1) + '%';
  bar.onclick = () => emit('gap', t - v);
  root.appendChild(bar);
};
```

`esc`, `el`, `sv` and `num` are already in scope, and the `bk-` classes in `bricks.css` are
shared. Return a function to tear down anything you started: `learn.orbit` returns one that
cancels its animation frame.

The gallery, the manifest, the frame and `src` all follow from the registration. Nothing else to
touch.

## Routes

`serve.connect(app, page=None)` registers seven routes on any Starlette or FastHTML app, and it
imports nothing from that app. Leela mounts the routes in its own process, and no second server
runs.

| route | is |
|---|---|
| `/bricks` | the gallery |
| `/bricks/manifest.json` | every brick, its ports and its emits |
| `/bricks/f/{name}` | one component, as a frame |
| `/bricks/wire/{name}` | the snippet, and the call that reads the ports remotely |
| `/bricks/data/{name}` | the ports, filled by running the snippet here |
| `/bricks/js`, `/bricks/css` | the drawing |

## Extracting it

This directory is the package. `pip install extensions/bricks` works anywhere, because nothing in
the package imports Leela. To move it to its own repository, use `git mv` and add a remote.
