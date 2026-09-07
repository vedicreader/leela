---
title: The traditional day
mode: learn
---

# The traditional day

A day in the panchangam runs sunrise to sunrise, not midnight to midnight. Five limbs read at
that sunrise give the day its name. The components below come from `leela_bricks`, and they
compute the limbs here rather than fetch them.

```canvas code id=td1
import json, urllib.request
_ports = json.load(urllib.request.urlopen('http://127.0.0.1:5001/bricks/data/panchanga.day'))
day = _ports['day']
day['tithi']['name'], day['nakshatra']['name'], day['masa']
```

This cell is the wiring `leela_bricks:panchanga.day` ships. With the package installed beside the
document, the wiring is two imports and a call. Without the package, as here, the same call goes
to the host that owns it. The document keeps whichever wiring it used, in the open.

```canvas brick id=td2 src=leela_bricks:panchanga.day emit_limb=limb
bind day = day
prop height = 250
```

```canvas code id=td3
limb = 'tithi'
```

```canvas data id=td4
bind text = f"You are looking at the **{limb}**: {day[limb]['name']}, until {day[limb].get('end','—')[11:16]}."
```

Click a limb above. The card hands the name back into this document, and the sentence follows it.

## The twenty-four horas

The panchangam cuts each daylight and each night into twelve horas, and the lords run in the
Chaldean order. The lord of the weekday takes the first hora of the day. Almost every language
that names a weekday for a planet follows that rule.

```canvas brick id=td5 src=leela_bricks:panchanga.horas emit_hora=hora
bind horas = day['horas']
prop height = 150
```

```canvas code id=td6
hora = day['horas'][0]
```

```canvas data id=td7
bind text = f"**{hora['name']}** hora, {hora['start'][11:16]} to {hora['end'][11:16]}, {hora['phase']}."
```

## Where the grahas actually are

```canvas brick id=td8 src=leela_bricks:panchanga.wheel emit_rasi=rasi
bind planets = day['planets']
bind highlight = day['moon_rasi']
prop height = 380
```

```canvas ask id=td9
explain nakshatra
```
