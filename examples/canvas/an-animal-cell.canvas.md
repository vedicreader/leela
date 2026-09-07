---
title: An animal cell
mode: learn
---

# An animal cell

Click anything in the cell. What you click becomes a name in this document, and every brick
below reads that name.

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

## What the membranes are for

A cell keeps compartments because some reactions fight each other. A lysosome holds acid, and
the cytosol does not. A mitochondrion holds a proton gradient, and only a sealed membrane keeps
that gradient. The nucleus keeps transcription apart from translation. The cell therefore edits a
transcript before it reads it. Every membrane in the picture bounds one reaction.

```canvas ask id=c5
explain mitochondrion
```

<!--canvas quiz id=c6-->
1. Why does messenger RNA exist at all
2. What would happen to a cell whose lysosomes leaked
3. Which organelle carries its own genome, and what does that suggest
<!--/canvas-->
