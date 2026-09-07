---
title: Tunnelling
mode: learn
---

# Tunnelling

A particle with less energy than a barrier still turns up on the other side. Not over the top:
through. The amplitude inside the barrier decays rather than oscillates, and if the barrier ends
before the decay finishes, whatever is left keeps going.

The simulation below integrates the one-dimensional Schrödinger equation in the frame, forty
steps a screen refresh. Nothing is precomputed.

```canvas code id=q1
barrier = 1.02
width = 6
```

```canvas brick id=q2 src=lego.bricks:learn.wavepacket emit_transmission=transmission
bind barrier = barrier
bind width = width
prop height = 300
```

```canvas sim id=q3
prop height = 130
const draw = () => {
  root.innerHTML = `<div class="row"><label style="width:130px">barrier ×E</label>
      <input type=range min=0.9 max=2 step=0.02 id=b><b id=bv></b></div>
    <div class="row"><label style="width:130px">width</label>
      <input type=range min=2 max=30 step=1 id=w><b id=wv></b></div>`;
  const b = root.querySelector('#b'), w = root.querySelector('#w');
  b.value = props.barrier ?? 1.02; w.value = props.width ?? 6;
  const show = () => { root.querySelector('#bv').textContent = (+b.value).toFixed(2);
                       root.querySelector('#wv').textContent = w.value; };
  b.onchange = () => { show(); emit('barrier', +b.value); };
  w.onchange = () => { show(); emit('width', +w.value); };
  b.oninput = show; w.oninput = show; show();
};
```

```canvas code id=q4
transmission = 0.0
kappa = round((2 * max(1e-6, (barrier - 1)) * 0.245) ** 0.5, 4)
predicted = round(2.718281828 ** (-2 * kappa * width) * 100, 2)
```

```canvas data id=q5
bind text = f"At {barrier:.2f}× the packet energy over {width} cells, the decay constant κ is {kappa} and the crude estimate exp(−2κa) is **{predicted}%**. The simulation is measuring **{transmission*100:.1f}%**."
```

Drag the barrier up and the transmitted lobe on the right disappears long before the barrier is
twice the energy. That steepness is the whole of the effect: tunnelling is exponential in both
the height and the width, so a barrier one and a half times as thick is not half as leaky.

```canvas ask id=q6
explain tunnelling
```

```canvas video id=q7 src=Ltni6c1lC4c
Sixty Symbols on quantum tunnelling, if you want it said out loud.
```

<!--canvas quiz id=q8-->
1. Why does doubling the barrier width cost more than doubling its height
2. What is the packet doing inside the barrier, if it is not oscillating
3. Where does the reflected part of the packet go
<!--/canvas-->
