---
title: Pricing a run
mode: make
---

# Pricing a run

An agent run costs four numbers and one multiplication. Every argument about the cost is an
argument about one of the four. Put the four in a cell, and the argument becomes editable.

```canvas code id=p1
in_tokens  = 18_000
out_tokens = 2_400
runs_a_day = 400
prices = {'Opus 5': (15, 75), 'Sonnet 5': (3, 15), 'Haiku 4.5': (0.8, 4)}
```

```canvas code id=p2
def cost(model):
    i, o = prices[model]
    return in_tokens/1e6*i + out_tokens/1e6*o

rows = [{'label': m, 'per_request': round(cost(m), 5), 'monthly': round(cost(m)*runs_a_day*30, 2)}
        for m in prices]
rows
```

```canvas brick id=p3 src=leela_bricks:thrifty.costs emit_row=picked
bind rows = rows
prop height = 220
```

```canvas code id=p4
picked = rows[-1]
```

```canvas data id=p5
bind text = f"**{picked['label']}** at this shape of request is ${picked['per_request']} a call and ${picked['monthly']:,.0f} a month at {runs_a_day} runs a day. The cheapest option is {(min(rows, key=lambda r: r['monthly'])['monthly']/picked['monthly']*100):.0f}% of that."
```

Click a row. `picked` changes, and the sentence below binds to `picked`, which changes it too.

## The knob that actually matters

```canvas sim id=p6
prop height = 120
const draw = () => {
  root.innerHTML = `<div class="row"><label style="width:140px">runs a day</label>
    <input type=range min=50 max=5000 step=50 id=r><b id=v></b></div>`;
  const r = root.querySelector('#r');
  r.value = props.runs_a_day ?? 400;
  const show = () => root.querySelector('#v').textContent = r.value;
  r.oninput = show; r.onchange = () => { show(); emit('runs_a_day', +r.value); }; show();
};
```

```canvas brick id=p7 src=leela_bricks:viz.series
bind labels = [r['label'] for r in rows]
bind series = [{'name': 'monthly $', 'values': [r['monthly'] for r in rows]}]
prop height = 240
```

Every model here prices an output token at four to five times an input token. A longer prompt
therefore costs little, and a longer answer costs much more. This is why "make it more concise"
is a budget decision.

```canvas ask id=p8
chart rows
```
