---
title: A sales funnel that argues back
mode: learn
---

# A sales funnel that argues back

A funnel is not a picture. It is a chain of conditional probabilities, and the only interesting
question is which link is worst. Drag any bar below and watch the rest of this document rewrite
itself, because every number under it is computed from the same five stages.

```canvas code id=sf1
stages = [{'name': 'Leads', 'value': 1000}, {'name': 'Qualified', 'value': 420},
          {'name': 'Demo', 'value': 180}, {'name': 'Proposal', 'value': 74}, {'name': 'Won', 'value': 23}]
spend = 180_000
deal = 24_000
```

```canvas brick id=sf2 src=lego.bricks:viz.funnel emit_stages=stages
bind stages = stages
prop height = 330
```

```canvas code id=sf3
rates = [round(b['value'] / max(1, a['value']) * 100, 1) for a, b in zip(stages, stages[1:])]
names = [s['name'] for s in stages[1:]]
won = stages[-1]['value']
cac = round(spend / max(1, won))
worst = min(zip(rates, names))
revenue = won * deal
payback = round(cac / (deal * 0.7), 2)
```

```canvas brick id=sf4 src=lego.bricks:viz.tiles
bind tiles = [{'label': 'Won', 'value': won}, {'label': 'CAC', 'value': f'${cac:,}'}, {'label': 'Revenue', 'value': f'${revenue/1000:.0f}k'}, {'label': 'Worst step', 'value': worst[1], 'delta': worst[0]}]
prop height = 130
```

```canvas data id=sf5
bind text = f"The weakest link is **{worst[1]}**, converting at **{worst[0]}%**. Taking it to {worst[0]+10:.0f}% would be worth about ${(won*(worst[0]+10)/worst[0]-won)*deal/1000:.0f}k a year, against a customer acquisition cost of ${cac:,} and {payback} months of gross margin to pay it back."
```

```canvas brick id=sf6 src=lego.bricks:viz.series
bind labels = names
bind series = [{'name': 'conversion %', 'values': rates}]
prop height = 240
```

<!--canvas note id=sf7-->
The chart above is bound to `rates`, which is computed in the cell above it, which reads `stages`,
which the funnel writes when you drag it. Nothing is refreshed. Each thing recomputes because
something it reads moved.
<!--/canvas-->

```canvas ask id=sf8
what is cac?
```

```canvas quiz id=sf9
1. Which stage costs the most to fix, and why is it not the one with the fewest deals
2. What happens to CAC if you double Leads and hold every conversion rate
3. Why is payback measured against gross margin rather than revenue
```
