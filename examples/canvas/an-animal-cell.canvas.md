---
title: An animal cell
mode: learn
---

# An animal cell

Click anything in the cell. What you clicked becomes a name in this document, and everything
below it is written from that name.

```canvas code id=c1
organelle = {'name': 'nothing yet', 'doc': 'Click an organelle above.'}
seen = []
```

```canvas brick id=c2 src=leela_bricks:learn.cell emit_organelle=organelle
bind label = organelle['name']
prop height = 420
```

```canvas code id=c3
if organelle['name'] not in seen and organelle['name'] != 'nothing yet': seen = seen + [organelle['name']]
found = len(seen)
```

```canvas data id=c4
bind text = f"### {organelle['name']}\n\n{organelle['doc']}\n\nYou have opened **{found} of 8**: {', '.join(seen) or 'none yet'}."
```

## Why any of this is separate

A cell is compartments because chemistry that would fight is kept apart. Lysosomes are acidic and
the cytosol is not; the mitochondrion holds a proton gradient that only works across a sealed
membrane; the nucleus keeps transcription away from translation so a transcript can be edited
before it is read. Every membrane in the picture is a boundary condition on a reaction.

```canvas ask id=c5
explain mitochondrion
```

<!--canvas quiz id=c6-->
1. Why does messenger RNA exist at all
2. What would happen to a cell whose lysosomes leaked
3. Which organelle carries its own genome, and what does that suggest
<!--/canvas-->
