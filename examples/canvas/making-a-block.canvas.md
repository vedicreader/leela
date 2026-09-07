---
title: Making a block
mode: make
---

# Making a block

This document is the software and the note about the software. The code below is what would go in
`lego/<name>/data.py`; the component under it is the thing it feeds. Neither is a screenshot.

```canvas code id=m1
from datetime import date, timedelta

def burndown(start, days, done_per_day):
    "Points left on each day, from a start and a rate."
    left, out = start, []
    for i in range(days):
        left = max(0, left - done_per_day)
        out.append({'day': (date(2026, 9, 1) + timedelta(days=i)).strftime('%d %b'), 'left': left})
    return out

plan = burndown(180, 12, 16)
labels = [p['day'] for p in plan]
left = [p['left'] for p in plan]
```

```canvas brick id=m2 src=leela_bricks:viz.series emit_point=point
bind labels = labels
bind series = [{'name': 'points left', 'values': left}]
prop height = 240
```

```canvas code id=m3
point = {'label': labels[0], 'value': left[0]}
lands = next((p['day'] for p in plan if p['left'] == 0), 'not in this window')
```

```canvas data id=m4
bind text = f"On the plan as written it lands **{lands}**. You clicked {point['label']}, where {point['value']} points were left."
```

<!--canvas note id=m5-->
The brick above is `leela_bricks:viz.series`. It came from the palette with `/`, and the two lines
that fill it came from its own package rather than from here. Open the wiring panel from the block menu, on the grip in the gutter, and the expressions are
the ones you would have written.
<!--/canvas-->

## Sketching a component before it is a package

A sketch is a component authored in this file. It gets the same two messages a packaged brick
gets and nothing else, so it can be promoted into a package without changing a line of it.

```canvas sim id=m6
bind done = done
prop height = 190
const draw = () => {
  const done = props.done ?? 0.4;
  root.innerHTML = `<svg viewBox="0 0 400 120" style="width:100%">
    <rect x="10" y="40" width="380" height="26" rx="13" fill="#e7ebf3"></rect>
    <rect x="10" y="40" width="${(380*done).toFixed(0)}" height="26" rx="13" fill="#2f6df6"></rect>
    <text x="200" y="90" text-anchor="middle" font-size="13" fill="#6b7280">${(done*100).toFixed(0)}% of the plan burned down</text>
  </svg>
  <div class="row"><input type=range min=0 max=1 step=0.01 id=d value="${done}"></div>`;
  root.querySelector('#d').oninput = e => { emit('done', +e.target.value); };
};
```

```canvas code id=m7
done = 1 - left[-1]/180
```

```canvas pdf id=m9 src=assets/brick-ports.pdf
The contract a component makes with a document, on one page. It is a file beside this one, and
`/canvas/file` will not serve anything outside the canvas directory.
```

```canvas ask id=m8
what is a bind?
```
